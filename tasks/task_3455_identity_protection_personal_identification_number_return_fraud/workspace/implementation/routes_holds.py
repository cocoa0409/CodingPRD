"""FilterHold routes: mark-false-positive (the false-positive-burden release)."""
from flask import Blueprint

from auth import require_roles
from domain import get_hold, pub, touch
from envelope import ok
from errors import err
from store import DB

bp = Blueprint("holds", __name__)


@bp.post("/identity-protection/filter-holds/<string:hold_id>/mark-false-positive")
def mark_false_positive(hold_id):
    require_roles(["FraudAnalyst"])
    hold = get_hold(hold_id)
    # RESOLVED_* holds are non-terminal (PRD §2.10): wrong state -> 409 INVALID_STATE.
    if hold["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Only an OPEN hold can be marked as a false positive.")
    hold["status"] = "RESOLVED_FALSE_POSITIVE"
    touch(hold)
    ret = DB.returns.get(hold["return_id"])
    if ret is not None and ret["status"] == "FILTER_HELD":
        ret["status"] = "FILTER_PASSED"
        touch(ret)
    return ok(pub(hold))
