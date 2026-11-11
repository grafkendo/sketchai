"""Etch — deterministic vector sketch engine for AI agents (Phase 1 MVP)."""

# WHY the sys.path shim: this package uses bare sibling imports
# (``from components import ...``) so the modules also run standalone
# (``cd engine && python demo.py`` / ``python engine/mcp_server.py``).
# When installed via pip and imported as ``engine.mcp_server``, the engine
# directory isn't on sys.path — but this __init__ runs first, so registering
# it here keeps both the pip-installed and the direct-launch workflows alive.
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from components import COMPONENT_CATALOG, KNOWN_TYPES
from render import compose, content_hash, edit, find_node, to_pdf, to_png

__all__ = ["compose", "edit", "find_node", "content_hash", "to_png", "to_pdf",
           "COMPONENT_CATALOG", "KNOWN_TYPES"]
__version__ = "0.3.0"
