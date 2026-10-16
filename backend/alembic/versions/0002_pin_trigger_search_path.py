"""pin the append-only trigger function's search_path

A function whose search_path is taken from the caller can be redirected by objects created
earlier in that path. The trigger function only raises an exception and references no
relations, so an empty search_path is safe (flagged by Supabase's database linter).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16 10:10:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER FUNCTION meddefender_block_mutation() SET search_path = ''")


def downgrade() -> None:
    op.execute("ALTER FUNCTION meddefender_block_mutation() RESET search_path")
