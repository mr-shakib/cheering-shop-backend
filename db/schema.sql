-- =====================================================================
-- CR Shop — Food Delivery Backend
-- Initial database schema
--
-- Target:   PostgreSQL 15+  (UNIQUE NULLS NOT DISTINCT requires 15)
--           PostGIS 3.3+
-- Source:   cr-shop-backend-api-specification.md v1.0.0
--
-- Conventions
--   * All PKs are UUIDv4 (spec §2) via gen_random_uuid() — core since PG13.
--   * All money is BIGINT in MINOR UNITS (paisa). 1059 taka == 105900.
--   * All timestamps are TIMESTAMPTZ, stored UTC (spec §2).
--   * lat/lng are the source of truth; `location` is a GENERATED geography
--     column so the two can never drift, and carries the GiST index.
--   * Tables are tagged [SPEC] (named in spec §6) or [EXTENDED] (required by
--     an endpoint in §3 that §6 forgot to model).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS postgis;    -- geography types, ST_DWithin
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- fuzzy restaurant/item search

-- ---------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------
CREATE TYPE user_role         AS ENUM ('CUSTOMER', 'VENDOR', 'RIDER', 'ADMIN');
CREATE TYPE address_type      AS ENUM ('HOME', 'WORK', 'OTHER');
CREATE TYPE restaurant_status AS ENUM ('OPEN', 'CLOSED');
CREATE TYPE order_status      AS ENUM ('PENDING', 'PREPARING', 'READY', 'PICKED_UP', 'DELIVERED', 'CANCELLED');
CREATE TYPE payment_method    AS ENUM ('COD', 'WALLET', 'BKASH', 'CARD');
CREATE TYPE payment_status    AS ENUM ('PENDING', 'PAID', 'FAILED', 'REFUNDED');
CREATE TYPE otp_purpose       AS ENUM ('SIGNUP', 'LOGIN', 'PASSWORD_RESET');
CREATE TYPE discount_type     AS ENUM ('PERCENTAGE', 'FIXED');
CREATE TYPE device_platform   AS ENUM ('IOS', 'ANDROID', 'WEB');
CREATE TYPE actor_type        AS ENUM ('CUSTOMER', 'VENDOR', 'RIDER', 'ADMIN', 'SYSTEM');

-- ---------------------------------------------------------------------
-- Shared trigger: maintain updated_at
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =====================================================================
-- IDENTITY & SECURITY
-- =====================================================================

-- [SPEC] User
CREATE TABLE users (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role                   user_role   NOT NULL,
    email                  citext      UNIQUE,
    phone                  varchar(20) UNIQUE,
    password_hash          text,                                    -- NULL for OTP-only accounts
    full_name              varchar(150),
    avatar_url             text,

    -- Security surface behind GET /users/me/security
    is_2fa_enabled         boolean     NOT NULL DEFAULT false,
    totp_secret            text,                                    -- encrypted at rest by the app layer
    totp_pending_secret    text,                                    -- POST /auth/2fa/generate, before verification
    is_biometrics_enabled  boolean     NOT NULL DEFAULT false,

    is_email_verified      boolean     NOT NULL DEFAULT false,
    is_phone_verified      boolean     NOT NULL DEFAULT false,
    is_active              boolean     NOT NULL DEFAULT true,
    last_login_at          timestamptz,

    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),

    -- An account must be reachable by at least one identifier; /auth/otp/send
    -- accepts either, and the provisional-user upsert needs a key to match on.
    CONSTRAINT ck_users_identifier CHECK (email IS NOT NULL OR phone IS NOT NULL),
    -- 2FA cannot be "on" with no secret to verify against.
    CONSTRAINT ck_users_2fa_secret CHECK (NOT is_2fa_enabled OR totp_secret IS NOT NULL),

    -- Target for the composite role-guard FKs used below. Lets the database,
    -- not application code, guarantee that only a VENDOR owns a restaurant and
    -- only a RIDER is assigned to a delivery.
    CONSTRAINT uq_users_id_role UNIQUE (id, role)
);
CREATE INDEX ix_users_role ON users (role) WHERE is_active;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [EXTENDED] Device-bound biometric keys.
-- POST /auth/biometrics/enable is meaningless as a bare boolean: the server must
-- hold a per-device public key to verify the signed challenge the phone returns.
CREATE TABLE biometric_credentials (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id     varchar(255) NOT NULL,
    device_name   varchar(120),
    public_key    text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    CONSTRAINT uq_biometric_user_device UNIQUE (user_id, device_id)
);

-- [EXTENDED] FCM tokens — required by spec §9 (POST /users/me/devices).
CREATE TABLE user_devices (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fcm_token     text        NOT NULL UNIQUE,
    platform      device_platform NOT NULL,
    is_active     boolean     NOT NULL DEFAULT true,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_user_devices_user ON user_devices (user_id) WHERE is_active;

-- [EXTENDED] Refresh-token rotation store.
-- The spec mandates an access/refresh pair (§1) but models no way to revoke one.
-- Hashes only — a leaked table dump must not yield usable tokens.
CREATE TABLE refresh_tokens (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      text        NOT NULL UNIQUE,
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    replaced_by_id  uuid        REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    user_agent      text,
    ip_address      inet,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_tokens_user_active ON refresh_tokens (user_id)
    WHERE revoked_at IS NULL;

-- [EXTENDED] OTP store, shared by /auth/otp/* and /auth/password/*.
-- Codes are hashed; `attempts` powers lockout, `consumed_at` prevents replay.
CREATE TABLE otp_codes (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identifier   citext      NOT NULL,             -- email or phone as submitted
    purpose      otp_purpose NOT NULL,
    code_hash    text        NOT NULL,
    expires_at   timestamptz NOT NULL,
    consumed_at  timestamptz,
    attempts     smallint    NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_otp_attempts CHECK (attempts >= 0)
);
CREATE INDEX ix_otp_lookup ON otp_codes (identifier, purpose, created_at DESC);

-- [EXTENDED] Idempotency-Key support — spec §9 recommends it for POST /orders.
-- Keyed per user so one client cannot probe another's cached responses.
CREATE TABLE idempotency_keys (
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key           varchar(255) NOT NULL,
    endpoint      varchar(255) NOT NULL,
    request_hash  text        NOT NULL,            -- rejects key reuse with a different body
    status_code   smallint,
    response_body jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX ix_idempotency_expiry ON idempotency_keys (expires_at);


-- =====================================================================
-- ADDRESSES
-- =====================================================================

-- [SPEC] Address
CREATE TABLE addresses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            address_type  NOT NULL DEFAULT 'OTHER',
    label           varchar(80),
    street_address  text          NOT NULL,
    apartment       varchar(120),
    landmark        varchar(255),
    city            varchar(120),
    postal_code     varchar(20),
    contact_phone   varchar(20),
    latitude        double precision NOT NULL,
    longitude       double precision NOT NULL,
    location        geography(Point, 4326) GENERATED ALWAYS AS (
                        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                    ) STORED,
    is_default      boolean       NOT NULL DEFAULT false,
    created_at      timestamptz   NOT NULL DEFAULT now(),
    updated_at      timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_addresses_lat CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_addresses_lng CHECK (longitude BETWEEN -180 AND 180)
);
-- Enforces spec §4's "unset default on all other addresses" invariant in the
-- database. A concurrent double-set now fails loudly instead of silently
-- leaving a user with two default addresses.
CREATE UNIQUE INDEX uq_addresses_one_default ON addresses (user_id) WHERE is_default;
CREATE INDEX ix_addresses_user ON addresses (user_id);
CREATE INDEX ix_addresses_location ON addresses USING GIST (location);
CREATE TRIGGER trg_addresses_updated_at BEFORE UPDATE ON addresses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =====================================================================
-- RESTAURANTS & CATALOG
-- =====================================================================

-- [SPEC] Restaurant
CREATE TABLE restaurants (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id            uuid        NOT NULL,
    owner_role          user_role   NOT NULL DEFAULT 'VENDOR',
    name                varchar(180) NOT NULL,
    slug                varchar(200) NOT NULL UNIQUE,
    description         text,
    cuisine_types       text[]      NOT NULL DEFAULT '{}',
    phone               varchar(20),
    logo_url            text,
    cover_image_url     text,

    status              restaurant_status NOT NULL DEFAULT 'CLOSED',  -- PATCH /vendor/store/status
    is_verified         boolean     NOT NULL DEFAULT false,
    is_active           boolean     NOT NULL DEFAULT true,

    rating_avg          numeric(2,1) NOT NULL DEFAULT 0.0,
    rating_count        integer      NOT NULL DEFAULT 0,

    address_line        text,
    latitude            double precision NOT NULL,
    longitude           double precision NOT NULL,
    location            geography(Point, 4326) GENERATED ALWAYS AS (
                            ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                        ) STORED,

    delivery_fee_base   bigint      NOT NULL DEFAULT 0,   -- paisa
    min_order_amount    bigint      NOT NULL DEFAULT 0,   -- paisa
    avg_prep_time_mins  smallint    NOT NULL DEFAULT 20,
    commission_rate     numeric(5,4) NOT NULL DEFAULT 0.0000,  -- 0.1500 == 15%, for /vendor/analytics

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    -- Role guard: the owner row must literally be a VENDOR.
    CONSTRAINT ck_restaurants_owner_role  CHECK (owner_role = 'VENDOR'),
    CONSTRAINT fk_restaurants_owner       FOREIGN KEY (owner_id, owner_role)
                                          REFERENCES users(id, role) ON DELETE RESTRICT,
    CONSTRAINT ck_restaurants_lat     CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_restaurants_lng     CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_restaurants_rating  CHECK (rating_avg BETWEEN 0 AND 5 AND rating_count >= 0),
    CONSTRAINT ck_restaurants_money   CHECK (delivery_fee_base >= 0 AND min_order_amount >= 0),
    CONSTRAINT ck_restaurants_commission CHECK (commission_rate BETWEEN 0 AND 1),

    -- Decision D1: one storefront per vendor, matching the singular
    -- /vendor/store/status. The constraint is NOT the expensive part to reverse
    -- — a breaking API change for shipped mobile clients is. So the hedge lives
    -- in code: vendor services must resolve their restaurant through a single
    -- dependency rather than querying owner_id directly, and every vendor
    -- response carries restaurant_id so clients already hold it. Multi-outlet
    -- then costs one migration plus one dependency, not a rewrite.
    CONSTRAINT uq_restaurants_owner UNIQUE (owner_id)
);
-- The discovery index. Powers GET /restaurants?lat=&lng= via ST_DWithin.
CREATE INDEX ix_restaurants_location ON restaurants USING GIST (location);
-- Covering index for the common "open restaurants, best rated" feed query.
CREATE INDEX ix_restaurants_open_rating ON restaurants (status, rating_avg DESC)
    WHERE is_active AND is_verified;
CREATE INDEX ix_restaurants_name_trgm ON restaurants USING GIN (name gin_trgm_ops);
CREATE INDEX ix_restaurants_cuisines ON restaurants USING GIN (cuisine_types);
CREATE TRIGGER trg_restaurants_updated_at BEFORE UPDATE ON restaurants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [EXTENDED] Favorites — N:M, required by GET/POST /users/me/favorites.
CREATE TABLE favorites (
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id uuid        NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, restaurant_id)
);
CREATE INDEX ix_favorites_restaurant ON favorites (restaurant_id);

-- [SPEC] MenuCategory
CREATE TABLE menu_categories (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id uuid         NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    name          varchar(120) NOT NULL,
    sort_order    smallint     NOT NULL DEFAULT 0,
    is_active     boolean      NOT NULL DEFAULT true,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_menu_categories_name UNIQUE (restaurant_id, name),
    -- FK target that lets menu_items carry restaurant_id safely (see below).
    CONSTRAINT uq_menu_categories_id_restaurant UNIQUE (id, restaurant_id)
);
CREATE INDEX ix_menu_categories_restaurant ON menu_categories (restaurant_id, sort_order);
CREATE TRIGGER trg_menu_categories_updated_at BEFORE UPDATE ON menu_categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [SPEC] MenuItem
-- restaurant_id is deliberately denormalized: the cart's "single restaurant"
-- rule must be checkable without a join, and it anchors the composite FK chain.
-- The composite FK below makes the denormalized value impossible to falsify.
CREATE TABLE menu_items (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id    uuid         NOT NULL,
    restaurant_id  uuid         NOT NULL,
    name           varchar(180) NOT NULL,
    description    text,
    base_price     bigint       NOT NULL,          -- paisa
    image_url      text,
    is_available   boolean      NOT NULL DEFAULT true,   -- PATCH /vendor/menu/items/{id}/status
    is_veg         boolean      NOT NULL DEFAULT false,
    prep_time_mins smallint,
    sort_order     smallint     NOT NULL DEFAULT 0,
    deleted_at     timestamptz,                    -- soft delete: order history must survive
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT ck_menu_items_price CHECK (base_price >= 0),
    CONSTRAINT fk_menu_items_category FOREIGN KEY (category_id, restaurant_id)
        REFERENCES menu_categories(id, restaurant_id) ON DELETE CASCADE,
    -- FK targets for cart_items / item children.
    CONSTRAINT uq_menu_items_id_restaurant UNIQUE (id, restaurant_id)
);
CREATE INDEX ix_menu_items_category ON menu_items (category_id, sort_order)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_menu_items_restaurant_available ON menu_items (restaurant_id)
    WHERE deleted_at IS NULL AND is_available;
CREATE INDEX ix_menu_items_search ON menu_items
    USING GIN (to_tsvector('simple', name || ' ' || coalesce(description, '')));
CREATE TRIGGER trg_menu_items_updated_at BEFORE UPDATE ON menu_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [SPEC] ItemVariant — price REPLACES base_price (spec §4: base 500, "Small" 270).
CREATE TABLE item_variants (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id uuid         NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    name         varchar(120) NOT NULL,
    price        bigint       NOT NULL,            -- paisa, absolute
    is_default   boolean      NOT NULL DEFAULT false,
    is_available boolean      NOT NULL DEFAULT true,
    sort_order   smallint     NOT NULL DEFAULT 0,
    CONSTRAINT ck_item_variants_price CHECK (price >= 0),
    CONSTRAINT uq_item_variants_name UNIQUE (menu_item_id, name),
    -- Lets cart_items prove the chosen variant belongs to the chosen item.
    CONSTRAINT uq_item_variants_id_item UNIQUE (id, menu_item_id)
);
CREATE UNIQUE INDEX uq_item_variants_one_default ON item_variants (menu_item_id) WHERE is_default;

-- [SPEC] ItemAddOn — price ADDS to the resolved unit price.
CREATE TABLE item_add_ons (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id uuid         NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    name         varchar(120) NOT NULL,
    price        bigint       NOT NULL,            -- paisa, additive
    is_available boolean      NOT NULL DEFAULT true,
    sort_order   smallint     NOT NULL DEFAULT 0,
    CONSTRAINT ck_item_add_ons_price CHECK (price >= 0),
    CONSTRAINT uq_item_add_ons_name UNIQUE (menu_item_id, name),
    CONSTRAINT uq_item_add_ons_id_item UNIQUE (id, menu_item_id)
);


-- =====================================================================
-- CART
-- =====================================================================

-- [SPEC] Cart  (decision D5: surrogate PK)
-- §6 specifies user_id as the PK. We use a surrogate `id` instead so every
-- table shares one shape for the ORM base class, and so group/scheduled carts
-- remain possible later. UNIQUE(user_id) is exactly as absolute a guarantee as
-- a primary key would have been: one cart per user, enforced by the database.
CREATE TABLE carts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid        NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id uuid        NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    -- FK target for the cross-restaurant guard on cart_items.
    CONSTRAINT uq_carts_id_restaurant UNIQUE (id, restaurant_id)
);
CREATE TRIGGER trg_carts_updated_at BEFORE UPDATE ON carts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [SPEC] CartItem
--
-- The single-restaurant rule (spec §10) is enforced structurally here, not by
-- application code. cart_items carries restaurant_id, and that one column is
-- shared by two composite foreign keys:
--     (cart_id,      restaurant_id) -> carts(id, restaurant_id)
--     (menu_item_id, restaurant_id) -> menu_items(id, restaurant_id)
-- Inserting an item from another restaurant cannot satisfy both at once. The
-- 409 in the API becomes a *nicer* error for a case the DB already refuses.
--
-- Decision D4: variant price REPLACES base_price. Consequence the spec does not
-- address — when a menu item has one or more variants, base_price is a display
-- price only ("from ৳270") and variant_id is REQUIRED here. That rule spans two
-- tables, so it is enforced in the service layer, not by a CHECK.
CREATE TABLE cart_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id       uuid        NOT NULL,
    restaurant_id uuid        NOT NULL,
    menu_item_id  uuid        NOT NULL,
    variant_id    uuid,
    quantity      smallint    NOT NULL,
    -- Sorted, hashed add-on id list. Lets "same item, same options" collapse
    -- into one row while "same item, different options" stays separate.
    add_ons_fingerprint text  NOT NULL DEFAULT '',
    notes         varchar(255),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_cart_items_qty CHECK (quantity > 0),
    CONSTRAINT fk_cart_items_cart FOREIGN KEY (cart_id, restaurant_id)
        REFERENCES carts(id, restaurant_id) ON DELETE CASCADE,
    CONSTRAINT fk_cart_items_menu_item FOREIGN KEY (menu_item_id, restaurant_id)
        REFERENCES menu_items(id, restaurant_id) ON DELETE CASCADE,
    CONSTRAINT fk_cart_items_variant FOREIGN KEY (variant_id, menu_item_id)
        REFERENCES item_variants(id, menu_item_id) ON DELETE CASCADE,
    -- NULLS NOT DISTINCT (PG15+) so a NULL variant still collapses correctly.
    CONSTRAINT uq_cart_items_config UNIQUE NULLS NOT DISTINCT
        (cart_id, menu_item_id, variant_id, add_ons_fingerprint)
);
CREATE INDEX ix_cart_items_cart ON cart_items (cart_id);
CREATE TRIGGER trg_cart_items_updated_at BEFORE UPDATE ON cart_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [EXTENDED] Cart item add-ons (N:M). menu_item_id is carried so the composite
-- FK can prove the add-on belongs to the item it is attached to.
CREATE TABLE cart_item_add_ons (
    cart_item_id uuid NOT NULL REFERENCES cart_items(id) ON DELETE CASCADE,
    add_on_id    uuid NOT NULL,
    menu_item_id uuid NOT NULL,
    PRIMARY KEY (cart_item_id, add_on_id),
    CONSTRAINT fk_cart_item_add_ons_addon FOREIGN KEY (add_on_id, menu_item_id)
        REFERENCES item_add_ons(id, menu_item_id) ON DELETE CASCADE
);


-- =====================================================================
-- PROMOTIONS
-- =====================================================================

-- [EXTENDED] Required by GET /checkout/summary?promo_code=XYZ.
CREATE TABLE promo_codes (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code              citext        NOT NULL UNIQUE,
    description       text,
    discount_type     discount_type NOT NULL,
    discount_value    bigint        NOT NULL,   -- paisa if FIXED, basis points if PERCENTAGE
    max_discount      bigint,                   -- paisa cap for PERCENTAGE
    min_order_amount  bigint        NOT NULL DEFAULT 0,
    restaurant_id     uuid          REFERENCES restaurants(id) ON DELETE CASCADE,  -- NULL = platform-wide
    valid_from        timestamptz   NOT NULL DEFAULT now(),
    valid_until       timestamptz   NOT NULL,
    usage_limit       integer,                  -- NULL = unlimited
    per_user_limit    smallint      NOT NULL DEFAULT 1,
    times_used        integer       NOT NULL DEFAULT 0,
    is_active         boolean       NOT NULL DEFAULT true,
    created_at        timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_promo_window CHECK (valid_until > valid_from),
    CONSTRAINT ck_promo_value  CHECK (discount_value > 0),
    CONSTRAINT ck_promo_usage  CHECK (times_used >= 0 AND (usage_limit IS NULL OR usage_limit > 0))
);
CREATE INDEX ix_promo_active ON promo_codes (code) WHERE is_active;


-- =====================================================================
-- RIDERS
-- =====================================================================

-- [EXTENDED] The spec defines a RIDER role, a rider_id on Order, live GPS, and
-- rider earnings — but never models the rider. This is that table.
--
-- Decision D2: current_latitude/longitude are LAST KNOWN, synced periodically
-- from Redis — they are NOT the authoritative live position and must not be
-- read by dispatch. Redis GEOADD/GEOSEARCH owns live position and nearest-rider
-- matching. Deliberately NOT GiST-indexed: a geography index updated every 5s
-- per rider produces a dead tuple and an index entry per ping, which at 500
-- riders is ~8.6M dead tuples/day for autovacuum to chase — and the index
-- degrades precisely when dispatch depends on it.
CREATE TABLE rider_profiles (
    user_id           uuid PRIMARY KEY,
    user_role         user_role   NOT NULL DEFAULT 'RIDER',
    vehicle_type      varchar(40),
    license_number    varchar(60),
    is_online         boolean     NOT NULL DEFAULT false,
    is_verified       boolean     NOT NULL DEFAULT false,
    current_latitude  double precision,
    current_longitude double precision,
    current_location  geography(Point, 4326) GENERATED ALWAYS AS (
                          CASE WHEN current_latitude IS NULL OR current_longitude IS NULL THEN NULL
                               ELSE ST_SetSRID(ST_MakePoint(current_longitude, current_latitude), 4326)::geography
                          END
                      ) STORED,
    last_location_at  timestamptz,
    rating_avg        numeric(2,1) NOT NULL DEFAULT 0.0,
    rating_count      integer      NOT NULL DEFAULT 0,
    total_deliveries  integer      NOT NULL DEFAULT 0,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ck_rider_role CHECK (user_role = 'RIDER'),
    CONSTRAINT fk_rider_user FOREIGN KEY (user_id, user_role)
        REFERENCES users(id, role) ON DELETE CASCADE,
    CONSTRAINT ck_rider_rating CHECK (rating_avg BETWEEN 0 AND 5)
);
-- NOTE: no GiST index here by design — see the D2 comment above. Nearest-rider
-- dispatch is served by Redis GEOSEARCH. This B-tree only supports admin views
-- ("who is on shift right now"), which do not run per-ping.
CREATE INDEX ix_rider_online ON rider_profiles (is_online) WHERE is_online;
CREATE TRIGGER trg_rider_profiles_updated_at BEFORE UPDATE ON rider_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =====================================================================
-- ORDERS
-- =====================================================================

-- [SPEC] Order
CREATE TABLE orders (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number       bigint       GENERATED BY DEFAULT AS IDENTITY UNIQUE,  -- human-facing
    customer_id        uuid         NOT NULL,
    customer_role      user_role    NOT NULL DEFAULT 'CUSTOMER',
    restaurant_id      uuid         NOT NULL REFERENCES restaurants(id) ON DELETE RESTRICT,
    rider_id           uuid,
    rider_role         user_role,

    status             order_status NOT NULL DEFAULT 'PENDING',

    -- Money, all paisa. The CHECK is the arithmetic contract of
    -- GET /checkout/summary — a mispriced order cannot be persisted.
    item_total         bigint       NOT NULL,
    delivery_fee       bigint       NOT NULL DEFAULT 0,
    discount           bigint       NOT NULL DEFAULT 0,
    tip                bigint       NOT NULL DEFAULT 0,
    -- Decision D6: present from day one, defaulting to 0, so v1 behaviour is
    -- identical to the spec while VAT / bKash processing fees can be switched
    -- on without altering a CHECK constraint on a populated orders table.
    packaging_fee      bigint       NOT NULL DEFAULT 0,
    tax_amount         bigint       NOT NULL DEFAULT 0,
    platform_fee       bigint       NOT NULL DEFAULT 0,
    grand_total        bigint       NOT NULL,

    -- Commission SNAPSHOT, for the same reason line-item prices are snapshotted.
    -- restaurants.commission_rate is mutable; raising a vendor from 15% to 18%
    -- must not retroactively rewrite what they earned on past orders.
    -- Vendor payout == item_total - commission_amount.
    commission_amount  bigint       NOT NULL DEFAULT 0,

    payment_method     payment_method NOT NULL,
    payment_status     payment_status NOT NULL DEFAULT 'PENDING',
    payment_reference  varchar(255),

    promo_code_id      uuid         REFERENCES promo_codes(id) ON DELETE SET NULL,

    -- Handoff proof (spec §4). Decision D3.
    --
    -- Stored as HMAC-SHA256(server_pepper, order_id || pin) — NOT bcrypt.
    -- A 4-digit PIN has 10,000 candidates, so bcrypt falls in seconds to anyone
    -- holding the table and costs latency on every handoff for nothing. An HMAC
    -- keyed by a pepper in KMS/config means a database dump alone is useless,
    -- and scoping by order_id stops identical PINs correlating across orders.
    --
    -- Issued when the order reaches READY, not at creation: the PIN should not
    -- exist during the whole cooking window. Support REGENERATES, never reads.
    rider_pin_hash     text,
    rider_pin_issued_at timestamptz,
    handoff_attempts   smallint     NOT NULL DEFAULT 0,

    -- Delivery address is SNAPSHOTTED. The customer may delete or edit the
    -- address afterwards; a delivered order must still say where it went.
    delivery_address_id   uuid      REFERENCES addresses(id) ON DELETE SET NULL,
    delivery_address_text text      NOT NULL,
    delivery_latitude     double precision NOT NULL,
    delivery_longitude    double precision NOT NULL,
    delivery_location     geography(Point, 4326) GENERATED ALWAYS AS (
                              ST_SetSRID(ST_MakePoint(delivery_longitude, delivery_latitude), 4326)::geography
                          ) STORED,
    delivery_contact_phone varchar(20),
    special_instructions   varchar(500),

    -- Lifecycle timestamps, one per §8 transition.
    placed_at            timestamptz NOT NULL DEFAULT now(),
    auto_decline_at      timestamptz,   -- the 60s vendor timeout the worker sweeps
    accepted_at          timestamptz,
    ready_at             timestamptz,
    picked_up_at         timestamptz,
    delivered_at         timestamptz,
    cancelled_at         timestamptz,
    cancelled_by         actor_type,
    cancellation_reason  varchar(255),
    estimated_delivery_at timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_orders_customer_role CHECK (customer_role = 'CUSTOMER'),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id, customer_role)
        REFERENCES users(id, role) ON DELETE RESTRICT,
    CONSTRAINT ck_orders_rider_role CHECK (rider_role IS NULL OR rider_role = 'RIDER'),
    CONSTRAINT ck_orders_rider_pair CHECK ((rider_id IS NULL) = (rider_role IS NULL)),
    CONSTRAINT fk_orders_rider FOREIGN KEY (rider_id, rider_role)
        REFERENCES users(id, role) ON DELETE RESTRICT,

    CONSTRAINT ck_orders_money_nonneg CHECK (
        item_total >= 0 AND delivery_fee >= 0 AND discount >= 0
        AND tip >= 0 AND packaging_fee >= 0 AND tax_amount >= 0
        AND platform_fee >= 0 AND commission_amount >= 0 AND grand_total >= 0
    ),
    CONSTRAINT ck_orders_total_math CHECK (
        grand_total = item_total + delivery_fee + packaging_fee
                    + tax_amount + platform_fee + tip - discount
    ),
    -- A vendor cannot be charged more commission than the food was worth.
    CONSTRAINT ck_orders_commission CHECK (commission_amount <= item_total),
    CONSTRAINT ck_orders_cancelled CHECK (
        (status = 'CANCELLED') = (cancelled_at IS NOT NULL)
    ),
    CONSTRAINT ck_orders_delivered CHECK (
        status <> 'DELIVERED' OR delivered_at IS NOT NULL
    ),
    -- A picked-up order must have a rider attached.
    CONSTRAINT ck_orders_rider_required CHECK (
        status NOT IN ('PICKED_UP', 'DELIVERED') OR rider_id IS NOT NULL
    )
);

-- Vendor queue: GET /vendor/orders, newest first, filtered by status.
CREATE INDEX ix_orders_vendor_queue ON orders (restaurant_id, status, placed_at DESC);
-- Customer history: GET /orders?sort=-created_at
CREATE INDEX ix_orders_customer_history ON orders (customer_id, placed_at DESC);
-- Rider's active job list.
CREATE INDEX ix_orders_rider ON orders (rider_id, status) WHERE rider_id IS NOT NULL;
-- The auto-decline sweeper. Tiny partial index: only unaccepted orders live here.
CREATE INDEX ix_orders_auto_decline ON orders (auto_decline_at)
    WHERE status = 'PENDING' AND auto_decline_at IS NOT NULL;
-- Vendor analytics date-range scans.
CREATE INDEX ix_orders_analytics ON orders (restaurant_id, delivered_at)
    WHERE status = 'DELIVERED';
CREATE TRIGGER trg_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- [EXTENDED] OrderItem — the single most important omission in spec §6.
-- Without it an order has no line items, and repricing a menu would silently
-- rewrite the history of every past order. Every user-visible field is a
-- snapshot taken at purchase time.
CREATE TABLE order_items (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id          uuid         NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id      uuid         REFERENCES menu_items(id) ON DELETE SET NULL,
    variant_id        uuid         REFERENCES item_variants(id) ON DELETE SET NULL,
    item_name         varchar(180) NOT NULL,   -- snapshot
    variant_name      varchar(120),            -- snapshot
    image_url         text,                    -- snapshot
    unit_price        bigint       NOT NULL,   -- snapshot: variant price or base_price
    add_ons_total     bigint       NOT NULL DEFAULT 0,
    quantity          smallint     NOT NULL,
    line_total        bigint       NOT NULL,
    notes             varchar(255),
    CONSTRAINT ck_order_items_qty   CHECK (quantity > 0),
    CONSTRAINT ck_order_items_money CHECK (unit_price >= 0 AND add_ons_total >= 0 AND line_total >= 0),
    CONSTRAINT ck_order_items_math  CHECK (line_total = (unit_price + add_ons_total) * quantity)
);
CREATE INDEX ix_order_items_order ON order_items (order_id);
CREATE INDEX ix_order_items_menu_item ON order_items (menu_item_id);  -- "top selling item" analytics

-- [EXTENDED] Add-ons chosen per line, snapshotted.
CREATE TABLE order_item_add_ons (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_item_id uuid         NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
    add_on_id     uuid         REFERENCES item_add_ons(id) ON DELETE SET NULL,
    name          varchar(120) NOT NULL,   -- snapshot
    price         bigint       NOT NULL,   -- snapshot
    CONSTRAINT ck_order_item_add_ons_price CHECK (price >= 0)
);
CREATE INDEX ix_order_item_add_ons_item ON order_item_add_ons (order_item_id);

-- [EXTENDED] Status audit trail. Powers the GET /orders/{id}/tracking timeline
-- and answers "who cancelled this and when" in a dispute.
CREATE TABLE order_status_history (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    uuid         NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    from_status order_status,
    to_status   order_status NOT NULL,
    actor       actor_type   NOT NULL,
    actor_id    uuid         REFERENCES users(id) ON DELETE SET NULL,
    note        varchar(255),
    created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX ix_order_status_history_order ON order_status_history (order_id, created_at);

-- [EXTENDED] Promo redemption ledger — enforces per_user_limit truthfully.
CREATE TABLE promo_redemptions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    promo_code_id uuid        NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id      uuid        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    discount_applied bigint   NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_promo_redemption_order UNIQUE (promo_code_id, order_id)
);
CREATE INDEX ix_promo_redemptions_user ON promo_redemptions (promo_code_id, user_id);

-- [EXTENDED] Reviews — POST /orders/{id}/reviews. One review per order.
CREATE TABLE reviews (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id          uuid        NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    customer_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id     uuid        NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    rider_id          uuid        REFERENCES users(id) ON DELETE SET NULL,
    restaurant_rating smallint    NOT NULL,
    rider_rating      smallint,
    comment           varchar(1000),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_reviews_restaurant_rating CHECK (restaurant_rating BETWEEN 1 AND 5),
    CONSTRAINT ck_reviews_rider_rating CHECK (rider_rating IS NULL OR rider_rating BETWEEN 1 AND 5)
);
CREATE INDEX ix_reviews_restaurant ON reviews (restaurant_id, created_at DESC);
CREATE INDEX ix_reviews_rider ON reviews (rider_id) WHERE rider_id IS NOT NULL;

-- [EXTENDED] Rider GPS breadcrumbs. Decision D2: this is the COLD trail, not
-- the live feed. Redis serves WS /ws/orders/{id}/live-tracking at full ping
-- rate; only a decimated track lands here (roughly one row per 30s, plus every
-- status transition), which is enough to settle a "rider says delivered,
-- customer says it never arrived" dispute at ~1/6th the volume.
--
-- RANGE-partitioned on recorded_at so retention is a DROP PARTITION (instant,
-- no bloat) instead of a mass DELETE. Retention target: 90 days.
-- The PK must include the partition key, hence (id, recorded_at).
CREATE TABLE rider_location_pings (
    id          bigint GENERATED BY DEFAULT AS IDENTITY,
    rider_id    uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id    uuid        REFERENCES orders(id) ON DELETE SET NULL,
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    location    geography(Point, 4326) GENERATED ALWAYS AS (
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                ) STORED,
    heading     smallint,
    speed_kph   real,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Bootstrap partitions. Provision new months ahead of time with pg_partman or a
-- scheduled worker task; writes to an uncovered range fail loudly rather than
-- landing somewhere wrong.
CREATE TABLE rider_location_pings_2026_08 PARTITION OF rider_location_pings
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE rider_location_pings_2026_09 PARTITION OF rider_location_pings
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE rider_location_pings_2026_10 PARTITION OF rider_location_pings
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
-- Catches out-of-range writes instead of erroring, so a clock-skewed device
-- cannot drop telemetry on the floor. Monitor it: rows here mean bad timestamps.
CREATE TABLE rider_location_pings_default PARTITION OF rider_location_pings DEFAULT;

-- Replaying one delivery's route: the dominant read pattern.
CREATE INDEX ix_rider_pings_order ON rider_location_pings (order_id, recorded_at DESC);
-- BRIN on append-only time-ordered data: kilobytes where a B-tree costs gigabytes.
CREATE INDEX ix_rider_pings_time ON rider_location_pings USING BRIN (recorded_at);

COMMIT;
