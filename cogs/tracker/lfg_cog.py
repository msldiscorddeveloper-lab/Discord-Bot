import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Literal

from services.database import db
from services.settings_service import settings_service
from utils.checks import require_admin_auth

# ─────────────────────────────────────────────────────────────────
# Section 1 — Role-Mode Registry
# ─────────────────────────────────────────────────────────────────
LFG_ROLES = [
    # (settings_key,          button_label,   emoji, db_column,         button_row)
    ("lfg_role_ranked",       "Ranked",       "🏆",  "lfg_ranked",      0),
    ("lfg_role_classic",      "Classic",      "⚔️",  "lfg_classic",     0),
    ("lfg_role_brawl",        "Brawl",        "🥊",  "lfg_brawl",       0),
    ("lfg_role_mro",          "MRO",          "🤖",  "lfg_mro",         1),
    ("lfg_role_arcade",       "Arcade",       "🎮",  "lfg_arcade",      1),
    ("lfg_role_magic_chess",  "Magic Chess",  "♟️",  "lfg_magic_chess", 1),
]

# ─────────────────────────────────────────────────────────────────
# Section 2 — LFGRolesPanelView (Persistent Button Panel)
# ─────────────────────────────────────────────────────────────────
class LFGToggleButton(discord.ui.Button):
    def __init__(self, settings_key: str, label: str, emoji: str, db_column: str, row: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji,
            custom_id=f"lfg_toggle:{db_column}",
            row=row
        )
        self.settings_key = settings_key
        self.db_column = db_column
        self.role_name_display = label

    async def callback(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        
        role_id = await settings_service.get_int(self.settings_key)
        if role_id == 0:
            return await inter.followup.send("⚠️ LFG roles not configured. Ask an admin to run `/setup lfg-roles` first.", ephemeral=True)
            
        role = inter.guild.get_role(role_id)
        if not role:
            return await inter.followup.send(f"❌ The LFG role for **{self.role_name_display}** was deleted from the server.", ephemeral=True)
            
        if role >= inter.guild.me.top_role:
            return await inter.followup.send(f"❌ I cannot assign {role.mention} because it is higher than my highest role.", ephemeral=True)

        # Toggle role
        if role in inter.user.roles:
            await inter.user.remove_roles(role, reason="LFG Role Opt-out")
            new_state = False
            embed = discord.Embed(
                description=f"✅ You have unsubscribed from {role.mention} pings.",
                color=discord.Color.light_grey()
            )
        else:
            await inter.user.add_roles(role, reason="LFG Role Opt-in")
            new_state = True
            embed = discord.Embed(
                description=f"✅ You have subscribed to {role.mention} pings.",
                color=discord.Color.green()
            )

        # Sync to DB
        await db.execute(f'''
            INSERT INTO users (user_id, {self.db_column}) 
            VALUES (%s, %s) 
            ON DUPLICATE KEY UPDATE {self.db_column} = %s
        ''', (inter.user.id, new_state, new_state))
        
        await inter.followup.send(embed=embed, ephemeral=True)


class LFGRolesPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for settings_key, label, emoji, db_column, row in LFG_ROLES:
            self.add_item(LFGToggleButton(settings_key, label, emoji, db_column, row))


# ─────────────────────────────────────────────────────────────────
# Main Cog
# ─────────────────────────────────────────────────────────────────
class LFGCog(commands.GroupCog, group_name="lfg"):
    """Looking For Group notification system."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(LFGRolesPanelView())
        self.expire_lfg_pings.start()
        
    def cog_unload(self):
        self.expire_lfg_pings.cancel()

    # ─────────────────────────────────────────────────────────────────
    # Section 4 — Background Expiry Loop
    # ─────────────────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def expire_lfg_pings(self):
        """Auto-delete expired LFG pings from the channel."""
        pings = await db.fetch_all('''
            SELECT id, channel_id, message_id 
            FROM lfg_pings 
            WHERE expires_at <= NOW() AND deleted = FALSE
        ''')
        
        for ping in pings:
            try:
                channel = self.bot.get_channel(ping['channel_id'])
                if channel:
                    msg = await channel.fetch_message(ping['message_id'])
                    await msg.delete()
            except discord.NotFound:
                pass  # Already deleted manually
            except discord.Forbidden:
                pass  # Lost permissions, just mark as deleted
            except Exception as e:
                print(f"[LFG Expiry] Error deleting message {ping['message_id']}: {e}")
                
            # Always mark as deleted in DB so we don't retry forever
            await db.execute("UPDATE lfg_pings SET deleted = TRUE WHERE id = %s", (ping['id'],))

    @expire_lfg_pings.before_loop
    async def before_expire_lfg_pings(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────────────────────────
    # Section 3 — /lfg <mode> Slash Command
    # ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="ping", description="Ping a role to look for teammates in a specific game mode.")
    @app_commands.describe(mode="The game mode you want to play")
    async def lfg_ping(
        self, 
        inter: discord.Interaction, 
        mode: Literal["Ranked", "Classic", "Brawl", "MRO", "Arcade", "Magic Chess"]
    ):
        # 1. LFG channel configured
        channel_id = await settings_service.get_int("lfg_channel_id")
        if channel_id == 0:
            return await inter.response.send_message("⚠️ LFG channel not set. Ask an admin to run `/setup channel lfg`.", ephemeral=True)
            
        # 2. LFG channel exists
        lfg_channel = inter.guild.get_channel(channel_id)
        if not lfg_channel:
            return await inter.response.send_message("❌ Configured LFG channel no longer exists. Contact admin.", ephemeral=True)
            
        # Find the mode config
        mode_conf = next((m for m in LFG_ROLES if m[1] == mode), None)
        if not mode_conf:
            return await inter.response.send_message("❌ Invalid mode.", ephemeral=True)
            
        settings_key, label, emoji, db_col, _ = mode_conf
        
        # 3. Role is provisioned
        role_id = await settings_service.get_int(settings_key)
        if role_id == 0:
            return await inter.response.send_message("⚠️ LFG roles not mapped. Ask an admin to run `/setup lfg-roles`.", ephemeral=True)
            
        # 4. Role exists
        role = inter.guild.get_role(role_id)
        if not role:
            return await inter.response.send_message(f"❌ LFG role for **{mode}** was deleted. Contact admin.", ephemeral=True)
            
        # 5. User has the role
        if role not in inter.user.roles:
            return await inter.response.send_message(f"🔒 You must subscribe to **{role.name}** first. Use the LFG Roles panel.", ephemeral=True)
            
        # 6. Global 5-min user cooldown check
        user_row = await db.fetch_one("SELECT lfg_last_ping FROM users WHERE user_id = %s", (inter.user.id,))
        if user_row and user_row['lfg_last_ping']:
            last_ping = user_row['lfg_last_ping']
            import datetime
            from utils.constants import TZ_MANILA
            now = datetime.datetime.now(TZ_MANILA).replace(tzinfo=None) # DB returns naive datetime
            delta = now - last_ping
            if delta.total_seconds() < 300: # 5 minutes
                remaining = int(300 - delta.total_seconds())
                mins, secs = divmod(remaining, 60)
                return await inter.response.send_message(f"⏳ You can send another LFG ping in **{mins} min {secs} sec**.", ephemeral=True)
                
        # We are good to go!
        # Colors match the setup deployment logic generally
        colors = {
            "Ranked": discord.Color.gold(),
            "Classic": discord.Color.blue(),
            "Brawl": discord.Color.red(),
            "MRO": discord.Color.purple(),
            "Arcade": discord.Color.green(),
            "Magic Chess": discord.Color.teal()
        }
        
        embed = discord.Embed(
            title=f"{emoji} Looking for Group — {mode}",
            description=f"{inter.user.mention} is looking for teammates!",
            color=colors.get(mode, discord.Color.default()),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="⏱ This ping expires in 15 minutes • React ✅ to join")
        
        try:
            msg = await lfg_channel.send(content=role.mention, embed=embed)
            await msg.add_reaction("✅")
        except discord.Forbidden:
            return await inter.response.send_message(f"❌ I lack permissions to send messages or mention roles in {lfg_channel.mention}.", ephemeral=True)
        except discord.HTTPException as e:
            return await inter.response.send_message(f"❌ Discord API error: {e}", ephemeral=True)
            
        # On success, update cooldown and log ping
        await db.execute('''
            INSERT INTO users (user_id, lfg_last_ping) 
            VALUES (%s, NOW()) 
            ON DUPLICATE KEY UPDATE lfg_last_ping = NOW()
        ''', (inter.user.id,))
        
        await db.execute('''
            INSERT INTO lfg_pings (user_id, mode, message_id, channel_id, expires_at) 
            VALUES (%s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 15 MINUTE))
        ''', (inter.user.id, mode, msg.id, lfg_channel.id))
        
        await inter.response.send_message(f"✅ LFG ping sent to {lfg_channel.mention}!", ephemeral=True)


# ─────────────────────────────────────────────────────────────────
# LFG Roles Deploy Command (Admin)
# ─────────────────────────────────────────────────────────────────
class LFGRolesAdmin(commands.GroupCog, group_name="lfg-roles"):
    """Admin commands for LFG role panel."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="deploy", description="Deploy the LFG role preferences panel.")
    @app_commands.describe(channel="Channel to deploy the panel in")
    @require_admin_auth()
    async def deploy_lfg_panel(self, inter: discord.Interaction, channel: discord.TextChannel):
        # Validate all roles are mapped before deploying
        missing = []
        mapped_mentions = []
        for settings_key, label, emoji, _, _ in LFG_ROLES:
            role_id = await settings_service.get_int(settings_key)
            if role_id == 0:
                missing.append(label)
            else:
                role = inter.guild.get_role(role_id)
                if not role:
                    missing.append(f"{label} (Role Deleted)")
                else:
                    mapped_mentions.append(f"{emoji} **{label}:** {role.mention}")
                    
        if missing:
            return await inter.response.send_message(f"❌ Cannot deploy. The following modes are not mapped to roles:\n" + "\n".join(f"- {m}" for m in missing) + "\n\nRun `/setup lfg-roles` first.", ephemeral=True)
            
        embed = discord.Embed(
            title="🎮 LFG Role Preferences",
            description="Subscribe to get pinged when someone is looking for a group in your favorite game modes!\n\nClick the buttons below to opt-in or opt-out. You must have the role to use the `/lfg` command for that mode.",
            color=discord.Color.brand_green()
        )
        embed.add_field(name="Available Modes", value="\n".join(mapped_mentions), inline=False)
        embed.set_footer(text="Roles sync automatically. Pings expire after 15 mins to keep chat clean.")
        
        try:
            await channel.send(embed=embed, view=LFGRolesPanelView())
            await inter.response.send_message(f"✅ Panel deployed to {channel.mention}", ephemeral=True)
        except discord.Forbidden:
            await inter.response.send_message("❌ I lack permissions to send messages in that channel.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LFGCog(bot))
    await bot.add_cog(LFGRolesAdmin(bot))
