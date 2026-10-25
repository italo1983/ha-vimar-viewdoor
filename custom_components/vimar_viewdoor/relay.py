"""Loopback RTSP relay: a camera connection exists only while clients need it."""

import threading
import time

from quii_helper.streaming.h264 import H264LiveAssembler
from quii_helper.streaming.rtsp import RtspH264Server


class OnDemandRelay:
    """Stable local URL with demand-driven, reconnecting producer.

    The listener is loopback-only. Local HA stream workers connect to it; HA
    provides authentication for browser delivery. A listener without clients
    never opens the intercom. A dropped producer retries only with viewers.
    """

    def __init__(
        self,
        connector,
        *,
        idle_seconds=5.0,
        retry_seconds=3.0,
        server_factory=RtspH264Server,
        assembler_factory=H264LiveAssembler,
    ):
        self.connector = connector
        self.idle_seconds = idle_seconds
        self.retry_seconds = retry_seconds
        self.server = server_factory(host="127.0.0.1", port=0, path="/live")
        self._assembler_factory = assembler_factory
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._lock = threading.Lock()
        self._session = None
        self._thread = None
        self.access_units = 0
        self.messages = {}
        self.last_error_type = None

    @property
    def url(self):
        return self.server.url

    @property
    def connected(self):
        with self._lock:
            return self._session is not None

    def start(self):
        if self._stop.is_set():
            raise RuntimeError("Relay closed")
        self.server.start()
        self._thread = threading.Thread(target=self._run, name="vimar-video-relay", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self.server.close()
            raise
        return self

    def _run(self):
        while not self._stop.is_set():
            if self._paused.is_set() or not self.server.client_count:
                self._stop.wait(0.1)
                continue
            try:
                session = self.connector.create_lan_session()
                with self._lock:
                    if self._stop.is_set() or self._paused.is_set():
                        session.close()
                        continue
                    self._session = session
                assembler = self._assembler_factory(
                    sink=self.server.publish, wait_for_keyframe=True
                )
                with session:
                    last_media = last_viewer = time.monotonic()
                    while not self._stop.is_set() and not self._paused.is_set():
                        if self.server.client_count:
                            last_viewer = time.monotonic()
                        elif time.monotonic() - last_viewer >= self.idle_seconds:
                            break
                        if time.monotonic() - last_media > 12:
                            raise ConnectionError("Video source stalled")
                        try:
                            decoded = session.recv_message(timeout=1.0)
                        except TimeoutError:
                            continue
                        if decoded.get("is_media"):
                            last_media = time.monotonic()
                        packet_type = decoded["header"].packet_type
                        self.messages[packet_type] = self.messages.get(packet_type, 0) + 1
                        assembler.feed_message(decoded)
                        self.access_units = assembler.access_unit_count
            except Exception as exc:
                self.last_error_type = type(exc).__name__
                # Never log a vendor exception: it may contain keys or UID.
                self._stop.wait(self.retry_seconds)
            finally:
                with self._lock:
                    session, self._session = self._session, None
                if session is not None:
                    session.close()

    def pause(self):
        """Release an existing viewer session before an explicit gate workflow."""
        self._paused.set()
        with self._lock:
            session = self._session
        if session is not None:
            session.close()

    def resume(self):
        self._paused.clear()

    def close(self):
        self._stop.set()
        with self._lock:
            session = self._session
        if session is not None:
            session.close()
        self.server.close()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError("Video producer did not stop")
