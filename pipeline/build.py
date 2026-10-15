"""Edit spec -> base video (cuts, punch-ins, grade, cleaned voice) + timeline.json for the graphics layer.

usage: .venv/bin/python pipeline/build.py SPEC.json [--stills 3,10,25]   (then graphics/render_overlay.mjs)

Spec (all times in SOURCE seconds; see specs/*.json):
  source, words, out_dir, grade, caption{style,...}, tighten{min_gap,keep},
  pieces: [{src:[a,b], zoom, head_frac?}],  overlays: [{type, t, until?, ...}]
"""
import json
import math
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1080, 1920, 30

GRADES = {
    "none": "null",
    "natural": "eq=contrast=1.06:saturation=1.08:gamma=1.02,colorbalance=rm=0.03:bm=-0.03:rh=0.02:bh=-0.02",
    "punchy": "eq=contrast=1.12:saturation=1.16:gamma=1.01,curves=preset=medium_contrast,"
              "colorbalance=rm=0.04:bm=-0.04,vignette=PI/5",
    # house default: a touch warm, gentle contrast (between natural and cinematic)
    "warm": "eq=contrast=1.07:saturation=1.06:gamma=1.01,colorbalance=rs=-0.02:bs=0.03:rm=0.04:bm=-0.03:rh=0.05:bh=-0.04,"
            "curves=all='0/0.02 0.5/0.5 1/0.98',vignette=PI/6",
    "cinematic": "colorbalance=rs=-0.06:bs=0.07:rm=0.03:bm=-0.02:rh=0.07:gh=0.02:bh=-0.06,"
                 "eq=contrast=1.08:saturation=0.98,curves=all='0/0.04 0.5/0.48 1/0.97',vignette=PI/4.5,"
                 "noise=alls=4:allf=t",
}
# voice: rumble cut, light denoise, gentle compression. loudness is set after the SFX mix.
VOICE = "highpass=f=70,afftdn=nr=8:nf=-42,acompressor=threshold=-18dB:ratio=2.5:attack=5:release=80:makeup=1.5"
PUNCT = "،,.؛;:!«»\"'()"


def load_audio(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def energy_db(audio, hop=160):
    a = audio[: len(audio) // hop * hop].reshape(-1, hop)
    return 20 * np.log10(np.sqrt((a ** 2).mean(axis=1)) + 1e-9)  # 10 ms frames


def low_runs(db, thr, min_len):
    runs, i, low = [], 0, db < thr
    while i < len(low):
        if low[i]:
            j = i
            while j < len(low) and low[j]:
                j += 1
            if (j - i) / 100 >= min_len:
                runs.append((i / 100, j / 100))
            i = j
        else:
            i += 1
    return runs


def snap(t, db, win=0.08):
    """move a cut to the quietest 10 ms frame within +-win, so cuts land between syllables"""
    a, b = max(0, int((t - win) * 100)), min(len(db), int((t + win) * 100) + 1)
    return (a + int(np.argmin(db[a:b]))) / 100 if b > a else t


def expand_pieces(spec, db):
    """snap piece edges, then split each piece around long internal pauses (tighten)"""
    tg = spec.get("tighten") or {}
    gaps = low_runs(db, tg.get("thr_db", -30), tg["min_gap"]) if tg else []
    out = []
    for idx, p in enumerate(spec["pieces"]):
        p = {**p, "idx": idx}
        a, b = snap(p["src"][0], db), snap(p["src"][1], db)
        cur = a
        for g0, g1 in gaps:
            if g0 > cur + 0.15 and g1 < b - 0.15:
                keep = tg.get("keep", 0.1) / 2
                out.append({**p, "src": [cur, g0 + keep]})
                cur = g1 - keep
        out.append({**p, "src": [cur, b]})
    t = 0.0
    for p in out:
        p["out"] = [t, t + p["src"][1] - p["src"][0]]
        t = p["out"][1]
    return out, t


def to_out(pieces, t, edge="start"):
    """source time -> output time. Times inside a cut snap to the next piece (start) or previous piece end (end)."""
    hits = [p for p in pieces if p["src"][0] <= t <= p["src"][1]]
    if hits:
        p = hits[0]
        return p["out"][0] + t - p["src"][0]
    if edge == "start":
        later = [p for p in pieces if p["src"][0] > t and p["src"][0] - t < 0.6]
        return later[0]["out"][0] if later else None
    earlier = [p for p in pieces if p["src"][1] < t]
    return max(p["out"][1] for p in earlier) if earlier else None


def phrases_from_words(words, pieces, cfg):
    ow = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        for p in pieces:
            if p["src"][0] <= mid <= p["src"][1]:
                s = p["out"][0] + max(w["start"], p["src"][0]) - p["src"][0]
                e = p["out"][0] + min(w["end"], p["src"][1]) - p["src"][0]
                ow.append({"w": w["w"], "start": round(s, 3), "end": round(e, 3)})
                break
    ow.sort(key=lambda x: x["start"])
    max_w, max_c = cfg.get("max_words", 5), cfg.get("max_chars", 26)
    phrases, cur = [], []
    for w in ow:
        text = w["w"].strip(PUNCT)
        if cur:
            chars = sum(len(x["text"]) + 1 for x in cur) + len(text)
            prev_end_punct = cur[-1]["raw"][-1:] in "،,.؛;:!؟?"
            gap = w["start"] - cur[-1]["end"]
            if len(cur) >= max_w or chars > max_c or (prev_end_punct and len(cur) >= 2) or gap > 0.6:
                phrases.append(cur)
                cur = []
        cur.append({"text": text, "raw": w["w"], "start": w["start"], "end": w["end"]})
    if cur:
        phrases.append(cur)
    out = []
    for i, ph in enumerate(phrases):
        end = ph[-1]["end"] + 0.35
        if i + 1 < len(phrases):
            end = min(end, phrases[i + 1][0]["start"]) if phrases[i + 1][0]["start"] - ph[-1]["end"] < 0.6 else end
        out.append({"start": ph[0]["start"], "end": round(end, 3),
                    "words": [{"w": x["text"], "start": x["start"], "end": x["end"]} for x in ph]})
    return out


def crop_for(p, sw, sh):
    z = p.get("zoom", 1.0)
    cw, ch = int(sw / z) // 2 * 2, int(sh / z) // 2 * 2
    hx, hy = p.get("head_x", 0.5) * sw, p.get("head_y", 0.30) * sh
    x0 = min(max(hx - cw / 2, 0), sw - cw)
    y0 = min(max(hy - p.get("head_frac", 0.30) * ch, 0), sh - ch)
    return cw, ch, int(x0), int(y0)


def render_base(spec, pieces, out_path):
    src = os.path.join(ROOT, spec["source"])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                       "stream=width,height", "-of", "json", src],
                                      check=True, capture_output=True).stdout)["streams"][0]
    sw, sh = probe["width"], probe["height"]
    grade = GRADES[spec.get("grade", "natural")]
    n = len(pieces)
    # one input per piece with input-side seek: no giant split/buffer of the whole stream
    inputs, fc = [], []
    for i, p in enumerate(pieces):
        a, b = p["src"]
        cw, ch, x0, y0 = crop_for(p, sw, sh)
        d = b - a
        inputs += ["-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", src]
        # grade at source resolution (5x fewer pixels than 1080x1920), then upscale
        fc.append(f"[{i}:v]setpts=PTS-STARTPTS,crop={cw}:{ch}:{x0}:{y0},{grade},"
                  f"scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS}[vv{i}]")
        fc.append(f"[{i}:a]asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(d - 0.012, 0):.3f}:d=0.012[aa{i}]")
    fc.append("".join(f"[vv{i}][aa{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]")
    fc.append("[cv]unsharp=5:5:0.6:5:5:0,format=yuv420p[vout]")
    fc.append(f"[ca]{VOICE},aresample=48000[aout]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-crf", "14", "-preset", "veryfast",
                    "-c:a", "pcm_s16le", out_path.replace(".mp4", ".mov")], check=True)
    return out_path.replace(".mp4", ".mov")


def main():
    spec_path = sys.argv[1]
    spec = json.load(open(spec_path, encoding="utf-8"))
    out_dir = os.path.join(ROOT, spec["out_dir"])
    os.makedirs(out_dir, exist_ok=True)
    db = energy_db(load_audio(os.path.join(ROOT, spec["source"])))
    words = json.load(open(os.path.join(ROOT, spec["words"]), encoding="utf-8"))

    pieces, dur = expand_pieces(spec, db)
    phrases = phrases_from_words(words, pieces, spec.get("caption", {}))

    overlays = []
    for o in spec.get("overlays", []):
        o = dict(o)
        if "at_piece" in o:  # e.g. flash on the cut after a cold-open hook
            k = o.pop("at_piece")
            o["out_t"] = next(p["out"][0] for p in pieces if p["idx"] == k)
        if o.get("out_t") is not None:  # already in output time (hook titles, CTA)
            t0 = o.pop("out_t")
            t1 = o.pop("out_until") if "out_until" in o else t0 + o.pop("dur", 2.0)
        else:
            t0 = to_out(pieces, o.pop("t"), "start")
            if t0 is None:
                continue
            t1 = to_out(pieces, o.pop("until"), "end") if "until" in o else t0 + o.pop("dur", 2.0)
        for k in [k for k in o if k.endswith("_t")]:  # sub-events e.g. x_t (strike), steps[].t
            v = to_out(pieces, o[k], "start")
            o[k] = v
        if "steps" in o:
            o["steps"] = [{**s, "t": to_out(pieces, s["t"], "start")} for s in o["steps"]]
            o["steps"] = [s for s in o["steps"] if s["t"] is not None]
        if o.get("svg"):
            svg = open(os.path.join(ROOT, "assets/logos", o["svg"]), encoding="utf-8").read()
            o["svg"] = svg.replace("<svg ", f'<svg fill="{o.get("color", "#fff")}" ', 1)
        overlays.append({**o, "t0": round(t0, 3), "t1": round(min(t1, dur), 3)})

    cuts = [p["out"][0] for p in pieces[1:]]
    timeline = {"W": W, "H": H, "fps": FPS, "dur": round(dur, 3), "caption": spec.get("caption", {}),
                "phrases": phrases, "overlays": overlays, "cuts": cuts,
                "zooms": [{"t": p["out"][0], "z": p.get("zoom", 1.0)} for p in pieces]}
    json.dump(timeline, open(os.path.join(out_dir, "timeline.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    sfx = [{"t": o["t0"], "type": o["sfx"], "gain": o.get("sfx_gain", 0.6)} for o in overlays if o.get("sfx")]
    sfx += [{"t": o["x_t"], "type": "thump", "gain": 0.5} for o in overlays if o.get("x_t")]
    json.dump(sfx, open(os.path.join(out_dir, "sfx_cues.json"), "w"))

    base = render_base(spec, pieces, os.path.join(out_dir, "base.mp4"))
    print(f"pieces={len(pieces)} dur={dur:.2f}s phrases={len(phrases)} overlays={len(overlays)} -> {base}")


if __name__ == "__main__":
    main()
