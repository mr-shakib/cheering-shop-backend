"""google sign-in: federated auth identities

Revision ID: 0006_google_sign_in
Revises: 0005_customer_ordering
Create Date: 2026-09-04

Sign in with Google needs somewhere to record "this Google account is this
user". Two options were on the table:

* **Columns on `users`** (`google_id`, later `apple_id`, ...). Cheap today,
  but every new provider is another migration against the busiest table in the
  schema, and the "which providers has this user linked?" query becomes a
  column scan rather than a row count.
* **A join table.** Chosen. Apple sign-in is not optional -- the App Store
  requires it of any iOS app that offers a third-party login -- so a second
  provider is a certainty, not a hypothetical.

The link key is the provider's `sub` claim, never the email address. Google
Workspace addresses are renamed and consumer primary addresses can change; a
link keyed on email would silently break, and a recycled address would resolve
to the wrong account, which is an account-takeover bug rather than a bug.

Purely additive -- no existing table changes shape, so this is safe to apply to
a live database. `users.password_hash` was already nullable (a provisional
OTP user has no password), so a Google-only account needs no change there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_google_sign_in"
down_revision: str | None = "0005_customer_ordering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE auth_identities (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider      varchar(32)  NOT NULL,
    subject       varchar(255) NOT NULL,   -- the provider's stable user id ('sub')
    email         citext,                  -- for support lookups only, never the join key
    last_login_at timestamptz,
    created_at    timestamptz  NOT NULL DEFAULT now(),

    -- Without this, two concurrent first-time sign-ins for the same Google
    -- account both find nothing and both insert, producing two local users
    -- for one person.
    CONSTRAINT uq_auth_identity_provider_subject UNIQUE (provider, subject),
    -- Signing in again updates the existing link instead of accumulating rows.
    CONSTRAINT uq_auth_identity_user_provider UNIQUE (user_id, provider),
    -- A CHECK, not a native enum: adding 'apple' is then a constraint edit
    -- rather than an ALTER TYPE, which cannot run inside a transaction on
    -- older Postgres and complicates every deploy that touches it.
    CONSTRAINT ck_auth_identity_provider CHECK (provider IN ('google', 'apple'))
);

-- "Which providers has this user linked?" -- read by GET /users/me/security so
-- the app can show a Google badge and decide whether unlinking is safe.
CREATE INDEX ix_auth_identities_user ON auth_identities (user_id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_identities CASCADE")
