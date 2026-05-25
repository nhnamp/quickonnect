from client.features.whiteboard_engine import last_undoable_seq, make_draw_packet, normalize_rect


def test_normalize_rect_orders_coordinates():
    assert normalize_rect(10, 20, 4, 5) == {"x": 4, "y": 5, "w": 6, "h": 15}


def test_make_draw_packet_includes_room_and_client_seq():
    packet = make_draw_packet("ABC-1234", "TEXT", {"text": "hi"}, 7)
    assert packet["room_code"] == "ABC-1234"
    assert packet["event_type"] == "TEXT"
    assert packet["client_seq_num"] == 7


def test_last_undoable_seq_skips_already_undone_events():
    events = [
        {"seq_num": 1, "user_id": 10, "event_type": "STROKE", "payload": {}},
        {"seq_num": 2, "user_id": 10, "event_type": "RECT", "payload": {}},
        {"seq_num": 3, "user_id": 10, "event_type": "UNDO", "payload": {"target_seq_num": 2}},
    ]
    assert last_undoable_seq(events, 10) == 1

