"""The case schedule and representative authorizations (PRD 3.3, 3.4)."""
from flask import Blueprint

import calc
import cascades
import db
from db import store
from errors import ApiError
from reqval import (
    authenticate,
    pagination_params,
    query_enum,
    query_string,
    read_body,
    require_ordered,
)
from routes import common

bp = Blueprint("cases", __name__, url_prefix="/vendor-access")

SCHEDULABLE = ("SCHEDULED", "RESCHEDULED")


# ----------------------------------------------------------- SurgicalCase
@bp.post("/surgical-cases")
def schedule_case():
    authenticate(("ORCoordinator",))
    body = read_body()
    facility_id = body.string("facility_id")
    case_number = body.string("case_number")
    procedure_name = body.string("procedure_name")
    start_raw, start = body.instant("scheduled_start_utc")
    end_raw, end = body.instant("scheduled_end_utc")
    restriction_level = body.enum(
        "restriction_level", db.RESTRICTION_LEVELS, required=False, default="STANDARD"
    )
    implant_required = body.boolean("implant_required", required=False, default=False)

    require_ordered(start, end)
    facility = common.facility(facility_id)

    for existing in store.surgical_cases.values():
        if existing["facility_id"] == facility["id"] and existing["case_number"] == case_number:
            raise ApiError("ERR_DUPLICATE_CASE_NUMBER")

    row = db.stamp_common(
        {
            "facility_id": facility["id"],
            "case_number": case_number,
            "procedure_name": procedure_name,
            "scheduled_start_utc": start_raw,
            "scheduled_end_utc": end_raw,
            # Pinned at creation and never rewritten again, not even by a
            # reschedule: the audit basis for the pinned loaner deadline.
            "original_scheduled_start_utc": start_raw,
            "restriction_level": restriction_level,
            "implant_required": implant_required,
            "status": "SCHEDULED",
            "vendor_coverage_status": "UNCOVERED" if implant_required else "NOT_REQUIRED",
            "implant_readiness_status": "PENDING" if implant_required else "NOT_APPLICABLE",
            "approved_rep_count": 0,
            "revoked_authorization_count": 0,
            "reschedule_count": 0,
        }
    )
    store.surgical_cases[row["id"]] = row
    return common.created(row)


@bp.get("/surgical-cases/<row_id>")
def read_case(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.surgical_case(row_id))


@bp.get("/surgical-cases")
def list_cases():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    facility_id = query_string("facility_id")
    status = query_enum("status", db.CASE_STATUSES)
    coverage = query_enum("vendor_coverage_status", db.COVERAGE_STATUSES)
    readiness = query_enum("implant_readiness_status", db.READINESS_STATUSES)
    rows = [
        row
        for row in store.surgical_cases.values()
        if common.matches(row, "facility_id", facility_id)
        and common.matches(row, "status", status)
        and common.matches(row, "vendor_coverage_status", coverage)
        and common.matches(row, "implant_readiness_status", readiness)
    ]
    return common.listing(rows, limit, offset)


def _refresh_badge_windows(case, facility):
    """Recompute the window of every APPROVED authorization and the copies
    carried by every badge still ISSUED (PRD 3.3).
    """
    for auth in db.in_creation_order(calc.authorizations_of_case(case["id"])):
        if auth["status"] != "APPROVED":
            continue
        window_start, window_end = calc.compute_badge_window(case, facility)
        auth["badge_window_start_utc"] = window_start
        auth["badge_window_end_utc"] = window_end
        cascades.mark(auth)
        for check_in in db.in_creation_order(calc.check_ins_of_authorization(auth["id"])):
            if check_in["badge_status"] != "ISSUED":
                continue
            check_in["valid_from_utc"] = window_start
            check_in["valid_until_utc"] = window_end
            cascades.mark(check_in)


def _refresh_loaner_sets(case, facility):
    """Re-derive the current-basis deadline, the bay occupation and the
    delivery branch of every set the reschedule disturbs (PRD 3.3, 3.7).
    """
    for loaner_set in db.in_creation_order(calc.loaner_sets_of_case(case["id"])):
        if loaner_set["status"] == "RELEASED_TO_OR":
            continue
        deadline = calc.compute_deadline(
            case["scheduled_start_utc"],
            case,
            facility,
            loaner_set["reprocessing_complexity"],
            loaner_set["tray_count"],
        )
        loaner_set["required_delivery_deadline_utc"] = deadline
        loaner_set["spd_occupation_start_utc"] = deadline
        loaner_set["spd_occupation_end_utc"] = case["scheduled_start_utc"]
        cascades.mark(loaner_set)

        if loaner_set["delivered_at_utc"]:
            loaner_set["late_minutes_current_basis"] = calc.compute_late_minutes(
                deadline, loaner_set["delivered_at_utc"]
            )
            late_minutes = loaner_set["late_minutes_current_basis"]
            if loaner_set["status"] == "DELIVERED_LATE" and late_minutes == 0:
                loaner_set["status"] = "DELIVERED_ON_TIME"
                if loaner_set["fee_status"] == "ASSESSED":
                    # The amount itself is retained as the historical assessment.
                    loaner_set["fee_status"] = "REVERSED"
            elif loaner_set["status"] == "REJECTED_LATE" and (
                0 < late_minutes <= db.HARD_REJECT_GRACE_MINUTES
            ):
                loaner_set["status"] = "DELIVERED_LATE"
                loaner_set["assessed_late_fee_cents"] = calc.compute_late_fee(loaner_set)
                loaner_set["fee_status"] = calc.compute_fee_status(loaner_set)
        cascades.mark_vendor_id(calc.loaner_set_vendor_id(loaner_set))


@bp.post("/surgical-cases/<row_id>/reschedule")
def reschedule_case(row_id):
    authenticate(("ORCoordinator",))
    body = read_body()
    start_raw, start = body.instant("new_scheduled_start_utc")
    end_raw, end = body.instant("new_scheduled_end_utc")
    require_ordered(start, end)

    case = common.surgical_case(row_id)
    if case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")

    facility = calc.case_facility(case)
    case["scheduled_start_utc"] = start_raw
    case["scheduled_end_utc"] = end_raw
    case["status"] = "RESCHEDULED"
    case["reschedule_count"] = case["reschedule_count"] + 1
    cascades.mark_case(case)

    _refresh_badge_windows(case, facility)
    _refresh_loaner_sets(case, facility)

    cascades.flush()
    return common.ok(case)


@bp.post("/surgical-cases/<row_id>/cancel")
def cancel_case(row_id):
    authenticate(("ORCoordinator",))
    body = read_body()
    body.string("cancellation_reason")

    case = common.surgical_case(row_id)
    if case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")

    case["status"] = "CANCELLED"
    cascades.mark_case(case)

    for auth in db.in_creation_order(calc.authorizations_of_case(case["id"])):
        if auth["status"] == "REQUESTED":
            auth["status"] = "DENIED"
            cascades.mark(auth)
    for auth in db.in_creation_order(calc.authorizations_of_case(case["id"])):
        if auth["status"] == "APPROVED":
            cascades.revoke_authorization(auth, "CASE_CANCELLED")

    cascades.flush()
    return common.ok(case)


# --------------------------------------------------- CaseRepAuthorization
@bp.post("/case-rep-authorizations")
def request_authorization():
    user_id, role = authenticate(("VendorAdmin", "ORCoordinator"))
    body = read_body()
    surgical_case_id = body.string("surgical_case_id")
    vendor_rep_id = body.string("vendor_rep_id")
    requested_role = body.enum("requested_role", db.REQUESTED_ROLES)

    case = common.surgical_case(surgical_case_id)
    rep = common.vendor_rep(vendor_rep_id)
    common.require_vendor_scope(role, user_id, rep["vendor_id"])

    if rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")
    if case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")
    for existing in calc.authorizations_of_case(case["id"]):
        if existing["vendor_rep_id"] == rep["id"] and existing["status"] in (
            "REQUESTED",
            "APPROVED",
        ):
            raise ApiError("ERR_DUPLICATE_AUTHORIZATION")

    row = db.stamp_common(
        {
            "surgical_case_id": case["id"],
            "vendor_rep_id": rep["id"],
            "requested_role": requested_role,
            "requested_by_user_id": user_id,
            "status": "REQUESTED",
            # escort_required, both badge-window instants and epoch_number all
            # stay empty until a decision is taken.
            "escort_required": None,
            "escort_user_id": None,
            "decided_by_user_id": None,
            "decided_at_utc": None,
            "revoked_reason": "NONE",
            "badge_window_start_utc": None,
            "badge_window_end_utc": None,
            "epoch_number": None,
        }
    )
    store.authorizations[row["id"]] = row
    return common.created(row)


@bp.get("/case-rep-authorizations/<row_id>")
def read_authorization(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.authorization(row_id))


@bp.get("/case-rep-authorizations")
def list_authorizations():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    surgical_case_id = query_string("surgical_case_id")
    vendor_rep_id = query_string("vendor_rep_id")
    status = query_enum("status", db.AUTH_STATUSES)
    rows = [
        row
        for row in store.authorizations.values()
        if common.matches(row, "surgical_case_id", surgical_case_id)
        and common.matches(row, "vendor_rep_id", vendor_rep_id)
        and common.matches(row, "status", status)
    ]
    return common.listing(rows, limit, offset)


def _conflicting_window(rep, candidate_start, candidate_end):
    """Only the representative's other APPROVED authorizations are considered,
    examined in ascending creation order, and compared as half-open intervals.
    """
    for other in db.in_creation_order(calc.authorizations_of_rep(rep["id"])):
        if other["status"] != "APPROVED":
            continue
        if not other["badge_window_start_utc"] or not other["badge_window_end_utc"]:
            continue
        if calc.windows_conflict(
            candidate_start,
            candidate_end,
            other["badge_window_start_utc"],
            other["badge_window_end_utc"],
        ):
            return other
    return None


def _vendor_owns_active_implant_product(vendor_id):
    for product in store.approved_products.values():
        if product["status"] != "ACTIVE" or not product["is_implant"]:
            continue
        if calc.product_vendor_id(product) == vendor_id:
            return True
    return False


@bp.post("/case-rep-authorizations/<row_id>/decide")
def decide_authorization(row_id):
    user_id, _role = authenticate(("ORCoordinator",))
    body = read_body()
    decision = body.enum("decision", ("APPROVE", "DENY"))
    escort_user_id = body.string("escort_user_id", required=False)

    auth = common.authorization(row_id)
    rep = store.vendor_reps.get(auth["vendor_rep_id"])
    case = store.surgical_cases.get(auth["surgical_case_id"])

    if decision == "DENY":
        # A denial is cheap: it needs only that the authorization is REQUESTED
        # and that the acting user differs from requested_by_user_id.
        if auth["status"] != "REQUESTED":
            raise ApiError("ERR_AUTHORIZATION_NOT_REQUESTED")
        if user_id == auth["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        auth["status"] = "DENIED"
        auth["decided_by_user_id"] = user_id
        auth["decided_at_utc"] = db.now_str()
        cascades.mark(auth)
        cascades.flush()
        return common.ok(auth)

    # The approval path runs the full safety, temporal, referential and fiscal
    # ladder, in the pinned order of PRD 2.9.
    facility = calc.case_facility(case)
    vendor = calc.vendor_of_rep(rep)

    if rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")
    if rep["access_status"] == "SUSPENDED":
        raise ApiError("ERR_REP_ACCESS_SUSPENDED")
    if auth["status"] != "REQUESTED":
        raise ApiError("ERR_AUTHORIZATION_NOT_REQUESTED")
    if case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")
    if user_id == auth["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if calc.compute_credential_posture(rep) not in ("COMPLIANT", "EXPIRING_SOON"):
        raise ApiError("ERR_REP_CREDENTIALS_NOT_COMPLIANT")

    window_start, window_end = calc.compute_badge_window(case, facility)
    if _conflicting_window(rep, window_start, window_end) is not None:
        raise ApiError("ERR_REP_BADGE_WINDOW_CONFLICT")
    if case["implant_required"] and not _vendor_owns_active_implant_product(vendor["id"]):
        raise ApiError("ERR_IMPLANT_REQUIRES_APPROVED_PRODUCT")
    if vendor["authorizations_used_epoch"] >= calc.quota_hard_cap(
        vendor["access_quota_in_effect"]
    ):
        raise ApiError("ERR_VENDOR_ACCESS_QUOTA_EXCEEDED")
    if vendor["late_fee_balance_cents"] >= db.FEE_HOLD_THRESHOLD_CENTS:
        raise ApiError("ERR_VENDOR_FEE_HOLD")

    auth["status"] = "APPROVED"
    auth["decided_by_user_id"] = user_id
    auth["decided_at_utc"] = db.now_str()
    auth["badge_window_start_utc"] = window_start
    auth["badge_window_end_utc"] = window_end
    auth["escort_required"] = bool(
        case["restriction_level"] == "RESTRICTED" and facility["restricted_escort_required"]
    )
    if escort_user_id is not None:
        auth["escort_user_id"] = escort_user_id
    auth["epoch_number"] = vendor["last_sweep_epoch"]
    cascades.mark(auth)

    vendor["authorizations_used_epoch"] = vendor["authorizations_used_epoch"] + 1
    cascades.mark_vendor(vendor)
    rep["open_authorization_count"] = rep["open_authorization_count"] + 1
    cascades.mark_rep(rep)
    case["approved_rep_count"] = case["approved_rep_count"] + 1
    cascades.mark_case(case)

    cascades.flush()
    return common.ok(auth)


@bp.post("/case-rep-authorizations/<row_id>/revoke")
def revoke_authorization(row_id):
    authenticate(("ORCoordinator", "CredentialingOfficer"))
    body = read_body()
    revoked_reason = body.enum(
        "revoked_reason", db.REVOKED_REASONS, required=False, default="MANUAL"
    )

    auth = common.authorization(row_id)
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED")

    cascades.revoke_authorization(auth, revoked_reason)
    cascades.flush()
    return common.ok(auth)


@bp.get("/case-rep-authorizations/<row_id>/check-ins")
def list_authorization_check_ins(row_id):
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    badge_status = query_enum("badge_status", db.BADGE_STATUSES)
    auth = common.authorization(row_id)
    rows = [
        row
        for row in calc.check_ins_of_authorization(auth["id"])
        if common.matches(row, "badge_status", badge_status)
    ]
    return common.listing(rows, limit, offset)
