"""Tests for the server-side whiteboard manager."""

import json
import unittest
from unittest.mock import MagicMock, patch

from server.features.whiteboard import WhiteboardState, BACKGROUND_COLOR


class TestWhiteboardState(unittest.TestCase):
    """Test suite for WhiteboardState."""

    def setUp(self) -> None:
        self.room_id = 42
        self.room_code = "ROOM-42"

        # Start patcher for database connection
        self.patcher = patch("server.features.whiteboard.get_connection")
        self.mock_get_connection = self.patcher.start()

        # Mock psycopg connection and cursor
        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_conn.__enter__.return_value = self.mock_conn
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cursor
        self.mock_get_connection.return_value = self.mock_conn

        # Mock database loading empty rows initially
        self.mock_cursor.fetchall.return_value = []
        self.mock_cursor.fetchone.return_value = None

        self.state = WhiteboardState(self.room_id, self.room_code, start_thread=False)

        # Reset mock calls recorded during initialization (e.g. load_from_db)
        self.mock_cursor.reset_mock()
        self.mock_conn.reset_mock()

    def tearDown(self) -> None:
        self.state.stop()
        self.patcher.stop()

    def test_load_from_db_parses_existing_events(self) -> None:
        # Mock existing draw and undo events in database
        self.mock_cursor.fetchall.return_value = [
            (1, 10, "pen", json.dumps({"points": [[10, 10]], "color": "#ffffff", "width": 4})),
            (2, 11, "rect", json.dumps({"rect": [20, 20, 100, 50], "color": "#ff5555", "width": 2})),
            (3, 10, "undo", json.dumps({"target_seq": 1})),
        ]

        self.state.load_from_db()

        # Target event 1 should be recorded as undone
        self.assertIn(1, self.state._undone_seqs)
        self.assertEqual(self.state._last_seq, 3)

        # active events list should only contain rect (seq=2)
        active = self.state.get_active_events()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["seq_num"], 2)
        self.assertEqual(active[0]["event_type"], "rect")

    def test_add_event_persists_to_db(self) -> None:
        payload = {"rect": [10, 20, 30, 40], "color": "#00ff00"}
        seq = self.state.add_event(10, "rect", payload)

        self.assertEqual(seq, 1)
        self.assertEqual(self.state._last_seq, 1)

        # Verify cursor execution
        self.mock_cursor.execute.assert_called_once()
        args = self.mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO whiteboard_events", args[0])
        self.assertEqual(args[1], (self.room_id, 10, 1, "rect", json.dumps(payload)))
        self.mock_conn.commit.assert_called_once()

    def test_undo_filtration_logic(self) -> None:
        # Simulate local events
        self.state.add_event(10, "rect", {"rect": [0, 0, 10, 10]})
        self.state.add_event(10, "oval", {"rect": [0, 0, 10, 10]})
        self.state.add_event(10, "undo", {"target_seq": 1})  # undoes rect

        active = self.state.get_active_events()
        # Should contain only oval (seq=2)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["seq_num"], 2)
        self.assertEqual(active[0]["event_type"], "oval")

    def test_headless_rendering_png(self) -> None:
        # Load drawing events of all types
        self.state.add_event(10, "pen", {"points": [[50, 50], [100, 100]], "color": "#ffffff", "width": 4})
        self.state.add_event(10, "rect", {"rect": [20, 20, 200, 100], "color": "#ff5555", "width": 2})
        self.state.add_event(10, "oval", {"rect": [300, 300, 50, 50], "color": "#55ff55", "width": 3})
        self.state.add_event(10, "text", {"text": "hello", "text_pos": [100, 200], "color": "#ffff55"})
        self.state.add_event(10, "eraser", {"points": [[40, 40], [80, 80]], "width": 10})

        # Test rendering
        png_bytes = self.state.render_png()

        self.assertTrue(len(png_bytes) > 0)
        # Check standard PNG file signature: 89 50 4E 47 0D 0A 1A 0A
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
