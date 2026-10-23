"""Unit tests for text chunking and Khmer punctuation handling."""
import pytest
from app.features.voice_clone.text_chunks import split_text_into_chunks, verify_chunk_coverage

def test_split_short_text():
    text = "សួស្តីបងប្អូនទាំងអស់គ្នា។ នេះជាការសាកល្បងសំឡេងថ្មី។"
    chunks = split_text_into_chunks(text, max_chunk_chars=180)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert verify_chunk_coverage(text, chunks) is True

def test_split_long_khmer_text_with_punctuation():
    text = (
        "សួស្តីបងប្អូនទាំងអស់គ្នា។ ថ្ងៃនេះយើងនឹងបង្ហាញអំពីការប្រើប្រាស់បញ្ញាសិប្បនិម្មិត AI ក្នុងការបង្កើតវីដេអូ។ "
        "ប្រព័ន្ធនេះមានសមត្ថភាពបង្កើតសំឡេងនិយាយបានយ៉ាងរលូន និងមានលក្ខណៈធម្មជាតិបំផុត។ "
        "លោកអ្នកអាចបញ្ចូលរូបថតមួយសន្លឹក និងសំឡេងដែលបានថត ឬសំឡេង Clone ដើម្បីឱ្យរូបថតនោះកម្រើកមាត់ និងក្បាលបាន។ "
        "សូមរីករាយជាមួយបទពិសោធន៍ថ្មីនៃបច្ចេកវិទ្យាជំនាន់ក្រោយនេះទាំងអស់គ្នា។"
    )
    chunks = split_text_into_chunks(text, max_chunk_chars=120)
    assert len(chunks) > 1

    # Verify every chunk is within limits
    for c in chunks:
        assert len(c.text) <= 150  # with punctuation tolerance
        assert c.char_start >= 0
        assert c.char_end > c.char_start

    # Verify full coverage without dropped characters
    assert verify_chunk_coverage(text, chunks) is True

def test_split_preserves_order_and_non_overlapping():
    text = "ឃ្លាទីមួយ។ ឃ្លាទីពីរ។ ឃ្លាទីបី។ ឃ្លាទីបួន។ ឃ្លាទីប្រាំ។ ឃ្លាទីប្រាំមួយ។"
    chunks = split_text_into_chunks(text, max_chunk_chars=25)
    assert len(chunks) >= 3

    for i in range(len(chunks) - 1):
        assert chunks[i].index == i
        assert chunks[i].char_end <= chunks[i+1].char_start
