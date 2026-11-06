"""matters: a lawyer's case file, and a conversation can be filed under one

A matter (api/routers/matters.py) holds the court, case number, sections charged, stage, next hearing date and facts that the lawyer states once; chats.matter_id files a conversation under it. Deleting a matter sets
chats.matter_id to NULL (the conversations stay, unfiled). Deleting the person deletes their matters with everything else. Down: the column and the table are dropped (the conversations stay).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

STAGES = "stage IS NULL OR stage IN ('fir', 'arrest', 'remand', 'bail', 'chargesheet', 'trial', 'appeal', 'other')"


def upgrade():
    op.create_table('matters',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('court', sa.String(length=200), nullable=True),
    sa.Column('case_number', sa.String(length=100), nullable=True),
    sa.Column('sections', sa.String(length=300), nullable=True),
    sa.Column('stage', sa.String(length=20), nullable=True),
    sa.Column('next_date', sa.Date(), nullable=True),
    sa.Column('facts', sa.Text(), nullable=True),
    sa.Column('archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(STAGES, name='ck_matter_stage'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_matters_user_updated', 'matters', ['user_id', 'updated_at'], unique=False)
    with op.batch_alter_table('chats') as b:
        b.add_column(sa.Column('matter_id', sa.Uuid(), nullable=True))
        b.create_foreign_key('fk_chats_matter_id', 'matters', ['matter_id'], ['id'], ondelete='SET NULL')
        b.create_index('ix_chats_matter_id', ['matter_id'], unique=False)


def downgrade():
    with op.batch_alter_table('chats') as b:
        b.drop_index('ix_chats_matter_id')
        b.drop_constraint('fk_chats_matter_id', type_='foreignkey')
        b.drop_column('matter_id')
    op.drop_index('ix_matters_user_updated', table_name='matters')
    op.drop_table('matters')
