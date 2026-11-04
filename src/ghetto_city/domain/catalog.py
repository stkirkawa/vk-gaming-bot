import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    image: str


@dataclass(frozen=True)
class Appearance:
    id: str
    name: str


@dataclass(frozen=True)
class Home:
    id: str
    name: str
    city_id: str
    price: int
    vehicle_slots: int
    image: str
    image_credit: str = ""


@dataclass(frozen=True)
class Vehicle:
    id: str
    name: str
    price: int
    duration_seconds: int
    image: str
    image_credit: str = ""


@dataclass(frozen=True)
class Business:
    id: str
    name: str
    city_id: str
    price: int
    income_per_period: int
    period_seconds: int
    image: str
    image_credit: str = ""


@dataclass(frozen=True)
class Transport:
    id: str
    name: str
    fare: int
    departure_delay_seconds: int
    duration_seconds: int
    image: str
    image_credit: str = ""

    @property
    def total_duration_seconds(self) -> int:
        return self.departure_delay_seconds + self.duration_seconds


class GameCatalog:
    def __init__(
        self,
        destinations: tuple[Destination, ...],
        appearances: tuple[Appearance, ...],
        homes: tuple[Home, ...],
        vehicles: tuple[Vehicle, ...],
        businesses: tuple[Business, ...],
        transports: tuple[Transport, ...],
        starting_city: str,
        starting_balance: int,
    ) -> None:
        if len({item.id for item in destinations}) != len(destinations):
            raise ValueError("Destination IDs must be unique")
        if len({item.id for item in appearances}) != len(appearances):
            raise ValueError("Appearance IDs must be unique")
        if len({item.id for item in homes}) != len(homes):
            raise ValueError("Home IDs must be unique")
        if len({item.id for item in vehicles}) != len(vehicles):
            raise ValueError("Vehicle IDs must be unique")
        if len({item.id for item in businesses}) != len(businesses):
            raise ValueError("Business IDs must be unique")
        if len({item.id for item in transports}) != len(transports):
            raise ValueError("Transport IDs must be unique")
        self.destinations = {item.id: item for item in destinations}
        self.appearances = {item.id: item for item in appearances}
        self.homes = {item.id: item for item in homes}
        self.vehicles = {item.id: item for item in vehicles}
        self.businesses = {item.id: item for item in businesses}
        self.transports = {item.id: item for item in transports}
        self.starting_city = starting_city
        self.starting_balance = starting_balance

    @classmethod
    def load(cls, path: Path) -> "GameCatalog":
        with path.open(encoding="utf-8") as file:
            data = json.load(file)

        destinations = tuple(Destination(**item) for item in data["cities"])
        appearances = tuple(Appearance(**item) for item in data["appearances"])
        homes = tuple(Home(**item) for item in data["homes"])
        vehicles = tuple(Vehicle(**item) for item in data["vehicles"])
        businesses = tuple(Business(**item) for item in data["businesses"])
        transports = tuple(Transport(**item) for item in data["transports"])
        catalog = cls(
            destinations,
            appearances,
            homes,
            vehicles,
            businesses,
            transports,
            data["starting_city"],
            data["starting_balance"],
        )
        catalog._validate()
        return catalog

    def _validate(self) -> None:
        if not self.destinations or not self.transports:
            raise ValueError("Catalog must include destinations and transports")
        if not self.appearances:
            raise ValueError("Catalog must include appearance choices")
        if not self.homes or not self.vehicles or not self.businesses:
            raise ValueError("Catalog must include homes, vehicles, and businesses")
        if self.starting_city not in self.destinations:
            raise ValueError("Starting city must exist in the destination catalog")
        if any(home.city_id not in self.destinations for home in self.homes.values()):
            raise ValueError("Home city must exist in the destination catalog")
        if any(
            business.city_id not in self.destinations
            for business in self.businesses.values()
        ):
            raise ValueError("Business city must exist in the destination catalog")
        if self.starting_balance < 0:
            raise ValueError("Starting balance cannot be negative")
        if any(home.price < 0 or home.vehicle_slots < 0 for home in self.homes.values()):
            raise ValueError("Home price and vehicle slots cannot be negative")
        if any(
            vehicle.price < 0 or vehicle.duration_seconds <= 0
            for vehicle in self.vehicles.values()
        ):
            raise ValueError("Vehicle price and travel time must be valid")
        if any(
            business.price < 0
            or business.income_per_period < 0
            or business.period_seconds <= 0
            for business in self.businesses.values()
        ):
            raise ValueError("Business prices, income, and periods must be valid")
        if any(transport.fare < 0 for transport in self.transports.values()):
            raise ValueError("Transport fares cannot be negative")
        if any(
            transport.duration_seconds <= 0
            or transport.departure_delay_seconds < 0
            for transport in self.transports.values()
        ):
            raise ValueError("Transport trip times must be positive")
