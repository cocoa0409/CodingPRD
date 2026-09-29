"""Destruction certification, retention and final settlement (PRD 3.8)."""
from flask import Blueprint

import clock
import constants
import db
import middleware
import response
import validate
from errors import (
    ERR_CERTIFICATE_ALREADY_ISSUED,
    ERR_DELIVERY_REQUIRED_BEFORE_DESTRUCTION,
    ERR_DESTROYED_UNITS_MISMATCH,
    ERR_FACILITY_NOT_PERMITTED,
    ERR_INVALID_CERTIFICATE_STATE,
    ERR_INVALID_FACILITY_STATE,
    ERR_INVALID_KIT_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import accounting, calc, lookup
from validate import Field

bp = Blueprint("certificates", __name__)

CERTIFICATE_READ_ROLES = (
    "ProgramAdmin",
    "DestructionOfficer",
    "SponsorRepresentative",
    "IntakeTechnician",
)

ISSUE_SCHEMA = [Field("destroyed_units", "int", required=True, minimum=0, maximum=100000)]
VOID_SCHEMA = [Field("void_reason", "string", required=True, min_len=1)]


@bp.post("/sharps/shipments/<shipment_id>/destruction-certificates")
@endpoint(["DestructionOfficer"])
def issue_certificate(shipment_id):
    body, _provided = validate.parse_body(ISSUE_SCHEMA)
    shipment = lookup.require("shipment", shipment_id)
    kit = lookup.shipment_kit(shipment)

    # state band
    if kit is None or kit["status"] != "RECEIVED":
        fail(ERR_INVALID_KIT_STATE)

    # safety band
    if shipment["screened_by_user_id"] is not None:
        if middleware.user_id() == shipment["screened_by_user_id"]:
            fail(ERR_SEGREGATION_OF_DUTIES)

    # constraint band, in the pinned order
    facility = lookup.shipment_facility(shipment)
    spec = lookup.shipment_spec(shipment)
    if facility is None:
        fail(ERR_FACILITY_NOT_PERMITTED)
    if spec is not None and spec["hazard_class"] not in facility["accepted_hazard_classes"]:
        fail(ERR_FACILITY_NOT_PERMITTED)
    if facility["status"] != "ACTIVE":
        fail(ERR_INVALID_FACILITY_STATE)
    if shipment["transport_status"] != "DELIVERED" or shipment["conformance_status"] not in (
        "CONFORMING",
        "REMEDIATED",
    ):
        fail(ERR_DELIVERY_REQUIRED_BEFORE_DESTRUCTION)
    for existing in lookup.shipment_certificates(shipment["id"]):
        if existing["status"] == "ISSUED":
            fail(ERR_CERTIFICATE_ALREADY_ISSUED)
    destroyed_units = body["destroyed_units"]
    if destroyed_units != kit["fill_units"]:
        fail(ERR_DESTROYED_UNITS_MISMATCH)

    program = lookup.kit_program(kit)
    sponsor = lookup.program_sponsor(program) if program is not None else None
    patient = lookup.kit_patient(kit)
    patient_rule = lookup.patient_state_rule(patient) if patient is not None else None
    facility_rule = lookup.facility_state_rule(facility)

    destruction_date = clock.now_date()
    committed_before = program["committed_cents"]
    final_cost, rebate_pct = calc.final_settlement(
        kit, shipment, sponsor, program, destroyed_units, committed_before
    )

    certificate = db.create_row(
        "certificates",
        {
            "shipment_id": shipment["id"],
            "kit_id": kit["id"],
            "treatment_facility_id": facility["id"],
            "certificate_number": calc.next_certificate_number(facility),
            "destroyed_units": destroyed_units,
            "destruction_date": clock.fmt_date(destruction_date),
            "retention_until_date": calc.retention_until_date(
                destruction_date, patient_rule, facility_rule
            ),
            "issued_by_user_id": middleware.user_id(),
            "final_kit_cost_cents": final_cost,
            "rebate_pct_applied": float(rebate_pct),
            "voided_at": None,
            "void_reason": None,
            "status": "ISSUED",
        },
    )

    kit["status"] = "DESTROYED"
    db.bump(kit)

    accounting.release_reservation(program, kit, accounting.MEMO_CERTIFICATE_SETTLEMENT)
    accounting.recompute_balances(program)
    accounting.append_entry(
        program,
        accounting.COMMITMENT,
        final_cost,
        kit["id"],
        accounting.MEMO_CERTIFICATE_SETTLEMENT,
    )
    accounting.recompute_program(program)

    facility["certificates_issued_count"] = facility["certificates_issued_count"] + 1
    facility["pending_intake_units"] = facility["pending_intake_units"] - shipment["custody_units"]
    facility["destroyed_units_total"] = facility["destroyed_units_total"] + destroyed_units
    db.touch(facility)
    return response.created(response.view("certificate", certificate))


@bp.post("/sharps/destruction-certificates/<certificate_id>/void")
@endpoint(["DestructionOfficer", "ProgramAdmin"])
def void_certificate(certificate_id):
    body, _provided = validate.parse_body(VOID_SCHEMA)
    certificate = lookup.require("certificate", certificate_id)
    if certificate["status"] != "ISSUED":
        fail(ERR_INVALID_CERTIFICATE_STATE)

    certificate["status"] = "VOIDED"
    certificate["voided_at"] = clock.now_iso()
    certificate["void_reason"] = body["void_reason"]
    db.bump(certificate)

    kit = db.get("kits", certificate["kit_id"])
    program = lookup.kit_program(kit) if kit is not None else None
    if program is not None:
        accounting.append_entry(
            program,
            accounting.COMMITMENT_REVERSAL,
            -certificate["final_kit_cost_cents"],
            certificate["kit_id"],
            accounting.MEMO_CERTIFICATE_VOID,
        )
        accounting.recompute_balances(program)
        accounting.append_entry(
            program,
            accounting.RESERVATION,
            kit["provisional_cost_cents"],
            kit["id"],
            accounting.MEMO_CERTIFICATE_VOID,
        )
    if kit is not None and kit["status"] == "DESTROYED":
        kit["status"] = "RECEIVED"
        db.bump(kit)

    shipment = db.get("shipments", certificate["shipment_id"])
    facility = db.get("treatment_facilities", certificate["treatment_facility_id"])
    if facility is not None:
        if shipment is not None:
            facility["pending_intake_units"] = (
                facility["pending_intake_units"] + shipment["custody_units"]
            )
        facility["destroyed_units_total"] = (
            facility["destroyed_units_total"] - certificate["destroyed_units"]
        )
        db.touch(facility)

    if program is not None:
        accounting.recompute_program(program)
    return response.ok(response.view("certificate", certificate))


@bp.get("/sharps/destruction-certificates/<certificate_id>")
@endpoint(CERTIFICATE_READ_ROLES, mutating=False)
def get_certificate(certificate_id):
    row = lookup.require("certificate", certificate_id)
    return response.ok(response.view("certificate", row))


@bp.get("/sharps/destruction-certificates")
@endpoint(CERTIFICATE_READ_ROLES, mutating=False)
def list_certificates():
    limit, offset = validate.pagination()
    shipment_id = validate.qs_str("shipment_id")
    kit_id = validate.qs_str("kit_id")
    facility_id = validate.qs_str("treatment_facility_id")
    status = validate.qs_enum("status", constants.CERTIFICATE_STATUSES)
    lookup.require_filter("shipment", shipment_id)
    lookup.require_filter("kit", kit_id)
    lookup.require_filter("facility", facility_id)
    rows = db.ordered("certificates")
    if shipment_id is not None:
        rows = [r for r in rows if r["shipment_id"] == shipment_id]
    if kit_id is not None:
        rows = [r for r in rows if r["kit_id"] == kit_id]
    if facility_id is not None:
        rows = [r for r in rows if r["treatment_facility_id"] == facility_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("certificate", rows, limit, offset)
