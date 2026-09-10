"""Integration tests for the repositories.

Each test here fails to fail against a mock or a substitute engine: every assertion depends on
behavior that only a real Oracle database exhibits.
"""

from datetime import datetime
from decimal import Decimal

import oracledb
import pytest

from oracle_poc import CustomerRepository, OrderRepository, TableSet


@pytest.fixture
def customers(connection: oracledb.Connection, tables: TableSet) -> CustomerRepository:
    return CustomerRepository(connection, tables)


@pytest.fixture
def orders(connection: oracledb.Connection, tables: TableSet) -> OrderRepository:
    return OrderRepository(connection, tables)


def test_money_round_trips_as_decimal_not_float(
    customers: CustomerRepository, orders: OrderRepository
) -> None:
    """NUMBER(10,2) comes back as an exact Decimal.

    A mock returning ``19.99`` as a float would pass a test like this while quietly costing money
    in production: 0.1 + 0.2 != 0.3 in binary floating point, but it is exact in Oracle's NUMBER.
    """
    customer_id = customers.add("Ada Lovelace")
    order_id = orders.add(customer_id, Decimal("0.10"), datetime(2026, 1, 1, 12, 0))
    other_id = orders.add(customer_id, Decimal("0.20"), datetime(2026, 1, 1, 12, 0))

    first = orders.get(order_id)
    second = orders.get(other_id)

    assert isinstance(first.amount, Decimal)
    assert first.amount + second.amount == Decimal("0.30")


def test_order_for_unknown_customer_violates_the_foreign_key(orders: OrderRepository) -> None:
    """The database refuses an orphaned order; the application never has to check first."""
    with pytest.raises(oracledb.IntegrityError) as caught:
        orders.add(999_999, Decimal("10.00"), datetime(2026, 1, 1, 12, 0))

    assert "ORA-02291" in str(caught.value)  # integrity constraint - parent key not found


def test_generated_ids_ascend(customers: CustomerRepository) -> None:
    """Identity columns hand out increasing ids without the application choosing them."""
    first = customers.add("Grace Hopper")
    second = customers.add("Alan Turing")

    assert second > first


def test_join_returns_each_order_with_its_customer(
    customers: CustomerRepository, orders: OrderRepository
) -> None:
    ada = customers.add("Ada Lovelace")
    grace = customers.add("Grace Hopper")
    orders.add(ada, Decimal("12.50"), datetime(2026, 1, 1, 9, 0))
    orders.add(grace, Decimal("99.00"), datetime(2026, 1, 2, 9, 0))

    listed = orders.list_with_customer_name()

    assert [(row.customer_name, row.amount) for row in listed] == [
        ("Ada Lovelace", Decimal("12.50")),
        ("Grace Hopper", Decimal("99.00")),
    ]


def test_oversized_name_is_rejected_not_truncated(customers: CustomerRepository) -> None:
    """VARCHAR2(50) raises rather than silently storing a shortened name.

    This is the assertion most worth having: a fake store backed by a dict has no length at all,
    and some engines truncate quietly.
    """
    with pytest.raises(oracledb.DatabaseError) as caught:
        customers.add("A" * 51)

    assert "ORA-12899" in str(caught.value)  # value too large for column


def test_timestamp_round_trips_with_sub_second_precision(
    customers: CustomerRepository, orders: OrderRepository
) -> None:
    """TIMESTAMP keeps microseconds, where Oracle's older DATE type would drop them."""
    placed_at = datetime(2026, 3, 14, 15, 9, 26, 535000)
    customer_id = customers.add("Ada Lovelace")

    order_id = orders.add(customer_id, Decimal("1.00"), placed_at)

    assert orders.get(order_id).placed_at == placed_at


def test_missing_rows_are_absent_not_errors(orders: OrderRepository) -> None:
    assert orders.get(999_999) is None
