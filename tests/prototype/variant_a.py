"""PROTOTYPE — variant A: one fixture, everything inline.

Throwaway. See tests/prototype/README.md and issue #6.

The bet: the fixture is small enough that splitting it costs more than it buys. Container config,
readiness and the SYS bootstrap all live in `oracle_dsn`, which stays the single thing a test
depends on. Read it top to bottom and judge whether it is still readable at this size.
"""

import os
import sys
import time
from collections.abc import Iterator

import oracledb
import pytest
from testcontainers.core.container import DockerContainer

# Pinned by digest: the tag is not immutable and this is the exact build measured in #3
# (Oracle 19c Enterprise 19.19.0.0.0, arm64 native, 2.86 GB).
IMAGE = (
    "codeassertion/oracledb-arm64-standalone@sha256:"
    "6a5e663cdc494e3086f455d7a8b4c6bcf284214e6f10f973a6b2b89e04230e4c"
)

ORACLE_PORT = 1521
SYS_PASSWORD = "oracle"
CDB_NAME = "ORCLCDB"
SERVICE_NAME = "ORCLPDB1"

APP_USER = "app"
APP_PASSWORD = "app"

# Cold boot is DBCA building the database from scratch: 316s clean, 412s alongside a second
# Oracle container (#3). testcontainers' default is 120s, which would fire every single time.
BOOT_TIMEOUT = 600

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
    bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{ORACLE_PORT}/tcp")
    return int(bindings[0]["HostPort"]) if bindings else None


def _default_tablespace(connection: oracledb.Connection) -> str | None:
    """The PDB's default permanent tablespace, if it exists and is online yet."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT t.tablespace_name
              FROM database_properties p
              JOIN dba_tablespaces t ON t.tablespace_name = p.property_value
             WHERE p.property_name = 'DEFAULT_PERMANENT_TABLESPACE'
               AND t.status = 'ONLINE'
        """)
        row = cursor.fetchone()
    return row[0] if row else None


def _wait_until_usable(dsn: str, timeout: int = BOOT_TIMEOUT) -> None:
    """Block until the PDB can hold a table.

    Not a log predicate: `DATABASE IS READY TO USE!` is in `docker logs` from the *previous* run of
    a reused container, so matching it returns instantly while the database is still mounting (#3).

    And not merely "SYS can connect" either: measured here, the ready line lands at 09:32:40.311
    and the PDB's `ALTER DATABASE DEFAULT TABLESPACE "USERS"` lands four milliseconds later, so a
    bootstrap that starts the instant SYS accepts it dies on ORA-00959.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            connection = oracledb.connect(
                user="SYS", password=SYS_PASSWORD, dsn=dsn, mode=oracledb.AUTH_MODE_SYSDBA
            )
            try:
                if _default_tablespace(connection) is not None:
                    return
            finally:
                connection.close()
        except oracledb.Error as error:
            last_error = error
        time.sleep(2)
    raise TimeoutError(f"Oracle at {dsn} was not usable within {timeout}s") from last_error


def _bootstrap_app_user(dsn: str) -> None:
    """Create the app user inside the PDB, as SYS.

    The 23ai image did this from `APP_USER`/`APP_USER_PASSWORD`; this image ignores those, so the
    work becomes ours. Idempotent because in reuse mode the user is already there.

    The quota is the part that is easy to miss and fatal: without it every `CREATE TABLE` in the
    suite fails with ORA-01950, which #4 named as the migration's real risk.
    """
    with (
        oracledb.connect(
            user="SYS", password=SYS_PASSWORD, dsn=dsn, mode=oracledb.AUTH_MODE_SYSDBA
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT COUNT(*) FROM dba_users WHERE username = :name", name=APP_USER.upper()
        )
        (exists,) = cursor.fetchone()
        if not exists:
            cursor.execute(f'CREATE USER {APP_USER} IDENTIFIED BY "{APP_PASSWORD}"')
        cursor.execute(f"GRANT CREATE SESSION, CREATE TABLE TO {APP_USER}")
        cursor.execute(f"ALTER USER {APP_USER} QUOTA UNLIMITED ON USERS")


@pytest.fixture(scope="session")
def oracle_dsn() -> Iterator[str]:
    """A DSN pointing at a PDB with the app user already created."""
    if _reuse_requested():
        port = _already_running_port()
        if port is not None:
            dsn = _dsn("localhost", port)
            _wait_until_usable(dsn)
            _bootstrap_app_user(dsn)
            yield dsn
            return

    container = (
        DockerContainer(IMAGE)
        .with_env("ORACLE_PWD", SYS_PASSWORD)
        .with_env("ORACLE_SID", CDB_NAME)
        .with_env("ORACLE_PDB", SERVICE_NAME)
        .with_exposed_ports(ORACLE_PORT)
    )
    # No --shm-size. DBCA configures ASMM, so the SGA is a SysV segment, not /dev/shm; a container
    # booted at Docker's default 64 MB /dev/shm left it 0% used (#3). What does bind is ~3.2 GB of
    # container memory.

    if _reuse_requested():
        container.with_name(REUSED_CONTAINER_NAME)

    container.start()
    try:
        dsn = _dsn(container.get_container_host_ip(), container.get_exposed_port(ORACLE_PORT))
        _wait_until_usable(dsn)
        _bootstrap_app_user(dsn)
        yield dsn
    finally:
        if not _reuse_requested():
            container.stop()


# --- runnable outside pytest, so the shape can be felt without the suite -------------------------


def main() -> None:
    """Walk the same steps the fixture walks, printing the state reached at each one."""
    keep = "--keep" in sys.argv
    if keep:
        os.environ[REUSE_FLAG] = "1"

    print(f"variant A | reuse={_reuse_requested()}")
    started = time.monotonic()

    container = None
    port = _already_running_port() if _reuse_requested() else None
    if port is not None:
        dsn = _dsn("localhost", port)
        print(f"  attached to         {REUSED_CONTAINER_NAME}")
    else:
        container = (
            DockerContainer(IMAGE)
            .with_env("ORACLE_PWD", SYS_PASSWORD)
            .with_env("ORACLE_SID", CDB_NAME)
            .with_env("ORACLE_PDB", SERVICE_NAME)
            .with_exposed_ports(ORACLE_PORT)
        )
        if _reuse_requested():
            container.with_name(REUSED_CONTAINER_NAME)
        container.start()
        dsn = _dsn(container.get_container_host_ip(), container.get_exposed_port(ORACLE_PORT))
        print(f"  started             {container.get_wrapped_container().short_id}")

    print(f"  dsn                 {dsn}")
    _wait_until_usable(dsn)
    print(f"  usable after        {time.monotonic() - started:.1f}s")
    _bootstrap_app_user(dsn)
    print(f"  app user ready      {APP_USER}")

    try:
        with oracledb.connect(user=APP_USER, password=APP_PASSWORD, dsn=dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT user, sys_context('userenv', 'con_name'), "
                    "(SELECT banner FROM v$version WHERE ROWNUM = 1) FROM dual"
                )
                who, con_name, banner = cursor.fetchone()
            print(f"  connected as        {who} in {con_name}")
            print(f"  server              {banner}")
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE prototype_smoke_a (id NUMBER)")
                cursor.execute("DROP TABLE prototype_smoke_a PURGE")
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
