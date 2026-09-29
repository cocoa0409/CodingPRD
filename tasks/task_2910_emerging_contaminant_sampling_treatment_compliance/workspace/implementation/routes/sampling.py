"""Sample collection, custody transfer, receipt, invalidation and reinstatement,
plus analytical reporting and review (PRD sections 3.2, 3.3 and 3.4).
"""

from decimal import Decimal

from flask import Blueprint

import constants as C
import db
from db import store, touch, now
from errors import ApiError, invalid
from middleware import authenticate
from numeric import divide, q2
from response import created_response, object_response
from routes.common import (
    apply_scalar_filters,
    detail,
    filter_fk,
    page,
    pagination,
    resolve,
)
from services import compliance
from shape import Body, filter_value, period_of

bp = Blueprint("sampling", __name__)

LAB_SCOPED = True


# --------------------------------------------------------------------- samples
@bp.route("/samples", methods=["POST"])
def create_sample():
    user_id, _role = authenticate(("SamplingTechnician",))
    body = Body(
        [
            "entry_point_id",
            "panel_contaminant_ids",
            "monitoring_period",
            "collected_at",
            "protocol",
            "ptfe_free_kit",
            "field_blank_included",
            "preservative_lot",
            "resample_of_sample_id",
        ]
    )
    entry_point_id = body.string("entry_point_id")
    panel = body.string_list("panel_contaminant_ids")
    monitoring_period = body.period("monitoring_period")
    collected_at = body.instant("collected_at")
    protocol = body.enum("protocol", C.SAMPLE_PROTOCOLS)
    ptfe_free_kit = body.boolean("ptfe_free_kit")
    field_blank_included = body.boolean("field_blank_included")
    preservative_lot = body.string("preservative_lot", min_len=1, max_len=40)
    resample_of = body.string("resample_of_sample_id", required=False, default=None)

    entry_point = resolve("entry_points", entry_point_id)
    for contaminant_id in panel:
        resolve("contaminants", contaminant_id)
    target = None
    if resample_of is not None:
        target = resolve("samples", resample_of)

    if entry_point["monitoring_status"] == "SUSPENDED":
        raise ApiError("ERR_MONITORING_SUSPENDED")
    if not ptfe_free_kit:
        raise ApiError("ERR_PROHIBITED_SAMPLING_MATERIAL")
    if not field_blank_included:
        raise ApiError("ERR_FIELD_BLANK_REQUIRED")
    if target is not None and target["status"] != "INVALIDATED":
        raise ApiError("ERR_RESAMPLE_TARGET_NOT_INVALIDATED")
    if collected_at > now():
        raise ApiError("ERR_COLLECTED_IN_FUTURE")
    if monitoring_period != period_of(collected_at):
        raise ApiError("ERR_MONITORING_PERIOD_MISMATCH")

    row = db.insert(
        "samples",
        {
            "entry_point_id": entry_point_id,
            "panel_contaminant_ids": panel,
            "collector_user_id": user_id,
            "monitoring_period": monitoring_period,
            "collected_at": collected_at,
            "protocol": protocol,
            "ptfe_free_kit": ptfe_free_kit,
            "field_blank_included": field_blank_included,
            "preservative_lot": preservative_lot,
            "resample_of_sample_id": resample_of,
            "assigned_laboratory_id": None,
            "shipped_at": None,
            "received_at": None,
            "chain_of_custody_intact": None,
            "field_blank_result_ng_per_l": None,
            "status": "COLLECTED",
            "status_before_invalidation": None,
            "invalidation_reason": None,
        },
    )
    return created_response(db.public(row))


@bp.route("/samples", methods=["GET"])
def list_samples():
    authenticate(C.ANY_ROLE, laboratory_identity=LAB_SCOPED)
    limit, offset = pagination()
    rows = db.sorted_rows("samples")
    rows = filter_fk(rows, "entry_point_id", "entry_points")
    rows = filter_fk(rows, "assigned_laboratory_id", "laboratories")
    rows = filter_fk(rows, "resample_of_sample_id", "samples")
    contaminant_id = filter_value("panel_contaminant_ids")
    if contaminant_id is not None:
        resolve("contaminants", contaminant_id)
        rows = [row for row in rows if contaminant_id in row["panel_contaminant_ids"]]
    rows = apply_scalar_filters(rows, ["collector_user_id", "monitoring_period", "status"])
    return page(rows, limit, offset)


@bp.route("/samples/<row_id>", methods=["GET"])
def get_sample(row_id):
    authenticate(C.ANY_ROLE)
    return detail("samples", row_id)


@bp.route("/samples/<row_id>/ship", methods=["POST"])
def ship_sample(row_id):
    authenticate(("SamplingTechnician",))
    sample = resolve("samples", row_id)
    body = Body(["laboratory_id"])
    laboratory_id = body.string("laboratory_id")
    resolve("laboratories", laboratory_id)
    if sample["status"] != "COLLECTED":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")
    if now() < sample["collected_at"]:
        raise ApiError("ERR_SHIP_BEFORE_COLLECTION")
    sample["assigned_laboratory_id"] = laboratory_id
    sample["shipped_at"] = now()
    sample["status"] = "IN_TRANSIT"
    touch(sample)
    return object_response(db.public(sample))


@bp.route("/samples/<row_id>/receive", methods=["POST"])
def receive_sample(row_id):
    user_id, _role = authenticate(("LaboratoryManager",), laboratory_identity=LAB_SCOPED)
    sample = resolve("samples", row_id)
    body = Body(["chain_of_custody_intact", "field_blank_result_ng_per_l"])
    custody_intact = body.boolean("chain_of_custody_intact")
    blank = body.decimal("field_blank_result_ng_per_l", minimum=0)
    if sample["assigned_laboratory_id"] != user_id:
        raise ApiError("ERR_LABORATORY_ASSIGNMENT_MISMATCH")
    if sample["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    entry_point = store.entry_points.get(sample["entry_point_id"])
    sample["chain_of_custody_intact"] = custody_intact
    sample["field_blank_result_ng_per_l"] = blank
    if custody_intact and blank < C.FIELD_BLANK_LIMIT_NG_PER_L:
        sample["status"] = "RECEIVED"
        sample["received_at"] = now()
        if entry_point is not None:
            entry_point["consecutive_invalidated_samples"] = 0
            touch(entry_point)
    else:
        sample["status"] = "INVALIDATED"
        sample["invalidation_reason"] = (
            "CHAIN_OF_CUSTODY_BROKEN" if not custody_intact else "FIELD_BLANK_CONTAMINATED"
        )
        sample["status_before_invalidation"] = None
        if entry_point is not None:
            compliance.register_invalidation(entry_point)
            touch(entry_point)
    touch(sample)
    return object_response(db.public(sample))


@bp.route("/samples/<row_id>/invalidate", methods=["POST"])
def invalidate_sample(row_id):
    authenticate(("ComplianceOfficer",))
    sample = resolve("samples", row_id)
    body = Body(["invalidation_reason"])
    reason = body.enum("invalidation_reason", C.INVALIDATION_REASONS)
    if sample["status"] not in ("RECEIVED", "ANALYZED"):
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    sample["status_before_invalidation"] = sample["status"]
    sample["invalidation_reason"] = reason
    sample["status"] = "INVALIDATED"
    touch(sample)

    for result in db.sorted_rows("lab_results"):
        if result["sample_id"] != sample["id"]:
            continue
        if result["status"] == "SUBMITTED":
            result["status"] = "REJECTED"
            result["reject_reason_code"] = "QC_FAILURE"
            touch(result)
        elif result["status"] == "ACCEPTED":
            result["status"] = "SUPERSEDED"
            touch(result)

    entry_point = store.entry_points.get(sample["entry_point_id"])
    if entry_point is not None:
        compliance.rederive_entry_point(entry_point)
        compliance.register_invalidation(entry_point)
        touch(entry_point)
    return object_response(db.public(sample))


@bp.route("/samples/<row_id>/reinstate", methods=["POST"])
def reinstate_sample(row_id):
    authenticate(("ComplianceOfficer",))
    sample = resolve("samples", row_id)
    Body([])
    if sample["status"] != "INVALIDATED":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")
    if (
        sample["invalidation_reason"] != "OPERATOR_ERROR"
        or sample["status_before_invalidation"] is None
    ):
        raise ApiError("ERR_INVALIDATION_NOT_REVERSIBLE")

    sample["status"] = sample["status_before_invalidation"]
    sample["status_before_invalidation"] = None
    sample["invalidation_reason"] = None
    touch(sample)

    for result in db.sorted_rows("lab_results"):
        if result["sample_id"] != sample["id"]:
            continue
        if result["status"] == "SUPERSEDED":
            result["status"] = "ACCEPTED"
            touch(result)

    entry_point = store.entry_points.get(sample["entry_point_id"])
    if entry_point is not None:
        compliance.rederive_entry_point(entry_point)
        streak = entry_point["consecutive_invalidated_samples"] - 1
        entry_point["consecutive_invalidated_samples"] = streak if streak > 0 else 0
        touch(entry_point)
    return object_response(db.public(sample))


# ------------------------------------------------------------------ lab results
@bp.route("/lab-results", methods=["POST"])
def create_lab_result():
    user_id, _role = authenticate(("LaboratoryManager",), laboratory_identity=LAB_SCOPED)
    body = Body(
        [
            "sample_id",
            "contaminant_id",
            "method",
            "reported_ng_per_l",
            "detection_limit_ng_per_l",
            "analyzed_at",
        ]
    )
    sample_id = body.string("sample_id")
    contaminant_id = body.string("contaminant_id")
    method = body.enum("method", C.METHODS)
    reported = body.decimal("reported_ng_per_l", minimum=0)
    detection_limit = body.decimal("detection_limit_ng_per_l", exclusive_minimum=0)
    analyzed_at = body.instant("analyzed_at")

    sample = resolve("samples", sample_id)
    contaminant = resolve("contaminants", contaminant_id)
    laboratory = store.laboratories[user_id]

    if sample["assigned_laboratory_id"] != user_id:
        raise ApiError("ERR_LABORATORY_ASSIGNMENT_MISMATCH")
    if sample["status"] != "RECEIVED":
        raise ApiError("ERR_SAMPLE_NOT_RECEIVED")
    if contaminant_id not in sample["panel_contaminant_ids"]:
        raise ApiError("ERR_CONTAMINANT_NOT_IN_PANEL")
    if method not in laboratory["certified_methods"]:
        raise ApiError("ERR_METHOD_NOT_CERTIFIED")
    if detection_limit > contaminant["required_mrl_ng_per_l"]:
        raise ApiError("ERR_DETECTION_LIMIT_TOO_HIGH")
    if detection_limit < laboratory["lowest_achievable_dl_ng_per_l"]:
        raise ApiError("ERR_DETECTION_LIMIT_BELOW_CAPABILITY")

    elapsed_hours = divide(
        Decimal((analyzed_at - sample["collected_at"]).total_seconds()), Decimal(3600)
    )
    if elapsed_hours > C.HOLDING_TIME_HOURS_BY_METHOD[method]:
        raise ApiError("ERR_HOLDING_TIME_EXCEEDED")
    if analyzed_at >= laboratory["certification_expires_on"]:
        raise ApiError("ERR_LABORATORY_CERTIFICATION_EXPIRED")
    if analyzed_at < sample["collected_at"]:
        raise ApiError("ERR_ANALYZED_BEFORE_COLLECTION")

    live = 0
    for existing in store.lab_results.values():
        if existing["laboratory_id"] != user_id:
            continue
        if existing["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if existing["analyzed_at"].date() == analyzed_at.date():
            live += 1
    if live >= laboratory["daily_analysis_capacity"]:
        raise ApiError("ERR_LAB_DAILY_CAPACITY_EXCEEDED")

    censored = reported < detection_limit
    row = db.insert(
        "lab_results",
        {
            "sample_id": sample_id,
            "laboratory_id": user_id,
            "contaminant_id": contaminant_id,
            "method": method,
            "reported_ng_per_l": reported,
            "detection_limit_ng_per_l": detection_limit,
            "analyzed_at": analyzed_at,
            "censored": censored,
            "compliance_value_ng_per_l": Decimal("0.00") if censored else reported,
            "planning_value_ng_per_l": (
                q2(divide(detection_limit, 2)) if censored else reported
            ),
            "status": "SUBMITTED",
            "review_note": None,
            "reject_reason_code": None,
        },
    )
    return created_response(db.public(row))


@bp.route("/lab-results", methods=["GET"])
def list_lab_results():
    authenticate(C.ANY_ROLE, laboratory_identity=LAB_SCOPED)
    limit, offset = pagination()
    rows = db.sorted_rows("lab_results")
    rows = filter_fk(rows, "sample_id", "samples")
    rows = filter_fk(rows, "laboratory_id", "laboratories")
    rows = filter_fk(rows, "contaminant_id", "contaminants")
    rows = apply_scalar_filters(rows, ["status"])
    return page(rows, limit, offset)


@bp.route("/lab-results/<row_id>", methods=["GET"])
def get_lab_result(row_id):
    authenticate(C.ANY_ROLE)
    return detail("lab_results", row_id)


@bp.route("/lab-results/<row_id>/review", methods=["POST"])
def review_lab_result(row_id):
    authenticate(("ComplianceOfficer",))
    result = resolve("lab_results", row_id)
    body = Body(["action", "reject_reason_code", "review_note"])
    action = body.enum("action", ("ACCEPT", "REJECT"))
    reject_reason_code = body.enum(
        "reject_reason_code", C.REJECT_REASON_CODES, required=False, default=None
    )
    review_note = body.string("review_note", required=False, default=None)
    if action == "REJECT" and reject_reason_code is None:
        raise invalid("reject_reason_code is required when rejecting a result")

    if result["status"] != "SUBMITTED":
        raise ApiError("ERR_RESULT_STATE_INVALID")

    sample = store.samples.get(result["sample_id"])

    if action == "REJECT":
        result["status"] = "REJECTED"
        result["reject_reason_code"] = reject_reason_code
        result["review_note"] = review_note
        touch(result)
        return object_response(db.public(result))

    if sample is None or sample["status"] != "RECEIVED":
        raise ApiError("ERR_SAMPLE_NOT_RECEIVED")
    entry_point = store.entry_points.get(sample["entry_point_id"])
    for other in store.lab_results.values():
        if other["id"] == result["id"] or other["status"] != "ACCEPTED":
            continue
        if other["contaminant_id"] != result["contaminant_id"]:
            continue
        other_sample = store.samples.get(other["sample_id"])
        if other_sample is None:
            continue
        if other_sample["entry_point_id"] != sample["entry_point_id"]:
            continue
        if other_sample["monitoring_period"] != sample["monitoring_period"]:
            continue
        raise ApiError("ERR_DUPLICATE_PERIOD_RESULT")

    result["status"] = "ACCEPTED"
    result["review_note"] = review_note
    touch(result)

    if entry_point is not None and entry_point["monitoring_status"] == "INITIAL":
        entry_point["monitoring_status"] = "QUARTERLY"
    if sample["status"] == "RECEIVED" and compliance.sample_panel_complete(sample):
        sample["status"] = "ANALYZED"
        touch(sample)
    if entry_point is not None:
        compliance.rederive_entry_point(entry_point)
        touch(entry_point)
    return object_response(db.public(result))
