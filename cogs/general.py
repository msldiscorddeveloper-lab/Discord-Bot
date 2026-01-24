import discord
import sqlite3
import datetime
from random import randint
from discord.ext import commands, tasks
from discord.ui import Select, View

class EventSelect(Select):
  def __init__(self):
    # Define your 3 options here
    options = [
        discord.SelectOption(label="Regular", emoji="❓", description="kek"),
        discord.SelectOption(label="Partner Led", emoji="✨", description="lol"),
        discord.SelectOption(label="Programs", emoji="⚔️", description="rotfl")
    ]
    # The placeholder is the text shown before clicking
    super().__init__(placeholder="Select an event type...", max_values=1, min_values=1, options=options)

  async def callback(self, interaction: discord.Interaction):
    # This runs when the user selects an option
    choice = self.values[0]
    
    # You can add logic here later to actually START the event
    await interaction.response.send_message(f"✅ **{choice}** selected! (Functionality coming soon)", ephemeral=True)

class EventView(View):
  def __init__(self):
    super().__init__()
    # Add the dropdown to the view
    self.add_item(EventSelect())

class General(commands.Cog):
  def __init__(self, bot):
    self.bot = bot
    self.cycle_speed = 30

    self.user_msg_xp_cache = {}
    self.daily_cap_cache = {}

    self.gained_msg_xp = set()
    self.pending_xp = {}

    self.bot_channel_ids = {
      1462845640663892090
    }

    self.db = sqlite3.connect('levels.db')
    self.cursor = self.db.cursor()
    self.cursor.execute('''
      CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        xp INTEGER
      )
    ''')
    self.db.commit()

    self.batch_update_db.start()
  
  def cog_unload(self):
    self.batch_update_db.cancel()
    self.db.close()

  @tasks.loop(seconds=10)
  async def batch_update_db(self):
    print('CYCLE')
    self.gained_msg_xp.clear()

    if len(self.user_msg_xp_cache) > 10000:
      self.user_msg_xp_cache.clear()

    if self.bot.guilds:
      guild = self.bot.guilds[0]

      afk_channel = guild.afk_channel

      for vc in guild.voice_channels:
        if afk_channel and vc.id == afk_channel.id:
          continue

        valid_members = [
          member for member in vc.members
          if not member.bot
          and not member.voice.mute
          and not member.voice.self_mute
          and not member.voice.deaf
          and not member.voice.self_deaf
          and not member.voice.suppress
        ]

        if len(valid_members) >= 2:
          for member in valid_members:
            user_id = member.id
            self.pending_xp[user_id] = self.pending_xp.get(user_id, 0) + 2

    if not self.pending_xp:
      return
  
    print(f'saving data for {len(self.pending_xp)} users...')

    data = self.pending_xp.copy()
    self.pending_xp.clear()

    for uid, xp in data.items():
      self.cursor.execute('''
        INSERT INTO users (user_id, xp) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET xp = xp + ?
      ''', (uid, xp, xp))
    
    self.db.commit()
    print('data saved successfully')
  
  @batch_update_db.before_loop
  async def before_batch_update(self):
    await self.bot.wait_until_ready()
  
  @commands.Cog.listener()
  async def on_reaction_add(self, reaction, user):
    if user.bot: return

    msg_id = reaction.message.id
    reactor_id = user.id
    today = str(datetime.date.today())

    user_daily_data = self.daily_cap_cache.get(reactor_id, {'date': today, 'xp': 0})

    if user_daily_data['date'] != today:
      user_daily_data = {'date': today, 'xp': 0}
    
    if user_daily_data['xp'] >= 100:
      return

    cache_key = (reactor_id, msg_id)
    current_earned_from_message = self.user_msg_xp_cache.get(cache_key, 0)

    if current_earned_from_message >= 50:
      return

    self.user_msg_xp_cache[cache_key] = current_earned_from_message + 5

    user_daily_data['xp'] += 5
    self.daily_cap_cache[reactor_id] = user_daily_data

    self.pending_xp[reactor_id] = self.pending_xp.get(reactor_id, 0) + 5
  
  @commands.Cog.listener()
  async def on_message(self, message):
    if message.author.bot: return
    if len(message.content)<10: return
    if message.channel.id in self.bot_channel_ids:
      return
    
    user_id = message.author.id

    if user_id not in self.gained_msg_xp:
      self.gained_msg_xp.add(user_id)
      self.pending_xp[user_id] = self.pending_xp.get(user_id, 0) + randint(10, 15)
  
  @commands.command()
  async def ping(self, ctx):
    await ctx.reply('Pong')
  
  @commands.command(aliases=['lb', 'top'])
  async def leaderboard(self, ctx):
    self.cursor.execute("SELECT user_id, xp FROM users ORDER BY xp DESC LIMIT 10")
    top_users = self.cursor.fetchall()

    embed = discord.Embed(title="🏆 Server Leaderboard", color=discord.Color.gold())

    description = ''
    for index, (user_id, xp) in enumerate(top_users, start=1):
      member = ctx.guild.get_member(user_id)

      if member:
        name = member.display_name
      else:
        name = f'User {user_id}'

      rank_str = f'**{index}.**'
    
      description += f'{rank_str} **{name}**  {xp:,} XP\n'

    embed.description = description
    embed.set_footer(text='keep chatting to climb ranks')

    await ctx.reply(embed=embed)
  
  @commands.command()
  @commands.has_permissions(administrator=True) # Only Admins can use this
  async def event(self, ctx):
    """Opens the Event Selection Menu"""
    await ctx.send("🎉 **Event Control Panel**\nPlease select an event type below:", view=EventView())

async def setup(bot):
  await bot.add_cog(General(bot))