"""Dispense encounters: documentation, supervision, commitment, fitting, delivery."""
from datetime import timedelta

from flask import Blueprint, request

import guards
from calc import (covered_units_for, patient_responsibility, refresh_shelf,
                 refresh_supplier_rollup)
from common import (ALL_ROLES, authorize, body_json, bool_arg, ceil_minutes, dec,
                    enum_arg, fail, need_enum, need_instant, need_int,
                    need_object, need_str, now, opt_date, opt_enum, paginate,
                    respond_list, respond_object, today)
from store import (CLINICAL_STATUSES, FINANCIAL_STATUSES, FIT_OUTCOMES,
                   SIGNATURE_ROLES, SUPERVISION_LEVELS, db,
                   effective_verification, encounter_fab_order,
                   encounter_fitting_records, encounter_json,
                   encounter_prior_auth, encounter_verifications, fab_order_json,
                   find_par_level,
                   fitting_record_json, greatest_notice, insert, lookup,
                   sort_created, stamp, touch)

bp = Blueprint("encounters", __name__)

ENCOUNTER_LIST_ROLES = ["PracticeAdmin", "ComplianceOfficer", "InsuranceCoordinator",
                        "OrthoPhysician", "DmeFitter"]
FITTING_READ_ROLES = ["PracticeAdmin", "ComplianceOfficer", "DmeFitter"]
FITTING_BUFFER_SECONDS = 15 * 60


def new_encounter_row(clinic_id, patient_id, product_id, ordering_physician_id,
                      quantity, service_date):
    return stamp({
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "product_id": product_id,
        "ordering_physician_id": ordering_physician_id,
        "mn_physician_id": None,
        "ioas_attesting_physician_id": None,
        "fitter_id": None,
        "refit_of_encounter_id": None,
        "quantity": quantity,
        "service_date": service_date,
        "clinical_status": "DRAFT",
        "financial_status": "UNVERIFIED",
        "compliance_hold": False,
        "hold_reason": None,
        "mn_diagnosis_code": None,
        "mn_functional_deficit": None,
        "mn_expected_duration_months": None,
        "mn_signed_at": None,
        "ioas_attested_at": None,
        "ioas_supervision_level_observed": None,
        "delivered_at": None,
        "delivery_signature_role": None,
        "covered_units": 0,
        "patient_responsibility_cents": 0,
        "billable_amount_cents": 0,
        "responsibility_variant": None,
    })


def encounter_product(encounter):
    return db["products"].get(encounter["product_id"])


def encounter_clinic(encounter):
    return db["clinics"].get(encounter["clinic_id"])


def product_supplier(product):
    return db["suppliers"].get(product["supplier_id"]) if product else None


def release_reservation(encounter, par_level):
    """Compensating shelf move: reserved_qty falls, posture is untouched."""
    if par_level is None:
        return
    par_level["reserved_qty"] -= encounter["quantity"]
    if par_level["reserved_qty"] < 0:
        par_level["reserved_qty"] = 0
    touch(par_level)


@bp.post("/dme/encounters")
def create_encounter():
    authorize(["PracticeAdmin", "OrthoPhysician"])
    body = body_json()
    clinic_id = need_str(body, "clinic_id")
    patient_id = need_str(body, "patient_id")
    product_id = need_str(body, "product_id")
    ordering_physician_id = need_str(body, "ordering_physician_id")
    quantity = need_int(body, "quantity", 1, 20)
    service_date = opt_date(body, "service_date")
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    product = lookup("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    patient = lookup("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    physician = lookup("physicians", ordering_physician_id, "ERR_PHYSICIAN_NOT_FOUND")
    if patient["clinic_id"] != clinic["id"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if physician["clinic_id"] != clinic["id"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if physician["specialty"] != product["specialty"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if service_date is None:
        service_date = today()
    row = new_encounter_row(clinic["id"], patient["id"], product["id"],
                            physician["id"], quantity, service_date)
    insert("encounters", row)
    return respond_object(encounter_json(row), 201)


@bp.get("/dme/encounters/<encounter_id>")
def get_encounter(encounter_id):
    authorize(ALL_ROLES)
    row = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    return respond_object(encounter_json(row), 200)


@bp.get("/dme/encounters")
def list_encounters():
    authorize(ENCOUNTER_LIST_ROLES)
    rows = list(db["encounters"].values())
    for field in ("clinic_id", "patient_id", "product_id", "ordering_physician_id",
                  "mn_physician_id", "ioas_attesting_physician_id", "fitter_id",
                  "refit_of_encounter_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    clinical_status = enum_arg("clinical_status", CLINICAL_STATUSES)
    if clinical_status is not None:
        rows = [r for r in rows if r["clinical_status"] == clinical_status]
    financial_status = enum_arg("financial_status", FINANCIAL_STATUSES)
    if financial_status is not None:
        rows = [r for r in rows if r["financial_status"] == financial_status]
    compliance_hold = bool_arg("compliance_hold")
    if compliance_hold is not None:
        rows = [r for r in rows if r["compliance_hold"] == compliance_hold]
    page, pagination = paginate(sort_created(rows))
    return respond_list([encounter_json(r) for r in page], pagination, 200)


@bp.post("/dme/encounters/<encounter_id>/medical-necessity-note")
def sign_medical_necessity_note(encounter_id):
    user_id, _ = authorize(["OrthoPhysician"])
    body = body_json()
    mn_diagnosis_code = need_str(body, "mn_diagnosis_code", 1)
    mn_functional_deficit = need_str(body, "mn_functional_deficit", 1)
    mn_expected_duration_months = need_int(body, "mn_expected_duration_months", 0)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    if encounter["clinical_status"] != "DRAFT":
        fail("ERR_INVALID_CLINICAL_STATE")
    if user_id != encounter["ordering_physician_id"]:
        fail("ERR_INVALID_CLINICAL_STATE")
    clinic = encounter_clinic(encounter)
    guards.guard_clinic_accreditation(clinic)
    guards.guard_stark(encounter)
    encounter["mn_diagnosis_code"] = mn_diagnosis_code
    encounter["mn_functional_deficit"] = mn_functional_deficit
    encounter["mn_expected_duration_months"] = mn_expected_duration_months
    encounter["mn_physician_id"] = user_id
    encounter["mn_signed_at"] = now()
    encounter["clinical_status"] = "DOCUMENTED"
    touch(encounter)
    return respond_object(encounter_json(encounter), 201)


IOAS_WINDOW = ("DOCUMENTED", "AWAITING_DEVICE", "RESERVED", "FITTED")


@bp.post("/dme/encounters/<encounter_id>/ioas-attestation")
def attest_ioas(encounter_id):
    user_id, _ = authorize(["OrthoPhysician"])
    body = body_json()
    observed = need_enum(body, "ioas_supervision_level_observed", SUPERVISION_LEVELS)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    if encounter["clinical_status"] not in IOAS_WINDOW:
        fail("ERR_INVALID_CLINICAL_STATE")
    if user_id == encounter["ordering_physician_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    guards.guard_stark(encounter, attesting_physician_id=user_id)
    encounter["ioas_attesting_physician_id"] = user_id
    encounter["ioas_attested_at"] = now()
    encounter["ioas_supervision_level_observed"] = observed
    touch(encounter)
    return respond_object(encounter_json(encounter), 201)


@bp.post("/dme/encounters/<encounter_id>/reservations")
def create_reservation(encounter_id):
    authorize(["DmeFitter"])
    body = body_json()
    expected_version = need_int(body, "expected_par_level_version", 0)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = encounter_product(encounter)
    clinic = encounter_clinic(encounter)
    par_level = find_par_level(encounter["clinic_id"], encounter["product_id"])
    # A shelf is required only for devices that pass through one at all.
    if product["category"] != "CUSTOM_FABRICATED" and par_level is None:
        fail("ERR_PAR_LEVEL_NOT_FOUND")
    if encounter["clinical_status"] != "DOCUMENTED":
        fail("ERR_INVALID_CLINICAL_STATE")
    if par_level is not None and expected_version != par_level["version"]:
        fail("ERR_STALE_PAR_LEVEL_VERSION")
    guards.guard_clinic_accreditation(clinic)
    supplier = product_supplier(product)
    guards.guard_supplier_standards(supplier)
    guards.guard_supplier_quality(supplier)
    if product["category"] not in ("OFF_SHELF_PREFAB", "CUSTOM_FITTED_PREFAB"):
        fail("ERR_PRODUCT_CATEGORY_MISMATCH")
    guards.guard_clinic_dispensing(clinic, par_level)
    available = par_level["on_hand_qty"] - par_level["reserved_qty"]
    if available < encounter["quantity"]:
        fail("ERR_INSUFFICIENT_PAR_STOCK")
    par_level["reserved_qty"] += encounter["quantity"]
    touch(par_level)
    # stock_posture is deliberately untouched: on_hand_qty did not move.
    encounter["clinical_status"] = "RESERVED"
    touch(encounter)
    return respond_object(encounter_json(encounter), 201)


@bp.post("/dme/encounters/<encounter_id>/custom-fab-orders")
def create_custom_fab_order(encounter_id):
    authorize(["DmeFitter"])
    body = body_json()
    supplier_id = need_str(body, "supplier_id")
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    supplier = lookup("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    product = encounter_product(encounter)
    clinic = encounter_clinic(encounter)
    if encounter["clinical_status"] != "DOCUMENTED":
        fail("ERR_INVALID_CLINICAL_STATE")
    guards.guard_supplier_standards(supplier)
    guards.guard_supplier_quality(supplier)
    if not supplier["custom_fab_capable"]:
        fail("ERR_CUSTOM_FAB_NOT_SUPPORTED")
    if product["category"] != "CUSTOM_FABRICATED":
        fail("ERR_PRODUCT_CATEGORY_MISMATCH")
    guards.guard_clinic_dispensing(clinic, None)
    submitted_at = now()
    promised = supplier["promised_turnaround_days"]
    order = stamp({
        "encounter_id": encounter["id"],
        "supplier_id": supplier["id"],
        "status": "SUBMITTED",
        "submitted_at": submitted_at,
        "promised_turnaround_days_snapshot": promised,
        "promised_delivery_on": submitted_at.date() + timedelta(days=promised),
        "first_delivered_at": None,
        "accepted_at": None,
        "adjustment_rounds": 0,
        "first_delivery_days": None,
        "total_elapsed_days": None,
        "projected_turnaround_score": None,
        "final_turnaround_score": None,
    })
    insert("fab_orders", order)
    encounter["clinical_status"] = "AWAITING_DEVICE"
    touch(encounter)
    return respond_object(fab_order_json(order), 201)


FITTING_FROM_STATES = {
    "ACCEPTABLE": ("RESERVED", "AWAITING_DEVICE"),
    "ADJUST_NEEDED": ("RESERVED",),
    "REJECTED": ("RESERVED",),
}


@bp.post("/dme/encounters/<encounter_id>/fitting-records")
def create_fitting_record(encounter_id):
    # Carve-out: an unknown DmeFitter actor here is ERR_FITTER_NOT_FOUND (11),
    # never ERR_ACTOR_NOT_FOUND (4).
    user_id, _ = authorize(["DmeFitter"], actor_check=False)
    body = body_json()
    start_at = need_instant(body, "fitting_start_at")
    end_at = need_instant(body, "fitting_end_at")
    measurement_set = need_object(body, "measurement_set")
    fit_outcome = need_enum(body, "fit_outcome", FIT_OUTCOMES)
    fitter = lookup("fitters", user_id, "ERR_FITTER_NOT_FOUND")
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = encounter_product(encounter)
    if fitter["clinic_id"] != encounter["clinic_id"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if encounter["clinical_status"] not in FITTING_FROM_STATES[fit_outcome]:
        fail("ERR_INVALID_CLINICAL_STATE")
    if encounter["clinical_status"] == "AWAITING_DEVICE":
        order = encounter_fab_order(encounter["id"])
        if order is None or order["status"] != "ACCEPTED":
            fail("ERR_INVALID_FAB_ORDER_STATE")
    guards.guard_compliance_hold(encounter)
    guards.guard_fitter_credential(fitter)
    guards.guard_fitter_privilege(fitter, product)
    for existing in db["fitting_records"].values():
        if existing["fitter_id"] != fitter["id"]:
            continue
        s0 = existing["fitting_start_at"]
        e0 = existing["fitting_end_at"]
        if ((start_at - e0).total_seconds() <= FITTING_BUFFER_SECONDS
                and (end_at - s0).total_seconds() >= -FITTING_BUFFER_SECONDS):
            fail("ERR_FITTING_SLOT_CONFLICT")
    if end_at <= start_at:
        fail("ERR_INVALID_INTERVAL")
    clock_date = today()
    if start_at.date() > clock_date or end_at.date() > clock_date:
        fail("ERR_INVALID_INTERVAL")

    minutes = ceil_minutes(start_at, end_at)
    record = stamp({
        "encounter_id": encounter["id"],
        "fitter_id": fitter["id"],
        "fitting_start_at": start_at,
        "fitting_end_at": end_at,
        "fitting_minutes": minutes,
        "measurement_set": measurement_set,
        "fit_outcome": fit_outcome,
        "delivery_signature_role": None,
        "delivery_signed_at": None,
    })
    insert("fitting_records", record)
    fitter["fitting_minutes_booked"] += minutes
    touch(fitter)
    if fit_outcome == "ACCEPTABLE":
        encounter["fitter_id"] = fitter["id"]
        encounter["clinical_status"] = "FITTED"
    elif fit_outcome == "REJECTED":
        par_level = find_par_level(encounter["clinic_id"], encounter["product_id"])
        release_reservation(encounter, par_level)
        encounter["clinical_status"] = "DOCUMENTED"
    touch(encounter)
    return respond_object(fitting_record_json(record), 201)


@bp.get("/dme/fitting-records/<record_id>")
def get_fitting_record(record_id):
    authorize(FITTING_READ_ROLES)
    row = lookup("fitting_records", record_id, "ERR_FITTING_RECORD_NOT_FOUND")
    return respond_object(fitting_record_json(row), 200)


@bp.get("/dme/fitting-records")
def list_fitting_records():
    authorize(FITTING_READ_ROLES)
    rows = list(db["fitting_records"].values())
    for field in ("encounter_id", "fitter_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    fit_outcome = enum_arg("fit_outcome", FIT_OUTCOMES)
    if fit_outcome is not None:
        rows = [r for r in rows if r["fit_outcome"] == fit_outcome]
    page, pagination = paginate(sort_created(rows))
    return respond_list([fitting_record_json(r) for r in page], pagination, 200)


DISPENSABLE_FINANCIAL = ("VERIFIED", "AUTH_APPROVED", "SELF_PAY")


@bp.post("/dme/encounters/<encounter_id>/dispense")
def dispense(encounter_id):
    user_id, _ = authorize(["DmeFitter"])
    body = body_json()
    # Enum membership is a shape concern; absence and REFUSED are priority 39.
    signature_role = opt_enum(body, "delivery_signature_role", SIGNATURE_ROLES)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = encounter_product(encounter)
    clinic = encounter_clinic(encounter)
    fitter = db["fitters"].get(user_id)

    if encounter["clinical_status"] != "FITTED":
        fail("ERR_INVALID_CLINICAL_STATE")
    financial = encounter["financial_status"]
    if financial not in DISPENSABLE_FINANCIAL:
        if financial == "UNVERIFIED" and not encounter_verifications(encounter["id"]):
            fail("ERR_COVERAGE_VERIFICATION_MISSING")
        if financial == "ABN_ISSUED":
            fail("ERR_ABN_NOT_SIGNED")
        fail("ERR_INVALID_FINANCIAL_STATE")

    guards.guard_clinic_accreditation(clinic)
    guards.guard_supplier_standards(product_supplier(product))
    guards.guard_compliance_hold(encounter)
    guards.guard_ioas(encounter, product, clinic)
    guards.guard_stark(encounter,
                       attesting_physician_id=encounter["ioas_attesting_physician_id"])
    guards.guard_medical_necessity(encounter)
    guards.guard_fitter_credential(fitter)
    if signature_role is None or signature_role == "REFUSED":
        fail("ERR_DELIVERY_SIGNATURE_MISSING")

    verifications = encounter_verifications(encounter["id"])
    if not verifications:
        fail("ERR_COVERAGE_VERIFICATION_MISSING")
    verification = verifications[-1]
    clock = now()
    if verification["expires_at"] is not None and verification["expires_at"] < clock:
        fail("ERR_COVERAGE_VERIFICATION_EXPIRED")

    prior_auth = encounter_prior_auth(encounter["id"])
    if product["requires_prior_auth"]:
        if prior_auth is None:
            fail("ERR_PRIOR_AUTH_REQUIRED")
        if prior_auth["status"] == "APPROVED":
            expires_at = prior_auth["expires_at"]
            if expires_at is not None and expires_at < clock:
                prior_auth["status"] = "EXPIRED"
                touch(prior_auth)
                fail("ERR_PRIOR_AUTH_REQUIRED")
        else:
            fail("ERR_PRIOR_AUTH_REQUIRED")

    notice = greatest_notice(encounter["id"])
    covered_units = covered_units_for(encounter, product, verification, prior_auth)
    if encounter["quantity"] > covered_units:
        if (notice is None or notice["status"] != "SIGNED"
                or notice["option_selected"] not in ("OPTION_1", "OPTION_2")):
            fail("ERR_ABN_REQUIRED_FOR_EXCESS_UNITS")

    par_level = find_par_level(encounter["clinic_id"], encounter["product_id"])
    guards.guard_clinic_dispensing(clinic, par_level)

    # ---- commit
    encounter["delivered_at"] = clock
    encounter["delivery_signature_role"] = signature_role
    records = encounter_fitting_records(encounter["id"])
    if records:
        latest = records[-1]
        latest["delivery_signature_role"] = signature_role
        latest["delivery_signed_at"] = clock
        touch(latest)
    money = patient_responsibility(encounter, product, verification, prior_auth, notice)
    encounter["covered_units"] = money["covered_units"]
    encounter["responsibility_variant"] = money["responsibility_variant"]
    encounter["patient_responsibility_cents"] = money["patient_responsibility_cents"]
    encounter["billable_amount_cents"] = money["billable_amount_cents"]
    encounter["clinical_status"] = "DELIVERED"
    encounter["financial_status"] = "BILLED"
    touch(encounter)

    if product["category"] != "CUSTOM_FABRICATED" and par_level is not None:
        par_level["on_hand_qty"] -= encounter["quantity"]
        par_level["reserved_qty"] -= encounter["quantity"]
        if par_level["reserved_qty"] < 0:
            par_level["reserved_qty"] = 0
        touch(par_level)
        refresh_shelf(par_level, exclude_encounter_id=encounter["id"])
    return respond_object(encounter_json(encounter), 201)
