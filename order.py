from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    side: Side
    price: int = Field(ge=1, le=99)  # tick range: 1–99 for this binary-outcome instrument
    quantity: int = Field(gt=0)
    owner: str


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    buy_order_id: str
    sell_order_id: str
    price: int = Field(ge=1)
    quantity: int = Field(gt=0)


class Order(BaseModel):
    model_config = ConfigDict(frozen=False)

    # Client-supplied — frozen after creation
    side: Side
    price: int = Field(ge=1, le=99)  # tick range: 1–99 for this binary-outcome instrument
    quantity: int = Field(gt=0)
    owner: str

    # Engine-assigned — frozen after creation
    order_id: str
    sequence_number: int

    # The only field that changes after creation
    remaining: int = Field(ge=0)

    # Note: runtime guard only — mypy won't catch order.price = 50 at type-check time
    _FROZEN: ClassVar[frozenset[str]] = frozenset(
        {"side", "price", "quantity", "owner", "order_id", "sequence_number"}
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._FROZEN:
            raise AttributeError(f"'{name}' is frozen after creation")
        if name == "remaining":
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"remaining must be >= 0, got {value!r}")
            if value > self.quantity:
                raise ValueError(f"remaining ({value}) cannot exceed quantity ({self.quantity})")
        super().__setattr__(name, value)

    @classmethod
    def create(
        cls,
        *,
        side: Side,
        price: int,
        quantity: int,
        owner: str,
        order_id: str,
        sequence_number: int,
    ) -> Order:
        return cls(
            side=side,
            price=price,
            quantity=quantity,
            owner=owner,
            order_id=order_id,
            sequence_number=sequence_number,
            remaining=quantity,
        )


if __name__ == "__main__":
    o = Order.create(
        side=Side.BUY, price=50, quantity=100, owner="alice", order_id="x1", sequence_number=1
    )
    assert o.remaining == o.quantity == 100
    o.remaining = 75
    assert o.remaining == 75

    for frozen_field in ("side", "price", "quantity", "owner", "order_id", "sequence_number"):
        try:
            setattr(o, frozen_field, None)
            raise AssertionError(f"{frozen_field} should have raised")
        except AttributeError:
            pass

    try:
        o.remaining = -1
        raise AssertionError("negative remaining should have raised")
    except ValueError:
        pass

    try:
        o.remaining = 101
        raise AssertionError("remaining > quantity should have raised")
    except ValueError:
        pass

    print("ok")
