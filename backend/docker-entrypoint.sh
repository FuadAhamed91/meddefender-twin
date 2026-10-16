#!/bin/sh
# Container entrypoint: bring the schema up to date and load the synthetic baseline, then
# start the API. Both steps are idempotent, so restarts are safe. Set RUN_MIGRATIONS=false or
# RUN_SEED=false to skip either step.
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "meddefender: applying database migrations"
  alembic upgrade head
fi

if [ "${RUN_SEED:-true}" = "true" ]; then
  echo "meddefender: loading the synthetic baseline (skipped if already present)"
  python -m app.seed
fi

exec "$@"
