"""Who owns each journey. The journeys themselves stay in the LangGraph checkpoints."""

from typing import Protocol
from uuid import UUID

from psycopg_pool import ConnectionPool


class OwnerStore(Protocol):
    def add(self, journey_id: UUID, email: str) -> None: ...

    def owner(self, journey_id: UUID) -> str | None: ...


class MemoryOwners:
    def __init__(self) -> None:
        self._owners: dict[UUID, str] = {}

    def add(self, journey_id: UUID, email: str) -> None:
        self._owners[journey_id] = email

    def owner(self, journey_id: UUID) -> str | None:
        return self._owners.get(journey_id)


class PostgresOwners:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def setup(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS journey_owners ("
                " journey_id uuid PRIMARY KEY,"
                " owner_email text NOT NULL,"
                " created_at timestamptz NOT NULL DEFAULT now())"
            )

    def add(self, journey_id: UUID, email: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO journey_owners (journey_id, owner_email) VALUES (%s, %s)",
                (journey_id, email),
            )

    def owner(self, journey_id: UUID) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT owner_email FROM journey_owners WHERE journey_id = %s", (journey_id,)
            ).fetchone()
        return row["owner_email"] if row else None
