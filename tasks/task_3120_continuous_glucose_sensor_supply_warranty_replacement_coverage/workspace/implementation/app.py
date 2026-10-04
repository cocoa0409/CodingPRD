"""CGM Supply, Warranty & Coverage API — Flask implementation.

All state is in-memory (see db.py). The store starts empty on every boot.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Flask, request

from db import db
from errors import ApiError, err_not_found, err_invalid_request, err_invalid_state
from helpers import (
    add_days_str,
    date_to_str,
    day_diff,
    evaluate_criteria,
    iso_now_3f,
    logical_now_dt,
    logical_today,
    new_id,
    opt_enum,
    opt_field,
    parse_date,
    req_enum,
    req_field,
    get_body,
    set_logical_now,
    stamp_new,
    touch,
    COVERED_DIAGNOSES,
    EARLY_REFILL_TOLERANCE_FRACTION,
    WATCH_THRESHOLD,
    HOLD_THRESHOLD,
    SAVINGS_CARD_EXCLUDED_STATES,
    CARD_PROGRAM_CAP_CENTS,
    CARD_ANNUAL_FILL_MULTIPLIER,
    PRO_RATA_MIN_GENERATION,
    PAYER_SPECIALTIES,
    BENEFIT_ROUTES,
    COVERAGE_POLICIES,
    READER_CHANNELS,
    BINDING_CHANNELS,
    INSULIN_USES,
    FAILURE_CATEGORIES,
    SEVERITIES,
    EVENT_TYPES,
    DENIAL_REASONS,
)
from middleware import require_roles
from response import success_object, paginate, sort_by_created_at, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(err_not_found("route"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(err_not_found("route"))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "internal error", 500))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def serialize(entity, kind):
    """Return a copy with internal keys stripped; dynamic fields computed."""
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    if kind == "sensor_unit":
        if out.get("status") == "ACTIVE" and out.get("activated_on"):
            out["wear_days_used"] = max(0, day_diff(date_to_str(logical_today()), out["activated_on"]))
    return out


# ---------------------------------------------------------------------------
# Auto-transition reconciliation (logical-clock driven)
# ---------------------------------------------------------------------------

def reconcile():
    today = logical_today()
    now = logical_now_dt()
    # Prescription expiry
    for rx in db.prescriptions.values():
        if rx["status"] == "ACTIVE" and day_diff(date_to_str(today), rx["expires_on"]) > 0:
            rx["status"] = "EXPIRED"
            touch(rx)
            for cv in db.coverage_verifications.values():
                if cv["prescription_id"] == rx["id"] and cv["decision"] == "PENDING":
                    payer = db.payers.get(cv["payer_id"])
                    if payer and payer["status"] == "TERMINATED":
                        cv["decision"] = "DENIED"
                        cv["denial_reason"] = "PAYER_INACTIVE"
                        touch(cv)
    # Sensor wear expiry: unit ACTIVE whose binding.expires_at < logical now
    for unit in db.sensor_units.values():
        if unit["status"] != "ACTIVE":
            continue
        binding = None
        for b in db.device_bindings.values():
            if b["sensor_unit_id"] == unit["id"] and b["status"] == "ACTIVE":
                binding = b
                break
        if binding is None:
            continue
        expires_at = binding["_expires_at_dt"]
        if now > expires_at:
            unit["status"] = "EXPIRED_WORN"
            touch(unit)
            binding["status"] = "ENDED_NORMALLY"
            touch(binding)


@app.before_request
def _before():
    if request.path.startswith("/cgm"):
        reconcile()


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(table, rid, what="resource"):
    rec = table.get(rid)
    if rec is None:
        raise err_not_found(what)
    return rec


def product_for_lot(lot):
    return db.sensor_products.get(lot["product_id"])


def product_for_unit(unit):
    lot = db.sensor_lots.get(unit["lot_id"])
    return db.sensor_products.get(lot["product_id"]) if lot else None


def recompute_lot_posture(lot):
    if lot["complaint_count"] >= HOLD_THRESHOLD:
        new = "HOLD"
    elif lot["complaint_count"] >= WATCH_THRESHOLD:
        new = "WATCH"
    else:
        new = "NORMAL"
    if new != lot["complaint_posture"]:
        lot["complaint_posture"] = new
        touch(lot)


def floor_money(cents, pct):
    return int((Decimal(int(cents)) * Decimal(str(pct))).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.post("/cgm/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso8601 = req_field(body, "to_iso8601", (str,))
    # Validate it parses as an ISO 8601 timestamp
    s = to_iso8601
    try:
        from datetime import datetime
        datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    set_logical_now(to_iso8601)
    return success_object({"current_utc": to_iso8601}, 200)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.post("/cgm/patients")
def create_patient():
    require_roles("PlatformAdmin")
    body = get_body()
    full_name = req_field(body, "full_name", (str,))
    dob = req_field(body, "date_of_birth", (str,))
    parse_date(dob)
    state_code = req_field(body, "state_code", (str,))
    rec = stamp_new({
        "full_name": full_name,
        "date_of_birth": dob,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    db.patients[rec["id"]] = rec
    return success_object(serialize(rec, "patient"), 201)


@app.get("/cgm/patients")
def list_patients():
    require_roles("Any")
    return paginate([serialize(r, "patient") for r in sort_by_created_at(db.patients.values())])


@app.get("/cgm/patients/<pid>")
def get_patient(pid):
    require_roles("Any")
    rec = get_or_404(db.patients, pid, "patient")
    return success_object(serialize(rec, "patient"))


@app.get("/cgm/patients/<pid>/coverage-verifications")
def list_patient_coverage_verifications(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(v, "coverage_verification") for v in db.coverage_verifications.values() if v["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/patients/<pid>/sensor-units")
def list_patient_sensor_units(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(u, "sensor_unit") for u in db.sensor_units.values() if u.get("patient_id") == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/patients/<pid>/warranty-claims")
def list_patient_warranty_claims(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(c, "warranty_claim") for c in db.warranty_claims.values() if c["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/patients/<pid>/adverse-event-reports")
def list_patient_aers(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(a, "aer") for a in db.adverse_event_reports.values() if a["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


# ---------------------------------------------------------------------------
# Prescribers
# ---------------------------------------------------------------------------

@app.post("/cgm/prescribers")
def create_prescriber():
    require_roles("PlatformAdmin")
    body = get_body()
    full_name = req_field(body, "full_name", (str,))
    npi = req_field(body, "npi", (str,))
    specialty = req_enum(body, "specialty", PAYER_SPECIALTIES)
    rec = stamp_new({
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
        "status": "ACTIVE",
    })
    db.prescribers[rec["id"]] = rec
    return success_object(serialize(rec, "prescriber"), 201)


@app.get("/cgm/prescribers/<pid>")
def get_prescriber(pid):
    require_roles("Any")
    rec = get_or_404(db.prescribers, pid, "prescriber")
    return success_object(serialize(rec, "prescriber"))


@app.get("/cgm/prescribers/<pid>/prescriptions")
def list_prescriber_prescriptions(pid):
    require_roles("Any")
    get_or_404(db.prescribers, pid, "prescriber")
    items = [serialize(r, "prescription") for r in db.prescriptions.values() if r["prescriber_id"] == pid]
    return paginate(sort_by_created_at(items))


# ---------------------------------------------------------------------------
# Payers
# ---------------------------------------------------------------------------

@app.post("/cgm/payers")
def create_payer():
    require_roles("PlatformAdmin")
    body = get_body()
    name = req_field(body, "name", (str,))
    plan_code = req_field(body, "plan_code", (str,))
    benefit_route = req_enum(body, "benefit_route", BENEFIT_ROUTES)
    policy = req_enum(body, "cgm_coverage_policy", COVERAGE_POLICIES)
    pharmacy_copay_pct = req_field(body, "pharmacy_copay_pct", (int, float))
    dme_coinsurance_pct = req_field(body, "dme_coinsurance_pct", (int, float))
    deductible_cap_cents = req_field(body, "deductible_cap_cents", (int,))
    for p in db.payers.values():
        if p["plan_code"] == plan_code:
            raise err_invalid_request("plan_code must be unique")
    rec = stamp_new({
        "name": name,
        "plan_code": plan_code,
        "benefit_route": benefit_route,
        "cgm_coverage_policy": policy,
        "pharmacy_copay_pct": pharmacy_copay_pct,
        "dme_coinsurance_pct": dme_coinsurance_pct,
        "deductible_cap_cents": deductible_cap_cents,
        "status": "ACTIVE",
    })
    db.payers[rec["id"]] = rec
    return success_object(serialize(rec, "payer"), 201)


@app.get("/cgm/payers/<pid>")
def get_payer(pid):
    require_roles("Any")
    rec = get_or_404(db.payers, pid, "payer")
    return success_object(serialize(rec, "payer"))


@app.get("/cgm/payers/<pid>/coverage-verifications")
def list_payer_coverage_verifications(pid):
    require_roles("Any")
    get_or_404(db.payers, pid, "payer")
    items = [serialize(v, "coverage_verification") for v in db.coverage_verifications.values() if v["payer_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/payers/<pid>/support-enrollments")
def list_payer_support_enrollments(pid):
    require_roles("Any")
    get_or_404(db.payers, pid, "payer")
    items = [serialize(e, "support_enrollment") for e in db.support_enrollments.values() if e["payer_id"] == pid]
    return paginate(sort_by_created_at(items))


# ---------------------------------------------------------------------------
# Sensor Products
# ---------------------------------------------------------------------------

@app.post("/cgm/sensor-products")
def create_sensor_product():
    require_roles("PlatformAdmin")
    body = get_body()
    sku = req_field(body, "sku", (str,))
    generation = req_field(body, "generation", (int,))
    wear_days = req_field(body, "wear_days", (int,))
    reader_channel = req_enum(body, "reader_channel", READER_CHANNELS)
    compat = req_field(body, "compatible_prior_generations", (list,))
    for g in compat:
        if not isinstance(g, int) or isinstance(g, bool):
            raise err_invalid_request("compatible_prior_generations must be an array of integers")
    list_price_cents = req_field(body, "list_price_cents", (int,))
    for p in db.sensor_products.values():
        if p["sku"] == sku:
            raise err_invalid_request("sku must be unique")
    rec = stamp_new({
        "sku": sku,
        "generation": generation,
        "wear_days": wear_days,
        "reader_channel": reader_channel,
        "compatible_prior_generations": list(compat),
        "list_price_cents": list_price_cents,
        "status": "ACTIVE",
    })
    db.sensor_products[rec["id"]] = rec
    return success_object(serialize(rec, "sensor_product"), 201)


@app.get("/cgm/sensor-products/<pid>")
def get_sensor_product(pid):
    require_roles("Any")
    rec = get_or_404(db.sensor_products, pid, "sensor_product")
    return success_object(serialize(rec, "sensor_product"))


@app.get("/cgm/sensor-products/<pid>/prescriptions")
def list_product_prescriptions(pid):
    require_roles("Any")
    get_or_404(db.sensor_products, pid, "sensor_product")
    items = [serialize(r, "prescription") for r in db.prescriptions.values() if r["product_id"] == pid]
    return paginate(sort_by_created_at(items))


# ---------------------------------------------------------------------------
# Sensor Lots
# ---------------------------------------------------------------------------

@app.post("/cgm/sensor-products/<pid>/sensor-lots")
def create_sensor_lot(pid):
    require_roles("PlatformAdmin")
    product = get_or_404(db.sensor_products, pid, "sensor_product")
    body = get_body()
    lot_code = req_field(body, "lot_code", (str,))
    quantity_manufactured = req_field(body, "quantity_manufactured", (int,))
    manufacture_date = req_field(body, "manufacture_date", (str,))
    expiry_date = req_field(body, "expiry_date", (str,))
    md = parse_date(manufacture_date)
    ed = parse_date(expiry_date)
    if not ed > md:
        raise err_invalid_request("expiry_date must be strictly later than manufacture_date")
    for lot in db.sensor_lots.values():
        if lot["product_id"] == pid and lot["lot_code"] == lot_code:
            raise err_invalid_request("lot_code must be unique per product")
    rec = stamp_new({
        "product_id": pid,
        "lot_code": lot_code,
        "quantity_manufactured": quantity_manufactured,
        "complaint_count": 0,
        "complaint_posture": "NORMAL",
        "manufacture_date": manufacture_date,
        "expiry_date": expiry_date,
    })
    db.sensor_lots[rec["id"]] = rec
    return success_object(serialize(rec, "sensor_lot"), 201)


@app.get("/cgm/sensor-products/<pid>/sensor-lots")
def list_product_lots(pid):
    require_roles("Any")
    get_or_404(db.sensor_products, pid, "sensor_product")
    items = [serialize(l, "sensor_lot") for l in db.sensor_lots.values() if l["product_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/sensor-lots/<lid>")
def get_sensor_lot(lid):
    require_roles("Any")
    rec = get_or_404(db.sensor_lots, lid, "sensor_lot")
    return success_object(serialize(rec, "sensor_lot"))


@app.get("/cgm/sensor-lots/<lid>/sensor-orders")
def list_lot_orders(lid):
    require_roles("Any")
    get_or_404(db.sensor_lots, lid, "sensor_lot")
    items = [serialize(o, "sensor_order") for o in db.sensor_orders.values() if o["lot_id"] == lid]
    return paginate(sort_by_created_at(items))


@app.post("/cgm/sensor-lots/<lid>/downgrade-posture")
def downgrade_lot_posture(lid):
    require_roles("QualityEngineer")
    lot = get_or_404(db.sensor_lots, lid, "sensor_lot")
    body = get_body()
    review_notes = req_field(body, "review_notes", (str,))
    if not review_notes:
        raise err_invalid_request("review_notes is required")
    if lot["complaint_posture"] == "HOLD":
        lot["complaint_posture"] = "WATCH"
    elif lot["complaint_posture"] == "WATCH":
        lot["complaint_posture"] = "NORMAL"
    else:
        raise err_invalid_state("lot posture cannot be downgraded from NORMAL")
    touch(lot)
    return success_object(serialize(lot, "sensor_lot"))


# ---------------------------------------------------------------------------
# Sensor Units
# ---------------------------------------------------------------------------

@app.post("/cgm/sensor-lots/<lid>/sensor-units")
def create_sensor_unit(lid):
    require_roles("PlatformAdmin")
    get_or_404(db.sensor_lots, lid, "sensor_lot")
    body = get_body()
    serial_number = req_field(body, "serial_number", (str,))
    for u in db.sensor_units.values():
        if u["serial_number"] == serial_number:
            raise err_invalid_request("serial_number must be unique")
    rec = stamp_new({
        "lot_id": lid,
        "serial_number": serial_number,
        "status": "IN_STOCK",
        "patient_id": None,
        "activated_on": None,
        "failed_on": None,
        "wear_days_used": 0,
    })
    db.sensor_units[rec["id"]] = rec
    return success_object(serialize(rec, "sensor_unit"), 201)


@app.get("/cgm/sensor-lots/<lid>/sensor-units")
def list_lot_units(lid):
    require_roles("Any")
    get_or_404(db.sensor_lots, lid, "sensor_lot")
    items = [serialize(u, "sensor_unit") for u in db.sensor_units.values() if u["lot_id"] == lid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/sensor-units/<uid>")
def get_sensor_unit(uid):
    require_roles("Any")
    rec = get_or_404(db.sensor_units, uid, "sensor_unit")
    return success_object(serialize(rec, "sensor_unit"))


@app.get("/cgm/sensor-units/<uid>/device-bindings")
def list_unit_bindings(uid):
    require_roles("Any")
    get_or_404(db.sensor_units, uid, "sensor_unit")
    items = [serialize(b, "device_binding") for b in db.device_bindings.values() if b["sensor_unit_id"] == uid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/sensor-units/<uid>/replacement-shipments")
def list_unit_replacement_shipments(uid):
    require_roles("Any")
    get_or_404(db.sensor_units, uid, "sensor_unit")
    items = [serialize(s, "replacement_shipment") for s in db.replacement_shipments.values()
             if s.get("replacement_sensor_unit_id") == uid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/sensor-units/<uid>/adverse-event-reports")
def list_unit_aers(uid):
    require_roles("Any")
    get_or_404(db.sensor_units, uid, "sensor_unit")
    items = [serialize(a, "aer") for a in db.adverse_event_reports.values() if a["sensor_unit_id"] == uid]
    return paginate(sort_by_created_at(items))


@app.post("/cgm/sensor-units/<uid>/report-early-failure")
def report_early_failure(uid):
    ctx = require_roles("Patient")
    unit = get_or_404(db.sensor_units, uid, "sensor_unit")
    if unit["status"] != "ACTIVE":
        raise ApiError("ERR_UNIT_NOT_ACTIVE", "SensorUnit.status != ACTIVE on report-early-failure", 409)
    if ctx.user_id != unit.get("patient_id"):
        raise ApiError("ERR_UNIT_OWNER_MISMATCH", "X-User-ID != sensor_unit.patient_id", 403)
    today = date_to_str(logical_today())
    unit["failed_on"] = today
    unit["wear_days_used"] = max(0, day_diff(today, unit["activated_on"])) if unit.get("activated_on") else 0
    unit["status"] = "FAILED_EARLY"
    touch(unit)
    for b in db.device_bindings.values():
        if b["sensor_unit_id"] == unit["id"] and b["status"] == "ACTIVE":
            b["status"] = "ENDED_EARLY_FAILURE"
            touch(b)
    return success_object(serialize(unit, "sensor_unit"))


@app.post("/cgm/sensor-units/<uid>/scrap")
def scrap_unit(uid):
    require_roles("QualityEngineer")
    unit = get_or_404(db.sensor_units, uid, "sensor_unit")
    if unit["status"] != "FAILED_EARLY":
        raise err_invalid_state("unit must be FAILED_EARLY to scrap")
    for a in db.adverse_event_reports.values():
        if a["sensor_unit_id"] == uid and a["status"] in ("OPEN", "INVESTIGATING"):
            raise err_invalid_state("open or investigating adverse event reports reference this unit")
    unit["status"] = "SCRAPPED"
    touch(unit)
    return success_object(serialize(unit, "sensor_unit"))


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------

@app.post("/cgm/patients/<pid>/prescriptions")
def create_prescription(pid):
    require_roles("Prescriber")
    patient = get_or_404(db.patients, pid, "patient")
    body = get_body()
    prescriber_id = req_field(body, "prescriber_id", (str,))
    product_id = req_field(body, "product_id", (str,))
    get_or_404(db.prescribers, prescriber_id, "prescriber")
    get_or_404(db.sensor_products, product_id, "sensor_product")
    diagnosis_code = req_field(body, "diagnosis_code", (str,))
    insulin_use = req_enum(body, "insulin_use", INSULIN_USES)
    documentation_attached = req_field(body, "documentation_attached", (bool,))
    quantity_per_fill = req_field(body, "quantity_per_fill", (int,))
    fills_authorized = req_field(body, "fills_authorized", (int,))
    written_on = req_field(body, "written_on", (str,))
    parse_date(written_on)
    expected_patient_version = req_field(body, "expected_patient_version", (int,))
    if not (1 <= quantity_per_fill <= 6):
        raise err_invalid_request("quantity_per_fill must be between 1 and 6")
    if not (1 <= fills_authorized <= 24):
        raise err_invalid_request("fills_authorized must be between 1 and 24")
    if expected_patient_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", "expected_patient_version does not match Patient.version", 412)
    rec = stamp_new({
        "patient_id": pid,
        "prescriber_id": prescriber_id,
        "product_id": product_id,
        "diagnosis_code": diagnosis_code,
        "insulin_use": insulin_use,
        "documentation_attached": documentation_attached,
        "quantity_per_fill": quantity_per_fill,
        "fills_authorized": fills_authorized,
        "fills_consumed": 0,
        "written_on": written_on,
        "expires_on": add_days_str(written_on, 365),
        "status": "ACTIVE",
    })
    db.prescriptions[rec["id"]] = rec
    # Writing a prescription against a patient advances the patient's version.
    touch(patient)
    return success_object(serialize(rec, "prescription"), 201)


@app.get("/cgm/patients/<pid>/prescriptions")
def list_patient_prescriptions(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(r, "prescription") for r in db.prescriptions.values() if r["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/prescriptions/<rid>")
def get_prescription(rid):
    require_roles("Any")
    rec = get_or_404(db.prescriptions, rid, "prescription")
    return success_object(serialize(rec, "prescription"))


@app.get("/cgm/prescriptions/<rid>/sensor-orders")
def list_prescription_orders(rid):
    require_roles("Any")
    get_or_404(db.prescriptions, rid, "prescription")
    items = [serialize(o, "sensor_order") for o in db.sensor_orders.values() if o["prescription_id"] == rid]
    return paginate(sort_by_created_at(items))


@app.post("/cgm/prescriptions/<rid>/cancel")
def cancel_prescription(rid):
    ctx = require_roles("Prescriber")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    if rx["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription not in ACTIVE status", 409)
    if ctx.user_id != rx["prescriber_id"]:
        raise ApiError("ERR_PRESCRIPTION_OWNER_MISMATCH", "Acting prescriber is not the prescription's prescriber", 403)
    rx["status"] = "CANCELLED"
    touch(rx)
    for o in db.sensor_orders.values():
        if o["prescription_id"] == rid and o["fulfillment_status"] == "PENDING_PICK":
            o["fulfillment_status"] = "CANCELLED"
            touch(o)
    return success_object(serialize(rx, "prescription"))


# ---------------------------------------------------------------------------
# Coverage Verifications
# ---------------------------------------------------------------------------

@app.post("/cgm/prescriptions/<rid>/coverage-verifications")
def create_coverage_verification(rid):
    require_roles("CoverageReviewer")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    body = get_body()
    payer_id = req_field(body, "payer_id", (str,))
    payer = get_or_404(db.payers, payer_id, "payer")
    if payer["status"] != "ACTIVE":
        raise ApiError("ERR_PAYER_NOT_ACTIVE", "Payer.status != ACTIVE", 409)
    diag, insulin, doc = evaluate_criteria(payer, rx)
    now = logical_now_dt()
    rec = stamp_new({
        "prescription_id": rid,
        "patient_id": rx["patient_id"],
        "payer_id": payer_id,
        "run_at": fmt_dt(now),
        "benefit_route": payer["benefit_route"],
        "criteria_diagnosis_met": diag,
        "criteria_insulin_met": insulin,
        "criteria_documentation_met": doc,
        "decision": "PENDING",
        "denial_reason": None,
    })
    db.coverage_verifications[rec["id"]] = rec
    return success_object(serialize(rec, "coverage_verification"), 201)


@app.get("/cgm/prescriptions/<rid>/coverage-verifications")
def list_prescription_verifications(rid):
    require_roles("Any")
    get_or_404(db.prescriptions, rid, "prescription")
    items = [serialize(v, "coverage_verification") for v in db.coverage_verifications.values() if v["prescription_id"] == rid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/coverage-verifications/<vid>")
def get_coverage_verification(vid):
    require_roles("Any")
    rec = get_or_404(db.coverage_verifications, vid, "coverage_verification")
    return success_object(serialize(rec, "coverage_verification"))


@app.get("/cgm/coverage-verifications/<vid>/sensor-orders")
def list_verification_orders(vid):
    require_roles("Any")
    get_or_404(db.coverage_verifications, vid, "coverage_verification")
    items = [serialize(o, "sensor_order") for o in db.sensor_orders.values() if o["coverage_verification_id"] == vid]
    return paginate(sort_by_created_at(items))


@app.post("/cgm/coverage-verifications/<vid>/decide")
def decide_coverage_verification(vid):
    require_roles("CoverageReviewer")
    cv = get_or_404(db.coverage_verifications, vid, "coverage_verification")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    if cv["decision"] != "PENDING":
        raise ApiError("ERR_VERIFICATION_ALREADY_DECIDED", "CoverageVerification decision != PENDING on decide", 409)
    payer = db.payers.get(cv["payer_id"])
    if decision == "APPROVED":
        if payer is None or payer["status"] != "ACTIVE":
            raise ApiError("ERR_PAYER_NOT_ACTIVE", "Payer.status != ACTIVE", 409)
        rx = db.prescriptions.get(cv["prescription_id"])
        diag, insulin, doc = evaluate_criteria(payer, rx)
        policy = payer["cgm_coverage_policy"]
        if policy == "STRICT":
            ok = diag and insulin and doc
        else:
            ok = diag and insulin
        if not ok:
            raise ApiError("ERR_COVERAGE_CRITERIA_NOT_MET", "Coverage criteria fail under payer.cgm_coverage_policy", 422)
        cv["decision"] = "APPROVED"
        cv["denial_reason"] = None
    else:
        denial_reason = req_enum(body, "denial_reason", DENIAL_REASONS)
        cv["decision"] = "DENIED"
        cv["denial_reason"] = denial_reason
    touch(cv)
    return success_object(serialize(cv, "coverage_verification"))


# ---------------------------------------------------------------------------
# Sensor Orders
# ---------------------------------------------------------------------------

@app.post("/cgm/patients/<pid>/sensor-orders")
def create_sensor_order(pid):
    require_roles("FulfillmentAgent")
    get_or_404(db.patients, pid, "patient")
    body = get_body()
    prescription_id = req_field(body, "prescription_id", (str,))
    coverage_verification_id = req_field(body, "coverage_verification_id", (str,))
    lot_id = req_field(body, "lot_id", (str,))
    quantity = req_field(body, "quantity", (int,))
    rx = get_or_404(db.prescriptions, prescription_id, "prescription")
    cv = get_or_404(db.coverage_verifications, coverage_verification_id, "coverage_verification")
    lot = get_or_404(db.sensor_lots, lot_id, "sensor_lot")
    product = db.sensor_products.get(rx["product_id"])

    # p9: verification belongs to same prescription and is APPROVED
    if cv["prescription_id"] != prescription_id or cv["decision"] != "APPROVED" or rx["patient_id"] != pid:
        raise ApiError("ERR_COVERAGE_NOT_APPROVED",
                       "Referenced verification is not APPROVED or belongs to a different prescription", 409)
    # p10: lot's product matches prescription product
    if lot["product_id"] != rx["product_id"]:
        raise ApiError("ERR_PRODUCT_MISMATCH", "SensorOrder.lot_id product does not match prescription.product_id", 422)
    # p11: prescription ACTIVE and not past expires_on
    today = date_to_str(logical_today())
    if rx["status"] != "ACTIVE" or day_diff(rx["expires_on"], today) < 0:
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription not in ACTIVE status, or past expires_on", 409)
    # p12: refill cadence
    priors = [o for o in db.sensor_orders.values()
              if o["prescription_id"] == prescription_id and o["fulfillment_status"] != "CANCELLED"]
    earliest_refill_date = None
    if priors:
        prior = max(priors, key=lambda o: (o["fill_date"], o["created_at"]))
        supply_days = rx["quantity_per_fill"] * product["wear_days"]
        offset_days = math.ceil(supply_days * (1 - EARLY_REFILL_TOLERANCE_FRACTION))
        earliest_refill_date = add_days_str(prior["fill_date"], offset_days)
        if day_diff(today, earliest_refill_date) < 0:
            raise ApiError("ERR_REFILL_TOO_EARLY", "logical_date < earliest_refill_date per refill_cadence_rule", 409)
    # p15: quantity equals quantity_per_fill
    if quantity != rx["quantity_per_fill"]:
        raise ApiError("ERR_QUANTITY_MISMATCH", "Order quantity != prescription.quantity_per_fill", 422)
    # p16: fills remaining
    if rx["fills_consumed"] >= rx["fills_authorized"]:
        raise ApiError("ERR_PRESCRIPTION_EXHAUSTED", "fills_consumed >= fills_authorized", 409)

    rec = stamp_new({
        "patient_id": pid,
        "prescription_id": prescription_id,
        "coverage_verification_id": coverage_verification_id,
        "lot_id": lot_id,
        "quantity": quantity,
        "fulfillment_status": "PENDING_PICK",
        "billing_status": "UNBILLED",
        "fill_date": today,
        "earliest_refill_date": earliest_refill_date,
        "allowed_amount_cents": 0,
        "plan_paid_cents": 0,
        "patient_paid_cents": 0,
        "savings_card_paid_cents": 0,
    })
    db.sensor_orders[rec["id"]] = rec
    return success_object(serialize(rec, "sensor_order"), 201)


@app.get("/cgm/patients/<pid>/sensor-orders")
def list_patient_orders(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(o, "sensor_order") for o in db.sensor_orders.values() if o["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/sensor-orders/<oid>")
def get_sensor_order(oid):
    require_roles("Any")
    rec = get_or_404(db.sensor_orders, oid, "sensor_order")
    return success_object(serialize(rec, "sensor_order"))


def _order_units(order, status):
    return [u for u in db.sensor_units.values()
            if u["_order_id"] == order["id"] and u["status"] == status] if "_order_id" in order else []


def _units_for_order(order):
    return [u for u in db.sensor_units.values() if u.get("_order_id") == order["id"]]


@app.post("/cgm/sensor-orders/<oid>/pick")
def pick_order(oid):
    require_roles("FulfillmentAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["fulfillment_status"] != "PENDING_PICK":
        raise ApiError("ERR_ORDER_NOT_PICKABLE", "fulfillment_status != PENDING_PICK on pick", 409)
    lot = get_or_404(db.sensor_lots, order["lot_id"], "sensor_lot")
    if lot["complaint_posture"] == "HOLD":
        raise ApiError("ERR_LOT_ON_HOLD", "SensorLot.complaint_posture == HOLD during pick", 409)
    candidates = [u for u in db.sensor_units.values()
                  if u["lot_id"] == lot["id"] and u["status"] == "IN_STOCK"]
    candidates.sort(key=lambda u: (lot["manufacture_date"], u["serial_number"]))
    if len(candidates) < order["quantity"]:
        raise ApiError("ERR_INSUFFICIENT_LOT_STOCK",
                       "Fewer than order.quantity IN_STOCK units remain in lot at pick time", 409)
    chosen = candidates[:order["quantity"]]
    for u in chosen:
        u["status"] = "ALLOCATED"
        u["patient_id"] = order["patient_id"]
        u["_order_id"] = order["id"]
        touch(u)
    rx = db.prescriptions.get(order["prescription_id"])
    if rx is not None:
        rx["fills_consumed"] += 1
        if rx["status"] == "ACTIVE" and rx["fills_consumed"] >= rx["fills_authorized"]:
            rx["status"] = "EXHAUSTED"
        touch(rx)
    order["fulfillment_status"] = "PICKED"
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/adjudicate")
def adjudicate_order(oid):
    require_roles("BillingAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    body = get_body()
    expected_order_version = req_field(body, "expected_order_version", (int,))
    if expected_order_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", "expected_order_version does not match SensorOrder.version", 412)
    if order["billing_status"] != "UNBILLED":
        raise ApiError("ERR_ORDER_ALREADY_ADJUDICATED", "billing_status != UNBILLED on adjudicate", 409)
    if order["fulfillment_status"] not in ("PENDING_PICK", "PICKED"):
        raise ApiError("ERR_ORDER_NOT_ADJUDICATABLE_STATE",
                       "fulfillment_status not in {PENDING_PICK, PICKED} on adjudicate", 409)
    for other in db.sensor_orders.values():
        if (other["id"] != order["id"]
                and other["prescription_id"] == order["prescription_id"]
                and other["fill_date"] == order["fill_date"]
                and other["billing_status"] in ("ADJUDICATED", "PAID")):
            raise ApiError("ERR_DUPLICATE_ADJUDICATION",
                           "Another ADJUDICATED or PAID order for same prescription on same fill_date exists", 409)

    rx = db.prescriptions[order["prescription_id"]]
    product = db.sensor_products[rx["product_id"]]
    cv = db.coverage_verifications[order["coverage_verification_id"]]
    payer = db.payers[cv["payer_id"]]
    patient = db.patients[order["patient_id"]]

    qty = order["quantity"]
    list_price = product["list_price_cents"]
    allowed = qty * list_price

    if cv["benefit_route"] == "PHARMACY":
        used = db.deductible_used.get(order["patient_id"], 0)
        deductible_remaining = max(0, payer["deductible_cap_cents"] - used)
        deductible_applied = min(allowed, deductible_remaining)
        # PRD §3.6: coinsurance base = allowed - deductible applied; the per-line
        # floored coinsurance applies to the post-deductible remainder only.
        coinsurance_base = allowed - deductible_applied
        patient_coinsurance = min(qty * floor_money(list_price, payer["pharmacy_copay_pct"]),
                                  coinsurance_base)
        patient_paid = deductible_applied + patient_coinsurance
        plan_paid = allowed - patient_paid
    else:  # DME
        deductible_applied = 0
        patient_coinsurance = qty * floor_money(list_price, payer["dme_coinsurance_pct"])
        patient_paid = patient_coinsurance
        plan_paid = allowed - patient_paid

    savings_card_paid = 0
    enrollment_used = None
    if cv["benefit_route"] == "PHARMACY" and patient["state_code"] not in SAVINGS_CARD_EXCLUDED_STATES:
        candidates = [e for e in db.support_enrollments.values()
                      if e["patient_id"] == order["patient_id"]
                      and e["payer_id"] == payer["id"]
                      and e["status"] == "ENROLLED"]
        candidates = sort_by_created_at(candidates)
        if candidates:
            enrollment_used = candidates[0]
            savings_card_paid = min(patient_paid,
                                    enrollment_used["card_max_per_fill_cents"],
                                    enrollment_used["card_remaining_cents"])
            patient_paid -= savings_card_paid

    order["allowed_amount_cents"] = allowed
    order["plan_paid_cents"] = plan_paid
    order["patient_paid_cents"] = patient_paid
    order["savings_card_paid_cents"] = savings_card_paid
    order["_deductible_applied_cents"] = deductible_applied
    order["_enrollment_id"] = enrollment_used["id"] if enrollment_used else None
    order["billing_status"] = "ADJUDICATED"
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/mark-paid")
def mark_paid_order(oid):
    require_roles("BillingAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["billing_status"] != "ADJUDICATED":
        raise ApiError("ERR_ORDER_NOT_PAID_STATE", "billing_status != ADJUDICATED on mark-paid", 409)
    order["billing_status"] = "PAID"
    # Record deductible usage (single-order scope; starts at 0 per plan year)
    db.deductible_used[order["patient_id"]] = db.deductible_used.get(order["patient_id"], 0) + order.get("_deductible_applied_cents", 0)
    enr_id = order.get("_enrollment_id")
    if enr_id and order["savings_card_paid_cents"] > 0:
        enr = db.support_enrollments.get(enr_id)
        if enr is not None:
            enr["card_remaining_cents"] -= order["savings_card_paid_cents"]
            touch(enr)
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/reverse")
def reverse_order(oid):
    require_roles("BillingAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["billing_status"] != "ADJUDICATED":
        raise ApiError("ERR_ORDER_NOT_REVERSIBLE", "billing_status != ADJUDICATED on reverse", 409)
    if order["fulfillment_status"] not in ("PENDING_PICK", "PICKED"):
        raise ApiError("ERR_ORDER_NOT_REVERSIBLE", "cannot reverse after ship", 409)
    order["billing_status"] = "REVERSED"
    order["plan_paid_cents"] = 0
    order["patient_paid_cents"] = 0
    order["savings_card_paid_cents"] = 0
    order["allowed_amount_cents"] = 0
    if order["fulfillment_status"] == "PICKED":
        for u in _units_for_order(order):
            if u["status"] == "ALLOCATED":
                u["status"] = "IN_STOCK"
                u["patient_id"] = None
                u.pop("_order_id", None)
                touch(u)
    rx = db.prescriptions.get(order["prescription_id"])
    if rx is not None:
        rx["fills_consumed"] = max(0, rx["fills_consumed"] - 1)
        if rx["status"] == "EXHAUSTED" and rx["fills_consumed"] < rx["fills_authorized"]:
            rx["status"] = "ACTIVE"
        touch(rx)
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/ship")
def ship_order(oid):
    require_roles("FulfillmentAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["fulfillment_status"] != "PICKED":
        raise ApiError("ERR_ORDER_NOT_SHIPPABLE", "fulfillment_status != PICKED on ship", 409)
    if order["billing_status"] != "ADJUDICATED":
        raise ApiError("ERR_ORDER_NOT_ADJUDICATED", "billing_status != ADJUDICATED on ship", 409)
    for u in _units_for_order(order):
        if u["status"] == "ALLOCATED":
            u["status"] = "SHIPPED"
            touch(u)
    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/deliver")
def deliver_order(oid):
    require_roles("FulfillmentAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_ORDER_NOT_DELIVERABLE", "fulfillment_status != SHIPPED on deliver", 409)
    for u in _units_for_order(order):
        if u["status"] == "SHIPPED":
            u["status"] = "IN_HAND"
            touch(u)
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return success_object(serialize(order, "sensor_order"))


@app.post("/cgm/sensor-orders/<oid>/cancel")
def cancel_order(oid):
    require_roles("FulfillmentAgent")
    order = get_or_404(db.sensor_orders, oid, "sensor_order")
    if order["fulfillment_status"] != "PENDING_PICK":
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", "fulfillment_status != PENDING_PICK on cancel", 409)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success_object(serialize(order, "sensor_order"))


# ---------------------------------------------------------------------------
# Device Bindings
# ---------------------------------------------------------------------------

@app.post("/cgm/patients/<pid>/device-bindings")
def create_device_binding(pid):
    require_roles("Patient")
    get_or_404(db.patients, pid, "patient")
    body = get_body()
    sensor_unit_id = req_field(body, "sensor_unit_id", (str,))
    channel = req_enum(body, "channel", BINDING_CHANNELS)
    unit = get_or_404(db.sensor_units, sensor_unit_id, "sensor_unit")
    product = product_for_unit(unit)
    now = logical_now_dt()
    expires_at = now + timedelta(days=product["wear_days"])

    # Is this unit a replacement dispatched under an APPROVED warranty claim?
    is_replacement = False
    for s in db.replacement_shipments.values():
        if s.get("replacement_sensor_unit_id") == unit["id"]:
            claim = db.warranty_claims.get(s["warranty_claim_id"])
            if claim is not None and claim["status"] == "APPROVED":
                is_replacement = True
                break

    # p13: one-active-sensor rule (half-open interval overlap per channel)
    overlapping = []
    for b in db.device_bindings.values():
        if b["patient_id"] != pid or b["channel"] != channel or b["status"] != "ACTIVE":
            continue
        # overlap iff now < existing.expires_at (existing.activated_at <= now always)
        if now < b["_expires_at_dt"]:
            overlapping.append(b)
    if overlapping and not is_replacement:
        raise ApiError("ERR_ACTIVE_BINDING_EXISTS", "Another ACTIVE DeviceBinding overlaps on the same channel", 409)

    # p14: generation compatibility vs most recent prior binding
    prior_bindings = sort_by_created_at([b for b in db.device_bindings.values() if b["patient_id"] == pid])
    if prior_bindings:
        prior_unit = db.sensor_units.get(prior_bindings[-1]["sensor_unit_id"])
        prior_product = product_for_unit(prior_unit) if prior_unit else None
        if prior_product is not None:
            prior_gen = prior_product["generation"]
            new_gen = product["generation"]
            if new_gen != prior_gen and prior_gen not in product["compatible_prior_generations"]:
                raise ApiError("ERR_GENERATION_INCOMPATIBLE",
                               "New binding's product generation incompatible with patient's prior binding", 422)

    # p20: channel permitted by product.reader_channel
    rc = product["reader_channel"]
    if rc != "HYBRID" and rc != channel:
        raise ApiError("ERR_CHANNEL_NOT_SUPPORTED", "Channel not permitted by product.reader_channel", 422)

    # p21: unit activatable
    if unit["status"] != "IN_HAND" or unit.get("patient_id") != pid:
        raise ApiError("ERR_UNIT_NOT_ACTIVATABLE",
                       "SensorUnit.status != IN_HAND or patient_id mismatch on binding create", 409)

    # Supersede cascade for replacement activations
    for b in overlapping:
        b["status"] = "SUPERSEDED"
        touch(b)
        old_unit = db.sensor_units.get(b["sensor_unit_id"])
        if old_unit is not None and old_unit["status"] == "ACTIVE":
            old_unit["status"] = "REPLACED"
            touch(old_unit)

    today = date_to_str(logical_today())
    unit["status"] = "ACTIVE"
    unit["activated_on"] = today
    touch(unit)

    rec = stamp_new({
        "patient_id": pid,
        "sensor_unit_id": unit["id"],
        "channel": channel,
        "activated_at": fmt_dt(now),
        "expires_at": fmt_dt(expires_at),
        "status": "ACTIVE",
    })
    rec["_expires_at_dt"] = expires_at
    db.device_bindings[rec["id"]] = rec
    return success_object(serialize(rec, "device_binding"), 201)


@app.get("/cgm/patients/<pid>/device-bindings")
def list_patient_bindings(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(b, "device_binding") for b in db.device_bindings.values() if b["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/device-bindings/<bid>")
def get_device_binding(bid):
    require_roles("Any")
    rec = get_or_404(db.device_bindings, bid, "device_binding")
    return success_object(serialize(rec, "device_binding"))


# ---------------------------------------------------------------------------
# Warranty Claims
# ---------------------------------------------------------------------------

@app.post("/cgm/sensor-units/<uid>/warranty-claims")
def create_warranty_claim(uid):
    require_roles("Patient")
    unit = get_or_404(db.sensor_units, uid, "sensor_unit")
    body = get_body()
    reported_failure_day_index = req_field(body, "reported_failure_day_index", (int,))
    failure_category = req_enum(body, "failure_category", FAILURE_CATEGORIES)
    device_data_attached = req_field(body, "device_data_attached", (bool,))
    if reported_failure_day_index < 0:
        raise err_invalid_request("reported_failure_day_index must be >= 0")
    rec = stamp_new({
        "sensor_unit_id": uid,
        "patient_id": unit.get("patient_id"),
        "reported_failure_day_index": reported_failure_day_index,
        "failure_category": failure_category,
        "device_data_attached": device_data_attached,
        "review_notes": "",
        "replacement_credit_cents": 0,
        "status": "SUBMITTED",
    })
    db.warranty_claims[rec["id"]] = rec
    return success_object(serialize(rec, "warranty_claim"), 201)


@app.get("/cgm/sensor-units/<uid>/warranty-claims")
def list_unit_claims(uid):
    require_roles("Any")
    get_or_404(db.sensor_units, uid, "sensor_unit")
    items = [serialize(c, "warranty_claim") for c in db.warranty_claims.values() if c["sensor_unit_id"] == uid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/warranty-claims/<cid>")
def get_warranty_claim(cid):
    require_roles("Any")
    rec = get_or_404(db.warranty_claims, cid, "warranty_claim")
    return success_object(serialize(rec, "warranty_claim"))


@app.post("/cgm/warranty-claims/<cid>/begin-review")
def begin_review_claim(cid):
    require_roles("WarrantyReviewer")
    claim = get_or_404(db.warranty_claims, cid, "warranty_claim")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", "WarrantyClaim.status != SUBMITTED on begin-review", 409)
    if not claim["device_data_attached"]:
        raise ApiError("ERR_DEVICE_DATA_REQUIRED", "device_data_attached == false on begin-review", 422)
    claim["status"] = "DATA_REVIEW"
    touch(claim)
    return success_object(serialize(claim, "warranty_claim"))


@app.post("/cgm/warranty-claims/<cid>/request-more-info")
def request_more_info_claim(cid):
    require_roles("WarrantyReviewer")
    claim = get_or_404(db.warranty_claims, cid, "warranty_claim")
    if claim["status"] != "DATA_REVIEW":
        raise err_invalid_state("claim must be in DATA_REVIEW to request more info")
    claim["status"] = "MORE_INFO_REQUESTED"
    touch(claim)
    return success_object(serialize(claim, "warranty_claim"))


@app.post("/cgm/warranty-claims/<cid>/resubmit-data")
def resubmit_data_claim(cid):
    ctx = require_roles("Patient")
    claim = get_or_404(db.warranty_claims, cid, "warranty_claim")
    if claim["status"] != "MORE_INFO_REQUESTED":
        raise err_invalid_state("claim must be in MORE_INFO_REQUESTED to resubmit data")
    if ctx.user_id != claim["patient_id"]:
        raise ApiError("ERR_UNIT_OWNER_MISMATCH", "X-User-ID != claim.patient_id", 403)
    body = get_body()
    device_data_attached = req_field(body, "device_data_attached", (bool,))
    claim["device_data_attached"] = device_data_attached
    claim["status"] = "DATA_REVIEW"
    touch(claim)
    return success_object(serialize(claim, "warranty_claim"))


@app.post("/cgm/warranty-claims/<cid>/decide")
def decide_warranty_claim(cid):
    require_roles("WarrantyReviewer")
    claim = get_or_404(db.warranty_claims, cid, "warranty_claim")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    review_notes = opt_field(body, "review_notes", (str,), default="")
    if claim["status"] != "DATA_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_IN_REVIEW", "WarrantyClaim.status != DATA_REVIEW on decide", 409)
    unit = db.sensor_units[claim["sensor_unit_id"]]
    product = product_for_unit(unit)
    if decision == "APPROVED":
        if not claim["device_data_attached"]:
            raise ApiError("ERR_DEVICE_DATA_REQUIRED", "device_data_attached == false on decide", 422)
        if not review_notes or len(review_notes) < 10:
            raise err_invalid_request("review_notes must be at least 10 characters on decision")
        if claim["reported_failure_day_index"] >= product["wear_days"]:
            raise ApiError("ERR_NOT_EARLY_FAILURE",
                           "reported_failure_day_index >= product.wear_days on APPROVED decide", 422)
        # warranty_credit_rule
        if product["generation"] >= PRO_RATA_MIN_GENERATION:
            wear_used = claim["reported_failure_day_index"] + 1
            unused_days = max(0, product["wear_days"] - wear_used)
            credit = (product["list_price_cents"] * unused_days) // product["wear_days"]
        else:
            credit = product["list_price_cents"]
        claim["replacement_credit_cents"] = credit
        claim["review_notes"] = review_notes
        claim["status"] = "APPROVED"
        touch(claim)
        # Allocate replacement unit from same-product lot with posture NORMAL
        lot_by_id = db.sensor_lots
        candidates = []
        for u in db.sensor_units.values():
            if u["status"] != "IN_STOCK":
                continue
            lot = lot_by_id.get(u["lot_id"])
            if lot is None or lot["product_id"] != product["id"]:
                continue
            if lot["complaint_posture"] != "NORMAL":
                continue
            candidates.append((lot["manufacture_date"], u["serial_number"], u))
        if not candidates:
            raise ApiError("ERR_INSUFFICIENT_LOT_STOCK",
                           "No IN_STOCK replacement unit available in a NORMAL-posture lot for the product", 409)
        candidates.sort(key=lambda t: (t[0], t[1]))
        replacement_unit = candidates[0][2]
        replacement_unit["status"] = "ALLOCATED"
        replacement_unit["patient_id"] = claim["patient_id"]
        touch(replacement_unit)
        shipment = stamp_new({
            "warranty_claim_id": claim["id"],
            "replacement_sensor_unit_id": replacement_unit["id"],
            "shipped_on": None,
            "status": "PENDING_SHIP",
        })
        db.replacement_shipments[shipment["id"]] = shipment
    else:
        claim["review_notes"] = review_notes
        claim["status"] = "DENIED"
        touch(claim)
    return success_object(serialize(claim, "warranty_claim"))


@app.post("/cgm/warranty-claims/<cid>/close")
def close_warranty_claim(cid):
    require_roles("WarrantyReviewer")
    claim = get_or_404(db.warranty_claims, cid, "warranty_claim")
    if claim["status"] != "DENIED":
        raise err_invalid_state("claim must be DENIED to close")
    claim["status"] = "CLOSED"
    touch(claim)
    return success_object(serialize(claim, "warranty_claim"))


# ---------------------------------------------------------------------------
# Replacement Shipments
# ---------------------------------------------------------------------------

@app.get("/cgm/warranty-claims/<cid>/replacement-shipments")
def list_claim_shipments(cid):
    require_roles("Any")
    get_or_404(db.warranty_claims, cid, "warranty_claim")
    items = [serialize(s, "replacement_shipment") for s in db.replacement_shipments.values()
             if s["warranty_claim_id"] == cid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/replacement-shipments/<sid>")
def get_replacement_shipment(sid):
    require_roles("Any")
    rec = get_or_404(db.replacement_shipments, sid, "replacement_shipment")
    return success_object(serialize(rec, "replacement_shipment"))


@app.post("/cgm/replacement-shipments/<sid>/ship")
def ship_replacement(sid):
    require_roles("FulfillmentAgent")
    shipment = get_or_404(db.replacement_shipments, sid, "replacement_shipment")
    if shipment["status"] != "PENDING_SHIP":
        raise err_invalid_state("shipment must be PENDING_SHIP to ship")
    unit = db.sensor_units.get(shipment["replacement_sensor_unit_id"])
    if unit is not None and unit["status"] == "ALLOCATED":
        unit["status"] = "SHIPPED"
        touch(unit)
    shipment["status"] = "SHIPPED"
    shipment["shipped_on"] = date_to_str(logical_today())
    touch(shipment)
    return success_object(serialize(shipment, "replacement_shipment"))


@app.post("/cgm/replacement-shipments/<sid>/deliver")
def deliver_replacement(sid):
    require_roles("FulfillmentAgent")
    shipment = get_or_404(db.replacement_shipments, sid, "replacement_shipment")
    if shipment["status"] != "SHIPPED":
        raise err_invalid_state("shipment must be SHIPPED to deliver")
    unit = db.sensor_units.get(shipment["replacement_sensor_unit_id"])
    if unit is not None and unit["status"] == "SHIPPED":
        unit["status"] = "IN_HAND"
        touch(unit)
    claim = db.warranty_claims.get(shipment["warranty_claim_id"])
    if claim is not None:
        original = db.sensor_units.get(claim["sensor_unit_id"])
        if original is not None and original["status"] == "FAILED_EARLY":
            original["status"] = "REPLACED"
            touch(original)
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return success_object(serialize(shipment, "replacement_shipment"))


@app.post("/cgm/replacement-shipments/<sid>/cancel")
def cancel_replacement(sid):
    require_roles("WarrantyReviewer")
    shipment = get_or_404(db.replacement_shipments, sid, "replacement_shipment")
    if shipment["status"] != "PENDING_SHIP":
        raise err_invalid_state("shipment must be PENDING_SHIP to cancel")
    unit = db.sensor_units.get(shipment["replacement_sensor_unit_id"])
    if unit is not None and unit["status"] == "ALLOCATED":
        unit["status"] = "IN_STOCK"
        unit["patient_id"] = None
        touch(unit)
    claim = db.warranty_claims.get(shipment["warranty_claim_id"])
    if claim is not None:
        claim["status"] = "CLOSED"
        touch(claim)
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return success_object(serialize(shipment, "replacement_shipment"))


# ---------------------------------------------------------------------------
# Support Enrollments
# ---------------------------------------------------------------------------

@app.post("/cgm/patients/<pid>/support-enrollments")
def create_support_enrollment(pid):
    require_roles("PatientSupportAgent")
    patient = get_or_404(db.patients, pid, "patient")
    body = get_body()
    payer_id = req_field(body, "payer_id", (str,))
    card_max_per_fill_cents = req_field(body, "card_max_per_fill_cents", (int,))
    payer = get_or_404(db.payers, payer_id, "payer")
    # p19: state-law exclusions + route eligibility
    if patient["state_code"] in SAVINGS_CARD_EXCLUDED_STATES or payer["benefit_route"] != "PHARMACY":
        raise ApiError("ERR_SAVINGS_CARD_NOT_PERMITTED",
                       "Patient in excluded state OR payer route is DME on support-enrollment creation", 422)
    # p22: program cap
    if card_max_per_fill_cents < 0 or card_max_per_fill_cents > CARD_PROGRAM_CAP_CENTS:
        raise ApiError("ERR_INVALID_CARD_CAP", "card_max_per_fill_cents out of range", 422)
    rec = stamp_new({
        "patient_id": pid,
        "payer_id": payer_id,
        "savings_card_number": "SC-" + new_id().replace("-", "")[:16].upper(),
        "card_max_per_fill_cents": card_max_per_fill_cents,
        "card_remaining_cents": card_max_per_fill_cents * CARD_ANNUAL_FILL_MULTIPLIER,
        "status": "ENROLLED",
    })
    db.support_enrollments[rec["id"]] = rec
    return success_object(serialize(rec, "support_enrollment"), 201)


@app.get("/cgm/patients/<pid>/support-enrollments")
def list_patient_enrollments(pid):
    require_roles("Any")
    get_or_404(db.patients, pid, "patient")
    items = [serialize(e, "support_enrollment") for e in db.support_enrollments.values() if e["patient_id"] == pid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/support-enrollments/<eid>")
def get_support_enrollment(eid):
    require_roles("Any")
    rec = get_or_404(db.support_enrollments, eid, "support_enrollment")
    return success_object(serialize(rec, "support_enrollment"))


@app.post("/cgm/support-enrollments/<eid>/suspend")
def suspend_enrollment(eid):
    require_roles("PatientSupportAgent")
    enr = get_or_404(db.support_enrollments, eid, "support_enrollment")
    if enr["status"] != "ENROLLED":
        raise err_invalid_state("enrollment must be ENROLLED to suspend")
    enr["status"] = "SUSPENDED"
    touch(enr)
    return success_object(serialize(enr, "support_enrollment"))


@app.post("/cgm/support-enrollments/<eid>/reinstate")
def reinstate_enrollment(eid):
    require_roles("PatientSupportAgent")
    enr = get_or_404(db.support_enrollments, eid, "support_enrollment")
    if enr["status"] != "SUSPENDED":
        raise err_invalid_state("enrollment must be SUSPENDED to reinstate")
    enr["status"] = "ENROLLED"
    touch(enr)
    return success_object(serialize(enr, "support_enrollment"))


@app.post("/cgm/support-enrollments/<eid>/terminate")
def terminate_enrollment(eid):
    require_roles("PatientSupportAgent")
    enr = get_or_404(db.support_enrollments, eid, "support_enrollment")
    if enr["status"] not in ("ENROLLED", "SUSPENDED"):
        raise err_invalid_state("enrollment must be ENROLLED or SUSPENDED to terminate")
    enr["status"] = "TERMINATED"
    touch(enr)
    return success_object(serialize(enr, "support_enrollment"))


# ---------------------------------------------------------------------------
# Adverse Event Reports
# ---------------------------------------------------------------------------

@app.post("/cgm/sensor-lots/<lid>/adverse-event-reports")
def create_aer(lid):
    require_roles("Patient", "QualityEngineer")
    get_or_404(db.sensor_lots, lid, "sensor_lot")
    body = get_body()
    sensor_unit_id = req_field(body, "sensor_unit_id", (str,))
    patient_id = req_field(body, "patient_id", (str,))
    get_or_404(db.sensor_units, sensor_unit_id, "sensor_unit")
    get_or_404(db.patients, patient_id, "patient")
    severity = req_enum(body, "severity", SEVERITIES)
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    rec = stamp_new({
        "lot_id": lid,
        "sensor_unit_id": sensor_unit_id,
        "patient_id": patient_id,
        "severity": severity,
        "event_type": event_type,
        "reported_on": date_to_str(logical_today()),
        "status": "OPEN",
    })
    db.adverse_event_reports[rec["id"]] = rec
    return success_object(serialize(rec, "aer"), 201)


@app.get("/cgm/sensor-lots/<lid>/adverse-event-reports")
def list_lot_aers(lid):
    require_roles("Any")
    get_or_404(db.sensor_lots, lid, "sensor_lot")
    items = [serialize(a, "aer") for a in db.adverse_event_reports.values() if a["lot_id"] == lid]
    return paginate(sort_by_created_at(items))


@app.get("/cgm/adverse-event-reports/<aid>")
def get_aer(aid):
    require_roles("Any")
    rec = get_or_404(db.adverse_event_reports, aid, "aer")
    return success_object(serialize(rec, "aer"))


@app.post("/cgm/adverse-event-reports/<aid>/investigate")
def investigate_aer(aid):
    require_roles("QualityEngineer")
    aer = get_or_404(db.adverse_event_reports, aid, "aer")
    if aer["status"] != "OPEN":
        raise err_invalid_state("report must be OPEN to investigate")
    aer["status"] = "INVESTIGATING"
    touch(aer)
    return success_object(serialize(aer, "aer"))


@app.post("/cgm/adverse-event-reports/<aid>/close")
def close_aer(aid):
    require_roles("QualityEngineer")
    aer = get_or_404(db.adverse_event_reports, aid, "aer")
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUBSTANTIATED", "UNSUBSTANTIATED"})
    if aer["status"] != "INVESTIGATING":
        raise err_invalid_state("report must be INVESTIGATING to close")
    if outcome == "SUBSTANTIATED":
        aer["status"] = "CLOSED_SUBSTANTIATED"
        lot = db.sensor_lots.get(aer["lot_id"])
        if lot is not None:
            lot["complaint_count"] += 1
            touch(lot)
            recompute_lot_posture(lot)
    else:
        aer["status"] = "CLOSED_UNSUBSTANTIATED"
    touch(aer)
    return success_object(serialize(aer, "aer"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
