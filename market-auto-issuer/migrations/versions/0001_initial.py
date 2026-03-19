"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incoming_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notification_type", sa.String(64), nullable=False, index=True),
        sa.Column("order_id", sa.String(64), nullable=True, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_table(
        "market_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("substatus", sa.String(64), nullable=True),
        sa.Column("raw_order", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "stock_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_code", sa.String(128), nullable=False, index=True),
        sa.Column("secret_payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="free", index=True),
        sa.Column("reserved_for_order_id", sa.String(64), nullable=True, index=True),
        sa.Column("issued_to_order_id", sa.String(64), nullable=True, index=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_table(
        "issuances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False, index=True),
        sa.Column("order_item_key", sa.String(128), nullable=False),
        sa.Column("stock_item_id", sa.Integer(),
                  sa.ForeignKey("stock_items.id"), nullable=True),
        sa.Column("delivery_status", sa.String(16), nullable=False,
                  server_default="pending"),
        sa.Column("delivery_message_id", sa.String(256), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("issuances")
    op.drop_table("stock_items")
    op.drop_table("market_orders")
    op.drop_table("incoming_events")
