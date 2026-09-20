# Vacation Video Maker

Turn a list of exported video clips, photos, and map/route images into one
finished vacation video — trimmed, ordered, captioned, and transitioned
together.

Claude can't reach your Photos library directly, so this works in two steps:
you export the media you want (from Photos, or wherever it lives) into a
folder, then this script assembles it from a simple text playlist.

## 1. One-time setup (on your Mac)

```bash
brew install ffmpeg
pip3 install pyyaml pillow
```

If you want background music pulled straight from a YouTube (or other)
URL instead of a local file, also install
[yt-dlp](https://github.com/yt-dlp/yt-dlp):

```bash
brew install yt-dlp
```

## 2. Export your media from Photos

For each clip/photo/map you want in the video:
- **Videos & photos:** select them in Photos → File → Export → Export
  Unmodified (or "Export N Photos/Videos") → save into a folder, e.g.
  `~/Movies/iceland-trip/clips` and `~/Movies/iceland-trip/photos`.
- **Maps/routes:** screenshot or export the map image (from Apple/Google
  Maps, AllTrails, a GPS app, etc.) as a PNG/JPG into e.g.
  `~/Movies/iceland-trip/maps`.

You don't need to trim clips in Photos first — just export the whole clip
and tell the script which portion to use (see below).

## 3. Write your playlist

Copy `example_playlist.yaml` to something like `my_trip.yaml` and list your
media in the order you want it to appear:

```yaml
output: vacation_video.mp4
resolution: [1920, 1080]
fps: 30
transition: fade

items:
  - type: title
    text: "Portugal, June 2026"
    duration: 3

  - type: video
    path: clips/arrival.mov
    start: "00:00:05"     # only use this part of the source clip
    end: "00:00:32"
    title: "Landing in Lisbon"

  - type: photo
    path: photos/hotel_view.jpg
    title: "The view from our room"
    duration: 6            # override the default photo duration for just this one

  - type: map
    path: maps/day1_route.png
    title: "Day 1 — Alfama walking route"
    transition: wipeleft   # a different transition into just this item
```

Paths are relative to wherever the `.yaml` file lives. Full item format:

| Field | Applies to | Meaning |
|---|---|---|
| `type` | all | `video`, `photo`, `map`, or `title` |
| `path` | video, photo, map | path to the source file (not used by `title`) |
| `title` | video, photo, map, optional | on-screen caption overlaid on the media |
| `text` | title | the text shown on a full-frame title card (supports `\n` for line breaks; long lines wrap automatically) |
| `start`, `end` | video | portion of the clip to use — seconds or `HH:MM:SS`. **Omit both to use the entire clip start-to-finish** (no need to time it in another app first). |
| `duration` | photo, map, title | how long to show it, in seconds — **overrides the playlist-wide default for just this item** (default: `photo_duration` / `map_duration` / `title_duration`) |
| `ken_burns` | photo | set `false` to disable the slow zoom for just this photo |
| `background` | title, optional | background color, e.g. `"#000000"` (default: black) |
| `text_color` | title, optional | text color (default: white) |
| `font_size` | title, optional | overrides `title_font_size` for just this card |
| `transition` | any item after the first, optional | transition used to cut **into** this item from the one before it — overrides the playlist-wide default for just this boundary. `cut` (or `none`) is an instant jump cut with no blend; anything else is the name of an ffmpeg `xfade` transition (see below) |
| `transition_duration` | same as above, optional | overrides the playlist-wide default duration for just this boundary (ignored for `cut`/`none`) |

Top-level settings (all optional, shown with defaults):

| Setting | Default | Meaning |
|---|---|---|
| `output` | `vacation_video.mp4` | output filename |
| `resolution` | `[1920, 1080]` | output size |
| `fps` | `30` | output frame rate |
| `photo_duration` | `4.0` | default seconds per photo |
| `map_duration` | `6.0` | default seconds per map |
| `title_duration` | `3.0` | default seconds per title card |
| `title_font_size` | `64` | default title card text size |
| `ken_burns` | `true` | slow zoom/pan on photos (maps and titles stay static) |
| `transition` | `fade` | default transition between every pair of items (see below) |
| `transition_duration` | `0.75` | default crossfade length in seconds |
| `music` | *(none)* | path to a background audio track, or a URL (e.g. YouTube) — looped/trimmed to fit |
| `music_volume` | `0.25` | relative volume of the music under clip audio |

### Music

`music` accepts either a local file path or a URL (YouTube and anything
else [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports):

```yaml
music: audio/vacation_theme.mp3
# or
music: https://youtu.be/dQw4w9WgXcQ
```

A URL requires `yt-dlp` on your PATH (see setup above). The audio is
downloaded once into a `.music_cache/` folder next to the playlist and
reused on later runs of the same playlist, so re-rendering while you
tweak the video doesn't re-download it. Delete `.music_cache/` if you
change the URL and want a fresh download.

### Transitions

`transition` (top-level, or per-item to override just one boundary) is either:
- `cut` or `none` — an instant jump cut, no blending
- the name of an ffmpeg `xfade` transition — most commonly `fade`,
  `dissolve`, `wipeleft`/`wiperight`/`wipeup`/`wipedown`,
  `slideleft`/`slideright`/`slideup`/`slidedown`, `circleopen`/`circleclose`,
  `pixelize`, `radial`, `hblur`. The full list (there are dozens more) is in
  the [ffmpeg xfade docs](https://ffmpeg.org/ffmpeg-filters.html#xfade).

You can mix and match freely — e.g. fades everywhere by default, with one
particular cut to a hard jump for effect:

```yaml
transition: fade   # the default for the whole video

items:
  - type: video
    path: clips/a.mov
  - type: video
    path: clips/b.mov
    transition: cut       # hard cut into this clip specifically
  - type: photo
    path: photos/c.jpg
    transition: wipeleft  # a wipe into this one instead
```

## 4. Build the video

```bash
python3 make_video.py my_trip.yaml
```

It normalizes every clip/photo/map/title to the same resolution and frame
rate, applies the transitions between them, mixes in music if you set one,
and writes the final `.mp4` next to your playlist. Progress prints as it
goes; a ~5-minute video with a dozen items typically takes a few minutes to
render.

Useful flags:
- `-o out.mp4` — override the output path
- `--keep-temp` — keep the intermediate per-item clips (for debugging)

## Tips

- Order the `items` list exactly as you want the final video to play —
  reordering the video is just reordering this list.
- For a clip where you want the whole thing, omit `start`/`end`.
- Maps default to a longer, static display (no zoom) so routes stay
  readable; add `ken_burns: true` on a specific map item if you want it
  panned anyway.
- Use `type: title` for section headers ("Day 2: The Fjords") between groups
  of clips — no media file needed, just `text`.
- Captions are drawn with Pillow and composited onto each clip, so they
  work no matter how your ffmpeg build was compiled (some Homebrew/conda
  builds omit ffmpeg's own `drawtext` filter — this script no longer relies
  on it). If captions look wrong, it's likely no system font was found —
  open an issue with your OS and we can point `make_video.py` at the right
  font file.
