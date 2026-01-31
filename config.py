"""
Centralized configuration for the MLBB Discord Bot.
Loads environment variables from .env file.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Discord Bot Settings
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not found in environment variables!")

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "levels.db")

# Channel IDs
BOT_CHANNEL_ID = int(os.getenv("BOT_CHANNEL_ID", "0"))
BOOST_ANNOUNCE_CHANNEL_ID = int(os.getenv("BOOST_ANNOUNCE_CHANNEL_ID", "0"))

# XP Settings
XP_CONFIG = {
    "message": {
        "min_xp": 10,
        "max_xp": 15,
        "min_length": 10,        # Minimum message length to earn XP
        "cooldown_seconds": 10,  # One XP gain per cycle
    },
    "reaction": {
        "xp_per_reaction": 5,
        "max_xp_per_message": 50,   # Max XP a message can generate from reactions
        "daily_cap": 100,           # User's daily cap for reaction XP
    },
    "voice": {
        "xp_per_cycle": 2,
        "min_members": 2,           # Minimum active members in VC
        "cycle_seconds": 10,
    },
}

# Batch update interval (seconds)
BATCH_UPDATE_INTERVAL = 10

# ─────────────────────────────────────────────────────────────────────
# Booster Rewards System
# ─────────────────────────────────────────────────────────────────────

# Private Booster Channels
BOOSTER_CHAT_CHANNEL_ID = int(os.getenv("BOOSTER_CHAT_CHANNEL_ID", "0"))
BOOSTER_LOUNGE_VC_ID = int(os.getenv("BOOSTER_LOUNGE_VC_ID", "0"))

# Booster Tier Configuration
BOOSTER_TIERS = {
    "server": {
        "name": "Server Booster",
        "role_id": int(os.getenv("SERVER_BOOSTER_ROLE_ID", "0")),
        "months_required": 0,
        "xp_multiplier": 1.5,
        "token_multiplier": 1.5,  # MSL Token multiplier
        "shop_discount": 0.20,
        "raffle_entries": 1,      # Weekly diamond raffle
        "daily_pouches": 1,       # Moniyan Mystery Pouches
    },
    "veteran": {
        "name": "Veteran Booster",
        "role_id": int(os.getenv("VETERAN_BOOSTER_ROLE_ID", "0")),
        "months_required": 3,
        "xp_multiplier": 1.75,
        "token_multiplier": 1.75,
        "shop_discount": 0.20,
        "raffle_entries": 4,
        "daily_pouches": 2,
    },
    "mythic": {
        "name": "Mythic Booster",
        "role_id": int(os.getenv("MYTHIC_BOOSTER_ROLE_ID", "0")),
        "months_required": 5,
        "xp_multiplier": 2.0,
        "token_multiplier": 2.0,
        "shop_discount": 0.20,
        "raffle_entries": 8,
        "daily_pouches": 3,
        "spotlight_eligible": True,  # Booster of the Week
    },
}

# Booster Color Roles (15 exclusive colors)
# Format: {"display_name": role_id}
def _parse_color_roles():
    """Parse color role IDs from environment."""
    roles = {}
    color_names = [
        "Ruby Red", "Sapphire Blue", "Emerald Green", "Amethyst Purple",
        "Topaz Gold", "Diamond White", "Obsidian Black", "Rose Pink",
        "Ocean Teal", "Sunset Orange", "Midnight Navy", "Forest Green",
        "Coral Pink", "Arctic Blue", "Royal Purple"
    ]
    for i, name in enumerate(color_names, 1):
        role_id = int(os.getenv(f"BOOSTER_COLOR_ROLE_{i}", "0"))
        if role_id:
            roles[name] = role_id
    return roles

BOOSTER_COLOR_ROLES = _parse_color_roles()

# Booster Emblem Roles (Tier 2+ only)
BOOSTER_EMBLEM_ROLES = {
    "💠": int(os.getenv("BOOSTER_EMBLEM_DIAMOND", "0")),
    "⚜️": int(os.getenv("BOOSTER_EMBLEM_FLEUR", "0")),
    "🔱": int(os.getenv("BOOSTER_EMBLEM_TRIDENT", "0")),
    "⭐": int(os.getenv("BOOSTER_EMBLEM_STAR", "0")),
    "👑": int(os.getenv("BOOSTER_EMBLEM_CROWN", "0")),
}

# Spotlight role for "Booster of the Week"
BOOSTER_SPOTLIGHT_ROLE_ID = int(os.getenv("BOOSTER_SPOTLIGHT_ROLE_ID", "0"))

# List of all booster role IDs for easy lookup
BOOSTER_ROLE_IDS = [tier["role_id"] for tier in BOOSTER_TIERS.values() if tier["role_id"]]

