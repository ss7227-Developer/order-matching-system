# cancel_order + snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cancel_order` and `snapshot` to `MatchingEngine` as one-line delegations to `self._book`, with four covering tests.

**Architecture:** Both methods are pure pass-throughs to `OrderBook.cancel()` and `OrderBook.snapshot()` which already exist and are tested. No new state, no new logic.

**Tech Stack:** Python 3.10+, pydantic v2

## Global Constraints
- `cancel_order` returns the removed `Order` or `None` — no distinction between "filled" and "never existed"
- Both methods route exclusively through `self._book` — no parallel state
- Do not touch `submit_order` or `_match`

---

### Task 1: Add `cancel_order` + `snapshot` to `MatchingEngine` with tests

**Files:**
- Modify: `engine.py` — add two methods after `submit_order`
- Modify: `test_matching.py` — add four tests, update `__main__` block

**Interfaces:**
- Consumes: `OrderBook.cancel(order_id: str) -> Order | None` (already in `book.py`)
- Consumes: `OrderBook.snapshot() -> dict` (already in `book.py`)
- Produces: `MatchingEngine.cancel_order(order_id: str) -> Order | None`
- Produces: `MatchingEngine.snapshot() -> dict`

- [ ] **Step 1: Add four failing tests to `test_matching.py`**

Append these functions before the `if __name__ == "__main__":` block:

```python
def test_cancel_removes_resting_order() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))  # order-1
    cancelled = eng.cancel_order("order-1")
    assert cancelled is not None
    assert cancelled.order_id == "order-1"
    assert eng._book.best_bid() is None


def test_cancel_nonexistent_returns_none() -> None:
    eng = MatchingEngine()
    assert eng.cancel_order("order-999") is None


def test_cancel_already_filled_returns_none() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))   # order-1
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))    # order-2, fills order-1
    assert eng.cancel_order("order-1") is None


def test_snapshot_reflects_state() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=48, quantity=5, owner="alice"))
    eng.submit_order(OrderRequest(side=Side.SELL, price=52, quantity=3, owner="bob"))
    assert eng.snapshot() == {
        "bids": [{"price": 48, "quantity": 5}],
        "asks": [{"price": 52, "quantity": 3}],
    }
```

Also add all four to the `if __name__ == "__main__":` block:

```python
    test_cancel_removes_resting_order()
    test_cancel_nonexistent_returns_none()
    test_cancel_already_filled_returns_none()
    test_snapshot_reflects_state()
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python test_matching.py
```
Expected: `AttributeError: 'MatchingEngine' object has no attribute 'cancel_order'`

- [ ] **Step 3: Add `cancel_order` and `snapshot` to `engine.py`**

Add these two methods to `MatchingEngine` after `submit_order`:

```python
def cancel_order(self, order_id: str) -> Order | None:
    return self._book.cancel(order_id)

def snapshot(self) -> dict:
    return self._book.snapshot()
```

- [ ] **Step 4: Run tests to confirm all pass**

```
python test_matching.py
```
Expected: `all ok`

- [ ] **Step 5: Commit**

```bash
git add engine.py test_matching.py
git commit -m "feat: add cancel_order and snapshot to MatchingEngine"
```
