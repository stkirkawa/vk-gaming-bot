import time
from dataclasses import dataclass

from ghetto_city.domain.catalog import GameCatalog, Transport
from ghetto_city.infrastructure.database import Database, Player, Trip


@dataclass(frozen=True)
class TripQuote:
    origin_city_id: str
    destination_city_id: str
    transport: Transport


class GameService:
    def __init__(self, database: Database, catalog: GameCatalog) -> None:
        self.database = database
        self.catalog = catalog

    def get_or_create_player(self, user_id: int) -> tuple[Player, bool]:
        existing = self.database.get_player(user_id)
        if existing:
            return existing, False
        player = self.database.create_player(
            user_id,
            self.catalog.starting_city,
            self.catalog.starting_balance,
            time.time(),
        )
        return player, True

    def set_nickname(self, user_id: int, nickname: str) -> Player:
        normalized = nickname.strip()
        if not 3 <= len(normalized) <= 20:
            raise ValueError("Никнейм должен содержать от 3 до 20 символов")
        if any(not (character.isalnum() or character in " _-") for character in normalized):
            raise ValueError("Используйте буквы, цифры, пробел, дефис или подчёркивание")
        if not any(character.isalpha() for character in normalized):
            raise ValueError("В никнейме должна быть хотя бы одна буква")
        return self.database.set_nickname(user_id, normalized)

    def set_appearance(self, user_id: int, appearance_id: str) -> Player:
        if appearance_id not in self.catalog.appearances:
            raise ValueError("Такой внешний вид недоступен")
        return self.database.set_appearance(user_id, appearance_id)

    def profile(self, user_id: int) -> dict:
        player = self.database.get_player(user_id)
        if player is None:
            raise ValueError("Сначала отправьте /start в личные сообщения бота")
        assets = self.database.get_player_assets(user_id)
        homes = [
            self.catalog.homes[item["home_id"]].name
            for item in assets["homes"]
            if item["home_id"] in self.catalog.homes
        ]
        vehicles = [
            (
                item["id"],
                self.catalog.vehicles[item["vehicle_id"]].name,
            )
            for item in assets["vehicles"]
            if item["vehicle_id"] in self.catalog.vehicles
        ]
        businesses = [
            self.catalog.businesses[item["business_id"]].name
            for item in assets["businesses"]
            if item["business_id"] in self.catalog.businesses
        ]
        return {
            "player": player,
            "city": self.catalog.destinations[player.city_id].name,
            "appearance": self.catalog.appearances.get(player.appearance_id),
            "active_trip": self.database.get_active_trip(user_id),
            "homes": homes,
            "vehicles": vehicles,
            "businesses": businesses,
        }

    def available_transports(self, user_id: int) -> tuple[Transport, ...]:
        owned = self.database.get_player_assets(user_id)["vehicles"]
        personal = tuple(
            Transport(
                id=f"personal_vehicle:{item['id']}",
                name=self.catalog.vehicles[item["vehicle_id"]].name,
                fare=0,
                departure_delay_seconds=0,
                duration_seconds=self.catalog.vehicles[
                    item["vehicle_id"]
                ].duration_seconds,
                image=self.catalog.vehicles[item["vehicle_id"]].image,
            )
            for item in owned
            if item["vehicle_id"] in self.catalog.vehicles
        )
        return (*self.catalog.transports.values(), *personal)

    def get_transport(self, user_id: int, transport_id: str) -> Transport:
        transport = self.catalog.transports.get(transport_id)
        if transport:
            return transport
        prefix, separator, instance_id = transport_id.partition(":")
        if prefix != "personal_vehicle" or not separator or not instance_id.isdigit():
            raise ValueError("Такой транспорт недоступен")
        instance = self.database.get_player_vehicle(user_id, int(instance_id))
        if instance is None:
            raise ValueError("Личный автомобиль вам не принадлежит")
        model = self.catalog.vehicles.get(instance["vehicle_id"])
        if model is None:
            raise ValueError("Модель автомобиля больше недоступна")
        return Transport(
            id=transport_id,
            name=model.name,
            fare=0,
            departure_delay_seconds=0,
            duration_seconds=model.duration_seconds,
            image=model.image,
            image_credit=model.image_credit,
        )

    def buy_home(self, user_id: int, home_id: str, operation_id: str) -> bool:
        home = self.catalog.homes.get(home_id)
        if home is None:
            raise ValueError("Такого дома нет в каталоге")
        return self.database.buy_home(
            user_id,
            home_id,
            home.price,
            home.vehicle_slots,
            operation_id,
            time.time(),
        )

    def buy_vehicle(
        self, user_id: int, vehicle_id: str, operation_id: str
    ) -> bool:
        vehicle = self.catalog.vehicles.get(vehicle_id)
        if vehicle is None:
            raise ValueError("Такого автомобиля нет в каталоге")
        return self.database.buy_vehicle(
            user_id,
            vehicle_id,
            vehicle.price,
            operation_id,
            time.time(),
        )

    def buy_business(
        self, user_id: int, business_id: str, operation_id: str
    ) -> bool:
        business = self.catalog.businesses.get(business_id)
        if business is None:
            raise ValueError("Такого бизнеса нет в каталоге")
        return self.database.buy_business(
            user_id, business_id, business.price, operation_id, time.time()
        )

    def claim_business_income(self, user_id: int, business_id: str) -> int:
        business = self.catalog.businesses.get(business_id)
        if business is None:
            raise ValueError("Такого бизнеса нет в каталоге")
        amount, _ = self.database.claim_business_income(
            user_id,
            business_id,
            business.income_per_period,
            business.period_seconds,
            time.time(),
        )
        return amount

    def quote_trip(
        self, user_id: int, destination_city_id: str, transport_id: str
    ) -> TripQuote:
        player = self.database.get_player(user_id)
        if player is None:
            raise ValueError("Сначала отправьте /start")
        if player.onboarding_step != "complete":
            raise ValueError("Сначала завершите регистрацию")
        if self.database.get_active_trip(user_id):
            raise ValueError("Вы уже находитесь в пути")
        destination = self.catalog.destinations.get(destination_city_id)
        if destination is None:
            raise ValueError("Такого пункта назначения нет")
        if destination_city_id == player.city_id:
            raise ValueError("Вы уже находитесь в этом городе")
        transport = self.get_transport(user_id, transport_id)
        return TripQuote(player.city_id, destination_city_id, transport)

    def start_trip(
        self,
        user_id: int,
        destination_city_id: str,
        transport_id: str,
        operation_id: str,
        now: float | None = None,
    ) -> Trip:
        destination = self.catalog.destinations.get(destination_city_id)
        if destination is None:
            raise ValueError("Маршрут или транспорт не найден")
        existing = self.database.get_trip_by_operation(operation_id)
        if existing:
            if (
                existing.user_id != user_id
                or existing.destination_city_id != destination_city_id
                or existing.transport_id != transport_id
            ):
                raise ValueError("Идентификатор операции уже использован")
            return existing

        quote = self.quote_trip(user_id, destination_city_id, transport_id)
        started_at = time.time() if now is None else now
        return self.database.start_trip(
            operation_id=operation_id,
            user_id=user_id,
            destination_city_id=destination_city_id,
            transport_id=transport_id,
            fare=quote.transport.fare,
            started_at=started_at,
            arrival_at=started_at + quote.transport.total_duration_seconds,
            transport_name=quote.transport.name,
            transport_image=quote.transport.image,
            transport_credit=quote.transport.image_credit,
        )
