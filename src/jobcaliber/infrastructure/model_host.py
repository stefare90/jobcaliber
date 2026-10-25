"""Bring the machine that serves an engine up and down, from the controller side.

The controller owns the policy and the host only exposes three elementary commands (start, stop,
power off): the rule is *leave the host as you found it*. To apply that rule the controller has to
know whether the machine was already up, which is why `address` is required whenever it may wake or
power it off.
"""
from __future__ import annotations

import socket
import subprocess
import time
from typing import Callable

from jobcaliber.core.config import ModelHost, WakeOnLan

COMMAND_TIMEOUT_S = 60
POLL_INTERVAL_S = 2
MAGIC_PACKET_PORT = 9


class ModelHostUnreachable(RuntimeError):
    """The host or its engine did not come up: retrying cannot help."""


def magic_packet(mac: str) -> bytes:
    """Six 0xFF bytes followed by the MAC repeated sixteen times (the WoL payload)."""
    clean = mac.replace(":", "").replace("-", "").strip()
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def tcp_open(address: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def send_magic_packet(wake: WakeOnLan, times: int = 3) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = magic_packet(wake.mac)
        for _ in range(times):
            sock.sendto(payload, (wake.broadcast, MAGIC_PACKET_PORT))
    finally:
        sock.close()


def run_command(command: str) -> int:
    done = subprocess.run(command, shell=True, capture_output=True, text=True,
                          timeout=COMMAND_TIMEOUT_S)
    return done.returncode


class ModelHostController:
    def __init__(self, config: ModelHost, probe: Callable[[], None], *,
                 sleep: Callable[[float], None] = time.sleep,
                 run: Callable[[str], int] | None = None,
                 probe_host: Callable[[], bool] | None = None,
                 send: Callable[[WakeOnLan], None] | None = None,
                 progress: Callable[..., None] = print):
        self.config = config
        self.probe = probe                      # the engine answers?
        self.sleep = sleep
        self.run = run or run_command
        self.send = send or send_magic_packet
        self.progress = progress
        self._probe_host = probe_host
        self.host_was_on = False
        self.started_engine = False

    @property
    def was_woken(self) -> bool:
        return not self.host_was_on

    def ensure_ready(self) -> None:
        """Make the engine answer, waking the host only if it is down."""
        if self._engine_up():
            self.host_was_on = True
            return
        if self._host_up():
            self.host_was_on = True
            self.progress("model host: machine already on, starting the engine")
        elif self.config.wake_on_lan is not None:
            self.progress(f"model host: waking {self.config.address}")
            self.send(self.config.wake_on_lan)

        wake = self.config.wake_on_lan
        deadline = wake.wait_s if wake is not None else 150
        waited = 0
        while True:
            if self._host_up():
                self._try_start()
            if self._engine_up():
                self.progress(f"model host: engine ready after about {waited}s")
                return
            if waited >= deadline:
                raise ModelHostUnreachable(
                    f"model host did not answer within {deadline}s: check the wake command and "
                    f"the engine on {self.config.address}"
                )
            self.sleep(POLL_INTERVAL_S)
            waited += POLL_INTERVAL_S

    def release(self) -> None:
        """Undo what we did, best effort: a failure here never fails the run."""
        if self.host_was_on:
            if self.started_engine and self.config.stop_command:
                self.progress("model host: stopping the engine (the machine stays on)")
                self._best_effort(self.config.stop_command, "stop the engine")
            return
        if self.config.poweroff_command:
            self.progress("model host: powering the machine off")
            self._best_effort(self.config.poweroff_command, "power the machine off")

    def _try_start(self) -> None:
        if self.started_engine or not self.config.start_command:
            return
        self.started_engine = self.run(self.config.start_command) == 0
        if self.started_engine:
            self.progress("model host: engine start requested")

    def _engine_up(self) -> bool:
        try:
            self.probe()
            return True
        except Exception:
            return False

    def _host_up(self) -> bool:
        if not self.config.address:
            return False
        if self._probe_host is not None:
            return self._probe_host()
        return tcp_open(self.config.address, self.config.ssh_port)

    def _best_effort(self, command: str, what: str) -> None:
        try:
            if self.run(command) != 0:
                self.progress(f"model host: could not {what} (command exited non-zero)")
        except Exception as error:
            self.progress(f"model host: could not {what} ({type(error).__name__}: {error})")
