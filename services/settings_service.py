"""
Settings Service - Manages server configuration stored in database.
"""

from services.database import db


class SettingsService:
    """Handles server settings stored in database."""
    
    # Default settings keys
    KEYS = {
        # Channels
        "bot_channel_id": "0",
        "boost_announce_channel_id": "0",
        "booster_chat_channel_id": "0",
        "booster_lounge_vc_id": "0",
        "mod_log_channel_id": "0",
        "command_log_channel_id": "0",
        
        # Tier roles
        "server_booster_role_id": "0",
        "veteran_booster_role_id": "0",
        "mythic_booster_role_id": "0",
        
        # Other roles
        "booster_spotlight_role_id": "0",
        
        # Moderation roles
        "muted_role_id": "0",
        "restricted_role_id": "0",
        
        # Color roles (stored as JSON list)
        "booster_color_roles": "[]",
        
        # Emblem roles (stored as JSON dict)
        "booster_emblem_roles": "{}",
    }
    
    async def get(self, key: str) -> str:
        """Get a setting value."""
        result = await db.fetch_one(
            'SELECT value FROM server_settings WHERE `key` = %s',
            (key,)
        )
        if result:
            return result['value']
        return self.KEYS.get(key, "0")
    
    async def get_int(self, key: str) -> int:
        """Get a setting as integer."""
        value = await self.get(key)
        try:
            return int(value)
        except ValueError:
            return 0
    
    async def set(self, key: str, value: str) -> None:
        """Set a setting value."""
        await db.execute('''
            INSERT INTO server_settings (`key`, value) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE value = VALUES(value)
        ''', (key, value))
    
    async def get_all(self) -> dict:
        """Get all settings."""
        rows = await db.fetch_all('SELECT `key`, value FROM server_settings')
        settings = dict(self.KEYS)  # Start with defaults
        for row in rows:
            settings[row['key']] = row['value']
        return settings
    
    async def get_color_roles(self) -> dict:
        """Get color roles as dict {name: role_id}."""
        import json
        value = await self.get("booster_color_roles")
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    
    async def set_color_role(self, name: str, role_id: int) -> None:
        """Add or update a color role."""
        import json
        roles = await self.get_color_roles()
        roles[name] = role_id
        await self.set("booster_color_roles", json.dumps(roles))
    
    async def remove_color_role(self, name: str) -> None:
        """Remove a color role."""
        import json
        roles = await self.get_color_roles()
        roles.pop(name, None)
        await self.set("booster_color_roles", json.dumps(roles))
    
    async def get_emblem_roles(self) -> dict:
        """Get emblem roles as dict {emoji: role_id}."""
        import json
        value = await self.get("booster_emblem_roles")
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    
    async def set_emblem_role(self, emoji: str, role_id: int) -> None:
        """Add or update an emblem role."""
        import json
        roles = await self.get_emblem_roles()
        roles[emoji] = role_id
        await self.set("booster_emblem_roles", json.dumps(roles))


# Singleton instance
settings_service = SettingsService()
