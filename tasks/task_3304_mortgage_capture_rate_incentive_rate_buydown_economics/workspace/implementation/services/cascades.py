"""State-machine side effects and the multi-layer cascades.

Every function here is called from a route after the request has cleared its
validation ladder, so each one performs the documented transition plus its
side effects; illegal source states are handled by the callers.
"""

from db import db, now_iso, parse_iso, plus_days, format_iso
from errors import fail
from services import common, calc, selectors

BUYER_ALLOWED = {
    "PROSPECT": {"CONTRACTED", "WITHDRAWN"},
    "CONTRACTED": {"QUALIFIED", "WITHDRAWN"},
    "QUALIFIED": {"CONTRACTED", "WITHDRAWN"},
    "WITHDRAWN": {"CONTRACTED"},
}


def set_buyer_status(buyer, target):
    """Apply a bubble-up buyer transition when one is declared for the source state."""
    if buyer is None:
        return None
    current = buyer.get("buyer_status")
    if current == target:
        return buyer
    if target not in BUYER_ALLOWED.get(current, set()):
        return buyer
    buyer["buyer_status"] = target
    common.touch(buyer)
    return buyer


def buyer_of_contract(contract):
    return db.buyers.get(contract.get("buyer_id"))


def buyer_has_live_application(buyer_id):
    for app in db.loan_applications.values():
        if app.get("application_status") in ("SUBMITTED", "QUALIFIED"):
            contract = db.contracts.get(app.get("contract_id"))
            if contract is not None and contract.get("buyer_id") == buyer_id:
                return True
    return False


def refresh_buyer(buyer):
    if buyer is None:
        return None
    common.recompute_buyer_total(buyer)
    common.recompute_steering_protection(buyer)
    common.touch(buyer)
    return buyer


def refresh_community_for_contract(contract):
    community = common.community_of(contract)
    if community is not None:
        calc.capture_rate_realization(community)
        common.touch(community)
    return community


# ---------------------------------------------------------------------------
# Forward-commitment unit ledger
# ---------------------------------------------------------------------------
def draw_unit(commitment):
    commitment["units_drawn"] = int(commitment.get("units_drawn") or 0) + 1
    common.recompute_commitment_counters(commitment)
    if commitment["units_available"] <= 0 and commitment.get("commitment_status") == "OPEN":
        commitment["commitment_status"] = "EXHAUSTED"
    common.touch(commitment)
    return commitment


def release_unit(commitment):
    commitment["units_released"] = int(commitment.get("units_released") or 0) + 1
    common.recompute_commitment_counters(commitment)
    if commitment.get("commitment_status") == "EXHAUSTED":
        commitment["commitment_status"] = "OPEN"
    common.touch(commitment)
    return commitment


def force_waiver_refused(application):
    """Void an application's waiver track (declared REQUESTED -> REFUSED edge)."""
    if application is None:
        return None
    if application.get("lock_waiver_status") == "REQUESTED":
        application["lock_waiver_status"] = "REFUSED"
        application["uw_precedence"] = "%s_%s" % (
            application.get("application_status"),
            application.get("lock_waiver_status"),
        )
        common.touch(application)
    return application