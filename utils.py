import os
import shutil

def get_ffmpeg_path() -> str:
    """
    ស្វែងរក FFmpeg executable លើម៉ាស៊ីន
    ប្រសិនបើគ្មានក្នុង System PATH ទេ វានឹងប្រើ binary ពី imageio_ffmpeg ដោយស្វ័យប្រវត្តិ
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    raise RuntimeError(
        "រកមិនឃើញ FFmpeg ទេ! សូមដំឡើង 'pip install imageio-ffmpeg' ឬដំឡើង FFmpeg លើកុំព្យូទ័រ។"
    )

def get_video_dimensions(video_path: str) -> tuple:
    """ទាញយកទំហំ Video (width, height) ដោយប្រើ FFmpeg"""
    import re
    import subprocess
    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-i", video_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="replace")
    m = re.search(r",\s*(\d{3,5})x(\d{3,5})", res.stderr)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (1080, 1920)
