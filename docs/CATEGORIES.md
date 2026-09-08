# Browse categories

The row of chips on the customer home screen — Burger, Pizza, Biryani — and
everything behind it: how a vendor's menu section gets there, who approves it,
how a customer browses it, and how an administrator keeps it looking like a
product.

This document covers one feature end to end because it is the only feature that
crosses all three apps. The per-audience references are
[CUSTOMER-API.md](CUSTOMER-API.md), [VENDOR-API.md](VENDOR-API.md) and
[ADMIN-APP.md](ADMIN-APP.md).

---

## 1. The two things called "category"

This is the whole design in one distinction, and everything below depends on
getting it right.

| | **Menu section** (`menu_categories`) | **Browse category** (`categories`) |
|---|---|---|
| Whose | One restaurant's | The platform's |
| Example | KFC's "Zinger Burgers" | "Burger" |
| Seen where | KFC's menu page only | The home screen chip row, shared by every restaurant |
| Created by | The vendor, on their Menu tab | An administrator, or by a vendor's section name pending approval |
| Named by | The vendor, however they like | Curated: one name, one image, one spelling |

**A vendor's section name never leaves their page.** KFC calls it "Zinger
Burgers" and only KFC's customers ever see that string. What travels is the
link: that section is filed under the shared **Burger** category, so KFC now
appears when a customer taps the Burger chip.

One column carries the whole relationship: `menu_categories.category_id`. It is
nullable, and it is `ON DELETE SET NULL` — deleting a chip can never delete a
vendor's menu section.

---

## 2. Why it is built this way

### The split is standard

Every major food delivery platform separates a restaurant's own menu headings
from the taxonomy customers browse by. foodpanda, Uber Eats, DoorDash, Swiggy
and Zomato all do it.

The reason is that the two lists have incompatible requirements:

- A menu section must be **whatever the vendor wants**. "Chef's Specials",
  "Combo Deals", "Ramadan Iftar Box" are all good section names and none of
  them is a browse category.
- A browse chip must be **one name, with an image, in a deliberate order**.
  There is one Burger, it has a picture, and it sits where the operator put it.

Merging the two lists breaks both. Either every vendor's "Chef's Specials"
becomes a home screen chip, or vendors are forced to name their menu sections
from a fixed list, which no vendor will accept and which makes a restaurant's
menu read like a spreadsheet.

So the answer to "will customers only see KFC's category on KFC's page" is:
**the section, yes. The category it feeds, no, by design** — and that is what
makes the chip row work at all.

### Vendors grow the taxonomy, an administrator approves it

A section name that matches no existing category **creates one, hidden**. It
is linked to the vendor's section immediately and it reaches customers only
once an administrator approves it.

That middle position is deliberate, and it is worth being explicit about what
each half buys:

**Why vendors get to create at all.** A curated-only list is empty until
somebody fills it, and whoever fills it has to already know what the vendors
sell. The thirty seeded categories are a guess; the vendors are not guessing.
Kacchi and shawarma are seeded, but tehari, haleem, morog polao, fuchka and
jhalmuri are not, and a vendor selling those should not be invisible because
nobody thought to add the chip. The alternative also makes a small vendor wait
on an administrator a second time, after already waiting for approval once.

**Why it is hidden until approved.** The home screen is the most valuable
surface on the platform. Letting anyone who signs up write to it means that if
nobody watches the admin console, the chip row drifts into "Combo Deals" and
"Special Offer". The gate costs the vendor nothing, because their section and
its dishes are live on their own menu page the entire time. Only the chip
waits, and approving it is one click that publishes every restaurant that
accumulated under it at once.

The pattern the big platforms use is stricter still: staff own the list and a
vendor cannot add to it. That is right once your taxonomy has settled and the
review queue becomes noise. Section 9 has that change when you want it.

### Two hidden states, not one

`is_active` and `reviewed_at` are separate columns because "hidden, nobody has
looked at it" and "hidden, an administrator decided that" need opposite
handling. The first is a queue item; the second is a finished decision that
must never reappear in the queue.

| `is_active` | `reviewed_at` | Meaning | Where it shows |
|---|---|---|---|
| false | NULL | A vendor's section created it. Awaiting a decision. | The review queue |
| true | set | Approved. A live chip. | The home screen, once a restaurant sells under it |
| false | set | An administrator looked and said no. | The full admin list only |

Any admin write sets `reviewed_at`, including one that changes nothing. That
is how "I looked at this and it stays hidden" becomes a decision rather than a
row that comes back on every refresh.

---

## 3. Using it as a vendor

Nothing new is required. Create a menu section the way you already do:

```http
POST /vendor/menu/categories
{ "name": "Burgers", "sort_order": 1 }
```

The response now tells you where customers will find it:

```json
{
  "id": "…",
  "restaurant_id": "…",
  "name": "Burgers",
  "sort_order": 1,
  "is_active": true,
  "item_count": 0,
  "platform_category": {
    "id": "…",
    "name": "Burger",
    "slug": "burger",
    "image_url": "https://cdn.example/burger.png"
  }
}
```

`platform_category` is the chip. It appears on `GET /vendor/menu/categories`
and inside `GET /vendor/menu` too.

**Matching ignores case and spacing** and knows a list of alternative
spellings, so "burgers", "  BURGERS " and "Hamburgers" all resolve to Burger.
Matching an existing category is instant — nothing waits.

A name that matches nothing creates a **new chip awaiting approval**. Your
section and its dishes work immediately; the chip appears on the home screen
once an administrator approves it, and every restaurant that named a section
the same way is published with it. Nothing in the vendor API distinguishes the
two cases, deliberately: from the vendor's side a section is a section.

### Filing a section explicitly

A section whose name says nothing about the food — "Chef's Picks", "Combo
Deals" — should be filed by hand. `GET /categories` is the picker; it is
public, so the vendor app can call it without any special permission.

```http
POST /vendor/menu/categories
{ "name": "Chef's Picks", "platform_category_id": "…" }
```

Only approved categories appear in the picker and only approved ones can be
pinned to, so an id for a hidden or pending category is a 404.

### Changing the link later

`PATCH /vendor/menu/categories/{id}` follows PATCH rules, with one deliberate
twist on `platform_category_id`:

| You send | What happens |
|---|---|
| `"platform_category_id": "…"` | Pinned to that chip |
| `"platform_category_id": null` | Unlinked — the section stays on your menu, under no chip |
| Omitted, and you renamed the section | Re-matched by the **new** name, but the current link is kept if the new name matches nothing |
| Omitted, no rename | Left alone |

That third row is the important one. It means a typo cannot silently move your
restaurant out of Burger and into a chip called "Burgres". A section that is
currently unlinked *does* pick up a new category from a rename, because there
is nothing to protect.

### What takes you out of a chip

- `is_active: false` on the section. It disappears from your menu page and
  from the chip at the same time.
- The section having no live dishes. An empty "Desserts" section does not
  advertise desserts you cannot sell.
- Your restaurant being unverified or deactivated.

---

## 4. Using it as a customer client

### The chip row

`GET /home/feed` now carries `categories` alongside the existing `cuisines`:

```json
{
  "categories": [
    { "id": "…", "name": "Burger", "slug": "burger", "image_url": "https://…", "restaurant_count": 14 }
  ],
  "cuisines": [ { "name": "Bengali", "restaurant_count": 22, "image_url": null } ]
}
```

Render `image_url`, and fall back to a placeholder when it is `null` rather
than a broken image. The feed carries the first twelve; `GET /categories`
returns the full list for an "all categories" screen.

`cuisines` is the older restaurant-level tag list and still works. New clients
should render `categories` as the chip row.

Approval is invisible from here. An unapproved category is simply not in any
customer response.

### What a tap opens

Both take the `slug`, never the id:

```http
GET /restaurants?category=burger&lat=&lng=      # the restaurants
GET /categories/burger/items?lat=&lng=          # the dishes, across restaurants
```

The restaurant list is exactly as long as the chip's `restaurant_count` —
both come from the same rule (section 7), so the number on the chip can never
disagree with the screen behind it. Every other filter and sort still applies,
so `?category=burger&is_open=true&sort=rating` works.

The dish list is paginated and each row carries enough restaurant to draw a
card:

```json
{
  "id": "…", "name": "Zinger Burger", "description": "…", "image_url": "…",
  "base_price": 320, "is_veg": false, "is_available": true,
  "restaurant_id": "…", "restaurant_name": "KFC Dhanmondi",
  "restaurant_is_open": true, "restaurant_rating_avg": 4.4,
  "distance_km": 1.6
}
```

Ordering is orderable first, then open kitchens, then nearest, then best
rated. A sold-out dish from a closed restaurant is still an honest answer to
"who sells burgers", so it goes last rather than being hidden.

Send `lat`/`lng` to fill in `distance_km` and to bound the search by `radius`
(metres, capped at 25000). Without coordinates every visible restaurant's
dishes qualify and `distance_km` is `null`.

### Deep links

```http
GET /categories/burger
```

Resolves a slug on its own. Three behaviours worth knowing:

- An **empty** category returns `restaurant_count: 0` rather than 404. A link
  shared last week should open onto "nothing here yet", not a screen that
  looks broken.
- A **merged** slug keeps working and returns the survivor, so links shared
  before an administrator tidied up do not rot.
- A **hidden, pending or unknown** slug is a 404.

### Search

`GET /search?q=bur` now returns `categories` as well as restaurants and
dishes, so typing three letters offers the Burger chip above the
burger-named dishes. It matches names and aliases, and returns at most five.

---

## 5. Using it as an administrator

### The review queue

This is the job that has to be done regularly. Open `/admin/`, sign in with an
`ADMIN` account, pick the **Categories** tab and set the filter to **Needs
review**. Anything in that list is a category a vendor's section name created,
which means a vendor whose food is not yet browsable.

Each row tells you how many restaurants are waiting behind it, and the queue is
ordered by that, so the one holding up the most vendors is at the top.

Two buttons:

- **Approve — show to customers.** It becomes a live chip immediately, with
  every restaurant already under it.
- **Keep hidden.** Records that you decided, and takes it out of the queue
  permanently. Use it for "Combo Deals" and friends.

Neither one touches the vendor's menu, and neither is final: a kept-hidden
category can be shown later, and an approved one can be hidden again.

Over the API:

```http
GET   /admin/categories?pending=true&limit=100
PATCH /admin/categories/{id}   { "is_active": true }    # approve
PATCH /admin/categories/{id}   { "is_active": false }   # keep hidden
```

### Curating the rest

Selecting any row opens the edit form. **New category** opens it empty.

| Action | What it does |
|---|---|
| Name | Renames the chip. The slug does **not** change, and the old name is kept as an alias. |
| Image URL | The chip picture. Upload first (below), paste the public URL. |
| Pinned position | `0` is first. Blank means unpinned, and it sorts by restaurant count instead. |
| Also answers to | Comma-separated spellings vendors type. Replaces the whole list. |
| Shown to customers | The approve/hide switch, in checkbox form. |
| Delete | Only for a category no menu section links to. |
| Merge | Moves every section into another category and deletes this one. |

A category **you** create is approved by definition — you typed it — so it
never enters the queue and its `is_active` is honoured as sent.

### Merge is the one that matters

Three vendors will type "Burger", "Burgers" and "Hamburgers", and customers
must see one chip. Merging folds the loser into the survivor:

- every menu section moves across,
- the survivor learns the loser's name **and slug** as aliases, so that
  spelling resolves there from now on and old deep links keep working,
- the loser row is deleted.

It is not reversible, so the console asks for confirmation. Merging is usually
better than "keep hidden" for a duplicate, because it puts the vendor under a
real chip instead of under nothing.

### Hide vs delete vs merge

The three are not interchangeable and picking the wrong one loses work:

- **Hide** — "this should not be on the home screen." Everything stays linked;
  un-hiding restores it exactly.
- **Merge** — "these sections belong under a different chip." Nothing is lost;
  the restaurants keep a chip.
- **Delete** — "this row is junk and nothing points at it." Refused while any
  section links to it, because the foreign key would `SET NULL` and silently
  drop those restaurants out of their chip with no trace. A pending category
  always has at least one section behind it, so delete is not the tool there.

### Category images

The console cannot upload files directly; its Content-Security-Policy only
lets it talk to the API's own origin. Upload first, then paste:

```http
POST /uploads/presigned-url
{ "file_type": "image/png", "file_name": "burger.png" }
```

`PUT` the bytes to `upload_url` with the returned `headers`, then paste
`public_url` into the Image URL field. Returns 503 if Cloudflare R2 is not
configured in this environment — see [storage-setup-r2.md](storage-setup-r2.md).

---

## 6. Day one

Migration 0007 seeds thirty categories with their common alternative
spellings, **approved and visible**, and links every menu section that already
existed. Sections whose names it recognised are live at once. Sections whose
names it did not recognise get a category each, hidden and queued, exactly as
if they had been created after the migration.

What to do after that, in order:

1. **Apply the migration.** `make migrate`.
2. **Open the Categories tab, filter to Needs review.** This is the backfill's
   leftovers: every section name the seeded taxonomy did not recognise.
   Approve the real food, keep-hidden the rest, merge the duplicates.
3. **Add images** to the ones you want on the home screen. A chip with no
   image renders as a placeholder, which looks unfinished.
4. **Pin the top few** — `sort_order` 0, 1, 2 — so the first three chips are
   your choice rather than whichever category happens to have the most
   restaurants this week. Leave the rest unpinned and let demand sort them.

Then check the queue when you approve new vendors. It is empty most of the
time, because the seeded aliases absorb the common spellings.

---

## 7. How a chip is counted

One rule, used by the chip's `restaurant_count`, by
`GET /restaurants?category=`, and by whether the chip appears at all. They can
never disagree, because they are the same predicate in the code
(`category_service.restaurant_counts` and `category_service.sells_under`).

A restaurant counts under a category when **all** of these hold:

- the restaurant is **verified** and **active** (the same visibility rule the
  rest of discovery uses — `OPEN`/`CLOSED` is irrelevant, a closed kitchen
  still counts and still appears, greyed),
- it has a menu section that is **active**,
- that section is **linked** to the category,
- that section holds **at least one dish that is not soft-deleted**,
- and the category itself is **active**, which for a vendor-created one means
  approved.

Two deliberate choices in there:

- **A sold-out dish still counts.** `is_available` flickers dozens of times a
  service. A chip that appeared and vanished with it would look broken, and
  "they sell burgers, they're out right now" is still a true answer.
- **A restaurant counts once**, however many of its sections link to the
  category. "Beef Burgers" and "Chicken Burgers" is one burger place.

---

## 8. Reference

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /categories | public | Every approved category with restaurants under it, in chip order |
| GET | /categories/{slug} | public | One category, for deep links |
| GET | /categories/{slug}/items | public | Dishes in a category, across restaurants |
| GET | /restaurants?category={slug} | public | Restaurants in a category |
| GET | /home/feed | public | Carries the first twelve as `categories` |
| GET | /search?q= | public | Carries matching chips as `categories` |
| POST | /vendor/menu/categories | vendor | Optional `platform_category_id` |
| PATCH | /vendor/menu/categories/{id} | vendor | Optional `platform_category_id` |
| GET | /admin/categories | admin | All of them; `?pending=true` for the review queue |
| POST | /admin/categories | admin | Create one deliberately, already approved |
| PATCH | /admin/categories/{id} | admin | Approve, hide, rename, image, pin, aliases |
| DELETE | /admin/categories/{id} | admin | Only if nothing links to it |
| POST | /admin/categories/{id}/merge | admin | Fold into another category |

### Seeded categories

Burger, Pizza, Biryani, Kacchi, Fried Chicken, Kebab, Shawarma, Fast Food,
Bengali, Indian, Chinese, Thai, Rice, Noodles, Pasta, Seafood, Grill, Soup,
Sandwich, Snacks, Breakfast, Healthy, Dessert, Sweets, Cake, Ice Cream,
Coffee, Tea, Juice, Drinks.

Each carries aliases — Burger answers to "burgers", "hamburger" and
"hamburgers"; Biryani to "biriyani", "biryanis" and "biriani". The full list
is `SEED` in the migration. Adding to it is the cheapest way to keep the
review queue empty, since a recognised name never queues.

### Where the code lives

| Concern | File |
|---|---|
| Table | [app/models/category.py](../app/models/category.py) |
| Link column | `MenuCategory.category_id` in [app/models/menu.py](../app/models/menu.py) |
| Matching, approval, counting, curation | [app/services/category_service.py](../app/services/category_service.py) |
| Vendor linking | `_platform_for` in [app/services/menu_service.py](../app/services/menu_service.py) |
| Customer browsing | [app/services/customer/discovery.py](../app/services/customer/discovery.py) |
| Customer routes | [app/api/v1/endpoints/discovery.py](../app/api/v1/endpoints/discovery.py) |
| Admin routes | [app/api/v1/endpoints/admin.py](../app/api/v1/endpoints/admin.py) |
| Console tab | [app/static/admin/admin.js](../app/static/admin/admin.js) |
| Schema + backfill | `migrations/versions/20260908_0007_platform_categories.py` |
| Tests | [tests/test_categories.py](../tests/test_categories.py) |

### Naming rules

Three derived forms of a name, each with one job, all in
`category_service`:

- `match_key` — lower-cased, single-spaced. What two spellings are compared
  on and what `aliases` stores.
- `slug_for` — the public identifier. NFKD-normalised, so "Café" becomes
  `cafe`; a name with no Latin characters at all (বার্গার) gets a stable hash
  instead of an empty slug.
- `display_name` — how an auto-created category is shown. Capitalises words
  the vendor typed in lower case and leaves "BBQ" alone.

Migration 0007 carries a **snapshot** of the first two for its backfill rather
than importing them. A migration must produce the same result next year
whatever the service layer looks like by then.

---

## 9. Changing the policy

The gate is one value in `category_service.resolve`, and the two callers are
`_platform_for` and the rename branch of `update_category`, both in
[app/services/menu_service.py](../app/services/menu_service.py).

**To let vendors publish chips directly**, drop `is_active=False` from the
insert in `resolve`. New categories go live the moment a restaurant sells
under them, and the review queue stops filling. Faster for vendors, and it
hands the home screen to whoever signs up.

**To stop vendors creating categories at all**, swap `resolve` for
`find_by_name` at both call sites and let the link stay `null` when nothing
matches. Vendors then file unmatched sections by hand with
`platform_category_id` from the picker, and an administrator adds any genuinely
new category with `POST /admin/categories`. This is what the large platforms
do, and it is the right end state once your taxonomy stops growing.

Either change needs `tests/test_categories.py` updated — the approval tests
assert today's behaviour explicitly, which is the point of having them.
