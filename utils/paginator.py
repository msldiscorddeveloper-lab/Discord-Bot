import discord

class EmbedPaginator(discord.ui.View):
    """
    A reusable paginator for lists of discord.Embed objects.
    Provides Next and Previous buttons, and a label indicating the current page.
    """
    
    def __init__(self, pages: list[discord.Embed], author_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.current_page = 0
        
        # Setup initial button state
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the original command author to use the buttons."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("❌ This is not your menu.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        """Disable all buttons when the view times out."""
        for child in self.children:
            child.disabled = True
        
        # Attempt to edit the message if we still have the view attached
        # Note: If this view was attached to an ephemeral message, editing might fail if it's too old
        # But Discord automatically greys them out on the client side after 15 mins for ephemeral anyway
        pass

    def _update_buttons(self):
        """Update the state of the buttons based on the current page."""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1
        self.page_label.label = f"Page {self.current_page + 1}/{len(self.pages)}"

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="paginator_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, custom_id="paginator_label", disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This button is just a label, it's always disabled
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="paginator_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
