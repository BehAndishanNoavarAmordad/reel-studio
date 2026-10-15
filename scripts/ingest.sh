#!/usr/bin/env bash
# usage: bash scripts/ingest.sh videos/raw.mp4 <id>
# -> work/<id>/{contact.png, audio.mp3, tx_local.json, tx_local.txt, tx_api.txt (STT_MODE=api)}
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=$1; ID=$2; W=work/$ID
set -a; [ -f .env ] && . ./.env; set +a
mkdir -p "$W" "out/$ID"

ffprobe -v error -show_entries format=duration:stream=codec_type,width,height,r_frame_rate -of compact "$SRC" | tee "$W/probe.txt"
ffmpeg -v error -y -i "$SRC" -vf "fps=1/4,scale=240:-1,tile=7x4" -frames:v 1 "$W/contact.png"
ffmpeg -v error -y -i "$SRC" -vn -ac 1 -ar 16000 -c:a libmp3lame -b:a 64k "$W/audio.mp3"

# word timings always come from local faster-whisper (text may be rough; align.py fixes that)
HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1} .venv/bin/python pipeline/transcribe_local.py "$W/audio.mp3" "$W/tx_local.json" \
  --model "${WHISPER_LOCAL_MODEL:-small}" ${STT_LANGUAGE:+--lang "$STT_LANGUAGE"} > "$W/tx_local.txt"
tail -1 "$W/tx_local.txt"

if [ "${STT_MODE:-local}" = "api" ]; then
  python3 pipeline/transcribe_api.py "$W/audio.mp3" "$W/tx_api.txt"
fi
echo "next: write $W/transcript.txt, then: python3 pipeline/align.py $W/transcript.txt $W/tx_local.json $W/words.json"
