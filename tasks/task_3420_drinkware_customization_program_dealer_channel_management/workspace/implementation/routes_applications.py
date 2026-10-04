"""Dealer authorization applications: the fork-join of the inspection leg
(FieldInspector) and the documents leg (ChannelManager), joined at decide."""
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import inspector_schedule_conflict
from constants import BRAND_SCORE_THRESHOLD
from envelope import (
    get_body, new_entity, req_bool, req_dt, req_enum, req_int, req_str,
    req_str_array, sort_created, success, success_list, touch,
)
from errors import fail
from serialize import ser_application
from store import DB, get_clock

bp = Blueprint("applications", __name__)


def load_application(app_id):
    a = DB.applications.get(app_id)
    if a is None:
        fail("ERR_APPLICATION_NOT_FOUND", "no dealer application with id %s" % app_id)
    return a


@bp.post("/drinkware/dealer-applications")
def create_application():
    _, role = context()
    require_roles(role, ["ChannelManager"])
    body = get_body()
    dealer_id = req_str(body, "dealer_id")
    has_storefront = req_bool(body, "has_physical_storefront")
    sqft = req_int(body, "storefront_sqft", minimum=1)
    document_refs = req_str_array(body, "document_refs")
    dealer = DB.dealers.get(dealer_id)
    if dealer is None:
        fail("ERR_DEALER_NOT_FOUND", "no dealer with id %s" % dealer_id)
    for existing in DB.applications.values():
        if (existing["dealer_id"] == dealer_id
                and existing["status"] in ("SUBMITTED", "VETTING")):
            fail("ERR_APPLICATION_ALREADY_OPEN",
                 "the dealer already has an open application")
    app = new_entity({
        "dealer_id": dealer_id,
        "has_physical_storefront": has_storefront,
        "storefront_sqft": sqft,
        "document_refs": document_refs,
        "status": "SUBMITTED",
        "inspection_status": "UNSCHEDULED",
        "docs_status": "PENDING",
        "inspector_user_id": None,
        "inspection_window_start": None,
        "inspection_window_end": None,
        "brand_presentation_score": None,
        "inspection_recorded_by": None,
        "docs_reviewed_by": None,
        "decision_reason": None,
    })
    DB.applications[app["id"]] = app
    return success(ser_application(app), 201)


@bp.get("/drinkware/dealer-applications/<app_id>")
def get_application(app_id):
    uid, role = context()
    require_roles(role, ["ChannelManager", "FieldInspector", "Dealer"])
    app = load_application(app_id)
    if role == "Dealer" and app["dealer_id"] != uid:
        forbidden("Dealer role may read only its own dealer's applications")
    return success(ser_application(app))


@bp.get("/drinkware/dealer-applications")
def list_applications():
    _, role = context()
    require_roles(role, ["ChannelManager", "FieldInspector"])
    dealer_id = request.args.get("dealer_id")
    status = request.args.get("status")
    items = sort_created(list(DB.applications.values()))
    if dealer_id is not None:
        items = [a for a in items if a["dealer_id"] == dealer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return success_list([ser_application(a) for a in items])


@bp.post("/drinkware/dealer-applications/<app_id>/schedule-inspection")
def schedule_inspection(app_id):
    uid, role = context()
    require_roles(role, ["FieldInspector"])
    app = load_application(app_id)
    body = get_body()
    inspector_user_id = req_str(body, "inspector_user_id")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    if inspector_user_id != uid:
        forbidden("inspector_user_id must equal the acting inspector")
    if app["status"] not in ("SUBMITTED", "VETTING") or app["inspection_status"] != "UNSCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "application is not open for inspection scheduling")
    if inspector_schedule_conflict(inspector_user_id, window_start, window_end):
        fail("ERR_INSPECTOR_SCHEDULE_CONFLICT",
             "window collides with another scheduled inspection (closed-interval overlap or < 60-minute travel buffer)")
    app["inspector_user_id"] = inspector_user_id
    app["inspection_window_start"] = window_start
    app["inspection_window_end"] = window_end
    app["inspection_status"] = "SCHEDULED"
    if app["status"] == "SUBMITTED":
        app["status"] = "VETTING"
    touch(app)
    return success(ser_application(app))


@bp.post("/drinkware/dealer-applications/<app_id>/record-inspection")
def record_inspection(app_id):
    uid, role = context()
    require_roles(role, ["FieldInspector"])
    app = load_application(app_id)
    if app["inspector_user_id"] != uid:
        forbidden("only the assigned inspector may record this inspection")
    body = get_body()
    outcome = req_enum(body, "outcome", ("PASSED", "FAILED"))
    score = req_int(body, "brand_presentation_score", minimum=0, maximum=100)
    if app["inspection_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "no inspection is currently scheduled")
    if get_clock() < app["inspection_window_end"]:
        fail("ERR_INSPECTION_WINDOW_NOT_REACHED",
             "the inspection outcome may be recorded only once the window has ended")
    app["inspection_status"] = outcome
    app["brand_presentation_score"] = score
    app["inspection_recorded_by"] = uid
    touch(app)
    return success(ser_application(app))


@bp.post("/drinkware/dealer-applications/<app_id>/verify-documents")
def verify_documents(app_id):
    uid, role = context()
    require_roles(role, ["ChannelManager"])
    app = load_application(app_id)
    body = get_body()
    outcome = req_enum(body, "outcome", ("VERIFIED", "REJECTED"))
    if app["status"] not in ("SUBMITTED", "VETTING") or app["docs_status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "application is not open for document verification")
    app["docs_status"] = outcome
    app["docs_reviewed_by"] = uid
    if app["status"] == "SUBMITTED":
        app["status"] = "VETTING"
    touch(app)
    return success(ser_application(app))


@bp.post("/drinkware/dealer-applications/<app_id>/decide")
def decide_application(app_id):
    uid, role = context()
    require_roles(role, ["ChannelManager"])
    app = load_application(app_id)
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    decision_reason = req_str(body, "decision_reason")
    if app["status"] not in ("SUBMITTED", "VETTING"):
        fail("ERR_INVALID_STATE_TRANSITION", "application is already decided")
    if decision == "APPROVE":
        # The join, in the PRD's declared order.
        if app["inspection_status"] != "PASSED" or app["docs_status"] != "VERIFIED":
            fail("ERR_APPLICATION_INCOMPLETE",
                 "approval requires a PASSED inspection and VERIFIED documents")
        if not app["has_physical_storefront"]:
            fail("ERR_STOREFRONT_REQUIRED",
                 "authorization is impossible without a physical storefront")
        if app["brand_presentation_score"] is None or app["brand_presentation_score"] < BRAND_SCORE_THRESHOLD:
            fail("ERR_BRAND_STANDARD_BELOW_THRESHOLD",
                 "brand presentation score must be at least 70")
        if uid == app["inspection_recorded_by"] or uid == app["docs_reviewed_by"]:
            fail("ERR_SOD_VIOLATION",
                 "the decider must differ from the inspection recorder and the docs reviewer")
        dealer = DB.dealers.get(app["dealer_id"])
        if dealer is None or dealer["status"] != "PENDING":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "the dealer is no longer PENDING")
        app["status"] = "APPROVED"
        app["decision_reason"] = decision_reason
        touch(app)
        dealer["status"] = "AUTHORIZED"
        dealer["storefront_verified"] = True
        dealer["brand_presentation_score"] = app["brand_presentation_score"]
        touch(dealer)
    else:
        app["status"] = "REJECTED"
        app["decision_reason"] = decision_reason
        touch(app)
    return success(ser_application(app))
