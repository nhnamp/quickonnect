#!/usr/bin/env python3
"""Start two chat servers and one load balancer for a local demo."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python() -> str:
    return sys.executable


def _start(name: str, args: list[str], env: dict[str, str]) -> subprocess.Popen:
    print(f"Starting {name}: {' '.join(args)}")
    return subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def main() -> int:
    base_env = os.environ.copy()
    base_env.setdefault(
        "CHAT_SERVERS",
        "server-9001:127.0.0.1:9001,server-9002:127.0.0.1:9002",
    )

    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        for port in (9001, 9002):
            env = base_env.copy()
            env["SERVER_PORT"] = str(port)
            env["SERVER_ID"] = f"server-{port}"
            processes.append((
                f"server-{port}",
                _start(f"server-{port}", [_python(), "scripts/run_server.py", str(port)], env),
            ))
            time.sleep(0.8)

        processes.append((
            "load-balancer",
            _start("load-balancer", [_python(), "scripts/run_lb.py"], base_env),
        ))

        print("\nDemo stack is running.")
        print("Open clients with: python scripts/run_client.py")
        print("Press Ctrl+C here to stop the servers and load balancer.\n")

        while True:
            time.sleep(1)
            for name, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"{name} exited with code {code}; stopping demo stack.")
                    return code or 1
    except KeyboardInterrupt:
        print("\nStopping demo stack...")
        return 0
    finally:
        for _name, proc in reversed(processes):
            if proc.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
            except Exception:
                proc.terminate()
        deadline = time.time() + 5
        for _name, proc in processes:
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
