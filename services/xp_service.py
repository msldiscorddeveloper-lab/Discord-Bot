"""
XP Service - Business logic for XP/Leveling system.
Handles all XP calculations and database operations.
"""

from services.database import db


class XpService:
    """Handles XP-related business logic."""
    
    async def add_xp(self, user_id: int, amount: int) -> int:
        """
        Add XP to a user and return their new total.
        
        Args:
            user_id: Discord user ID
            amount: Amount of XP to add
            
        Returns:
            New total XP for the user
        """
        await db.execute('''
            INSERT INTO users (user_id, xp) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET xp = xp + ?
        ''', (user_id, amount, amount))
        
        result = await db.fetch_one(
            'SELECT xp FROM users WHERE user_id = ?', 
            (user_id,)
        )
        return result['xp'] if result else amount
    
    async def get_xp(self, user_id: int) -> int:
        """
        Get a user's current XP.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            User's current XP, or 0 if not found
        """
        result = await db.fetch_one(
            'SELECT xp FROM users WHERE user_id = ?', 
            (user_id,)
        )
        return result['xp'] if result else 0
    
    async def get_leaderboard(self, limit: int = 10) -> list:
        """
        Get the top users by XP.
        
        Args:
            limit: Number of users to return
            
        Returns:
            List of (user_id, xp) tuples
        """
        rows = await db.fetch_all(
            'SELECT user_id, xp FROM users ORDER BY xp DESC LIMIT ?',
            (limit,)
        )
        return [(row['user_id'], row['xp']) for row in rows]
    
    async def batch_update(self, pending_xp: dict) -> None:
        """
        Batch update XP for multiple users at once.
        More efficient than individual updates.
        
        Args:
            pending_xp: Dict mapping user_id -> xp_amount
        """
        for user_id, xp in pending_xp.items():
            await db.execute('''
                INSERT INTO users (user_id, xp) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET xp = xp + ?
            ''', (user_id, xp, xp))
    
    async def get_rank(self, user_id: int) -> tuple:
        """
        Get a user's rank and XP.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Tuple of (rank, xp) or (None, 0) if not found
        """
        xp = await self.get_xp(user_id)
        if xp == 0:
            return (None, 0)
        
        result = await db.fetch_one('''
            SELECT COUNT(*) + 1 as rank 
            FROM users 
            WHERE xp > (SELECT xp FROM users WHERE user_id = ?)
        ''', (user_id,))
        
        return (result['rank'], xp) if result else (None, xp)


# Singleton instance
xp_service = XpService()
