"""Site-readiness reviews: dimensional qualification, verdicts and uplift."""

from flask import Blueprint

from db import DB, base_record, as_bool, as_int, as_str, check_version, touch
from errors import ApiError
from middleware import authenticate, check_region
from response import success
from routes import common
from serializers import readiness_review as ser_review
from services import calc, machines

bp = Blueprint("readiness", __name__)

DIMENSION_FIELDS = {
    "operating_room_length_cm": "operating_room_length_cm",
    "operating_room_width_cm": "operating_room_width_cm",
    "table_throw_radius_cm": "table_throw_radius_cm",
    "ceiling_clearance_cm": "ceiling_clearance_cm",
    "length": "operating_room_length_cm",
    "width": "operating_room_width_cm",
    "throw_radius": "table_throw_radius_cm",
    "ceiling": "ceiling_clearance_cm",
}


@bp.post("/api/accounts/<account_id>/readiness-reviews")
def create_readiness_review(account_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    data = common.body()
    config = common.get_config(common.require_str(data, "evaluated_configuration_id"))
    site_code = common.require_str(data, "site_code")
    for existing in calc.reviews_of_account(account_id):
        if existing.get("site_code") == site_code:
            raise ApiError("ERR_DUPLICATE_SITE_CODE")
    record = base_record({
        "hospital_account_id": account_id,
        "review_round": 1,
        "site_code": site_code,
        "operating_room_length_cm": as_int(data.get("operating_room_length_cm"), 0),
        "operating_room_width_cm": as_int(data.get("operating_room_width_cm"), 0),
        "table_throw_radius_cm": as_int(data.get("table_throw_radius_cm"), 0),
        "ceiling_clearance_cm": as_int(data.get("ceiling_clearance_cm"), 0),
        "has_dedicated_power_circuit": as_bool(data.get("has_dedicated_power_circuit")),
        "has_dark_fiber_run": as_bool(data.get("has_dark_fiber_run")),
        "evaluated_configuration_id": config.get("id"),
        "readiness_status": "PENDING_REVIEW",
        "remediation_note": None,
    })
    record["conditional_clearance_count"] = calc.conditional_clearance_count(record)
    record["construction_uplift_fee_cents"] = calc.construction_uplift_fee(record)
    DB.site_readiness_reviews[record["id"]] = record
    machines.refresh_posture(account)
    return success(ser_review(record)), 201


@bp.get("/api/accounts/<account_id>/readiness-reviews")
def list_account_reviews(account_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    records = calc.reviews_of_account(account_id)
    status = common.arg("readiness_status")
    if status:
        records = [r for r in records if r.get("readiness_status") == status]
    site_code = common.arg("site_code")
    if site_code:
        records = [r for r in records if r.get("site_code") == site_code]
    return common.paged(records, "site_readiness_reviews")


@bp.get("/api/account-readiness-reviews")
def list_reviews_by_config():
    authenticate(["PlatformAdmin", "ClinicalOperationsLead"])
    records = list(DB.site_readiness_reviews.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        common.get_account(account_id)
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    config_id = common.arg("evaluated_configuration_id")
    if config_id:
        records = [r for r in records if r.get("evaluated_configuration_id") == config_id]
    return common.paged(records, "site_readiness_reviews")


@bp.get("/api/account-readiness-reviews/<review_id>")
def get_readiness_review(review_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead"])
    record = common.get_review(review_id)
    return success(ser_review(record))


@bp.post("/api/account-readiness-reviews/<review_id>/submit-verdict")
def submit_verdict(review_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    review = common.get_review(review_id)
    account = common.get_account(review.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    verdict = as_str(data.get("verdict")).strip().upper()
    if verdict not in ("PASSED", "CONDITIONAL"):
        raise ApiError("ERR_INVALID_REQUEST")
    status = review.get("readiness_status")
    # Priority 6 — the review must be PENDING_REVIEW, or CONDITIONAL for a pass.
    if verdict == "PASSED":
        if status not in ("PENDING_REVIEW", "CONDITIONAL"):
            raise ApiError("ERR_READINESS_REVIEW_NOT_PENDING")
    else:
        if status != "PENDING_REVIEW":
            raise ApiError("ERR_READINESS_REVIEW_NOT_PENDING")
    # Priority 12 — every dimension and the throw radius meet the minimums.
    if not calc.room_requirements_met(review):
        raise ApiError("ERR_ROOM_REQUIREMENTS_UNMET")
    clearances = calc.conditional_clearance_count(review)
    if verdict == "PASSED":
        # Priority 13 — a pass requires zero outstanding conditional clearances.
        if clearances > 0:
            raise ApiError("ERR_CONDITIONAL_CLEARANCE_REQUIRES_REVIEW")
    else:
        # A CONDITIONAL verdict requires at least one in-band clearance.
        if clearances == 0:
            raise ApiError("ERR_ROOM_REQUIREMENTS_UNMET")
    # Priorities 14 / 15 — the integration facts.
    power_ok, fiber_ok = calc.integration_requirements_met(review)
    if not power_ok:
        raise ApiError("ERR_POWER_CIRCUIT_MISSING")
    if not fiber_ok:
        raise ApiError("ERR_NETWORK_INTEGRATION_MISSING")
    # Both paths require a posture other than EXPANSION_BLOCKED.
    if calc.account_posture(account) == "EXPANSION_BLOCKED":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")
    check_version(review, data, "expected_review_version")
    review["readiness_status"] = verdict
    review["conditional_clearance_count"] = clearances
    touch(review)
    machines.refresh_posture(account)
    return success(ser_review(review))


@bp.post("/api/account-readiness-reviews/<review_id>/reject")
def reject_review(review_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    review = common.get_review(review_id)
    account = common.get_account(review.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if review.get("readiness_status") != "PENDING_REVIEW":
        raise ApiError("ERR_READINESS_REVIEW_NOT_PENDING")
    note = data.get("remediation_note")
    if note is None or not as_str(note).strip():
        raise ApiError("ERR_REMEDIATION_NOTE_REQUIRED")
    check_version(review, data, "expected_review_version")
    review["readiness_status"] = "REJECTED"
    review["remediation_note"] = as_str(note).strip()
    touch(review)
    machines.refresh_posture(account)
    return success(ser_review(review))


@bp.post("/api/account-readiness-reviews/<review_id>/return-to-review")
def return_to_review(review_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    review = common.get_review(review_id)
    account = common.get_account(review.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if review.get("readiness_status") != "REJECTED":
        raise ApiError("ERR_READINESS_REVIEW_NOT_REJECTED")
    check_version(review, data, "expected_review_version")
    review["readiness_status"] = "PENDING_REVIEW"
    review["review_round"] = int(review.get("review_round") or 1) + 1
    if data.get("remediation_note") is not None:
        review["remediation_note"] = as_str(data.get("remediation_note"))
    review["conditional_clearance_count"] = calc.conditional_clearance_count(review)
    touch(review)
    machines.refresh_posture(account)
    return success(ser_review(review))


@bp.post("/api/account-readiness-reviews/<review_id>/readiness-checks")
def readiness_checks(review_id):
    """Re-measure a single dimensional check. The review's status is untouched
    but the conditional clearance count is recomputed."""
    ctx = authenticate(["ClinicalOperationsLead"])
    review = common.get_review(review_id)
    account = common.get_account(review.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    check_type = common.require_str(data, "check_type")
    field = DIMENSION_FIELDS.get(check_type)
    if field is None:
        field = DIMENSION_FIELDS.get(check_type.lower())
    if field is None:
        raise ApiError("ERR_INVALID_REQUEST")
    if "measured_value_cm" not in data or data.get("measured_value_cm") is None:
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(review, data, "expected_review_version")
    review[field] = as_int(data.get("measured_value_cm"))
    review["conditional_clearance_count"] = calc.conditional_clearance_count(review)
    touch(review)
    return success(ser_review(review))