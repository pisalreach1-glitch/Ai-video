"""
Required Test 3: Timeline & Fractional Cuts.
Verifies:
- Multiple fractional cuts produce exactly matching frame totals.
- Overlay and subtitle mapping accurately survives silence removal cuts.
"""

import pytest
from timecode_utils import calculate_timeline_frames, map_time_to_timeline, map_overlay_to_timeline


class TestTimeline:
    def test_fractional_cuts_matching_frame_totals(self):
        """
        Multiple fractional cuts with varying durations must produce
        exactly matching integer frame totals at 30 fps.
        """
        fps = 30
        cuts = [
            {"start": 0.123, "end": 2.456},  # duration: 2.333s -> round(2.333 * 30) = 70 frames
            {"start": 3.891, "end": 5.712},  # duration: 1.821s -> round(1.821 * 30) = 55 frames
            {"start": 7.005, "end": 10.334}, # duration: 3.329s -> round(3.329 * 30) = 100 frames
            {"start": 12.500, "end": 14.125} # duration: 1.625s -> round(1.625 * 30) = 49 frames
        ]

        total_frames, cut_frames = calculate_timeline_frames(cuts, fps=fps)

        # Check integer frame counts
        for cf in cut_frames:
            assert isinstance(cf, int)
            assert cf > 0

        # Exact match
        assert total_frames == sum(cut_frames)
        assert total_frames == (70 + 55 + 100 + 49)

    def test_overlay_mapping_survives_silence_removal(self):
        """
        If video has a 2.0s silence gap removed between Cut 1 and Cut 2,
        an overlay in Cut 2 must shift by exactly 2.0s forward in the assembled timeline.
        """
        cuts = [
            {"start": 0.0, "end": 3.0},   # Cut 1: [0.0 - 3.0], dur: 3.0s
            # Silence gap: [3.0 - 5.0] (2.0s silence removed)
            {"start": 5.0, "end": 9.0}    # Cut 2: [5.0 - 9.0], dur: 4.0s
        ]

        # Overlay originally in Cut 2 from 6.0s to 8.0s (1.0s to 3.0s into Cut 2)
        mapped_start, mapped_end = map_overlay_to_timeline(6.0, 8.0, cuts)

        # In assembled timeline:
        # Cut 1 occupies 0.0s to 3.0s.
        # Cut 2 starts immediately at 3.0s.
        # So 1.0s into Cut 2 should be at 3.0 + 1.0 = 4.0s.
        # 3.0s into Cut 2 should be at 3.0 + 3.0 = 6.0s.
        assert pytest.approx(mapped_start, 0.01) == 4.0
        assert pytest.approx(mapped_end, 0.01) == 6.0

    def test_overlay_during_silence_boundary(self):
        """Overlay starting inside a removed silence gap is snapped to the boundary."""
        cuts = [
            {"start": 0.0, "end": 2.0},
            {"start": 4.0, "end": 7.0}
        ]
        # Overlay originally in silence gap [2.5, 3.5]
        mapped_s, mapped_e = map_overlay_to_timeline(2.5, 3.5, cuts)
        assert mapped_s >= 2.0
        assert mapped_e > mapped_s
