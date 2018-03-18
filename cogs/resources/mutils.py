# ----------------------------------------------------------------------------------- #

from itertools import islice

def nth(iterable, n, default=None):
    temp = iterable
    return next(islice(temp, n, None), default)

# ----------------------------------------------------------------------------------- #

import inspect
from functools import wraps
from itertools import zip_longest as zipln

def typecasted(func):
    """Decorator that casts a func's arg to its type hint if possible"""
    #TODO: Allow (callable, callable, ..., callable) sequences to apply
    # each callable in order on the last's return value
    params = inspect.signature(func).parameters.items()
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Prepare list/dict of all positional/keyword args of annotation or None
        pannot, kwannot = (
          [func.__annotations__.get(p.name) for _, p in params if p.kind < 3],
          {None if p.kind - 3 else p.name: func.__annotations__.get(p.name) for _, p in params if p.kind >= 3}
          )
        # Assign default to handle **kwargs annotation if not given/callable
        if not callable(kwannot.get(None)):
            kwannot[None] = lambda x: x
        ret = func(
            *(hint(val) if callable(hint) else val for hint, val in zipln(pannot, args, fillvalue=pannot[-1])),
            **{a: kwannot[a](b) if a in kwannot and callable(kwannot[a]) else kwannot[None](b) for a, b in kwargs.items()}
            )
        conv = func.__annotations__.get('return')
        return conv(ret) if callable(conv) else ret
    return wrapper

# ----------------------------------------------------------------------------------- #

import asyncio
import concurrent

async def await_event_or_coro(bot, event, coro, *, ret_check=None, event_check=None, timeout=None):
    """
    discord.Client.wait_for, but force-cancels on completion of
    :param:coro rather than on a timeout
    """
    future = bot.loop.create_future()
    event_check = event_check or (lambda *_, **__: True)
    try:
        listeners = bot._listeners[event.lower()]
    except KeyError:
        listeners = []
        bot._listeners[event.lower()] = listeners
    listeners.append((future, event_check))
    [done], pending = await asyncio.wait([future, coro], timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED)
    for task in pending:
        task.cancel() # does this even do anything???
    try:
        which = 'coro' if event_check(*done.result()) else 'event'
    except TypeError:
        which = 'coro'
    return {which: done.result()}
    

async def wait_for_any(ctx, events, checks, *, timeout=15.0):
    """
    ctx: Context instance
    events: Sequence of events as outlined in dpy's event reference
    checks: Sequence of check functions as outlined in dpy's docs
    timeout: asyncio.wait timeout
    
    Params events and checks must be of equal length.
    """
    mapped = list(zip(events, checks))
    futures = [ctx.bot.wait_for(event, timeout=timeout, check=check) for event, check in mapped]
    [done], pending = await asyncio.wait(futures, loop=ctx.bot.loop, timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED)
    result = done.result()
    for event, check in mapped:
        try:
            # maybe just check(result) and force multi-param checks to unpack?
            valid = check(*result) if isinstance(result, tuple) else check(result)
        except (TypeError, AttributeError, ValueError): # maybe just except Exception
            continue
        if valid:
            return {event: result}
    return None

# ----------------------------------------------------------------------------------- #

# Typehint converter; truncates seq.
TRUNC = lambda end: lambda seq: seq[:end]
# TRUNC(end)(seq) -> seq[0:end]

@typecasted
def parse_args(args: list, regex: [compile], defaults: [object]) -> ([str], [str]):
    """
    Sorts `args` according to order in `regexes`.
    
    If no matches for a given regex are found in `args`, the item
    in `defaults` with the same index is dropped in to replace it.
    
    Extraneous arguments in `args` are left untouched, and the
    second item in this func's return tuple will consist of these
    extraneous args, if there are any.
    """
    assert len(regex) == len(defaults)
    new, regex = [], [i if isinstance(i, (list, tuple)) else [i] for i in regex]
    for ridx, rgx in enumerate(regex): 
        for aidx, arg in enumerate(args):
            if any(k.match(arg) for k in rgx):
                new.append(arg)
                args.pop(aidx)
                break
        else: 
             new.append(defaults[ridx])
    return new, args

@typecasted
def parse_flags(flags: list, *, prefix: TRUNC(1) = '-', delim: TRUNC(1) = ':') -> {str: str}:
    # FIXME: This ALMOST works perfectly. Fails when flags ==
    # ['-test', "-a:'", "bb", "'", "-bb:'aaa", "'", "-one:'", "two", "three", "four'"]
    # AKA "-test -a:' bb ' -bb:'aaa ' -one:' two three four'".split()
    # in case I screwed up transcribing to list
    op = f"{delim}'"
    openers = (i for i, v in enumerate(flags) if op in v)
    closers = (i for i, v in enumerate(flags) if v.endswith("'") and op not in v)
    while True:
        try:
            begin = next(openers)
        except (IndexError, StopIteration):
            break
        end = (
          next(closers)
            if flags[begin].endswith(op) and flags[begin].count(op) == 1
          else begin
            if flags[begin].endswith("'")
          else next(closers)
          )
        new = ' '.join(flags[begin:1+end])
        flags[begin:end] = ''
        flags[begin] = new.rstrip("'").replace(op, delim)
    # now just get 'em into a dict
    new = {}
    for v in (i.lstrip(prefix) for i in flags if i.startswith(prefix)):
        flag, opts = (v+delim[delim in v:]).split(delim, 1)
        new[flag] = opts
    return new

# ----------------------------------------------------------------------------------- #

import dis
import types

CODE_TYPE = type((lambda: None).__code__)

def attrify(func):
    """Assign nested callables to attributes of their enclosing function"""
    for nest in (types.FunctionType(i.argval, globals()) for i in dis.get_instructions(func) if type(i.argval) is CODE_TYPE):
        setattr(func, nest.__name__, nest)
    return func

# ----------------------------------------------------------------------------------- #

def chain(nested):
    """itertools.chain() but leave strings untouched"""
    for i in nested:
        if isinstance(i, (list, tuple)):
            yield from chain(i)
        else:
            yield i

# ------------- Custom command/group decos with info pointing to cmd.py ------------- #

import dis
import types

import discord
from discord.ext import commands

from .import cmd

class HelpAttrsMixin:
    @property
    def helpsafe_name(self):
        return self.qualified_name.replace(' ', '/')
    
    @property
    def invocation_args(self):
        return cmd.args.get(self.qualified_name, '')
    
    @property
    def aliases(self):
        return cmd.aliases.get(self.qualified_name, [])
    
    @aliases.setter
    def aliases(*_):
        """Eliminates "can't set attribute" when dpy tries assigning aliases"""

class Command(HelpAttrsMixin, commands.Command):
    def __init__(self, name, callback, **kwargs):
        self.parent = None
        cbc = callback.__code__
        self.loc = types.SimpleNamespace(
          file = cbc.co_filename,
          start = cbc.co_firstlineno - 1,
          end = max(i for _, i in dis.findlinestarts(cbc))
          )
        self.loc.len = self.loc.end - self.loc.start
        super().__init__(name, callback, **kwargs)

class Group(HelpAttrsMixin, commands.Group):
    def __init__(self, **attrs):
        self.parent = None
        cbc = attrs['callback'].__code__
        self.loc = types.SimpleNamespace(
          file = cbc.co_filename,
          start = cbc.co_firstlineno - 1,
          end = max(i for _, i in dis.findlinestarts(cbc))
          )
        self.loc.len = self.loc.end - self.loc.start
        super().__init__( **attrs)
    
    def command(self, *args, **kwargs):
        def decorator(func):
            res = commands.command(cls=Command, *args, **kwargs)(func)
            self.add_command(res)
            return res
        return decorator
    
    def group(self, *args, **kwargs):
        def decorator(func):
            res = commands.group(*args, **kwargs)(func)
            self.add_command(res)
            return res
        return decorator

def command(brief=None, name=None, cls=Command, **attrs):
    return lambda func: commands.command(name or func.__name__, cls, brief=brief, **attrs)(func)

def group(brief=None, name=None, *, invoke_without_command=True, **attrs):
    return command(brief, name, cls=Group, invoke_without_command=invoke_without_command, **attrs)

# ----------------------------- For uploading assets -------------------------------- #

import json

def extract_rule_info(fp):
    """
    Extract rulename and colors from a ruletable file.
    """
    fp.seek(0)
    in_colors = False
    name, n_states, colors  = None, 0, {}
    for line in (i.decode().strip() for i in fp):
        line, *_ = line.split('#')
        if not line:
            continue
        if line.startswith(('n_states:', 'num_states=')):
            n_states = int(line.split('=')[-1].split(':')[-1].strip())
            if n_states > 24:
                raise NotImplementedError('Rules with greater than 24 states not supported yet')
            continue
        if line.startswith('@RULE'):
            name = line.partition(' ')[-1]
            continue
        if name == '':
            # Captures rulename if on own line after @RULE
            name = line
            continue
        if line.startswith('@'):
            # makeshift state flag (indicates whether inside @COLORS declaration)
            in_colors = line.startswith('@COLORS')
            continue
        if in_colors:
            # '0    255 255 255   random comments' ->
            # {0: (255, 255, 255)}
            state, rgb = line.split(None, 1)
            colors[state] = tuple(map(int, rgb.split()[:3]))
    return name, n_states, json.dumps(colors or {'1': (0,0,0), '0': (255,255,255)})

# --------------------------- For rule-color shenanigans ---------------------------- #

class ColorRange:
    def __init__(self, n_states: int, start=(255,255,0), end=(255,0,0)):
        self.n_states = n_states
        self.start = start
        self.end = end
        self.avgs = [(final-initial)//n_states for initial, final in zip(start, end)]
    
    def at(self, state):
        if not 0 <= state <= self.n_states:
            raise ValueError('Requested state out of range')
        return tuple(initial+level*state for initial, level in zip(self.start, self.avgs))
    
    def __iter__(self):
        for state in range(self.n_states):
            yield tuple(initial+level*state for initial, level in zip(self.start, self.avgs))

def colorpatch(states: dict, n_states: int, bg, start=(255,255,0), end=(255,0,0)):
    # FIXME: Fails on rules with > 24 states because of min()/max() and chr()
    if n_states < 3:
        return {
          'o': states.get('1', (0,0,0)),
          'b': states.get('0', (255,255,255))
          }
    crange = ColorRange(n_states, start, end)
    return {'.' if i == '.' else chr(64+i): states.get(str(i), crange.at(i) if i else bg) for i in range(n_states)}

# -------------------------------------- Misc --------------------------------------- #

def scale(li, mul, chunk=1):
    """
    scale([a, b, c], 2) => (a, a, b, b, c, c)
    scale([a, b, c], 2, 3) => (a, b, c, a, b, c)
    """
    return tuple(j for i in zip(*[iter(li)]*chunk) for _ in range(mul) for j in i)
