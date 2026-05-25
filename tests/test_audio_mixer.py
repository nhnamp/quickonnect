import struct

from server.features.audio_mixer import BYTES_PER_FRAME, mix_pcm16


def _frame(value: int) -> bytes:
    sample_count = BYTES_PER_FRAME // 2
    return struct.pack("<" + "h" * sample_count, *([value] * sample_count))


def _first_sample(frame: bytes) -> int:
    return struct.unpack("<h", frame[:2])[0]


def test_mix_pcm16_averages_sources():
    mixed = mix_pcm16([_frame(1000), _frame(3000)])
    assert len(mixed) == BYTES_PER_FRAME
    assert _first_sample(mixed) == 2000


def test_mix_pcm16_excludes_empty_input():
    assert mix_pcm16([]) == b""


def test_mix_pcm16_clips_to_int16_range():
    mixed = mix_pcm16([_frame(32767), _frame(32767), _frame(32767)])
    assert _first_sample(mixed) == 32767
