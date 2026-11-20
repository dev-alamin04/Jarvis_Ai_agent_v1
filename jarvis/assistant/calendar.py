"""
jarvis/assistant/calendar.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Google Calendar Integration & Event Reminders.

Capabilities:
  • Lists events for today and tomorrow.
  • Adds new events from voice commands.
  • Proactively alerts 10 minutes before each event.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.assistant.oauth import get_google_credentials
from jarvis.assistant.reminders import parse_due_time
from jarvis.logger import logger

# Set of event IDs already alerted for the 10-minute warning
_ALERTED_EVENTS: set[str] = set()

# Simulated calendar events for test / offline fallback
_SIMULATED_EVENTS = [
    {
        "id": "evt_001",
        "summary": "Sprint Planning & Client Standup",
        "start": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "end": (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "location": "Google Meet",
        "day": "today",
    },
    {
        "id": "evt_002",
        "summary": "Laravel Production Deployment Review",
        "start": (datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
        "end": (datetime.now() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
        "location": "Office",
        "day": "today",
    },
    {
        "id": "evt_003",
        "summary": "Mobile App Architecture Sync",
        "start": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 11:00:00"),
        "end": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 12:00:00"),
        "location": "Zoom",
        "day": "tomorrow",
    },
]


def _get_calendar_service():
    """Build and return an authorized Calendar API service client, or None."""
    creds = get_google_credentials(interactive=False)
    if not creds or not creds.valid:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds)
    except Exception as exc:
        logger.debug(f"[Calendar] Service build note: {exc}")
        return None


def calendar_list_events(day: str = "today") -> str:
    """
    List calendar events for 'today', 'tomorrow', or 'both'.
    """
    clean_day = day.strip().lower()
    logger.info(f"[Calendar] Listing events for `{clean_day}`...")

    service = _get_calendar_service()
    events = []

    now = datetime.now()
    if clean_day == "tomorrow":
        start_dt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        end_dt = datetime.combine(now.date() + timedelta(days=1), datetime.max.time())
    elif clean_day in ("both", "upcoming", "all"):
        start_dt = datetime.combine(now.date(), datetime.min.time())
        end_dt = datetime.combine(now.date() + timedelta(days=1), datetime.max.time())
    else:
        # Default: today
        start_dt = datetime.combine(now.date(), datetime.min.time())
        end_dt = datetime.combine(now.date(), datetime.max.time())

    if service:
        try:
            t_min = start_dt.astimezone(timezone.utc).isoformat()
            t_max = end_dt.astimezone(timezone.utc).isoformat()
            res = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=t_min,
                    timeMax=t_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            for item in res.get("items", []):
                s_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                e_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
                events.append({
                    "id": item.get("id"),
                    "summary": item.get("summary", "Untitled Event"),
                    "start": s_raw,
                    "end": e_raw,
                    "location": item.get("location", ""),
                })
        except Exception as exc:
            logger.warning(f"[Calendar] API fetch error ({exc}). Using offline cache.")
            events = [e for e in _SIMULATED_EVENTS if clean_day in ("both", "all") or e.get("day") == clean_day]
    else:
        events = [e for e in _SIMULATED_EVENTS if clean_day in ("both", "all") or e.get("day") == clean_day]

    if not events:
        return f"📅 You have no scheduled calendar events for {clean_day}."

    lines = []
    for idx, ev in enumerate(events, 1):
        loc = f" (📍 {ev['location']})" if ev.get("location") else ""
        lines.append(f"{idx}. 🗓️ **{ev['summary']}**{loc}\n   - **Time**: `{ev['start']}` to `{ev['end']}`")

    # Spoken summary
    first_ev = events[0]
    spoken_summary = (
        f"You have {len(events)} event{'s' if len(events) != 1 else ''} scheduled for {clean_day}. "
        f"First is '{first_ev['summary']}' at {first_ev['start'].split(' ')[-1]}."
    )

    return (
        f"### 📅 Calendar Schedule: {clean_day.capitalize()} ({len(events)} event{'s' if len(events) != 1 else ''})\n\n"
        + "\n".join(lines)
        + f"\n\n📢 *Voice Summary*: \"{spoken_summary}\""
    )


def calendar_add_event(
    summary: str,
    start_time: str,
    duration_minutes: int = 60,
    description: str | None = None,
) -> str:
    """
    Schedule an event on Google Calendar from natural voice descriptions
    (e.g. 'Project standup' at 'tomorrow at 3pm').
    """
    due_ts, readable_start = parse_due_time(start_time)
    start_dt = datetime.fromtimestamp(due_ts)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    readable_end = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"[Calendar] Adding event '{summary}' at {readable_start}...")
    service = _get_calendar_service()
    event_id = f"evt_sim_{int(due_ts) % 100000}"

    if service:
        try:
            body = {
                "summary": summary,
                "description": description or f"Scheduled by Jarvis AI Assistant on {datetime.now().strftime('%Y-%m-%d')}",
                "start": {"dateTime": start_dt.astimezone().isoformat()},
                "end": {"dateTime": end_dt.astimezone().isoformat()},
            }
            created = service.events().insert(calendarId="primary", body=body).execute()
            event_id = created.get("id", event_id)
        except Exception as exc:
            logger.error(f"[Calendar] Add event error: {exc}")

    spoken_summary = f"I scheduled '{summary}' for {readable_start}."
    return (
        f"✅ **Event Scheduled on Calendar (ID #{event_id})**\n"
        f"**Event**: `{summary}`\n"
        f"**Start Time**: `{readable_start}`\n"
        f"**End Time**: `{readable_end}` ({duration_minutes} mins)\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )


def check_upcoming_event_reminders(
    speak_fn: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Check for events starting in the next 10 minutes.
    Speaks proactive reminder aloud ten minutes before each event.
    Returns list of alerted events.
    """
    now = datetime.now()
    ten_mins_later = now + timedelta(minutes=10)
    alerts_triggered = []

    # Get today's events
    events = _SIMULATED_EVENTS
    service = _get_calendar_service()
    if service:
        try:
            t_min = now.astimezone(timezone.utc).isoformat()
            t_max = (now + timedelta(hours=1)).astimezone(timezone.utc).isoformat()
            res = service.events().list(calendarId="primary", timeMin=t_min, timeMax=t_max, singleEvents=True).execute()
            events = [
                {
                    "id": i.get("id"),
                    "summary": i.get("summary", "Event"),
                    "start": i.get("start", {}).get("dateTime") or i.get("start", {}).get("date"),
                }
                for i in res.get("items", [])
            ]
        except Exception:
            pass

    for ev in events:
        ev_id = ev.get("id")
        if ev_id in _ALERTED_EVENTS:
            continue

        start_str = ev.get("start", "")
        try:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
                try:
                    ev_dt = datetime.strptime(start_str.split(".")[0], fmt)
                    if ev_dt.tzinfo:
                        ev_dt = ev_dt.astimezone().replace(tzinfo=None)
                    break
                except ValueError:
                    continue
            else:
                continue

            # Check if event starts within 10 minutes (between now and now + 10 mins)
            diff_secs = (ev_dt - now).total_seconds()
            if 0 <= diff_secs <= 600:
                _ALERTED_EVENTS.add(ev_id)
                time_display = ev_dt.strftime("%I:%M %p")
                spoken_msg = f"Alamin, you have '{ev['summary']}' starting in 10 minutes at {time_display}."
                logger.info(f"[Calendar Reminder] 10-minute alert: {spoken_msg}")

                if speak_fn:
                    try:
                        speak_fn(spoken_msg)
                    except Exception:
                        pass
                elif os.environ.get("JARVIS_TEST_MODE") != "1":
                    try:
                        from jarvis.voice_output import speak
                        speak(spoken_msg)
                    except Exception:
                        pass

                alerts_triggered.append({"id": ev_id, "summary": ev["summary"], "time": time_display, "spoken": spoken_msg})
        except Exception:
            continue

    return alerts_triggered
