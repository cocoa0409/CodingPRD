"""Retail Pharmacy Immunization API — Flask application.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request

from db import DB
from errors import ApiError, err
from middleware import require_roles
from response import success, error, paginate
import services as S

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = ["StoreManager", "Pharmacist", "PharmacyTechnician", "Immunizer",
             "ObservationMonitor", "ComplianceOfficer", "Patient"]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def get_or_404(table, rid):
    entity = table.get(rid)
    if entity is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return entity


def bad(message):
    raise err("ERR_INVALID_REQUEST", message)


def check_enum(value, allowed, field):
    if value not in allowed:
        bad(f"Invalid value for {field}")


def check_int(value, field, minimum=None):
    if not isinstance(value, int) or isinstance(value, bool):
        bad(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        bad(f"{field} out of range")


def check_number(value, field):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        bad(f"{field} must be a number")


def list_response(items, args):
    items.sort(key=lambda e: (S.parse_dt(e["created_at"]), e["id"]))
    page, meta = paginate(items, args)
    return success(page, is_array=True, pagination=meta)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error("ERR_INVALID_REQUEST", str(e), 400)


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------

@app.post("/immunization/_clock/set_current_utc")
def set_clock():
    require_roles(["StoreManager", "ComplianceOfficer"])
    data = body()
    target = S.parse_dt(data.get("to_iso8601"))
    DB.clock = target
    S.run_sweeps()
    return success({"current_utc": S.clock_ts()}, status=200)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

@app.post("/immunization/stores")
def create_store():
    require_roles(["StoreManager"])
    data = body()
    for f in ("store_number", "state_code", "address_line"):
        if not isinstance(data.get(f), str) or not data[f]:
            bad(f"Missing required field: {f}")
    now = S.iso_now()
    store = {
        "id": S.new_id(),
        "store_number": data["store_number"],
        "state_code": data["state_code"],
        "address_line": data["address_line"],
        "status": "ACTIVE",
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.stores[store["id"]] = store
    return success(store, status=201)


@app.get("/immunization/stores")
def list_stores():
    require_roles(ALL_ROLES)
    items = list(DB.stores.values())
    if request.args.get("state_code") is not None:
        items = [s for s in items if s["state_code"] == request.args["state_code"]]
    if request.args.get("status") is not None:
        items = [s for s in items if s["status"] == request.args["status"]]
    return list_response(items, request.args)


@app.get("/immunization/stores/<store_id>")
def get_store(store_id):
    require_roles(ALL_ROLES)
    return success(get_or_404(DB.stores, store_id))


@app.put("/immunization/stores/<store_id>")
def update_store(store_id):
    require_roles(["StoreManager"])
    store = get_or_404(DB.stores, store_id)
    data = body()
    if "address_line" in data:
        if not isinstance(data["address_line"], str):
            bad("address_line must be a string")
        store["address_line"] = data["address_line"]
    if "status" in data:
        check_enum(data["status"], ("ACTIVE", "SUSPENDED"), "status")
        if store["status"] == "ACTIVE" and data["status"] == "SUSPENDED":
            # Cascade: cancel all SCHEDULED appointments at this store.
            for appt in DB.appointments.values():
                if appt["store_id"] == store["id"] and appt["status"] == "SCHEDULED":
                    appt["status"] = "CANCELLED"
                    appt["cancellation_reason"] = "STORE_SUSPENDED"
                    S.touch(appt)
        store["status"] = data["status"]
    S.touch(store)
    return success(store)


# ---------------------------------------------------------------------------
# State Protocols
# ---------------------------------------------------------------------------

@app.post("/immunization/state-protocols")
def create_protocol():
    require_roles(["ComplianceOfficer"])
    data = body()
    for f in ("state_code", "vaccine_product_id", "authority_type",
              "min_patient_age_years", "registry_format", "registry_deadline_hours"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    check_enum(data["authority_type"],
               ("STANDING_ORDER", "PROTOCOL", "PRESCRIPTION_REQUIRED"), "authority_type")
    check_enum(data["registry_format"],
               ("HL7_VXU", "FLAT_FILE_CSV", "STATE_API_JSON"), "registry_format")
    check_int(data["min_patient_age_years"], "min_patient_age_years", 0)
    check_int(data["registry_deadline_hours"], "registry_deadline_hours", 0)
    max_doses = data.get("max_doses_per_patient_per_day", 2)
    check_int(max_doses, "max_doses_per_patient_per_day", 1)
    # Unique per (state_code, vaccine_product_id)
    for p in DB.state_protocols.values():
        if (p["state_code"] == data["state_code"]
                and p["vaccine_product_id"] == data["vaccine_product_id"]):
            raise err("ERR_INVALID_STATE",
                      "Protocol already exists for this (state_code, vaccine_product_id)")
    now = S.iso_now()
    proto = {
        "id": S.new_id(),
        "state_code": data["state_code"],
        "vaccine_product_id": data["vaccine_product_id"],
        "authority_type": data["authority_type"],
        "min_patient_age_years": data["min_patient_age_years"],
        "max_doses_per_patient_per_day": max_doses,
        "registry_format": data["registry_format"],
        "registry_deadline_hours": data["registry_deadline_hours"],
        "status": "ACTIVE",
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.state_protocols[proto["id"]] = proto
    return success(proto, status=201)


@app.get("/immunization/state-protocols")
def list_protocols():
    require_roles(["StoreManager", "Pharmacist", "ComplianceOfficer"])
    items = list(DB.state_protocols.values())
    if request.args.get("state_code") is not None:
        items = [p for p in items if p["state_code"] == request.args["state_code"]]
    if request.args.get("vaccine_product_id") is not None:
        items = [p for p in items if p["vaccine_product_id"] == request.args["vaccine_product_id"]]
    if request.args.get("status") is not None:
        items = [p for p in items if p["status"] == request.args["status"]]
    return list_response(items, request.args)


@app.get("/immunization/state-protocols/<protocol_id>")
def get_protocol(protocol_id):
    require_roles(["StoreManager", "Pharmacist", "ComplianceOfficer"])
    return success(get_or_404(DB.state_protocols, protocol_id))


@app.put("/immunization/state-protocols/<protocol_id>")
def update_protocol(protocol_id):
    require_roles(["ComplianceOfficer"])
    proto = get_or_404(DB.state_protocols, protocol_id)
    data = body()
    if "min_patient_age_years" in data:
        check_int(data["min_patient_age_years"], "min_patient_age_years", 0)
        proto["min_patient_age_years"] = data["min_patient_age_years"]
    if "registry_deadline_hours" in data:
        check_int(data["registry_deadline_hours"], "registry_deadline_hours", 0)
        proto["registry_deadline_hours"] = data["registry_deadline_hours"]
    if "status" in data:
        check_enum(data["status"], ("ACTIVE", "RETIRED"), "status")
        proto["status"] = data["status"]
    S.touch(proto)
    return success(proto)


# ---------------------------------------------------------------------------
# Vaccine Products
# ---------------------------------------------------------------------------

@app.post("/immunization/vaccine-products")
def create_product():
    require_roles(["ComplianceOfficer"])
    data = body()
    for f in ("cvx_code", "name", "min_patient_age_years", "doses_per_series",
              "cash_price_cents", "fridge_temp_min_c", "fridge_temp_max_c"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    check_int(data["min_patient_age_years"], "min_patient_age_years", 0)
    check_int(data["doses_per_series"], "doses_per_series", 1)
    check_int(data["cash_price_cents"], "cash_price_cents", 0)
    check_number(data["fridge_temp_min_c"], "fridge_temp_min_c")
    check_number(data["fridge_temp_max_c"], "fridge_temp_max_c")
    min_interval = data.get("min_interval_days", 0)
    obs_minutes = data.get("observation_minutes", 15)
    check_int(min_interval, "min_interval_days", 0)
    check_int(obs_minutes, "observation_minutes", 0)
    now = S.iso_now()
    product = {
        "id": S.new_id(),
        "cvx_code": data["cvx_code"],
        "name": data["name"],
        "min_patient_age_years": data["min_patient_age_years"],
        "doses_per_series": data["doses_per_series"],
        "min_interval_days": min_interval,
        "cash_price_cents": data["cash_price_cents"],
        "fridge_temp_min_c": data["fridge_temp_min_c"],
        "fridge_temp_max_c": data["fridge_temp_max_c"],
        "observation_minutes": obs_minutes,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.vaccine_products[product["id"]] = product
    return success(product, status=201)


@app.get("/immunization/vaccine-products")
def list_products():
    require_roles(ALL_ROLES)
    items = list(DB.vaccine_products.values())
    if request.args.get("cvx_code") is not None:
        items = [p for p in items if p["cvx_code"] == request.args["cvx_code"]]
    return list_response(items, request.args)


@app.get("/immunization/vaccine-products/<product_id>")
def get_product(product_id):
    require_roles(ALL_ROLES)
    return success(get_or_404(DB.vaccine_products, product_id))


# ---------------------------------------------------------------------------
# Insurance Plans
# ---------------------------------------------------------------------------

@app.post("/immunization/insurance-plans")
def create_plan():
    require_roles(["ComplianceOfficer"])
    data = body()
    for f in ("plan_name", "benefit_type", "copay_cents", "covered_cvx_codes"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    check_enum(data["benefit_type"], ("PHARMACY", "MEDICAL", "BOTH"), "benefit_type")
    check_int(data["copay_cents"], "copay_cents", 0)
    if not isinstance(data["covered_cvx_codes"], list):
        bad("covered_cvx_codes must be an array")
    coinsurance = data.get("coinsurance_pct", 0)
    check_number(coinsurance, "coinsurance_pct")
    deductible = data.get("deductible_remaining_cents", 0)
    check_int(deductible, "deductible_remaining_cents", 0)
    now = S.iso_now()
    plan = {
        "id": S.new_id(),
        "plan_name": data["plan_name"],
        "benefit_type": data["benefit_type"],
        "copay_cents": data["copay_cents"],
        "coinsurance_pct": coinsurance,
        "deductible_remaining_cents": deductible,
        "covered_cvx_codes": list(data["covered_cvx_codes"]),
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.insurance_plans[plan["id"]] = plan
    return success(plan, status=201)


@app.get("/immunization/insurance-plans/<plan_id>")
def get_plan(plan_id):
    require_roles(["StoreManager", "Pharmacist", "PharmacyTechnician", "ComplianceOfficer"])
    return success(get_or_404(DB.insurance_plans, plan_id))


@app.put("/immunization/insurance-plans/<plan_id>")
def update_plan(plan_id):
    require_roles(["ComplianceOfficer"])
    plan = get_or_404(DB.insurance_plans, plan_id)
    data = body()
    if "copay_cents" in data:
        check_int(data["copay_cents"], "copay_cents", 0)
        plan["copay_cents"] = data["copay_cents"]
    if "coinsurance_pct" in data:
        check_number(data["coinsurance_pct"], "coinsurance_pct")
        plan["coinsurance_pct"] = data["coinsurance_pct"]
    if "deductible_remaining_cents" in data:
        check_int(data["deductible_remaining_cents"], "deductible_remaining_cents", 0)
        plan["deductible_remaining_cents"] = data["deductible_remaining_cents"]
    if "covered_cvx_codes" in data:
        if not isinstance(data["covered_cvx_codes"], list):
            bad("covered_cvx_codes must be an array")
        plan["covered_cvx_codes"] = list(data["covered_cvx_codes"])
    if "benefit_type" in data:
        check_enum(data["benefit_type"], ("PHARMACY", "MEDICAL", "BOTH"), "benefit_type")
        plan["benefit_type"] = data["benefit_type"]
    S.touch(plan)
    return success(plan)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.post("/immunization/patients")
def create_patient():
    require_roles(["PharmacyTechnician", "Pharmacist"])
    data = body()
    for f in ("full_name", "date_of_birth", "state_code"):
        if not isinstance(data.get(f), str) or not data[f]:
            bad(f"Missing required field: {f}")
    S.parse_date(data["date_of_birth"])  # validates format
    allergy_flags = data.get("allergy_flags", [])
    if not isinstance(allergy_flags, list):
        bad("allergy_flags must be an array")
    high_risk = data.get("high_risk_flag", False)
    if not isinstance(high_risk, bool):
        bad("high_risk_flag must be a boolean")
    insurance_plan_id = data.get("insurance_plan_id")
    if insurance_plan_id is not None and insurance_plan_id not in DB.insurance_plans:
        bad("insurance_plan_id does not reference an existing plan")
    now = S.iso_now()
    patient = {
        "id": S.new_id(),
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "state_code": data["state_code"],
        "allergy_flags": list(allergy_flags),
        "high_risk_flag": high_risk,
        "insurance_plan_id": insurance_plan_id,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.patients[patient["id"]] = patient
    return success(patient, status=201)


@app.get("/immunization/patients/<patient_id>")
def get_patient(patient_id):
    require_roles(["PharmacyTechnician", "Pharmacist", "Immunizer", "ComplianceOfficer"])
    return success(get_or_404(DB.patients, patient_id))


@app.get("/immunization/patients")
def list_patients():
    require_roles(["PharmacyTechnician", "Pharmacist", "ComplianceOfficer"])
    items = list(DB.patients.values())
    if request.args.get("state_code") is not None:
        items = [p for p in items if p["state_code"] == request.args["state_code"]]
    if request.args.get("insurance_plan_id") is not None:
        items = [p for p in items if p["insurance_plan_id"] == request.args["insurance_plan_id"]]
    return list_response(items, request.args)


# ---------------------------------------------------------------------------
# Vaccine Lots
# ---------------------------------------------------------------------------

LOT_READERS = ["StoreManager", "Pharmacist", "PharmacyTechnician", "Immunizer", "ComplianceOfficer"]


def lot_expired(lot, ref=None):
    ref = ref or DB.clock.date()
    return S.parse_date(lot["expiration_date"]) <= ref


@app.post("/immunization/stores/<store_id>/lots")
def create_lot(store_id):
    require_roles(["StoreManager"])
    store = get_or_404(DB.stores, store_id)
    data = body()
    for f in ("vaccine_product_id", "lot_number", "expiration_date", "doses_received"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    if data["vaccine_product_id"] not in DB.vaccine_products:
        bad("vaccine_product_id does not reference an existing product")
    S.parse_date(data["expiration_date"])
    check_int(data["doses_received"], "doses_received", 0)
    # Unique lot_number per store
    for lot in DB.lots.values():
        if lot["store_id"] == store["id"] and lot["lot_number"] == data["lot_number"]:
            raise err("ERR_INVALID_STATE", "lot_number already exists at this store")
    now = S.iso_now()
    lot = {
        "id": S.new_id(),
        "store_id": store["id"],
        "vaccine_product_id": data["vaccine_product_id"],
        "lot_number": data["lot_number"],
        "expiration_date": data["expiration_date"],
        "doses_received": data["doses_received"],
        "doses_available": data["doses_received"],
        "status": "RELEASED",
        "quarantine_reason": None,
        "last_excursion_severity_tier": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.lots[lot["id"]] = lot
    return success(lot, status=201)


@app.get("/immunization/stores/<store_id>/lots")
def list_store_lots(store_id):
    require_roles(LOT_READERS)
    store = get_or_404(DB.stores, store_id)
    items = [l for l in DB.lots.values() if l["store_id"] == store["id"]]
    if request.args.get("vaccine_product_id") is not None:
        items = [l for l in items if l["vaccine_product_id"] == request.args["vaccine_product_id"]]
    if request.args.get("status") is not None:
        items = [l for l in items if l["status"] == request.args["status"]]
    return list_response(items, request.args)


@app.get("/immunization/lots/<lot_id>")
def get_lot(lot_id):
    require_roles(LOT_READERS)
    return success(get_or_404(DB.lots, lot_id))


@app.get("/immunization/lots")
def list_lots():
    require_roles(LOT_READERS)
    items = list(DB.lots.values())
    if request.args.get("vaccine_product_id") is not None:
        items = [l for l in items if l["vaccine_product_id"] == request.args["vaccine_product_id"]]
    if request.args.get("store_id") is not None:
        items = [l for l in items if l["store_id"] == request.args["store_id"]]
    if request.args.get("status") is not None:
        items = [l for l in items if l["status"] == request.args["status"]]
    return list_response(items, request.args)


@app.post("/immunization/lots/<lot_id>/temperature-readings")
def create_temperature_reading(lot_id):
    require_roles(["StoreManager", "PharmacyTechnician"])
    lot = get_or_404(DB.lots, lot_id)
    data = body()
    if data.get("recorded_at") is None or data.get("temperature_c") is None:
        bad("Missing required field: recorded_at, temperature_c")
    S.parse_dt(data["recorded_at"])
    check_number(data["temperature_c"], "temperature_c")
    product = DB.vaccine_products.get(lot["vaccine_product_id"])
    is_excursion, tier = S.peak_delta_tier(product, data["temperature_c"])
    reading = {
        "id": S.new_id(),
        "lot_id": lot["id"],
        "recorded_at": data["recorded_at"],
        "temperature_c": data["temperature_c"],
        "is_excursion": is_excursion,
        "excursion_severity_tier": tier,
        "created_at": S.iso_now(),
    }
    DB.temperature_readings[reading["id"]] = reading
    if is_excursion and lot["status"] == "RELEASED":
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = "EXCURSION"
        lot["last_excursion_severity_tier"] = tier
        S.touch(lot)
    elif is_excursion:
        lot["last_excursion_severity_tier"] = tier
        S.touch(lot)
    return success(reading, status=201)


@app.get("/immunization/lots/<lot_id>/temperature-readings")
def list_temperature_readings(lot_id):
    require_roles(["StoreManager", "Pharmacist", "ComplianceOfficer"])
    lot = get_or_404(DB.lots, lot_id)
    items = [r for r in DB.temperature_readings.values() if r["lot_id"] == lot["id"]]
    return list_response(items, request.args)


@app.post("/immunization/lots/<lot_id>/quarantine")
def quarantine_lot(lot_id):
    require_roles(["StoreManager"])
    lot = get_or_404(DB.lots, lot_id)
    if lot["status"] != "RELEASED":
        raise err("ERR_LOT_NOT_RELEASED", "Lot is not RELEASED")
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = "MANUAL"
    S.touch(lot)
    return success(lot)


@app.post("/immunization/lots/<lot_id>/release")
def release_lot(lot_id):
    require_roles(["StoreManager"])
    lot = get_or_404(DB.lots, lot_id)
    data = body()
    if lot["status"] != "QUARANTINED":
        raise err("ERR_LOT_NOT_QUARANTINED", "Lot is not QUARANTINED")
    disposition = data.get("excursion_disposition")
    if disposition not in ("RELEASE_OK", "RELEASE_OK_CUMULATIVE"):
        raise err("ERR_EXCURSION_DISPOSITION_REQUIRED",
                  "excursion_disposition must be RELEASE_OK or RELEASE_OK_CUMULATIVE")
    if disposition == "RELEASE_OK_CUMULATIVE":
        lot["last_excursion_severity_tier"] = S.cumulative_minutes_tier(lot["id"])
    lot["status"] = "RELEASED"
    lot["quarantine_reason"] = None
    S.touch(lot)
    return success(lot)


@app.post("/immunization/lots/<lot_id>/retire")
def retire_lot(lot_id):
    require_roles(["StoreManager"])
    lot = get_or_404(DB.lots, lot_id)
    if lot["status"] not in ("RELEASED", "QUARANTINED"):
        raise err("ERR_LOT_NOT_RETIRABLE", "Lot is not retirable")
    lot["status"] = "RETIRED"
    lot["doses_available"] = 0
    S.touch(lot)
    # Auto-cancel PLANNED clinic events using this lot as mobile inventory
    for ev in DB.clinic_events.values():
        if ev["mobile_lot_id"] == lot["id"] and ev["status"] == "PLANNED":
            ev["status"] = "CANCELLED"
            S.touch(ev)
    return success(lot)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

APPT_READERS = ["StoreManager", "Pharmacist", "PharmacyTechnician", "Immunizer", "ComplianceOfficer"]


@app.post("/immunization/appointments")
def create_appointment():
    user_id, role = require_roles(["PharmacyTechnician", "Pharmacist", "Patient"])
    data = body()
    for f in ("store_id", "patient_id", "vaccine_product_id"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    is_walk_in = bool(data.get("is_walk_in", False))
    # Self-booking ownership (RBAC layer)
    if role == "Patient" and data["patient_id"] != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Patients may only book for themselves")
    store = DB.stores.get(data["store_id"])
    patient = DB.patients.get(data["patient_id"])
    product = DB.vaccine_products.get(data["vaccine_product_id"])
    if store is None or patient is None or product is None:
        raise err("ERR_NOT_FOUND", "Referenced resource not found")
    if is_walk_in:
        slot_start = DB.clock
        slot_start_str = S.clock_ts()
    else:
        if data.get("slot_start") is None:
            bad("Missing required field: slot_start")
        slot_start = S.parse_dt(data["slot_start"])
        slot_start_str = data["slot_start"]
    # Resolve governing protocol from (store.state_code, product)
    protocol = None
    for p in DB.state_protocols.values():
        if p["state_code"] == store["state_code"] and p["vaccine_product_id"] == product["id"]:
            protocol = p
            break
    if protocol is None:
        raise err("ERR_NOT_FOUND", "No state protocol governs this product at this store")
    # Store must be ACTIVE
    if store["status"] != "ACTIVE":
        raise err("ERR_STORE_SUSPENDED", "Store is SUSPENDED")
    # Age eligibility at the slot date (safety layer)
    dob = S.parse_date(patient["date_of_birth"])
    age = S.age_on(dob, slot_start.date())
    required_age = max(protocol["min_patient_age_years"], product["min_patient_age_years"])
    if age < required_age:
        raise err("ERR_PATIENT_UNDER_MIN_AGE",
                  "Patient under minimum age at administration date")
    # Series rules (constraint layer)
    dose_number = S.compute_dose_number(patient["id"], product["id"], product, slot_start)
    # Slot overlap (constraint layer, non-walk-in only)
    if not is_walk_in:
        new_start = slot_start
        new_end = slot_start + timedelta(minutes=15)
        for other in DB.appointments.values():
            if other["store_id"] != store["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "CHECKED_IN"):
                continue
            o_start = S.parse_dt(other["slot_start"])
            o_end = o_start + timedelta(minutes=15)
            if new_start < o_end and o_start < new_end:
                raise err("ERR_SLOT_CONFLICT", "Slot overlaps an existing appointment")
    now = S.iso_now()
    appt = {
        "id": S.new_id(),
        "store_id": store["id"],
        "patient_id": patient["id"],
        "vaccine_product_id": product["id"],
        "state_protocol_id": protocol["id"],
        "slot_start": slot_start_str,
        "is_walk_in": is_walk_in,
        "dose_number": dose_number,
        "status": "SCHEDULED",
        "scheduled_dose_count_today": 0,
        "checked_in_by": None,
        "clinic_event_id": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.appointments[appt["id"]] = appt
    return success(appt, status=201)


@app.get("/immunization/appointments")
def list_appointments():
    require_roles(APPT_READERS)
    items = list(DB.appointments.values())
    for param, field in (("store_id", "store_id"), ("patient_id", "patient_id"),
                         ("vaccine_product_id", "vaccine_product_id"),
                         ("state_protocol_id", "state_protocol_id"), ("status", "status")):
        if request.args.get(param) is not None:
            items = [a for a in items if a[field] == request.args[param]]
    return list_response(items, request.args)


@app.get("/immunization/appointments/<appt_id>")
def get_appointment(appt_id):
    user_id, role = require_roles(APPT_READERS + ["Patient"])
    appt = get_or_404(DB.appointments, appt_id)
    if role == "Patient" and appt["patient_id"] != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Patients may only view their own appointments")
    return success(appt)


@app.get("/immunization/appointments/<appt_id>/price-quote")
def price_quote(appt_id):
    user_id, role = require_roles(["PharmacyTechnician", "Pharmacist", "Patient"])
    appt = get_or_404(DB.appointments, appt_id)
    if role == "Patient" and appt["patient_id"] != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Patients may only view their own price quote")
    product = DB.vaccine_products[appt["vaccine_product_id"]]
    patient = DB.patients[appt["patient_id"]]
    plan = DB.insurance_plans.get(patient["insurance_plan_id"]) if patient.get("insurance_plan_id") else None
    charge, channel = S.adjudicate(product, plan)
    return success({"quoted_charge_cents": charge, "billing_channel": channel})


@app.post("/immunization/appointments/<appt_id>/check-in")
def check_in(appt_id):
    user_id, role = require_roles(["PharmacyTechnician", "Pharmacist"])
    appt = get_or_404(DB.appointments, appt_id)
    if appt["status"] != "SCHEDULED":
        raise err("ERR_APPOINTMENT_NOT_SCHEDULED", "Appointment is not SCHEDULED")
    if not appt["is_walk_in"]:
        slot = S.parse_dt(appt["slot_start"])
        now = DB.clock
        if not (slot - timedelta(minutes=30) <= now <= slot + timedelta(minutes=60)):
            raise err("ERR_CHECKIN_WINDOW_MISSED", "Check-in window missed")
    store = DB.stores[appt["store_id"]]
    if store["status"] != "ACTIVE":
        raise err("ERR_STORE_SUSPENDED", "Store is SUSPENDED")
    appt["status"] = "CHECKED_IN"
    appt["checked_in_by"] = user_id
    S.touch(appt)
    return success(appt)


@app.post("/immunization/appointments/<appt_id>/questionnaire")
def submit_questionnaire(appt_id):
    user_id, role = require_roles(["PharmacyTechnician"])
    appt = get_or_404(DB.appointments, appt_id)
    data = body()
    # A second questionnaire for this appointment is rejected with
    # ERR_QUESTIONNAIRE_ALREADY_EXISTS even though the appointment has already
    # advanced past CHECKED_IN (scaffold transition preconditions).
    for q in DB.questionnaires.values():
        if q["appointment_id"] == appt["id"]:
            raise err("ERR_QUESTIONNAIRE_ALREADY_EXISTS",
                      "Questionnaire already exists for this appointment")
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_APPOINTMENT_NOT_CHECKED_IN", "Appointment is not CHECKED_IN")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        bad("answers must be an object")
    patient = DB.patients[appt["patient_id"]]
    contra = S.compute_contraindication(answers, patient.get("allergy_flags"))
    now = S.iso_now()
    questionnaire = {
        "id": S.new_id(),
        "appointment_id": appt["id"],
        "answers": answers,
        "contraindication_detected": contra,
        "reviewed_by_pharmacist_id": None,
        "review_outcome": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.questionnaires[questionnaire["id"]] = questionnaire
    appt["status"] = "SCREENED"
    S.touch(appt)
    return success(questionnaire, status=201)


@app.get("/immunization/appointments/<appt_id>/questionnaire")
def get_questionnaire(appt_id):
    require_roles(["Pharmacist", "PharmacyTechnician", "ComplianceOfficer"])
    appt = get_or_404(DB.appointments, appt_id)
    items = [q for q in DB.questionnaires.values() if q["appointment_id"] == appt["id"]]
    items.sort(key=lambda e: (S.parse_dt(e["created_at"]), e["id"]))
    return success(items, is_array=True)


@app.post("/immunization/appointments/<appt_id>/review-consent")
def review_consent(appt_id):
    user_id, role = require_roles(["Pharmacist"])
    appt = get_or_404(DB.appointments, appt_id)
    data = body()
    # OCC check (priority 4) runs before any business-rule validation
    expected = data.get("expected_appointment_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        bad("expected_appointment_version is required")
    if expected != appt["version"]:
        raise err("ERR_STALE_APPOINTMENT_VERSION",
                  "expected_appointment_version does not match current version")
    outcome = data.get("outcome")
    if outcome not in ("CLEAR", "REFER_OUT"):
        bad("outcome must be CLEAR or REFER_OUT")
    # State check
    if appt["status"] != "SCREENED":
        raise err("ERR_APPOINTMENT_NOT_SCREENED", "Appointment is not SCREENED")
    questionnaire = None
    for q in DB.questionnaires.values():
        if q["appointment_id"] == appt["id"]:
            questionnaire = q
            break
    if outcome == "REFER_OUT":
        questionnaire["review_outcome"] = "REFERRED_OUT"
        questionnaire["reviewed_by_pharmacist_id"] = user_id
        S.touch(questionnaire)
        appt["status"] = "CANCELLED"
        S.touch(appt)
        return success(appt)
    # outcome == CLEAR — evaluate business rules in scaffold order
    if questionnaire["contraindication_detected"]:
        raise err("ERR_CONTRAINDICATION_DETECTED", "Contraindication detected")
    protocol = DB.state_protocols[appt["state_protocol_id"]]
    if protocol["status"] != "ACTIVE":
        raise err("ERR_PROTOCOL_NOT_ACTIVE", "Governing protocol is not ACTIVE")
    if appt["is_walk_in"] and protocol["authority_type"] == "PRESCRIPTION_REQUIRED":
        raise err("ERR_PROTOCOL_NOT_ACTIVE",
                  "PRESCRIPTION_REQUIRED authority forbids walk-in administration")
    product = DB.vaccine_products[appt["vaccine_product_id"]]
    patient = DB.patients[appt["patient_id"]]
    slot = S.parse_dt(appt["slot_start"])
    dob = S.parse_date(patient["date_of_birth"])
    required_age = max(protocol["min_patient_age_years"], product["min_patient_age_years"])
    if S.age_on(dob, slot.date()) < required_age:
        raise err("ERR_PATIENT_UNDER_MIN_AGE", "Patient under minimum age")
    if S.scheduled_dose_count_today(patient["id"], appt["store_id"], slot) >= protocol["max_doses_per_patient_per_day"]:
        raise err("ERR_DAILY_DOSE_LIMIT_REACHED", "Daily dose limit reached")
    has_lot = S.eligible_lot_exists(appt["store_id"], product["id"], slot.date())
    if not has_lot:
        event_id = appt.get("clinic_event_id")
        ev = DB.clinic_events.get(event_id) if event_id else None
        if ev is None or ev["status"] != "ACTIVE" or (ev["doses_reserved"] - ev["doses_administered"]) <= 0:
            raise err("ERR_NO_ELIGIBLE_LOT", "No eligible lot at this store")
    if appt.get("checked_in_by") is not None and appt["checked_in_by"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                  "Reviewer must differ from check-in operator")
    questionnaire["review_outcome"] = "CLEARED"
    questionnaire["reviewed_by_pharmacist_id"] = user_id
    S.touch(questionnaire)
    appt["status"] = "CONSENTED"
    S.touch(appt)
    return success(appt)


@app.post("/immunization/appointments/<appt_id>/administer")
def administer(appt_id):
    user_id, role = require_roles(["Immunizer"])
    appt = get_or_404(DB.appointments, appt_id)
    data = body()
    # OCC check (priority 4) — before state and business rules
    expected_lot_version = data.get("expected_lot_version")
    if expected_lot_version is None or not isinstance(expected_lot_version, int) or isinstance(expected_lot_version, bool):
        bad("expected_lot_version is required")
    lot_id = data.get("lot_id")
    if lot_id is None:
        bad("Missing required field: lot_id")
    lot = DB.lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    if expected_lot_version != lot["version"]:
        raise err("ERR_STALE_LOT_VERSION", "expected_lot_version does not match current lot version")
    # State check
    if appt["status"] != "CONSENTED":
        raise err("ERR_APPOINTMENT_NOT_CONSENTED", "Appointment is not CONSENTED")
    product = DB.vaccine_products[appt["vaccine_product_id"]]
    patient = DB.patients[appt["patient_id"]]
    # A SUSPENDED store cannot accept administrations (PRD §3.1)
    store = DB.stores[appt["store_id"]]
    if store["status"] != "ACTIVE":
        raise err("ERR_STORE_SUSPENDED", "Store is SUSPENDED")
    # Lot administerability
    if lot["status"] != "RELEASED" or lot_expired(lot):
        raise err("ERR_LOT_NOT_ADMINISTERABLE", "Lot is not administerable")
    if lot["doses_available"] <= 0:
        raise err("ERR_LOT_DEPLETED", "Lot has no doses available")
    if lot["vaccine_product_id"] != appt["vaccine_product_id"]:
        raise err("ERR_LOT_PRODUCT_MISMATCH", "Lot product does not match appointment product")
    # Segregation of duties: immunizer differs from reviewing pharmacist
    questionnaire = None
    for q in DB.questionnaires.values():
        if q["appointment_id"] == appt["id"]:
            questionnaire = q
            break
    reviewer = questionnaire.get("reviewed_by_pharmacist_id") if questionnaire else None
    if reviewer is not None and reviewer == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                  "Immunizer must differ from reviewing pharmacist")
    # Clinic event attachment
    clinic_event_id = data.get("clinic_event_id")
    event = None
    if clinic_event_id is not None:
        event = DB.clinic_events.get(clinic_event_id)
        if event is None:
            raise err("ERR_NOT_FOUND", "Clinic event not found")
    # --- Atomic fan-out ---
    protocol = DB.state_protocols[appt["state_protocol_id"]]
    administered_at = S.clock_ts()
    plan = DB.insurance_plans.get(patient["insurance_plan_id"]) if patient.get("insurance_plan_id") else None
    charge, channel = S.adjudicate(product, plan)
    now = S.iso_now()
    record = {
        "id": S.new_id(),
        "appointment_id": appt["id"],
        "patient_id": patient["id"],
        "lot_id": lot["id"],
        "administered_by": user_id,
        "administered_at": administered_at,
        "dose_number": appt["dose_number"],
        "charge_cents": charge,
        "billing_channel": channel,
        "status": "COMPLETED",
        "adverse_event_flag": False,
        "clinic_event_id": clinic_event_id,
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.immunization_records[record["id"]] = record
    lot["doses_available"] -= 1
    S.touch(lot)
    due_at = S.clock_ts(DB.clock + timedelta(hours=protocol["registry_deadline_hours"]))
    payload = S.render_payload(protocol["registry_format"], record, patient, product, lot, appt)
    submission = {
        "id": S.new_id(),
        "immunization_record_id": record["id"],
        "payload_format": protocol["registry_format"],
        "payload": payload,
        "due_at": due_at,
        "submitted_at": None,
        "acknowledged_at": None,
        "is_late": False,
        "status": "PENDING",
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.registry_submissions[submission["id"]] = submission
    required_minutes = 30 if patient["high_risk_flag"] else product["observation_minutes"]
    session = {
        "id": S.new_id(),
        "immunization_record_id": record["id"],
        "observer_id": user_id,
        "required_minutes": required_minutes,
        "started_at": administered_at,
        "ended_at": None,
        "adverse_reaction": False,
        "reaction_notes": None,
        "status": "IN_PROGRESS",
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.observation_sessions[session["id"]] = session
    if event is not None:
        event["doses_administered"] += 1
        S.touch(event)
    appt["status"] = "VACCINATED"
    appt["scheduled_dose_count_today"] = S.scheduled_dose_count_today(
        patient["id"], appt["store_id"], S.parse_dt(appt["slot_start"]))
    if clinic_event_id is not None:
        appt["clinic_event_id"] = clinic_event_id
    S.touch(appt)
    return success(record, status=201)


@app.post("/immunization/appointments/<appt_id>/cancel")
def cancel_appointment(appt_id):
    user_id, role = require_roles(["PharmacyTechnician", "Pharmacist", "Patient"])
    appt = get_or_404(DB.appointments, appt_id)
    if role == "Patient" and appt["patient_id"] != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Patients may only cancel their own appointments")
    if appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise err("ERR_APPOINTMENT_NOT_CANCELLABLE", "Appointment is not cancellable")
    appt["status"] = "CANCELLED"
    S.touch(appt)
    return success(appt)


# ---------------------------------------------------------------------------
# Immunization Records
# ---------------------------------------------------------------------------

RECORD_READERS = ["Pharmacist", "Immunizer", "ComplianceOfficer", "PharmacyTechnician"]


@app.get("/immunization/immunization-records/<record_id>")
def get_record(record_id):
    require_roles(RECORD_READERS)
    return success(get_or_404(DB.immunization_records, record_id))


@app.get("/immunization/immunization-records")
def list_records():
    require_roles(RECORD_READERS)
    items = list(DB.immunization_records.values())
    for param, field in (("patient_id", "patient_id"), ("lot_id", "lot_id"), ("status", "status")):
        if request.args.get(param) is not None:
            items = [r for r in items if r[field] == request.args[param]]
    return list_response(items, request.args)


@app.post("/immunization/immunization-records/<record_id>/void")
def void_record(record_id):
    user_id, role = require_roles(["Pharmacist"])
    record = get_or_404(DB.immunization_records, record_id)
    body()  # reason optional-accepted; presence not enforced
    if record["status"] != "COMPLETED":
        raise err("ERR_RECORD_ALREADY_VOIDED", "Record is already VOIDED")
    submission = None
    for s in DB.registry_submissions.values():
        if s["immunization_record_id"] == record["id"]:
            submission = s
            break
    if submission is not None and submission["status"] in ("SUBMITTED", "ACKNOWLEDGED"):
        raise err("ERR_SUBMISSION_ALREADY_TRANSMITTED",
                  "Submission already transmitted; cannot void")
    record["status"] = "VOIDED"
    S.touch(record)
    lot = DB.lots.get(record["lot_id"])
    if lot is not None:
        lot["doses_available"] += 1
        S.touch(lot)
    if submission is not None:
        del DB.registry_submissions[submission["id"]]
    for sess in DB.observation_sessions.values():
        if sess["immunization_record_id"] == record["id"] and sess["status"] == "IN_PROGRESS":
            sess["status"] = "COMPLETED"
            sess["ended_at"] = S.clock_ts()
            S.touch(sess)
    if record.get("clinic_event_id"):
        event = DB.clinic_events.get(record["clinic_event_id"])
        if event is not None:
            event["doses_administered"] = max(0, event["doses_administered"] - 1)
            S.touch(event)
    return success(record)


@app.get("/immunization/appointments/<appt_id>/immunization-records")
def list_records_for_appointment(appt_id):
    require_roles(RECORD_READERS)
    appt = get_or_404(DB.appointments, appt_id)
    items = [r for r in DB.immunization_records.values() if r["appointment_id"] == appt["id"]]
    items.sort(key=lambda e: (S.parse_dt(e["created_at"]), e["id"]))
    return success(items, is_array=True)


# ---------------------------------------------------------------------------
# Registry Submissions
# ---------------------------------------------------------------------------

@app.get("/immunization/immunization-records/<record_id>/registry-submissions")
def list_submissions_for_record(record_id):
    require_roles(["ComplianceOfficer", "Pharmacist"])
    record = get_or_404(DB.immunization_records, record_id)
    items = [s for s in DB.registry_submissions.values()
             if s["immunization_record_id"] == record["id"]]
    items.sort(key=lambda e: (S.parse_dt(e["created_at"]), e["id"]))
    return success(items, is_array=True)


@app.get("/immunization/registry-submissions/<submission_id>")
def get_submission(submission_id):
    require_roles(["ComplianceOfficer"])
    sub = get_or_404(DB.registry_submissions, submission_id)
    if sub["acknowledged_at"] is None and DB.clock > S.parse_dt(sub["due_at"]):
        sub = dict(sub)
        sub["is_late"] = True
    return success(sub)


@app.get("/immunization/registry-submissions")
def list_submissions():
    require_roles(["ComplianceOfficer"])
    items = list(DB.registry_submissions.values())
    if request.args.get("status") is not None:
        items = [s for s in items if s["status"] == request.args["status"]]
    if request.args.get("payload_format") is not None:
        items = [s for s in items if s["payload_format"] == request.args["payload_format"]]
    if request.args.get("is_late") is not None:
        want = request.args["is_late"].strip().lower() == "true"
        items = [s for s in items if bool(s["is_late"]) == want]
    return list_response(items, request.args)


@app.post("/immunization/registry-submissions/<submission_id>/submit")
def submit_submission(submission_id):
    require_roles(["ComplianceOfficer"])
    sub = get_or_404(DB.registry_submissions, submission_id)
    data = body()
    record = DB.immunization_records.get(sub["immunization_record_id"])
    if sub["status"] not in ("PENDING", "REJECTED", "LATE_UNRESOLVED"):
        raise err("ERR_SUBMISSION_NOT_SUBMITTABLE", "Submission not in a submittable state")
    if record is not None and record["status"] == "VOIDED":
        raise err("ERR_RECORD_VOIDED", "Parent record is VOIDED")
    if sub["status"] == "REJECTED":
        corrected = data.get("corrected_payload")
        if corrected is None:
            raise err("ERR_CORRECTED_PAYLOAD_REQUIRED",
                      "corrected_payload required for resubmission of a REJECTED submission")
        sub["payload"] = corrected
    sub["status"] = "SUBMITTED"
    sub["submitted_at"] = S.clock_ts()
    S.touch(sub)
    return success(sub)


@app.post("/immunization/registry-submissions/<submission_id>/acknowledge")
def acknowledge_submission(submission_id):
    require_roles(["ComplianceOfficer"])
    sub = get_or_404(DB.registry_submissions, submission_id)
    if sub["status"] != "SUBMITTED":
        raise err("ERR_SUBMISSION_NOT_SUBMITTED", "Submission is not SUBMITTED")
    sub["status"] = "ACKNOWLEDGED"
    sub["acknowledged_at"] = S.clock_ts()
    if DB.clock > S.parse_dt(sub["due_at"]):
        sub["is_late"] = True
    S.touch(sub)
    return success(sub)


@app.post("/immunization/registry-submissions/<submission_id>/reject")
def reject_submission(submission_id):
    require_roles(["ComplianceOfficer"])
    sub = get_or_404(DB.registry_submissions, submission_id)
    if sub["status"] != "SUBMITTED":
        raise err("ERR_SUBMISSION_NOT_SUBMITTED", "Submission is not SUBMITTED")
    sub["status"] = "REJECTED"
    S.touch(sub)
    return success(sub)


# ---------------------------------------------------------------------------
# Observation Sessions
# ---------------------------------------------------------------------------

@app.get("/immunization/immunization-records/<record_id>/observation-sessions")
def list_sessions_for_record(record_id):
    require_roles(["ObservationMonitor", "Pharmacist", "ComplianceOfficer"])
    record = get_or_404(DB.immunization_records, record_id)
    items = [s for s in DB.observation_sessions.values()
             if s["immunization_record_id"] == record["id"]]
    items.sort(key=lambda e: (S.parse_dt(e["created_at"]), e["id"]))
    return success(items, is_array=True)


@app.post("/immunization/observation-sessions/<session_id>/complete")
def complete_session(session_id):
    user_id, role = require_roles(["ObservationMonitor"])
    sess = get_or_404(DB.observation_sessions, session_id)
    if sess["status"] != "IN_PROGRESS":
        raise err("ERR_SESSION_NOT_IN_PROGRESS", "Session is not IN_PROGRESS")
    earliest = S.parse_dt(sess["started_at"]) + timedelta(minutes=sess["required_minutes"])
    if DB.clock < earliest:
        raise err("ERR_OBSERVATION_TOO_EARLY", "Observation window has not elapsed")
    if sess["adverse_reaction"]:
        raise err("ERR_REACTION_MUST_ESCALATE",
                  "Session with an adverse reaction must be escalated")
    if sess["observer_id"] != user_id:
        raise err("ERR_NOT_ASSIGNED_OBSERVER", "Caller is not the assigned observer")
    sess["status"] = "COMPLETED"
    sess["ended_at"] = S.clock_ts()
    S.touch(sess)
    return success(sess)


@app.post("/immunization/observation-sessions/<session_id>/escalate")
def escalate_session(session_id):
    user_id, role = require_roles(["ObservationMonitor", "Pharmacist"])
    sess = get_or_404(DB.observation_sessions, session_id)
    if sess["status"] != "IN_PROGRESS":
        raise err("ERR_SESSION_NOT_IN_PROGRESS", "Session is not IN_PROGRESS")
    data = body()
    adverse = bool(data.get("adverse_reaction", False))
    notes = data.get("reaction_notes")
    if adverse and (not isinstance(notes, str) or not notes.strip()):
        raise err("ERR_REACTION_NOTES_REQUIRED",
                  "reaction_notes required when adverse_reaction is true")
    sess["adverse_reaction"] = adverse
    if adverse:
        sess["reaction_notes"] = notes
    sess["status"] = "ESCALATED"
    S.touch(sess)
    record = DB.immunization_records.get(sess["immunization_record_id"])
    if record is not None:
        record["adverse_event_flag"] = True
        S.touch(record)
    return success(sess)


# ---------------------------------------------------------------------------
# Clinic Events
# ---------------------------------------------------------------------------

EVENT_READERS = ["StoreManager", "Pharmacist", "ComplianceOfficer"]


@app.post("/immunization/clinic-events")
def create_clinic_event():
    require_roles(["StoreManager"])
    data = body()
    for f in ("store_id", "employer_name", "event_start", "event_end", "mobile_lot_id", "doses_reserved"):
        if data.get(f) is None:
            bad(f"Missing required field: {f}")
    store = DB.stores.get(data["store_id"])
    if store is None:
        raise err("ERR_NOT_FOUND", "Store not found")
    lot = DB.lots.get(data["mobile_lot_id"])
    if lot is None:
        raise err("ERR_NOT_FOUND", "Mobile lot not found")
    check_int(data["doses_reserved"], "doses_reserved", 0)
    start = S.parse_dt(data["event_start"])
    end = S.parse_dt(data["event_end"])
    if end <= start or end.date() != start.date():
        raise err("ERR_EVENT_STILL_RUNNING",
                  "event_end must be strictly after event_start within the same calendar day")
    if lot["status"] != "RELEASED" or lot_expired(lot):
        raise err("ERR_LOT_NOT_ADMINISTERABLE", "Mobile lot must be RELEASED and non-expired")
    # Raw capacity (priority 15)
    if data["doses_reserved"] > lot["doses_available"]:
        raise err("ERR_INSUFFICIENT_DOSES", "doses_reserved exceeds mobile lot availability")
    # Overlap (priority 16) — half-open [start, end) intervals
    overlapping_reserved = 0
    for ev in DB.clinic_events.values():
        if ev["mobile_lot_id"] != lot["id"] or ev["status"] not in ("PLANNED", "ACTIVE"):
            continue
        o_start = S.parse_dt(ev["event_start"])
        o_end = S.parse_dt(ev["event_end"])
        if start < o_end and o_start < end:
            overlapping_reserved += ev["doses_reserved"]
    if data["doses_reserved"] > lot["doses_available"] - overlapping_reserved:
        raise err("ERR_MOBILE_LOT_OVER_RESERVED",
                  "Mobile lot over-reserved across overlapping events")
    now = S.iso_now()
    event = {
        "id": S.new_id(),
        "store_id": store["id"],
        "employer_name": data["employer_name"],
        "event_start": data["event_start"],
        "event_end": data["event_end"],
        "mobile_lot_id": lot["id"],
        "doses_reserved": data["doses_reserved"],
        "doses_administered": 0,
        "status": "PLANNED",
        "created_at": now, "updated_at": now, "version": 1,
    }
    DB.clinic_events[event["id"]] = event
    return success(event, status=201)


@app.get("/immunization/stores/<store_id>/clinic-events")
def list_store_events(store_id):
    require_roles(EVENT_READERS)
    store = get_or_404(DB.stores, store_id)
    items = [e for e in DB.clinic_events.values() if e["store_id"] == store["id"]]
    if request.args.get("status") is not None:
        items = [e for e in items if e["status"] == request.args["status"]]
    return list_response(items, request.args)


@app.get("/immunization/clinic-events/<event_id>")
def get_clinic_event(event_id):
    require_roles(EVENT_READERS)
    return success(get_or_404(DB.clinic_events, event_id))


@app.get("/immunization/clinic-events")
def list_clinic_events():
    require_roles(EVENT_READERS)
    items = list(DB.clinic_events.values())
    for param, field in (("store_id", "store_id"), ("mobile_lot_id", "mobile_lot_id"), ("status", "status")):
        if request.args.get(param) is not None:
            items = [e for e in items if e[field] == request.args[param]]
    return list_response(items, request.args)


@app.post("/immunization/clinic-events/<event_id>/cancel")
def cancel_clinic_event(event_id):
    require_roles(["StoreManager"])
    event = get_or_404(DB.clinic_events, event_id)
    if event["status"] != "PLANNED":
        raise err("ERR_EVENT_NOT_CANCELLABLE", "Event is not PLANNED")
    event["status"] = "CANCELLED"
    S.touch(event)
    return success(event)


@app.post("/immunization/clinic-events/<event_id>/close")
def close_clinic_event(event_id):
    require_roles(["StoreManager"])
    event = get_or_404(DB.clinic_events, event_id)
    if event["status"] != "ACTIVE":
        raise err("ERR_EVENT_NOT_ACTIVE", "Event is not ACTIVE")
    if DB.clock < S.parse_dt(event["event_end"]):
        raise err("ERR_EVENT_STILL_RUNNING", "Event has not ended")
    if event["doses_administered"] > event["doses_reserved"]:
        raise err("ERR_RECONCILIATION_OVERFLOW", "doses_administered exceeds doses_reserved")
    returned = event["doses_reserved"] - event["doses_administered"]
    lot = DB.lots.get(event["mobile_lot_id"])
    if lot is not None:
        lot["doses_available"] += returned
        S.touch(lot)
    event["status"] = "CLOSED"
    S.touch(event)
    return success(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
