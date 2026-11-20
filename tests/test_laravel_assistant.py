"""
tests/test_laravel_assistant.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test suite for Jarvis Laravel Developer Assistant:
  1. Active project resolution from memory context
  2. Strict .env & secrets access prevention
  3. Permission Gate enforcement (destructive migrations, force push, hard reset)
  4. Stack trace parsing & log reading
  5. Test runner voice summaries
  6. Database backup before destructive actions
  7. Code review pillars
  8. Scaffolding commands & route generation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.laravel.context import get_active_laravel_project, run_artisan
from jarvis.laravel.database import (
    laravel_backup_database,
    laravel_run_migrations,
    laravel_table_schema,
)
from jarvis.laravel.debug import parse_stack_trace, read_laravel_log
from jarvis.laravel.git_tools import (
    laravel_git_commit,
    laravel_git_create_branch,
    laravel_git_diff,
    laravel_git_push,
    laravel_git_reset_hard,
    laravel_git_status,
)
from jarvis.laravel.review import laravel_code_review
from jarvis.laravel.scaffold import laravel_scaffold
from jarvis.laravel.tests import laravel_run_tests
from jarvis.memory import memory_manager
from jarvis.permission_gate import (
    PermissionDenied,
    check as gate_check,
)


def _setup_mock_laravel_project(tmpdir: Path) -> Path:
    """Create a minimal mock Laravel project directory structure."""
    proj = tmpdir / "mock_laravel"
    proj.mkdir()
    (proj / "artisan").write_text("#!/usr/bin/env php\n<?php echo 'Mock Artisan 11.0.0';\n")
    (proj / "composer.json").write_text('{"name": "mock/laravel"}')
    (proj / "storage" / "logs").mkdir(parents=True)
    (proj / "database").mkdir(parents=True)
    (proj / "routes").mkdir(parents=True)
    (proj / "app" / "Http" / "Controllers").mkdir(parents=True)
    (proj / "tests" / "Feature").mkdir(parents=True)

    # Mock routes file
    (proj / "routes" / "web.php").write_text("<?php\nuse Illuminate\\Support\\Facades\\Route;\n")

    # Mock log file
    log_content = (
        "[2026-11-20 12:00:00] local.ERROR: Call to undefined method App\\Models\\User::fakeMethod() "
        '{"exception":"[object] (BadMethodCallException(code: 0): Method fakeMethod does not exist. '
        'at /home/alamin/project/mock_laravel/app/Http/Controllers/UserController.php:42)\n'
        '[stacktrace]\n'
        '#0 /home/alamin/project/mock_laravel/vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php(180): UserController->show()\n'
        '#1 /home/alamin/project/mock_laravel/app/Http/Controllers/UserController.php(42): App\\\\Models\\\\User::fakeMethod()\n'
        '"}\n'
    )
    (proj / "storage" / "logs" / "laravel.log").write_text(log_content)

    return proj


def test_project_context_resolution():
    print("[TEST] Active project context resolution from memory...")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_path = _setup_mock_laravel_project(Path(tmpdir))

        # Set in memory
        memory_manager.set_active_project("mock_proj", str(proj_path))

        name, p = get_active_laravel_project()
        assert name == "mock_proj"
        assert p == proj_path.resolve()
        assert (p / "artisan").exists()

    print("  ✓ Active project correctly resolved from memory context.")


def test_env_and_secrets_strictly_blocked():
    print("[TEST] Strict .env and secrets blocking in Permission Gate...")

    blocked_calls = [
        ("read_file", {"path": "/var/www/my-app/.env"}),
        ("read_file", {"path": ".env.production"}),
        ("edit_file", {"path": "/var/www/.env", "target": "DB_PASS=123", "replacement": "DB_PASS=456"}),
        ("search_files", {"query": "APP_KEY", "directory": "/var/www/.env"}),
        ("run_shell_command", {"command": "cat .env"}),
        ("run_shell_command", {"command": "head -n 5 /path/to/.env.staging"}),
        ("run_shell_command", {"command": "grep DB_PASSWORD .env"}),
        ("read_file", {"path": "/home/user/.ssh/id_rsa"}),
    ]

    for tool, args in blocked_calls:
        try:
            gate_check(tool, args)
            raise AssertionError(f"Tool `{tool}` with args {args} should have been strictly BLOCKED!")
        except PermissionDenied as exc:
            assert "Access to .env files and secrets is blocked" in str(exc)

    print("  ✓ All access attempts to .env and secret files are strictly blocked.")


def test_permission_gate_laravel_rules():
    print("[TEST] Permission Gate Laravel rules (migrations, git)...")

    # Safe operations (pass through without confirmation)
    safe_ops = [
        ("read_laravel_log", {"lines": 50}),
        ("laravel_run_tests", {"test_filter": "UserTest"}),
        ("laravel_git_status", {}),
        ("laravel_git_diff", {}),
        ("laravel_table_schema", {"table_name": "users"}),
        ("laravel_backup_database", {}),
        ("laravel_code_review", {}),
        ("laravel_run_migrations", {"action": "migrate"}),
        ("laravel_run_migrations", {"action": "status"}),
        ("laravel_git_push", {"force": False}),
    ]

    for tool, args in safe_ops:
        try:
            gate_check(tool, args)
        except Exception as e:
            raise AssertionError(f"Expected safe Laravel tool `{tool}` to pass, got: {e}")

    # Dangerous operations (must require confirmation, fail when user rejects)
    with patch("jarvis.permission_gate._ask_user", return_value=False):
        # 1. Destructive migrations: fresh, reset, rollback
        for act in ("fresh", "reset", "rollback"):
            try:
                gate_check("laravel_run_migrations", {"action": act})
                raise AssertionError(f"laravel_run_migrations action='{act}' must require confirmation!")
            except PermissionDenied:
                pass

        # 2. Git force push
        try:
            gate_check("laravel_git_push", {"force": True})
            raise AssertionError("laravel_git_push force=True must require confirmation!")
        except PermissionDenied:
            pass

        # 3. Git hard reset
        try:
            gate_check("laravel_git_reset_hard", {"target": "HEAD~1"})
            raise AssertionError("laravel_git_reset_hard must require confirmation!")
        except PermissionDenied:
            pass

        # 4. Git branch deletion
        try:
            gate_check("laravel_git_delete_branch", {"branch_name": "feature/payments"})
            raise AssertionError("laravel_git_delete_branch must require confirmation!")
        except PermissionDenied:
            pass

    print("  ✓ Permission Gate correctly safeguards destructive migrations and git commands.")


def test_stack_trace_parsing_and_logs():
    print("[TEST] Stack trace parsing and log reader...")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_path = _setup_mock_laravel_project(Path(tmpdir))

        log_out = read_laravel_log(lines=40, project_path=proj_path)
        assert "Call to undefined method" in log_out
        assert "UserController.php:42" in log_out

        parsed = parse_stack_trace(log_out, proj_path)
        assert parsed["file"] is not None and "UserController.php" in parsed["file"]
        assert parsed["line"] == 42
        assert "Call to undefined method" in parsed["message"]

    print("  ✓ Stack trace parser extracted offending file, line, and message.")


def test_database_backup_and_schema():
    print("[TEST] Database automatic backup and schema inspection...")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_path = _setup_mock_laravel_project(Path(tmpdir))

        # Create valid sqlite db
        sqlite_file = proj_path / "database" / "database.sqlite"
        import sqlite3
        with sqlite3.connect(str(sqlite_file)) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL, name TEXT)")
            conn.commit()

        # 1. Test backup
        backup_res = laravel_backup_database(project_path=proj_path)
        assert "Created SQLite database backup" in backup_res
        backups = list((proj_path / "storage" / "backups").glob("*.sqlite"))
        assert len(backups) == 1, "Backup file must exist"

        # 2. Test table schema on SQLite
        schema_res = laravel_table_schema("users", project_path=proj_path)
        assert "email" in schema_res and "INTEGER" in schema_res

    print("  ✓ Database backups and schema inspector verified.")


def test_scaffolding_and_routes():
    print("[TEST] Scaffolding components and route definitions...")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_path = _setup_mock_laravel_project(Path(tmpdir))

        # Test adding a route
        res = laravel_scaffold(
            component_type="route",
            name="products",
            route_definition="Route::get('/products', [ProductController::class, 'index']);",
            project_path=proj_path,
        )
        assert "Successfully added route" in res
        web_php = (proj_path / "routes" / "web.php").read_text(encoding="utf-8")
        assert "Route::get('/products'" in web_php

    print("  ✓ Route scaffolding and route file updates verified.")


def test_voice_test_runner_summary():
    print("[TEST] Test runner voice summary parsing...")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_path = _setup_mock_laravel_project(Path(tmpdir))

        # Mock php artisan test execution
        mock_output = (
            "   PASS  Tests\\Unit\\ExampleTest\n"
            "  ✓ that true is true\n\n"
            "  Tests:    12 passed (24 assertions)\n"
            "  Duration: 0.32s\n"
        )
        with patch("jarvis.laravel.tests.run_project_cmd", return_value=(0, mock_output, "")):
            res = laravel_run_tests(project_path=proj_path)
            assert "Voice Summary" in res
            assert "All tests passed successfully" in res
            assert "12 passed" in res

    print("  ✓ Test runner correctly parses statistics and generates spoken voice summary.")


if __name__ == "__main__":
    print("\n════════════════════════════════════════════════════════════════════")
    print(" Running Jarvis Laravel Developer Assistant Test Suite ")
    print("════════════════════════════════════════════════════════════════════\n")
    test_project_context_resolution()
    test_env_and_secrets_strictly_blocked()
    test_permission_gate_laravel_rules()
    test_stack_trace_parsing_and_logs()
    test_database_backup_and_schema()
    test_scaffolding_and_routes()
    test_voice_test_runner_summary()
    print("\n════════════════════════════════════════════════════════════════════")
    print(" ALL LARAVEL ASSISTANT TESTS PASSED SUCCESSFULLY! ")
    print("════════════════════════════════════════════════════════════════════\n")
