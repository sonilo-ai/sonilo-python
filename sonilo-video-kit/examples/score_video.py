"""Usage: SONILO_API_KEY=sk_... python examples/score_video.py clip.mp4 "upbeat, energetic"

Generates a soundtrack for a video and mixes it in locally with ffmpeg.
Requires ffmpeg + ffprobe on PATH.
"""
import sys

from sonilo_video_kit import generate_music_for_video, mix_with_video

video = sys.argv[1] if len(sys.argv) > 1 else "clip.mp4"
prompt = sys.argv[2] if len(sys.argv) > 2 else "cinematic orchestral score"
output = "clip.scored.mp4"

track = generate_music_for_video(video, prompt=prompt)

out = mix_with_video(video=video, audio=track.audio, output=output)

title = f' — "{track.title}"' if track.title else ""
print(f"Saved {out}{title}")
