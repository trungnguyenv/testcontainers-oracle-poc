# Oracle Testcontainers POC

A proof of concept for testing data-access code against a real Oracle database running in a
throwaway container, rather than against mocks or a substitute engine like SQLite.

## Language

### Testing

**Integration test**:
A test that exercises a repository against a real Oracle database in a container. These stand in
for what many teams would write as mock-based unit tests.
_Avoid_: unit test, database test

**Table set**:
The pair of uniquely-named tables (`customers_<suffix>`, `orders_<suffix>`) created for a single
integration test and dropped when it finishes. Represented by the `TableSet` value object, which
carries both names together because the foreign key couples them.
_Avoid_: schema (means something else here), test tables, fixtures

**Suffix**:
The random hex string appended to table names to make one test's table set distinct from every
other's.

**Created database**:
The Oracle database built on first boot, which lives on outside any single container. The image
ships binaries only, so the first run pays several minutes to create the database; every run after
that starts a fresh container against the database already there. Keyed to the pinned image
digest, so a digest bump creates a new one rather than reusing the old.
_Avoid_: reuse mode, cached database, warm container

### Oracle

**Schema**:
An Oracle user's namespace. In Oracle a user and a schema are the same thing, so the app user owns
every table the tests create. Never used in this project to mean a set of table definitions.

**App user**:
The dedicated non-privileged Oracle user the tests connect as. Created by the test session itself
rather than by the image, and dropped and recreated at the start of every session so its schema
starts empty however the previous run ended. Distinct from `SYS`, which the session uses only to
create this user and never to run a test.
_Avoid_: test user, admin

### Domain under test

**Customer**:
A person or organization that places orders. The parent side of the foreign key.

**Order**:
A purchase placed by a customer, carrying a monetary amount and a placement timestamp.
_Avoid_: purchase, transaction

**Repository**:
The object under test. It reads and writes one part of the domain, receives an open connection
rather than opening its own, and is told which table set to address.
_Avoid_: DAO, store, manager
