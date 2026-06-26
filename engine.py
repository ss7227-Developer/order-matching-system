import threading

from book import OrderBook
from order import CancelledOrder, Order, OrderRequest, Side, Trade, SubmitResult


class MatchingEngine:
    def __init__(self) -> None:
        self._next_seq = 0
        self._book = OrderBook()
        self._lock = threading.RLock()
        # ponytail: unbounded cache; production would evict entries older than ~24 h or use an LRU
        self._submit_cache: dict[str, SubmitResult] = {}
        self._resolved: bool = False
        self._outcome: str | None = None

    def submit_order(self, request: OrderRequest) -> SubmitResult:
        with self._lock:
            if self._resolved:
                raise RuntimeError(f"market already resolved: {self._outcome}")
            cached = self._submit_cache.get(request.client_order_id)
            if cached is not None:
                return cached
            order = self._create_order(request)
            trades = self._match(order)
            if order.remaining > 0:
                self._book.add(order)
            bids = self._book.prices(Side.BUY)
            asks = self._book.prices(Side.SELL)
            if bids and asks and bids[0] >= asks[0]:
                raise RuntimeError(f"book crossed: best bid {bids[0]} >= best ask {asks[0]}")
            result = SubmitResult(
                order_id=order.order_id,
                trades=trades,
                remaining=order.remaining,
            )
            self._submit_cache[request.client_order_id] = result
            return result

    def cancel_order(self, order_id: str, owner_id: int) -> CancelledOrder | None:
        with self._lock:
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

    def resolve_market(self, outcome: str) -> dict:
        with self._lock:
            all_orders = list(self._book._index.values())
            for order in all_orders:
                self._book.cancel(order.order_id)
            self._resolved = True
            self._outcome = outcome
            return {
                "outcome": outcome,
                "cancelled": len(all_orders),
                "book": self._book.snapshot(),
            }

    def snapshot(self) -> dict:
        with self._lock:
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
                    self._book.remove(resting)
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
