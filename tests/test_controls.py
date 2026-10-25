"""Actuator tests use injected transports only: no packets reach a real gate."""

import importlib.util
from pathlib import Path
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "viewdoor_controls", Path(__file__).parents[1] / "custom_components/vimar_viewdoor/controls.py"
)
controls = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = controls
spec.loader.exec_module(controls)


def test_construction_and_mapping_do_not_send():
    calls = []
    controller = controls.GateController(
        "192.168.1.50", "a" * 64, sender=lambda **kw: calls.append(kw)
    )
    controls.GateTarget("pedestrian", 1)
    controls.GateTarget("driveway", 2)
    assert calls == []
    assert controller._last_attempt is None


def test_each_button_maps_to_one_request_without_redirects(monkeypatch):
    from quii_helper.device import control

    calls = []

    def transport(command, **kwargs):
        calls.append((command, kwargs))
        return {"raw": b"<envelope><body><error>0</error></body></envelope>"}

    monkeypatch.setattr(control, "request_cgi", transport)
    now = [100.0]
    gate = controls.GateController("192.168.1.50", "a" * 64, clock=lambda: now[0])
    for key, output in [("pedestrian", 1), ("driveway", 2)]:
        gate.press(controls.GateTarget(key, output))
        now[0] += 11
    assert len(calls) == 2
    for output, (command, kwargs) in enumerate(calls, 1):
        assert command == "set.device.opendoor"
        assert kwargs["allow_redirects"] is False
        assert kwargs["debug"] is False
        assert kwargs["content"].findtext("door") == "1"
        assert kwargs["content"].findtext("locknumber") == str(output)
        assert kwargs["content"].findtext("password") == "a" * 64


def test_timeout_is_unknown_never_retried_and_blocks_other_button():
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise OSError("SECRET-MUST-NOT-LEAK")

    gate = controls.GateController("192.168.1.50", "a" * 64, sender=fail)
    with pytest.raises(controls.GateCommandError) as caught:
        gate.press(controls.GateTarget("pedestrian", 1))
    assert "SECRET" not in str(caught.value)
    assert "potrebbe" in str(caught.value)
    with pytest.raises(controls.GateCommandError):
        gate.press(controls.GateTarget("driveway", 2))
    assert len(calls) == 1


def test_concurrent_presses_are_not_queued_or_replayed():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(accepted=True)

    gate = controls.GateController("192.168.1.50", "a" * 64, sender=send)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(gate.press, controls.GateTarget("pedestrian", 1))
        try:
            assert entered.wait(1)
            with pytest.raises(controls.GateCommandError):
                gate.press(controls.GateTarget("driveway", 2))
        finally:
            release.set()
        future.result()
    assert len(calls) == 1


@pytest.mark.parametrize("output", [0, 3, -1])
def test_invalid_output_never_calls_transport(output):
    def forbidden(**_):
        raise AssertionError("No transport allowed")

    gate = controls.GateController("192.168.1.50", "a" * 64, sender=forbidden)
    with pytest.raises(controls.GateCommandError):
        gate.press(controls.GateTarget("pedestrian", output))


class VideoSession:
    def __init__(self, events, *, ready=True, fail_at=None):
        self.events = events
        self.play_accepted = ready
        self.fail_at = fail_at
        self.reads = 0

    def open(self):
        self.events.append('video-open')
        if self.fail_at == 'open':
            raise OSError('secret')

    def recv_message(self, *, timeout):
        self.reads += 1
        self.events.append('image')
        if self.fail_at == 'read':
            raise OSError('secret')
        return {'is_media': self.play_accepted}

    def close(self):
        self.events.append('video-close')


def video_workflow(*, ready=True, fail_at=None):
    events = []
    session = VideoSession(events, ready=ready, fail_at=fail_at)
    def send(**kwargs):
        events.append(('impulse', kwargs['lock_number']))
        if fail_at == 'impulse':
            raise OSError('secret')
        return SimpleNamespace(accepted=True)
    now = [0]
    def clock():
        now[0] += 0.1
        return now[0]
    controller = controls.GateController('192.168.1.50', 'a'*64, sender=send)
    class Assembler:
        def __init__(self, **kwargs):
            assert kwargs["wait_for_keyframe"] is True
            self.access_unit_count = 0

        def feed_message(self, message):
            self.access_unit_count += bool(message.get("is_media"))

    workflow = controls.VideoGateController(controller, lambda: session, clock=clock,
                                           ready_seconds=1, settle_seconds=0.2,
                                           assembler_factory=Assembler)
    return workflow, events


@pytest.mark.parametrize('output', [1, 2])
def test_video_ready_then_one_impulse_then_close(output):
    workflow, events = video_workflow()
    workflow.press(controls.GateTarget('target', output))
    assert events[:4] == ['video-open', 'image', 'image', 'image']
    assert [e for e in events if isinstance(e, tuple)] == [('impulse', output)]
    assert events[-1] == 'video-close'


@pytest.mark.parametrize('failure', ['open', 'read', 'impulse'])
def test_every_error_closes_video_and_never_retries(failure):
    workflow, events = video_workflow(fail_at=failure)
    with pytest.raises(controls.GateCommandError) as caught:
        workflow.press(controls.GateTarget('target', 1))
    assert 'secret' not in str(caught.value)
    assert events[-1] == 'video-close'
    assert len([e for e in events if isinstance(e, tuple)]) == (failure == 'impulse')


def test_no_images_means_no_impulse():
    workflow, events = video_workflow(ready=False)
    with pytest.raises(controls.GateCommandError, match='Video non pronto'):
        workflow.press(controls.GateTarget('target', 1))
    assert not any(isinstance(e, tuple) for e in events)
    assert events[-1] == 'video-close'


def test_cancel_before_ready_never_opens_gate():
    workflow, events = video_workflow()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(controls.GateCommandError, match='annullata'):
        workflow.press(controls.GateTarget('target', 1), cancelled=cancelled)
    assert events == ['video-open', 'video-close']
