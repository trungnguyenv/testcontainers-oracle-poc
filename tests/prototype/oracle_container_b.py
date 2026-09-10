"""PROTOTYPE — variant B: the Oracle container, as a module the fixtures call.

Throwaway. See tests/prototype/README.md and issue #6.

The bet: "how this image is run" is a different concern from "what a test is handed", and naming
the seam makes both sides shallow. Nothing here knows about pytest; nothing in `variant_b.py`
knows about Docker or SYSDBA.
"""

import oracledb
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget

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


def dsn(host: str, port: int) -> str:
    """Where the tests connect: the PDB service, not the CDB root."""
    return f"{host}:{port}/{SERVICE_NAME}"


def sys_connect(dsn_: str) -> oracledb.Connection:
    """The privileged bootstrap connection. Thin mode, confirmed working against this image (#3)."""
    return oracledb.connect(
        user="SYS", password=SYS_PASSWORD, dsn=dsn_, mode=oracledb.AUTH_MODE_SYSDBA
    )


def default_tablespace(connection: oracledb.Connection) -> str | None:
    """The PDB's default permanent tablespace, if it exists and is online yet.

    Read rather than hardcoded. `USERS` is what this image ends up with, but it is created *late*
    (see `PdbUsableWaitStrategy`), and asking the database is both the readiness probe and the
    right way to name the tablespace for the quota.
    """
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


class PdbUsableWaitStrategy(WaitStrategy):
    """Ready means the PDB can hold a table, not merely that something answered on 1521.

    Two weaker predicates were tried and both are wrong for this image:

    1. **The log line.** `DATABASE IS READY TO USE!` is still in `docker logs` from the *previous*
       run of a reused container, so matching it returns instantly while the database is still
       mounting (#3).
    2. **SYS can connect.** Measured here: the ready line lands at 09:32:40.311 and the PDB's
       `CREATE SMALLFILE TABLESPACE "USERS"` / `ALTER DATABASE DEFAULT TABLESPACE "USERS"` land at
       09:32:40.315 — *four milliseconds later*. A bootstrap that connects the instant SYS accepts
       it races that window and dies on `ORA-00959: tablespace 'USERS' does not exist`.

    So the probe is the strongest cheap thing: SYS connects **and** the PDB has an online default
    permanent tablespace. That is exactly the precondition `create_app_user` needs, which is what
    makes it the honest place to stop waiting.
    """

    def wait_until_ready(self, container: WaitStrategyTarget) -> None:
        target = dsn(container.get_container_host_ip(), container.get_exposed_port(ORACLE_PORT))

        def usable() -> bool:
            connection = sys_connect(target)
            try:
                return default_tablespace(connection) is not None
            finally:
                connection.close()

        if not self._poll(usable, transient_exceptions=[oracledb.Error]):
            raise TimeoutError(f"Oracle at {target} was not usable within {BOOT_TIMEOUT}s")


def oracle_container(name: str | None = None) -> DockerContainer:
    """A configured, not-yet-started 19c container. `start()` returns only once it is connectable.

    No --shm-size. DBCA configures ASMM, so the SGA is a SysV segment, not /dev/shm; a container
    booted at Docker's default 64 MB /dev/shm left it 0% used (#3). What does bind is ~3.2 GB of
    container memory.
    """
    container = (
        DockerContainer(IMAGE)
        .with_env("ORACLE_PWD", SYS_PASSWORD)
        .with_env("ORACLE_SID", CDB_NAME)
        .with_env("ORACLE_PDB", SERVICE_NAME)
        .with_exposed_ports(ORACLE_PORT)
        .waiting_for(
            PdbUsableWaitStrategy().with_startup_timeout(BOOT_TIMEOUT).with_poll_interval(2)
        )
    )
    if name is not None:
        container.with_name(name)
    return container


def create_app_user(connection: oracledb.Connection) -> None:
    """Create the app user inside the PDB. Given a SYS connection; does not open its own.

    The 23ai image did this from `APP_USER`/`APP_USER_PASSWORD`; this image ignores those, so the
    work becomes ours. Idempotent because in reuse mode the user is already there.

    The quota is the part that is easy to miss and fatal: without it every `CREATE TABLE` in the
    suite fails with ORA-01950, which #4 named as the migration's real risk. The tablespace it is
    granted on is read from the database rather than spelled `USERS`, so this cannot drift from
    whatever the image actually built.
    """
    tablespace = default_tablespace(connection)
    if tablespace is None:
        raise RuntimeError("PDB has no online default permanent tablespace; the wait ended early")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM dba_users WHERE username = :name", name=APP_USER.upper()
        )
        (exists,) = cursor.fetchone()
        if not exists:
            cursor.execute(f'CREATE USER {APP_USER} IDENTIFIED BY "{APP_PASSWORD}"')
        cursor.execute(f"GRANT CREATE SESSION, CREATE TABLE TO {APP_USER}")
        cursor.execute(f"ALTER USER {APP_USER} QUOTA UNLIMITED ON {tablespace}")
