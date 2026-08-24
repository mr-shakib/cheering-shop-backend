"""customer ordering: scheduled delivery and order chat

Revision ID: 0005_customer_ordering
Revises: 0004_vendor_operations
Create Date: 2026-08-24

Two things the customer app's screens need that the schema could not hold:

* **orders.scheduled_for** — the Schedule Order sheet lets a customer book a
  delivery window days ahead. Nullable, because "as soon as possible" is the
  overwhelming majority of orders and defaulting it to placed_at would destroy
  the ability to ask whether an order was scheduled at all. A scheduled order
  also carries a NULL auto_decline_at: the 60-second vendor countdown starts
  when the kitchen is asked, not when the customer books.

* **order_messages** — the Message screen had nowhere to write. There is no
  thread table on purpose: the order IS the thread, so the channel's lifetime
  is the order's lifetime and a delivered order's chat closes on its own. A
  standing channel to a stranger's device is a safety problem, not a feature.

Both are additive. Nothing existing changes shape, so this migration is safe to
apply to a database with live orders in it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_customer_ordering"
down_revision: str | None = "0004_vendor_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
-- Scheduled delivery. NULL = deliver as soon as possible.
ALTER TABLE orders ADD COLUMN scheduled_for timestamptz;

-- The vendor's scheduled-order queue: what is due soon, oldest first. Partial,
-- so it stays tiny however many ASAP orders the table accumulates.
CREATE INDEX ix_orders_scheduled ON orders (scheduled_for ASC)
    WHERE scheduled_for IS NOT NULL AND status = 'PENDING';

-- One thread per order. actor_type already exists (created in 0001), so the
-- column reuses it rather than declaring a second enum with the same members.
CREATE TABLE order_messages (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    sender_id   uuid        NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    sender_role actor_type  NOT NULL,
    body        varchar(2000) NOT NULL,
    -- Per-message rather than a per-thread high-water mark, so the read ticks
    -- on each bubble are exact rather than inferred.
    read_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_order_messages_body CHECK (length(btrim(body)) > 0),
    CONSTRAINT ck_order_messages_role CHECK (
        sender_role IN ('CUSTOMER', 'VENDOR', 'RIDER', 'ADMIN', 'SYSTEM')
    )
);

-- The thread read: this order's messages, oldest first.
CREATE INDEX ix_order_messages_thread ON order_messages (order_id, created_at);
-- The unread badge — a count over a tiny partial index, not a thread scan.
CREATE INDEX ix_order_messages_unread ON order_messages (order_id, sender_role)
    WHERE read_at IS NULL;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_messages CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_orders_scheduled")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS scheduled_for")
