"""Path/body identifier resolution (rungs 3 and 6) and list scoping."""
from flask import request

from errors import ApiError
from store import store

_TABLES = (
    ("home_school", "home_schools", "ERR_HOME_SCHOOL_NOT_FOUND"),
    ("center", "centers", "ERR_CENTER_NOT_FOUND"),
    ("student", "students", "ERR_STUDENT_NOT_FOUND"),
    ("course", "courses", "ERR_COURSE_NOT_FOUND"),
    ("prior_record", "prior_records", "ERR_PRIOR_RECORD_NOT_FOUND"),
    ("referral", "referrals", "ERR_REFERRAL_NOT_FOUND"),
    ("placement", "placements", "ERR_PLACEMENT_NOT_FOUND"),
    ("enrollment", "enrollments", "ERR_ENROLLMENT_NOT_FOUND"),
    ("award", "awards", "ERR_AWARD_NOT_FOUND"),
    ("plan", "plans", "ERR_PLAN_NOT_FOUND"),
    ("station", "stations", "ERR_STATION_NOT_FOUND"),
    ("proctor_session", "proctor_sessions", "ERR_SESSION_NOT_FOUND"),
    ("provider", "providers", "ERR_PROVIDER_NOT_FOUND"),
    ("support_session", "support_sessions", "ERR_SUPPORT_SESSION_NOT_FOUND"),
)


def _fetch(table, error_id, row_id):
    row = getattr(store, table).get(row_id)
    if row is None:
        raise ApiError(error_id, "%s does not exist" % row_id)
    return row


def _make(name, table, error_id):
    def getter(row_id):
        return _fetch(table, error_id, row_id)
    getter.__name__ = "get_" + name
    return getter


get_home_school = _make(*_TABLES[0])
get_center = _make(*_TABLES[1])
get_student = _make(*_TABLES[2])
get_course = _make(*_TABLES[3])
get_prior_record = _make(*_TABLES[4])
get_referral = _make(*_TABLES[5])
get_placement = _make(*_TABLES[6])
get_enrollment = _make(*_TABLES[7])
get_award = _make(*_TABLES[8])
get_plan = _make(*_TABLES[9])
get_station = _make(*_TABLES[10])
get_proctor_session = _make(*_TABLES[11])
get_provider = _make(*_TABLES[12])
get_support_session = _make(*_TABLES[13])


# ---- list query filters ----------------------------------------------
def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_int(name):
    value = q(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def q_bool(name):
    value = q(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be true or false" % name)


def eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r[field] == value]
