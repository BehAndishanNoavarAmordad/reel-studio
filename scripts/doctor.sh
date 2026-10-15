#!/usr/bin/env bash
# Checks everything the pipeline needs. Prints OK / MISSING per item.
cd "$(dirname "$0")/.."
ok(){ printf '  %-28s OK\n' "$1"; }; no(){ printf '  %-28s MISSING  %s\n' "$1" "$2"; FAIL=1; }
FAIL=0
command -v ffmpeg >/dev/null && ok ffmpeg || no ffmpeg "install ffmpeg (apt/brew/winget)"
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q " libx264 " && ok "ffmpeg libx264" || no "ffmpeg libx264" "need a full ffmpeg build"
for f in loudnorm afftdn acompressor; do ffmpeg -hide_banner -filters 2>/dev/null | grep -q " $f " && ok "ffmpeg $f" || no "ffmpeg $f" "need a full ffmpeg build"; done
command -v node >/dev/null && ok "node $(node -v)" || no node "Node 18+"
command -v python3 >/dev/null && ok "$(python3 --version)" || no python3 "Python 3.10+"
[ -x .venv/bin/python ] && .venv/bin/python -c "import faster_whisper, numpy" 2>/dev/null && ok "python venv" || no "python venv" "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
[ -d node_modules/playwright ] && ok playwright || no playwright "npm install && npx playwright install chromium"
ls assets/fonts/Vazirmatn-Bold.ttf >/dev/null 2>&1 && ok fonts || no fonts "bash scripts/fetch_assets.sh"
[ -f .env ] && ok ".env" || no ".env" "cp .env.example .env"
[ -f STYLE.md ] && ok "STYLE.md" || no "STYLE.md" "run setup (see SETUP.md)"
exit $FAIL
