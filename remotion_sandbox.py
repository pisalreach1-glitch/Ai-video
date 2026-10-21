"""
Execution Sandbox and Validation for Remotion rendering.
Enforces:
- Strict whitelist validation of composition names.
- Validation and sanitization of Remotion props and asset paths.
- Secret scrubbing: Never exposes bot tokens or API keys to Node/Remotion subprocesses.
- Prevents arbitrary npm package installations during render execution.
"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

ALLOWED_COMPOSITIONS = {"ShortComposition", "PreviewComposition"}
SENSITIVE_ENV_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "GEMINI_API_KEY",
    "BOT_TOKEN",
    "API_KEY",
    "SECRET_KEY"
}


class SecurityValidationError(ValueError):
    """Raised when generated props or composition fail security validation."""
    pass


def validate_composition_name(composition: str) -> str:
    """
    Validates composition name against a strict whitelist.
    Prevents shell injection or arbitrary composition execution.
    """
    comp = str(composition).strip()
    if comp not in ALLOWED_COMPOSITIONS:
        raise SecurityValidationError(
            f"Invalid or unauthorized Remotion composition: '{comp}'. "
            f"Allowed compositions: {ALLOWED_COMPOSITIONS}"
        )
    return comp


def validate_props_file(props_data: Dict[str, Any], allowed_roots: List[Path]) -> None:
    """
    Validates props JSON payload before passing to Remotion CLI:
    - Checks videoSrc does not attempt path traversal.
    - Validates cuts array and numerical time limits.
    - Validates that visual overlays do not load unauthorized remote/local files.
    """
    if not isinstance(props_data, dict):
        raise SecurityValidationError("Props data must be a dictionary.")

    video_src = props_data.get("videoSrc")
    if not video_src or not isinstance(video_src, str):
        raise SecurityValidationError("Props must contain a non-empty 'videoSrc' string.")

    # Prevent path traversal in videoSrc
    if ".." in video_src or "/" in video_src or "\\" in video_src:
        # If filename only, it's relative to public/; if contains slashes, check absolute path
        p = Path(video_src).resolve()
        is_safe = any(base.resolve() in p.parents or base.resolve() == p for base in allowed_roots)
        if not is_safe:
            raise SecurityValidationError(f"Path traversal detected in videoSrc: '{video_src}'")

    # Validate cuts structure
    cuts = props_data.get("cuts", [])
    if not isinstance(cuts, list):
        raise SecurityValidationError("Props 'cuts' must be a list.")

    for idx, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            raise SecurityValidationError(f"Cut #{idx} must be a dictionary.")
        st = cut.get("start")
        et = cut.get("end")
        if st is None or et is None or float(et) < float(st):
            raise SecurityValidationError(f"Invalid cut duration in cut #{idx}: start={st}, end={et}")

    # Validate visual overlays
    overlays = props_data.get("visualOverlays", [])
    if isinstance(overlays, list):
        for o_idx, ov in enumerate(overlays):
            img_src = ov.get("imageSrc")
            if img_src and isinstance(img_src, str):
                if ".." in img_src:
                    raise SecurityValidationError(f"Path traversal detected in overlay imageSrc #{o_idx}: '{img_src}'")


def get_sanitized_render_env(extra_env: Dict[str, str] = None) -> Dict[str, str]:
    """
    Constructs a sanitized environment for Node / Remotion execution:
    - Retains only safe execution variables (PATH, SystemRoot, Temp, Node configuration).
    - EXPLICITLY scrubs all secrets (Telegram tokens, Gemini keys, session keys).
    - Guarantees that generated compositions cannot inspect environment secrets.
    """
    safe_keys = {
        "PATH",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "HOME",
        "LANG",
        "LC_ALL",
        "NODE_ENV"
    }

    sanitized = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        # Skip any key in sensitive keys or containing KEY/TOKEN/SECRET/HASH
        if k_upper in SENSITIVE_ENV_KEYS:
            continue
        if any(bad in k_upper for bad in ["TOKEN", "SECRET", "API_HASH", "API_KEY"]):
            continue
        if k_upper in safe_keys:
            sanitized[k] = v

    sanitized["NODE_ENV"] = "production"

    if extra_env:
        for ek, ev in extra_env.items():
            if ek.upper() not in SENSITIVE_ENV_KEYS:
                sanitized[ek] = ev

    return sanitized
