import os
import sys
import logging
import time
import requests
from io import BytesIO
from typing import List, Dict
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# Cache models on Drive D to avoid consuming Drive C space
MODELS_DIR = r"D:\bot video\models"
os.makedirs(MODELS_DIR, exist_ok=True)
os.environ["HF_HOME"] = MODELS_DIR

_pipe_instance = None

def fetch_free_stock_photo(query: str, output_path: str) -> bool:
    """
    ទាញយករូបភាពពិតៗកម្រិតច្បាស់ (Real High-Res Stock Photography) ១០០% ឥតគិតថ្លៃ (Zero Cost, No API Key)
    ពី Openverse (Creative Commons & Stock Engine)
    លឿនខ្លាំង (~1-3s) គ្មានដែនកំណត់ និងមិនអស់លុយសូម្បីតែ ១ សេន!
    """
    if not query or len(query.strip()) < 2:
        return False

    clean_query = query.strip()
    logger.info(f"🔍 កំពុងស្វែងរករូបភាពពិតកម្រិតច្បាស់ (Free Stock Photo) សម្រាប់: '{clean_query}'...")
    try:
        url = "https://api.openverse.org/v1/images/"
        params = {"q": clean_query, "page_size": 5}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, params=params, headers=headers, timeout=6)
        if r.status_code == 200:
            results = r.json().get("results", [])
            for res in results:
                img_url = res.get("url")
                if not img_url:
                    continue
                try:
                    img_resp = requests.get(img_url, headers=headers, timeout=7)
                    if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                        img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                        
                        # Resize preserving aspect ratio to fit clean 1080 frame
                        img.thumbnail((1080, 1080), Image.Resampling.LANCZOS)
                        img.save(output_path, "JPEG", quality=93)
                        logger.info(f"📸 រកឃើញរូបថតពិតដ៏ស្រស់ស្អាត: '{res.get('title', clean_query)}' ({img.size[0]}x{img.size[1]})")
                        return True
                except Exception as inner_e:
                    continue
        logger.warning(f"រកមិនឃើញរូបភាពសម្រាប់ '{clean_query}' ពី Openverse")
        return False
    except Exception as e:
        logger.warning(f"Openverse search error for '{clean_query}': {e}")
        return False

def get_local_pipeline():
    """Lazy-load SD-Turbo pipeline on NVIDIA RTX 3080 as local free fallback"""
    global _pipe_instance
    if _pipe_instance is not None:
        return _pipe_instance

    try:
        import torch
        torch.backends.cudnn.enabled = False

        from diffusers import AutoPipelineForText2Image

        if not torch.cuda.is_available():
            return None

        logger.info("🚀 កំពុងដំណើរការ NVIDIA RTX 3080 ជាមួយម៉ូឌែល SD-Turbo...")
        pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sd-turbo",
            torch_dtype=torch.float16,
            variant="fp16",
            cache_dir=MODELS_DIR
        )
        pipe.to("cuda")
        pipe.enable_attention_slicing()
        _pipe_instance = pipe
        logger.info("✨ SD-Turbo Pipeline រួចរាល់លើ RTX 3080!")
        return _pipe_instance
    except Exception as e:
        logger.error(f"Error loading SD-Turbo pipeline on GPU: {e}")
        return None

def create_fallback_graphic(topic: str, output_path: str):
    """បង្កើត Elegant Visual Card ប្រសិនបើរករូបភាពពិតមិនឃើញ"""
    try:
        img = Image.new("RGB", (720, 520), color=(15, 17, 26))
        draw = ImageDraw.Draw(img)

        # Draw glowing gradient effect
        for r in range(160, 0, -6):
            draw.ellipse(
                [(360 - r, 260 - r), (360 + r, 260 + r)],
                fill=(255, 200, 0)
            )

        draw.rounded_rectangle([(10, 10), (710, 510)], radius=32, outline=(255, 215, 0), width=4)
        img.save(output_path, "JPEG", quality=92)
        return output_path
    except Exception as e:
        logger.error(f"Error creating fallback image: {e}")
        return output_path

def generate_visual_overlays(
    scenes: List[Dict],
    public_dir: str,
    output_prefix: str = "scene"
) -> List[Dict]:
    """
    បង្កើត Motion Explainer & Real B-Roll Overlays ច្នៃប្រឌិតខ្ពស់ (១០០% ឥតគិតថ្លៃ គ្មាន AI Fantasy)៖
    1. Polaroid Photo Frames ជាមួយរូបថតពិត & Caption សោភ័ណភាព
    2. Cinematic Fullscreen B-Roll ជាមួយ Ken Burns Slow Zoom
    3. Minimalist Frosted Glass Pills (គន្លឹះ, Feedback, ចំណាំ)
    4. Kinetic Word Slam / Dynamic Highlighters
    5. Clean Floating Cards & Comparison Bar Widgets
    """
    story_dir = os.path.join(public_dir, "story_images")
    os.makedirs(story_dir, exist_ok=True)

    overlays = []
    unique_tag = int(time.time() * 1000)

    vibrant_palette = ["#FFE600", "#10B981", "#F43F5E", "#06B6D4", "#F59E0B", "#A855F7"]
    tilt_angles = [-3.2, 2.8, -2.6, 3.1]

    for idx, scene in enumerate(scenes):
        start = float(scene.get("start", 0))
        end = float(scene.get("end", start + 3.8))
        topic = str(scene.get("topic", "")).strip()
        raw_lay = str(scene.get("layout", "")).lower().strip()
        if raw_lay in ["split_screen", "cinematic_broll", "talking_head"]:
            layout = raw_lay
        else:
            layout = "split_screen" if idx % 2 == 0 else "cinematic_broll"

        step_badge = str(scene.get("step_badge", "")).strip()
        headline_prefix = str(scene.get("headline_prefix", "")).strip()
        highlight_word = str(scene.get("highlight_word", topic or "ចំណុចសំខាន់")).strip()
        headline_suffix = str(scene.get("headline_suffix", "")).strip()
        caption = str(scene.get("caption", topic or highlight_word)).strip()
        pill_category = str(scene.get("pill_category", "🎬 B-ROLL" if layout == "cinematic_broll" else "✨ ពិសេស")).strip()
        pill_text = str(scene.get("pill_text", highlight_word or topic)).strip()
        floating_icon = str(scene.get("floating_icon", "sparkle")).strip()
        accent_color = str(scene.get("accent_color", vibrant_palette[idx % len(vibrant_palette)])).strip()
        rotation_deg = 0.0
        search_query = str(scene.get("search_query", topic)).strip()
        cards = []
        comparison = None

        rel_img_src = ""
        # Fetch real photographic image for split_screen & cinematic_broll
        if layout in ["split_screen", "cinematic_broll", "real_broll"]:
            img_filename = f"{output_prefix}_{unique_tag}_{idx}.jpg"
            img_full_path = os.path.join(story_dir, img_filename)
            logger.info(f"🔍 ស្វែងរករូបថតពិតសម្រាប់ [{layout}] '{topic}' [Search: '{search_query}']...")
            success = fetch_free_stock_photo(search_query or topic, img_full_path)
            if success:
                rel_img_src = f"story_images/{img_filename}"
            else:
                fallback_path = create_fallback_graphic(topic, img_full_path)
                if os.path.exists(fallback_path):
                    rel_img_src = f"story_images/{img_filename}"

        # 2. Comparison widget validation
        if layout == "comparison" and not comparison:
            comparison = {
                "leftTitle": "មុន",
                "rightTitle": "ក្រោយ",
                "leftValues": [40, 50, 45, 60, 55],
                "rightValues": [70, 85, 80, 95, 90]
            }

        # 3. Clean floating cards validation
        if layout == "floating_card" and not cards and not comparison:
            cards = [
                {
                    "title": topic or "ចំណុចសំខាន់",
                    "subtitle": highlight_word,
                    "iconType": floating_icon if floating_icon in ["chart", "food", "star", "fire", "bulb", "heart"] else "sparkle",
                    "accentColor": accent_color,
                    "rotationDeg": rotation_deg
                }
            ]

        overlay_item = {
            "start": start,
            "end": end,
            "layout": layout,
            "stepBadge": step_badge,
            "headlinePrefix": headline_prefix,
            "highlightWord": highlight_word,
            "headlineSuffix": headline_suffix,
            "caption": caption,
            "pillCategory": pill_category,
            "pillText": pill_text,
            "floatingIcon": floating_icon,
            "accentColor": accent_color,
            "rotationDeg": rotation_deg,
            "topic": topic,
            "cards": cards,
            "comparison": comparison,
            "imageSrc": rel_img_src,
            "transition": "spring_pop"
        }

        overlays.append(overlay_item)
        logger.info(f"✨ បានបង្កើត Creative Overlay ទី {idx+1}/{len(scenes)}: [{layout}] {caption or highlight_word}")

    return overlays

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    test_scenes = [
        {"start": 1.0, "end": 4.5, "topic": "ទូរស័ព្ទដៃ", "search_query": "modern smartphone desk", "prompt": "modern smartphone desk"},
        {"start": 6.0, "end": 9.5, "topic": "ការរកលុយ", "search_query": "dollar bills money cash", "prompt": "dollar bills money"}
    ]
    res = generate_visual_overlays(test_scenes, r"D:\bot video\remotion\public")
    print(f"Generated {len(res)} overlays successfully!")
