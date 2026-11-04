"""Keep long-running operations visible without inventing percentages or ETAs."""
import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
PROGRESS_INTERVAL_SECONDS = 8.0

STAGE_LABELS = {
    "separating_background": "🎵 កំពុងដកសំឡេងនិយាយដើម និងរក្សាតន្ត្រី / SFX",
    "downloading": "📥 កំពុងទាញវីដេអូពីលីង",
    "analyzing_source": "🎧 កំពុងស្ដាប់សំឡេង និងស្រង់ពាក្យពីវីដេអូ",
    "translating_segments": "🌐 កំពុងរង់ចាំអត្ថបទបកប្រែពី AI",
    "generating_audio": "🎙️ កំពុងបង្កើតសំឡេងអាន",
    "generating_segments": "🎙️ កំពុងបង្កើតសំឡេងតាមឃ្លា និងតម្រឹមពេលវេលា",
    "assembling_timeline": "🎵 កំពុងភ្ជាប់សំឡេងតាមពេលវីដេអូ",
    "preview_queued": "🕓 វីដេអូគំរូកំពុងរង់ចាំវេន",
    "final_queued": "🕓 វីដេអូពេញកំពុងរង់ចាំវេន",
    "preview_rendering": "🎬 កំពុងបង្កើតវីដេអូគំរូ",
    "rendering": "🎬 កំពុងបង្កើតវីដេអូ",
    "voice_converting": "🎙️ កំពុងបម្លែងសំឡេង",
    "uploading": "📤 កំពុងផ្ញើវីដេអូទៅ Telegram",
    "awaiting_approval": "👀 រួចរាល់សម្រាប់ពិនិត្យ និងអនុម័ត",
    "awaiting_segment_review": "📝 រួចរាល់សម្រាប់ពិនិត្យអត្ថបទបកប្រែ",
    "awaiting_fit_resolution": "✏️ ត្រូវពិនិត្យឃ្លាដែលនិយាយវែងជាងពេលវីដេអូ",
    "completed": "✅ ការងារបានបញ្ចប់",
    "cancelled": "❌ ការងារត្រូវបានបោះបង់",
    "failed": "❌ ការងារបរាជ័យ។ សូមមើលសារបញ្ហា និងសាកល្បងម្ដងទៀត",
    "delivery_failed": "📤 វីដេអូរួចហើយ ប៉ុន្តែផ្ញើមិនបាន។ សូមចុចផ្ញើម្ដងទៀត",
}

def stage_label(status):
    key = status.value if hasattr(status, "value") else str(status)
    return STAGE_LABELS.get(key, "⏳ កំពុងរៀបចំការងារ")

def progress_text(label, elapsed):
    minutes, seconds = divmod(max(0, int(elapsed)), 60)
    duration = f"{minutes} នាទី {seconds} វិនាទី" if minutes else f"{seconds} វិនាទី"
    return (
        f"{label}\n\n⏱ ពេលកន្លងទៅក្នុងជំហាននេះ៖ {duration}\n"
        "ស្ថានភាពធ្វើបច្ចុប្បន្នភាពស្វ័យប្រវត្តិ។ អាចចុចបោះបង់បាន។"
    )

@asynccontextmanager
async def live_progress(update, cancelled=None):
    """Stop updates before the caller displays results, including on errors/cancel."""
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def monitor():
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)
            if cancelled and cancelled():
                return
            try:
                await asyncio.wait_for(update(int(loop.time() - started)), timeout=5.0)
            except Exception:
                # Telegram outages must not abort media processing.
                logger.warning("Could not refresh operation progress.")

    task = asyncio.create_task(monitor())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
