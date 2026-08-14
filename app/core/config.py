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
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60  # spec: 429 on /auth/otp/send
    LOGIN_MAX_ATTEMPTS: int = 10             # per identifier, per window
    LOGIN_WINDOW_SECONDS: int = 900          # 15 minutes
    LOGIN_IP_MAX_ATTEMPTS: int = 50          # per source IP, per window
    HANDOFF_MAX_ATTEMPTS: int = 5            # rider-PIN guesses before lockout

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

    # --- Object storage (spec §2: presigned S3 uploads) --------------------
    S3_BUCKET: str = ""
    S3_REGION: str = "ap-south-1"
    S3_ENDPOINT_URL: str | None = None
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
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
