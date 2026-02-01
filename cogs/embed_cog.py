"""
Embeds Cog - Discohook Embed Manager with Scheduling
Allows admins to send and schedule embeds from Discohook links.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import base64
import random
import string
import datetime
import logging
from urllib.parse import urlparse, parse_qs

from services.database import db
from utils.constants import TZ_MANILA
from utils.views import CancelScheduledEmbedView

logger = logging.getLogger('mlbb_bot')


def generate_identifier(length=6):
    """Generate a random identifier for scheduled embeds."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def discohook_to_view(components_data):
    """Convert Discohook component data to a discord.ui.View."""
    if not components_data:
        return None
    
    view = discord.ui.View(timeout=None)
    
    for row in components_data:
        for comp in row.get("components", []):
            comp_type = comp.get("type")
            
            if comp_type == 2:  # Button
                style = comp.get("style", 1)
                label = comp.get("label")
                url = comp.get("url")
                disabled = comp.get("disabled", False)
                emoji = comp.get("emoji", {}).get("name") if comp.get("emoji") else None
                
                if style == 5 and url:  # Link button
                    view.add_item(discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        label=label,
                        url=url,
                        emoji=emoji,
                        disabled=disabled
                    ))
                else:
                    view.add_item(discord.ui.Button(
                        style=discord.ButtonStyle(style),
                        label=label,
                        custom_id=comp.get("custom_id"),
                        emoji=emoji,
                        disabled=disabled
                    ))
            
            elif comp_type == 3:  # Select Menu
                options = [
                    discord.SelectOption(
                        label=o["label"],
                        value=o["value"],
                        description=o.get("description"),
                        emoji=o.get("emoji", {}).get("name") if o.get("emoji") else None,
                        default=o.get("default", False)
                    )
                    for o in comp.get("options", [])
                ]
                view.add_item(discord.ui.Select(
                    custom_id=comp.get("custom_id"),
                    placeholder=comp.get("placeholder"),
                    min_values=1,
                    max_values=1,
                    options=options,
                    disabled=comp.get("disabled", False)
                ))
    
    return view if len(view.children) > 0 else None


class EmbedsCog(commands.Cog, name="Embeds"):
    """Discohook embed manager with scheduling capabilities."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.schedule_loop.start()
    
    def cog_unload(self):
        self.schedule_loop.cancel()
    
    # ─────────────────────────────────────────────────────────────────────
    # Background Task: Send Scheduled Embeds
    # ─────────────────────────────────────────────────────────────────────
    
    @tasks.loop(minutes=1)
    async def schedule_loop(self):
        """Check and send pending scheduled embeds."""
        query = """
            SELECT identifier, channel_id, user_id, content, embed_json 
            FROM scheduled_embeds 
            WHERE status = 'pending' AND schedule_for <= NOW()
        """
        rows = await db.fetch_all(query)
        
        for row in rows:
            try:
                channel = self.bot.get_channel(row['channel_id'])
                if not channel:
                    channel = await self.bot.fetch_channel(row['channel_id'])
                
                data = json.loads(row['embed_json'])
                embeds = [discord.Embed.from_dict(e) for e in data.get("embeds", [])]
                view = discohook_to_view(data.get("components", []))
                content = row['content']
                
                await channel.send(content=content, embeds=embeds, view=view)
                
                # Mark as sent
                await db.execute(
                    "UPDATE scheduled_embeds SET status = 'sent' WHERE identifier = %s",
                    (row['identifier'],)
                )
                
                # Log success
                log_row = await db.fetch_one(
                    "SELECT embed_log_channel_id FROM guild_settings WHERE guild_id = %s",
                    (channel.guild.id,)
                )
                if log_row and log_row.get('embed_log_channel_id'):
                    log_channel = self.bot.get_channel(log_row['embed_log_channel_id'])
                    if log_channel:
                        embed = discord.Embed(
                            title="✅ Scheduled Embed Sent",
                            color=0x00FF00,
                            timestamp=datetime.datetime.now(TZ_MANILA)
                        )
                        embed.add_field(name="Identifier", value=row['identifier'])
                        embed.add_field(name="Channel", value=channel.mention)
                        embed.add_field(name="Scheduled By", value=f"<@{row['user_id']}>")
                        await log_channel.send(embed=embed)
            
            except Exception as e:
                logger.error(f"Failed to send scheduled embed {row['identifier']}: {e}")
                await db.execute(
                    "UPDATE scheduled_embeds SET status = 'failed' WHERE identifier = %s",
                    (row['identifier'],)
                )
    
    @schedule_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
    
    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    
    async def _process_link(self, link: str):
        """Parse a Discohook share link and extract embed data."""
        try:
            parsed = urlparse(link)
            qs = parse_qs(parsed.query)
            encoded = qs.get("data", [None])[0]
            
            if not encoded:
                return None
            
            # Add padding if needed
            missing = len(encoded) % 4
            if missing:
                encoded += "=" * (4 - missing)
            
            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
            data = json.loads(decoded)
            
            # Discohook format: messages[0].data
            msg_data = data["messages"][0]["data"]
            return msg_data
        
        except Exception as e:
            logger.error(f"Link parse error: {e}")
            return None
    
    # ─────────────────────────────────────────────────────────────────────
    # Slash Commands
    # ─────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="send_embed", description="Send an embed from a Discohook link")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel to send the embed to",
        link="Discohook share link",
        schedule_minutes="Minutes from now to send (0 = immediate)"
    )
    async def send_embed(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        link: str,
        schedule_minutes: int = 0
    ):
        """Send or schedule an embed from a Discohook link."""
        data = await self._process_link(link)
        
        if not data:
            await interaction.response.send_message("❌ Invalid Discohook link.", ephemeral=True)
            return
        
        content = data.get("content", "")
        embeds_list = data.get("embeds", [])
        components_list = data.get("components", [])
        
        if schedule_minutes > 0:
            # Schedule for later
            schedule_time = datetime.datetime.now() + datetime.timedelta(minutes=schedule_minutes)
            identifier = generate_identifier()
            full_json = json.dumps({"embeds": embeds_list, "components": components_list})
            
            await db.execute(
                """INSERT INTO scheduled_embeds 
                   (identifier, channel_id, user_id, content, embed_json, schedule_for, status) 
                   VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
                (identifier, channel.id, interaction.user.id, content, full_json, schedule_time)
            )
            
            await interaction.response.send_message(
                f"✅ Embed scheduled for <t:{int(schedule_time.timestamp())}:R> (ID: `{identifier}`)",
                ephemeral=True
            )
        else:
            # Send immediately
            embeds = [discord.Embed.from_dict(e) for e in embeds_list]
            view = discohook_to_view(components_list)
            await channel.send(content=content, embeds=embeds, view=view)
            await interaction.response.send_message(f"✅ Embed sent to {channel.mention}!", ephemeral=True)
    
    @app_commands.command(name="cancel_embed", description="Cancel a scheduled embed")
    @app_commands.default_permissions(administrator=True)
    async def cancel_embed(self, interaction: discord.Interaction):
        """Cancel a pending scheduled embed."""
        rows = await db.fetch_all(
            "SELECT identifier, schedule_for FROM scheduled_embeds WHERE user_id = %s AND status = 'pending'",
            (interaction.user.id,)
        )
        
        if not rows:
            await interaction.response.send_message("❌ You have no pending scheduled embeds.", ephemeral=True)
            return
        
        view = CancelScheduledEmbedView(rows, self, interaction.user)
        await interaction.response.send_message("Select an embed to cancel:", view=view, ephemeral=True)
    
    async def cancel_scheduled_embed_action(self, interaction: discord.Interaction, identifier: str):
        """Actually cancel the embed (called from the view)."""
        await db.execute("DELETE FROM scheduled_embeds WHERE identifier = %s", (identifier,))
        await interaction.response.send_message(f"✅ Cancelled scheduled embed `{identifier}`.", ephemeral=True)
    
    @app_commands.command(name="set_embed_log", description="Set the channel for scheduled embed logs")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="Channel for embed logs")
    async def set_embed_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Configure where scheduled embed logs are sent."""
        await db.execute(
            """INSERT INTO guild_settings (guild_id, embed_log_channel_id) 
               VALUES (%s, %s) 
               ON DUPLICATE KEY UPDATE embed_log_channel_id = VALUES(embed_log_channel_id)""",
            (interaction.guild.id, channel.id)
        )
        await interaction.response.send_message(
            f"✅ Scheduled embed logs will be sent to {channel.mention}.",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedsCog(bot))
