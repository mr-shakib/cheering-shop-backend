"""account self-deletion

Revision ID: 0014_account_deletion
Revises: 0013_priority_delivery_hours
Create Date: 2026-10-15

* **users.deleted_at**: set when the owner deletes their account
  (`DELETE /users/me`). The row itself stays: orders reference it with
  ON DELETE RESTRICT, and completed orders are records we must keep. What
  the row held about the person (email, phone, name, photo, credentials) is
  wiped in the same transaction.
* **ck_users_identifier** now lets a deleted account have neither an email
  nor a phone. Every live account still needs one.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_account_deletion"
down_revision: str | None = "0013_priority_delivery_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN deleted_at timestamptz,
            DROP CONSTRAINT ck_users_identifier,
            ADD CONSTRAINT ck_users_identifier
                CHECK (email IS NOT NULL OR phone IS NOT NULL OR deleted_at IS NOT NULL);
        """
    )


def downgrade() -> None:
    # A deleted account has no identifier left, so the old check cannot hold
    # for it. Give each one an address on the reserved .invalid domain (RFC
    # 2606): unique, and never deliverable.
    op.execute(
        """
        UPDATE users SET email = 'deleted-' || id || '@deleted.invalid'
            WHERE deleted_at IS NOT NULL AND email IS NULL AND phone IS NULL;

        ALTER TABLE users
            DROP CONSTRAINT ck_users_identifier,
            ADD CONSTRAINT ck_users_identifier CHECK (email IS NOT NULL OR phone IS NOT NULL),
            DROP COLUMN deleted_at;
        """
    )
