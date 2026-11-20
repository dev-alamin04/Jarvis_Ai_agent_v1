"""
jarvis/laravel/tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Test Runner & Test Writer (Pest & PHPUnit).

Features:
  • Runs Pest or PHPUnit test suites and filters.
  • Parses results into a crisp voice-friendly spoken summary.
  • Automatically generates new Pest/PHPUnit tests for specified code.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.laravel.context import get_active_laravel_project, run_artisan, run_project_cmd
from jarvis.logger import logger


def laravel_run_tests(
    test_filter: str | None = None,
    suite: str | None = None,
    project_path: Path | None = None,
) -> str:
    """
    Run PHPUnit or Pest tests in the active Laravel project and report results.

    Parameters
    ----------
    test_filter : str | None
        Optional method or class filter (e.g. 'UserTest' or 'can_create_user').
    suite : str | None
        Optional test suite: 'Unit' or 'Feature'.
    """
    if not project_path:
        project_name, project_path = get_active_laravel_project()
    else:
        project_name = project_path.name

    logger.info(f"[Laravel Tests] Running tests in '{project_name}' (filter={test_filter}, suite={suite})")

    # Check for vendor/bin/pest or artisan test
    cmd = []
    pest_bin = project_path / "vendor" / "bin" / "pest"
    phpunit_bin = project_path / "vendor" / "bin" / "phpunit"

    if pest_bin.exists():
        cmd = ["./vendor/bin/pest"]
    elif phpunit_bin.exists():
        cmd = ["./vendor/bin/phpunit"]
    else:
        cmd = ["php", "artisan", "test"]

    if test_filter:
        cmd.extend(["--filter", test_filter])
    if suite:
        cmd.extend(["--testsuite", suite])

    code, stdout, stderr = run_project_cmd(cmd, project_path=project_path, timeout=90)
    output = stdout or stderr or "(no output)"

    # Parse test statistics
    # Formats:
    # Tests:    12 passed (24 assertions)
    # Tests:    2 failed, 10 passed
    # OK (15 tests, 30 assertions)
    # FAILURES! Tests: 15, Assertions: 25, Failures: 2.
    summary_line = ""
    for line in reversed(output.splitlines()):
        if any(w in line for w in ["passed", "failed", "Tests:", "OK (", "FAILURES!"]):
            summary_line = line.strip()
            break

    # Format voice-friendly message
    if code == 0:
        voice_summary = f"All tests passed successfully in {project_name}. {summary_line}"
    else:
        voice_summary = f"Tests failed in {project_name}. {summary_line}"

    # Extract failing test names if any
    failed_tests = re.findall(r"(?:FAILED|FAIL)\s+([^\n\r]+)", output)
    if failed_tests:
        voice_summary += f" Failing: {', '.join(failed_tests[:3])}."

    result_text = (
        f"**Voice Summary**: {voice_summary}\n\n"
        f"**Command**: `{' '.join(cmd)}`\n"
        f"**Exit Code**: {code}\n\n"
        f"```\n{output[-2000:]}\n```"
    )
    return result_text


def laravel_write_test(
    target_name: str,
    test_description: str,
    test_framework: str = "pest",
    project_path: Path | None = None,
) -> str:
    """
    Generate and write a new Pest or PHPUnit test for a controller, model, or service.

    Parameters
    ----------
    target_name : str
        The class or feature to test (e.g. 'UserController', 'OrderService', 'Product').
    test_description : str
        Description of what scenarios to test (e.g. 'test that user registration succeeds and validates email').
    test_framework : str
        'pest' (default) or 'phpunit'.
    """
    if not project_path:
        project_name, project_path = get_active_laravel_project()
    else:
        project_name = project_path.name

    logger.info(f"[Laravel Tests] Writing {test_framework} test for '{target_name}' in {project_name}")

    # Inspect source file if it exists in app/
    class_snippet = ""
    for cand in (project_path / "app").rglob(f"{target_name}.php"):
        try:
            class_snippet = cand.read_text(encoding="utf-8")[:1800]
            break
        except Exception:
            pass

    from jarvis.brain import _get_client
    client = _get_client()
    prompt = (
        f"You are an expert Laravel test engineer. Write a complete, production-grade test file.\n\n"
        f"Project: {project_name}\n"
        f"Target Code: {target_name}\n"
        f"Test Framework: {test_framework.upper()} (Pest or PHPUnit)\n"
        f"Scenarios to test: {test_description}\n"
        f"{f'Source class code snippet:\n```php\n{class_snippet}\n```' if class_snippet else ''}\n\n"
        "Requirements:\n"
        "1. Follow standard Laravel testing best practices (RefreshDatabase, mock external services).\n"
        "2. If Pest, use `test('description', function () { ... });` or `it('...')`.\n"
        "3. If PHPUnit, extend `Tests\\TestCase`.\n"
        "4. Return ONLY valid PHP code (with <?php tag), no markdown formatting, no commentary."
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
        )
        code_text = (resp.choices[0].message.content or "").strip()
        code_text = re.sub(r"^```(?:php)?\s*", "", code_text, flags=re.I)
        code_text = re.sub(r"\s*```$", "", code_text)
    except Exception as exc:
        return f"Failed to generate test code: {exc}"

    # Determine destination filename
    clean_name = target_name.replace("Test", "").strip()
    test_filename = f"{clean_name}Test.php"

    # Default to tests/Feature
    dest_dir = project_path / "tests" / "Feature"
    dest_dir.mkdir(parents=True, exist_ok=True)
    test_path = dest_dir / test_filename

    try:
        test_path.write_text(code_text, encoding="utf-8")
    except Exception as exc:
        return f"Failed to save test file to {test_path}: {exc}"

    # Run the newly generated test immediately
    run_res = laravel_run_tests(test_filter=test_filename.replace(".php", ""), project_path=project_path)

    return (
        f"Created test file at `{test_path.relative_to(project_path)}`.\n\n"
        f"**Test Run Results**:\n{run_res}"
    )
