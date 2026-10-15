"""Network utilities, DNS resolution resilience, and socket tuning for Airi."""
from __future__ import annotations

import os
import socket
from typing import Any

_installed: bool = False


def setup_network_resilience() -> None:
    """Ensure socket resolution prefers IPv4 (AF_INET) over IPv6.

    This prevents indefinite connection hangs (SYN-SENT) when local networks,
    VPN interfaces (e.g. tun0 / WireGuard), or Wi-Fi routers advertise IPv6
    addresses but fail to route public IPv6 internet traffic.
    """
    global _installed
    if _installed or getattr(socket, "_airi_ipv4_first_installed", False):
        return

    # Disable unnecessary Hugging Face telemetry calls that add latency
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    orig_getaddrinfo = socket.getaddrinfo

    def ipv4_first_getaddrinfo(
        host: Any,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[Any]:
        res = orig_getaddrinfo(host, port, family, type, proto, flags)
        # Prioritize AF_INET (IPv4) entries before AF_INET6
        return sorted(res, key=lambda x: 0 if x[0] == socket.AF_INET else 1)

    socket.getaddrinfo = ipv4_first_getaddrinfo
    socket._airi_ipv4_first_installed = True
    _installed = True
