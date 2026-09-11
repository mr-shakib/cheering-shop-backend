#!/usr/bin/env python
"""Seed browsable demo data so the discovery endpoints return something.

    ./scripts/seed_demo.py                # create the demo restaurants
    ./scripts/seed_demo.py --remove       # delete every trace of them
    ./scripts/seed_demo.py --yes          # skip the confirmation prompt

Run it inside the container, the same way as create_admin.py:
    docker compose exec api python scripts/seed_demo.py

WHY THIS EXISTS. `GET /categories` only ever returns a chip a *visible*
restaurant actually sells under (see category_service.restaurant_counts), which
is the rule that stops a chip opening onto an empty screen. The consequence is
that a fresh deployment shows an empty chip row however many categories
migration 0007 seeded, and a client developer has nothing to render against.
This creates the restaurants that light the chips up.

DELIBERATELY NOT AN API ENDPOINT, for the same reason as create_admin.py: a
route that writes fake restaurants into discovery is a hole whether or not it
is authenticated. Gating it on shell access gates it on infrastructure.

EVERYTHING IT WRITES IS MARKED AND REVERSIBLE. Vendor accounts live at
@{DEMO_DOMAIN}, every restaurant name starts with "{NAME_PREFIX}", every slug
with "{SLUG_PREFIX}", and every image points at {IMAGE_HOST}. `--remove` keys
off exactly those markers, so nothing a real vendor created can be caught by
it. The restaurants ARE visible to customers while they exist -- that is the
entire point -- so on a deployment real customers can reach, seed it, let the
client developer work, and remove it.

Idempotent: re-running skips vendors that already exist rather than failing on
the unique email.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# `__file__` is absent when the script is piped in (`python - < seed_demo.py`),
# which is how it runs on a server without redeploying the image. The container
# WORKDIR is the project root, so cwd is the right fallback.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd())
)

from sqlalchemy import delete, select, update  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.money import to_minor  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.category import Category  # noqa: E402
from app.models.enums import RestaurantStatus, UserRole  # noqa: E402
from app.models.menu import MenuCategory, MenuItem  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import category_service  # noqa: E402

# --- Markers. `--remove` finds the demo data by these and nothing else. ------

DEMO_DOMAIN = "demo.cheeringshop.local"
NAME_PREFIX = "[Demo] "
SLUG_PREFIX = "demo-"
IMAGE_HOST = "https://placehold.co"
DEMO_PASSWORD = "DemoVendor!2026"  # noqa: S105 - fixed on purpose; see --help

# Labelled placeholders rather than photo-stock URLs: they always resolve, they
# never rot, and they read as obviously-not-real in a screenshot. Swap the
# helpers below for your CDN when you have real art.

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def chip_image(name: str) -> str:
    """The category chip picture."""
    return f"{IMAGE_HOST}/240x240/f97316/ffffff/png?text={name.replace(' ', '+')}"


def dish_image(name: str) -> str:
    return f"{IMAGE_HOST}/480x360/e5e7eb/111827/png?text={name.replace(' ', '+')}"


def cover_image(name: str) -> str:
    return f"{IMAGE_HOST}/1200x480/1f2937/ffffff/png?text={name.replace(' ', '+')}"


def logo_image(name: str) -> str:
    return f"{IMAGE_HOST}/160x160/111827/ffffff/png?text={name[:2].upper()}"


# Open every day; the Business Hours screen has something to draw.
HOURS = {
    d: {"is_open": True, "opens_at": "10:00", "closes_at": "23:00"}
    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}

# --- The data ---------------------------------------------------------------
#
# Section names are spelled to hit the categories migration 0007 seeded, so
# they resolve to APPROVED chips and appear to customers immediately. A name
# that matched nothing would create a chip stuck in the review queue, which is
# correct behaviour and useless for a demo.
#
# (name, cuisines, lat, lng, delivery_fee_taka, min_order_taka, prep, status,
#  [(section, [(dish, description, price_taka, is_veg), ...]), ...])

RESTAURANTS: list[tuple] = [
    (
        "Dhanmondi Grill House", ["Fast Food", "Grill"], 23.7461, 90.3742, 60, 200, 25,
        RestaurantStatus.OPEN,
        [
            ("Burgers", [
                ("Classic Beef Burger", "Beef patty, cheddar, lettuce, house sauce", 320, False),
                ("Double Cheese Burger", "Two patties, double cheddar", 480, False),
                ("Crispy Chicken Burger", "Buttermilk fried chicken thigh", 290, False),
                ("Veggie Burger", "Spiced potato and pea patty", 220, True),
            ]),
            ("Grill", [
                ("Chicken Tikka Platter", "Half chicken, naan, salad", 520, False),
                ("Beef Seekh Kebab", "Four skewers, mint chutney", 450, False),
            ]),
            ("Drinks", [
                ("Cold Coffee", "Double shot, milk, ice", 180, True),
                ("Lemon Mint Cooler", None, 140, True),
            ]),
        ],
    ),
    (
        "Gulshan Pizza Co.", ["Italian", "Fast Food"], 23.7925, 90.4078, 80, 300, 30,
        RestaurantStatus.OPEN,
        [
            ("Pizza", [
                ("Margherita", "San Marzano, mozzarella, basil", 650, True),
                ("Pepperoni Feast", "Double pepperoni, chilli honey", 890, False),
                ("BBQ Chicken", "Smoked chicken, red onion, barbecue base", 850, False),
                ("Four Cheese", "Mozzarella, cheddar, parmesan, blue", 920, True),
            ]),
            ("Pasta", [
                ("Chicken Alfredo", "Fettuccine, cream, parmesan", 560, False),
                ("Arrabbiata", "Penne, tomato, chilli, garlic", 480, True),
            ]),
            ("Dessert", [
                ("Tiramisu", "Mascarpone, espresso, cocoa", 320, True),
            ]),
        ],
    ),
    (
        "Purana Paltan Kacchi", ["Biryani & Kacchi", "Bangladeshi"], 23.7340, 90.4130, 50, 250, 45,
        RestaurantStatus.OPEN,
        [
            ("Kacchi", [
                ("Mutton Kacchi (Full)", "Basmati, mutton leg, borhani", 480, False),
                ("Mutton Kacchi (Half)", None, 280, False),
                ("Chicken Roast Kacchi", "With potato and egg", 360, False),
            ]),
            ("Biryani", [
                ("Beef Tehari", "Short-grain rice, mustard oil", 260, False),
                ("Chicken Biryani", None, 300, False),
            ]),
            ("Drinks", [
                ("Borhani", "Spiced yoghurt drink", 90, True),
            ]),
        ],
    ),
    (
        "Banani Fried Chicken", ["Fast Food"], 23.7936, 90.4043, 60, 200, 20,
        RestaurantStatus.OPEN,
        [
            ("Fried Chicken", [
                ("3 Pcs Chicken Bucket", "Hot and crispy, with fries", 420, False),
                ("Spicy Wings (6)", "Tossed in chilli glaze", 320, False),
                ("Chicken Strips (5)", "With honey mustard", 300, False),
            ]),
            ("Sandwich", [
                ("Grilled Chicken Sandwich", "Sourdough, cheddar, pickle", 280, False),
                ("Egg & Cheese Sandwich", None, 200, True),
            ]),
        ],
    ),
    (
        "Uttara Shawarma Point", ["Middle Eastern", "Fast Food"], 23.8759, 90.3795, 40, 150, 15,
        RestaurantStatus.OPEN,
        [
            ("Shawarma", [
                ("Chicken Shawarma Roll", "Garlic sauce, pickles", 180, False),
                ("Beef Shawarma Roll", None, 240, False),
                ("Shawarma Platter", "Rice, salad, two sauces", 380, False),
            ]),
            ("Kebab", [
                ("Chicken Shish Kebab", "Three skewers", 340, False),
                ("Falafel Plate", "Six pieces, tahini", 260, True),
            ]),
        ],
    ),
    (
        "Mirpur Chinese Kitchen", ["Chinese", "Thai"], 23.8069, 90.3687, 70, 350, 35,
        RestaurantStatus.OPEN,
        [
            ("Chinese", [
                ("Chicken Chilli Onion", "Dry, with capsicum", 420, False),
                ("Beef Black Pepper", None, 520, False),
                ("Mixed Vegetable", "Seasonal, garlic sauce", 320, True),
            ]),
            ("Noodles", [
                ("Chicken Chowmein", None, 340, False),
                ("Prawn Hakka Noodles", None, 460, False),
            ]),
            ("Soup", [
                ("Thai Soup", "Hot and sour, chicken", 280, False),
                ("Sweet Corn Soup", None, 220, True),
            ]),
        ],
    ),
    (
        "Bashundhara Bake Shop", ["Bakery", "Desserts"], 23.8198, 90.4265, 50, 200, 30,
        RestaurantStatus.OPEN,
        [
            ("Cake", [
                ("Chocolate Fudge Slice", None, 180, True),
                ("Red Velvet Slice", "Cream cheese frosting", 200, True),
                ("Whole Vanilla Cake (1kg)", "48h notice preferred", 1400, True),
            ]),
            ("Ice Cream", [
                ("Belgian Chocolate Scoop", None, 120, True),
                ("Mango Sorbet Scoop", None, 110, True),
            ]),
            ("Coffee", [
                ("Flat White", None, 220, True),
                ("Iced Americano", None, 190, True),
            ]),
        ],
    ),
    (
        "Old Dhaka Bhoj", ["Bangladeshi"], 23.7104, 90.4074, 40, 150, 40,
        RestaurantStatus.CLOSED,  # one closed on purpose: the greyed-card state
        [
            ("Bengali", [
                ("Shorshe Ilish", "Hilsa in mustard gravy", 650, False),
                ("Beef Bhuna", "Slow-cooked, with paratha", 420, False),
                ("Dal & Bhorta Thali", "Five bhortas, rice, dal", 280, True),
            ]),
            ("Breakfast", [
                ("Paratha & Dal", None, 120, True),
                ("Khichuri with Beef", None, 260, False),
            ]),
            ("Sweets", [
                ("Roshogolla (4)", None, 160, True),
                ("Mishti Doi", "Earthen pot", 140, True),
            ]),
        ],
    ),
    (
        "Mohakhali Seafood Bar", ["Seafood"], 23.7806, 90.4074, 90, 400, 35,
        RestaurantStatus.OPEN,
        [
            ("Seafood", [
                ("Grilled Rupchanda", "Whole, lemon butter", 780, False),
                ("Prawn Garlic Butter", "Eight pieces", 690, False),
                ("Fish & Chips", "Beer-battered bhetki", 520, False),
            ]),
            ("Healthy", [
                ("Grilled Chicken Salad", "Greens, olive, vinaigrette", 380, False),
                ("Quinoa Veg Bowl", None, 340, True),
            ]),
        ],
    ),
]


def slugify(name: str) -> str:
    return SLUG_PREFIX + "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def email_for(name: str) -> str:
    local = "".join(c for c in name.lower() if c.isalnum() or c == " ").replace(" ", ".")
    return f"{local}@{DEMO_DOMAIN}"


async def seed() -> int:
    created_restaurants = created_items = 0
    touched_categories: set[str] = set()

    async with SessionLocal() as db:
        for (
            name, cuisines, lat, lng, fee, min_order, prep, status, sections
        ) in RESTAURANTS:
            display = NAME_PREFIX + name
            email = email_for(name)

            if await db.scalar(select(User.id).where(User.email == email)):
                print(f"  {DIM}· {display} already seeded, skipping{RESET}")
                continue

            owner = User(
                role=UserRole.VENDOR,
                email=email,
                full_name=f"{name} Owner",
                password_hash=hash_password(DEMO_PASSWORD),
                is_email_verified=True,
                is_active=True,
            )
            db.add(owner)
            await db.flush()

            restaurant = Restaurant(
                owner_id=owner.id,
                owner_role=UserRole.VENDOR,
                name=display,
                slug=slugify(name),
                description=f"Demo storefront for client development. {name}.",
                cuisine_types=cuisines,
                phone="+8801700000000",
                logo_url=logo_image(name),
                cover_image_url=cover_image(name),
                status=status,
                # Both required for the restaurant to exist to customers at all.
                is_verified=True,
                is_active=True,
                address_line=f"{name}, Dhaka",
                latitude=lat,
                longitude=lng,
                delivery_fee_base=to_minor(fee),
                min_order_amount=to_minor(min_order),
                avg_prep_time_mins=prep,
                business_hours=HOURS,
            )
            db.add(restaurant)
            await db.flush()

            for order, (section_name, dishes) in enumerate(sections):
                # The real matching path, so the link is made exactly as it
                # would be for a vendor typing this name into the app.
                category = await category_service.resolve(db, section_name)
                touched_categories.add(str(category.id))

                section = MenuCategory(
                    restaurant_id=restaurant.id,
                    name=section_name,
                    sort_order=order,
                    is_active=True,
                    category_id=category.id,
                )
                db.add(section)
                await db.flush()

                for i, (dish, description, price, is_veg) in enumerate(dishes):
                    db.add(
                        MenuItem(
                            category_id=section.id,
                            restaurant_id=restaurant.id,
                            name=dish,
                            description=description,
                            base_price=to_minor(price),
                            # Every third dish has no picture, so the client's
                            # placeholder branch gets exercised too.
                            image_url=None if i % 3 == 2 else dish_image(dish),
                            is_available=True,
                            is_veg=is_veg,
                            prep_time_mins=prep,
                            sort_order=i,
                        )
                    )
                    created_items += 1

            created_restaurants += 1
            print(f"  {GREEN}✓{RESET} {display}  {DIM}{len(sections)} sections{RESET}")

        # Give every chip these restaurants light up a picture, but never
        # overwrite one an administrator already chose.
        for row in (
            await db.execute(
                select(Category).where(
                    Category.id.in_(touched_categories), Category.image_url.is_(None)
                )
            )
        ).scalars():
            row.image_url = chip_image(row.name)

        await db.commit()

    print(
        f"\n{GREEN}Seeded{RESET} {created_restaurants} restaurants, {created_items} dishes, "
        f"{len(touched_categories)} categories given a chip image."
    )
    print(f"{DIM}Vendor logins: <name>@{DEMO_DOMAIN} / {DEMO_PASSWORD}{RESET}")
    return 0


async def remove() -> int:
    async with SessionLocal() as db:
        owner_ids = (
            await db.execute(select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}")))
        ).scalars().all()

        if not owner_ids:
            print("Nothing to remove — no demo vendors found.")
            return 0

        restaurant_ids = (
            await db.execute(select(Restaurant.id).where(Restaurant.owner_id.in_(owner_ids)))
        ).scalars().all()

        # menu_categories and menu_items are ON DELETE CASCADE from the
        # restaurant, so this one delete takes the whole menu with it. The FK
        # from menu_categories to categories is SET NULL, so no chip is harmed.
        if restaurant_ids:
            await db.execute(delete(Restaurant).where(Restaurant.id.in_(restaurant_ids)))
        await db.execute(delete(User).where(User.id.in_(owner_ids)))

        # Only the images this script set — identified by the host.
        cleared = await db.execute(
            update(Category)
            .where(Category.image_url.like(f"{IMAGE_HOST}%"))
            .values(image_url=None)
        )
        await db.commit()

    print(
        f"{GREEN}Removed{RESET} {len(restaurant_ids)} demo restaurants, "
        f"{len(owner_ids)} demo vendors, {cleared.rowcount} chip images."
    )
    return 0


def main() -> int:
    args = set(sys.argv[1:])
    removing = "--remove" in args

    from app.core.config import settings

    # Host and database only — never print the password back at the operator.
    target = str(settings.DATABASE_URL).split("@")[-1]
    action = "DELETE all demo data from" if removing else "WRITE demo restaurants to"
    print(f"About to {action}:\n  {target}\n")

    if "--yes" not in args and input("Type 'yes' to continue: ").strip().lower() != "yes":
        print("Aborted.")
        return 1

    try:
        return asyncio.run(remove() if removing else seed())
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}Failed:{RESET} {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
