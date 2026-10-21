"""
Timecode and timeline utilities for Video Bot.
Provides:
- format_srt_timestamp: Exact SRT formatting with millisecond rounding and rollover (e.g. 1.9996 -> 00:00:02,000).
- format_ass_timestamp: Exact ASS formatting (H:MM:SS.cc).
- parse_timecode: Parses standard SRT and MM:SS.mmm. Legacy formats require explicit allow_legacy=True.
- build_srt_content: Converts words list to standard valid SRT text.
- calculate_timeline_frames: Ensures multiple fractional cuts produce exactly matching frame totals.
- map_time_to_timeline & map_overlay_to_timeline: Ensures subtitle and visual overlays survive silence removal.
"""

import math
import re
from typing import List, Dict, Tuple, Optional, Any


def format_srt_timestamp(seconds: Any) -> str:
    """
    Format floating seconds into official standard SRT timecode: HH:MM:SS,mmm
    Handles:
    - Millisecond rounding: 1.9996 -> "00:00:02,000"
    - Minute rollover: 59.9996 -> "00:01:00,000"
    - Hour rollover: 3599.9996 -> "01:00:00,000"
    - Invalid values (negative, NaN, inf, None, non-numeric) -> "00:00:00,000"
    """
    if seconds is None:
        return "00:00:00,000"
    try:
        val = float(seconds)
    except (ValueError, TypeError):
        return "00:00:00,000"

    if math.isnan(val) or math.isinf(val) or val < 0.0:
        val = 0.0

    # Round to nearest millisecond integer
    total_ms = int(round(val * 1000.0))

    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_ass_timestamp(seconds: Any) -> str:
    """
    Format floating seconds into ASS timecode: H:MM:SS.cc (centiseconds)
    """
    if seconds is None:
        return "0:00:00.00"
    try:
        val = float(seconds)
    except (ValueError, TypeError):
        return "0:00:00.00"

    if math.isnan(val) or math.isinf(val) or val < 0.0:
        val = 0.0

    # Total centiseconds rounded to nearest integer
    total_cs = int(round(val * 100.0))

    cs = total_cs % 100
    total_seconds = total_cs // 100
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def parse_timecode(tc: str, allow_legacy: bool = False, max_dur: float = 86400.0) -> float:
    """
    Parses timecodes into float seconds.
    Standard formats:
    - Standard SRT: "00:01:23,456" or "00:01:23.456" (HH:MM:SS,mmm)
    - Standard MM:SS.mmm: "01:23.456" or "01:23,456"
    - Standard SS.mmm: "23.456"
    - Standard HH:MM:SS: "01:02:03"
    
    Legacy syntax:
    - e.g. "01:32:150" where 3rd part is treated as milliseconds or minutes:seconds:frames.
    Legacy syntax is ONLY accepted when allow_legacy=True.
    When allow_legacy=False, invalid/ambiguous formats raise ValueError.
    """
    if not isinstance(tc, str):
        raise ValueError(f"Timecode must be a string, got {type(tc).__name__}")

    raw = tc.strip()
    if not raw:
        raise ValueError("Empty timecode string")

    # Standard SRT pattern: HH:MM:SS[,.]mmm
    srt_match = re.fullmatch(r"^(\d{1,2}):(\d{2}):(\d{2})[,\.](\d{1,3})$", raw)
    if srt_match:
        h, m, s, ms_str = srt_match.groups()
        h_val, m_val, s_val = int(h), int(m), int(s)
        if m_val >= 60 or s_val >= 60:
            raise ValueError(f"Invalid standard SRT timecode values: {raw}")
        ms_val = int(ms_str.ljust(3, "0")[:3])
        sec = h_val * 3600.0 + m_val * 60.0 + s_val + (ms_val / 1000.0)
        return min(sec, max_dur)

    # Standard MM:SS[,.]mmm
    mmss_match = re.fullmatch(r"^(\d{1,3}):(\d{2})[,\.](\d{1,3})$", raw)
    if mmss_match:
        m, s, ms_str = mmss_match.groups()
        m_val, s_val = int(m), int(s)
        if s_val >= 60:
            raise ValueError(f"Invalid seconds in MM:SS timecode: {raw}")
        ms_val = int(ms_str.ljust(3, "0")[:3])
        sec = m_val * 60.0 + s_val + (ms_val / 1000.0)
        return min(sec, max_dur)

    # Standard HH:MM:SS
    hms_match = re.fullmatch(r"^(\d{1,2}):(\d{2}):(\d{2})$", raw)
    if hms_match:
        h, m, s = map(int, hms_match.groups())
        if m >= 60 or s >= 60:
            raise ValueError(f"Invalid standard HH:MM:SS values: {raw}")
        sec = h * 3600.0 + m * 60.0 + s
        return min(float(sec), max_dur)

    # Standard MM:SS
    ms_match = re.fullmatch(r"^(\d{1,3}):(\d{2})$", raw)
    if ms_match:
        m, s = map(int, ms_match.groups())
        if s >= 60:
            raise ValueError(f"Invalid standard MM:SS values: {raw}")
        sec = m * 60.0 + s
        return min(float(sec), max_dur)

    # Pure float/seconds e.g. "23.456"
    sec_match = re.fullmatch(r"^(\d+(?:\.\d+)?)$", raw)
    if sec_match:
        return min(float(sec_match.group(1)), max_dur)

    # Check for legacy syntax e.g. "01:32:150"
    if allow_legacy:
        norm = raw.replace(",", ".")
        parts = norm.split(":")
        try:
            if len(parts) == 3:
                p0, p1, p2 = float(parts[0]), float(parts[1]), float(parts[2])
                if p0 == 0:
                    return min(p1 * 60.0 + p2, max_dur)
                if p0 * 3600 > max_dur or p2 > 60:
                    frac = p2 / 1000.0 if p2 >= 100 else p2 / 100.0 if p2 >= 10 else p2 / 10.0
                    return min(p0 * 60.0 + p1 + frac, max_dur)
                return min(p0 * 3600.0 + p1 * 60.0 + p2, max_dur)
            elif len(parts) == 2:
                return min(float(parts[0]) * 60.0 + float(parts[1]), max_dur)
            elif len(parts) == 1:
                return min(float(parts[0]), max_dur)
        except Exception:
            pass

    raise ValueError(f"Unsupported or invalid timecode format: '{tc}' (allow_legacy={allow_legacy})")


def build_srt_content(words_list: List[Dict]) -> str:
    """
    Builds official standard SRT string from a list of words or subtitle segments.
    Properly uses format_srt_timestamp to guarantee validity.
    """
    if not words_list:
        return ""

    blocks = []
    idx = 1
    for item in words_list:
        txt = str(item.get("word") or item.get("text") or "").strip()
        if not txt:
            continue
        try:
            st = float(item.get("start", 0.0))
            et = float(item.get("end", st + 1.0))
        except (ValueError, TypeError):
            continue

        if et <= st:
            et = st + 0.5

        st_tc = format_srt_timestamp(st)
        et_tc = format_srt_timestamp(et)
        blocks.append(f"{idx}\n{st_tc} --> {et_tc}\n{txt}\n")
        idx += 1

    return "\n".join(blocks).strip() + "\n" if blocks else ""


def calculate_timeline_frames(cuts: List[Dict], fps: int = 30) -> Tuple[int, List[int]]:
    """
    Computes exact frame counts for multiple fractional cuts.
    Guarantees:
    - Each cut receives integer frame count: round(cut_duration * fps).
    - Total timeline frames equals the exact sum of all cut frames.
    Returns:
        (total_frames, list_of_cut_frames)
    """
    cut_frames = []
    for c in cuts:
        start = float(c.get("start", 0.0))
        end = float(c.get("end", start))
        dur = max(0.0, end - start)
        frames = int(round(dur * fps))
        cut_frames.append(frames)

    total_frames = sum(cut_frames)
    return total_frames, cut_frames


def map_time_to_timeline(orig_time: float, cuts: List[Dict]) -> float:
    """
    Maps an original video timestamp to the assembled timeline after silence removal.
    If orig_time lands inside a retained cut, its relative offset in that cut is added to
    the accumulated duration of all previous cuts.
    If orig_time lands in a deleted silence gap, it is mapped smoothly to the boundary.
    """
    if not cuts:
        return max(0.0, orig_time)

    accumulated = 0.0
    for cut in cuts:
        c_start = float(cut["start"])
        c_end = float(cut["end"])
        c_dur = max(0.0, c_end - c_start)

        if orig_time < c_start:
            # Timestamp falls before this cut (in a silence gap) -> map to cut start
            return accumulated
        elif c_start <= orig_time <= c_end:
            # Timestamp falls within this cut
            return accumulated + (orig_time - c_start)
        else:
            accumulated += c_dur

    # If orig_time is after all cuts
    return accumulated


def map_overlay_to_timeline(
    orig_start: float,
    orig_end: float,
    cuts: List[Dict],
    min_duration: float = 0.5
) -> Tuple[float, float]:
    """
    Maps overlay / subtitle start and end times across silence removal cuts.
    Guarantees that overlay/subtitle timing survives silence removal.
    """
    mapped_start = map_time_to_timeline(orig_start, cuts)
    mapped_end = map_time_to_timeline(orig_end, cuts)

    if mapped_end <= mapped_start:
        orig_dur = max(min_duration, orig_end - orig_start)
        mapped_end = mapped_start + orig_dur

    return round(mapped_start, 3), round(mapped_end, 3)
