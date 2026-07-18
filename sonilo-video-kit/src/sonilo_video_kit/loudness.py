"""Loudness math ported 1:1 from loudness.ts (no I/O)."""
from __future__ import annotations

FALLBACK_MUSIC_LUFS = -16.0
OUTPUT_CEILING_DBFS = -1.0
SLIDER_CENTER = 0.5
SLIDER_SPAN_DB = 24.0
GAP_BELOW_VOICE_LU = 4.0
DELIVERY_TARGET_LUFS = -14.0
MAX_DELIVERY_BOOST_DB = 12.0


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20)


def offset_db(slider01: float) -> float:
    return (slider01 - SLIDER_CENTER) * SLIDER_SPAN_DB


def gap_gain(bed_lufs: float, music_lufs: float, slider01: float) -> float:
    if slider01 <= 0:
        return 0.0
    return db_to_linear(bed_lufs + offset_db(slider01) - music_lufs)


def original_final_gain(slider01: float) -> float:
    return max(0.0, min(slider01, 1.0))
