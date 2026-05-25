#!/usr/bin/env python3
"""Check whether the local machine is ready for an end-to-end demo test."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


REQUIRED_MODULES = {
    "cryptography": "cryptography",
    "bcrypt": "bcrypt",
    "psycopg": "psycopg",
    "psycopg_pool": "psycopg_pool",
    "redis": "redis",
    "PyQt6": "PyQt6",
    "mss": "mss",
    "pyautogui": "pyautogui",
    "pyaudio": "pyaudio",
}

OPTIONAL_MODULES = {
    "faster_whisper": "faster_whisper",
    "pytest": "pytest",
}

REQUIRED_FILES = [
    "scripts/run_demo_stack.py",
    "scripts/run_client.py",
    "scripts/setup_db.py",
    "docker-compose.yml",
    "server/features/audio_mixer.py",
    "server/features/whiteboard.py",
    "client/ui/audio_widget.py",
    "client/ui/whiteboard_widget.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--check-ports", action="store_true", help="Also probe common local service ports.")
    args = parser.parse_args()

    checks: list[CheckResult] = []
    checks.extend(check_python())
    checks.extend(check_files())
    checks.extend(check_modules())
    checks.extend(check_environment())
    if args.check_ports:
        checks.extend(check_ports())

    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        print_report(checks)

    failed_required = [check for check in checks if check.required and not check.ok]
    return 1 if failed_required else 0


def check_python() -> list[CheckResult]:
    version = sys.version_info
    ok = version >= (3, 11)
    detail = f"{version.major}.{version.minor}.{version.micro}"
    return [CheckResult("Python >= 3.11", ok, detail)]


def check_files() -> list[CheckResult]:
    out = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        out.append(CheckResult(f"File: {rel}", path.exists(), "found" if path.exists() else "missing"))
    return out


def check_modules() -> list[CheckResult]:
    out = []
    for label, module_name in REQUIRED_MODULES.items():
        out.append(_module_check(label, module_name, required=True))
    for label, module_name in OPTIONAL_MODULES.items():
        out.append(_module_check(label, module_name, required=False))
    return out


def _module_check(label: str, module_name: str, required: bool) -> CheckResult:
    found = importlib.util.find_spec(module_name) is not None
    return CheckResult(
        f"Python module: {label}",
        found,
        "installed" if found else "not installed",
        required=required,
    )


def check_environment() -> list[CheckResult]:
    data_dir = os.environ.get("QUICKONNECT_DATA", "~/.quickonnect")
    stt_enabled = os.environ.get("QUICKONNECT_STT_ENABLED", "0")
    return [
        CheckResult("QUICKONNECT_DATA", True, data_dir, required=False),
        CheckResult("QUICKONNECT_STT_ENABLED", True, stt_enabled, required=False),
    ]


def check_ports() -> list[CheckResult]:
    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = int(os.environ.get("DB_PORT", "5432"))
    db_name = os.environ.get("DB_NAME", "quickonnect")
    db_user = os.environ.get("DB_USER", "quickonnect")
    db_password = os.environ.get("DB_PASSWORD", "quickonnect")
    redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    lb_host = os.environ.get("LB_HOST", "127.0.0.1")
    lb_port = int(os.environ.get("LB_PORT", "9000"))
    results = [
        _postgres_check(db_host, db_port, db_name, db_user, db_password),
    ]
    targets = [
        (f"Redis {redis_port}", redis_host, redis_port, True),
        (f"Load balancer {lb_port}", lb_host, lb_port, False),
        ("Chat server 9001", "127.0.0.1", 9001, False),
        ("Chat server 9002", "127.0.0.1", 9002, False),
    ]
    results.extend(
        CheckResult(name, _can_connect(host, port), f"{host}:{port}", required=required)
        for name, host, port, required in targets
    )
    return results


def _postgres_check(host: str, port: int, db_name: str, user: str, password: str) -> CheckResult:
    try:
        import psycopg
    except ImportError:
        return CheckResult("PostgreSQL login", False, "psycopg is not installed")

    detail = f"{host}:{port}/{db_name} as {user}"
    dsn = f"host={host} port={port} dbname={db_name} user={user} password={password} connect_timeout=2"
    try:
        with psycopg.connect(dsn):
            return CheckResult("PostgreSQL login", True, detail)
    except psycopg.OperationalError as exc:
        first_line = str(exc).splitlines()[0]
        return CheckResult("PostgreSQL login", False, f"{detail} - {first_line}")


def _can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def print_report(checks: list[CheckResult]) -> None:
    print("QuicKonNect E2E readiness check\n")
    for check in checks:
        status = "OK" if check.ok else "MISSING"
        label = "required" if check.required else "optional"
        print(f"[{status:7}] {check.name} ({label}) - {check.detail}")

    required_missing = [check for check in checks if check.required and not check.ok]
    optional_missing = [check for check in checks if not check.required and not check.ok]

    print()
    if required_missing:
        print("Required items missing:")
        for check in required_missing:
            print(f"  - {check.name}")
        if any(check.name.startswith("Python module:") for check in required_missing):
            print("\nInstall dependencies with:")
            print("  python -m pip install -r requirements.txt")
        if any(check.name == "PostgreSQL login" for check in required_missing):
            print("\nCheck PostgreSQL settings:")
            print("  Set DB_HOST, DB_PORT, DB_NAME, DB_USER, and DB_PASSWORD to the database you initialized.")
            print("  If using the demo container from README.md, set DB_PORT=55432 before setup and startup.")
    else:
        print("Required checks passed.")

    if optional_missing:
        print("\nOptional items missing:")
        for check in optional_missing:
            print(f"  - {check.name}")


if __name__ == "__main__":
    raise SystemExit(main())
