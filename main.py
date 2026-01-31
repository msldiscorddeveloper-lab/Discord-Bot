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
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
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
    await db.get_pool()
    logger.info('Database connected')
    
    # Check for missing settings
    await check_missing_settings()
    
    # Sync slash commands to guild for instant update
    try:
        guild = bot.guilds[0] if bot.guilds else None
        if guild:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f'Synced {len(synced)} slash commands to {guild.name}')
        else:
            synced = await bot.tree.sync()
            logger.info(f'Synced {len(synced)} slash commands globally')
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


@bot.tree.command(name="reload", description="Reload bot cogs (Admin only)")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(cog="Cog to reload (leave empty for all)")
async def reload(inter: discord.Interaction, cog: str = None):
    """Reload cogs."""
    cog_mapping = {
        "xp": "cogs.leveling.xp_cog",
        "leveling": "cogs.leveling.xp_cog",
        "mod": "cogs.moderation.mod_cog",
        "moderation": "cogs.moderation.mod_cog",
        "boost": "cogs.tracker.boost_cog",
        "tracker": "cogs.tracker.boost_cog",
        "setup": "cogs.setup.setup_cog",
    }
    
    if cog:
        cog_path = cog_mapping.get(cog.lower())
        if not cog_path:
            return await inter.response.send_message(f"❌ Unknown cog: `{cog}`", ephemeral=True)
        
        try:
            await bot.reload_extension(cog_path)
            await inter.response.send_message(f"✅ Reloaded `{cog}`", ephemeral=True)
            logger.info(f'Reloaded: {cog_path}')
        except Exception as e:
            await inter.response.send_message(f"❌ Failed to reload: {e}", ephemeral=True)
    else:
        reloaded = []
        failed = []
        unique_paths = list(dict.fromkeys(cog_mapping.values()))
        
        for path in unique_paths:
            try:
                await bot.reload_extension(path)
                reloaded.append(path.split('.')[-1])
            except Exception as e:
                failed.append(f"{path}: {e}")
        
        msg = f"✅ Reloaded: {', '.join(reloaded)}" if reloaded else ""
        if failed:
            msg += f"\n❌ Failed: {', '.join(failed)}"
        
        await inter.response.send_message(msg or "No cogs to reload", ephemeral=True)


@bot.tree.command(name="ping", description="Check bot latency")
async def ping(inter: discord.Interaction):
    """Check bot latency."""
    latency = round(bot.latency * 1000)
    await inter.response.send_message(f"🏓 Pong! Latency: `{latency}ms`")


async def main():
    """Main entry point."""
    await load_extensions()
    await bot.start(DISCORD_TOKEN)


async def shutdown():
    """Graceful shutdown - close bot and database."""
    logger.info('Shutting down gracefully...')
    try:
        await db.close()
    except:
        pass
    if not bot.is_closed():
        await bot.close()
    logger.info('Bot stopped')


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info('Received Ctrl+C, shutting down...')
    finally:
        # Cleanup
        loop.run_until_complete(shutdown())
        
        # Cancel all pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # Wait for cancellation
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        
        loop.close()
        logger.info('Shutdown complete')