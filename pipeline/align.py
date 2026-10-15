"""Put timestamps on a clean transcript using a rough local transcript's word timings.

The clean text (gpt-4o-transcribe + human/LLM fixes) has the right words but no times;
faster-whisper has times but garbled words. Align them character by character.

usage: python3 align.py CLEAN.txt LOCAL.json OUT_words.json
"""
import json
import re
import sys
from difflib import SequenceMatcher

AR2FA = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و"})


def norm_chars(word):
    w = word.translate(AR2FA).lower()
    return re.sub(r"[^\w]|_|\d", "", w)


def main(clean_path, local_path, out_path):
    # split on normal whitespace only: NBSP keeps multi-word terms ("Coding Agent") in one caption token
    clean_words = [w for w in re.split(r"[ \t\r\n]+", open(clean_path, encoding="utf-8").read()) if w]
    local = json.load(open(local_path, encoding="utf-8"))
    lw = [w for s in local["segments"] for w in s["words"]]

    # local chars with per-char times (linear inside each word)
    lchars, ltimes = [], []
    for w in lw:
        cs = norm_chars(w["w"])
        n = max(len(cs), 1)
        for i, c in enumerate(cs):
            lchars.append(c)
            ltimes.append((w["start"] + (w["end"] - w["start"]) * i / n,
                           w["start"] + (w["end"] - w["start"]) * (i + 1) / n))

    cchars, owner = [], []
    for wi, w in enumerate(clean_words):
        for c in norm_chars(w):
            cchars.append(c)
            owner.append(wi)

    sm = SequenceMatcher(None, cchars, lchars, autojunk=False)
    hits = [[] for _ in clean_words]
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            hits[owner[a + k]].append(ltimes[b + k])

    out = []
    for w, h in zip(clean_words, hits):
        # need >=2 matched chars (or the whole word) to trust a match
        ok = h and (len(h) >= 2 or len(norm_chars(w)) <= 1)
        out.append({"w": w, "start": min(t[0] for t in h) if ok else None,
                    "end": max(t[1] for t in h) if ok else None})

    # interpolate unmatched words (e.g. Latin "Codex" vs whisper's "کودیکس") between neighbours
    i = 0
    while i < len(out):
        if out[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j]["start"] is None:
            j += 1
        t0 = out[i - 1]["end"] if i > 0 else 0.0
        t1 = out[j]["start"] if j < len(out) else lw[-1]["end"]
        step = (t1 - t0) / (j - i)
        for k in range(i, j):
            out[k]["start"], out[k]["end"] = t0 + step * (k - i), t0 + step * (k - i + 1)
        i = j

    # enforce monotonic, non-overlapping times
    for k in range(1, len(out)):
        out[k]["start"] = max(out[k]["start"], out[k - 1]["start"] + 0.01)
        out[k - 1]["end"] = min(max(out[k - 1]["end"], out[k - 1]["start"] + 0.05), out[k]["start"])
    for w in out:
        w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)

    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    matched = sum(1 for h in hits if h)
    print(f"{len(out)} words, {matched} matched, {len(out) - matched} interpolated -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
