"""Tests for client-side audio frame helpers."""

from client.features.audio_engine import (
    AudioEngine,
    CHUNK_SIZE,
    FRAME_DURATION_MS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
)


def test_frames_per_packet_uses_20ms_window() -> None:
    assert AudioEngine._frames_per_packet(SAMPLE_RATE) == CHUNK_SIZE
    assert AudioEngine._frames_per_packet(48000) == int(48000 * FRAME_DURATION_MS / 1000)


def test_candidate_rates_prefers_network_rate_then_device_rate() -> None:
    rates = AudioEngine._candidate_rates({"defaultSampleRate": 48000.0})

    assert rates[0] == SAMPLE_RATE
    assert 48000 in rates
    assert len(rates) == len(set(rates))


def test_fit_pcm_frame_pads_and_truncates_to_network_frame_size() -> None:
    target_bytes = CHUNK_SIZE * SAMPLE_WIDTH

    short = b"\x01\x02"
    fitted_short = AudioEngine._fit_pcm_frame(short)
    assert len(fitted_short) == target_bytes
    assert fitted_short.startswith(short)
    assert fitted_short.endswith(b"\x00" * (target_bytes - len(short)))

    long = b"\x03" * (target_bytes + 100)
    fitted_long = AudioEngine._fit_pcm_frame(long)
    assert len(fitted_long) == target_bytes
    assert fitted_long == long[:target_bytes]


def test_resample_pcm_mono16_changes_sample_count() -> None:
    source_rate = 48000
    target_rate = SAMPLE_RATE
    source_samples = int(source_rate * FRAME_DURATION_MS / 1000)
    pcm = b"\x00\x00" * source_samples

    resampled = AudioEngine._resample_pcm_mono16(pcm, source_rate, target_rate)

    assert len(resampled) == CHUNK_SIZE * SAMPLE_WIDTH
