# Per-test table sets for isolation

All integration tests share a single session-scoped Oracle container, so they need protection from
each other's writes. Each test creates its own `customers_<suffix>` / `orders_<suffix>` pair with a
random suffix and drops them at teardown, rather than rolling back a transaction per test or
truncating shared tables between tests.

## Considered options

- **Transaction rollback per test.** Cheapest and total, but it requires that the code under test
  never commits, which would constrain the repository's API for the sake of the tests. It also
  cannot isolate tests that run concurrently.
- **Truncate shared tables between tests.** Tolerates commits, but needs a registry of every table
  to clean and leaves tests coupled to a single mutable schema.
- **A fresh Oracle schema (user) per test.** Achieves the same isolation while keeping table names
  literal, at the cost of a `CREATE USER` per test. Rejected as more machinery than a POC needs,
  but it is the natural upgrade path if the interpolation cost below starts to hurt. That upgrade
  has since become less natural than it reads here: `CREATE USER` needs `SYS`, and ADR 0002's
  bootstrap deliberately opens the SYSDBA connection once and closes it before any test runs, so a
  per-test schema would mean holding a privileged connection open across the session or reopening
  one per test.

## Consequences

Table names are runtime data, and Oracle cannot bind identifiers as parameters — only values. Every
repository statement therefore interpolates its table names into the SQL string. This is safe here
because suffixes are generated rather than user-supplied, but it looks like the injection pattern
readers are taught to avoid, so it is deliberate rather than careless.

Each test also pays two `CREATE TABLE` round-trips and two `DROP`s, and Oracle's DDL commits
implicitly. In exchange, nothing the repository does — including committing — can leak into another
test, and the design would hold up unchanged under parallel test execution.
