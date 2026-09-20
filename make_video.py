#!/usr/bin/env python3
"""
make_video.py — Assemble a vacation video from a simple YAML playlist of
video clips, photos, and map/route images.

Usage:
    python3 make_video.py playlist.yaml
    python3 make_video.py playlist.yaml -o my_vacation.mp4

Requires:
    - ffmpeg / ffprobe on PATH  (macOS: `brew install ffmpeg`)
    - Python 3.9+
    - PyYAML                    (`pip3 install pyyaml`)
    - Pillow                    (`pip3 install pillow`)
    - yt-dlp on PATH, only if `music:` is a URL (macOS: `brew install yt-dlp`)

See README.md and example_playlist.yaml for the playlist format.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: run  pip3 install pyyaml")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Missing dependency: run  pip3 install pillow")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def run(cmd, quiet=True):
    """Run a command, raising with full output on failure."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n\n{result.stdout}"
        )
    if not quiet:
        print(result.stdout)
    return result.stdout


def parse_timecode(value):
    """Accept seconds (int/float) or 'HH:MM:SS(.ms)' / 'MM:SS' strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    parts = value.split(":")
    parts = [float(p) for p in parts]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def ffprobe_duration(path):
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", path,
    ])
    return float(json.loads(out)["format"]["duration"])


def find_font():
    """Best-effort TrueType font path for caption text across macOS/Linux."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# --------------------------------------------------------------------------
# Segment builders — each produces a normalized .mp4 with matching
# resolution / fps / pixel format / audio layout so they can be concatenated.
# --------------------------------------------------------------------------

class Config:
    def __init__(self, data, base_dir):
        self.width, self.height = data.get("resolution", [1920, 1080])
        self.fps = data.get("fps", 30)
        self.photo_duration = float(data.get("photo_duration", 4.0))
        self.map_duration = float(data.get("map_duration", data.get("photo_duration", 6.0)))
        self.ken_burns = bool(data.get("ken_burns", True))
        self.transition = data.get("transition", "fade")  # "cut"/"none", or an ffmpeg xfade name
        self.transition_duration = float(data.get("transition_duration", 0.75))
        self.caption_font = find_font()
        self.caption_size = int(data.get("caption_font_size", 42))
        self.title_duration = float(data.get("title_duration", 3.0))
        self.title_font_size = int(data.get("title_font_size", 64))
        self.music = data.get("music")
        self.music_volume = float(data.get("music_volume", 0.25))
        self.base_dir = base_dir

    def resolve(self, path):
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)


def render_caption_png(cfg, text, out_path):
    """Render a caption (white text on a translucent box) to a transparent
    PNG the size of the output frame, positioned near the bottom-center.

    Composited onto segments with ffmpeg's 'overlay' filter, which is a
    core filter always available — unlike 'drawtext', which requires an
    ffmpeg build compiled with libfreetype (many Homebrew/conda builds
    omit it).
    """
    img = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if cfg.caption_font:
        font = ImageFont.truetype(cfg.caption_font, cfg.caption_size)
    else:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 16, 10
    box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
    box_x0 = (cfg.width - box_w) // 2
    box_y0 = cfg.height - box_h - 60

    draw.rectangle(
        [box_x0, box_y0, box_x0 + box_w, box_y0 + box_h],
        fill=(0, 0, 0, 115),
    )
    draw.text(
        (box_x0 + pad_x - bbox[0], box_y0 + pad_y - bbox[1]),
        text, font=font, fill=(255, 255, 255, 255),
    )
    img.save(out_path)


def build_video_segment(cfg, item, out_path, tmpdir):
    src = cfg.resolve(item["path"])
    start = parse_timecode(item.get("start", 0))
    end = parse_timecode(item.get("end"))
    duration = None
    if end is not None:
        duration = end - start

    vf_chain = ",".join([
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase",
        f"crop={cfg.width}:{cfg.height}",
        f"fps={cfg.fps}",
        "setsar=1",
    ])

    title = item.get("title")
    if duration is None and title:
        # A caption is composited from a still PNG looped with '-loop 1',
        # which never reaches EOF on its own. Without a known duration to
        # cap it with, ffmpeg can't reliably tell when to stop (relying on
        # '-shortest' here is not dependable across ffmpeg builds/filters),
        # so measure the source's own length up front.
        duration = ffprobe_duration(src) - start

    cmd = ["ffmpeg", "-y", "-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", src]

    if title:
        caption_png = os.path.join(tmpdir, f"cap_{os.path.basename(out_path)}.png")
        render_caption_png(cfg, title, caption_png)
        cmd += ["-loop", "1", "-t", str(duration), "-i", caption_png]
        filter_complex = (
            f"[0:v]{vf_chain}[vbase];"
            f"[vbase][1:v]overlay=0:0:format=auto[vout];"
            f"[0:a]aresample=async=1:first_pts=0[aout]"
        )
        cmd += ["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"]
    else:
        cmd += [
            "-vf", vf_chain,
            "-af", "aresample=async=1:first_pts=0",
        ]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        # Always produce an audio track so every segment has the same
        # streams, even if the source clip is silent/has no audio.
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest",
        out_path,
    ]
    run(cmd)


def build_still_segment(cfg, item, out_path, tmpdir, is_map):
    src = cfg.resolve(item["path"])
    default_dur = cfg.map_duration if is_map else cfg.photo_duration
    duration = float(item.get("duration", default_dur))

    # Ken Burns: slow zoom on photos; maps stay static so routes stay readable
    # unless explicitly requested.
    use_kb = cfg.ken_burns and not is_map and item.get("ken_burns", True)

    frames = int(duration * cfg.fps)
    if use_kb:
        # Upscale first so the zoom has headroom, then zoompan.
        zoom_vf = (
            f"scale=iw*2.4:ih*2.4,"
            f"zoompan=z='min(zoom+0.0012,1.3)':d={frames}:s={cfg.width}x{cfg.height}:fps={cfg.fps}"
        )
        vf_chain = ",".join([zoom_vf, "setsar=1"])
    else:
        vf_chain = ",".join([
            f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease",
            f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color=black",
            f"fps={cfg.fps}",
            "setsar=1",
        ])

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", src,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]

    title = item.get("title")
    if title:
        caption_png = os.path.join(tmpdir, f"cap_{os.path.basename(out_path)}.png")
        render_caption_png(cfg, title, caption_png)
        cmd += ["-loop", "1", "-t", str(duration), "-i", caption_png]
        filter_complex = f"[0:v]{vf_chain}[vbase];[vbase][2:v]overlay=0:0:format=auto[vout]"
        cmd += [
            "-t", str(duration),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "1:a",
        ]
    else:
        cmd += ["-t", str(duration), "-vf", vf_chain]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest",
        out_path,
    ]
    run(cmd)


def wrap_text(draw, text, font, max_width):
    """Greedy word-wrap so a title fits within max_width pixels."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def build_title_segment(cfg, item, out_path, tmpdir):
    """A full-frame title card: solid background + centered text. Used for
    section headers ('Day 1 — Bergen') rather than as a caption over media.
    """
    text = str(item.get("text", ""))
    duration = float(item.get("duration", cfg.title_duration))
    background = item.get("background", "#000000")
    text_color = item.get("text_color", "#FFFFFF")
    font_size = int(item.get("font_size", cfg.title_font_size))

    img = Image.new("RGB", (cfg.width, cfg.height), background)
    draw = ImageDraw.Draw(img)
    font = (
        ImageFont.truetype(cfg.caption_font, font_size)
        if cfg.caption_font else ImageFont.load_default()
    )

    lines = wrap_text(draw, text, font, max_width=int(cfg.width * 0.8))
    bboxes = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    line_heights = [b[3] - b[1] for b in bboxes]
    spacing = int(font_size * 0.3)
    total_h = sum(line_heights) + spacing * (len(lines) - 1)
    y = (cfg.height - total_h) // 2

    for ln, bbox, lh in zip(lines, bboxes, line_heights):
        line_w = bbox[2] - bbox[0]
        x = (cfg.width - line_w) // 2
        draw.text((x - bbox[0], y - bbox[1]), ln, font=font, fill=text_color)
        y += lh + spacing

    title_png = os.path.join(tmpdir, f"titlecard_{os.path.basename(out_path)}.png")
    img.save(title_png)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", title_png,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-vf", f"fps={cfg.fps},setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest",
        out_path,
    ]
    run(cmd)


def build_segments(cfg, items, tmpdir):
    segment_paths = []
    for i, item in enumerate(items):
        kind = item["type"]
        out_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        label = item.get("title") or item.get("text") or os.path.basename(item.get("path", kind))
        print(f"[{i+1}/{len(items)}] {kind}: {label}")
        if kind == "video":
            build_video_segment(cfg, item, out_path, tmpdir)
        elif kind == "photo":
            build_still_segment(cfg, item, out_path, tmpdir, is_map=False)
        elif kind == "map":
            build_still_segment(cfg, item, out_path, tmpdir, is_map=True)
        elif kind == "title":
            build_title_segment(cfg, item, out_path, tmpdir)
        else:
            raise ValueError(f"Unknown item type: {kind!r}")
        segment_paths.append(out_path)
    return segment_paths


# --------------------------------------------------------------------------
# Joining segments
# --------------------------------------------------------------------------

def concat_no_transition(segment_paths, tmpdir, out_path):
    list_file = os.path.join(tmpdir, "concat_list.txt")
    with open(list_file, "w") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", out_path,
    ])


def resolve_transition(cfg, item):
    """The transition used to cut INTO `item` from the one before it.

    Returns (kind, duration). kind is either "cut" (instant jump cut, no
    blend) or the name of an ffmpeg 'xfade' transition (e.g. "fade",
    "wipeleft", "dissolve", ...). An item can override the playlist's
    top-level `transition` / `transition_duration` just for its own
    incoming boundary.
    """
    kind = item.get("transition", cfg.transition)
    duration = float(item.get("transition_duration", cfg.transition_duration))
    if kind in ("none", "cut") or duration <= 0:
        return ("cut", 0.0)
    return (kind, duration)


def concat_with_transitions(segment_paths, durations, transitions, out_path):
    """Join segments where each boundary is independently either a hard cut
    (ffmpeg's 'concat' filter) or a named crossfade ('xfade' + 'acrossfade').
    `transitions[i]` describes the boundary going INTO segment i+1.
    """
    n = len(segment_paths)
    inputs = []
    for p in segment_paths:
        inputs += ["-i", p]

    filter_parts = []
    # Normalize every segment's timebase up front. Mixing the 'concat'
    # filter (hard cuts) with 'xfade' (crossfades) in the same graph
    # otherwise fails ffmpeg's "First input link main timebase ... do not
    # match" check, because concat's output timebase differs from a raw
    # decoded stream's.
    for i in range(n):
        filter_parts.append(f"[{i}:v]settb=AVTB[v{i}n]")
        filter_parts.append(f"[{i}:a]asettb=AVTB[a{i}n]")

    v_prev, a_prev = "v0n", "a0n"
    accumulated = durations[0]

    for i in range(1, n):
        kind, d = transitions[i - 1]
        v_cur, a_cur = f"v{i}n", f"a{i}n"
        v_out, a_out = f"vout{i}", f"aout{i}"
        if kind == "cut":
            filter_parts.append(
                f"[{v_prev}][{a_prev}][{v_cur}][{a_cur}]concat=n=2:v=1:a=1[{v_out}][{a_out}]"
            )
            accumulated = accumulated + durations[i]
        else:
            offset = accumulated - d
            filter_parts.append(
                f"[{v_prev}][{v_cur}]xfade=transition={kind}:duration={d}:offset={offset}[{v_out}]"
            )
            filter_parts.append(f"[{a_prev}][{a_cur}]acrossfade=d={d}[{a_out}]")
            accumulated = offset + durations[i]
        v_prev, a_prev = v_out, a_out

    filter_complex = ";".join(filter_parts)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex,
           "-map", f"[{v_prev}]", "-map", f"[{a_prev}]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", out_path]
    run(cmd)


def resolve_music_source(cfg):
    """Return a local audio file path for cfg.music.

    A local path is resolved relative to the playlist as usual. A URL
    (e.g. a YouTube link) is downloaded via yt-dlp into a cache directory
    next to the playlist, keyed by a hash of the URL, so re-running on
    the same playlist doesn't re-download the track every time.
    """
    if not cfg.music.startswith(("http://", "https://")):
        return cfg.resolve(cfg.music)

    if shutil.which("yt-dlp") is None:
        sys.exit("Missing dependency: music is a URL, run  brew install yt-dlp  (or  pip3 install yt-dlp)")

    cache_dir = os.path.join(cfg.base_dir, ".music_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(cfg.music.encode()).hexdigest()[:16]
    cache_path = os.path.join(cache_dir, f"{key}.mp3")
    if not os.path.exists(cache_path):
        run(["yt-dlp", "-x", "--audio-format", "mp3",
             "-o", os.path.join(cache_dir, f"{key}.%(ext)s"), cfg.music])
    return cache_path


def add_music(cfg, video_path, out_path):
    music_path = resolve_music_source(cfg)
    total_dur = ffprobe_duration(video_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex",
        f"[1:a]volume={cfg.music_volume},afade=t=out:st={max(total_dur-2,0)}:d=2[music];"
        f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-t", str(total_dur),
        out_path,
    ]
    run(cmd)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("playlist", help="Path to the YAML playlist file")
    ap.add_argument("-o", "--output", help="Output video path (overrides playlist 'output')")
    ap.add_argument("--keep-temp", action="store_true", help="Keep intermediate segment files (for debugging)")
    args = ap.parse_args()

    with open(args.playlist) as f:
        data = yaml.safe_load(f)

    base_dir = os.path.dirname(os.path.abspath(args.playlist))
    cfg = Config(data, base_dir)
    items = data["items"]
    if not items:
        sys.exit("Playlist has no items.")

    output_path = args.output or data.get("output", "vacation_video.mp4")
    if not os.path.isabs(output_path):
        output_path = os.path.join(base_dir, output_path)

    tmpdir = tempfile.mkdtemp(prefix="vacation_video_")
    try:
        segment_paths = build_segments(cfg, items, tmpdir)
        durations = [ffprobe_duration(p) for p in segment_paths]

        print("Joining segments...")
        joined_path = os.path.join(tmpdir, "joined.mp4")
        if len(segment_paths) == 1:
            concat_no_transition(segment_paths, tmpdir, joined_path)
        else:
            transitions = [resolve_transition(cfg, item) for item in items[1:]]
            if all(kind == "cut" for kind, _ in transitions):
                # No blending anywhere: the plain concat demuxer is faster
                # (stream copy, no re-encode) and produces the same result.
                concat_no_transition(segment_paths, tmpdir, joined_path)
            else:
                concat_with_transitions(segment_paths, durations, transitions, joined_path)

        if cfg.music:
            print("Mixing background music...")
            add_music(cfg, joined_path, output_path)
        else:
            shutil.copy(joined_path, output_path)

        print(f"\nDone -> {output_path}")
        print(f"Total duration: {ffprobe_duration(output_path):.1f}s")
    finally:
        if args.keep_temp:
            print(f"(intermediate files kept in {tmpdir})")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
