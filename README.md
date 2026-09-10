# Oracle Testcontainers POC

Integration tests for data-access code, run against a real Oracle database in a throwaway
container — no mocks, no SQLite stand-in, no Oracle install on your machine.

## Why not mocks or SQLite

Every test in `tests/test_orders.py` asserts something that only a real Oracle database does.
Two of them failed the first time this POC ran, and the fixes landed in production code:

- **Money came back as `float`.** python-oracledb fetches every `NUMBER` as a Python float by
  default, so `NUMBER(10,2)` arrives with binary rounding error. `oracle_poc.db.connect` installs
  an output type handler that fetches `NUMBER` as `Decimal`. A mock returning `Decimal("19.99")`
  would have hidden this indefinitely.
- **Timestamps lost their sub-second part.** A Python `datetime` binds as Oracle's `DATE` type,
  which has no fractional seconds, so microseconds were silently discarded on insert.
  `OrderRepository.add` now calls `setinputsizes(placed_at=oracledb.DB_TYPE_TIMESTAMP)`.

The rest cover foreign-key violations (`ORA-02291`), `VARCHAR2` overflow raising rather than
truncating (`ORA-12899`), identity-column generation, and a two-table join.

## Prerequisites

- Docker running, with roughly 2GB of memory available to it
- [uv](https://docs.astral.sh/uv/) — the Python toolchain and interpreter are managed for you

## Running

```sh
uv sync
uv run pytest
```

The first run pulls `gvenzl/oracle-free:23-slim-faststart` (~500MB). After that a full run takes
about 13 seconds, nearly all of it database startup.

### Reuse mode

```sh
ORACLE_POC_REUSE=1 uv run pytest
```

Leaves the container running under the name `oracle-poc-reused`, so the next run attaches to it
instead of booting Oracle again: **13s → 0.4s**. The tests behave identically either way. Tear it
down with `docker rm -f oracle-poc-reused`.

## How isolation works

One container serves the whole test session, so tests must not see each other's data. Each test
creates its own `customers_<suffix>` / `orders_<suffix>` pair and drops them at teardown, rather
than rolling back a transaction per test. That means the repositories are free to commit — they
own their transactions, exactly as they would in production.

The cost: Oracle cannot bind identifiers as parameters, only values, so table names are
interpolated into the SQL strings. This looks like the injection pattern you are taught to avoid,
and it is deliberate — the suffixes are generated, never user input. See
[ADR 0001](docs/adr/0001-per-test-table-sets-for-isolation.md).

## Layout

```
src/oracle_poc/
  db.py           how the application connects (NUMBER → Decimal)
  model.py        Customer, Order
  repository.py   the code under test; receives a connection, is told which tables to address
  tables.py       TableSet — the per-test table names, plus their DDL
tests/
  conftest.py     container, connection and table-set fixtures
  test_orders.py  the tests
CONTEXT.md        project glossary
docs/adr/         decisions worth remembering
```

## Notes

- `gvenzl/oracle-free:23-slim-faststart` is used because it publishes **native arm64 images**.
  The commonly-cited `gvenzl/oracle-xe` is amd64-only and runs under emulation on Apple Silicon.
- python-oracledb runs in **thin mode**: no Oracle Instant Client, no native dependencies.
- These are integration tests, not unit tests. They cross a process boundary and hit a real
  database; they stand in for what many teams would write as mock-based unit tests.
