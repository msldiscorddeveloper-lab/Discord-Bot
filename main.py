"""
MLBB Community Discord Bot
Main entry point with dynamic cog loading.
"""

import discord
import asyncio
import logging
from pathlib import Path
from discord.ext import commands

from config import DISCORD_TOKEN, GUILD_ID
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

# Target guild object (created after bot connects)
TARGET_GUILD = None


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    global TARGET_GUILD
    logger.info(f'Bot started as {bot.user}')
    
    # Initialize database
    await db.get_pool()
    logger.info('Database connected')
    
    # Check for missing settings
    await check_missing_settings()
    
    # Get target guild
    TARGET_GUILD = bot.get_guild(GUILD_ID)
    
    # Sync slash commands to the specific guild only
    try:
        if TARGET_GUILD:
            # Debug: Show how many commands are in the tree
            all_commands = bot.tree.get_commands()
            logger.info(f'Commands in tree before sync: {len(all_commands)}')
            for cmd in all_commands:
                logger.info(f'  - /{cmd.name}')
            
            bot.tree.copy_global_to(guild=TARGET_GUILD)
            synced = await bot.tree.sync(guild=TARGET_GUILD)
            logger.info(f'Synced {len(synced)} slash commands to {TARGET_GUILD.name}')
        else:
            logger.warning(f'Target guild {GUILD_ID} not found! Bot may not be in the server.')
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
        "cogs.embed_cog",
        "cogs.voice_cog",
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
        "embeds": "cogs.embed_cog",
        "voice": "cogs.voice_cog",
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


@bot.tree.command(name="help", description="View all available commands")
async def help_command(inter: discord.Interaction):
    """Display commands based on user's roles and permissions."""
    
    # ─────────────────────────────────────────────────────────────────
    # Command Metadata: Define all commands with their category
    # Categories: 'general', 'booster', 'admin'
    # ─────────────────────────────────────────────────────────────────
    
    COMMANDS = {
        "general": {
            "emoji": "🎯",
            "title": "General",
            "commands": [
                ("**`/help`**", "Show this help menu"),
                ("**`/ping`**", "Check bot response time"),
                ("**`/rank [user]`**", "View XP and server rank"),
                ("**`/leaderboard`**", "View top 10 XP earners"),
            ]
        },
        "booster": {
            "emoji": "💎",
            "title": "Booster Perks",
            "commands": [
                ("**`/boostperks`**", "View your tier and multipliers"),
                ("**`/colorpick`**", "Choose a custom name color"),
                ("**`/emblempick`**", "Choose an emblem badge"),
                ("**`/pouch`**", "Claim daily token pouch"),
            ]
        },
        "admin_voice": {
            "emoji": "🎤",
            "title": "Voice Channels",
            "commands": [
                ("**`/autocreate_setup <channel>`**", "Set up auto-create VC"),
                ("**`/autocreate_remove <channel>`**", "Remove auto-create"),
            ]
        },
        "admin_embeds": {
            "emoji": "📝",
            "title": "Embeds",
            "commands": [
                ("**`/send_embed <channel> <link> [mins]`**", "Send/schedule embed"),
                ("**`/cancel_embed`**", "Cancel scheduled embed"),
                ("**`/set_embed_log <channel>`**", "Set embed log channel"),
            ]
        },
        "admin_mod": {
            "emoji": "🛡️",
            "title": "Moderation",
            "commands": [
                ("**`/warn <user> <reason>`**", "Warning + 24h XP lock"),
                ("**`/mute <user> <duration> [reason]`**", "Assign Muted role"),
                ("**`/unmute <user>`**", "Remove Muted role"),
                ("**`/restrict <user> <duration> [reason]`**", "Block images/embeds"),
                ("**`/unrestrict <user>`**", "Restore access"),
                ("**`/kick <user> [reason]`**", "Kick from server"),
                ("**`/ban <user> [duration] [reason]`**", "Ban (perm wipes data)"),
                ("**`/history <user>`**", "View mod history"),
            ]
        },
        "admin_setup": {
            "emoji": "⚙️",
            "title": "Setup",
            "commands": [
                ("**`/setup view`**", "View all current settings"),
                ("**`/setup channel <type> <#channel>`**", "Set bot channels"),
                ("**`/setup role <type> <@role>`**", "Set roles (muted, restricted)"),
                ("**`/boosters`**", "List all server boosters"),
                ("**`/reload [cog]`**", "Hot-reload bot cogs"),
            ]
        },
    }
    
    # ─────────────────────────────────────────────────────────────────
    # Determine User's Access Level
    # ─────────────────────────────────────────────────────────────────
    
    member = inter.user
    is_admin = member.guild_permissions.administrator if inter.guild else False
    is_booster = member.premium_since is not None if hasattr(member, 'premium_since') else False
    
    # Determine which categories to show
    visible_categories = ["general"]
    
    if is_booster or is_admin:
        visible_categories.append("booster")
    
    if is_admin:
        visible_categories.extend(["admin_voice", "admin_embeds", "admin_mod", "admin_setup"])
    
    # ─────────────────────────────────────────────────────────────────
    # Build the Embed
    # ─────────────────────────────────────────────────────────────────
    
    # Set title and color based on access level
    if is_admin:
        title = "📖 Bot Commands (Admin View)"
        color = discord.Color.red()
        description = "You have **admin** access. Showing all commands."
    elif is_booster:
        title = "📖 Bot Commands (Booster View)"
        color = discord.Color(0xf47fff)  # Nitro pink
        description = "You have **booster** perks! Showing general + booster commands."
    else:
        title = "📖 Bot Commands"
        color = discord.Color.blue()
        description = "Showing public commands available to everyone."
    
    embed = discord.Embed(title=title, description=description, color=color)
    
    # Add fields for each visible category
    for cat_key in visible_categories:
        cat = COMMANDS[cat_key]
        
        # Format commands as "command — description"
        lines = [f"{cmd} — {desc}" for cmd, desc in cat["commands"]]
        value = "\n".join(lines)
        
        embed.add_field(
            name=f"{cat['emoji']} {cat['title']}",
            value=value,
            inline=False
        )
    
    # Footer based on access level
    if not is_admin and not is_booster:
        embed.set_footer(text="� Boost the server to unlock booster-exclusive commands!")
    elif is_booster and not is_admin:
        embed.set_footer(text="💜 Thank you for boosting!")
    else:
        embed.set_footer(text="🔐 Administrator access granted")
    
    await inter.response.send_message(embed=embed, ephemeral=True)


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