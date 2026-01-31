"""
MLBB Community Discord Bot
Main entry point with dynamic cog loading.
"""

import discord
import asyncio
import logging
from pathlib import Path
from discord.ext import commands

from config import DISCORD_TOKEN
from services.database import db
from services.settings_service import settings_service

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mlbb_bot')

# Configure intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# Create bot instance
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f'Bot started as {bot.user}')
    
    # Initialize database
    await db.connect()
    logger.info('Database connected')
    
    # Check for missing settings
    await check_missing_settings()
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f'Synced {len(synced)} slash commands')
    except Exception as e:
        logger.error(f'Failed to sync commands: {e}')
    
    # Send startup message
    bot_channel_id = await settings_service.get_int("bot_channel_id")
    if bot_channel_id:
        channel = bot.get_channel(bot_channel_id)
        if channel:
            await channel.send("✅ Bot started successfully!")


async def check_missing_settings():
    """Log warnings for settings that haven't been configured."""
    settings_to_check = {
        # Channels
        "bot_channel_id": "Bot Channel (!setup channel bot #channel)",
        "boost_announce_channel_id": "Boost Announce (!setup channel announce #channel)",
        "mod_log_channel_id": "Mod Log (!setup channel modlog #channel)",
        # Roles
        "server_booster_role_id": "Server Booster Role (!setup role server @role)",
        "veteran_booster_role_id": "Veteran Booster Role (!setup role veteran @role)",
        "mythic_booster_role_id": "Mythic Booster Role (!setup role mythic @role)",
        "verified_role_id": "Verified Role (!setup role verified @role)",
    }
    
    missing = []
    for key, label in settings_to_check.items():
        value = await settings_service.get_int(key)
        if value == 0:
            missing.append(label)
    
    if missing:
        logger.warning("⚠️ Missing settings (use !setup to configure):")
        for item in missing:
            logger.warning(f"   - {item}")


async def load_extensions():
    """Dynamically load all cogs from the cogs directory."""
    cogs_dir = Path(__file__).parent / "cogs"
    
    # List of cog modules to load
    cog_modules = [
        "cogs.leveling.xp_cog",
        "cogs.moderation.mod_cog",
        "cogs.tracker.boost_cog",
        "cogs.setup.setup_cog",
    ]
    
    for cog in cog_modules:
        try:
            await bot.load_extension(cog)
            logger.info(f'Loaded extension: {cog}')
        except Exception as e:
            logger.error(f'Failed to load {cog}: {e}')


@bot.command()
@commands.has_permissions(administrator=True)
async def reload(ctx: commands.Context, cog_name: str = None):
    """
    Reload cogs. Usage: !reload [cog_name]
    If no cog specified, reloads all cogs.
    """
    cog_mapping = {
        "xp": "cogs.leveling.xp_cog",
        "leveling": "cogs.leveling.xp_cog",
        "mod": "cogs.moderation.mod_cog",
        "moderation": "cogs.moderation.mod_cog",
        "boost": "cogs.tracker.boost_cog",
        "tracker": "cogs.tracker.boost_cog",
        "setup": "cogs.setup.setup_cog",
    }
    
    if cog_name:
        # Reload specific cog
        cog_path = cog_mapping.get(cog_name.lower())
        if not cog_path:
            return await ctx.reply(f"❌ Unknown cog: `{cog_name}`")
        
        try:
            await bot.reload_extension(cog_path)
            await ctx.reply(f"✅ Reloaded `{cog_name}`")
            logger.info(f'Reloaded: {cog_path}')
        except Exception as e:
            await ctx.reply(f"❌ Failed to reload: {e}")
    else:
        # Reload all cogs
        reloaded = []
        failed = []
        
        for name, path in cog_mapping.items():
            if path not in [cog_mapping[k] for k in list(cog_mapping.keys())[:list(cog_mapping.keys()).index(name)]]:
                try:
                    await bot.reload_extension(path)
                    reloaded.append(name)
                except Exception as e:
                    failed.append(f"{name}: {e}")
        
        msg = f"✅ Reloaded: {', '.join(reloaded)}" if reloaded else ""
        if failed:
            msg += f"\n❌ Failed: {', '.join(failed)}"
        
        await ctx.reply(msg or "No cogs to reload")


@bot.command()
async def ping(ctx: commands.Context):
    """Check bot latency."""
    latency = round(bot.latency * 1000)
    await ctx.reply(f"🏓 Pong! Latency: `{latency}ms`")


async def main():
    """Main entry point."""
    async with bot:
        await load_extensions()
        await bot.start(DISCORD_TOKEN)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Bot stopped by user')