# Binary Outcome Order-Matching Engine

A toy, in-memory limit-order matching engine with a REST API for a binary outcome market: submit/cancel limit orders, match by price-time priority, partial fills, and an order-book snapshot.

*A more detailed write-up of my design tradeoffs and decisions is in [`DESIGN_NOTES.pdf`](./DESIGN_NOTES.pdf) for anyone who wants the deeper reasoning. This README stands on its own.*

---

## What I built

- **Limit orders only** — buy/sell at a price or better, resting on the book if unfilled.
- **Price-time priority matching** — best price first; FIFO is the tiebreaker within a price level.
- **Partial fills**, tracked precisely: an order's `remaining` quantity is separate from its original `quantity`, and is the only field that mutates after creation.
- **Cancel**, by order id, scoped to the owner who placed it.
- **Self-trade prevention** — if a new order would match against the same owner's resting order, I cancel the resting order rather than letting both sides rest at a crossing price.
- **An order-book snapshot** — bids and asks aggregated by price level.
- **Idempotent submission** — a client-generated `client_order_id` is cached server-side so a retried request returns the original result instead of double-placing an order.
- **Market resolution** — cancels all resting orders and locks the book against further trading.

Prices are integer cents, 1-99 (a binary contract's price is a probability, and it can't be 0 or 100 while still tradeable).

## How I built it

Four layers, with one rule enforced throughout: **the matching engine has no knowledge that HTTP exists.**

```
app.py     FastAPI + Pydantic - the only file that imports FastAPI. Thin translation only.
engine.py  MatchingEngine - the matching loop, self-trade policy, and the lock that
           serializes every mutation.
book.py    OrderBook - bids/asks as price -> FIFO queue, plus an id index for cancel.
order.py   Domain types: Order, OrderRequest, and the Price/Quantity constraints.
```

A few decisions I want to call out directly, because they're the ones that actually mattered:

- **Time priority uses a monotonic counter, not a wall-clock timestamp.** A clock can produce ties at the same instant, and can be adjusted backwards by NTP - either of which would break FIFO ordering silently. A counter that only increments can't do either.
- **The matching loop has to run one order at a time, but I initially got the *enforcement* of that wrong.** I first assumed the engine was single-threaded "by nature" and removed a lock I'd added - but FastAPI actually runs request handlers in a threadpool, so `submit` and `cancel` can land on different threads at the same time. I reproduced the resulting race as real exceptions, then put a lock back around every state-mutating method so the engine is serialized in code, not by assumption.
- **My first self-trade prevention policy was wrong, and I caught it by testing, not by reading the code.** A "skip and continue" approach left a crossed book (a bid priced above an ask) in a case with no other resting order to fall back on. The fix was to cancel the resting order outright rather than skip past it.
- **The crossed-book safety check uses `raise`, not `assert`**, since `assert` is silently stripped out when Python runs with `-O`.

I tested the engine directly - no HTTP involved - with 37 tests covering self-trades, partial fills, FIFO ordering, cancellation, validation, idempotency, and a concurrency stress test, all passing.

## What I'd do with more time

1. **Persistence.** Everything is in-memory right now and disappears on restart. I'd add an append-only event log of every accepted order and cancel, so the book could be rebuilt deterministically by replaying it.
2. **A faster cancel for deep order books.** Cancelling currently scans the price level it's removing from, which is fine at the depth a toy sees but becomes the bottleneck if many orders stack at one price. I scoped out a doubly-linked-list-per-level redesign that makes cancel O(1) instead - I have the design worked out, but didn't take it on the night before submission, since it touches five different parts of the book and the risk of leaving a dangling reference wasn't one I wanted to carry untested into a deadline.
3. **Real authentication.** Ownership is currently asserted with a plain `owner_id` query parameter, which is a stand-in, not security.

---

*Built with Claude as an implementation assistant for typing and pressure-testing code against decisions I'd already made - not as a designer. The accompanying AI-tool export reflects that process.*
