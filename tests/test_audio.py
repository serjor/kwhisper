# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Audio lifecycle tests without PortAudio or a microphone."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def audio_module(monkeypatch):
    device = SimpleNamespace(InputStream=Mock())
    monkeypatch.setitem(sys.modules, "sounddevice", device)
    path = Path(__file__).parents[1] / "src/kwhisper/audio.py"
    spec = importlib.util.spec_from_file_location("audio_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_clean(recorder):
    assert not recorder.recording
    assert recorder._stream is None
    assert recorder._frames == []
    assert recorder.level == 0


def capture(recorder, samples):
    recorder._callback(samples, len(samples), None, None)


def assert_retry(module, recorder):
    module.sd.InputStream = Mock(return_value=Mock())
    recorder.start()
    assert recorder.recording
    samples = np.array([[16384], [-16384]], dtype=np.int16)
    capture(recorder, samples)
    np.testing.assert_array_equal(recorder.stop(), [0.5, -0.5])
    assert_clean(recorder)


@pytest.mark.parametrize("failure", ["construct", "start", "start_and_close"])
def test_failed_start_releases_state_and_allows_retry(audio_module, failure, caplog):
    recorder = audio_module.AudioRecorder()
    stream = Mock()
    original = RuntimeError("microphone unavailable")
    if failure == "construct":
        audio_module.sd.InputStream.side_effect = original
    else:
        audio_module.sd.InputStream.return_value = stream

        def fail_start():
            capture(recorder, np.full((4, 1), 10000, dtype=np.int16))
            raise original

        stream.start.side_effect = fail_start
        if failure == "start_and_close":
            stream.close.side_effect = RuntimeError("close failed too")
    with pytest.raises(RuntimeError) as error:
        recorder.start()
    assert error.value is original
    if failure != "construct":
        stream.close.assert_called_once()
    if failure == "start_and_close":
        assert "close failed too" in caplog.text
    assert_clean(recorder)
    assert_retry(audio_module, recorder)


@pytest.mark.parametrize("failure", ["stop", "close", "stop_and_close"])
def test_failed_stop_closes_discards_and_allows_retry(audio_module, failure, caplog):
    recorder = audio_module.AudioRecorder()
    stream = audio_module.sd.InputStream.return_value
    recorder.start()
    capture(recorder, np.full((4, 1), 10000, dtype=np.int16))
    original = RuntimeError("capture failed")
    if failure != "close":
        stream.stop.side_effect = original
    if failure != "stop":
        stream.close.side_effect = original if failure == "close" else RuntimeError("close too")
    with pytest.raises(RuntimeError) as error:
        recorder.stop()
    assert error.value is original
    stream.close.assert_called_once()
    if failure == "stop_and_close":
        assert "close too" in caplog.text
    assert_clean(recorder)
    assert recorder.stop().size == 0
    assert_retry(audio_module, recorder)


@pytest.mark.parametrize("channels", [1, 2])
def test_successful_capture_normalization_and_late_callback(audio_module, channels):
    recorder = audio_module.AudioRecorder(channels=channels)
    stream = audio_module.sd.InputStream.return_value
    samples = np.array([[-32768, 16384], [32767, 0]], dtype=np.int16)[:, :channels]

    def feed():
        # PortAudio must never be invoked while holding the callback lock.
        assert recorder._lock.acquire(blocking=False)
        recorder._lock.release()
        capture(recorder, samples)

    stream.start.side_effect = feed
    stream.stop.side_effect = feed
    stream.close.side_effect = feed
    recorder.start()
    recorder.start()  # Already recording: do not open another stream.
    audio_module.sd.InputStream.assert_called_once()
    result = recorder.stop()
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, samples.mean(axis=1).astype(np.float32) / 32768)
    assert_clean(recorder)
    capture(recorder, samples)  # Even a callback after close cannot revive the meter.
    assert_clean(recorder)
    assert recorder.stop().size == 0
    stream.close.assert_called_once()
