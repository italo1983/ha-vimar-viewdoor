"""Demand-driven connection, idle teardown and reconnect lifecycle."""

import importlib.util
from pathlib import Path
import time
import threading

spec = importlib.util.spec_from_file_location(
    "viewdoor_relay", Path(__file__).parents[1] / "custom_components/vimar_viewdoor/relay.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Server:
    def __init__(self, **kwargs):
        assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 0
        self.client_count = 0
        self.url = "rtsp://127.0.0.1:1234/live"
        self.closed = False

    def start(self):
        pass

    def publish(self, _):
        pass

    def close(self):
        self.closed = True


class Session:
    def __init__(self):
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def recv_message(self, **_):
        self.closed.wait(0.01)
        raise TimeoutError

    def close(self):
        self.closed.set()


class Connector:
    def __init__(self):
        self.sessions = []

    def create_lan_session(self):
        session = Session()
        self.sessions.append(session)
        return session


class Assembler:
    def __init__(self, **_):
        pass

    def feed_message(self, _):
        pass


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_no_viewer_no_device_then_idle_and_restart():
    connector = Connector()
    relay = module.OnDemandRelay(
        connector,
        idle_seconds=0.05,
        retry_seconds=0.01,
        server_factory=Server,
        assembler_factory=Assembler,
    ).start()
    try:
        time.sleep(0.15)
        assert not connector.sessions
        relay.server.client_count = 1
        wait_for(lambda: len(connector.sessions) == 1)
        relay.server.client_count = 0
        wait_for(lambda: connector.sessions[0].closed.is_set())
        assert relay.url == "rtsp://127.0.0.1:1234/live"
        relay.server.client_count = 1
        wait_for(lambda: len(connector.sessions) == 2)
    finally:
        relay.close()
    assert all(s.closed.is_set() for s in connector.sessions)
    assert not relay._thread.is_alive()
    assert relay.server.closed


def test_close_interrupts_active_receiver():
    connector = Connector()
    relay = module.OnDemandRelay(
        connector, server_factory=Server, assembler_factory=Assembler
    ).start()
    relay.server.client_count = 1
    wait_for(lambda: bool(connector.sessions))
    relay.close()
    relay.close()
    assert connector.sessions[0].closed.is_set()
    assert not relay._thread.is_alive()


def test_pause_closes_viewer_and_prevents_reconnect_until_resumed():
    connector = Connector()
    relay = module.OnDemandRelay(
        connector, retry_seconds=0.01, server_factory=Server, assembler_factory=Assembler
    ).start()
    try:
        relay.server.client_count = 1
        wait_for(lambda: bool(connector.sessions))
        relay.pause()
        assert connector.sessions[0].closed.is_set()
        count = len(connector.sessions)
        time.sleep(0.15)
        assert len(connector.sessions) == count
        relay.resume()
        wait_for(lambda: len(connector.sessions) > count)
    finally:
        relay.close()
