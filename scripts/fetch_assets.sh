#!/usr/bin/env bash
# usage: bash scripts/fetch_assets.sh [logo-slug ...]
# Vazirmatn font (OFL) + brand logos from simple-icons (CC0). Slugs: https://simpleicons.org
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p assets/fonts assets/logos
for w in Regular Bold ExtraBold Black; do
  f=assets/fonts/Vazirmatn-$w.ttf
  [ -s "$f" ] || curl -sfL -o "$f" "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-$w.ttf"
done
for n in ${@:-openai claude anthropic github jira trello notion docker}; do
  f=assets/logos/$n.svg
  [ -s "$f" ] || curl -sfL -o "$f" "https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/$n.svg" || { rm -f "$f"; echo "no logo: $n"; }
done
ls assets/fonts assets/logos
