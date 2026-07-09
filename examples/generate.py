"""Usage: SONILO_API_KEY=sk_... python examples/generate.py "lofi beat" 30"""
import sys

from sonilo import Sonilo

prompt = sys.argv[1] if len(sys.argv) > 1 else "cinematic orchestral score"
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60

with Sonilo() as client:
    track = client.text_to_music.generate(prompt=prompt, duration=duration)

out = track.save("output.mp3")
title = f' — "{track.title}"' if track.title else ""
print(f"Saved {out} ({len(track.audio)} bytes){title}")
