"""
Setup Cog - Admin commands to configure bot settings.
"""

import discord
from discord.ext import commands
from discord import app_commands

from services.settings_service import settings_service


class SetupCog(commands.Cog, name="Setup"):
    """Admin commands for bot configuration."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ─────────────────────────────────────────────────────────────────────
    # Channel Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def setup(self, ctx: commands.Context):
        """View current bot settings."""
        settings = await settings_service.get_all()
        
        embed = discord.Embed(title="⚙️ Bot Settings", color=discord.Color.blue())
        
        # Channels
        channels = [
            ("Bot Channel", settings.get("bot_channel_id", "0")),
            ("Boost Announce", settings.get("boost_announce_channel_id", "0")),
            ("Booster Chat", settings.get("booster_chat_channel_id", "0")),
            ("Booster Lounge VC", settings.get("booster_lounge_vc_id", "0")),
        ]
        channel_text = "\n".join([
            f"**{name}:** <#{cid}>" if cid != "0" else f"**{name}:** Not set"
            for name, cid in channels
        ])
        embed.add_field(name="📢 Channels", value=channel_text, inline=False)
        
        # Tier Roles
        roles = [
            ("Server Booster", settings.get("server_booster_role_id", "0")),
            ("Veteran Booster", settings.get("veteran_booster_role_id", "0")),
            ("Mythic Booster", settings.get("mythic_booster_role_id", "0")),
            ("Spotlight", settings.get("booster_spotlight_role_id", "0")),
        ]
        role_text = "\n".join([
            f"**{name}:** <@&{rid}>" if rid != "0" else f"**{name}:** Not set"
            for name, rid in roles
        ])
        embed.add_field(name="🎭 Roles", value=role_text, inline=False)
        
        # Color & Emblem counts
        color_roles = await settings_service.get_color_roles()
        emblem_roles = await settings_service.get_emblem_roles()
        embed.add_field(
            name="🎨 Cosmetics",
            value=f"**Color Roles:** {len(color_roles)}\n**Emblem Roles:** {len(emblem_roles)}",
            inline=False
        )
        
        embed.set_footer(text="Use !setup <setting> <value> to configure")
        await ctx.reply(embed=embed)
    
    @setup.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def setup_channel(self, ctx: commands.Context, setting: str, channel: discord.TextChannel):
        """Set a channel. Settings: bot, announce, booster_chat"""
        key_map = {
            "bot": "bot_channel_id",
            "announce": "boost_announce_channel_id",
            "booster_chat": "booster_chat_channel_id",
        }
        
        if setting not in key_map:
            return await ctx.reply(f"❌ Unknown setting. Use: {', '.join(key_map.keys())}")
        
        await settings_service.set(key_map[setting], str(channel.id))
        await ctx.reply(f"✅ **{setting}** channel set to {channel.mention}")
    
    @setup.command(name="vc")
    @commands.has_permissions(administrator=True)
    async def setup_vc(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Set the booster lounge VC."""
        await settings_service.set("booster_lounge_vc_id", str(channel.id))
        await ctx.reply(f"✅ Booster Lounge VC set to **{channel.name}**")
    
    # ─────────────────────────────────────────────────────────────────────
    # Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup.command(name="role")
    @commands.has_permissions(administrator=True)
    async def setup_role(self, ctx: commands.Context, setting: str, role: discord.Role):
        """Set a role. Settings: server, veteran, mythic, spotlight"""
        key_map = {
            "server": "server_booster_role_id",
            "veteran": "veteran_booster_role_id",
            "mythic": "mythic_booster_role_id",
            "spotlight": "booster_spotlight_role_id",
        }
        
        if setting not in key_map:
            return await ctx.reply(f"❌ Unknown setting. Use: {', '.join(key_map.keys())}")
        
        await settings_service.set(key_map[setting], str(role.id))
        await ctx.reply(f"✅ **{setting}** role set to {role.mention}")
    
    # ─────────────────────────────────────────────────────────────────────
    # Color Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup.command(name="color")
    @commands.has_permissions(administrator=True)
    async def setup_color(self, ctx: commands.Context, action: str, name: str = None, role: discord.Role = None):
        """Manage color roles. Actions: add, remove, list"""
        if action == "list":
            colors = await settings_service.get_color_roles()
            if not colors:
                return await ctx.reply("No color roles configured.")
            
            lines = [f"**{n}:** <@&{rid}>" for n, rid in colors.items()]
            embed = discord.Embed(
                title="🎨 Color Roles",
                description="\n".join(lines),
                color=discord.Color.purple()
            )
            return await ctx.reply(embed=embed)
        
        elif action == "add":
            if not name or not role:
                return await ctx.reply("❌ Usage: `!setup color add <name> @role`")
            await settings_service.set_color_role(name, role.id)
            await ctx.reply(f"✅ Added color **{name}** → {role.mention}")
        
        elif action == "remove":
            if not name:
                return await ctx.reply("❌ Usage: `!setup color remove <name>`")
            await settings_service.remove_color_role(name)
            await ctx.reply(f"✅ Removed color **{name}**")
        
        else:
            await ctx.reply("❌ Actions: `add`, `remove`, `list`")
    
    # ─────────────────────────────────────────────────────────────────────
    # Emblem Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup.command(name="emblem")
    @commands.has_permissions(administrator=True)
    async def setup_emblem(self, ctx: commands.Context, action: str, emoji: str = None, role: discord.Role = None):
        """Manage emblem roles. Actions: add, remove, list"""
        if action == "list":
            emblems = await settings_service.get_emblem_roles()
            if not emblems:
                return await ctx.reply("No emblem roles configured.")
            
            lines = [f"{e} → <@&{rid}>" for e, rid in emblems.items()]
            embed = discord.Embed(
                title="⚜️ Emblem Roles",
                description="\n".join(lines),
                color=discord.Color.gold()
            )
            return await ctx.reply(embed=embed)
        
        elif action == "add":
            if not emoji or not role:
                return await ctx.reply("❌ Usage: `!setup emblem add <emoji> @role`")
            await settings_service.set_emblem_role(emoji, role.id)
            await ctx.reply(f"✅ Added emblem {emoji} → {role.mention}")
        
        elif action == "remove":
            if not emoji:
                return await ctx.reply("❌ Usage: `!setup emblem remove <emoji>`")
            emblems = await settings_service.get_emblem_roles()
            emblems.pop(emoji, None)
            await settings_service.set("booster_emblem_roles", str(emblems))
            await ctx.reply(f"✅ Removed emblem {emoji}")
        
        else:
            await ctx.reply("❌ Actions: `add`, `remove`, `list`")


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
