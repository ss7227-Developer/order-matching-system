# Binary-Outcome Order Matching Engine

A limit-order matching engine with a REST API for a single binary-outcome market — a YES/NO
contract priced in integer cents (`1`–`99`). Orders match on **price-time priority**; any
unfilled remainder rests on the book. The matching core has no knowledge of HTTP and can be
driven entirely in-process (the test suite does exactly that).

---

## What it does

- Accepts limit orders (`BUY`/`SELL`, price `1`–`99`, positive integer quantity) over HTTP.
- Matches an incoming order against the resting book **best price first, FIFO within a price level**.
- Rests any unfilled remainder and returns the trades produced plus the remaining quantity.
- Cancels resting orders by id (owner-scoped).
- Serves a live order-book snapshot.

It handles the four required edge cases — self-trades, partial-fill accounting,
cancel-while-matching, and input validation — plus two deliberate extras: **idempotent submit**
and **market resolution**.

---

## Architecture

Four layers, one job each, dependencies pointing one direction
(`transport → engine → book → domain`):

| File | Responsibility |
|------|----------------|
| `order.py` | Domain types + validation (Pydantic v2). The only definition of what an order *is*. |
| `book.py` | Order-book data structure: price levels, FIFO queues, an id index. No matching logic. |
| `engine.py` | Matching algorithm, idempotency, resolution, concurrency control. **The single writer.** |
| `app.py` | HTTP transport. The only module that imports FastAPI. |
| `exceptions.py` | Engine error types. |

`app.py` is the only file that knows about HTTP; `engine.py` is the only file that mutates state.
That separation is why the entire engine is testable without starting a web server.

---

## API

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/orders` | `201` with `{order_id, trades, remaining}` |
| `DELETE` | `/orders/{order_id}?owner_id=…` | `200` with the cancelled order, or `404` |
| `GET` | `/orderbook` | snapshot of resting bids and asks |

Market resolution (`resolve_market`) is modelled at the engine layer and tested directly. It is a
privileged operational action, not a public participant endpoint in this iteration — see
**Future work**.

---

## Running it

```bash
pip install fastapi "uvicorn[standard]" "pydantic>=2"
uvicorn app:app --reload
```

Submit an order:

```bash
curl -X POST localhost:8000/orders \
  -H 'content-type: application/json' \
  -d '{"client_order_id":"abc","side":"SELL","price":50,"quantity":10,"owner_id":202}'
```

---

## Tests

```bash
python test_matching.py     # runs the full suite, prints "all ok"
# or
pytest test_matching.py
```

37 tests covering matching (full / partial / multi-level), price-then-time priority, FIFO across
cancellation, self-trade prevention in every queue position, cancellation and owner-scoping,
input validation, idempotency, market resolution, immutability of returned snapshots, and an
**8-thread × 250-submit concurrency stress test** that fails without the engine lock.

---

## How I built it

I used Claude as an implementation assistant. The architectural decisions, tradeoffs, and final design choices were mine. 
I built one layer at a time, and for the two genuinely hard cases I deliberately shipped the *wrong* version to myself first: skip-and-continue self-trade
prevention, and a lock-less engine. I then reproduced the resulting crossed book and the
threadpool race with live probes and fixed both. That debugging is the part a one-shot prompt
doesn't produce, and the accompanying AI-usage export shows it directly.

The full rationale — every decision, the alternative I weighed against it, and what each one
costs — is in [`DESIGN.md`](./DESIGN.md).

---

## What I'd do with more time

1. **Bound the idempotency cache** (TTL or LRU). It grows unbounded today — fine for an exercise,
   a leak in production.
2. **Map engine exceptions to HTTP status codes.** `MarketResolvedError` and `BookInvariantError`
   currently surface as `500`; they should be `409` and a `500`-with-alert respectively.
3. **Swap each price level's `deque` for an intrusive doubly-linked list** so cancellation is true
   `O(1)` instead of `O(k)` in level depth.
4. **Expose resolution behind an authenticated admin endpoint**, and replace the `owner_id`
   query-param stand-in with real authentication.
5. **Add `GET /orders/{order_id}`** to query a single order's live state.
6. **Model the binary market as a dual YES/NO book** with cross-side matching, rather than one
   single-sided book.
7. **Scale by sharding per instrument** — one single-writer engine per contract — *not* by adding
   threads inside a book.
