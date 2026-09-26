"""admin catalog: commission at every level, product moderation, payout reopen

Revision ID: 0009_admin_catalog
Revises: 0008_order_refunds
Create Date: 2026-09-26

Three things the admin console needs from the schema.

**Commission at every level.** Until now the only rate was
`restaurants.commission_rate`. The console sets it per product and per browse
category too, and the business wants all three available rather than one
replacing the others. They are nullable here; a NULL means "not set at this
level". Each order line is charged at the most specific rate that is set --
product, then its section's category, then the restaurant -- and the order
still snapshots the resulting total in `orders.commission_amount` (D6), so
changing any of the three never restates a past order.

**Product moderation.** `is_available` is the vendor's sold-out switch and
flips all day. Hiding a dish that should not be on the platform is a different
decision, made by someone else, that the vendor must not be able to undo, so it
is its own column. `is_featured` is the console's Featured button.

**Categories get a kind.** The console splits categories into Restaurant and
Store tabs; everything that exists today is restaurant food, so that is the
default.

**Payouts can be reopened.** Marking a payout COMPLETED is a claim that money
left; an operator who clicked it by mistake, or whose transfer later bounced,
needs to take the claim back. Reopening returns the payout to PROCESSING, which
the balance formula already deducts, so the vendor's balance does not move --
only the status and the audit trail do.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_admin_catalog"
down_revision: str | None = "0008_order_refunds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE menu_items
            ADD COLUMN commission_rate numeric(5,4),
            ADD COLUMN is_hidden   boolean NOT NULL DEFAULT false,
            ADD COLUMN is_featured boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_menu_items_commission CHECK (
                commission_rate IS NULL OR commission_rate BETWEEN 0 AND 1
            );

        ALTER TABLE categories
            ADD COLUMN commission_rate numeric(5,4),
            ADD COLUMN kind varchar(20) NOT NULL DEFAULT 'RESTAURANT',
            ADD CONSTRAINT ck_categories_commission CHECK (
                commission_rate IS NULL OR commission_rate BETWEEN 0 AND 1
            ),
            ADD CONSTRAINT ck_categories_kind CHECK (kind IN ('RESTAURANT', 'STORE'));

        ALTER TABLE vendor_payouts
            ADD COLUMN reopened_at   timestamptz,
            ADD COLUMN reopened_by   uuid,
            ADD COLUMN reopen_reason text,
            ADD CONSTRAINT fk_vendor_payouts_reopened_by FOREIGN KEY (reopened_by)
                REFERENCES users(id) ON DELETE SET NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE vendor_payouts
            DROP CONSTRAINT IF EXISTS fk_vendor_payouts_reopened_by,
            DROP COLUMN IF EXISTS reopen_reason,
            DROP COLUMN IF EXISTS reopened_by,
            DROP COLUMN IF EXISTS reopened_at;

        ALTER TABLE categories
            DROP CONSTRAINT IF EXISTS ck_categories_kind,
            DROP CONSTRAINT IF EXISTS ck_categories_commission,
            DROP COLUMN IF EXISTS kind,
            DROP COLUMN IF EXISTS commission_rate;

        ALTER TABLE menu_items
            DROP CONSTRAINT IF EXISTS ck_menu_items_commission,
            DROP COLUMN IF EXISTS is_featured,
            DROP COLUMN IF EXISTS is_hidden,
            DROP COLUMN IF EXISTS commission_rate;
        """
    )
