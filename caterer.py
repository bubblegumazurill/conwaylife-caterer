import asyncio
import collections
import copy
import os
import select
import subprocess
from datetime import datetime

import aiofiles
import asyncpg
import discord
from discord.ext import commands

from cogs.resources import mutils


def get_prefix(bot, message):
    try:
        return ['ca.'] + ([('!', ';')[bot.user.id == 376485072561504257]] if message.guild.id == 357922255553953794 else [])
    except AttributeError:  # if in DMs, message.guild is None and therefore has no attribute 'id'
        return '!'  # TODO: override commands.Bot.get_prefix to allow this to be ''


class Context(commands.Context):
    async def update(self):
        self.message = await self.fetch_message(self.message.id)
    
    async def upd_rxns(self):
        await self.update()
        return self.message.reactions
    
    async def thumbsup(self, user=None, text='Success!', ping=False, *, channel=None, override=True):
        try:
            if not override and any(rxn.emoji in '👍👎' for rxn in await self.upd_rxns() if rxn.me):
                return
            await self.message.add_reaction('👍')
            if user is not None and ping:
                await (self if channel is None else channel).send(f'{user.mention}: {text}')
        except discord.NotFound:
            pass
    
    async def thumbsdown(self, user=None, text='Failure.', ping=False, *, channel=None, override=True):
        try:
            if not override and any(rxn.emoji in '👍👎' for rxn in await self.upd_rxns() if rxn.me):
                return
            await self.message.add_reaction('👎')
            if user is not None and ping:
                await (self if channel is None else channel).send(f'{user.mention}: {text}')
        except discord.NotFound:
            pass
    
    async def invoke(self, *args, **kwargs):
        return await super().invoke(*args, **kwargs, __invoking=True)


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        self.first_time = True
        self.owner = None
        self.assets_chn = None
        super().__init__(*args, **kwargs)
    
    async def on_message(self, message):
        await self.invoke(await self.custom_context(message))
    
    async def custom_context(self, message):
        return await self.get_context(message, cls=Context)
    
    async def approve_asset(self, file, blurb, author, kind, *, created_at=None, name=None, approval='✅', rejection='❌'):
        if name is None:
            name = file.filename.rsplit('.', 1)[0]
        msg = await self.assets_chn.send(f'{kind.upper()} {name}: {blurb}', file=file)
        await msg.edit(content=f'{msg.content}\nFrom {author.mention}')
        await msg.add_reaction(approval)
        await msg.add_reaction(rejection)
        file.reset()
        return await self.approve_msg(msg, created_at, approval=approval, rejection=rejection)
    
    async def approve_msg(self, msg, created_at=None, *, approval='✅', rejection='❌'):
        def check(rxn, usr):
            # ...not going to check role IDs anymore, because if someone has access to
            # the caterer-assets channel it's likely a given that they're trusted
            return usr.id != self.user.id and rxn.message.id == msg.id and rxn.emoji in (approval, rejection)
        if created_at is None:
            created_at = msg.created_at
        rxn, _ = await self.wait_for('reaction_add', check=check)  # no timeout
        await msg.delete()
        # if it hasn't even been a minute yet, then they're probably still around to see
        # the thumbs-up, so don't ping
        should_ping = (datetime.now() - created_at).total_seconds() >= 60
        if rxn.emoji == approval:
            return True, should_ping
        return False, should_ping



bot = Bot(
  command_prefix=get_prefix,
  description='A cellular automata bot for Conwaylife.com',
  help_command=None
)

@bot.check
def ignore_bots(ctx):
    return not ctx.author.bot

@bot.event
async def on_ready():
    if bot.first_time:
        #### DEV STUFF
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ####
        bot.pool = await asyncpg.create_pool(
          ssl=context,
          dsn=os.getenv('DATABASE_URL'), max_size=15, loop=bot.loop
        )
        bot.assets_chn = bot.get_channel(424383992666783754)
        bot.owner = (await bot.application_info()).owner
        for cog in ('meta', 'wiki', 'ca', 'admin'):
            try:
                bot.load_extension(f'cogs.{cog}')
            except Exception:
                raise
        bot.help_padding = 1 + max(len(i.name) for i in bot.commands)
        bot.sorted_commands = sorted(bot.commands, key=lambda x: x.name)
        print(f'Logged in as\n{bot.user.name}\n{bot.user.id}')
        print('Guilds:', len(bot.guilds))
        print('------')
        bot.first_time = False

bot.run(os.getenv('DISCORD_TOKEN'))
