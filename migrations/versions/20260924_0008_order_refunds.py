"""order refunds: who refunded an order, when, and why

Revision ID: 0008_order_refunds
Revises: 0007_platform_categories
Create Date: 2026-09-24

Until now a refund was a single write, `payment_status = 'REFUNDED'`, made as a
side effect of a vendor rejecting a paid order. The admin console adds a
Refund button of its own, and a money movement an operator triggers by hand
needs an audit trail: the dispute that follows is always "who gave this money
back, and on what grounds?".

Three nullable columns rather than a refunds table: an order is refunded in
full or not at all (no gateway supports partial refunds yet), so there is at
most one refund per order and a separate table would only add a join.

The constraint runs one way. A refund record implies REFUNDED, but REFUNDED
does not imply a record: orders refunded before this migration have none, and
backfilling an actor would invent one.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_order_refunds"
down_revision: str | None = "0007_platform_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE orders
            ADD COLUMN refunded_at   timestamptz,
            ADD COLUMN refunded_by   uuid,
            ADD COLUMN refund_reason varchar(255),
            ADD CONSTRAINT fk_orders_refunded_by FOREIGN KEY (refunded_by)
                REFERENCES users(id) ON DELETE SET NULL,
            ADD CONSTRAINT ck_orders_refund_status CHECK (
                refunded_at IS NULL OR payment_status = 'REFUNDED'
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE orders
            DROP CONSTRAINT IF EXISTS ck_orders_refund_status,
            DROP CONSTRAINT IF EXISTS fk_orders_refunded_by,
            DROP COLUMN IF EXISTS refund_reason,
            DROP COLUMN IF EXISTS refunded_by,
            DROP COLUMN IF EXISTS refunded_at
        """
    )
