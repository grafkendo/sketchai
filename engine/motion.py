#!/usr/bin/env python3
"""
Etch engine — motion.py

Frame-sequence animation: N render PNGs -> one animated GIF.

WHY GIF (not MP4): zero native dependencies — Pillow writes GIFs with no
ffmpeg, no system libraries. The output is deterministic: same frames in
the same order at the same frame duration always produce byte-identical
GIFs (the format carries no timestamps). MP4 would need an external
encoder and would break the "pip install and go" story.

The natural input is a storyboard (sketch_sequence render_ids) or any
explicit render_id list — e.g. successive sketch_edit versions of one
scene, which animates "the design converging" frame by frame.
"""

from __future__ import annotations

import hashlib
import io
import os

from PIL import Image

from components import EtchError

ANIMATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "animated")


class MotionError(EtchError):
    pass


def animate_gif(png_frames: list[bytes], ms_per_frame: int,
               out_path: str | None = None) -> dict:
    """Assemble PNG frames into an animated GIF.

    Returns {"path", "frames", "ms_per_frame", "bytes"}. Frame order is the
    input order. Raises MotionError on empty frames or non-positive
    duration — a 0ms GIF is a spec violation, not a fast animation.
    """
    if not png_frames:
        raise MotionError(None, "no frames provided",
                          "Pass 2+ PNGs — e.g. render_ids from sketch_sequence.")
    if not isinstance(ms_per_frame, int) or ms_per_frame <= 0:
        raise MotionError(
            None, f"ms_per_frame must be a positive int, got {ms_per_frame!r}",
            "Try ms_per_frame=500 for a half-second beat per frame.")
    frames = [Image.open(io.BytesIO(p)).convert("RGB") for p in png_frames]
    # WHY RGB (not P): GIF is palette-based; letting Pillow quantize from
    # RGB keeps the conversion deterministic across runs.
    if out_path is None:
        seed = "|".join(hashlib.sha256(p).hexdigest() for p in png_frames)
        seed += f"|{ms_per_frame}"
        name = "animated_" + hashlib.sha256(seed.encode()).hexdigest()[:16] + ".gif"
        os.makedirs(ANIMATED_DIR, exist_ok=True)
        out_path = os.path.join(ANIMATED_DIR, name)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                    duration=ms_per_frame, loop=0)
    with open(out_path, "rb") as f:
        data = f.read()
    return {"path": out_path, "frames": len(frames),
            "ms_per_frame": ms_per_frame, "bytes": len(data)}


def gif_frame_count(gif_bytes: bytes) -> int:
    """Count frames in a GIF (test helper)."""
    im = Image.open(io.BytesIO(gif_bytes))
    n = 0
    try:
        while True:
            n += 1
            im.seek(n)
    except EOFError:
        pass
    return n
