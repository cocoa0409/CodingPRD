"""Application actions: approval-decision, withdraw, record-first-marketing."""
from flask import Blueprint

from auth import auth, own_application, require_role
from clock import add_days, today
from domain import (
    award_for_app,
    certified_p4_certs,
    check_carve_out,
    close_current_cycle,
    exclusivity_blocked,
    facility_clearance_ok,
    has_accepted_be,
    has_open_deficiency,
    notice_for_cert,
    patent_blocked_until,
)
from envelope import success_object
from errors import fail
from serialize import application, award
from state import get, touch
from system_eval import forfeit_award
from validate import body, req_enum

bp = Blueprint("app_actions", __name__)


@bp.post("/generic-drug-review/applications/<app_id>/approval-decision")
def approval_decision(app_id):
    _uid, role = auth()
    require_role(role, ["RegulatoryReviewer"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REFUSE"))
    if app["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE",
             "A review decision requires the application to be RECEIVED")
    if has_open_deficiency(app_id):
        fail("ERR_DEFICIENCY_RESPONSE_OPEN",
             "A review cycle stands CRL_ISSUED with no response received")
    t = today()
    if decision == "REFUSE":
        # Refusal is always available; an ELIGIBLE award survives it.
        app["status"] = "REFUSED_APPROVAL"
        close_current_cycle(app, "REFUSAL")
        touch(app)
        return success_object(application(app))
    # APPROVE: scientific gates in PRD 2.7 pipeline order.
    if not has_accepted_be(app_id):
        fail("ERR_NO_ADEQUATE_BE_STUDY",
             "At least one ACCEPTED bioequivalence study is required")
    if not facility_clearance_ok(app_id):
        fail("ERR_FACILITY_CLEARANCE_FAILED",
             "Facility clearance evaluation failed")
    check_carve_out(app)
    for c in certified_p4_certs(app_id):
        if notice_for_cert(c["id"]) is None:
            fail("ERR_P4_NOTICE_REQUIRED",
                 "A CERTIFIED PARAGRAPH_IV_CHALLENGE certification lacks its notice")
    # Patent-side posture: a block reroutes APPROVE to TENTATIVE_APPROVAL.
    if patent_blocked_until(app) is not None or exclusivity_blocked(app):
        app["status"] = "TENTATIVE_APPROVAL"
        app["tentative_approval_date"] = t.isoformat()
        close_current_cycle(app, "TENTATIVE_APPROVAL")
        touch(app)
        return success_object(application(app))
    app["status"] = "APPROVED"
    app["approval_date"] = t.isoformat()
    close_current_cycle(app, "APPROVAL")
    aw = award_for_app(app_id)
    if aw is not None and aw["status"] == "ELIGIBLE":
        aw["status"] = "AWARDED"
        aw["awarded_date"] = t.isoformat()
        aw["approval_date"] = t.isoformat()
        aw["marketing_deadline"] = add_days(t, 75).isoformat()
        touch(aw)
    touch(app)
    return success_object(application(app))


@bp.post("/generic-drug-review/applications/<app_id>/withdraw")
def withdraw_application(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    st = app["status"]
    if st not in ("DRAFT", "RECEIVED", "TENTATIVE_APPROVAL", "APPROVED"):
        fail("ERR_INVALID_STATE",
             "A terminal application cannot be withdrawn")
    app["status"] = "WITHDRAWN"
    aw = award_for_app(app_id)
    if st == "RECEIVED":
        close_current_cycle(app, "SUPERSEDED")
        if aw is not None and aw["status"] in ("ELIGIBLE", "AWARDED"):
            forfeit_award(aw, "APPLICATION_WITHDRAWN")
    elif st == "TENTATIVE_APPROVAL":
        if aw is not None and aw["status"] in ("ELIGIBLE", "AWARDED"):
            forfeit_award(aw, "APPLICATION_WITHDRAWN")
    elif st == "APPROVED":
        if aw is not None and aw["status"] in ("AWARDED", "ACTIVE"):
            forfeit_award(aw, "APPLICATION_WITHDRAWN")
    # DRAFT: a clean exit with no cascade.
    touch(app)
    return success_object(application(app))


@bp.post("/generic-drug-review/applications/<app_id>/record-first-marketing")
def record_first_marketing(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    aw = award_for_app(app_id)
    if app["status"] != "APPROVED":
        fail("ERR_INVALID_STATE",
             "First marketing requires an APPROVED application")
    if aw is None or aw["status"] != "AWARDED":
        fail("ERR_INVALID_STATE",
             "First marketing requires this application's award to be AWARDED")
    t = today()
    app["first_marketing_date"] = t.isoformat()
    aw["first_marketing_date"] = t.isoformat()
    aw["exclusivity_end_date"] = add_days(t, 180).isoformat()
    aw["status"] = "ACTIVE"
    touch(aw)
    touch(app)
    return success_object(award(aw))
