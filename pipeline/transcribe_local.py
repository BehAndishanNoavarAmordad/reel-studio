"""Transcribe a video/audio file with word-level timestamps (local, CPU).

usage: .venv/bin/python pipeline/transcribe_local.py INPUT OUT.json [--model small] [--lang fa] [--device cpu|cuda]
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np
from faster_whisper import WhisperModel


def load_audio(path):
    # decode with system ffmpeg (16 kHz mono f32) instead of PyAV: handles mkv/mp4 and avoids av version breakage
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


ap = argparse.ArgumentParser()
ap.add_argument("input")
ap.add_argument("out")
ap.add_argument("--model", default=os.environ.get("WHISPER_LOCAL_MODEL", "small"))
ap.add_argument("--device", default=os.environ.get("WHISPER_DEVICE", "cpu"), help="cpu or cuda")
ap.add_argument("--lang", default=None, help="fa, en, ... (default: auto-detect)")
a = ap.parse_args()

t0 = time.time()
model = WhisperModel(a.model, device=a.device, compute_type="int8" if a.device == "cpu" else "float16",
                     cpu_threads=os.cpu_count() or 4)
t_load = time.time() - t0

t0 = time.time()
segments, info = model.transcribe(
    load_audio(a.input),
    language=a.lang,
    word_timestamps=True,
    vad_filter=True,
)
out = {"language": info.language, "language_prob": info.language_probability,
       "duration": info.duration, "model": a.model, "segments": []}
for s in segments:
    out["segments"].append({
        "start": s.start, "end": s.end, "text": s.text.strip(),
        "words": [{"w": w.word.strip(), "start": w.start, "end": w.end, "p": round(w.probability, 3)}
                  for w in (s.words or [])],
    })
    print(f"[{s.start:7.2f} -> {s.end:7.2f}] {s.text.strip()}", flush=True)
t_run = time.time() - t0

with open(a.out, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"\nlang={info.language} ({info.language_probability:.2f}) audio={info.duration:.1f}s "
      f"load={t_load:.1f}s transcribe={t_run:.1f}s -> {a.out}")
