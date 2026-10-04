"""Auth, RBAC, existence fetchers, and shared rule predicates.

Validation priority (PRD 2.6): 1 authentication -> 2 authorization ->
3 entity-backed ownership -> 4 existence -> 5 state preconditions -> business
rules in their numbered order. Handlers call auth_context() then
require_roles() first; ownership and existence helpers come next.
"""

from flask import request

from constants import (
    AFP_RATE_MAX,
    AFP_RATE_MIN,
    GDP_RATE_MAX,
    GDP_RATE_MIN,
    ROLES,
)
from errors import ApiError
from storage import DB


# --- Priority 1-2: authentication / authorization ------------------------------
def auth_context():
    """Validate X-User-ID and X-User-Role; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(*roles):
    role = request.headers.get("X-User-Role")
    if role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "role %s is not permitted on this endpoint" % role
        )


# --- Priority 4: existence fetchers ---------------------------------------------
def get_facility(facility_id):
    rec = DB["facilities"].get(facility_id)
    if rec is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND", "facility %s not found" % facility_id)
    return rec


def get_operator(operator_id):
    rec = DB["operators"].get(operator_id)
    if rec is None:
        raise ApiError("ERR_OPERATOR_NOT_FOUND", "operator %s not found" % operator_id)
    return rec


def get_tmi(tmi_id):
    rec = DB["tmis"].get(tmi_id)
    if rec is None:
        raise ApiError("ERR_TMI_NOT_FOUND", "tmi %s not found" % tmi_id)
    return rec


def get_flight(flight_id):
    rec = DB["flights"].get(flight_id)
    if rec is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", "flight %s not found" % flight_id)
    return rec


def get_event(event_id):
    rec = DB["constraint_events"].get(event_id)
    if rec is None:
        raise ApiError(
            "ERR_CONSTRAINT_EVENT_NOT_FOUND", "constraint event %s not found" % event_id
        )
    return rec


def get_forecast(forecast_id):
    rec = DB["forecasts"].get(forecast_id)
    if rec is None:
        raise ApiError("ERR_FORECAST_NOT_FOUND", "forecast %s not found" % forecast_id)
    return rec


def get_ga_request(request_id):
    rec = DB["ga_requests"].get(request_id)
    if rec is None:
        raise ApiError(
            "ERR_GA_REQUEST_NOT_FOUND", "GA request %s not found" % request_id
        )
    return rec


def get_reroute(assignment_id):
    rec = DB["reroutes"].get(assignment_id)
    if rec is None:
        raise ApiError(
            "ERR_REROUTE_ASSIGNMENT_NOT_FOUND",
            "reroute assignment %s not found" % assignment_id,
        )
    return rec


# --- Shared predicates -----------------------------------------------------------
def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap (PRD 2.9): adjacency (a_end == b_start) is NOT overlap."""
    return a_start < b_end and b_start < a_end


def check_window(start, end):
    """Priority 8: every windowed create/extend requires start < end."""
    if not (start < end):
        raise ApiError(
            "ERR_INVALID_WINDOW", "window start must be strictly before window end"
        )


def check_gdp_rate(rate):
    """GROUND_DELAY_PROGRAM rate shape: 6 <= r <= 60 and 3600 % r == 0."""
    if rate is None:
        rate = 0
    if not (GDP_RATE_MIN <= rate <= GDP_RATE_MAX and 3600 % rate == 0):
        raise ApiError(
            "ERR_INVALID_RATE",
            "GROUND_DELAY_PROGRAM controlled_rate must be an integer in [6, 60] "
            "that divides 3600 exactly",
        )


def check_rate_shape(tmi_type, rate):
    """Priority 15: per-type controlled_rate format. REROUTE rates are ignored
    (stored 0) so no check applies to them."""
    if tmi_type == "GROUND_DELAY_PROGRAM":
        check_gdp_rate(rate)
    elif tmi_type == "AIRSPACE_FLOW_PROGRAM":
        if not (AFP_RATE_MIN <= rate <= AFP_RATE_MAX):
            raise ApiError(
                "ERR_INVALID_RATE",
                "AIRSPACE_FLOW_PROGRAM controlled_rate must be an integer in [1, 60]",
            )
    elif tmi_type == "GROUND_STOP":
        if rate != 0:
            raise ApiError(
                "ERR_INVALID_RATE", "GROUND_STOP controlled_rate must be 0"
            )


def tmi_terminal_guard(tmi):
    """Any action on a CANCELLED or COMPLETED TMI (PRD 2.6 rule 5)."""
    if tmi["status"] in ("CANCELLED", "COMPLETED"):
        raise ApiError(
            "ERR_TMI_TERMINAL", "TMI %s is %s" % (tmi["id"], tmi["status"])
        )


def tmi_require_active(tmi):
    """Substitutions, compression runs, GA adjudication, reroute assignment and
    revision creation all require an ACTIVE TMI."""
    tmi_terminal_guard(tmi)
    if tmi["status"] != "ACTIVE":
        raise ApiError("ERR_TMI_NOT_ACTIVE", "TMI %s is not ACTIVE" % tmi["id"])
