"""Logical-clock test-driving endpoints (PRD §2.5)."""
from core import auth, clock, scheduled
from core.auth import require_field
from core.errors import ERR_INVALID_ADVANCE_DAYS, fail
from .common import single


def register(app):

    @app.post("/servicing/_clock/set_current_utc")
    def set_current_utc():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        to_iso8601 = require_field(payload, "to_iso8601", "string")
        try:
            clock.set_current(to_iso8601)
        except ValueError:
            raise fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
        return single({})

    @app.post("/servicing/_clock/advance")
    def advance_clock():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        days = require_field(payload, "days", "int")
        if days < clock.CLOCK_MIN_ADVANCE_DAYS or days > clock.CLOCK_MAX_ADVANCE_DAYS:
            raise fail(ERR_INVALID_ADVANCE_DAYS,
                       "days must be a whole-day count between 1 and 3650 inclusive.")
        window_start = clock.now()
        window_end = clock.add_days(days)
        scheduled.run_due_effects(window_start, window_end)
        return single({"current_utc": clock.now_iso(), "advanced_days": days})