"""depth_ctx.py -- the size of the answer being written (MATTER_WORKSPACE_PLAN.md W2), kept for the length of one question in a thread-local so that the places that spend money (the scope check, the AI Act detection,
the wider search, the verbatim excerpts, the judgments, the second answer, the thinking) can ask 'is this a research answer?' without a new parameter. Light on purpose: no imports of the engine.

Sizes: None (no size was chosen: everything as before), 'file', 'explain', 'standard', 'research', 'smalltalk'. Only 'standard' skips things on the full path (the file and explain sizes never run it):
  skip_scope()      no scope check (a question in a matter that holds documents is in scope; the gate is open on the site)
  skip_ai_act()     no Haiku pass to guess the Act (the word pass is free and stays)
  skip_wider()      no wider search, no fed judgments
  skip_cases()      no judgments of the library, no verbatim anchor excerpts, no pilot list: the law on hand only
  no_regen()        an untraceable section number is removed by code, a missing Act name or companion is added by code: never a second paid answer
  effort()          'low' (thinking) for every size below research
"""
import threading

_LOCAL = threading.local()
LOW = ("file", "explain", "standard")


def set_depth(d):
    _LOCAL.depth = d if d in ("file", "explain", "standard", "research", "smalltalk") else None


def depth():
    return getattr(_LOCAL, "depth", None)


def is_standard():
    return depth() == "standard"


skip_scope = skip_ai_act = skip_wider = skip_cases = no_regen = is_standard


def effort():
    return "low" if depth() in LOW else None
