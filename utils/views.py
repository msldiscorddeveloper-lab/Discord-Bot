"""
Discord UI Views for the bot.
"""

import discord


class CancelScheduledEmbedView(discord.ui.View):
    """Dropdown view for cancelling scheduled embeds."""
    
    def __init__(self, scheduled_embeds: list, cog, user: discord.User):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        
        # Create options from scheduled embeds
        options = [
            discord.SelectOption(
                label=f"ID: {row['identifier']}",
                value=row['identifier'],
                description=f"Scheduled for: {row['schedule_for']}"
            )
            for row in scheduled_embeds[:25]  # Max 25 options
        ]
        
        self.select = discord.ui.Select(
            placeholder="Select embed to cancel...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the original user can use this view."""
        return interaction.user.id == self.user.id
    
    async def select_callback(self, interaction: discord.Interaction):
        """Handle selection."""
        identifier = self.select.values[0]
        await self.cog.cancel_scheduled_embed_action(interaction, identifier)
        self.stop()
