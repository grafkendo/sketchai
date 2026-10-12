"""Etch — deterministic vector sketch engine for AI agents (Phase 1 MVP)."""
from components import COMPONENT_CATALOG, KNOWN_TYPES
from render import compose, content_hash, edit, find_node, to_pdf, to_png

__all__ = ["compose", "edit", "find_node", "content_hash", "to_png", "to_pdf",
           "COMPONENT_CATALOG", "KNOWN_TYPES"]
__version__ = "0.1.0"
