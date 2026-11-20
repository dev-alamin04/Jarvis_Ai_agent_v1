"""
jarvis/devops/watcher.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Background DevOps & Website Watcher.

Runs every few minutes to check:
  1. Each website HTTP response status (flags if down or 4xx/5xx).
  2. SSL certificate expiry date (flags if expiring within threshold days).
  3. New errors appearing in Laravel and Nginx logs.

Proactive Voice Alerts:
  When something goes wrong, the agent speaks up on its own:
    "Alamin, the site is not responding."
    "Alamin, the SSL certificate for mrym_laravel expires in 5 days."
    "Alamin, new errors appeared in the Laravel log on cloudpanel_prod."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests

from jarvis import audio_state, ui_events
from jarvis.devops.config import get_all_servers, get_all_websites, get_watcher_config
from jarvis.devops.ssh_client import execute_remote_command
from jarvis.logger import logger


class BackgroundServerWatcher:
    """
    Background daemon thread monitoring website health, SSL certificates,
    and server error logs.
    """

    def __init__(
        self,
        speak_callback=None,
        interval_seconds: int | None = None,
    ):
        self._speak_cb = speak_callback
        self._cfg = get_watcher_config()
        self._interval = interval_seconds or int(self._cfg.get("interval_seconds", 180))
        self._owner_name = self._cfg.get("owner_name", "Alamin")
        self._ssl_threshold = int(self._cfg.get("ssl_warning_days", 14))
        self._cooldown = int(self._cfg.get("alert_cooldown_seconds", 600))

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_alert_times: dict[str, float] = {}
        self._log_offsets: dict[str, int] = {}

    def start(self) -> None:
        """Start the background monitoring thread."""
        if not self._cfg.get("enabled", True):
            logger.info("[DevOps Watcher] Watcher disabled in configuration.")
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="devops-server-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"[DevOps Watcher] Started monitoring thread (Interval: {self._interval}s, "
            f"Addressee: {self._owner_name}, SSL threshold: {self._ssl_threshold}d)"
        )

    def stop(self) -> None:
        """Signal the background watcher thread to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("[DevOps Watcher] Stopped.")

    def _speak_alert(self, key: str, spoken_text: str) -> None:
        """
        Speak proactive alert aloud, respecting cooldown to prevent alert fatigue.
        """
        now = time.time()
        last = self._last_alert_times.get(key, 0.0)
        if now - last < self._cooldown:
            logger.debug(f"[DevOps Watcher] Suppressed duplicate alert for {key} (in cooldown)")
            return

        self._last_alert_times[key] = now
        logger.warning(f"[DevOps Watcher Alert] Proactive speech: \"{spoken_text}\"")

        # Emit UI alert
        try:
            ui_events.emit("log", text=f"⚠️ {spoken_text}")
        except Exception:
            pass

        if self._speak_cb:
            try:
                self._speak_cb(spoken_text)
            except Exception as exc:
                logger.error(f"[DevOps Watcher] Custom speak error: {exc}")
        else:
            try:
                from jarvis.voice_output import speak
                speak(spoken_text)
            except Exception as exc:
                logger.debug(f"[DevOps Watcher] Default voice speak note: {exc}")

    def check_now(self) -> list[str]:
        """
        Run a single full inspection cycle across all websites and server logs.
        Returns a list of alerts detected.
        """
        websites = get_all_websites()
        alerts: list[str] = []

        for site_name, site in websites.items():
            url = site.get("url", "")
            if not url:
                continue

            # 1. HTTP Website Availability Check
            http_err = self._check_website_http(url)
            if http_err:
                alert_msg = f"{self._owner_name}, the site {site_name} is not responding. {http_err}"
                alerts.append(alert_msg)
                self._speak_alert(f"http:{site_name}", alert_msg)

            # 2. SSL Expiry Check
            ssl_err = self._check_ssl_expiry(url, threshold_days=site.get("ssl_days_threshold", self._ssl_threshold))
            if ssl_err:
                alert_msg = f"{self._owner_name}, {ssl_err}"
                alerts.append(alert_msg)
                self._speak_alert(f"ssl:{site_name}", alert_msg)

            # 3. New Laravel / Nginx Log Errors Check
            server_name = site.get("server")
            laravel_log = site.get("laravel_log_path")
            if server_name and laravel_log:
                log_alert = self._check_new_log_errors(server_name, site_name, laravel_log)
                if log_alert:
                    alert_msg = f"{self._owner_name}, {log_alert}"
                    alerts.append(alert_msg)
                    self._speak_alert(f"log:{site_name}", alert_msg)

        return alerts

    def _check_website_http(self, url: str) -> str | None:
        """Check if site responds with HTTP 2xx or 3xx."""
        try:
            resp = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Jarvis-Server-Watcher/1.0"},
                verify=False,  # allow self-signed or intermediate inspection
            )
            if resp.status_code >= 400:
                return f"HTTP status {resp.status_code}."
            return None
        except requests.exceptions.Timeout:
            return "Connection timed out."
        except requests.exceptions.ConnectionError:
            return "Connection refused."
        except Exception as exc:
            return f"Error: {str(exc)[:50]}."

    def _check_ssl_expiry(self, url: str, threshold_days: int) -> str | None:
        """Inspect SSL certificate expiration date over TLS."""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return None

        hostname = parsed.hostname or parsed.netloc
        port = parsed.port or 443

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # retrieve cert even if self-signed in test

            with socket.create_connection((hostname, port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    if not cert or "notAfter" not in cert:
                        return None

                    # Format: 'May 15 12:00:00 2026 GMT'
                    not_after_str = cert["notAfter"]
                    expires_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                    days_left = (expires_dt - datetime.now()).days

                    if days_left <= threshold_days:
                        return f"the SSL certificate for {hostname} expires in {days_left} days."
            return None
        except Exception:
            # Domain might not be resolvable or port 443 closed
            return None

    def _check_new_log_errors(
        self, server_name: str, site_name: str, log_path: str
    ) -> str | None:
        """Check for new error entries in Laravel log on remote server."""
        cmd = f"tail -n 25 {log_path} 2>/dev/null | grep -E 'ERROR|CRITICAL|Fatal error' | tail -n 1"
        code, out, _ = execute_remote_command(server_name, cmd)

        if code == 0 and out.strip():
            # Check if this error line was already flagged
            last_seen = self._log_offsets.get(f"{server_name}:{log_path}", "")
            cleaned = out.strip()
            if cleaned != last_seen:
                self._log_offsets[f"{server_name}:{log_path}"] = cleaned
                return f"new errors appeared in the Laravel log on {server_name}."

        return None

    def _run_loop(self) -> None:
        """Main daemon loop."""
        while not self._stop_event.is_set():
            try:
                self.check_now()
            except Exception as exc:
                logger.debug(f"[DevOps Watcher] Loop note: {exc}")

            # Sleep in small slices to respond promptly to stop event
            for _ in range(self._interval * 2):
                if self._stop_event.is_set() or audio_state.shutdown.is_set():
                    return
                time.sleep(0.5)


# Global singleton instance
watcher = BackgroundServerWatcher()
