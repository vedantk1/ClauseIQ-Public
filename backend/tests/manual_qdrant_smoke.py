"""Opt-in real Qdrant check using one owned, tmpfs-only disposable container.

Run from backend after installing dependencies and pulling the exact image:
    venv/bin/python tests/manual_qdrant_smoke.py --run-isolated-live

No application server, MongoDB, existing vector collection, credentials or paid
provider is used. Default invocation only describes the check. Docker must already
be running; this script never pulls images or starts the project's Compose stack.
"""
import argparse
import asyncio
import json
import re
import socket
import subprocess
import sys
import time
import uuid
import warnings
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
OWNERSHIP_LABEL = "clauseiq.disposable-vector-check"
SERVER_VERSIONS = ("1.16.2", "1.16.3")
EXPECTED_CLIENT_VERSION = "1.16.2"


def validate_image_reference(reference):
    """Never execute an arbitrary image or implicitly pull a moving tag."""
    if not re.fullmatch(r"qdrant/qdrant(?::v1\.16\.[23]|@sha256:[0-9a-f]{64})", reference):
        raise ValueError("Use an exact supported Qdrant tag or official-image digest")
    return reference


def require_disposable_container(record, expected_id, expected_name, token):
    """Refuse cleanup or testing unless exact ownership and isolation hold."""
    if (record.get("Id") != expected_id or record.get("Name") != f"/{expected_name}"
            or record.get("Config", {}).get("Labels", {}).get(OWNERSHIP_LABEL) != token):
        raise ValueError("Container ownership does not match this invocation")
    host = record.get("HostConfig", {})
    if host.get("Binds") or host.get("VolumesFrom"):
        raise ValueError("Disposable service cannot mount existing storage")
    mounts = record.get("Mounts", []) + host.get("Mounts", [])
    if any(mount.get("Type") != "tmpfs" for mount in mounts):
        raise ValueError("Disposable service must use tmpfs storage only")
    if not {"/qdrant/storage", "/qdrant/snapshots"} <= set(host.get("Tmpfs", {})):
        raise ValueError("Disposable storage and snapshots must be tmpfs")
    bindings = record.get("NetworkSettings", {}).get("Ports", {}).get("6333/tcp", [])
    if len(bindings or []) != 1 or bindings[0].get("HostIp") != "127.0.0.1":
        raise ValueError("Disposable service must have one loopback REST binding")
    port = int(bindings[0].get("HostPort", 0))
    if not 1024 <= port <= 65535 or port in {3000, 8000, 27017, 6333, 6334}:
        raise ValueError("Disposable service must use a separate nondefault port")
    if any(key != "6333/tcp" and value for key, value in record["NetworkSettings"]["Ports"].items()):
        raise ValueError("Unexpected additional published port")
    return port


def docker(*args, timeout=25):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT,
                                   timeout=timeout).strip()


def running_services():
    ids = docker("ps", "-q").splitlines()
    records = json.loads(docker("inspect", *ids)) if ids else []
    return {record["Id"]: {"started_at": record["State"]["StartedAt"],
                           "ports": record["NetworkSettings"]["Ports"]} for record in records}


def emit(event, **details):
    print(json.dumps({"event": event, **details}), flush=True)


async def exercise_service(port, collection):
    """Use the application's real service with synthetic embeddings only."""
    from unittest.mock import patch
    from config.environments import EnvironmentConfig
    from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
    from services import qdrant_vector_service as vector_module

    settings = EnvironmentConfig(_env_file=None, qdrant_host="127.0.0.1", qdrant_port=port,
                                 qdrant_collection=collection, qdrant_api_key=None)
    vector = [1.0] + [0.0] * 3071

    async def one_embedding(_text):
        return vector.copy()

    async def batch_embeddings(texts):
        return [vector.copy() for _ in texts]

    def forbid_provider():
        raise AssertionError("Provider access is forbidden in the isolated Qdrant check")

    with patch.object(vector_module, "get_environment_config", return_value=settings):
        service = vector_module.QdrantVectorService()
    service._get_openai_client = forbid_provider
    service._generate_embedding = one_embedding
    service._generate_embeddings_batch = batch_embeddings
    try:
        assert await service.initialize(), "Real service initialization failed"
        assert service.embedding_dimension == 3072
        assert service.client.get_collection(collection).points_count == 0
        schema = (await service.async_client.get_collection(collection)).payload_schema
        assert {"workspace_id", "document_id"} <= schema.keys()
        cases = [("document-a", "workspace-a", 2), ("document-b", "workspace-a", 1),
                 ("document-a", "workspace-b", 1)]
        for document, workspace, count in cases:
            result = await service.store_document_chunks(document, workspace, [
                {"text": f"Synthetic chunk {index}",
                 "metadata": {"workspace_id": "must-not-override", "document_id": "must-not-override"}}
                for index in range(count)
            ])
            assert result["success"] is True and result["chunk_count"] == count
        assert await service.get_document_chunk_count("document-a", "workspace-a") == 2
        assert await service.get_document_chunk_count("document-b", "workspace-a") == 1
        assert await service.get_document_chunk_count("document-a", "workspace-b") == 1
        own = await service.search_similar_chunks("Synthetic query", "workspace-a", "document-a", k=10)
        assert len(own) == 2 and all(result["document_id"] == "document-a" for result in own)
        assert all(result["metadata"]["workspace_id"] == "workspace-a" for result in own)
        assert all(result["similarity_score"] > 0.99 for result in own)
        workspace_results = await service.search_similar_chunks("Synthetic query", "workspace-a", k=10)
        assert len(workspace_results) == 3
        emit("service_crud_and_scope_passed", synthetic_dimensions=3072, stored=4, scoped_query_count=2)

        # Exercise the SDK shapes used by migration without running migration on
        # any database: preserve legacy metadata and add a workspace marker.
        legacy_id = str(uuid.uuid4())
        await service.async_client.upsert(collection_name=collection, wait=True, points=[PointStruct(
            id=legacy_id, vector=vector,
            payload={"user_id": "synthetic-legacy-owner", "document_id": "legacy-document"},
        )])
        points = []
        offset = None
        page_count = 0
        while True:
            page, offset = await service.async_client.scroll(
                collection_name=collection, limit=2, offset=offset,
                with_payload=["user_id", "workspace_id"], with_vectors=False,
            )
            page_count += 1
            points.extend(page)
            assert page_count <= 3, "Unexpected repeated pagination or extra points"
            if offset is None:
                break
        assert len(points) == 5 and len({point.id for point in points}) == 5 and page_count == 3
        assert next(point for point in points if point.id == legacy_id).payload == {"user_id": "synthetic-legacy-owner"}
        await service.async_client.set_payload(collection_name=collection, payload={"workspace_id": "workspace-legacy"},
                                               points=[legacy_id], wait=True)
        await service.async_client.create_payload_index(collection_name=collection, field_name="workspace_id",
                                                        field_schema="keyword", wait=True)
        migrated, _ = await service.async_client.scroll(collection_name=collection, limit=10,
            scroll_filter=Filter(must=[FieldCondition(key="workspace_id", match=MatchValue(value="workspace-legacy"))]),
            with_payload=True, with_vectors=False)
        assert len(migrated) == 1 and migrated[0].id == legacy_id
        assert migrated[0].payload["user_id"] == "synthetic-legacy-owner"
        emit("migration_sdk_shapes_passed", preserved_legacy_metadata=True, scroll_pages=page_count)

        assert (await service.delete_document_chunks("document-a", "workspace-a"))["success"] is True
        assert await service.get_document_chunk_count("document-a", "workspace-a") == 0
        assert await service.get_document_chunk_count("document-b", "workspace-a") == 1
        assert await service.get_document_chunk_count("document-a", "workspace-b") == 1
        assert await service.get_document_chunk_count("legacy-document", "workspace-legacy") == 1
        assert service.client.count(collection, exact=True).count == 3
        assert await service.search_similar_chunks("Synthetic query", "workspace-a", "document-a") == []
        emit("scoped_deletion_passed", unrelated_synthetic_points_preserved=3)
    finally:
        if service.async_client:
            await service.async_client.close()
        if service.client:
            service.client.close()


def run(server_version, image):
    import httpx
    from importlib.metadata import version
    assert version("qdrant-client") == EXPECTED_CLIENT_VERSION, "Install the pinned candidate client first"
    image = validate_image_reference(image)
    # An explicit cache prerequisite: Docker run must never pull implicitly.
    docker("image", "inspect", image)
    baseline_services = running_services()
    baseline_volumes = set(docker("volume", "ls", "-q").splitlines())
    token = uuid.uuid4().hex
    name = f"clauseiq-qdrant-smoke-{token[:12]}"
    assert not docker("ps", "-aq", "--filter", f"name=^/{name}$")
    container_id = None
    port = None
    try:
        container_id = docker("run", "--pull=never", "--rm", "-d", "--name", name,
            "--label", f"{OWNERSHIP_LABEL}={token}", "--tmpfs", "/qdrant/storage", "--tmpfs", "/qdrant/snapshots",
            "-p", "127.0.0.1::6333", "-e", "QDRANT__TELEMETRY_DISABLED=true", image)
        record = json.loads(docker("inspect", container_id))[0]
        port = require_disposable_container(record, container_id, name, token)
        deadline = time.monotonic() + 20
        with httpx.Client(timeout=2, trust_env=False) as client:
            while True:
                try:
                    response = client.get(f"http://127.0.0.1:{port}/")
                    response.raise_for_status()
                    assert response.json()["version"] == server_version, "Container version differs from requested check"
                    response = client.get(f"http://127.0.0.1:{port}/collections")
                    response.raise_for_status()
                    assert response.json()["result"]["collections"] == []
                    break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Disposable Qdrant did not become ready within 20 seconds") from None
                    time.sleep(0.25)
        emit("empty_server_ready", server_version=server_version, client_version=EXPECTED_CLIENT_VERSION)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            asyncio.run(asyncio.wait_for(exercise_service(port, f"smoke-{token}"), timeout=45))
        assert not any("compatib" in str(item.message).lower() or "server version" in str(item.message).lower()
                       for item in captured), "SDK reported version or compatibility uncertainty"
        emit("compatibility_passed", server_version=server_version, compatibility_checks_enabled=True)
    finally:
        if container_id and docker("ps", "-aq", "--filter", f"id={container_id}"):
            record = json.loads(docker("inspect", container_id))[0]
            require_disposable_container(record, container_id, name, token)
            docker("stop", "--time", "10", container_id)
        assert not docker("ps", "-aq", "--filter", f"label={OWNERSHIP_LABEL}={token}")
        assert set(docker("volume", "ls", "-q").splitlines()) == baseline_volumes
        services = running_services()
        assert all(services.get(identity) == state for identity, state in baseline_services.items())
        if port is not None:
            with socket.socket() as connection:
                assert connection.connect_ex(("127.0.0.1", port)) != 0
        emit("cleanup_passed", disposable_containers_remaining=0, extra_volumes=0, existing_services_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-live", action="store_true")
    parser.add_argument("--server-version", choices=SERVER_VERSIONS, default="1.16.3")
    parser.add_argument("--image", help="Optional exact official image digest already cached locally")
    args = parser.parse_args()
    image = validate_image_reference(args.image or f"qdrant/qdrant:v{args.server_version}")
    if not args.run_isolated_live:
        emit("dry_run", server_version=args.server_version, client_version=EXPECTED_CLIENT_VERSION,
             image=image, action="Explicit opt-in required; no Docker, database or provider access")
        return
    sys.path.insert(0, str(BACKEND))
    run(args.server_version, image)


if __name__ == "__main__":
    main()
