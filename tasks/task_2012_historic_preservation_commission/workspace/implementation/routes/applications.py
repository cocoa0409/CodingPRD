"""Certificate of Appropriateness applications (PRD 3.2-3.6): intake, completeness
review, the decision, withdrawal refunds, and fee payments."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_FORBIDDEN_ROLE, ERR_INVALID_STATE,
    ERR_DEMOLITION_PROHIBITED, ERR_DISTRICT_UNDER_REVIEW,
    ERR_VIOLATION_NOT_UNDER_NOTICE, ERR_VIOLATION_PROPERTY_MISMATCH,
    ERR_EMPTY_WORK_ITEMS, ERR_RESUBMISSION_WINDOW_LAPSED,
    ERR_COMMISSION_HEARING_REQUIRED, ERR_STAFF_DECISION_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES, ERR_DENIAL_RATIONALE_REQUIRED,
    ERR_CONDITIONS_REQUIRED, ERR_GUIDELINE_SET_SUPERSEDED, ERR_OVERPAYMENT,
)
from middleware import get_caller, check_role_allowed, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from services.calculations import (
    application_fee_declared, application_fee_final, determine_review_track,
)
from services.core import (
    new_record, touch, adopted_guideline_set_for, hearing_for_application,
    refresh_meeting_count,
)
from services.workflows import (
    check_demolition_delay_overlap, demolition_approval_side_effects,
    after_the_fact_resolution, withdrawal_cascade,
)
from util import CLOCK, parse_dt, fmt_dt, add_days
from validate import (
    get_body, req_str, req_enum, req_bool, opt_bool, req_int, req_work_items,
    req_verified_work_items, opt_str_list, require_path_resource, require_body_ref,
)

bp = Blueprint("applications", __name__, url_prefix="/preservation")

APPLICATION_TYPES = {"ALTERATION", "ADDITION", "NEW_CONSTRUCTION", "DEMOLITION", "RELOCATION"}
DECIDE_OUTCOMES = {"APPROVE", "APPROVE_WITH_CONDITIONS", "DENY"}
APPROVAL_TERMINAL = {"APPROVED", "APPROVED_WITH_CONDITIONS", "APPROVED_ON_APPEAL"}
WITHDRAWABLE = {
    "SUBMITTED", "UNDER_STAFF_REVIEW", "INCOMPLETE", "ACCEPTED",
    "HEARING_SCHEDULED", "HEARING_DEFERRED", "HEARING_OPEN",
}
STAFF = ["PreservationStaff"]
APPLICANT = ["Applicant"]

RESUBMISSION_WINDOW_DAYS = 90
APPEAL_WINDOW_DAYS = 30


def _app_district(app, prop=None):
    prop = prop or db["properties"].get(app["property_id"])
    if prop is None or prop.get("district_id") is None:
        return None
    return db["districts"].get(prop["district_id"])


@bp.post("/applications")
def create_application():
    caller = get_caller()
    body = get_body()
    # Layer 1: request shape.
    property_id = req_str(body, "property_id")
    owner_id = req_str(body, "owner_id")
    application_type = req_enum(body, "application_type", APPLICATION_TYPES)
    is_visible = req_bool(body, "is_visible_from_public_way")
    after_the_fact = req_bool(body, "after_the_fact")
    work_items = req_work_items(body, "work_items")
    violation_id = body.get("violation_id")
    if after_the_fact:
        if violation_id is None or not isinstance(violation_id, str):
            raise_error(ERR_VALIDATION, "violation_id is required when after_the_fact is true")
    else:
        if violation_id is not None:
            raise_error(ERR_VALIDATION, "violation_id must be null when after_the_fact is false")
    # Layer 2: role, then applicant identity vs payload owner.
    check_role_allowed(caller, APPLICANT)
    if caller.user_id != owner_id:
        raise_error(ERR_FORBIDDEN_ROLE, "owner_id must equal X-User-ID for an Applicant")
    # Layer 3: existence of body-supplied references.
    prop = require_body_ref("properties", property_id, "property_id")
    require_body_ref("owners", owner_id, "owner_id")
    violation = None
    if after_the_fact:
        violation = require_body_ref("violations", violation_id, "violation_id")
    # Layer 6 (safety): DEMOLITION prohibited for CONTRIBUTING properties in ICONIC districts.
    district = _app_district({"property_id": property_id}, prop)
    if (
        application_type == "DEMOLITION"
        and prop.get("contributing_status") == "CONTRIBUTING"
        and district is not None
        and district.get("significance_tier") == "ICONIC"
    ):
        raise_error(ERR_DEMOLITION_PROHIBITED,
                    "demolition of a CONTRIBUTING property in an ICONIC district is prohibited")
    # Layer 7 (referential): district active; after-the-fact linkage.
    if district is not None and district.get("status") != "ACTIVE":
        raise_error(ERR_DISTRICT_UNDER_REVIEW,
                    "application intake is frozen while the district is in BOUNDARY_REVIEW")
    if after_the_fact:
        if violation["status"] != "NOTICE_ISSUED":
            raise_error(ERR_VIOLATION_NOT_UNDER_NOTICE,
                        "after-the-fact application requires a violation in NOTICE_ISSUED status")
        if violation["property_id"] != property_id:
            raise_error(ERR_VIOLATION_PROPERTY_MISMATCH,
                        "after-the-fact application's property differs from the violation's property")
    # Layer 9 (structural): work items must be non-empty.
    if len(work_items) == 0:
        raise_error(ERR_EMPTY_WORK_ITEMS, "work_items must not be empty")

    rec = new_record("applications", {
        "property_id": property_id,
        "owner_id": owner_id,
        "application_type": application_type,
        "is_visible_from_public_way": is_visible,
        "after_the_fact": after_the_fact,
        "violation_id": violation_id if after_the_fact else None,
        "work_items": work_items,
        "declared_cost_cents": sum(i["estimated_cost_cents"] for i in work_items),
        "provisional_fee_cents": application_fee_declared(work_items),
        "verified_work_items": None,
        "verified_cost_cents": None,
        "review_track": None,
        "assessed_fee_cents": None,
        "paid_fee_cents": 0,
        "refunded_fee_cents": 0,
        "fee_balance_cents": 0,
        "guideline_set_id": None,
        "completeness_accepted_by": None,
        "resubmission_count": 0,
        "returned_at": None,
        "decided_at": None,
        "decision_conditions": [],
        "denial_rationale_sections": [],
        "status": "SUBMITTED",
    })
    if after_the_fact:
        # Submission immediately flips the violation to AFTER_THE_FACT_PENDING.
        violation["status"] = "AFTER_THE_FACT_PENDING"
        touch(violation)
    return success_object(public(rec), status=201)


@bp.get("/applications")
def list_applications():
    from middleware import authorized
    authorized(ALL_ROLES)
    items = list(db["applications"].values())
    property_id = request.args.get("property_id")
    owner_id = request.args.get("owner_id")
    district_id = request.args.get("district_id")
    violation_id = request.args.get("violation_id")
    guideline_set_id = request.args.get("guideline_set_id")
    status = request.args.get("status")
    work_category = request.args.get("work_category")
    if property_id is not None:
        items = [a for a in items if a.get("property_id") == property_id]
    if owner_id is not None:
        items = [a for a in items if a.get("owner_id") == owner_id]
    if district_id is not None:
        items = [
            a for a in items
            if (db["properties"].get(a.get("property_id")) or {}).get("district_id") == district_id
        ]
    if violation_id is not None:
        items = [a for a in items if a.get("violation_id") == violation_id]
    if guideline_set_id is not None:
        items = [a for a in items if a.get("guideline_set_id") == guideline_set_id]
    if status is not None:
        items = [a for a in items if a.get("status") == status]
    if work_category is not None:
        items = [
            a for a in items
            if any(i.get("category") == work_category for i in (a.get("work_items") or []))
        ]
    return list_response("applications", items=items)


@bp.get("/applications/<rid>")
def get_application(rid):
    return get_one("applications", rid)


@bp.post("/applications/<rid>/begin-review")
def begin_review(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, STAFF)
    app = require_path_resource("applications", rid)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"begin-review requires SUBMITTED, got {app['status']}")
    app["status"] = "UNDER_STAFF_REVIEW"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/return-incomplete")
def return_incomplete(rid):
    caller = get_caller()
    body = get_body()
    req_str(body, "deficiency_notes")
    check_role_allowed(caller, STAFF)
    app = require_path_resource("applications", rid)
    if app["status"] != "UNDER_STAFF_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"return-incomplete requires UNDER_STAFF_REVIEW, got {app['status']}")
    app["status"] = "INCOMPLETE"
    app["returned_at"] = CLOCK.now_iso()
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/resubmit")
def resubmit(rid):
    caller = get_caller()
    body = get_body()
    work_items = req_work_items(body, "work_items")
    new_visibility = None
    if "is_visible_from_public_way" in body and body["is_visible_from_public_way"] is not None:
        new_visibility = req_bool(body, "is_visible_from_public_way")
    check_role_allowed(caller, APPLICANT)
    app = require_path_resource("applications", rid)
    # Layer 2: applicant ownership — surfaces before the resubmission window (PRD 2.8).
    if caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning applicant may resubmit")
    # Layer 5: state.
    if app["status"] != "INCOMPLETE":
        raise_error(ERR_INVALID_STATE, f"resubmit requires INCOMPLETE, got {app['status']}")
    # Layer 8: the ninety-day window.
    if CLOCK.now() > add_days(parse_dt(app["returned_at"]), RESUBMISSION_WINDOW_DAYS):
        raise_error(ERR_RESUBMISSION_WINDOW_LAPSED,
                    "resubmission window (returned_at + 90 days) has lapsed")
    # Layer 9: non-empty work items.
    if len(work_items) == 0:
        raise_error(ERR_EMPTY_WORK_ITEMS, "work_items must not be empty")

    app["work_items"] = work_items
    if new_visibility is not None:
        app["is_visible_from_public_way"] = new_visibility
    app["declared_cost_cents"] = sum(i["estimated_cost_cents"] for i in work_items)
    app["provisional_fee_cents"] = application_fee_declared(work_items)
    app["resubmission_count"] += 1
    app["status"] = "UNDER_STAFF_REVIEW"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/accept-completeness")
def accept_completeness(rid):
    caller = get_caller()
    body = get_body()
    verified_items = req_verified_work_items(body, "verified_work_items")
    check_role_allowed(caller, STAFF)
    app = require_path_resource("applications", rid)
    if app["status"] != "UNDER_STAFF_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"accept-completeness requires UNDER_STAFF_REVIEW, got {app['status']}")

    prop = db["properties"].get(app["property_id"])
    district = _app_district(app, prop)
    verified_cost = sum(i["verified_cost_cents"] for i in verified_items)
    track = determine_review_track(app, prop, district, verified_cost)
    assessed = application_fee_final(verified_items, track)
    adopted = adopted_guideline_set_for(district["id"]) if district else None

    app["verified_work_items"] = verified_items
    app["verified_cost_cents"] = verified_cost
    app["review_track"] = track
    app["assessed_fee_cents"] = assessed
    app["fee_balance_cents"] = assessed
    app["guideline_set_id"] = adopted["id"] if adopted else None
    app["completeness_accepted_by"] = caller.user_id
    app["status"] = "ACCEPTED"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/decide")
def decide(rid):
    caller = get_caller()
    body = get_body()
    outcome = req_enum(body, "outcome", DECIDE_OUTCOMES)
    conditions = opt_str_list(body, "conditions")
    rationale = opt_str_list(body, "denial_rationale_sections")
    override_ack = opt_bool(body, "guideline_override_ack", False)
    check_role_allowed(caller, ["PreservationStaff", "Commissioner"])
    app = require_path_resource("applications", rid)

    # Layer 5: state — a decision is declared only from ACCEPTED or HEARING_OPEN.
    if app["status"] not in ("ACCEPTED", "HEARING_OPEN"):
        raise_error(ERR_INVALID_STATE,
                    f"decide requires ACCEPTED or HEARING_OPEN, got {app['status']}")

    # Layer 9 (structural), in declared precondition order.
    if app["status"] == "ACCEPTED":
        if app.get("review_track") == "COMMISSION":
            raise_error(ERR_COMMISSION_HEARING_REQUIRED,
                        "a COMMISSION-track application must be heard before decision")
        # STAFF-track: staff-only decision authority.
        if caller.role != "PreservationStaff":
            raise_error(ERR_FORBIDDEN_ROLE,
                        "only PreservationStaff may decide a STAFF-track application")
        if caller.user_id == app.get("completeness_accepted_by"):
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "the staff user who accepted completeness cannot decide this application")
    else:  # HEARING_OPEN — commission-only decision authority.
        if caller.role == "PreservationStaff":
            raise_error(ERR_STAFF_DECISION_NOT_PERMITTED,
                        "only a Commissioner may decide a COMMISSION-track application in HEARING_OPEN")

    if outcome == "APPROVE_WITH_CONDITIONS" and not conditions:
        raise_error(ERR_CONDITIONS_REQUIRED,
                    "APPROVE_WITH_CONDITIONS requires a non-empty conditions array")
    if outcome == "DENY" and not rationale:
        raise_error(ERR_DENIAL_RATIONALE_REQUIRED,
                    "DENY requires a non-empty denial_rationale_sections array")

    # Superseded-guideline acknowledgement (version pinning).
    pinned_id = app.get("guideline_set_id")
    prop = db["properties"].get(app["property_id"])
    district = _app_district(app, prop)
    repin_to = None
    repin_needed = False
    if pinned_id is not None:
        pinned = db["guideline_sets"].get(pinned_id)
        if pinned is not None and pinned.get("status") != "ADOPTED":
            if not override_ack:
                raise_error(ERR_GUIDELINE_SET_SUPERSEDED,
                            "the pinned guideline set is no longer the district's ADOPTED set")
            adopted = adopted_guideline_set_for(district["id"]) if district else None
            repin_to = adopted["id"] if adopted else None
            repin_needed = True

    decided_dt = CLOCK.now()
    is_approval = outcome in ("APPROVE", "APPROVE_WITH_CONDITIONS")

    # Demolition overlap gate: runs BEFORE the approval commits.
    base_days = None
    if is_approval and app["application_type"] == "DEMOLITION" and prop is not None:
        base_days = check_demolition_delay_overlap(prop, decided_dt)

    # Commit.
    app["decided_at"] = fmt_dt(decided_dt)
    if outcome == "APPROVE":
        app["status"] = "APPROVED"
        app["decision_conditions"] = []
    elif outcome == "APPROVE_WITH_CONDITIONS":
        app["status"] = "APPROVED_WITH_CONDITIONS"
        app["decision_conditions"] = conditions
    else:
        app["status"] = "DENIED"
        app["denial_rationale_sections"] = rationale
    if repin_needed:
        app["guideline_set_id"] = repin_to
    touch(app)

    # Commission-track mirror: the OPENED hearing moves to DECIDED.
    hearing = hearing_for_application(app["id"], statuses={"OPENED"})
    if hearing is not None:
        meeting_id = hearing["meeting_id"]
        hearing["status"] = "DECIDED"
        touch(hearing)
        refresh_meeting_count(meeting_id)
    if is_approval:
        if app["application_type"] == "DEMOLITION" and prop is not None:
            demolition_approval_side_effects(app, decided_dt, base_days)
        if app.get("after_the_fact"):
            after_the_fact_resolution(app, decided_dt)
    return success_object(public(app))


@bp.post("/applications/<rid>/withdraw")
def withdraw(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, APPLICANT)
    app = require_path_resource("applications", rid)
    # Layer 2: applicant ownership.
    if caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning applicant may withdraw")
    # Layer 5: withdrawal is declared from the seven non-terminal live states.
    if app["status"] not in WITHDRAWABLE:
        raise_error(ERR_INVALID_STATE,
                    f"cannot withdraw an application in status {app['status']}")
    withdrawal_cascade(app)  # stage-based refund + hearing release
    app["status"] = "WITHDRAWN"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/finalize-denial")
def finalize_denial(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, STAFF)
    app = require_path_resource("applications", rid)
    if app["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE,
                    f"finalize-denial requires DENIED, got {app['status']}")
    pending = any(
        a for a in db["appeals"].values()
        if a.get("application_id") == app["id"] and a.get("status") == "FILED"
    )
    if pending:
        raise_error(ERR_INVALID_STATE, "an appeal for this application is still FILED")
    if CLOCK.now() <= add_days(parse_dt(app["decided_at"]), APPEAL_WINDOW_DAYS):
        raise_error(ERR_INVALID_STATE, "the appeal window is still open")
    app["status"] = "DENIED_FINAL"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<rid>/fee-payments")
def fee_payment(rid):
    caller = get_caller()
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=1)
    check_role_allowed(caller, APPLICANT)
    app = require_path_resource("applications", rid)
    if caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning applicant may pay fees")
    if app["status"] in ("WITHDRAWN", "DENIED_FINAL"):
        raise_error(ERR_INVALID_STATE,
                    f"fee payments are not accepted for status {app['status']}")
    # Layer 10 (fiscal): a payment must not exceed the outstanding balance.
    if amount > app["fee_balance_cents"]:
        raise_error(ERR_OVERPAYMENT,
                    f"payment {amount} exceeds outstanding balance {app['fee_balance_cents']}")
    app["paid_fee_cents"] += amount
    app["fee_balance_cents"] -= amount
    touch(app)
    return success_object(public(app), status=201)
