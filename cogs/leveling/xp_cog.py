"""
XP/Leveling Cog - Handles XP gain from messages, reactions, and voice.
All commands are slash commands.
"""

import discord
import datetime
from random import randint
from discord.ext import commands, tasks
from discord import app_commands

from config import XP_CONFIG, BATCH_UPDATE_INTERVAL
from services.xp_service import xp_service
from services.settings_service import settings_service
from utils.embeds import create_leaderboard_embed, create_rank_embed


class XpCog(commands.Cog, name="Leveling"):
    """XP and Leveling system for the server."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Spam prevention caches
        self.gained_msg_xp = set()
        self.pending_xp = {}
        
        # Reaction XP tracking
        self.message_reaction_xp = {}
        self.user_reacted_to_message = set()
        self.daily_reaction_cache = {}
        
        # Start background task
        self.batch_update_db.start()
    
    def cog_unload(self):
        self.batch_update_db.cancel()
    
    # ─────────────────────────────────────────────────────────────────────
    # Background Task - Batch XP Updates
    # ─────────────────────────────────────────────────────────────────────
    
    @tasks.loop(seconds=BATCH_UPDATE_INTERVAL)
    async def batch_update_db(self):
        """Process pending XP and award voice XP."""
        self.gained_msg_xp.clear()
        
        # Clear large caches
        if len(self.message_reaction_xp) > 10000:
            self.message_reaction_xp.clear()
        if len(self.user_reacted_to_message) > 50000:
            self.user_reacted_to_message.clear()
        
        await self._process_voice_xp()
        
        if self.pending_xp:
            await xp_service.batch_update(self.pending_xp.copy())
            self.pending_xp.clear()
    
    @batch_update_db.before_loop
    async def before_batch_update(self):
        await self.bot.wait_until_ready()
    
    async def _process_voice_xp(self):
        """Award XP to active voice channel participants."""
        if not self.bot.guilds:
            return
        
        guild = self.bot.guilds[0]
        afk_channel = guild.afk_channel
        voice_config = XP_CONFIG["voice"]
        
        for vc in guild.voice_channels:
            if afk_channel and vc.id == afk_channel.id:
                continue
            
            valid_members = [
                m for m in vc.members
                if not m.bot
                and not m.voice.mute and not m.voice.self_mute
                and not m.voice.deaf and not m.voice.self_deaf
                and not m.voice.suppress
            ]
            
            if len(valid_members) >= voice_config["min_members"]:
                for member in valid_members:
                    self.pending_xp[member.id] = (
                        self.pending_xp.get(member.id, 0) + 
                        voice_config["xp_per_cycle"]
                    )
    
    # ─────────────────────────────────────────────────────────────────────
    # Event Listeners
    # ─────────────────────────────────────────────────────────────────────
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Award XP for messages (with spam prevention)."""
        if message.author.bot:
            return
        
        msg_config = XP_CONFIG["message"]
        
        if len(message.content) < msg_config["min_length"]:
            return
        
        # Ignore bot channel
        bot_channel_id = await settings_service.get_int("bot_channel_id")
        if message.channel.id == bot_channel_id:
            return
        
        user_id = message.author.id
        
        if user_id not in self.gained_msg_xp:
            self.gained_msg_xp.add(user_id)
            xp_amount = randint(msg_config["min_xp"], msg_config["max_xp"])
            self.pending_xp[user_id] = self.pending_xp.get(user_id, 0) + xp_amount
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Award XP for reactions with caps."""
        if user.bot:
            return
        
        react_config = XP_CONFIG["reaction"]
        msg_id = reaction.message.id
        user_id = user.id
        today = str(datetime.date.today())
        
        reaction_key = (user_id, msg_id)
        if reaction_key in self.user_reacted_to_message:
            return
        
        user_daily = self.daily_reaction_cache.get(user_id, {'date': today, 'xp': 0})
        if user_daily['date'] != today:
            user_daily = {'date': today, 'xp': 0}
        
        if user_daily['xp'] >= react_config["daily_cap"]:
            return
        
        msg_total_xp = self.message_reaction_xp.get(msg_id, 0)
        if msg_total_xp >= react_config["max_xp_per_message"]:
            return
        
        xp_amount = react_config["xp_per_reaction"]
        
        self.user_reacted_to_message.add(reaction_key)
        self.message_reaction_xp[msg_id] = msg_total_xp + xp_amount
        user_daily['xp'] += xp_amount
        self.daily_reaction_cache[user_id] = user_daily
        
        self.pending_xp[user_id] = self.pending_xp.get(user_id, 0) + xp_amount
    
    # ─────────────────────────────────────────────────────────────────────
    # Slash Commands
    # ─────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="leaderboard", description="Show the server XP leaderboard")
    async def leaderboard(self, inter: discord.Interaction):
        """Show the server XP leaderboard."""
        top_users = await xp_service.get_leaderboard(limit=10)
        embed = create_leaderboard_embed(inter.guild, top_users)
        await inter.response.send_message(embed=embed)
    
    @app_commands.command(name="rank", description="Show your or another user's rank")
    async def rank(self, inter: discord.Interaction, member: discord.Member = None):
        """Show your or another user's rank."""
        target = member or inter.user
        rank, xp = await xp_service.get_rank(target.id)
        embed = create_rank_embed(target, rank, xp)
        await inter.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(XpCog(bot))
