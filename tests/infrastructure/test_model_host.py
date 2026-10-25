"""The controller side of the model host: wake it, start the engine, undo what it did."""
import pytest

from jobcaliber.core.config import ModelHost, WakeOnLan
from jobcaliber.infrastructure.model_host import (
    ModelHostController,
    ModelHostUnreachable,
    magic_packet,
)

WAKE = WakeOnLan(mac="34:5a:60:a2:87:9c", broadcast="10.10.0.255", wait_s=20)
HOST = ModelHost(address="10.10.0.2", wake_on_lan=WAKE, start_command="ssh start",
                 stop_command="ssh stop", poweroff_command="ssh poweroff")


def test_the_magic_packet_is_six_ff_bytes_and_the_mac_sixteen_times():
    packet = magic_packet("34:5A:60:A2:87:9C")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("345a60a2879c") * 16


class Script:
    """A sequence of booleans for the probes, consumed one call at a time (last one repeats)."""

    def __init__(self, answers):
        self.answers = list(answers)

    def __call__(self):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Engine(Script):
    def __call__(self):
        up = super().__call__()
        if not up:
            raise ConnectionError("engine down")
        return True


class Commands:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.seen = []

    def __call__(self, command):
        self.seen.append(command)
        return self.results.pop(0) if self.results else 0


def build(engine_answers, host_answers, results=None):
    commands, packets = Commands(results), []
    host = ModelHostController(
        HOST, Engine(engine_answers),
        sleep=lambda _: None, run=commands, probe_host=Script(host_answers),
        send=lambda wake: packets.append(wake), progress=lambda *_: None,
    )
    return host, commands, packets


def test_an_engine_that_already_answers_is_left_alone():
    host, commands, packets = build([True], [True])
    host.ensure_ready()
    host.release()
    assert host.was_woken is False
    assert packets == [] and commands.seen == []


def test_a_powered_off_host_is_woken_and_powered_off_again():
    host, commands, packets = build([False, False, True], [False, False, True])
    host.ensure_ready()
    assert packets, "the magic packet must be sent"
    assert "ssh start" in commands.seen
    assert host.was_woken is True

    commands.seen.clear()
    host.release()
    assert commands.seen == ["ssh poweroff"]


def test_a_host_that_is_on_with_the_engine_down_is_started_and_stopped():
    host, commands, packets = build([False, False, True], [True])
    host.ensure_ready()
    assert packets == [], "no wake for a machine that is already up"
    assert host.was_woken is False
    assert "ssh start" in commands.seen

    commands.seen.clear()
    host.release()
    assert commands.seen == ["ssh stop"]        # the machine stays on


def test_a_host_that_never_answers_raises_and_does_not_pretend():
    host, commands, packets = build([False], [False])
    with pytest.raises(ModelHostUnreachable, match="did not answer within"):
        host.ensure_ready()


def test_a_failing_release_command_never_raises():
    host, commands, _ = build([False, False, True], [False, False, True], results=[0, 0, 1])
    host.ensure_ready()
    host.release()                              # must not raise
    assert commands.seen[-1] == "ssh poweroff"


def test_a_host_configuration_without_power_needs_no_address():
    only_engine = ModelHost(start_command="ssh start", stop_command="ssh stop")
    assert only_engine.address is None
