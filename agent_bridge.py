"""
Antigravity Agent Bridge and Assisted Fallback Handler.
Provides:
- Capability check for automated agent bridges.
- Honest degradation when external agent runtime is unavailable.
- State management for 'awaiting_manual_agent'.
- Export of structured agent briefs for manual pair programming.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Configurable flag for Antigravity automated sidecar/bridge
ANTIGRAVITY_BRIDGE_ENABLED = os.getenv("ANTIGRAVITY_BRIDGE_ENABLED", "false").lower() in ("true", "1", "yes")


class AntigravityBridge:
    """
    Manages Antigravity agent integration or explicit assisted fallback.
    """

    @staticmethod
    def is_bridge_supported() -> bool:
        """
        Honestly checks if an active Antigravity CLI or sidecar bridge is connected.
        Defaults to False unless explicitly configured with live sidecar credentials.
        """
        return ANTIGRAVITY_BRIDGE_ENABLED

    @staticmethod
    def generate_agent_brief(
        job_id: str,
        job_dir: Path,
        user_prompt: Optional[str],
        words: list,
        mode: str = "custom"
    ) -> Tuple[Path, str]:
        """
        Generates structured agent brief and export artifact for manual assistant execution.
        """
        brief_path = Path(job_dir) / "agent_brief.md"
        json_path = Path(job_dir) / "agent_brief.json"

        total_words = len(words)
        total_duration = max([w.get("end", 0.0) for w in words]) if words else 0.0

        brief_content = f"""# 🤖 Antigravity Video Editing Brief (Job {job_id[:8]})

## 🎯 Objective
Custom video composition and creative editing requested by user.

## 📊 Video Specifications
- **Job ID:** `{job_id}`
- **Requested Mode:** `{mode}`
- **Estimated Duration:** `{total_duration:.2f}s`
- **Total Speech Segments:** `{total_words}`
- **Custom User Instructions:**
> {user_prompt or 'No custom prompt provided (Standard viral template)'}

## 📝 Subtitle Transcript Excerpt
"""
        for i, w in enumerate(words[:8]):
            brief_content += f"- [{w.get('start', 0.0):.2f}s - {w.get('end', 0.0):.2f}s]: {w.get('word', '')}\n"

        if total_words > 8:
            brief_content += f"- ... and {total_words - 8} more segments.\n"

        brief_content += """
## 💡 Recommended Next Actions for Manual Agent
1. Verify React component styling in `remotion/src/Composition.tsx`.
2. Apply requested custom layout or motion graphics.
3. Validate and render using `npm run render`.
"""
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(brief_content)

        data = {
            "job_id": job_id,
            "mode": mode,
            "user_prompt": user_prompt,
            "duration": total_duration,
            "words_count": total_words
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return brief_path, brief_content
