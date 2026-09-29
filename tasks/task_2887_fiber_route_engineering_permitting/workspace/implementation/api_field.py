"""FieldWalkout, PoleObservation, PoleAttachmentApplication and MakeReadyItem endpoints."""

from flask import Blueprint

import calc
import domain
import serialize
import validate as v
from auth import (ALL_ROLES, ROLE_FIELD_SURVEYOR, ROLE_PERMIT_COORDINATOR, ROLE_POLE_OWNER,
                  ROLE_ROUTE_ENGINEER, acting_user_id, endpoint)
from envelope import bool_filter, filter_value, object_response, paginate
from errors import ApiError
from store import db, new_record, now_iso, touch

bp = Blueprint("field", __name__)

WALKOUT_CREATE_FIELDS = ("segment_id", "walked_on", "obstruction_count",
                         "conduit_available_confirmed", "surveyor_note")
OBSERVATION_CREATE_FIELDS = ("walkout_id", "pole_tag", "pole_owner", "condition_grade",
                            "available_vertical_clearance_in", "existing_attachment_count")
POLE_APP_CREATE_FIELDS = ("segment_id", "pole_owner", "pole_count")

NON_TERMINAL_POLE_APP_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED",
                                  "MAKE_READY_ESTIMATED", "GRANTED")


# ---------------------------------------------------------------------------
# FieldWalkout
# ---------------------------------------------------------------------------


@bp.route("/walkouts", methods=["POST"])
@endpoint([ROLE_FIELD_SURVEYOR])
def create_walkout():
    payload = v.body()
    v.check_body(payload, WALKOUT_CREATE_FIELDS)
    segment_id = v.req_id(payload, "segment_id")
    walked_on = v.req_date(payload, "walked_on")
    obstruction_count = v.opt_int(payload, "obstruction_count", default=0, minimum=0)
    conduit_confirmed = v.opt_bool(payload, "conduit_available_confirmed", default=False)
    surveyor_note = v.opt_str(payload, "surveyor_note", default=None)

    segment = domain.get_segment(segment_id)

    rec = new_record()
    rec.update({
        "segment_id": segment["id"],
        "walked_on": walked_on,
        "obstruction_count": obstruction_count,
        "conduit_available_confirmed": conduit_confirmed,
        "surveyor_note": surveyor_note,
        "status": "OPEN",
        "worst_pole_condition_grade": "NONE",
        "make_ready_flagged_pole_count": 0,
        "review_round": 0,
        "reviewed_by_user_id": None,
        "rejection_reason": None,
    })
    db.walkouts[rec["id"]] = rec
    return object_response(serialize.walkout(rec), 201)


@bp.route("/walkouts/<walkout_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_walkout(walkout_id):
    return object_response(serialize.walkout(domain.get_walkout(walkout_id)))


@bp.route("/walkouts/<walkout_id>/pole-observations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_walkout_observations(walkout_id):
    walkout = domain.get_walkout(walkout_id)
    rows = domain.observations_of_walkout(walkout["id"])
    flag = bool_filter("requires_make_ready")
    if flag is not None:
        rows = [r for r in rows if r["requires_make_ready"] == flag]
    return paginate(rows, serialize.observation)


@bp.route("/pole-observations", methods=["POST"])
@endpoint([ROLE_FIELD_SURVEYOR])
def create_pole_observation():
    payload = v.body()
    v.check_body(payload, OBSERVATION_CREATE_FIELDS)
    walkout_id = v.req_id(payload, "walkout_id")
    pole_tag = v.req_str(payload, "pole_tag")
    pole_owner = v.req_enum(payload, "pole_owner", calc.POLE_OWNERS)
    condition_grade = v.req_enum(payload, "condition_grade", calc.CONDITION_GRADES)
    clearance = v.req_int(payload, "available_vertical_clearance_in", minimum=0)
    attachments = v.req_int(payload, "existing_attachment_count", minimum=0)

    walkout = domain.get_walkout(walkout_id)

    requires_make_ready = (
        condition_grade in ("C", "D")
        or clearance < calc.MAKE_READY_CLEARANCE_THRESHOLD_IN
    )

    rec = new_record(versioned=False)
    rec.update({
        "walkout_id": walkout["id"],
        "pole_tag": pole_tag,
        "pole_owner": pole_owner,
        "condition_grade": condition_grade,
        "available_vertical_clearance_in": clearance,
        "existing_attachment_count": attachments,
        "requires_make_ready": requires_make_ready,
    })
    db.observations[rec["id"]] = rec

    domain.recompute_walkout_rollups(walkout)
    touch(walkout)
    return object_response(serialize.observation(rec), 201)


@bp.route("/walkouts/<walkout_id>/submit", methods=["POST"])
@endpoint([ROLE_FIELD_SURVEYOR])
def submit_walkout(walkout_id):
    v.check_body(v.body(), ())
    walkout = domain.get_walkout(walkout_id)

    if walkout["status"] not in ("OPEN", "REJECTED"):
        raise ApiError("ERR_INVALID_WALKOUT_STATE")
    if not domain.observations_of_walkout(walkout["id"]):
        raise ApiError("ERR_WALKOUT_HAS_NO_OBSERVATIONS")

    # a REJECTED walkout passes through OPEN and re-evaluates OPEN -> SUBMITTED
    # inside this same request, so the answer shows SUBMITTED.
    walkout["status"] = "SUBMITTED"
    touch(walkout)
    return object_response(serialize.walkout(walkout))


@bp.route("/walkouts/<walkout_id>/review", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def review_walkout(walkout_id):
    payload = v.body()
    v.check_body(payload, ("decision", "rejection_reason"))
    decision = v.req_enum(payload, "decision", calc.WALKOUT_DECISIONS)
    rejection_reason = v.opt_str(payload, "rejection_reason", default=None)
    if decision == "REJECTED" and v.is_blank(rejection_reason):
        v.bad("Field 'rejection_reason' is required and must be non-blank on a rejection.")

    walkout = domain.get_walkout(walkout_id)
    if walkout["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_WALKOUT_STATE")

    walkout["reviewed_by_user_id"] = acting_user_id()

    if decision == "ACCEPTED":
        walkout["status"] = "ACCEPTED"
        touch(walkout)
        segment = db.segments.get(walkout["segment_id"])
        if segment is not None:
            if segment["engineering_status"] == "DRAFT":
                segment["engineering_status"] = "WALKED"
            domain.recompute_segment_walkout_fields(segment)
            touch(segment)
    else:
        walkout["status"] = "REJECTED"
        walkout["rejection_reason"] = rejection_reason
        walkout["review_round"] = walkout["review_round"] + 1
        touch(walkout)
        domain.rewalk_rejection_cascade(walkout)

    return object_response(serialize.walkout(walkout))


# ---------------------------------------------------------------------------
# PoleAttachmentApplication
# ---------------------------------------------------------------------------


@bp.route("/pole-attachment-applications", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def create_pole_app():
    payload = v.body()
    v.check_body(payload, POLE_APP_CREATE_FIELDS)
    segment_id = v.req_id(payload, "segment_id")
    pole_owner = v.req_enum(payload, "pole_owner", calc.POLE_OWNERS)
    pole_count = v.req_int(payload, "pole_count", minimum=1)

    segment = domain.get_segment(segment_id)

    rec = new_record()
    rec.update({
        "segment_id": segment["id"],
        "pole_owner": pole_owner,
        "pole_count": pole_count,
        "status": "DRAFT",
        "submitted_at": None,
        "revision_round": 0,
        "make_ready_items_subtotal_cents": None,
        "make_ready_admin_fee_bp": None,
        "make_ready_admin_fee_cents": None,
        "make_ready_cost_cents": None,
        "make_ready_days": None,
        "committed": False,
        "owner_note": None,
    })
    db.pole_apps[rec["id"]] = rec
    return object_response(serialize.pole_app(rec), 201)


@bp.route("/pole-attachment-applications/<app_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_pole_app(app_id):
    return object_response(serialize.pole_app(domain.get_pole_app(app_id)))


@bp.route("/pole-attachment-applications/<app_id>/make-ready-items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_make_ready_items(app_id):
    app = domain.get_pole_app(app_id)
    rows = domain.mr_items_of_app(app["id"])
    work_class = filter_value("work_class")
    if work_class is not None:
        rows = [r for r in rows if r["work_class"] == work_class]
    return paginate(rows, serialize.mr_item)


@bp.route("/pole-attachment-applications/<app_id>/submit", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def submit_pole_app(app_id):
    v.check_body(v.body(), ())
    app = domain.get_pole_app(app_id)

    if app["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_POLE_APPLICATION_STATE")

    segment = db.segments.get(app["segment_id"])
    if segment is None or segment["engineering_status"] == "DRAFT":
        raise ApiError("ERR_WALKOUT_NOT_ACCEPTED")

    app["status"] = "SUBMITTED"
    app["submitted_at"] = now_iso()
    touch(app)
    return object_response(serialize.pole_app(app))


def _validate_make_ready_items(payload):
    raw = payload.get("make_ready_items")
    if raw is None or not isinstance(raw, list) or len(raw) == 0:
        v.bad("Field 'make_ready_items' must be a non-empty array on an ESTIMATED outcome.")
    parsed = []
    for element in raw:
        if not isinstance(element, dict):
            v.bad("Each element of 'make_ready_items' must be an object.")
        v.no_unknown(element, ("pole_tag", "work_class", "quantity"))
        pole_tag = v.req_str(element, "pole_tag")
        work_class = v.req_enum(element, "work_class", calc.WORK_CLASSES)
        quantity = v.req_int(element, "quantity", minimum=1)
        parsed.append((pole_tag, work_class, quantity))
    return parsed


@bp.route("/pole-attachment-applications/<app_id>/owner-response", methods=["POST"])
@endpoint([ROLE_POLE_OWNER])
def pole_app_owner_response(app_id):
    payload = v.body()
    v.check_body(payload, ("outcome", "make_ready_items", "owner_note"))
    outcome = v.req_enum(payload, "outcome", calc.OWNER_OUTCOMES)
    owner_note = v.opt_str(payload, "owner_note", default=None)
    items = _validate_make_ready_items(payload) if outcome == "ESTIMATED" else None

    app = domain.get_pole_app(app_id)
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_POLE_APPLICATION_STATE")

    if owner_note is not None:
        app["owner_note"] = owner_note

    if outcome == "REVISION_REQUESTED":
        app["status"] = "REVISION_REQUESTED"
        app["revision_round"] = app["revision_round"] + 1
    elif outcome == "DENIED":
        app["status"] = "DENIED"
    else:
        # the earlier estimate's item set is replaced wholesale, never accumulated
        for existing in domain.mr_items_of_app(app["id"]):
            del db.mr_items[existing["id"]]
        lead_days_values = []
        subtotal = 0
        for pole_tag, work_class, quantity in items:
            unit_cost, extended, lead_days = calc.make_ready_item_figures(
                work_class, quantity, app["pole_owner"]
            )
            item = new_record(versioned=False)
            item.update({
                "application_id": app["id"],
                "pole_tag": pole_tag,
                "work_class": work_class,
                "quantity": quantity,
                "unit_cost_cents": unit_cost,
                "extended_cost_cents": extended,
                "lead_days": lead_days,
            })
            db.mr_items[item["id"]] = item
            subtotal += extended
            lead_days_values.append(lead_days)

        fee_bp = calc.admin_fee_bp(subtotal)
        fee_cents = calc.admin_fee_cents(subtotal, fee_bp)
        app["make_ready_items_subtotal_cents"] = subtotal
        app["make_ready_admin_fee_bp"] = fee_bp
        app["make_ready_admin_fee_cents"] = fee_cents
        app["make_ready_cost_cents"] = subtotal + fee_cents
        app["make_ready_days"] = calc.make_ready_days(lead_days_values, app["pole_count"])
        app["status"] = "MAKE_READY_ESTIMATED"

    touch(app)
    return object_response(serialize.pole_app(app))


@bp.route("/pole-attachment-applications/<app_id>/accept-make-ready", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def accept_make_ready(app_id):
    v.check_body(v.body(), ())
    app = domain.get_pole_app(app_id)

    if app["status"] != "MAKE_READY_ESTIMATED":
        raise ApiError("ERR_INVALID_POLE_APPLICATION_STATE")

    segment = db.segments.get(app["segment_id"])
    route = domain.route_of_segment(segment)

    if domain.segment_has_grade_d_pole(segment["id"]):
        has_replacement = any(
            item["work_class"] == "POLE_REPLACEMENT" for item in domain.mr_items_of_app(app["id"])
        )
        if not has_replacement:
            raise ApiError("ERR_MAKE_READY_REQUIRED")

    cost = app["make_ready_cost_cents"] or 0
    if cost > route["budget_available_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED")

    app["status"] = "GRANTED"
    app["committed"] = True
    touch(app)

    domain.recompute_route_budget(route)
    if domain.rederive_bid_ready_if_design_locked(segment):
        touch(segment)
    domain.recompute_route_bid_ready_rollup(route)
    touch(route)
    return object_response(serialize.pole_app(app))


@bp.route("/pole-attachment-applications/<app_id>/withdraw", methods=["POST"])
@endpoint([ROLE_PERMIT_COORDINATOR])
def withdraw_pole_app(app_id):
    payload = v.body()
    v.check_body(payload, ("reason",))
    v.opt_str(payload, "reason", default=None)

    app = domain.get_pole_app(app_id)
    if app["status"] not in NON_TERMINAL_POLE_APP_STATUSES:
        raise ApiError("ERR_INVALID_POLE_APPLICATION_STATE")

    # hop 1: the make-ready breakdown is deliberately retained for audit
    app["status"] = "WITHDRAWN"
    app["committed"] = False
    touch(app)

    domain.attachment_withdrawal_cascade(app)
    return object_response(serialize.pole_app(app))
