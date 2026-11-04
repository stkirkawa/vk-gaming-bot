import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from ghetto_city.application.game_service import GameService
from ghetto_city.domain.catalog import GameCatalog, Transport
from ghetto_city.infrastructure.database import Database, Player
from ghetto_city.media.catalog import MediaCatalog

logger = logging.getLogger(__name__)


class MessageSender(Protocol):
    def send(
        self,
        peer_id: int,
        text: str,
        image: str,
        keyboard: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class Button:
    label: str
    action: str
    value: str = ""


class BotApplication:
    MENU_PROFILE = "👤 Профиль"
    MENU_MAIN = "📋 Меню"
    MENU_CITY = "🚕 Поездка"
    MENU_HOMES = "🏠 Дома"
    MENU_VEHICLES = "🚘 Авто"
    MENU_BUSINESSES = "🏢 Бизнес"
    MENU_HELP = "ℹ️ Помощь"

    def __init__(
        self,
        database: Database,
        catalog: GameCatalog,
        service: GameService,
        media: MediaCatalog,
        sender: MessageSender,
        group_id: int,
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.service = service
        self.media = media
        self.sender = sender
        self.group_id = group_id

    def handle_message(
        self, user_id: int, peer_id: int, text: str, event_id: str
    ) -> None:
        if not self.database.record_event(event_id, time.time()):
            logger.info("Ignoring duplicate VK event %s", event_id)
            return

        if self._is_conversation(peer_id):
            player = self.database.get_player(user_id)
            if player is None or player.onboarding_step != "complete":
                self._send_chat_registration_prompt(peer_id)
                return

        player, is_new = self.service.get_or_create_player(user_id)
        if is_new:
            self._send_nickname_prompt(peer_id)
            return

        if player.onboarding_step == "nickname":
            try:
                player = self.service.set_nickname(user_id, text)
            except ValueError as error:
                self._send_nickname_prompt(peer_id, str(error))
                return
            self._send_appearance_selection(peer_id, player)
            return
        if player.onboarding_step == "appearance":
            self._send_appearance_selection(peer_id, player)
            return

        normalized = text.strip().lower()
        if normalized in {self.MENU_MAIN.lower(), "меню", "menu", "/start"}:
            self._send_main_menu(peer_id, player)
        elif normalized in {
            self.MENU_PROFILE.lower(),
            "профиль",
            "profile",
        }:
            self._send_profile(peer_id, user_id)
        elif normalized in {self.MENU_HOMES.lower(), "дома", "недвижимость"}:
            self._send_homes(peer_id, user_id)
        elif normalized in {
            self.MENU_CITY.lower(),
            "город",
            "поехать",
            "путешествие",
        }:
            self._send_city_selection(peer_id, player)
        elif normalized in {self.MENU_VEHICLES.lower(), "авто", "машины"}:
            self._send_vehicles(peer_id, user_id)
        elif normalized in {self.MENU_BUSINESSES.lower(), "бизнес", "бизнесы"}:
            self._send_businesses(peer_id, user_id)
        elif normalized in {self.MENU_HELP.lower(), "помощь", "/help"}:
            self._send_help(peer_id)
        elif normalized in {"авторы фото", "фото и лицензии"}:
            self._send_image_credits(peer_id)
        elif any(
            normalized == city.name.lower() or normalized == city.id.lower()
            for city in self.catalog.destinations.values()
        ):
            destination = next(
                city
                for city in self.catalog.destinations.values()
                if normalized in {city.name.lower(), city.id.lower()}
            )
            self._send_transport_selection(peer_id, user_id, destination.id)
        else:
            self._send_main_menu(peer_id, player)

    def handle_callback(
        self,
        user_id: int,
        peer_id: int,
        payload: dict | str | None,
        event_id: str,
    ) -> None:
        if not self.database.record_event(event_id, time.time()):
            logger.info("Ignoring duplicate VK callback %s", event_id)
            return

        if self._is_conversation(peer_id):
            player = self.database.get_player(user_id)
            if player is None or player.onboarding_step != "complete":
                self._send_chat_registration_prompt(peer_id)
                return

        player, is_new = self.service.get_or_create_player(user_id)
        if is_new:
            self._send_nickname_prompt(peer_id)
            return

        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            if not isinstance(data, dict):
                raise ValueError("Invalid button payload")
            action = data.get("action")
            if not isinstance(action, str):
                raise ValueError("Invalid button action")
            if action == "appearance":
                player = self.service.set_appearance(
                    user_id, self._required_text(data, "appearance_id")
                )
                self._send_main_menu(peer_id, player, greeting=True)
            elif player.onboarding_step == "nickname":
                self._send_nickname_prompt(peer_id)
            elif player.onboarding_step == "appearance":
                self._send_appearance_selection(peer_id, player)
            elif action == "city":
                self._send_transport_selection(
                    peer_id, user_id, self._required_text(data, "city_id")
                )
            elif action == "transport":
                self._send_trip_confirmation(
                    peer_id,
                    user_id,
                    self._required_text(data, "city_id"),
                    self._required_text(data, "transport_id"),
                )
            elif action == "confirm":
                self._confirm_trip(
                    peer_id,
                    user_id,
                    self._required_text(data, "city_id"),
                    self._required_text(data, "transport_id"),
                    event_id,
                )
            elif action == "menu":
                self._send_main_menu(peer_id, player)
            elif action == "travel":
                self._send_city_selection(peer_id, player)
            elif action == "help":
                self._send_help(peer_id)
            elif action == "image_credits":
                self._send_image_credits(peer_id)
            elif action == "profile":
                self._send_profile(peer_id, user_id)
            elif action == "homes":
                self._send_homes(peer_id, user_id)
            elif action == "home_page":
                self._send_home_page(
                    peer_id, user_id, self._required_text(data, "home_id")
                )
            elif action == "vehicles":
                self._send_vehicles(peer_id, user_id)
            elif action in {"preview_vehicle", "vehicle_page"}:
                self._send_vehicle_preview(
                    peer_id, user_id, self._required_text(data, "vehicle_id")
                )
            elif action == "businesses":
                self._send_businesses(peer_id, user_id)
            elif action == "business_page":
                self._send_business_page(
                    peer_id, user_id, self._required_text(data, "business_id")
                )
            elif action == "buy_home":
                home_id = self._required_text(data, "home_id")
                bought = self.service.buy_home(
                    user_id,
                    home_id,
                    f"vk-event:{event_id}",
                )
                home = self.catalog.homes[home_id]
                self.sender.send(
                    peer_id,
                    (
                        f"Дом «{home.name}» куплен."
                        if bought
                        else "Покупка уже была обработана."
                    ),
                    home.image,
                    self._main_keyboard(),
                )
                self._send_profile(peer_id, user_id)
            elif action == "buy_vehicle":
                vehicle_id = self._required_text(data, "vehicle_id")
                bought = self.service.buy_vehicle(
                    user_id,
                    vehicle_id,
                    f"vk-event:{event_id}",
                )
                vehicle = self.catalog.vehicles[vehicle_id]
                message = (
                    "Автомобиль куплен."
                    if bought
                    else "Покупка уже была обработана."
                )
                self.sender.send(
                    peer_id,
                    message,
                    vehicle.image,
                    self._main_keyboard(),
                )
                self._send_profile(peer_id, user_id)
            elif action == "buy_business":
                business_id = self._required_text(data, "business_id")
                bought = self.service.buy_business(
                    user_id,
                    business_id,
                    f"vk-event:{event_id}",
                )
                business = self.catalog.businesses[business_id]
                self.sender.send(
                    peer_id,
                    (
                        f"Бизнес «{business.name}» куплен."
                        if bought
                        else "Покупка уже была обработана."
                    ),
                    business.image,
                    self._main_keyboard(),
                )
                self._send_profile(peer_id, user_id)
            elif action == "claim_business":
                business_id = self._required_text(data, "business_id")
                amount = self.service.claim_business_income(
                    user_id, business_id
                )
                text = (
                    f"Получено {amount}$ дохода."
                    if amount
                    else "Пока нет накопленного дохода."
                )
                self.sender.send(
                    peer_id,
                    text,
                    self.catalog.businesses[business_id].image,
                    self._main_keyboard(),
                )
                self._send_business_page(peer_id, user_id, business_id)
            else:
                raise ValueError("Unknown button action")
        except ValueError as error:
            logger.info("Rejected VK button action for user %s: %s", user_id, error)
            self.sender.send(
                peer_id,
                f"Не получилось выполнить действие: {error}",
                "city_overview.png",
                self._main_keyboard(),
            )

    def handle_chat_invite(self, peer_id: int, event_id: str) -> None:
        if not self.database.record_event(event_id, time.time()):
            logger.info("Ignoring duplicate VK chat invite %s", event_id)
            return
        self._send_chat_registration_prompt(peer_id)

    def _send_chat_registration_prompt(self, peer_id: int) -> None:
        link = f"https://vk.me/club{self.group_id}"
        keyboard = VkKeyboard(one_time=True, inline=True)
        keyboard.add_openlink_button("Открыть бота в ЛС", link)
        self.sender.send(
            peer_id,
            "Чтобы играть в этой беседе, сначала создайте аккаунт в личных "
            "сообщениях с ботом. Откройте ЛС, завершите регистрацию, затем "
            "вернитесь сюда и отправьте любое сообщение.",
            "city_overview.png",
            keyboard.get_keyboard(),
        )

    @staticmethod
    def _is_conversation(peer_id: int) -> bool:
        return peer_id >= 2_000_000_000

    @staticmethod
    def _required_text(data: dict, key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Invalid {key} in button payload")
        return value

    def _send_city_selection(
        self, peer_id: int, player: Player, greeting: bool = False
    ) -> None:
        if player.onboarding_step == "nickname":
            self._send_nickname_prompt(peer_id)
            return
        if player.onboarding_step == "appearance":
            self._send_appearance_selection(peer_id, player)
            return

        active_trip = self.database.get_active_trip(player.user_id)
        if active_trip:
            destination = self.catalog.destinations[active_trip.destination_city_id]
            transport = self.service.get_transport(
                player.user_id, active_trip.transport_id
            )
            remaining = max(0, round(active_trip.arrival_at - time.time()))
            text = (
                f"Вы уже едете в {destination.name} на транспорте "
                f"«{transport.name}».\nОсталось примерно {remaining} сек."
            )
            self.sender.send(
                peer_id,
                text,
                transport.image,
                self._main_keyboard(),
            )
            return

        current_city = self.catalog.destinations[player.city_id]
        if greeting:
            intro = f"Добро пожаловать в Ghetto City, {player.nickname}!\n"
            location = f"Вы находитесь в {current_city.name}."
        else:
            intro = ""
            location = f"{player.nickname}, вы находитесь в {current_city.name}."
        text = f"{intro}{location}\nБаланс: {player.balance}$.\n\nКуда отправимся?"
        buttons = [
            Button(city.name, "city", city.id)
            for city in self.catalog.destinations.values()
            if city.id != player.city_id
        ]
        self.sender.send(
            peer_id,
            text,
            "city_overview.png",
            self._city_keyboard(buttons),
        )

    def _send_profile(self, peer_id: int, user_id: int) -> None:
        profile = self.service.profile(user_id)
        player = profile["player"]
        appearance = profile["appearance"]
        trip = profile["active_trip"]
        appearance_name = appearance.name if appearance else "Не выбрано"
        lines = [
            f"Профиль: {player.nickname}",
            f"Внешний вид: {appearance_name}",
            f"Город: {profile['city']}",
            f"Баланс: {player.balance}$",
            "",
            f"Дома: {', '.join(profile['homes']) if profile['homes'] else 'пока нет'}",
            "Автомобили: "
            + (
                ", ".join(name for _, name in profile["vehicles"])
                if profile["vehicles"]
                else "пока нет"
            ),
            "Бизнесы: "
            + (
                ", ".join(profile["businesses"])
                if profile["businesses"]
                else "пока нет"
            ),
        ]
        if trip:
            destination = self.catalog.destinations[trip.destination_city_id]
            remaining = max(0, round(trip.arrival_at - time.time()))
            lines.extend(
                [
                    "",
                    f"В пути в {destination.name}, осталось примерно {remaining} сек.",
                ]
            )
        self.sender.send(
            peer_id,
            "\n".join(lines),
            "profile_card.png",
            self._main_keyboard(),
        )

    def _send_main_menu(
        self,
        peer_id: int,
        player: Player | None = None,
        greeting: bool = False,
    ) -> None:
        buttons = [
            Button("👤 Профиль", "profile"),
            Button("🏠 Дома", "homes"),
            Button("🚘 Автомобили", "vehicles"),
            Button("🏢 Бизнес", "businesses"),
            Button("ℹ️ Помощь", "help"),
        ]
        introduction = ""
        if greeting and player is not None:
            city = self.catalog.destinations[player.city_id]
            introduction = (
                f"Добро пожаловать в Ghetto City, {player.nickname}!\n"
                f"Вы находитесь в {city.name}.\n\n"
            )
        self.sender.send(
            peer_id,
            f"{introduction}Главное меню Ghetto City\n\n"
            "Выберите игровой раздел. Поездки между городами находятся "
            "отдельно — кнопка «Поездка» внизу.",
            "city_overview.png",
            self._keyboard(buttons, buttons_per_line=2),
        )

    def _send_homes(self, peer_id: int, user_id: int) -> None:
        if not self.catalog.homes:
            raise ValueError("Каталог домов пуст")
        self._send_home_page(
            peer_id, user_id, next(iter(self.catalog.homes))
        )

    def _send_home_page(
        self, peer_id: int, user_id: int, home_id: str
    ) -> None:
        homes = tuple(self.catalog.homes.values())
        home_index = next(
            (index for index, home in enumerate(homes) if home.id == home_id),
            None,
        )
        if home_index is None:
            raise ValueError("Такой дом не найден")
        player = self.database.get_player(user_id)
        if player is None or player.onboarding_step != "complete":
            raise ValueError("Сначала завершите регистрацию в личных сообщениях")
        assets = self.database.get_player_assets(user_id)
        owned = {item["home_id"] for item in assets["homes"]}
        home = homes[home_index]
        status = "Уже куплено" if home.id in owned else "Доступно к покупке"
        lines = [
            f"Недвижимость · баланс {player.balance}$",
            f"{home_index + 1}/{len(homes)}",
            "",
            home.name,
            f"Цена: {home.price}$",
            f"Город: {self.catalog.destinations[home.city_id].name}",
            f"Мест для автомобилей: {home.vehicle_slots}",
            f"Статус: {status}",
        ]
        previous = homes[(home_index - 1) % len(homes)]
        following = homes[(home_index + 1) % len(homes)]
        buttons = [
            Button("← Назад", "home_page", previous.id),
            Button("Далее →", "home_page", following.id),
        ]
        if home.id not in owned:
            buttons.append(Button("Купить дом", "buy_home", home.id))
        buttons.append(Button("📋 Меню", "menu"))
        self.sender.send(
            peer_id,
            "\n".join(lines),
            home.image,
            self._keyboard(buttons, buttons_per_line=2),
        )

    def _send_vehicles(self, peer_id: int, user_id: int) -> None:
        if not self.catalog.vehicles:
            raise ValueError("Автосалон пока пуст")
        self._send_vehicle_preview(
            peer_id, user_id, next(iter(self.catalog.vehicles))
        )

    def _send_vehicle_preview(
        self, peer_id: int, user_id: int, vehicle_id: str
    ) -> None:
        vehicle = self.catalog.vehicles.get(vehicle_id)
        if vehicle is None:
            raise ValueError("Такой автомобиль не найден")
        player = self.database.get_player(user_id)
        if player is None or player.onboarding_step != "complete":
            raise ValueError("Сначала завершите регистрацию в личных сообщениях")
        assets = self.database.get_player_assets(user_id)
        slots = sum(
            self.catalog.homes[item["home_id"]].vehicle_slots
            for item in assets["homes"]
            if item["home_id"] in self.catalog.homes
        )
        occupied = len(assets["vehicles"])
        vehicles = tuple(self.catalog.vehicles.values())
        vehicle_index = next(
            index
            for index, item in enumerate(vehicles)
            if item.id == vehicle.id
        )
        lines = [
            f"Автосалон · баланс {player.balance}$",
            f"{vehicle_index + 1}/{len(vehicles)}",
            "",
            vehicle.name,
            f"Цена: {vehicle.price}$",
            f"Время поездки между районами: {vehicle.duration_seconds} сек.",
            f"Гараж: {occupied}/{slots} мест занято",
        ]
        previous = vehicles[(vehicle_index - 1) % len(vehicles)]
        following = vehicles[(vehicle_index + 1) % len(vehicles)]
        buttons = [
            Button("← Назад", "vehicle_page", previous.id),
            Button("Далее →", "vehicle_page", following.id),
        ]
        if occupied < slots:
            buttons.append(Button("Купить автомобиль", "buy_vehicle", vehicle.id))
        else:
            lines.extend(["", "Нет свободного места в гараже."])
        buttons.append(Button("📋 Меню", "menu"))
        self.sender.send(
            peer_id,
            "\n".join(lines),
            vehicle.image,
            self._keyboard(buttons, buttons_per_line=2),
        )

    def _send_businesses(self, peer_id: int, user_id: int) -> None:
        if not self.catalog.businesses:
            raise ValueError("Каталог бизнеса пока пуст")
        self._send_business_page(
            peer_id, user_id, next(iter(self.catalog.businesses))
        )

    def _send_business_page(
        self, peer_id: int, user_id: int, business_id: str
    ) -> None:
        businesses = tuple(self.catalog.businesses.values())
        business_index = next(
            (index for index, item in enumerate(businesses) if item.id == business_id),
            None,
        )
        if business_index is None:
            raise ValueError("Такого бизнеса нет в каталоге")
        player = self.database.get_player(user_id)
        if player is None or player.onboarding_step != "complete":
            raise ValueError("Сначала завершите регистрацию в личных сообщениях")
        assets = self.database.get_player_assets(user_id)
        owned = {item["business_id"]: item for item in assets["businesses"]}
        current_time = time.time()
        business = businesses[business_index]
        record = owned.get(business.id)
        accumulated = 0
        if record:
            periods = min(
                24,
                max(
                    0,
                    int(
                        (current_time - record["last_payout_at"])
                        // business.period_seconds
                    ),
                ),
            )
            accumulated = periods * business.income_per_period
        status = "Ваш бизнес" if record else "Доступно к покупке"
        lines = [
            f"Городской бизнес · баланс {player.balance}$",
            f"{business_index + 1}/{len(businesses)}",
            "",
            business.name,
            f"Цена: {business.price}$",
            f"Доход: {business.income_per_period}$ в час",
            f"Город: {self.catalog.destinations[business.city_id].name}",
            f"Статус: {status}",
        ]
        if record:
            lines.append(f"Накоплено: {accumulated}$ (сбор максимум за 24 часа)")
        previous = businesses[(business_index - 1) % len(businesses)]
        following = businesses[(business_index + 1) % len(businesses)]
        buttons = [
            Button("← Назад", "business_page", previous.id),
            Button("Далее →", "business_page", following.id),
        ]
        if record:
            if accumulated:
                buttons.append(
                    Button(
                        f"Забрать {accumulated}$",
                        "claim_business",
                        business.id,
                    )
                )
        else:
            buttons.append(
                Button("Купить бизнес", "buy_business", business.id)
            )
        buttons.append(Button("📋 Меню", "menu"))
        self.sender.send(
            peer_id,
            "\n".join(lines),
            business.image,
            self._keyboard(buttons, buttons_per_line=2),
        )

    def _send_help(self, peer_id: int) -> None:
        self.sender.send(
            peer_id,
            "Меню:\n"
            "• Профиль — персонаж и его имущество\n"
            "• Дома — жильё и места в гараже\n"
            "• Авто — каталог и покупка личного транспорта\n"
            "• Бизнес — покупка предприятий и сбор дохода\n"
            "• Поездка — выбор города, затем транспорта",
            "city_overview.png",
            self._keyboard(
                [
                    Button("Авторы фото", "image_credits"),
                    Button("📋 Меню", "menu"),
                ],
                buttons_per_line=2,
            ),
        )

    def _send_image_credits(self, peer_id: int) -> None:
        credits = [
            item.image_credit
            for catalog_items in (
                self.catalog.homes.values(),
                self.catalog.vehicles.values(),
                self.catalog.businesses.values(),
            )
            for item in catalog_items
            if item.image_credit
        ]
        text = "Авторы и лицензии фотографий:\n\n" + "\n\n".join(credits)
        self.sender.send(
            peer_id,
            text,
            "city_overview.png",
            self._keyboard(
                [
                    Button("← Помощь", "help"),
                    Button("📋 Меню", "menu"),
                ],
                buttons_per_line=2,
            ),
        )

    def _main_keyboard(self) -> str:
        keyboard = VkKeyboard(one_time=False, inline=False)
        labels = [
            self.MENU_MAIN,
            self.MENU_CITY,
            self.MENU_PROFILE,
            self.MENU_HELP,
        ]
        for index, label in enumerate(labels):
            keyboard.add_button(label, color=VkKeyboardColor.SECONDARY)
            if index % 2 == 1 and index < len(labels) - 1:
                keyboard.add_line()
        return keyboard.get_keyboard()

    def _city_keyboard(self, city_buttons: list[Button]) -> str:
        keyboard = VkKeyboard(one_time=False, inline=False)
        items = [item.label for item in city_buttons] + [
            self.MENU_CITY,
            self.MENU_MAIN,
            self.MENU_PROFILE,
        ]
        for index, label in enumerate(items):
            keyboard.add_button(label, color=VkKeyboardColor.SECONDARY)
            if index % 2 == 1 and index < len(items) - 1:
                keyboard.add_line()
        return keyboard.get_keyboard()

    def _send_nickname_prompt(self, peer_id: int, error: str | None = None) -> None:
        prefix = f"{error}\n\n" if error else ""
        self.sender.send(
            peer_id,
            f"{prefix}Добро пожаловать в Ghetto City!\n"
            "Придумайте игровой никнейм длиной от 3 до 20 символов. "
            "Можно использовать буквы, цифры, пробел, дефис и подчёркивание.",
            "city_overview.png",
        )

    def _send_appearance_selection(self, peer_id: int, player: Player) -> None:
        if player.nickname is None:
            raise ValueError("Для выбора внешнего вида сначала нужен никнейм")
        buttons = [
            Button(item.name, "appearance", item.id)
            for item in self.catalog.appearances.values()
        ]
        self.sender.send(
            peer_id,
            f"Никнейм «{player.nickname}» сохранён.\n"
            "Выберите внешний вид персонажа:",
            "appearance_choices.png",
            self._keyboard(buttons),
        )

    def _send_transport_selection(
        self, peer_id: int, user_id: int, destination_city_id: str
    ) -> None:
        destination = self.catalog.destinations.get(destination_city_id)
        player = self.database.get_player(user_id)
        if destination is None or player is None:
            raise ValueError("Пункт назначения сейчас недоступен")
        if destination.id == player.city_id:
            raise ValueError("Вы уже находитесь в этом городе")
        if self.database.get_active_trip(user_id):
            raise ValueError("Вы уже находитесь в пути")
        quote_options = self.service.available_transports(user_id)

        lines = [
            f"Вы выбрали направление: {destination.name}.",
            "На чём поедем?",
            "",
        ]
        for transport in quote_options:
            total_seconds = transport.total_duration_seconds
            lines.append(
                f"• {transport.name} — {transport.fare}$, "
                f"в пути {total_seconds} сек."
            )
        self.sender.send(
            peer_id,
            "\n".join(lines),
            destination.image,
            self._transport_keyboard(destination.id, quote_options),
        )

    def _transport_keyboard(
        self, destination_id: str, transports: tuple[Transport, ...]
    ) -> str:
        return self._keyboard(
            [
                Button(
                    transport.name,
                    "transport",
                    f"{destination_id}|{transport.id}",
                )
                for transport in transports
            ],
            encode_pair=True,
        )

    def _send_trip_confirmation(
        self, peer_id: int, user_id: int, destination_id: str, transport_id: str
    ) -> None:
        quote = self.service.quote_trip(user_id, destination_id, transport_id)
        player = self.database.get_player(user_id)
        if player is None:
            raise ValueError("Профиль не найден. Отправьте /start")
        destination = self.catalog.destinations[destination_id]
        transport = quote.transport
        can_afford = player.balance >= transport.fare
        text = (
            f"Маршрут: {destination.name}\n"
            f"Транспорт: {transport.name}\n"
            f"Стоимость: {transport.fare}$\n"
            f"Баланс: {player.balance}$\n"
            f"Отправление через {transport.departure_delay_seconds} сек.\n"
            f"Время в пути: {transport.duration_seconds} сек.\n\n"
        )
        if can_afford:
            text += f"Баланс после оплаты: {player.balance - transport.fare}$\n\n"
            text += "Подтвердить поездку?"
            buttons = [
                Button(
                    "Подтвердить поездку",
                    "confirm",
                    f"{destination_id}|{transport_id}",
                ),
                Button("Назад к городам", "travel"),
            ]
        else:
            text += (
                f"Не хватает {transport.fare - player.balance}$ для этой поездки."
            )
            buttons = [Button("Назад к городам", "travel")]
        self.sender.send(
            peer_id,
            text,
            transport.image,
            self._keyboard(buttons, encode_pair=True),
        )

    def _confirm_trip(
        self,
        peer_id: int,
        user_id: int,
        destination_id: str,
        transport_id: str,
        event_id: str,
    ) -> None:
        destination = self.catalog.destinations.get(destination_id)
        if destination is None:
            raise ValueError("Маршрут или транспорт не найден")
        quote = self.service.quote_trip(user_id, destination_id, transport_id)
        transport = quote.transport
        trip = self.service.start_trip(
            user_id,
            destination_id,
            transport_id,
            operation_id=f"vk-event:{event_id}",
        )
        delay = f"отправляется через {transport.departure_delay_seconds} сек." \
            if transport.departure_delay_seconds else "отправляется сейчас."
        text = (
            f"Поездка в {destination.name} началась.\n"
            f"Транспорт «{transport.name}» {delay}\n"
            f"Время в пути: {transport.duration_seconds} сек."
        )
        self.sender.send(
            peer_id,
            text,
            transport.image,
            self._keyboard([Button("Открыть меню", "menu")]),
        )
        logger.info("Trip %s started for user %s", trip.id, user_id)

    @staticmethod
    def _keyboard(
        buttons: list[Button],
        encode_pair: bool = False,
        buttons_per_line: int = 1,
    ) -> str:
        keyboard = VkKeyboard(one_time=False, inline=True)
        for index, button in enumerate(buttons):
            if button.action == "open_link":
                keyboard.add_openlink_button(button.label, button.value)
                continue
            payload: dict[str, str] = {"action": button.action}
            if button.value:
                if encode_pair:
                    first, separator, second = button.value.partition("|")
                    if separator:
                        payload.update(city_id=first, transport_id=second)
                    else:
                        payload["city_id"] = first
                elif button.action == "city":
                    payload["city_id"] = button.value
                elif button.action == "appearance":
                    payload["appearance_id"] = button.value
                elif button.action == "buy_home":
                    payload["home_id"] = button.value
                elif button.action == "home_page":
                    payload["home_id"] = button.value
                elif button.action == "buy_vehicle":
                    payload["vehicle_id"] = button.value
                elif button.action in {"preview_vehicle", "vehicle_page"}:
                    payload["vehicle_id"] = button.value
                elif button.action in {"buy_business", "claim_business"}:
                    payload["business_id"] = button.value
                elif button.action == "business_page":
                    payload["business_id"] = button.value
                else:
                    payload["transport_id"] = button.value
            keyboard.add_callback_button(
                label=button.label,
                color=VkKeyboardColor.PRIMARY,
                payload=payload,
            )
            if (
                (index + 1) % buttons_per_line == 0
                and index < len(buttons) - 1
            ):
                keyboard.add_line()
        return keyboard.get_keyboard()
