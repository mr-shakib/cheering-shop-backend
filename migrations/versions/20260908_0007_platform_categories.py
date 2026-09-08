"""platform categories: the browse chips customers tap

Revision ID: 0007_platform_categories
Revises: 0006_google_sign_in
Create Date: 2026-09-08

Until now the only thing customers could browse by was `restaurants.cuisine_types`,
a free-text array set at registration. A vendor who created a "Burger" section
on their menu got a section on their own menu page and nothing else -- no chip
on the home screen, no "all burgers near me". Every food app has that chip row,
and it is the first thing a customer taps.

Two designs were on the table:

* **Derive chips from menu section names.** Zero schema, but "Burger",
  "Burgers" and "burger" become three chips, nobody can attach an image to one,
  and a section called "Chef's Specials" becomes a chip too.
* **A platform table that sections link into.** Chosen. Sections resolve to a
  platform category by name (or create one) so vendors do not have to know the
  table exists, while an administrator can give a category an image, pin it,
  hide it, or merge two spellings into one. Customer counts and filters go
  through the link, never through the section name.

A category a vendor's section name creates starts **hidden** (`is_active`
false, `reviewed_at` NULL) and reaches customers only once an administrator
approves it. The vendor is never blocked -- their section works on their own
menu page immediately -- but the home screen, which is the most valuable
surface on the platform, is never written to by someone who has not been
looked at. The seeded taxonomy below is curated by definition, so it lands
approved; the categories this migration has to invent for section names it
does not recognise land in the review queue, which is exactly what they are.

Additive: one new table, one nullable column. Existing sections are linked
during the upgrade using the same name matching the application applies, so a
menu built before this migration appears under the right chip immediately. The
matching is snapshotted here rather than imported from the application -- a
migration must produce the same result next year, whatever the service layer
looks like by then.
"""

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0007_platform_categories"
down_revision: str | None = "0006_google_sign_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
-- [EXTENDED] Platform browse categories. See app/models/category.py.
CREATE TABLE categories (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(80)  NOT NULL,
    slug        varchar(100) NOT NULL,        -- public id; stable across renames
    image_url   text,
    sort_order  smallint,                     -- NULL = not pinned
    aliases     text[]       NOT NULL DEFAULT '{}',  -- match keys, lower-cased
    is_active   boolean      NOT NULL DEFAULT true,
    reviewed_at timestamptz,                  -- NULL = awaiting an admin's decision
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_categories_slug UNIQUE (slug),
    CONSTRAINT ck_categories_slug CHECK (slug <> '')
);
CREATE TRIGGER trg_categories_updated_at BEFORE UPDATE ON categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A menu section lists under at most one platform category. SET NULL rather
-- than CASCADE: deleting a chip must never delete a vendor's menu section.
ALTER TABLE menu_categories
    ADD COLUMN category_id uuid REFERENCES categories(id) ON DELETE SET NULL;
CREATE INDEX ix_menu_categories_category ON menu_categories (category_id);
"""

# A starter taxonomy so the home screen is not empty on day one. Aliases are
# the spellings vendors actually type; each is a match key (lower-cased,
# single-spaced). ON CONFLICT DO NOTHING, so re-running is harmless and a
# category an operator already created by hand is left alone.
SEED: list[tuple[str, list[str]]] = [
    ("Burger", ["burgers", "hamburger", "hamburgers"]),
    ("Pizza", ["pizzas"]),
    ("Biryani", ["biriyani", "biryanis", "biriani"]),
    ("Kacchi", ["kacchi biryani", "kachchi"]),
    ("Fried Chicken", ["chicken", "crispy chicken", "broast"]),
    ("Kebab", ["kabab", "kebabs", "kababs"]),
    ("Shawarma", ["shawarmas", "shwarma", "shawerma"]),
    ("Fast Food", ["fastfood", "fast-food"]),
    ("Bengali", ["bangla", "bengali food", "deshi", "desi"]),
    ("Indian", ["indian food"]),
    ("Chinese", ["chinese food"]),
    ("Thai", ["thai food"]),
    ("Rice", ["rice bowl", "rice bowls", "fried rice"]),
    ("Noodles", ["noodle", "chowmein", "chow mein"]),
    ("Pasta", ["pastas"]),
    ("Seafood", ["sea food", "fish"]),
    ("Grill", ["grilled", "bbq", "barbecue", "barbeque"]),
    ("Soup", ["soups"]),
    ("Sandwich", ["sandwiches"]),
    ("Snacks", ["snack"]),
    ("Breakfast", ["breakfasts", "nasta"]),
    ("Healthy", ["salad", "salads", "healthy food"]),
    ("Dessert", ["desserts"]),
    ("Sweets", ["mishti", "misti"]),
    ("Cake", ["cakes"]),
    ("Ice Cream", ["ice-cream", "icecream"]),
    ("Coffee", ["coffees", "cafe"]),
    ("Tea", ["cha", "chai"]),
    ("Juice", ["juices"]),
    ("Drinks", ["drink", "beverages", "cold drinks", "soft drinks"]),
]


# --- name matching, snapshotted from app/services/category_service.py -------


def _match_key(name: str) -> str:
    return " ".join(name.split()).lower()


def _slug(name: str) -> str:
    normalised = unicodedata.normalize("NFKD", " ".join(name.split()))
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")[:100].strip("-")
    if slug:
        return slug
    return "c-" + hashlib.sha1(_match_key(name).encode()).hexdigest()[:12]


def _display(name: str) -> str:
    words = " ".join(name.split()).split(" ")
    return " ".join(w if any(c.isupper() for c in w) else w[:1].upper() + w[1:] for w in words)[
        :80
    ]


def upgrade() -> None:
    op.execute(DDL)
    bind = op.get_bind()

    # Seeded rows are curated, so they are approved and visible from the start.
    bind.execute(
        text(
            "INSERT INTO categories (name, slug, aliases, reviewed_at) "
            "VALUES (:name, :slug, :aliases, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        [{"name": n, "slug": _slug(n), "aliases": a} for n, a in SEED],
    )

    # Link every existing menu section the way create_category will from now
    # on: slug match, then name match, then alias match, else a new category.
    sections = bind.execute(text("SELECT id, name FROM menu_categories")).all()
    for section_id, name in sections:
        slug, key = _slug(name), _match_key(name)
        found = bind.execute(
            text(
                "SELECT id FROM categories "
                "WHERE slug = :slug OR lower(name) = :key OR :key = ANY(aliases) "
                "ORDER BY (slug = :slug) DESC, (lower(name) = :key) DESC LIMIT 1"
            ),
            {"slug": slug, "key": key},
        ).scalar()
        if found is None:
            # Invented from a section name nothing recognised: hidden, and in
            # the review queue, the same as one created after this migration.
            bind.execute(
                text(
                    "INSERT INTO categories (name, slug, is_active) "
                    "VALUES (:name, :slug, false) ON CONFLICT (slug) DO NOTHING"
                ),
                {"name": _display(name), "slug": slug},
            )
            found = bind.execute(
                text("SELECT id FROM categories WHERE slug = :slug"), {"slug": slug}
            ).scalar()
        bind.execute(
            text("UPDATE menu_categories SET category_id = :cid WHERE id = :sid"),
            {"cid": found, "sid": section_id},
        )


def downgrade() -> None:
    op.execute("ALTER TABLE menu_categories DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS categories CASCADE")
