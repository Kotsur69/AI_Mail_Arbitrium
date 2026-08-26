#!/usr/bin/env bash
# Download the GGUF weights Phase 1 needs, straight from Hugging Face.
#
# Why not `lms get`: it managed ~2 MB/s and did not recover from a dropped
# connection -- it stalled silently mid-file twice. Plain curl to the same host
# sustains ~9 MB/s and resumes correctly, so a 20 GB pull is ~35 min instead of
# ~3 h. Files land in LM Studio's own models tree, where it sideloads them.
#
# Run:  bash scripts/fetch_models.sh

set -u

MODELS_DIR="$HOME/.lmstudio/models"
RETRIES=100
RETRY_DELAY=15

# repo | filename                              (one line per file to fetch)
# The vision model needs its mmproj projector alongside the weights.
FILES=(
  "lmstudio-community/Qwen2.5-VL-32B-Instruct-GGUF|Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf"
  "lmstudio-community/Qwen2.5-VL-32B-Instruct-GGUF|mmproj-model-f16.gguf"
  "lmstudio-community/Qwen3-32B-GGUF|Qwen3-32B-Q4_K_M.gguf"
)

fetch() {
  local repo="$1" name="$2"
  local dest_dir="$MODELS_DIR/$repo" dest
  mkdir -p "$dest_dir"
  dest="$dest_dir/$name"

  local expected
  expected=$(curl -sIL "https://huggingface.co/$repo/resolve/main/$name" \
             | tr -d '\r' | awk 'tolower($1)=="content-length:"{n=$2} END{print n}')

  if [ -f "$dest" ] && [ -n "$expected" ] && [ "$(stat -c %s "$dest")" = "$expected" ]; then
    echo "[$(date +%H:%M:%S)] $name -- already complete ($((expected/1048576)) MiB)"
    return 0
  fi

  echo "[$(date +%H:%M:%S)] $name -- fetching $((expected/1048576)) MiB"
  # -C - resumes from whatever is on disk; --retry covers dropped connections.
  curl -L --fail --progress-bar -C - \
       --retry "$RETRIES" --retry-delay "$RETRY_DELAY" --retry-all-errors \
       --speed-time 120 --speed-limit 10240 \
       -o "$dest" "https://huggingface.co/$repo/resolve/main/$name" 2>&1 | tr '\r' '\n' | tail -1

  local got
  got=$(stat -c %s "$dest" 2>/dev/null || echo 0)
  if [ -n "$expected" ] && [ "$got" != "$expected" ]; then
    echo "[$(date +%H:%M:%S)] $name -- INCOMPLETE: $got of $expected bytes"
    return 1
  fi
  echo "[$(date +%H:%M:%S)] $name -- done ($((got/1048576)) MiB)"
}

rc=0
for entry in "${FILES[@]}"; do
  fetch "${entry%%|*}" "${entry##*|}" || rc=1
done

# LM Studio's stale partial from its own failed attempt is now dead weight.
find "$MODELS_DIR" -name 'downloading_*.part' -delete 2>/dev/null

echo "=== inventory ==="
"$HOME/.lmstudio/bin/lms.exe" ls 2>&1 | tr -d '\r'
exit "$rc"
