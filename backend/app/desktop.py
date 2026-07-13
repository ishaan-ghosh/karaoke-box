from __future__ import annotations

import argparse
import http.cookiejar
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote


def _run_internal_demucs(arguments: list[str]) -> int:
    from demucs.separate import main as demucs_main

    demucs_main(arguments)
    return 0


def _configure_desktop_environment() -> Path:
    from platformdirs import user_data_path

    data_root = Path(user_data_path("Karaoke Box", appauthor=False, roaming=False))
    model_root = data_root / "models"
    data_root.mkdir(parents=True, exist_ok=True)
    model_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("KARAOKE_DATA_DIR", str(data_root))
    os.environ.setdefault("TORCH_HOME", str(model_root / "torch"))
    os.environ.setdefault("HF_HOME", str(model_root / "huggingface"))
    os.environ.setdefault("KARAOKE_SESSION_TOKEN", secrets.token_urlsafe(32))
    # The desktop distribution is intentionally CPU-only, even on machines
    # that happen to have CUDA drivers installed.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    # Desktop requests are same-origin inside the embedded webview.
    os.environ.setdefault("KARAOKE_CORS_ORIGINS", "")
    return data_root


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class _ApiServer(threading.Thread):
    def __init__(self, port: int):
        super().__init__(name="karaoke-api", daemon=True)
        import uvicorn

        from .main import app

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=5)


def _wait_until_ready(base_url: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("The local Karaoke Box service did not start in time.")


def _smoke_test(base_url: str, token: str) -> int:
    cookies = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    browser.open(f"{base_url}/desktop/start?token={quote(token)}", timeout=5).read()
    with browser.open(f"{base_url}/api/health", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Desktop health check returned {response.status}.")
    return 0


def _run_desktop(smoke_test: bool) -> int:
    _configure_desktop_environment()

    from .main import ACTIVE_STATUSES, job_manager, job_store
    from .runtime import web_dist_dir

    if not web_dist_dir().is_dir():
        raise RuntimeError(
            "The compiled frontend was not found. Run `npm run build` before desktop mode."
        )

    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    token = os.environ["KARAOKE_SESSION_TOKEN"]
    server = _ApiServer(port)
    server.start()
    try:
        _wait_until_ready(base_url)
        if smoke_test:
            return _smoke_test(base_url, token)

        import webview

        start_url = f"{base_url}/desktop/start?token={quote(token)}"
        window = webview.create_window(
            "Karaoke Box",
            start_url,
            width=1180,
            height=820,
            min_size=(820, 640),
            background_color="#11100f",
        )

        def prevent_close_while_processing() -> bool:
            if any(job.status in ACTIVE_STATUSES for job in job_store.list(100)):
                window.evaluate_js(
                    "alert('A track is still processing. Wait for it to finish before closing Karaoke Box.')"
                )
                return False
            return True

        window.events.closing += prevent_close_while_processing
        webview.start(debug=os.environ.get("KARAOKE_DESKTOP_DEBUG") == "1")
        return 0
    finally:
        job_manager.shutdown()
        server.stop()


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments and arguments[0] == "--internal-demucs":
        return _run_internal_demucs(arguments[1:])

    parser = argparse.ArgumentParser(description="Karaoke Box desktop application")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start the packaged service, verify it, and exit without opening a window",
    )
    options = parser.parse_args(arguments)
    return _run_desktop(options.smoke_test)


if __name__ == "__main__":
    raise SystemExit(main())
