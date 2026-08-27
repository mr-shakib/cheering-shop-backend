"""Application settings.

Every value is environment-driven. Secrets have NO defaults — the app refuses to
start without them rather than silently running on a well-known development key.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Application -------------------------------------------------------
    ENVIRONMENT: Literal["local", "test", "staging", "production"] = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"  # spec §2: versioned via URL path
    PROJECT_NAME: str = "CR Shop API"
    # None = derive from ENVIRONMENT (see docs_enabled). Set true/false to force.
    ENABLE_DOCS: bool | None = None
    # NoDecode: without it, pydantic-settings tries json.loads() on the raw
    # .env value before any validator runs, so `a,b` raises a SettingsError.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Reverse-proxy trust. Behind Caddy/nginx, request.client.host is the PROXY's
    # address unless uvicorn is told which peers may set X-Forwarded-For.
    #
    # Do NOT parse X-Forwarded-For in application code: it is client-controllable
    # and trusting it blindly lets anyone spoof any IP, defeating IP rate limits
    # and poisoning audit logs. Let uvicorn resolve it from a trusted-peer list,
    # then read request.client.host normally.
    #   uvicorn --proxy-headers --forwarded-allow-ips="$FORWARDED_ALLOW_IPS"
    FORWARDED_ALLOW_IPS: str = ""            # e.g. "172.18.0.5" or the proxy subnet

    # --- Database ----------------------------------------------------------
    # psycopg3 async driver. postgresql+psycopg:// (NOT psycopg2, NOT asyncpg).
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # recycle before most cloud idle timeouts
    DB_ECHO: bool = False

    # --- Redis -------------------------------------------------------------
    # Decision D2: Redis is a hard dependency, not a cache. It owns live rider
    # position (GEOADD/GEOSEARCH) and backs the arq task queue.
    REDIS_URL: RedisDsn

    # --- JWT (spec §1: access/refresh pair, Bearer header) -----------------
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 30
    # Short-lived token issued when login is intercepted by 2FA (spec §4).
    TEMP_2FA_TOKEN_TTL_MINUTES: int = 5
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 15

    # --- Secrets that are not JWT keys -------------------------------------
    # Decision D3: peppers the rider-PIN HMAC. A database dump without this
    # value cannot be brute-forced back into usable handoff PINs.
    RIDER_PIN_PEPPER: str = Field(min_length=32)
    # Peppers OTP code hashes for the same reason.
    OTP_PEPPER: str = Field(min_length=32)
    # Encrypts users.totp_secret at rest. Fernet key (base64, 32 bytes).
    TOTP_ENCRYPTION_KEY: str = Field(min_length=32)

    # --- OTP / auth policy -------------------------------------------------
    # 4 digits is 10,000 candidates — two orders of magnitude weaker than 6.
    # What makes it safe is the attempt budget below, NOT the code length, so
    # do not loosen those without shortening the TTL to compensate.
    OTP_LENGTH: int = 4
    OTP_TTL_SECONDS: int = 300
    # Guesses allowed against ONE code before it is burned.
    OTP_MAX_ATTEMPTS: int = 3
    # Guesses allowed against an identifier across ALL codes, per hour. This is
    # the ceiling that actually bounds a brute-force run: 10/hour against 10,000
    # candidates is ~0.1% per hour, and the attacker must also generate a fresh
    # OTP email for each batch — which the victim sees.
    OTP_VERIFY_MAX_PER_HOUR: int = 10
    OTP_RESEND_COOLDOWN_SECONDS: int = 60  # spec: 429 on /auth/otp/send
    LOGIN_MAX_ATTEMPTS: int = 10             # per identifier, per window
    LOGIN_WINDOW_SECONDS: int = 900          # 15 minutes
    LOGIN_IP_MAX_ATTEMPTS: int = 50          # per source IP, per window
    HANDOFF_MAX_ATTEMPTS: int = 5            # rider-PIN guesses before lockout
    # Vendor applications are unauthenticated writes, so both are per source IP.
    APPLICATION_SUBMIT_MAX_PER_HOUR: int = 5
    APPLICATION_UPLOAD_MAX_PER_HOUR: int = 30
    # Smallest withdrawal, in whole taka. Sub-100 transfers cost more in
    # mobile-wallet fees than they move.
    PAYOUT_MIN_AMOUNT: int = 100

    # --- Order pricing (spec §5 checkout summary) --------------------------
    # Every line of the bill is platform policy except delivery_fee_base and
    # commission_rate, which are per-restaurant columns. Basis points keep the
    # whole computation in integers — see core/money.percentage_of — so a 5%
    # VAT on an odd subtotal never produces a fractional paisa.
    # What a newly created restaurant starts on, in basis points (1500 == 15%).
    # The column default is 0, which silently means "this vendor pays us
    # nothing" — a restaurant created before an admin gets round to pricing it
    # would bank every order at full value, and orders snapshot the rate, so
    # those are unrecoverable. Set it at creation instead. Per-restaurant
    # renegotiation is PATCH /admin/restaurants/{id}/commission.
    DEFAULT_COMMISSION_BASIS_POINTS: int = 1500
    TAX_BASIS_POINTS: int = 500  # 5% VAT on the food, not on delivery or tip
    PLATFORM_FEE_BASIS_POINTS: int = 200  # 2% service fee
    PACKAGING_FEE_PER_ORDER: int = 10  # whole taka, flat
    # Delivery is the restaurant's base fee plus distance beyond the first km.
    DELIVERY_FEE_PER_KM: int = 10  # whole taka
    DELIVERY_FREE_KM: float = 1.0  # covered by the base fee
    # Above this order value delivery is on us. 0 disables the promotion.
    FREE_DELIVERY_THRESHOLD: int = 0  # whole taka
    # Refuse to quote a delivery this far out rather than charging for a trip
    # no rider will take.
    MAX_DELIVERY_DISTANCE_KM: float = 15.0

    # --- Scheduled delivery (Schedule Order screen) ------------------------
    SCHEDULE_SLOT_MINUTES: int = 10  # width of one bookable window
    SCHEDULE_MAX_DAYS_AHEAD: int = 4  # the date tabs on the picker
    # A slot must be at least this far out: the kitchen needs the notice, and a
    # "scheduled" order arriving in five minutes is just a normal order.
    SCHEDULE_MIN_LEAD_MINUTES: int = 30

    # --- Order chat (Message screen) ---------------------------------------
    CHAT_MESSAGE_MAX_LENGTH: int = 2000
    # Chat closes with the order. An open channel to a stranger's phone number
    # long after delivery is a safety problem, not a feature.
    CHAT_OPEN_AFTER_DELIVERY_HOURS: int = 24

    # --- Business rules (spec §9, §4) --------------------------------------
    VENDOR_AUTO_DECLINE_SECONDS: int = 60  # the timeout the task queue enforces
    ORDER_CANCEL_GRACE_SECONDS: int = 60  # cancel allowed only while PENDING
    RIDER_PIN_LENGTH: int = 4
    DEFAULT_SEARCH_RADIUS_METRES: int = 5000
    MAX_SEARCH_RADIUS_METRES: int = 25000

    # --- Money -------------------------------------------------------------
    # All money is stored as BIGINT minor units. The API speaks whole taka, so
    # 1059 on the wire == 105900 in the column. Conversion happens ONLY at the
    # serializer boundary (app/core/money.py) — never inside business logic.
    CURRENCY_CODE: str = "BDT"
    CURRENCY_MINOR_UNITS: int = 100

    # --- Pagination (spec §2) ----------------------------------------------
    DEFAULT_PAGE_LIMIT: int = 20
    MAX_PAGE_LIMIT: int = 100

    # --- Email delivery (Resend) -------------------------------------------
    # Empty RESEND_API_KEY disables sending: codes are logged instead of mailed,
    # so local development works with no third-party account. A DEPLOYED
    # environment with no key is a misconfiguration — see check_email_config().
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "onboarding@resend.dev"
    EMAIL_FROM_NAME: str = "CR Shop"
    EMAIL_TIMEOUT_SECONDS: float = 10.0
    EMAIL_REPLY_TO: str = ""

    # --- Object storage (spec §2: presigned uploads to Cloudflare R2) ------
    # R2 speaks the S3 API, so the signing in storage_service is plain SigV4.
    # What it does NOT give you is a readable URL: an R2 bucket is private, and
    # the signing endpoint always demands auth, so R2_PUBLIC_BASE_URL — the
    # r2.dev subdomain or a custom domain bound to the bucket — is where
    # `public_url` comes from and is required, not cosmetic. There is no region
    # setting because R2 has none; the signature scope is always "auto".
    R2_ACCOUNT_ID: str = ""
    R2_BUCKET: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_PUBLIC_BASE_URL: str = ""
    # Override for a jurisdiction-locked bucket (<account>.eu.r2.cloudflare
    # storage.com) or to point a local stack at MinIO. Unset, it is derived
    # from R2_ACCOUNT_ID.
    R2_ENDPOINT_URL: str | None = None
    PRESIGNED_URL_TTL_SECONDS: int = 900
    ALLOWED_UPLOAD_TYPES: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp"]
    )

    # --- Live tracking (decision D2) ---------------------------------------
    RIDER_PING_INTERVAL_SECONDS: int = 5  # what the rider app sends
    RIDER_TRAIL_DECIMATION_SECONDS: int = 30  # what actually lands in Postgres
    RIDER_LOCATION_TTL_SECONDS: int = 300  # Redis key expiry for a stale rider

    @field_validator("CORS_ORIGINS", "ALLOWED_UPLOAD_TYPES", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Accept either a comma-separated string or a real list."""
        if isinstance(v, str):
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def email_enabled(self) -> bool:
        return bool(self.RESEND_API_KEY)

    @property
    def docs_enabled(self) -> bool:
        """Whether /docs, /redoc and /openapi.json are served.

        Defaults to "everywhere except production". Publishing the full API
        surface on a public staging host is a deliberate choice, not something
        that should follow silently from the environment name — set
        ENABLE_DOCS explicitly either way.
        """
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return not self.is_production

    @property
    def expose_debug_secrets(self) -> bool:
        """Whether OTP codes may be echoed in API responses.

        An allowlist of non-deployed environments, deliberately NOT
        `not is_production` — that would leak live OTP codes over staging,
        which is internet-facing and frequently shares real phone numbers.
        """
        return self.ENVIRONMENT in {"local", "test"}

    @property
    def sqlalchemy_url(self) -> str:
        return str(self.DATABASE_URL)


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
