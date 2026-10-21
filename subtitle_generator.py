import os
from typing import List, Dict, Optional

# បញ្ជី Font ដែលដំណើរការបានល្អឥតខ្ចោះជាមួយ OpenType Shaping លើ Windows
AVAILABLE_FONTS = {
    # ពុម្ពអក្សរខ្មែរ CapCut & Windows Popular
    "kantumruy": {
        "name": "Kantumruy Pro",
        "label": "🌟 Kantumruy Pro (CapCut Hot)",
        "size": 72,
        "margin_v": 280,
        "bold": -1
    },
    "leelawadee": {
        "name": "Leelawadee UI Bold",
        "label": "🌟 ស្ដង់ដារទំនើប (Leelawadee UI Bold)",
        "size": 72,
        "margin_v": 280,
        "bold": -1
    },
    "battambang": {
        "name": "Khmer OS Battambang",
        "label": "🇰🇭 បាត់ដំបង (Khmer OS Battambang)",
        "size": 68,
        "margin_v": 280,
        "bold": -1
    },
    "fasthand": {
        "name": "Khmer OS Fasthand",
        "label": "✍️ អក្សរឆ្លាក់ដៃ (Khmer OS Fasthand)",
        "size": 70,
        "margin_v": 280,
        "bold": -1
    },
    "bokor": {
        "name": "Khmer OS Bokor",
        "label": "🎬 បូកគោ (Khmer OS Bokor)",
        "size": 70,
        "margin_v": 280,
        "bold": -1
    },
    "samsung": {
        "name": "Samsung Khmer",
        "label": "📱 Samsung Khmer (Modern Tech)",
        "size": 72,
        "margin_v": 280,
        "bold": -1
    },
    "siemreap": {
        "name": "Khmer OS Siemreap",
        "label": "🌊 សៀមរាប (Khmer OS Siemreap)",
        "size": 65,
        "margin_v": 280,
        "bold": -1
    },
    "moul": {
        "name": "Khmer OS Muol",
        "label": "🏛️ អក្សរមូល (Khmer OS Muol)",
        "size": 65,
        "margin_v": 280,
        "bold": -1
    },
    # ពុម្ពអក្សរអង់គ្លេស
    "arial": {
        "name": "Arial Black",
        "label": "🔥 Arial Black (Classic Bold)",
        "size": 75,
        "margin_v": 280,
        "bold": -1
    },
    "impact": {
        "name": "Impact",
        "label": "⚡ Impact (TikTok Viral)",
        "size": 78,
        "margin_v": 280,
        "bold": -1
    }
}

def format_ass_time(seconds: float) -> str:
    """បំប្លែងវិនាទី (float) ទៅជាទម្រង់ម៉ោង ASS: H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def generate_animated_ass(
    words: List[Dict],
    output_ass_path: str,
    language: Optional[str] = None,
    font_key: Optional[str] = None,
    highlight_color: str = "&H002BF7FF&", # Bright Yellow/Gold (&H00BBGGRR&)
    default_color: str = "&H00FFFFFF&",   # Crisp White
) -> str:
    """
    បង្កើត Animated Subtitle File (.ass) កម្រិតខ្ពស់សម្រាប់ Short / Reel / TikTok:
    - បង្ហាញម្ដង ១ ឃ្លាខ្លីៗធំច្បាស់នៅកណ្តាលអេក្រង់
    - មានចលនា Pop / Zoom Effect ពេលនិយាយដល់ឃ្លានីមួយៗ
    - ប្រើ Leelawadee UI Bold ដើម្បីធានាថាជើងអក្សរ និងស្រៈខ្មែរទាំងអស់ត្រឹមត្រូវ ១០០%
    """
    if not words:
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write("")
        return output_ass_path

    is_khmer = (language == "km")

    # ជ្រើសរើស Font Configuration
    if font_key and font_key in AVAILABLE_FONTS:
        font_conf = AVAILABLE_FONTS[font_key]
    else:
        # Default សម្រាប់ខ្មែរគឺ Leelawadee UI Bold (ការពារការបាក់ជើងអក្សរ)
        default_font_key = "leelawadee" if is_khmer else "arial"
        font_conf = AVAILABLE_FONTS[default_font_key]

    font_name = font_conf["name"]
    font_size = font_conf["size"]
    margin_v = font_conf["margin_v"]
    bold_val = font_conf.get("bold", -1)

    # រៀបចំ ASS Header
    ass_content = f"""[Script Info]
Title: Animated Captions for Short Video
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{highlight_color},&H000000FF,&H00000000,&H80000000,{bold_val},0,0,0,100,100,0,0,1,6,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for item in words:
        text = item.get("word", "").strip()
        if not text:
            continue

        start_time = format_ass_time(item["start"])
        end_time = format_ass_time(item["end"])

        # ចលនា Pop-in Zoom 112% -> 100% ក្នុងរយៈពេល 120ms ដំបូង
        pop_effect = r"{\t(0,100,\fscx112\fscy112)\t(100,200,\fscx100\fscy100)}"
        animated_text = f"{pop_effect}{text}"

        line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{animated_text}"
        dialogue_lines.append(line)

    full_ass = ass_content + "\n".join(dialogue_lines) + "\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(full_ass)

    return output_ass_path
