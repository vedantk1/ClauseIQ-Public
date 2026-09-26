"""Offline checks for the browser harness's destructive-operation boundary."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import signal
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "realstack_smoke", Path(__file__).resolve().parents[2] / "scripts/run_realstack_smoke.py",
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def owned(service="mongo"):
    port = "27017/tcp" if service == "mongo" else "6333/tcp"
    storage = ("/data/db", "/data/configdb") if service == "mongo" else ("/qdrant/storage", "/qdrant/snapshots")
    return {
        "Id": "owned-id", "Name": "/owned-name",
        "Config": {"Image": smoke.IMAGES[service], "Labels": {smoke.LABEL: "owned-token"}},
        "HostConfig": {"AutoRemove": True, "Tmpfs": dict.fromkeys(storage, "")},
        "Mounts": [{"Type": "tmpfs", "Destination": path} for path in storage],
        "NetworkSettings": {"Ports": {port: [{"HostIp": "127.0.0.1", "HostPort": "49100"}]}},
    }


@pytest.mark.parametrize("service", ["mongo", "qdrant"])
def test_only_exact_owned_tmpfs_loopback_service_is_accepted(service):
    assert smoke.require_owned(owned(service), "owned-id", "owned-name", "owned-token", service) == 49100


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(Id="other-id"),
    lambda value: value.update(Name="/other-name"),
    lambda value: value["Config"].update(Labels={}),
    lambda value: value["Config"].update(Image="mongo:latest"),
    lambda value: value["HostConfig"].update(Binds=["existing-volume:/data/db"]),
    lambda value: value["HostConfig"].update(AutoRemove=False),
    lambda value: value["HostConfig"].update(Tmpfs={}),
    lambda value: value.update(Mounts=[{"Type": "volume"}]),
    lambda value: value["NetworkSettings"]["Ports"]["27017/tcp"][0].update(HostIp="0.0.0.0"),
    lambda value: value["NetworkSettings"]["Ports"]["27017/tcp"][0].update(HostPort="27017"),
    lambda value: value["NetworkSettings"]["Ports"].update({"6334/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49101"}]}),
])
def test_cleanup_refuses_ambiguous_or_nonisolated_container(mutation):
    value = deepcopy(owned())
    mutation(value)
    with pytest.raises(RuntimeError):
        smoke.require_owned(value, "owned-id", "owned-name", "owned-token", "mongo")


def test_child_environment_does_not_inherit_application_or_provider_settings(monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "existing-workspace")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    monkeypatch.setenv("HTTPS_PROXY", "https://invalid.example")
    environment = smoke.clean_environment()
    assert not {"MONGODB_DATABASE", "OPENAI_API_KEY", "HTTPS_PROXY"} & environment.keys()


@pytest.mark.parametrize("outcome", ["success", "timeout", "interrupted"])
def test_browser_runner_owns_and_cleans_only_its_spawned_process_group(monkeypatch, outcome):
    if smoke.os.name != "posix":
        pytest.skip("POSIX process-group boundary")
    events = []

    class Process:
        pid = 12345

        def wait(self, timeout):
            if timeout == 360 and outcome == "timeout":
                raise subprocess.TimeoutExpired("synthetic-browser", timeout)
            if timeout == 360 and outcome == "interrupted":
                raise KeyboardInterrupt
            return 0

        def poll(self):
            return 0

    def spawn(command, **kwargs):
        assert command[:2] == ["npx", "--no-install"]
        assert kwargs["start_new_session"] is True
        return Process()

    def kill_group(identity, operation):
        events.append((identity, operation))
        if operation == 0:
            raise ProcessLookupError

    monkeypatch.setattr(smoke.subprocess, "Popen", spawn)
    monkeypatch.setattr(smoke.os, "killpg", kill_group)
    if outcome == "success":
        assert smoke.run_browser() == 0
    else:
        with pytest.raises(subprocess.TimeoutExpired if outcome == "timeout" else KeyboardInterrupt):
            smoke.run_browser()
    assert events == [(12345, signal.SIGTERM), (12345, 0)]


def test_stubborn_browser_descendants_receive_bounded_group_cleanup(monkeypatch):
    if smoke.os.name != "posix":
        pytest.skip("POSIX process-group boundary")
    events = []
    process = type("Process", (), {"pid": 23456, "wait": lambda self, **_: 0, "poll": lambda self: 0})()
    monkeypatch.setattr(smoke.subprocess, "Popen", lambda *_, **__: process)
    monkeypatch.setattr(smoke.os, "killpg", lambda identity, operation: events.append((identity, operation)))
    ticks = iter([0, 6])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks))
    assert smoke.run_browser() == 0
    assert events == [(23456, signal.SIGTERM), (23456, 0), (23456, signal.SIGKILL)]


def test_disposable_container_removal_waits_for_docker_auto_remove(monkeypatch):
    responses = iter(["owned-id", "owned-id", ""])
    calls = []
    monkeypatch.setattr(smoke, "docker", lambda *args: calls.append(args) or next(responses))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    smoke.wait_for_owned_removal("owned-token")
    assert calls == [("ps", "-aq", "--filter", f"label={smoke.LABEL}=owned-token")] * 3


def test_disposable_container_removal_still_fails_after_deadline(monkeypatch):
    monkeypatch.setattr(smoke, "docker", lambda *_: "owned-id")
    ticks = iter([0, 11])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="cleanup was unsuccessful"):
        smoke.wait_for_owned_removal("owned-token", timeout=10)
