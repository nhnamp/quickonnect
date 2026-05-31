"""Tests for the per-room audio mixer."""

import base64
import struct
import unittest
from unittest.mock import MagicMock

from server.features.audio_mixer import (
    AudioMixerState,
    FRAME_BYTES,
    FRAME_SIZE,
    SAMPLE_RATE,
    CHANNELS,
    SAMPLE_WIDTH,
)
from shared.constants import PacketType


class TestAudioMixer(unittest.TestCase):
    """Test suite for AudioMixerState."""

    def setUp(self) -> None:
        self.room_code = "TEST-123"
        self.clients = {}
        self.get_clients = lambda: self.clients
        self.stt_feed = MagicMock()
        self.mixer = AudioMixerState(
            self.room_code,
            self.get_clients,
            stt_feed_fn=self.stt_feed,
        )

    def tearDown(self) -> None:
        self.mixer.stop()

    def test_participant_management(self) -> None:
        self.assertFalse(self.mixer.has_participants())
        
        self.mixer.add_participant(1, "alice")
        self.assertTrue(self.mixer.has_participants())
        self.assertIn(1, self.mixer._buffers)
        self.assertEqual(self.mixer._usernames[1], "alice")

        self.mixer.remove_participant(1)
        self.assertFalse(self.mixer.has_participants())
        self.assertNotIn(1, self.mixer._buffers)

    def test_feed_audio_normalises_frame_size(self) -> None:
        # Create silent frames of different sizes
        short_frame = b"\x01\x02"
        long_frame = b"\x01" * 1000
        correct_frame = b"\x02" * FRAME_BYTES

        # Short frame should be padded with zeros
        self.mixer.feed_audio(1, base64.b64encode(short_frame).decode("ascii"))
        self.stt_feed.assert_called_once()
        fed_pcm = self.stt_feed.call_args[0][2]
        self.assertEqual(len(fed_pcm), FRAME_BYTES)
        self.assertTrue(fed_pcm.startswith(short_frame))
        self.assertTrue(fed_pcm.endswith(b"\x00" * (FRAME_BYTES - len(short_frame))))

        # Long frame should be truncated
        self.stt_feed.reset_mock()
        self.mixer.feed_audio(1, base64.b64encode(long_frame).decode("ascii"))
        fed_pcm = self.stt_feed.call_args[0][2]
        self.assertEqual(len(fed_pcm), FRAME_BYTES)
        self.assertEqual(fed_pcm, long_frame[:FRAME_BYTES])

        # Correct frame should stay as-is
        self.stt_feed.reset_mock()
        self.mixer.feed_audio(1, base64.b64encode(correct_frame).decode("ascii"))
        fed_pcm = self.stt_feed.call_args[0][2]
        self.assertEqual(len(fed_pcm), FRAME_BYTES)
        self.assertEqual(fed_pcm, correct_frame)

    def test_feed_audio_handles_invalid_base64(self) -> None:
        self.mixer.feed_audio(1, "invalid_base64_string!!!")
        self.stt_feed.assert_not_called()
        self.assertEqual(len(self.mixer._buffers.get(1, [])), 0)

    def test_mixing_frames_single_frame(self) -> None:
        frame = b"\x05" * FRAME_BYTES
        mixed = AudioMixerState._mix_frames([frame])
        self.assertEqual(mixed, frame)

    def test_mixing_frames_adds_samples(self) -> None:
        # Create frames with distinct values
        fmt = f"<{FRAME_SIZE}h"
        samples1 = [10] * FRAME_SIZE
        samples2 = [20] * FRAME_SIZE
        frame1 = struct.pack(fmt, *samples1)
        frame2 = struct.pack(fmt, *samples2)

        mixed = AudioMixerState._mix_frames([frame1, frame2])
        mixed_samples = struct.unpack(fmt, mixed)
        self.assertEqual(list(mixed_samples), [30] * FRAME_SIZE)

    def test_mixing_frames_clips_samples(self) -> None:
        fmt = f"<{FRAME_SIZE}h"
        samples1 = [30000] * FRAME_SIZE
        samples2 = [10000] * FRAME_SIZE
        frame1 = struct.pack(fmt, *samples1)
        frame2 = struct.pack(fmt, *samples2)

        mixed = AudioMixerState._mix_frames([frame1, frame2])
        mixed_samples = struct.unpack(fmt, mixed)
        self.assertEqual(list(mixed_samples), [32767] * FRAME_SIZE)  # clipped to max int16

        samples3 = [-30000] * FRAME_SIZE
        samples4 = [-10000] * FRAME_SIZE
        frame3 = struct.pack(fmt, *samples3)
        frame4 = struct.pack(fmt, *samples4)

        mixed_neg = AudioMixerState._mix_frames([frame3, frame4])
        mixed_neg_samples = struct.unpack(fmt, mixed_neg)
        self.assertEqual(list(mixed_neg_samples), [-32768] * FRAME_SIZE)  # clipped to min int16

    def test_mix_tick_sends_to_everyone_excluding_self(self) -> None:
        # Register two clients in get_clients
        alice_handler = MagicMock()
        bob_handler = MagicMock()
        self.clients = {1: alice_handler, 2: bob_handler}

        self.mixer.add_participant(1, "alice")
        self.mixer.add_participant(2, "bob")

        # Feed audio from alice
        alice_fmt = f"<{FRAME_SIZE}h"
        alice_samples = [10] * FRAME_SIZE
        alice_frame = struct.pack(alice_fmt, *alice_samples)
        self.mixer.feed_audio(1, base64.b64encode(alice_frame).decode("ascii"))

        # Feed audio from bob
        bob_samples = [20] * FRAME_SIZE
        bob_frame = struct.pack(alice_fmt, *bob_samples)
        self.mixer.feed_audio(2, base64.b64encode(bob_frame).decode("ascii"))

        # Call mix tick manually
        self.mixer._mix_tick()

        # Alice should receive Bob's audio (20)
        alice_handler.send.assert_called_once()
        args, kwargs = alice_handler.send.call_args
        self.assertEqual(args[0], PacketType.MIXED_AUDIO)
        payload = args[1]
        self.assertEqual(payload["room_code"], self.room_code)
        alice_mixed = base64.b64decode(payload["pcm_b64"])
        alice_mixed_samples = struct.unpack(alice_fmt, alice_mixed)
        self.assertEqual(list(alice_mixed_samples), bob_samples)

        # Bob should receive Alice's audio (10)
        bob_handler.send.assert_called_once()
        args, kwargs = bob_handler.send.call_args
        self.assertEqual(args[0], PacketType.MIXED_AUDIO)
        payload = args[1]
        self.assertEqual(payload["room_code"], self.room_code)
        bob_mixed = base64.b64decode(payload["pcm_b64"])
        bob_mixed_samples = struct.unpack(alice_fmt, bob_mixed)
        self.assertEqual(list(bob_mixed_samples), alice_samples)


if __name__ == "__main__":
    unittest.main()
