import asyncpg
from typing import Optional
from app.config import settings

class Database:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "Database pool is not initialized"
        return self._pool

    async def connect(self):
        self._pool = await asyncpg.create_pool(dsn=settings.database_url)

    async def disconnect(self):
        if self._pool:
            await self._pool.close()

db = Database()
