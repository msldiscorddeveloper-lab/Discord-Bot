"""
Moderation Cog - Kick, Ban, Mute commands with logging.
Uses ModService for database operations.
"""

import discord
from datetime import timedelta
from discord.ext import commands

from services.mod_service import mod_service
from utils.embeds import create_mod_action_embed, create_modlog_embed


class ModCog(commands.Cog, name="Moderation"):
    """Server moderation commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ─────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────
    
    async def _notify_user(
        self, 
        user: discord.Member, 
        action: str, 
        reason: str, 
        guild_name: str
    ):
        """Attempt to DM the user about the moderation action."""
        try:
            embed = discord.Embed(
                title=f"You have been {action}",
                description=f"**Server:** {guild_name}\n**Reason:** {reason or 'No reason provided'}",
                color=discord.Color.red()
            )
            await user.send(embed=embed)
        except discord.Forbidden:
            pass  # Can't DM user
    
    def _parse_duration(self, duration_str: str) -> timedelta | None:
        """
        Parse duration string to timedelta.
        Supports: 1m, 1h, 1d, 1w (minutes, hours, days, weeks)
        """
        if not duration_str:
            return None
        
        try:
            unit = duration_str[-1].lower()
            amount = int(duration_str[:-1])
            
            if unit == 'm':
                return timedelta(minutes=amount)
            elif unit == 'h':
                return timedelta(hours=amount)
            elif unit == 'd':
                return timedelta(days=amount)
            elif unit == 'w':
                return timedelta(weeks=amount)
        except (ValueError, IndexError):
            return None
        
        return None
    
    # ─────────────────────────────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(
        self, 
        ctx: commands.Context, 
        member: discord.Member, 
        *, 
        reason: str = None
    ):
        """Kick a member from the server."""
        # Check hierarchy
        if member.top_role >= ctx.author.top_role:
            return await ctx.reply("❌ You cannot kick someone with an equal or higher role.")
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.reply("❌ I cannot kick someone with an equal or higher role than me.")
        
        # Notify user before kick
        await self._notify_user(member, "kicked", reason, ctx.guild.name)
        
        # Perform kick
        await member.kick(reason=reason)
        
        # Log action
        await mod_service.log_action("kick", ctx.author.id, member.id, reason)
        
        # Send confirmation
        embed = create_mod_action_embed("Kick", member, ctx.author, reason)
        await ctx.reply(embed=embed)
    
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(
        self, 
        ctx: commands.Context, 
        member: discord.Member, 
        *, 
        reason: str = None
    ):
        """Ban a member from the server."""
        # Check hierarchy
        if member.top_role >= ctx.author.top_role:
            return await ctx.reply("❌ You cannot ban someone with an equal or higher role.")
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.reply("❌ I cannot ban someone with an equal or higher role than me.")
        
        # Notify user before ban
        await self._notify_user(member, "banned", reason, ctx.guild.name)
        
        # Perform ban
        await member.ban(reason=reason, delete_message_days=0)
        
        # Log action
        await mod_service.log_action("ban", ctx.author.id, member.id, reason)
        
        # Send confirmation
        embed = create_mod_action_embed("Ban", member, ctx.author, reason)
        await ctx.reply(embed=embed)
    
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = None):
        """Unban a user by their ID."""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            
            # Log action
            await mod_service.log_action("unban", ctx.author.id, user_id, reason)
            
            await ctx.reply(f"✅ **{user}** has been unbanned.")
        except discord.NotFound:
            await ctx.reply("❌ User not found or not banned.")
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def mute(
        self, 
        ctx: commands.Context, 
        member: discord.Member, 
        duration: str, 
        *, 
        reason: str = None
    ):
        """
        Timeout a member using Discord's native timeout.
        Duration format: 1m, 1h, 1d, 1w (minutes, hours, days, weeks)
        """
        # Check hierarchy
        if member.top_role >= ctx.author.top_role:
            return await ctx.reply("❌ You cannot mute someone with an equal or higher role.")
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.reply("❌ I cannot mute someone with an equal or higher role than me.")
        
        # Parse duration
        timeout_duration = self._parse_duration(duration)
        if not timeout_duration:
            return await ctx.reply("❌ Invalid duration. Use format: `1m`, `1h`, `1d`, `1w`")
        
        # Max timeout is 28 days
        if timeout_duration.days > 28:
            return await ctx.reply("❌ Maximum timeout duration is 28 days.")
        
        # Notify user
        await self._notify_user(member, f"muted for {duration}", reason, ctx.guild.name)
        
        # Apply timeout
        await member.timeout(timeout_duration, reason=reason)
        
        # Log action
        await mod_service.log_action("mute", ctx.author.id, member.id, f"{duration}: {reason or 'No reason'}")
        
        # Send confirmation
        embed = create_mod_action_embed("Mute", member, ctx.author, reason, duration=duration)
        await ctx.reply(embed=embed)
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def unmute(
        self, 
        ctx: commands.Context, 
        member: discord.Member, 
        *, 
        reason: str = None
    ):
        """Remove timeout from a member."""
        if not member.is_timed_out():
            return await ctx.reply("❌ This member is not muted.")
        
        await member.timeout(None, reason=reason)
        
        # Log action
        await mod_service.log_action("unmute", ctx.author.id, member.id, reason)
        
        await ctx.reply(f"✅ **{member.display_name}** has been unmuted.")
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def warn(
        self, 
        ctx: commands.Context, 
        member: discord.Member, 
        *, 
        reason: str
    ):
        """Issue a warning to a member."""
        # Log action
        await mod_service.log_action("warn", ctx.author.id, member.id, reason)
        
        # Notify user
        await self._notify_user(member, "warned", reason, ctx.guild.name)
        
        # Get warning count
        warn_count = await mod_service.get_action_count(member.id, "warn")
        
        embed = create_mod_action_embed("Warning", member, ctx.author, reason)
        embed.add_field(name="Total Warnings", value=str(warn_count), inline=True)
        await ctx.reply(embed=embed)
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def modlog(self, ctx: commands.Context, member: discord.Member):
        """View a member's moderation history."""
        history = await mod_service.get_user_history(member.id, limit=10)
        embed = create_modlog_embed(member, history)
        await ctx.reply(embed=embed)
    
    # ─────────────────────────────────────────────────────────────────────
    # Error Handlers
    # ─────────────────────────────────────────────────────────────────────
    
    @kick.error
    @ban.error
    @mute.error
    @unmute.error
    @warn.error
    async def mod_error(self, ctx: commands.Context, error):
        """Handle moderation command errors."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You don't have permission to use this command.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ Member not found.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"❌ Missing required argument: `{error.param.name}`")
        else:
            await ctx.reply(f"❌ An error occurred: {error}")


async def setup(bot: commands.Bot):
    """Load the Moderation cog."""
    await bot.add_cog(ModCog(bot))
