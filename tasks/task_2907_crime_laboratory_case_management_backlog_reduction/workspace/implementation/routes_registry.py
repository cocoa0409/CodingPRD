"""Clock, examiner registry, method catalogue and vendor registry."""
from decimal import Decimal

from flask import Blueprint

import serialize
import services as S
from auth import ANALYST, CASE_MANAGER, LAB_DIRECTOR, QUALITY_MANAGER, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import dec, fmt_instant, q2
from validate import Field, parse

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------- clock
@bp.route("/lab/_clock/set_current_utc", methods=["POST"])
@endpoint(LAB_DIRECTOR)
def set_clock():
    body = parse([Field("current_utc", "instant", required=True)])
    db.set_clock(body["current_utc"])
    return object_response({"current_utc": fmt_instant(db.now())}, 200)


# ---------------------------------------------------------------- analysts
ANALYST_CREATE_FIELDS = [
    Field("full_name", "string", required=True, min_length=1, max_length=120),
    Field("disciplines", "enum_array", required=True, min_length=1,
          choices=S.DISCIPLINES),
    Field("competency_level", "integer", default=1, minimum=1, maximum=5),
    Field("weekly_capacity_hours", "number", required=True,
          exclusive_minimum="0.00", maximum="60.00"),
    Field("training_hours_per_week", "number", default=Decimal("0.00"),
          minimum="0.00"),
    Field("employment_status", "enum", default="ACTIVE",
          choices=S.EMPLOYMENT_STATUSES),
]


@bp.route("/lab/analysts", methods=["POST"])
@endpoint(LAB_DIRECTOR)
def create_analyst():
    body = parse(ANALYST_CREATE_FIELDS)
    if dec(body["training_hours_per_week"]) > dec(body["weekly_capacity_hours"]):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "training_hours_per_week may not exceed weekly_capacity_hours.",
        )
    row = new_row()
    row.update({
        "full_name": body["full_name"],
        "disciplines": body["disciplines"],
        "competency_level": body["competency_level"],
        "weekly_capacity_hours": q2(body["weekly_capacity_hours"]),
        "training_hours_per_week": q2(body["training_hours_per_week"]),
        "employment_status": body["employment_status"],
        "qualification_state": "QUALIFIED",
        "consecutive_pt_failures": 0,
        "assigned_casework_hours": Decimal("0.00"),
        "probation_entered_at_utc": None,
        "suspended_at_utc": None,
    })
    db.analysts[row["id"]] = row
    return object_response(serialize.analyst(row), 201)


ANALYST_PATCH_FIELDS = [
    Field("weekly_capacity_hours", "number",
          exclusive_minimum="0.00", maximum="60.00"),
    Field("training_hours_per_week", "number", minimum="0.00"),
    Field("competency_level", "integer", minimum=1, maximum=5),
    Field("disciplines", "enum_array", min_length=1, choices=S.DISCIPLINES),
    Field("employment_status", "enum", choices=S.EMPLOYMENT_STATUSES),
]


@bp.route("/lab/analysts/<analyst_id>", methods=["PATCH"])
@endpoint(LAB_DIRECTOR)
def patch_analyst(analyst_id):
    analyst = S.find_analyst(analyst_id)
    body = parse(ANALYST_PATCH_FIELDS)
    capacity = body.get("weekly_capacity_hours", analyst["weekly_capacity_hours"])
    training = body.get("training_hours_per_week", analyst["training_hours_per_week"])
    if dec(training) > dec(capacity):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "training_hours_per_week may not exceed weekly_capacity_hours.",
        )
    if "weekly_capacity_hours" in body:
        analyst["weekly_capacity_hours"] = q2(body["weekly_capacity_hours"])
    if "training_hours_per_week" in body:
        analyst["training_hours_per_week"] = q2(body["training_hours_per_week"])
    if "competency_level" in body:
        analyst["competency_level"] = body["competency_level"]
    if "disciplines" in body:
        analyst["disciplines"] = body["disciplines"]
    if "employment_status" in body:
        analyst["employment_status"] = body["employment_status"]
    touch(analyst)
    return object_response(serialize.analyst(analyst), 200)


@bp.route("/lab/analysts/<analyst_id>/reinstate", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def reinstate_analyst(analyst_id):
    analyst = S.find_analyst(analyst_id)
    parse([Field("rationale", "string", required=True, min_length=1, max_length=500)])
    if analyst["qualification_state"] == "DECERTIFIED":
        raise ApiError("ERR_ANALYST_DECERTIFIED")
    if analyst["qualification_state"] != "SUSPENDED":
        raise ApiError("ERR_ANALYST_INVALID_QUALIFICATION_STATE")
    if S.has_live_nonconformance(analyst["id"]):
        raise ApiError("ERR_OPEN_NONCONFORMANCE_BLOCKS_REINSTATEMENT")
    suspended_at = analyst.get("suspended_at_utc")
    passed = False
    for test in db.proficiency_tests.values():
        if test["analyst_id"] != analyst["id"]:
            continue
        if test["status"] != "SCORED" or test.get("result") != "PASS":
            continue
        scored_at = test.get("scored_at_utc")
        if scored_at is None:
            continue
        if suspended_at is None or scored_at > suspended_at:
            passed = True
            break
    if not passed:
        raise ApiError("ERR_REINSTATEMENT_PT_REQUIRED")
    analyst["qualification_state"] = "PROBATION"
    analyst["consecutive_pt_failures"] = 0
    analyst["suspended_at_utc"] = None
    analyst["probation_entered_at_utc"] = db.now()
    touch(analyst)
    return object_response(serialize.analyst(analyst), 200)


# ---------------------------------------------------------------- methods
METHOD_CREATE_FIELDS = [
    Field("name", "string", required=True, min_length=1, max_length=160),
    Field("discipline", "enum", required=True, choices=S.DISCIPLINES),
    Field("standard_hours_per_item", "number", required=True,
          exclusive_minimum="0.00", maximum="40.00"),
    Field("min_competency_level", "integer", required=True, minimum=1, maximum=5),
    Field("max_items_per_request", "integer", default=20, minimum=1, maximum=200),
    Field("is_consumptive", "boolean", default=False),
    Field("accreditation_scope_code", "string", required=True,
          min_length=1, max_length=40),
    Field("validation_study_item_count", "integer", default=None, minimum=0,
          nullable=True),
    Field("precision_cv_pct", "number", default=None, minimum="0.00",
          nullable=True),
    Field("validation_expires_at_utc", "instant", default=None, nullable=True),
]


@bp.route("/lab/methods", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def create_method():
    body = parse(METHOD_CREATE_FIELDS)
    row = new_row()
    row.update({
        "name": body["name"],
        "discipline": body["discipline"],
        "standard_hours_per_item": q2(body["standard_hours_per_item"]),
        "min_competency_level": body["min_competency_level"],
        "max_items_per_request": body["max_items_per_request"],
        "is_consumptive": body["is_consumptive"],
        "accreditation_scope_code": body["accreditation_scope_code"],
        "validation_status": "DRAFT",
        "validation_study_item_count": body["validation_study_item_count"],
        "precision_cv_pct": (
            None if body["precision_cv_pct"] is None
            else q2(body["precision_cv_pct"])
        ),
        "validated_at_utc": None,
        "validation_expires_at_utc": body["validation_expires_at_utc"],
        "retired_at_utc": None,
        "retirement_reason": None,
    })
    db.methods[row["id"]] = row
    return object_response(serialize.method(row), 201)


@bp.route("/lab/methods/<method_id>/validate", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def validate_method(method_id):
    method = S.find_method(method_id)
    body = parse([
        Field("validation_study_item_count", "integer", required=True, minimum=0),
        Field("precision_cv_pct", "number", required=True, minimum="0.00"),
        Field("expires_at_utc", "instant", required=True),
    ])
    if method["validation_status"] != "DRAFT":
        raise ApiError("ERR_METHOD_INVALID_STATE")
    if (body["validation_study_item_count"] < S.MIN_VALIDATION_STUDY_ITEMS
            or dec(body["precision_cv_pct"]) > S.MAX_VALIDATION_CV_PCT):
        raise ApiError("ERR_METHOD_VALIDATION_INSUFFICIENT")
    if body["expires_at_utc"] <= db.now():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "expires_at_utc must lie strictly after the logical clock.",
        )
    method["validation_study_item_count"] = body["validation_study_item_count"]
    method["precision_cv_pct"] = q2(body["precision_cv_pct"])
    method["validation_status"] = "VALIDATED"
    method["validated_at_utc"] = db.now()
    method["validation_expires_at_utc"] = body["expires_at_utc"]
    touch(method)
    return object_response(serialize.method(method), 200)


@bp.route("/lab/methods/<method_id>/retire", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def retire_method(method_id):
    method = S.find_method(method_id)
    body = parse([
        Field("retirement_reason", "string", required=True),
    ])
    if method["validation_status"] != "VALIDATED":
        raise ApiError("ERR_METHOD_INVALID_STATE")
    method["validation_status"] = "RETIRED"
    method["retired_at_utc"] = db.now()
    method["retirement_reason"] = body["retirement_reason"]
    touch(method)
    affected = []
    for request_row in db.examination_requests.values():
        if request_row["method_id"] != method["id"]:
            continue
        if request_row["status"] != "QUEUED":
            continue
        request_row["status"] = "CANCELLED"
        touch(request_row)
        if request_row["case_id"] not in affected:
            affected.append(request_row["case_id"])
    for case_id in affected:
        case_row = db.cases.get(case_id)
        if case_row is not None:
            S.case_recompute(case_row)
    return object_response(serialize.method(method), 200)


# ---------------------------------------------------------------- vendors
@bp.route("/lab/vendors", methods=["POST"])
@endpoint(LAB_DIRECTOR)
def create_vendor():
    body = parse([
        Field("name", "string", required=True, min_length=1, max_length=120),
        Field("accredited_disciplines", "enum_array", required=True,
              min_length=1, choices=S.DISCIPLINES),
        Field("accreditation_expires_at_utc", "instant", required=True),
        Field("concurrent_case_capacity", "integer", required=True,
              minimum=1, maximum=50),
        Field("unit_price_cents", "integer", required=True, minimum=1),
        Field("rush_surcharge_pct", "number", default=Decimal("0.00"),
              minimum="0.00", maximum="0.50"),
        Field("contract_ceiling_cents", "integer", required=True, minimum=1),
    ])
    row = new_row()
    row.update({
        "name": body["name"],
        "accredited_disciplines": body["accredited_disciplines"],
        "accreditation_expires_at_utc": body["accreditation_expires_at_utc"],
        "concurrent_case_capacity": body["concurrent_case_capacity"],
        "unit_price_cents": body["unit_price_cents"],
        "rush_surcharge_pct": q2(body["rush_surcharge_pct"]),
        "contract_ceiling_cents": body["contract_ceiling_cents"],
        "encumbered_cents": 0,
        "spent_cents": 0,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    db.vendors[row["id"]] = row
    return object_response(serialize.vendor(row), 201)


@bp.route("/lab/vendors/<vendor_id>/status", methods=["POST"])
@endpoint(LAB_DIRECTOR)
def set_vendor_status(vendor_id):
    vendor = S.find_vendor(vendor_id)
    body = parse([
        Field("status", "enum", required=True, choices=S.VENDOR_STATUSES),
        Field("suspension_reason", "string"),
    ])
    vendor["status"] = body["status"]
    if "suspension_reason" in body:
        vendor["suspension_reason"] = body["suspension_reason"]
    touch(vendor)
    return object_response(serialize.vendor(vendor), 200)
