# A named privilege surface for the app user

The app user is granted nine system privileges — `CREATE SESSION`, `CREATE TABLE`,
`CREATE SEQUENCE`, `CREATE VIEW`, `CREATE PROCEDURE`, `CREATE TRIGGER`, `CREATE TYPE`,
`CREATE SYNONYM`, `CREATE MATERIALIZED VIEW` — chosen to cover the object types a data-access
layer works with, not the three the current tests happen to need. The 23ai image had been granting
`DB_DEVELOPER_ROLE`, 29 privileges nobody had chosen, and the suite silently depended on one of
them: `CREATE SEQUENCE`, which an identity column needs for the sequence Oracle creates behind it.
Removing that image turned every `CREATE TABLE` into `ORA-01031` and cost a 410-second run to
diagnose. Replacing 29 invisible grants with a list somebody can defend line by line is the point;
sizing that list to today's tests would leave the next privilege to be discovered the same way.

Note that `CREATE PROCEDURE` is three object types wide — procedures, functions and packages all
depend on it — so the count of privileges is deliberately not the count of things the app user can
create.

## Considered options

- **Least privilege, extended on demand.** Grant exactly what the seven tests need, and let a
  future test fail with `ORA-01031` until someone widens the list. Attractive because `ORA-01031`
  names the missing privilege and, now that the created database persists, costs about 11 seconds
  to hit rather than the 410 that made the original diagnosis expensive. Rejected because it makes
  the grant list a record of test history rather than a claim about the application: the surface
  would be re-litigated every time a test touched a new object type, and each widening would be
  argued from "a test needs it" instead of from what a data-access layer is.
- **The `RESOURCE` role.** One line, and unlike 23ai's `DB_DEVELOPER_ROLE` it exists on 19c.
  Measured on the pinned digest it holds eight privileges and is neither a subset nor a superset of
  what we want: it omits `CREATE SESSION`, so a `RESOURCE`-only user cannot log in at all, omits
  `CREATE VIEW`, `CREATE SYNONYM` and `CREATE MATERIALIZED VIEW`, and adds `CREATE CLUSTER`,
  `CREATE INDEXTYPE` and `CREATE OPERATOR`, which nothing here has a use for. A role whose contents
  vary by version and patch level is the same hidden work this decision exists to remove, with our
  name on it instead of the image's.
- **The full own-schema `CREATE` set**, including `CLUSTER`, `INDEXTYPE`, `OPERATOR` and the
  analytic-view family. Rejected on the same ground as `RESOURCE`: an entry no one can explain is
  the 23ai failure mode in miniature, and every entry in this list has to answer "why is this
  here?".
- **Asserting the granted set after bootstrap**, to catch drift. Rejected as machinery for a closed
  door: since ADR 0002 the session drops and recreates the app user itself, so the image never
  touches it and nothing else can grant it anything. Note that the closed door is the whole of the
  argument. An earlier draft of this ADR also claimed drift announces itself as `ORA-01031`
  "naming the privilege", and that is false — the verbatim text is `ORA-01031: insufficient
  privileges` and nothing more, which is why #7 needed a bisection to land on `CREATE SEQUENCE`.
  Evidence: `docs/runs/privilege-bisection-19c.json`.

## Consequences

Oracle grants no separate privilege for DDL on one's own schema, so this list is the entire DDL
surface. Measured against the pinned digest, a user holding only `CREATE SESSION` and
`CREATE TABLE` can already `CREATE INDEX`, `ALTER`, `TRUNCATE`, `COMMENT ON` and `DROP` its own
tables — those come with ownership. Every privilege that had to be granted was a
`CREATE <object type>`, and the only way to widen DDL past this list is the `ANY` variants, which
reach into other schemas and are deliberately absent. Evidence:
`docs/runs/own-schema-ddl-19c.json`.

Six of the nine — `CREATE VIEW`, `CREATE PROCEDURE`, `CREATE TRIGGER`, `CREATE TYPE`,
`CREATE SYNONYM`, `CREATE MATERIALIZED VIEW` — are exercised by nothing in `test_orders.py`, so
they are defended by a test that *uses* them rather than by one that reads the granted set back.
A separate module creates one object of each type in the app user's schema and drops it, one test
per privilege, so a grant that turns out to be insufficient fails on its own name — the naming
`ORA-01031` declines to do. This measures sufficiency, which is not obvious: an identity column
needing `CREATE SEQUENCE` was the surprise that started this, and a materialized view builds a
real table underneath it. If a privilege proves insufficient, the surface widens and the extra
grant is recorded here; that outcome is the test paying for itself, not a defect.

It is deliberately not in `test_orders.py`, whose docstring claims every assertion there depends
on behaviour only a real Oracle database exhibits. Grant semantics qualify, but "the seven" is a
phrase about that file, and this is not one of them. Asserting `session_privs` equals the constant
was rejected for the same reason it would have been the first test in the suite to fail only when
the fixture is misconfigured.

The list lives in `tests/oracle_container.py`, beside the `CREATE USER` that needs it, rather than
in `src/oracle_poc/` next to the `NUMBER`-to-`Decimal` handler that `db.py` argues belongs in
production code because it is a property of the application. The two are different: the output type
handler is code the application runs, whereas the grant list is run once by whoever provisions an
environment, and `src/` has no provisioning code for it to join. What this repository can claim
about production's app user is therefore a claim in prose, in the README, not a constant in the
package.
