# Ghetto City RPG bot

The first playable flow is deliberately small:

1. A new player chooses a nickname and character appearance.
2. They choose a destination and transport.
3. The bot shows the fare and travel time, then asks for confirmation.
4. On confirmation, the fare is charged once and the trip is stored.
5. A background worker completes the trip and sends an arrival message.
6. The persistent bottom keyboard separates the main menu from the travel tab.
   The menu opens profile, homes, vehicles, businesses, and help; travel opens
   destination selection, followed by transport selection.

The four initial destinations are the four districts named in the original
specification. Names, fares, travel times, starting balance, and images are
provisional catalog data in `config/gameplay.json`; adjust them there during
balancing. The map is visual only, not a route graph or territory grid.
Detailed map and Ghetto territory gameplay are intentionally deferred.

## Profile, homes, vehicles, and businesses

The profile displays the player's nickname, appearance, current city, balance,
active trip, and owned assets. Homes unlock garage slots. Personal vehicles
can be selected as free transport and are stored as distinct player-owned
instances. Businesses accrue configurable hourly income that can be collected
from the business screen; collection is capped at 24 hours and recorded in the
transaction ledger.

Starting funds, prices, vehicle travel times, garage slots, and business income
in `config/gameplay.json` are prototype balance values, not final economy
decisions. They can be adjusted without changing the game code.

The car dealer contains five real models, with no fictional starter vehicles:
Mercedes-AMG G 63, Mercedes-AMG C 63 S, BMW M5 Competition, Audi RS 6 Avant,
and Nissan GT-R R35. Each preview shows its photo, price, travel time, and
garage availability. Homes, businesses, and cars each have their own
photographic catalog cards, with previous/next navigation and a separate
purchase/collection button. Add catalog entries in `config/gameplay.json`;
their card images and attribution are loaded from those entries. Image credits
and source links are available from Help → Photo credits.

Photo credits and licenses:

- Mercedes-AMG G 63 — Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Mercedes-AMG_G_63_(2018)_IMG_4370.jpg).
- Mercedes-AMG C 63 S — Matti Blume, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Mercedes-AMG_C_63S_Coupe,_IAA_2017,_Frankfurt_(1Y7A3011).jpg).
- BMW M5 Competition — Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:BMW_M5_Competition_FL_IMG_3574.jpg).
- Audi RS 6 Avant — Charles from Port Chester, New York, [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/), [source](https://commons.wikimedia.org/wiki/File:Audi_RS_6_Avant_(2022)_(52566506314).jpg).
- Nissan GT-R R35 — Yu Chu Chin, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Nissan_GT-R_R35_at_the_2026_Adelaide_Motorsport_Festival_(DSCF2567).jpg).
- Dormitory room — Guillaume Speurt, [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/), [source](https://commons.wikimedia.org/wiki/File:My_room_in_the_dormitory_(7950132936).jpg).
- Apartment block — Matti Blume, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Apartment_block,_Zadar_(P1080730).jpg).
- Modern apartment building — Wiki.cullin, [CC0](https://creativecommons.org/publicdomain/zero/1.0/), [source](https://commons.wikimedia.org/wiki/File:Curved_modern_apartment_building_with_glass_stairwell_tower.jpg).
- Grocery store — Wolfmann, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:REMA_1000_Supermarket_interior_grocery_store_T%C3%B8nsberg,_Norway_2017-11-03_fruit_vegetables.jpg).
- Auto workshop — Sodiq Jimoh, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Cars_in_a_local_mechanic_workshop_in_Nigeria.jpg).
- Cafe — Kgbo, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), [source](https://commons.wikimedia.org/wiki/File:Interior_of_Medley_Caf%C3%A9_and_Restaurant,_Kangaroo_Point,_Queensland,_01.jpg).

## Playing in conversations

When the bot or a player is added to a VK conversation, the bot posts a link to
its private messages. Each player must complete nickname and appearance setup
in private messages before using the game in a conversation. Their account is
shared between private messages and conversations; once registered, game
menus and trip actions work in the conversation.

VK message deduplication uses the conversation message ID (or a stable event
hash when VK supplies no message ID), since group conversation messages may
have `id = 0`.

## Architecture

- `domain`: catalog definitions and game rules.
- `application`: use cases such as quoting and starting a trip.
- `infrastructure`: SQLite storage and transactional operations.
- `vk_gateway`: VK community long poll, callback keyboards, message delivery.
- `media`: image catalog and VK photo uploads.
- `jobs`: persisted trip completion and retryable arrival notifications.

The VK layer contains no fare calculation or trip-state rules. The SQLite
database stores players, trips, balance transactions, processed VK events, and
an outbox for arrival notifications. A restart does not lose an active trip.
The first MVP uses SQLite to be easy to run; PostgreSQL can replace it before
production as a separate migration task.

## Setup

Use Python 3.11 or newer:

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `VK_BOT_TOKEN` and the numeric `VK_GROUP_ID` in the local `.env`. Enable
community messages in VK. Never put a real token in source files or commit
`.env`; if a token was shared or exposed, revoke it and create another.

Run from the project directory:

```powershell
python -m ghetto_city
```

Generated message artwork is in `assets/images`. To regenerate the original
illustrations after editing `tools/generate_assets.py`:

```powershell
python tools/generate_assets.py
```

Run tests with:

```powershell
python -m pytest
```

## Current scope and next milestones

Implemented: nickname and appearance registration, persisted player profiles,
destination and transport selection, fare previews, atomic fare deduction,
duplicate-event protection, trip completion after restart, notification retry,
profile screen, home/vehicle/business purchases, personal-car trips, business
income collection, persistent bottom navigation, and image-backed messages.

Not implemented yet: selling/upgrading homes and vehicles, business
management/expansion, factions, missions, admin tooling, and production
deployment/backup procedures. Design decisions for the detailed map and
territory system remain open and are not assumed by this MVP.
