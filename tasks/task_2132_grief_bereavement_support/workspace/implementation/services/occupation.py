"""Meeting-space occupation clash detection (§3.3).

Closed-interval arithmetic: the room's turnover buffer is applied to the
incoming occupation on both sides, and both comparisons are non-strict, so a
gap of exactly the buffer still collides.
"""

from core import calc
from core.errors import ApiError
from core.shape import parse_date
from core.store import store

LIVE_COHORT_STATES = {"FORMING", "OPEN_ENROLLMENT", "UNDERSUBSCRIBED", "RUNNING", "SUSPENDED"}
LIVE_EVENT_STATES = {"PLANNED", "CONFIRMED"}


def _conflict():
    raise ApiError("ERR_SPACE_TIME_CONFLICT",
                   "The requested slot collides with an existing occupation of this space.")


def check_cohort(space, weekday, series_start, series_end, start_minute, duration):
    buffer_minutes = space["turnover_buffer_minutes"]
    for other in store.find("Cohort", meeting_space_id=space["id"]):
        if other["status"] not in LIVE_COHORT_STATES:
            continue
        o_start = parse_date(other["series_start_date"], "series_start_date")
        o_end = parse_date(other["series_end_date"], "series_end_date")
        if not calc.dates_intersect_cohorts(series_start, series_end, weekday,
                                            o_start, o_end, other["weekday"]):
            continue
        if calc.minutes_collide(start_minute, duration,
                                other["start_minute_utc"], other["duration_minutes"],
                                buffer_minutes):
            _conflict()
    for event in store.find("RemembranceEvent", meeting_space_id=space["id"]):
        if event["status"] not in LIVE_EVENT_STATES:
            continue
        e_date = parse_date(event["event_date"], "event_date")
        if not calc.dates_intersect_cohort_event(series_start, series_end, weekday, e_date):
            continue
        if calc.minutes_collide(start_minute, duration,
                                event["start_minute_utc"], event["duration_minutes"],
                                buffer_minutes):
            _conflict()


def check_event(space, event_date, start_minute, duration):
    buffer_minutes = space["turnover_buffer_minutes"]
    for cohort in store.find("Cohort", meeting_space_id=space["id"]):
        if cohort["status"] not in LIVE_COHORT_STATES:
            continue
        c_start = parse_date(cohort["series_start_date"], "series_start_date")
        c_end = parse_date(cohort["series_end_date"], "series_end_date")
        if not calc.dates_intersect_cohort_event(c_start, c_end, cohort["weekday"], event_date):
            continue
        if calc.minutes_collide(start_minute, duration,
                                cohort["start_minute_utc"], cohort["duration_minutes"],
                                buffer_minutes):
            _conflict()
    for other in store.find("RemembranceEvent", meeting_space_id=space["id"]):
        if other["status"] not in LIVE_EVENT_STATES:
            continue
        if parse_date(other["event_date"], "event_date") != event_date:
            continue
        if calc.minutes_collide(start_minute, duration,
                                other["start_minute_utc"], other["duration_minutes"],
                                buffer_minutes):
            _conflict()
