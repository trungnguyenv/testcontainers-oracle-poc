"""Repositories over the customers and orders tables.

Each repository receives an open connection rather than opening its own, and is told which table
set to address. It owns its transactions and commits freely: isolation between tests comes from
each test having its own tables, not from withheld commits.
"""

from datetime import datetime
from decimal import Decimal

import oracledb

from oracle_poc.model import Customer, Order, OrderWithCustomer
from oracle_poc.tables import TableSet


class CustomerRepository:
    """Reads and writes customers."""

    def __init__(self, connection: oracledb.Connection, tables: TableSet) -> None:
        self._connection = connection
        self._table = tables.customers

    def add(self, name: str, email: str | None = None) -> int:
        """Insert a customer and return the id Oracle generated for it."""
        with self._connection.cursor() as cursor:
            new_id = cursor.var(int)
            cursor.execute(
                f"INSERT INTO {self._table} (name, email) VALUES (:name, :email) "
                "RETURNING id INTO :new_id",
                name=name,
                email=email,
                new_id=new_id,
            )
            self._connection.commit()
            return int(new_id.getvalue()[0])

    def get(self, customer_id: int) -> Customer | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id, name, email FROM {self._table} WHERE id = :id", id=customer_id
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return Customer(id=int(row[0]), name=row[1], email=row[2])


class OrderRepository:
    """Reads and writes orders, including the join back to the customer who placed them."""

    def __init__(self, connection: oracledb.Connection, tables: TableSet) -> None:
        self._connection = connection
        self._table = tables.orders
        self._customers_table = tables.customers

    def add(self, customer_id: int, amount: Decimal, placed_at: datetime) -> int:
        """Insert an order and return its generated id.

        Raises ``oracledb.IntegrityError`` if no such customer exists.
        """
        with self._connection.cursor() as cursor:
            new_id = cursor.var(int)
            # Without this, python-oracledb binds a datetime as Oracle's DATE type, which has
            # no fractional seconds, and the sub-second part is silently discarded on the way in.
            cursor.setinputsizes(placed_at=oracledb.DB_TYPE_TIMESTAMP)
            cursor.execute(
                f"INSERT INTO {self._table} (customer_id, amount, placed_at) "
                "VALUES (:customer_id, :amount, :placed_at) RETURNING id INTO :new_id",
                customer_id=customer_id,
                amount=amount,
                placed_at=placed_at,
                new_id=new_id,
            )
            self._connection.commit()
            return int(new_id.getvalue()[0])

    def get(self, order_id: int) -> Order | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id, customer_id, amount, placed_at FROM {self._table} WHERE id = :id",
                id=order_id,
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return Order(id=int(row[0]), customer_id=int(row[1]), amount=row[2], placed_at=row[3])

    def list_with_customer_name(self) -> list[OrderWithCustomer]:
        """Every order, with the name of the customer who placed it, oldest order first."""
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT o.id, c.name, o.amount
                  FROM {self._table} o
                  JOIN {self._customers_table} c ON c.id = o.customer_id
                 ORDER BY o.id
            """)
            rows = cursor.fetchall()
        return [
            OrderWithCustomer(order_id=int(row[0]), customer_name=row[1], amount=row[2])
            for row in rows
        ]
