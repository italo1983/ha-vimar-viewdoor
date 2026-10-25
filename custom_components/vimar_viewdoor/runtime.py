"""Serialized image capture independent of Home Assistant entity lifecycle."""

import asyncio
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import threading


class DeviceRuntime:
    """Serialize physical-device access, including cancelled HA requests."""

    def __init__(self, hass, data):
        self.hass = hass
        self.data = data
        self.lock = asyncio.Lock()
        self.relays = {}
        self.closed = False
        # Opening logic is instantiated lazily; setup never contacts a relay.
        self._gates = None
        self._gate_pending = False

    @property
    def gates(self):
        if self._gates is None:
            from .controls import GateController, VideoGateController

            self._gates = VideoGateController(
                GateController(self.data["host"], self.data["auth_code"]),
                self._gate_session,
            )
        return self._gates

    def _gate_session(self):
        from .protocol import make_camera

        return make_camera(
            self.data["host"], self.data["device_id"], self.data["stream_key"],
            self.data["auth_code"], 1, "/tmp",
        ).connector.create_lan_session()

    def _press_gate(self, target, options, cancelled):
        paused = []
        try:
            for relay in self.relays.values():
                paused.append(relay)
                relay.pause()
            self.gates.press(
                target, password=options.get("unlock_password") or None,
                password_mode=options.get("unlock_password_mode", "sha256"),
                cancelled=cancelled,
            )
        finally:
            for relay in paused:
                relay.resume()

    async def press_gate(self, target, options):
        from .controls import GateCommandError

        # No await between checking and setting: duplicate requests are rejected,
        # not queued behind the video warm-up or another image capture.
        if self.closed or self._gate_pending:
            raise GateCommandError("Comando già in corso o integrazione non disponibile.")
        self._gate_pending = True
        cancelled = threading.Event()
        try:
            async with self.lock:
                if self.closed:
                    raise GateCommandError("Integrazione non disponibile.")
                job = asyncio.ensure_future(self.hass.async_add_executor_job(
                    self._press_gate, target, dict(options), cancelled
                ))
                try:
                    await asyncio.shield(job)
                except asyncio.CancelledError:
                    cancelled.set()
                    try:
                        await job
                    except Exception:
                        pass
                    raise
        finally:
            self._gate_pending = False

    async def stream_source(self, input_id):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Device unloaded")
            if input_id not in self.relays:
                job = asyncio.ensure_future(
                    self.hass.async_add_executor_job(self._start_relay, input_id)
                )
                try:
                    self.relays[input_id] = await asyncio.shield(job)
                except asyncio.CancelledError:
                    relay = await job
                    await self.hass.async_add_executor_job(relay.close)
                    raise
            return self.relays[input_id].url

    def _start_relay(self, input_id):
        from .protocol import make_camera
        from .relay import OnDemandRelay

        camera = make_camera(
            self.data["host"],
            self.data["device_id"],
            self.data["stream_key"],
            self.data["auth_code"],
            input_id,
            "/tmp",
        )
        return OnDemandRelay(camera.connector).start()

    async def close(self):
        async with self.lock:
            self.closed = True
            for relay in self.relays.values():
                await self.hass.async_add_executor_job(relay.close)
            self.relays.clear()

    def _capture(self, input_id):
        # No images or diagnostic artifacts persist in the HA configuration.
        from .protocol import make_camera

        with TemporaryDirectory(prefix="vimar-viewdoor-") as directory:
            if input_id in self.relays:
                image = Path(directory) / "frame.jpg"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-rtsp_transport",
                        "tcp",
                        "-i",
                        self.relays[input_id].url,
                        "-vf",
                        "select=gte(t\\,2)",
                        "-frames:v",
                        "1",
                        "-y",
                        str(image),
                    ],
                    check=True,
                    timeout=18,
                    capture_output=True,
                )
                return image.read_bytes()
            camera = make_camera(
                self.data["host"],
                self.data["device_id"],
                self.data["stream_key"],
                self.data["auth_code"],
                input_id,
                directory,
            )
            # The device initially sends black frames while powering the input.
            # Retain a short clip privately and extract a frame near its end.
            video = camera.save_video(8, output_path=Path(directory) / "warmup.mp4")
            image = Path(directory) / "frame.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-sseof",
                    "-0.2",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-y",
                    str(image),
                ],
                check=True,
                timeout=10,
                capture_output=True,
            )
            return image.read_bytes()

    async def image(self, input_id):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Device unloaded")
            job = asyncio.ensure_future(
                self.hass.async_add_executor_job(partial(self._capture, input_id))
            )
            try:
                return await asyncio.shield(job)
            except asyncio.CancelledError:
                # Executor threads cannot be cancelled. Keep the device lock
                # until the underlying socket/capture has actually finished.
                try:
                    await job
                except Exception:
                    pass
                raise
