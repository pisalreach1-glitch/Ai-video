import sys
import os
import time
import logging
import asyncio
import difflib
from pathlib import Path

# កំណត់ Encoding UTF-8 សម្រាប់ Windows Console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from pyrogram import Client
from video_processor import VideoProcessor
from remotion_processor import RemotionProcessor
from subtitle_generator import AVAILABLE_FONTS


# ផ្ទុក environment variables ពី .env
load_dotenv()

# កំណត់ Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# អានការកំណត់
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "").strip()
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip()

# បង្កើត folder ផ្ទុកឯកសារបណ្ដោះអាសន្ន និង Cache ក្នុង Folder គម្រោងផ្ទាល់
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# បង្ខំឱ្យ cache និងឯកសារបណ្ដោះអាសន្នទាំងអស់របស់ AI/Python/Subprocess ចូលក្នុង Folder នេះ (មិនឱ្យពេញ Drive C)
os.environ["TEMP"] = str(TEMP_DIR)
os.environ["TMP"] = str(TEMP_DIR)
os.environ["HF_HOME"] = str(CACHE_DIR / "huggingface")
os.environ["TORCH_HOME"] = str(CACHE_DIR / "torch")
import tempfile
tempfile.tempdir = str(TEMP_DIR)

import json
FONTS_FILE = BASE_DIR / "khmer_fonts.json"
ALL_FONTS = []
if FONTS_FILE.exists():
    try:
        with open(FONTS_FILE, "r", encoding="utf-8") as f:
            ALL_FONTS = json.load(f)
    except Exception as e:
        pass

# Instances
processor = None
remotion_proc = None
pyro_client = None

async def get_pyro_client():
    global pyro_client
    if pyro_client is None and TELEGRAM_API_ID and TELEGRAM_API_HASH:
        logger.info("⚡ កំពុងភ្ជាប់ Pyrogram MTProto (សម្រាប់ Support 2,000MB / 2GB)...")
        pyro_client = Client(
            "bot_pyro_session",
            api_id=int(TELEGRAM_API_ID),
            api_hash=TELEGRAM_API_HASH,
            bot_token=TELEGRAM_BOT_TOKEN,
            workdir=str(TEMP_DIR)
        )
        await pyro_client.start()
        logger.info("✅ Pyrogram MTProto ភ្ជាប់ជោគជ័យ! (អាចទាញយក & ផ្ញើវីដេអូទំហំរហូតដល់ 2GB)")
    return pyro_client

def get_processor():
    global processor
    if processor is None:
        logger.info("កំពុងរៀបចំ VideoProcessor...")
        processor = VideoProcessor(whisper_model=WHISPER_MODEL)
    return processor

def get_remotion_processor():
    global remotion_proc
    if remotion_proc is None:
        logger.info("កំពុងរៀបចំ RemotionProcessor...")
        remotion_proc = RemotionProcessor()
    return remotion_proc

import re


def format_time_display(sec: float) -> str:
    """បំលែងវិនាទីទៅជាទម្រង់ 00:00.00 (នាទី:វិនាទី)"""
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"

def build_srt_content(words_list: list) -> str:
    """បង្កើតទម្រង់ SRT Standard ផ្លូវការពីបញ្ជីពាក្យ/ឃ្លា"""
    srt_blocks = []
    for i, w in enumerate(words_list):
        txt = str(w.get("word", "")).strip()
        if not txt:
            continue
        st = max(0.0, float(w.get("start", 0)))
        et = max(st + 0.1, float(w.get("end", st + 1.5)))
        st_h = int(st // 3600)
        st_m = int((st % 3600) // 60)
        st_s = st % 60
        et_h = int(et // 3600)
        et_m = int((et % 3600) // 60)
        et_s = et % 60
        tc_str = f"{st_h:02d}:{st_m:02d}:{int(st_s):02d},{int(round((st_s % 1)*1000)):03d} --> {et_h:02d}:{et_m:02d}:{int(et_s):02d},{int(round((et_s % 1)*1000)):03d}"
        srt_blocks.append(f"{i+1}\n{tc_str}\n{txt}\n")
    return "\n".join(srt_blocks)

def process_edit_input(words: list, user_text: str):
    """
    កែប្រែពាក្យខុសដោយរក្សា Timestamps ឱ្យត្រូវមាត់ ១០០%៖
    1. កែទាំង Timestamp និងអត្ថបទ: "1. [00:00.50 ➔ 00:02.80] ពាក្យថ្មី"
    2. កែតាមលេខជួរ (Line Number): "2 = ពាក្យថ្មី" ឬ "2. ពាក្យថ្មី"
    3. Find & Replace: "ពាក្យចាស់ -> ពាក្យថ្មី" ឬ "ដូរ កាហ្វេ ទៅ តែ"
    """
    changes = []
    edit_lines = [l.strip() for l in user_text.strip().split("\n") if l.strip()]

    from gemini_transcriber import parse_timecode

    for line in edit_lines:
        # 1. ពិនិត្យមើល Format កែទាំង Timestamp & Text (ឧ. 1. [00:00.50 ➔ 00:02.80] អក្សរថ្មី)
        tc_match = re.search(
            r"^(\d+)[\.\:\s]*(?:\[)?(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)\s*(?:➔|-->|->|—>|to)\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)(?:\])?\s*[:\|]?\s*(.+)$",
            line,
            re.IGNORECASE
        )
        if tc_match:
            idx = int(tc_match.group(1)) - 1
            st_str = tc_match.group(2)
            et_str = tc_match.group(3)
            new_text = re.sub(r"<[^>]+>", "", tc_match.group(4)).strip()
            if 0 <= idx < len(words):
                try:
                    words[idx]["start"] = parse_timecode(st_str)
                    words[idx]["end"] = parse_timecode(et_str)
                except Exception:
                    pass
                old_text = words[idx]["word"]
                words[idx]["word"] = new_text
                changes.append(f"ជួរទី {idx+1} (កែទាំងពេល & អត្ថបទ)៖ [{st_str} ➔ {et_str}] «{new_text}»")
                continue

        # 2. បើ User កែតាមលេខជួរ (សម្អាត timestamp ចាស់ចេញបើមានជាប់មក)
        line_clean = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?\s*(?:➔|-->|->|—>|to)\s*\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?\]\s*[:\|]?\s*", "", line)
        line_num_match = re.match(r"^(\d+)[\.\:\=\-\>\s]+(.+)$", line_clean)
        if line_num_match:
            idx = int(line_num_match.group(1)) - 1
            new_text = re.sub(r"<[^>]+>", "", line_num_match.group(2)).strip()
            if 0 <= idx < len(words):
                old_text = words[idx]["word"]
                words[idx]["word"] = new_text
                changes.append(f"ជួរទី {idx+1}៖ «{old_text}» ➡️ «{new_text}»")
                continue

        # 3. ពិនិត្យមើល Format Find & Replace: "ចាស់ -> ថ្មី" ឬ "ចាស់ ទៅ ថ្មី"
        sep_found = None
        for sep in ["->", "=>", " ទៅ ", " : ", ":", "="]:
            if sep in line:
                sep_found = sep
                break

        if sep_found:
            parts = line.split(sep_found, 1)
            old_w = parts[0].strip()
            new_w = parts[1].strip()
            old_w = re.sub(r"^(ដូរ|កែ|ប្តូរ)\s*", "", old_w).strip()
            if old_w and new_w:
                found_count = 0
                for item in words:
                    if old_w in item["word"]:
                        item["word"] = item["word"].replace(old_w, new_w)
                        found_count += 1
                if found_count > 0:
                    changes.append(f"«{old_w}» ➡️ «{new_w}» ({found_count} កន្លែង)")
                else:
                    changes.append(f"⚠️ រកមិនឃើញពាក្យ «{old_w}» ក្នុងវីដេអូទេ")

    return words, changes

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """សារស្វាគមន៍ /start"""
    welcome_text = (
        "👋 **ជំរាបសួរ! ខ្ញុំជា AI Video Auto-Cut & Subtitle Bot ជំនាន់ថ្មី** 🎬\n\n"
        "⚡ **ស្រួលប្រើបំផុត៖**\n"
        "1. គ្រាន់តែផ្ញើវីដេអូមក (គាំទ្ររហូតដល់ **2,000MB / 2 GB**)\n"
        "2. AI នឹងផ្ញើអត្ថបទសម្ដីនិយាយតាមលេខជួរនីមួយៗ\n"
        "3. បើត្រូវអស់ហើយ ចុច **[ 🚀 យល់ព្រម Render ]** ភ្លាម!\n"
        "4. បើមានពាក្យខុស គ្រាន់តែផ្ញើ `ពាក្យខុស -> ពាក្យត្រូវ` ឬ `លេខជួរ = ពាក្យត្រូវ` (រក្សាត្រូវមាត់ ១០០%)!\n\n"
        "✨ ចលនា Spring Pop + Font ខ្មែរ TikTok Viral + 12 Auto SFX + BGM Ducking ស្វ័យប្រវត្តិ។\n\n"
        "👉 *ផ្ញើវីដេអូដើម្បីចាប់ផ្ដើមឥឡូវនេះបាន!*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """សារជំនួយ /help"""
    help_text = (
        "ℹ️ **ការណែនាំ៖**\n\n"
        "- **ទំហំវីដេអូ:** គាំទ្ររហូតដល់ **2,000MB (2 GB)** តាមរយៈប្រព័ន្ធ MTProto ល្បឿនលឿន\n"
        "- **របៀបកែពាក្យខុស (ត្រូវមាត់ ១០០%):**\n"
        "  • ផ្ញើ: `ពាក្យខុស -> ពាក្យត្រូវ` (ឧ. `កាហ្វេ -> តែបៃតង`)\n"
        "  • ឬផ្ញើ: `លេខជួរ = ពាក្យថ្មី` (ឧ. `2 = សួស្តីបងប្អូន`)"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ទទួលវីដេអូ -> ទាញយក -> Transcribe -> ផ្ញើអត្ថបទតាមលេខជួរឱ្យ User ពិនិត្យ"""
    message = update.message
    video_obj = message.video or message.document

    if not video_obj:
        await message.reply_text("សូមផ្ញើជា file វីដេអូ! (Video file)")
        return

    file_size = getattr(video_obj, "file_size", 0) or 0
    if file_size > 2000 * 1024 * 1024:
        await message.reply_text("⚠️ វីដេអូនេះធំជាង 2GB (2,000MB)! Telegram កម្រិតការផ្ទុកត្រឹម 2GB។")
        return

    chat_id = message.chat_id
    msg_id = message.message_id
    file_id = video_obj.file_id

    file_size_mb = file_size / (1024 * 1024) if file_size else 0
    size_str = f" ({file_size_mb:.1f}MB)" if file_size_mb > 0 else ""

    status_msg = await message.reply_text(
        f"📥 **កំពុងទាញយក និងឱ្យ AI ស្ដាប់សម្ដីនិយាយក្នុងវីដេអូ{size_str}...** 🧠\n*(សូមរង់ចាំបន្តិច)*",
        parse_mode="Markdown"
    )

    input_filename = f"input_{chat_id}_{msg_id}.mp4"
    output_filename = f"output_{chat_id}_{msg_id}.mp4"
    input_path = str(TEMP_DIR / input_filename)
    output_path = str(TEMP_DIR / output_filename)

    context.user_data["input_path"] = input_path
    context.user_data["output_path"] = output_path
    context.user_data["pending_chat_id"] = chat_id
    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_message_id"] = msg_id

    # ការកំណត់ស្ដង់ដារ (លំនាំដើមស្អាតបំផុត)
    context.user_data["selected_theme"] = "tiktok_viral"
    context.user_data["selected_style_label"] = "🔥 TikTok Viral Gold (Kdam Thmor)"
    context.user_data["bgm_choice"] = "lofi"
    context.user_data["bgm_label"] = "☕ Lofi Chill"
    context.user_data["lang_code"] = "km"
    context.user_data["lang_label"] = "ភាសាខ្មែរ 🇰🇭"

    try:
        downloaded = False
        if file_size and file_size <= 20 * 1024 * 1024:
            try:
                tg_file = await context.bot.get_file(file_id)
                await tg_file.download_to_drive(custom_path=input_path)
                downloaded = True
            except Exception as e:
                logger.warning(f"Standard download failed: {e}. Switching to MTProto...")

        if not downloaded:
            pyro = await get_pyro_client()
            if not pyro:
                raise RuntimeError("Pyrogram MTProto មិនទាន់ដំណើរការ!")

            last_dl_edit = 0.0
            async def dl_progress(current, total):
                nonlocal last_dl_edit
                try:
                    now = time.time()
                    if now - last_dl_edit >= 3.5 or current == total:
                        last_dl_edit = now
                        pct = (current * 100) / (total or 1)
                        cur_mb = current / (1024 * 1024)
                        tot_mb = (total / (1024 * 1024)) if total else (file_size / (1024 * 1024))
                        try:
                            await status_msg.edit_text(
                                f"📥 **កំពុងទាញយកវីដេអូ ({pct:.0f}%)...** ⚡\n"
                                f"📊 ទំហំ៖ `{cur_mb:.1f}MB / {tot_mb:.1f}MB`\n"
                                f"*(សូមរង់ចាំដំណើរការទាញយកពេញលេញ)*",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

            msg = await pyro.get_messages(chat_id, msg_id)
            dl_result = None
            if msg and (msg.video or msg.document):
                dl_result = await pyro.download_media(msg, file_name=input_path, progress=dl_progress)
            if not dl_result:
                dl_result = await pyro.download_media(file_id, file_name=input_path, progress=dl_progress)
            if dl_result and os.path.exists(dl_result):
                if os.path.abspath(dl_result) != os.path.abspath(input_path):
                    if os.path.exists(input_path):
                        os.remove(input_path)
                    os.rename(dl_result, input_path)
                downloaded = True

        if not downloaded or not os.path.exists(input_path):
            await status_msg.edit_text("❌ មិនអាចទាញយកវីដេអូបានទេ សូមផ្ញើវីដេអូម្ដងទៀត!")
            return

        actual_size = os.path.getsize(input_path)
        if file_size and actual_size < int(file_size * 0.98):
            logger.warning(f"Downloaded video truncated! Actual: {actual_size}, Expected: {file_size}")
            try:
                os.remove(input_path)
            except Exception:
                pass
            await status_msg.edit_text(
                f"❌ **ការទាញយកមិនពេញលេញ (បាត់បង់ទិន្នន័យកណ្តាលទី)៖**\n\n"
                f"• ទាញយកបាន៖ `{actual_size / (1024*1024):.1f}MB`\n"
                f"• ទំហំពេញ៖ `{file_size / (1024*1024):.1f}MB`\n\n"
                f"សូមផ្ញើវីដេអូនេះម្ដងទៀត ដើម្បីឱ្យ Bot ទាញយកឡើងវិញពេញលេញ!",
                parse_mode="Markdown"
            )
            return

        await status_msg.edit_text("🧠 **AI កំពុងស្ដាប់សំឡេងទាញយកពាក្យសម្ដី & Timestamps...** 🎙️", parse_mode="Markdown")

        r_proc = get_remotion_processor()
        loop = asyncio.get_running_loop()
        words, hook_title = await loop.run_in_executor(
            None,
            r_proc.transcribe_video,
            input_path,
            None  # ស្គាល់គ្រប់ភាសាដោយស្វ័យប្រវត្តិ (Auto-detect all languages)
        )

        detected_lang = getattr(r_proc.transcriber, "detected_language", "km")
        lang_flags = {
            "km": "🇰🇭 ភាសាខ្មែរ (Khmer)",
            "en": "🇬🇧 អង់គ្លេស (English)",
            "zh": "🇨🇳 ចិន (Chinese)",
            "th": "🇹🇭 ថៃ (Thai)",
            "vi": "🇻🇳 វៀតណាម (Vietnamese)",
            "ja": "🇯🇵 ជប៉ុន (Japanese)",
            "ko": "🇰🇷 កូរ៉េ (Korean)",
            "fr": "🇫🇷 បារាំង (French)",
            "es": "🇪🇸 អេស្ប៉ាញ (Spanish)",
            "mixed": "🌐 ភាសាចម្រុះ (Multilingual)"
        }
        lang_label = lang_flags.get(detected_lang, f"🌐 {detected_lang.upper()}")

        context.user_data["words"] = words
        context.user_data["hook_title"] = hook_title
        context.user_data["detected_lang"] = detected_lang
        context.user_data["lang_label"] = lang_label
        context.user_data["awaiting_edited_text"] = True

        # បង្កើតអត្ថបទតាមជួរលេខរៀងព្រមទាំង Timestamps ច្បាស់លាស់ (00:00.00 ➔ 00:02.50)
        formatted_lines = []
        for i, w in enumerate(words):
            txt = w.get("word", "").strip()
            if not txt:
                continue
            st = float(w.get("start", 0))
            et = float(w.get("end", 0))
            sfx_tag = f" 🔔 [{w['sfx']}]" if w.get("sfx") else ""
            formatted_lines.append(f"{i+1}. [{format_time_display(st)} ➔ {format_time_display(et)}] {txt}{sfx_tag}")

        if not formatted_lines:
            lines_text = "(មិនមានសម្ដីនិយាយក្នុងវីដេអូទេ)"
            await message.reply_text(
                f"📝 **អត្ថបទសម្ដីនិយាយក្នុងវីដេអូ (០ ឃ្លា)៖**\n\n{lines_text}"
            )
        else:
            header = (
                f"📝 **អត្ថបទសម្ដីនិយាយក្នុងវីដេអូ ({len(formatted_lines)} ឃ្លា)៖**\n"
                f"🌐 **ភាសាដែល AI រកឃើញ៖** {lang_label}\n"
                f"⏱ *Timestamps ត្រូវមាត់ ១០០% (SRT / Timecode Format)*\n\n"
            )
            chunk = header
            for line_item in formatted_lines:
                if len(chunk) + len(line_item) + 2 > 3800:
                    await message.reply_text(chunk)
                    chunk = ""
                chunk += line_item + "\n"
            if chunk.strip():
                await message.reply_text(chunk.strip())

        # សារទី ២: ប៊ូតុងបញ្ជា
        keyboard = [
            [
                InlineKeyboardButton("⚡ របៀប ១៖ Quick Viral Pop", callback_data="action_render_quick"),
                InlineKeyboardButton("📊 របៀប ២៖ Motion Explainer & Raw B-Roll", callback_data="action_render_story")
            ],
            [
                InlineKeyboardButton("📥 ទាញយកឯកសារ Subtitle (.SRT)", callback_data="action_download_srt"),
                InlineKeyboardButton("🎨 ប្ដូរ Font ឬភ្លេង (ជម្រើសបន្ថែម)", callback_data="action_customize")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        guide_text = (
            "💡 **របៀបកែពាក្យខុសឱ្យត្រូវមាត់ ១០០% (ជ្រើសមួយណាក៏បាន)៖**\n\n"
            "👉 **វិធីទី ១ (ស្រួលបំផុត) ៖** ផ្ញើ «ពាក្យខុស -> ពាក្យត្រូវ»\n"
            "   *(ឧទាហរណ៍៖ `កាហ្វេ -> តែបៃតង`)*\n\n"
            "👉 **វិធីទី ២ ៖** កែតាមលេខជួរ «លេខជួរ = ពាក្យថ្មី»\n"
            "   *(ឧទាហរណ៍៖ `2 = សួស្តីពុកម៉ែបងប្អូន`)*\n\n"
            "• **បើត្រូវអស់ហើយ ៖** ចុចប៊ូតុង **[ 🚀 យល់ព្រម Render វីដេអូ ]** ខាងក្រោមភ្លាម!"
        )

        await status_msg.edit_text(guide_text, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        logger.exception("ជួបបញ្ហាពេលដំណើរការវីដេអូ:")
        await status_msg.edit_text(f"❌ ជួបបញ្ហា៖ {str(e)}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ពេល User ផ្ញើពាក្យដែលត្រូវកែ (Find & Replace ឬ កែរូបភាព B-Roll ឬ កែតាមលេខជួរ)"""
    text = (update.message.text or "").strip()

    # 1. ពិនិត្យមើលថាតើ User កំពុងនៅក្នុង Mode កែអត្ថបទ/ចំណងជើងប្លង់ Overlay
    txt_idx = context.user_data.get("editing_overlay_txt_idx")
    story_ovs = context.user_data.get("story_overlays", [])
    if txt_idx is not None and story_ovs and txt_idx < len(story_ovs):
        new_topic = text.strip()
        story_ovs[txt_idx]["topic"] = new_topic
        story_ovs[txt_idx]["highlightWord"] = new_topic
        story_ovs[txt_idx]["headlinePrefix"] = ""
        context.user_data["story_overlays"] = story_ovs
        context.user_data["editing_overlay_txt_idx"] = None
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="story_rerender_now")],
            [InlineKeyboardButton("🖼️ កែប្លង់ផ្សេងទៀត", callback_data="story_edit_menu")]
        ])
        await update.message.reply_text(
            f"✅ **បានកែចំណងជើងប្លង់ទី {txt_idx+1} ទៅជា «{new_topic}» ដោយជោគជ័យ!**\n\n"
            "ចុច **«Re-render វីដេអូ»** ដើម្បីទទួលវីដេអូថ្មីភ្លាមៗ",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # 2. ពិនិត្យមើលថាតើ User កំពុងនៅក្នុង Mode កែរូបភាព B-Roll
    scene_idx = context.user_data.get("editing_story_scene_idx")
    story_ovs = context.user_data.get("story_overlays")
    if scene_idx is not None and story_ovs and scene_idx < len(story_ovs):
        ov = story_ovs[scene_idx]
        topic = ov.get("topic", f"ប្លង់ទី {scene_idx+1}")
        query_text = text.strip()

        msg_search = await update.message.reply_text(
            f"🔍 កំពុងស្វែងរករូបថតពិតកម្រិតច្បាស់ (Free Stock Photo) សម្រាប់: `{query_text}`...",
            parse_mode="Markdown"
        )
        import image_story_generator
        import time
        r_proc = get_remotion_processor()
        img_name = ov.get("imageSrc")
        if not img_name or not str(img_name).strip():
            img_name = f"stock_broll_{int(time.time() * 1000)}_{scene_idx + 1}.jpg"
            ov["imageSrc"] = img_name
            ov["layout"] = "real_broll"
        target_path = os.path.join(r_proc.public_dir, img_name)
        os.makedirs(r_proc.public_dir, exist_ok=True)

        success = image_story_generator.fetch_free_stock_photo(query_text, target_path)
        if success:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="story_rerender_now")],
                [InlineKeyboardButton("🖼️ កែប្លង់ផ្សេងទៀត", callback_data="story_edit_menu")]
            ])
            with open(target_path, "rb") as pf:
                await update.message.reply_photo(
                    photo=pf,
                    caption=f"✅ **រកឃើញរូបថតពិតថ្មីស្អាតកម្រិតច្បាស់សម្រាប់ប្លង់ទី {scene_idx+1} («{query_text}»)!**\n\n"
                            f"ចុច **«Re-render វីដេអូ»** ដើម្បីទទួលវីដេអូថ្មីភ្លាមៗ",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            await msg_search.delete()
        else:
            await msg_search.edit_text(
                f"⚠️ រកមិនឃើញរូបថតសម្រាប់ `{query_text}` ទេ! សូមសាកល្បងពាក្យជាភាសាអង់គ្លេសផ្សេងទៀត ឬផ្ញើរូបភាពដោយផ្ទាល់មកទីនេះ។",
                parse_mode="Markdown"
            )
        context.user_data["editing_story_scene_idx"] = None
        return

    if not context.user_data.get("awaiting_edited_text") or not context.user_data.get("words"):
        await update.message.reply_text(
            "👋 **ជំរាបសួរ!** សូមផ្ញើជា **File វីដេអូ** មកកាន់ខ្ញុំ ដើម្បីចាប់ផ្ដើមកាត់ត និងដាក់ Subtitle ស្អាតៗ! 🎬",
            parse_mode="Markdown"
        )
        return

    text = update.message.text.strip()

    # ពិនិត្យមើលថាតើ User ចង់ប្ដូរ Font តាមឈ្មោះ ឬលេខ (ឧ. font naga ឬ font 10)
    lower_t = text.lower()
    if lower_t.startswith("font ") or lower_t.startswith("ពុម្ព "):
        query_font = re.sub(r"^(font|ពុម្ព)\\s*", "", text, flags=re.IGNORECASE).strip()
        matched = None
        if query_font.isdigit():
            idx = int(query_font) - 1
            if 0 <= idx < len(ALL_FONTS):
                matched = ALL_FONTS[idx]
        if not matched:
            for f_obj in ALL_FONTS:
                if query_font.lower() in f_obj["name"].lower():
                    matched = f_obj
                    break
        if matched:
            font_name = matched["name"]
            context.user_data["selected_custom_font"] = font_name
            context.user_data["selected_style_label"] = f"🇰🇭 {font_name}"
            keyboard = [
                [
            InlineKeyboardButton("⚡ របៀប ១៖ Quick Viral Pop", callback_data="action_render_quick"),
            InlineKeyboardButton("📊 របៀប ២៖ Motion Explainer & Raw B-Roll", callback_data="action_render_story")
        ],
                [InlineKeyboardButton("🎨 ប្ដូរ Font ឬភ្លេង", callback_data="action_customize")]
            ]
            await update.message.reply_text(
                f"✅ **បានជ្រើសរើស Font «{font_name}» ដោយជោគជ័យ!** 🎨\n\n"
                "👉 ចុចខាងក្រោមដើម្បី Render វីដេអូ៖",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

    words = context.user_data.get("words", [])
    words, changes = process_edit_input(words, text)
    context.user_data["words"] = words

    if not changes:
        await update.message.reply_text(
            "⚠️ **មិនអាចកែបានទេ!** សូមផ្ញើតាមទម្រង់ខាងក្រោម៖\n"
            "• `ពាក្យខុស -> ពាក្យត្រូវ` (ឧទាហរណ៍៖ `កាហ្វេ -> តែបៃតង`)\n"
            "• ឬ `លេខជួរ = ពាក្យថ្មី` (ឧទាហរណ៍៖ `2 = សួស្តីពុកម៉ែបងប្អូន`)",
            parse_mode="Markdown"
        )
        return

    changes_summary = "\n".join([f"• {c}" for c in changes])

    if context.user_data.get("last_mode"):
        keyboard = [
            [InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="action_rerender_now")],
            [InlineKeyboardButton("✏️ កែអត្ថបទបន្ថែមទៀត", callback_data="action_edit_subtitles")]
        ]
        prompt_txt = "👉 **ចុចខាងក្រោមដើម្បី Re-render វីដេអូថ្មីភ្លាមៗ ៖**"
    else:
        keyboard = [
            [
                InlineKeyboardButton("⚡ របៀប ១៖ Quick Viral Pop", callback_data="action_render_quick"),
                InlineKeyboardButton("📊 របៀប ២៖ Motion Explainer & Raw B-Roll", callback_data="action_render_story")
            ],
            [InlineKeyboardButton("🎨 ប្ដូរ Font ឬភ្លេង", callback_data="action_customize")]
        ]
        prompt_txt = "👉 **ចុចប៊ូតុងខាងក្រោមដើម្បីបង្កើតវីដេអូ៖**"

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ **បានកែសម្រួលដោយជោគជ័យ (រក្សា Timestamps ត្រូវមាត់ ១០០%)៖**\n\n"
        f"{changes_summary}\n\n"
        f"{prompt_txt}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_customize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """បង្ហាញម៉ឺនុយជ្រើសរើស Font & Palette (Top Picks + 293 Fonts Library)"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("🌟 Kantumruy Pro (CapCut Hot)", callback_data="font_kantumruy"),
            InlineKeyboardButton("🔥 Kdam Thmor (TikTok Gold)", callback_data="font_tiktok"),
        ],
        [
            InlineKeyboardButton("👑 Koulen Bold (Punchy)", callback_data="font_koulen"),
            InlineKeyboardButton("⚡ Dangrek (Neon Comic)", callback_data="font_tilt"),
        ],
        [
            InlineKeyboardButton("🇰🇭 បាត់ដំបង (Battambang Bold)", callback_data="font_battambang"),
            InlineKeyboardButton("✍️ អក្សរឆ្លាក់ដៃ (Fasthand Art)", callback_data="font_fasthand"),
        ],
        [
            InlineKeyboardButton("💎 AKbalthom Naga (Modern)", callback_data="font_akbalthom_naga"),
            InlineKeyboardButton("🏛️ Royal Moul (មហោឡារិក)", callback_data="font_moul"),
        ],
        [
            InlineKeyboardButton("🎬 បូកគោ (Bokor Cinematic)", callback_data="font_bokor"),
            InlineKeyboardButton("📱 Samsung Khmer (Modern Tech)", callback_data="font_samsung"),
        ],
        [
            InlineKeyboardButton("📚 បញ្ជី Font ខ្មែរទាំងអស់ (293 Fonts)", callback_data="fontpage_0"),
        ],
        [
            InlineKeyboardButton("🔙 ថយក្រោយ (ត្រឡប់ទៅ Render)", callback_data="action_back_to_ready")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🎨 **សូមជ្រើសរើសម៉ូដ Font អក្សរខ្មែរដែលអ្នកពេញចិត្ត៖**\n\n"
        "💡 _បងក៏អាចវាយឈ្មោះ Font ផ្ញើមកក្នុងឆាតបានដែរ ឧទាហរណ៍៖ `font naga` ឬ `font moul`!_",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_font_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ពេល User ជ្រើសរើស Font រួច បង្ហាញជម្រើសភ្លេង BGM"""
    query = update.callback_query
    await query.answer()

    data_key = query.data.replace("font_", "")
    remotion_themes = {
        "kantumruy": ("capcut_kantumruy", "🌟 Kantumruy Pro (CapCut Viral Gold)", "Kantumruy Pro"),
        "tiktok": ("tiktok_viral", "🔥 TikTok Viral Gold (Kdam Thmor)", "Kdam Thmor Pro"),
        "koulen": ("koulen_punch", "👑 Coral Fire (Koulen Bold)", "Koulen"),
        "tilt": ("comic_tilt", "⚡ Neon Lime (Dangrek Comic)", "Dangrek"),
        "battambang": ("capcut_battambang", "🇰🇭 Battambang Bold (Cyan Pop)", "Khmer OS Battambang"),
        "fasthand": ("capcut_fasthand", "✍️ Fasthand Art (Hot Pink)", "Khmer OS Fasthand"),
        "bokor": ("capcut_bokor", "🎬 Bokor Cinematic (Golden Amber)", "Khmer OS Bokor"),
        "samsung": ("capcut_samsung", "📱 Samsung Smart Khmer (Ice White)", "Samsung Khmer"),
        "akbalthom_naga": ("tiktok_viral", "💎 AKbalthom Naga Bold", "AKbalthom Naga"),
        "siemreap": ("capcut_siemreap", "🌊 Siemreap Elegant (Soft Gold)", "Khmer OS Siemreap"),
        "moul": ("royal_moul", "🏛️ Royal Moul Gold (មហោឡារិក)", "Khmer OS Muol"),
        "frost": ("frost_diamond", "💎 Frost Diamond (Koulen Ice)", "Koulen"),
        "pink": ("bubblegum_pink", "🌸 Barbie Bubblegum Pink (Dangrek)", "Dangrek"),
        "violet": ("cyber_purple", "💜 Cyber Violet (Kdam Thmor)", "Kdam Thmor Pro"),
        "lava": ("lava_orange", "🌋 Lava Heat Orange (Dangrek)", "Dangrek"),
        "cyber": ("cyber_cyan", "🚀 Electric Cyan (Kdam Neon)", "Kdam Thmor Pro"),
    }

    if data_key in remotion_themes:
        item = remotion_themes[data_key]
        remotion_theme = item[0]
        style_label = item[1]
        custom_font_name = item[2] if len(item) > 2 else None
    else:
        remotion_theme, style_label, custom_font_name = ("tiktok_viral", "🔥 TikTok Viral Gold", None)

    context.user_data["selected_theme"] = remotion_theme
    context.user_data["selected_style_label"] = style_label
    context.user_data["selected_custom_font"] = custom_font_name

    keyboard = [
        [
            InlineKeyboardButton("☕ Lofi Chill (ស្រទន់ លំហែ)", callback_data="bgm_lofi"),
            InlineKeyboardButton("🔥 Upbeat Pop (រស់រវើក)", callback_data="bgm_upbeat"),
        ],
        [
            InlineKeyboardButton("⚡ Hype Drive (កម្លាំងចិត្ត)", callback_data="bgm_hype"),
            InlineKeyboardButton("🔇 គ្មានភ្លេង (No Music)", callback_data="bgm_none"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ ម៉ូដ Font៖ **{style_label}**\n\n"
        "👉 **សូមជ្រើសរើសភ្លេងកំដរ (Background Music)៖**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_font_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ទំព័ររុករក Font ទាំង ២៩៣ ក្នុងម៉ាស៊ីន (Pagination)"""
    query = update.callback_query
    await query.answer()

    page = int(query.data.replace("fontpage_", ""))
    page_size = 8
    total_fonts = len(ALL_FONTS)
    total_pages = max(1, (total_fonts + page_size - 1) // page_size)

    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1

    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_fonts)
    page_fonts = ALL_FONTS[start_idx:end_idx]

    keyboard = []
    row = []
    for f_obj in page_fonts:
        f_name = f_obj["name"]
        short_label = f_name if len(f_name) <= 20 else f_name[:18] + ".."
        row.append(InlineKeyboardButton(short_label, callback_data=f"sel_font_{f_obj['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ មុន", callback_data=f"fontpage_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ បន្ទាប់", callback_data=f"fontpage_{page+1}"))
    keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⭐ ត្រឡប់ទៅ Font ពេញនិយម", callback_data="action_customize")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"📚 **បណ្ដុំ Font អក្សរខ្មែរទាំងអស់ (សរុប {total_fonts} Fonts)៖**\n\n"
        f"ទំព័រទី **{page+1} / {total_pages}** (បង្ហាញ Font លេខ {start_idx+1} ដល់ {end_idx})៖\n"
        "👉 _ចុចលើ Font ណាមួយខាងក្រោមដើម្បីប្រើ៖_",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_all_font_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ជ្រើសរើស Font ពីបញ្ជី ២៩៣ Fonts"""
    query = update.callback_query
    await query.answer()

    f_id = query.data.replace("sel_font_", "")
    matched_font = next((f for f in ALL_FONTS if f["id"] == f_id), None)
    if matched_font:
        font_name = matched_font["name"]
        context.user_data["selected_custom_font"] = font_name
        context.user_data["selected_theme"] = "tiktok_viral"
        style_label = f"🇰🇭 {font_name}"
    else:
        font_name = "Kdam Thmor Pro"
        style_label = "🔥 TikTok Gold"

    context.user_data["selected_style_label"] = style_label

    keyboard = [
        [
            InlineKeyboardButton("☕ Lofi Chill (ស្រទន់ លំហែ)", callback_data="bgm_lofi"),
            InlineKeyboardButton("🔥 Upbeat Pop (រស់រវើក)", callback_data="bgm_upbeat"),
        ],
        [
            InlineKeyboardButton("⚡ Hype Drive (កម្លាំងចិត្ត)", callback_data="bgm_hype"),
            InlineKeyboardButton("🔇 គ្មានភ្លេង (No Music)", callback_data="bgm_none"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ បានជ្រើសរើស Font៖ **{style_label}**\n\n"
        "👉 **សូមជ្រើសរើសភ្លេងកំដរ (Background Music)៖**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    keyboard = [
        [
            InlineKeyboardButton("☕ Lofi Chill (ស្រទន់ លំហែ)", callback_data="bgm_lofi"),
            InlineKeyboardButton("🔥 Upbeat Pop (រស់រវើក)", callback_data="bgm_upbeat"),
        ],
        [
            InlineKeyboardButton("⚡ Hype Drive (កម្លាំងចិត្ត)", callback_data="bgm_hype"),
            InlineKeyboardButton("🔇 គ្មានភ្លេង (No Music)", callback_data="bgm_none"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ ម៉ូដ Font៖ **{style_label}**\n\n"
        "👉 **សូមជ្រើសរើសភ្លេងកំដរ (Background Music)៖**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_bgm_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ពេល User ជ្រើសរើស BGM រួច បង្ហាញប៊ូតុង Render"""
    query = update.callback_query
    await query.answer()

    bgm_choice = query.data.replace("bgm_", "")
    bgm_labels = {
        "lofi": "☕ Lofi Chill",
        "upbeat": "🔥 Upbeat Pop",
        "hype": "⚡ Hype Drive",
        "none": "🔇 គ្មានភ្លេង (No Music)"
    }
    bgm_label = bgm_labels.get(bgm_choice, "☕ Lofi Chill")

    context.user_data["bgm_choice"] = bgm_choice
    context.user_data["bgm_label"] = bgm_label

    style_label = context.user_data.get("selected_style_label", "🔥 TikTok Viral Gold")

    keyboard = [
        [
            InlineKeyboardButton("⚡ របៀប ១៖ Quick Viral Pop", callback_data="action_render_quick"),
            InlineKeyboardButton("📊 របៀប ២៖ Motion Explainer & Raw B-Roll", callback_data="action_render_story")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ ម៉ូដ Font៖ **{style_label}**\n"
        f"✅ ភ្លេងកំដរ៖ **{bgm_label}**\n\n"
        "👉 **ការកំណត់រួចរាល់! ចុចប៊ូតុងខាងក្រោមដើម្បី Render៖**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_back_to_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ត្រឡប់ទៅប៊ូតុង Render វិញ"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("⚡ របៀប ១៖ Quick Viral Pop", callback_data="action_render_quick"),
            InlineKeyboardButton("📊 របៀប ២៖ Motion Explainer & Raw B-Roll", callback_data="action_render_story")
        ],
        [InlineKeyboardButton("🎨 ប្ដូរ Font ឬភ្លេង", callback_data="action_customize")]
    ]
    await query.edit_message_text(
        "👉 **ចុចប៊ូតុងខាងក្រោមដើម្បីបង្កើតវីដេអូ៖**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_render_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ដំណើរការ Render វីដេអូតាម Remotion CLI"""
    query = update.callback_query
    await query.answer()

    input_path = context.user_data.get("input_path")
    output_path = context.user_data.get("output_path")
    words = context.user_data.get("words", [])
    hook_title = context.user_data.get("hook_title", "")
    remotion_theme = context.user_data.get("selected_theme", "tiktok_viral")
    style_label = context.user_data.get("selected_style_label", "🔥 TikTok Viral Gold")
    bgm_choice = context.user_data.get("bgm_choice", "lofi")
    bgm_label = context.user_data.get("bgm_label", "☕ Lofi Chill")
    lang_code = context.user_data.get("lang_code", "km")
    lang_label = context.user_data.get("lang_label", "ភាសាខ្មែរ 🇰🇭")
    chat_id = context.user_data.get("pending_chat_id", query.message.chat_id)

    if not input_path or not os.path.exists(input_path):
        await query.edit_message_text("⚠️ បាត់បង់ឯកសារវីដេអូបណ្ដោះអាសន្ន! សូមផ្ញើវីដេអូម្ដងទៀត។")
        return

    try:
        await query.edit_message_text(
            f"⚙️ **កំពុងដំណើរការ៖** {style_label} | {bgm_label}\n\n"
            "🎙️ **ជំហានទី ១:** កាត់ Noise និងជម្រុញសំឡេងឱ្យច្បាស់បែប Studio...\n"
            "🎬 **ជំហានទី ២:** កាត់ Punch-In Zoom, បញ្ចូល 12 Auto SFX & BGM Ducking...\n"
            "⚡ **ជំហានទី ៣:** Remotion កំពុង Render វីដេអូ Kinetic Pop...",
            parse_mode="Markdown"
        )

        r_proc = get_remotion_processor()
        loop = asyncio.get_running_loop()
        custom_font = context.user_data.get("selected_custom_font", None)
        cached_vid = context.user_data.get("cached_clean_video", None)
        await loop.run_in_executor(
            None,
            lambda: r_proc.process_video(
                input_video_path=input_path,
                output_video_path=output_path,
                language=lang_code or "km",
                theme=remotion_theme,
                bgm=bgm_choice,
                show_progress_bar=True,
                words=words,
                hook_title=hook_title,
                custom_font=custom_font,
                cached_clean_video=cached_vid
            )
        )
        context.user_data["cached_clean_video"] = getattr(r_proc, "last_clean_video", None)

        caption_text = (
            f"✨ **វីដេអូកាត់តទាន់សម័យកម្រិត Pro រួចរាល់ហើយ!** 🎉\n"
            f"🎨 ម៉ូដ Font៖ {style_label}\n"
            f"🎵 ភ្លេងកំដរ៖ {bgm_label}\n\n"
            f"🚀 **បច្ចេកវិទ្យា Trending ជំនាន់ថ្មី៖**\n"
            f"• ⚡ **100% Mouth-Synced Subtitles:** អក្សរលោតត្រូវតាមមាត់និយាយ\n"
            f"• 🎵 **Smart Audio Ducking:** ភ្លេងបន្ថយ auto ពេលមនុស្សនិយាយ (11% -> 22%)\n"
            f"• 📊 **Retention Progress Bar:** របារពេលវេលាខាងក្រោមទប់ Watch Time\n"
            f"• ✂️ **Smart Silence Cut:** កាត់ចន្លោះស្ងាត់ (> 0.40s) ដោយមិនដាច់ដង្ហើម\n"
            f"• 🔍 **Dynamic Punch-In Jump Cut:** កាមេរ៉ា Zoom ប្ដូរប្លង់រៀងរាល់ ២-៣s\n"
            f"• 🔊 **12 Auto Sound Effects:** Whoosh, Cash, Ding, Buzzer, Tada, etc."
        )

        await query.edit_message_text(
            f"🚀 **រួចរាល់ហើយ! កំពុង Upload វីដេអូត្រឡប់មកវិញ...**",
            parse_mode="Markdown"
        )

        output_file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        import time
        last_edit_ts = [0.0]

        async def upload_progress_callback(current, total):
            now = time.time()
            if now - last_edit_ts[0] >= 3.0:  # Update every 3 seconds
                last_edit_ts[0] = now
                pct = int(current * 100 / total)
                mb_curr = current / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                try:
                    await query.edit_message_text(
                        f"🚀 **កំពុង Upload វីដេអូត្រឡប់មកវិញ... {pct}%** ({mb_curr:.1f} / {mb_tot:.1f} MB)",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        # ប្រសិនបើវីដេអូកាត់រួចធំជាង 50MB បញ្ជូនតាម Pyrogram MTProto
        if output_file_size > 50 * 1024 * 1024:
            logger.info(f"Uploading large video ({output_file_size / (1024*1024):.1f}MB) via Pyrogram MTProto...")
            pyro = await get_pyro_client()
            if pyro:
                await pyro.send_video(
                    chat_id=chat_id,
                    video=output_path,
                    caption=caption_text,
                    supports_streaming=True,
                    progress=upload_progress_callback
                )
            else:
                with open(output_path, "rb") as video_file:
                    await query.message.reply_video(
                        video=video_file,
                        caption=caption_text,
                        supports_streaming=True
                    )
        else:
            with open(output_path, "rb") as video_file:
                await query.message.reply_video(
                    video=video_file,
                    caption=caption_text,
                    supports_streaming=True,
                    read_timeout=300.0,
                    write_timeout=300.0
                )

        await query.message.delete()

        context.user_data["last_mode"] = "quick"
        context.user_data["pending_chat_id"] = chat_id
        context.user_data["awaiting_edited_text"] = True

        edit_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ កែប្រែអត្ថបទអក្សរ (Edit Subtitles)", callback_data="action_edit_subtitles")]
        ])
        await context.bot.send_message(
            chat_id=chat_id,
            text="💡 **ចង់កែអត្ថបទអក្សរ Subtitle ឡើងវិញទេ?**\n"
                 "លោកអ្នកអាចចុច **«✏️ កែប្រែអត្ថបទអក្សរ»** ដើម្បីកែពាក្យខុស រួច Re-render យ៉ាងលឿន !",
            reply_markup=edit_kb,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.exception("ជួបបញ្ហាពេល Process វីដេអូ:")
        await query.edit_message_text(f"❌ ជួបបញ្ហាពេលកែច្នៃវីដេអូ៖ {str(e)}")


async def handle_render_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ដំណើរការ Render វីដេអូបែប Mode 2: AI Visual Storyteller (RTX 3080 B-Roll & Transitions)"""
    query = update.callback_query
    await query.answer()

    input_path = context.user_data.get("input_path")
    output_path = context.user_data.get("output_path")
    words = context.user_data.get("words", [])
    hook_title = context.user_data.get("hook_title", "")
    remotion_theme = context.user_data.get("selected_theme", "tiktok_viral")
    style_label = context.user_data.get("selected_style_label", "🔥 TikTok Viral Gold")
    bgm_choice = context.user_data.get("bgm_choice", "lofi")
    bgm_label = context.user_data.get("bgm_label", "☕ Lofi Chill")
    lang_code = context.user_data.get("lang_code", "km")
    lang_label = context.user_data.get("lang_label", "ភាសាខ្មែរ 🇰🇭")
    chat_id = context.user_data.get("pending_chat_id", query.message.chat_id)

    if not input_path or not os.path.exists(input_path):
        await query.edit_message_text("⚠️ បាត់បង់ឯកសារវីដេអូបណ្ដោះអាសន្ន! សូមផ្ញើវីដេអូម្ដងទៀត។")
        return

    try:
        await query.edit_message_text(
            f"📊 **ដំណើរការ Mode 2៖ Motion Explainer & Raw B-Roll**\n"
            f"*{style_label} | {bgm_label}*\n\n"
            "🎙️ **ជំហានទី ១:** កាត់ Noise និងជម្រុញសំឡេងឱ្យច្បាស់បែប Studio...\n"
            "🧠 **ជំហានទី ២:** Gemini AI កំពុងវិភាគសាច់រឿង រកប្លង់ Motion Explainer...\n"
            "⏳ *សូមរង់ចាំបន្តិច...*",
            parse_mode="Markdown"
        )

        r_proc = get_remotion_processor()
        loop = asyncio.get_running_loop()

        # Step 2: Extract Visual Story Scenes with Gemini
        logger.info("🧠 Gemini កំពុងវិភាគសាច់រឿង រកប្លង់ Motion Explainer...")
        scenes = await loop.run_in_executor(None, r_proc.transcriber.extract_visual_story_scenes, words)

        await query.edit_message_text(
            f"📊 **ដំណើរការ Mode 2៖ Motion Explainer & Raw B-Roll**\n\n"
            f"✨ រកឃើញ **{len(scenes)} ប្លង់ Motion Graphic** ក្នុងសាច់រឿង!\n"
            "⚡ **ជំហានទី ៣:** រៀបចំប្លង់ Explainer (Split-Screen, Phone PIP, Reference Cards & Data Comparisons)...\n"
            "⏳ *រៀបចំ Motion Graphics & Real B-Roll...*",
            parse_mode="Markdown"
        )

        # Step 3: Generate Overlays
        import image_story_generator
        overlays = await loop.run_in_executor(
            None,
            image_story_generator.generate_visual_overlays,
            scenes,
            r_proc.public_dir
        )

        await query.edit_message_text(
            f"📊 **ដំណើរការ Mode 2៖ Motion Explainer & Raw B-Roll**\n\n"
            f"✅ រៀបចំ Motion Overlays **{len(overlays)} ប្លង់** រួចរាល់!\n"
            "🎬 **ជំហានទី ៤:** Remotion កំពុង Render វីដេអូបែប Motion Explainer (Sticker Highlights, Split-Screen & Raw B-Roll)...",
            parse_mode="Markdown"
        )

        # Step 4: Remotion Render with Visual Overlays
        custom_font = context.user_data.get("selected_custom_font", None)
        cached_vid = context.user_data.get("cached_clean_video", None)
        await loop.run_in_executor(
            None,
            lambda: r_proc.process_video(
                input_video_path=input_path,
                output_video_path=output_path,
                language=lang_code,
                theme=remotion_theme,
                bgm=bgm_choice,
                show_progress_bar=True,
                words=words,
                hook_title=hook_title,
                custom_font=custom_font,
                visual_overlays=overlays,
                cached_clean_video=cached_vid
            )
        )
        context.user_data["cached_clean_video"] = getattr(r_proc, "last_clean_video", None)

        # Pyrogram Realtime Upload Progress Bar
        final_file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        final_file_size_mb = final_file_size / (1024 * 1024) if final_file_size else 0

        last_percent = [-1]
        async def upload_progress_callback(current, total):
            if total > 0:
                pct = int((current / total) * 100)
                if pct != last_percent[0] and pct % 20 == 0:
                    last_percent[0] = pct
                    try:
                        await query.edit_message_text(
                            f"📤 **កំពុង Upload វីដេអូ AI Visual Story... {pct}%** ({current/(1024*1024):.1f}/{total/(1024*1024):.1f}MB)"
                        )
                    except Exception:
                        pass

        await query.edit_message_text(
            f"📤 **កំពុង Upload វីដេអូ AI Visual Story ({final_file_size_mb:.1f}MB) ទៅ Telegram...**"
        )

        pyro = await get_pyro_client()
        caption_text = (
            f"🎬 **វីដេអូ AI Visual Storyteller រួចរាល់ហើយ!** 🎨✨\n\n"
            f"• ប្រភេទ៖ **របៀបទី ២ (Motion Explainer & Raw B-Roll)**\n"
            f"• រូបភាព B-Roll៖ **{len(overlays)} ប្លង់ (NVIDIA RTX 3080)**\n"
            f"• ទម្រង់ Font៖ {style_label}\n"
            f"• ភ្លេង BGM៖ {bgm_label}\n"
            f"• ភាសា៖ {lang_label}\n\n"
            f"⚡ *កាត់តដោយប្រព័ន្ធ AI Visual Storyteller*"
        )
        if pyro and pyro.is_connected:
            await pyro.send_video(
                chat_id=chat_id,
                video=output_path,
                caption=caption_text,
                supports_streaming=True,
                progress=upload_progress_callback
            )
        else:
            with open(output_path, "rb") as vf:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vf,
                    caption=caption_text,
                    supports_streaming=True
                )

        await query.message.delete()

        # Save for interactive editing
        context.user_data["story_overlays"] = overlays
        context.user_data["pending_chat_id"] = chat_id
        context.user_data["last_mode"] = "story"
        context.user_data["awaiting_edited_text"] = True

        edit_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ កែប្រែអត្ថបទអក្សរ (Edit Subtitles)", callback_data="action_edit_subtitles")],
            [InlineKeyboardButton("📊 កែប្លង់ Motion / Reference Cards", callback_data="story_edit_menu")]
        ])
        await context.bot.send_message(
            chat_id=chat_id,
            text="💡 **ចង់កែប្រែអ្វីមួយឡើងវិញទេ?**\n"
                 "លោកអ្នកអាចកែអត្ថបទអក្សរ ឬដូរប្លង់រូបភាព B-Roll រួច Re-render យ៉ាងលឿន (~១៥-២៥ វិនាទី)!",
            reply_markup=edit_kb,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in handle_render_story: {e}", exc_info=True)
        await query.edit_message_text(f"❌ ជួបបញ្ហាពេលកែច្នៃវីដេអូ Mode 2៖ {str(e)}")


LAYOUT_LABELS = {
    "split_screen": "🔀 Split-Screen (50/50)",
    "cinematic_broll": "🎬 Cinematic B-Roll",
    "talking_head": "🗣️ Talking Head",
    "real_broll": "🎬 Cinematic B-Roll",
}

async def handle_story_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """បង្ហាញបញ្ជីប្លង់រូបភាព B-Roll ទាំងអស់សម្រាប់ User ជ្រើសរើសកែប្រែ"""
    query = update.callback_query
    await query.answer()

    overlays = context.user_data.get("story_overlays", [])
    if not overlays:
        await query.message.reply_text(
            "ℹ️ **បច្ចុប្បន្នមិនមានប្លង់ Motion Overlays ទេ** (វីដេអូដើម Talking Head សុទ្ធ ១០០%)!\n\n"
            "👉 លោកអ្នកអាចចុច Re-render ដើម្បីទទួលវីដេអូស្អាតភ្លាមៗ៖",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Re-render វីដេអូដើមសុទ្ធ", callback_data="story_rerender_now")],
                [InlineKeyboardButton("⬅️ ត្រឡប់ក្រោយ", callback_data="action_back_to_ready")]
            ])
        )
        return

    buttons = []
    for i, ov in enumerate(overlays):
        topic = ov.get("topic", f"ប្លង់ទី {i+1}")
        st = ov.get("start", 0)
        en = ov.get("end", st + 3.5)
        lay = ov.get("layout", "split_screen")
        arch = LAYOUT_LABELS.get(lay, "🔀 Split (50/50)")
        buttons.append([InlineKeyboardButton(f"{arch} ទី {i+1}៖ {topic} [{st:.1f}s - {en:.1f}s]", callback_data=f"story_pick_{i}")])

    # ប៊ូតុងបញ្ជាសំខាន់ៗ
    buttons.append([InlineKeyboardButton("🗑️ បិទ/លុប Overlays ទាំងអស់ (យកតែ Talking Head សុទ្ធ)", callback_data="story_del_all")])
    buttons.append([
        InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="story_rerender_now"),
        InlineKeyboardButton("⬅️ ត្រឡប់ក្រោយ", callback_data="action_back_to_ready")
    ])

    await query.message.reply_text(
        f"🎨 **បញ្ជីប្លង់ទាំង ៣ ទម្រង់ ({len(overlays)} ប្លង់)៖**\n"
        f"1. 🔀 **Split-Screen (50/50)** (លើ B-Roll / ក្រោម Speaker)\n"
        f"2. 🎬 **Cinematic B-Roll** (រូបភាពភាពយន្តពេញអេក្រង់)\n"
        f"3. 🗣️ **Talking Head** (វីដេអូដើមអ្នកនិយាយសុទ្ធ)\n\n"
        "👇 ចុចលើប្លង់ណាមួយដើម្បី **មើល Screenshot, ដូរទម្រង់, ដូររូបភាព ឬកែអត្ថបទ**៖",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )


async def handle_story_pick_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ពេល User ចុចជ្រើសរើសប្លង់ជាក់លាក់ណាមួយដើម្បីកែ ព្រមទាំងផ្ញើរូបភាព Screenshot ជូន User ពិនិត្យភ្លាមៗ!"""
    query = update.callback_query
    await query.answer()

    try:
        idx = int(query.data.replace("story_pick_", ""))
    except ValueError:
        return

    overlays = context.user_data.get("story_overlays", [])
    if not overlays or idx >= len(overlays):
        await query.message.reply_text("⚠️ រកមិនឃើញប្លង់នេះទេ!")
        return

    ov = overlays[idx]
    topic = ov.get("topic", f"ប្លង់ទី {idx+1}")
    st = float(ov.get("start", 0))
    en = float(ov.get("end", st + 3.5))
    curr_lay = ov.get("layout", "split_screen")
    arch_title = LAYOUT_LABELS.get(curr_lay, "🔀 Split-Screen (50/50)")

    # 1. ស្រង់រូបភាព Screenshot ជាក់ស្តែងចេញពីវីដេអូ
    chat_id = query.message.chat_id
    output_path = context.user_data.get("output_path") or context.user_data.get("input_path")
    preview_img = os.path.join(str(TEMP_DIR), f"scene_shot_{chat_id}_{idx}_{int(time.time())}.jpg")
    has_shot = False

    if output_path and os.path.exists(output_path):
        try:
            mid_sec = max(0.0, (st + en) / 2.0)
            ffmpeg_p = utils.get_ffmpeg_path()
            cmd = [
                ffmpeg_p,
                "-y",
                "-ss", f"{mid_sec:.2f}",
                "-i", output_path,
                "-vframes", "1",
                "-q:v", "2",
                preview_img
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            has_shot = os.path.exists(preview_img)
        except Exception as shot_err:
            logger.warning(f"Screenshot extract error: {shot_err}")

    caption = (
        f"📸 **រូបភាព Screenshot ប្លង់ទី {idx+1}៖ {arch_title}**\n\n"
        f"📌 **ប្រធានបទ៖** «{topic}»\n"
        f"⏱ **ពេលវេលា៖** `{st:.1f}s` ➔ `{en:.1f}s`\n"
        f"🎨 **ទម្រង់បច្ចុប្បន្ន៖** **{arch_title}**\n\n"
        f"👇 **ចុចប៊ូតុងខាងក្រោមដើម្បីដូរទម្រង់ប្លង់ ឬដូររូបភាព៖**"
    )

    action_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔀 ដូរជា Split-Screen (50/50)", callback_data=f"story_lay_split_{idx}"),
            InlineKeyboardButton("🎬 ដូរជា Cinematic B-Roll", callback_data=f"story_lay_broll_{idx}")
        ],
        [
            InlineKeyboardButton("🗣️ ដូរជា Talking Head (វីដេអូសុទ្ធ)", callback_data=f"story_lay_talk_{idx}"),
            InlineKeyboardButton("🖼️ ដូររូបថត B-Roll ថ្មី", callback_data=f"story_img_{idx}")
        ],
        [
            InlineKeyboardButton("✏️ កែអត្ថបទចំណងជើង", callback_data=f"story_txt_{idx}"),
            InlineKeyboardButton(f"🗑️ លុបប្លង់ទី {idx+1} ចោល", callback_data=f"story_del_{idx}")
        ],
        [
            InlineKeyboardButton("⚡ Re-render វីដេអូភ្លាមៗ", callback_data="story_rerender_now"),
            InlineKeyboardButton("⬅️ ត្រឡប់ទៅបញ្ជីប្លង់", callback_data="story_edit_menu")
        ]
    ])

    if has_shot:
        try:
            with open(preview_img, "rb") as pf:
                await query.message.reply_photo(photo=pf, caption=caption, reply_markup=action_kb, parse_mode="Markdown")
        except Exception as send_err:
            logger.warning(f"Send photo error: {send_err}")
            await query.message.reply_text(caption, reply_markup=action_kb, parse_mode="Markdown")
    else:
        await query.message.reply_text(caption, reply_markup=action_kb, parse_mode="Markdown")


async def handle_story_change_layout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ប្ដូរទម្រង់ប្លង់រវាង Split-Screen, Cinematic B-Roll, និង Talking Head"""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("_")
    lay_type = parts[2]
    idx = int(parts[3])

    target_map = {
        "split": "split_screen",
        "broll": "cinematic_broll",
        "talk": "talking_head"
    }
    target_layout = target_map.get(lay_type, "split_screen")

    overlays = context.user_data.get("story_overlays", [])
    if 0 <= idx < len(overlays):
        ov = overlays[idx]
        ov["layout"] = target_layout
        topic = ov.get("topic", f"ប្លង់ទី {idx+1}")
        arch_title = LAYOUT_LABELS.get(target_layout, target_layout)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Re-render វីដេអូភ្លាមៗ", callback_data="story_rerender_now")],
            [InlineKeyboardButton(f"📸 មើលប្លង់ទី {idx+1} ឡើងវិញ", callback_data=f"story_pick_{idx}")],
            [InlineKeyboardButton("⬅️ ត្រឡប់ទៅបញ្ជីប្លង់", callback_data="story_edit_menu")]
        ])
        await query.message.reply_text(
            f"✅ **បានប្ដូរទម្រង់ប្លង់ទី {idx+1} («{topic}») ទៅជា៖**\n"
            f"👉 **{arch_title}**\n\n"
            f"ចុច **«⚡ Re-render វីដេអូភ្លាមៗ»** ដើម្បីមើលលទ្ធផលវីដេអូថ្មី!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text("⚠️ រកមិនឃើញប្លង់នេះទេ!")


async def handle_story_delete_scene(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """លុបប្លង់ Overlay តែមួយជាក់លាក់"""
    query = update.callback_query
    await query.answer()

    try:
        idx = int(query.data.replace("story_del_", ""))
    except ValueError:
        return

    overlays = context.user_data.get("story_overlays", [])
    if 0 <= idx < len(overlays):
        deleted_ov = overlays.pop(idx)
        context.user_data["story_overlays"] = overlays
        topic = deleted_ov.get("topic", f"ប្លង់ទី {idx+1}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="story_rerender_now")],
            [InlineKeyboardButton("🖼️ កែប្លង់ផ្សេងទៀត", callback_data="story_edit_menu")]
        ])
        await query.message.reply_text(
            f"✅ **បានលុបប្លង់ទី {idx+1} («{topic}») ដោយជោគជ័យ!** (នៅសល់ {len(overlays)} ប្លង់)\n\n"
            "ចុច **«Re-render វីដេអូ»** ដើម្បីទទួលវីដេអូថ្មីភ្លាមៗ",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text("⚠️ រកមិនឃើញប្លង់នេះទេ!")


async def handle_story_delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """បិទ/លុប Motion Overlays ទាំងអស់ យកតែវីដេអូដើមសុទ្ធ"""
    query = update.callback_query
    await query.answer()

    context.user_data["story_overlays"] = []
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Re-render វីដេអូដើមសុទ្ធ", callback_data="story_rerender_now")]
    ])
    await query.message.reply_text(
        "✅ **បានបិទ Motion Overlays ទាំងអស់ជោគជ័យ!**\n\n"
        "ឥឡូវនេះវីដេអូរបស់លោកអ្នកនឹងបង្ហាញ **ពេញអេក្រង់ ១០០% វីដេអូដើមសុទ្ធ** ជាមួយ Subtitle ស្អាត គ្មានក្រាហ្វិក ឬប្លង់ណាមកបាំងឡើយ!\n\n"
        "👉 ចុចប៊ូតុងខាងក្រោមដើម្បី Re-render ភ្លាមៗ៖",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def handle_story_edit_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """កំណត់ Mode ឱ្យ User វាយអត្ថបទចំណងជើងថ្មី"""
    query = update.callback_query
    await query.answer()

    try:
        idx = int(query.data.replace("story_txt_", ""))
    except ValueError:
        return

    context.user_data["editing_overlay_txt_idx"] = idx
    context.user_data["editing_story_scene_idx"] = None
    overlays = context.user_data.get("story_overlays", [])
    topic = overlays[idx].get("topic", "") if idx < len(overlays) else ""
    await query.message.reply_text(
        f"✏️ **កែចំណងជើងប្លង់ទី {idx+1}** (បច្ចុប្បន្ន៖ «{topic}»)\n\n"
        "👉 *សូមវាយពាក្យថ្មីដែលត្រូវបង្ហាញ (ឧ. «ម្ហូបខ្មែរឆ្ងាញ់» ឬ «សិស្សរៀនធ្វើម្ហូប»)...*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ត្រឡប់ក្រោយ", callback_data=f"story_pick_{idx}")]])
    )


async def handle_story_edit_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """កំណត់ Mode ឱ្យ User ផ្ញើរូបភាព ឬវាយពាក្យស្វែងរក"""
    query = update.callback_query
    await query.answer()

    try:
        idx = int(query.data.replace("story_img_", ""))
    except ValueError:
        return

    context.user_data["editing_story_scene_idx"] = idx
    context.user_data["editing_overlay_txt_idx"] = None
    overlays = context.user_data.get("story_overlays", [])
    topic = overlays[idx].get("topic", "") if idx < len(overlays) else ""
    await query.message.reply_text(
        f"🖼️ **ដូររូបភាព B-Roll សម្រាប់ប្លង់ទី {idx+1} («{topic}»)**\n\n"
        "1️⃣ **ផ្ញើរូបភាព (Photo):** ផ្ញើរូបថតពីទូរស័ព្ទចូលទីនេះផ្ទាល់\n"
        "2️⃣ **វាយពាក្យស្វែងរក (Text):** វាយពាក្យ (ឧ. `cambodian food`, `cooking soup`, `fresh vegetables`)\n\n"
        "👉 *សូមផ្ញើរូបភាព ឬវាយពាក្យមកទីនេះ...*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ត្រឡប់ក្រោយ", callback_data=f"story_pick_{idx}")]])
    )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ពេល User ផ្ញើរូបភាព (Photo) មកជំនួសប្លង់ B-Roll"""
    idx = context.user_data.get("editing_story_scene_idx")
    overlays = context.user_data.get("story_overlays")

    if idx is None or not overlays or idx >= len(overlays):
        await update.message.reply_text(
            "👋 សូមផ្ញើជា **File វីដេអូ** មកកាន់ខ្ញុំដើម្បីកាត់ត ឬជ្រើសរើសប្លង់ B-Roll ជាមុនសិន! 🎬",
            parse_mode="Markdown"
        )
        return

    ov = overlays[idx]
    topic = ov.get("topic", f"ប្លង់ទី {idx+1}")
    import time
    r_proc = get_remotion_processor()
    img_name = ov.get("imageSrc")
    if not img_name or not str(img_name).strip():
        img_name = f"user_broll_{int(time.time() * 1000)}_{idx + 1}.jpg"
        ov["imageSrc"] = img_name
        ov["layout"] = "real_broll"
    target_path = os.path.join(r_proc.public_dir, img_name)
    os.makedirs(r_proc.public_dir, exist_ok=True)

    try:
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(target_path)
        context.user_data["story_overlays"] = overlays

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Re-render វីដេអូឥឡូវនេះ", callback_data="story_rerender_now")],
            [InlineKeyboardButton("🖼️ កែប្លង់ផ្សេងទៀត", callback_data="story_edit_menu")]
        ])

        await update.message.reply_text(
            f"✅ **បានដាក់រូបភាពផ្ទាល់ខ្លួនជំនួសប្លង់ទី {idx+1} («{topic}») រួចរាល់!**\n\n"
            f"ចុច **«Re-render វីដេអូ»** ដើម្បីទទួលវីដេអូថ្មីភ្លាមៗ ",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        context.user_data["editing_story_scene_idx"] = None
    except Exception as e:
        logger.error(f"Error replacing photo: {e}")
        await update.message.reply_text(f"❌ ជួបបញ្ហាពេលរក្សាទុករូបភាព៖ {e}")


async def handle_story_rerender_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-render វីដេអូឡើងវិញយ៉ាងលឿនជាមួយរូបភាពថ្មី (~15-25 វិនាទី)"""
    query = update.callback_query
    await query.answer()

    input_path = context.user_data.get("input_path")
    output_path = context.user_data.get("output_path")
    words = context.user_data.get("words", [])
    hook_title = context.user_data.get("hook_title", "")
    remotion_theme = context.user_data.get("selected_theme", "tiktok_viral")
    style_label = context.user_data.get("selected_style_label", "🔥 TikTok Viral Gold")
    bgm_choice = context.user_data.get("bgm_choice", "lofi")
    bgm_label = context.user_data.get("bgm_label", "☕ Lofi Chill")
    lang_code = context.user_data.get("lang_code", "km")
    custom_font = context.user_data.get("selected_custom_font", None)
    overlays = context.user_data.get("story_overlays", [])
    chat_id = context.user_data.get("pending_chat_id", query.message.chat_id)

    if not input_path or not os.path.exists(input_path):
        await query.message.reply_text("⚠️ បាត់បង់ឯកសារវីដេអូដើម! សូមផ្ញើវីដេអូម្ដងទៀត។")
        return

    tot_dur = max([float(w.get("end", 0)) for w in words]) if words else 30
    est_sec = max(20, min(55, int(tot_dur * 0.55)))

    msg_status = await query.message.reply_text(
        f"⚡ **កំពុង Re-render វីដេអូជាមួយរូបភាពថ្មី...** (ប៉ាន់ស្មាន ~{est_sec} វិនាទី)\n"
        "🚀 *ដំណើរការលឿនដោយ GPU RTX 3080 & កាត់ចន្លោះស្ងាត់ Smart Cut...*",
        parse_mode="Markdown"
    )

    try:
        r_proc = get_remotion_processor()
        loop = asyncio.get_running_loop()
        cached_vid = context.user_data.get("cached_clean_video", None)

        await loop.run_in_executor(
            None,
            lambda: r_proc.process_video(
                input_video_path=input_path,
                output_video_path=output_path,
                language=lang_code,
                theme=remotion_theme,
                bgm=bgm_choice,
                show_progress_bar=True,
                words=words,
                hook_title=hook_title,
                custom_font=custom_font,
                visual_overlays=overlays,
                cached_clean_video=cached_vid
            )
        )
        context.user_data["cached_clean_video"] = getattr(r_proc, "last_clean_video", None)

        caption_text = (
            f"🎬 **វីដេអូ Re-render ជាមួយរូបភាពថ្មីរួចរាល់ហើយ!** 🎨✨\n\n"
            f"• ប្រភេទ៖ **AI Visual Story (ប្លង់កែប្រែរួច)**\n"
            f"• រូបភាព B-Roll៖ **{len(overlays)} ប្លង់**\n"
            f"• ទម្រង់ Font៖ {style_label}\n"
            f"• ភ្លេង BGM៖ {bgm_label}\n\n"
            f"⚡ *Re-render ជោគជ័យ ១០០%*"
        )

        edit_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ កែរូបភាព B-Roll បន្តទៀត", callback_data="story_edit_menu")]
        ])

        pyro = await get_pyro_client()
        if pyro and pyro.is_connected:
            await pyro.send_video(
                chat_id=chat_id,
                video=output_path,
                caption=caption_text,
                supports_streaming=True
            )
        else:
            with open(output_path, "rb") as vf:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vf,
                    caption=caption_text,
                    supports_streaming=True
                )

        await context.bot.send_message(
            chat_id=chat_id,
            text="💡 លោកអ្នកអាចកែរូបភាពប្លង់ផ្សេងទៀតបានគ្រប់ពេល៖",
            reply_markup=edit_kb
        )
        await msg_status.delete()

    except Exception as e:
        logger.error(f"Error in handle_story_rerender_now: {e}", exc_info=True)
        await msg_status.edit_text(f"❌ ជួបបញ្ហាពេល Re-render៖ {str(e)}")


async def handle_edit_subtitles_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """បង្ហាញបញ្ជីអត្ថបទ Subtitle ទាំងអស់សម្រាប់ User ពិនិត្យ និងកែសម្រួល"""
    query = update.callback_query
    await query.answer()

    words = context.user_data.get("words", [])
    if not words:
        await query.message.reply_text("⚠️ មិនមានទិន្នន័យ Subtitles សម្រាប់កែប្រែទេ!")
        return

    context.user_data["awaiting_edited_text"] = True

    lines = []
    for i, w in enumerate(words):
        txt = w.get("word", "").strip()
        if txt:
            st = float(w.get("start", 0))
            et = float(w.get("end", 0))
            lines.append(f"{i+1}. [{format_time_display(st)} ➔ {format_time_display(et)}] {txt}")

    full_text = "\n".join(lines)
    if len(full_text) > 3000:
        full_text = full_text[:3000] + "\n...(នៅមានបន្ត)..."

    help_guide = (
        "📝 **កែសម្រួលអត្ថបទ Subtitles (Edit Text)**\n\n"
        f"{full_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 **របៀបកែពាក្យខុស៖**\n"
        "1️⃣ **កែតាមលេខជួរ៖** វាយ `2 = ពាក្យថ្មី` (ឬ `2. ពាក្យថ្មី`)\n"
        "2️⃣ **កែពាក្យ (Find & Replace)៖** វាយ `ពាក្យខុស -> ពាក្យត្រូវ`\n\n"
        "👉 *សូមវាយពាក្យដែលត្រូវកែផ្ញើមកទីនេះ...*"
    )

    back_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Re-render វីដេអូឥឡូវនេះ", callback_data="action_rerender_now")],
        [InlineKeyboardButton("📥 ទាញយកឯកសារ Subtitle (.SRT)", callback_data="action_download_srt")]
    ])

    await query.message.reply_text(help_guide, reply_markup=back_btn, parse_mode="Markdown")



async def handle_download_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ផ្ញើឯកសារ Subtitle .SRT ផ្លូវការឱ្យ User ទាញយក"""
    query = update.callback_query
    await query.answer()
    words = context.user_data.get("words", [])
    if not words:
        await query.message.reply_text("⚠️ មិនមានទិន្នន័យ Subtitles ទេ!")
        return

    import io
    srt_content = build_srt_content(words)
    srt_file = io.BytesIO(srt_content.encode("utf-8"))
    srt_file.name = "subtitles.srt"

    await query.message.reply_document(
        document=srt_file,
        caption="📥 **ឯកសារ Subtitles (.SRT) ផ្លូវការ**\n"
                "⏱ មាន Timestamps ត្រឹមត្រូវកម្រិតមីលីវិនាទី អាចយកទៅ Import ចូល Premiere Pro, CapCut, ឬ DaVinci Resolve បានភ្លាមៗ! 🎬"
    )

async def handle_rerender_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-render វីដេអូឡើងវិញជាមួយអត្ថបទ Subtitle ដែលបានកែប្រែថ្មី (~15-20s)"""
    query = update.callback_query
    await query.answer()

    input_path = context.user_data.get("input_path")
    output_path = context.user_data.get("output_path")
    words = context.user_data.get("words", [])
    hook_title = context.user_data.get("hook_title", "")
    remotion_theme = context.user_data.get("selected_theme", "tiktok_viral")
    style_label = context.user_data.get("selected_style_label", "🔥 TikTok Viral Gold")
    bgm_choice = context.user_data.get("bgm_choice", "lofi")
    bgm_label = context.user_data.get("bgm_label", "☕ Lofi Chill")
    lang_code = context.user_data.get("lang_code", "km")
    custom_font = context.user_data.get("selected_custom_font", None)
    last_mode = context.user_data.get("last_mode", "quick")
    overlays = context.user_data.get("story_overlays", []) if last_mode == "story" else None
    chat_id = context.user_data.get("pending_chat_id", query.message.chat_id)

    if not input_path or not os.path.exists(input_path):
        await query.message.reply_text("⚠️ បាត់បង់ឯកសារវីដេអូដើម! សូមផ្ញើវីដេអូម្ដងទៀត។")
        return

    tot_dur = max([float(w.get("end", 0)) for w in words]) if words else 30
    est_sec = max(20, min(55, int(tot_dur * 0.55)))

    msg_status = await query.message.reply_text(
        f"⚡ **កំពុង Re-render វីដេអូជាមួយអត្ថបទថ្មី...** (ប៉ាន់ស្មាន ~{est_sec} វិនាទី)\n"
        "🚀 *ដំណើរការលឿនដោយ GPU RTX 3080 & កាត់ចន្លោះស្ងាត់ Smart Cut...*",
        parse_mode="Markdown"
    )

    try:
        r_proc = get_remotion_processor()
        loop = asyncio.get_running_loop()
        cached_vid = context.user_data.get("cached_clean_video", None)

        await loop.run_in_executor(
            None,
            lambda: r_proc.process_video(
                input_video_path=input_path,
                output_video_path=output_path,
                language=lang_code,
                theme=remotion_theme,
                bgm=bgm_choice,
                show_progress_bar=True,
                words=words,
                hook_title=hook_title,
                custom_font=custom_font,
                visual_overlays=overlays,
                cached_clean_video=cached_vid
            )
        )
        context.user_data["cached_clean_video"] = getattr(r_proc, "last_clean_video", None)

        mode_name = "AI Visual Story" if last_mode == "story" else "Quick Viral Pop"
        caption_text = (
            f"🎬 **វីដេអូ Re-render ជាមួយ Subtitle ថ្មីរួចរាល់ហើយ!** ✍️✨\n\n"
            f"• ប្រភេទ៖ **{mode_name}**\n"
            f"• ទម្រង់ Font៖ {style_label}\n"
            f"• ភ្លេង BGM៖ {bgm_label}\n\n"
            f"⚡ *កែអត្ថបទត្រូវមាត់ ១០០%*"
        )

        buttons = [
            [InlineKeyboardButton("✏️ កែប្រែអត្ថបទអក្សរបន្តទៀត", callback_data="action_edit_subtitles")]
        ]
        if last_mode == "story":
            buttons.append([InlineKeyboardButton("📊 កែប្លង់ Motion / Reference Cards", callback_data="story_edit_menu")])

        pyro = await get_pyro_client()
        if pyro and pyro.is_connected:
            await pyro.send_video(
                chat_id=chat_id,
                video=output_path,
                caption=caption_text,
                supports_streaming=True
            )
        else:
            with open(output_path, "rb") as vf:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vf,
                    caption=caption_text,
                    supports_streaming=True
                )

        await context.bot.send_message(
            chat_id=chat_id,
            text="💡 លោកអ្នកអាចកែសម្រួលបន្ថែមបានគ្រប់ពេល៖",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await msg_status.delete()

    except Exception as e:
        logger.error(f"Error in handle_rerender_now: {e}", exc_info=True)
        await msg_status.edit_text(f"❌ ជួបបញ្ហាពេល Re-render៖ {str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n" + "="*60)
        print("⚠️  កំហុស៖ មិនទាន់បានដាក់ TELEGRAM_BOT_TOKEN នៅក្នុង file .env ទេ!")
        print("="*60 + "\n")
        return

    print("🤖 កំពុងចាប់ផ្ដើម Telegram Bot (គាំទ្រវីដេអូរហូតដល់ 2,000MB / 2GB)...")

    request = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=300.0,
        write_timeout=300.0
    )

    async def post_init(application):
        if TELEGRAM_API_ID and TELEGRAM_API_HASH:
            await get_pyro_client()

    async def post_shutdown(application):
        global pyro_client
        if pyro_client and pyro_client.is_connected:
            await pyro_client.stop()

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # ចុះឈ្មោះ Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(CallbackQueryHandler(handle_render_action, pattern="^action_render_quick$"))
    app.add_handler(CallbackQueryHandler(handle_render_story, pattern="^action_render_story$"))
    app.add_handler(CallbackQueryHandler(handle_render_action, pattern="^action_render$"))
    app.add_handler(CallbackQueryHandler(handle_customize, pattern="^action_customize$"))
    app.add_handler(CallbackQueryHandler(handle_back_to_ready, pattern="^action_back_to_ready$"))
    app.add_handler(CallbackQueryHandler(handle_font_page, pattern="^fontpage_"))
    app.add_handler(CallbackQueryHandler(handle_all_font_choice, pattern="^sel_font_"))
    app.add_handler(CallbackQueryHandler(handle_font_choice, pattern="^font_"))
    app.add_handler(CallbackQueryHandler(handle_bgm_choice, pattern="^bgm_"))
    app.add_handler(CallbackQueryHandler(handle_story_edit_menu, pattern="^story_edit_menu$"))
    app.add_handler(CallbackQueryHandler(handle_story_change_layout, pattern="^story_lay_"))
    app.add_handler(CallbackQueryHandler(handle_story_pick_scene, pattern="^story_pick_"))
    app.add_handler(CallbackQueryHandler(handle_story_delete_scene, pattern="^story_del_\\d+$"))
    app.add_handler(CallbackQueryHandler(handle_story_delete_all, pattern="^story_del_all$"))
    app.add_handler(CallbackQueryHandler(handle_story_edit_txt, pattern="^story_txt_\\d+$"))
    app.add_handler(CallbackQueryHandler(handle_story_edit_img, pattern="^story_img_\\d+$"))
    app.add_handler(CallbackQueryHandler(handle_story_rerender_now, pattern="^story_rerender_now$"))
    app.add_handler(CallbackQueryHandler(handle_edit_subtitles_menu, pattern="^action_edit_subtitles$"))
    app.add_handler(CallbackQueryHandler(handle_rerender_now, pattern="^action_rerender_now$"))
    app.add_handler(CallbackQueryHandler(handle_download_srt, pattern="^action_download_srt$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("✅ Bot កំពុងដំណើរការដោយជោគជ័យ! សាមញ្ញ ងាយស្រួលប្រើ & គាំទ្រវីដេអូដល់ 2GB (2,000MB)។")
    app.run_polling()

if __name__ == "__main__":
    main()
