# Oracle Testcontainers POC

Integration tests for data-access code, run against **Oracle 19c Enterprise Edition** in a
throwaway container — the same version production runs, on your laptop, with no Oracle install, no
mocks and no SQLite stand-in.

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

Both are **the driver's doing, not the database version's**: they are decided client-side by
python-oracledb and behave identically on 19c and 23ai, so expect them on any version you port
this to.

The rest cover foreign-key violations (`ORA-02291`), `VARCHAR2` overflow raising rather than
truncating (`ORA-12899`), identity-column generation, and a two-table join.

## Why this version, and not a convenient one

The suite used to run against `gvenzl/oracle-free:23-slim-faststart` — 500MB, official, and up in
13 seconds. Production runs 19c Enterprise, so that image was testing against a database nobody
ships on. Moving to 19c cost a 2.86GB image and a several-minute first boot, and it immediately
found something a mock could not have hidden and the free image *had* been hiding:

- **The suite had been leaning on a privilege nobody granted it.** The 23ai image handed the app
  user `DB_DEVELOPER_ROLE` — 29 privileges chosen by the image, not by us. One of them was
  `CREATE SEQUENCE`, which an identity column needs for the sequence Oracle creates behind it. On
  19c, where the app user gets a list we wrote ourselves, every `CREATE TABLE` in the suite failed
  with `ORA-01031: insufficient privileges` — which names no privilege, so finding it took a
  bisection. See [ADR 0003](docs/adr/0003-a-named-privilege-surface-for-the-app-user.md).

This one failed no assertion. It broke the fixture, which is why a suite that passes tells you less
than you think when the container is choosing your grants. All seven assertions then passed on 19c
unchanged, `ORA-02291` and `ORA-12899` byte-identical in the asserted part.

## Prerequisites

- Docker running, with at least **3.2GB of memory** available to a single container, and roughly
  **6GB of disk** free (a 2.86GB image plus a ~3GB database volume — see
  [Where the database lives](#where-the-database-lives))
- [uv](https://docs.astral.sh/uv/) — the Python toolchain and interpreter are managed for you

## Running

```sh
uv sync
uv run pytest
```

**The first run takes about seven minutes.** The image ships Oracle binaries only, so DBCA builds
the database on first boot: 410 seconds measured, inside `uv run pytest`, with the wait strategy
reporting what it is waiting for. **Every run after that takes about 11 seconds** — faster than the
13.25s the free image managed, because the database it built is still there.

That cost is paid once per pinned image digest, not once per run and not once per clone-age.

## Where the database lives

The container is throwaway; the database is not. The fixture mounts a named Docker volume on
`/opt/oracle/oradata`, so the created database outlives the container that built it and each run
starts a fresh container against a database that already exists. There is no flag and no mode — the
volume is mounted unconditionally.

The volume is named after the pinned digest:

```sh
docker volume ls | grep oracle-poc-oradata      # oracle-poc-oradata-6a5e663c, ~3GB
docker volume rm oracle-poc-oradata-6a5e663c    # reclaim the space
```

Removing it — or bumping the pinned digest, or running `docker system prune --volumes` — means
paying the seven minutes again. Naming it after the digest is deliberate: a pin bump makes the old
database unreachable by construction rather than by a staleness check. See
[ADR 0002](docs/adr/0002-persistent-database-throwaway-container.md).

## How isolation works

One container serves the whole test session, so tests must not see each other's data. Each test
creates its own `customers_<suffix>` / `orders_<suffix>` pair and drops them at teardown, rather
than rolling back a transaction per test. That means the repositories are free to commit — they
own their transactions, exactly as they would in production.

The cost: Oracle cannot bind identifiers as parameters, only values, so table names are
interpolated into the SQL strings. This looks like the injection pattern you are taught to avoid,
and it is deliberate — the suffixes are generated, never user input. See
[ADR 0001](docs/adr/0001-per-test-table-sets-for-isolation.md).

Because the database survives between runs, so would anything left in it by a run killed
mid-test. The session bootstrap therefore drops and recreates the app user rather than creating it
if absent, which makes a leaked table set impossible rather than merely tidied.

## What the app user may do

The tests connect as a dedicated Oracle user holding **nine named system privileges**, granted one
by one rather than through a role. The list is sized to the object types a data-access layer works
with, not to the three the current tests need, and every entry has to answer "why is this here?".
`tests/test_privileges.py` creates and drops one object of each otherwise-unexercised type, so a
grant that turns out to be insufficient fails on its own name.

What this repository can claim about a production app user is this: a list somebody can defend line
by line, in place of a role whose contents vary by version and patch level. The nine are in
`tests/oracle_container.py` as `PRIVILEGE_SURFACE`, and argued in
[ADR 0003](docs/adr/0003-a-named-privilege-surface-for-the-app-user.md).

## Layout

```
src/oracle_poc/
  db.py                how the application connects (NUMBER → Decimal)
  model.py             Customer, Order
  repository.py        the code under test; receives a connection, is told which tables to address
  tables.py            TableSet — the per-test table names, plus their DDL
tests/
  oracle_container.py  Docker, the pinned image, the SYS bootstrap — knows nothing about pytest
  conftest.py          container, connection and table-set fixtures — knows nothing about Docker
  test_orders.py       the seven
  test_privileges.py   one test per otherwise-unexercised privilege
CONTEXT.md             project glossary
docs/adr/              decisions worth remembering
docs/runs/             measurements those decisions rest on
```

## Notes on the image

`codeassertion/oracledb-arm64-standalone:19.3.0-enterprise`, pinned by digest.

It is used because it is a **native arm64 build of 19c Enterprise**. gvenzl publishes no 19c at
all, and the commonly-cited `gvenzl/oracle-xe` is amd64-only, so it runs under emulation on Apple
Silicon.

**It is also a third-party repackage of Oracle Enterprise binaries, not an Oracle-published
image.** The licensing of that redistribution has not been examined here. This is an accepted risk
for a POC that runs on one laptop, and it is recorded rather than mitigated — do not copy this
image choice into anything you ship, into CI, or into a shared environment. The legitimate route is
building your own image from [`oracle/docker-images`](https://github.com/oracle/docker-images) plus
binaries you download under your own licence; Oracle also publishes
`container-registry.oracle.com/database/enterprise:19.3.0.0`, which is amd64-only. Both are out of
scope here and neither was measured. See
[ADR 0004](docs/adr/0004-oracle-19c-enterprise-as-the-only-database.md).

Other things worth knowing:

- Tests connect to the **PDB** (`ORCLPDB1`), never the CDB root, so the app user is an ordinary
  user rather than a common `C##` one.
- python-oracledb runs in **thin mode**: no Oracle Instant Client, no native dependencies.
- No `--shm-size` is needed. DBCA configures ASMM, so the SGA is a SysV shared-memory segment
  rather than a file under `/dev/shm`.
- These are integration tests, not unit tests. They cross a process boundary and hit a real
  database; they stand in for what many teams would write as mock-based unit tests.
