# A persistent database in a throwaway container

The 19c Enterprise image ships Oracle binaries only, and DBCA creates the database on first boot at
a cost of roughly 316 seconds. To avoid paying that once per test run, the fixture mounts a named
Docker volume on `/opt/oracle/oradata` — unconditionally, with no flag — so the created database
outlives the container that built it and every later run starts a fresh container against it in
about 12 seconds. The container stays throwaway; the database does not. The volume is named after
the pinned image digest, so a digest bump makes the old database unreachable by construction rather
than by a staleness check.

## Considered options

- **`docker commit` a first-booted container.** Genuinely viable: the image declares no `VOLUME`,
  so the DBCA output does land in the writable layer. Rejected because it costs ~11GB against the
  volume's ~3GB, and because it replaces a verifiable pinned digest with an unpinned local artifact
  built by no recorded recipe. The entrypoint's fast path keys off the *data* — a checkpoint file
  under `oradata` — not off the container, so a volume reaches the same 12-second start with the
  pin left as literally the thing that runs.
- **Reuse mode: leave a named container running between runs.** This is what the project did
  against the 23ai image, and the obvious answer while the boot cost minutes. Once the volume made
  every start ~12 seconds, container-level reuse bought back only those 12 seconds, and charged for
  them: a container matched by name alone would silently serve a previous digest, the attach path
  skipped the readiness wait entirely, and a leftover container's exclusive mount on the volume
  broke ordinary runs with `ORA-01102`. Removed outright — no flag, no opt-out, no named container.
- **A separate `make db` warm-up step.** Rejected because it invents a second way to be wrong, in
  the form of a hand-started container nobody's fixture owns, and moves setup back out of the
  fixture. The cold boot stays inside `uv run pytest`, with the wait strategy reporting what it is
  waiting for so five silent minutes do not read as a hung tool.

## Consequences

Because the database survives between runs, so does everything in it: the app user, and any table
set left behind by a run killed mid-test. The session bootstrap therefore drops and recreates the
app user rather than creating it if absent, which makes leaked table sets impossible instead of
merely tidied and removes the need for the bootstrap to be idempotent by inspection.

Nothing spares a fresh clone the first several minutes; that cost is real and is stated plainly in
the README. It is paid again on `docker system prune --volumes` and on any digest bump — the latter
mandatory, or the pin would be decorative. Two containers cannot share the volume, but the second
one fails loudly on `ORA-01102` with the first unharmed, so no lock guards it. An interrupted first
boot self-heals: the entrypoint wipes an incomplete database before recreating it.
