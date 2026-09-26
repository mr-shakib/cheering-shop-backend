"""admin operations: settings, riders, support, notifications, invitations,
ad tracking, community

Revision ID: 0010_admin_operations
Revises: 0009_admin_catalog
Create Date: 2026-09-26

Everything the rest of the admin console needs, in one additive migration.
Nothing here changes an existing column's meaning.

* **platform_settings** is a single row (`id = 1`). Every tunable is nullable
  and NULL means "use the server configuration", so deploying this changes no
  price until an administrator saves a value.
* **Riders** gain the identity fields the rider profile screen shows (date of
  birth, NID, documents, payout details), an incentives ledger, and payouts of
  their own. A rider's balance is derived exactly like a vendor's: earnings
  minus payouts not FAILED, never stored.
* **rider_applications** is the rider twin of vendor_applications. Unlike a
  vendor application it creates no account at submission: a courier account is
  only minted when an administrator approves.
* **support_tickets / support_messages** back Support Ticket and Live Chat.
  EVENT rows in the message table are the ticket's history ("assigned",
  "closed"), so one ordered read gives the whole thread.
* **notification_campaigns / user_notifications**: a campaign fans out into
  one inbox row per recipient when it is sent. The inbox works whether or not
  push is configured; push is best effort on top.
* **admin_invitations**: the only way to make a second administrator without
  shell access. Only a SHA-256 of the token is stored.
* **promo_codes** gain impression and click counters for the Advertisement
  screen.
* **community_posts / community_reports** back the Community screen.
  `report_count` is denormalised so the moderation queue sorts without a join.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_admin_operations"
down_revision: str | None = "0009_admin_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
-- Settings ------------------------------------------------------------------
CREATE TABLE platform_settings (
    id                          smallint PRIMARY KEY DEFAULT 1,
    app_name                    varchar(80),
    support_email               varchar(254),
    support_phone               varchar(20),
    delivery_base_fee           bigint,
    delivery_per_km_fee         bigint,
    delivery_min_fee            bigint,
    restaurant_commission_rate  numeric(5,4),
    grocery_commission_rate     numeric(5,4),
    pharmacy_commission_rate    numeric(5,4),
    rain_surcharge              bigint  NOT NULL DEFAULT 0,
    rain_surcharge_active       boolean NOT NULL DEFAULT false,
    heatwave_fee                bigint  NOT NULL DEFAULT 0,
    heatwave_fee_active         boolean NOT NULL DEFAULT false,
    high_demand_fee             bigint  NOT NULL DEFAULT 0,
    high_demand_fee_active      boolean NOT NULL DEFAULT false,
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    updated_by                  uuid,
    CONSTRAINT ck_platform_settings_singleton CHECK (id = 1),
    CONSTRAINT fk_platform_settings_updated_by FOREIGN KEY (updated_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_platform_settings_money CHECK (
        coalesce(delivery_base_fee, 0) >= 0 AND coalesce(delivery_per_km_fee, 0) >= 0
        AND coalesce(delivery_min_fee, 0) >= 0 AND rain_surcharge >= 0
        AND heatwave_fee >= 0 AND high_demand_fee >= 0
    ),
    CONSTRAINT ck_platform_settings_rates CHECK (
        coalesce(restaurant_commission_rate, 0) BETWEEN 0 AND 1
        AND coalesce(grocery_commission_rate, 0) BETWEEN 0 AND 1
        AND coalesce(pharmacy_commission_rate, 0) BETWEEN 0 AND 1
    )
);
INSERT INTO platform_settings (id) VALUES (1);

-- Riders --------------------------------------------------------------------
ALTER TABLE rider_profiles
    ADD COLUMN date_of_birth date,
    ADD COLUMN national_id   varchar(50),
    ADD COLUMN documents     jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN payout        jsonb NOT NULL DEFAULT '{}';

CREATE TABLE rider_incentives (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rider_id    uuid         NOT NULL,
    amount      bigint       NOT NULL,
    reason      varchar(255) NOT NULL,
    created_by  uuid,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_rider_incentives_rider FOREIGN KEY (rider_id)
        REFERENCES rider_profiles(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_rider_incentives_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_rider_incentives_amount CHECK (amount > 0)
);
CREATE INDEX ix_rider_incentives_rider ON rider_incentives (rider_id, created_at DESC);

CREATE TABLE rider_payouts (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rider_id       uuid          NOT NULL,
    reference      varchar(20)   NOT NULL,
    amount         bigint        NOT NULL,
    method         payout_method NOT NULL,
    account_number varchar(50)   NOT NULL,
    account_name   varchar(150)  NOT NULL,
    bank_name      varchar(150),
    branch_name    varchar(150),
    status         payout_status NOT NULL DEFAULT 'PROCESSING',
    failure_reason text,
    processed_by   uuid,
    processed_at   timestamptz,
    reopened_at    timestamptz,
    reopened_by    uuid,
    reopen_reason  text,
    created_at     timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT uq_rider_payouts_reference UNIQUE (reference),
    CONSTRAINT fk_rider_payouts_rider FOREIGN KEY (rider_id)
        REFERENCES rider_profiles(user_id) ON DELETE RESTRICT,
    CONSTRAINT fk_rider_payouts_processed_by FOREIGN KEY (processed_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_rider_payouts_reopened_by FOREIGN KEY (reopened_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_rider_payouts_amount CHECK (amount > 0)
);
CREATE INDEX ix_rider_payouts_rider ON rider_payouts (rider_id, created_at DESC);
CREATE INDEX ix_rider_payouts_processing ON rider_payouts (created_at ASC)
    WHERE status = 'PROCESSING';

CREATE TABLE rider_applications (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_no varchar(20)  NOT NULL,
    full_name      varchar(150) NOT NULL,
    email          citext       NOT NULL,
    phone          varchar(20)  NOT NULL,
    vehicle_type   varchar(40)  NOT NULL,
    license_number varchar(60),
    date_of_birth  date         NOT NULL,
    national_id    varchar(50)  NOT NULL,
    documents      jsonb        NOT NULL DEFAULT '{}',
    payout         jsonb        NOT NULL DEFAULT '{}',
    status         vendor_application_status NOT NULL DEFAULT 'PENDING',
    review_note    text,
    reviewed_by    uuid,
    reviewed_at    timestamptz,
    user_id        uuid,
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_rider_applications_no UNIQUE (application_no),
    CONSTRAINT fk_rider_applications_reviewed_by FOREIGN KEY (reviewed_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_rider_applications_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX ix_rider_applications_queue ON rider_applications (status, created_at ASC);
CREATE INDEX ix_rider_applications_email ON rider_applications (email);
CREATE TRIGGER trg_rider_applications_updated_at BEFORE UPDATE ON rider_applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Support -------------------------------------------------------------------
CREATE TABLE support_tickets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_number   bigint GENERATED BY DEFAULT AS IDENTITY,
    user_id         uuid         NOT NULL,
    subject         varchar(200) NOT NULL,
    type            varchar(30)  NOT NULL,
    priority        varchar(10)  NOT NULL DEFAULT 'MEDIUM',
    status          varchar(10)  NOT NULL DEFAULT 'OPEN',
    order_id        uuid,
    assigned_to     uuid,
    unread_by_staff boolean      NOT NULL DEFAULT true,
    unread_by_user  boolean      NOT NULL DEFAULT false,
    last_message_at timestamptz  NOT NULL DEFAULT now(),
    resolved_at     timestamptz,
    closed_at       timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_support_tickets_number UNIQUE (ticket_number),
    CONSTRAINT fk_support_tickets_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_support_tickets_order FOREIGN KEY (order_id)
        REFERENCES orders(id) ON DELETE SET NULL,
    CONSTRAINT fk_support_tickets_assigned_to FOREIGN KEY (assigned_to)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_support_tickets_type CHECK (type IN (
        'ORDER_ISSUE', 'RIDER_COMPLAINT', 'VENDOR_COMPLAINT', 'PAYMENT', 'REFUND',
        'ACCOUNT', 'OTHER'
    )),
    CONSTRAINT ck_support_tickets_priority CHECK (
        priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')
    ),
    CONSTRAINT ck_support_tickets_status CHECK (
        status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')
    )
);
CREATE INDEX ix_support_tickets_queue ON support_tickets (status, last_message_at DESC);
CREATE INDEX ix_support_tickets_user ON support_tickets (user_id, created_at DESC);
CREATE TRIGGER trg_support_tickets_updated_at BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE support_messages (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   uuid        NOT NULL,
    kind        varchar(10) NOT NULL DEFAULT 'MESSAGE',
    sender_id   uuid,
    sender_role user_role,
    body        text        NOT NULL,
    attachments jsonb       NOT NULL DEFAULT '[]',
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_support_messages_ticket FOREIGN KEY (ticket_id)
        REFERENCES support_tickets(id) ON DELETE CASCADE,
    CONSTRAINT fk_support_messages_sender FOREIGN KEY (sender_id)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_support_messages_kind CHECK (kind IN ('MESSAGE', 'EVENT'))
);
CREATE INDEX ix_support_messages_ticket ON support_messages (ticket_id, created_at);

-- Notifications -------------------------------------------------------------
CREATE TABLE notification_campaigns (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title           varchar(120) NOT NULL,
    message         varchar(500) NOT NULL,
    type            varchar(20)  NOT NULL,
    audience        varchar(20)  NOT NULL,
    status          varchar(20)  NOT NULL DEFAULT 'SCHEDULED',
    scheduled_for   timestamptz  NOT NULL,
    sent_at         timestamptz,
    recipient_count integer      NOT NULL DEFAULT 0,
    push_sent_count integer      NOT NULL DEFAULT 0,
    failure_reason  text,
    created_by      uuid,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_notification_campaigns_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_notification_campaigns_type CHECK (
        type IN ('PROMOTION', 'ALERT', 'UPDATE')
    ),
    CONSTRAINT ck_notification_campaigns_audience CHECK (
        audience IN ('CUSTOMER', 'VENDOR', 'RIDER', 'ALL')
    ),
    CONSTRAINT ck_notification_campaigns_status CHECK (
        status IN ('SCHEDULED', 'SENT', 'FAILED', 'CANCELLED')
    )
);
CREATE INDEX ix_notification_campaigns_due ON notification_campaigns (scheduled_for)
    WHERE status = 'SCHEDULED';

CREATE TABLE user_notifications (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid         NOT NULL,
    campaign_id uuid,
    title       varchar(120) NOT NULL,
    message     varchar(500) NOT NULL,
    type        varchar(20)  NOT NULL,
    read_at     timestamptz,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_user_notifications_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_notifications_campaign FOREIGN KEY (campaign_id)
        REFERENCES notification_campaigns(id) ON DELETE CASCADE
);
CREATE INDEX ix_user_notifications_user ON user_notifications (user_id, created_at DESC);

-- Admin invitations -----------------------------------------------------------
CREATE TABLE admin_invitations (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email            citext       NOT NULL,
    full_name        varchar(150),
    token_hash       varchar(64)  NOT NULL,
    invited_by       uuid,
    expires_at       timestamptz  NOT NULL,
    accepted_at      timestamptz,
    accepted_user_id uuid,
    revoked_at       timestamptz,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_admin_invitations_token UNIQUE (token_hash),
    CONSTRAINT fk_admin_invitations_invited_by FOREIGN KEY (invited_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_admin_invitations_accepted_user FOREIGN KEY (accepted_user_id)
        REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX ix_admin_invitations_email ON admin_invitations (email);

-- Ad tracking -----------------------------------------------------------------
ALTER TABLE promo_codes
    ADD COLUMN impressions bigint NOT NULL DEFAULT 0,
    ADD COLUMN clicks      bigint NOT NULL DEFAULT 0;

-- Community -------------------------------------------------------------------
CREATE TABLE community_posts (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id      uuid          NOT NULL,
    body           varchar(2000) NOT NULL,
    image_urls     text[]        NOT NULL DEFAULT '{}',
    restaurant_id  uuid,
    report_count   integer       NOT NULL DEFAULT 0,
    removed_at     timestamptz,
    removed_by     uuid,
    removal_reason varchar(255),
    created_at     timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT fk_community_posts_author FOREIGN KEY (author_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_community_posts_restaurant FOREIGN KEY (restaurant_id)
        REFERENCES restaurants(id) ON DELETE SET NULL,
    CONSTRAINT fk_community_posts_removed_by FOREIGN KEY (removed_by)
        REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_community_posts_reports CHECK (report_count >= 0)
);
CREATE INDEX ix_community_posts_feed ON community_posts (created_at DESC)
    WHERE removed_at IS NULL;
CREATE INDEX ix_community_posts_author ON community_posts (author_id, created_at DESC);

CREATE TABLE community_reports (
    post_id     uuid         NOT NULL,
    reporter_id uuid         NOT NULL,
    reason      varchar(255),
    created_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_community_reports PRIMARY KEY (post_id, reporter_id),
    CONSTRAINT fk_community_reports_post FOREIGN KEY (post_id)
        REFERENCES community_posts(id) ON DELETE CASCADE,
    CONSTRAINT fk_community_reports_reporter FOREIGN KEY (reporter_id)
        REFERENCES users(id) ON DELETE CASCADE
);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS community_reports;
        DROP TABLE IF EXISTS community_posts;
        ALTER TABLE promo_codes DROP COLUMN IF EXISTS clicks, DROP COLUMN IF EXISTS impressions;
        DROP TABLE IF EXISTS admin_invitations;
        DROP TABLE IF EXISTS user_notifications;
        DROP TABLE IF EXISTS notification_campaigns;
        DROP TABLE IF EXISTS support_messages;
        DROP TABLE IF EXISTS support_tickets;
        DROP TABLE IF EXISTS rider_applications;
        DROP TABLE IF EXISTS rider_payouts;
        DROP TABLE IF EXISTS rider_incentives;
        ALTER TABLE rider_profiles
            DROP COLUMN IF EXISTS payout,
            DROP COLUMN IF EXISTS documents,
            DROP COLUMN IF EXISTS national_id,
            DROP COLUMN IF EXISTS date_of_birth;
        DROP TABLE IF EXISTS platform_settings;
        """
    )
