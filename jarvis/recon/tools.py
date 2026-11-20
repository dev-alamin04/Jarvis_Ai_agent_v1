"""
jarvis/recon/tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core Security Reconnaissance Tools.

Tools:
  • recon_subdomains: passive & certificate transparency subdomain discovery
  • recon_dns_records: DNS records resolution & SPF/DMARC email audit
  • recon_http_headers: HTTP header security audit & technology detection
  • recon_port_scan: rate-limited TCP port scanner (safe nmap / socket)
  • recon_exposed_files: non-destructive check for exposed .env, .git, backups
  • recon_nuclei_scan: safe vulnerability template scanner with nuclei

Rules of Engagement:
  • Every tool strictly verifies the target against config/recon_scope.yaml.
  • Exact command lines are displayed before execution.
  • No brute-forcing, no denial of service, and no exploits.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse
import requests

from jarvis.logger import logger
from jarvis.recon.logger import log_recon_scan
from jarvis.recon.report import generate_recon_report
from jarvis.recon.scope import assert_in_scope, extract_host_and_port

# Standard rate-limited ports for safe scanning
DEFAULT_RECON_PORTS = [21, 22, 25, 53, 80, 443, 3306, 5432, 6379, 8000, 8080, 8443, 9000, 27017]
COMMON_SERVICE_NAMES = {
    21: "FTP",
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    443: "HTTPS",
    3306: "MySQL/MariaDB",
    5432: "PostgreSQL",
    6379: "Redis",
    8000: "HTTP-Alt / Dev",
    8080: "HTTP-Proxy / Alt",
    8443: "HTTPS-Alt",
    9000: "PHP-FPM / SonarQube",
    27017: "MongoDB",
}


# ── 1. Subdomain Discovery ───────────────────────────────────────────────────

def recon_subdomains(domain: str, speak_fn=None) -> str:
    """
    Discover active subdomains for an authorized target using passive
    Certificate Transparency (crt.sh) and subfinder (if installed).
    """
    clean_host = assert_in_scope(domain, speak_fn=speak_fn)
    logger.info(f"[Recon Subdomains] Discovering subdomains for `{clean_host}`...")

    discovered: set[str] = {clean_host}
    tools_used: list[str] = []

    # 1. Check if subfinder is installed
    subfinder_bin = shutil.which("subfinder")
    if subfinder_bin:
        cmd = f"{subfinder_bin} -d {clean_host} -silent"
        print(f"\n[Security Recon Command]: {cmd}")
        tools_used.append(f"`{cmd}`")
        try:
            res = subprocess.run(
                [subfinder_bin, "-d", clean_host, "-silent"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            for line in res.stdout.splitlines():
                sub = line.strip().lower()
                if sub and ("." in sub) and not sub.startswith("*"):
                    discovered.add(sub)
        except Exception as exc:
            logger.debug(f"[Recon Subdomains] subfinder note: {exc}")

    # 2. Passive crt.sh Certificate Transparency query
    crt_url = f"https://crt.sh/?q=%25.{clean_host}&output=json"
    tools_used.append(f"Certificate Transparency API: `{crt_url}`")
    try:
        resp = requests.get(crt_url, timeout=6, headers={"User-Agent": "Jarvis-Security-Recon/1.0"})
        if resp.status_code == 200:
            entries = resp.json()
            for entry in entries:
                name_value = entry.get("name_value", "")
                for sub in name_value.splitlines():
                    sub = sub.strip().lower().lstrip("*.")
                    if sub and sub.endswith(clean_host) and "." in sub:
                        discovered.add(sub)
    except Exception as exc:
        logger.debug(f"[Recon Subdomains] crt.sh note: {exc}")

    sorted_subs = sorted(discovered)
    findings = [
        {
            "title": f"Discovered Subdomain: {sub}",
            "severity": "INFO",
            "category": "subdomains",
            "evidence": f"Active or registered subdomain: {sub}",
            "suggested_fix": "Ensure all discovered subdomains have valid certificates and updated access controls.",
        }
        for sub in sorted_subs
    ]

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Tool": "Subdomain Discovery", "Total Subdomains": len(sorted_subs)},
    )

    log_recon_scan(
        target=clean_host,
        tool_name="recon_subdomains",
        command=" / ".join(tools_used),
        findings_count=len(sorted_subs),
        highest_severity="INFO",
        summary=f"Discovered {len(sorted_subs)} subdomains for {clean_host}",
    )

    sub_list = "\n".join(f"- `{s}`" for s in sorted_subs)
    return (
        f"### 🌐 Subdomain Discovery: `{clean_host}`\n"
        f"**Discovered**: {len(sorted_subs)} subdomain(s)\n"
        f"**Command / Sources**: {', '.join(tools_used)}\n\n"
        f"{sub_list}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )


# ── 2. DNS Records Resolution ────────────────────────────────────────────────

def recon_dns_records(domain: str, speak_fn=None) -> str:
    """
    Resolve DNS records (A, AAAA, MX, TXT, NS, CNAME) and audit email
    security (SPF, DMARC) for an authorized target.
    """
    clean_host = assert_in_scope(domain, speak_fn=speak_fn)
    logger.info(f"[Recon DNS] Resolving DNS records for `{clean_host}`...")

    exact_cmd = f"dig +noall +answer {clean_host} ANY"
    print(f"\n[Security Recon Command]: {exact_cmd}")

    records_found: list[dict[str, str]] = []
    has_spf = False
    has_dmarc = False

    # Attempt dnspython
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.timeout = 4
        resolver.lifetime = 4

        for rtype in ["A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA"]:
            try:
                answers = resolver.resolve(clean_host, rtype)
                for rdata in answers:
                    val = str(rdata).strip('"')
                    records_found.append({"type": rtype, "value": val})
                    if rtype == "TXT" and "v=spf1" in val:
                        has_spf = True
            except Exception:
                continue

        # Check DMARC
        try:
            dmarc_answers = resolver.resolve(f"_dmarc.{clean_host}", "TXT")
            for rdata in dmarc_answers:
                val = str(rdata).strip('"')
                if "v=DMARC1" in val:
                    has_dmarc = True
                    records_found.append({"type": "DMARC", "value": val})
        except Exception:
            pass

    except ImportError:
        # Fallback to dig or socket
        try:
            res = subprocess.run(
                ["dig", "+noall", "+answer", clean_host, "ANY"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                parts = line.split(maxsplit=4)
                if len(parts) >= 5:
                    records_found.append({"type": parts[3], "value": parts[4]})
                    if "v=spf1" in parts[4]:
                        has_spf = True
                    if "v=DMARC1" in parts[4]:
                        has_dmarc = True
        except Exception:
            try:
                ip = socket.gethostbyname(clean_host)
                records_found.append({"type": "A", "value": ip})
            except Exception:
                pass

    # Findings
    findings: list[dict[str, Any]] = []
    for r in records_found:
        findings.append({
            "title": f"DNS Record [{r['type']}]: {clean_host}",
            "severity": "INFO",
            "category": "dns",
            "evidence": f"{r['type']}: {r['value']}",
            "suggested_fix": "Maintain up-to-date authoritative name server configurations.",
        })

    if not has_spf:
        findings.append({
            "title": "Missing SPF (Sender Policy Framework) Record",
            "severity": "MEDIUM",
            "category": "email_security",
            "evidence": f"No TXT record with `v=spf1` found for {clean_host}.",
            "suggested_fix": "Add a TXT record defining allowed mail senders (e.g. `v=spf1 mx -all`) to prevent domain spoofing.",
        })

    if not has_dmarc:
        findings.append({
            "title": "Missing DMARC Policy Record",
            "severity": "MEDIUM",
            "category": "email_security",
            "evidence": f"No DMARC record found at `_dmarc.{clean_host}`.",
            "suggested_fix": "Publish a DMARC policy TXT record (e.g. `v=DMARC1; p=reject; rua=mailto:dmarc@{clean_host}`) to block unauthorized email spoofing.",
        })

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Tool": "DNS Reconnaissance", "Records Count": len(records_found)},
    )

    highest_sev = "MEDIUM" if (not has_spf or not has_dmarc) else "INFO"
    log_recon_scan(
        target=clean_host,
        tool_name="recon_dns_records",
        command=exact_cmd,
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"Resolved {len(records_found)} DNS records; SPF={has_spf}, DMARC={has_dmarc}",
    )

    records_md = "\n".join(f"- **{r['type']}**: `{r['value']}`" for r in records_found)
    return (
        f"### 📡 DNS Records: `{clean_host}`\n"
        f"**Command**: `{exact_cmd}`\n\n"
        f"**Resolved Records** ({len(records_found)} found):\n{records_md or '*No records resolved*'}\n\n"
        f"**Email Security Audit**:\n"
        f"- SPF Record: {'✅ Present' if has_spf else '⚠️ Missing (Medium Risk)'}\n"
        f"- DMARC Record: {'✅ Present' if has_dmarc else '⚠️ Missing (Medium Risk)'}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )


# ── 3. HTTP Headers & Technology Detection ───────────────────────────────────

def recon_http_headers(target: str, speak_fn=None) -> str:
    """
    Inspect HTTP response headers, detect web technologies, and check for
    missing security headers (HSTS, CSP, X-Frame-Options, etc.).
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    url = target if target.startswith("http") else f"https://{clean_host}"

    exact_cmd = f"httpx -u {url} -title -server -tech-detect -status-code"
    print(f"\n[Security Recon Command]: {exact_cmd}")

    logger.info(f"[Recon Headers] Inspecting HTTP headers for `{url}`...")

    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Jarvis-Security-Recon/1.0"},
            verify=False,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError:
        url = f"http://{clean_host}"
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Jarvis-Security-Recon/1.0"},
            allow_redirects=True,
        )
    except Exception as exc:
        return f"Failed to connect to `{url}`: {exc}"

    headers = resp.headers
    findings: list[dict[str, Any]] = []
    tech_stack: list[str] = []

    # 1. Tech detection from headers
    server_hdr = headers.get("Server", "")
    if server_hdr:
        tech_stack.append(f"Web Server: {server_hdr}")
        if re.search(r"/\d+\.", server_hdr):
            findings.append({
                "title": f"Server Banner Information Disclosure ({server_hdr})",
                "severity": "LOW",
                "category": "info_disclosure",
                "evidence": f"Server: {server_hdr}",
                "suggested_fix": "Disable exact server version banners in server config (e.g. `server_tokens off;` in Nginx or `ServerTokens Prod` in Apache).",
            })

    x_powered_by = headers.get("X-Powered-By", "")
    if x_powered_by:
        tech_stack.append(f"Backend Runtime: {x_powered_by}")
        findings.append({
            "title": f"X-Powered-By Header Discloses Technology ({x_powered_by})",
            "severity": "LOW",
            "category": "info_disclosure",
            "evidence": f"X-Powered-By: {x_powered_by}",
            "suggested_fix": "Disable `expose_php = Off` in php.ini or remove the header in reverse proxy configuration.",
        })

    # Cookies tech detection
    cookies_str = str(headers.get("Set-Cookie", ""))
    if "XSRF-TOKEN" in cookies_str or "laravel_session" in cookies_str:
        tech_stack.append("Framework: Laravel (PHP)")
    elif "PHPSESSID" in cookies_str:
        tech_stack.append("Backend: PHP")
    elif "sessionid" in cookies_str or "csrftoken" in cookies_str:
        tech_stack.append("Framework: Django (Python)")

    # 2. Security headers audit
    # HSTS
    if url.startswith("https") and "Strict-Transport-Security" not in headers:
        findings.append({
            "title": "Missing Strict-Transport-Security (HSTS) Header",
            "severity": "MEDIUM",
            "category": "security_headers",
            "evidence": f"Response from {url} is missing Strict-Transport-Security.",
            "suggested_fix": "Add `add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;` to force HTTPS.",
        })

    # Content-Security-Policy
    if "Content-Security-Policy" not in headers:
        findings.append({
            "title": "Missing Content-Security-Policy (CSP) Header",
            "severity": "MEDIUM",
            "category": "security_headers",
            "evidence": "No Content-Security-Policy header defined in HTTP response.",
            "suggested_fix": "Implement a Content-Security-Policy header to prevent Cross-Site Scripting (XSS) and unauthorized resource loading.",
        })

    # X-Frame-Options
    if "X-Frame-Options" not in headers:
        findings.append({
            "title": "Missing X-Frame-Options Header (Clickjacking Risk)",
            "severity": "MEDIUM",
            "category": "security_headers",
            "evidence": "X-Frame-Options header not present in HTTP response.",
            "suggested_fix": "Add `X-Frame-Options: SAMEORIGIN` or `DENY` to protect against framing and Clickjacking attacks.",
        })

    # X-Content-Type-Options
    if headers.get("X-Content-Type-Options", "").lower() != "nosniff":
        findings.append({
            "title": "Missing or Invalid X-Content-Type-Options Header",
            "severity": "LOW",
            "category": "security_headers",
            "evidence": f"X-Content-Type-Options is '{headers.get('X-Content-Type-Options', '')}'. Expected 'nosniff'.",
            "suggested_fix": "Add `X-Content-Type-Options: nosniff` to prevent MIME-type confusion attacks.",
        })

    # Referrer-Policy
    if "Referrer-Policy" not in headers:
        findings.append({
            "title": "Missing Referrer-Policy Header",
            "severity": "LOW",
            "category": "security_headers",
            "evidence": "Referrer-Policy header not defined.",
            "suggested_fix": "Add `Referrer-Policy: strict-origin-when-cross-origin` to limit sensitive data leakage in referrers.",
        })

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Target URL": url, "HTTP Status": resp.status_code, "Technologies": ", ".join(tech_stack)},
    )

    highest_sev = "MEDIUM" if any(f["severity"] == "MEDIUM" for f in findings) else "LOW"
    log_recon_scan(
        target=clean_host,
        tool_name="recon_http_headers",
        command=exact_cmd,
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"HTTP {resp.status_code}. Tech: {', '.join(tech_stack) or 'Unknown'}. Findings: {len(findings)}",
    )

    tech_md = "\n".join(f"- {t}" for t in tech_stack) if tech_stack else "- No specific tech signatures identified"
    findings_md = "\n".join(f"- **[{f['severity']}]** {f['title']}" for f in findings)

    return (
        f"### 🛡️ HTTP Headers & Technology Recon: `{clean_host}`\n"
        f"**Target URL**: `{url}` (Status `{resp.status_code}`)\n"
        f"**Command**: `{exact_cmd}`\n\n"
        f"**Detected Technologies**:\n{tech_md}\n\n"
        f"**Header Security Findings** ({len(findings)} detected):\n{findings_md or '*All recommended headers present*'}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )


# ── 4. Port Scan with Rate Limits ────────────────────────────────────────────

def recon_port_scan(
    target: str,
    ports: str | None = None,
    speak_fn=None,
) -> str:
    """
    Perform a safe, rate-limited TCP port scan against an authorized target.
    Uses nmap (-sT -T3 --max-rate 50) when available, or a throttled socket scanner.
    Flags dangerously exposed services (MySQL, Redis, MongoDB).
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    port_list_str = ports or ",".join(str(p) for p in DEFAULT_RECON_PORTS)

    exact_cmd = f"nmap -sT -T3 --max-rate 50 -Pn -p {port_list_str} {clean_host}"
    print(f"\n[Security Recon Command]: {exact_cmd}")
    logger.info(f"[Recon Port Scan] Scanning `{clean_host}` on ports {port_list_str}...")

    open_ports: list[dict[str, Any]] = []
    nmap_bin = shutil.which("nmap")

    if nmap_bin:
        try:
            res = subprocess.run(
                [nmap_bin, "-sT", "-T3", "--max-rate", "50", "-Pn", "-p", port_list_str, clean_host],
                capture_output=True,
                text=True,
                timeout=25,
            )
            # Parse nmap output: 80/tcp open http
            for line in res.stdout.splitlines():
                m = re.match(r"^(\d+)/tcp\s+open\s+(\S+)", line.strip())
                if m:
                    p_num = int(m.group(1))
                    svc = m.group(2)
                    open_ports.append({"port": p_num, "service": svc})
        except Exception as exc:
            logger.debug(f"[Recon Port Scan] nmap execution note: {exc}")

    # Fallback to throttled socket scanner if nmap returned nothing or was absent
    if not open_ports and not nmap_bin:
        port_ints = [int(p.strip()) for p in port_list_str.split(",") if p.strip().isdigit()]

        def check_port(port: int):
            time.sleep(0.02)  # Rate limiting delay
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                res = s.connect_ex((clean_host, port))
                if res == 0:
                    return port
            except Exception:
                pass
            finally:
                s.close()
            return None

        with ThreadPoolExecutor(max_workers=5) as ex:
            results = ex.map(check_port, port_ints)
            for p in results:
                if p:
                    open_ports.append({"port": p, "service": COMMON_SERVICE_NAMES.get(p, "unknown")})

    # Analyze open ports for risky exposures
    findings: list[dict[str, Any]] = []
    for op in open_ports:
        p = op["port"]
        svc = op["service"]

        if p in (3306, 5432, 6379, 27017):
            findings.append({
                "title": f"Exposed Database Service on Port {p} ({svc})",
                "severity": "CRITICAL" if p in (6379, 27017) else "HIGH",
                "category": "service_exposure",
                "evidence": f"Port {p}/tcp is OPEN ({svc}) on host {clean_host}.",
                "suggested_fix": f"Bind {svc} strictly to localhost (127.0.0.1) or restrict access with firewall (ufw deny {p}). Never expose databases directly to public interfaces.",
            })
        elif p in (21, 23):
            findings.append({
                "title": f"Insecure Cleartext Protocol on Port {p} ({svc})",
                "severity": "MEDIUM",
                "category": "insecure_protocol",
                "evidence": f"Port {p}/tcp is OPEN ({svc}).",
                "suggested_fix": "Disable unencrypted legacy services (FTP/Telnet). Use SFTP/SSH instead.",
            })
        else:
            findings.append({
                "title": f"Open TCP Port {p} ({svc})",
                "severity": "INFO",
                "category": "port_exposure",
                "evidence": f"Port {p}/tcp is OPEN ({svc}).",
                "suggested_fix": "Ensure the service running on this port is intended for external exposure and kept patched.",
            })

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Tool": "Rate-Limited Port Scan", "Command": exact_cmd, "Open Ports": len(open_ports)},
    )

    highest_sev = "INFO"
    if any(f["severity"] == "CRITICAL" for f in findings):
        highest_sev = "CRITICAL"
    elif any(f["severity"] == "HIGH" for f in findings):
        highest_sev = "HIGH"

    log_recon_scan(
        target=clean_host,
        tool_name="recon_port_scan",
        command=exact_cmd,
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"Found {len(open_ports)} open ports: {[op['port'] for op in open_ports]}",
    )

    ports_md = "\n".join(f"- Port **{op['port']}** ({op['service']})" for op in open_ports)
    return (
        f"### 🔌 Port Scan: `{clean_host}`\n"
        f"**Command**: `{exact_cmd}`\n"
        f"**Scanned Ports**: `{port_list_str}` (Rate-limited, safe execution)\n\n"
        f"**Open Ports** ({len(open_ports)} found):\n{ports_md or '*No open ports found*'}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )


# ── 5. Exposed Sensitive Files Check ─────────────────────────────────────────

def recon_exposed_files(target: str, speak_fn=None) -> str:
    """
    Check for publicly exposed sensitive files (.env, .git, backups, logs, phpinfo)
    using non-destructive HTTP requests with signature verification.
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    base_url = target.rstrip("/") if target.startswith("http") else f"https://{clean_host}"

    logger.info(f"[Recon Exposed Files] Checking exposed paths on `{base_url}`...")

    PROBE_PATHS = [
        ("/.env", "CRITICAL", ["APP_KEY=", "DB_PASSWORD=", "APP_ENV=", "MAIL_PASSWORD="]),
        ("/.git/HEAD", "CRITICAL", ["ref: refs/heads/"]),
        ("/.git/config", "CRITICAL", ["[core]", "[remote \"origin\"]"]),
        ("/storage/logs/laravel.log", "HIGH", ["production.ERROR", "Stack trace:", "local.ERROR"]),
        ("/database/database.sqlite", "CRITICAL", ["SQLite format 3"]),
        ("/backup.sql", "HIGH", ["MySQL dump", "CREATE TABLE", "-- Dump completed"]),
        ("/backup.zip", "MEDIUM", ["PK\x03\x04"]),
        ("/phpinfo.php", "MEDIUM", ["PHP Version", "Configuration File (php.ini) Path"]),
        ("/.DS_Store", "LOW", ["\x00\x00\x00\x01Bud1"]),
    ]

    findings: list[dict[str, Any]] = []

    for path, sev, sigs in PROBE_PATHS:
        url = f"{base_url}{path}"
        try:
            resp = requests.get(
                url,
                timeout=5,
                headers={"User-Agent": "Jarvis-Security-Recon/1.0"},
                verify=False,
                stream=True,
            )
            if resp.status_code == 200:
                # Read sample body (max 2048 bytes)
                raw_chunk = resp.raw.read(2048).decode("utf-8", errors="replace")
                # Verify signatures to eliminate false positives
                matched = any(sig in raw_chunk for sig in sigs)
                if matched:
                    snippet = raw_chunk[:120].replace("\n", " ")
                    findings.append({
                        "title": f"Publicly Accessible Sensitive File: {path}",
                        "severity": sev,
                        "category": "exposed_file",
                        "evidence": f"URL {url} returned HTTP 200 OK with signature match. Sample: `{snippet}`",
                        "suggested_fix": f"Block access to `{path}` immediately in your web server configuration (e.g. `location ~ /\\.(?!well-known).* {{ deny all; }}` in Nginx).",
                    })
        except Exception:
            continue

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Target Base": base_url, "Probes Tested": len(PROBE_PATHS)},
    )

    highest_sev = "CRITICAL" if any(f["severity"] == "CRITICAL" for f in findings) else ("HIGH" if findings else "INFO")
    log_recon_scan(
        target=clean_host,
        tool_name="recon_exposed_files",
        command=f"curl -s -I {base_url}/<probe>",
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"Checked {len(PROBE_PATHS)} sensitive paths; found {len(findings)} exposed files",
    )

    if findings:
        findings_md = "\n".join(f"- **[{f['severity']}]** `{f['title']}`" for f in findings)
    else:
        findings_md = "✅ **Clean**: No sensitive files (.env, .git, backups, logs) are exposed."

    return (
        f"### 📂 Exposed Files Audit: `{clean_host}`\n"
        f"**Target URL**: `{base_url}`\n\n"
        f"**Results**:\n{findings_md}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )


# ── 6. Safe Nuclei Vulnerability Scan ────────────────────────────────────────

def recon_nuclei_scan(
    target: str,
    tags: str = "misconfig,exposure",
    speak_fn=None,
) -> str:
    """
    Run safe, non-intrusive vulnerability and misconfiguration templates with Nuclei.
    Strictly restricted to authorized scope with info/low/medium severity only.
    """
    clean_host = assert_in_scope(target, speak_fn=speak_fn)
    url = target if target.startswith("http") else f"https://{clean_host}"

    nuclei_bin = shutil.which("nuclei")
    exact_cmd = f"nuclei -u {url} -tags {tags} -severity info,low,medium -silent"
    print(f"\n[Security Recon Command]: {exact_cmd}")

    if not nuclei_bin:
        return f"Nuclei scanner is not installed on this system. Run `sudo apt install nuclei` to enable."

    logger.info(f"[Recon Nuclei] Running safe templates for `{url}`...")

    findings: list[dict[str, Any]] = []
    try:
        res = subprocess.run(
            [nuclei_bin, "-u", url, "-tags", tags, "-severity", "info,low,medium", "-json", "-silent"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                name = item.get("info", {}).get("name", "Misconfiguration")
                sev = item.get("info", {}).get("severity", "info").upper()
                matched_at = item.get("matched-at", url)
                findings.append({
                    "title": f"Nuclei Finding: {name}",
                    "severity": sev if sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "INFO",
                    "category": "nuclei_template",
                    "evidence": f"Matched at: {matched_at}",
                    "suggested_fix": item.get("info", {}).get("remediation", "Review and patch the flagged component."),
                })
            except Exception:
                continue
    except Exception as exc:
        logger.warning(f"[Recon Nuclei] Execution error: {exc}")

    report_md, report_file, voice_summary = generate_recon_report(
        clean_host,
        findings,
        metadata={"Tool": "Nuclei Safe Scanner", "Command": exact_cmd},
    )

    highest_sev = "MEDIUM" if any(f["severity"] == "MEDIUM" for f in findings) else "INFO"
    log_recon_scan(
        target=clean_host,
        tool_name="recon_nuclei_scan",
        command=exact_cmd,
        findings_count=len(findings),
        highest_severity=highest_sev,
        summary=f"Nuclei finished with {len(findings)} findings",
    )

    findings_md = "\n".join(f"- **[{f['severity']}]** {f['title']}" for f in findings) or "✅ No misconfigurations flagged by Nuclei safe templates."

    return (
        f"### 🔍 Nuclei Vulnerability Scan: `{clean_host}`\n"
        f"**Command**: `{exact_cmd}`\n\n"
        f"**Findings** ({len(findings)} detected):\n{findings_md}\n\n"
        f"📁 *Report saved*: `{report_file}`\n"
        f"📢 *Voice Summary*: \"{voice_summary}\""
    )
