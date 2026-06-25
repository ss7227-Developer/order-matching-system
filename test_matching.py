from book import OrderBook
from engine import MatchingEngine
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


def test_sell_aggressor_full_fill() -> None:
    # resting BUY@50, incoming SELL@50 → one trade, correct buy/sell ids
    eng = MatchingEngine()
    eng.submit_order(OrderRequest(side=Side.BUY, price=50, quantity=10, owner="alice"))   # order-1
    trades = eng.submit_order(OrderRequest(side=Side.SELL, price=50, quantity=10, owner="bob"))
    assert len(trades) == 1
    assert trades[0].price == 50
    assert trades[0].quantity == 10
    assert trades[0].buy_order_id == "order-1"
    assert trades[0].sell_order_id == "order-2"
    assert eng._book.best_bid() is None
    assert eng._book.best_ask() is None


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
    print("all ok")
