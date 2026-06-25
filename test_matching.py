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
