"""generate_music_for_video (ported from generate.ts)."""
from __future__ import annotations

import os
from typing import Any, List, Optional, Protocol


class _V2M(Protocol):
    def generate(self, *, video: Any = None, prompt: Optional[str] = None,
                 segments: Optional[List[Any]] = None) -> Any: ...


class VideoMusicClient(Protocol):
    video_to_music: _V2M


def generate_music_for_video(
    video: "str | os.PathLike[str]",
    *,
    prompt: Optional[str] = None,
    segments: Optional[List[Any]] = None,
    client: Optional[VideoMusicClient] = None,
) -> Any:
    if client is None:
        from sonilo import Sonilo

        from sonilo_video_kit._version import __version__
        # Only the kit's own default client is tagged; a caller-supplied client
        # keeps whatever identity its owner gave it.
        client = Sonilo(client_name="kit-python-video", client_version=__version__)
    return client.video_to_music.generate(video=video, prompt=prompt, segments=segments)
