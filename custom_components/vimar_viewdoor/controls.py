"""Explicit single-attempt gate commands; never called during setup or probes."""

from dataclasses import dataclass
import threading
import time

from quii_helper.device.control import request_open_door
from quii_helper.streaming.h264 import H264LiveAssembler


class GateCommandError(Exception):
    """Safe to display: deliberately excludes vendor errors and credentials."""


@dataclass(frozen=True)
class GateTarget:
    key: str
    lock_number: int


class GateController:
    """Serialize both relays and suppress duplicate opening attempts.

    A network failure means the outcome is unknown. Never retry an opening,
    including when the other configured method could plausibly work.
    """

    def __init__(
        self, host, auth_code, *, cooldown=10.0, sender=request_open_door, clock=time.monotonic
    ):
        self.host = host
        self.auth_code = auth_code
        self.cooldown = cooldown
        self._sender = sender
        self._clock = clock
        self._lock = threading.Lock()
        self._last_attempt = None

    def press(self, target, *, password=None, password_mode="sha256"):
        if isinstance(target.lock_number, bool) or target.lock_number not in (1, 2):
            raise GateCommandError("Uscita non valida: nessun comando inviato.")
        if password_mode not in ("sha256", "plain"):
            raise GateCommandError("Modalità password non valida: nessun comando inviato.")
        if not self._lock.acquire(blocking=False):
            raise GateCommandError("Un comando è già in corso. Attendi e verifica il cancello.")
        try:
            now = self._clock()
            if self._last_attempt is not None and now - self._last_attempt < self.cooldown:
                raise GateCommandError(
                    "Attendi almeno 10 secondi e verifica il cancello prima di riprovare."
                )
            # Includes failed/unknown attempts: do not allow immediate duplicate actuation.
            self._last_attempt = now
            try:
                result = self._sender(
                    host=self.host,
                    auth_code=self.auth_code,
                    unlock_password=password or self.auth_code,
                    channel=1,
                    lock_number=target.lock_number,
                    password_mode=password_mode,
                    debug=False,
                )
            except Exception:
                raise GateCommandError(
                    "Nessuna conferma dal citofono: l'apertura potrebbe essere avvenuta. "
                    "Verifica fisicamente; il comando non è stato ripetuto."
                ) from None
            if not result.accepted:
                raise GateCommandError(
                    "Il citofono ha rifiutato il comando. Nessun tentativo automatico aggiuntivo."
                )
            # Acknowledgement confirms acceptance only, not movement or open state.
            return None
        finally:
            self._lock.release()


class VideoGateController:
    """Own one video session around exactly one explicit opening attempt."""

    def __init__(self, controller, session_factory, *, clock=time.monotonic,
                 ready_seconds=8.0, settle_seconds=3.0, assembler_factory=H264LiveAssembler):
        self.controller = controller
        self.session_factory = session_factory
        self.clock = clock
        self.ready_seconds = ready_seconds
        self.settle_seconds = settle_seconds
        self.assembler_factory = assembler_factory

    def press(self, target, *, password=None, password_mode="sha256", cancelled=None):
        session = None
        attempted = False
        try:
            session = self.session_factory()
            session.open()
            deadline = self.clock() + self.ready_seconds
            assembler = self.assembler_factory(wait_for_keyframe=True)
            while self.clock() < deadline:
                if cancelled is not None and cancelled.is_set():
                    raise GateCommandError("Richiesta annullata: nessuna apertura inviata.")
                try:
                    message = session.recv_message(timeout=1.0)
                except TimeoutError:
                    continue
                assembler.feed_message(message)
                if session.play_accepted and assembler.access_unit_count >= 3:
                    break
            else:
                raise GateCommandError("Video non pronto: nessuna apertura inviata.")
            if cancelled is not None and cancelled.is_set():
                raise GateCommandError("Richiesta annullata: nessuna apertura inviata.")
            attempted = True
            self.controller.press(target, password=password, password_mode=password_mode)
            deadline = self.clock() + self.settle_seconds
            while self.clock() < deadline:
                try:
                    session.recv_message(timeout=1.0)
                except TimeoutError:
                    pass
        except GateCommandError:
            raise
        except Exception:
            if attempted:
                raise GateCommandError(
                    "Errore dopo l'invio: verifica il cancello. Nessun comando ripetuto."
                ) from None
            raise GateCommandError("Connessione video fallita: nessuna apertura inviata.") from None
        finally:
            if session is not None:
                session.close()
