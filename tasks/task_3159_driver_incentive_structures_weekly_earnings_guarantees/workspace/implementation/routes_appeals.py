"""Appeal endpoints."""
from flask import Blueprint, request

import db
from errors import (
    err_appeal_adjustment_required,
    err_appeal_identity_mismatch,
    err_appeal_not_escalatable,
    err_appeal_rounds_exhausted,
    err_cross_market_reference,
    err_invalid_request,
    err_invalid_state,
    err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    appeal_view,
    get_appeal_or_404,
    get_driver_or_404,
    get_statement_or_404,
    new_entity,
    paginate,
    require_enum,
    require_int,
    require_str,
    touch,
    APPEAL_OUTCOMES,
    SUBJECT_TYPES,
)

bp = Blueprint("appeals", __name__)


@bp.post("/appeals")
@require_roles("Driver")
def create_appeal(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    if driver_id != _user_id:
        raise err_unauthorized("Driver may only file appeals as themselves")
    driver = get_driver_or_404(driver_id)
    subject_type = require_enum(body.get("subject_type"), "subject_type", SUBJECT_TYPES)
    reason = body.get("reason")
    if not isinstance(reason, str):
        raise err_invalid_request("reason is required")

    statement_id = body.get("statement_id")
    statement = None
    if subject_type == "STATEMENT":
        if not isinstance(statement_id, str):
            raise err_invalid_request("statement_id is required for STATEMENT appeals")
        statement = get_statement_or_404(statement_id)
        if statement["driver_id"] != driver["id"]:
            raise err_cross_market_reference("Statement belongs to a different driver")
        if statement["status"] != "PUBLISHED":
            raise err_invalid_state("Statement must be PUBLISHED to dispute")
    else:
        statement_id = None

    adjustment_cents = body.get("adjustment_cents")
    if adjustment_cents is not None:
        adjustment_cents = require_int(adjustment_cents, "adjustment_cents")

    a = new_entity(
        {
            "driver_id": driver["id"],
            "subject_type": subject_type,
            "statement_id": statement_id,
            "reason": reason,
            "round_count": 0,
            "status": "FILED",
            "adjustment_cents": adjustment_cents,
        }
    )
    db.appeals[a["id"]] = a
    if statement is not None:
        statement["status"] = "DISPUTED"
        touch(statement)
    return success_object(appeal_view(a), 201)


@bp.get("/appeals/<aid>")
@require_roles("PlatformAdmin", "PaymentsOfficer", "Driver")
def get_appeal(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    return success_object(appeal_view(a))


@bp.get("/appeals")
@require_roles("PlatformAdmin", "PaymentsOfficer")
def list_appeals(_user_id, _role):
    items = list(db.appeals.values())
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    subject_type = request.args.get("subject_type")
    statement_id = request.args.get("statement_id")
    if driver_id is not None:
        items = [a for a in items if a["driver_id"] == driver_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if subject_type is not None:
        items = [a for a in items if a["subject_type"] == subject_type]
    if statement_id is not None:
        items = [a for a in items if a.get("statement_id") == statement_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([appeal_view(a) for a in page], limit, offset, total)


@bp.post("/appeals/<aid>/start-review")
@require_roles("PaymentsOfficer")
def start_review(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["status"] != "FILED":
        raise err_invalid_state("Appeal must be FILED to start review")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(appeal_view(a))


@bp.post("/appeals/<aid>/request-info")
@require_roles("PaymentsOfficer")
def request_info(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Appeal must be UNDER_REVIEW to request info")
    if a["round_count"] >= 2:
        raise err_appeal_rounds_exhausted()
    a["status"] = "MORE_INFO"
    touch(a)
    return success_object(appeal_view(a))


@bp.post("/appeals/<aid>/provide-info")
@require_roles("Driver")
def provide_info(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["driver_id"] != _user_id:
        raise err_appeal_identity_mismatch()
    if a["status"] != "MORE_INFO":
        raise err_invalid_state("Appeal must be MORE_INFO to provide info")
    a["round_count"] += 1
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(appeal_view(a))


@bp.post("/appeals/<aid>/resolve")
@require_roles("PaymentsOfficer", "PlatformAdmin")
def resolve_appeal(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["status"] == "ESCALATED":
        if _role != "PlatformAdmin":
            raise err_unauthorized("Escalated appeals require PlatformAdmin")
    elif a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Appeal must be UNDER_REVIEW or ESCALATED to resolve")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    outcome = require_enum(body.get("outcome"), "outcome", APPEAL_OUTCOMES)
    adjustment = body.get("adjustment_cents")

    if outcome == "UPHELD":
        a["status"] = "RESOLVED_UPHELD"
        touch(a)
        if a["subject_type"] == "STATEMENT" and a.get("statement_id"):
            st = db.statements.get(a["statement_id"])
            if st is not None and st["status"] == "DISPUTED":
                st["status"] = "PUBLISHED"
                touch(st)
        return success_object(appeal_view(a))

    # OVERTURNED
    if a["subject_type"] == "STATEMENT":
        if adjustment is None:
            raise err_appeal_adjustment_required()
        adjustment = require_int(adjustment, "adjustment_cents")
        if adjustment == 0:
            raise err_appeal_adjustment_required()
        a["adjustment_cents"] = adjustment
        st = db.statements.get(a["statement_id"])
        if st is not None:
            st["status"] = "AMENDED"
            st["adjustments_cents"] = st.get("adjustments_cents", 0) + adjustment
            st["total_cents"] = (
                st["base_fares_cents"]
                + st["tips_cents_total"]
                + st["bonus_total_cents"]
                + st["make_up_total_cents"]
                + st["adjustments_cents"]
            )
            touch(st)
    else:
        driver = db.drivers.get(a["driver_id"])
        if driver is not None:
            driver["rate_posture"] = "ELIGIBLE"
            driver["offers_total"] = 0
            driver["accepted_total"] = 0
            driver["cancelled_total"] = 0
            driver["acceptance_rate_bps"] = 10000
            driver["cancellation_rate_bps"] = 0
            db.rate_events[driver["id"]] = []
            touch(driver)
    a["status"] = "RESOLVED_OVERTURNED"
    touch(a)
    return success_object(appeal_view(a))


@bp.post("/appeals/<aid>/escalate")
@require_roles("PaymentsOfficer")
def escalate_appeal(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Appeal must be UNDER_REVIEW to escalate")
    if a["round_count"] != 2:
        raise err_appeal_not_escalatable()
    a["status"] = "ESCALATED"
    touch(a)
    return success_object(appeal_view(a))


@bp.post("/appeals/<aid>/withdraw")
@require_roles("Driver")
def withdraw_appeal(aid, _user_id, _role):
    a = get_appeal_or_404(aid)
    if a["driver_id"] != _user_id:
        raise err_appeal_identity_mismatch()
    if a["status"] not in ("FILED", "UNDER_REVIEW", "MORE_INFO"):
        raise err_invalid_state("Appeal cannot be withdrawn from its current state")
    a["status"] = "WITHDRAWN"
    touch(a)
    if a["subject_type"] == "STATEMENT" and a.get("statement_id"):
        st = db.statements.get(a["statement_id"])
        if st is not None and st["status"] == "DISPUTED":
            st["status"] = "PUBLISHED"
            touch(st)
    return success_object(appeal_view(a))
