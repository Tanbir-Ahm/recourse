"""matter files and instructions: the lawyer's standing instructions for a matter, and the documents filed under it, read page by page

matters.instructions (P0) holds the lawyer's standing preferences (style, focus, side), handed to the answer model as preferences that cannot loosen a rule (matter_files.instructions_block).
matter_files (P1) is one row per uploaded document: its name, kind, size, a SHA-256 of its bytes, the number of pages (PDF) or paragraphs (Word, text), the pages with no readable text. THE FILE ITSELF IS NOT KEPT: only the text
a program read from it, as passages (matter_file_passages, each with its page or paragraph range and, when the meaning search was reachable, its vector). Deleting the matter, the file or the person deletes them all
(ON DELETE CASCADE). Down: the two tables and the column are dropped.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('matters') as b:
        b.add_column(sa.Column('instructions', sa.Text(), nullable=True))
    op.create_table('matter_files',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('matter_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('doc_no', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('unit', sa.String(length=10), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('units', sa.Integer(), nullable=False),
    sa.Column('unread', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('passages', sa.Integer(), nullable=False),
    sa.Column('embedded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('pdf', 'docx', 'txt')", name='ck_matter_file_kind'),
    sa.CheckConstraint("unit IN ('page', 'para')", name='ck_matter_file_unit'),
    sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('matter_id', 'doc_no', name='uq_matter_file_no')
    )
    op.create_index('ix_matter_files_user', 'matter_files', ['user_id'], unique=False)
    op.create_table('matter_file_passages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('file_id', sa.Uuid(), nullable=False),
    sa.Column('matter_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('loc', sa.Integer(), nullable=False),
    sa.Column('loc_to', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('vec', sa.LargeBinary(), nullable=True),
    sa.ForeignKeyConstraint(['file_id'], ['matter_files.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_id', 'seq', name='uq_matter_passage_seq')
    )
    op.create_index('ix_matter_file_passages_matter', 'matter_file_passages', ['matter_id'], unique=False)


def downgrade():
    op.drop_index('ix_matter_file_passages_matter', table_name='matter_file_passages')
    op.drop_table('matter_file_passages')
    op.drop_index('ix_matter_files_user', table_name='matter_files')
    op.drop_table('matter_files')
    with op.batch_alter_table('matters') as b:
        b.drop_column('instructions')
