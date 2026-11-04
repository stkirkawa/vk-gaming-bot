import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghetto_city.application.game_service import GameService
from ghetto_city.domain.catalog import GameCatalog
from ghetto_city.infrastructure.database import Database
from ghetto_city.jobs.trip_worker import process_due_trips
from ghetto_city.media.catalog import MediaCatalog
from ghetto_city.vk_gateway.application import BotApplication
from ghetto_city.vk_gateway.longpoll import (
    _message_action_type,
    _message_event_id,
)

ROOT = Path(__file__).resolve().parents[1]


def register_player(service, user_id):
    service.get_or_create_player(user_id)
    service.set_nickname(user_id, f"Player {user_id}")
    return service.set_appearance(user_id, "no_mask")


def set_player_balance(database, user_id, balance):
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE players SET balance = ? WHERE user_id = ?",
            (balance, user_id),
        )


@pytest.fixture
def game(tmp_path):
    catalog = GameCatalog.load(ROOT / "config" / "gameplay.json")
    database = Database(tmp_path / "game.sqlite3")
    database.initialize()
    service = GameService(database, catalog)
    return database, catalog, service


def test_trip_charge_is_atomic_and_operation_is_idempotent(game):
    database, catalog, service = game
    player = register_player(service, 101)
    assert player.city_id == catalog.starting_city

    trip = service.start_trip(
        101, "business_ghetto", "bus", "confirm-event-1", now=1000
    )
    retry = service.start_trip(
        101, "business_ghetto", "bus", "confirm-event-1", now=2000
    )

    assert retry == trip
    assert database.get_player(101).balance == catalog.starting_balance - 800
    assert database.get_active_trip(101).arrival_at == 1110


def test_rejects_insufficient_funds_without_partial_trip(game):
    database, catalog, service = game
    register_player(service, 102)
    with closing(database.connect()) as connection:
        connection.execute("UPDATE players SET balance = 10 WHERE user_id = 102")

    with pytest.raises(ValueError, match="Not enough money"):
        service.start_trip(102, "business_ghetto", "bus", "poor-player", now=1000)

    assert database.get_player(102).balance == 10
    assert database.get_active_trip(102) is None


def test_trip_completion_updates_location_once_and_queues_notification(game):
    database, _, service = game
    register_player(service, 103)
    service.start_trip(103, "new_ghetto", "bus", "complete-once", now=1000)

    restarted_database = Database(database.path)
    restarted_database.initialize()

    assert restarted_database.get_active_trip(103).arrival_at == 1110
    assert restarted_database.complete_due_trips(now=1109) == []
    completed = restarted_database.complete_due_trips(now=1110)
    assert len(completed) == 1
    assert restarted_database.complete_due_trips(now=1200) == []
    assert restarted_database.get_player(103).city_id == "new_ghetto"
    assert len(restarted_database.pending_notifications()) == 1


def test_legacy_player_table_is_migrated_to_onboarding(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE players (
                user_id INTEGER PRIMARY KEY,
                city_id TEXT NOT NULL,
                balance INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO players VALUES (201, 'old_ghetto', 10000, 0)"
        )

    database = Database(database_path)
    database.initialize()

    player = database.get_player(201)
    assert player.onboarding_step == "nickname"
    assert player.nickname is None


def test_legacy_trip_tables_are_migrated_for_photo_credits(tmp_path):
    database_path = tmp_path / "legacy-trips.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE players (
                user_id INTEGER PRIMARY KEY,
                city_id TEXT NOT NULL,
                balance INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                origin_city_id TEXT NOT NULL,
                destination_city_id TEXT NOT NULL,
                transport_id TEXT NOT NULL,
                fare INTEGER NOT NULL,
                started_at REAL NOT NULL,
                arrival_at REAL NOT NULL,
                status TEXT NOT NULL,
                completed_at REAL,
                transport_name TEXT,
                transport_image TEXT
            );
            CREATE TABLE notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                destination_city_id TEXT NOT NULL,
                transport_id TEXT NOT NULL,
                transport_name TEXT,
                transport_image TEXT,
                created_at REAL NOT NULL,
                sent_at REAL
            );
            """
        )

    database = Database(database_path)
    database.initialize()

    with closing(database.connect()) as connection:
        trip_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(trips)")
        }
        notification_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(notification_outbox)"
            )
        }
    assert "transport_credit" in trip_columns
    assert "transport_credit" in notification_columns


def test_nickname_validation_and_case_insensitive_uniqueness(game):
    _, _, service = game
    service.get_or_create_player(202)
    service.get_or_create_player(203)

    with pytest.raises(ValueError, match="от 3 до 20"):
        service.set_nickname(202, "ab")
    service.set_nickname(202, "City Player")
    with pytest.raises(ValueError, match="уже занят"):
        service.set_nickname(203, "city player")


def test_home_vehicle_and_business_purchases_are_persistent_and_idempotent(game):
    database, catalog, service = game
    register_player(service, 204)
    set_player_balance(database, 204, 300000)

    assert service.buy_home(204, "room", "home-purchase")
    assert not service.buy_home(204, "room", "home-purchase")
    with pytest.raises(ValueError, match="уже принадлежит"):
        service.buy_home(204, "room", "duplicate-home")

    assert service.buy_vehicle(204, "mercedes_amg_g63", "vehicle-purchase")
    assert not service.buy_vehicle(204, "mercedes_amg_g63", "vehicle-purchase")
    assert database.get_player(204).balance == (
        300000
        - catalog.homes["room"].price
        - catalog.vehicles["mercedes_amg_g63"].price
    )
    assets = database.get_player_assets(204)
    assert assets["homes"][0]["home_id"] == "room"
    assert assets["vehicles"][0]["vehicle_id"] == "mercedes_amg_g63"

    assert service.buy_business(204, "corner_store", "business-purchase")
    assert database.get_player_assets(204)["businesses"][0]["business_id"] == (
        "corner_store"
    )


def test_vehicle_capacity_is_checked_inside_purchase_transaction(game):
    database, _, service = game
    register_player(service, 205)

    with pytest.raises(ValueError, match="Сначала купите дом"):
        service.buy_vehicle(205, "mercedes_amg_g63", "car-without-garage")

    set_player_balance(database, 205, 200000)
    service.buy_home(205, "room", "one-slot-home")
    service.buy_vehicle(205, "mercedes_amg_g63", "first-car")
    with pytest.raises(ValueError, match="Нет свободного места"):
        service.buy_vehicle(205, "mercedes_amg_g63", "second-car")
    assert len(database.get_player_assets(205)["vehicles"]) == 1


def test_business_income_is_collected_once_per_elapsed_period(game):
    database, catalog, service = game
    register_player(service, 206)
    service.buy_business(206, "corner_store", "income-business")
    business = catalog.businesses["corner_store"]
    owned = database.get_player_assets(206)["businesses"][0]
    payout_time = owned["last_payout_at"] + business.period_seconds * 3

    amount, operation_id = database.claim_business_income(
        206,
        business.id,
        business.income_per_period,
        business.period_seconds,
        payout_time,
    )
    assert amount == business.income_per_period * 3
    assert operation_id
    assert service.claim_business_income(206, business.id) == 0
    assert database.get_player(206).balance == (
        catalog.starting_balance - business.price + amount
    )
    with closing(database.connect()) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE reason LIKE 'business-income:%'"
        ).fetchone()
    assert rows["count"] == 1


def test_personal_vehicle_can_be_selected_for_trip(game):
    database, catalog, service = game
    register_player(service, 207)
    set_player_balance(database, 207, 200000)
    service.buy_home(207, "room", "vehicle-home")
    service.buy_vehicle(207, "mercedes_amg_g63", "vehicle-car")
    vehicle_instance = database.get_player_assets(207)["vehicles"][0]["id"]
    transport_id = f"personal_vehicle:{vehicle_instance}"

    assert transport_id in {
        transport.id for transport in service.available_transports(207)
    }
    trip = service.start_trip(
        207,
        "business_ghetto",
        transport_id,
        "personal-vehicle-trip",
        now=1000,
    )
    assert trip.fare == 0
    assert trip.transport_name == catalog.vehicles["mercedes_amg_g63"].name
    assert trip.transport_image == catalog.vehicles["mercedes_amg_g63"].image
    assert database.get_player(207).balance == (
        200000
        - catalog.homes["room"].price
        - catalog.vehicles["mercedes_amg_g63"].price
    )


def test_personal_vehicle_trip_uses_saved_arrival_notification(game):
    database, catalog, service = game
    register_player(service, 209)
    set_player_balance(database, 209, 200000)
    service.buy_home(209, "room", "notification-home")
    service.buy_vehicle(209, "mercedes_amg_g63", "notification-car")
    vehicle_instance = database.get_player_assets(209)["vehicles"][0]["id"]
    transport_id = f"personal_vehicle:{vehicle_instance}"
    transport = service.get_transport(209, transport_id)
    service.start_trip(
        209,
        "business_ghetto",
        transport_id,
        "notification-trip",
        now=1000,
    )
    sent = []

    process_due_trips(
        database,
        catalog,
        MediaCatalog(ROOT / "assets"),
        lambda user_id, text, image: sent.append((user_id, text, image)),
        now=1000 + transport.duration_seconds,
    )

    assert sent[0][0] == 209
    assert catalog.vehicles["mercedes_amg_g63"].name in sent[0][1]
    assert sent[0][2].endswith(catalog.vehicles["mercedes_amg_g63"].image)


def test_real_car_catalog_has_individual_attributed_photos(game):
    _, catalog, _ = game
    expected = {
        "mercedes_amg_g63",
        "mercedes_amg_c63s",
        "bmw_m5_competition",
        "audi_rs6_avant",
        "nissan_gtr_r35",
    }

    assert set(catalog.vehicles) == expected
    assert expected.issubset(catalog.vehicles)
    for vehicle_id in expected:
        vehicle = catalog.vehicles[vehicle_id]
        assert vehicle.image != "vehicle_catalog.png"
        assert vehicle.image_credit.startswith("Фото:")
        assert MediaCatalog(ROOT / "assets").image(vehicle.image).is_file()


def test_real_car_preview_displays_photo_credit_and_purchase_button(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 211)
    service.buy_home(211, "room", "preview-home")

    application.handle_callback(
        211,
        211,
        {"action": "preview_vehicle", "vehicle_id": "mercedes_amg_g63"},
        "preview-g63",
    )

    vehicle = catalog.vehicles["mercedes_amg_g63"]
    message = sender.messages[-1]
    assert message["image"] == vehicle.image
    assert vehicle.name in message["text"]
    assert vehicle.image_credit not in message["text"]
    buttons = json.loads(message["keyboard"])["buttons"]
    payloads = [
        json.loads(button["action"]["payload"])
        for row in buttons
        for button in row
    ]
    purchase_payload = next(
        payload for payload in payloads if payload["action"] == "buy_vehicle"
    )
    assert purchase_payload == {
        "action": "buy_vehicle",
        "vehicle_id": "mercedes_amg_g63",
    }

    application.handle_message(211, 211, "ℹ️ Помощь", "photo-help")
    help_buttons = json.loads(sender.messages[-1]["keyboard"])["buttons"]
    credits_payload = json.loads(help_buttons[0][0]["action"]["payload"])
    assert credits_payload["action"] == "image_credits"
    application.handle_callback(211, 211, credits_payload, "photo-credits")
    credits_message = sender.messages[-1]["text"]
    for model_id in (
        "mercedes_amg_g63",
        "mercedes_amg_c63s",
        "bmw_m5_competition",
        "audi_rs6_avant",
        "nissan_gtr_r35",
    ):
        assert catalog.vehicles[model_id].image_credit in credits_message
    for home in catalog.homes.values():
        assert home.image_credit in credits_message
    for business in catalog.businesses.values():
        assert business.image_credit in credits_message


def test_business_shop_cycles_through_real_photo_cards(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 215)
    application.handle_message(215, 215, "🏢 Бизнес", "business-shop")

    businesses = tuple(catalog.businesses.values())
    for index, business in enumerate(businesses):
        message = sender.messages[-1]
        assert f"{index + 1}/{len(businesses)}" in message["text"]
        assert business.name in message["text"]
        assert message["image"] == business.image
        buttons = json.loads(message["keyboard"])["buttons"]
        payloads = [
            json.loads(button["action"]["payload"])
            for row in buttons
            for button in row
        ]
        next_page = next(
            payload
            for payload in payloads
            if payload["action"] == "business_page"
            and payload["business_id"]
            == businesses[(index + 1) % len(businesses)].id
        )
        application.handle_callback(
            215, 215, next_page, f"business-page-{index}"
        )

    assert businesses[0].name in sender.messages[-1]["text"]
    assert f"1/{len(businesses)}" in sender.messages[-1]["text"]


def test_business_purchase_uses_its_catalog_photo(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 216)

    application.handle_callback(
        216,
        216,
        {"action": "buy_business", "business_id": "corner_store"},
        "business-purchase-photo",
    )

    assert database.get_player_assets(216)["businesses"][0]["business_id"] == (
        "corner_store"
    )
    assert sender.messages[-2]["image"] == catalog.businesses["corner_store"].image
    assert "Продуктовый магазин" in sender.messages[-2]["text"]


def test_vehicle_shop_next_button_cycles_through_catalog(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 213)
    application.handle_message(213, 213, "🚘 Авто", "vehicle-shop")

    vehicles = tuple(catalog.vehicles.values())
    for index, vehicle in enumerate(vehicles):
        message = sender.messages[-1]
        assert f"{index + 1}/{len(vehicles)}" in message["text"]
        assert vehicle.name in message["text"]
        assert message["image"] == vehicle.image
        buttons = json.loads(message["keyboard"])["buttons"]
        payloads = [
            json.loads(button["action"]["payload"])
            for row in buttons
            for button in row
        ]
        next_page = next(
            payload for payload in payloads
            if payload["action"] == "vehicle_page"
            and payload["vehicle_id"] == vehicles[(index + 1) % len(vehicles)].id
        )
        application.handle_callback(
            213, 213, next_page, f"vehicle-page-{index}"
        )

    assert vehicles[0].name in sender.messages[-1]["text"]
    assert f"1/{len(vehicles)}" in sender.messages[-1]["text"]


def test_home_shop_next_button_opens_each_house_card(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 214)
    application.handle_message(214, 214, "🏠 Дома", "home-shop")

    homes = tuple(catalog.homes.values())
    for index, home in enumerate(homes):
        message = sender.messages[-1]
        assert f"{index + 1}/{len(homes)}" in message["text"]
        assert home.name in message["text"]
        assert message["image"] == home.image
        buttons = json.loads(message["keyboard"])["buttons"]
        payloads = [
            json.loads(button["action"]["payload"])
            for row in buttons
            for button in row
        ]
        next_page = next(
            payload for payload in payloads
            if payload["action"] == "home_page"
            and payload["home_id"] == homes[(index + 1) % len(homes)].id
        )
        application.handle_callback(214, 214, next_page, f"home-page-{index}")

    assert homes[0].name in sender.messages[-1]["text"]
    assert f"1/{len(homes)}" in sender.messages[-1]["text"]


def test_real_car_photo_credit_is_saved_with_trip_notification(game):
    database, catalog, service = game
    register_player(service, 212)
    set_player_balance(database, 212, 200000)
    service.buy_home(212, "room", "credit-home")
    service.buy_vehicle(212, "mercedes_amg_g63", "credit-car")
    vehicle_instance = database.get_player_assets(212)["vehicles"][0]["id"]
    transport = service.get_transport(212, f"personal_vehicle:{vehicle_instance}")
    trip = service.start_trip(
        212,
        "business_ghetto",
        f"personal_vehicle:{vehicle_instance}",
        "credit-trip",
        now=1000,
    )
    assert trip.transport_credit == transport.image_credit
    sent = []

    process_due_trips(
        database,
        catalog,
        MediaCatalog(ROOT / "assets"),
        lambda user_id, text, image: sent.append((user_id, text, image)),
        now=1000 + transport.duration_seconds,
    )

    assert transport.image_credit not in sent[0][1]
    assert sent[0][2].endswith(transport.image)


def test_every_configured_choice_has_an_image(game):
    _, catalog, _ = game
    media = MediaCatalog(ROOT / "assets")
    filenames = [
        "city_overview.png",
        "appearance_choices.png",
        "profile_card.png",
    ]
    filenames.extend(city.image for city in catalog.destinations.values())
    filenames.extend(transport.image for transport in catalog.transports.values())
    filenames.extend(home.image for home in catalog.homes.values())
    filenames.extend(vehicle.image for vehicle in catalog.vehicles.values())
    filenames.extend(business.image for business in catalog.businesses.values())

    for filename in filenames:
        assert media.image(filename).is_file()


def test_worker_retries_notification_after_send_error(game):
    database, catalog, service = game
    media = MediaCatalog(ROOT / "assets")
    register_player(service, 104)
    service.start_trip(104, "new_ghetto", "bus", "worker-retry", now=1000)

    def fail_send(*_args):
        raise OSError("temporary send failure")

    with pytest.raises(OSError):
        process_due_trips(database, catalog, media, fail_send, now=1110)
    assert len(database.pending_notifications()) == 1

    sent = []
    process_due_trips(
        database,
        catalog,
        media,
        lambda user_id, text, image: sent.append((user_id, text, image)),
        now=1111,
    )
    assert len(sent) == 1
    assert sent[0][0] == 104
    assert len(database.pending_notifications()) == 0


class FakeSender:
    def __init__(self):
        self.messages = []

    def send(self, peer_id, text, image, keyboard=None):
        self.messages.append(
            {"peer_id": peer_id, "text": text, "image": image, "keyboard": keyboard}
        )


def test_bot_guides_player_through_city_and_transport_choices(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )

    application.handle_message(105, 105, "/start", "message:1")
    first_message = sender.messages[-1]
    assert "Придумайте игровой никнейм" in first_message["text"]
    assert first_message["image"] == "city_overview.png"
    application.handle_message(105, 105, "Street Player", "message:2")
    assert "Выберите внешний вид" in sender.messages[-1]["text"]
    assert sender.messages[-1]["image"] == "appearance_choices.png"

    application.handle_callback(
        105,
        105,
        {"action": "appearance", "appearance_id": "no_mask"},
        "callback:appearance",
    )
    assert "Old Ghetto Street" in sender.messages[-1]["text"]
    assert "Главное меню Ghetto City" in sender.messages[-1]["text"]
    assert "Поездка" in sender.messages[-1]["text"]
    menu_buttons = json.loads(sender.messages[-1]["keyboard"])["buttons"]
    menu_actions = {
        json.loads(button["action"]["payload"])["action"]
        for row in menu_buttons
        for button in row
    }
    assert menu_actions == {"profile", "homes", "vehicles", "businesses", "help"}

    application.handle_message(105, 105, "🚕 Поездка", "message:travel")
    assert "Куда отправимся?" in sender.messages[-1]["text"]

    application.handle_callback(
        105,
        105,
        {"action": "city", "city_id": "business_ghetto"},
        "callback:1",
    )
    assert "На чём поедем?" in sender.messages[-1]["text"]
    assert sender.messages[-1]["image"] == "city_business_ghetto.png"

    application.handle_callback(
        105,
        105,
        {
            "action": "transport",
            "city_id": "business_ghetto",
            "transport_id": "bus",
        },
        "callback:2",
    )
    assert "Подтвердить поездку?" in sender.messages[-1]["text"]
    assert sender.messages[-1]["image"] == "transport_bus.png"
    assert json.loads(sender.messages[-1]["keyboard"])["buttons"]


def test_bottom_keyboard_opens_profile_assets_and_help(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        GameCatalog.load(ROOT / "config" / "gameplay.json"),
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 208)

    application.handle_message(208, 208, "👤 Профиль", "menu-profile")
    assert "Профиль: Player 208" in sender.messages[-1]["text"]
    assert "Баланс:" in sender.messages[-1]["text"]
    keyboard = json.loads(sender.messages[-1]["keyboard"])
    assert keyboard["one_time"] is False
    assert keyboard["inline"] is False

    application.handle_message(208, 208, "📋 Меню", "menu-main")
    assert "Главное меню Ghetto City" in sender.messages[-1]["text"]
    menu_buttons = json.loads(sender.messages[-1]["keyboard"])["buttons"]
    assert len(menu_buttons) == 3

    application.handle_message(208, 208, "🚕 Поездка", "menu-travel")
    assert "Куда отправимся?" in sender.messages[-1]["text"]
    travel_keyboard = json.loads(sender.messages[-1]["keyboard"])
    assert travel_keyboard["inline"] is False
    assert "📋 Меню" in {
        button["action"]["label"] for row in travel_keyboard["buttons"] for button in row
    }

    application.handle_message(208, 208, "🏠 Дома", "menu-homes")
    assert "Комната в общежитии" in sender.messages[-1]["text"]
    home_keyboard = json.loads(sender.messages[-1]["keyboard"])
    assert home_keyboard["inline"] is True
    assert f"1/{len(catalog.homes)}" in sender.messages[-1]["text"]

    application.handle_message(208, 208, "🏢 Бизнес", "menu-business")
    assert "Продуктовый магазин" in sender.messages[-1]["text"]
    business_keyboard = json.loads(sender.messages[-1]["keyboard"])
    assert f"1/{len(catalog.businesses)}" in sender.messages[-1]["text"]
    assert sender.messages[-1]["image"] == next(
        iter(catalog.businesses.values())
    ).image
    assert business_keyboard["inline"] is True
    assert len(business_keyboard["buttons"]) == 2
    assert sender.messages[-1]["image"] == next(
        iter(catalog.businesses.values())
    ).image
    application.handle_message(208, 208, "🚘 Авто", "menu-cars")
    assert "Гараж: 0/0" in sender.messages[-1]["text"]
    assert "Mercedes-AMG G 63" in sender.messages[-1]["text"]
    assert f"1/{len(catalog.vehicles)}" in sender.messages[-1]["text"]
    vehicle_keyboard = json.loads(sender.messages[-1]["keyboard"])
    assert vehicle_keyboard["inline"] is True
    assert len(vehicle_keyboard["buttons"]) == 2
    application.handle_message(208, 208, "ℹ️ Помощь", "menu-help")
    assert "Поездка — выбор города" in sender.messages[-1]["text"]


def test_asset_purchase_callback_updates_profile(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        GameCatalog.load(ROOT / "config" / "gameplay.json"),
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 210)

    application.handle_callback(
        210,
        210,
        {"action": "buy_home", "home_id": "room"},
        "asset-home-buy",
    )

    assert database.get_player_assets(210)["homes"][0]["home_id"] == "room"
    assert sender.messages[-2]["image"] == catalog.homes["room"].image
    assert sender.messages[-1]["image"] == "profile_card.png"
    assert "Комната в общежитии" in sender.messages[-1]["text"]


def test_confirm_callback_charges_once(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    register_player(service, 107)
    payload = {
        "action": "confirm",
        "city_id": "business_ghetto",
        "transport_id": "bus",
    }

    application.handle_callback(107, 107, payload, "confirm-event")
    application.handle_callback(107, 107, payload, "confirm-event")

    assert database.get_player(107).balance == catalog.starting_balance - 800
    assert database.get_active_trip(107) is not None
    assert len(sender.messages) == 1
    assert "Поездка в Business Ghetto Street началась" in sender.messages[0]["text"]


def test_chat_invite_points_to_private_account_creation(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    chat_peer_id = 2_000_000_123
    application.handle_chat_invite(chat_peer_id, "invite:1")
    application.handle_chat_invite(chat_peer_id, "invite:1")

    assert sender.messages[-1]["peer_id"] == chat_peer_id
    assert "создайте аккаунт в личных" in sender.messages[-1]["text"]
    button = json.loads(sender.messages[-1]["keyboard"])["buttons"][0][0]["action"]
    assert button["type"] == "open_link"
    assert button["link"] == "https://vk.me/club157163771"


def test_chat_requires_dm_registration_then_allows_gameplay(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )
    user_id = 109
    chat_peer_id = 2_000_000_124

    application.handle_message(user_id, chat_peer_id, "привет", "chat:1")
    assert database.get_player(user_id) is None
    assert "создайте аккаунт в личных" in sender.messages[-1]["text"]

    application.handle_message(user_id, user_id, "/start", "dm:1")
    application.handle_message(user_id, user_id, "Chat Player", "dm:2")
    application.handle_callback(
        user_id,
        user_id,
        {"action": "appearance", "appearance_id": "no_mask"},
        "dm:3",
    )
    assert database.get_player(user_id).onboarding_step == "complete"

    application.handle_message(user_id, chat_peer_id, "меню", "chat:2")
    assert sender.messages[-1]["peer_id"] == chat_peer_id
    assert "Главное меню Ghetto City" in sender.messages[-1]["text"]
    assert "Поездка" in sender.messages[-1]["text"]
    assert database.get_player(user_id).city_id == catalog.starting_city


def test_message_event_ids_use_conversation_message_id():
    first = SimpleNamespace(peer_id=2_000_000_123, id=0, conversation_message_id=41)
    second = SimpleNamespace(peer_id=2_000_000_123, id=0, conversation_message_id=42)

    assert _message_event_id(first, {}) != _message_event_id(second, {})


def test_message_event_ids_have_stable_fallback_when_vk_id_is_zero():
    message = SimpleNamespace(peer_id=2_000_000_123, id=0, conversation_message_id=0)

    assert _message_event_id(message, {"object": {"text": "first"}}) == (
        _message_event_id(message, {"object": {"text": "first"}})
    )
    assert _message_event_id(message, {"object": {"text": "first"}}) != (
        _message_event_id(message, {"object": {"text": "second"}})
    )


def test_chat_invite_action_is_read_from_mapping_or_object():
    assert _message_action_type(
        SimpleNamespace(action={"type": "chat_invite_user"})
    ) == "chat_invite_user"
    assert _message_action_type(
        SimpleNamespace(action=SimpleNamespace(type="chat_invite_user_by_link"))
    ) == "chat_invite_user_by_link"


def test_duplicate_vk_event_is_ignored(game):
    database, catalog, service = game
    sender = FakeSender()
    application = BotApplication(
        database,
        catalog,
        service,
        MediaCatalog(ROOT / "assets"),
        sender,
        group_id=157163771,
    )

    application.handle_message(106, 106, "/start", "message:duplicate")
    application.handle_message(106, 106, "/start", "message:duplicate")

    assert len(sender.messages) == 1
