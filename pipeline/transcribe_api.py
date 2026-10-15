"""Clean transcript text (no timestamps needed) from any OpenAI-compatible speech-to-text API.

usage: python3 pipeline/transcribe_api.py AUDIO OUT.txt
Reads STT_BASE_URL, STT_API_KEY, STT_MODEL, STT_LANGUAGE from .env. Stdlib only.
Works with OpenAI, Groq, and gateways that expose POST {base}/audio/transcriptions.
"""
import json
import os
import sys
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")
env = {**(dict(l.strip().split("=", 1) for l in open(ENV_FILE) if "=" in l and not l.lstrip().startswith("#"))
          if os.path.exists(ENV_FILE) else {}), **os.environ}
audio, out = sys.argv[1], sys.argv[2]

fields = {"model": env.get("STT_MODEL", "gpt-4o-transcribe"), "response_format": "json"}
if env.get("STT_LANGUAGE"):
    fields["language"] = env["STT_LANGUAGE"]
b = uuid.uuid4().hex
body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in fields.items())
body += (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(audio)}\"\r\n"
         f"Content-Type: application/octet-stream\r\n\r\n").encode() + open(audio, "rb").read() + f"\r\n--{b}--\r\n".encode()
req = urllib.request.Request(env.get("STT_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions",
                             data=body, method="POST", headers={
                                 "Authorization": f"Bearer {env['STT_API_KEY']}",
                                 "Content-Type": f"multipart/form-data; boundary={b}"})
text = json.load(urllib.request.urlopen(req, timeout=300))["text"]
open(out, "w", encoding="utf-8").write(text.strip() + "\n")
print(f"{len(text.split())} words -> {out}")
