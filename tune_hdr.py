#!/usr/bin/env python3
"""
tune_hdr.py — Hand-tune make_video.py's HLG -> SDR conversion on one frame,
with sliders.

Usage:
    python3 tune_hdr.py part2/media/IMG_0799.mov --config part2/storyboard.yaml [--time 2.0]

Grabs one frame from an HLG HDR clip (e.g. an iPhone .mov) and shows it in
a window with sliders for gain, gamma and saturation; the preview
re-renders shortly after you stop dragging (each render re-runs ffmpeg, so
expect a second or so). Each slider has a Revert button (back to its value
at startup); Undo steps back through your slider changes, one per drag;
Reset all restores all three. Compare it against the original in Photos/QuickTime.

"Save to config" writes the three values into the playlist's top-level
`hdr:` block (replacing an existing one, otherwise inserting it above
`items:`), which make_video.py reads on the next render — the rest of the
file, comments included, is left alone. Without --config the values are
just printed when you close the window. With --config, the sliders start
from that file's current `hdr:` values.

Requires ffmpeg on PATH, plus PyYAML and Pillow (see requirements.txt).
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

import yaml
from PIL import Image, ImageTk

import make_video

PREVIEW_WIDTH = 1280        # frame is downscaled to this for fast re-renders
MAX_DISPLAY = (1280, 720)   # and fitted inside this on screen
DEBOUNCE_MS = 150
SLIDERS = {                 # name: (min, max)
    "gain": (0.3, 3.0),
    "gamma": (0.6, 1.6),
    "saturation": (0.5, 2.5),
}

HDR_BLOCK_RE = re.compile(r"(?m)^hdr:[^\n]*\n(?:[ \t]+[^\n]*\n|[ \t]*\n)*")


def save_hdr_block(path, values):
    """Write `values` as the top-level `hdr:` block of the YAML file at
    `path` as plain text, so the rest of the file (comments, formatting) is
    untouched."""
    block = "hdr:\n" + "".join(f"  {k}: {values[k]:g}\n" for k in SLIDERS) + "\n"
    with open(path) as f:
        text = f.read()
    if HDR_BLOCK_RE.search(text):
        text = HDR_BLOCK_RE.sub(lambda _: block, text, count=1)
    elif re.search(r"(?m)^items:", text):
        text = re.sub(r"(?m)^items:", lambda _: block + "items:", text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + block
    with open(path, "w") as f:
        f.write(text)


def load_start_values(config_path):
    if not config_path:
        return dict(make_video.HDR_DEFAULTS)
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return make_video.hdr_settings(data)


class Tuner:
    def __init__(self, root, args, values):
        self.root, self.args = root, args
        self.png = os.path.join(tempfile.mkdtemp(prefix="tune_hdr_"), "frame.png")
        self.proc = None            # running ffmpeg, if any
        self.dirty = True           # slider changed since the last render started
        self.after_id = None
        self.photo = None

        root.title("tune_hdr")
        self.image_label = tk.Label(root, text="Rendering...", padx=40, pady=40)
        self.image_label.pack()

        controls = ttk.Frame(root, padding=8)
        controls.pack(fill="x")
        self.vars = {}
        for row, (name, (lo, hi)) in enumerate(SLIDERS.items()):
            ttk.Label(controls, text=name, width=11).grid(row=row, column=0, sticky="w")
            var = tk.DoubleVar(value=values[name])
            self.vars[name] = var
            scale = tk.Scale(
                controls, variable=var, from_=lo, to=hi, resolution=0.01,
                orient="horizontal", length=560, command=lambda _v: self.schedule(),
            )
            scale.grid(row=row, column=1, sticky="ew")
            # One undo step per drag, not per tick.
            scale.bind("<ButtonRelease-1>", lambda _e: self.commit())
            ttk.Button(controls, text="Revert", width=7,
                       command=lambda n=name: self.revert(n)).grid(row=row, column=2, padx=(6, 0))
        controls.columnconfigure(1, weight=1)

        buttons = ttk.Frame(root, padding=(8, 0, 8, 8))
        buttons.pack(fill="x")
        self.save_btn = ttk.Button(buttons, text="Save to config", command=self.save)
        self.save_btn.pack(side="left")
        if not args.config:
            self.save_btn.state(["disabled"])
        self.undo_btn = ttk.Button(buttons, text="Undo", command=self.undo)
        self.undo_btn.pack(side="left", padx=6)
        self.undo_btn.state(["disabled"])
        ttk.Button(buttons, text="Reset all", command=self.reset).pack(side="left")
        self.status = ttk.Label(
            buttons, text=f"Saves to {args.config}" if args.config
            else "No --config given: values print on close")
        self.status.pack(side="left", padx=8)

        self.start_values = dict(values)
        self.history = [self.values()]   # committed states, for Undo
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.schedule()
        self.poll()

    def values(self):
        return {name: round(var.get(), 2) for name, var in self.vars.items()}

    def schedule(self):
        self.dirty = True
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.after_id = self.root.after(DEBOUNCE_MS, self.maybe_render)

    def maybe_render(self):
        self.after_id = None
        if self.proc is not None or not self.dirty:
            return          # poll() re-renders once the running one finishes
        self.dirty = False
        self.rendered_values = self.values()
        vf = ",".join([f"scale={PREVIEW_WIDTH}:-2",
                       *make_video.hlg_to_sdr_vf(**self.rendered_values)])
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(self.args.time),
             "-i", self.args.source, "-frames:v", "1", "-vf", vf, self.png],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

    def poll(self):
        # Everything stays on Tk's own event loop (no threads): conda's
        # Tcl aborts with "Notifier not initialized" if other threads run.
        if self.proc is not None and self.proc.poll() is not None:
            err = self.proc.stderr.read().decode(errors="replace").strip()
            ok = self.proc.returncode == 0
            self.proc = None
            if ok:
                self.show()
            else:
                self.status.configure(text=f"ffmpeg failed: {err[-200:]}")
            if self.dirty:
                self.maybe_render()
        self.root.after(50, self.poll)

    def show(self):
        img = Image.open(self.png)
        img.thumbnail(MAX_DISPLAY)
        self.photo = ImageTk.PhotoImage(img)    # keep a reference
        self.image_label.configure(image=self.photo, text="", padx=0, pady=0)
        v = self.rendered_values
        self.root.title(f"tune_hdr — gain {v['gain']}  gamma {v['gamma']}  "
                        f"saturation {v['saturation']}")

    def commit(self):
        """Record the current values as an undo step (if they changed)."""
        values = self.values()
        if values != self.history[-1]:
            self.history.append(values)
            self.undo_btn.state(["!disabled"])

    def apply(self, values):
        for name, var in self.vars.items():
            var.set(values[name])
        self.schedule()

    def undo(self):
        if len(self.history) > 1:
            self.history.pop()
            self.apply(self.history[-1])
        if len(self.history) <= 1:
            self.undo_btn.state(["disabled"])

    def revert(self, name):
        """Put one slider back to the value it had when the tool started."""
        self.vars[name].set(self.start_values[name])
        self.commit()
        self.schedule()

    def reset(self):
        self.apply(self.start_values)
        self.commit()

    def save(self):
        values = self.values()
        save_hdr_block(self.args.config, values)
        self.status.configure(text=f"Saved {values} to {self.args.config}")

    def close(self):
        print(f"Final values: {self.values()}")
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="HLG HDR video to take a frame from")
    ap.add_argument("--config", help="playlist YAML to read/save the `hdr:` values in "
                                     "(e.g. part2/storyboard.yaml)")
    ap.add_argument("--time", type=float, default=1.0,
                    help="seconds into the clip to grab (default 1.0)")
    args = ap.parse_args()

    transfer = make_video.ffprobe_color_transfer(args.source)
    if transfer != make_video.HLG_TRANSFER:
        sys.exit(f"{args.source} isn't HLG HDR (color_transfer={transfer or 'unknown'}); "
                 f"nothing to tune.")

    root = tk.Tk()
    Tuner(root, args, load_start_values(args.config))
    root.mainloop()


if __name__ == "__main__":
    main()
