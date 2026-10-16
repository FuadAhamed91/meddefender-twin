# MedDefender Twin backend

FastAPI modular monolith: the device-message security pipeline, policy engine, detection
rules, graphs, incidents, containment, audit trail, the simulator and scenarios A-F. All
data is synthetic. See the [root README](../README.md) for the full picture and
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for the design.

```bash
uv sync --extra localpg                                  # dependencies (+ embedded PostgreSQL)
uv run --extra localpg python scripts/local_postgres.py start
uv run alembic upgrade head                              # schema, incl. append-only triggers
uv run python -m app.seed                                # synthetic baseline + demo users
uv run uvicorn app.main:create_app --factory --port 8000 # API, docs at /api/docs
uv run pytest -q                                         # tests (TEST_DATABASE_URL)
uv run ruff check . && uv run ruff format --check .      # lint
```

Settings come from environment variables or the repository-root `.env`
(`app/core/config.py`). Tests never read `.env`; they use `TEST_DATABASE_URL`, which
defaults to the embedded database's `meddefender_test`.

The container image (`Dockerfile`, built from the repository root) runs the migrations and
the idempotent seed on start, then a single uvicorn worker.
