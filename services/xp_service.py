"""
XP Service - Business logic for XP/Leveling system.
Handles all XP calculations and database operations.
"""

from datetime import datetime
from services.database import db


class XpService:
    """Handles XP-related business logic."""
    
    async def get_multiplier(self, user_id: int) -> float:
        """Get a user's current XP multiplier."""
        result = await db.fetch_one(
            'SELECT xp_multiplier FROM users WHERE user_id = ?',
            (user_id,)
        )
        return result['xp_multiplier'] if result and result['xp_multiplier'] else 1.0
    
    async def is_xp_locked(self, user_id: int) -> bool:
        """Check if user is XP locked (from warn)."""
        result = await db.fetch_one(
            'SELECT xp_locked, xp_lock_until FROM users WHERE user_id = ?',
            (user_id,)
        )
        if not result or not result['xp_locked']:
            return False
        
        # Check if lock expired
        if result['xp_lock_until']:
            lock_until = datetime.fromisoformat(result['xp_lock_until'])
            if datetime.now() > lock_until:
                # Auto-remove expired lock
                await db.execute('UPDATE users SET xp_locked = 0, xp_lock_until = NULL WHERE user_id = ?', (user_id,))
                return False
        return True
    
    async def add_xp(self, user_id: int, amount: int) -> int:
        """
        Add XP to a user (with multiplier applied) and return new total.
        Returns 0 if user is XP locked.
        """
        # Check XP lock
        if await self.is_xp_locked(user_id):
            return 0
        
        # Get user's multiplier
        multiplier = await self.get_multiplier(user_id)
        final_xp = int(amount * multiplier)
        
        await db.execute('''
            INSERT INTO users (user_id, xp) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET xp = xp + ?
        ''', (user_id, final_xp, final_xp))
        
        result = await db.fetch_one(
            'SELECT xp FROM users WHERE user_id = ?', 
            (user_id,)
        )
        return result['xp'] if result else final_xp
    
    async def get_xp(self, user_id: int) -> int:
        """Get a user's current XP."""
        result = await db.fetch_one(
            'SELECT xp FROM users WHERE user_id = ?', 
            (user_id,)
        )
        return result['xp'] if result else 0
    
    async def get_leaderboard(self, limit: int = 10) -> list:
        """Get the top users by XP."""
        rows = await db.fetch_all(
            'SELECT user_id, xp FROM users ORDER BY xp DESC LIMIT ?',
            (limit,)
        )
        return [(row['user_id'], row['xp']) for row in rows]
    
    async def batch_update(self, pending_xp: dict) -> None:
        """
        Batch update XP for multiple users (with multipliers applied).
        """
        for user_id, xp in pending_xp.items():
            multiplier = await self.get_multiplier(user_id)
            final_xp = int(xp * multiplier)
            await db.execute('''
                INSERT INTO users (user_id, xp) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET xp = xp + ?
            ''', (user_id, final_xp, final_xp))
    
    async def get_rank(self, user_id: int) -> tuple:
        """Get a user's rank and XP."""
        xp = await self.get_xp(user_id)
        if xp == 0:
            return (None, 0)
        
        result = await db.fetch_one('''
            SELECT COUNT(*) + 1 as rank 
            FROM users 
            WHERE xp > (SELECT xp FROM users WHERE user_id = ?)
        ''', (user_id,))
        
        return (result['rank'], xp) if result else (None, xp)
    
    # ─────────────────────────────────────────────────────────────────────
    # Booster Perks Methods
    # ─────────────────────────────────────────────────────────────────────
    
    async def set_booster_perks(
        self, 
        user_id: int, 
        xp_multiplier: float, 
        shop_discount: float,
        boost_start_date: datetime = None
    ) -> None:
        """
        Set booster perks for a user.
        
        Args:
            user_id: Discord user ID
            xp_multiplier: XP multiplier (e.g., 1.5 for 50% bonus)
            shop_discount: Shop discount (e.g., 0.20 for 20% off)
            boost_start_date: When they started boosting
        """
        start_date = boost_start_date or datetime.now()
        
        await db.execute('''
            INSERT INTO users (user_id, xp_multiplier, shop_discount, boost_start_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                xp_multiplier = ?,
                shop_discount = ?,
                boost_start_date = COALESCE(boost_start_date, ?)
        ''', (user_id, xp_multiplier, shop_discount, start_date,
              xp_multiplier, shop_discount, start_date))
    
    async def remove_booster_perks(self, user_id: int) -> None:
        """Remove all booster perks from a user."""
        await db.execute('''
            UPDATE users SET 
                xp_multiplier = 1.0,
                shop_discount = 0.0,
                boost_start_date = NULL
            WHERE user_id = ?
        ''', (user_id,))
    
    async def get_boost_start_date(self, user_id: int) -> datetime | None:
        """Get when a user started boosting."""
        result = await db.fetch_one(
            'SELECT boost_start_date FROM users WHERE user_id = ?',
            (user_id,)
        )
        if result and result['boost_start_date']:
            return datetime.fromisoformat(result['boost_start_date'])
        return None
    
    async def get_user_perks(self, user_id: int) -> dict:
        """Get all perks for a user."""
        result = await db.fetch_one('''
            SELECT xp_multiplier, shop_discount, boost_start_date
            FROM users WHERE user_id = ?
        ''', (user_id,))
        
        if result:
            return {
                'xp_multiplier': result['xp_multiplier'] or 1.0,
                'shop_discount': result['shop_discount'] or 0.0,
                'boost_start_date': result['boost_start_date'],
            }
        return {'xp_multiplier': 1.0, 'shop_discount': 0.0, 'boost_start_date': None}


# Singleton instance
xp_service = XpService()

