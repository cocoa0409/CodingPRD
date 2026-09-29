"""Logical clock and the three registries: contaminants, laboratories and
entry points, plus the entry point's monitoring-frequency endpoints.
"""

from decimal import Decimal, ROUND_CEILING

from flask import Blueprint

import constants as C
import db
from db import store, touch
from errors import ApiError, invalid
from middleware import authenticate
from numeric import divide
from response import created_response, object_response
from routes.common import (
    apply_scalar_filters,
    detail,
    page,
    pagination,
    resolve,
)
from shape import Body

bp = Blueprint("registry", __name__)

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


# --------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = Body(["current_utc"])
    instant = body.instant("current_utc")
    store.clock = instant
    return object_response({"current_utc": store.clock})


# ---------------------------------------------------------------- contaminants
@bp.route("/contaminants", methods=["POST"])
def create_contaminant():
    authenticate(("UtilityAdmin",))
    body = Body(
        [
            "code",
            "mcl_ng_per_l",
            "trigger_level_ng_per_l",
            "required_mrl_ng_per_l",
            "hazard_index_member",
            "hbwc_ng_per_l",
            "notification_tier",
        ]
    )
    code = body.string("code", min_len=1, max_len=16, pattern=r"^[A-Z0-9_]{1,16}$")
    mcl = body.decimal("mcl_ng_per_l", exclusive_minimum=0)
    trigger = body.decimal("trigger_level_ng_per_l", exclusive_minimum=0)
    mrl = body.decimal("required_mrl_ng_per_l", exclusive_minimum=0)
    member = body.boolean("hazard_index_member", required=False, default=False)
    tier = body.enum("notification_tier", C.NOTIFICATION_TIERS, required=False, default="TIER_2")
    if trigger >= mcl:
        raise invalid("trigger_level_ng_per_l must be strictly below mcl_ng_per_l")
    if mrl > mcl:
        raise invalid("required_mrl_ng_per_l must not exceed mcl_ng_per_l")
    if member:
        hbwc = body.decimal("hbwc_ng_per_l", exclusive_minimum=0)
    else:
        if body.has("hbwc_ng_per_l") and body.raw("hbwc_ng_per_l") is not None:
            raise invalid("hbwc_ng_per_l must be null when hazard_index_member is false")
        hbwc = None
    for existing in store.contaminants.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CONTAMINANT_CODE")
    row = db.insert(
        "contaminants",
        {
            "code": code,
            "mcl_ng_per_l": mcl,
            "trigger_level_ng_per_l": trigger,
            "required_mrl_ng_per_l": mrl,
            "hazard_index_member": member,
            "hbwc_ng_per_l": hbwc,
            "notification_tier": tier,
        },
    )
    return created_response(db.public(row))


@bp.route("/contaminants/<row_id>", methods=["GET"])
def get_contaminant(row_id):
    authenticate(C.ANY_ROLE)
    return detail("contaminants", row_id)


# ---------------------------------------------------------------- laboratories
@bp.route("/laboratories", methods=["POST"])
def create_laboratory():
    authenticate(("UtilityAdmin",))
    body = Body(
        [
            "name",
            "certification_id",
            "certified_methods",
            "lowest_achievable_dl_ng_per_l",
            "certification_expires_on",
            "daily_analysis_capacity",
        ]
    )
    name = body.string("name", min_len=1, max_len=120)
    certification_id = body.string("certification_id", min_len=1, max_len=40)
    methods = body.string_list("certified_methods", choices=C.METHODS)
    lowest = body.decimal("lowest_achievable_dl_ng_per_l", exclusive_minimum=0)
    expires = body.date("certification_expires_on")
    capacity = body.integer("daily_analysis_capacity", required=False, default=3, minimum=1)
    for existing in store.laboratories.values():
        if existing["certification_id"] == certification_id:
            raise ApiError("ERR_DUPLICATE_CERTIFICATION_ID")
    row = db.insert(
        "laboratories",
        {
            "name": name,
            "certification_id": certification_id,
            "certified_methods": methods,
            "lowest_achievable_dl_ng_per_l": lowest,
            "certification_expires_on": expires,
            "daily_analysis_capacity": capacity,
        },
    )
    return created_response(db.public(row))


@bp.route("/laboratories/<row_id>", methods=["GET"])
def get_laboratory(row_id):
    authenticate(C.ANY_ROLE)
    return detail("laboratories", row_id)


# ---------------------------------------------------------------- entry points
@bp.route("/entry-points", methods=["POST"])
def create_entry_point():
    authenticate(("UtilityAdmin",))
    body = Body(["label", "source_type", "population_served"])
    label = body.string("label", min_len=1, max_len=40)
    source_type = body.enum("source_type", C.SOURCE_TYPES)
    population = body.integer("population_served", minimum=1)
    for existing in store.entry_points.values():
        if existing["label"] == label:
            raise ApiError("ERR_DUPLICATE_ENTRY_POINT_LABEL")
    accounts = int(
        divide(Decimal(population), C.PERSONS_PER_ACCOUNT).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    kgal = accounts * C.KGAL_PER_ACCOUNT_PER_YEAR
    row = db.insert(
        "entry_points",
        {
            "label": label,
            "source_type": source_type,
            "population_served": population,
            "monitoring_status": "INITIAL",
            "requested_monitoring_status": None,
            "treatment_status": "NONE",
            "compliance_posture": "COMPLIANT",
            "max_compliance_ratio": ZERO4,
            "hazard_index": ZERO2,
            "accepted_result_count": 0,
            "consecutive_qualifying_quarters": 0,
            "consecutive_invalidated_samples": 0,
            "open_violation_count": 0,
            "served_account_count": accounts,
            "annual_billed_kgal": kgal,
            "baseline_annual_revenue_cents": kgal * C.BASE_RATE_CENTS_PER_KGAL,
        },
    )
    return created_response(db.public(row))


@bp.route("/entry-points", methods=["GET"])
def list_entry_points():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("entry_points")
    rows = apply_scalar_filters(
        rows, ["source_type", "monitoring_status", "compliance_posture", "treatment_status"]
    )
    return page(rows, limit, offset)


@bp.route("/entry-points/<row_id>", methods=["GET"])
def get_entry_point(row_id):
    authenticate(C.ANY_ROLE)
    return detail("entry_points", row_id)


@bp.route("/entry-points/<row_id>/monitoring-status", methods=["POST"])
def set_monitoring_status(row_id):
    authenticate(("UtilityAdmin",))
    entry_point = resolve("entry_points", row_id)
    body = Body(["action", "reason"])
    action = body.enum("action", ("SUSPEND", "RESUME"))
    body.string("reason", required=False, default=None, max_len=None)
    current = entry_point["monitoring_status"]
    if action == "SUSPEND":
        if current == "SUSPENDED":
            raise ApiError("ERR_MONITORING_STATE_INVALID")
        entry_point["monitoring_status"] = "SUSPENDED"
        entry_point["requested_monitoring_status"] = None
    else:
        if current != "SUSPENDED":
            raise ApiError("ERR_MONITORING_STATE_INVALID")
        entry_point["monitoring_status"] = "QUARTERLY"
        entry_point["consecutive_invalidated_samples"] = 0
    touch(entry_point)
    return object_response(db.public(entry_point))


@bp.route("/entry-points/<row_id>/monitoring-reduction-requests", methods=["POST"])
def request_monitoring_reduction(row_id):
    authenticate(("ComplianceOfficer",))
    entry_point = resolve("entry_points", row_id)
    body = Body(["target_status", "justification"])
    target = body.enum("target_status", ("ANNUAL", "TRIENNIAL"))
    body.string("justification", required=False, default=None)
    if entry_point["monitoring_status"] != "QUARTERLY":
        raise ApiError("ERR_MONITORING_STATE_INVALID")
    if entry_point["compliance_posture"] == "VIOLATION_PENDING":
        raise ApiError("ERR_VIOLATION_PENDING_BLOCKS_REDUCTION")
    if entry_point["open_violation_count"] != 0:
        raise ApiError("ERR_OPEN_VIOLATION_BLOCKS_REDUCTION")
    if entry_point["consecutive_qualifying_quarters"] < C.REDUCTION_MIN_QUARTERS_ANNUAL:
        raise ApiError("ERR_INSUFFICIENT_MONITORING_HISTORY")
    if (
        target == "TRIENNIAL"
        and entry_point["consecutive_qualifying_quarters"] < C.REDUCTION_MIN_QUARTERS_TRIENNIAL
    ):
        raise ApiError("ERR_TRIENNIAL_HISTORY_INSUFFICIENT")
    entry_point["monitoring_status"] = "REDUCTION_PENDING"
    entry_point["requested_monitoring_status"] = target
    touch(entry_point)
    return object_response(db.public(entry_point))


@bp.route("/entry-points/<row_id>/monitoring-reduction-decisions", methods=["POST"])
def decide_monitoring_reduction(row_id):
    authenticate(("StateRegulator",))
    entry_point = resolve("entry_points", row_id)
    body = Body(["approve", "decision_note"])
    approve = body.boolean("approve")
    body.string("decision_note", required=False, default=None)
    if entry_point["monitoring_status"] != "REDUCTION_PENDING":
        raise ApiError("ERR_MONITORING_STATE_INVALID")
    if entry_point["compliance_posture"] == "VIOLATION_PENDING":
        raise ApiError("ERR_VIOLATION_PENDING_BLOCKS_REDUCTION")
    if approve:
        entry_point["monitoring_status"] = entry_point["requested_monitoring_status"] or "QUARTERLY"
    else:
        entry_point["monitoring_status"] = "QUARTERLY"
    entry_point["requested_monitoring_status"] = None
    touch(entry_point)
    return object_response(db.public(entry_point))
