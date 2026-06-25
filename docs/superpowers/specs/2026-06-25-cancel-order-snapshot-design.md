# cancel_order + snapshot Design
**Date:** 2026-06-25

## Overview
Add `cancel_order` and `snapshot` to `MatchingEngine` as pure delegations to `self._book`. No new state, no new logic — both operations already exist on `OrderBook`.

## Changes

### `engine.py` — two new public methods
```python
def cancel_order(self, order_id: str) -> Order | None:
    return self._book.cancel(order_id)

def snapshot(self) -> dict:
    return self._book.snapshot()
```

### `test_matching.py` — four new tests
- `test_cancel_removes_resting_order` — submit buy that rests, cancel by order_id, assert Order returned, assert `best_bid() is None`
- `test_cancel_nonexistent_returns_none` — cancel unknown id, assert `None`
- `test_cancel_already_filled_returns_none` — fill a sell fully, then cancel its id, assert `None`
- `test_snapshot_reflects_state` — two resting orders, assert `engine.snapshot()` matches expected structure

## Constraints
- `cancel_order` returns the removed `Order` or `None` — no distinction between "filled" and "never existed"
- Both methods route through `self._book` — no parallel state
- `submit_order` and `cancel_order` are the only two mutating entry points
