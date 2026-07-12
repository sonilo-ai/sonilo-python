"""Generate a sound effect from text and save it locally.

Usage: SONILO_API_KEY=sk_... python examples/sfx.py
"""
from sonilo import Sonilo

with Sonilo() as client:
    result = client.text_to_sfx.generate(
        prompt="glass shattering on a stone floor", duration=5
    )
    path = result.save("sfx.m4a")
    print(f"Saved {path}")
