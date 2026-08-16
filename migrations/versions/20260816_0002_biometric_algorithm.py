"""add biometric algorithm

Revision ID: 0002_biometric_algorithm
Revises: 0001_initial
Create Date: 2026-08-16

Biometric enrolment stored a public key but recorded nothing about how to
verify against it. iOS Secure Enclave produces P-256 ECDSA only; Android
Keystore can produce either that or Ed25519. Without knowing which, the server
cannot check a signature — so enrolment wrote a key that nothing could read.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_biometric_algorithm"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE biometric_algorithm AS ENUM ('ES256', 'ED25519')")
    op.add_column(
        "biometric_credentials",
        sa.Column(
            "algorithm",
            sa.Enum("ES256", "ED25519", name="biometric_algorithm", create_type=False),
            nullable=False,
            server_default="ES256",
        ),
    )
    # Counts consecutive failed signature checks; reset on success.
    op.add_column(
        "biometric_credentials",
        sa.Column("failed_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("biometric_credentials", "failed_attempts")
    op.drop_column("biometric_credentials", "algorithm")
    op.execute("DROP TYPE IF EXISTS biometric_algorithm")
