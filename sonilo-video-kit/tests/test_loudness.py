import math
from sonilo_video_kit import loudness as L


def test_constants_exact():
    assert L.FALLBACK_MUSIC_LUFS == -16.0
    assert L.OUTPUT_CEILING_DBFS == -1.0
    assert L.SLIDER_CENTER == 0.5
    assert L.SLIDER_SPAN_DB == 24.0
    assert L.GAP_BELOW_VOICE_LU == 4.0
    assert L.DELIVERY_TARGET_LUFS == -14.0
    assert L.MAX_DELIVERY_BOOST_DB == 12.0


def test_db_to_linear():
    assert L.db_to_linear(0) == 1.0
    assert math.isclose(L.db_to_linear(6), 1.9952623149688795, rel_tol=1e-9)


def test_offset_db_slider_endpoints():
    assert L.offset_db(0.5) == 0.0
    assert math.isclose(L.offset_db(1.0), 12.0)
    assert math.isclose(L.offset_db(0.0), -12.0)


def test_gap_gain_zero_when_slider_nonpositive():
    assert L.gap_gain(-20.0, -16.0, 0.0) == 0.0


def test_gap_gain_value():
    # bed=-20, music=-16, slider=0.5 -> offset 0 -> db_to_linear(-20+0-(-16)) = db_to_linear(-4)
    assert math.isclose(L.gap_gain(-20.0, -16.0, 0.5), L.db_to_linear(-4.0))


def test_original_final_gain_clamps():
    assert L.original_final_gain(1.5) == 1.0
    assert L.original_final_gain(-0.2) == 0.0
    assert L.original_final_gain(0.3) == 0.3
