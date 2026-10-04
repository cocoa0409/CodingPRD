"""FraudFlag endpoints."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success_list, success_object
from services import (
    fraud_flag_view,
    fraud_posture_recompute,
    get_driver_or_404,
    get_flag_or_404,
    get_ride_or_404,
    iso_now,
    maybe_fraud_posture_cascade,
    new_entity,
    paginate,
    require_enum,
    require_int,
    touch,
    SIGNAL_TYPES,
)

bp = Blueprint("fraud", __name__)


@bp.post("/fraud-flags")
@require_roles("FraudAnalyst")
def create_flag(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    driver = get_driver_or_404(driver_id)
    ride_id = body.get("ride_id")
    if not isinstance(ride_id, str):
        raise err_invalid_request("ride_id is required")
    get_ride_or_404(ride_id)
    signal_type = require_enum(body.get("signal_type"), "signal_type", SIGNAL_TYPES)
    severity = require_int(body.get("severity"), "severity", minimum=1, maximum=10)
    ring_id = body.get("ring_id")
    if ring_id is not None and not isinstance(ring_id, str):
        raise err_invalid_request("ring_id must be a string or null")

    f = new_entity(
        {
            "driver_id": driver["id"],
            "ride_id": ride_id,
            "ring_id": ring_id,
            "signal_type": signal_type,
            "severity": severity,
            "status": "OPEN",
            "confirmed_at": None,
        }
    )
    db.fraud_flags[f["id"]] = f
    acute, chronic = _scores(driver)
    f["acute_score"] = acute
    f["chronic_score"] = chronic
    return success_object(fraud_flag_view(f), 201)


def _scores(driver):
    confirmed = [
        fl
        for fl in db.fraud_flags.values()
        if fl["driver_id"] == driver["id"] and fl["status"] == "CONFIRMED"
    ]
    from services import parse_iso

    acute = sum(fl["severity"] for fl in confirmed)
    chronic = 0
    now = db.now()
    for fl in confirmed:
        conf_at = parse_iso(fl["confirmed_at"]) if fl.get("confirmed_at") else parse_iso(fl["updated_at"])
        age_seconds = max(0, (now - conf_at).total_seconds())
        bucket_seconds = 4 * 7 * 24 * 3600
        age_bucket = int(age_seconds // bucket_seconds)
        chronic += (fl["severity"] * 100) // (2 ** age_bucket) // 100
    return acute, chronic


@bp.get("/fraud-flags/<fid>")
@require_roles("PlatformAdmin", "FraudAnalyst")
def get_flag(fid, _user_id, _role):
    f = get_flag_or_404(fid)
    return success_object(fraud_flag_view(f))


@bp.get("/fraud-flags")
@require_roles("PlatformAdmin", "FraudAnalyst")
def list_flags(_user_id, _role):
    items = list(db.fraud_flags.values())
    driver_id = request.args.get("driver_id")
    ring_id = request.args.get("ring_id")
    ride_id = request.args.get("ride_id")
    status = request.args.get("status")
    if driver_id is not None:
        items = [f for f in items if f["driver_id"] == driver_id]
    if ring_id is not None:
        items = [f for f in items if f.get("ring_id") == ring_id]
    if ride_id is not None:
        items = [f for f in items if f["ride_id"] == ride_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([fraud_flag_view(f) for f in page], limit, offset, total)


@bp.post("/fraud-flags/<fid>/confirm")
@require_roles("FraudAnalyst")
def confirm_flag(fid, _user_id, _role):
    f = get_flag_or_404(fid)
    if f["status"] != "OPEN":
        raise err_invalid_state("FraudFlag must be OPEN to confirm")
    f["status"] = "CONFIRMED"
    f["confirmed_at"] = iso_now()
    touch(f)

    driver = get_driver_or_404(f["driver_id"])
    old, new = fraud_posture_recompute(driver)
    acute, chronic = _scores(driver)
    f["acute_score"] = acute
    f["chronic_score"] = chronic

    # anchor ride: COMPLETED -> UNDER_REVIEW
    ride = db.rides.get(f["ride_id"])
    if ride is not None and ride["status"] == "COMPLETED":
        ride["status"] = "UNDER_REVIEW"
        touch(ride)
        # reopen finalized settlements for driver+week
        from services import parse_iso, ride_week

        wk = ride_week(ride)
        if wk is not None:
            for s in db.settlements.values():
                if (
                    s["driver_id"] == driver["id"]
                    and s["status"] == "FINALIZED"
                    and parse_iso(s["week_start_utc"]) == wk
                ):
                    s["status"] = "REOPENED"
                    s["basis_variant"] = "PROVISIONAL"
                    touch(s)

    # ring members WATCH floor
    if f.get("ring_id"):
        for other_flag in db.fraud_flags.values():
            if (
                other_flag["id"] != f["id"]
                and other_flag.get("ring_id") == f["ring_id"]
                and other_flag["status"] in ("OPEN", "CONFIRMED")
                and other_flag["driver_id"] != driver["id"]
            ):
                other_driver = db.drivers.get(other_flag["driver_id"])
                if other_driver is not None:
                    o_old, o_new = fraud_posture_recompute(other_driver)
                    if other_driver["fraud_posture"] == "CLEAR":
                        other_driver["fraud_posture"] = "WATCH"
                        touch(other_driver)
                        o_new = "WATCH"
                    maybe_fraud_posture_cascade(other_driver, o_old, other_driver["fraud_posture"])

    maybe_fraud_posture_cascade(driver, old, new)
    return success_object(fraud_flag_view(f))


@bp.post("/fraud-flags/<fid>/dismiss")
@require_roles("FraudAnalyst")
def dismiss_flag(fid, _user_id, _role):
    f = get_flag_or_404(fid)
    if f["status"] != "OPEN":
        raise err_invalid_state("FraudFlag must be OPEN to dismiss")
    f["status"] = "DISMISSED"
    touch(f)
    driver = get_driver_or_404(f["driver_id"])
    fraud_posture_recompute(driver)
    acute, chronic = _scores(driver)
    f["acute_score"] = acute
    f["chronic_score"] = chronic
    return success_object(fraud_flag_view(f))
