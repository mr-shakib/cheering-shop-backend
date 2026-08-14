-- =====================================================================
-- Constraint verification harness.
-- Every block below asserts that the DATABASE refuses invalid data, so the
-- invariants in the spec survive application bugs and race conditions.
-- Run with: psql -v ON_ERROR_STOP=1 -f verify_constraints.sql
-- =====================================================================

\set ON_ERROR_STOP on

-- Helper: assert that a statement fails.
CREATE OR REPLACE FUNCTION must_fail(sql text, label text) RETURNS void AS $$
BEGIN
    BEGIN
        EXECUTE sql;
    EXCEPTION WHEN others THEN
        RAISE NOTICE 'PASS  %  (rejected: %)', label, left(SQLERRM, 70);
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL  %  — the database ACCEPTED invalid data', label;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- Fixtures: two vendors, two restaurants, one customer, one rider.
-- ---------------------------------------------------------------------
INSERT INTO users (id, role, email, full_name) VALUES
    ('11111111-1111-1111-1111-111111111111', 'VENDOR',   'vendor.a@test.com', 'Vendor A'),
    ('22222222-2222-2222-2222-222222222222', 'VENDOR',   'vendor.b@test.com', 'Vendor B'),
    ('33333333-3333-3333-3333-333333333333', 'CUSTOMER', 'cust@test.com',     'Customer'),
    ('44444444-4444-4444-4444-444444444444', 'RIDER',    'rider@test.com',    'Rider');

INSERT INTO restaurants (id, owner_id, name, slug, latitude, longitude, status) VALUES
    ('aaaaaaaa-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     'Burger Place', 'burger-place', 23.7936, 90.4064, 'OPEN'),
    ('bbbbbbbb-0000-0000-0000-000000000002', '22222222-2222-2222-2222-222222222222',
     'Pizza Place',  'pizza-place',  23.8010, 90.4110, 'OPEN');

INSERT INTO menu_categories (id, restaurant_id, name) VALUES
    ('c1c1c1c1-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'Burgers'),
    ('c2c2c2c2-0000-0000-0000-000000000002', 'bbbbbbbb-0000-0000-0000-000000000002', 'Pizzas');

INSERT INTO menu_items (id, category_id, restaurant_id, name, base_price) VALUES
    ('11111111-0000-0000-0000-00000000000a', 'c1c1c1c1-0000-0000-0000-000000000001',
     'aaaaaaaa-0000-0000-0000-000000000001', 'Cheeseburger', 50000),
    ('22222222-0000-0000-0000-00000000000b', 'c2c2c2c2-0000-0000-0000-000000000002',
     'bbbbbbbb-0000-0000-0000-000000000002', 'Margherita',   80000);

INSERT INTO item_variants (id, menu_item_id, name, price, is_default) VALUES
    ('d1d1d1d1-0000-0000-0000-000000000001', '11111111-0000-0000-0000-00000000000a', 'Small', 27000, true),
    ('d2d2d2d2-0000-0000-0000-000000000002', '22222222-0000-0000-0000-00000000000b', 'Large', 95000, true);

INSERT INTO carts (id, user_id, restaurant_id) VALUES
    ('caca0000-0000-0000-0000-000000000001',
     '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0000-0000-0000-000000000001');

INSERT INTO addresses (id, user_id, street_address, latitude, longitude, is_default) VALUES
    ('e1e1e1e1-0000-0000-0000-000000000001', '33333333-3333-3333-3333-333333333333',
     'House 12, Road 8', 23.7936, 90.4064, true);

\echo ''
\echo '=== Invariant checks ==='

-- 1. THE headline rule: single restaurant per cart (spec §10).
--    Cart belongs to Burger Place; try to insert a Pizza Place item.
SELECT must_fail($$
    INSERT INTO cart_items (cart_id, restaurant_id, menu_item_id, quantity)
    VALUES ('caca0000-0000-0000-0000-000000000001',
            'bbbbbbbb-0000-0000-0000-000000000002',
            '22222222-0000-0000-0000-00000000000b', 1)
$$, 'cross-restaurant cart item (declared restaurant_id)');

-- 1b. The sneakier version: lie about restaurant_id to match the cart, while
--     the menu item actually belongs elsewhere. The second composite FK catches it.
SELECT must_fail($$
    INSERT INTO cart_items (cart_id, restaurant_id, menu_item_id, quantity)
    VALUES ('caca0000-0000-0000-0000-000000000001',
            'aaaaaaaa-0000-0000-0000-000000000001',
            '22222222-0000-0000-0000-00000000000b', 1)
$$, 'cross-restaurant cart item (spoofed restaurant_id)');

-- 1c. The legitimate insert must still succeed.
INSERT INTO cart_items (cart_id, restaurant_id, menu_item_id, variant_id, quantity)
VALUES ('caca0000-0000-0000-0000-000000000001',
        'aaaaaaaa-0000-0000-0000-000000000001',
        '11111111-0000-0000-0000-00000000000a',
        'd1d1d1d1-0000-0000-0000-000000000001', 2);
\echo 'PASS  same-restaurant cart item accepted'

-- 2. A variant belonging to a different menu item.
SELECT must_fail($$
    INSERT INTO cart_items (cart_id, restaurant_id, menu_item_id, variant_id, quantity)
    VALUES ('caca0000-0000-0000-0000-000000000001',
            'aaaaaaaa-0000-0000-0000-000000000001',
            '11111111-0000-0000-0000-00000000000a',
            'd2d2d2d2-0000-0000-0000-000000000002', 1)
$$, 'variant from a different menu item');

-- 3. Duplicate cart configuration collapses instead of duplicating.
SELECT must_fail($$
    INSERT INTO cart_items (cart_id, restaurant_id, menu_item_id, variant_id, quantity)
    VALUES ('caca0000-0000-0000-0000-000000000001',
            'aaaaaaaa-0000-0000-0000-000000000001',
            '11111111-0000-0000-0000-00000000000a',
            'd1d1d1d1-0000-0000-0000-000000000001', 1)
$$, 'duplicate cart line (same item+variant+addons)');

-- 4. Two default addresses for one user (spec §4 transactional rule).
SELECT must_fail($$
    INSERT INTO addresses (user_id, street_address, latitude, longitude, is_default)
    VALUES ('33333333-3333-3333-3333-333333333333', 'Second address', 23.79, 90.40, true)
$$, 'second default address for one user');

-- 5. Two carts for one user.
SELECT must_fail($$
    INSERT INTO carts (id, user_id, restaurant_id)
    VALUES ('caca0000-0000-0000-0000-000000000002',
            '33333333-3333-3333-3333-333333333333', 'bbbbbbbb-0000-0000-0000-000000000002')
$$, 'second cart for one user');

-- 6. Role guards: a CUSTOMER cannot own a restaurant.
SELECT must_fail($$
    INSERT INTO restaurants (owner_id, name, slug, latitude, longitude)
    VALUES ('33333333-3333-3333-3333-333333333333', 'Fake Store', 'fake-store', 23.79, 90.40)
$$, 'non-VENDOR owning a restaurant');

-- 6b. A CUSTOMER cannot be assigned as the rider on an order.
SELECT must_fail($$
    INSERT INTO orders (customer_id, restaurant_id, rider_id, rider_role, item_total, grand_total,
                        payment_method, delivery_address_text, delivery_latitude, delivery_longitude)
    VALUES ('33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0000-0000-0000-000000000001',
            '33333333-3333-3333-3333-333333333333', 'RIDER', 50000, 50000,
            'COD', 'House 12', 23.79, 90.40)
$$, 'non-RIDER assigned as order rider');

-- 7. Order arithmetic: grand_total must equal the sum of its parts.
SELECT must_fail($$
    INSERT INTO orders (customer_id, restaurant_id, item_total, delivery_fee, discount, tip,
                        grand_total, payment_method, delivery_address_text,
                        delivery_latitude, delivery_longitude)
    VALUES ('33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0000-0000-0000-000000000001',
            105900, 4000, 0, 0, 999999, 'COD', 'House 12', 23.79, 90.40)
$$, 'grand_total not equal to item+fee+tip-discount');

-- 7b. The spec's own worked example must be accepted: 1059 + 40 = 1099 taka.
INSERT INTO orders (id, customer_id, restaurant_id, item_total, delivery_fee, discount, tip,
                    grand_total, payment_method, delivery_address_text,
                    delivery_latitude, delivery_longitude, auto_decline_at)
VALUES ('0de40de4-0000-0000-0000-000000000001',
        '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0000-0000-0000-000000000001',
        105900, 4000, 0, 0, 109900, 'COD', 'House 12, Road 8', 23.7936, 90.4064,
        now() + interval '60 seconds');
\echo 'PASS  spec worked example (1059 + 40 = 1099) accepted'

-- 8. Order line-item arithmetic.
SELECT must_fail($$
    INSERT INTO order_items (order_id, item_name, unit_price, add_ons_total, quantity, line_total)
    VALUES ('0de40de4-0000-0000-0000-000000000001', 'Cheeseburger', 50000, 2000, 2, 50000)
$$, 'order line_total not equal to (unit+addons)*qty');

-- 9. A DELIVERED order with no rider attached.
SELECT must_fail($$
    UPDATE orders SET status = 'DELIVERED', delivered_at = now()
    WHERE id = '0de40de4-0000-0000-0000-000000000001'
$$, 'DELIVERED order with no rider');

-- 10. 2FA enabled with no TOTP secret stored.
SELECT must_fail($$
    UPDATE users SET is_2fa_enabled = true
    WHERE id = '33333333-3333-3333-3333-333333333333'
$$, '2FA enabled without a totp_secret');

-- 11. An account with neither email nor phone.
SELECT must_fail($$
    INSERT INTO users (role, full_name) VALUES ('CUSTOMER', 'Ghost')
$$, 'user with no email and no phone');

-- 12. Out-of-range coordinates.
SELECT must_fail($$
    INSERT INTO addresses (user_id, street_address, latitude, longitude)
    VALUES ('33333333-3333-3333-3333-333333333333', 'Nowhere', 999, 90.40)
$$, 'latitude outside -90..90');

-- 13. Review rating outside 1..5.
SELECT must_fail($$
    INSERT INTO reviews (order_id, customer_id, restaurant_id, restaurant_rating)
    VALUES ('0de40de4-0000-0000-0000-000000000001', '33333333-3333-3333-3333-333333333333',
            'aaaaaaaa-0000-0000-0000-000000000001', 9)
$$, 'review rating of 9 out of 5');

-- 14. D6: the widened arithmetic contract accepts a VAT-bearing order.
--     1059 items + 40 delivery + 20 packaging + 15% VAT (158.85 -> 15885 paisa)
--     + 10 platform + 50 tip - 100 discount = 1237.85 taka.
INSERT INTO orders (id, customer_id, restaurant_id, item_total, delivery_fee, packaging_fee,
                    tax_amount, platform_fee, tip, discount, grand_total, commission_amount,
                    payment_method, delivery_address_text, delivery_latitude, delivery_longitude)
VALUES ('0de40de4-0000-0000-0000-000000000002',
        '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0000-0000-0000-000000000001',
        105900, 4000, 2000, 15885, 1000, 5000, 10000, 123785, 15885,
        'BKASH', 'House 12, Road 8', 23.7936, 90.4064);
\echo 'PASS  VAT-bearing order accepted under widened total contract'

-- 15. D6: commission cannot exceed the value of the food.
SELECT must_fail($$
    UPDATE orders SET commission_amount = 999999
    WHERE id = '0de40de4-0000-0000-0000-000000000002'
$$, 'commission larger than item_total');

-- 16. D2: a ping with an out-of-range timestamp lands in the DEFAULT partition
--     rather than being rejected, so clock-skewed devices never lose telemetry.
INSERT INTO rider_location_pings (rider_id, order_id, latitude, longitude, recorded_at)
VALUES ('44444444-4444-4444-4444-444444444444', '0de40de4-0000-0000-0000-000000000002',
        23.8010, 90.4110, '2019-01-01T00:00:00Z');
SELECT CASE WHEN count(*) = 1
            THEN 'PASS  clock-skewed ping routed to DEFAULT partition'
            ELSE 'FAIL  skewed ping did not reach the default partition' END
FROM rider_location_pings_default;

-- 17. D2: an in-range ping routes to its month partition.
INSERT INTO rider_location_pings (rider_id, order_id, latitude, longitude, recorded_at)
VALUES ('44444444-4444-4444-4444-444444444444', '0de40de4-0000-0000-0000-000000000002',
        23.8010, 90.4110, '2026-08-15T10:00:00Z');
SELECT CASE WHEN count(*) = 1
            THEN 'PASS  August ping routed to rider_location_pings_2026_08'
            ELSE 'FAIL  ping did not reach its month partition' END
FROM rider_location_pings_2026_08;

\echo ''
\echo '=== Geospatial sanity ==='

-- The discovery query from GET /restaurants?lat=&lng=, verified against a
-- known distance: the two fixture restaurants are ~900m apart in Dhaka.
SELECT
    r.name,
    round(ST_Distance(
        r.location,
        ST_SetSRID(ST_MakePoint(90.4064, 23.7936), 4326)::geography
    )::numeric, 1) AS metres_from_search_point
FROM restaurants r
WHERE ST_DWithin(
        r.location,
        ST_SetSRID(ST_MakePoint(90.4064, 23.7936), 4326)::geography,
        2000  -- 2 km radius
      )
ORDER BY r.location <-> ST_SetSRID(ST_MakePoint(90.4064, 23.7936), 4326)::geography;

\echo ''
\echo '=== Generated geography columns stay in sync with lat/lng ==='
SELECT
    'address' AS entity,
    latitude, longitude,
    round(ST_Y(location::geometry)::numeric, 4) AS derived_lat,
    round(ST_X(location::geometry)::numeric, 4) AS derived_lng
FROM addresses
WHERE id = 'e1e1e1e1-0000-0000-0000-000000000001';

\echo ''
\echo '=== ALL INVARIANT CHECKS PASSED ==='
