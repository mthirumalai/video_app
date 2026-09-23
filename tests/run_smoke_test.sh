#!/usr/bin/env bash
# Regenerate synthetic fixtures, render the smoke playlist, and sanity-check
# the result. Run from anywhere:
#   bash tests/run_smoke_test.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
EXPECTED_DURATION=32.4
TOLERANCE=1.5

echo "== Generating synthetic fixtures =="
python3 "$HERE/generate_test_assets.py"

echo
echo "== Validating smoke_playlist.yaml (-nop) =="
python3 "$ROOT/make_video.py" -nop "$HERE/smoke_playlist.yaml"

echo
echo "== Rendering smoke_playlist.yaml =="
python3 "$ROOT/make_video.py" "$HERE/smoke_playlist.yaml"

OUTPUT="$HERE/smoke_output.mp4"
if [ ! -f "$OUTPUT" ]; then
    echo "FAIL: $OUTPUT was not created"
    exit 1
fi

DURATION=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$OUTPUT")
echo
echo "Output duration: ${DURATION}s (expected ~${EXPECTED_DURATION}s +/- ${TOLERANCE}s)"

python3 - "$DURATION" "$EXPECTED_DURATION" "$TOLERANCE" <<'EOF'
import sys
duration, expected, tolerance = (float(x) for x in sys.argv[1:4])
if abs(duration - expected) > tolerance:
    print(f"FAIL: duration off by {abs(duration - expected):.2f}s (>{tolerance}s tolerance)")
    sys.exit(1)
print("PASS: duration within tolerance")
EOF

STREAMS=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$OUTPUT" | tr '\n' ',' )
echo "Streams: $STREAMS"
case "$STREAMS" in
    *video*audio*|*audio*video*) echo "PASS: has both video and audio streams" ;;
    *) echo "FAIL: expected both a video and an audio stream, got: $STREAMS"; exit 1 ;;
esac

echo
echo "All checks passed. Inspect $OUTPUT directly if you want to eyeball it"
echo "(e.g. ffmpeg -ss <t> -i \"$OUTPUT\" -frames:v 1 frame.png)."
