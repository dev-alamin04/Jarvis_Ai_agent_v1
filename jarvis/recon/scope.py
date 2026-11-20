"""
jarvis/recon/scope.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Security Reconnaissance Scope Manager & Gatekeeper.

Enforces the strict security policy:
  • Every security recon and audit tool MUST check the target against
    config/recon_scope.yaml first.
  • Any target outside the scope is REFUSED, announcing the refusal out loud.
  • The agent can NEVER edit the scope file by itself. Only the user
    can edit it by hand.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import fnmatch
import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
import yaml

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

SCOPE_FILE_PATH = PROJECT_ROOT / "config" / "recon_scope.yaml"


class ScopeViolationError(PermissionError):
    """Raised when a reconnaissance target is not authorized in recon_scope.yaml."""


class ScopeFileTamperError(PermissionError):
    """Raised when the agent attempts to modify the protected scope file."""


def assert_not_scope_file(file_path: str | Path) -> None:
    """
    Enforce invariant: The agent can NEVER edit config/recon_scope.yaml.
    Only the user can edit it by hand.
    """
    p = Path(file_path).resolve()
    target_p = SCOPE_FILE_PATH.resolve()

    if p == target_p or p.name == "recon_scope.yaml":
        msg = (
            "Security Policy Violation: The scope file (config/recon_scope.yaml) "
            "cannot be edited or modified by the agent. Only the user (Alamin) "
            "is authorized to edit it by hand."
        )
        logger.error(f"[Recon Scope] {msg}")
        raise ScopeFileTamperError(msg)


def load_scope_config() -> dict[str, Any]:
    """Load authorized reconnaissance targets from config/recon_scope.yaml."""
    if not SCOPE_FILE_PATH.exists():
        logger.warning(f"[Recon Scope] Scope file not found at {SCOPE_FILE_PATH}. Defaulting to empty scope.")
        return {"domains": [], "ip_ranges": [], "apps": {}}

    try:
        with open(SCOPE_FILE_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data
    except Exception as exc:
        logger.error(f"[Recon Scope] Failed to parse scope configuration: {exc}")
        return {"domains": [], "ip_ranges": [], "apps": {}}


def extract_host_and_port(target: str) -> tuple[str, int | None]:
    """
    Extract clean hostname/IP and optional port from a target string.
    Handles URLs (https://example.com:8443/path), host:port, or bare hostnames.
    """
    target = target.strip()
    if not target:
        return "", None

    # Add dummy scheme if bare URL-like with slashes
    if "://" not in target and ("/" in target or target.startswith("http")):
        target = "http://" + target

    if "://" in target:
        parsed = urlparse(target)
        host = parsed.hostname or ""
        port = parsed.port
        return host.lower(), port

    # Check for host:port (IPv4 or hostname)
    if ":" in target and not target.endswith("]"):
        parts = target.split(":")
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0].lower(), int(parts[1])

    return target.lower(), None


def is_in_scope(target: str) -> tuple[bool, str]:
    """
    Check if a domain, IP address, or URL is within authorized scope.
    Returns (True, reason) if authorized, or (False, reason) if refused.
    """
    host, _ = extract_host_and_port(target)
    if not host:
        return False, "Target host is empty or invalid"

    cfg = load_scope_config()
    domains: list[str] = [d.lower() for d in cfg.get("domains", [])]
    ip_ranges: list[str] = cfg.get("ip_ranges", [])
    apps: dict[str, Any] = cfg.get("apps", {})

    # 1. Check named apps
    for app_id, app_info in apps.items():
        if target.lower() == app_id.lower():
            return True, f"Target matches authorized app `{app_id}`"
        app_url = app_info.get("url", "")
        if app_url:
            app_host, _ = extract_host_and_port(app_url)
            if host == app_host:
                return True, f"Target matches authorized app `{app_id}` ({app_host})"

    # 2. Check domain / wildcard matches
    for dom in domains:
        # Exact match
        if host == dom:
            return True, f"Target matches authorized domain `{dom}`"
        # Wildcard match (e.g. *.example.com matches sub.example.com)
        if dom.startswith("*."):
            suffix = dom[1:]  # e.g. .example.com
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True, f"Target matches authorized wildcard `{dom}`"
            # Also allow root domain if wildcard *.example.com is specified
            if host == dom[2:]:
                return True, f"Target matches authorized root domain of `{dom}`"
        elif fnmatch.fnmatch(host, dom):
            return True, f"Target matches authorized pattern `{dom}`"

    # 3. Check IP address directly
    try:
        ip_obj = ipaddress.ip_address(host)
        for cidr in ip_ranges:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                if ip_obj in network:
                    return True, f"Target IP `{host}` falls within authorized range `{cidr}`"
            except ValueError:
                continue
    except ValueError:
        # Host is a domain name, not an IP literal
        pass

    # 4. Optional DNS resolution check for domain pointing to authorized subnet
    try:
        resolved_ips = socket.gethostbyname_ex(host)[2]
        for r_ip in resolved_ips:
            ip_obj = ipaddress.ip_address(r_ip)
            for cidr in ip_ranges:
                try:
                    network = ipaddress.ip_network(cidr, strict=False)
                    if ip_obj in network:
                        return True, f"Domain `{host}` resolves to authorized IP `{r_ip}` within `{cidr}`"
                except ValueError:
                    continue
    except (socket.error, OSError):
        pass

    return False, f"Target `{target}` (host: `{host}`) is not in authorized recon scope"


def assert_in_scope(
    target: str,
    speak_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Check if target is in scope. If outside scope, speaks out loud and
    raises ScopeViolationError. If inside scope, returns clean hostname.
    """
    allowed, reason = is_in_scope(target)
    if allowed:
        host, _ = extract_host_and_port(target)
        return host or target

    refusal_spoken = f"Target {target} is outside authorized scope. Scanning is refused."
    refusal_detail = f"SCOPE REFUSAL: {reason}. Action strictly denied."
    logger.warning(f"[Recon Scope] {refusal_detail}")

    if speak_fn:
        try:
            speak_fn(refusal_spoken)
        except Exception as exc:
            logger.debug(f"[Recon Scope] Spoken refusal error: {exc}")
    elif os.environ.get("JARVIS_TEST_MODE") != "1" and not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from jarvis.voice_output import speak
            speak(refusal_spoken)
        except Exception:
            pass

    raise ScopeViolationError(f"{refusal_detail} Refusal spoken: \"{refusal_spoken}\"")
