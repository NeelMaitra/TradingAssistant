"""Load the baseline trader-skill tools from .claude/skills/<folder>/<name>.py.

The baseline skills (MIT, Jake Schincariol) live in .claude/skills so Claude Code
can use them directly as project skills. The scanner reuses their parsers
(news + 8-K feeds, SEC XBRL facts, NYSE calendar) instead of copying them.
"""

import importlib.util
import os
import sys

from .config import ROOT

SKILLS = os.path.join(ROOT, ".claude", "skills")
_cache = {}


def load(folder, name):
    key = (folder, name)
    if key in _cache:
        return _cache[key]
    path = os.path.join(SKILLS, folder, name + ".py")
    if not os.path.isfile(path):
        raise ImportError("baseline tool missing: %s" % path)
    spec = importlib.util.spec_from_file_location("baseline_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _cache[key] = mod
    return mod
