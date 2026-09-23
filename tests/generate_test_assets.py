#!/usr/bin/env python3
"""
Generate small synthetic clips/photos/map images with ffmpeg's built-in
test-pattern sources, so make_video.py can be smoke-tested without needing
anyone's real vacation photos.

Usage:
    python3 tests/generate_test_assets.py

Writes into tests/fixtures/ (safe to delete and regenerate at any time).
"""

import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stdout}")


def main():
    clips = os.path.join(FIXTURES, "clips")
    photos = os.path.join(FIXTURES, "photos")
    maps_ = os.path.join(FIXTURES, "maps")
    for d in (clips, photos, maps_):
        os.makedirs(d, exist_ok=True)

    print("Generating clip1.mp4 (8s test pattern + tone)...")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        os.path.join(clips, "clip1.mp4"),
    ])

    print("Generating clip2.mp4 (8s bars + tone)...")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "smptebars=size=960x540:rate=24:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=8",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        os.path.join(clips, "clip2.mp4"),
    ])

    print("Generating clip3.mp4 (5s portrait test pattern + tone, for fit: contain)...")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        os.path.join(clips, "clip3.mp4"),
    ])

    print("Generating photo1.jpg / photo2.jpg...")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:size=1600x1200",
         "-frames:v", "1", os.path.join(photos, "photo1.jpg")])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:size=1600x1200",
         "-frames:v", "1", os.path.join(photos, "photo2.jpg")])

    print("Generating photo3.jpg (portrait, for fit: contain)...")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:size=1200x1600",
         "-frames:v", "1", os.path.join(photos, "photo3.jpg")])

    print("Generating map1.png...")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=beige:size=1400x1000",
         "-frames:v", "1", os.path.join(maps_, "map1.png")])

    print("Generating music.mp3 (6s tone, looped by make_video.py as needed)...")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=523:duration=6",
        "-c:a", "libmp3lame", os.path.join(FIXTURES, "music.mp3"),
    ])

    print(f"Done -> {FIXTURES}")


if __name__ == "__main__":
    main()
