"""Inspection records: arrival, screening, disposition and enforcement."""

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, parse_iso, serialize, touch
from validate import (arg_filter, opt_dt, opt_enum, opt_int, opt_ref,
                      opt_str, read_body, req_bool, req_dt,
                      req_enum, req_int, req_ref, require_auth)

bp = Blueprint("records", __name__)

DISPOSITIONS = ("PASS", "DECON", "REFUSE")
ENFORCEMENT_ACTIONS = ("REFER", "CITE", "DISMISS")
REFERRAL_REASONS = ("INSPECTION_REFUSAL", "QUARANTINE_RELEASE_FAILURE",
                    "SEAL_TAMPER", "DECON_EVASION")
DISPOSED = ("PASSED", "DECON_REQUIRED", "DECON_COMPLETED",
            "DECON_FAILED_ABANDONED", "REFUSED")


@bp.post("/inspection-records")
def open_record():
    user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    station_id = req_ref(body, "station_id")
    watercraft_id = req_ref(body, "watercraft_id")
    arrived_at = req_dt(body, "arrived_at")

    station = services.station_or_404(station_id)
    vessel = services.watercraft_or_404(watercraft_id)

    if station["status"] != "OPEN":
        raise ApiError("ERR_STATION_NOT_OPEN")

    services.require_active(actor)

    inside = False
    for window in db.station_hours.values():
        if window["station_id"] != station["id"]:
            continue
        opens = parse_iso(window["opens_at"])
        closes = parse_iso(window["closes_at"])
        if opens <= arrived_at < closes:
            inside = True
            break
    if not inside:
        raise ApiError("ERR_STATION_OUTSIDE_OPERATING_HOURS")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "inspector_id": user_id,
        "watercraft_id": vessel["id"],
        "prior_water_body_id": None,
        "honored_agreement_id": None,
        "arrived_at": fmt_iso(arrived_at),
        "residual_water_present": False,
        "standing_water_ml": 0,
        "presented_seal_number": None,
        "presented_seal_state_code": None,
        "presented_seal_issued_at": None,
        "screening_completed_at": None,
        "reciprocity_seal_honored": False,
        "reciprocity_credit_points": 0,
        "dry_credit_points": 0,
        "risk_score": 0,
        "advisory_risk_score": 0,
        "risk_band": "LOW",
        "decon_mandatory": False,
        "quarantine_warranted": False,
        "inspection_status": "INITIATED",
        "enforcement_status": "NONE",
        "referral_reason": None,
        "agency_code": None,
        "penalty_cents": 0,
        "inspection_fee_cents": 0,
        "decon_fee_cents": 0,
        "surcharge_cents": 0,
        "total_fee_cents": 0,
        "fee_refunded_cents": 0,
    })
    db.records[row["id"]] = row
    return created(serialize(row))


@bp.get("/inspection-records/<rid>")
def get_record(rid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.record_or_404(rid)))


@bp.get("/inspection-records")
def list_records():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "station_id": arg_filter("station_id"),
        "inspector_id": arg_filter("inspector_id"),
        "watercraft_id": arg_filter("watercraft_id"),
        "prior_water_body_id": arg_filter("prior_water_body_id"),
        "honored_agreement_id": arg_filter("honored_agreement_id"),
        "inspection_status": arg_filter("inspection_status"),
        "enforcement_status": arg_filter("enforcement_status"),
        "risk_band": arg_filter("risk_band"),
    }
    rows = [r for r in db.records.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/inspection-records/<rid>/screening")
def screen_record(rid):
    user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    expected_version = req_int(body, "expected_watercraft_version")
    residual = req_bool(body, "residual_water_present")
    standing_ml = opt_int(body, "standing_water_ml", 0, minimum=0)
    supplied_prior = opt_ref(body, "prior_water_body_id")
    seal_number = opt_str(body, "presented_seal_number", min_len=None)
    seal_state_code = opt_str(body, "presented_seal_state_code", min_len=None)
    seal_issued_at = opt_dt(body, "presented_seal_issued_at")

    record = services.record_or_404(rid)
    vessel = services.watercraft_or_404(record["watercraft_id"])

    prior_id = supplied_prior if supplied_prior is not None else vessel["last_water_body_id"]
    if prior_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "prior_water_body_id is required when the vessel has no "
                       "recorded last water body.")

    water_body = services.water_body_or_404(prior_id)

    agreement = None
    if seal_number is not None:
        for candidate in db.agreements.values():
            if candidate["partner_state_code"] == seal_state_code:
                agreement = candidate
                break
        if agreement is None:
            raise ApiError("ERR_RECIPROCITY_AGREEMENT_NOT_FOUND")

    if record["inspector_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if record["inspection_status"] not in ("INITIATED", "SCREENED"):
        raise ApiError("ERR_RECORD_ALREADY_DISPOSED")

    if expected_version != vessel["version"]:
        raise ApiError("ERR_STALE_WATERCRAFT_VERSION")

    services.require_active(actor)

    honored = False
    if seal_number is not None and agreement["status"] != "SUSPENDED":
        prefix = agreement["accepted_seal_prefix"]
        if not seal_number.startswith(prefix) or not agreement["honors_our_seals"]:
            raise ApiError("ERR_SEAL_PREFIX_MISMATCH")
        age = services.seal_age_hours(seal_issued_at, parse_iso(record["arrived_at"]))
        if age > agreement["max_seal_age_hours"]:
            raise ApiError("ERR_SEAL_RECIPROCITY_EXPIRED")
        honored = True

    if (supplied_prior is not None and vessel["last_water_body_id"] is not None
            and supplied_prior != vessel["last_water_body_id"]):
        raise ApiError("ERR_PRIOR_WATER_BODY_MISMATCH")

    record["prior_water_body_id"] = water_body["id"]
    record["presented_seal_number"] = seal_number
    record["presented_seal_state_code"] = seal_state_code
    record["presented_seal_issued_at"] = fmt_iso(seal_issued_at)
    services.apply_screening(record, water_body, vessel, residual, standing_ml,
                             agreement, honored)
    return ok(serialize(record))


@bp.post("/inspection-records/<rid>/disposition")
def dispose_record(rid):
    user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    opt_str(body, "notes", min_len=None)

    record = services.record_or_404(rid)

    if record["inspector_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if record["inspection_status"] == "INITIATED":
        raise ApiError("ERR_RECORD_NOT_SCREENED")
    if record["inspection_status"] != "SCREENED":
        raise ApiError("ERR_RECORD_ALREADY_DISPOSED")

    services.require_active(actor)

    vessel = db.watercraft.get(record["watercraft_id"])
    if disposition == "PASS":
        owed = record["decon_mandatory"] or (
            vessel is not None and vessel["mandatory_decon_flag"])
        if owed and not services.has_verified_decon(record["id"]):
            raise ApiError("ERR_DECON_REQUIRED_BEFORE_PASS")
        record["inspection_status"] = "PASSED"
    elif disposition == "DECON":
        record["inspection_status"] = "DECON_REQUIRED"
    else:
        record["inspection_status"] = "REFUSED"

    services.apply_fee(record, None)
    if disposition == "REFUSE" and record["enforcement_status"] == "NONE":
        services.apply_referral(record, "INSPECTION_REFUSAL")
    touch(record)
    return ok(serialize(record))


@bp.post("/inspection-records/<rid>/enforcement")
def enforce_record(rid):
    user_id, _role, _actor = require_auth(("EnforcementOfficer",))
    body = read_body()
    action = req_enum(body, "action", ENFORCEMENT_ACTIONS)
    referral_reason = opt_enum(body, "referral_reason", REFERRAL_REASONS)
    agency_code = opt_str(body, "agency_code", min_len=None)
    opt_str(body, "notes", min_len=None)

    record = services.record_or_404(rid)
    current = record["enforcement_status"]

    if action == "REFER":
        if current != "NONE":
            raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
        services.apply_referral(record, referral_reason, agency_code)
    elif action == "CITE":
        if current != "REFERRED":
            raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
        vessel = db.watercraft.get(record["watercraft_id"])
        strikes = vessel["compliance_strikes"] if vessel is not None else 0
        record["enforcement_status"] = "CITED"
        record["penalty_cents"] = calc.penalty_for(strikes)
        if agency_code is not None:
            record["agency_code"] = agency_code
        touch(record)
    else:
        if current != "REFERRED":
            raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
        record["enforcement_status"] = "DISMISSED"
        record["penalty_cents"] = 0
        if agency_code is not None:
            record["agency_code"] = agency_code
        vessel = db.watercraft.get(record["watercraft_id"])
        if vessel is not None:
            vessel["compliance_strikes"] = max(0, vessel["compliance_strikes"] - 1)
            services.derive_watchlist(vessel)
            touch(vessel)
        touch(record)

    return ok(serialize(record))
