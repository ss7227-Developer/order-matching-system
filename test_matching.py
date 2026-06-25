from book import OrderBook
from engine import MatchingEngine
from order import CancelledOrder, Order, OrderRequest, Side, Trade


def _order(oid: str, side: Side, price: int, qty: int) -> Order:
    return Order.create(
        side=side, price=price, quantity=qty, owner_id=1,
        order_id=oid, sequence_number=int(oid),
    )


def _req(side: Side, price: int, qty: int, owner_id: int = 101) -> OrderRequest:
    return OrderRequest(side=side, price=price, quantity=qty, owner_id=owner_id)


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


def test_no_cross_rests_in_book() -> None:
    eng = MatchingEngine()
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))
    assert trades == []


def test_full_fill() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))
    assert len(trades) == 1
    assert trades[0].price == 50
    assert trades[0].quantity == 10


def test_partial_fill_incoming_rests() -> None:
    # incoming buy 15, resting sell 10 → 10 filled, 5 rests as bid
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=15, owner_id=101))
    assert len(trades) == 1
    assert trades[0].quantity == 10


def test_partial_fill_resting_stays() -> None:
    # incoming buy 5, resting sell 10 → 5 filled, resting has 5 remaining
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=5, owner_id=101))
    assert len(trades) == 1
    assert trades[0].quantity == 5


def test_multi_level_fill() -> None:
    # buy 20 @51 crosses two ask levels: 10@50, 10@51
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))
    eng.submit_order(OrderRequest(side=Side.SELL, price=51, quantity=10, owner_id=303))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=51, quantity=20, owner_id=101))
    assert len(trades) == 2
    assert trades[0].price == 50   # best ask filled first
    assert trades[1].price == 51


def test_self_trade_skipped() -> None:
    # same owner: incoming buy expires on own ask — no crossed book, no resting bid
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=101))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))
    assert trades == []


def test_fifo_within_level() -> None:
    # two sells at same price; first arrival (order-1) fills before second (order-2)
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=5, owner_id=202))    # order-1
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=5, owner_id=303))  # order-2
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=5, owner_id=101))
    assert len(trades) == 1
    assert trades[0].sell_order_id == "order-1"


def test_sell_aggressor_full_fill() -> None:
    # resting BUY@50, incoming SELL@50 → one trade, correct buy/sell ids
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))   # order-1
    trades = eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))
    assert len(trades) == 1
    assert trades[0].price == 50
    assert trades[0].quantity == 10
    assert trades[0].buy_order_id == "order-1"
    assert trades[0].sell_order_id == "order-2"


def test_cancel_removes_resting_order() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))  # order-1
    cancelled = eng.cancel_order("order-1", 101)
    assert isinstance(cancelled, CancelledOrder)
    assert cancelled.order_id == "order-1"
    assert cancelled.remaining == 10  # untouched


def test_cancel_nonexistent_returns_none() -> None:
    eng = MatchingEngine()
    assert eng.cancel_order("order-999", 101) is None


def test_cancel_already_filled_returns_none() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))   # order-1
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=202))    # order-2, fills order-1
    assert eng.cancel_order("order-1", 101) is None


def test_snapshot_reflects_state() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=48, quantity=5, owner_id=101))
    eng.submit_order(OrderRequest(side=Side.SELL, price=52, quantity=3, owner_id=202))
    assert eng.snapshot() == {
        "bids": [{"price": 48, "quantity": 5}],
        "asks": [{"price": 52, "quantity": 3}],
    }


def test_self_trade_no_crossed_book() -> None:
    # self-trade skip: alice's ask@50, incoming buy@52 skips it and rests at 52
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=101))  # order-1
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=52, quantity=10, owner_id=101))
    assert trades == []


def test_self_trade_buy_crossing_own_ask() -> None:
    # BUY crosses own resting ASK → skip, buy rests at 55; both sides remain in book
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=101))
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=55, quantity=10, owner_id=101))
    assert trades == []


def test_self_trade_sell_crossing_own_bid() -> None:
    # SELL crosses own resting BID → skip, sell rests at 50; both sides remain in book
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=55, quantity=10, owner_id=101))
    trades = eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner_id=101))
    assert trades == []


def test_self_trade_partial_fill_then_skip_rest() -> None:
    # BUY fills against bob@50, then hits alice's ask@51 → skip, remainder rests at 55
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=5, owner_id=202))    # order-1
    eng.submit_order(OrderRequest(side=Side.SELL, price=51, quantity=5, owner_id=101))  # order-2 (own ask)
    trades = eng.submit_order(OrderRequest(side=Side.BUY, price=55, quantity=10, owner_id=101))
    assert len(trades) == 1          # filled against bob only
    assert trades[0].quantity == 5
    assert trades[0].price == 50


def test_cancel_wrong_owner() -> None:
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101))  # order-1
    assert eng.cancel_order("order-1", 202) is None  # wrong owner


def test_owner_id_validation() -> None:
    # valid
    OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=101)

    for bad in ("101", True, 0, -1):
        try:
            OrderRequest(side=Side.BUY, price=50, quantity=10, owner_id=bad)  # type: ignore[arg-type]
            raise AssertionError(f"owner_id={bad!r} should have been rejected")
        except Exception as e:
            assert not isinstance(e, AssertionError), str(e)


def test_duplicate_order_id_rejected() -> None:
    book = OrderBook()
    o = _order("1", Side.BUY, 50, 5)
    book.add(o)
    try:
        book.add(o)
        raise AssertionError("should have raised ValueError")
    except ValueError as e:
        assert "duplicate" in str(e).lower()


def test_cancel_returns_remaining_at_cancel_time() -> None:
    # partially filled order carries correct remaining in CancelledOrder snapshot
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 10, 202))   # order-1 rests
    eng.submit_order(_req(Side.BUY, 50, 3))           # fills 3 from order-1 (7 remaining)
    cancelled = eng.cancel_order("order-1", 202)
    assert cancelled is not None
    assert cancelled.quantity == 10
    assert cancelled.remaining == 7


def test_fill_accounting_invariant() -> None:
    # total traded + final resting remainder == original submitted quantity
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 3, 202))
    eng.submit_order(_req(Side.SELL, 51, 4, 303))
    trades = eng.submit_order(_req(Side.BUY, 52, 10))  # fills 7, 3 rests
    total_traded = sum(t.quantity for t in trades)
    resting = eng.snapshot()["bids"][0]["quantity"]
    assert total_traded == 7
    assert total_traded + resting == 10


def test_partial_fill_multiple_resting_remainder_rests() -> None:
    # buy 12 @ 52: fills 5@50 + 5@51 = 10, 2 rests as bid
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 5, 202))
    eng.submit_order(_req(Side.SELL, 51, 5, 303))
    trades = eng.submit_order(_req(Side.BUY, 52, 12))
    assert len(trades) == 2
    assert sum(t.quantity for t in trades) == 10


def test_fully_consumed_across_multiple_resting() -> None:
    # buy 8 @ 52: fills 5@50 + 3@51 = 8 exactly, no bid rests
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 5, 202))
    eng.submit_order(_req(Side.SELL, 51, 5, 303))
    trades = eng.submit_order(_req(Side.BUY, 52, 8))
    assert sum(t.quantity for t in trades) == 8


def test_partially_filled_resting_keeps_priority() -> None:
    # order-1: sell 10@50, order-2: sell 5@50.
    # buy 3 fills 3 from order-1. Next buy 5 still fills from order-1's remaining 7.
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 10, 202))  # order-1
    eng.submit_order(_req(Side.SELL, 50, 5, 303))   # order-2
    trades1 = eng.submit_order(_req(Side.BUY, 50, 3))
    assert trades1[0].sell_order_id == "order-1"
    trades2 = eng.submit_order(_req(Side.BUY, 50, 5))
    assert trades2[0].sell_order_id == "order-1"  # order-1 still heads the queue


def test_better_price_beats_earlier_time() -> None:
    # order-1: sell@52 arrives first. order-2: sell@50 arrives second.
    # buy@52 fills order-2 (better ask price) before order-1.
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 52, 5, 202))  # order-1, worse price
    eng.submit_order(_req(Side.SELL, 50, 5, 303))  # order-2, better price
    trades = eng.submit_order(_req(Side.BUY, 52, 5))
    assert len(trades) == 1
    assert trades[0].sell_order_id == "order-2"
    assert trades[0].price == 50


def test_fifo_after_cancellation() -> None:
    # cancel first resting order; next buy fills the second (now head of queue)
    eng = MatchingEngine()
    eng.submit_order(_req(Side.SELL, 50, 5, 202))   # order-1
    eng.submit_order(_req(Side.SELL, 50, 5, 303))   # order-2
    eng.cancel_order("order-1", 202)
    trades = eng.submit_order(_req(Side.BUY, 50, 5))
    assert len(trades) == 1
    assert trades[0].sell_order_id == "order-2"


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
    test_sell_aggressor_full_fill()
    test_cancel_removes_resting_order()
    test_cancel_nonexistent_returns_none()
    test_cancel_already_filled_returns_none()
    test_snapshot_reflects_state()
    test_self_trade_no_crossed_book()
    test_self_trade_buy_crossing_own_ask()
    test_self_trade_sell_crossing_own_bid()
    test_self_trade_partial_fill_then_skip_rest()
    test_cancel_wrong_owner()
    test_owner_id_validation()
    test_duplicate_order_id_rejected()
    test_cancel_returns_remaining_at_cancel_time()
    test_fill_accounting_invariant()
    test_partial_fill_multiple_resting_remainder_rests()
    test_fully_consumed_across_multiple_resting()
    test_partially_filled_resting_keeps_priority()
    test_better_price_beats_earlier_time()
    test_fifo_after_cancellation()
    print("all ok")
