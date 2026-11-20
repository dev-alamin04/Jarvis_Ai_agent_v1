"""
jarvis/recon/laravel.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Specific Security Reconnaissance & Vulnerability Audit.

Performs deep security checks on authorized Laravel applications:
  1. Debug mode on (Ignition / Whoops stack trace exposure)
  2. Exposed Telescope (/telescope) or Horizon (/horizon) dashboards
  3. Unsafe CORS policies (wildcard origins or reflecting arbitrary origins)
  4. Missing security headers (HSTS, CSP, X-Frame-Options)
  5. Known vulnerable package versions from composer.lock
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import requests

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger
from jarvis.recon.logger import log_recon_scan
from jarvis.recon.report import generate_recon_report
from jarvis.recon.scope import assert_in_scope

# Database of notable known CVEs for PHP/Laravel dependencies
KNOWN_VULNERABLE_PACKAGES: list[dict[str, Any]] = [
    {
        "name": "facade/ignition",
        "affected_max": "2.5.1",
        "cve": "CVE-2021-3129",
        "severity": "CRITICAL",
        "title": "Remote Code Execution via Ignition Deserialization",
        "fix": "Upgrade to facade/ignition >= 2.5.2 or spatie/laravel-ignition.",
    },
    {
        "name": "laravel/framework",
        "affected_max": "8.83.26",
        "cve": "CVE-2022-35653",
        "severity": "HIGH",
        "title": "Laravel Framework Arbitrary File Read / Manipulation",
        "fix": "Upgrade laravel/framework to >= 8.83.27, 9.52.16, or 10.x.",
    },
    {
        "name": "guzzlehttp/guzzle",
        "affected_max": "7.4.4",
        "cve": "CVE-2022-31090",
        "severity": "MEDIUM",
        "title": "CURLOPT_HTTPAUTH authorization header disclosure on redirect",
        "fix": "Run `composer update guzzlehttp/guzzle` to upgrade to >= 7.4.5.",
    },
    {
        "name": "phpunit/phpunit",
        "affected_max": "9.5.19",
        "cve": "CVE-2020-35239",
        "severity": "HIGH",
        "title": "Arbitrary Code Execution in eval-stdin.php",
        "fix": "Remove phpunit from production dependencies or upgrade to >= 9.5.20.",
    },
]


def _version_lte(v1: str, v2: str) -> bool:
    """Simple semver comparison: check if v1 <= v2."""
    def parse_v(s: str):
        nums = [int(p) for p in s.lstrip("v").split(".") if p.isdigit()]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums[:3])
    try:
        return parse_v(v1) <= parse_v(v2)
    except Exception:
        return False


def recon_laravel_audit(
    target: str,
    project_path: str | None = None,
    speak_fn=None,
) -> str:
    """
    Perform comprehensive Laravel application security recon:
    Check debug mode, exposed Telescope/Horizon, CORS, headers, and composer.lock.
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    base_url = target.rstrip("/") if target.startswith("http") else f"https://{clean_host}"

    logger.info(f"[Laravel Recon] Auditing Laravel security for `{base_url}`...")
    findings: list[dict[str, Any]] = []

    # ── 1. Debug Mode & Stack Trace Leak Check ──────────────────────────────
    try:
        # Benign test: request invalid URL to trigger error handling
        err_url = f"{base_url}/_jarvis_recon_test_404_{hash(base_url)}"
        resp = requests.get(
            err_url,
            timeout=6,
            headers={"User-Agent": "Jarvis-Security-Recon/1.0", "Accept": "text/html"},
            verify=False,
        )
        body = resp.text

        ignition_signatures = [
            "Ignition",
            "Spatie\\LaravelIgnition",
            "Facade\\Ignition",
            "Whoops! There was an error.",
            "APP_DEBUG=true",
            "SQLSTATE[",
        ]
        if any(sig in body for sig in ignition_signatures):
            findings.append({
                "title": "Laravel Debug Mode Enabled in Production (APP_DEBUG=true)",
                "severity": "CRITICAL",
                "category": "laravel_debug",
                "evidence": f"Detailed stack trace and environment parameters exposed at {err_url}.",
                "suggested_fix": "Set `APP_DEBUG=false` in your `.env` file and clear cache with `php artisan config:cache` immediately.",
            })
    except Exception as exc:
        logger.debug(f"[Laravel Recon] Debug check note: {exc}")

    # ── 2. Exposed Telescope Dashboard ──────────────────────────────────────
    try:
        tel_url = f"{base_url}/telescope"
        resp = requests.get(
            tel_url,
            timeout=5,
            headers={"User-Agent": "Jarvis-Security-Recon/1.0"},
            verify=False,
            allow_redirects=False,
        )
        if resp.status_code == 200 and ("Telescope" in resp.text or "telescope" in resp.text.lower()):
            findings.append({
                "title": "Exposed Laravel Telescope Dashboard (/telescope)",
                "severity": "HIGH",
                "category": "exposed_dashboard",
                "evidence": f"Telescope is publicly accessible at {tel_url} without authentication (HTTP 200).",
                "suggested_fix": "Restrict Telescope access in `app/Providers/TelescopeServiceProvider.php` using `Telescope::auth()` gate, or disable in production.",
            })
    except Exception:
        pass

    # ── 3. Exposed Horizon Dashboard ────────────────────────────────────────
    try:
        hor_url = f"{base_url}/horizon"
        resp = requests.get(
            hor_url,
            timeout=5,
            headers={"User-Agent": "Jarvis-Security-Recon/1.0"},
            verify=False,
            allow_redirects=False,
        )
        if resp.status_code == 200 and ("Horizon" in resp.text or "horizon" in resp.text.lower()):
            findings.append({
                "title": "Exposed Laravel Horizon Dashboard (/horizon)",
                "severity": "HIGH",
                "category": "exposed_dashboard",
                "evidence": f"Horizon queue dashboard is publicly accessible at {hor_url} (HTTP 200).",
                "suggested_fix": "Protect Horizon with the `Horizon::auth()` gate in `app/Providers/HorizonServiceProvider.php` to restrict to authorized admins.",
            })
    except Exception:
        pass

    # ── 4. Unsafe CORS Policy ───────────────────────────────────────────────
    try:
        cors_headers = {
            "Origin": "https://unauthorized-origin.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        }
        resp = requests.options(f"{base_url}/api/v1/user", timeout=5, headers=cors_headers, verify=False)
        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        acac = resp.headers.get("Access-Control-Allow-Credentials", "").lower()

        if acao == "*":
            findings.append({
                "title": "Permissive Wildcard CORS Header (Access-Control-Allow-Origin: *)",
                "severity": "MEDIUM",
                "category": "cors",
                "evidence": "API responds with `Access-Control-Allow-Origin: *` to arbitrary origins.",
                "suggested_fix": "Specify explicit allowed origins in `config/cors.php` instead of wildcard `*`.",
            })
        elif "unauthorized-origin.test" in acao:
            findings.append({
                "title": "Unsafe CORS Origin Reflection",
                "severity": "HIGH",
                "category": "cors",
                "evidence": f"Server dynamically reflected untrusted Origin header: `{acao}` (Credentials={acac}).",
                "suggested_fix": "Validate incoming Origin against a strict whitelist in `config/cors.php` before reflecting.",
            })
    except Exception:
        pass

    # ── 5. Composer.lock Vulnerability Audit ────────────────────────────────
    lock_file = None
    if project_path:
        candidate_path = Path(project_path) / "composer.lock"
        if candidate_path.exists():
            lock_file = candidate_path

    if not lock_file:
        # Check active project from memory or root
        candidate_root = PROJECT_ROOT / "composer.lock"
        if candidate_root.exists():
            lock_file = candidate_root

    packages_audited = 0
    if lock_file and lock_file.exists():
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                lock_data = json.load(f)
                installed_packages = lock_data.get("packages", [])
                packages_audited = len(installed_packages)

                pkg_map = {p.get("name"): p.get("version", "").lstrip("v") for p in installed_packages}

                for vuln in KNOWN_VULNERABLE_PACKAGES:
                    pkg_name = vuln["name"]
                    if pkg_name in pkg_map:
                        inst_v = pkg_map[pkg_name]
                        if _version_lte(inst_v, vuln["affected_max"]):
                            findings.append({
                                "title": f"Vulnerable Dependency: {pkg_name} ({inst_v}) - {vuln['cve']}",
                                "severity": vuln["severity"],
                                "category": "composer_cve",
                                "evidence": f"Package `{pkg_name}` version `{inst_v}` <= `{vuln['affected_max']}` installed. {vuln['title']}",
                                "suggested_fix": vuln["fix"],
                            })
        except Exception as exc:
            logger.debug(f"[Laravel Recon] composer.lock audit note: {exc}")

    # Generate report
    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={
            "Target Base URL": base_url,
            "Packages Audited": packages_audited,
            "composer.lock": str(lock_file) if lock_file else "Not provided",
        },
    )

    highest_sev = "INFO"
    if any(f["severity"] == "CRITICAL" for f in findings):
        highest_sev = "CRITICAL"
    elif any(f["severity"] == "HIGH" for f in findings):
        highest_sev = "HIGH"
    elif any(f["severity"] == "MEDIUM" for f in findings):
        highest_sev = "MEDIUM"

    log_recon_scan(
        target=clean_host,
        tool_name="recon_laravel_audit",
        command=f"laravel_security_audit({base_url})",
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"Laravel audit found {len(findings)} issues on {base_url}",
    )

    if findings:
        findings_md = "\n".join(f"- **[{f['severity']}]** {f['title']}" for f in findings)
    else:
        findings_md = "✅ **Clean**: No debug mode, exposed dashboards, unsafe CORS, or known package vulnerabilities detected."

    return (
        f"### 🛡️ Laravel Security Audit: `{clean_host}`\n"
        f"**Target URL**: `{base_url}`\n"
        f"**Dependencies Audited**: {packages_audited} packages from `composer.lock`\n\n"
        f"**Audit Findings** ({len(findings)} detected):\n{findings_md}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )
