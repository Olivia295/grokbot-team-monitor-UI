"""Read-only host status for the internal page.

Ported from the grok-bot status dashboard (``dashboard/server.py``). Same facts,
same formatting: uptime, load, memory, disk, listening ports, and a read-only
``tailscale status --json``. Standard library only. Never writes, and never
changes Tailscale configuration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

SERVICES = (("JupyterLab", 8888), ("Dashboard", 8080), ("Blog", 4000))
DISK_PATH = "/home/box"
REFRESH_SECONDS = 30


def sh(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception as error:
        return f"error: {error}"


def port_up(port: int, listing: str | None = None) -> bool:
    text = listing if listing is not None else sh("ss -ltn")
    return f":{port} " in text


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def collect(*, generated_at: str | None = None, read_text=None, disk_usage=None, run=None) -> dict:
    """Return the facts the old dashboard page showed.

    ``read_text``, ``disk_usage`` and ``run`` are injectable so tests never
    touch the real box, Tailscale, or ``/proc``.
    """
    read_text = read_text or _read_text
    disk_usage = disk_usage or shutil.disk_usage
    run = run or sh
    stamp = generated_at if generated_at is not None else time.strftime("%Y-%m-%d %H:%M:%S %Z")

    uptime = {"seconds": 0.0, "days": 0, "hours": 0, "minutes": 0, "text": "unavailable"}
    try:
        up = float(read_text("/proc/uptime").split()[0])
        uptime = {
            "seconds": up,
            "days": int(up // 86400),
            "hours": int(up % 86400 // 3600),
            "minutes": int(up % 3600 // 60),
            "text": f"{int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m",
        }
    except Exception:
        pass

    load: list[str] = []
    try:
        load = read_text("/proc/loadavg").split()[:3]
    except Exception:
        load = []

    memory = {"used_mib": 0, "total_mib": 0, "text": "unavailable"}
    try:
        mem = {}
        for line in read_text("/proc/meminfo").splitlines():
            if ":" not in line:
                continue
            key = line.split(":")[0]
            mem[key] = int(line.split()[1])
        used = (mem["MemTotal"] - mem["MemAvailable"]) // 1024
        total = mem["MemTotal"] // 1024
        memory = {"used_mib": used, "total_mib": total, "text": f"{used} / {total} MiB used"}
    except Exception:
        pass

    disk = {"path": DISK_PATH, "used_gib": 0, "total_gib": 0, "free_gib": 0, "text": "unavailable"}
    try:
        usage = disk_usage(DISK_PATH)
        used_gib = usage.used // 2**30
        total_gib = usage.total // 2**30
        free_gib = usage.free // 2**30
        disk = {
            "path": DISK_PATH,
            "used_gib": used_gib,
            "total_gib": total_gib,
            "free_gib": free_gib,
            "text": f"{used_gib} / {total_gib} GiB used ({free_gib} GiB free)",
        }
    except Exception:
        pass

    tsinfo = "unavailable"
    peers: list[dict] = []
    try:
        ts = json.loads(run("tailscale status --json"))
        tsinfo = (
            f'{ts["BackendState"]} · {ts["Self"]["DNSName"].rstrip(".")} · '
            f'{", ".join(ts["Self"]["TailscaleIPs"][:1])} · key expires {ts["Self"].get("KeyExpiry", "?")}'
        )
        peers = [
            {"host": str(peer.get("HostName")), "os": str(peer.get("OS")), "online": bool(peer.get("Online"))}
            for peer in (ts.get("Peer") or {}).values()
        ]
    except Exception:
        tsinfo, peers = "unavailable", []

    listing = run("ss -ltn")
    services = [{"name": name, "port": port, "up": port_up(port, listing)} for name, port in SERVICES]

    return {
        "generated_at": stamp,
        "refresh_seconds": REFRESH_SECONDS,
        "uptime": uptime,
        "load": load,
        "memory": memory,
        "disk": disk,
        "tailscale": tsinfo,
        "peers": peers,
        "services": services,
    }
