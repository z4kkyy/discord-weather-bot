"""
Copyright © Krypton 2019-2023 - https://github.com/kkrypt0nn (https://krypton.ninja)

Version: 6.1.0

Modified by z4kky - https://github.com/z4kkyy
Further modified to include necessary database operations
"""

import aiosqlite


class DatabaseManager:
    def __init__(self, *, connection: aiosqlite.Connection) -> None:
        self.connection = connection

    async def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = []
        async with self.connection.cursor() as cursor:
            await cursor.execute(sql, parameters)
            return cursor

    async def fetchone(self, sql, parameters=None):
        if parameters is None:
            parameters = []
        async with self.connection.cursor() as cursor:
            await cursor.execute(sql, parameters)
            return await cursor.fetchone()

    async def fetchall(self, sql, parameters=None):
        if parameters is None:
            parameters = []
        async with self.connection.cursor() as cursor:
            await cursor.execute(sql, parameters)
            return await cursor.fetchall()

    async def commit(self):
        await self.connection.commit()

    async def close(self):
        await self.connection.close()
