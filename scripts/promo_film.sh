#!/usr/bin/env bash
# Meshwright v1 launch film (docs/15 section 7, Ralph promo-1 US-005). Strings the cover, the two diorama
# orbits, slides 2-5 (slow zoom), the turntable and an end card into one 25-30 s 1920x1080 MP4, plus a
# 1080x1080 centre-cropped square for X / LinkedIn. Everything is local: ffmpeg assembles the video, and the
# dark studio background (ffmpeg gradient) and the end card (make.mjs, which has the text styling) are made once.
# Offline, no network, no audio track.
#
# usage: bash scripts/promo_film.sh [--dry-run] [--promo DIR] [--out DIR]
set -euo pipefail
cd "$(dirname "$0")/.."

PROMO="release/v1/promo"
OUT=""
DRY=0

usage() {
  cat <<'EOF'
usage: bash scripts/promo_film.sh [--dry-run] [--promo DIR] [--out DIR]
  --dry-run     print the ffmpeg command lines (and the steps they would run) and exit; nothing is written
  --promo DIR   promo asset root (default release/v1/promo); reads out/cover_1280x640.png, out/slides/,
                out/turntable_1200.mp4, scenes_out/{village,harbour}_orbit/ and writes bg_1920x1080.png here
  --out DIR     where the two MP4s and the end card go (default DIR/out/film)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --promo) PROMO="${2:?--promo needs a value}"; shift 2 ;;
    --out) OUT="${2:?--out needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
OUT="${OUT:-$PROMO/out/film}"

W=1920; H=1080; FPS=30; CRF=18; XFADE=0.4
TITLE_SEC=2.5; ORBIT_SEC=6.0; SLIDE_SEC=2.5; TURN_SEC=3.0; END_SEC=3.0
ORBIT_FPS=20

COVER="$PROMO/out/cover_1280x640.png"
SLIDES_DIR="$PROMO/out/slides"
VILLAGE_ORBIT="$PROMO/scenes_out/village_orbit"
HARBOUR_ORBIT="$PROMO/scenes_out/harbour_orbit"
TURNTABLE="$PROMO/out/turntable_1200.mp4"
BG="$PROMO/bg_1920x1080.png"
END_CARD="$OUT/end_card.png"
FILM="$OUT/meshwright_v1_film.mp4"
SQUARE="$OUT/meshwright_v1_film_square.mp4"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/meshwright-film.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

die() { echo "promo_film: $*" >&2; exit 1; }
emit() { printf '+ %s\n' "$*"; [ "$DRY" = 1 ] || "$@"; }

# Print a command, but skip it (real runs only) when its output file already exists.
have_or_make() {
  local file="$1"; shift
  if [ "$DRY" = 0 ] && [ -f "$file" ]; then
    printf '# kept (already present): %s\n' "$file"
  else
    emit "$@"
  fi
}

frame_count() {  # number of %04d.png frames in an orbit dir, with a sane fallback for the plan
  local n
  n=$(ls "$1"/*.png 2>/dev/null | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ] && echo "$n" || echo 96
}

if [ "$DRY" = 0 ]; then
  for f in "$COVER" "$TURNTABLE"; do [ -f "$f" ] || die "missing input: $f"; done
  for d in "$SLIDES_DIR" "$VILLAGE_ORBIT" "$HARBOUR_ORBIT"; do [ -d "$d" ] || die "missing input dir: $d"; done
  mkdir -p "$OUT"
fi

# --- prepare the two still cards that ffmpeg cannot draw itself -------------------------------
# A dark studio gradient (ffmpeg radial gradient) so the transparent orbit frames composite onto something.
have_or_make "$BG" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "gradients=s=${W}x${H}:c0=0x2b3a63:c1=0x151c33:c2=0x0b0f1e:n=3:type=radial:x0=1190:y0=626" \
  -frames:v 1 "$BG"
# The end card: slide 1's diorama with the headline replaced by the install command and the licence line.
have_or_make "$END_CARD" node release/v1/promo/make.mjs --endcard --out "$OUT"

# --- one clip per part, all ${W}x${H} @ ${FPS}fps yuv420p so they cross-fade cleanly -------------
SCALED_H=$((W * 640 / 1280)); PAD_Y=$(((H - SCALED_H) / 2))
NF_VILLAGE=$(frame_count "$VILLAGE_ORBIT")
NF_HARBOUR=$(frame_count "$HARBOUR_ORBIT")
PARTS=()

# 1) title card: the 1280x640 cover scaled and padded to 1920x1080
emit ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate "$FPS" -t "$TITLE_SEC" -i "$COVER" \
  -vf "scale=${W}:${SCALED_H}:flags=lanczos,pad=${W}:${H}:0:${PAD_Y}:color=0x0b0f1e,setsar=1,fps=${FPS},format=yuv420p" \
  -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$WORK/01_title.mp4"
PARTS+=("$WORK/01_title.mp4")

# 2) village orbit: 20 fps frames looped over the gradient
emit ffmpeg -hide_banner -loglevel error -y -framerate "$ORBIT_FPS" -i "$VILLAGE_ORBIT/%04d.png" -loop 1 -framerate "$FPS" -i "$BG" \
  -filter_complex "[0:v]loop=loop=-1:size=${NF_VILLAGE},setpts=N/(${ORBIT_FPS}*TB),fps=${FPS}[fg];[1:v]fps=${FPS}[bg];[bg][fg]overlay=eof_action=repeat,format=yuv420p[out]" \
  -map "[out]" -t "$ORBIT_SEC" -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$WORK/02_village_orbit.mp4"
PARTS+=("$WORK/02_village_orbit.mp4")

# 3-6) slides 2-5, each with a slow 4% zoom-in
slide_i=3
for slide in "$SLIDES_DIR"/0[2-5]_*.png; do
  [ -f "$slide" ] || continue
  name="$(basename "$slide" .png)"; name="${name#*_}"
  n=$(printf '%02d' "$slide_i")
  part="$WORK/${n}_slide_${name}.mp4"
  emit ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate "$FPS" -t "$SLIDE_SEC" -i "$slide" \
    -vf "scale=2000:1125:flags=lanczos,zoompan=z='min(zoom+0.00055,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=${W}x${H}:fps=${FPS},setsar=1,format=yuv420p" \
    -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$part"
  PARTS+=("$part")
  slide_i=$((slide_i + 1))
done

# 7) harbour orbit
emit ffmpeg -hide_banner -loglevel error -y -framerate "$ORBIT_FPS" -i "$HARBOUR_ORBIT/%04d.png" -loop 1 -framerate "$FPS" -i "$BG" \
  -filter_complex "[0:v]loop=loop=-1:size=${NF_HARBOUR},setpts=N/(${ORBIT_FPS}*TB),fps=${FPS}[fg];[1:v]fps=${FPS}[bg];[bg][fg]overlay=eof_action=repeat,format=yuv420p[out]" \
  -map "[out]" -t "$ORBIT_SEC" -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$WORK/07_harbour_orbit.mp4"
PARTS+=("$WORK/07_harbour_orbit.mp4")

# 8) turntable centred on the gradient
emit ffmpeg -hide_banner -loglevel error -y -i "$TURNTABLE" -loop 1 -framerate "$FPS" -i "$BG" \
  -filter_complex "[0:v]trim=duration=${TURN_SEC},setpts=PTS-STARTPTS,scale=900:900:flags=lanczos[t];[1:v]fps=${FPS}[bg];[bg][t]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]" \
  -map "[out]" -t "$TURN_SEC" -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$WORK/08_turntable.mp4"
PARTS+=("$WORK/08_turntable.mp4")

# 9) end card
emit ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate "$FPS" -t "$END_SEC" -i "$END_CARD" \
  -vf "scale=${W}:${H}:flags=lanczos,setsar=1,fps=${FPS},format=yuv420p" \
  -r "$FPS" -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -an "$WORK/09_endcard.mp4"
PARTS+=("$WORK/09_endcard.mp4")

# --- cross-fade the nine parts into the film (0.4 s fade, offset accumulates per cut) -----------
DUR=("$TITLE_SEC" "$ORBIT_SEC" "$SLIDE_SEC" "$SLIDE_SEC" "$SLIDE_SEC" "$SLIDE_SEC" "$ORBIT_SEC" "$TURN_SEC" "$END_SEC")
n=${#PARTS[@]}
[ "$n" -eq "${#DUR[@]}" ] || die "expected ${#DUR[@]} parts, built $n (slides 2-5 missing?)"

filter=""
for ((i = 0; i < n - 1; i++)); do
  sum=0
  for ((j = 0; j <= i; j++)); do sum=$(awk "BEGIN{printf \"%.4f\", $sum + ${DUR[$j]}}"); done
  off=$(awk "BEGIN{printf \"%.4f\", $sum - ($i + 1) * $XFADE}")
  if [ "$i" -eq 0 ]; then
    filter="[0:v][1:v]xfade=transition=fade:duration=${XFADE}:offset=${off}[v1]"
  else
    filter="${filter};[v${i}][$((i + 1)):v]xfade=transition=fade:duration=${XFADE}:offset=${off}[v$((i + 1))]"
  fi
done

inputs=(); for p in "${PARTS[@]}"; do inputs+=(-i "$p"); done
emit ffmpeg -hide_banner -loglevel error -y "${inputs[@]}" \
  -filter_complex "$filter" -map "[v$((n - 1))]" \
  -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -movflags +faststart -an "$FILM"

# --- 1080x1080 centre crop for X / LinkedIn, same encode settings ------------------------------
emit ffmpeg -hide_banner -loglevel error -y -i "$FILM" \
  -vf "crop=1080:1080:(in_w-1080)/2:(in_h-1080)/2" \
  -c:v libx264 -crf "$CRF" -pix_fmt yuv420p -movflags +faststart -an "$SQUARE"

if [ "$DRY" = 1 ]; then
  printf '# dry run: %d parts, %d crossfades of %ss\n' "$n" "$((n - 1))" "$XFADE"
  exit 0
fi

film_dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$FILM")
sq_dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$SQUARE")
echo "film:   $FILM  ${film_dur}s"
echo "square: $SQUARE  ${sq_dur}s"
awk -v d="$film_dur" 'BEGIN { if (d < 25 || d > 30) { printf "promo_film: duration %.2fs is outside 25-30s\n", d > "/dev/stderr"; exit 1 } }'
