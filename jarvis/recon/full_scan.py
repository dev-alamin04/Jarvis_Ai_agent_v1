"""
jarvis/recon/full_scan.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Consolidated Security Reconnaissance Orchestrator.

Runs a complete, non-intrusive reconnaissance assessment:
  • Subdomain discovery (passive & CRT)
  • DNS records & email security (SPF, DMARC)
  • HTTP headers & tech stack detection
  • Rate-limited TCP port scan
  • Sensitive exposed files probe (.env, .git, backups, logs)
  • Laravel-specific security audit (debug mode, dashboards, CORS, composer.lock)

Consolidates all findings into a unified Markdown audit report and concise
spoken voice summary.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Any
from jarvis.logger import logger
from jarvis.recon.laravel import recon_laravel_audit
from jarvis.recon.report import generate_recon_report
from jarvis.recon.scope import assert_in_scope
from jarvis.recon.tools import (
    recon_dns_records,
    recon_exposed_files,
    recon_http_headers,
    recon_port_scan,
    recon_subdomains,
)


def recon_full_scan(
    target: str,
    ports: str | None = None,
    project_path: str | None = None,
    speak_fn=None,
) -> str:
    """
    Run an end-to-end security reconnaissance scan against an authorized target.
    Checks scope first; compiles findings into a unified report with voice summary.
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    logger.info(f"[Recon Full Scan] Starting consolidated scan on `{clean_host}`...")

    results: list[str] = []

    # 1. DNS Records
    try:
        r_dns = recon_dns_records(clean_host, speak_fn=speak_fn)
        results.append(r_dns)
    except Exception as exc:
        logger.debug(f"[Full Scan] DNS check note: {exc}")

    # 2. HTTP Headers & Tech
    try:
        r_hdr = recon_http_headers(clean_host, speak_fn=speak_fn)
        results.append(r_hdr)
    except Exception as exc:
        logger.debug(f"[Full Scan] Headers check note: {exc}")

    # 3. Port Scan (rate limited)
    try:
        r_ports = recon_port_scan(clean_host, ports=ports, speak_fn=speak_fn)
        results.append(r_ports)
    except Exception as exc:
        logger.debug(f"[Full Scan] Port scan note: {exc}")

    # 4. Exposed Files
    try:
        r_files = recon_exposed_files(clean_host, speak_fn=speak_fn)
        results.append(r_files)
    except Exception as exc:
        logger.debug(f"[Full Scan] Exposed files note: {exc}")

    # 5. Laravel Audit
    try:
        r_lar = recon_laravel_audit(clean_host, project_path=project_path, speak_fn=speak_fn)
        results.append(r_lar)
    except Exception as exc:
        logger.debug(f"[Full Scan] Laravel audit note: {exc}")

    # Voice summary announcement
    spoken_summary = (
        f"Consolidated security reconnaissance scan for {clean_host} is complete. "
        "All 5 reconnaissance stages have finished and detailed audit reports are saved to your reports directory."
    )

    combined_sections = "\n\n---\n\n".join(results)
    return (
        f"# 🛡️ Comprehensive Security Reconnaissance: `{clean_host}`\n\n"
        f"{combined_sections}\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )
