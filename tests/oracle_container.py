"""How the Oracle container is run: Docker, the pinned image, and the SYS bootstrap.

Nothing here knows about pytest, and nothing in ``conftest.py`` knows about Docker or SYSDBA —
the seam chosen on #6. The image ships binaries only; DBCA builds the *created database* on first
boot and the entrypoint fast-paths on it afterwards, so the database is persisted in a named
volume (#9) while the container itself stays throwaway.
"""

import oracledb
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget

# Pinned by digest: the tag is not immutable and this is the exact build measured in #3
# (Oracle 19c Enterprise 19.19.0.0.0, arm64 native, 2.86 GB).
IMAGE_REPOSITORY = "codeassertion/oracledb-arm64-standalone"
IMAGE_DIGEST = "sha256:6a5e663cdc494e3086f455d7a8b4c6bcf284214e6f10f973a6b2b89e04230e4c"
IMAGE = f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"

ORACLE_PORT = 1521
SYS_PASSWORD = "oracle"
CDB_NAME = "ORCLCDB"
SERVICE_NAME = "ORCLPDB1"

APP_USER = "app"
APP_PASSWORD = "app"

PRIVILEGE_SURFACE = (
    "CREATE SESSION",
    "CREATE TABLE",
    "CREATE SEQUENCE",
    "CREATE VIEW",
    "CREATE PROCEDURE",
    "CREATE TRIGGER",
    "CREATE TYPE",
    "CREATE SYNONYM",
    "CREATE MATERIALIZED VIEW",
)
"""What the app user may create, chosen as a set a data-access layer can defend (ADR 0003).

Not sized to the current tests, which need only the first three. Oracle grants nothing separately
for DDL on one's own schema: ALTER, DROP, TRUNCATE, COMMENT ON and CREATE INDEX on owned tables
come with ownership, so this list is the whole DDL surface short of the ANY privileges, which reach
into other schemas. CREATE PROCEDURE is three object types wide — procedures, functions and
packages — so the count here is not the count of things the app user can create.
"""

ORADATA = "/opt/oracle/oradata"
"""Where DBCA writes the created database. The image declares no VOLUME, so without a mount the
~3GB lands in the container's writable layer and dies with the container."""

ORADATA_VOLUME = f"oracle-poc-oradata-{IMAGE_DIGEST.removeprefix('sha256:')[:8]}"
"""Named after the digest, so bumping the pin makes the old created database unreachable by
construction rather than by a staleness probe (#9)."""

# Cold boot is DBCA building the created database from scratch: 316s clean, 412s alongside a
# second Oracle container (#3). testcontainers' default is 120s, which would fire every time.
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

    Read rather than hardcoded. ``USERS`` is what this image ends up with, but it is created
    *late* (see ``PdbUsableWaitStrategy``), and asking the database is both the readiness probe
    and the right way to name the tablespace for the app user's quota.
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

    Measured on #6: the ``DATABASE IS READY TO USE!`` log line lands four milliseconds *before*
    the PDB's ``CREATE SMALLFILE TABLESPACE "USERS"``, so a bootstrap that connects the instant
    SYS accepts it dies on ``ORA-00959: tablespace 'USERS' does not exist``. The probe is
    therefore SYS connecting **and** an online default permanent tablespace — exactly the
    precondition ``reset_app_user`` needs.
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


def oracle_container() -> DockerContainer:
    """A configured, not-yet-started 19c container. ``start()`` returns only once it is usable.

    No --shm-size. DBCA configures ASMM, so the SGA is a SysV segment, not /dev/shm (#3). What
    does bind is ~3.2 GB of container memory.
    """
    return (
        DockerContainer(IMAGE)
        .with_env("ORACLE_PWD", SYS_PASSWORD)
        .with_env("ORACLE_SID", CDB_NAME)
        .with_env("ORACLE_PDB", SERVICE_NAME)
        .with_exposed_ports(ORACLE_PORT)
        .with_volume_mapping(ORADATA_VOLUME, ORADATA, "rw")
        .waiting_for(
            PdbUsableWaitStrategy().with_startup_timeout(BOOT_TIMEOUT).with_poll_interval(2)
        )
    )


def reset_app_user(connection: oracledb.Connection) -> None:
    """Drop and recreate the app user inside the PDB. Given a SYS connection; opens none.

    Drop-and-recreate rather than create-if-absent (#5): the created database outlives the run,
    so a table set left behind by a killed session would otherwise survive into the next one.
    ``DROP USER ... CASCADE`` makes the schema empty by construction.

    The grants are ``PRIVILEGE_SURFACE``, spelled out rather than rolled into a role. The 23ai
    image handed the app user ``DB_DEVELOPER_ROLE`` — 29 privileges — and the suite silently
    leaned on one of them: ``CREATE SEQUENCE``, which an identity column needs for the sequence
    Oracle creates behind it. Without it every ``CREATE TABLE`` in the suite fails with ORA-01031
    (#7). The surface is not re-asserted after bootstrap: this function creates the user, so
    nothing else can grant it anything, and a missing privilege says ORA-01031 by name (#10).

    The quota is the other easy-to-miss, fatal part. Its tablespace is read from the database
    rather than spelled ``USERS``.
    """
    tablespace = default_tablespace(connection)
    if tablespace is None:
        raise RuntimeError("PDB has no online default permanent tablespace; the wait ended early")

    with connection.cursor() as cursor:
        try:
            cursor.execute(f"DROP USER {APP_USER} CASCADE")
        except oracledb.DatabaseError as error:
            (problem,) = error.args
            if problem.full_code != "ORA-01918":  # user does not exist: a first-ever run
                raise
        cursor.execute(f'CREATE USER {APP_USER} IDENTIFIED BY "{APP_PASSWORD}"')
        cursor.execute(f"GRANT {', '.join(PRIVILEGE_SURFACE)} TO {APP_USER}")
        cursor.execute(f"ALTER USER {APP_USER} QUOTA UNLIMITED ON {tablespace}")
