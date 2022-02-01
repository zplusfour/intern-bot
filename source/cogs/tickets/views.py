import re
import asyncio
import nextcord

from os import path

from nextcord import ui

from source import COLOR

from db import session
from db.models import Client
from db.models import Ticket
from db.models import Context
from db.utility import commit

from .utility import ROLES
from .utility import TARGET
from .utility import make_client
from .utility import file_content


class HelpBoard(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.target = TARGET

    @nextcord.ui.button(label="Code Help", custom_id="ps:cod", emoji=r"💳")
    async def code_button(self, *args, **kwargs):
        await self.handle_click(*args, **kwargs)

    @nextcord.ui.button(label="Replit Help", custom_id="ps:rep", emoji=r"🖥️")
    async def replit_button(self, *args, **kwargs):
        await self.handle_click(*args, **kwargs)

    @nextcord.ui.button(label="Bot Help", custom_id="ps:bot", emoji=r"🤖")
    async def bot_button(self, *args, **kwargs):
        await self.handle_click(*args, **kwargs)

    async def handle_click(self, btn, inter):
        res = inter.response
        client = make_client(inter.user.id)
        can_open, reason = client.can_open()

        if not can_open:
            return await res.send_message(reason, ephemeral=True)
        else:
            commit(client.opened())

        target = self.bot.get_channel(self.target)
        thread = await target.create_thread(
            type=None,
            auto_archive_duration=1440,
            name=f"ticket-{inter.user.name}{inter.user.discriminator}",
            reason=f"Auto-created thread for help ticket from {inter.user.name}",
        )

        ticket = commit(
            Ticket(body=None, type_=btn.label, client_id=client.id, thread_id=thread.id)
        )[0]

        await thread.edit(name=f"{thread.name}-{ticket.id}")

        c = file_content("thread")
        check = lambda m: m.author.id == inter.user.id
        em = nextcord.Embed(title=f"{btn.label} Thread", description=c, color=COLOR)
        em.set_footer(text=f"Ticket ID: {ticket.id} | Opened: {ticket.stamp}")

        await thread.add_user(inter.user); await thread.send(embed=em)

        try:
            m = await self.bot.wait_for("message", check=check, timeout=60 * 5)
        except asyncio.TimeoutError:
            await thread.send("Timed out while waiting for response. Archiving thread.")
            await thread.edit(archived=True)

            ticket.update(resolved=True, body="error:asyncio.TimeoutError")
            session.commit()

            return True

        ticket.update(body=m.content)

        for a in m.attachments:
            commit(Context(url=a.url, type_=a.content_type, ticket_id=ticket.id))

        session.commit()

        await thread.send(
            "Got it! Please select all the categories "
            "that apply to your question. (No more than 3)",
            view=CategoryDropdownView(ticket, self)
        )
    
    async def handoff(self, ticket, rnames, inter):
        target = self.bot.get_channel(self.target)
        thread = self.bot.get_channel(ticket.thread_id)
        roles = [r for r in thread.guild.roles if r.name in rnames]


        em = nextcord.Embed(color=COLOR)
        em.title=f"**New Help Request**: {inter.user.mention}"
        em.description = f"**Body**: \"{ticket.body[:240]}...\"\n"
        em.description += f"**Categories**: {' '.join(rnames)}\n\n"
        em.description += f"**0** users are currently in this help thread."
        em.set_footer(text=f"Ticket ID: {ticket.id} | Opened: {ticket.stamp}")

        m = await target.send(
            f"CC: {' '.join([r.mention for r in roles])}",
            embed=em,
            allowed_mentions=nextcord.AllowedMentions.none(),
            view=JoinThreadView(ticket, self.bot)
        )

        ticket.notice_id = m.id
        commit(ticket)

        await thread.edit(locked=False)
        await thread.send(
            "Your ticket has been saved. Help will join the thread soon! "
            "Once you have recieved satisfactory help, use `%tickets.resolve` "
            "so I know to archive the thread and mark your question as resolved."
        )

        await inter.message.delete()


class CategoryDropdownView(ui.View):
    def __init__(self, t, other):
        super().__init__(timeout=None)

        self.add_item(CategoryDropdown(t, other))


class CategoryDropdown(ui.Select):
    def __init__(self, t, other):
        super().__init__(
            min_values=1,
            max_values=3,
            custom_id=f"ps:tick-{t.id}",
            placeholder="Select the languages that apply.",
            options=[nextcord.SelectOption(**r) for r in ROLES]
        )

        self.ticket = t
        self.other = other
    
    async def callback(self, inter):
        await self.other.handoff(self.ticket, self.values, inter)


class JoinThreadView(ui.View):
    def __init__(self, t, bot):
        super().__init__(timeout=None)

        btn = ui.Button(
            disabled=t.resolved,
            label="Join the Thread!",
            style=nextcord.ButtonStyle.success,
            custom_id=f"ps:thread-{t.thread_id}",
        ); btn.callback = self.callback

        self.bot = bot
        self.ticket = t
        self.add_item(btn)
    
    async def callback(self, inter):
        target = self.bot.get_channel(TARGET)
        thread = self.bot.get_channel(self.ticket.thread_id)

        await thread.add_user(inter.user)

        m = await target.fetch_message(self.ticket.notice_id)

        em = m.embeds[0]
        num = re.findall(r"\d+", em.description)[0]

        em.description = em.description.replace(num, str(int(num) + 1))

        await m.edit(embed=em)


class ResolvedThreadView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Thread is resolved.", disabled=True)
    async def button(self, *args):
        pass
