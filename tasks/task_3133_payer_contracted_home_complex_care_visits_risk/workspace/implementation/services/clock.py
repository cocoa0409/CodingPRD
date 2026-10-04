"""Logical clock service per PRD §2.4.

The server maintains a logical UTC clock initialized to 2026-09-01T00:00:00Z.
It MUST NOT fall back to real wall-clock time before the operator first drives
it. Business timestamps (triggered_at, on_scene_at, actual_start/end, etc.)
are read from this clock.
"""
from datetime import datetime, timezone, timedelta

from db import db
from errors import err_input, ERR_INVALID_REQUEST


def now_clock():
    """Return the current logical clock as a timezone-aware UTC datetime."""
    return db.clock


def now_iso():
    return fmt_ts(db.clock)


def fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_ts(value, field="timestamp"):
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise err_input(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
    s = value.strip()
    if not s:
        raise err_input(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_input(ERR_INVALID_REQUEST, "%s must be a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


def advance_clock_hours(by_hours):
    db.clock = db.clock + timedelta(hours=by_hours)


def sweep_episode_lapses():
    """Lapse any TRIGGERED or DISPATCHED episode whose sla_deadline has passed.

    Per PRD §3.6: TRIGGERED/DISPATCHED → LAPSED sets sla_met = false and
    recomputes composite_score; a lapse from DISPATCHED also decrements the
    dispatched clinician's active_daily_visit_count.
    """
    from services.measurements import recompute_composite
    from services.resources import touch

    now = db.clock
    for ep in db.episodes.values():
        if ep["status"] not in ("TRIGGERED", "DISPATCHED"):
            continue
        deadline = parse_ts(ep["sla_deadline"])
        if deadline is None:
            continue
        if now > deadline:
            was_dispatched = ep["status"] == "DISPATCHED"
            ep["status"] = "LAPSED"
            ep["sla_met"] = False
            if was_dispatched and ep.get("dispatched_clinician_id"):
                clin = db.clinicians.get(ep["dispatched_clinician_id"])
                if clin is not None:
                    clin["active_daily_visit_count"] = max(
                        0, clin["active_daily_visit_count"] - 1)
                    touch(clin)
            touch(ep)
            m = find_measurement_for_episode(ep)
            if m is not None:
                recompute_composite(m)


def find_measurement_for_episode(ep):
    from services.measurements import find_measurement
    member = db.members.get(ep.get("member_id"))
    if member is None:
        return None
    program = db.care_programs.get(member.get("care_program_id"))
    period = program["current_period_index"] if program else 0
    return find_measurement(member.get("payer_contract_id"), member["id"], period)
