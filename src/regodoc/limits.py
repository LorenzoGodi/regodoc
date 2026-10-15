"""Limiti di risorse applicati dal motore: tempo per comando e, su Linux, memoria.

Il motore li applica da sé (contratto, §2.3): il tempo con un timer del processo, la memoria
con il limite dello spazio d'indirizzi, che i processi figli, come pdflatex, ereditano. Al
termine del comando i limiti tornano com'erano, così il motore si può chiamare anche dentro
un altro processo Python, per esempio nelle prove.
"""

import contextlib
import signal
import sys
import threading
import time
from collections.abc import Iterator
from types import FrameType

from regodoc.declaration import RESOURCES

try:  # il modulo resource non esiste su Windows
    import resource
except ImportError:  # pragma: no cover - piattaforma non supportata
    resource = None  # type: ignore[assignment]


class TimeLimitExceeded(BaseException):
    """Il tempo massimo del comando è scaduto.

    Deriva da BaseException, come KeyboardInterrupt, perché nessun ``except Exception`` lo
    scambi per un errore del pacchetto o del motore.
    """

    def __init__(self, seconds: int) -> None:
        super().__init__(seconds)
        self.seconds = seconds


def time_limit(command: str | None, max_seconds: int | None) -> int | None:
    """Il tempo massimo del comando: quello dichiarato, abbassato da ``--max-seconds``."""
    declared = RESOURCES["time_seconds"].get(command) if command else None
    if declared is None:
        return None
    return min(declared, max_seconds) if max_seconds is not None else declared


def time_enforced() -> bool:
    """Vero dove il sistema ha il segnale e il timer che servono al tempo massimo (POSIX)."""
    return hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


def memory_enforced() -> bool:
    """Vero dove il motore applica da sé il limite di memoria."""
    return sys.platform in RESOURCES["memory_enforced_on"] and resource is not None


@contextlib.contextmanager
def applied(command: str | None, max_seconds: int | None) -> Iterator[dict[str, int | None]]:
    """Applica i limiti per la durata del comando e restituisce quelli davvero attivi.

    Il limite di memoria si abbassa soltanto: se chi chiama ne ha già impostato uno più
    basso, resta il suo, e ``memory_bytes`` riporta quello in vigore.
    """
    active: dict[str, int | None] = {"time_seconds": None, "memory_bytes": None}
    with contextlib.ExitStack() as stack:
        seconds = time_limit(command, max_seconds)
        main_thread = threading.current_thread() is threading.main_thread()
        if seconds is not None and main_thread and time_enforced():
            stack.enter_context(_alarm(seconds))
            active["time_seconds"] = seconds
        if command is not None and memory_enforced():
            active["memory_bytes"] = stack.enter_context(_address_space(RESOURCES["memory_bytes"]))
        yield active


# Stato del timer del comando: armato o no.
_TIMER = {"armed": False}


def disarm() -> None:
    """Ferma il timer del comando. Si chiama prima di scrivere il rapporto: un tempo che
    scade a metà scrittura lascerebbe su stdout un rapporto tronco seguito da un altro."""
    if _TIMER["armed"]:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _TIMER["armed"] = False


@contextlib.contextmanager
def _alarm(seconds: int) -> Iterator[None]:
    def expired(_signum: int, _frame: FrameType | None) -> None:
        raise TimeLimitExceeded(seconds)

    previous_handler = signal.signal(signal.SIGALRM, expired)
    started = time.monotonic()
    previous_delay, previous_interval = signal.setitimer(signal.ITIMER_REAL, seconds)
    _TIMER["armed"] = True
    try:
        yield
    finally:
        disarm()
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            # Il timer di chi chiama riparte con il tempo che gli restava.
            remaining = max(previous_delay - (time.monotonic() - started), 1e-6)
            signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)


@contextlib.contextmanager
def _address_space(limit: int) -> Iterator[int]:
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    applied_limit = limit
    if soft != resource.RLIM_INFINITY:
        applied_limit = min(limit, soft)
    if hard != resource.RLIM_INFINITY:
        applied_limit = min(applied_limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (applied_limit, hard))
    try:
        yield applied_limit
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
