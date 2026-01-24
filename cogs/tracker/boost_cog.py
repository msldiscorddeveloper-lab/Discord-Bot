"""
Boost Tracker Cog - Detects and announces server boosts.
Uses on_member_update to detect changes in premium_since.
"""

import discord
from datetime import datetime, timedelta
from discord.ext import commands

from config import BOOST_ANNOUNCE_CHANNEL_ID
from utils.embeds import create_boost_announcement_embed


class BoostCog(commands.Cog, name="Boost Tracker"):
    """Tracks and announces server boosts."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Anti-spam: Track recent boost announcements
        # Key: user_id -> datetime of last announcement
        self.recent_boosts = {}
        
        # Cooldown period (prevent duplicate announcements)
        self.cooldown_seconds = 60
    
    # ─────────────────────────────────────────────────────────────────────
    # Event Listeners
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Detect when a member boosts the server.
        
        Anti-spam strategy:
        1. Only trigger when premium_since changes from None to a timestamp
        2. Use cooldown dict to prevent duplicate announcements
        3. Clean up old cooldown entries periodically
        """
        # Skip if boost status didn't change
        if before.premium_since == after.premium_since:
            return
        
        # Detect NEW boost (was None, now has a timestamp)
        if before.premium_since is None and after.premium_since is not None:
            await self._handle_new_boost(after)
    
    async def _handle_new_boost(self, member: discord.Member):
        """Process a new boost and announce it."""
        user_id = member.id
        now = datetime.now()
        
        # Anti-spam: Check cooldown
        if user_id in self.recent_boosts:
            last_announcement = self.recent_boosts[user_id]
            if (now - last_announcement).total_seconds() < self.cooldown_seconds:
                return  # Still in cooldown, skip
        
        # Update cooldown cache
        self.recent_boosts[user_id] = now
        
        # Clean up old entries (older than 5 minutes)
        self._cleanup_old_boosts()
        
        # Get announcement channel
        channel = self.bot.get_channel(BOOST_ANNOUNCE_CHANNEL_ID)
        if not channel:
            print(f"[BoostTracker] Warning: Could not find channel {BOOST_ANNOUNCE_CHANNEL_ID}")
            return
        
        # Create and send announcement
        embed = create_boost_announcement_embed(member)
        
        try:
            await channel.send(embed=embed)
            print(f"[BoostTracker] Announced boost from {member.display_name}")
        except discord.Forbidden:
            print(f"[BoostTracker] Error: Missing permissions to send in channel {channel.name}")
    
    def _cleanup_old_boosts(self):
        """Remove old entries from the cooldown cache."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=5)
        
        # Create list of keys to remove (avoid modifying dict during iteration)
        to_remove = [
            uid for uid, timestamp in self.recent_boosts.items()
            if timestamp < cutoff
        ]
        
        for uid in to_remove:
            del self.recent_boosts[uid]
    
    # ─────────────────────────────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def boosters(self, ctx: commands.Context):
        """List all current server boosters."""
        boosters = [m for m in ctx.guild.members if m.premium_since is not None]
        
        if not boosters:
            return await ctx.reply("No boosters yet! 💔")
        
        # Sort by boost date
        boosters.sort(key=lambda m: m.premium_since)
        
        embed = discord.Embed(
            title="💎 Server Boosters",
            description=f"**{len(boosters)}** amazing members boosting this server!",
            color=discord.Color.nitro_pink()
        )
        
        booster_list = []
        for i, member in enumerate(boosters[:25], 1):  # Limit to 25
            days_boosting = (datetime.now(member.premium_since.tzinfo) - member.premium_since).days
            booster_list.append(f"**{i}.** {member.mention} — {days_boosting} days")
        
        embed.add_field(
            name="Boosters",
            value="\n".join(booster_list) or "None",
            inline=False
        )
        
        if len(boosters) > 25:
            embed.set_footer(text=f"Showing 25 of {len(boosters)} boosters")
        
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    """Load the Boost Tracker cog."""
    await bot.add_cog(BoostCog(bot))
