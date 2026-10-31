#!/usr/bin/env bash
# One election-night update, no Claude: analyse the newest results file and rebuild the night site.
#   bash live/night.sh            # real results, from live/k26/latest.csv (written by fetch.py)
#   bash live/night.sh --boot 30  # with uncertainty intervals (about a minute at full count)
#   bash live/night.sh --boot 1000 --final   # once the committee publishes its final results
#   bash live/night.sh --if-changed   # stop at once if the file has the same size as at the last build
#   K26=data/sim/k26_sim_town30.csv bash live/night.sh --test   # dry run
# Publishing the rebuilt out/site_live is the one step done by Claude.
set -euo pipefail
cd "$(dirname "$0")/.."
K26="${K26:-live/k26/latest.csv}"
K26="${K26#}"
BOOT=0; TEST=(); IFCH=0; FINAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --boot) BOOT="$2"; shift 2 ;;
    --test) TEST=(--test); shift ;;
    --if-changed) IFCH=1; shift ;;
    --final) FINAL=(--final); shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
# the background downloader does not survive an idle container: on the default file, take one fresh download first
[ "$K26" = live/k26/latest.csv ] && python3 -I live/fetch.py --knesset 26 --once || true
[ -s "$K26" ] || { echo "no results file at $K26 yet; is fetch.py running?" >&2; exit 1; }
# the size of the file at the last build; the same size means no new ballots, so there is nothing to redo
SIZE="$(wc -c < "$K26" | tr -d ' ')"; LAST=live/k26/last_built_size
if [ "$IFCH" = 1 ] && [ -s "$LAST" ] && [ "$(cat "$LAST")" = "$SIZE" ]; then
  echo "no change: $K26 is $SIZE bytes, as at the last build"; exit 3
fi
# a fresh container may lack the scientific packages
python3 -c "import numpy, pandas, scipy, openpyxl" 2>/dev/null || pip install -q -r requirements.txt
start=$(date +%s)
python3 -I scripts/live_update.py --k26 "$K26" --boot "$BOOT"
python3 -I scripts/build_site_live.py --k26 "$K26" "${TEST[@]}" "${FINAL[@]}"
python3 -I live/seats.py --file "$K26" --out out/site_live/seats26_detail.json | tail -3
python3 -I scripts/briefing.py >/dev/null && echo "briefing: out/live/briefing.md"
python3 -I scripts/track.py
node scripts/render_png.js >/dev/null 2>&1 && echo "images: out/live/png" || echo "image rendering failed (non-fatal)"
# the renderer sometimes fails on a cold browser start, leaving no images; one retry
{ node scripts/render_share.js out/site_live >/dev/null 2>&1 || node scripts/render_share.js out/site_live >/dev/null 2>&1; } \
  && echo "share images: out/site_live/share" || echo "share images failed (non-fatal)"
mkdir -p "$(dirname "$LAST")"; echo "$SIZE" > "$LAST"
echo "night update done in $(( $(date +%s) - start )) s"
