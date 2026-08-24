from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest


HELPER = Path(__file__).resolve().parents[1] / "find_available_tcp_port.ps1"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launcher")
def test_port_probe_moves_to_next_port_when_start_port_is_occupied():
    blocker = None
    start_port = None
    for _ in range(20):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        candidate.bind(("0.0.0.0", 0))
        candidate.listen()
        candidate_port = candidate.getsockname()[1]
        if candidate_port == 65535:
            candidate.close()
            continue

        next_port_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            next_port_probe.bind(("0.0.0.0", candidate_port + 1))
        except OSError:
            candidate.close()
            next_port_probe.close()
            continue
        next_port_probe.close()
        blocker = candidate
        start_port = candidate_port
        break

    if blocker is None or start_port is None:
        pytest.skip("Could not reserve two consecutive TCP ports")

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(HELPER),
                "-StartPort",
                str(start_port),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        blocker.close()

    assert result.stdout.strip() == str(start_port + 1)
