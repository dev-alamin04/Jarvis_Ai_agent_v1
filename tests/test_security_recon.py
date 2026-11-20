"""
tests/test_security_recon.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for Jarvis Security Reconnaissance & Defense:
  1. Scope file verification & strict refusal of out-of-scope targets
  2. Scope file immutability: agent attempts to modify scope file are blocked
  3. Passive & subfinder subdomain discovery with command display
  4. DNS records resolution & SPF/DMARC mail security audit
  5. HTTP headers & tech detection with missing security header flags
  6. Rate-limited TCP port scan (safe nmap / throttled socket)
  7. Non-destructive sensitive file exposure probe (.env, .git, backups)
  8. Laravel security audit (debug mode, Telescope/Horizon, CORS, composer.lock)
  9. Markdown report generation & concise voice summary formatting
  10. Server defense mode: SSH failed logins & web path scan detection
  11. Permission gate: spoken confirmation for firewall IP blocking
  12. Audit logging to logs/security_recon.log & tamper-evident hash chain
  13. Tool registry and Central Tool Risk Table integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
os.environ["JARVIS_TEST_MODE"] = "1"

import json
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.permission_gate import PermissionDenied
from jarvis.recon.defense import recon_block_ip, recon_server_defense_audit
from jarvis.recon.full_scan import recon_full_scan
from jarvis.recon.laravel import recon_laravel_audit
from jarvis.recon.logger import RECON_LOG_PATH, log_recon_scan
from jarvis.recon.report import generate_recon_report
from jarvis.recon.scope import (
    ScopeFileTamperError,
    ScopeViolationError,
    assert_in_scope,
    assert_not_scope_file,
    is_in_scope,
    load_scope_config,
)
from jarvis.recon.tools import (
    recon_dns_records,
    recon_exposed_files,
    recon_http_headers,
    recon_nuclei_scan,
    recon_port_scan,
    recon_subdomains,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel, verify_tamper_evident_log
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ── 1. Scope Enforcement & Out-of-Scope Refusal ───────────────────────────────

def test_scope_enforcement_and_refusal():
    print("[TEST] Scope enforcement and out-of-scope refusal...")
    spoken_refusals = []

    def mock_speak(msg):
        spoken_refusals.append(msg)

    # 1. Authorized targets MUST pass
    in_scope_targets = [
        "localhost",
        "127.0.0.1",
        "127.0.0.1:8000",
        "mrym.example.com",
        "api.mrym.example.com",
        "https://mrym.example.com/login",
        "ibrahimcheikh.example.com",
        "dev.local",
        "192.168.1.100",
        "192.168.1.45:8080",
    ]
    for target in in_scope_targets:
        allowed, reason = is_in_scope(target)
        assert allowed, f"Expected {target} to be IN SCOPE, but was rejected: {reason}"
        clean = assert_in_scope(target, speak_fn=mock_speak)
        assert clean, f"Expected clean host for {target}"

    # 2. Out-of-scope targets MUST be strictly refused and announced aloud
    out_of_scope_targets = [
        "google.com",
        "https://facebook.com",
        "github.com",
        "8.8.8.8",
        "1.1.1.1",
        "bank.unauthorized.com",
        "malicious-target.org",
        "172.16.0.1",
    ]
    for target in out_of_scope_targets:
        allowed, reason = is_in_scope(target)
        assert not allowed, f"Expected {target} to be OUT OF SCOPE, but was allowed!"

        spoken_refusals.clear()
        with pytest.raises(ScopeViolationError) as exc_info:
            assert_in_scope(target, speak_fn=mock_speak)

        # Verify exact spoken refusal was announced
        assert len(spoken_refusals) > 0, f"Expected spoken refusal for {target}"
        assert f"Target {target} is outside authorized scope" in spoken_refusals[0]
        assert "refused" in spoken_refusals[0].lower()
        assert "SCOPE REFUSAL" in str(exc_info.value)

    print("  ✓ Scope enforcement and out-of-scope refusal verified.")


# ── 2. Scope File Immutability ────────────────────────────────────────────────

def test_scope_file_immutability():
    print("[TEST] Scope file immutability (agent cannot edit scope file)...")
    # Invariant: assert_not_scope_file raises ScopeFileTamperError
    with pytest.raises(ScopeFileTamperError):
        assert_not_scope_file("config/recon_scope.yaml")

    with pytest.raises(ScopeFileTamperError):
        assert_not_scope_file("/home/alamin/Server/jarvis/config/recon_scope.yaml")

    with pytest.raises(ScopeFileTamperError):
        assert_not_scope_file("recon_scope.yaml")

    # Regular files do not raise
    assert_not_scope_file("config/servers.yaml")
    assert_not_scope_file("reports/recon/report.md")

    print("  ✓ Scope file immutability verified.")


# ── 3. Subdomain Discovery ────────────────────────────────────────────────────

def test_recon_subdomains():
    print("[TEST] Subdomain discovery with Certificate Transparency & subfinder...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_subdomains("unauthorized-victim.com")

    # 2. Authorized domain scan
    mock_crt = [
        {"name_value": "api.mrym.example.com\nadmin.mrym.example.com"},
        {"name_value": "mrym.example.com"},
    ]
    with patch("subprocess.run", return_value=MagicMock(stdout="api.mrym.example.com\nadmin.mrym.example.com\n", returncode=0)):
        with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: mock_crt)):
            res = recon_subdomains("mrym.example.com")
            assert "Subdomain Discovery" in res
            assert "mrym.example.com" in res
            assert "api.mrym.example.com" in res
            assert "admin.mrym.example.com" in res
            assert "Voice Summary" in res

    print("  ✓ Subdomain discovery verified.")


# ── 4. DNS Records & Mail Security ────────────────────────────────────────────

def test_recon_dns_records():
    print("[TEST] DNS records resolution and SPF/DMARC audit...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_dns_records("evil.org")

    # 2. In-scope DNS check with mock
    res = recon_dns_records("localhost")
    assert "DNS Records" in res
    assert "Command" in res
    assert "SPF Record" in res
    assert "DMARC Record" in res
    assert "Voice Summary" in res

    print("  ✓ DNS records & mail security audit verified.")


# ── 5. HTTP Headers & Tech Detection ──────────────────────────────────────────

def test_recon_http_headers():
    print("[TEST] HTTP headers inspection and technology detection...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_http_headers("https://bank.com")

    # 2. In-scope headers check
    mock_headers = {
        "Server": "Apache/2.4.41 (Ubuntu)",
        "X-Powered-By": "PHP/8.2.0",
        "Set-Cookie": "XSRF-TOKEN=test; laravel_session=test",
        # Missing HSTS, CSP, X-Frame-Options
    }
    mock_resp = MagicMock(status_code=200, headers=mock_headers)

    with patch("requests.get", return_value=mock_resp):
        res = recon_http_headers("https://mrym.example.com")
        assert "HTTP Headers & Technology Recon" in res
        assert "Apache/2.4.41" in res
        assert "Laravel" in res
        assert "Strict-Transport-Security" in res
        assert "Content-Security-Policy" in res
        assert "X-Frame-Options" in res
        assert "Voice Summary" in res

    print("  ✓ HTTP headers & technology detection verified.")


# ── 6. Port Scan with Rate Limits ─────────────────────────────────────────────

def test_recon_port_scan():
    print("[TEST] Rate-limited port scan and exposed database detection...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_port_scan("192.0.2.1")

    # 2. In-scope port scan with mock nmap output
    mock_nmap = (
        "Starting Nmap 7.80 ( https://nmap.org ) at 2026-11-20 16:00 UTC\n"
        "Nmap scan report for mrym.example.com (127.0.0.1)\n"
        "Host is up (0.00010s latency).\n"
        "PORT     STATE SERVICE\n"
        "22/tcp   open  ssh\n"
        "80/tcp   open  http\n"
        "443/tcp  open  https\n"
        "3306/tcp open  mysql\n"
        "6379/tcp open  redis\n"
        "\nNmap done: 1 IP address scanned in 0.45 seconds\n"
    )

    with patch("subprocess.run", return_value=MagicMock(stdout=mock_nmap, returncode=0)):
        res = recon_port_scan("mrym.example.com", ports="22,80,443,3306,6379")
        assert "Port Scan" in res
        assert "--max-rate 50" in res  # Verified rate limiting
        assert "3306" in res
        assert "6379" in res
        assert "Voice Summary" in res

    print("  ✓ Rate-limited port scan verified.")


# ── 7. Exposed Sensitive Files Probe ──────────────────────────────────────────

def test_recon_exposed_files():
    print("[TEST] Exposed sensitive files probe (.env, .git, backups)...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_exposed_files("https://victim.com")

    # 2. Simulate .env exposure detection
    def mock_get(url, **kwargs):
        resp = MagicMock()
        if url.endswith("/.env"):
            resp.status_code = 200
            resp.raw.read.return_value = b"APP_NAME=Laravel\nAPP_ENV=production\nAPP_KEY=base64:abcd1234efgh\nDB_PASSWORD=secret\n"
        elif url.endswith("/.git/HEAD"):
            resp.status_code = 200
            resp.raw.read.return_value = b"ref: refs/heads/main\n"
        else:
            resp.status_code = 404
            resp.raw.read.return_value = b"Not Found"
        return resp

    with patch("requests.get", side_effect=mock_get):
        res = recon_exposed_files("https://mrym.example.com")
        assert "Exposed Files Audit" in res
        assert "/.env" in res
        assert "/.git/HEAD" in res
        assert "CRITICAL" in res
        assert "Voice Summary" in res

    print("  ✓ Exposed sensitive files probe verified.")


# ── 8. Laravel Security Audit ─────────────────────────────────────────────────

def test_recon_laravel_audit():
    print("[TEST] Laravel security audit (debug mode, dashboards, CORS, composer.lock)...")
    # 1. Out-of-scope refusal
    with pytest.raises(ScopeViolationError):
        recon_laravel_audit("https://external-target.com")

    # 2. Simulate debug mode on and exposed Telescope
    def mock_get(url, **kwargs):
        resp = MagicMock()
        if "_jarvis_recon_test_404" in url:
            resp.status_code = 500
            resp.text = "<html><body>Ignition - Whoops! There was an error. APP_DEBUG=true Stack trace: ...</body></html>"
        elif url.endswith("/telescope"):
            resp.status_code = 200
            resp.text = "<html><title>Laravel Telescope</title><body>Telescope Dashboard</body></html>"
        elif url.endswith("/horizon"):
            resp.status_code = 200
            resp.text = "<html><title>Laravel Horizon</title><body>Horizon Dashboard</body></html>"
        else:
            resp.status_code = 404
            resp.text = "404 Not Found"
        return resp

    # Mock composer.lock with vulnerable guzzlehttp and facade/ignition
    mock_lock_data = {
        "packages": [
            {"name": "facade/ignition", "version": "v2.5.1"},
            {"name": "guzzlehttp/guzzle", "version": "7.4.2"},
            {"name": "laravel/framework", "version": "10.48.0"},
        ]
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_lock = Path(tmp_dir) / "composer.lock"
        tmp_lock.write_text(json.dumps(mock_lock_data), encoding="utf-8")

        with patch("requests.get", side_effect=mock_get):
            res = recon_laravel_audit("https://mrym.example.com", project_path=tmp_dir)
            assert "Laravel Security Audit" in res
            assert "Debug Mode Enabled" in res
            assert "Telescope Dashboard" in res
            assert "Horizon Dashboard" in res
            assert "CVE-2021-3129" in res
            assert "CVE-2022-31090" in res
            assert "Voice Summary" in res

    print("  ✓ Laravel security audit verified.")


# ── 9. Markdown Reporting & Voice Summary ─────────────────────────────────────

def test_generate_recon_report():
    print("[TEST] Markdown report generation & severity categorizations...")
    mock_findings = [
        {
            "title": "Exposed .env Configuration File",
            "severity": "CRITICAL",
            "category": "exposed_file",
            "evidence": "APP_KEY=base64:xyz",
            "suggested_fix": "Deny all in web server.",
        },
        {
            "title": "Debug Mode Enabled in Production",
            "severity": "HIGH",
            "category": "laravel_debug",
            "evidence": "APP_DEBUG=true in response",
            "suggested_fix": "Set APP_DEBUG=false.",
        },
        {
            "title": "Missing HSTS Header",
            "severity": "MEDIUM",
            "category": "security_headers",
            "evidence": "Strict-Transport-Security header missing",
            "suggested_fix": "Add Strict-Transport-Security header.",
        },
    ]

    report_md, report_file, voice_summary = generate_recon_report(
        "mrym.example.com",
        mock_findings,
        metadata={"Auditor": "Jarvis"},
    )

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# 🛡️ Security Reconnaissance & Audit Report" in content
    assert "CRITICAL" in content
    assert "Exposed .env" in content
    assert "APP_DEBUG=true" in content
    assert "Suggested Remediation" in content
    assert "Voice Summary" in report_md

    # Test voice summary brevity (under 3 sentences)
    assert "mrym.example.com" in voice_summary
    assert "critical" in voice_summary.lower()
    sentences = [s.strip() for s in voice_summary.split(". ") if s.strip()]
    assert len(sentences) <= 3

    print("  ✓ Markdown report generation verified.")


# ── 10. Server Defense Mode (Brute-Force & Scanning Detection) ────────────────

def test_server_defense_audit():
    print("[TEST] Server defense mode (SSH brute force & web scan detection)...")
    # Simulate auth.log with 8 failed logins from 203.0.113.45
    auth_log = (
        "Nov 20 15:00:01 srv sshd[100]: Failed password for root from 203.0.113.45 port 50000 ssh2\n"
        "Nov 20 15:00:02 srv sshd[101]: Failed password for root from 203.0.113.45 port 50002 ssh2\n"
        "Nov 20 15:00:03 srv sshd[102]: Invalid user admin from 203.0.113.45 port 50004\n"
        "Nov 20 15:00:04 srv sshd[103]: Failed password for invalid user admin from 203.0.113.45 port 50006 ssh2\n"
        "Nov 20 15:00:05 srv sshd[104]: Failed password for root from 203.0.113.45 port 50008 ssh2\n"
        "Nov 20 15:00:06 srv sshd[105]: Failed password for root from 203.0.113.45 port 50010 ssh2\n"
    )

    # Simulate nginx access.log with 6 attack requests from 198.51.100.22
    nginx_log = (
        '198.51.100.22 - - [20/Nov/2026:15:01:00 +0000] "GET /.env HTTP/1.1" 404 162\n'
        '198.51.100.22 - - [20/Nov/2026:15:01:01 +0000] "GET /wp-login.php HTTP/1.1" 404 162\n'
        '198.51.100.22 - - [20/Nov/2026:15:01:02 +0000] "GET /phpmyadmin/ HTTP/1.1" 404 162\n'
        '198.51.100.22 - - [20/Nov/2026:15:01:03 +0000] "GET /.git/config HTTP/1.1" 404 162\n'
        '198.51.100.22 - - [20/Nov/2026:15:01:04 +0000] "GET /actuator/health HTTP/1.1" 404 162\n'
        '198.51.100.22 - - [20/Nov/2026:15:01:05 +0000] "GET /cgi-bin/test HTTP/1.1" 404 162\n'
    )

    def fake_remote(srv, cmd, **kwargs):
        if "auth.log" in cmd or "secure" in cmd:
            return 0, auth_log, ""
        elif "access.log" in cmd:
            return 0, nginx_log, ""
        return 0, "", ""

    with patch("jarvis.recon.defense.execute_remote_command", side_effect=fake_remote):
        res = recon_server_defense_audit("cloudpanel_prod")
        assert "Hostile Activity Detected" in res
        assert "203.0.113.45" in res
        assert "SSH Brute-Force" in res
        assert "198.51.100.22" in res
        assert "Malicious Web Scanning" in res
        assert "Voice Summary" in res

    print("  ✓ Server defense audit verified.")


# ── 11. Firewall IP Blocking & Spoken Confirmation Gate ───────────────────────

def test_recon_block_ip():
    print("[TEST] Firewall IP blocking permission gate (requires spoken confirmation)...")
    spoken_prompts = []

    def mock_speak(msg):
        spoken_prompts.append(msg)

    # 1. User says "no" -> PermissionDenied
    with pytest.raises(PermissionDenied):
        recon_block_ip(
            server_name="cloudpanel_prod",
            ip_address="203.0.113.45",
            reason="SSH Brute Force",
            speak_fn=mock_speak,
            ask_user_fn=lambda _: False,  # User denies
        )

    assert len(spoken_prompts) > 0
    assert "203.0.113.45" in spoken_prompts[0]
    assert "Do you approve?" in spoken_prompts[0]

    # 2. User says "yes" -> Executes ufw block rule
    with patch("jarvis.recon.defense.execute_remote_command", return_value=(0, "Rule added", "")):
        res = recon_block_ip(
            server_name="cloudpanel_prod",
            ip_address="203.0.113.45",
            reason="SSH Brute Force",
            speak_fn=mock_speak,
            ask_user_fn=lambda _: True,  # User approves
        )
        assert "Firewall Rule Applied" in res
        assert "203.0.113.45" in res
        assert "ufw insert 1 deny" in res

    print("  ✓ Firewall IP blocking permission gate verified.")


# ── 12. Audit Logging & Tamper-Evident Chain ──────────────────────────────────

def test_recon_audit_logging():
    print("[TEST] Security recon logging & cryptographic hash chain...")
    log_recon_scan(
        target="mrym.example.com",
        tool_name="test_scan",
        command="test_scan --target mrym.example.com",
        findings_count=3,
        highest_severity="HIGH",
        status="COMPLETED",
        summary="Test scan summary",
    )

    assert RECON_LOG_PATH.exists()
    content = RECON_LOG_PATH.read_text(encoding="utf-8")
    assert "[TARGET: mrym.example.com]" in content
    assert "[TOOL: test_scan]" in content
    assert "[SEVERITY: HIGH]" in content

    # Verify tamper-evident action log integrity
    valid, err = verify_tamper_evident_log()
    assert valid, f"Tamper chain broken: {err}"

    print("  ✓ Security recon audit logging verified.")


# ── 13. Tool Registry & Central Risk Table ────────────────────────────────────

def test_recon_registry_and_risk_table():
    print("[TEST] Tool registry and Central Tool Risk Table integration...")
    recon_tools = [
        "recon_subdomains",
        "recon_dns_records",
        "recon_http_headers",
        "recon_port_scan",
        "recon_exposed_files",
        "recon_nuclei_scan",
        "recon_laravel_audit",
        "recon_full_scan",
        "recon_server_defense_audit",
        "recon_block_ip",
    ]

    # Verify all tools in TOOL_REGISTRY
    for t_name in recon_tools:
        assert t_name in TOOL_REGISTRY, f"Tool `{t_name}` missing from TOOL_REGISTRY"

    # Verify all tools in schemas
    schemas = get_tool_schemas()
    schema_names = [s["function"]["name"] for s in schemas]
    for t_name in recon_tools:
        assert t_name in schema_names, f"Tool `{t_name}` missing from schemas"

    # Verify Risk Levels in Central Risk Table
    for t_name in recon_tools:
        if t_name == "recon_block_ip":
            assert CENTRAL_TOOL_RISK_TABLE[t_name] == RiskLevel.NEEDS_CONFIRMATION
        else:
            assert CENTRAL_TOOL_RISK_TABLE[t_name] == RiskLevel.SAFE

    print("  ✓ Tool registry & Central Tool Risk Table integration verified.")


if __name__ == "__main__":
    test_scope_enforcement_and_refusal()
    test_scope_file_immutability()
    test_recon_subdomains()
    test_recon_dns_records()
    test_recon_http_headers()
    test_recon_port_scan()
    test_recon_exposed_files()
    test_recon_laravel_audit()
    test_generate_recon_report()
    test_server_defense_audit()
    test_recon_block_ip()
    test_recon_audit_logging()
    test_recon_registry_and_risk_table()
    print("\n🎉 ALL SECURITY RECONNAISSANCE & DEFENSE TESTS PASSED! 🎉")
