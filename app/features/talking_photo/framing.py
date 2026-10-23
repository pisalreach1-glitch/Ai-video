"""Full framing, canvas calculation, and aspect ratio validation."""
import math
from pathlib import Path
from typing import Tuple, Dict, Any

def calculate_letterbox_padding(
    src_width: int,
    src_height: int,
    target_width: int,
    target_height: int,
) -> Tuple[int, int, int, int]:
    """
    Calculate padding (pad_top, pad_bottom, pad_left, pad_right) to fit source
    into target canvas without stretching or cropping body/limbs.
    """
    if src_width <= 0 or src_height <= 0 or target_width <= 0 or target_height <= 0:
        raise ValueError("Dimensions must be positive integers.")

    src_aspect = src_width / src_height
    target_aspect = target_width / target_height

    if abs(src_aspect - target_aspect) < 1e-4:
        return 0, 0, 0, 0

    if src_aspect > target_aspect:
        # Source is wider than target: fit width, pad top & bottom
        scaled_height = int(round(target_width / src_aspect))
        total_pad = max(0, target_height - scaled_height)
        pad_top = total_pad // 2
        pad_bottom = total_pad - pad_top
        return pad_top, pad_bottom, 0, 0
    else:
        # Source is taller than target: fit height, pad left & right
        scaled_width = int(round(target_height * src_aspect))
        total_pad = max(0, target_width - scaled_width)
        pad_left = total_pad // 2
        pad_right = total_pad - pad_left
        return 0, 0, pad_left, pad_right

def validate_aspect_ratio_preservation(
    src_width: int,
    src_height: int,
    out_width: int,
    out_height: int,
    tolerance: float = 0.05,
) -> bool:
    """
    Validate that output video aspect ratio preserves source aspect ratio within tolerance,
    preventing squashed or distorted anatomy.
    """
    if src_width <= 0 or src_height <= 0 or out_width <= 0 or out_height <= 0:
        return False
    src_ratio = src_width / src_height
    out_ratio = out_width / out_height
    diff = abs(src_ratio - out_ratio) / src_ratio
    return diff <= tolerance

def build_framing_manifest(
    image_path: str,
    width: int,
    height: int,
    target_size: int = 256,
) -> Dict[str, Any]:
    """Build framing metadata manifest recording composition details."""
    pad_t, pad_b, pad_l, pad_r = calculate_letterbox_padding(width, height, target_size, target_size)
    return {
        "image_path": str(image_path),
        "source_width": width,
        "source_height": height,
        "aspect_ratio": round(width / height, 4) if height > 0 else 1.0,
        "canvas_size": target_size,
        "padding": {
            "top": pad_t,
            "bottom": pad_b,
            "left": pad_l,
            "right": pad_r,
        },
        "mode": "letterbox_pad_preserved",
    }
