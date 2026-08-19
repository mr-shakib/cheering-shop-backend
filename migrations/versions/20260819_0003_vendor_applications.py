"""vendor partner applications

Revision ID: 0003_vendor_applications
Revises: 0002_biometric_algorithm
Create Date: 2026-08-19

The partner application form (business info, location, owner identity,
documents, payout details) had nowhere to land: registration wrote a user and a
restaurant and threw the rest of the form away, which left an administrator
approving storefronts with no NID, no trade licence and no payout account to
look at. One row per application; the row is the thing that gets reviewed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_vendor_applications"
down_revision: str | None = "0002_biometric_algorithm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TYPE vendor_application_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED');

CREATE TABLE vendor_applications (
    id                uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    application_no    varchar(20)   NOT NULL UNIQUE,

    user_id           uuid          NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
    restaurant_id     uuid          NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,

    -- Business information (form step 1)
    business_name     varchar(180)  NOT NULL,
    business_type     varchar(40)   NOT NULL,
    business_category varchar(80)   NOT NULL,
    branch_count      smallint      NOT NULL DEFAULT 1,
    cuisine_types     text[]        NOT NULL DEFAULT '{}',

    -- Location (form step 2)
    address_line      text          NOT NULL,
    area              varchar(120),
    latitude          double precision NOT NULL,
    longitude         double precision NOT NULL,

    -- Owner information (form step 3)
    owner_full_name   varchar(150)  NOT NULL,
    owner_email       citext        NOT NULL,
    owner_phone       varchar(20)   NOT NULL,
    national_id       varchar(50)   NOT NULL,

    -- Documents & payout (form step 4)
    documents         jsonb         NOT NULL DEFAULT '{}',
    payout            jsonb         NOT NULL DEFAULT '{}',

    agreed_to_terms   boolean       NOT NULL,

    -- Review
    status            vendor_application_status NOT NULL DEFAULT 'PENDING',
    review_note       text,
    reviewed_by       uuid          REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at       timestamptz,

    created_at        timestamptz   NOT NULL DEFAULT now(),
    updated_at        timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT ck_vendor_applications_branches CHECK (branch_count >= 1),
    CONSTRAINT ck_vendor_applications_lat      CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_vendor_applications_lng      CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_vendor_applications_terms    CHECK (agreed_to_terms)
);

-- The admin queue: pending applications, oldest first.
CREATE INDEX ix_vendor_applications_queue ON vendor_applications (status, created_at ASC);
CREATE INDEX ix_vendor_applications_owner_email ON vendor_applications (owner_email);

CREATE TRIGGER trg_vendor_applications_updated_at BEFORE UPDATE ON vendor_applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vendor_applications CASCADE")
    op.execute("DROP TYPE IF EXISTS vendor_application_status CASCADE")
