"""add request form data, eligibility result and document category

Additive only: three nullable columns, no existing data is touched.

Revision ID: 7b3c1a9e5d42
Revises: 2d9f0673822c
Create Date: 2026-10-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7b3c1a9e5d42'
down_revision: Union[str, Sequence[str], None] = '2d9f0673822c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('form_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('applications', sa.Column('eligibility_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('uploaded_documents', sa.Column('document_category', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_documents', 'document_category')
    op.drop_column('applications', 'eligibility_result')
    op.drop_column('applications', 'form_data')
