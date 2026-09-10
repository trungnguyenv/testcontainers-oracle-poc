"""PROTOTYPE — variant B: three fixtures over a named module.

Throwaway. See tests/prototype/README.md and issue #6.

Compare against `variant_a.py`. The container work has moved to `oracle_container_b.py`, so what
is left here is only the pytest lifecycle: what is session-scoped, what is per-test, what a test
is allowed to ask for.

Chosen shape (#6): this seam, with SYSDBA opened and closed inside `app_user` rather than held
open for the session, so no privileged connection is reachable from a test.
"""

import os
import sys
import time
from collections.abc import Iterator

import oracledb
import pytest
from tests.prototype import oracle_container_b as oracle

from oracle_poc.db import connect

REUSE_FLAG = "ORACLE_POC_REUSE"
REUSED_CONTAINER_NAME = "oracle-poc-reused"


def _reuse_requested() -> bool:
    return os.environ.get(REUSE_FLAG, "").lower() in ("1", "true", "yes")


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
    bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{oracle.ORACLE_PORT}/tcp")
    return int(bindings[0]["HostPort"]) if bindings else None


@pytest.fixture(scope="session")
def oracle_dsn() -> Iterator[str]:
    """A DSN for the PDB, on a database that is up and accepting connections.

    Says nothing about users: `sys_connection` and `app_connection` are what turn a live database
    into one this suite can use.
    """
    if _reuse_requested():
        port = _already_running_port()
        if port is not None:
            yield oracle.dsn("localhost", port)
            return

    container = oracle.oracle_container(name=REUSED_CONTAINER_NAME if _reuse_requested() else None)
    container.start()  # returns only once SYS can connect
    try:
        yield oracle.dsn(
            container.get_container_host_ip(), container.get_exposed_port(oracle.ORACLE_PORT)
        )
    finally:
        if not _reuse_requested():
            container.stop()


@pytest.fixture(scope="session")
def app_user(oracle_dsn: str) -> str:
    """Create the app user, once, before any test connects as it.

    SYSDBA lives for the length of this call and no longer: it is opened, used, and closed here,
    so no test can reach for it and no privileged connection sits open across the session. What
    is left behind is the user, which is all the suite actually needs.
    """
    connection = oracle.sys_connect(oracle_dsn)
    try:
        oracle.create_app_user(connection)
    finally:
        connection.close()
    return oracle.APP_USER


@pytest.fixture
def connection(oracle_dsn: str, app_user: str) -> Iterator[oracledb.Connection]:
    """A connection as the app user, fresh per test so no session state leaks between tests.

    Depending on `app_user` is how "the user must exist first" is said in pytest's vocabulary.
    """
    conn = connect(user=app_user, password=oracle.APP_PASSWORD, dsn=oracle_dsn)
    try:
        yield conn
    finally:
        conn.close()


# --- runnable outside pytest, so the shape can be felt without the suite -------------------------


def main() -> None:
    """Walk the same steps the fixtures walk, printing the state reached at each one."""
    keep = "--keep" in sys.argv
    if keep:
        os.environ[REUSE_FLAG] = "1"

    print(f"variant B | reuse={_reuse_requested()}")
    started = time.monotonic()

    container = None
    port = _already_running_port() if _reuse_requested() else None
    if port is not None:
        dsn = oracle.dsn("localhost", port)
        print(f"  attached to         {REUSED_CONTAINER_NAME}")
        print("  wait strategy       SKIPPED on the attach path (see #5)")
    else:
        container = oracle.oracle_container(
            name=REUSED_CONTAINER_NAME if _reuse_requested() else None
        )
        container.start()
        dsn = oracle.dsn(
            container.get_container_host_ip(), container.get_exposed_port(oracle.ORACLE_PORT)
        )
        print(f"  started             {container.get_wrapped_container().short_id}")

    print(f"  dsn                 {dsn}")
    if container is not None:
        print(f"  start() returned    {time.monotonic() - started:.1f}s (wait strategy ran)")

    sys_conn = oracle.sys_connect(dsn)
    try:
        oracle.create_app_user(sys_conn)
    finally:
        sys_conn.close()
    print(f"  app user ready      {oracle.APP_USER} (SYSDBA closed)")

    try:
        with connect(user=oracle.APP_USER, password=oracle.APP_PASSWORD, dsn=dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user, sys_context('userenv', 'con_name'), "
                    "(SELECT banner FROM v$version WHERE ROWNUM = 1) FROM dual"
                )
                who, con_name, banner = cursor.fetchone()
            print(f"  connected as        {who} in {con_name}")
            print(f"  server              {banner}")
            with conn.cursor() as cursor:
                cursor.execute("CREATE TABLE prototype_smoke_b (id NUMBER)")
                cursor.execute("DROP TABLE prototype_smoke_b PURGE")
            print("  CREATE TABLE        ok (no ORA-01950)")
    finally:
        if container is not None and not keep:
            container.stop()
            print("  stopped")
        elif keep:
            print(f"  left running as     {REUSED_CONTAINER_NAME} (next run ~12s)")

    print(f"  total               {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
