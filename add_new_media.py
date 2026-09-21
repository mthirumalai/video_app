#!/usr/bin/env python3
"""
add_new_media.py — Scan a media folder for files not yet in a storyboard
playlist and append them as new items, so you don't have to hand-type an
entry for every new export.

Usage:
    python3 add_new_media.py storyboard.yaml media/

New items are appended to the end of the playlist's "items" list as plain
text (the file isn't parsed and rewritten), so your existing formatting
and comments are left untouched. Each new item gets its type inferred
(see make_video.py's infer_type) and its optional fields added, commented
out, for you to fill in and uncomment as needed:

    - path: media/IMG_0710.mov
      # start: "00:00:00"
      # end: "00:00:00"
      # title: ""

Requires:
    - PyYAML (`pip3 install pyyaml`)

See README.md for the playlist format.
"""

import argparse
import os
import sys

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: run  pip3 install pyyaml")

import make_video as mv

HIDDEN_PREFIXES = (".",)


def existing_paths(data, base_dir):
    """Absolute paths of every item already referenced in the playlist."""
    paths = set()
    for item in data.get("items") or []:
        path = item.get("path")
        if path is None:
            continue
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        paths.add(os.path.abspath(path))
    return paths


def find_new_files(media_dir, already_referenced):
    new_files = []
    for name in sorted(os.listdir(media_dir)):
        if name.startswith(HIDDEN_PREFIXES):
            continue
        full_path = os.path.join(media_dir, name)
        if not os.path.isfile(full_path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in mv.VIDEO_EXTENSIONS and ext not in mv.IMAGE_EXTENSIONS:
            print(f"Skipping {name} (unrecognized extension {ext!r})")
            continue
        if os.path.abspath(full_path) in already_referenced:
            continue
        new_files.append(full_path)
    return new_files


def render_item(path, base_dir, photo_duration, map_duration):
    rel_path = os.path.relpath(path, base_dir)
    kind = mv.infer_type({"path": rel_path})
    lines = [f"  - path: {rel_path}"]
    if kind == "video":
        lines += [
            '    # start: "00:00:00"',
            '    # end: "00:00:00"',
            '    # title: ""',
        ]
    else:
        default_duration = map_duration if kind == "map" else photo_duration
        lines += [
            f"    # duration: {default_duration}",
            '    # title: ""',
        ]
    return kind, "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("playlist", help="Path to the YAML storyboard/playlist file")
    ap.add_argument("media_dir", help="Folder to scan for new media files")
    args = ap.parse_args()

    with open(args.playlist) as f:
        data = yaml.safe_load(f)

    base_dir = os.path.dirname(os.path.abspath(args.playlist))
    photo_duration = data.get("photo_duration", 4.0)
    map_duration = data.get("map_duration", data.get("photo_duration", 6.0))

    already_referenced = existing_paths(data, base_dir)
    new_files = find_new_files(args.media_dir, already_referenced)

    if not new_files:
        print("No new files found.")
        return

    blocks = []
    for path in new_files:
        kind, block = render_item(path, base_dir, photo_duration, map_duration)
        blocks.append(block)
        rel_path = os.path.relpath(path, base_dir)
        print(f"+ {rel_path} ({kind})")

    with open(args.playlist, "a") as f:
        f.write("\n" + "\n".join(blocks))

    print(f"\nAppended {len(new_files)} item(s) to {args.playlist}")


if __name__ == "__main__":
    main()
