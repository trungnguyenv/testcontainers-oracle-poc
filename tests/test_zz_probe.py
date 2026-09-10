"""MEASUREMENT INSTRUMENT for issue #7 — not one of the seven assertions.

Captures the exact facts the ticket asks to compare across versions: the server banner, the
connected user and container, and the verbatim ``str(exception)`` for the two ORA codes the
suite asserts on by substring.
"""

import json
import os
from datetime import datetime
from decimal import Decimal

import oracledb
import pytest

from oracle_poc import CustomerRepository, OrderRepository, TableSet

OUT = os.environ.get("PROBE_OUT", "/tmp/probe.json")


def test_zz_probe(connection: oracledb.Connection, tables: TableSet) -> None:
    facts: dict[str, object] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT user, sys_context('userenv','con_name'), sys_context('userenv','db_name'), "
            "(SELECT banner FROM v$version WHERE ROWNUM = 1) FROM dual"
        )
        who, con_name, db_name, banner = cursor.fetchone()
    facts["user"] = who
    facts["con_name"] = con_name
    facts["db_name"] = db_name
    facts["banner"] = banner

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT value FROM v$parameter WHERE name = 'max_string_size'")
            row = cursor.fetchone()
        facts["max_string_size"] = row[0] if row else None
    except oracledb.DatabaseError as error:
        facts["max_string_size"] = f"unreadable as app user: {str(error).splitlines()[0]}"

    with connection.cursor() as cursor:
        cursor.execute("SELECT privilege FROM session_privs ORDER BY 1")
        facts["session_privs"] = [row[0] for row in cursor.fetchall()]

    customers = CustomerRepository(connection, tables)
    orders = OrderRepository(connection, tables)

    with pytest.raises(oracledb.IntegrityError) as fk:
        orders.add(999_999, Decimal("10.00"), datetime(2026, 1, 1, 12, 0))
    facts["ORA-02291_text"] = str(fk.value)

    with pytest.raises(oracledb.DatabaseError) as ov:
        customers.add("A" * 51)
    facts["ORA-12899_text"] = str(ov.value)

    facts["oracledb_version"] = oracledb.__version__
    facts["thin_mode"] = oracledb.is_thin_mode()

    with open(OUT, "w") as handle:
        json.dump(facts, handle, indent=2)
    print("\n" + json.dumps(facts, indent=2))
