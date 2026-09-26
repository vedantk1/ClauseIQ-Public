"""Test-only real FastAPI launcher with no application env/key/provider access.

The production application has no test-mode bypass. Only the isolated smoke
orchestrator runs this file, with owned store ports and a fresh temporary cwd.
"""
import os
from pathlib import Path
import runpy
import socket
import sys


def main():
    state = Path(os.environ["WORKSPACE_STATE_DIR"]).resolve()
    guard = Path(os.environ["CLAUSEIQ_REALSTACK_GUARD"]).resolve()
    if (state != Path.cwd() or not state.name.startswith("clauseiq-realstack-")
            or guard.parent != state or not os.environ["MONGODB_DATABASE"].startswith("clauseiq_realstack_")):
        raise RuntimeError("Only the isolated real-stack orchestrator may launch this server")

    def forbidden(kind):
        with guard.open("a") as handle:
            handle.write(f"{kind}\n")
        raise RuntimeError("Forbidden access in unpaid isolated browser test")

    from urllib.parse import urlsplit
    mongo_port = urlsplit(os.environ["MONGODB_URI"]).port
    allowed = {("127.0.0.1", mongo_port), ("127.0.0.1", int(os.environ["QDRANT_PORT"]))}

    def audit(event, arguments):
        if event == "socket.connect" and arguments[0].family in (socket.AF_INET, socket.AF_INET6):
            address = arguments[1]
            if tuple(address[:2]) not in allowed:
                forbidden("network")
        if event == "open" and isinstance(arguments[0], (str, bytes)):
            name = Path(os.fsdecode(arguments[0])).name
            if name == ".env" or name.startswith(".env.") or name == "credential.key":
                forbidden("environment-or-credential-file")

    sys.addaudithook(audit)
    import openai
    openai.OpenAI = lambda *args, **kwargs: forbidden("provider-client")
    openai.AsyncOpenAI = lambda *args, **kwargs: forbidden("provider-client")
    from config.environments import EnvironmentConfig
    # Preserve real config validation, while never reading the person's .env.
    EnvironmentConfig.model_config = {**EnvironmentConfig.model_config, "env_file": None}
    from importlib.metadata import version
    if version("qdrant-client") != "1.16.2":
        raise RuntimeError("Install the declared qdrant-client==1.16.2 in the test interpreter; do not change a running app's environment")
    if sys.argv[1:] == ["--ask-smoke"]:
        path = Path(__file__).with_name("manual_review_ask_smoke.py")
        sys.argv = [str(path), "--run-isolated-live", "--mongo-port", str(mongo_port)]
        runpy.run_path(str(path), run_name="__main__")
        return
    if sys.argv[1:]:
        raise RuntimeError("Unsupported isolated launcher action")
    import uvicorn
    from main import app
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), access_log=False)


if __name__ == "__main__":
    main()
