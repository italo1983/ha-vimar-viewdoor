"""Instance-scoped adapter for the K42955 QUII input selector.

No APK assets, global monkey patches, cloud calls or actuator commands.
Private quii-helper attributes are intentionally confined to this module;
requirements must remain pinned until adapter compatibility is re-tested.
"""

from dataclasses import dataclass
import ipaddress
import time
import threading

from quii_helper import Camera
from quii_helper.camera.connection.session import CameraConnector
from quii_helper.protocols.quii.live_packets import (
    build_live_play_packet,
    build_live_play_packet_from_body,
)
from quii_helper.protocols.tcp.live.packet_builder import QuiiLiveOpenPacketBuilder
from quii_helper.protocols.tcp.live.session import LanTcpSession


def validate_credentials(host: str, device_id: str, stream_key: str, auth_code: str) -> None:
    """Reject URLs/public targets and malformed secrets before opening sockets."""
    address = ipaddress.ip_address(host)
    if (
        not address.is_private
        or address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or address.is_link_local
    ):
        raise ValueError("A private, unicast LAN address is required")
    if not device_id.strip() or len(stream_key.encode()) != 32:
        raise ValueError("Invalid device ID or stream key")
    if len(auth_code) != 64 or any(c not in "0123456789abcdefABCDEF" for c in auth_code):
        raise ValueError("Expected the 64-character cloud out-auth-code")


@dataclass
class VimarOpenPacketBuilder(QuiiLiveOpenPacketBuilder):
    """Header byte 13 selects the physical input; the path alone does not."""

    input_id: int = 1

    def build_live_open_packet(
        self, *, crypto_mode, play_param=1, stream_flag=0, timestamp_ms=None
    ):
        if self.input_id not in (1, 3):
            raise ValueError("Only the physically verified inputs 1 and 3 are supported")
        return build_live_play_packet(
            self.username,
            self.password,
            self.path,
            timestamp_ms=int(time.time()) if timestamp_ms is None else timestamp_ms,
            play_param=play_param,
            ext_len_low=self.input_id,
            stream_flag=stream_flag,
            inner=self.use_inner,
            crypto_mode=crypto_mode,
            sha_mode=1,
            key=self.key_bytes(crypto_mode) if crypto_mode else None,
            encrypt=crypto_mode != 0,
        )[2]


class VimarLanTcpSession(LanTcpSession):
    """Send the native stream teardown (type 7) before releasing its socket.

    Native CQUIIStreamBase::SendTeardown uses an empty body, zero play flags,
    SHA256 and the negotiated AES envelope. This ends only this video stream;
    it is not a global hang-up, an unlock or a device reset.
    """

    def __init__(self, *args, **kwargs):
        self._io_lock = threading.RLock()
        self._closing = threading.Event()
        self.teardown_sent = False
        self.teardown_error_type = None
        super().__init__(*args, **kwargs)

    def open(self):
        with self._io_lock:
            if self._closing.is_set():
                raise RuntimeError("Video session is stopping")
            return super().open()

    def recv_message(self, *, timeout=1.0):
        with self._io_lock:
            if self._closing.is_set():
                raise RuntimeError("Video session is stopping")
            # Closing waits only for this bounded in-flight receive, then owns I/O.
            return super().recv_message(timeout=min(timeout, 1.0))

    def _maybe_send_keepalive(self):
        with self._io_lock:
            if not self._closing.is_set() and not self._closed.is_set():
                super()._maybe_send_keepalive()

    def close(self):
        # Detach future reads/keepalives first, then wait for the active read.
        # RLock also supports base open/receive error paths calling close().
        self._closing.set()
        with self._io_lock:
            if self._closed.is_set():
                return
            try:
                if self._opened and self._client.crypto_mode == 2:
                    # Bound shutdown and serialize against keepalive. Never reconnect
                    # or retry a teardown; failures still release the local socket.
                    self._client.transport.set_timeout(1.0)
                    packet = build_live_play_packet_from_body(
                        b"", packet_type=7, play_param=0,
                        crypto_mode=2, sha_mode=1, key=self._key, encrypt=True,
                    )[2]
                    self._client.transport.send_all(packet)
                    self.teardown_sent = True
            except Exception as exc:
                self.teardown_error_type = type(exc).__name__
            finally:
                super().close()


class VimarConnector(CameraConnector):
    """Each connection receives its own builder, without changing the library."""

    def create_lan_session(self):
        session = VimarLanTcpSession(self.config)
        client = session._client
        client.live_open_builder = VimarOpenPacketBuilder(
            client.username,
            client.password,
            client.path,
            client.key,
            client.use_inner,
            input_id=self.config.channel,
        )
        return session


def make_camera(host, device_id, stream_key, auth_code, input_id, data_dir):
    validate_credentials(host, device_id, stream_key, auth_code)
    if input_id not in (1, 3):
        raise ValueError("Unsupported input")
    camera = Camera(
        connection_mode="lan",
        device_host=host,
        device_id=device_id,
        stream_key=stream_key,
        auth_code=auth_code,
        channel=input_id,
        stream=2,
        data_dir=data_dir,
        emit=lambda *_a, **_k: None,
        status=lambda *_a, **_k: None,
    )
    camera.connector = VimarConnector(camera.config)
    return camera
