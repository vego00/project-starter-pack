"""PostgreSQL checkpointer so a journey outlives the process (Notion 02-1 §2.6, DiV P4)."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

POOL_MAX_SIZE = 5


@contextmanager
def open_checkpointer(database_url: str, *, timeout: float = 10) -> Iterator[PostgresSaver]:
    """Opens a pool and creates missing tables; raises PoolTimeout if the DB is unreachable."""
    with ConnectionPool(
        database_url,
        min_size=1,
        max_size=POOL_MAX_SIZE,
        open=False,
        # Connection options required by PostgresSaver.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        pool.wait(timeout=timeout)
        saver = PostgresSaver(pool)
        saver.setup()
        yield saver
