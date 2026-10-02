"""priority delivery, and business hours that open and close the store

Revision ID: 0013_priority_delivery_hours
Revises: 0012_reels_banners
Create Date: 2026-10-03

* **orders.delivery_type / priority_fee**: checkout's Standard / Priority
  choice. Priority adds a flat fee the rider earns in full; it is part of the
  bill, so `ck_orders_total_math` now counts it. Existing orders are all
  STANDARD with no priority fee, which satisfies every new constraint.
* **platform_settings.priority_delivery_fee**: the admin override for that
  fee. NULL falls back to the server configuration, like the other fees.
* **restaurants.scheduled_open**: what the business hours said when they last
  set `status`. NULL for every restaurant now, so the worker's first pass
  applies each restaurant's hours straight away: a store whose hours say it
  is open right now opens on deploy.

Tax and packaging are no longer charged, but their order columns stay: orders
placed before this were charged them, and the total-math check must still
hold for those rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_priority_delivery_hours"
down_revision: str | None = "0012_reels_banners"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE orders
            ADD COLUMN priority_fee bigint NOT NULL DEFAULT 0,
            ADD COLUMN delivery_type varchar(10) NOT NULL DEFAULT 'STANDARD',
            DROP CONSTRAINT ck_orders_money_nonneg,
            ADD CONSTRAINT ck_orders_money_nonneg CHECK (
                item_total >= 0 AND delivery_fee >= 0 AND discount >= 0
                AND tip >= 0 AND packaging_fee >= 0 AND tax_amount >= 0
                AND platform_fee >= 0 AND commission_amount >= 0 AND grand_total >= 0
                AND priority_fee >= 0
            ),
            DROP CONSTRAINT ck_orders_total_math,
            ADD CONSTRAINT ck_orders_total_math CHECK (
                grand_total = item_total + delivery_fee + priority_fee + packaging_fee
                            + tax_amount + platform_fee + tip - discount
            ),
            ADD CONSTRAINT ck_orders_delivery_type
                CHECK (delivery_type IN ('STANDARD', 'PRIORITY')),
            ADD CONSTRAINT ck_orders_priority_fee
                CHECK (delivery_type = 'PRIORITY' OR priority_fee = 0);

        ALTER TABLE platform_settings
            ADD COLUMN priority_delivery_fee bigint,
            DROP CONSTRAINT ck_platform_settings_money,
            ADD CONSTRAINT ck_platform_settings_money CHECK (
                coalesce(delivery_base_fee, 0) >= 0 AND coalesce(delivery_per_km_fee, 0) >= 0
                AND coalesce(delivery_min_fee, 0) >= 0
                AND coalesce(priority_delivery_fee, 0) >= 0 AND rain_surcharge >= 0
                AND heatwave_fee >= 0 AND high_demand_fee >= 0
            );

        ALTER TABLE restaurants ADD COLUMN scheduled_open boolean;
        """
    )


def downgrade() -> None:
    # Priority orders cannot survive the old total-math check with their fee
    # removed, so the fee is folded into the delivery fee: the total stays
    # exactly what the customer paid, and the rider still earns it.
    op.execute(
        """
        ALTER TABLE restaurants DROP COLUMN scheduled_open;

        ALTER TABLE platform_settings
            DROP CONSTRAINT ck_platform_settings_money,
            DROP COLUMN priority_delivery_fee,
            ADD CONSTRAINT ck_platform_settings_money CHECK (
                coalesce(delivery_base_fee, 0) >= 0 AND coalesce(delivery_per_km_fee, 0) >= 0
                AND coalesce(delivery_min_fee, 0) >= 0 AND rain_surcharge >= 0
                AND heatwave_fee >= 0 AND high_demand_fee >= 0
            );

        ALTER TABLE orders
            DROP CONSTRAINT ck_orders_priority_fee,
            DROP CONSTRAINT ck_orders_delivery_type,
            DROP CONSTRAINT ck_orders_total_math,
            DROP CONSTRAINT ck_orders_money_nonneg;
        UPDATE orders SET delivery_fee = delivery_fee + priority_fee WHERE priority_fee > 0;
        ALTER TABLE orders
            DROP COLUMN delivery_type,
            DROP COLUMN priority_fee,
            ADD CONSTRAINT ck_orders_money_nonneg CHECK (
                item_total >= 0 AND delivery_fee >= 0 AND discount >= 0
                AND tip >= 0 AND packaging_fee >= 0 AND tax_amount >= 0
                AND platform_fee >= 0 AND commission_amount >= 0 AND grand_total >= 0
            ),
            ADD CONSTRAINT ck_orders_total_math CHECK (
                grand_total = item_total + delivery_fee + packaging_fee
                            + tax_amount + platform_fee + tip - discount
            );
        """
    )
