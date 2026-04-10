"""Development launcher for backend API on Windows.

Features:
1) Pre-clean stale listener on target port (default 8001).
2) Start uvicorn with optional --reload.
3) On Ctrl+C, force-kill uvicorn process tree to avoid orphan listeners.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Set


def _run(command: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _listening_pids(port: int) -> Set[int]:
    result = _run(["netstat", "-ano", "-p", "tcp"])
    pids: Set[int] = set()
    if result.returncode != 0:
        return pids

    suffix = f":{port}"
    for line in result.stdout.splitlines():
        text = " ".join(line.split())
        if not text:
            continue
        parts = text.split(" ")
        if len(parts) < 5:
            continue
        proto, local_addr, _, state, pid_text = parts[0], parts[1], parts[2], parts[3], parts[4]
        if proto.upper() != "TCP" or state.upper() != "LISTENING":
            continue
        if not local_addr.endswith(suffix):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue

    return pids


def _kill_process_tree(pid: int) -> None:
    _run(["taskkill", "/PID", str(pid), "/T", "/F"])


def _wait_port_release(port: int, timeout_sec: float = 3.0) -> bool:
    end = time.time() + timeout_sec
    while time.time() < end:
        if not _listening_pids(port):
            return True
        time.sleep(0.1)
    return not _listening_pids(port)


def _clean_port(port: int) -> None:
    pids = _listening_pids(port)
    if not pids:
        return

    for pid in sorted(pids):
        print(f"[dev_server] stopping stale listener pid={pid} on port {port}")
        _kill_process_tree(pid)

    released = _wait_port_release(port, timeout_sec=5.0)
    if not released:
        print(f"[dev_server] warning: port {port} still appears busy")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start backend uvicorn with stale-port cleanup")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reload", action="store_true", default=True)
    parser.add_argument("--no-reload", action="store_true", default=False)
    args = parser.parse_args()

    use_reload = args.reload and not args.no_reload
    backend_dir = Path(__file__).resolve().parents[1]

    _clean_port(args.port)

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if use_reload:
        command.append("--reload")

    env = os.environ.copy()
    # More stable on Windows terminals; avoids some reloader edge cases.
    env.setdefault("WATCHFILES_FORCE_POLLING", "true")

    print(f"[dev_server] launch: {' '.join(command)}")
    proc = subprocess.Popen(command, cwd=str(backend_dir), env=env)

    try:
        return proc.wait()
    except KeyboardInterrupt:
        print("\n[dev_server] Ctrl+C received, stopping backend process tree...")
        try:
            if proc.poll() is None:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                    time.sleep(0.3)
        except Exception:
            pass

        if proc.poll() is None:
            _kill_process_tree(proc.pid)
        _wait_port_release(args.port, timeout_sec=5.0)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
