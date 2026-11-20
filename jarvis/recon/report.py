"""
jarvis/recon/report.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Security Reconnaissance Report Generator.

Creates comprehensive markdown audit reports categorized by severity:
  • 🔴 CRITICAL: Immediate exposure (.env, database leak, exposed keys)
  • 🟠 HIGH: Debug mode on, exposed Telescope/Horizon, unsafe CORS
  • 🟡 MEDIUM: Missing security headers (HSTS, CSP), vulnerable dependencies
  • 🔵 LOW: Information disclosure (Server banner, X-Powered-By)
  • ⚪ INFO: Passive OSINT, subdomains, open web ports

Saves reports to reports/recon/recon_<target>_<timestamp>.md and generates
concise voice summaries for spoken readback.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

REPORTS_DIR = PROJECT_ROOT / "reports" / "recon"

SEVERITY_ORDER = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
    "INFO": 5,
}

SEVERITY_ICONS = {
    "CRITICAL": "🔴 CRITICAL",
    "HIGH": "🟠 HIGH",
    "MEDIUM": "🟡 MEDIUM",
    "LOW": "🔵 LOW",
    "INFO": "⚪ INFO",
}


def sanitize_slug(name: str) -> str:
    """Sanitize target string for use in filenames."""
    s = re.sub(r"[^\w\-\.]+", "_", name.strip().lower())
    return s.strip("._") or "target"


def format_voice_summary(target: str, findings: list[dict[str, Any]]) -> str:
    """Format a concise spoken voice summary (under 3 sentences)."""
    if not findings:
        return f"Reconnaissance scan for {target} is complete. No security vulnerabilities or exposures were detected."

    crit_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
    high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
    med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    low_count = sum(1 for f in findings if f.get("severity") == "LOW")

    total = len(findings)
    parts = []
    if crit_count:
        parts.append(f"{crit_count} critical")
    if high_count:
        parts.append(f"{high_count} high")
    if med_count:
        parts.append(f"{med_count} medium")
    if low_count:
        parts.append(f"{low_count} low")

    breakdown = ", ".join(parts) if parts else "informational items"

    # Identify most severe issue
    sorted_findings = sorted(findings, key=lambda x: SEVERITY_ORDER.get(x.get("severity", "INFO"), 99))
    top_issue = sorted_findings[0].get("title", "issue")

    summary = (
        f"Reconnaissance scan for {target} found {total} item{'s' if total != 1 else ''}, including {breakdown}. "
        f"The primary concern is {top_issue}. "
        "A full markdown report has been saved to your reports directory."
    )
    return summary


def generate_recon_report(
    target: str,
    findings: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> tuple[str, Path, str]:
    """
    Generate and save a structured markdown security audit report.
    Returns (report_markdown, file_path, voice_summary).
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
    file_ts = ts.strftime("%Y%m%d_%H%M%S")
    slug = sanitize_slug(target)
    report_file = REPORTS_DIR / f"recon_{slug}_{file_ts}.md"

    # Sort findings by severity
    sorted_findings = sorted(
        findings,
        key=lambda x: SEVERITY_ORDER.get(x.get("severity", "INFO"), 99),
    )

    crit_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
    high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
    med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    low_count = sum(1 for f in findings if f.get("severity") == "LOW")
    info_count = sum(1 for f in findings if f.get("severity") == "INFO")

    voice_summary = format_voice_summary(target, findings)

    # Build markdown findings section
    findings_blocks = []
    for idx, item in enumerate(sorted_findings, start=1):
        sev = item.get("severity", "INFO")
        sev_badge = SEVERITY_ICONS.get(sev, sev)
        title = item.get("title", f"Finding {idx}")
        cat = item.get("category", "General")
        evidence = item.get("evidence", "No raw evidence provided.")
        suggested_fix = item.get("suggested_fix", "Review application configuration and security headers.")

        block = (
            f"### {idx}. [{sev_badge}] {title}\n"
            f"- **Category**: `{cat}`\n"
            f"- **Evidence**:\n"
            f"```text\n{evidence.strip()}\n```\n"
            f"- **Suggested Remediation**:\n"
            f"  {suggested_fix}\n"
        )
        findings_blocks.append(block)

    findings_content = "\n".join(findings_blocks) if findings_blocks else "*No security issues or exposures detected.*"

    # Meta lines
    meta_info = metadata or {}
    meta_lines = "\n".join(f"- **{k.title()}**: `{v}`" for k, v in meta_info.items())

    report_md = f"""# 🛡️ Security Reconnaissance & Audit Report

**Target**: `{target}`  
**Scan Timestamp**: `{ts_str}`  
**Scope Status**: Authorized Target (`config/recon_scope.yaml`)  
{meta_lines}

---

## Executive Summary

| Total Findings | 🔴 Critical | 🟠 High | 🟡 Medium | 🔵 Low | ⚪ Info |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **{len(findings)}** | `{crit_count}` | `{high_count}` | `{med_count}` | `{low_count}` | `{info_count}` |

> 📢 **Voice Summary**:  
> *"{voice_summary}"*

---

## Detailed Findings & Remediations

{findings_content}

---
*Report generated automatically by Jarvis Security Recon Assistant.*
"""

    try:
        report_file.write_text(report_md, encoding="utf-8")
        logger.info(f"[Recon Report] Saved audit report to {report_file}")
    except Exception as exc:
        logger.error(f"[Recon Report] Failed to write report file {report_file}: {exc}")

    return report_md, report_file, voice_summary
