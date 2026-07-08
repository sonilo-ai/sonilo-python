from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

Segment = Dict[str, Any]
"""{"start": float, "prompt": str, "label": optional str}"""

StreamEvent = Dict[str, Any]
"""One NDJSON event; audio_chunk events carry `data` as decoded bytes."""


@dataclass
class Track:
    audio: bytes
    title: Optional[str] = None
    cost: Optional[Dict[str, str]] = None

    def save(self, path: Union[str, Path]) -> Path:
        """Write the audio bytes to `path` and return it."""
        p = Path(path)
        p.write_bytes(self.audio)
        return p
