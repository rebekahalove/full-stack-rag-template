"""Allow provider-configurable embedding dimensions.

Revision ID: 20261028_0002
Revises: 20261027_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20261028_0002"
down_revision: str | None = "20261027_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector indexes require a fixed dimension. Removing this global index lets the
    # shared column safely hold provider-specific dimensions; document-scoped retrieval
    # remains exact. Deployments that pin one embedding space can add a partial expression
    # index cast to vector(n) in a deployment-specific migration.
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.alter_column(
        "chunks",
        "embedding",
        existing_type=Vector(dim=1536),
        type_=Vector(),
        postgresql_using="embedding::vector",
        existing_nullable=False,
    )
    op.add_column("chunks", sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
    op.execute("UPDATE chunks SET embedding_dimensions = vector_dims(embedding)")
    op.alter_column("chunks", "embedding_dimensions", nullable=False)
    op.create_check_constraint(
        op.f("ck_chunks_embedding_dimensions_match"),
        "chunks",
        "embedding_dimensions = vector_dims(embedding)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chunks WHERE embedding_dimensions <> 1536
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade while chunks contain embeddings other than 1536 dimensions';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(op.f("ck_chunks_embedding_dimensions_match"), "chunks", type_="check")
    op.drop_column("chunks", "embedding_dimensions")
    op.alter_column(
        "chunks",
        "embedding",
        existing_type=Vector(),
        type_=Vector(dim=1536),
        postgresql_using="embedding::vector(1536)",
        existing_nullable=False,
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
