# Workbench operational checks

Run these commands from `backend` so the `app` package is importable.

- `python ops/multi_worker_restart_check.py` verifies stale-job recovery and cross-worker SQLite lease ownership without contacting TWC.
- `python ops/verify_database_backup.py` creates a consistent SQLite backup, runs `PRAGMA integrity_check`, compares every table count, and prints the backup SHA-256. Use `--source` or `--output` to override configured paths.
- `python ops/live_twc_smoke.py` performs a real Workbench-to-TWC login, project visibility read, background permission refresh, inventory status read, and logout. It requires `WORKBENCH_SMOKE_BASE_URL`, `TWC_SMOKE_SERVER_ID`, and `TWC_SMOKE_TOKEN`; the token is never printed.

Set `WORKBENCH_SMOKE_VERIFY_TLS=false` only for an explicitly approved test environment with a private or self-signed certificate.
