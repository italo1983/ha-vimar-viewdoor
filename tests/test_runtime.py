"""Exercise real executor cancellation and per-device serialization."""

import asyncio
import importlib.util
from pathlib import Path
import threading
from functools import partial

spec = importlib.util.spec_from_file_location(
    "viewdoor_runtime", Path(__file__).parents[1] / "custom_components/vimar_viewdoor/runtime.py"
)
runtime_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_module)


class HassExecutor:
    def async_add_executor_job(self, function, *args):
        return asyncio.get_running_loop().run_in_executor(None, partial(function, *args))


def test_cancelled_request_keeps_lock_until_worker_finishes():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        runtime = runtime_module.DeviceRuntime(HassExecutor(), {})

        def capture(_input):
            entered.set()
            assert release.wait(3)
            return b"jpeg"

        runtime._capture = capture
        first = asyncio.create_task(runtime.image(1))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            first.cancel()
            await asyncio.sleep(0)
            assert runtime.lock.locked()
            second = asyncio.create_task(runtime.image(3))
            await asyncio.sleep(0)
            assert not second.done()
            release.set()
            try:
                await first
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Cancellation must propagate")
            assert await second == b"jpeg"
            assert not runtime.lock.locked()
        finally:
            release.set()

    asyncio.run(scenario())


def test_worker_failure_does_not_block_next_camera():
    async def scenario():
        runtime = runtime_module.DeviceRuntime(HassExecutor(), {})

        def capture(input_id):
            if input_id == 1:
                raise OSError("offline")
            return b"jpeg"

        runtime._capture = capture
        try:
            await runtime.image(1)
        except OSError:
            pass
        else:
            raise AssertionError("Failure should propagate to camera boundary")
        assert await runtime.image(3) == b"jpeg"

    asyncio.run(scenario())


def test_stream_source_lazy_shared_and_unload_closes_all():
    async def scenario():
        runtime = runtime_module.DeviceRuntime(HassExecutor(), {})
        created = []

        class Relay:
            def __init__(self, input_id):
                self.url = f"rtsp://127.0.0.1:{10000 + input_id}/live"
                self.closed = False

            def close(self):
                self.closed = True

        def start(input_id):
            relay = Relay(input_id)
            created.append(relay)
            return relay

        runtime._start_relay = start
        assert not created
        first, same = await asyncio.gather(runtime.stream_source(1), runtime.stream_source(1))
        assert first == same and len(created) == 1
        assert await runtime.stream_source(3) != first
        await runtime.close()
        assert all(r.closed for r in created)
        assert not runtime.relays
        try:
            await runtime.stream_source(1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Cannot reopen unloaded entry")

    asyncio.run(scenario())


def test_gate_cancel_waits_for_cleanup_and_rejects_duplicate(monkeypatch):
    import sys
    from types import SimpleNamespace
    from importlib.machinery import ModuleSpec
    monkeypatch.setattr(runtime_module, '__package__', 'runtime_test_package')
    monkeypatch.setattr(runtime_module, '__spec__',
                        ModuleSpec('runtime_test_package.runtime', loader=None))
    monkeypatch.setitem(sys.modules, 'runtime_test_package.controls',
                        SimpleNamespace(GateCommandError=RuntimeError))

    async def scenario():
        runtime = runtime_module.DeviceRuntime(HassExecutor(), {})
        entered, release = threading.Event(), threading.Event()
        completed = []
        def worker(target, options, cancelled):
            entered.set()
            assert release.wait(3)
            assert cancelled.is_set()
            completed.append('closed')
        runtime._press_gate = worker
        first = asyncio.create_task(runtime.press_gate('pedestrian', {}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            try:
                await runtime.press_gate('driveway', {})
            except RuntimeError:
                pass
            else:
                raise AssertionError('Duplicate must be rejected, never queued')
            first.cancel()
            await asyncio.sleep(0)
            assert runtime.lock.locked() and runtime._gate_pending
            unloading = asyncio.create_task(runtime.close())
            await asyncio.sleep(0)
            assert not unloading.done()
            release.set()
            try:
                await first
            except asyncio.CancelledError:
                pass
            await unloading
            assert completed == ['closed']
            assert runtime.closed and not runtime._gate_pending
        finally:
            release.set()
    asyncio.run(scenario())


def test_gate_workflow_pauses_viewers_and_resumes_after_failure():
    from types import SimpleNamespace
    runtime = runtime_module.DeviceRuntime(HassExecutor(), {})
    events = []
    runtime.relays = {1: SimpleNamespace(
        pause=lambda: events.append('paused'), resume=lambda: events.append('resumed'))}
    def fail(*args, **kwargs):
        events.append('gate')
        raise RuntimeError('failed')
    runtime._gates = SimpleNamespace(press=fail)
    try:
        runtime._press_gate('target', {}, threading.Event())
    except RuntimeError:
        pass
    assert events == ['paused', 'gate', 'resumed']
