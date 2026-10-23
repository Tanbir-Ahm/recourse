"""usage kinds for the search page

The search page (api/routers/search.py) counts its uses in usage_events: kind 'search' (the library) and 'search_wider' (the sci-search passages). The check constraint on usage_events.kind is replaced by one that
allows the two new kinds. Down: the rows of the two kinds are deleted (they carry no text and no cost) and the old constraint is put back.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 20:00:00.000000
"""
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

OLD = "kind IN ('answer_layman', 'answer_lawyer', 'draft', 'doc_read', 'anon_answer')"
NEW = "kind IN ('answer_layman', 'answer_lawyer', 'draft', 'doc_read', 'anon_answer', 'search', 'search_wider')"


def upgrade():
    op.drop_constraint('ck_usage_kind', 'usage_events', type_='check')
    op.create_check_constraint('ck_usage_kind', 'usage_events', NEW)


def downgrade():
    op.execute("DELETE FROM usage_events WHERE kind IN ('search', 'search_wider')")
    op.drop_constraint('ck_usage_kind', 'usage_events', type_='check')
    op.create_check_constraint('ck_usage_kind', 'usage_events', OLD)
