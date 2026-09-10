"""Data-access code exercised against a real Oracle database."""

from oracle_poc.db import connect
from oracle_poc.model import Customer, Order, OrderWithCustomer
from oracle_poc.repository import CustomerRepository, OrderRepository
from oracle_poc.tables import TableSet

__all__ = [
    "Customer",
    "CustomerRepository",
    "Order",
    "OrderRepository",
    "OrderWithCustomer",
    "TableSet",
    "connect",
]
