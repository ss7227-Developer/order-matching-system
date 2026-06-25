import threading

from book import OrderBook
from order import Order, OrderRequest, Side, Trade


class MatchingEngine:
    def __init__(self) -> None:
        self._next_seq = 0
        self._book = OrderBook()
        # serializes submit/cancel/snapshot — prevents cancel-while-matching race
        self._lock = threading.Lock()

    def submit_order(self, request: OrderRequest) -> list[Trade]:
        with self._lock:
            order = self._create_order(request)
            trades, expired = self._match(order)
            if not expired and order.remaining > 0:
                self._book.add(order)
            return trades

    def cancel_order(self, order_id: str, owner: str) -> Order | None:
        with self._lock:
            order = self._book._index.get(order_id)
            if order is None or order.owner != owner:
                return None
            return self._book.cancel(order_id)

    def snapshot(self) -> dict:
        with self._lock:
            return self._book.snapshot()

    def _match(self, incoming: Order) -> tuple[list[Trade], bool]:
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
                    return trades, True  # self-trade: expire remainder, keep prior fills
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

        return trades, False

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
