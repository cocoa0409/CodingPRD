"""Demand side: subsidy programs, prescriptions, fills, voids, the allocation
cycle and the logical clock.

Endpoints (11): POST /subsidy-programs, GET /subsidy-programs/{id},
POST/GET /prescriptions, GET /prescriptions/{id},
GET/POST /prescriptions/{id}/dispenses, POST /prescriptions/{id}/cancel,
POST /dispenses/{id}/void, POST /allocation-cycles,
POST /_clock/set_current_utc.
"""

from flask import Blueprint

import domain_dispense
import domain_sweep
import serializers
from auth import (ADMIN, DISPENSING_PHARMACIST, MEDICAL_DIRECTOR, PRESCRIBER,
                  actor_id, guard)
from envelope import ok, page, pagination
from errors import fail, not_found
from listing import apply_filters, sort_by
from store import db, find, insert, set_field
from util import dec, fmt_date, parse_date, parse_instant
from validate import field, json_body, validate

bp = Blueprint("rx", __name__)

PATIENT_TYPES = ("NICU_INPATIENT", "OUTPATIENT")
ACUITIES = ("CRITICAL", "STANDARD")

PROGRAM_READERS = (ADMIN, DISPENSING_PHARMACIST, MEDICAL_DIRECTOR)
RX_READERS = (PRESCRIBER, DISPENSING_PHARMACIST, ADMIN)
RX_DETAIL_READERS = (PRESCRIBER, DISPENSING_PHARMACIST, MEDICAL_DIRECTOR, ADMIN)


def program_or_404(program_id):
    program = find("programs", program_id)
    if program is None:
        not_found("Subsidy program '%s' does not exist." % program_id)
    return program


def prescription_or_404(prescription_id):
    prescription = find("prescriptions", prescription_id)
    if prescription is None:
        not_found("Prescription '%s' does not exist." % prescription_id)
    return prescription


def derive_tier(patient_type, acuity):
    if patient_type == "NICU_INPATIENT":
        return 1 if acuity == "CRITICAL" else 2
    return 3


# --- POST /subsidy-programs ------------------------------------------------
@bp.route("/subsidy-programs", methods=["POST"])
@guard(ADMIN)
def create_program():
    body = json_body()
    values = validate(body, [
        field("program_code", "string", regex=r"^SUB-[0-9]{4}$"),
        field("name", "string", minlen=1, maxlen=120),
        field("coverage_pct", "number", min="0.00", max="1.00"),
        field("annual_cap_cents", "integer", min=1, max=100000000),
    ])
    for existing in db.rows("programs"):
        if existing["program_code"] == values["program_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "program_code '%s' is already in use." % values["program_code"])
    program = insert("programs", {
        "program_code": values["program_code"],
        "name": values["name"],
        "coverage_pct": dec(values["coverage_pct"]),
        "annual_cap_cents": values["annual_cap_cents"],
        "consumed_cents": 0,
        "status": "OPEN",
    })
    return ok(serializers.program_out(program), 201)


# --- GET /subsidy-programs/{id} -------------------------------------------
@bp.route("/subsidy-programs/<program_id>", methods=["GET"])
@guard(*PROGRAM_READERS)
def get_program(program_id):
    return ok(serializers.program_out(program_or_404(program_id)))


# --- POST /prescriptions ---------------------------------------------------
@bp.route("/prescriptions", methods=["POST"])
@guard(PRESCRIBER)
def create_prescription():
    body = json_body()
    raw_program_id = body.get("subsidy_program_id")
    if isinstance(raw_program_id, str):
        program_or_404(raw_program_id)

    values = validate(body, [
        field("prescription_code", "string", regex=r"^RX-[0-9]{4}$"),
        field("subsidy_program_id", "string", required=False, default=None),
        field("patient_reference", "string", minlen=1, maxlen=40),
        field("patient_type", "enum", enum=PATIENT_TYPES),
        field("clinical_acuity", "enum", enum=ACUITIES),
        field("requires_preterm_milk", "boolean", required=False, default=False),
        field("subsidy_required", "boolean", required=False, default=False),
        field("prescribed_ml", "integer", min=50, max=12000),
        field("needed_by_date", "date"),
    ])
    for existing in db.rows("prescriptions"):
        if existing["prescription_code"] == values["prescription_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "prescription_code '%s' is already in use."
                 % values["prescription_code"])

    tier = derive_tier(values["patient_type"], values["clinical_acuity"])
    prescription = insert("prescriptions", {
        "prescription_code": values["prescription_code"],
        "subsidy_program_id": values["subsidy_program_id"],
        "patient_reference": values["patient_reference"],
        "patient_type": values["patient_type"],
        "clinical_acuity": values["clinical_acuity"],
        "priority_tier": tier,
        "requires_preterm_milk": values["requires_preterm_milk"],
        "subsidy_required": values["subsidy_required"],
        "prescribed_ml": values["prescribed_ml"],
        "cumulative_dispensed_ml": 0,
        "remaining_ml": values["prescribed_ml"],
        "needed_by_date": fmt_date(values["needed_by_date"]),
        "waitlist_position": None,
        "status": "QUEUED",
        "prescriber_user_id": actor_id(),
    })
    domain_dispense.renumber_tier(tier)
    return ok(serializers.prescription_out(prescription), 201)


# --- GET /prescriptions ----------------------------------------------------
@bp.route("/prescriptions", methods=["GET"])
@guard(*RX_READERS)
def list_prescriptions():
    limit, offset = pagination()
    rows = apply_filters(db.rows("prescriptions"),
                         [("subsidy_program_id", "subsidy_program_id", "str"),
                          ("status", "status", "str"),
                          ("priority_tier", "priority_tier", "int")])
    sort_by(rows, [(lambda r: r["priority_tier"], False),
                   (lambda r: r["created_at"], False),
                   (lambda r: r["prescription_code"], False)])
    return page(rows, limit, offset, serializers.prescription_out)


# --- GET /prescriptions/{id} ----------------------------------------------
@bp.route("/prescriptions/<prescription_id>", methods=["GET"])
@guard(*RX_DETAIL_READERS)
def get_prescription(prescription_id):
    return ok(serializers.prescription_out(prescription_or_404(prescription_id)))


# --- GET /prescriptions/{id}/dispenses ------------------------------------
@bp.route("/prescriptions/<prescription_id>/dispenses", methods=["GET"])
@guard(*RX_DETAIL_READERS)
def list_prescription_dispenses(prescription_id):
    prescription = prescription_or_404(prescription_id)
    limit, offset = pagination()
    rows = [d for d in db.rows("dispenses")
            if d["prescription_id"] == prescription["id"]]
    rows = apply_filters(rows, [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], False),
                   (lambda r: r["_seq"], False)])
    return page(rows, limit, offset, serializers.dispense_out)


# --- POST /prescriptions/{id}/dispenses -----------------------------------
@bp.route("/prescriptions/<prescription_id>/dispenses", methods=["POST"])
@guard(DISPENSING_PHARMACIST)
def create_dispense(prescription_id):
    prescription = prescription_or_404(prescription_id)
    body = json_body()
    raw_lot_id = body.get("lot_id")
    lot = None
    if isinstance(raw_lot_id, str):
        lot = find("lots", raw_lot_id)
        if lot is None:
            not_found("Milk lot '%s' does not exist." % raw_lot_id)

    values = validate(body, [
        field("lot_id", "string"),
        field("volume_ml", "integer", min=20, max=12000),
        field("expected_lot_version", "integer"),
    ])
    volume_ml = values["volume_ml"]
    today = db.clock_date()

    # PRD 2.10 / 3.9 gauntlet.
    if lot["release_status"] != "RELEASED":
        fail("ERR_LOT_STATE_INVALID",
             "A lot in %s may not be dispensed from." % lot["release_status"])
    if prescription["status"] not in domain_dispense.OPEN_PRESCRIPTION_STATES:
        fail("ERR_PRESCRIPTION_STATE_INVALID",
             "A prescription in %s may not be filled." % prescription["status"])
    if values["expected_lot_version"] != lot["version"]:
        fail("ERR_STALE_VERSION", "The lot is at version %d." % lot["version"])
    if actor_id() == prescription["prescriber_user_id"]:
        fail("ERR_SOD_DISPENSE_CONFLICT",
             "The prescribing operator may not dispense her own order.")
    if prescription["requires_preterm_milk"] and lot["milk_class"] != "PRETERM":
        fail("ERR_LOT_MILK_CLASS_UNSUITABLE",
             "The order requires PRETERM milk; the lot is %s." % lot["milk_class"])
    expiration = parse_date(lot["expiration_date"])
    if expiration is None or expiration < today:
        fail("ERR_LOT_EXPIRED", "The lot expired on %s." % lot["expiration_date"])
    needed_by = parse_date(prescription["needed_by_date"])
    if needed_by is None or needed_by < today:
        fail("ERR_PRESCRIPTION_PAST_NEEDED_BY",
             "The order was needed by %s." % prescription["needed_by_date"])
    if volume_ml > prescription["remaining_ml"]:
        fail("ERR_DISPENSE_EXCEEDS_PRESCRIPTION_REMAINING",
             "Only %d ml remain outstanding on the order."
             % prescription["remaining_ml"])
    if volume_ml > lot["available_ml"]:
        fail("ERR_DISPENSE_EXCEEDS_LOT_AVAILABLE",
             "The lot holds only %d ml." % lot["available_ml"])
    if prescription["priority_tier"] == 3:
        after = domain_dispense.released_available_total() - volume_ml
        if after < domain_dispense.NICU_RESERVE_ML:
            fail("ERR_NICU_RESERVE_PROTECTED",
                 "The bank must retain %d ml for neonatal demand."
                 % domain_dispense.NICU_RESERVE_ML)

    program = domain_dispense.program_of(prescription)
    priced = domain_dispense.price_fill(prescription, program, volume_ml)
    if prescription["subsidy_required"]:
        if program is None or program["status"] != "OPEN":
            fail("ERR_SUBSIDY_PROGRAM_EXHAUSTED",
                 "The order requires a subsidy but no OPEN program is linked.")
        headroom = program["annual_cap_cents"] - program["consumed_cents"]
        if headroom < priced["uncapped_subsidy_cents"]:
            fail("ERR_SUBSIDY_CAP_EXCEEDED",
                 "The programme has only %d cents of headroom." % headroom)

    dispense = domain_dispense.apply_fill(
        prescription, lot, volume_ml, priced, actor_id())
    domain_dispense.renumber_tier(prescription["priority_tier"])
    return ok(serializers.dispense_out(dispense), 201)


# --- POST /prescriptions/{id}/cancel --------------------------------------
@bp.route("/prescriptions/<prescription_id>/cancel", methods=["POST"])
@guard(PRESCRIBER)
def cancel_prescription(prescription_id):
    prescription = prescription_or_404(prescription_id)
    if prescription["status"] not in domain_dispense.OPEN_PRESCRIPTION_STATES:
        fail("ERR_PRESCRIPTION_STATE_INVALID",
             "A prescription in %s may not be cancelled." % prescription["status"])
    set_field(prescription, "status", "CANCELLED")
    set_field(prescription, "waitlist_position", None)
    domain_dispense.renumber_tier(prescription["priority_tier"])
    return ok(serializers.prescription_out(prescription))


# --- POST /dispenses/{id}/void --------------------------------------------
@bp.route("/dispenses/<dispense_id>/void", methods=["POST"])
@guard(DISPENSING_PHARMACIST)
def void_dispense(dispense_id):
    dispense = find("dispenses", dispense_id)
    if dispense is None:
        not_found("Dispense '%s' does not exist." % dispense_id)
    if dispense["status"] != "DISPENSED":
        fail("ERR_DISPENSE_STATE_INVALID",
             "A fill in %s may not be voided." % dispense["status"])
    domain_dispense.void_fill(dispense)
    return ok(serializers.dispense_out(dispense))


# --- POST /allocation-cycles ----------------------------------------------
@bp.route("/allocation-cycles", methods=["POST"])
@guard(DISPENSING_PHARMACIST, ADMIN)
def run_allocation_cycle():
    domain_dispense.run_allocation_cycle(actor_id())
    return ok({})


# --- POST /_clock/set_current_utc -----------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(ADMIN)
def set_clock():
    body = json_body()
    values = validate(body, [
        field("current_utc", "datetime"),
    ])
    requested = values["current_utc"]
    if requested < db.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock may not move backwards.")
    db.clock = requested
    domain_sweep.sweep()
    return ok({})
