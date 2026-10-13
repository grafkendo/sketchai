#!/usr/bin/env python3
"""
Etch engine — imagegen.py

Diffusion bridge (interface only). Image nodes may carry `gen_prompt`
instead of `src`; this module resolves the prompt into a local image file
whose path becomes the node's src before render validation runs.

Provider selection via ETCH_IMAGE_PROVIDER:
- "none" (default): gen_prompt is an error naming the missing provider.
- "command": runs ETCH_IMAGE_COMMAND with {prompt} and {out} placeholders;
  the command must write an image file to {out}, which becomes the slot's
  asset.

WHY a command and not an HTTP API: Etch makes zero network calls by design
(deterministic renders, no keys in the engine). The user points the command
at their own local ComfyUI / sd-cli / script; Etch shells out and reads the
file back. NO external API calls, NO image services, NO keys — the command
IS the whole bridge.

Determinism: resolved assets are cached under engine/assets/generated/,
keyed by sha256(command + prompt). Same prompt + same command = same file
on disk = same content_hash downstream. The cache also means a re-render
never re-runs the (slow, possibly non-deterministic) generator.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess

from PIL import Image

from components import EtchError

GENERATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "generated")


class ImageGenError(EtchError):
    pass


def _provider() -> str:
    return os.environ.get("ETCH_IMAGE_PROVIDER", "none").strip().lower()


def resolve_gen_prompt(node_id: str | None, prompt: str) -> str:
    """Resolve a gen_prompt to a local image file path. Raises ImageGenError
    naming the node and the fix when no provider is configured."""
    provider = _provider()
    if provider == "none":
        raise ImageGenError(
            node_id,
            "gen_prompt needs an image provider (ETCH_IMAGE_PROVIDER is 'none')",
            "Set ETCH_IMAGE_PROVIDER=command and ETCH_IMAGE_COMMAND to a "
            "template with {prompt} and {out} placeholders, e.g. "
            "'python my_gen.py --prompt {prompt} --out {out}'.")
    if provider == "command":
        return _resolve_via_command(node_id, prompt)
    raise ImageGenError(
        node_id, f"unknown ETCH_IMAGE_PROVIDER '{provider}'",
        "Use 'none' or 'command'.")


def _resolve_via_command(node_id: str | None, prompt: str) -> str:
    command = os.environ.get("ETCH_IMAGE_COMMAND", "").strip()
    if not command:
        raise ImageGenError(
            node_id,
            "ETCH_IMAGE_PROVIDER=command but ETCH_IMAGE_COMMAND is not set",
            "Set ETCH_IMAGE_COMMAND to a template with {prompt} and {out} "
            "placeholders, e.g. 'python my_gen.py --prompt {prompt} --out {out}'.")
    if "{prompt}" not in command or "{out}" not in command:
        raise ImageGenError(
            node_id,
            "ETCH_IMAGE_COMMAND must contain {prompt} and {out} placeholders",
            f"Got: {command!r} — add both placeholders so Etch can pass the "
            "prompt in and read the image back out.")
    # WHY the cache key includes the command: changing the generator must
    # not silently reuse images made by the old one.
    key = hashlib.sha256(f"{command}\n{prompt}".encode()).hexdigest()[:16]
    os.makedirs(GENERATED_DIR, exist_ok=True)
    out_path = os.path.join(GENERATED_DIR, f"gen_{key}.png")
    if os.path.isfile(out_path):
        return out_path  # cache hit — never re-run the generator
    # WHY shlex.split + no shell: the prompt is agent-supplied text; shell=True
    # would let a crafted prompt execute arbitrary commands. Substituting
    # after the split keeps {prompt} as exactly one argv element.
    argv = [part.replace("{prompt}", prompt).replace("{out}", out_path)
            for part in shlex.split(command, posix=True)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        raise ImageGenError(
            node_id, f"image command not found: {argv[0]!r}",
            "Check the program in ETCH_IMAGE_COMMAND is installed and on PATH.")
    except subprocess.TimeoutExpired:
        raise ImageGenError(
            node_id, "image command timed out after 600s",
            "Point ETCH_IMAGE_COMMAND at a faster generator or pre-generate "
            "the asset and use src instead.")
    if proc.returncode != 0 or not os.path.isfile(out_path):
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise ImageGenError(
            node_id,
            f"image command failed (exit {proc.returncode}): {detail}",
            "The command must exit 0 and write an image file to {out}.")
    # WHY verify: a command that writes a text file to {out} would otherwise
    # die deep in the SVG writer with a confusing error.
    try:
        with Image.open(out_path) as im:
            im.verify()
    except Exception:
        os.remove(out_path)
        raise ImageGenError(
            node_id, f"command output is not a valid image: {out_path}",
            "The command must write a real image file (PNG/JPEG) to {out}.")
    return out_path


def resolve_node(node: dict) -> bool:
    """Resolve one node's gen_prompt into src. Returns True if it resolved
    anything. Nodes that already have src are left alone — an explicit src
    always wins over gen_prompt."""
    if node.get("type") == "image" and node.get("gen_prompt") and not node.get("src"):
        node["src"] = resolve_gen_prompt(node.get("node_id"), node["gen_prompt"])
        return True
    return False
