"""case file: what the person has told us in a conversation, kept where they can see it and edit it

chats.case_file holds the file of case_file.py as JSON: the facts (sentences the person typed, copied word for word, plus lines they added or edited and tapped answers) and a list of fingerprints of sentences they removed. NULL for a
conversation that has none. Deleting the conversation deletes it. Down: the column is dropped.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chats') as b:
        b.add_column(sa.Column('case_file', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))


def downgrade():
    with op.batch_alter_table('chats') as b:
        b.drop_column('case_file')
