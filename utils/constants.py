"""
Utility constants for the bot.
"""

import datetime
import pytz

# Philippine Standard Time
TZ_MANILA = pytz.timezone('Asia/Manila')

def now_manila():
    """Get current time in Manila timezone."""
    return datetime.datetime.now(TZ_MANILA)
