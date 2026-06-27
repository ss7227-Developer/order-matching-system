from __future__ import annotations

from collections import deque

from order import Order, Side


# Price levels: dict[int, deque[Order]] — lookup by price is O(1), prices sorted on demand O(P log P).
# Cancel via _index is O(1) lookup + O(N) deque removal (N = orders at that level).
# Acceptable for a toy engine; production would use a sorted container (e.g. SortedDict) and O(1)
# per-order removal via a doubly-linked structure or order-id-keyed dict.
class OrderBook:
    def __init__(self) -> None:
        self._bids: dict[int, deque[Order]] = {}
        self._asks: dict[int, deque[Order]] = {}
        self._index: dict[str, Order] = {}

    def _side_book(self, side: Side) -> dict[int, deque[Order]]:
        return self._bids if side == Side.BUY else self._asks

    def add(self, order: Order) -> None:
        if order.order_id in self._index:
            raise ValueError(f"duplicate order_id: {order.order_id!r}")
        book = self._side_book(order.side)
        if order.price not in book:
            book[order.price] = deque()
        book[order.price].append(order)
        self._index[order.order_id] = order

    def remove(self, order: Order) -> None:
        book = self._side_book(order.side)
        book[order.price].remove(order)
        if not book[order.price]:
            del book[order.price]
        self._index.pop(order.order_id, None)

    def cancel(self, order_id: str) -> Order | None:
        order = self._index.get(order_id)
        if order is None:
            return None
        self.remove(order)
        return order

    def get(self, order_id: str) -> Order | None:
        return self._index.get(order_id)

    def level(self, side: Side, price: int) -> deque[Order]:
        return self._side_book(side).get(price, deque())

    def all_orders(self) -> list[Order]:
        return list(self._index.values())

    def prices(self, side: Side) -> list[int]:
        return sorted(self._side_book(side), reverse=(side == Side.BUY))

    def snapshot(self) -> dict[str, list[dict]]:
        def expand(book: dict[int, deque[Order]], reverse: bool) -> list[dict]:
            entries = []
            for price in sorted(book, reverse=reverse):
                for o in book[price]:
                    if o.remaining:
                        entries.append({"order_id": o.order_id, "owner_id": o.owner_id, "price": o.price, "quantity": o.remaining})
            return entries

        return {
            "bids": expand(self._bids, reverse=True),
            "asks": expand(self._asks, reverse=False),
        }


if __name__ == "__main__":
    def make(order_id: str, side: Side, price: int, qty: int) -> Order:
        return Order.create(
            side=side, price=price, quantity=qty, owner_id=1,
            order_id=order_id, sequence_number=int(order_id),
        )

    book = OrderBook()
    b1 = make("1", Side.BUY, 50, 10)
    b2 = make("2", Side.BUY, 50, 5)
    a1 = make("3", Side.SELL, 55, 8)

    book.add(b1); book.add(b2); book.add(a1)

    assert list(book.level(Side.BUY, 50)) == [b1, b2]

    snap = book.snapshot()
    assert snap["bids"] == [
        {"order_id": "1", "owner_id": 1, "price": 50, "quantity": 10},
        {"order_id": "2", "owner_id": 1, "price": 50, "quantity": 5},
    ]
    assert snap["asks"] == [{"order_id": "3", "owner_id": 1, "price": 55, "quantity": 8}]

    cancelled = book.cancel("2")
    assert cancelled is b2
    assert book.cancel("2") is None
    assert book.level(Side.BUY, 50) == deque([b1])

    book.remove(b1)

    dup = make("99", Side.BUY, 50, 5)
    book2 = OrderBook()
    book2.add(dup)
    try:
        book2.add(dup)
        raise AssertionError("duplicate should have raised")
    except ValueError:
        pass

    print("ok")
