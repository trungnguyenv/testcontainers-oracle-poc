# Oracle 19c Enterprise as the only database

The integration suite runs against Oracle 19c Enterprise Edition —
`codeassertion/oracledb-arm64-standalone:19.3.0-enterprise`, pinned by digest — and nothing else.
`gvenzl/oracle-free:23-slim-faststart` is removed outright. The driver is fidelity to production,
which runs 19c EE; the fidelity that matters is the **version** gap, not the edition, and no
decision here chases an Enterprise-only feature.

The price is a 2.86GB image in place of a 500MB one, a first boot of roughly seven minutes in place
of thirteen seconds, and an image that Oracle did not publish. The payoff was not hypothetical: the
free image had been granting the app user `DB_DEVELOPER_ROLE`, and the suite was silently depending
on one of its 29 privileges (ADR 0003). A suite that passes against a database nobody ships on was
answering a question we were not asking.

## Considered options

- **Stay on `gvenzl/oracle-free:23-slim-faststart`.** Official, 500MB, arm64-native, and up in 13
  seconds — everything an inner loop wants. Rejected because the version gap is the whole point:
  23ai is not what production runs, and a POC whose purpose is to show that real-database testing
  catches real defects cannot be run against the wrong real database. The `CREATE SEQUENCE`
  discovery is the concrete cost of having done so.
- **Make the image selectable**, 19c for fidelity and the free image for a fast local loop.
  Rejected while the destination was being named. Two supported databases means every decision
  downstream is taken twice or taken for the weaker one: the wait strategy, the privilege surface,
  the bootstrap's `SYS` connection and the persistence story all differ between them, and the
  version-specific defect this migration exists to surface is precisely what a developer running
  the fast option would not see. A selectable database is a second way to be wrong, dressed as
  convenience.
- **Run both images side by side**, asserting the same tests against each. Rejected while naming
  the destination. It answers a question this POC is not asking — it is a compatibility matrix, not
  a demonstration that integration tests beat mocks — and it doubles the boot cost of every run to
  do it.
- **Build our own image from `oracle/docker-images` plus binaries downloaded under our own
  licence.** The legitimate answer to the provenance problem below, and the one to reach for if
  this ever leaves the laptop. Rejected as out of scope for a POC: it adds a build step with its
  own inputs, its own recipe to keep working, and a manual binary download that cannot be pinned by
  digest, in exchange for a licensing position that a single laptop does not need.
- **Oracle's own published image**, `container-registry.oracle.com/database/enterprise:19.3.0.0`.
  This would settle the provenance question outright. It is, to our understanding, **amd64-only**,
  which on Apple Silicon means QEMU emulation — where Oracle is unsupported and a database that
  already takes seven minutes to create has no headroom to spare. **This was not measured**: arm64
  is the only architecture in scope here (amd64 and Intel Macs were ruled out while naming the
  destination), so there was no configuration in which the comparison could have changed the
  decision. It is recorded because it is the first alternative any reader with a licensing concern
  will think of, not because it was tested and found wanting.

## Consequences

**The image is third-party.** It is a repackage of Oracle Enterprise binaries by neither Oracle nor
gvenzl, and the licensing of that redistribution has not been examined. This is an accepted risk
for a laptop-only POC, recorded rather than mitigated. Pinning by digest bounds it to one
reviewable artifact and makes a silent substitution impossible, which is all a pin can do — it does
not make the redistribution legitimate. The README says so plainly, in the section a reader hits
before they act on the image choice, because this is the one risk the migration transfers to the
reader rather than absorbing.

**The fast local loop is sacrificed knowingly, and mostly returned.** The first run costs 410
seconds; every run after costs 11, which is faster than the 13.25s the free image managed, because
ADR 0002's named volume keeps the created database. The cost is one-off per pinned digest rather
than per run — but it is real, it is paid again on any pin bump, and nothing spares a fresh clone.

**The database is a CDB with a PDB, and the tests live in the PDB.** The free image's `FREEPDB1`
was handed over ready to use; this one is created by DBCA on first boot as `ORCLCDB` containing
`ORCLPDB1`. Everything the suite creates targets the PDB, which is why the app user is `app` rather
than the `C##app` a CDB-root connection would have forced, and why the readiness probe has to wait
for the PDB's default tablespace rather than for the instance. This shape is now assumed by the
fixture, the glossary's **PDB** term, and ADR 0002's volume, so reversing this decision is not a
matter of changing one string.

**`testcontainers.community.oracle.OracleDbContainer` is unusable and gone**, along with the
`testcontainers[oracle-free]` extra it came from. Its `_configure()` sets `APP_USER`,
`APP_USER_PASSWORD` and `ORACLE_DATABASE`, which this image ignores, and its
`get_connection_url()` falls back to `FREEPDB1`. The fixture drives a plain `DockerContainer` and
supplies its own wait strategy, which it needed anyway: the default 120-second startup timeout is
guaranteed to fire on a cold boot.

Evidence for the numbers and behaviours above is in `docs/runs/`.
