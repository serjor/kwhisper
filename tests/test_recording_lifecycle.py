# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Application callbacks without Qt, GPU, or a desktop session."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kwhisper.app import KWhisper
from kwhisper.hotkey.portal_listener import PortalListener


@pytest.fixture
def app():
    instance = KWhisper.__new__(KWhisper)
    instance._lock = threading.Lock()
    instance.enabled = True
    instance._recording = False
    instance._processing = False
    instance.recorder = Mock()
    instance.tts = Mock()
    instance.feedback = Mock()
    instance.router = None
    instance._overlay_placer = None
    instance.ctrl = SimpleNamespace(state=Mock(), overlay=Mock(), notify=Mock())
    return instance


def test_failed_start_can_be_retried(app):
    app.recorder.start.side_effect = [RuntimeError("no microphone"), None]
    assert app._on_start() is False
    assert not app._recording
    assert not app._processing
    app.ctrl.notify.emit.assert_called_once()
    assert app._on_start() is True
    assert app._recording


@pytest.mark.parametrize("failure", ["stop", "feedback", "construct_worker", "start_worker"])
@pytest.mark.parametrize("enabled", [True, False])
def test_stop_failure_cleans_state_before_next_recording(app, monkeypatch, failure, enabled):
    assert app._on_start()
    app.enabled = enabled
    original = RuntimeError("simulated failure")
    worker = Mock()
    factory = Mock(return_value=worker)
    monkeypatch.setattr("kwhisper.app.threading.Thread", factory)
    if failure == "stop":
        app.recorder.stop.side_effect = original
    elif failure == "feedback":
        app.feedback.play.side_effect = original
    elif failure == "construct_worker":
        factory.side_effect = original
    else:
        worker.start.side_effect = original
    events = []

    def on_overlay(*args):
        events.append(("overlay", args))
        assert app._processing
        assert not app._on_start()

    def on_state(state):
        events.append(("state", state))
        assert app._processing
        assert not app._on_start()

    app.ctrl.overlay.emit.side_effect = on_overlay
    app.ctrl.state.emit.side_effect = on_state
    assert app._on_stop() is True
    assert not app._recording
    assert not app._processing
    assert events[-2:] == [("overlay", ("", "")), ("state", "idle" if enabled else "disabled")]
    app.ctrl.notify.emit.assert_called_once()
    if failure in ("stop", "feedback"):
        factory.assert_not_called()
    assert app._on_stop() is False
    app.enabled = True
    app.feedback.play.side_effect = None
    app.ctrl.overlay.emit.side_effect = None
    app.ctrl.state.emit.side_effect = None
    assert app._on_start() is True


def test_portal_can_restart_after_failed_stop(app):
    portal = PortalListener(app._on_start, app._on_stop)
    portal._toggle()
    assert portal._recording
    app.recorder.stop.side_effect = RuntimeError("microphone disconnected")
    portal._toggle()
    assert not portal._recording
    assert not app._processing
    portal._toggle()
    assert portal._recording
    assert app._recording
    assert app.recorder.start.call_count == 2


def test_successful_stop_hands_audio_to_worker(app, monkeypatch):
    worker = Mock()
    factory = Mock(return_value=worker)
    monkeypatch.setattr("kwhisper.app.threading.Thread", factory)
    assert app._on_start()
    assert app._on_stop()
    assert app._processing
    assert not app._recording
    assert not app._on_start()
    assert factory.call_args.kwargs["target"] == app._process
    assert factory.call_args.kwargs["args"] == (app.recorder.stop.return_value,)
    worker.start.assert_called_once()
    app.ctrl.notify.emit.assert_not_called()
