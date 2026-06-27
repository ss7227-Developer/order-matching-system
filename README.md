# Binary Outcome Order-Matching Engine

A toy, in-memory limit-order matching engine with a REST API, built for a binary outcome (prediction) market. It supports limit orders, price-time priority matching, partial fills, cancellation, idempotent submission, a live order-book snapshot, and market resolution.

**This README is written to explain *why* I built it the way I did, not just what's in the files.** The code shows the *what*; anyone reading `engine.py` can see the data structures and the loop. What the code can't show is the decisions I weighed, the alternatives I rejected, the one design I shipped to myself that turned out to be a bug, and — most importantly — what each choice *cost* me. A matching engine is mostly tradeoffs, so I've tried to write down both sides of every one: what I gained, and what I gave up to get it.

---

## Contents

- [What I built](#what-i-built)
- [Running it](#running-it)
- [How the system is shaped, and why](#how-the-system-is-shaped-and-why)
- [The decisions, and the tradeoffs I weighed](#the-decisions-and-the-tradeoffs-i-weighed)
  - [1. Integer cents, not floats](#1-integer-cents-not-floats)
  - [2. A counter, not a clock — the timing decision](#2-a-counter-not-a-clock--the-timing-decision)
  - [3. The data structure, and its runtime](#3-the-data-structure-and-its-runtime)
  - [4. Single-threaded vs multi-threaded — the decision I changed my mind on](#4-single-threaded-vs-multi-threaded--the-decision-i-changed-my-mind-on)
  - [5. Self-trade prevention — the bug I shipped to myself first](#5-self-trade-prevention--the-bug-i-shipped-to-myself-first)
  - [6. Partial fills, and the invariants I protect](#6-partial-fills-and-the-invariants-i-protect)
  - [7. Idempotent submission](#7-idempotent-submission)
  - [8. The REST decisions](#8-the-rest-decisions)
- [The matching algorithm](#the-matching-algorithm)
- [What I deliberately left out](#what-i-deliberately-left-out)
- [What I'd do with more time](#what-id-do-with-more-time)
- [How I worked on this](#how-i-worked-on-this)

---

## What I built

A binary outcome market resolves to one of two states (YES / NO), so a contract's price is naturally a probability expressed in integer cents from **1 to 99**. My engine accepts limit orders to buy or sell that contract, matches crossing orders by **price-time priority**, records the trades, lets unmatched quantity rest on the book, supports cancellation and idempotent retries, exposes a snapshot, and can resolve the market.

The guarantees I hold:

- A trade only happens when a buy price meets or exceeds a sell price.
- The **best price wins**; ties at the same price break **first-in-first-out**.
- Partial fills are tracked exactly — a 100-unit order that fills 40 leaves 60 resting.
- The book is never *crossed* (a resting bid at or above a resting ask). This is the one structural invariant the whole design exists to protect.

---

## Running it

```bash
pip install -r requirements.txt        # fastapi, uvicorn, pydantic, sortedcontainers
python -m uvicorn app:app --reload
```

Server comes up on `http://127.0.0.1:8000`. FastAPI generates interactive docs from my Pydantic models at `http://127.0.0.1:8000/docs`, which is the fastest way to submit, cancel, and read the book without writing a client.

---

## How the system is shaped, and why

I built it as four layers, and I enforced **one rule that drove everything else: the matching engine has zero knowledge that HTTP exists.**

```
   HTTP client
        │
        ▼
   app.py            FastAPI + Pydantic — the ONLY file that imports FastAPI.
   (transport)       Validates input, translates to/from the engine, maps results to status codes.
        │
        ▼
   engine.py         MatchingEngine — submit_order, cancel_order, snapshot, resolve_market.
   (matching)        Owns the matching loop, the self-trade policy, and the serialization lock.
        │
        ▼
   book.py           OrderBook — bids, asks, and the id index. Pure storage and ordering.
        │
        ▼
   order.py          Domain types: Order, OrderRequest, and the Price/Quantity constraints.
```

I made this separation strict on purpose, and the reason is that **the engine is the asset and the web framework is a detail.** I wanted to be able to drive the exact same matching logic from a test, a CLI, or a message queue without touching a line of it. Keeping `app.py` as the only file that imports FastAPI means the core stays portable: if I ever swapped FastAPI for something else, the matching code wouldn't notice.

The payoff I cared about most was testability. Because the engine has no HTTP in it, every matching scenario is a plain Python call — construct an `OrderRequest`, call `submit_order`, assert on the trades it returns. I wrote 32 tests against the engine directly with no server running and no HTTP mocking. The rule I held while building the REST layer was simple: if a route handler ever contained an `if/else` that decided something about *trading*, that was a smell — that logic belongs in `engine.py`, and the handler should only parse, call one method, and shape the output.

---

## The decisions, and the tradeoffs I weighed

### 1. Integer cents, not floats

I represent every price as an `int` in cents (1–99), never a float. This is a correctness decision, not a style one. Floating-point prices drift — `0.1 + 0.2` is not `0.3` — and my engine's entire job is to *compare* prices to decide whether they cross. Drift in a comparison means a wrong match. Integer cents make every comparison exact. The 1–99 bound is the binary market itself: a still-tradeable probability can't be 0 or 100. I encoded the bound as a reusable type so the constraint lives in exactly one place:

```python
Price    = Annotated[int, Field(ge=1, le=99)]   # integer cents, binary-market bounds
Quantity = Annotated[int, Field(gt=0)]          # strictly positive
```

**What this cost me:** nothing meaningful for a binary market. In a market with fractional pricing or many decimal places I'd need a fixed-point or decimal type instead, but here `int` is both correct and the simplest thing that works.

### 2. A counter, not a clock — the timing decision

Time priority needs a tiebreaker: when two orders sit at the same price, the earlier one fills first. The obvious instinct is to timestamp each order. **I deliberately did not do that.** Every order gets a `sequence_number` that is a monotonic integer counter, incremented once per accepted order — not a wall-clock time.

I want to be explicit about *why a clock is the wrong tool here*, because this is the decision that's easiest to get quietly wrong. A wall-clock timestamp fails in two ways:

- **Collisions.** Two orders can arrive inside the same clock resolution and get identical timestamps. Now FIFO ordering is ambiguous — and breaking ties deterministically is the *entire* point of the sequence field. The thing it exists to do is the thing the clock can't guarantee.
- **The clock can run backwards.** NTP corrections and leap-second handling can move the system clock *backwards*. If ordering depends on the clock, a later order can silently receive an earlier timestamp and jump the queue ahead of an order that genuinely came first. In an exchange that isn't a glitch — it's broken fairness, and it's the kind of bug that only shows up in production and is nearly impossible to reproduce.

A counter sidesteps both. It is strictly increasing by construction, so "earlier" is always unambiguous and can never reverse. Time priority becomes an integer comparison that never reads a clock.

I also derive `order_id` straight from this counter — `f"order-{sequence_number}"` — instead of generating a UUID. The engine already needs a unique, monotonic value; minting a second independent identifier would be a redundant id-generation mechanism with its own failure modes. Reusing the sequence number gives me human-readable ids in logs and tests for free.

**What this cost me:** the counter is per-process state, so it only orders correctly *within one engine instance*. If I sharded the book across processes, each shard would have its own counter and there'd be no global cross-shard ordering — I'd need a central sequencer for that. For a single-book toy that's irrelevant; in a sharded production system it's exactly the next thing I'd have to design, and it connects directly to the scaling story below.

### 3. The data structure, and its runtime

Each side of the book is a `SortedDict` mapping **price level → `deque` of orders**, plus one flat dictionary indexing **order_id → order** for cancellation.

```
_bids:  SortedDict { 60: deque([Alice(100), Bob(50)]),  59: deque([Dana(30)]) }
_asks:  SortedDict { 62: deque([Eve(40)]),  65: deque([Frank(80)]) }
_index: dict       { "order-1": Alice, "order-2": Bob, ... }
```

I chose each piece for a runtime reason:

- **`SortedDict` of price levels** because matching always needs the best price next. A structure sorted by price hands me the best bid (highest key) and best ask (lowest key) without re-sorting on every operation, and groups orders by level so the loop can walk best-first. Insert/lookup of a level is `O(log L)` in the number of price levels `L`.
- **`deque` within each level** because time priority within a level is pure FIFO. A deque gives `O(1)` append at the back (a newly resting order) and `O(1)` pop from the front (the next order to fill) — exactly the queue discipline FIFO needs.
- **The flat `_index` dict** because cancellation is by `order_id`, and without an index, *finding* the order means scanning every level and queue — `O(N)`. The index makes the lookup `O(1)`.

There's a binary-market detail that makes all of this faster than it looks: **because prices are integer cents bounded to 1–99, `L` can never exceed 99.** So every `O(log L)` operation is bounded by a small constant in practice — the book has at most 99 price levels no matter how many orders flow through it. My domain caps the part of the complexity that would otherwise grow.

I also want to be honest about the one place this structure is *not* `O(1)`, because it's the most interesting runtime tradeoff in the whole design. The `_index` makes *finding* a cancelled order `O(1)`, but *removing* it from its level's deque is `O(k)` in that level's depth — a deque doesn't support `O(1)` removal of an interior element, so the remove has to scan the queue to find it. I chose the deque anyway, and here's the tradeoff I made:

- **Deque (what I did):** dead simple, obviously correct, `O(1)` to rest and to fill from the front, `O(k)` to cancel an order buried mid-queue.
- **Intrusive doubly-linked list per level (the alternative):** store the list *node* in the index so a cancel can splice the order out in true `O(1)`. This is what a latency-sensitive production engine uses — but it's more code, more pointers to keep consistent, and more ways to corrupt the structure.
- **Lazy / tombstone deletion (another alternative):** mark the order cancelled in the index and skip it when the matching loop reaches it. Cancel becomes `O(1)`, but the book carries dead orders until a sweep removes them, so memory grows with cancellations.

For a toy where clarity and provable correctness matter more than cancel latency, the deque is the right call. In a real engine I'd move to the intrusive linked list, and I note that below as a "more time" item. The point is that I picked the simpler structure *knowing* its cost, not by default.

Matching itself is `O(k)` in the number of resting orders an incoming order consumes — a large order that sweeps several levels does `O(m)` work in orders filled, which is just the unavoidable work of executing `m` trades. Snapshot walks the levels and is bounded by the small number of price levels plus the resting orders.

### 4. Single-threaded vs multi-threaded — the decision I changed my mind on

This is the decision I went back and forth on the most, and the final design is stronger *because* I got it wrong first and had to correct it. I'll tell it as it actually happened.

**Step one: I worked out that the matching loop has to be single-threaded.** FIFO only means anything if one thread at a time walks the queue. If two threads were both inside the match loop on the same price level, they'd both see the same resting order, both try to fill it, and double-count the fill — the resting order's quantity gets sold twice and the accounting is corrupt. So single-threaded matching is correct *by design*. The whole match — one incoming order consuming as many resting orders as it needs, in price-then-time order — has to be one atomic operation.

**Step two: I drew the wrong conclusion from that.** I reasoned that if the engine is single-threaded by nature, I don't need a lock — so I removed it. That felt clean. It was wrong.

**Step three: I found the hole, and I reproduced it.** FastAPI runs synchronous endpoint handlers in a *threadpool*. So a `submit` and a `cancel` actually land on different threads, and under Python's GIL handoff both end up inside the engine at the same time — one thread mid-match while another mutates the book. I didn't theorize this; I reproduced it as `ValueError: Order not in deque` and `KeyError` when the two operations overlapped on the same order. My "single-threaded by construction" assumption was an assumption about my *code* that the *web framework* quietly broke.

**Step four: I had two real options to actually enforce single-threading,** and I weighed them:

- **Option 1 — a lock.** Wrap `submit_order`, `cancel_order`, `snapshot`, and `resolve_market` in a `threading.RLock`. The HTTP server still handles requests concurrently at the OS level, but every engine mutation is serialized through the lock, so the engine stays single-threaded. Portable, and the guarantee lives *in the code*.
- **Option 2 — constrain the deployment.** Run `uvicorn app:app --workers 1 --threads 1` so only one request is ever in flight. The engine is then genuinely single-threaded by deployment. Simpler code — but fragile: if someone runs it with `--workers 4` by accident, it breaks silently, and the guarantee lives in a deploy flag instead of the code.

I also briefly considered **switching to Flask**, because I'd read that its development server is single-threaded and thought that would remove the need for a lock entirely. That turned out to be a trap, not a shortcut. Flask's dev server can't handle concurrent requests *at all* — fine for local testing — but the moment it runs under a real WSGI server like Gunicorn, you get multiple workers by default and you're right back in the same problem. Flask would have *hidden* the concurrency question during development, not answered it. So I stayed on FastAPI.

**I chose Option 1, the lock.** For a take-home it's the stronger signal: it says "I know the engine must be single-threaded, and I enforced it in code, not by hope and documentation." It survives any deployment, and it's three lines. I used `RLock` rather than `Lock` as insurance — a re-entrant lock won't self-deadlock if I later add a feature like cancel-replace where one locked method has to call another.

Now the part I think actually matters — **the honest ups and downs of single-writer versus multi-threaded**, because the decision only means something if I can name what I traded away:

What going single-writer **buys me**:
- **Determinism.** The same sequence of orders always produces the same trades, in the same order. For an exchange that's not a nicety — it's what makes the system auditable and replayable.
- **Correctness by construction.** The cancel-while-matching race can't *exist*, because two operations can never be inside the engine at once. I'm not managing the race; I'm eliminating it.
- **Fair FIFO ordering**, preserved exactly, because there's a single well-defined order of operations.

What going single-writer **costs me**:
- **No multi-core parallelism inside a book.** Throughput is bounded by a single core, and under heavy load, requests queue behind the lock. I cannot make one book go faster by adding threads.

What multi-threading **would buy**:
- **Parallel matching across price levels** and higher throughput on many cores.

What multi-threading **would cost**:
- **Non-determinism** — trade order would depend on thread scheduling, which is unacceptable where fairness and replayability matter.
- **Lock-ordering and deadlock complexity**, and a class of bugs that only appear under load and are miserable to reproduce (exactly the `KeyError` I already hit, but worse and intermittent).

The verdict I landed on, and why I'm confident in it: **for a matching engine, determinism and correctness dominate raw throughput.** This isn't just true for a toy — real production engines (CME, major crypto exchanges) run their core single-threaded for the same reason. The right way to scale is *not* to parallelize within a book; it's to keep each book single-writer and deterministic and **shard by instrument**, so every contract runs on its own single-threaded engine. That's the answer I'd give to "how does this scale?" — and it's the opposite of the "add concurrency" instinct.

### 5. Self-trade prevention — the bug I shipped to myself first

A single owner can legitimately rest a buy and a sell at the same time, as long as they don't cross in price. The problem is only when a *new* order from an owner would match against that *same owner's* resting order.

My first implementation used **skip-and-continue**: on a self-match, skip that resting order and keep looking. I thought it was clean — and it was wrong, which I only found because I probed it instead of trusting that it looked right. After a same-owner submit sequence, the book showed `best_bid = 60, best_ask = 55` — a **crossed book**, a bid priced *above* an ask, which is logically impossible. The cause: when there's no other order on the opposite side, "skip" leaves my incoming order resting on top of my own resting order at a crossing price.

The fix is to pick a side and remove it. My engine **cancels the resting order** and lets the incoming order proceed — "your newer order supersedes the old one." Cancelling the incoming order, or cancelling both, are equally defensible policies; the requirement is to choose one and hold the invariant: **best bid is always strictly less than best ask.** I check that invariant explicitly with a `raise`, not an `assert` — because `assert` statements are stripped out when Python runs with the `-O` flag, which would silently disable my most important safety check exactly where it matters most. An invariant that protects correctness must not be optimizable away.

I'm including this story deliberately. The skip approach *reads* correctly. The only reason I know it's broken is that I reproduced the crossed book with an actual probe — and that's the habit I'd bring to production code, not the assumption that plausible-looking logic is right.

### 6. Partial fills, and the invariants I protect

`quantity` is the permanent record of how big an order was; `remaining` is its live state as it fills. Conflating them would make partial-fill accounting impossible, so they're separate fields — and `remaining` is the *only* mutable field on the order. I enforce that: the other six fields are frozen via a custom `__setattr__` override (Pydantic v2's `frozen=True` is all-or-nothing at the model level, which isn't what I needed), so an accidental write to `price` or `side` anywhere in the loop raises immediately instead of corrupting the book quietly.

Three invariants hold at all times: `remaining` is never negative, never exceeds the original `quantity`, and an order whose `remaining` hits zero is removed from the book — no zero-quantity ghost orders left on a level to "match" for nothing. These guard against the three bug classes I was most worried about: double-counting a fill, an off-by-one on `remaining`, and a filled husk lingering on the book.

### 7. Idempotent submission

Every submit carries a client-generated `client_order_id` (a UUID). The server caches the result per id; a retry with the same id returns the original result instead of placing a duplicate order. This is what makes the API safe to retry over an unreliable network, where a client genuinely can't tell whether a dropped response means "never arrived" or "arrived, reply lost." This wasn't required — I added it because it's the difference between an API that's safe to put behind a retrying client and one that double-fills on a flaky connection.

**The cost I accepted and documented:** the cache is unbounded in this toy. In production it needs TTL or size-based eviction, accepting that retries older than the window would no longer be deduplicated. I'd rather name that gap than pretend the cache is production-ready.

### 8. The REST decisions

A few status mappings are deliberate:

- **`POST /orders` returns `201` whether or not the order traded.** A submit that fully rests, partially fills, or fully fills all return `201`, because the order *was* created regardless of whether it found a counterparty. Fill state belongs in the body (the trades and remaining quantity), not the status code. The code answers "was your request accepted?"; the body answers "what happened to it?"
- **`DELETE` collapses "not found" and "wrong owner" into one `404`, deliberately not a `403`.** A `403` would tell the caller "this order exists, but it isn't yours" — leaking the existence of another participant's order, which a real exchange wouldn't do. Returning `404` for both refuses to confirm the order exists to a non-owner. The less-informative response is the more correct one.
- **`owner_id` as a query parameter is a stand-in for auth, not a substitute for it.** With no real auth system in scope, ownership is asserted via `?owner_id=101`. It's explicitly not secure — it's a placeholder for "prove you own this order" that keeps cancel semantics meaningful without building an auth layer that's out of scope.

---

## The matching algorithm

When an order arrives, I match it against the **opposite** side before letting any remainder rest:

1. Look at the best price level on the opposite side.
2. If it doesn't **cross** the incoming order's limit, stop — any remaining quantity rests on the book.
3. Otherwise fill against the front order in that level. Fill size is `min(incoming.remaining, resting.remaining)`.
4. **The trade executes at the *resting* order's price,** not the incoming order's — this gives price improvement to the aggressor.
5. Decrement both `remaining` values; remove the resting order if it's fully filled, and drop the level if it's empty.
6. Repeat until the incoming order is exhausted or no opposite level crosses.

**Worked example.** Book before:

```
Asks:  62 → [Eve 40]   65 → [Frank 80]
Bids:  60 → [Alice 100]
```

Incoming: **BUY 70 @ 63** from Carol.

- Best ask is 62, and 62 ≤ 63 → crosses. Fill `min(70, 40) = 40` at price **62** (Eve's resting price — Carol pays 62, not her limit of 63). Carol's `remaining` → 30; Eve is fully filled and leaves the book.
- Next best ask is 65, and 65 > 63 → no cross. Stop.
- Carol's remaining 30 rests as a new bid at 63.

```
Asks:  65 → [Frank 80]
Bids:  63 → [Carol 30]   60 → [Alice 100]
```

That one example exercises a cross, price improvement for the aggressor, a partial fill, and a remainder resting at a new level.

---

## What I deliberately left out

Naming what I left out matters as much as what I built, because it shows the scope was chosen, not stumbled into. This engine does **not** implement:

- **Market orders** (and types like IOC / FOK) — limit-orders-only by scope.
- **Multiple instruments** — one book, one contract.
- **Persistence across restart** — fully in-memory.
- **Authentication** — `owner_id` is a stand-in.
- **Horizontal scale** — single process by design.
- **A dual YES/NO book.** In a binary market, buying YES at price *p* is economically identical to selling NO at *(100 − p)*, and some real prediction-market exchanges (e.g. Kalshi) run two books and cross YES-buyers against NO-buyers, splitting the $1 of collateral. I scoped to a **single YES book** deliberately, because dual-book crossing is substantial added complexity that isn't needed for a correct matching demonstration. Knowing the duality exists and choosing not to build it is the point.

---

## What I'd do with more time

Roughly in priority order:

1. **Persistence via an append-only event log.** Record every accepted order and cancel as an event so the book can be deterministically rebuilt by replay. This fits the single-writer model cleanly — the writer is already the natural serialization point for the log.
2. **Bound the idempotency cache** with TTL or size-based eviction.
3. **Swap the per-level deque for an intrusive doubly-linked list** so cancellation is true `O(1)` instead of `O(k)` in level depth — the runtime tradeoff from section 3.
4. **Dual-book YES/NO crossing**, the binary-market-correct version of the book.
5. **A `GET /orders/{order_id}` status endpoint** to query a single order's live state.
6. **Real authentication** replacing the `owner_id` stand-in.
7. **Scale by sharding per instrument** — keep each book single-threaded and deterministic, and partition contracts across engines, with a central sequencer if global cross-shard ordering is ever needed. Not by adding concurrency inside a book.

---

## How I worked on this

I used Claude as an implementation assistant — to type and pressure-test code against decisions I'd already made — not as a designer. Every choice in this document is mine: the data structure and its runtime tradeoff, the counter-not-clock timing decision, the single-writer concurrency model and the two options I weighed to enforce it, the integer-cent prices, the status-code mappings, and the scoping to a single book. The self-trade and concurrency sections in particular reflect real debugging and a corrected assumption — I shipped skip-and-continue self-trade prevention and a lock-less engine to myself first, reproduced the crossed book and the threadpool race with actual probes, and fixed both — which is exactly the kind of reasoning a one-shot prompt doesn't produce. The accompanying AI-usage export shows that process directly.
