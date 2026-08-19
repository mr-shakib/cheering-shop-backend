"""vendor operations: payouts, hours, promotions, handoff code

Revision ID: 0004_vendor_operations
Revises: 0003_vendor_applications
Create Date: 2026-08-19

Four things the vendor app's screens need that the schema could not hold:

* **vendor_payouts** — the Withdraw flow had no ledger, so earnings could be
  displayed but never leave the platform.
* **restaurants.business_hours** — the Business Hour screen had nowhere to
  save. Informational only until a scheduler exists.
* **promo_codes** grows FREE_DELIVERY, a budget cap and per-item scoping — the
  Promotions screens offer all three and the table had none of them.
* **orders.rider_pin_cipher** — the handoff screen shows the code to the
  vendor while the order is READY; an HMAC alone cannot be displayed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_vendor_operations"
down_revision: str | None = "0003_vendor_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TYPE payout_method AS ENUM ('BANK', 'BKASH', 'NAGAD', 'ROCKET');
CREATE TYPE payout_status AS ENUM ('PROCESSING', 'COMPLETED', 'FAILED');

-- One row per withdrawal request. Balance is always derived
-- (delivered earnings - non-FAILED payouts), never stored.
CREATE TABLE vendor_payouts (
    id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id  uuid         NOT NULL REFERENCES restaurants(id) ON DELETE RESTRICT,
    reference      varchar(20)  NOT NULL UNIQUE,          -- e.g. CHR64445654
    amount         bigint       NOT NULL,                 -- paisa
    method         payout_method NOT NULL,
    account_number varchar(50)  NOT NULL,
    account_name   varchar(150) NOT NULL,
    bank_name      varchar(150),
    branch_name    varchar(150),
    status         payout_status NOT NULL DEFAULT 'PROCESSING',
    failure_reason text,
    processed_by   uuid         REFERENCES users(id) ON DELETE SET NULL,
    processed_at   timestamptz,
    created_at     timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT ck_vendor_payouts_amount CHECK (amount > 0)
);
CREATE INDEX ix_vendor_payouts_restaurant ON vendor_payouts (restaurant_id, created_at DESC);
-- The finance work queue.
CREATE INDEX ix_vendor_payouts_processing ON vendor_payouts (created_at ASC)
    WHERE status = 'PROCESSING';

-- Business Hour screen. Informational: nothing flips restaurants.status
-- from it — the manual OPEN/CLOSED toggle remains the only real switch.
ALTER TABLE restaurants ADD COLUMN business_hours jsonb;

-- Vendor promotions on top of promo_codes.
ALTER TABLE promo_codes ADD COLUMN budget_cap bigint;
ALTER TABLE promo_codes ADD COLUMN applies_to_item_ids uuid[];
ALTER TABLE promo_codes DROP CONSTRAINT ck_promo_value;
ALTER TABLE promo_codes ADD CONSTRAINT ck_promo_value
    CHECK ((discount_type = 'FREE_DELIVERY' AND discount_value = 0) OR discount_value > 0);

-- Handoff screen: the PIN, Fernet-encrypted so it can be shown to the owning
-- vendor while READY. The HMAC column remains what verification checks.
ALTER TABLE orders ADD COLUMN rider_pin_cipher text;
"""


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and
    # alembic wraps migrations in one — hence the autocommit escape hatch.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE discount_type ADD VALUE IF NOT EXISTS 'FREE_DELIVERY'")
    op.execute(DDL)


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS rider_pin_cipher")
    op.execute("ALTER TABLE promo_codes DROP CONSTRAINT IF EXISTS ck_promo_value")
    op.execute(
        "ALTER TABLE promo_codes ADD CONSTRAINT ck_promo_value CHECK (discount_value > 0)"
    )
    op.execute("ALTER TABLE promo_codes DROP COLUMN IF EXISTS applies_to_item_ids")
    op.execute("ALTER TABLE promo_codes DROP COLUMN IF EXISTS budget_cap")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS business_hours")
    op.execute("DROP TABLE IF EXISTS vendor_payouts CASCADE")
    op.execute("DROP TYPE IF EXISTS payout_status CASCADE")
    op.execute("DROP TYPE IF EXISTS payout_method CASCADE")
    # FREE_DELIVERY stays in discount_type: PostgreSQL cannot remove an enum
    # value, and its presence is harmless to older code.
