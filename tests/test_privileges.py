"""One test per privilege the seven never exercise.

``PRIVILEGE_SURFACE`` holds nine privileges, chosen for the object types a data-access layer works
with rather than the three ``test_orders.py`` happens to need (ADR 0003). Six of them —
CREATE VIEW, CREATE PROCEDURE, CREATE TRIGGER, CREATE TYPE, CREATE SYNONYM and
CREATE MATERIALIZED VIEW — had nothing standing behind them at all. Each test here creates one
object of its type in the app user's schema and drops it again.

These assert **sufficiency**: that the grant we made is enough to do the thing it was granted
for. They cannot catch a privilege we failed to grant — that is exactly the CREATE SEQUENCE
surprise (#7), and nothing in this file would have caught it. Sufficiency is the other half of
that surprise, and it is not documented-obvious: an identity column needs CREATE SEQUENCE, and a
materialized view builds a real table underneath itself. A grant that turns out to be
insufficient fails here on a test named after it, which ``ORA-01031: insufficient privileges``
declines to do.

Deliberately not in ``test_orders.py``, whose assertions are all about the domain under test.
The seven stay seven.

If a test here fails, the fix is to widen ``PRIVILEGE_SURFACE`` and record the addition in
ADR 0003. That is the test paying for itself, not a defect.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import oracledb

from oracle_poc import TableSet


def suffix_of(tables: TableSet) -> str:
    """The table set's own suffix, so dependents cannot be named for a different one.

    Every identifier this module interpolates is derived from here, which keeps ADR 0001's rule
    — runtime identifiers are generated, never user-supplied — true of this file too.
    """
    return tables.customers.removeprefix("customers_")


@contextmanager
def created(connection: oracledb.Connection, ddl: str, drop: str) -> Iterator[None]:
    """Create an object for the body of a test, and drop it however the test ends.

    Teardown here is not symmetric with the seven, which let the ``tables`` fixture clean up after
    them. A trigger does die with its table, but a materialized view is its own segment and
    survives the base table's ``DROP ... PURGE``, while a view and a synonym go *invalid* rather
    than away. The app user is reset once per session (ADR 0002), not once per test, so anything
    left behind here outlives the test that made it. Nesting these gives reverse-order teardown.
    """
    with connection.cursor() as cursor:
        cursor.execute(ddl)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(drop)


def object_status(connection: oracledb.Connection, name: str, object_type: str) -> str | None:
    """The data dictionary's view of one object the app user owns, or None if there is none.

    Worth asserting rather than taking a silent ``execute`` as proof: Oracle accepts
    ``CREATE PROCEDURE`` and ``CREATE TRIGGER`` even when the body fails to compile, leaving the
    object INVALID and the error to be fetched separately. A test that only checked the statement
    did not raise would pass on a broken body.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM user_objects WHERE object_name = :name AND object_type = :type",
            name=name.upper(),
            type=object_type,
        )
        row = cursor.fetchone()
    return row[0] if row else None


def test_create_view(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE VIEW is enough to put a view over a table the app user owns."""
    view = f"v_customers_{suffix_of(tables)}"

    with created(
        connection,
        f"CREATE VIEW {view} AS SELECT id, name FROM {tables.customers}",
        f"DROP VIEW {view}",
    ):
        assert object_status(connection, view, "VIEW") == "VALID"


def test_create_procedure(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE PROCEDURE is enough to compile a standalone procedure.

    The privilege is three object types wide — procedures, functions and packages all depend on
    it — so this exercises one of the three. Per-privilege, not per-object-type: the two are
    different enumerations, and the privilege is what is being defended.
    """
    procedure = f"p_touch_{suffix_of(tables)}"

    with created(
        connection,
        f"CREATE PROCEDURE {procedure} AS BEGIN NULL; END;",
        f"DROP PROCEDURE {procedure}",
    ):
        assert object_status(connection, procedure, "PROCEDURE") == "VALID"


def test_create_trigger(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE TRIGGER is enough to compile a row-level trigger on an owned table."""
    trigger = f"trg_customers_{suffix_of(tables)}"

    with created(
        connection,
        f"""
            CREATE TRIGGER {trigger}
                BEFORE INSERT ON {tables.customers}
                FOR EACH ROW
            BEGIN
                NULL;
            END;
        """,
        f"DROP TRIGGER {trigger}",
    ):
        assert object_status(connection, trigger, "TRIGGER") == "VALID"


def test_create_type(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE TYPE is enough to compile a standalone object type."""
    type_name = f"t_customer_{suffix_of(tables)}"

    with created(
        connection,
        f"CREATE TYPE {type_name} AS OBJECT (id NUMBER, name VARCHAR2(50))",
        f"DROP TYPE {type_name}",
    ):
        assert object_status(connection, type_name, "TYPE") == "VALID"


def test_create_synonym(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE SYNONYM is enough for a private synonym; nothing here needs PUBLIC."""
    synonym = f"syn_customers_{suffix_of(tables)}"

    with created(
        connection,
        f"CREATE SYNONYM {synonym} FOR {tables.customers}",
        f"DROP SYNONYM {synonym}",
    ):
        assert object_status(connection, synonym, "SYNONYM") == "VALID"


def test_create_materialized_view(connection: oracledb.Connection, tables: TableSet) -> None:
    """CREATE MATERIALIZED VIEW, together with CREATE TABLE, is enough to build one.

    This measures the pair, not the one privilege: a materialized view builds a real table
    underneath itself, asserted below because it is the reason the pair is what matters. Teasing
    the two apart would mean revoking a grant mid-session, which is out of scope — the app user
    holds both, and both are on the list.
    """
    view = f"mv_customers_{suffix_of(tables)}"

    with created(
        connection,
        f"""
            CREATE MATERIALIZED VIEW {view}
                BUILD IMMEDIATE
                REFRESH COMPLETE ON DEMAND
                AS SELECT id, name FROM {tables.customers}
        """,
        f"DROP MATERIALIZED VIEW {view}",
    ):
        assert object_status(connection, view, "MATERIALIZED VIEW") == "VALID"
        assert object_status(connection, view, "TABLE") == "VALID"
