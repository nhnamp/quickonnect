import logging
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool
from psycopg_pool import PoolTimeout

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    pool = ConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        open=True,
    )
    try:
        pool.wait(timeout=5)
    except PoolTimeout:
        pool.close()
        logger.error("Database connection pool could not open any PostgreSQL connection")
        raise
    _pool = pool
    logger.info("Database connection pool initialized (min=%d, max=%d)", min_size, max_size)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


@contextmanager
def get_connection():
    """Yield a database connection from the pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    with _pool.connection() as conn:
        yield conn
