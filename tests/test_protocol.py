"""Test actual protocol encryption/input selection without HA or a device."""

import importlib.util
from pathlib import Path
import sys
import pytest
from quii_helper.protocols.quii.crypto import aes_cbc_crypt

path = Path(__file__).parents[1] / "custom_components/vimar_viewdoor/protocol.py"
spec = importlib.util.spec_from_file_location("viewdoor_protocol", path)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


@pytest.mark.parametrize("input_id", [1, 3])
def test_encrypted_header_selects_physical_input(input_id):
    key = "a" * 32
    builder = protocol.VimarOpenPacketBuilder(
        "adminapp2", "b" * 64, "/mode=real", key, input_id=input_id
    )
    packet = builder.build_live_open_packet(crypto_mode=2, timestamp_ms=1000)
    header = aes_cbc_crypt(packet[:32], key.encode(), crypto_mode=2, decrypt=True)
    assert header[0] == 1  # Live play, never an actuator/transparent command.
    assert header[13] == input_id
    assert int.from_bytes(header[1:9], "little") == 1000


def test_independent_builders_do_not_change_global_default():
    from quii_helper.protocols.tcp.live.packet_builder import QuiiLiveOpenPacketBuilder

    first = protocol.VimarOpenPacketBuilder("u", "p", "/", "a" * 32, input_id=1)
    third = protocol.VimarOpenPacketBuilder("u", "p", "/", "a" * 32, input_id=3)
    assert first.input_id == 1 and third.input_id == 3
    assert (
        QuiiLiveOpenPacketBuilder.build_live_open_packet
        is not protocol.VimarOpenPacketBuilder.build_live_open_packet
    )


@pytest.mark.parametrize(
    "host", ["https://example.com", "8.8.8.8", "0.0.0.0", "127.0.0.1", "224.0.0.1"]
)
def test_invalid_targets_rejected(host):
    with pytest.raises(ValueError):
        protocol.validate_credentials(host, "test-device", "a" * 32, "b" * 64)


def test_secrets_validated_by_encoded_length():
    with pytest.raises(ValueError):
        protocol.validate_credentials("192.168.1.50", "test-device", "é" * 32, "b" * 64)
    protocol.validate_credentials("192.168.1.50", "test-device", "a" * 32, "b" * 64)


def test_unknown_input_rejected_before_network():
    with pytest.raises(ValueError):
        protocol.make_camera("192.168.1.50", "device", "a" * 32, "b" * 64, 2, "/tmp")


class FakeTransport:
    def __init__(self, host, port):
        self.sent = []
        self.closed = 0
        self.fail_send = False

    def set_timeout(self, value):
        assert value == 1.0

    def send_all(self, packet):
        if self.fail_send:
            raise OSError('secret-not-for-logs')
        self.sent.append(packet)

    def close(self):
        self.closed += 1


def closing_session():
    camera = protocol.make_camera('192.168.1.50', 'device', 'a' * 32, 'b' * 64, 1, '/tmp')
    session = protocol.VimarLanTcpSession(camera.config, transport_factory=FakeTransport)
    session._opened = True
    session._client.crypto_mode = 2
    return session, session._client.transport


def test_close_sends_native_teardown_once_then_closes():
    import hashlib
    session, transport = closing_session()
    session.close()
    session.close()
    assert len(transport.sent) == 1 and transport.closed == 1
    packet = transport.sent[0]
    header = aes_cbc_crypt(packet[:32], b'a' * 32, crypto_mode=2, decrypt=True)
    body = aes_cbc_crypt(packet[32:], b'a' * 32, crypto_mode=2, decrypt=True)
    assert header[0] == 7
    assert header[11:] == bytes(21)  # empty body, no selector/unlock/play flags
    assert body == hashlib.sha256(header).digest()
    assert session.teardown_sent and session._closed.is_set()


def test_close_without_open_never_sends():
    session, transport = closing_session()
    session._opened = False
    session.close()
    assert transport.sent == [] and transport.closed == 1


def test_failed_teardown_still_closes_without_retry_or_secret():
    session, transport = closing_session()
    transport.fail_send = True
    session.close()
    session.close()
    assert transport.closed == 1
    assert session.teardown_error_type == 'OSError'
    assert not session.teardown_sent


def test_concurrent_close_sends_only_once():
    from concurrent.futures import ThreadPoolExecutor
    session, transport = closing_session()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: session.close(), range(8)))
    assert len(transport.sent) == 1 and transport.closed == 1


def test_shutdown_waits_for_reader_before_teardown(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    session, transport = closing_session()
    entered, finish_read = threading.Event(), threading.Event()
    order = []

    def receive(self, *, timeout):
        assert timeout <= 1
        order.append('read-start')
        entered.set()
        assert finish_read.wait(2)
        order.append('read-end')
        return {}

    def send(packet):
        order.append('teardown')
        transport.sent.append(packet)

    monkeypatch.setattr(protocol.LanTcpSession, 'recv_message', receive)
    transport.send_all = send
    with ThreadPoolExecutor(2) as pool:
        reading = pool.submit(session.recv_message)
        assert entered.wait(1)
        closing = pool.submit(session.close)
        try:
            assert session._closing.wait(1)
            assert transport.sent == []
            assert not closing.done()
        finally:
            finish_read.set()
        reading.result(timeout=2)
        closing.result(timeout=2)
    assert order == ['read-start', 'read-end', 'teardown']
    with pytest.raises(RuntimeError, match='stopping'):
        session.recv_message()
    session._maybe_send_keepalive()
    assert len(transport.sent) == 1


def test_receive_failure_can_close_reentrantly(monkeypatch):
    session, transport = closing_session()

    def failure(self, *, timeout):
        self.close()
        raise RuntimeError('receive failed')

    monkeypatch.setattr(protocol.LanTcpSession, 'recv_message', failure)
    with pytest.raises(RuntimeError, match='receive failed'):
        session.recv_message()
    assert len(transport.sent) == 1 and transport.closed == 1
