"""Water quality readings, the closure protocol and reopening."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from db import parse_iso, service_date_of
from services import common, engine

bp = Blueprint("water_quality", __name__)

DECLARED_CREATE = (
    "attraction_id",
    "sampled_at",
    "ph_reading",
    "free_chlorine_ppm",
    "turbidity_ntu",
)
DECLARED_SUPERSEDE = ("sampled_at", "ph_reading", "free_chlorine_ppm", "turbidity_ntu")

# Plausibility window (rejection) - PRD 3.7
PH_PLAUSIBLE = (0.0, 14.0)
CHLORINE_PLAUSIBLE = (0.0, 10.0)
TURBIDITY_PLAUSIBLE = (0.0, 50.0)

# Safe window (classification) - PRD 3.7
PH_SAFE = (7.2, 7.8)
CHLORINE_SAFE = (1.0, 3.0)
TURBIDITY_SAFE_MAX = 1.0


def classify(ph, chlorine, turbidity):
    if ph < PH_SAFE[0] or ph > PH_SAFE[1]:
        return "FAIL", "pH outside the safe window [7.2, 7.8]"
    if chlorine < CHLORINE_SAFE[0] or chlorine > CHLORINE_SAFE[1]:
        return "FAIL", "Free chlorine outside the safe window [1.0, 3.0] ppm"
    if turbidity > TURBIDITY_SAFE_MAX:
        return "FAIL", "Turbidity above 1.0 NTU"
    return "PASS", None


def plausibility(payload):
    ph = v.required_number(payload, "ph_reading")
    chlorine = v.required_number(payload, "free_chlorine_ppm")
    turbidity = v.required_number(payload, "turbidity_ntu")
    if ph < PH_PLAUSIBLE[0] or ph > PH_PLAUSIBLE[1] \
            or chlorine < CHLORINE_PLAUSIBLE[0] or chlorine > CHLORINE_PLAUSIBLE[1] \
            or turbidity < TURBIDITY_PLAUSIBLE[0] or turbidity > TURBIDITY_PLAUSIBLE[1]:
        raise errors.water_quality_out_of_range()
    return ph, chlorine, turbidity


def duplicate_at_instant(resort_id, attraction_id, sampled_at):
    for log in _db.store().water_quality_logs.values():
        if log.get("resort_id") != resort_id:
            continue
        if log.get("attraction_id") != attraction_id:
            continue
        if parse_iso(log.get("sampled_at")) == parse_iso(sampled_at):
            return True
    return False


def apply_closure_cascade(resort_id, attraction_id, fail_service_date=None):
    """PRD 3.7 cascade: revoke today's bands and decline the grants they carried.

    The closure's band cascade is scoped to the service date the property is
    currently on at the moment of the closure (`fail_service_date` is that
    date, captured before the reading was recorded).  A reading logged for a
    different day, or recorded after the clock moved on, leaves bands whose
    `valid_on_service_date` is a historical date untouched.
    """
    current = fail_service_date or common.current_service_date(resort_id)
    for band in list(_db.store().wristbands.values()):
        if band.get("resort_id") != resort_id:
            continue
        if band.get("valid_on_service_date") != current:
            continue
        if band.get("wristband_status") not in ("ISSUED", "ACTIVE"):
            continue
        engine.revoke_band(band, "WATER_QUALITY_CLOSED", "WRISTBAND_REVOKED")
    common.recompute_pool_posture(resort_id)
    # PRD 3.7: every attraction associated with the failed body of water is
    # recomputed to CLOSED - coverage that cannot be delivered is not coverage.
    attraction = common.get("attraction", attraction_id)
    if attraction is not None and attraction.get("resort_id") == resort_id:
        attraction["attraction_status"] = "CLOSED"
    # PRD 3.7: every attraction holding a standing FAIL for that service date
    # is closed, whether or not it is the body of water just sampled.
    for other in list(_db.store().attractions.values()):
        if other.get("resort_id") != resort_id:
            continue
        if common.standing_fail_for_attraction_on(
                resort_id, other["id"], current):
            other["attraction_status"] = "CLOSED"


@bp.route("/resorts/<resort_id>/water-quality-logs", methods=["POST"])
def create_log(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "AquaticsManager")
    resort = common.get_resort(resort_id)

    attraction = common.fetch("attraction", v.required_str(payload, "attraction_id"), resort_id)
    sampled_at = v.required_instant(payload, "sampled_at")
    ph, chlorine, turbidity = plausibility(payload)

    if duplicate_at_instant(resort_id, attraction["id"], sampled_at):
        raise errors.duplicate_reading_at_instant()

    status, reason = classify(ph, chlorine, turbidity)

    log = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "attraction_id": attraction["id"],
        "sampled_at": sampled_at,
        "ph_reading": ph,
        "free_chlorine_ppm": chlorine,
        "turbidity_ntu": turbidity,
        "log_status": status,
        "closure_reason": reason if status == "FAIL" else None,
        "superseded_at": None,
    }
    _db.store().water_quality_logs[log["id"]] = log

    if status == "FAIL":
        apply_closure_cascade(
            resort_id, attraction["id"], service_date_of(parse_iso(sampled_at))
        )
    else:
        common.recompute_pool_posture(resort_id)

    common.touch(resort)
    return jsonify(response.success(common.serialise("water_quality_log", log))), 201


@bp.route("/resorts/<resort_id>/water-quality-logs", methods=["GET"])
def list_logs(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        log for log in _db.store().water_quality_logs.values()
        if log.get("resort_id") == resort_id
    ]
    attraction_id = v.query_str("attraction_id")
    if attraction_id:
        rows = [log for log in rows if log.get("attraction_id") == attraction_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("water_quality_log", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/water-quality-logs/<log_id>", methods=["GET"])
def get_log(resort_id, log_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)
    log = common.fetch("water_quality_log", log_id, resort_id)
    return jsonify(response.success(common.serialise("water_quality_log", log))), 200


@bp.route("/resorts/<resort_id>/water-quality-logs/<log_id>/supersede", methods=["POST"])
def supersede_log(resort_id, log_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_SUPERSEDE)
    middleware.require(caller, "AquaticsManager")
    resort = common.get_resort(resort_id)
    standing = common.fetch("water_quality_log", log_id, resort_id)

    if standing.get("log_status") != "FAIL" or standing.get("superseded_at") is not None:
        raise errors.invalid_state("Only a standing FAIL reading can be superseded.")

    sampled_at = v.required_instant(payload, "sampled_at")
    ph, chlorine, turbidity = plausibility(payload)

    if duplicate_at_instant(resort_id, standing["attraction_id"], sampled_at):
        raise errors.duplicate_reading_at_instant()

    status, reason = classify(ph, chlorine, turbidity)
    now = _db.now_iso()
    log = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "resort_id": resort_id,
        "attraction_id": standing["attraction_id"],
        "sampled_at": sampled_at,
        "ph_reading": ph,
        "free_chlorine_ppm": chlorine,
        "turbidity_ntu": turbidity,
        "log_status": status,
        "closure_reason": reason if status == "FAIL" else None,
        "superseded_at": None,
    }
    _db.store().water_quality_logs[log["id"]] = log

    standing["superseded_at"] = now
    common.touch(standing)

    if status == "FAIL":
        apply_closure_cascade(
            resort_id, standing["attraction_id"], service_date_of(parse_iso(sampled_at))
        )
    else:
        common.recompute_pool_posture(resort_id)

    common.touch(resort)
    return jsonify(response.success(common.serialise("water_quality_log", log))), 200