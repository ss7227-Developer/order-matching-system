from book import OrderBook
from order import CancelledOrder, Order, OrderRequest, Side, Trade, SubmitResult



class MatchingEngine:
    def __init__(self) -> None:
        self._next_seq = 0
        self._book = OrderBook()

    def submit_order(self, request: OrderRequest) -> SubmitResult:
        order = self._create_order(request)
        trades = self._match(order)
        if order.remaining > 0:
            self._book.add(order)
        return SubmitResult(
            order_id=order.order_id,
            trades=trades,
            remaining=order.remaining,
        )

    def cancel_order(self, order_id: str, owner_id: int) -> CancelledOrder | None:
        order = self._book.get(order_id)
        if order is None or order.owner_id != owner_id:
            return None
        self._book.cancel(order_id)
        return CancelledOrder(
            order_id=order.order_id,
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            remaining=order.remaining,
            owner_id=order.owner_id,
            sequence_number=order.sequence_number,
        )

    def snapshot(self) -> dict:
        return self._book.snapshot()

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
            for resting in list(self._book._level(opposite, price)):
                if incoming.remaining == 0:
                    break
                if resting.owner_id == incoming.owner_id:
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
            owner_id=request.owner_id,
            sequence_number=seq,
            order_id=f"order-{seq}",
        )
