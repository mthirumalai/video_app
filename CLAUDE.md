# CLAUDE.md

Guidance for Claude Code (or any future session) working in this repo.

## What this is

A small Python tool (`make_video.py`) that assembles a vacation video from
exported video clips, photos, and map/route screenshots, driven by a YAML
"playlist" file. It exists because Claude has no direct access to a Photos
library — the user exports media by hand into a folder, then this script
handles trimming, captioning, sequencing, transitions, and (optional)
background music. A companion script, `add_new_media.py`, scans a media
folder for files a playlist doesn't reference yet and appends items for
them, so growing a playlist doesn't mean hand-typing every new export.

User-facing docs — playlist format, setup, examples — live in `README.md`
and `example_playlist.yaml`. Read those before changing anything the user
sees; this file is about how the code itself works and what not to break.

## Setup

```bash
pip3 install -r requirements.txt   # pyyaml, pillow
brew install ffmpeg                # or any ffmpeg with libx264/aac
```

## Architecture (all in `make_video.py`)

1. `Config` — parses top-level playlist settings (resolution, fps,
   per-type defaults, transition defaults, music).
2. Segment builders — each turns ONE playlist item into a normalized
   `.mp4` (matching resolution / fps / pixel format / audio layout) in a
   temp dir, so segments can later be concatenated:
   - `build_video_segment` — trims a source clip to `start`/`end` (or uses
     the whole clip if both are omitted), optionally composites a caption.
   - `build_still_segment` — turns a photo/map into a video segment;
     photos get a Ken Burns zoom (`zoompan`), maps stay static so routes
     stay readable.
   - `build_title_segment` — renders a full-frame solid-background +
     centered, word-wrapped text card via Pillow. No source media.
3. `build_segments` dispatches each item to the right builder by `type`.
4. Joining — `concat_no_transition` (fast path, stream copy, used when
   every boundary is a hard cut) or `concat_with_transitions` (builds a
   `filter_complex` chain where each boundary is independently either a
   hard cut or a named `xfade` crossfade). `resolve_transition` decides
   cut-vs-blend per item, falling back to the playlist's top-level
   `transition`/`transition_duration` when an item doesn't override them.
5. `add_music` — optional background track, looped/trimmed and mixed in
   after joining.

`-nop`/`--dry-run` short-circuits `main()` into `validate_playlist`
instead of the pipeline above: it checks every item's `type` (explicit or
inferred), required fields, and `start`/`end`/`duration` parse, and that
every referenced media file exists on disk — no ffmpeg/ffprobe calls, no
temp dir. Keep it in sync with whatever a real render actually requires
(e.g. a new required field on an item type needs a check added here too).

`infer_type` and the `VIDEO_EXTENSIONS`/`IMAGE_EXTENSIONS` sets let `type`
be omitted on a playlist item (see the README). `add_new_media.py`
imports `make_video` and reuses these directly rather than duplicating
the classification logic — keep them as the single source of truth if
you touch either script.

## Gotchas already paid for — don't reintroduce these

- **No `drawtext` filter on some ffmpeg builds.** Many Homebrew/conda
  builds are compiled without `libfreetype`, so ffmpeg's `drawtext` filter
  doesn't exist at all (fails with "No such filter: 'drawtext'"). Captions
  are rendered as transparent PNGs with Pillow (`render_caption_png`) and
  composited with the `overlay` filter instead, which is a core filter
  always available. Don't switch captions back to `drawtext`.
- **`-shortest` is not reliable** when a filter graph includes an
  infinitely-looped image input (`-loop 1`, used for every caption and
  still-image segment). Relying on it can make ffmpeg run indefinitely
  instead of stopping at the intended duration. Always compute an explicit
  duration up front (via ffprobe if it isn't given directly, e.g. a
  captioned video with no `end`) and pass `-t` to every relevant input
  *and* the output — keep `-shortest` only as a harmless extra safety net,
  never as the sole stopping mechanism.
- **Timebase mismatch mixing `concat` and `xfade` in one filter graph.**
  ffmpeg's `concat` filter's output timebase doesn't match a raw decoded
  stream's, so a hard-cut boundary next to a crossfade boundary in the
  same `filter_complex` fails with "First input link main timebase ... do
  not match" unless every stream is normalized first. `concat_with_transitions`
  runs `settb=AVTB` / `asettb=AVTB` on every segment up front for exactly
  this reason — keep that if you touch the function.
- **ffmpeg builds vary** across the user's Mac, this dev environment, and
  CI. Don't assume a filter or codec is compiled in; if you add one, check
  `ffmpeg -filters` / `-encoders` or provide a fallback.

## Testing

There's no real Photos library to test against in a fresh environment —
use the synthetic smoke test instead of asking for real media:

```bash
bash tests/run_smoke_test.sh
```

This regenerates small synthetic clips/photos/map (`tests/generate_test_assets.py`,
pure ffmpeg lavfi sources — no real media needed), renders
`tests/smoke_playlist.yaml` (which exercises every item type — `title`,
`video` with and without `start`/`end`, `photo` with a `duration`
override, `map` — and every transition kind — default fade, per-item
`cut`, per-item named `xfade` — in one playlist), and checks the output's
duration and stream layout against the expected values documented in the
playlist's header comment.

There's no pixel-level assertion. When changing rendering logic (captions,
Ken Burns, title cards, a new transition), also manually pull a frame and
look at it:

```bash
ffmpeg -ss <seconds> -i tests/smoke_output.mp4 -frames:v 1 frame.png
```

The user's own playlists (e.g. `southofbergenislands/storyboard.yaml`)
reference real exported media in a sibling `media/` (and `maps/`) folder,
which isn't committed to git (see `.gitignore`) and won't exist in a
fresh checkout — don't rely on it for tests, but it's there for a final
manual check on the user's machine.

## Conventions

- `make_video.py` is a single file by design — it's small; don't split it
  into a package unless it grows substantially. A separate small script
  (like `add_new_media.py` or `tests/generate_test_assets.py`) that does
  one focused thing and imports `make_video` for shared logic is fine.
- Every ffmpeg invocation goes through the `run()` helper so failures
  raise with the full ffmpeg stderr/stdout attached — don't call
  `subprocess` directly elsewhere.
- Adding a new playlist field: read it with `item.get(...)` /
  `data.get(...)` (never required unless truly required — most fields
  should have a sensible default), and update BOTH the README's field
  tables and `example_playlist.yaml` in the same change. Undocumented
  fields are a support burden waiting to happen.
- Prefer explicit `-t` durations everywhere over relying on ffmpeg to
  infer stream length from context (see Gotchas).
- Keep `tests/smoke_playlist.yaml` exercising every item type and
  transition kind that exists — when you add a new one, add it there too
  and update the expected-duration comment.
