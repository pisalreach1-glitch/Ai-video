"""Stable option identifiers, constants, and labels for the UI."""

# Voice options
VOICE_FEMALE = "km-KH-SreymomNeural"
VOICE_MALE = "km-KH-PisethNeural"
VOICES = {
    VOICE_FEMALE: {
        "id": VOICE_FEMALE,
        "name": "ស្រី (Sreymom)",
        "label": "👩 សំឡេងស្រី",
        "gender": "Female",
    },
    VOICE_MALE: {
        "id": VOICE_MALE,
        "name": "ប្រុស (Piseth)",
        "label": "👨 សំឡេងប្រុស",
        "gender": "Male",
    },
}

# Short voice IDs to keep Telegram callback_data well under 64 bytes
VOICE_SHORT_TO_NAME = {
    "f": VOICE_FEMALE,
    "m": VOICE_MALE,
}
VOICE_NAME_TO_SHORT = {
    VOICE_FEMALE: "f",
    VOICE_MALE: "m",
}

# Speed presets
SPEED_SLOW = "-15%"
SPEED_NORMAL = "+0%"
SPEED_FAST = "+15%"
SPEEDS = {
    SPEED_SLOW: {"id": SPEED_SLOW, "label": "🐢 យឺត (-15%)"},
    SPEED_NORMAL: {"id": SPEED_NORMAL, "label": "▶️ ធម្មតា (1.0x)"},
    SPEED_FAST: {"id": SPEED_FAST, "label": "⚡ លឿន (+15%)"},
}

# Subtitle styling
SUBTITLE_COLOR_WHITE = "white"
SUBTITLE_COLOR_YELLOW = "yellow"
SUBTITLE_COLORS = {
    SUBTITLE_COLOR_WHITE: {"id": SUBTITLE_COLOR_WHITE, "label": "⚪ ពណ៌ស (White)"},
    SUBTITLE_COLOR_YELLOW: {"id": SUBTITLE_COLOR_YELLOW, "label": "🟡 ពណ៌លឿង (Yellow)"},
}

SUBTITLE_POS_BOTTOM = "bottom"
SUBTITLE_POS_MIDDLE = "middle"
SUBTITLE_POSITIONS = {
    SUBTITLE_POS_BOTTOM: {"id": SUBTITLE_POS_BOTTOM, "label": "⬇️ ខាងក្រោម (Bottom)"},
    SUBTITLE_POS_MIDDLE: {"id": SUBTITLE_POS_MIDDLE, "label": "⏸️ កណ្តាល (Middle)"},
}

# Source audio options
AUDIO_MUTE = "mute"
AUDIO_LOW_MIX = "low_mix"
AUDIO_MODES = {
    AUDIO_MUTE: {"id": AUDIO_MUTE, "label": "🔇 ជំនួសដោយសំឡេង AI"},
    AUDIO_LOW_MIX: {"id": AUDIO_LOW_MIX, "label": "🔉 រក្សាសំឡេងដើមតិចៗ (15%)"},
}

# Aspect ratio options (use colon-free IDs in callbacks to prevent split(":") bugs)
RATIO_ORIGINAL = "original"
RATIO_VERTICAL = "9:16"
RATIO_SQUARE = "1:1"
ASPECT_RATIOS = {
    RATIO_ORIGINAL: {"id": RATIO_ORIGINAL, "label": "📐 ទំហំដើម (Original)"},
    RATIO_VERTICAL: {"id": RATIO_VERTICAL, "label": "📱 បញ្ឈរ 9:16 (TikTok/Reel)"},
    RATIO_SQUARE: {"id": RATIO_SQUARE, "label": "⏹️ ការ៉េ 1:1 (Square)"},
}

RATIO_SHORT_TO_VAL = {
    "orig": RATIO_ORIGINAL,
    "vert": RATIO_VERTICAL,
    "sq": RATIO_SQUARE,
}
RATIO_VAL_TO_SHORT = {
    RATIO_ORIGINAL: "orig",
    RATIO_VERTICAL: "vert",
    RATIO_SQUARE: "sq",
}

# Framing mode options
FRAMING_FIT = "fit"
FRAMING_FILL = "fill"
FRAMING_MODES = {
    FRAMING_FIT: {"id": FRAMING_FIT, "label": "⬛ បន្ថែមគែមខ្មៅ (Fit Pad)"},
    FRAMING_FILL: {"id": FRAMING_FILL, "label": "✂️ កាត់ឱ្យពេញអេក្រង់ (Crop Fill)"},
}

# Duration policies when video is shorter than narration
DURATION_EXTEND = "extend"
DURATION_LOOP = "loop"
DURATION_SHORTEN = "shorten"
DURATION_POLICIES = {
    DURATION_EXTEND: {"id": DURATION_EXTEND, "label": "🧊 ពន្យារូបភាពចុងក្រោយ (Extend)"},
    DURATION_LOOP: {"id": DURATION_LOOP, "label": "🔁 ចាក់វីដេអូឡើងវិញ (Loop)"},
    DURATION_SHORTEN: {"id": DURATION_SHORTEN, "label": "✏️ កាត់បន្ថយអត្ថបទ (Shorten)"},
}

# Video workflow modes
MODE_FREE = "free_narration"
MODE_DUB = "source_timed"
MODE_LABELS = {
    MODE_FREE: "🎙️ Narration ថ្មី (Free Narration)",
    MODE_DUB: "🌐 បកប្រែតាមពេលវីដេអូដើម (Source-Timed Khmer Dubbing)",
}
