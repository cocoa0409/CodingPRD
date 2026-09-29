"""Clock, expiry sweep and reference data: facilities, patients, clinicians,
procedure rooms and device lots.  PRD sections 2.4, 3.1, 3.4 and 3.6.
"""
from decimal import Decimal

from flask import Blueprint, request

import calc
from core import (
    ApiError, authenticate, base_record, db, envelope_object, facility_scope,
    filter_equals, get_body, iso3, list_response, must_get, opt_bool, opt_int,
    parse_date, public, req_date, req_dt, req_enum, req_id, req_int, req_str,
    round_half_up, touch,
)

bp = Blueprint("reference", __name__)

ALL_ROLES = ("CenterAdmin", "AccessCoordinator", "FacilityCoordinator",
             "Interventionalist", "SedationRN", "Coder")

MODALITIES = ("IN_CENTER_HD", "HOME_HD", "PD")
PAYER_PROGRAMS = ("BUNDLED_ESRD", "FEE_FOR_SERVICE")
CLINICIAN_ROLES = ("INTERVENTIONALIST", "SEDATION_RN", "RECOVERY_RN", "CODER")
ROOM_TYPES = ("ANGIO_SUITE", "PROCEDURE_ROOM")
DEVICE_TYPES = ("SHEATH", "BALLOON", "STENT")
READING_KINDS = ("ROUTINE", "URGENT")


# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("CenterAdmin",))
    body = get_body()
    raw, parsed = req_dt(body, "to_iso8601")
    db.clock = parsed
    return envelope_object({"current_utc": raw}), 200


# ---------------------------------------------------------------------------
# Expiry sweep (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/_ops/expiry-sweep")
def expiry_sweep():
    authenticate(("CenterAdmin",))
    today = db.clock.date()
    candidates = [lot for lot in db.lots.values()
                  if lot["status"] in ("AVAILABLE", "QUARANTINED")
                  and parse_date(lot["expires_on"]) < today]
    candidates.sort(key=calc.lot_sort_key)

    expired_lot_ids = []
    released_usage_ids = []
    for lot in candidates:
        lot["status"] = "EXPIRED"
        touch(lot)
        expired_lot_ids.append(lot["id"])
        usages = [u for u in db.usages.values()
                  if u["device_lot_id"] == lot["id"] and u["state"] == "RESERVED"]
        for usage in calc.seq_sorted(usages):
            calc.release_usage(usage)
            released_usage_ids.append(usage["id"])

    return envelope_object({
        "expired_lot_ids": expired_lot_ids,
        "released_usage_ids": released_usage_ids,
        "expired_count": len(expired_lot_ids),
        "released_count": len(released_usage_ids),
    }), 200


# ---------------------------------------------------------------------------
# Dialysis facilities (PRD 3.1, 3.4)
# ---------------------------------------------------------------------------
@bp.post("/dialysis-facilities")
def create_facility():
    authenticate(("CenterAdmin",))
    body = get_body()
    name = req_str(body, "name")
    facility_code = req_str(body, "facility_code", min_len=1, max_len=16)
    for existing in db.facilities.values():
        if existing["facility_code"] == facility_code:
            raise ApiError("ERR_DUPLICATE_FACILITY_CODE")

    facility = base_record()
    facility.update({
        "name": name,
        "facility_code": facility_code,
        "contract_status": "ACTIVE",
        "partnership_tier": "SILVER",
        "partnership_score": 100,
        "referral_volume_window": 0,
        "raw_missed_count_window": 0,
        "grace_credit_window": 0,
        "adjusted_missed_count_window": 0,
        "same_day_honored_window": 0,
        "last_scored_at": None,
    })
    db.facilities[facility["id"]] = facility
    return envelope_object(public(facility)), 201


@bp.get("/dialysis-facilities/<facility_id>")
def get_facility(facility_id):
    user_id, role = authenticate(ALL_ROLES)
    facility = must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    facility_scope(role, user_id, facility_id)
    return envelope_object(public(facility)), 200


@bp.get("/dialysis-facilities/<facility_id>/patients")
def list_facility_patients(facility_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator"))
    must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    rows = [p for p in db.patients.values() if p["dialysis_facility_id"] == facility_id]
    rows = filter_equals(rows, "dialysis_modality", request.args.get("dialysis_modality"))
    rows = filter_equals(rows, "payer_program", request.args.get("payer_program"))
    return list_response(calc.seq_sorted(rows))


@bp.get("/dialysis-facilities/<facility_id>/surveillance-readings")
def list_facility_readings(facility_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator"))
    must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    rows = [r for r in db.readings.values() if r["reported_by_facility_id"] == facility_id]
    rows = filter_equals(rows, "kind", request.args.get("kind"))
    rows.sort(key=calc.reading_sort_key)
    return list_response(rows)


@bp.get("/dialysis-facilities/<facility_id>/partnership-metrics")
def facility_metrics(facility_id):
    user_id, role = authenticate(("CenterAdmin", "AccessCoordinator", "FacilityCoordinator"))
    facility = must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    facility_scope(role, user_id, facility_id)

    window_start, window_end = calc.partnership_window()
    volume = facility["referral_volume_window"]
    raw_missed = facility["raw_missed_count_window"]
    honored = facility["same_day_honored_window"]

    if volume == 0:
        per_referral = 0
    else:
        per_referral = round_half_up(Decimal(raw_missed) * Decimal(100) / Decimal(volume))

    same_day_referrals = 0
    for referral in calc.window_referrals(facility_id):
        if referral.get("urgency") == "SAME_DAY":
            same_day_referrals += 1
    if same_day_referrals == 0:
        honor_rate = 0
    else:
        honor_rate = round_half_up(Decimal(honored) * Decimal(100) / Decimal(same_day_referrals))

    return envelope_object({
        "facility_id": facility["id"],
        "partnership_score": facility["partnership_score"],
        "partnership_tier": facility["partnership_tier"],
        "contract_status": facility["contract_status"],
        "referral_volume_window": volume,
        "raw_missed_count_window": raw_missed,
        "grace_credit_window": facility["grace_credit_window"],
        "adjusted_missed_count_window": facility["adjusted_missed_count_window"],
        "same_day_honored_window": honored,
        "last_scored_at": facility["last_scored_at"],
        "missed_treatments_per_referral_x100": per_referral,
        "same_day_honor_rate_pct": honor_rate,
        "window_start": iso3(window_start),
        "window_end": iso3(window_end),
    }), 200


# ---------------------------------------------------------------------------
# Patients (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    authenticate(("CenterAdmin", "AccessCoordinator"))
    body = get_body()
    mrn = req_str(body, "mrn")
    full_name = req_str(body, "full_name")
    facility_id = req_id(body, "dialysis_facility_id")
    modality = req_enum(body, "dialysis_modality", MODALITIES)
    payer_program = req_enum(body, "payer_program", PAYER_PROGRAMS)

    must_get(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_MRN")

    patient = base_record()
    patient.update({
        "mrn": mrn,
        "full_name": full_name,
        "dialysis_facility_id": facility_id,
        "dialysis_modality": modality,
        "payer_program": payer_program,
        "access_count": 0,
    })
    db.patients[patient["id"]] = patient
    return envelope_object(public(patient)), 201


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    authenticate(ALL_ROLES)
    patient = must_get(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    return envelope_object(public(patient)), 200


# ---------------------------------------------------------------------------
# Clinicians (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.post("/clinicians")
def create_clinician():
    authenticate(("CenterAdmin",))
    body = get_body()
    full_name = req_str(body, "full_name")
    clinician_role = req_enum(body, "clinician_role", CLINICIAN_ROLES)
    npi = req_str(body, "npi")
    credentialed = opt_bool(body, "moderate_sedation_credentialed", False)
    expires_on = None
    if body.get("credential_expires_on") is not None:
        expires_on = req_date(body, "credential_expires_on")
    max_concurrent = opt_int(body, "max_concurrent_sedation_cases", 2, minimum=0)

    for existing in db.clinicians.values():
        if existing["npi"] == npi:
            raise ApiError("ERR_DUPLICATE_NPI")

    clinician = base_record()
    clinician.update({
        "full_name": full_name,
        "clinician_role": clinician_role,
        "npi": npi,
        "moderate_sedation_credentialed": credentialed,
        "credential_expires_on": expires_on,
        "max_concurrent_sedation_cases": max_concurrent,
    })
    db.clinicians[clinician["id"]] = clinician
    return envelope_object(public(clinician)), 201


@bp.get("/clinicians/<clinician_id>")
def get_clinician(clinician_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "SedationRN", "Coder"))
    clinician = must_get(db.clinicians, clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    return envelope_object(public(clinician)), 200


# ---------------------------------------------------------------------------
# Procedure rooms (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.post("/procedure-rooms")
def create_room():
    authenticate(("CenterAdmin",))
    body = get_body()
    room_code = req_str(body, "room_code")
    room_type = req_enum(body, "room_type", ROOM_TYPES)
    turnover = opt_int(body, "turnover_buffer_min", 30, minimum=0)
    daily_cap = opt_int(body, "daily_case_cap", 6, minimum=0)
    bays = opt_int(body, "recovery_bay_count", 3, minimum=0)

    for existing in db.rooms.values():
        if existing["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_ROOM_CODE")

    room = base_record()
    room.update({
        "room_code": room_code,
        "room_type": room_type,
        "turnover_buffer_min": turnover,
        "daily_case_cap": daily_cap,
        "recovery_bay_count": bays,
    })
    db.rooms[room["id"]] = room
    return envelope_object(public(room)), 201


@bp.get("/procedure-rooms/<room_id>")
def get_room(room_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "SedationRN"))
    room = must_get(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    return envelope_object(public(room)), 200


# ---------------------------------------------------------------------------
# Device lots (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/device-lots")
def create_lot():
    authenticate(("CenterAdmin",))
    body = get_body()
    device_type = req_enum(body, "device_type", DEVICE_TYPES)
    catalog_code = req_str(body, "catalog_code")
    lot_number = req_str(body, "lot_number")
    expires_on = req_date(body, "expires_on")
    received_quantity = req_int(body, "received_quantity", minimum=1)
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)

    for existing in db.lots.values():
        if existing["device_type"] == device_type and existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER")

    lot = base_record()
    lot.update({
        "device_type": device_type,
        "catalog_code": catalog_code,
        "lot_number": lot_number,
        "expires_on": expires_on,
        "received_quantity": received_quantity,
        "unit_cost_cents": unit_cost_cents,
        "quantity_on_hand": received_quantity,
        "quantity_reserved": 0,
        "status": "AVAILABLE",
        "quarantine_reason": None,
    })
    db.lots[lot["id"]] = lot
    return envelope_object(public(lot)), 201


@bp.post("/device-lots/<lot_id>/quarantine")
def quarantine_lot(lot_id):
    authenticate(("CenterAdmin",))
    lot = must_get(db.lots, lot_id, "ERR_DEVICE_LOT_NOT_FOUND")
    body = get_body()
    reason = req_str(body, "quarantine_reason")
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_DEVICE_LOT_STATE_INVALID")

    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = reason
    touch(lot)
    usages = [u for u in db.usages.values()
              if u["device_lot_id"] == lot_id and u["state"] == "RESERVED"]
    for usage in calc.seq_sorted(usages):
        calc.release_usage(usage)
    return envelope_object(public(lot)), 200


@bp.post("/device-lots/<lot_id>/release")
def release_lot(lot_id):
    authenticate(("CenterAdmin",))
    lot = must_get(db.lots, lot_id, "ERR_DEVICE_LOT_NOT_FOUND")
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_DEVICE_LOT_STATE_INVALID")
    if parse_date(lot["expires_on"]) < db.clock.date():
        raise ApiError("ERR_DEVICE_LOT_EXPIRED")
    lot["status"] = "AVAILABLE"
    touch(lot)
    return envelope_object(public(lot)), 200


@bp.get("/device-lots/<lot_id>")
def get_lot(lot_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    lot = must_get(db.lots, lot_id, "ERR_DEVICE_LOT_NOT_FOUND")
    return envelope_object(public(lot)), 200


@bp.get("/device-lots")
def list_lots():
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    rows = list(db.lots.values())
    rows = filter_equals(rows, "device_type", request.args.get("device_type"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows.sort(key=calc.lot_sort_key)
    return list_response(rows)
