from __future__ import annotations

from collections import deque

from order import Order, Side


class OrderBook:
    def __init__(self) -> None:
        self._bids: dict[int, deque[Order]] = {}
        self._asks: dict[int, deque[Order]] = {}
        self._index: dict[str, Order] = {}

    def _side_book(self, side: Side) -> dict[int, deque[Order]]:
        return self._bids if side == Side.BUY else self._asks

    def add(self, order: Order) -> None:
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

    def best_bid(self) -> int | None:
        return max(self._bids) if self._bids else None

    def best_ask(self) -> int | None:
        return min(self._asks) if self._asks else None

    def level(self, side: Side, price: int) -> deque[Order]:
        return self._side_book(side).get(price, deque())

    def prices(self, side: Side) -> list[int]:
        return sorted(self._side_book(side), reverse=(side == Side.BUY))

    def snapshot(self) -> dict[str, list[dict[str, int]]]:
        def aggregate(book: dict[int, deque[Order]], reverse: bool) -> list[dict[str, int]]:
            levels = []
            for price in sorted(book, reverse=reverse):
                qty = sum(o.remaining for o in book[price])
                if qty:
                    levels.append({"price": price, "quantity": qty})
            return levels

        return {
            "bids": aggregate(self._bids, reverse=True),
            "asks": aggregate(self._asks, reverse=False),
        }


if __name__ == "__main__":
    from order import Order, Side

    def make(order_id: str, side: Side, price: int, qty: int) -> Order:
        return Order.create(
            side=side, price=price, quantity=qty, owner="t",
            order_id=order_id, sequence_number=int(order_id),
        )

    book = OrderBook()
    b1 = make("1", Side.BUY, 50, 10)
    b2 = make("2", Side.BUY, 50, 5)
    a1 = make("3", Side.SELL, 55, 8)

    book.add(b1); book.add(b2); book.add(a1)

    assert book.best_bid() == 50
    assert book.best_ask() == 55
    assert list(book.level(Side.BUY, 50)) == [b1, b2]

    snap = book.snapshot()
    assert snap["bids"] == [{"price": 50, "quantity": 15}]
    assert snap["asks"] == [{"price": 55, "quantity": 8}]

    cancelled = book.cancel("2")
    assert cancelled is b2
    assert book.cancel("2") is None
    assert book.level(Side.BUY, 50) == deque([b1])

    book.remove(b1)
    assert book.best_bid() is None

    print("ok")
