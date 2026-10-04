"""Wellness check resolution (SafetyOfficer only; notes required)."""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
from constants import WELLNESS_STATUSES

bp = Blueprint("wellness", __name__)


@bp.patch("/vdr/wellness-checks/<wid>")
def patch_wellness_check(wid):
    body = V.get_body()
    V.check_unknown(body, {"status", "resolved_notes"})
    target = V.req_enum(body, "status", WELLNESS_STATUSES)
    notes = V.opt_str(body, "resolved_notes", None)
    auth.require_roles("SafetyOfficer")
    check = db.get("wellness_checks", wid)
    if check is None:
        errors.wellness_check_not_found()
    if target != "RESOLVED":
        errors.invalid_state("a wellness check can only be resolved")
    if check["status"] != "OPEN":
        errors.invalid_state("the wellness check is already resolved")
    if not notes:
        errors.validation("resolving a wellness check requires non-empty resolved_notes")
    check["status"] = "RESOLVED"
    check["resolved_notes"] = notes
    db.touch(check)
    return envelope.ok(domain.public(check))
