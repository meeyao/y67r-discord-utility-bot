from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERER_ROOT = REPO_ROOT / "renderer"
RENDER_SCRIPT = RENDERER_ROOT / "src" / "render-weather.tsx"
CSS_BUNDLE = RENDERER_ROOT / "dist" / "weather-card.css"


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
