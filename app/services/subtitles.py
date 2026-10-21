"""SRT and ASS subtitle generation with Khmer font support and phrase grouping."""
import re
from pathlib import Path
from typing import Any
from app.config import config
from timecode_utils import format_srt_timestamp, format_ass_timestamp

# Group long sentences into readable subtitle phrases
def group_events_into_phrases(
    events: list[dict[str, Any]],
    max_chars_per_phrase: int = 45,
) -> list[dict[str, Any]]:
    """
    Split long sentence events into smaller readable phrase cues.
    Maintains timing continuity and preserves Khmer punctuation.
    """
    phrases: list[dict[str, Any]] = []

    for ev in events:
        text = ev["text"].strip()
        start = ev["start"]
        end = ev["end"]
        duration = max(0.1, end - start)

        if len(text) <= max_chars_per_phrase:
            phrases.append({"start": start, "end": end, "text": text})
            continue

        # Split on spaces or Khmer punctuation marks (។ ,)
        raw_tokens = re.findall(r'[^\s\u17d4\u17d6]+[\u17d4\u17d6]?|\s+', text)
        if not raw_tokens:
            phrases.append({"start": start, "end": end, "text": text})
            continue

        words = []
        for tok in raw_tokens:
            if len(tok) > max_chars_per_phrase:
                # Split along Khmer clusters without breaking diacritics or coeng
                clusters = re.findall(r'[\u1780-\u17a2\w](?:[\u17d2][\u1780-\u17a2]|[\u17b6-\u17d3\u17dd\u0300-\u036f])*|[^\s]', tok)
                curr_w = ""
                for c in clusters:
                    if len(curr_w) + len(c) > max_chars_per_phrase and curr_w:
                        words.append(curr_w)
                        curr_w = c
                    else:
                        curr_w += c
                if curr_w:
                    words.append(curr_w)
            else:
                words.append(tok)

        chunks: list[str] = []
        current_chunk = ""
        for w in words:
            if len(current_chunk) + len(w) > max_chars_per_phrase and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = w
            else:
                current_chunk += w
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        total_chars = sum(len(c) for c in chunks)
        curr_start = start
        for i, c in enumerate(chunks):
            ratio = len(c) / total_chars if total_chars > 0 else (1.0 / len(chunks))
            cue_dur = duration * ratio
            cue_end = end if i == len(chunks) - 1 else curr_start + cue_dur
            phrases.append({
                "start": round(curr_start, 3),
                "end": round(cue_end, 3),
                "text": c,
            })
            curr_start = cue_end

    return phrases

def generate_srt(events: list[dict[str, Any]], output_path: Path | str) -> Path:
    """Generate official SRT file from timed cues."""
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    phrases = group_events_into_phrases(events)
    lines: list[str] = []

    for i, cue in enumerate(phrases, start=1):
        start_tc = format_srt_timestamp(cue["start"])
        end_tc = format_srt_timestamp(cue["end"])
        text = cue["text"].strip()

        lines.append(str(i))
        lines.append(f"{start_tc} --> {end_tc}")
        lines.append(text)
        lines.append("")

    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return dest

def generate_ass(
    events: list[dict[str, Any]],
    output_path: Path | str,
    font_name: str = "Khmer OS Battambang",
    font_size: int = 56,
    color: str = "white",       # "white" | "yellow"
    position: str = "bottom",   # "bottom" | "middle"
    res_x: int = 1080,
    res_y: int = 1920,
) -> Path:
    """
    Generate Advanced SubStation Alpha (.ass) with Khmer font, safe margins, and styling.
    """
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    phrases = group_events_into_phrases(events)

    # Primary and secondary colors in ASS &HAABBGGRR format
    if color == "yellow":
        primary_color = "&H002BF7FF"  # Bright Yellow/Gold
    else:
        primary_color = "&H00FFFFFF"  # Crisp White

    outline_color = "&H00000000"     # Black Outline
    back_color = "&H80000000"        # Semi-transparent Shadow

    # Alignment: 2 = Bottom Center, 5 = Middle Center
    if position == "middle":
        alignment = 5
        margin_v = 0
    else:
        alignment = 2
        margin_v = max(30, int(res_y * 0.08)) # 8% from bottom safe zone

    # Scale font size relative to height if default
    effective_font_size = max(24, int(res_y * 0.042)) if res_y > 0 else font_size

    header = f"""[Script Info]
Title: Voiceover Khmer Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {res_x}
PlayResY: {res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{effective_font_size},{primary_color},&H000000FF,{outline_color},{back_color},-1,0,0,0,100,100,0,0,1,3,2,{alignment},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue_lines: list[str] = [header]

    for cue in phrases:
        start_tc = format_ass_timestamp(cue["start"])
        end_tc = format_ass_timestamp(cue["end"])
        text = cue["text"].replace("\n", "\\N").strip()
        dialogue_lines.append(f"Dialogue: 0,{start_tc},{end_tc},Default,,0,0,0,,{text}")

    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(dialogue_lines) + "\n")

    return dest

def parse_srt_events(srt_path: Path | str) -> list[dict[str, Any]]:
    """Parse timing events from an existing SRT file."""
    from timecode_utils import parse_timecode
    path = Path(srt_path)
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    blocks = re.split(r'\n\s*\n', content.strip())
    events: list[dict[str, Any]] = []
    for b in blocks:
        lines = [line.strip() for line in b.splitlines() if line.strip()]
        if len(lines) >= 2:
            time_idx = 1 if "-->" in lines[1] else (0 if "-->" in lines[0] else -1)
            if time_idx != -1:
                tc = lines[time_idx]
                parts = tc.split("-->")
                if len(parts) == 2:
                    try:
                        start = parse_timecode(parts[0].strip(), allow_legacy=True)
                        end = parse_timecode(parts[1].strip(), allow_legacy=True)
                        text = " ".join(lines[time_idx + 1:])
                        events.append({"start": start, "end": end, "text": text})
                    except Exception:
                        pass
    return events

def build_timeline_subtitles(
    plan: Any,
    output_srt: Path | str,
    output_ass: Path | str,
    color: str = "white",
    position: str = "bottom",
    res_x: int = 1080,
    res_y: int = 1920,
) -> list[dict[str, Any]]:
    """
    Transforms per-utterance TTS cues to the master video timeline using placement offsets
    and tempo scaling, then writes timeline SRT and styled ASS files.
    """
    timeline_events: list[dict[str, Any]] = []

    for clip in plan.clips:
        placement = plan.get_placement(clip.segment_id)
        if not placement:
            continue

        tempo = clip.tempo_factor if clip.tempo_factor > 0 else 1.0
        t_start_sec = placement.timeline_start_ms / 1000.0
        speech_end_sec = placement.speech_end_ms / 1000.0

        if clip.tts_events:
            for ev in clip.tts_events:
                c_start = t_start_sec + (float(ev["start"]) / tempo)
                c_end = t_start_sec + (float(ev["end"]) / tempo)
                c_end = min(c_end, speech_end_sec)
                if c_end > c_start:
                    timeline_events.append({
                        "start": round(c_start, 3),
                        "end": round(c_end, 3),
                        "text": ev["text"],
                    })
        else:
            t_seg = plan.get_translation(clip.segment_id)
            if t_seg and t_seg.translated_text:
                timeline_events.append({
                    "start": round(t_start_sec, 3),
                    "end": round(speech_end_sec, 3),
                    "text": t_seg.translated_text,
                })

    # Sort strictly by start time
    timeline_events.sort(key=lambda x: x["start"])

    # Write files
    generate_srt(timeline_events, output_srt)
    generate_ass(
        timeline_events,
        output_ass,
        color=color,
        position=position,
        res_x=res_x,
        res_y=res_y,
    )

    return timeline_events
