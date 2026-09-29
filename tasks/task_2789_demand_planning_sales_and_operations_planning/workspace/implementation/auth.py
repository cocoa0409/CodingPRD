"""Authentication, authorisation, phase gating and customer scoping.

Ladder positions implemented here (PRD 2.9):
  10 authentication, 20 authorisation, 60 phase actor, 70 customer scope,
  80 segregation of duties, 100 frozen cycle, 110 phase closed.
"""
import functools

from flask import g, request

from errors import ApiError
from store import store

ROLE_SOP_ADMIN = "SopAdmin"
ROLE_DEMAND_PLANNER = "DemandPlanner"
ROLE_DEMAND_REVIEW_LEAD = "DemandReviewLead"
ROLE_SUPPLY_PLANNER = "SupplyPlanner"
ROLE_EXECUTIVE_SPONSOR = "ExecutiveSponsor"
ROLE_CUSTOMER_REP = "CustomerRep"

ALL_ROLES = (
    ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
    ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR, ROLE_CUSTOMER_REP,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

# The role that "owns" each cycle phase. When the acting role owns the phase a
# class of write belongs to, a cycle-status mismatch surfaces as
# ERR_CYCLE_PHASE_CLOSED (priority 110); otherwise it surfaces earlier as
# ERR_UNAUTHORIZED_PHASE_ACTOR (priority 60). PUBLISHED has no owning role,
# which is why an accuracy-record post outside PUBLISHED is always a
# phase-actor rejection.
PHASE_OWNERS = {
    "DEMAND_REVIEW": {ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD},
    "SUPPLY_REVIEW": {ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER},
    "SCENARIO_REVIEW": {ROLE_SUPPLY_PLANNER},
    "EXECUTIVE_REVIEW": {ROLE_EXECUTIVE_SPONSOR},
    "PUBLISHED": set(),
}


def authenticate():
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'" % role)
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Decorator applying steps 10 and 20 of the rejection ladder."""
    allowed = tuple(roles)

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s may not invoke this operation" % g.role,
                )
            return fn(*args, **kwargs)
        return inner
    return wrap


def open_endpoint(fn):
    """The logical-clock capability: exempt from authentication and role checks."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        return fn(*args, **kwargs)
    return inner


# --------------------------------------------------------------------------
# priority 60 / 100 / 110
# --------------------------------------------------------------------------
def check_phase_actor(cycle, required_status):
    """PRD 2.8 step 60.

    This check covers exactly the nine operations PRD 2.8 enumerates, and for
    those nine ANY cycle-status mismatch is a phase-actor rejection regardless
    of the acting role: "An operation belonging to a different phase than the
    cycle currently occupies is rejected with ERR_UNAUTHORIZED_PHASE_ACTOR".
    The role-ownership condition belongs to ERR_CYCLE_PHASE_CLOSED alone, and
    because the phase-actor check sits earlier in the ladder of PRD 2.9 "it
    wins wherever both could apply" -- so phase-closed is reachable only for
    the two writes the actor check omits (forecast create and forecast
    transitions).
    """
    if cycle["status"] == required_status:
        return
    raise ApiError(
        "ERR_UNAUTHORIZED_PHASE_ACTOR",
        "This operation belongs to cycle phase %s, but the cycle is in %s"
        % (required_status, cycle["status"]),
    )


def check_frozen(cycle):
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN", "The planning cycle is frozen")


def check_phase_closed(cycle, required_status):
    if cycle["status"] != required_status:
        raise ApiError(
            "ERR_CYCLE_PHASE_CLOSED",
            "The cycle is in %s; this write is admitted only in %s"
            % (cycle["status"], required_status),
        )


def phase_gate(cycle, required_status, occ=None, phase_actor=True,
               frozen=True, phase_closed=True):
    """Run the phase gates in ladder order: 60, [90 via occ], 100, 110."""
    if phase_actor:
        check_phase_actor(cycle, required_status)
    if occ is not None:
        occ()
    if frozen:
        check_frozen(cycle)
    if phase_closed:
        check_phase_closed(cycle, required_status)


# --------------------------------------------------------------------------
# priority 70 -- CustomerRep scoping
# --------------------------------------------------------------------------
def scope_list_customer():
    """List reads of forecasts, allocations and accuracy records.

    Returns the customer_id filter a CustomerRep is pinned to, or None.
    """
    if g.role != ROLE_CUSTOMER_REP:
        return None
    supplied = request.args.get("customer_id")
    if supplied is None or supplied != g.user_id:
        raise ApiError(
            "ERR_CUSTOMER_SCOPE_VIOLATION",
            "A CustomerRep must filter by its own customer_id",
        )
    return g.user_id


def scope_row_customer(customer_id):
    """Single-resource reads of forecasts, allocations and accuracy records."""
    if g.role != ROLE_CUSTOMER_REP:
        return
    if customer_id != g.user_id:
        raise ApiError(
            "ERR_CUSTOMER_SCOPE_VIOLATION",
            "A CustomerRep may only read rows scoped to its own customer",
        )


# --------------------------------------------------------------------------
# priority 80 -- segregation of duties on X-User-ID
# --------------------------------------------------------------------------
def check_sod(other_user_id, what):
    if other_user_id is not None and g.user_id == other_user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who %s may not also perform this action" % what,
        )


def find_or_404(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id, "Unknown identifier")
    row = getattr(store, collection).get(row_id)
    if row is None:
        raise ApiError(error_id, "No such record: %s" % row_id)
    return row
