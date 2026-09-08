"""Identity and security tables."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKey
from app.models.enums import (
    BiometricAlgorithmType,
    DevicePlatformType,
    OtpPurposeType,
    UserRoleType,
)
from app.models.types import CIText


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"

    role: Mapped[str] = mapped_column(UserRoleType, nullable=False)
    email: Mapped[str | None] = mapped_column(CIText(), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(String(150))
    avatar_url: Mapped[str | None] = mapped_column(Text)

    # Surface behind GET /users/me/security
    is_2fa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    totp_secret: Mapped[str | None] = mapped_column(Text)
    totp_pending_secret: Mapped[str | None] = mapped_column(Text)
    is_biometrics_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    addresses: Mapped[list["Address"]] = relationship(back_populates="user", lazy="raise")  # noqa: F821
    restaurant: Mapped["Restaurant | None"] = relationship(  # noqa: F821
        back_populates="owner", lazy="raise", uselist=False
    )

    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_users_identifier"),
        CheckConstraint(
            "NOT is_2fa_enabled OR totp_secret IS NOT NULL", name="ck_users_2fa_secret"
        ),
        # Target for the composite role-guard FKs on restaurants / orders /
        # rider_profiles. This is what makes the §7 permission matrix a
        # property of the data rather than a convention.
        UniqueConstraint("id", "role", name="uq_users_id_role"),
        Index("ix_users_role", "role", postgresql_where=text("is_active")),
    )


class BiometricCredential(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Device-bound public keys for POST /auth/biometrics/enable."""

    __tablename__ = "biometric_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120))
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(
        BiometricAlgorithmType, nullable=False, server_default=text("'ES256'")
    )
    failed_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_biometric_user_device"),)


class AuthIdentity(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] A federated login linked to a local account.

    A separate table rather than `google_id`/`apple_id` columns on `users`,
    because the relationship is one-to-many in both directions that matter: a
    user may link several providers, and adding Apple sign-in (which the App
    Store requires of any iOS app offering Google) must be a row, not another
    migration against the identity table.

    `subject` is the provider's stable user id -- Google's `sub` claim. It is
    the join key, NOT the email: Google Workspace addresses get renamed and
    consumer accounts can change their primary address, and matching on email
    would either lose the link or, worse, follow a recycled address onto
    somebody else's account. Email is stored alongside only for support
    lookups.
    """

    __tablename__ = "auth_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(CIText())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The uniqueness that matters. Without it a race between two concurrent
        # first-time sign-ins would link the same Google account twice.
        UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"),
        # One link per provider per user: signing in with Google twice updates
        # the existing row instead of accumulating duplicates.
        UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
        # A CHECK rather than a native enum so adding 'apple' is a constraint
        # edit and not an ALTER TYPE, which cannot run inside a transaction on
        # older Postgres and so complicates every deploy that touches it.
        CheckConstraint("provider IN ('google', 'apple')", name="ck_auth_identity_provider"),
        # "Which providers has this user linked?" — read by GET /users/me/security.
        Index("ix_auth_identities_user", "user_id"),
    )


class UserDevice(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] FCM tokens — spec §9."""

    __tablename__ = "user_devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(DevicePlatformType, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_user_devices_user", "user_id", postgresql_where=text("is_active")),)


class RefreshToken(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Rotation store. Hashes only — a dump yields no usable tokens."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)

    __table_args__ = (
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class OtpCode(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Shared by /auth/otp/* and /auth/password/*."""

    __tablename__ = "otp_codes"

    identifier: Mapped[str] = mapped_column(CIText(), nullable=False)
    purpose: Mapped[str] = mapped_column(OtpPurposeType, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_otp_attempts"),
        Index("ix_otp_lookup", "identifier", "purpose", text("created_at DESC")),
    )


class IdempotencyKey(Base):
    """[EXTENDED] Spec §9 — prevents double order creation on flaky mobile networks."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    # Rejects reuse of a key with a *different* body, which would otherwise
    # return the first call's response for a materially different request.
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_idempotency_expiry", "expires_at"),)
