"""Tests for source canvas calculation, letterbox padding, and aspect ratio preservation."""
import pytest
from app.features.talking_photo.framing import (
    calculate_letterbox_padding,
    validate_aspect_ratio_preservation,
    build_framing_manifest,
)

def test_letterbox_padding_for_wide_image():
    # 16:9 widescreen source into 1:1 square canvas (512x512)
    src_w, src_h = 1920, 1080
    target_w, target_h = 512, 512

    pad_t, pad_b, pad_l, pad_r = calculate_letterbox_padding(src_w, src_h, target_w, target_h)
    assert pad_l == 0
    assert pad_r == 0
    assert pad_t > 0
    assert pad_b > 0
    # Scaled height = round(512 / (1920/1080)) = 288. Total pad = 512 - 288 = 224.
    assert pad_t + pad_b == 224

def test_letterbox_padding_for_tall_portrait():
    # 9:16 vertical portrait into 1:1 square canvas (512x512)
    src_w, src_h = 1080, 1920
    target_w, target_h = 512, 512

    pad_t, pad_b, pad_l, pad_r = calculate_letterbox_padding(src_w, src_h, target_w, target_h)
    assert pad_t == 0
    assert pad_b == 0
    assert pad_l > 0
    assert pad_r > 0
    assert pad_l + pad_r == 224

def test_aspect_ratio_validation():
    # Matching ratio
    assert validate_aspect_ratio_preservation(1920, 1080, 1280, 720) is True
    # Minor drift within tolerance (e.g. 1-2% due to rounding)
    assert validate_aspect_ratio_preservation(1000, 1000, 512, 510, tolerance=0.05) is True
    # Severely distorted/squashed ratio (e.g. 16:9 squeezed into 1:1)
    assert validate_aspect_ratio_preservation(1920, 1080, 512, 512, tolerance=0.05) is False

def test_build_framing_manifest():
    manifest = build_framing_manifest("/path/portrait.jpg", 1200, 1600, target_size=512)
    assert manifest["canvas_size"] == 512
    assert manifest["aspect_ratio"] == 0.75
    assert manifest["mode"] == "letterbox_pad_preserved"
    assert "padding" in manifest
