"""Fixtures for the integration tests.

The database is expensive to start, so one container serves the whole session. Isolation between
tests comes from each test owning a freshly-named table set, not from the container.

Set ``ORACLE_POC_REUSE=1`` to leave the container running after the session, so the next run
attaches to it instead of paying for startup again. Reuse is off by default, and the tests behave
identically either way.
"""

import os
from collections.abc import Iterator

import oracledb
import pytest
from testcontainers.community.oracle import OracleDbContainer

from oracle_poc.db import connect
from oracle_poc.tables import TableSet, create, drop

IMAGE = "gvenzl/oracle-free:23-slim-faststart"
"""Oracle 23ai Free. The faststart variant boots from a pre-built database, and unlike
gvenzl/oracle-xe it publishes native arm64 images."""

APP_USER = "app"
APP_PASSWORD = "app"
SERVICE_NAME = "FREEPDB1"

REUSE_FLAG = "ORACLE_POC_REUSE"
REUSED_CONTAINER_NAME = "oracle-poc-reused"


def _reuse_requested() -> bool:
    return os.environ.get(REUSE_FLAG, "").lower() in ("1", "true", "yes")


def _dsn(host: str, port: int) -> str:
    return f"{host}:{port}/{SERVICE_NAME}"


def _already_running_port() -> int | None:
    """The published Oracle port of a previously reused container, if one is still up."""
    from docker.errors import NotFound
    from testcontainers.core.docker_client import DockerClient

    try:
        container = DockerClient().client.containers.get(REUSED_CONTAINER_NAME)
    except NotFound:
        return None
    if container.status != "running":
        container.remove(force=True)
        return None
    bindings = container.attrs["NetworkSettings"]["Ports"].get("1521/tcp")
    return int(bindings[0]["HostPort"]) if bindings else None


@pytest.fixture(scope="session")
def oracle_dsn() -> Iterator[str]:
    """A DSN pointing at an Oracle database that is up and accepting connections."""
    if _reuse_requested():
        port = _already_running_port()
        if port is not None:
            yield _dsn("localhost", port)
            return

    container = OracleDbContainer(
        image=IMAGE,
        username=APP_USER,
        password=APP_PASSWORD,
        dbname=SERVICE_NAME,
    )

    if _reuse_requested():
        container.with_name(REUSED_CONTAINER_NAME)
        container.start()
        yield _dsn(container.get_container_host_ip(), container.get_exposed_port(1521))
        return  # deliberately left running for the next session

    with container:
        yield _dsn(container.get_container_host_ip(), container.get_exposed_port(1521))


@pytest.fixture
def connection(oracle_dsn: str) -> Iterator[oracledb.Connection]:
    """A connection as the app user, fresh per test so no session state leaks between tests."""
    conn = connect(user=APP_USER, password=APP_PASSWORD, dsn=oracle_dsn)
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
