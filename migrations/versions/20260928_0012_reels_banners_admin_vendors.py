"""reels, app banners, and vendors onboarded by an administrator

Revision ID: 0012_reels_banners
Revises: 0011_add_on_quantities
Create Date: 2026-09-28

* **reels**: short videos a restaurant posts, shown in the customer app's Reels
  feed. A vendor uploads their own; an administrator can upload for any
  restaurant and hide one without deleting it.
* **app_banners**: the promotional banners at the top of the customer app,
  managed from the admin console. Media is an image, a GIF or a Lottie
  animation (JSON), and each banner can open a restaurant, a category or a URL.
* **vendor_applications** doubles as a vendor's partner record: business type,
  NID and documents live there and nowhere else. A vendor an administrator
  adds directly gets one too, marked `source = 'ADMIN'`. Such a vendor never
  ticked the in-app terms box and may have no NID on file yet, so the terms
  check now applies to self-submitted applications only and `national_id` may
  be empty. Existing rows are all `APPLICATION` and keep both guarantees.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_reels_banners"
down_revision: str | None = "0011_add_on_quantities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vendor_applications
            ADD COLUMN source varchar(20) NOT NULL DEFAULT 'APPLICATION',
            ALTER COLUMN national_id DROP NOT NULL,
            DROP CONSTRAINT ck_vendor_applications_terms,
            ADD CONSTRAINT ck_vendor_applications_terms CHECK (agreed_to_terms OR source = 'ADMIN'),
            ADD CONSTRAINT ck_vendor_applications_source CHECK (source IN ('APPLICATION', 'ADMIN'));

        CREATE TABLE reels (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            restaurant_id    uuid         NOT NULL,
            video_url        text         NOT NULL,
            thumbnail_url    text,
            caption          varchar(300),
            duration_seconds smallint,
            menu_item_id     uuid,
            uploaded_by      uuid,
            is_hidden        boolean      NOT NULL DEFAULT false,
            hidden_reason    varchar(255),
            created_at       timestamptz  NOT NULL DEFAULT now(),
            updated_at       timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT fk_reels_restaurant FOREIGN KEY (restaurant_id)
                REFERENCES restaurants(id) ON DELETE CASCADE,
            CONSTRAINT fk_reels_menu_item FOREIGN KEY (menu_item_id)
                REFERENCES menu_items(id) ON DELETE SET NULL,
            CONSTRAINT fk_reels_uploaded_by FOREIGN KEY (uploaded_by)
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_reels_duration CHECK (duration_seconds IS NULL OR duration_seconds > 0)
        );
        CREATE INDEX ix_reels_feed ON reels (created_at DESC) WHERE NOT is_hidden;
        CREATE INDEX ix_reels_restaurant ON reels (restaurant_id, created_at DESC);
        CREATE TRIGGER trg_reels_updated_at BEFORE UPDATE ON reels
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE app_banners (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title        varchar(120) NOT NULL,
            media_url    text         NOT NULL,
            media_type   varchar(10)  NOT NULL,
            placement    varchar(40)  NOT NULL DEFAULT 'HOME',
            action_type  varchar(20)  NOT NULL DEFAULT 'NONE',
            action_value text,
            sort_order   integer      NOT NULL DEFAULT 0,
            is_active    boolean      NOT NULL DEFAULT true,
            starts_at    timestamptz,
            ends_at      timestamptz,
            created_by   uuid,
            created_at   timestamptz  NOT NULL DEFAULT now(),
            updated_at   timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT fk_app_banners_created_by FOREIGN KEY (created_by)
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_app_banners_media_type CHECK (media_type IN ('IMAGE', 'GIF', 'LOTTIE')),
            CONSTRAINT ck_app_banners_action CHECK (
                action_type IN ('NONE', 'RESTAURANT', 'CATEGORY', 'URL')
                AND (action_type = 'NONE' OR action_value IS NOT NULL)
            ),
            CONSTRAINT ck_app_banners_window CHECK (
                starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at
            )
        );
        CREATE INDEX ix_app_banners_placement ON app_banners (placement, sort_order)
            WHERE is_active;
        CREATE TRIGGER trg_app_banners_updated_at BEFORE UPDATE ON app_banners
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    # Restoring NOT NULL / the strict terms check fails while admin-onboarded
    # rows exist; that is the correct outcome, since dropping them would
    # delete vendors' records.
    op.execute(
        """
        DROP TABLE IF EXISTS app_banners;
        DROP TABLE IF EXISTS reels;
        ALTER TABLE vendor_applications
            DROP CONSTRAINT IF EXISTS ck_vendor_applications_source,
            DROP CONSTRAINT ck_vendor_applications_terms,
            ADD CONSTRAINT ck_vendor_applications_terms CHECK (agreed_to_terms),
            ALTER COLUMN national_id SET NOT NULL,
            DROP COLUMN IF EXISTS source;
        """
    )
