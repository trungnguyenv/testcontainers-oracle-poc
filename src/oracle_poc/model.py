"""The domain the repositories read and write."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Customer:
    """A person or organization that places orders."""

    id: int
    name: str
    email: str | None


@dataclass(frozen=True)
class Order:
    """A purchase placed by a customer."""

    id: int
    customer_id: int
    amount: Decimal
    placed_at: datetime


@dataclass(frozen=True)
class OrderWithCustomer:
    """An order joined to the name of the customer who placed it."""

    order_id: int
    customer_name: str
    amount: Decimal
