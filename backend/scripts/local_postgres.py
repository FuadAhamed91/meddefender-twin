"""Run a local PostgreSQL 16 for development and tests without Docker or a system install.

Uses the PostgreSQL binaries bundled in the ``pgserver`` wheel (``uv sync --extra localpg``).
The server listens on 127.0.0.1 only, uses SCRAM authentication and keeps its data in
``backend/.localdb`` (git-ignored). Credentials below are for local development only.

    uv run --extra localpg python scripts/local_postgres.py start
    uv run --extra localpg python scripts/local_postgres.py status
    uv run --extra localpg python scripts/local_postgres.py stop
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg import sql

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / ".localdb" / "data"
LOG_FILE = BACKEND_DIR / ".localdb" / "postgres.log"
PORT = int(os.environ.get("LOCAL_PG_PORT", "55432"))
SUPERUSER = "postgres"
SUPERUSER_PASSWORD = "postgres-local-dev"  # noqa: S105 - local dev server bound to 127.0.0.1
APP_USER = "meddefender"
APP_PASSWORD = "meddefender-local-dev"  # noqa: S105 - local dev server bound to 127.0.0.1
DATABASES = ("meddefender", "meddefender_test")


def _bin_dir() -> Path:
    try:
        import pgserver  # noqa: F401
        from pgserver._commands import POSTGRES_BIN_PATH
    except ImportError:
        sys.exit("pgserver is not installed. Run: uv sync --extra localpg")
    return Path(POSTGRES_BIN_PATH)


def _exe(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    return str(_bin_dir() / f"{name}{suffix}")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603


def is_running() -> bool:
    if not DATA_DIR.exists():
        return False
    return _run([_exe("pg_ctl"), "-D", str(DATA_DIR), "status"]).returncode == 0


def init_cluster() -> None:
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw") as pw:
        pw.write(SUPERUSER_PASSWORD)
        pwfile = pw.name
    try:
        result = _run(
            [
                _exe("initdb"),
                "-D",
                str(DATA_DIR),
                "-U",
                SUPERUSER,
                "--pwfile",
                pwfile,
                "--auth",
                "scram-sha-256",
                "-E",
                "UTF8",
                "--no-locale",
            ]
        )
    finally:
        os.unlink(pwfile)
    if result.returncode != 0:
        sys.exit(f"initdb failed:\n{result.stdout}\n{result.stderr}")


def start() -> None:
    if not DATA_DIR.exists():
        print(f"Initialising cluster in {DATA_DIR}")
        init_cluster()
    if is_running():
        print(f"PostgreSQL already running on 127.0.0.1:{PORT}")
    else:
        # The server outlives this process and would inherit captured pipes, which makes
        # subprocess wait forever on Windows. Server output goes to LOG_FILE instead.
        returncode = subprocess.call(  # noqa: S603
            [
                _exe("pg_ctl"),
                "-D",
                str(DATA_DIR),
                "-l",
                str(LOG_FILE),
                "-o",
                f"-p {PORT} -c listen_addresses=127.0.0.1",
                "-w",
                "start",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if returncode != 0:
            sys.exit(f"pg_ctl start failed (exit {returncode}). See {LOG_FILE}")
        print(f"PostgreSQL started on 127.0.0.1:{PORT}")
    ensure_databases()
    print_urls()


def ensure_databases() -> None:
    dsn = (
        f"host=127.0.0.1 port={PORT} user={SUPERUSER} password={SUPERUSER_PASSWORD} dbname=postgres"
    )
    for attempt in range(20):
        try:
            conn = psycopg.connect(dsn, autocommit=True)
            break
        except psycopg.OperationalError:
            if attempt == 19:
                raise
            time.sleep(0.5)
    with conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,)).fetchone()
        if not exists:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_USER), sql.Literal(APP_PASSWORD)
                )
            )
        for db in DATABASES:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
                conn.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(db), sql.Identifier(APP_USER)
                    )
                )


def print_urls() -> None:
    base = f"postgresql+psycopg://{APP_USER}:{APP_PASSWORD}@127.0.0.1:{PORT}"
    print(f"DATABASE_URL={base}/meddefender")
    print(f"TEST_DATABASE_URL={base}/meddefender_test")


def stop() -> None:
    if not is_running():
        print("PostgreSQL is not running")
        return
    result = _run([_exe("pg_ctl"), "-D", str(DATA_DIR), "-w", "-m", "fast", "stop"])
    if result.returncode != 0:
        sys.exit(f"pg_ctl stop failed:\n{result.stdout}\n{result.stderr}")
    print("PostgreSQL stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["start", "stop", "status", "urls"])
    args = parser.parse_args()
    if args.command == "start":
        start()
    elif args.command == "stop":
        stop()
    elif args.command == "status":
        print("running" if is_running() else "stopped")
    else:
        print_urls()


if __name__ == "__main__":
    main()
