"""
Async database connection management using aiosqlite.
Provides a centralized database pool for all services.
"""

import aiosqlite
from config import DATABASE_PATH


class Database:
    """Async SQLite database wrapper."""
    
    _instance = None
    _connection = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self):
        """Initialize the database connection."""
        if self._connection is None:
            self._connection = await aiosqlite.connect(DATABASE_PATH)
            self._connection.row_factory = aiosqlite.Row
            await self._init_tables()
        return self._connection
    
    async def _init_tables(self):
        """Create tables if they don't exist."""
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                tokens INTEGER DEFAULT 0,
                xp_multiplier REAL DEFAULT 1.0,
                token_multiplier REAL DEFAULT 1.0,
                shop_discount REAL DEFAULT 0.0,
                boost_start_date DATETIME DEFAULT NULL,
                badges TEXT DEFAULT '[]',
                color_role_id INTEGER DEFAULT NULL,
                emblem_role_id INTEGER DEFAULT NULL,
                raffle_entries INTEGER DEFAULT 0,
                pouches_today INTEGER DEFAULT 0,
                last_pouch_date DATE DEFAULT NULL
            )
        ''')
        
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS mod_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Server settings table for storing role/channel IDs
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        await self._connection.commit()
    
    async def close(self):
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
    
    async def execute(self, query: str, params: tuple = ()):
        """Execute a query and return cursor."""
        conn = await self.connect()
        cursor = await conn.execute(query, params)
        await conn.commit()
        return cursor
    
    async def fetch_one(self, query: str, params: tuple = ()):
        """Fetch a single row."""
        conn = await self.connect()
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()
    
    async def fetch_all(self, query: str, params: tuple = ()):
        """Fetch all rows."""
        conn = await self.connect()
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()


# Singleton instance
db = Database()
