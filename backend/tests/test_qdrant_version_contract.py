"""Keep the reviewed client/server pair and isolated-smoke boundaries explicit."""
from copy import deepcopy
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
import pytest
from qdrant_client import AsyncQdrantClient, QdrantClient


ROOT = Path(__file__).resolve().parents[2]


def qdrant_image(path):
    """Read the Qdrant image in our plain, two-space Compose service layout.

    Avoid making Docker or an undeclared YAML parser a unit-test dependency.
    Full Compose validation remains a separate configuration check.
    """
    in_services = False
    service = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_services = line == "services:"
            service = None
        elif in_services and indent == 2 and line.endswith(":"):
            service = line.strip()[:-1]
        elif in_services and service == "qdrant" and indent == 4 and line.strip().startswith("image:"):
            return line.strip().split(":", 1)[1].strip().strip("\"'")
    raise AssertionError(f"No Qdrant service image in {path.name}")


def test_qdrant_dependency_is_the_reviewed_exact_client_pin():
    requirements = []
    for line in (ROOT / "backend/requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            requirements.append(Requirement(line))
    matches = [item for item in requirements if item.name.lower().replace("_", "-") == "qdrant-client"]
    assert len(matches) == 1
    assert str(matches[0].specifier) == "==1.16.2"
    assert matches[0].url is None


def test_both_compose_stacks_pin_the_same_reviewed_server():
    images = [qdrant_image(ROOT / name) for name in ("docker-compose.dev.yml", "docker-compose.yml")]
    assert images == ["qdrant/qdrant:v1.16.3", "qdrant/qdrant:v1.16.3"]


@pytest.mark.parametrize("client", [QdrantClient, AsyncQdrantClient])
def test_sdk_constructor_retains_explicit_local_configuration(client):
    signature = inspect.signature(client)
    assert {"host", "port", "api_key", "timeout", "check_compatibility"} <= signature.parameters.keys()


@pytest.mark.parametrize("operation,keywords", [
    ("get_collections", set()),
    ("get_collection", {"collection_name"}),
    ("create_collection", {"collection_name", "vectors_config"}),
    ("create_payload_index", {"collection_name", "field_name", "field_schema", "wait"}),
    ("upsert", {"collection_name", "points", "wait"}),
    ("query_points", {"collection_name", "query", "query_filter", "limit", "with_payload", "score_threshold"}),
    ("delete", {"collection_name", "points_selector", "wait"}),
    ("count", {"collection_name", "count_filter"}),
    ("scroll", {"collection_name", "limit", "offset", "with_payload", "with_vectors"}),
    ("set_payload", {"collection_name", "payload", "points", "wait"}),
    ("retrieve", {"collection_name", "ids", "with_payload"}),
    ("delete_collection", {"collection_name"}),
    ("close", set()),
])
def test_async_sdk_retains_the_operations_and_keywords_used_by_the_app(operation, keywords):
    method = getattr(AsyncQdrantClient, operation)
    assert inspect.iscoroutinefunction(method)
    assert keywords <= inspect.signature(method).parameters.keys()


def smoke_module():
    path = ROOT / "backend/tests/manual_qdrant_smoke.py"
    spec = importlib.util.spec_from_file_location("isolated_qdrant_smoke_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke():
    return smoke_module()


@pytest.mark.parametrize("reference", [
    "qdrant/qdrant:v1.16.2", "qdrant/qdrant:v1.16.3", "qdrant/qdrant@sha256:" + "a" * 64,
])
def test_smoke_allows_only_reviewed_official_image_references(smoke, reference):
    assert smoke.validate_image_reference(reference) == reference


@pytest.mark.parametrize("reference", [
    "qdrant/qdrant:latest", "qdrant/qdrant", "qdrant/qdrant:v1.16", "qdrant/qdrant:v1.16.1",
    "qdrant/qdrant:v1.19.0", "another/image:v1.16.3", "registry.example/qdrant/qdrant:v1.16.3",
    "qdrant/qdrant@sha256:" + "a" * 63, "qdrant/qdrant@sha256:" + "g" * 64,
    "qdrant/qdrant:v1.16.3\n", " qdrant/qdrant:v1.16.3", "qdrant/qdrant:v1.16.3;anything",
])
def test_smoke_rejects_moving_unreviewed_or_malformed_image_references(smoke, reference):
    with pytest.raises(ValueError):
        smoke.validate_image_reference(reference)


def disposable_record(smoke):
    return {
        "Id": "a" * 64,
        "Name": "/clauseiq-qdrant-smoke-synthetic",
        "Config": {"Labels": {smoke.OWNERSHIP_LABEL: "synthetic-token"}},
        "HostConfig": {"Binds": None, "VolumesFrom": None, "Mounts": [],
                       "Tmpfs": {"/qdrant/storage": "", "/qdrant/snapshots": ""}},
        "Mounts": [{"Type": "tmpfs", "Destination": "/qdrant/storage"},
                   {"Type": "tmpfs", "Destination": "/qdrant/snapshots"}],
        "NetworkSettings": {"Ports": {"6333/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49152"}], "6334/tcp": None}},
    }


def inspect_disposable(smoke, record):
    return smoke.require_disposable_container(record, "a" * 64, "clauseiq-qdrant-smoke-synthetic", "synthetic-token")


def test_owned_smoke_container_has_an_isolated_nondefault_loopback_port(smoke):
    assert inspect_disposable(smoke, disposable_record(smoke)) == 49152


@pytest.mark.parametrize("path,value", [
    (("Id",), "b" * 64),
    (("Name",), "/clauseiq-qdrant-dev"),
    (("Config", "Labels"), {}),
    (("Config", "Labels"), {"clauseiq.disposable-vector-check": "another-invocation"}),
    (("HostConfig", "Binds"), ["existing-data:/qdrant/storage"]),
    (("HostConfig", "VolumesFrom"), ["existing-service"]),
    (("HostConfig", "Mounts"), [{"Type": "volume", "Source": "existing-data"}]),
    (("Mounts",), [{"Type": "bind", "Destination": "/qdrant/storage"}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/qdrant/storage"}]),
    (("HostConfig", "Tmpfs"), {}),
    (("HostConfig", "Tmpfs"), {"/qdrant/storage": ""}),
    (("NetworkSettings", "Ports", "6333/tcp"), []),
    (("NetworkSettings", "Ports", "6333/tcp"), None),
    (("NetworkSettings", "Ports", "6333/tcp"), [
        {"HostIp": "127.0.0.1", "HostPort": "49152"}, {"HostIp": "127.0.0.1", "HostPort": "49153"}]),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostIp"), "0.0.0.0"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostIp"), "::"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "1023"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "65536"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "6333"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "6334"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "3000"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "8000"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "27017"),
    (("NetworkSettings", "Ports", "6333/tcp", 0, "HostPort"), "not-a-port"),
    (("NetworkSettings", "Ports", "6334/tcp"), [{"HostIp": "127.0.0.1", "HostPort": "49153"}]),
])
def test_smoke_refuses_wrong_ownership_storage_or_network_boundaries(smoke, path, value):
    record = disposable_record(smoke)
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)
    with pytest.raises(ValueError):
        inspect_disposable(smoke, record)


def test_importing_the_manual_smoke_does_not_start_a_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Importing the manual smoke must not execute Docker or another process")

    monkeypatch.setattr(subprocess, "check_output", forbidden)
    module = smoke_module()
    assert callable(module.main)


def test_manual_smoke_default_invocation_is_inert_without_explicit_opt_in(smoke, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Default invocation must not touch Docker, databases or providers")

    monkeypatch.setattr(smoke, "docker", forbidden)
    monkeypatch.setattr(smoke, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["manual_qdrant_smoke.py"])
    smoke.main()
    result = json.loads(capsys.readouterr().out)
    assert result["event"] == "dry_run"
    assert result["client_version"] == "1.16.2"
    assert result["server_version"] == "1.16.3"
    assert result["image"] == "qdrant/qdrant:v1.16.3"
