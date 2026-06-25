# Matching Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add price-time priority matching to `MatchingEngine` with self-trade prevention and partial-fill resting.

**Architecture:** `Trade` is a frozen record produced by matching. `OrderBook.prices(side)` exposes sorted price keys so the engine can iterate levels in priority order. `MatchingEngine._match()` owns the crossing loop; `submit_order()` is the single public entry point.

**Tech Stack:** Python 3.10+, pydantic v2, collections.deque (stdlib)

## Global Constraints
- No market orders — all orders carry a price
- `Trade.price` is the resting (maker) order's price
- Self-trade: skip resting orders owned by incoming order's owner — do not cancel either side
- Partial remainder: incoming order rests in the book if `remaining > 0` after matching

---

### Task 1: Add `Trade` to `order.py` and `prices(side)` to `book.py`

**Files:**
- Modify: `order.py` — add `Trade` frozen pydantic model after `OrderRequest`
- Modify: `book.py` — add `prices(side)` method to `OrderBook`
- Test: `test_matching.py` (create)

**Interfaces:**
- Produces:
  - `Trade(buy_order_id: str, sell_order_id: str, price: int, quantity: int)` — frozen, immutable after creation
  - `OrderBook.prices(side: Side) -> list[int]` — price keys in priority order (BUY: descending, SELL: ascending)

- [ ] **Step 1: Write the failing test for `Trade` and `prices()`**

Create `test_matching.py`:

```python
from collections import deque

from book import OrderBook
from order import Order, OrderRequest, Side, Trade


def _order(oid: str, side: Side, price: int, qty: int) -> Order:
    return Order.create(
        side=side, price=price, quantity=qty, owner="t",
        order_id=oid, sequence_number=int(oid),
    )


def test_trade_is_immutable() -> None:
    t = Trade(buy_order_id="b1", sell_order_id="s1", price=50, quantity=10)
    assert t.price == 50
    try:
        t.price = 60  # type: ignore[misc]
        raise AssertionError("should have raised")
    except Exception as e:
        assert "frozen" in str(e).lower() or "immutable" in str(e).lower()


def test_prices_asks_ascending() -> None:
    book = OrderBook()
    for oid, p in [("3", 55), ("1", 50), ("2", 52)]:
        book.add(_order(oid, Side.SELL, p, 5))
    assert book.prices(Side.SELL) == [50, 52, 55]


def test_prices_bids_descending() -> None:
    book = OrderBook()
    for oid, p in [("1", 48), ("2", 50), ("3", 45)]:
        book.add(_order(oid, Side.BUY, p, 5))
    assert book.prices(Side.BUY) == [50, 48, 45]


if __name__ == "__main__":
    test_trade_is_immutable()
    test_prices_asks_ascending()
    test_prices_bids_descending()
    print("task 1 ok")
```

- [ ] **Step 2: Run test to confirm it fails**

```
python test_matching.py
```
Expected: `ImportError: cannot import name 'Trade' from 'order'`

- [ ] **Step 3: Add `Trade` to `order.py`**

Add after the `OrderRequest` class (before `class Order`):

```python
class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    buy_order_id: str
    sell_order_id: str
    price: int
    quantity: int
```

- [ ] **Step 4: Add `prices()` to `OrderBook` in `book.py`**

Add after the `level()` method:

```python
def prices(self, side: Side) -> list[int]:
    return sorted(self._side_book(side), reverse=(side == Side.BUY))
```

- [ ] **Step 5: Run test to confirm it passes**

```
python test_matching.py
```
Expected: `task 1 ok`

- [ ] **Step 6: Commit**

```bash
git add order.py book.py test_matching.py
git commit -m "feat: add Trade model and OrderBook.prices()"
```

---

### Task 2: Add `submit_order` and `_match` to `MatchingEngine`

**Files:**
- Modify: `engine.py` — add `_book`, `submit_order`, `_match`
- Modify: `test_matching.py` — add matching tests

**Interfaces:**
- Consumes:
  - `Trade(buy_order_id, sell_order_id, price, quantity)` from Task 1
  - `OrderBook.prices(side) -> list[int]` from Task 1
  - `OrderBook.level(side, price) -> deque[Order]`
  - `OrderBook.add(order)`, `OrderBook.remove(order)`
  - `Order.remaining: int` (mutable)
  - `MatchingEngine._create_order(request) -> Order`
- Produces:
  - `MatchingEngine.submit_order(request: OrderRequest) -> list[Trade]`

- [ ] **Step 1: Add matching tests to `test_matching.py`**

Append these functions to `test_matching.py` (before `if __name__ == "__main__":`):

```python
from engine import MatchingEngine


def test_no_cross_rests_in_book() -> None:
    eng = MatchingEngine()
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))
    assert trades == []
    assert eng._book.best_bid() == 50


def test_full_fill() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))
    assert len(trades) == 1
    assert trades[0].price == 50
    assert trades[0].quantity == 10
    assert eng._book.best_ask() is None
    assert eng._book.best_bid() is None


def test_partial_fill_incoming_rests() -> None:
    # incoming buy 15, resting sell 10 → 10 filled, 5 rests as bid
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=15, owner="alice"))
    assert len(trades) == 1
    assert trades[0].quantity == 10
    assert eng._book.best_bid() == 50


def test_partial_fill_resting_stays() -> None:
    # incoming buy 5, resting sell 10 → 5 filled, resting has 5 remaining
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=5, owner="alice"))
    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert eng._book.best_ask() == 50


def test_multi_level_fill() -> None:
    # buy 20 @51 crosses two ask levels: 10@50, 10@51
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))
    eng.submit_order(OrderRequest(side=Side.SELL, price=51, quantity=10, owner="carol"))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=51, quantity=20, owner="alice"))
    assert len(trades) == 2
    assert trades[0].price == 50   # best ask filled first
    assert trades[1].price == 51


def test_self_trade_skipped() -> None:
    # same owner: resting ask skipped, incoming buy rests as bid
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="alice"))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))
    assert trades == []
    assert eng._book.best_bid() == 50
    assert eng._book.best_ask() == 50


def test_fifo_within_level() -> None:
    # two sells at same price; first arrival (order-1) fills before second (order-2)
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=5, owner="bob"))    # order-1
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=5, owner="carol"))  # order-2
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=5, owner="alice"))
    assert len(trades) == 1
    assert trades[0].sell_order_id == "order-1"
```

Also update the `if __name__ == "__main__":` block at the bottom:

```python
if __name__ == "__main__":
    test_trade_is_immutable()
    test_prices_asks_ascending()
    test_prices_bids_descending()
    test_no_cross_rests_in_book()
    test_full_fill()
    test_partial_fill_incoming_rests()
    test_partial_fill_resting_stays()
    test_multi_level_fill()
    test_self_trade_skipped()
    test_fifo_within_level()
    print("all ok")
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python test_matching.py
```
Expected: `ImportError` or `AttributeError: MatchingEngine has no attribute '_book'`

- [ ] **Step 3: Rewrite `engine.py`**

```python
from book import OrderBook
from order import Order, OrderRequest, Side, Trade


class MatchingEngine:
    def __init__(self) -> None:
        self._next_seq = 0
        self._book = OrderBook()

    def submit_order(self, request: OrderRequest) -> list[Trade]:
        order = self._create_order(request)
        trades = self._match(order)
        if order.remaining > 0:
            self._book.add(order)
        return trades

    def _match(self, incoming: Order) -> list[Trade]:
        trades: list[Trade] = []
        opposite = Side.SELL if incoming.side == Side.BUY else Side.BUY

        for price in self._book.prices(opposite):
            if incoming.remaining == 0:
                break
            if incoming.side == Side.BUY and price > incoming.price:
                break
            if incoming.side == Side.SELL and price < incoming.price:
                break
            for resting in list(self._book.level(opposite, price)):
                if incoming.remaining == 0:
                    break
                if resting.owner == incoming.owner:
                    continue
                filled = min(incoming.remaining, resting.remaining)
                incoming.remaining -= filled
                resting.remaining -= filled
                buy_id = incoming.order_id if incoming.side == Side.BUY else resting.order_id
                sell_id = resting.order_id if incoming.side == Side.BUY else incoming.order_id
                trades.append(Trade(
                    buy_order_id=buy_id,
                    sell_order_id=sell_id,
                    price=price,
                    quantity=filled,
                ))
                if resting.remaining == 0:
                    self._book.remove(resting)

        return trades

    def _create_order(self, request: OrderRequest) -> Order:
        self._next_seq += 1
        seq = self._next_seq
        return Order.create(
            side=request.side,
            price=request.price,
            quantity=request.quantity,
            owner=request.owner,
            sequence_number=seq,
            order_id=f"order-{seq}",
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python test_matching.py
```
Expected: `all ok`

- [ ] **Step 5: Commit**

```bash
git add engine.py test_matching.py
git commit -m "feat: price-time priority matching with self-trade prevention"
```
