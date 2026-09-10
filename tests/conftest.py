"""Fixtures for the integration tests.

The database is expensive to start, so one container serves the whole session. Isolation between
tests comes from each test owning a freshly-named table set, not from the container.

The container is throwaway; the created database behind it is not. It lives in a named Docker
volume keyed to the image digest, so the several-minute first run is paid once per pin and every
run after starts in seconds. There is no flag: the volume is mounted unconditionally.
"""

from collections.abc import Iterator

import oracledb
import pytest

from oracle_poc.db import connect
from oracle_poc.tables import TableSet, create, drop
from tests import oracle_container as oracle


@pytest.fixture(scope="session")
def oracle_dsn() -> Iterator[str]:
    """A DSN for the PDB, on a database that is up and accepting connections.

    Says nothing about users: `app_user` is what turns a live database into one this suite can
    use.
    """
    container = oracle.oracle_container()
    container.start()  # returns only once the PDB can hold a table
    try:
        yield oracle.dsn(
            container.get_container_host_ip(), container.get_exposed_port(oracle.ORACLE_PORT)
        )
    finally:
        container.stop()


@pytest.fixture(scope="session")
def app_user(oracle_dsn: str) -> str:
    """Reset the app user, once, before any test connects as it.

    SYSDBA lives for the length of this call and no longer: opened, used and closed here, so no
    test can reach for it and no privileged connection sits open across the session.
    """
    connection = oracle.sys_connect(oracle_dsn)
    try:
        oracle.reset_app_user(connection)
    finally:
        connection.close()
    return oracle.APP_USER


@pytest.fixture
def connection(oracle_dsn: str, app_user: str) -> Iterator[oracledb.Connection]:
    """A connection as the app user, fresh per test so no session state leaks between tests."""
    conn = connect(user=app_user, password=oracle.APP_PASSWORD, dsn=oracle_dsn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tables(connection: oracledb.Connection) -> Iterator[TableSet]:
    """A table set owned by this test alone, dropped when it finishes."""
    table_set = TableSet.generate()
    create(connection, table_set)
    try:
        yield table_set
    finally:
        drop(connection, table_set)
