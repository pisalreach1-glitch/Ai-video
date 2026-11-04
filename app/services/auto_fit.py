"""Bounded automatic rephrasing of overlong dialogue, without truncating audio."""
import asyncio
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

def numbers(text):
    normalized=''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)
    return set(re.findall(r'\d+(?:[.,]\d+)*',normalized))

def safe_proposal(original, proposal):
    if not isinstance(proposal,str) or not proposal.strip() or not re.search(r'[\u1780-\u17ff]',proposal):
        return False
    if not numbers(original).issubset(numbers(proposal)):
        return False
    negations=('មិន','កុំ','គ្មាន','ហាម')
    if any(word in original for word in negations) and not any(word in proposal for word in negations):
        return False
    return True

async def auto_fit_overlong(plan, shorten, synthesize, cancelled=None, notify=None):
    """Try at most twice, then return the unresolved plan for explicit review."""
    for attempt in range(2):
        if cancelled and cancelled():
            raise asyncio.CancelledError('Automatic fitting cancelled')
        ids={clip.segment_id for clip in plan.clips if clip.status=='too_long'}
        if not ids:
            break
        items=[]
        for segment in plan.segments:
            translation=plan.get_translation(segment.segment_id)
            if segment.segment_id in ids and translation:
                items.append({'id':segment.segment_id,'source_text':segment.source_text,
                    'current_khmer':translation.translated_text,
                    'target_seconds':round(max(segment.duration_ms/1000*(0.9 if attempt else 1.0),0.001),3)})
        if not items:
            break
        if notify:
            await notify(attempt+1,len(items))
        try:
            proposals=await asyncio.wait_for(shorten(items,cancel_check=cancelled),timeout=60)
        except Exception:
            logger.warning('Automatic shortening unavailable; retaining text for review')
            break
        if cancelled and cancelled():
            raise asyncio.CancelledError('Automatic fitting cancelled')
        if not isinstance(proposals,dict):
            break
        changed=False
        for item in items:
            translation=plan.get_translation(item['id'])
            proposal=proposals.get(item['id'])
            original=translation.full_translation or translation.translated_text
            if not safe_proposal(original,proposal) or proposal.strip()==translation.translated_text:
                continue
            translation.full_translation=original
            translation.proposed_concise_text=proposal.strip()
            translation.translated_text=proposal.strip()
            translation.status='ready'
            changed=True
        if not changed:
            break
        plan=await synthesize(plan)
    return plan


def use_adjacent_pause(plan):
    """Offer only measured overlong clips a bounded existing pause; never move source starts."""
    ordered = sorted(plan.segments, key=lambda item: item.start_ms)
    clips = {clip.segment_id: clip for clip in plan.clips if clip.status == "too_long"}
    extensions = dict(plan.sync_policy_metadata.get("pause_extensions_ms", {}))
    changed = False
    for index, segment in enumerate(ordered):
        clip = clips.get(segment.segment_id)
        if not clip:
            continue
        next_start = ordered[index + 1].start_ms - 80 if index + 1 < len(ordered) else plan.source_duration_ms
        available = max(0, min(1000, next_start - segment.end_ms))
        needed = max(0, clip.raw_duration_ms - segment.duration_ms)
        extension = min(available, needed)
        if extension > extensions.get(segment.segment_id, 0):
            extensions[segment.segment_id] = extension
            changed = True
    if changed:
        plan.sync_policy_metadata["pause_extensions_ms"] = extensions
    return changed
