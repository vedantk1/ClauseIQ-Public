"""Unpaid browser/API/storage smoke using only newly owned disposable services.

Run with --run-isolated-live after installing Python/frontend dependencies,
Chromium and the exact official images below. Never starts a Compose stack,
pulls implicitly, connects to the normal database or reads the backend .env file.
Next.js can load frontend env files normally; its API origin is explicitly fixed
to the isolated API, and unexpected browser traffic is blocked by the test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
LABEL = "clauseiq.disposable-realstack-check"
# Official manifests: MongoDB 7.0.26 and Qdrant 1.16.3.
IMAGES = {
    "mongo": "mongo@sha256:8c3ce64d1a433bf57ea79035b48a38ea3e532997a1328fe3266e2e2e8bfb41b6",
    "qdrant": "qdrant/qdrant@sha256:0425e3e03e7fd9b3dc95c4214546afe19de2eb2e28ca621441a56663ac6e1f46",
}
API_PORT = 8101
WEB_PORT = 3101


def docker(*args: str) -> str:
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=40,
    ).strip()


def require_owned(record: dict, identity: str, name: str, token: str, service: str) -> int:
    """Validate exact ownership, tmpfs storage and loopback ports before cleanup."""
    if (record.get("Id") != identity or record.get("Name") != f"/{name}"
            or record.get("Config", {}).get("Labels", {}).get(LABEL) != token
            or record.get("Config", {}).get("Image") != IMAGES[service]):
        raise RuntimeError("Disposable service ownership does not match this invocation")
    host = record.get("HostConfig", {})
    if host.get("Binds") or host.get("VolumesFrom") or not host.get("AutoRemove"):
        raise RuntimeError("Disposable services must not mount persistent storage")
    mounts = record.get("Mounts", []) + host.get("Mounts", [])
    if any(mount.get("Type") != "tmpfs" for mount in mounts):
        raise RuntimeError("Only disposable tmpfs mounts are allowed")
    storage = {"/data/db", "/data/configdb"} if service == "mongo" else {"/qdrant/storage", "/qdrant/snapshots"}
    if not storage <= set(host.get("Tmpfs", {})):
        raise RuntimeError("Required disposable storage mounts are missing")
    container_port = "27017/tcp" if service == "mongo" else "6333/tcp"
    ports = record.get("NetworkSettings", {}).get("Ports", {})
    binding = ports.get(container_port) or []
    if len(binding) != 1 or binding[0].get("HostIp") != "127.0.0.1":
        raise RuntimeError("Disposable service must have one loopback binding")
    port = int(binding[0].get("HostPort", 0))
    if not 1024 <= port <= 65535 or port in {3000, 8000, 27017, 6333, 6334, API_PORT, WEB_PORT}:
        raise RuntimeError("Disposable service must use a separate port")
    if any(key != container_port and value for key, value in ports.items()):
        raise RuntimeError("Unexpected additional published port")
    return port


def assert_free(port: int) -> None:
    with socket.socket() as connection:
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is occupied; the smoke will not reuse or stop that service")


def clean_environment() -> dict[str, str]:
    # Explicit allowlist excludes provider credentials, application settings and
    # proxy overrides. OS home is needed by npm/Chromium, not used as test state.
    names = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "CI",
             "PLAYWRIGHT_BROWSERS_PATH", "LANG", "LC_ALL")
    return {name: os.environ[name] for name in names if name in os.environ}


def wait_for_api(process: subprocess.Popen, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Isolated API exited during startup; inspect synthetic diagnostics")
        try:
            with opener.open(f"http://127.0.0.1:{API_PORT}/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            pass
        time.sleep(0.2)
    raise RuntimeError("Isolated API did not become ready within the bounded startup wait")


def run_browser() -> int:
    """Own the runner's process group so a timeout cannot strand its dev server."""
    process = subprocess.Popen(
        ["npx", "--no-install", "playwright", "test", "--config", "playwright.real.config.mjs"],
        cwd=ROOT / "frontend", env=clean_environment() | {
            "NEXT_TELEMETRY_DISABLED": "1", "CLAUSEIQ_REALSTACK_BROWSER": "1",
        }, start_new_session=os.name == "posix",
    )
    try:
        return process.wait(timeout=360)
    finally:
        if os.name == "posix":
            try:
                # This session was created above, never inherited from a shell or
                # another application. Include child Next processes on interruption.
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while True:
                process.poll()  # Reap the runner; remaining group members are its children.
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() >= deadline:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
                time.sleep(0.05)
        elif process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=3)


def run(python_override: str | None = None) -> int:
    python = Path(python_override).absolute() if python_override else ROOT / "backend/venv/bin/python"
    if not python_override and not python.is_file():
        python = Path(sys.executable)
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError("The selected test Python interpreter is not executable")
    subprocess.run([str(python), "-c", (
        "import sys; from importlib.metadata import version; "
        "assert sys.version_info >= (3, 13), 'Use Python 3.13 or later'; "
        "assert version('qdrant-client') == '1.16.2', "
        "'Install declared dependencies in an isolated interpreter and pass --python'"
    )], env=clean_environment(), check=True, timeout=10)
    for port in (API_PORT, WEB_PORT):
        assert_free(port)
    for image in IMAGES.values():
        docker("image", "inspect", image)  # Never implicitly pull or use moving tags.
    token = uuid.uuid4().hex
    owned = []
    process = None
    output = ROOT / "output/playwright/real-stack"
    output.mkdir(parents=True, exist_ok=True)
    # Neither settings nor logs use the repository's normal backend state directory.
    with tempfile.TemporaryDirectory(prefix="clauseiq-realstack-") as state:
        try:
            ports = {}
            for service, image in IMAGES.items():
                name = f"clauseiq-realstack-{service}-{token[:12]}"
                storage = ("/data/db", "/data/configdb") if service == "mongo" else ("/qdrant/storage", "/qdrant/snapshots")
                args = ["run", "--pull=never", "--rm", "-d", "--name", name,
                        "--label", f"{LABEL}={token}"]
                for mount in storage:
                    args.extend(["--tmpfs", mount])
                if service == "qdrant":
                    args.extend(["-e", "QDRANT__TELEMETRY_DISABLED=true"])
                args.extend(["-p", f"127.0.0.1::{27017 if service == 'mongo' else 6333}", image])
                identity = docker(*args)
                owned.append((identity, name, service))
                ports[service] = require_owned(json.loads(docker("inspect", identity))[0], identity, name, token, service)
            environment = clean_environment() | {
                "ENVIRONMENT": "development", "HOST": "127.0.0.1", "PORT": str(API_PORT),
                "MONGODB_URI": f"mongodb://127.0.0.1:{ports['mongo']}/",
                "MONGODB_DATABASE": f"clauseiq_realstack_{token}", "MONGODB_COLLECTION_PREFIX": "",
                "MONGODB_SERVER_SELECTION_TIMEOUT_MS": "5000", "MONGODB_MIN_POOL_SIZE": "0",
                "QDRANT_HOST": "127.0.0.1", "QDRANT_PORT": str(ports["qdrant"]),
                "QDRANT_COLLECTION": f"realstack-{token}", "QDRANT_API_KEY": "",
                "WORKSPACE_STATE_DIR": state, "CORS_ORIGINS": f"http://127.0.0.1:{WEB_PORT}",
                "PYTHONPATH": os.pathsep.join((str(ROOT / "backend"), str(ROOT / "shared"))),
                "PYTHONDONTWRITEBYTECODE": "1",
                "CLAUSEIQ_REALSTACK_GUARD": str(Path(state) / "guard-violations.txt"),
            }
            with (output / "api.log").open("w") as log:
                process = subprocess.Popen([str(python), str(ROOT / "backend/tests/realstack_app.py")],
                                           cwd=state, env=environment, stdout=log, stderr=subprocess.STDOUT)
                wait_for_api(process)
                print("Isolated API, Mongo/GridFS and Qdrant ready; no saved credentials or providers", flush=True)
                # Separate random Ask fixture DB on this same owned Mongo service;
                # the harness checks fresh-connection persistence and its own cleanup.
                subprocess.run(
                    [str(python), str(ROOT / "backend/tests/realstack_app.py"), "--ask-smoke"],
                    cwd=state, env=environment, check=True, timeout=90,
                )
                result = run_browser()
                if Path(environment["CLAUSEIQ_REALSTACK_GUARD"]).exists():
                    raise RuntimeError("Test attempted forbidden environment, credential or network access")
                return result
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            cleanup_errors = []
            for identity, name, service in reversed(owned):
                try:
                    if not docker("ps", "-aq", "--filter", f"id={identity}"):
                        continue  # --rm may already have removed a failed service.
                    record = json.loads(docker("inspect", identity))[0]
                    require_owned(record, identity, name, token, service)
                    docker("stop", "--time", "5", identity)
                except (RuntimeError, ValueError, subprocess.SubprocessError) as error:
                    cleanup_errors.append(type(error).__name__)
            if cleanup_errors:
                raise RuntimeError("Owned-service cleanup was incomplete; inspect the labelled test containers")
            if docker("ps", "-aq", "--filter", f"label={LABEL}={token}"):
                raise RuntimeError("Disposable test containers remain; cleanup was unsuccessful")
            print("Cleanup complete: only this invocation's disposable containers and state removed", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-live", action="store_true")
    parser.add_argument("--print-images", action="store_true", help="Print the exact prerequisite images for an explicit pull")
    parser.add_argument("--python", help="Optional isolated Python interpreter with the declared backend dependencies")
    args = parser.parse_args()
    if args.print_images:
        print("\n".join(IMAGES.values()))
        return 0
    if not args.run_isolated_live:
        print("Dry run: creates isolated Mongo/Qdrant/API/browser state; no existing installation or paid calls.")
        return 0
    # Make SIGTERM follow the same owned-resource cleanup path as Ctrl-C.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    return run(args.python)


if __name__ == "__main__":
    raise SystemExit(main())
