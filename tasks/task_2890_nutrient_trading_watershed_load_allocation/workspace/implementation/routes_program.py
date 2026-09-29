"""Clock, watersheds, reaches, monitoring samples and adaptive reviews."""
from flask import Blueprint

import store
from auth import ALL_ROLES, require
from calc import (
    evaluate_response,
    monitoring_sample_load,
    rows_where,
    set_program_status,
)
from cascade import unwind_watershed
from common import collection_response, filtered, one, resolve, touched, view
from envelope import ok
from errors import ApiError
from store import (
    ZERO2,
    db,
    dec,
    new_row,
    now_iso,
    parse_date,
    parse_datetime,
    q2,
    q4,
    touch,
)
from validation import enum_arg, int_arg, spec, str_arg, validate_body

bp = Blueprint("program", __name__)

POLLUTANTS = ("TOTAL_NITROGEN", "TOTAL_PHOSPHORUS")
REACH_CLASSES = ("HEADWATER", "MAINSTEM", "COMPLIANCE_POINT", "BACKGROUND")
QA_STATUSES = ("ACCEPTED", "REJECTED", "PROVISIONAL")
PROGRAM_STATUSES = ("PROVISIONAL", "ACTIVE", "ADAPTIVE_HOLD", "TERMINATED")
REVIEW_STATUSES = ("OPEN", "FINALIZED")
VERDICTS = ("ON_TRACK", "OFF_TRACK", "INDETERMINATE")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(*ALL_ROLES)
    body = validate_body([spec("current_utc", "datetime")])
    moment = parse_datetime(body["current_utc"])
    store.db.clock = moment
    return ok({"current_utc": body["current_utc"]})


# --------------------------------------------------------------------------
# watersheds
# --------------------------------------------------------------------------
@bp.route("/watersheds", methods=["POST"])
def create_watershed():
    require("ProgramAdministrator")
    body = validate_body(
        [
            spec("name", "string"),
            spec("state_code", "string", pattern=r"^[A-Z]{2}$"),
            spec("watershed_code", "string", pattern=r"^[A-Z0-9]{2,8}$"),
            spec("pollutant", "enum", enum=POLLUTANTS),
            spec("baseline_year", "int"),
            spec("baseline_load_lbs_yr", "number", minimum=0, min_exclusive=True, dp=2),
            spec("eligible_zone_codes", "string_array"),
            spec("interim_target_pct", "number", required=False, minimum=0, maximum=100, dp=2,
                 default=q2("25.00")),
            spec("uncertainty_ratio", "number", required=False, minimum=1, dp=4, default=q4("2.0000")),
            spec("retirement_ratio", "number", required=False, minimum=0, maximum="0.5", dp=4,
                 default=q4("0.1000")),
            spec("equivalence_ratio", "number", required=False, minimum=0, min_exclusive=True, dp=4,
                 default=q4("1.0000")),
        ]
    )
    for existing in db.watersheds.values():
        if existing["watershed_code"] == body["watershed_code"]:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = new_row(
        "Watershed",
        name=body["name"],
        state_code=body["state_code"],
        watershed_code=body["watershed_code"],
        pollutant=body["pollutant"],
        baseline_year=body["baseline_year"],
        baseline_load_lbs_yr=q2(body["baseline_load_lbs_yr"]),
        eligible_zone_codes=body["eligible_zone_codes"],
        interim_target_pct=q2(body["interim_target_pct"]),
        uncertainty_ratio=q4(body["uncertainty_ratio"]),
        retirement_ratio=q4(body["retirement_ratio"]),
        equivalence_ratio=q4(body["equivalence_ratio"]),
        program_status="PROVISIONAL",
        trading_enabled=False,
        reserve_pool_lbs=ZERO2,
        serial_counter=0,
        allocated_wla_total_lbs_yr=ZERO2,
        allocated_la_total_lbs_yr=ZERO2,
    )
    db.watersheds[row["id"]] = row
    return one(row, 201)


@bp.route("/watersheds/<watershed_id>", methods=["GET"])
def get_watershed(watershed_id):
    require(*ALL_ROLES)
    return one(resolve(db.watersheds, "watershed_id", watershed_id))


WATERSHED_TRANSITIONS = {
    ("ACTIVE", "ADAPTIVE_HOLD"),
    ("ADAPTIVE_HOLD", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("ADAPTIVE_HOLD", "TERMINATED"),
}


@bp.route("/watersheds/<watershed_id>/program-status", methods=["POST"])
def watershed_program_status(watershed_id):
    require("ProgramAdministrator")
    watershed = resolve(db.watersheds, "watershed_id", watershed_id)
    body = validate_body(
        [
            spec("target_status", "enum", enum=PROGRAM_STATUSES),
            spec("reason", "string", required=False),
        ]
    )
    target = body["target_status"]
    current = watershed["program_status"]
    if (current, target) not in WATERSHED_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE")

    set_program_status(watershed, target, touched())
    if current == "ACTIVE" and target in ("ADAPTIVE_HOLD", "TERMINATED"):
        unwind_watershed(watershed, touched())
    return one(watershed)


# --------------------------------------------------------------------------
# reaches
# --------------------------------------------------------------------------
@bp.route("/reaches", methods=["POST"])
def create_reach():
    require("ProgramAdministrator", "TmdlAnalyst")
    body = validate_body(
        [
            spec("watershed_id", "id"),
            spec("reach_code", "string"),
            spec("trading_zone_code", "string"),
            spec("reach_class", "enum", enum=REACH_CLASSES),
            spec("delivery_factor", "number", minimum=0, min_exclusive=True, maximum=1, dp=4),
            spec("downstream_reach_id", "id", required=False),
        ]
    )
    watershed = resolve(db.watersheds, "watershed_id", body["watershed_id"])
    downstream = None
    if body["downstream_reach_id"] is not None:
        downstream = resolve(db.reaches, "downstream_reach_id", body["downstream_reach_id"])
        if downstream["watershed_id"] != watershed["id"]:
            raise ApiError("ERR_WATERSHED_MISMATCH")
    for existing in db.reaches.values():
        if existing["watershed_id"] == watershed["id"] and existing["reach_code"] == body["reach_code"]:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = new_row(
        "Reach",
        watershed_id=watershed["id"],
        reach_code=body["reach_code"],
        trading_zone_code=body["trading_zone_code"],
        reach_class=body["reach_class"],
        delivery_factor=q4(body["delivery_factor"]),
        downstream_reach_id=None if downstream is None else downstream["id"],
    )
    db.reaches[row["id"]] = row
    return one(row, 201)


@bp.route("/reaches/<reach_id>", methods=["GET"])
def get_reach(reach_id):
    require(*ALL_ROLES)
    return one(resolve(db.reaches, "reach_id", reach_id))


@bp.route("/reaches", methods=["GET"])
def list_reaches():
    require(*ALL_ROLES)
    filters = {
        "watershed_id": str_arg("watershed_id"),
        "downstream_reach_id": str_arg("downstream_reach_id"),
        "reach_class": enum_arg("reach_class", REACH_CLASSES),
        "trading_zone_code": str_arg("trading_zone_code"),
    }
    return collection_response(filtered(db.reaches, filters))


# --------------------------------------------------------------------------
# monitoring samples
# --------------------------------------------------------------------------
def _sample_sort(row):
    return (row["_sample_dt"], row["created_at"], row["_seq"])


@bp.route("/monitoring-samples", methods=["POST"])
def create_monitoring_sample():
    require("TmdlAnalyst", "ProgramAdministrator")
    body = validate_body(
        [
            spec("reach_id", "id"),
            spec("sample_datetime", "datetime"),
            spec("measured_conc_mg_l", "number", minimum=0, dp=4),
            spec("flow_cfs", "number", minimum=0, dp=2),
            spec("qa_status", "enum", enum=QA_STATUSES, required=False, default="ACCEPTED"),
        ]
    )
    reach = resolve(db.reaches, "reach_id", body["reach_id"])
    row = new_row(
        "MonitoringSample",
        versioned=False,
        reach_id=reach["id"],
        sample_datetime=body["sample_datetime"],
        measured_conc_mg_l=q4(body["measured_conc_mg_l"]),
        flow_cfs=q2(body["flow_cfs"]),
        qa_status=body["qa_status"],
        computed_load_lbs_yr=monitoring_sample_load(body["measured_conc_mg_l"], body["flow_cfs"]),
    )
    row["_sample_dt"] = parse_datetime(body["sample_datetime"])
    db.monitoring_samples[row["id"]] = row
    return one(row, 201)


@bp.route("/monitoring-samples/<monitoring_sample_id>", methods=["GET"])
def get_monitoring_sample(monitoring_sample_id):
    require(*ALL_ROLES)
    return one(resolve(db.monitoring_samples, "monitoring_sample_id", monitoring_sample_id))


@bp.route("/monitoring-samples", methods=["GET"])
def list_monitoring_samples():
    require(*ALL_ROLES)
    filters = {
        "reach_id": str_arg("reach_id"),
        "qa_status": enum_arg("qa_status", QA_STATUSES),
    }
    return collection_response(filtered(db.monitoring_samples, filters), sort_key=_sample_sort)


# --------------------------------------------------------------------------
# adaptive reviews
# --------------------------------------------------------------------------
def _review_sort(row):
    return (row["period_start_date"], row["created_at"], row["_seq"])


@bp.route("/watersheds/<watershed_id>/adaptive-reviews", methods=["POST"])
def create_adaptive_review(watershed_id):
    require("ProgramAdministrator")
    watershed = resolve(db.watersheds, "watershed_id", watershed_id)
    body = validate_body(
        [
            spec("review_label", "string"),
            spec("period_start_date", "date"),
            spec("period_end_date", "date"),
        ]
    )
    start = parse_date(body["period_start_date"])
    end = parse_date(body["period_end_date"])
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "period_end_date must fall strictly after period_start_date.")

    for existing in rows_where(db.adaptive_reviews, watershed_id=watershed["id"]):
        if existing["status"] not in ("OPEN", "FINALIZED"):
            continue
        other_start = parse_date(existing["period_start_date"])
        other_end = parse_date(existing["period_end_date"])
        clear = (start - other_end).days > 1 or (other_start - end).days > 1
        if not clear:
            raise ApiError("ERR_REVIEW_WINDOW_CONFLICT")

    row = new_row(
        "AdaptiveReview",
        watershed_id=watershed["id"],
        review_label=body["review_label"],
        period_start_date=body["period_start_date"],
        period_end_date=body["period_end_date"],
        status="OPEN",
        sample_count=None,
        observed_load_lbs_yr=None,
        achieved_reduction_pct=None,
        verdict=None,
        voided_transaction_count=None,
        finalized_at=None,
    )
    db.adaptive_reviews[row["id"]] = row
    return one(row, 201)


@bp.route("/adaptive-reviews/<adaptive_review_id>/finalize", methods=["POST"])
def finalize_adaptive_review(adaptive_review_id):
    require("ProgramAdministrator")
    review = resolve(db.adaptive_reviews, "adaptive_review_id", adaptive_review_id)
    watershed = db.watersheds.get(review["watershed_id"])
    if review["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    approved = None
    for assessment in rows_where(db.tmdl_assessments, watershed_id=review["watershed_id"], status="APPROVED"):
        approved = assessment
        break
    if approved is None:
        raise ApiError("ERR_TMDL_NOT_APPROVED")

    count, observed, achieved, verdict = evaluate_response(review, watershed)
    review["status"] = "FINALIZED"
    review["finalized_at"] = now_iso()
    review["sample_count"] = count
    review["observed_load_lbs_yr"] = observed
    review["achieved_reduction_pct"] = achieved
    review["verdict"] = verdict
    review["voided_transaction_count"] = 0
    touch(review, touched())

    if verdict == "OFF_TRACK":
        if watershed["program_status"] == "ACTIVE":
            set_program_status(watershed, "ADAPTIVE_HOLD", touched())
        review["voided_transaction_count"] = unwind_watershed(watershed, touched())
    return one(review)


@bp.route("/adaptive-reviews/<adaptive_review_id>", methods=["GET"])
def get_adaptive_review(adaptive_review_id):
    require(*ALL_ROLES)
    return one(resolve(db.adaptive_reviews, "adaptive_review_id", adaptive_review_id))


@bp.route("/adaptive-reviews", methods=["GET"])
def list_adaptive_reviews():
    require(*ALL_ROLES)
    filters = {
        "watershed_id": str_arg("watershed_id"),
        "status": enum_arg("status", REVIEW_STATUSES),
        "verdict": enum_arg("verdict", VERDICTS),
    }
    return collection_response(filtered(db.adaptive_reviews, filters), sort_key=_review_sort)
