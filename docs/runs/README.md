# Run evidence for [#7](https://github.com/trungnguyenv/testcontainers-oracle-poc/issues/7)

Captured artifacts, not documentation. The narrative is on the issue.

| File | What it is |
|---|---|
| `probe-23ai.json` | Baseline facts from the moving `gvenzl` tag (`sha256:f5ff1903…`, banner *26ai 23.26.3.0.0*) |
| `probe-19c.json` | The same facts from 19c EE 19.19.0.0.0 on the pinned digest |
| `privs-23ai.json` | What the 23ai image granted the app user: `DB_DEVELOPER_ROLE`, 29 privileges |
| `privilege-bisection-19c.json` | The bisection that isolated `ORA-01031` to the missing `CREATE SEQUENCE` |
| `19c-cold-boot-milestones.log` | DBCA milestones from the 410s first boot |
