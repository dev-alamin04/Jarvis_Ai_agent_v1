"""
tests/test_devops_monitoring.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for Jarvis Server Monitoring and DevOps tools:
  1. Config loading & fuzzy server/website matching
  2. SSH execution, command scrubbing, and remote_commands.log auditing
  3. Server health check (SSH, system metrics, services, docker, voice summary)
  4. Remote log analysis (Laravel, nginx, syslog) with automated fix suggestions
  5. Multi-step deployment pipeline with mandatory pre-migration DB backup
  6. Remote backup verification & age reporting
  7. DevOps permission gate: read-only bypass, spoken confirmation, and
     exact command announcement for destructive actions
  8. Background watcher: HTTP downtime, SSL expiry, new errors, proactive alerts
  9. Tool registry & Central Tool Risk Table integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Enable SSH simulation for all tests that rely on simulated server responses.
# Tests that specifically verify REAL connection-failure behaviour MUST unset
# this flag temporarily inside their own context.
# ---------------------------------------------------------------------------
os.environ["JARVIS_MOCK_SSH"] = "1"

from jarvis.devops.backup import server_check_backups
from jarvis.devops.config import (
    find_server,
    find_website,
    get_all_servers,
    get_all_websites,
    get_watcher_config,
    load_servers_config,
)
from jarvis.devops.deploy import server_deploy
from jarvis.devops.gate import (
    check_devops_permission,
    is_destructive_remote_command,
    is_state_changing_remote_command,
)
from jarvis.devops.health import server_health_check
from jarvis.devops.logs import server_analyze_logs
from jarvis.devops.services import (
    server_list_sites,
    server_restart_service,
    server_run_remote_command,
)
from jarvis.devops.ssh_client import (
    REMOTE_COMMANDS_LOG,
    _scrub_command,
    execute_remote_command,
    log_remote_command,
)
from jarvis.devops.watcher import BackgroundServerWatcher
from jarvis.permission_gate import PermissionDenied
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel, verify_tamper_evident_log
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ── 1. Config loading and fuzzy matching ──────────────────────────────────────

def test_config_loading_and_fuzzy_matching():
    print("[TEST] Config loading and fuzzy matching...")
    cfg = load_servers_config()
    assert "servers" in cfg
    assert "websites" in cfg
    assert "watcher" in cfg

    # Verify known servers can be looked up by name and alias
    s1 = find_server("cloudpanel_prod")
    assert s1 is not None
    assert s1["host"] == "127.0.0.1"

    s1_alias = find_server("cloudpanel")
    assert s1_alias is not None
    assert s1_alias["name"] == "cloudpanel_prod"

    s2 = find_server("do_vps")
    assert s2 is not None
    assert s2["type"] == "DigitalOcean"

    s2_alias = find_server("digitalocean")
    assert s2_alias is not None
    assert s2_alias["name"] == "do_vps"

    s3_alias = find_server("hostinger")
    assert s3_alias is not None
    assert s3_alias["name"] == "hostinger_vps"

    # Verify websites can be looked up
    w1 = find_website("mrym_laravel")
    assert w1 is not None
    assert "https://mrym.example.com" in w1["url"]

    w1_alias = find_website("mrym")
    assert w1_alias is not None
    assert w1_alias["name"] == "mrym_laravel"

    w2_alias = find_website("ibrahim")
    assert w2_alias is not None
    assert w2_alias["name"] == "ibrahimcheikh"

    # Verify secrets invariant: no plain passwords in yaml
    for s in get_all_servers().values():
        assert "password" not in s or not s["password"], f"Secret password found in {s['name']}"
        assert s["key_path"].startswith("~/.ssh/") or s["key_path"].startswith("/"), "Keys must reside outside repo"

    print("  ✓ Config loading & fuzzy matching passed.")


# ── 2. Audit logging & command scrubbing ──────────────────────────────────────

def test_audit_logging_and_scrubbing():
    print("[TEST] Remote command logging and credential scrubbing...")
    # Test sensitive scrubbing
    raw_cmd = "mysql -u root -p'SuperSecret123!' -e 'show databases;'"
    scrubbed = _scrub_command(raw_cmd)
    assert "SuperSecret123!" not in scrubbed
    assert "***" in scrubbed

    raw_token = "curl -H 'Authorization: Bearer secret_token_xyz987' https://api.test"
    scrubbed_token = _scrub_command(raw_token)
    assert "secret_token_xyz987" not in scrubbed_token or "***" in scrubbed_token

    # Test audit logging to logs/remote_commands.log
    test_server = "cloudpanel_prod"
    test_cmd = "uptime"
    log_remote_command(
        server_name=test_server,
        user="clp",
        command=test_cmd,
        exit_code=0,
        result_summary="16:00:00 up 45 days, 1 user, load average: 0.25",
        status="APPROVED",
    )

    assert REMOTE_COMMANDS_LOG.exists()
    content = REMOTE_COMMANDS_LOG.read_text(encoding="utf-8")
    assert f"[SERVER: {test_server}]" in content
    assert f"[CMD: {test_cmd}]" in content
    assert "[STATUS: APPROVED]" in content

    # Verify tamper evident chain
    valid, err = verify_tamper_evident_log()
    assert valid, f"Tamper chain invalid: {err}"

    print("  ✓ Remote command logging & scrubbing passed.")


# ── 3. Health check ───────────────────────────────────────────────────────────

def test_server_health_check():
    print("[TEST] Server health check...")
    # In simulation/offline mode, server_health_check returns comprehensive status
    result = server_health_check("cloudpanel_prod")
    assert "Health Report" in result or "cloudpanel_prod" in result
    assert "Disk" in result
    assert "Memory" in result or "RAM" in result
    assert "CPU Load" in result or "load average" in result
    assert "Uptime" in result
    assert "nginx" in result.lower()
    assert "mysql" in result.lower()
    assert "redis" in result.lower()
    assert "Voice Summary" in result or "Spoken Summary" in result

    # Non-existent server
    missing = server_health_check("non_existent_server_12345")
    assert "not found" in missing.lower()

    print("  ✓ Server health check passed.")


# ── 4. Log analysis & fix suggestions ─────────────────────────────────────────

def test_server_analyze_logs():
    print("[TEST] Server log analysis and automated diagnosis...")
    # 1. Laravel log analysis
    res_laravel = server_analyze_logs("cloudpanel_prod", log_type="laravel", lines=30)
    assert "Log Analysis" in res_laravel
    assert "Recommended Actions" in res_laravel or "Voice Summary" in res_laravel

    # 2. Test specific simulated pattern analysis
    mock_log = (
        "[2026-11-20 12:00:00] production.ERROR: SQLSTATE[HY000] [2002] "
        "Connection refused (Connection: mysql, Host: 127.0.0.1)\n"
    )
    with patch("jarvis.devops.logs.execute_remote_command", return_value=(0, mock_log, "")):
        analysis = server_analyze_logs("cloudpanel_prod", log_type="laravel")
        assert "mysql" in analysis.lower()
        assert "connection refused" in analysis.lower()

    # 3. Nginx 502 Bad Gateway
    mock_nginx = "2026/11/20 12:00:00 [error] 1234#1234: *1 connect() failed (111: Connection refused) while connecting to upstream"
    with patch("jarvis.devops.logs.execute_remote_command", return_value=(0, mock_nginx, "")):
        analysis_nginx = server_analyze_logs("cloudpanel_prod", log_type="nginx")
        assert "PHP-FPM" in analysis_nginx or "Upstream" in analysis_nginx

    print("  ✓ Server log analysis passed.")


# ── 5. Deployment pipeline & pre-migration backup ─────────────────────────────

def test_server_deploy_pipeline_and_pre_migration_backup():
    print("[TEST] Server deployment pipeline with mandatory pre-migration backup...")
    executed_commands = []

    def fake_exec(srv, cmd, **kwargs):
        executed_commands.append(cmd)
        return 0, f"OK: {cmd}", ""

    with patch("jarvis.devops.deploy.execute_remote_command", side_effect=fake_exec):
        res = server_deploy(
            server_name="cloudpanel_prod",
            project_name="mrym_laravel",
            branch="main",
            ask_user_fn=lambda _: True,  # User approves
        )
        assert "Deployment Report" in res or "SUCCESS" in res

        # Verify steps were executed in exact order
        # Step 1: git fetch / pull
        assert any("git pull" in c for c in executed_commands)
        # Step 2: composer install
        assert any("composer install" in c for c in executed_commands)

        # Step 3 & 4: Pre-migration backup MUST be executed BEFORE artisan migrate!
        backup_idx = -1
        migrate_idx = -1
        for idx, cmd in enumerate(executed_commands):
            if "backup" in cmd.lower() or "mysqldump" in cmd.lower():
                backup_idx = idx
            if "artisan migrate" in cmd.lower():
                migrate_idx = idx

        assert backup_idx != -1, "Pre-migration backup step was not executed!"
        assert migrate_idx != -1, "Artisan migrate was not executed!"
        assert backup_idx < migrate_idx, (
            f"Pre-migration backup (idx {backup_idx}) MUST occur BEFORE migrate (idx {migrate_idx})!"
        )

        # Step 5: optimize/cache clear
        assert any("artisan optimize:clear" in c or "artisan config:cache" in c for c in executed_commands)
        # Step 6: queue restart
        assert any("queue:restart" in c for c in executed_commands)

    # Test deployment denied by user
    with pytest.raises(PermissionDenied):
        server_deploy(
            server_name="cloudpanel_prod",
            project_name="mrym_laravel",
            branch="main",
            ask_user_fn=lambda _: False,  # User rejects
        )

    print("  ✓ Deployment pipeline & pre-migration backup verified.")


# ── 6. Remote backup verification ─────────────────────────────────────────────

def test_server_check_backups():
    print("[TEST] Remote backup check and staleness detection...")
    res = server_check_backups("cloudpanel_prod")
    assert "Backup Check" in res or "cloudpanel_prod" in res
    assert "Latest File" in res or "Recent Backups" in res
    assert "Status" in res

    # Non-existent server
    missing = server_check_backups("unknown_server_99")
    assert "not found" in missing.lower()

    print("  ✓ Server backup check passed.")


# ── 7. DevOps permission gate ─────────────────────────────────────────────────

def test_devops_permission_gate():
    print("[TEST] DevOps permission gate rules...")
    spoken_messages = []

    def mock_speak(msg):
        spoken_messages.append(msg)

    # 1. Read-only commands run freely without asking
    check_devops_permission("server_health_check", {"server_name": "cloudpanel_prod"})
    check_devops_permission("server_check_backups", {"server_name": "cloudpanel_prod"})
    check_devops_permission("server_analyze_logs", {"server_name": "cloudpanel_prod"})
    check_devops_permission("server_list_sites", {})

    # 2. Restarting service requires confirmation
    with pytest.raises(PermissionDenied):
        check_devops_permission(
            "server_restart_service",
            {"server_name": "cloudpanel_prod", "service": "nginx"},
            ask_user_fn=lambda _: False,
        )

    # Approval passes
    check_devops_permission(
        "server_restart_service",
        {"server_name": "cloudpanel_prod", "service": "nginx"},
        ask_user_fn=lambda _: True,
    )

    # 3. Deploy requires confirmation
    with pytest.raises(PermissionDenied):
        check_devops_permission(
            "server_deploy",
            {"server_name": "cloudpanel_prod", "project_name": "mrym"},
            ask_user_fn=lambda _: False,
        )

    # 4. State-changing remote command (e.g. sudo) requires confirmation
    is_state, _ = is_state_changing_remote_command("sudo systemctl restart php8.2-fpm")
    assert is_state

    with pytest.raises(PermissionDenied):
        check_devops_permission(
            "server_run_remote_command",
            {"server_name": "cloudpanel_prod", "command": "sudo systemctl restart php8.2-fpm"},
            ask_user_fn=lambda _: False,
        )

    # 5. Destructive command: EXACT command MUST be spoken aloud first
    is_destr, _ = is_destructive_remote_command("rm -rf /var/www/html/storage")
    assert is_destr

    spoken_messages.clear()
    with pytest.raises(PermissionDenied):
        check_devops_permission(
            "server_run_remote_command",
            {"server_name": "cloudpanel_prod", "command": "rm -rf /var/www/html/storage"},
            speak_fn=mock_speak,
            ask_user_fn=lambda _: False,
        )
    # Verify exact command was read aloud
    assert any("rm -rf /var/www/html/storage" in m for m in spoken_messages)

    # Database drop
    is_db_drop, _ = is_destructive_remote_command("mysql -e 'DROP DATABASE production_db;'")
    assert is_db_drop

    # Firewall modification
    is_fw, _ = is_destructive_remote_command("ufw disable")
    assert is_fw

    # Safe read-only remote commands run freely
    check_devops_permission(
        "server_run_remote_command",
        {"server_name": "cloudpanel_prod", "command": "uptime"},
        ask_user_fn=lambda _: False,  # Not called because safe
    )

    print("  ✓ DevOps permission gate passed.")


# ── 8. Background watcher & proactive voice alerts ────────────────────────────

def test_background_watcher_and_proactive_alerts():
    print("[TEST] Background watcher & proactive voice alerts...")
    spoken_alerts = []

    def speak_cb(msg):
        spoken_alerts.append(msg)

    watcher = BackgroundServerWatcher(speak_callback=speak_cb, interval_seconds=1)

    # 1. Direct HTTP method check
    err = watcher._check_website_http("https://invalid-non-existent.test")
    assert err is not None

    # 2. Test check_now() triggers alert when website is down
    mock_sites = {
        "mrym_laravel": {
            "name": "mrym_laravel",
            "url": "https://mrym.example.com",
            "server": "cloudpanel_prod",
            "laravel_log_path": "/var/log/laravel.log",
        }
    }

    with patch("jarvis.devops.watcher.get_all_websites", return_value=mock_sites):
        with patch("requests.get", side_effect=Exception("Connection refused")):
            alerts = watcher.check_now()
            assert len(alerts) > 0
            assert any("Alamin" in a and "not responding" in a for a in spoken_alerts)

        # 3. Test alert cooldown prevents immediate repeated speech
        initial_count = len(spoken_alerts)
        with patch("requests.get", side_effect=Exception("Connection refused")):
            watcher.check_now()
        # Should not alert again immediately due to cooldown
        assert len(spoken_alerts) == initial_count

        # 4. Test SSL expiration warning
        spoken_alerts.clear()
        watcher._last_alert_times.clear()
        with patch("requests.get", return_value=MagicMock(status_code=200)):
            with patch.object(
                watcher,
                "_check_ssl_expiry",
                return_value="the SSL certificate for mrym.example.com expires in 4 days.",
            ):
                alerts_ssl = watcher.check_now()
                assert any("Alamin" in a and "SSL" in a for a in spoken_alerts)

        # 5. Test error log alert
        spoken_alerts.clear()
        watcher._last_alert_times.clear()
        error_log = "2026/11/20 12:34:56 production.ERROR: Database connection timed out"
        with patch("requests.get", return_value=MagicMock(status_code=200)):
            with patch.object(watcher, "_check_ssl_expiry", return_value=None):
                with patch("jarvis.devops.watcher.execute_remote_command", return_value=(0, error_log, "")):
                    alerts_log = watcher.check_now()
                    assert any("Alamin" in a and "error" in a for a in spoken_alerts)

    print("  ✓ Background watcher & proactive voice alerts passed.")


# ── 9. Tool Registry & Central Risk Table Integration ─────────────────────────

def test_tool_registry_and_risk_table_integration():
    print("[TEST] Tool registry and Central Risk Table integration...")
    devops_tool_names = [
        "server_health_check",
        "server_analyze_logs",
        "server_deploy",
        "server_check_backups",
        "server_restart_service",
        "server_run_remote_command",
        "server_list_sites",
    ]

    # Verify all tools in TOOL_REGISTRY
    for name in devops_tool_names:
        assert name in TOOL_REGISTRY, f"Tool `{name}` missing from TOOL_REGISTRY"

    # Verify all tools in schemas
    schemas = get_tool_schemas()
    schema_names = [s["function"]["name"] for s in schemas]
    for name in devops_tool_names:
        assert name in schema_names, f"Tool `{name}` missing from get_tool_schemas()"

    # Verify Central Tool Risk Table mapping
    assert CENTRAL_TOOL_RISK_TABLE["server_health_check"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["server_check_backups"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["server_analyze_logs"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["server_list_sites"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["server_restart_service"] == RiskLevel.NEEDS_CONFIRMATION
    assert CENTRAL_TOOL_RISK_TABLE["server_deploy"] == RiskLevel.NEEDS_CONFIRMATION
    assert CENTRAL_TOOL_RISK_TABLE["server_run_remote_command"] == RiskLevel.NEEDS_CONFIRMATION

    # Test server_list_sites output
    sites_output = server_list_sites()
    assert "Configured Servers" in sites_output
    assert "cloudpanel_prod" in sites_output
    assert "mrym_laravel" in sites_output

    print("  ✓ Tool registry and risk table integration passed.")


# ── 10. SSH honesty: connection failure → error result, never fake data ────────

def test_ssh_connection_failure_returns_error_not_simulation():
    """A real connection failure must return exit 255 with an error message.
    Fake / simulated output must NEVER appear in the response."""
    print("[TEST] SSH connection failure returns honest error...")

    # Temporarily disable simulation so we exercise the real connection path.
    env_backup = os.environ.pop("JARVIS_MOCK_SSH", None)
    try:
        import paramiko
        # Simulate a network-level refusal (paramiko raises this for unreachable hosts).
        with patch.object(
            paramiko.SSHClient,
            "connect",
            side_effect=socket.error("Connection refused"),
        ):
            # We also need a non-placeholder host so the placeholder guard doesn't
            # fire first.  Patch find_server to return a realistic entry.
            fake_server = {
                "name": "cloudpanel_prod",
                "host": "192.0.2.1",   # TEST-NET — routable but unreachable
                "port": 22,
                "user": "clp",
                "key_path": "~/.ssh/id_rsa",
                "type": "CloudPanel",
                "services": ["nginx", "mysql", "redis"],
            }
            with patch("jarvis.devops.ssh_client.find_server", return_value=fake_server):
                rc, stdout, stderr = execute_remote_command("cloudpanel_prod", "df -h /")

        assert rc == 255, f"Expected exit code 255, got {rc}"
        assert "cloudpanel_prod" in stderr or "192.0.2.1" in stderr or "failed" in stderr.lower(), (
            f"Expected descriptive error in stderr, got: {stderr!r}"
        )

        # Must NOT contain any simulated content
        simulated_markers = ["32%", "RUNNING", "active", "Simulated output"]
        for marker in simulated_markers:
            assert marker not in stdout, (
                f"Simulated marker {marker!r} found in stdout — fake data was returned on failure!"
            )
            assert marker not in stderr, (
                f"Simulated marker {marker!r} found in stderr — fake data was returned on failure!"
            )

    finally:
        if env_backup is not None:
            os.environ["JARVIS_MOCK_SSH"] = env_backup

    print("  ✓ Connection failure returns honest error, no simulation leak.")


def test_placeholder_host_refused():
    """A server whose host is 127.0.0.1 / localhost / *.example.com must be
    refused immediately with exit 255 and a clear 'placeholder values' message."""
    print("[TEST] Placeholder host detection...")

    env_backup = os.environ.pop("JARVIS_MOCK_SSH", None)
    try:
        for placeholder in ("127.0.0.1", "localhost", "my.example.com"):
            fake_server = {
                "name": "test_server",
                "host": placeholder,
                "port": 22,
                "user": "root",
                "key_path": "~/.ssh/id_rsa",
                "type": "VPS",
                "services": [],
            }
            with patch("jarvis.devops.ssh_client.find_server", return_value=fake_server):
                rc, stdout, stderr = execute_remote_command("test_server", "uptime")

            assert rc == 255, f"Expected 255 for placeholder host {placeholder!r}, got {rc}"
            assert "placeholder" in stderr.lower(), (
                f"Expected 'placeholder' in stderr for host {placeholder!r}, got: {stderr!r}"
            )
            assert stdout == "", f"Expected empty stdout for placeholder host, got: {stdout!r}"

    finally:
        if env_backup is not None:
            os.environ["JARVIS_MOCK_SSH"] = env_backup

    print("  ✓ Placeholder hosts are refused with clear message.")


def test_simulation_only_with_mock_flag():
    """Verify that JARVIS_MOCK_SSH=1 returns simulated output, and without
    the flag a connection failure returns an error — never simulated data."""
    print("[TEST] Simulation gate: JARVIS_MOCK_SSH controls access to fake data...")

    # 1. With JARVIS_MOCK_SSH=1 — simulation should return expected content.
    os.environ["JARVIS_MOCK_SSH"] = "1"
    # Use a placeholder host: simulation must still work even with JARVIS_MOCK_SSH=1
    # because the placeholder guard fires BEFORE the simulation check.
    # To test simulation, use a non-placeholder host via patched find_server.
    real_looking_server = {
        "name": "cloudpanel_prod",
        "host": "10.0.0.1",  # private range, non-placeholder
        "port": 22,
        "user": "clp",
        "key_path": "~/.ssh/id_rsa",
        "type": "CloudPanel",
        "services": ["nginx", "mysql", "redis"],
    }
    with patch("jarvis.devops.ssh_client.find_server", return_value=real_looking_server):
        rc_sim, out_sim, _ = execute_remote_command("cloudpanel_prod", "df -h /")
    assert rc_sim == 0, f"Expected 0 from simulation, got {rc_sim}"
    assert "32%" in out_sim or "Filesystem" in out_sim, (
        f"Expected simulated disk output, got: {out_sim!r}"
    )

    # 2. Without JARVIS_MOCK_SSH — connection failure must return error, not fake data.
    del os.environ["JARVIS_MOCK_SSH"]
    try:
        import paramiko
        with patch.object(paramiko.SSHClient, "connect", side_effect=socket.error("refused")):
            with patch("jarvis.devops.ssh_client.find_server", return_value=real_looking_server):
                rc_fail, out_fail, err_fail = execute_remote_command("cloudpanel_prod", "df -h /")

        assert rc_fail == 255
        assert "32%" not in out_fail and "Filesystem" not in out_fail, (
            "Simulated disk data must NOT appear when JARVIS_MOCK_SSH is unset and connection fails."
        )
        assert "failed" in err_fail.lower() or "connection" in err_fail.lower(), (
            f"Expected connection failure message in stderr, got: {err_fail!r}"
        )
    finally:
        # Restore for any remaining tests
        os.environ["JARVIS_MOCK_SSH"] = "1"

    print("  ✓ Simulation gate: flag controls access correctly.")


if __name__ == "__main__":
    test_config_loading_and_fuzzy_matching()
    test_audit_logging_and_scrubbing()
    test_server_health_check()
    test_server_analyze_logs()
    test_server_deploy_pipeline_and_pre_migration_backup()
    test_server_check_backups()
    test_devops_permission_gate()
    test_background_watcher_and_proactive_alerts()
    test_tool_registry_and_risk_table_integration()
    test_ssh_connection_failure_returns_error_not_simulation()
    test_placeholder_host_refused()
    test_simulation_only_with_mock_flag()
    print("\n🎉 ALL DEVOPS & SERVER MONITORING TESTS PASSED SUCCESSFULLY! 🎉")
