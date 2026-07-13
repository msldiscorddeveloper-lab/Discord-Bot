"""
Verification Cog.
Persistent verification panel with button + modal.
Admin commands for lookup, edit, and unverify.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging

from services.verification_service import verification_service
from services.settings_service import settings_service
from services.referral_service import referral_service
from utils.checks import require_admin_auth

logger = logging.getLogger("mlbb_bot.verification_cog")

# Reference image showing where to find MLBB UID and Server
MLBB_REFERENCE_IMAGE = (
    "https://media.discordapp.net/attachments/1471519234608861264/"
    "1471519333837701272/Screenshot_2026-02-12_at_22.51.43.png"
    "?ex=69c153ac&is=69c0022c"
    "&hm=398671c5b2665b2ab7e10f91cc08ef3b3682e3289df6b5b6df6839d5fdc22bbc"
    "&=&format=webp&quality=lossless&width=1824&height=940"
)


# ─── PERSISTENT VIEW ────────────────────────────────────────────────────

class VerificationModal(discord.ui.Modal, title="📝 MLBB Account Verification"):
    """Three-field modal for collecting MLBB account info."""

    full_name = discord.ui.TextInput(
        label="Full Name",
        placeholder="e.g. Juan Dela Cruz",
        required=True,
        max_length=255,
    )
    mlbb_uid = discord.ui.TextInput(
        label="MLBB UID (Game ID number)",
        placeholder="e.g. 123456789",
        required=True,
        max_length=20,
    )
    mlbb_server = discord.ui.TextInput(
        label="MLBB Server ID (number next to UID)",
        placeholder="e.g. 3456",
        required=True,
        max_length=10,
    )
    referral_code = discord.ui.TextInput(
        label="Referral Code (optional)",
        placeholder="e.g. MSL-21I3V9",
        required=False,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # ── Validate UID is numeric ──
        uid_str = self.mlbb_uid.value.strip()
        if not uid_str.isdigit():
            return await interaction.response.send_message(
                "❌ **MLBB UID must be a number.** Check the reference image above and try again.",
                ephemeral=True,
            )

        # ── Validate Server is numeric ──
        server_str = self.mlbb_server.value.strip()
        if not server_str.isdigit():
            return await interaction.response.send_message(
                "❌ **MLBB Server ID must be a number.** Check the reference image above and try again.",
                ephemeral=True,
            )

        uid = int(uid_str)
        server = int(server_str)
        name = self.full_name.value.strip()

        # ── Attempt verification ──
        result = await verification_service.verify_user(
            interaction.user.id, name, uid, server
        )

        if result is None:
            # Success — grant the Verified role
            verified_role_id = await settings_service.get_int("verified_role_id")
            if verified_role_id:
                role = interaction.guild.get_role(verified_role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="MLBB Verification")
                    except discord.Forbidden:
                        logger.error(f"Cannot grant Verified role to {interaction.user.id}")

            # ── MSL Cross-Reference ──
            msl_status = ""
            if verification_service.is_msl(uid, server):
                msl_nickname = verification_service.get_msl_nickname(uid, server)
                msl_role_id = await settings_service.get_int("msl_role_id")
                if msl_role_id:
                    msl_role = interaction.guild.get_role(msl_role_id)
                    if msl_role:
                        try:
                            await interaction.user.add_roles(msl_role, reason="MSL Verification")
                            msl_status = f"\n\n🎓 **Moonton Student Leader Detected!**\nMSL Name: **{msl_nickname}**"
                        except discord.Forbidden:
                            logger.error(f"Cannot grant MSL role to {interaction.user.id}")
                    else:
                        msl_status = f"\n\n🎓 **Moonton Student Leader Detected!**\nMSL Name: **{msl_nickname}**"
                else:
                    msl_status = f"\n\n🎓 **Moonton Student Leader Detected!**\nMSL Name: **{msl_nickname}**"

            # ── Referral Code (non-blocking) ──
            referral_status = ""
            ref_code = self.referral_code.value.strip()
            if ref_code:
                try:
                    ref_result = await referral_service.link_referral(
                        interaction.user.id,
                        ref_code,
                        interaction.user.joined_at,
                    )
                    if ref_result is None:
                        referral_status = "\n\n🔗 Referral code applied!"
                    else:
                        referral_status = "\n\n⚠️ Referral code invalid — use `/referral-link` to try again."
                except Exception as e:
                    logger.error(f"Referral link error during verification: {e}")
                    referral_status = ""

            embed = discord.Embed(
                title="✅ Verification Successful!",
                description=(
                    f"**Name:** {name}\n"
                    f"**MLBB UID:** {uid}\n"
                    f"**Server:** {server}\n\n"
                    f"You can now earn XP and Event Points. Have fun! 🎉{msl_status}{referral_status}"
                ),
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif result == "already_verified":
            info = await verification_service.get_user_info(interaction.user.id)
            embed = discord.Embed(
                title="ℹ️ Already Verified",
                description=(
                    f"You're already verified with:\n"
                    f"**Name:** {info['full_name']}\n"
                    f"**MLBB UID:** {info['mlbb_uid']}\n"
                    f"**Server:** {info['mlbb_server']}\n\n"
                    "Need to update your info? Contact an admin."
                ),
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif result.startswith("uid_taken:"):
            other_id = result.split(":")[1]
            await interaction.response.send_message(
                f"❌ **This MLBB UID is already linked to another account** (<@{other_id}>).\n"
                f"If this is your account, contact an admin for help.",
                ephemeral=True,
            )


class VerifyView(discord.ui.View):
    """Persistent view with a single Verify button. Survives bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.green,
        emoji="✅",
        custom_id="verification:verify_button",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerificationModal())


class AdminEditModal(discord.ui.Modal, title="✏️ Edit Verification Info"):
    """Admin-only modal for editing a user's verification info."""

    def __init__(self, target_user_id: int, current_info: dict):
        super().__init__()
        self.target_user_id = target_user_id

        self.full_name = discord.ui.TextInput(
            label="Full Name",
            default=current_info['full_name'],
            required=True,
            max_length=255,
        )
        self.mlbb_uid = discord.ui.TextInput(
            label="MLBB UID",
            default=str(current_info['mlbb_uid']),
            required=True,
            max_length=20,
        )
        self.mlbb_server = discord.ui.TextInput(
            label="MLBB Server ID",
            default=str(current_info['mlbb_server']),
            required=True,
            max_length=10,
        )

        self.add_item(self.full_name)
        self.add_item(self.mlbb_uid)
        self.add_item(self.mlbb_server)

    async def on_submit(self, interaction: discord.Interaction):
        uid_str = self.mlbb_uid.value.strip()
        server_str = self.mlbb_server.value.strip()

        if not uid_str.isdigit() or not server_str.isdigit():
            return await interaction.response.send_message(
                "❌ UID and Server must be numbers.", ephemeral=True
            )

        result = await verification_service.update_user_info(
            self.target_user_id,
            self.full_name.value.strip(),
            int(uid_str),
            int(server_str),
        )

        if result is None:
            await interaction.response.send_message(
                f"✅ Updated verification info for <@{self.target_user_id}>.",
                ephemeral=True,
            )
        elif result.startswith("uid_taken:"):
            other_id = result.split(":")[1]
            await interaction.response.send_message(
                f"❌ UID already linked to <@{other_id}>.", ephemeral=True
            )


# ─── COG ────────────────────────────────────────────────────────────────

class VerificationCog(commands.Cog, name="verification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Register persistent view and load verification + MSL caches on startup."""
        self.bot.add_view(VerifyView())
        await verification_service.load_cache()
        await verification_service.load_msl_cache()
        if not self.msl_refresh_loop.is_running():
            self.msl_refresh_loop.start()
        logger.info("Verification system ready")

    @tasks.loop(hours=6)
    async def msl_refresh_loop(self):
        """Periodically refresh the MSL cache from Google Sheets."""
        count = await verification_service.load_msl_cache()
        logger.info(f"MSL cache refreshed: {count} entries")

    @msl_refresh_loop.before_loop
    async def before_msl_refresh(self):
        await self.bot.wait_until_ready()

    verify_group = app_commands.Group(name="verify", description="MLBB verification system", default_permissions=discord.Permissions(administrator=True))

    # ─── SETUP COMMANDS ─────────────────────────────────────────────────

    @verify_group.command(name="deploy", description="Post the verification panel in a channel.")
    @app_commands.default_permissions(administrator=True)
    async def setup_verification(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Post the persistent verification embed + button in the specified channel."""
        embed = discord.Embed(
            title="📋 Server Verification",
            description=(
                "To participate fully in this server, you need to verify your MLBB account.\n\n"
                "**What you'll need:**\n"
                "• Your **Full Name**\n"
                "• Your **MLBB Game ID (UID)**\n"
                "• Your **Server ID**\n\n"
                "**How to find your UID and Server:**\n"
                "Open MLBB → Profile → Your ID and Server are shown below your username "
                "(see the image below).\n\n"
                "Click the button below to get started! 👇"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_image(url=MLBB_REFERENCE_IMAGE)
        embed.set_footer(text="You only need to verify once. Your data is stored securely.")

        await channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message(
            f"✅ Verification panel posted in {channel.mention}.", ephemeral=True
        )

    # ─── ADMIN LOOKUP COMMANDS ──────────────────────────────────────────


    @verify_group.command(name="whois", description="Look up a Discord user by their MLBB UID.")
    @app_commands.default_permissions(administrator=True)
    async def whois(self, interaction: discord.Interaction, mlbb_uid: int):
        info = await verification_service.lookup_by_uid(mlbb_uid)
        if not info:
            return await interaction.response.send_message(
                f"❌ No user found with MLBB UID `{mlbb_uid}`.", ephemeral=True
            )

        member = interaction.guild.get_member(info['user_id'])
        name_display = member.mention if member else f"User ID: `{info['user_id']}`"

        embed = discord.Embed(
            title=f"🔍 MLBB UID Lookup — {mlbb_uid}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Discord User", value=name_display, inline=False)
        embed.add_field(name="Full Name", value=info['full_name'], inline=True)
        embed.add_field(name="Server", value=str(info['mlbb_server']), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── ADMIN EDIT / UNVERIFY ──────────────────────────────────────────

    @verify_group.command(name="update", description="Edit a user's MLBB verification info.")
    @app_commands.default_permissions(administrator=True)
    async def update_verification(self, interaction: discord.Interaction, user: discord.Member):
        info = await verification_service.get_user_info(user.id)
        if not info:
            return await interaction.response.send_message(
                f"❌ {user.mention} is not verified. Nothing to edit.", ephemeral=True
            )

        modal = AdminEditModal(user.id, info)
        await interaction.response.send_modal(modal)

    @verify_group.command(name="remove", description="Remove a user's verification.")
    @app_commands.default_permissions(administrator=True)
    async def unverify(self, interaction: discord.Interaction, user: discord.Member):
        removed = await verification_service.unverify_user(user.id)
        if not removed:
            return await interaction.response.send_message(
                f"❌ {user.mention} is not verified.", ephemeral=True
            )

        # Strip the Verified role
        verified_role_id = await settings_service.get_int("verified_role_id")
        if verified_role_id:
            role = interaction.guild.get_role(verified_role_id)
            if role and role in user.roles:
                try:
                    await user.remove_roles(role, reason="Admin unverification")
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            f"✅ {user.mention} has been **unverified**. They will no longer earn XP or EP.",
            ephemeral=True,
        )

    @verify_group.command(name="force-remove", description="Remove a verification by MLBB UID (works for users who left).")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(mlbb_uid="The MLBB UID to unverify")
    async def force_remove(self, interaction: discord.Interaction, mlbb_uid: int):
        """Remove a verification record by MLBB UID, even if the user has left the server."""
        await interaction.response.defer(ephemeral=True)

        removed_info = await verification_service.unverify_by_uid(mlbb_uid)
        if not removed_info:
            return await interaction.followup.send(
                f"❌ No verification found for MLBB UID `{mlbb_uid}`.", ephemeral=True
            )

        removed_user_id = removed_info['user_id']

        # Best-effort: strip Verified role if user is still in the server
        role_stripped = False
        verified_role_id = await settings_service.get_int("verified_role_id")
        if verified_role_id:
            try:
                member = await interaction.guild.fetch_member(removed_user_id)
                role = interaction.guild.get_role(verified_role_id)
                if role and role in member.roles:
                    await member.remove_roles(role, reason="Admin force-remove verification")
                    role_stripped = True
            except discord.NotFound:
                pass  # User left the server — expected
            except discord.Forbidden:
                logger.error(f"Cannot strip Verified role from {removed_user_id}")

        # Confirmation embed
        status_note = "✅ Verified role also stripped." if role_stripped else "ℹ️ User is not in the server — role strip skipped."
        embed = discord.Embed(
            title="🗑️ Verification Force-Removed",
            description=(
                f"**Removed record:**\n"
                f"**Name:** {removed_info['full_name']}\n"
                f"**MLBB UID:** {removed_info['mlbb_uid']}\n"
                f"**Server:** {removed_info['mlbb_server']}\n"
                f"**Discord ID:** `{removed_user_id}`\n\n"
                f"{status_note}\n\n"
                f"This MLBB UID is now free and can be re-verified."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Removed by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Audit log to mod log channel
        log_embed = discord.Embed(
            title="🗑️ Verification Force-Removed",
            color=discord.Color.orange(),
        )
        log_embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Discord User", value=f"<@{removed_user_id}> (`{removed_user_id}`)", inline=True)
        log_embed.add_field(name="MLBB UID", value=str(removed_info['mlbb_uid']), inline=True)
        log_embed.add_field(name="Full Name", value=removed_info['full_name'], inline=True)
        log_embed.add_field(name="Server", value=str(removed_info['mlbb_server']), inline=True)
        log_embed.add_field(name="Role Stripped", value="Yes" if role_stripped else "No (not in server)", inline=True)

        mod_log_id = await settings_service.get_int("mod_log_channel_id")
        if mod_log_id:
            log_channel = interaction.guild.get_channel(mod_log_id)
            if log_channel:
                try:
                    await log_channel.send(embed=log_embed)
                except discord.Forbidden:
                    logger.error("Cannot send to mod log channel")

    @verify_group.command(name="lookup", description="Look up verification info by Discord User ID.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user_id="Discord User ID (works for users who left)")
    async def lookup_user(self, interaction: discord.Interaction, user_id: str):
        """Look up a user's verification details by raw Discord User ID."""
        # Validate numeric input
        user_id_str = user_id.strip()
        if not user_id_str.isdigit():
            return await interaction.response.send_message(
                "❌ **User ID must be a number.** Right-click a user → Copy User ID.",
                ephemeral=True,
            )

        uid_int = int(user_id_str)
        info = await verification_service.get_user_info(uid_int)

        if not info:
            return await interaction.response.send_message(
                f"❌ No verification found for Discord user `{uid_int}`.",
                ephemeral=True,
            )

        # Check MSL status
        msl_status = "❌ No"
        if verification_service.is_msl(info['mlbb_uid'], info['mlbb_server']):
            nickname = verification_service.get_msl_nickname(info['mlbb_uid'], info['mlbb_server'])
            msl_status = f"✅ Yes — **{nickname}**"

        embed = discord.Embed(
            title=f"🔍 Verification Lookup — User `{uid_int}`",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Discord User", value=f"<@{uid_int}>", inline=True)
        embed.add_field(name="Full Name", value=info['full_name'], inline=True)
        embed.add_field(name="MLBB UID", value=str(info['mlbb_uid']), inline=True)
        embed.add_field(name="Server", value=str(info['mlbb_server']), inline=True)
        embed.add_field(name="MSL Member", value=msl_status, inline=True)
        if info.get('verified_at'):
            embed.add_field(name="Verified At", value=f"<t:{int(info['verified_at'].timestamp())}:F>", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── MSL SUBGROUP ────────────────────────────────────────────────────

    msl_group = app_commands.Group(
        name="msl", description="Moonton Student Leader verification",
        parent=verify_group
    )

    @msl_group.command(name="setup", description="Configure the MSL spreadsheet and role")
    @require_admin_auth()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        sheet_url="Google Sheets URL (must be public / anyone with link)",
        role="The MSL role to assign"
    )
    async def msl_setup(self, interaction: discord.Interaction, sheet_url: str, role: discord.Role):
        await interaction.response.defer(ephemeral=True)

        # Validate the URL looks like a Google Sheet
        if 'spreadsheets/d/' not in sheet_url:
            return await interaction.followup.send(
                "❌ That doesn't look like a Google Sheets URL. "
                "It should contain `spreadsheets/d/`.",
                ephemeral=True
            )

        await settings_service.set("msl_sheet_url", sheet_url)
        await settings_service.set("msl_role_id", str(role.id))

        # Immediately load the cache to validate
        count = await verification_service.load_msl_cache()

        await interaction.followup.send(
            f"✅ **MSL Verification configured!**\n\n"
            f"📄 Sheet: {sheet_url}\n"
            f"🏷️ Role: {role.mention}\n"
            f"👥 **{count}** MSL entries loaded from the FINAL tab.",
            ephemeral=True
        )

    @msl_group.command(name="refresh", description="Force refresh the MSL cache from Google Sheets")
    @require_admin_auth()
    @app_commands.default_permissions(administrator=True)
    async def msl_refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        count = await verification_service.load_msl_cache()
        await interaction.followup.send(
            f"✅ MSL cache refreshed — **{count}** entries loaded.",
            ephemeral=True
        )

    @msl_group.command(name="check", description="Check if a verified user is an MSL member")
    @require_admin_auth()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="The user to check")
    async def msl_check(self, interaction: discord.Interaction, user: discord.Member):
        info = await verification_service.get_user_info(user.id)
        if not info:
            return await interaction.response.send_message(
                f"❌ {user.mention} is not verified.", ephemeral=True
            )

        mlbb_uid = info['mlbb_uid']
        mlbb_server = info['mlbb_server']
        if verification_service.is_msl(mlbb_uid, mlbb_server):
            nickname = verification_service.get_msl_nickname(mlbb_uid, mlbb_server)
            msl_role_id = await settings_service.get_int("msl_role_id")

            # Grant role if not already assigned
            if msl_role_id:
                msl_role = interaction.guild.get_role(msl_role_id)
                if msl_role and msl_role not in user.roles:
                    try:
                        await user.add_roles(msl_role, reason="MSL manual check")
                    except discord.Forbidden:
                        pass

            await interaction.response.send_message(
                f"🎓 **{user.mention}** is an MSL member!\n"
                f"MSL Nickname: **{nickname}**\n"
                f"MLBB UID: **{mlbb_uid}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {user.mention} (UID: {mlbb_uid}) is **not** in the MSL spreadsheet.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
