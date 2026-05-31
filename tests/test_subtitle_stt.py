"""Tests for the speech-to-text worker and subtitle broadcaster."""

import json
import unittest
from unittest.mock import MagicMock, patch

from server.features.stt_worker import STTManager, FRAME_BYTES, _FRAMES_PER_CHUNK
from server.features.subtitle import SubtitleBroadcaster
from shared.constants import PacketType


class TestSTTManager(unittest.TestCase):
    """Test suite for STTManager."""

    def setUp(self) -> None:
        self.room_code = "TEST-123"
        self.on_transcript = MagicMock()

    @patch.dict("os.environ", {"ENABLE_STT": "1"})
    def test_stt_enabled_by_env(self) -> None:
        manager = STTManager(self.room_code, self.on_transcript)
        self.assertTrue(manager.is_enabled())
        self.assertIsNotNone(manager._pool)
        manager.stop()

    @patch.dict("os.environ", {"ENABLE_STT": "0"})
    def test_stt_disabled_by_env(self) -> None:
        manager = STTManager(self.room_code, self.on_transcript)
        self.assertFalse(manager.is_enabled())
        self.assertIsNone(manager._pool)
        manager.stop()

    @patch.dict("os.environ", {"ENABLE_STT": "1"})
    def test_stt_buffers_audio_before_submission(self) -> None:
        manager = STTManager(self.room_code, self.on_transcript)
        manager._pool = MagicMock()  # Mock the executor pool

        # Feed 149 frames
        for _ in range(_FRAMES_PER_CHUNK - 1):
            manager.feed_audio(1, "alice", b"\x00" * FRAME_BYTES)

        # Buffer should not be submitted yet
        manager._pool.submit.assert_not_called()
        self.assertEqual(len(manager._speaker_buffers[1]), _FRAMES_PER_CHUNK - 1)

        # Feed 150th frame
        manager.feed_audio(1, "alice", b"\x00" * FRAME_BYTES)

        # Should be submitted now
        manager._pool.submit.assert_called_once()
        self.assertEqual(len(manager._speaker_buffers[1]), 0)

        # Verify correct args to submit
        args = manager._pool.submit.call_args[0]
        self.assertEqual(args[0], manager._transcribe)  # target fn
        self.assertEqual(args[1], 1)  # user_id
        self.assertEqual(args[2], "alice")  # username
        self.assertEqual(len(args[3]), _FRAMES_PER_CHUNK)  # frames list

        manager.stop()


class TestSubtitleBroadcaster(unittest.TestCase):
    """Test suite for SubtitleBroadcaster."""

    def setUp(self) -> None:
        self.room_code = "TEST-123"
        self.clients = {}
        self.get_clients = lambda: self.clients
        self.broadcaster = SubtitleBroadcaster(self.room_code, self.get_clients)

    @patch.dict("os.environ", {"LIBRETRANSLATE_URL": "", "SUBTITLE_TARGET_LANG": ""})
    def test_broadcast_without_translation(self) -> None:
        # Re-init to load mocked env vars
        self.broadcaster = SubtitleBroadcaster(self.room_code, self.get_clients)

        alice_handler = MagicMock()
        self.clients = {1: alice_handler}

        self.broadcaster.broadcast_transcript(1, "alice", "hello world")

        alice_handler.send.assert_called_once()
        ptype, payload = alice_handler.send.call_args[0]
        self.assertEqual(ptype, PacketType.SUBTITLE)
        self.assertEqual(payload["room_code"], self.room_code)
        self.assertEqual(payload["speaker_user_id"], 1)
        self.assertEqual(payload["speaker_username"], "alice")
        self.assertEqual(payload["text"], "hello world")
        self.assertEqual(payload["translated_text"], "")
        self.assertEqual(payload["source_lang"], "auto")

    @patch.dict("os.environ", {
        "LIBRETRANSLATE_URL": "http://localhost:5000",
        "SUBTITLE_TARGET_LANG": "vi",
    })
    @patch("urllib.request.urlopen")
    def test_broadcast_with_translation_success(self, mock_urlopen) -> None:
        self.broadcaster = SubtitleBroadcaster(self.room_code, self.get_clients)

        alice_handler = MagicMock()
        self.clients = {1: alice_handler}

        # Mock the HTTP response from LibreTranslate
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "translatedText": "xin chào thế giới",
            "detectedLanguage": {"language": "en"},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        self.broadcaster.broadcast_transcript(1, "alice", "hello world")

        # Verify urllib.request.Request parameters
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://localhost:5000/translate")
        self.assertEqual(req.get_header("Content-type"), "application/json")

        # Verify client message
        alice_handler.send.assert_called_once()
        ptype, payload = alice_handler.send.call_args[0]
        self.assertEqual(ptype, PacketType.SUBTITLE)
        self.assertEqual(payload["translated_text"], "xin chào thế giới")
        self.assertEqual(payload["source_lang"], "en")
        self.assertEqual(payload["target_lang"], "vi")

    @patch.dict("os.environ", {
        "LIBRETRANSLATE_URL": "http://localhost:5000",
        "SUBTITLE_TARGET_LANG": "vi",
    })
    @patch("urllib.request.urlopen")
    def test_broadcast_with_translation_failure_sends_original(self, mock_urlopen) -> None:
        self.broadcaster = SubtitleBroadcaster(self.room_code, self.get_clients)

        alice_handler = MagicMock()
        self.clients = {1: alice_handler}

        # Mock HTTP connection failure
        mock_urlopen.side_effect = Exception("Connection refused")

        self.broadcaster.broadcast_transcript(1, "alice", "hello world")

        # Subtitle should still be sent, but with empty translated text
        alice_handler.send.assert_called_once()
        ptype, payload = alice_handler.send.call_args[0]
        self.assertEqual(ptype, PacketType.SUBTITLE)
        self.assertEqual(payload["text"], "hello world")
        self.assertEqual(payload["translated_text"], "")
        self.assertEqual(payload["source_lang"], "auto")


if __name__ == "__main__":
    unittest.main()
