"""phase9_full_schema

Revision ID: 8b78e6578b97
Revises: e8a9b0c1d2f3
Create Date: 2026-04-09 13:13:50.671149

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b78e6578b97'
down_revision: Union[str, Sequence[str], None] = 'e8a9b0c1d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop types if they already exist from a previous failed run
    op.execute("DROP TYPE IF EXISTS user_role, run_type, run_status CASCADE")

    # 2. Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('submitter', 'reviewer', 'admin', name='user_role'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 3. Alter projects table
    op.add_column('projects', sa.Column('submitter_id', sa.UUID(), nullable=True))
    op.add_column('projects', sa.Column('reviewer_id', sa.UUID(), nullable=True))
    op.add_column('projects', sa.Column('task', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('stage', sa.String(length=255), nullable=True))
    op.add_column('projects', sa.Column('deadlines', sa.String(length=255), nullable=True))
    op.add_column('projects', sa.Column('human_decision', sa.String(length=64), server_default='pending', nullable=False))
    op.add_column('projects', sa.Column('reviewer_comment', sa.Text(), nullable=True))
    op.create_foreign_key(None, 'projects', 'users', ['reviewer_id'], ['id'])
    op.create_foreign_key(None, 'projects', 'users', ['submitter_id'], ['id'])

    # 4. Create agent_runs table
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('run_type', sa.Enum('evaluation', 'deep_research', name='run_type'), nullable=False),
        sa.Column('status', sa.Enum('queued', 'running', 'completed', 'failed', name='run_status'), nullable=False),
        sa.Column('current_agent', sa.String(length=255), nullable=True),
        sa.Column('completed_agents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_agents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('evaluation_prompt', sa.Text(), nullable=True),
        sa.Column('result_json', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('progress_json', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_text', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 6. Create telegram_subscribers table
    op.create_table(
        'telegram_subscribers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('chat_id', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_id')
    )


def downgrade() -> None:
    op.drop_table('telegram_subscribers')
    op.drop_table('messages')
    op.drop_table('agent_runs')
    op.drop_constraint('projects_reviewer_id_fkey', 'projects', type_='foreignkey')
    op.drop_constraint('projects_submitter_id_fkey', 'projects', type_='foreignkey')
    op.drop_column('projects', 'reviewer_comment')
    op.drop_column('projects', 'human_decision')
    op.drop_column('projects', 'deadlines')
    op.drop_column('projects', 'stage')
    op.drop_column('projects', 'task')
    op.drop_column('projects', 'reviewer_id')
    op.drop_column('projects', 'submitter_id')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.execute("DROP TYPE run_status")
    op.execute("DROP TYPE run_type")
    op.execute("DROP TYPE user_role")
