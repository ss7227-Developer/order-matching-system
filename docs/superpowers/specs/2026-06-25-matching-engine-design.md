# Matching Engine Design
**Date:** 2026-06-25

## Overview
Add price-time priority matching to `MatchingEngine`. Incoming orders cross against resting orders on the opposite side; same-owner orders are skipped (self-trade prevention); partial fills rest in the book.

## Changes

### `order.py` — add `Trade`
Frozen pydantic model: `buy_order_id: str`, `sell_order_id: str`, `price: int`, `quantity: int`.

### `book.py` — add `prices(side) -> list[int]`
Returns price keys in priority order: descending for BUY (highest bid first), ascending for SELL (lowest ask first).

### `engine.py` — extend `MatchingEngine`
- `__init__`: add `self._book = OrderBook()`
- `submit_order(request: OrderRequest) -> list[Trade]`: creates order via `_create_order`, runs `_match`, rests remainder if `order.remaining > 0`, returns trades
- `_match(incoming: Order) -> list[Trade]`:
  - Crossing condition: incoming BUY crosses `ask_price <= buy.price`; incoming SELL crosses `bid_price >= sell.price`
  - Iterate opposite-side price levels in priority order; stop when no longer crossable or incoming fully filled
  - Within each level, iterate a snapshot of the deque FIFO; skip same owner; `filled = min(incoming.remaining, resting.remaining)`; decrement both; append `Trade`; `book.remove(resting)` if fully filled

## Constraints
- No market orders (all orders have a price)
- `Trade.price` is the resting order's price (maker price)
- Self-trade: skip, do not cancel
- Partial remainder: rests in book, not discarded
