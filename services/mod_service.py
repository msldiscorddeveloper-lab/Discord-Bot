"""
Moderation Service - Business logic for moderation actions.
Handles logging and retrieval of moderation history.
"""

from datetime import datetime
from services.database import db


class ModService:
    """Handles moderation-related business logic."""
    
    async def log_action(
        self, 
        action_type: str, 
        moderator_id: int, 
        target_id: int, 
        reason: str = None
    ) -> int:
        """
        Log a moderation action to the database.
        
        Args:
            action_type: Type of action (kick, ban, mute, warn, unmute, unban)
            moderator_id: Discord ID of the moderator
            target_id: Discord ID of the target user
            reason: Optional reason for the action
            
        Returns:
            The ID of the created log entry
        """
        cursor = await db.execute('''
            INSERT INTO mod_logs (action_type, moderator_id, target_id, reason)
            VALUES (?, ?, ?, ?)
        ''', (action_type, moderator_id, target_id, reason))
        
        return cursor.lastrowid
    
    async def get_user_history(self, user_id: int, limit: int = 10) -> list:
        """
        Get moderation history for a specific user.
        
        Args:
            user_id: Discord user ID
            limit: Maximum number of records to return
            
        Returns:
            List of moderation log entries
        """
        rows = await db.fetch_all('''
            SELECT id, action_type, moderator_id, reason, timestamp
            FROM mod_logs
            WHERE target_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (user_id, limit))
        
        return [dict(row) for row in rows]
    
    async def get_mod_actions(self, moderator_id: int, limit: int = 10) -> list:
        """
        Get actions performed by a specific moderator.
        
        Args:
            moderator_id: Discord user ID of the moderator
            limit: Maximum number of records to return
            
        Returns:
            List of moderation log entries
        """
        rows = await db.fetch_all('''
            SELECT id, action_type, target_id, reason, timestamp
            FROM mod_logs
            WHERE moderator_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (moderator_id, limit))
        
        return [dict(row) for row in rows]
    
    async def get_action_count(self, user_id: int, action_type: str = None) -> int:
        """
        Count moderation actions against a user.
        
        Args:
            user_id: Discord user ID
            action_type: Optional filter by action type
            
        Returns:
            Count of matching actions
        """
        if action_type:
            result = await db.fetch_one('''
                SELECT COUNT(*) as count 
                FROM mod_logs 
                WHERE target_id = ? AND action_type = ?
            ''', (user_id, action_type))
        else:
            result = await db.fetch_one('''
                SELECT COUNT(*) as count 
                FROM mod_logs 
                WHERE target_id = ?
            ''', (user_id,))
        
        return result['count'] if result else 0


# Singleton instance
mod_service = ModService()
