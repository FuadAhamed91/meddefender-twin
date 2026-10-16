"""Vercel Python function: the MedDefender Twin API (FastAPI) in serverless mode.

vercel.json routes /api/* here and bundles backend/app and shared/ with this function. In
serverless mode there is no background loop and no WebSocket: the console polls
/api/v1/events, and those polls also advance the simulation (see app/api/routes_events.py).
All data is synthetic.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SERVERLESS", "true")

from app.main import create_app  # noqa: E402

app = create_app()
