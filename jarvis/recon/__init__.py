"""
jarvis/recon/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis Security Reconnaissance & Server Defense Package.

Exports:
  • Scope Gate: is_in_scope, assert_in_scope, assert_not_scope_file,
                ScopeViolationError, ScopeFileTamperError
  • Recon Tools: recon_subdomains, recon_dns_records, recon_http_headers,
                 recon_port_scan, recon_exposed_files, recon_nuclei_scan,
                 recon_full_scan
  • Laravel Audit: recon_laravel_audit
  • Server Defense: recon_server_defense_audit, recon_block_ip
  • Reporting & Auditing: generate_recon_report, log_recon_scan
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.recon.defense import recon_block_ip, recon_server_defense_audit
from jarvis.recon.full_scan import recon_full_scan
from jarvis.recon.laravel import recon_laravel_audit
from jarvis.recon.logger import log_recon_scan
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

# Dynamically register security recon tools in Central Tool Risk Table
try:
    from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
    CENTRAL_TOOL_RISK_TABLE["recon_subdomains"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_dns_records"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_http_headers"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_port_scan"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_exposed_files"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_nuclei_scan"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_laravel_audit"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_full_scan"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["recon_server_defense_audit"] = RiskLevel.SAFE
    # Firewall modifications strictly require spoken user confirmation
    CENTRAL_TOOL_RISK_TABLE["recon_block_ip"] = RiskLevel.NEEDS_CONFIRMATION
except Exception:
    pass

__all__ = [
    "is_in_scope",
    "assert_in_scope",
    "assert_not_scope_file",
    "ScopeViolationError",
    "ScopeFileTamperError",
    "load_scope_config",
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
    "generate_recon_report",
    "log_recon_scan",
]
