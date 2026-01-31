"""
Moderation Cog - Visual moderation with slash commands and audit logging.
Includes /history, /warn (XP lock), /mute, /restrict, /ban (economy wipe).
"""

import discord
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands

from services.mod_service import mod_service
from services.database import db
from services.settings_service import settings_service


class ModCog(commands.Cog, name="Moderation"):
    """Visual moderation system with full audit logging."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ─────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────
    
    async def _notify_user(self, user: discord.Member, action: str, reason: str, guild_name: str):
        """DM the user about the moderation action."""
        try:
            embed = discord.Embed(
                title=f"You have been {action}",
                description=f"**Server:** {guild_name}\n**Reason:** {reason or 'No reason provided'}",
                color=discord.Color.red()
            )
            await user.send(embed=embed)
            return True
        except discord.Forbidden:
            return False
    
    async def _log_to_channel(self, guild: discord.Guild, embed: discord.Embed):
        """Log action to the mod log channel."""
        channel_id = await settings_service.get_int("mod_log_channel_id")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass
    
    def _parse_duration(self, duration_str: str) -> timedelta | None:
        """Parse duration string: 1m, 1h, 1d, 1w, perm"""
        if not duration_str or duration_str.lower() == "perm":
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
    
    def _get_action_icon(self, action: str) -> str:
        """Get visual icon for action type."""
        icons = {
            "warn": "⚠️",
            "mute": "🔇",
            "unmute": "🔊",
            "ban": "🚫",
            "unban": "✅",
            "kick": "👢",
            "restrict": "🔒",
            "unrestrict": "🔓",
        }
        return icons.get(action.lower(), "📋")
    
    def _get_action_color(self, action: str) -> discord.Color:
        """Get color for action type."""
        colors = {
            "warn": discord.Color.yellow(),
            "mute": discord.Color.red(),
            "unmute": discord.Color.green(),
            "ban": discord.Color.dark_red(),
            "unban": discord.Color.green(),
            "kick": discord.Color.orange(),
            "restrict": discord.Color.orange(),
            "unrestrict": discord.Color.green(),
        }
        return colors.get(action.lower(), discord.Color.greyple())
    
    async def _check_hierarchy(self, inter: discord.Interaction, target: discord.Member) -> bool:
        """Check if action is allowed based on role hierarchy."""
        if target.top_role >= inter.user.top_role:
            await inter.response.send_message("❌ Cannot target someone with equal or higher role.", ephemeral=True)
            return False
        if target.top_role >= inter.guild.me.top_role:
            await inter.response.send_message("❌ Target's role is higher than mine.", ephemeral=True)
            return False
        return True
    
    async def _apply_xp_lock(self, user_id: int, hours: int = 24):
        """Apply XP/Token lock to user."""
        lock_until = datetime.now() + timedelta(hours=hours)
        await db.execute('''
            INSERT INTO users (user_id, xp_locked, xp_lock_until) VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET xp_locked = 1, xp_lock_until = ?
        ''', (user_id, lock_until.isoformat(), lock_until.isoformat()))
    
    async def _wipe_economy(self, user_id: int):
        """Wipe all economy data for a user (perm ban)."""
        await db.execute('''
            UPDATE users SET 
                xp = 0, tokens = 0, xp_multiplier = 1.0, token_multiplier = 1.0,
                shop_discount = 0.0, raffle_entries = 0, pouches_today = 0
            WHERE user_id = ?
        ''', (user_id,))
    
    # ─────────────────────────────────────────────────────────────────────
    # Slash Commands
    # ─────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="history", description="View a user's moderation history (Rap Sheet)")
    @app_commands.default_permissions(moderate_members=True)
    async def history(self, inter: discord.Interaction, user: discord.Member):
        """Display visual moderation history."""
        history = await mod_service.get_user_history(user.id, limit=10)
        
        embed = discord.Embed(
            title=f"📋 Moderation History",
            description=f"**User:** {user.mention} ({user.id})\n**Total Infractions:** {len(history)}",
            color=discord.Color.dark_embed()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if not history:
            embed.add_field(name="Record", value="✨ Clean record!", inline=False)
        else:
            lines = []
            for entry in history:
                icon = self._get_action_icon(entry['action_type'])
                action = entry['action_type'].upper()
                mod_id = entry['moderator_id']
                reason = entry['reason'] or "No reason"
                timestamp = entry['timestamp'][:10] if entry['timestamp'] else "Unknown"
                
                lines.append(f"{icon} **{action}** | <@{mod_id}> | {timestamp}\n└ {reason[:50]}")
            
            embed.add_field(name="Last 10 Actions", value="\n\n".join(lines[:5]), inline=False)
            if len(lines) > 5:
                embed.add_field(name="​", value="\n\n".join(lines[5:]), inline=False)
        
        # Add current status
        status_parts = []
        if user.is_timed_out():
            status_parts.append("🔇 **Muted**")
        
        result = await db.fetch_one('SELECT xp_locked, is_restricted FROM users WHERE user_id = ?', (user.id,))
        if result:
            if result['xp_locked']:
                status_parts.append("⛔ **XP Locked**")
            if result['is_restricted']:
                status_parts.append("🔒 **Restricted**")
        
        if status_parts:
            embed.add_field(name="Current Status", value=" | ".join(status_parts), inline=False)
        
        await inter.response.send_message(embed=embed)
    
    @app_commands.command(name="warn", description="Issue a formal warning (applies 24h XP lock)")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, inter: discord.Interaction, user: discord.Member, reason: str):
        """Warn user with 24h XP/Token lock."""
        # Log action
        await mod_service.log_action("warn", inter.user.id, user.id, reason)
        
        # Apply 24h XP lock
        await self._apply_xp_lock(user.id, 24)
        
        # DM user
        dm_sent = await self._notify_user(user, "warned", reason, inter.guild.name)
        
        # Get warning count
        warn_count = await mod_service.get_action_count(user.id, "warn")
        
        embed = discord.Embed(
            title="⚠️ Warning Issued",
            color=discord.Color.yellow()
        )
        embed.add_field(name="User", value=f"{user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"{inter.user.mention}", inline=True)
        embed.add_field(name="Total Warnings", value=str(warn_count), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Penalty", value="24h XP/Token Lock Applied", inline=False)
        embed.set_footer(text="DM sent" if dm_sent else "DM failed (user has DMs closed)")
        
        await inter.response.send_message(embed=embed)
        await self._log_to_channel(inter.guild, embed)
    
    @app_commands.command(name="mute", description="Timeout a user")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, inter: discord.Interaction, user: discord.Member, duration: str, reason: str = None):
        """Mute user using Discord timeout."""
        if not await self._check_hierarchy(inter, user):
            return
        
        timeout_duration = self._parse_duration(duration)
        if not timeout_duration:
            return await inter.response.send_message("❌ Invalid duration. Use: `1m`, `1h`, `1d`, `1w`", ephemeral=True)
        
        if timeout_duration.days > 28:
            return await inter.response.send_message("❌ Max timeout is 28 days.", ephemeral=True)
        
        await self._notify_user(user, f"muted for {duration}", reason, inter.guild.name)
        await user.timeout(timeout_duration, reason=reason)
        await mod_service.log_action("mute", inter.user.id, user.id, f"{duration}: {reason or 'No reason'}")
        
        embed = discord.Embed(title="🔇 User Muted", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Moderator", value=inter.user.mention, inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        await inter.response.send_message(embed=embed)
        await self._log_to_channel(inter.guild, embed)
    
    @app_commands.command(name="restrict", description="Restrict user (remove verified, block images)")
    @app_commands.default_permissions(moderate_members=True)
    async def restrict(self, inter: discord.Interaction, user: discord.Member, duration: str, reason: str = None):
        """Restrict user - removes verified role, blocks shop access."""
        if not await self._check_hierarchy(inter, user):
            return
        
        # Mark as restricted in DB
        await db.execute('''
            INSERT INTO users (user_id, is_restricted) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET is_restricted = 1
        ''', (user.id,))
        
        # Remove verified role if configured
        verified_role_id = await settings_service.get_int("verified_role_id")
        if verified_role_id:
            verified_role = inter.guild.get_role(verified_role_id)
            if verified_role and verified_role in user.roles:
                await user.remove_roles(verified_role, reason="Restricted")
        
        await mod_service.log_action("restrict", inter.user.id, user.id, f"{duration}: {reason or 'No reason'}")
        await self._notify_user(user, "restricted", reason, inter.guild.name)
        
        embed = discord.Embed(title="🔒 User Restricted", color=discord.Color.orange())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Moderator", value=inter.user.mention, inline=True)
        embed.add_field(name="Effects", value="• Verified status removed\n• Shop access blocked\n• Cannot send images/embeds", inline=False)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        await inter.response.send_message(embed=embed)
        await self._log_to_channel(inter.guild, embed)
    
    @app_commands.command(name="unrestrict", description="Remove restriction from user")
    @app_commands.default_permissions(moderate_members=True)
    async def unrestrict(self, inter: discord.Interaction, user: discord.Member):
        """Remove restriction from user."""
        await db.execute('UPDATE users SET is_restricted = 0 WHERE user_id = ?', (user.id,))
        
        # Restore verified role
        verified_role_id = await settings_service.get_int("verified_role_id")
        if verified_role_id:
            verified_role = inter.guild.get_role(verified_role_id)
            if verified_role:
                await user.add_roles(verified_role, reason="Unrestricted")
        
        await mod_service.log_action("unrestrict", inter.user.id, user.id, None)
        
        await inter.response.send_message(f"🔓 **{user.display_name}** has been unrestricted.")
        
    @app_commands.command(name="ban", description="Ban a user (perm wipes economy)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, inter: discord.Interaction, user: discord.Member, duration: str = "perm", reason: str = None):
        """Ban user. Duration 'perm' wipes economy data."""
        if not await self._check_hierarchy(inter, user):
            return
        
        is_perm = duration.lower() == "perm"
        
        # DM before ban
        await self._notify_user(user, "banned" + (" permanently" if is_perm else f" for {duration}"), reason, inter.guild.name)
        
        # Wipe economy on perm ban
        if is_perm:
            await self._wipe_economy(user.id)
        
        await user.ban(reason=reason, delete_message_days=0)
        await mod_service.log_action("ban", inter.user.id, user.id, f"{'PERM' if is_perm else duration}: {reason or 'No reason'}")
        
        embed = discord.Embed(
            title="🚫 User Banned",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        embed.add_field(name="Duration", value="Permanent" if is_perm else duration, inline=True)
        embed.add_field(name="Moderator", value=inter.user.mention, inline=True)
        if is_perm:
            embed.add_field(name="Economy", value="⚠️ All data wiped", inline=False)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        await inter.response.send_message(embed=embed)
        await self._log_to_channel(inter.guild, embed)
    
    # ─────────────────────────────────────────────────────────────────────
    # Text Commands (Legacy Support)
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Kick a member from the server."""
        if member.top_role >= ctx.author.top_role:
            return await ctx.reply("❌ Cannot kick someone with equal or higher role.")
        
        await self._notify_user(member, "kicked", reason, ctx.guild.name)
        await member.kick(reason=reason)
        await mod_service.log_action("kick", ctx.author.id, member.id, reason)
        
        embed = discord.Embed(title="👢 User Kicked", color=discord.Color.orange())
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        await ctx.reply(embed=embed)
    
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = None):
        """Unban a user by their ID."""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            await mod_service.log_action("unban", ctx.author.id, user_id, reason)
            await ctx.reply(f"✅ **{user}** has been unbanned.")
        except discord.NotFound:
            await ctx.reply("❌ User not found or not banned.")
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Remove timeout from a member."""
        if not member.is_timed_out():
            return await ctx.reply("❌ This member is not muted.")
        
        await member.timeout(None, reason=reason)
        await mod_service.log_action("unmute", ctx.author.id, member.id, reason)
        await ctx.reply(f"🔊 **{member.display_name}** has been unmuted.")
    
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def modlog(self, ctx: commands.Context, member: discord.Member):
        """View a member's moderation history (alias for /history)."""
        history = await mod_service.get_user_history(member.id, limit=10)
        
        embed = discord.Embed(
            title=f"📋 Mod History: {member.display_name}",
            color=discord.Color.dark_embed()
        )
        
        if not history:
            embed.description = "✨ Clean record!"
        else:
            lines = []
            for entry in history:
                icon = self._get_action_icon(entry['action_type'])
                lines.append(f"{icon} **{entry['action_type'].upper()}** - <@{entry['moderator_id']}>\n└ {entry['reason'] or 'No reason'}")
            embed.description = "\n\n".join(lines)
        
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCog(bot))
