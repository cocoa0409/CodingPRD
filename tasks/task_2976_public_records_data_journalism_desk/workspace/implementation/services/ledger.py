"""Fee ledger and derived security posture (PRD sections 2.7 and 2.9)."""
import db
from errors import ApiError

TOTAL = "fee_budget_total_cents"
AVAILABLE = "fee_budget_available_cents"
COMMITTED = "fee_budget_committed_cents"
SPENT = "fee_budget_spent_cents"

POSTURE_OPEN = "OPEN"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_LOCKDOWN = "LOCKDOWN"

CLOSED_REQUEST_STATUSES = ("RELEASED", "LITIGATION_AUTHORIZED", "WITHDRAWN")


def check_commit(desk, amount):
    """Rung 38: a commit strictly greater than the available column is refused
    and nothing at all is written."""
    if amount > desk[AVAILABLE]:
        raise ApiError(
            "ERR_FEE_BUDGET_EXCEEDED",
            "Commit of %d cents exceeds the available budget of %d cents." % (amount, desk[AVAILABLE]),
        )


def commit(desk, amount):
    check_commit(desk, amount)
    desk[AVAILABLE] -= amount
    desk[COMMITTED] += amount


def settle(desk, amount):
    desk[COMMITTED] -= amount
    desk[SPENT] += amount


def release(desk, amount):
    desk[COMMITTED] -= amount
    desk[AVAILABLE] += amount


def adjust(desk, delta):
    desk[TOTAL] += delta
    desk[AVAILABLE] += delta


def recompute_posture(desk):
    """First match wins: source exposure, then litigation exposure, else open."""
    if desk["source_exposure_incident_count"] >= 1:
        desk["security_posture"] = POSTURE_LOCKDOWN
    elif desk["litigation_exposure_count"] >= 1:
        desk["security_posture"] = POSTURE_RESTRICTED
    else:
        desk["security_posture"] = POSTURE_OPEN
    return desk["security_posture"]


def recount_open_requests(desk):
    rows = db.children("records_requests", "desk_id", desk["id"])
    desk["open_request_count"] = len(
        [r for r in rows if r["status"] not in CLOSED_REQUEST_STATUSES]
    )
    return desk["open_request_count"]


def recount_open_appeals(desk):
    total = 0
    for req in db.children("records_requests", "desk_id", desk["id"]):
        for appeal in db.appeals_of_request(req["id"]):
            if appeal["status"] == "FILED":
                total += 1
    desk["open_appeal_count"] = total
    return total
