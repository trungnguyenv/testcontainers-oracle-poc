"""How this project connects to Oracle.

python-oracledb's defaults are lossy for money: it fetches every NUMBER as a Python float, so
``NUMBER(10, 2)`` arrives with binary rounding error. Connections opened here fetch NUMBER as
Decimal instead. This lives in production code rather than in a fixture because it is a property
of the application, not of the tests.
"""

import decimal

import oracledb


def _numbers_as_decimal(cursor: oracledb.Cursor, metadata: oracledb.FetchInfo):
    if metadata.type_code is oracledb.DB_TYPE_NUMBER:
        return cursor.var(decimal.Decimal, arraysize=cursor.arraysize)
    return None


def connect(user: str, password: str, dsn: str) -> oracledb.Connection:
    """Open a connection that round-trips NUMBER without losing precision."""
    connection = oracledb.connect(user=user, password=password, dsn=dsn)
    connection.outputtypehandler = _numbers_as_decimal
    return connection
