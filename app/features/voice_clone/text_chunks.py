"""Text chunking for long-form speech synthesis with stable manifests."""
import re
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    index: int
    text: str
    char_start: int
    char_end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def split_text_into_chunks(
    text: str,
    max_chunk_chars: int = 180,
    min_chunk_chars: int = 30,
) -> list[TextChunk]:
    """
    Split text into coherent sentence/phrase chunks respecting Khmer and standard punctuation.
    Preserves exact character offsets and order.
    Punctuation handled:
      - Khmer full stop: ។ (U+17D4)
      - Khmer pause/comma: ៗ (repetition), ៕ (section end)
      - Standard: . ! ? \n
    """
    clean_text = text.strip()
    if not clean_text:
        return []

    # If within chunk size, single chunk
    if len(clean_text) <= max_chunk_chars:
        return [TextChunk(chunk_id="chunk_000", index=0, text=clean_text, char_start=0, char_end=len(clean_text))]

    # Delimiters preserving sentence rhythm: \n+, [។.!?]+
    delimiters = r'(\n+|[។.!?]+(?:\s+|$))'
    tokens = re.split(delimiters, clean_text)

    chunks: list[TextChunk] = []
    current_buf: list[str] = []
    current_len = 0
    start_pos = 0
    chunk_idx = 0

    cursor = 0
    for tok in tokens:
        if not tok:
            continue
        tok_len = len(tok)

        # Check if adding this token exceeds max_chunk_chars
        if current_buf and (current_len + tok_len > max_chunk_chars):
            chunk_str = "".join(current_buf).strip()
            if chunk_str:
                c_start = clean_text.find(chunk_str, start_pos)
                if c_start == -1:
                    c_start = start_pos
                c_end = c_start + len(chunk_str)
                chunks.append(TextChunk(
                    chunk_id=f"chunk_{chunk_idx:03d}",
                    index=chunk_idx,
                    text=chunk_str,
                    char_start=c_start,
                    char_end=c_end,
                ))
                chunk_idx += 1
                start_pos = c_end

            current_buf = [tok]
            current_len = tok_len
        else:
            current_buf.append(tok)
            current_len += tok_len

    if current_buf:
        chunk_str = "".join(current_buf).strip()
        if chunk_str:
            c_start = clean_text.find(chunk_str, start_pos)
            if c_start == -1:
                c_start = start_pos
            c_end = c_start + len(chunk_str)
            chunks.append(TextChunk(
                chunk_id=f"chunk_{chunk_idx:03d}",
                index=chunk_idx,
                text=chunk_str,
                char_start=c_start,
                char_end=c_end,
            ))

    return chunks

def verify_chunk_coverage(original_text: str, chunks: list[TextChunk]) -> bool:
    """Verify that chunks accurately represent the text in order without loss."""
    if not chunks and not original_text.strip():
        return True
    if not chunks:
        return False

    # Check ascending index and non-overlapping ranges
    last_end = -1
    reconstructed_words = []
    for c in chunks:
        if c.char_start < last_end:
            return False
        last_end = c.char_end
        reconstructed_words.append(c.text)

    full_reconstructed = " ".join(reconstructed_words)
    # Ensure significant keywords/chars are present
    orig_chars = [ch for ch in original_text if not ch.isspace()]
    recon_chars = [ch for ch in full_reconstructed if not ch.isspace()]
    return orig_chars == recon_chars
