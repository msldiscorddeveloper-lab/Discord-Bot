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
