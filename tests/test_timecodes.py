"""
Required Test 2: Timecode parsing.
Verifies:
- Standard SRT format (HH:MM:SS,mmm and HH:MM:SS.mmm)
- Standard MM:SS.mmm format
- Standard HH:MM:SS and seconds format
- Legacy syntax only works when explicitly enabled (raises ValueError otherwise)
"""

import pytest
from timecode_utils import parse_timecode


class TestTimecodes:
    def test_standard_srt_comma(self):
        """Standard SRT timecode with comma separator."""
        val = parse_timecode("00:01:23,456", allow_legacy=False)
        assert pytest.approx(val, 0.001) == 83.456

    def test_standard_srt_dot(self):
        """Standard SRT timecode with dot separator."""
        val = parse_timecode("00:01:23.456", allow_legacy=False)
        assert pytest.approx(val, 0.001) == 83.456

    def test_mmss_mmm(self):
        """Standard MM:SS.mmm timecode."""
        val = parse_timecode("01:23.456", allow_legacy=False)
        assert pytest.approx(val, 0.001) == 83.456

        val2 = parse_timecode("00:05.200", allow_legacy=False)
        assert pytest.approx(val2, 0.001) == 5.200

    def test_hhmmss_and_seconds(self):
        val = parse_timecode("01:02:03", allow_legacy=False)
        assert pytest.approx(val, 0.001) == 3723.0

        val_sec = parse_timecode("45.678", allow_legacy=False)
        assert pytest.approx(val_sec, 0.001) == 45.678

    def test_legacy_syntax_disabled_by_default(self):
        """Non-standard legacy syntax must be rejected when allow_legacy=False."""
        with pytest.raises(ValueError):
            parse_timecode("01:32:150", allow_legacy=False)

        with pytest.raises(ValueError):
            parse_timecode("not:a:valid:timecode", allow_legacy=False)

    def test_legacy_syntax_explicitly_enabled(self):
        """Legacy syntax only parses when allow_legacy=True."""
        val = parse_timecode("01:32:150", allow_legacy=True)
        assert val > 0.0
