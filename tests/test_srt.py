"""
Required Test 1: SRT formatting and rollover.
Verifies:
- 1.9996 -> 00:00:02,000 (millisecond rounding)
- Minute and hour rollover behavior
- Handling of invalid values (negative, NaN, inf, None, strings)
- Standard SRT block building
"""

import math
import pytest
from timecode_utils import format_srt_timestamp, build_srt_content


class TestSRTFormatting:
    def test_exact_rounding_1_9996(self):
        """1.9996 must round to exactly 00:00:02,000 without 1000ms bug."""
        assert format_srt_timestamp(1.9996) == "00:00:02,000"

    def test_minute_rollover(self):
        """59.9996s must roll over to 00:01:00,000."""
        assert format_srt_timestamp(59.9996) == "00:01:00,000"
        assert format_srt_timestamp(119.9996) == "00:02:00,000"

    def test_hour_rollover(self):
        """3599.9996s must roll over to 01:00:00,000."""
        assert format_srt_timestamp(3599.9996) == "01:00:00,000"
        assert format_srt_timestamp(7199.9996) == "02:00:00,000"

    def test_standard_values(self):
        assert format_srt_timestamp(0.0) == "00:00:00,000"
        assert format_srt_timestamp(1.5) == "00:00:01,500"
        assert format_srt_timestamp(83.456) == "00:01:23,456"

    def test_invalid_values(self):
        """Negative, NaN, Inf, None, and non-numeric inputs must not crash."""
        assert format_srt_timestamp(-5.0) == "00:00:00,000"
        assert format_srt_timestamp(-0.001) == "00:00:00,000"
        assert format_srt_timestamp(float("nan")) == "00:00:00,000"
        assert format_srt_timestamp(float("inf")) == "00:00:00,000"
        assert format_srt_timestamp(float("-inf")) == "00:00:00,000"
        assert format_srt_timestamp(None) == "00:00:00,000"
        assert format_srt_timestamp("not_a_number") == "00:00:00,000"

    def test_build_srt_content(self):
        words = [
            {"word": "សួស្តី", "start": 0.0, "end": 1.9996},
            {"word": "ពុកម៉ែបងប្អូន", "start": 2.1, "end": 4.5}
        ]
        srt_text = build_srt_content(words)
        expected = (
            "1\n00:00:00,000 --> 00:00:02,000\nសួស្តី\n\n"
            "2\n00:00:02,100 --> 00:00:04,500\nពុកម៉ែបងប្អូន\n"
        )
        assert srt_text.strip() == expected.strip()
