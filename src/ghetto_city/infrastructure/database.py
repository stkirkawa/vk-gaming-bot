import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    city_id TEXT NOT NULL,
    balance INTEGER NOT NULL CHECK (balance >= 0),
    nickname TEXT,
    appearance_id TEXT,
    onboarding_step TEXT NOT NULL DEFAULT 'complete'
        CHECK (onboarding_step IN ('nickname', 'appearance', 'complete')),
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    origin_city_id TEXT NOT NULL,
    destination_city_id TEXT NOT NULL,
    transport_id TEXT NOT NULL,
    fare INTEGER NOT NULL CHECK (fare >= 0),
    started_at REAL NOT NULL,
    arrival_at REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
    completed_at REAL,
    transport_name TEXT,
    transport_image TEXT,
    transport_credit TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_trip_per_player
ON trips(user_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS transactions (
    operation_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL UNIQUE REFERENCES trips(id),
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    destination_city_id TEXT NOT NULL,
    transport_id TEXT NOT NULL,
    transport_name TEXT,
    transport_image TEXT,
    transport_credit TEXT,
    created_at REAL NOT NULL,
    sent_at REAL
);

CREATE TABLE IF NOT EXISTS player_homes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    home_id TEXT NOT NULL,
    purchased_at REAL NOT NULL,
    UNIQUE (user_id, home_id)
);

CREATE TABLE IF NOT EXISTS player_vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    vehicle_id TEXT NOT NULL,
    purchased_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS player_businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES players(user_id),
    business_id TEXT NOT NULL,
    purchased_at REAL NOT NULL,
    last_payout_at REAL NOT NULL,
    UNIQUE (user_id, business_id)
);
"""


@dataclass(frozen=True)
class Player:
    user_id: int
    city_id: str
    balance: int
    nickname: str | None
    appearance_id: str | None
    onboarding_step: str


@dataclass(frozen=True)
class Trip:
    id: int
    operation_id: str
    user_id: int
    origin_city_id: str
    destination_city_id: str
    transport_id: str
    fare: int
    started_at: float
    arrival_at: float
    transport_name: str | None
    transport_image: str | None
    transport_credit: str | None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path),
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            connection.executescript(SCHEMA)
            self._ensure_columns(
                connection,
                "trips",
                {
                    "transport_name": "TEXT",
                    "transport_image": "TEXT",
                    "transport_credit": "TEXT",
                },
            )
            self._ensure_columns(
                connection,
                "notification_outbox",
                {
                    "transport_name": "TEXT",
                    "transport_image": "TEXT",
                    "transport_credit": "TEXT",
                },
            )
            self._ensure_columns(
                connection,
                "player_homes",
                {"vehicle_slots": "INTEGER NOT NULL DEFAULT 0"},
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(players)")
            }
            if "nickname" not in columns:
                connection.execute("ALTER TABLE players ADD COLUMN nickname TEXT")
            if "appearance_id" not in columns:
                connection.execute(
                    "ALTER TABLE players ADD COLUMN appearance_id TEXT"
                )
            if "onboarding_step" not in columns:
                connection.execute(
                    """
                    ALTER TABLE players ADD COLUMN onboarding_step TEXT NOT NULL
                    DEFAULT 'complete'
                    """
                )
            connection.execute(
                """
                UPDATE players SET onboarding_step = 'nickname'
                WHERE nickname IS NULL AND onboarding_step = 'complete'
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS unique_player_nickname
                ON players(nickname COLLATE NOCASE) WHERE nickname IS NOT NULL
                """
            )

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection, table: str, columns: dict[str, str]
    ) -> None:
        existing = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def create_player(
        self, user_id: int, city_id: str, balance: int, now: float
    ) -> Player:
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO players
                    (user_id, city_id, balance, onboarding_step, created_at)
                VALUES (?, ?, ?, 'nickname', ?)
                """,
                (user_id, city_id, balance, now),
            )
            row = connection.execute(
                "SELECT * FROM players WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return self._player_from_row(row)

    def get_player(self, user_id: int) -> Player | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return self._player_from_row(row)

    def set_nickname(self, user_id: int, nickname: str) -> Player:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                player = connection.execute(
                    "SELECT onboarding_step FROM players WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if player is None or player["onboarding_step"] != "nickname":
                    raise ValueError("Нельзя изменить никнейм на этом шаге")
                duplicate = connection.execute(
                    "SELECT 1 FROM players WHERE nickname = ? COLLATE NOCASE",
                    (nickname,),
                ).fetchone()
                if duplicate:
                    raise ValueError("Этот никнейм уже занят")
                connection.execute(
                    """
                    UPDATE players SET nickname = ?, onboarding_step = 'appearance'
                    WHERE user_id = ?
                    """,
                    (nickname, user_id),
                )
                row = connection.execute(
                    "SELECT * FROM players WHERE user_id = ?", (user_id,)
                ).fetchone()
                connection.commit()
                return self._player_from_row(row)
            except Exception:
                connection.rollback()
                raise

    def set_appearance(self, user_id: int, appearance_id: str) -> Player:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                player = connection.execute(
                    "SELECT onboarding_step FROM players WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if player is None or player["onboarding_step"] != "appearance":
                    raise ValueError("Нельзя выбрать внешний вид на этом шаге")
                connection.execute(
                    """
                    UPDATE players
                    SET appearance_id = ?, onboarding_step = 'complete'
                    WHERE user_id = ?
                    """,
                    (appearance_id, user_id),
                )
                row = connection.execute(
                    "SELECT * FROM players WHERE user_id = ?", (user_id,)
                ).fetchone()
                connection.commit()
                return self._player_from_row(row)
            except Exception:
                connection.rollback()
                raise

    def get_active_trip(self, user_id: int) -> Trip | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM trips WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            ).fetchone()
        return self._trip_from_row(row) if row else None

    def get_player_assets(self, user_id: int) -> dict[str, list[sqlite3.Row]]:
        with closing(self.connect()) as connection:
            return {
                "homes": connection.execute(
                    """
                    SELECT home_id, vehicle_slots, purchased_at
                    FROM player_homes WHERE user_id = ? ORDER BY id
                    """,
                    (user_id,),
                ).fetchall(),
                "vehicles": connection.execute(
                    "SELECT id, vehicle_id, purchased_at FROM player_vehicles WHERE user_id = ? ORDER BY id",
                    (user_id,),
                ).fetchall(),
                "businesses": connection.execute(
                    """
                    SELECT business_id, purchased_at, last_payout_at
                    FROM player_businesses WHERE user_id = ? ORDER BY id
                    """,
                    (user_id,),
                ).fetchall(),
            }

    def get_player_vehicle(
        self, user_id: int, vehicle_instance_id: int
    ) -> sqlite3.Row | None:
        with closing(self.connect()) as connection:
            return connection.execute(
                """
                SELECT id, vehicle_id FROM player_vehicles
                WHERE user_id = ? AND id = ?
                """,
                (user_id, vehicle_instance_id),
            ).fetchone()

    def buy_home(
        self,
        user_id: int,
        home_id: str,
        price: int,
        vehicle_slots: int,
        operation_id: str,
        now: float,
    ) -> bool:
        return self._buy_asset(
            user_id,
            "player_homes",
            "home_id",
            home_id,
            price,
            operation_id,
            now,
            extra_columns=", vehicle_slots",
            extra_values=", ?",
            extra_params=(vehicle_slots,),
        )

    def buy_business(
        self,
        user_id: int,
        business_id: str,
        price: int,
        operation_id: str,
        now: float,
    ) -> bool:
        return self._buy_asset(
            user_id,
            "player_businesses",
            "business_id",
            business_id,
            price,
            operation_id,
            now,
            extra_columns=", last_payout_at",
            extra_values=", ?",
            extra_params=(now,),
        )

    def _buy_asset(
        self,
        user_id: int,
        table: str,
        asset_column: str,
        asset_id: str,
        price: int,
        operation_id: str,
        now: float,
        extra_columns: str = "",
        extra_values: str = "",
        extra_params: tuple = (),
    ) -> bool:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                owned = connection.execute(
                    f"SELECT 1 FROM {table} WHERE user_id = ? AND {asset_column} = ?",
                    (user_id, asset_id),
                ).fetchone()
                if owned:
                    transaction = connection.execute(
                        "SELECT reason FROM transactions WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if transaction and transaction["reason"] == f"purchase:{table}:{asset_id}":
                        connection.commit()
                        return False
                    raise ValueError("Этот объект уже принадлежит вам")

                transaction = connection.execute(
                    "SELECT reason FROM transactions WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                expected_reason = f"purchase:{table}:{asset_id}"
                if transaction:
                    if transaction["reason"] == expected_reason:
                        connection.commit()
                        return False
                    raise ValueError("Идентификатор операции уже использован")

                player = connection.execute(
                    "SELECT balance FROM players WHERE user_id = ? AND onboarding_step = 'complete'",
                    (user_id,),
                ).fetchone()
                if player is None:
                    raise ValueError("Сначала завершите регистрацию")
                if player["balance"] < price:
                    raise ValueError("Недостаточно денег")

                connection.execute(
                    "UPDATE players SET balance = balance - ? WHERE user_id = ?",
                    (price, user_id),
                )
                connection.execute(
                    f"""
                    INSERT INTO {table}
                        (user_id, {asset_column}, purchased_at{extra_columns})
                    VALUES (?, ?, ?{extra_values})
                    """,
                    (user_id, asset_id, now, *extra_params),
                )
                connection.execute(
                    """
                    INSERT INTO transactions
                        (operation_id, user_id, amount, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (operation_id, user_id, -price, expected_reason, now),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def buy_vehicle(
        self,
        user_id: int,
        vehicle_id: str,
        price: int,
        operation_id: str,
        now: float,
    ) -> bool:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                transaction = connection.execute(
                    "SELECT reason FROM transactions WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                expected_reason = f"purchase:player_vehicles:{vehicle_id}"
                if transaction:
                    if transaction["reason"] == expected_reason:
                        connection.commit()
                        return False
                    raise ValueError("Идентификатор операции уже использован")

                player = connection.execute(
                    "SELECT balance FROM players WHERE user_id = ? AND onboarding_step = 'complete'",
                    (user_id,),
                ).fetchone()
                if player is None:
                    raise ValueError("Сначала завершите регистрацию")
                owned_slots = connection.execute(
                    """
                    SELECT COALESCE(SUM(vehicle_slots), 0) AS count
                    FROM player_homes WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()["count"]
                owned_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM player_vehicles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()["count"]
                if owned_count >= owned_slots:
                    raise ValueError("Нет свободного места в гараже. Сначала купите дом.")
                if player["balance"] < price:
                    raise ValueError("Недостаточно денег")

                connection.execute(
                    "UPDATE players SET balance = balance - ? WHERE user_id = ?",
                    (price, user_id),
                )
                connection.execute(
                    """
                    INSERT INTO player_vehicles (user_id, vehicle_id, purchased_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, vehicle_id, now),
                )
                connection.execute(
                    """
                    INSERT INTO transactions
                        (operation_id, user_id, amount, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (operation_id, user_id, -price, expected_reason, now),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def claim_business_income(
        self,
        user_id: int,
        business_id: str,
        income_per_period: int,
        period_seconds: int,
        now: float,
        max_periods: int = 24,
    ) -> tuple[int, str | None]:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                owned = connection.execute(
                    """
                    SELECT last_payout_at FROM player_businesses
                    WHERE user_id = ? AND business_id = ?
                    """,
                    (user_id, business_id),
                ).fetchone()
                if owned is None:
                    raise ValueError("Этот бизнес вам не принадлежит")
                periods_due = int((now - owned["last_payout_at"]) // period_seconds)
                periods = min(periods_due, max_periods)
                if periods <= 0:
                    connection.commit()
                    return 0, None

                payout_at = owned["last_payout_at"] + periods * period_seconds
                if periods_due > max_periods:
                    payout_at = now
                operation_id = (
                    f"business-income:{user_id}:{business_id}:{payout_at:.6f}"
                )
                amount = income_per_period * periods
                connection.execute(
                    "UPDATE players SET balance = balance + ? WHERE user_id = ?",
                    (amount, user_id),
                )
                connection.execute(
                    """
                    UPDATE player_businesses SET last_payout_at = ?
                    WHERE user_id = ? AND business_id = ?
                    """,
                    (payout_at, user_id, business_id),
                )
                connection.execute(
                    """
                    INSERT INTO transactions
                        (operation_id, user_id, amount, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        user_id,
                        amount,
                        f"business-income:{business_id}:{periods}",
                        now,
                    ),
                )
                connection.commit()
                return amount, operation_id
            except Exception:
                connection.rollback()
                raise

    def get_trip_by_operation(self, operation_id: str) -> Trip | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM trips WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return self._trip_from_row(row) if row else None

    def start_trip(
        self,
        operation_id: str,
        user_id: int,
        destination_city_id: str,
        transport_id: str,
        fare: int,
        started_at: float,
        arrival_at: float,
        transport_name: str | None = None,
        transport_image: str | None = None,
        transport_credit: str | None = None,
    ) -> Trip:
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM trips WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                if existing:
                    if (
                        existing["user_id"] != user_id
                        or existing["destination_city_id"] != destination_city_id
                        or existing["transport_id"] != transport_id
                    ):
                        raise ValueError("Operation ID has already been used")
                    connection.commit()
                    return self._trip_from_row(existing)

                player = connection.execute(
                    "SELECT city_id, balance FROM players WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if player is None:
                    raise ValueError("Player is not registered")
                if player["city_id"] == destination_city_id:
                    raise ValueError("You are already in this destination")
                active = connection.execute(
                    "SELECT 1 FROM trips WHERE user_id = ? AND status = 'pending'",
                    (user_id,),
                ).fetchone()
                if active:
                    raise ValueError("A trip is already in progress")
                if player["balance"] < fare:
                    raise ValueError("Not enough money for this trip")

                connection.execute(
                    "UPDATE players SET balance = balance - ? WHERE user_id = ?",
                    (fare, user_id),
                )
                connection.execute(
                    """
                    INSERT INTO transactions (operation_id, user_id, amount, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (operation_id, user_id, -fare, "transport", started_at),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO trips (
                        operation_id, user_id, origin_city_id, destination_city_id,
                        transport_id, fare, started_at, arrival_at, status,
                        transport_name, transport_image, transport_credit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        operation_id,
                        user_id,
                        player["city_id"],
                        destination_city_id,
                        transport_id,
                        fare,
                        started_at,
                        arrival_at,
                        transport_name,
                        transport_image,
                        transport_credit,
                    ),
                )
                trip_id = cursor.lastrowid
                row = connection.execute(
                    "SELECT * FROM trips WHERE id = ?", (trip_id,)
                ).fetchone()
                connection.commit()
                return self._trip_from_row(row)
            except Exception:
                connection.rollback()
                raise

    def complete_due_trips(self, now: float) -> list[Trip]:
        completed: list[Trip] = []
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT * FROM trips WHERE status = 'pending' AND arrival_at <= ?",
                    (now,),
                ).fetchall()
                for row in rows:
                    updated = connection.execute(
                        """
                        UPDATE trips SET status = 'completed', completed_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (now, row["id"]),
                    )
                    if updated.rowcount != 1:
                        continue
                    connection.execute(
                        "UPDATE players SET city_id = ? WHERE user_id = ?",
                        (row["destination_city_id"], row["user_id"]),
                    )
                    connection.execute(
                        """
                        INSERT INTO notification_outbox
                            (trip_id, user_id, destination_city_id, transport_id,
                             transport_name, transport_image, transport_credit,
                             created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["id"],
                            row["user_id"],
                            row["destination_city_id"],
                            row["transport_id"],
                            row["transport_name"],
                            row["transport_image"],
                            row["transport_credit"],
                            now,
                        ),
                    )
                    completed.append(self._trip_from_row(row))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return completed

    def pending_notifications(self, limit: int = 100) -> list[sqlite3.Row]:
        with closing(self.connect()) as connection:
            return connection.execute(
                """
                SELECT id, user_id, destination_city_id, transport_id,
                       transport_name, transport_image, transport_credit
                FROM notification_outbox WHERE sent_at IS NULL
                ORDER BY id LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def mark_notification_sent(self, notification_id: int, now: float) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                """
                UPDATE notification_outbox SET sent_at = ?
                WHERE id = ? AND sent_at IS NULL
                """,
                (now, notification_id),
            )

    def record_event(self, event_id: str, now: float) -> bool:
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO processed_events (event_id, processed_at) VALUES (?, ?)",
                (event_id, now),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _player_from_row(row: sqlite3.Row) -> Player:
        return Player(
            user_id=row["user_id"],
            city_id=row["city_id"],
            balance=row["balance"],
            nickname=row["nickname"],
            appearance_id=row["appearance_id"],
            onboarding_step=row["onboarding_step"],
        )

    @staticmethod
    def _trip_from_row(row: sqlite3.Row) -> Trip:
        return Trip(
            id=row["id"],
            operation_id=row["operation_id"],
            user_id=row["user_id"],
            origin_city_id=row["origin_city_id"],
            destination_city_id=row["destination_city_id"],
            transport_id=row["transport_id"],
            fare=row["fare"],
            started_at=row["started_at"],
            arrival_at=row["arrival_at"],
            transport_name=row["transport_name"],
            transport_image=row["transport_image"],
            transport_credit=row["transport_credit"],
        )
