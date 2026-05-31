"""Tests for per-room camera state."""

from server.features.camera_state import CameraState


def test_camera_state_tracks_active_users() -> None:
    state = CameraState()

    assert not state.is_active(1)
    assert state.start_camera(1, "alice") is True
    assert state.is_active(1)
    assert state.start_camera(1, "alice") is False

    active = state.get_active()
    assert len(active) == 1
    assert active[0].to_dict() == {"user_id": 1, "username": "alice"}

    assert state.stop_camera(1) is True
    assert state.stop_camera(1) is False
    assert not state.is_active(1)


def test_camera_state_returns_sorted_snapshot() -> None:
    state = CameraState()

    state.start_camera(2, "bob")
    state.start_camera(1, "alice")

    assert [user.user_id for user in state.get_active()] == [1, 2]
