"""add-on quantities: "2× extra cheese", and add-on prices on receipts

Revision ID: 0011_add_on_quantities
Revises: 0010_admin_operations
Create Date: 2026-09-26

An add-on used to be on or off. A customer could not ask for two extra
cheeses, and sending the same add-on twice collided with the cart's primary
key. Each chosen add-on now carries a quantity, capped per add-on by the
vendor (`max_quantity`, 1 unless they raise it).

The quantity is per unit of the line: a line of 2 burgers with 2× cheese is
4 cheeses, priced as (burger + 2 × cheese) × 2.

Existing rows keep meaning what they meant: every default is 1.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_add_on_quantities"
down_revision: str | None = "0010_admin_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE item_add_ons
            ADD COLUMN max_quantity smallint NOT NULL DEFAULT 1,
            ADD CONSTRAINT ck_item_add_ons_max_quantity CHECK (max_quantity BETWEEN 1 AND 20);
        ALTER TABLE cart_item_add_ons
            ADD COLUMN quantity smallint NOT NULL DEFAULT 1,
            ADD CONSTRAINT ck_cart_item_add_ons_quantity CHECK (quantity > 0);
        ALTER TABLE order_item_add_ons
            ADD COLUMN quantity smallint NOT NULL DEFAULT 1,
            ADD CONSTRAINT ck_order_item_add_ons_quantity CHECK (quantity > 0);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE order_item_add_ons
            DROP CONSTRAINT IF EXISTS ck_order_item_add_ons_quantity,
            DROP COLUMN IF EXISTS quantity;
        ALTER TABLE cart_item_add_ons
            DROP CONSTRAINT IF EXISTS ck_cart_item_add_ons_quantity,
            DROP COLUMN IF EXISTS quantity;
        ALTER TABLE item_add_ons
            DROP CONSTRAINT IF EXISTS ck_item_add_ons_max_quantity,
            DROP COLUMN IF EXISTS max_quantity;
        """
    )
