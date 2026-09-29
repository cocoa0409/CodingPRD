"""Growing areas: registration, classification decisions, reopening, the
computed classification summary and the two monitoring journals (PRD 3.1-3.3).
"""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers as ser
from cascades import area_closure_cascade, close_area_for_sample_failure
from core import (
    ALL_ROLES,
    CLASSIFICATIONS,
    DEFAULT_CLEAN_SAMPLE_MPN_LIMIT,
    DEFAULT_RAINFALL_CLOSURE_HOURS,
    DEFAULT_RAINFALL_THRESHOLD_IN,
    DEFAULT_REOPEN_SAMPLE_COUNT,
    GEOMEAN_APPROVED_LIMIT,
    HARVEST_STATUSES,
    MIN_SAMPLES_FOR_DECISION,
    RESTRICTIVENESS_RANK,
    ROLE_AUTHORITY,
    ROLE_OPERATOR,
    SAMPLE_STATUSES,
    STAT_VARIANTS,
    apply_changes,
    authenticate,
    check_not_future_instant,
    clock,
    db,
    envelope_array,
    envelope_object,
    f_bool,
    f_enum,
    f_instant,
    f_int,
    f_num,
    f_str,
    get_area,
    invalid,
    json_body,
    pagination,
    paginate,
    q,
    q_bool,
    q_enum,
    q_str,
    sort_default,
    sort_journal,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("areas", __name__)


# --------------------------------------------------------------------------
# Registration and reads
# --------------------------------------------------------------------------
@bp.route("/growing-areas", methods=["POST"])
def register_growing_area():
    authenticate([ROLE_AUTHORITY])
    body = json_body()
    code = f_str(body, "code", min_len=3, max_len=32)
    water_body = f_str(body, "water_body")
    threshold = f_num(
        body,
        "rainfall_closure_threshold_in",
        required=False,
        default=DEFAULT_RAINFALL_THRESHOLD_IN,
        exclusive_minimum=0,
    )
    closure_hours = f_int(
        body,
        "rainfall_closure_hours",
        required=False,
        default=DEFAULT_RAINFALL_CLOSURE_HOURS,
        minimum=1,
    )
    reopen_required = f_int(
        body,
        "reopen_sample_count_required",
        required=False,
        default=DEFAULT_REOPEN_SAMPLE_COUNT,
        minimum=1,
    )
    clean_limit = f_num(
        body,
        "clean_sample_mpn_limit",
        required=False,
        default=DEFAULT_CLEAN_SAMPLE_MPN_LIMIT,
    )
    plan_on_file = f_bool(
        body, "conditional_management_plan_on_file", required=False, default=False
    )

    for existing in db.growing_areas.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_AREA_CODE")

    area = {
        "code": code,
        "water_body": water_body,
        "classification": "APPROVED",
        "harvest_status": "OPEN",
        "rainfall_closure_threshold_in": q(threshold, 2),
        "rainfall_closure_hours": closure_hours,
        "reopen_sample_count_required": reopen_required,
        "clean_sample_mpn_limit": clean_limit,
        "conditional_management_plan_on_file": plan_on_file,
        "last_closure_started_at": None,
        "closure_reopen_eligible_at": None,
        "consecutive_clean_samples": 0,
        "accepted_sample_count": 0,
        "geometric_mean_mpn": None,
        "p90_mpn": None,
        "eligible_classification": "INSUFFICIENT_DATA",
        "open_authorization_count": 0,
    }
    stamp_new(area)
    db.growing_areas[area["id"]] = area
    return envelope_object(ser.growing_area(area)), 201


@bp.route("/growing-areas/<area_id>", methods=["GET"])
def read_growing_area(area_id):
    authenticate(ALL_ROLES)
    area = get_area(area_id)
    return envelope_object(ser.growing_area(area)), 200


@bp.route("/growing-areas", methods=["GET"])
def list_growing_areas():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    water_body = q_str("water_body")
    classification = q_enum("classification", CLASSIFICATIONS)
    harvest_status = q_enum("harvest_status", HARVEST_STATUSES)
    rows = []
    for area in db.growing_areas.values():
        if water_body is not None and area["water_body"] != water_body:
            continue
        if classification is not None and area["classification"] != classification:
            continue
        if harvest_status is not None and area["harvest_status"] != harvest_status:
            continue
        rows.append(area)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.growing_area(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# Classification decisions (PRD 3.1)
# --------------------------------------------------------------------------
def _requires_data_support(current, target):
    current_rank = RESTRICTIVENESS_RANK[current]
    target_rank = RESTRICTIVENESS_RANK[target]
    strict_downgrade = target_rank > current_rank
    if strict_downgrade and target in ("RESTRICTED", "PROHIBITED"):
        return False
    return True


def _data_supports(current, target, eligible):
    if target == "APPROVED":
        return eligible == "APPROVED"
    if target == "CONDITIONALLY_APPROVED":
        return eligible in ("APPROVED", "RESTRICTED")
    if target == "RESTRICTED" and current == "PROHIBITED":
        return eligible in ("APPROVED", "RESTRICTED")
    return True


@bp.route("/growing-areas/<area_id>/classification-decisions", methods=["POST"])
def record_classification_decision(area_id):
    authenticate([ROLE_AUTHORITY])
    area = get_area(area_id)
    body = json_body()
    target = f_enum(body, "classification", CLASSIFICATIONS)
    expected_version = f_int(body, "expected_area_version")
    f_str(body, "decision_note", required=False, default=None)

    # Rung 6 — optimistic concurrency (PRD 2.8).
    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_AREA_VERSION")

    # Rung 12 — business constraints, in the order PRD 3.1 declares.
    if area["accepted_sample_count"] < MIN_SAMPLES_FOR_DECISION:
        raise ApiError("ERR_INSUFFICIENT_SAMPLE_DATA")
    current = area["classification"]
    if _requires_data_support(current, target) and not _data_supports(
        current, target, area["eligible_classification"]
    ):
        raise ApiError("ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA")
    current_rank = RESTRICTIVENESS_RANK[current]
    target_rank = RESTRICTIVENESS_RANK[target]
    if target_rank <= current_rank and (current_rank - target_rank) != 1:
        raise ApiError("ERR_CLASSIFICATION_STEP_SKIPPED")
    if target == "CONDITIONALLY_APPROVED" and not area[
        "conditional_management_plan_on_file"
    ]:
        raise ApiError("ERR_CONDITIONAL_PLAN_REQUIRED")

    if target != "PROHIBITED":
        apply_changes(area, {"classification": target})
    else:
        moment = clock.now()
        apply_changes(
            area,
            {
                "classification": "PROHIBITED",
                "harvest_status": "CLOSED_SAMPLE_FAILURE",
                "last_closure_started_at": moment,
                "closure_reopen_eligible_at": moment
                + timedelta(hours=area["rainfall_closure_hours"]),
                "consecutive_clean_samples": 0,
            },
        )
        area_closure_cascade(area)
    return envelope_object(ser.growing_area(area)), 200


# --------------------------------------------------------------------------
# Reopening (PRD 3.3)
# --------------------------------------------------------------------------
@bp.route("/growing-areas/<area_id>/reopen", methods=["POST"])
def reopen_growing_area(area_id):
    authenticate([ROLE_AUTHORITY])
    area = get_area(area_id)
    body = json_body()
    f_str(body, "reopen_note", required=False, default=None)

    # Rung 7 — the area must not already be open.
    if area["harvest_status"] == "OPEN":
        raise ApiError("ERR_AREA_ALREADY_OPEN")
    # Rung 8 — a prohibited area may not be reopened.
    if area["classification"] == "PROHIBITED":
        raise ApiError("ERR_AREA_PROHIBITED")
    # Rung 10 — the closure duration must have elapsed.
    eligible_at = area["closure_reopen_eligible_at"]
    if eligible_at is not None and clock.now().replace(
        microsecond=0
    ) < eligible_at.replace(microsecond=0):
        raise ApiError("ERR_REOPEN_TOO_EARLY")
    # Rung 12 — the clean-sample run must be long enough.
    if area["consecutive_clean_samples"] < area["reopen_sample_count_required"]:
        raise ApiError("ERR_INSUFFICIENT_CLEAN_SAMPLES")

    apply_changes(
        area,
        {
            "harvest_status": "OPEN",
            "consecutive_clean_samples": 0,
            "closure_reopen_eligible_at": None,
        },
    )
    return envelope_object(ser.growing_area(area)), 200


# --------------------------------------------------------------------------
# The computed classification summary (PRD 3.2)
# --------------------------------------------------------------------------
@bp.route("/growing-areas/<area_id>/classification-summary", methods=["GET"])
def classification_summary(area_id):
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    area = get_area(area_id)
    variant = q_enum("variant", STAT_VARIANTS)
    if variant is None:
        variant = "SYSTEMATIC_RANDOM"
    stats = calc.compute_statistics(area, variant)
    return envelope_object(ser.classification_summary(stats)), 200


# --------------------------------------------------------------------------
# Water samples (PRD 3.2)
# --------------------------------------------------------------------------
@bp.route("/growing-areas/<area_id>/water-samples", methods=["POST"])
def ingest_water_sample(area_id):
    authenticate([ROLE_AUTHORITY])
    area = get_area(area_id)
    body = json_body()
    station_code = f_str(body, "station_code")
    collected_at = f_instant(body, "collected_at")
    mpn = f_num(body, "fecal_coliform_mpn", minimum=1)
    water_temp_c = f_num(body, "water_temp_c")
    salinity_ppt = f_num(body, "salinity_ppt", required=False, default=None)

    # Rung 10 — nothing future-dated.
    check_not_future_instant(collected_at)

    # Supersession: one accepted figure per station per calendar day.
    collected_date = collected_at.date()
    for existing in calc.area_samples(area["id"]):
        if existing["sample_status"] != "ACCEPTED":
            continue
        if existing["station_code"] != station_code:
            continue
        if existing["collected_at"].date() != collected_date:
            continue
        existing["sample_status"] = "SUPERSEDED"

    sample = {
        "growing_area_id": area["id"],
        "station_code": station_code,
        "collected_at": collected_at,
        "fecal_coliform_mpn": mpn,
        "water_temp_c": water_temp_c,
        "salinity_ppt": salinity_ppt,
        "sample_status": "ACCEPTED",
    }
    stamp_new(sample, versioned=False)
    db.water_samples[sample["id"]] = sample

    # The sweep: recompute, then ask whether the new data condemned the area.
    calc.recompute_area_statistics(area)
    eligible = area["eligible_classification"]
    geometric_mean = area["geometric_mean_mpn"]
    if (
        area["accepted_sample_count"] >= MIN_SAMPLES_FOR_DECISION
        and geometric_mean is not None
        and geometric_mean > GEOMEAN_APPROVED_LIMIT
        and eligible in RESTRICTIVENESS_RANK
        and RESTRICTIVENESS_RANK[eligible]
        > RESTRICTIVENESS_RANK[area["classification"]]
    ):
        close_area_for_sample_failure(area, eligible, clock.now())

    return envelope_object(ser.water_sample(sample)), 201


@bp.route("/growing-areas/<area_id>/water-samples", methods=["GET"])
def list_water_samples(area_id):
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    area = get_area(area_id)
    limit, offset = pagination()
    sample_status = q_enum("sample_status", SAMPLE_STATUSES)
    rows = []
    for sample in calc.area_samples(area["id"]):
        if sample_status is not None and sample["sample_status"] != sample_status:
            continue
        rows.append(sample)
    rows = sort_journal(rows, "collected_at", True)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.water_sample(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# Rainfall events (PRD 3.3)
# --------------------------------------------------------------------------
@bp.route("/growing-areas/<area_id>/rainfall-events", methods=["POST"])
def ingest_rainfall_event(area_id):
    authenticate([ROLE_AUTHORITY])
    area = get_area(area_id)
    body = json_body()
    gauge_code = f_str(body, "gauge_code")
    observed_at = f_instant(body, "observed_at")
    inches = f_num(body, "inches_24h", minimum=0)

    # Rung 10 — nothing future-dated.
    check_not_future_instant(observed_at)

    inches = q(inches, 2)
    triggered = inches >= area["rainfall_closure_threshold_in"]
    event = {
        "growing_area_id": area["id"],
        "gauge_code": gauge_code,
        "observed_at": observed_at,
        "inches_24h": inches,
        "triggered_closure": triggered,
        "voided_authorization_count": 0,
    }
    stamp_new(event, versioned=False)
    db.rainfall_events[event["id"]] = event

    if triggered:
        status = area["harvest_status"]
        started = area["last_closure_started_at"]
        closes = status == "OPEN" or (
            status == "CLOSED_RAINFALL"
            and started is not None
            and observed_at.replace(microsecond=0) > started.replace(microsecond=0)
        )
        if closes:
            apply_changes(
                area,
                {
                    "harvest_status": "CLOSED_RAINFALL",
                    "last_closure_started_at": observed_at,
                    "closure_reopen_eligible_at": observed_at
                    + timedelta(hours=area["rainfall_closure_hours"]),
                    "consecutive_clean_samples": 0,
                },
            )
            event["voided_authorization_count"] = area_closure_cascade(area)

    return envelope_object(ser.rainfall_event(event)), 201


@bp.route("/growing-areas/<area_id>/rainfall-events", methods=["GET"])
def list_rainfall_events(area_id):
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    area = get_area(area_id)
    limit, offset = pagination()
    triggered = q_bool("triggered_closure")
    rows = []
    for event in calc.area_rainfall_events(area["id"]):
        if triggered is not None and event["triggered_closure"] != triggered:
            continue
        rows.append(event)
    rows = sort_journal(rows, "observed_at", True)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.rainfall_event(r) for r in page], limit, offset, total
    ), 200
