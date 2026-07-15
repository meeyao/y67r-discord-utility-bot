from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import selectors
import threading
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERER_ROOT = REPO_ROOT / "renderer"
RENDER_SCRIPT = RENDERER_ROOT / "src" / "render-weather.tsx"
WORKER_SCRIPT = RENDERER_ROOT / "src" / "render-weather-worker.tsx"
CSS_BUNDLE = RENDERER_ROOT / "dist" / "weather-card.css"
_WORKER: Optional[subprocess.Popen[str]] = None
_WORKER_LOCK = threading.Lock()


def render_weather_card_browser(payload: Dict[str, Any]) -> Optional[bytes]:
    if not _renderer_ready():
        return None

    with tempfile.TemporaryDirectory(prefix="convertcord-weather-") as temp_dir:
        temp_path = Path(temp_dir)
        payload_path = temp_path / "payload.json"
        output_path = temp_path / "weather-card.png"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        env = os.environ.copy()
        node_path = shutil.which("node")
        if not node_path:
            return None
        chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
        if chromium_path and "CHROMIUM_PATH" not in env:
            env["CHROMIUM_PATH"] = chromium_path

        image_bytes = _render_with_worker(env, payload, output_path)
        if image_bytes is not None:
            return image_bytes

        try:
            completed = subprocess.run(
                [node_path, "--import", "tsx/esm", str(RENDER_SCRIPT), str(payload_path), str(output_path)],
                cwd=RENDERER_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0 or not output_path.exists():
            return None
        return output_path.read_bytes()


def _renderer_ready() -> bool:
    return all(
        path.exists()
        for path in (RENDERER_ROOT, RENDER_SCRIPT, CSS_BUNDLE)
    )


def _render_with_worker(env: Dict[str, str], payload: Dict[str, Any], output_path: Path) -> Optional[bytes]:
    if not WORKER_SCRIPT.exists():
        return None

    node_path = shutil.which("node")
    if not node_path:
        return None

    request = json.dumps({"payload": payload, "outputPath": str(output_path)}, separators=(",", ":"))
    with _WORKER_LOCK:
        worker = _ensure_worker(node_path, env)
        if worker is None or worker.stdin is None or worker.stdout is None:
            return None

        try:
            worker.stdin.write(request + "\n")
            worker.stdin.flush()
            response_line = _read_worker_line(worker, timeout=12.0)
        except (BrokenPipeError, OSError, subprocess.SubprocessError):
            _stop_worker()
            return None

        if not response_line:
            _stop_worker()
            return None

        try:
            response = json.loads(response_line)
        except json.JSONDecodeError:
            _stop_worker()
            return None

        if response.get("ok") is True and output_path.exists():
            return output_path.read_bytes()
        if worker.poll() is not None:
            _stop_worker()
        return None


def _ensure_worker(node_path: str, env: Dict[str, str]) -> Optional[subprocess.Popen[str]]:
    global _WORKER
    if _WORKER is not None and _WORKER.poll() is None:
        return _WORKER

    try:
        _WORKER = subprocess.Popen(
            [node_path, "--import", "tsx/esm", str(WORKER_SCRIPT)],
            cwd=RENDERER_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        _WORKER = None
    return _WORKER


def _read_worker_line(worker: subprocess.Popen[str], timeout: float) -> Optional[str]:
    if worker.stdout is None:
        return None
    selector = selectors.DefaultSelector()
    try:
        selector.register(worker.stdout, selectors.EVENT_READ)
        events = selector.select(timeout)
        if not events:
            return None
        return worker.stdout.readline().strip()
    finally:
        selector.close()


def _stop_worker() -> None:
    global _WORKER
    if _WORKER is None:
        return
    try:
        _WORKER.kill()
    except OSError:
        pass
    try:
        _WORKER.wait(timeout=1)
    except (OSError, subprocess.SubprocessError):
        pass
    _WORKER = None
