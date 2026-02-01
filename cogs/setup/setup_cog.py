"""
Setup Cog - Admin slash commands to configure bot settings.
All commands are slash commands under /setup group.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal

from services.settings_service import settings_service


class SetupCog(commands.Cog, name="Setup"):
    """Admin slash commands for bot configuration."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    setup_group = app_commands.Group(name="setup", description="Configure bot settings", default_permissions=discord.Permissions(administrator=True))
    
    # ─────────────────────────────────────────────────────────────────────
    # View Settings
    # ─────────────────────────────────────────────────────────────────────
    
    @setup_group.command(name="view", description="View all current bot settings")
    async def setup_view(self, inter: discord.Interaction):
        """View current bot settings."""
        settings = await settings_service.get_all()
        
        embed = discord.Embed(title="⚙️ Bot Settings", color=discord.Color.blue())
        
        # Channels
        channels = [
            ("Bot Channel", settings.get("bot_channel_id", "0")),
            ("Boost Announce", settings.get("boost_announce_channel_id", "0")),
            ("Booster Chat", settings.get("booster_chat_channel_id", "0")),
            ("Booster Lounge VC", settings.get("booster_lounge_vc_id", "0")),
            ("Mod Log", settings.get("mod_log_channel_id", "0")),
        ]
        channel_text = "\n".join([
            f"**{name}:** <#{cid}>" if cid != "0" else f"**{name}:** Not set"
            for name, cid in channels
        ])
        embed.add_field(name="📢 Channels", value=channel_text, inline=False)
        
        # Roles
        roles = [
            ("Server Booster", settings.get("server_booster_role_id", "0")),
            ("Veteran Booster", settings.get("veteran_booster_role_id", "0")),
            ("Mythic Booster", settings.get("mythic_booster_role_id", "0")),
            ("Spotlight", settings.get("booster_spotlight_role_id", "0")),
            ("Verified", settings.get("verified_role_id", "0")),
        ]
        role_text = "\n".join([
            f"**{name}:** <@&{rid}>" if rid != "0" else f"**{name}:** Not set"
            for name, rid in roles
        ])
        embed.add_field(name="🎭 Roles", value=role_text, inline=False)
        
        # Moderation Roles
        mod_roles = [
            ("Muted", settings.get("muted_role_id", "0")),
            ("Restricted", settings.get("restricted_role_id", "0")),
        ]
        mod_role_text = "\n".join([
            f"**{name}:** <@&{rid}>" if rid != "0" else f"**{name}:** Not set"
            for name, rid in mod_roles
        ])
        embed.add_field(name="🛡️ Moderation Roles", value=mod_role_text, inline=False)
        
        # Cosmetics count
        color_roles = await settings_service.get_color_roles()
        emblem_roles = await settings_service.get_emblem_roles()
        embed.add_field(
            name="🎨 Cosmetics",
            value=f"**Color Roles:** {len(color_roles)}\n**Emblem Roles:** {len(emblem_roles)}",
            inline=False
        )
        
        await inter.response.send_message(embed=embed, ephemeral=True)
    
    # ─────────────────────────────────────────────────────────────────────
    # Channel Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup_group.command(name="channel", description="Set a text channel")
    @app_commands.describe(
        setting="Which channel setting to configure",
        channel="The channel to set"
    )
    async def setup_channel(
        self, 
        inter: discord.Interaction, 
        setting: Literal["bot", "announce", "booster_chat", "modlog"],
        channel: discord.TextChannel
    ):
        key_map = {
            "bot": "bot_channel_id",
            "announce": "boost_announce_channel_id",
            "booster_chat": "booster_chat_channel_id",
            "modlog": "mod_log_channel_id",
        }
        await settings_service.set(key_map[setting], str(channel.id))
        await inter.response.send_message(f"✅ **{setting}** channel set to {channel.mention}", ephemeral=True)
    
    @setup_group.command(name="vc", description="Set the booster lounge voice channel")
    async def setup_vc(self, inter: discord.Interaction, channel: discord.VoiceChannel):
        await settings_service.set("booster_lounge_vc_id", str(channel.id))
        await inter.response.send_message(f"✅ Booster Lounge VC set to **{channel.name}**", ephemeral=True)
    
    # ─────────────────────────────────────────────────────────────────────
    # Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup_group.command(name="role", description="Set a role")
    @app_commands.describe(
        setting="Which role setting to configure",
        role="The role to set"
    )
    async def setup_role(
        self, 
        inter: discord.Interaction, 
        setting: Literal["server", "veteran", "mythic", "spotlight", "muted", "restricted"],
        role: discord.Role
    ):
        key_map = {
            "server": "server_booster_role_id",
            "veteran": "veteran_booster_role_id",
            "mythic": "mythic_booster_role_id",
            "spotlight": "booster_spotlight_role_id",
            "muted": "muted_role_id",
            "restricted": "restricted_role_id",
        }
        await settings_service.set(key_map[setting], str(role.id))
        await inter.response.send_message(f"✅ **{setting}** role set to {role.mention}", ephemeral=True)
    
    # ─────────────────────────────────────────────────────────────────────
    # Color Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup_group.command(name="color-add", description="Add a booster color role")
    async def setup_color_add(self, inter: discord.Interaction, name: str, role: discord.Role):
        await settings_service.set_color_role(name, role.id)
        await inter.response.send_message(f"✅ Added color **{name}** → {role.mention}", ephemeral=True)
    
    @setup_group.command(name="color-remove", description="Remove a booster color role")
    async def setup_color_remove(self, inter: discord.Interaction, name: str):
        await settings_service.remove_color_role(name)
        await inter.response.send_message(f"✅ Removed color **{name}**", ephemeral=True)
    
    @setup_group.command(name="color-list", description="List all booster color roles")
    async def setup_color_list(self, inter: discord.Interaction):
        colors = await settings_service.get_color_roles()
        if not colors:
            return await inter.response.send_message("No color roles configured.", ephemeral=True)
        
        lines = [f"**{n}:** <@&{rid}>" for n, rid in colors.items()]
        embed = discord.Embed(
            title="🎨 Color Roles",
            description="\n".join(lines),
            color=discord.Color.purple()
        )
        await inter.response.send_message(embed=embed, ephemeral=True)
    
    # ─────────────────────────────────────────────────────────────────────
    # Emblem Role Setup
    # ─────────────────────────────────────────────────────────────────────
    
    @setup_group.command(name="emblem-add", description="Add a booster emblem role")
    async def setup_emblem_add(self, inter: discord.Interaction, emoji: str, role: discord.Role):
        await settings_service.set_emblem_role(emoji, role.id)
        await inter.response.send_message(f"✅ Added emblem {emoji} → {role.mention}", ephemeral=True)
    
    @setup_group.command(name="emblem-remove", description="Remove a booster emblem role")
    async def setup_emblem_remove(self, inter: discord.Interaction, emoji: str):
        emblems = await settings_service.get_emblem_roles()
        emblems.pop(emoji, None)
        import json
        await settings_service.set("booster_emblem_roles", json.dumps(emblems))
        await inter.response.send_message(f"✅ Removed emblem {emoji}", ephemeral=True)
    
    @setup_group.command(name="emblem-list", description="List all booster emblem roles")
    async def setup_emblem_list(self, inter: discord.Interaction):
        emblems = await settings_service.get_emblem_roles()
        if not emblems:
            return await inter.response.send_message("No emblem roles configured.", ephemeral=True)
        
        lines = [f"{e} → <@&{rid}>" for e, rid in emblems.items()]
        embed = discord.Embed(
            title="⚜️ Emblem Roles",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
