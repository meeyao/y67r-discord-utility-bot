from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional


CPU_NAMES = {
    "coretemp",
    "k10temp",
    "zenpower",
    "zenpower3",
    "cpu_thermal",
    "cpu-thermal",
}
GPU_NAMES = {
    "amdgpu",
    "nouveau",
    "nvidia",
    "i915",
    "intel_gpu",
    "gpu",
}
DRIVE_NAMES = {
    "drivetemp",
    "nvme",
    "nvme-pci",
    "nvme_pci",
}

CPU_TYPES = {"x86_pkg_temp", "cpu-thermal", "cpu_thermal", "cpu"}
GPU_TYPES = {"gpu-thermal", "gpu_thermal", "gpu"}
DRIVE_TYPES = {"nvme"}


def read_system_temps() -> Dict[str, List[float]]:
    temps = {"cpu": [], "gpu": [], "drive": []}
    _read_hwmon_temps(temps)
    if not temps["cpu"] or not temps["gpu"]:
        _read_thermal_temps(temps)
    return temps


def _read_hwmon_temps(temps: Dict[str, List[float]]) -> None:
    hwmon_root = Path("/sys/class/hwmon")
    if not hwmon_root.exists():
        return
    for hwmon in hwmon_root.glob("hwmon*"):
        name = _read_text(hwmon / "name")
        if not name:
            continue
        temp_values = _read_temp_inputs(hwmon)
        if not temp_values:
            continue
        category = _classify_hwmon(name)
        if category is None:
            continue
        temps[category].append(max(temp_values))


def _read_thermal_temps(temps: Dict[str, List[float]]) -> None:
    thermal_root = Path("/sys/class/thermal")
    if not thermal_root.exists():
        return
    for zone in thermal_root.glob("thermal_zone*"):
        zone_type = _read_text(zone / "type")
        if not zone_type:
            continue
        temp_value = _read_temp_value(zone / "temp")
        if temp_value is None:
            continue
        type_lower = zone_type.strip().lower()
        if type_lower in CPU_TYPES and temp_value not in temps["cpu"]:
            temps["cpu"].append(temp_value)
        elif type_lower in GPU_TYPES and temp_value not in temps["gpu"]:
            temps["gpu"].append(temp_value)
        elif type_lower in DRIVE_TYPES and temp_value not in temps["drive"]:
            temps["drive"].append(temp_value)


def _classify_hwmon(name: str) -> Optional[str]:
    lowered = name.strip().lower()
    if lowered in CPU_NAMES:
        return "cpu"
    if lowered in GPU_NAMES:
        return "gpu"
    if lowered in DRIVE_NAMES or lowered.startswith("nvme"):
        return "drive"
    return None


def _read_temp_inputs(hwmon: Path) -> List[float]:
    temps: List[float] = []
    for temp_input in hwmon.glob("temp*_input"):
        value = _read_temp_value(temp_input)
        if value is None:
            continue
        temps.append(value)
    return temps


def _read_temp_value(path: Path) -> Optional[float]:
    raw = _read_text(path)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value > 1000:
        return value / 1000.0
    return value


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return None


__all__ = ["read_system_temps"]
