# PROTOTYPE — the shape of the container fixture

**Throwaway.** Lives only on `prototype/container-fixture-shape`. Nothing here is meant to merge as-is.

Prototype for [#6 The shape of the container fixture](https://github.com/trungnguyenv/testcontainers-oracle-poc/issues/6).

## The question

Once `testcontainers.community.oracle.OracleDbContainer` is gone and the container is a plain
`DockerContainer` against 19c EE, what does `tests/conftest.py` look like? Specifically: where the
env vars and port live, what the wait strategy is, where the `SYS` bootstrap goes, what
`oracle_dsn` yields — and whether the fixture is **one** thing or **three**.

## Why this is code, not an HTML demo

The `prototype` skill's two branches (logic demo / UI variants) both assume a question a
non-developer can click through. This question is "where do the seams in a Python fixture go",
so the artifact to react to is a rough, runnable fixture. Stated as an assumption, per the skill.

## The verdict

**Variant B**, with SYSDBA opened and closed inside `app_user` rather than held open for the
session. Recorded on #6; `variant_a.py` stays here as the rejected alternative it was judged
against.

## What running it found

The prototype was not just read; it was booted. Two things came out of that, and neither was
visible from reading the image's docs.

### Readiness has to mean "the PDB can hold a table"

The first cold run reached `start()` at **408.8s** — proof that the custom `WaitStrategy` clears
testcontainers' 120s default, which #3 said would otherwise fire every time. Then the bootstrap
died:

```
ORA-00959: tablespace 'USERS' does not exist
```

`docker logs -t` explains it:

```
09:32:40.311  DATABASE IS READY TO USE!
09:32:40.315  ORCLPDB1(3):CREATE SMALLFILE TABLESPACE "USERS" ...
09:32:40.315  ORCLPDB1(3):ALTER DATABASE DEFAULT TABLESPACE "USERS"
```

The PDB's default tablespace is created **four milliseconds after** the ready line. So *both*
candidate predicates are too weak — the log line, and "SYS can connect". The strategy now waits
until SYS connects **and** the PDB reports an online `DEFAULT_PERMANENT_TABLESPACE`, which is
exactly the precondition the bootstrap needs.

### The quota tablespace is read, not spelled

`ALTER USER app QUOTA UNLIMITED ON USERS` hardcodes a name the image happens to pick. Both variants
now read `DEFAULT_PERMANENT_TABLESPACE` from `database_properties` and grant the quota on that. The
same query is the readiness probe, so the race and the hardcoding are closed by one change.

## The two variants

Both boot the same container, bootstrap the same app user, and hand out the same DSN. They differ
only in **where the seams are**, which is the open question.

| | `variant_a.py` | `variant_b.py` |
|---|---|---|
| Container config | inline in the fixture | `oracle_container.py`, a module the fixture calls |
| Readiness | inline retry loop after `start()` | a `WaitStrategy` subclass, so `start()` returns ready |
| `SYS` bootstrap | inline in the same fixture | a named function beside the container config |
| `SYS` lifetime | opened and closed per call | opened and closed inside `app_user` |
| Fixtures exposed | one (`oracle_dsn`) | three (`oracle_dsn`, `app_user`, `connection`) |

## Running it

Each variant is runnable on its own, outside pytest, and prints the state it reaches at each step:

```
uv run python -m tests.prototype.variant_a
uv run python -m tests.prototype.variant_b
```

Budget **~6 minutes** for a cold boot (316s clean, 412s contended — measured in #3). Add `--keep`
to leave the container running so the second run is ~12s and you can compare the two variants
without paying twice.

Neither variant runs the actual test suite. That is [#7](https://github.com/trungnguyenv/testcontainers-oracle-poc/issues/7).
