"""Household custody cycle and the mail-back label (PRD 3.5, 3.6)."""
from flask import Blueprint

import clock
import constants
import db
import middleware
import response
import validate
from errors import (
    ERR_ABSORBENT_MATERIAL_REQUIRED,
    ERR_CONTAINER_OVERFILLED,
    ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED,
    ERR_FACILITY_NOT_PERMITTED,
    ERR_INVALID_ENROLLMENT_STATE,
    ERR_INVALID_FACILITY_STATE,
    ERR_INVALID_KIT_STATE,
    ERR_INVALID_LABEL_STATE,
    ERR_INVALID_REQUEST,
    ERR_LABEL_EXPIRED,
    ERR_LABEL_WINDOW_CONFLICT,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PACKAGING_SPEC_MISMATCH,
    ERR_PACKAGING_SPEC_RETIRED,
    ERR_POSTAL_WEIGHT_EXCEEDED,
    ERR_STATE_MAILBACK_PROHIBITED,
    ERR_STATE_MANIFEST_REQUIRED,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import accounting, calc, kits as kit_svc, lookup
from validate import Field

bp = Blueprint("kitops", __name__)

LABEL_WRITE_ROLES = ("LogisticsCoordinator", "ProgramAdmin")
LABEL_READ_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician", "Patient")
LABEL_LIST_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician")

SEAL_SCHEMA = [
    Field("fill_units", "int", required=True),
    Field("sealed_gross_weight_grams", "int", required=True),
]

VOID_KIT_SCHEMA = [Field("void_reason", "string", required=True, min_len=1)]

PRINT_SCHEMA = [Field("packaging_spec_id", "string", required=True, min_len=1)]

VOID_LABEL_SCHEMA = [Field("void_reason", "string")]

ACTIVATE_SCHEMA = [
    Field("treatment_facility_id", "string", required=True, min_len=1),
    Field("scheduled_intake_date", "date", required=True),
    Field("declared_gross_weight_grams", "int", required=True, minimum=1, maximum=100000),
    Field("state_manifest_number", "string"),
    Field("absorbent_declared", "bool"),
]


def _require_kit_owner(kit):
    if middleware.role() != "Patient":
        return
    patient = lookup.kit_patient(kit)
    if patient is None or patient["id"] != middleware.user_id():
        fail(ERR_NOT_RESOURCE_OWNER)


@bp.post("/sharps/kits/<kit_id>/acknowledge-receipt")
@endpoint(["Patient", "ProgramAdmin"])
def acknowledge_receipt(kit_id):
    validate.parse_body([])
    kit = lookup.require("kit", kit_id)
    _require_kit_owner(kit)
    if kit["status"] not in ("ISSUED", "RETURNED_TO_PATIENT"):
        fail(ERR_INVALID_KIT_STATE)
    enrollment = lookup.kit_enrollment(kit)
    if enrollment is None or enrollment["status"] != "ACTIVE":
        fail(ERR_INVALID_ENROLLMENT_STATE)
    kit["status"] = "ACTIVE_FILLING"
    kit["acknowledged_at"] = clock.now_iso()
    db.bump(kit)
    return response.ok(response.view("kit", kit))


@bp.post("/sharps/kits/<kit_id>/seal")
@endpoint(["Patient", "ProgramAdmin"])
def seal_kit(kit_id):
    body, _provided = validate.parse_body(SEAL_SCHEMA)
    kit = lookup.require("kit", kit_id)
    _require_kit_owner(kit)
    enrollment = lookup.kit_enrollment(kit)
    if enrollment is None or enrollment["status"] != "ACTIVE":
        fail(ERR_INVALID_ENROLLMENT_STATE)
    if kit["status"] != "ACTIVE_FILLING":
        fail(ERR_INVALID_KIT_STATE)
    if body["fill_units"] < 1:
        fail(ERR_INVALID_REQUEST, "fill_units must be at least 1.")
    if body["fill_units"] > kit["capacity_units"]:
        fail(ERR_CONTAINER_OVERFILLED)
    kit["status"] = "SEALED"
    kit["fill_units"] = body["fill_units"]
    kit["sealed_gross_weight_grams"] = body["sealed_gross_weight_grams"]
    db.bump(kit)
    return response.ok(response.view("kit", kit))


@bp.post("/sharps/kits/<kit_id>/void")
@endpoint(["ProgramAdmin", "LogisticsCoordinator"])
def void_kit(kit_id):
    body, _provided = validate.parse_body(VOID_KIT_SCHEMA)
    kit = lookup.require("kit", kit_id)
    if kit["status"] not in ("ISSUED", "ACTIVE_FILLING"):
        fail(ERR_INVALID_KIT_STATE)
    program = kit_svc.void_kit(kit, body["void_reason"], accounting.MEMO_KIT_VOID)
    accounting.recompute_program(program)
    enrollment = lookup.kit_enrollment(kit)
    if enrollment is not None:
        kit_svc.recompute_kits_issued(enrollment)
        db.touch(enrollment)
    return response.ok(response.view("kit", kit))


# ---- labels -------------------------------------------------------------

@bp.post("/sharps/kits/<kit_id>/return-labels")
@endpoint(LABEL_WRITE_ROLES)
def print_label(kit_id):
    body, _provided = validate.parse_body(PRINT_SCHEMA)
    kit = lookup.require("kit", kit_id)
    spec = lookup.require("packaging_spec", body["packaging_spec_id"])
    if kit["status"] != "SEALED":
        fail(ERR_INVALID_KIT_STATE)
    if kit["container_size"] not in spec["allowed_container_sizes"]:
        fail(ERR_PACKAGING_SPEC_MISMATCH)
    if spec["status"] != "ACTIVE":
        fail(ERR_PACKAGING_SPEC_RETIRED)
    valid_from = clock.now()
    valid_until = calc.label_window(valid_from)
    if calc.label_window_conflict(kit["id"], valid_from, valid_until):
        fail(ERR_LABEL_WINDOW_CONFLICT)
    if calc.label_quarantine_active(kit["id"]):
        fail(ERR_LABEL_WINDOW_CONFLICT)
    label = db.create_row(
        "return_labels",
        {
            "kit_id": kit["id"],
            "packaging_spec_id": spec["id"],
            "postal_service": spec["postal_service"],
            "tracking_number": calc.next_tracking_number(spec["postal_service"]),
            "valid_from": clock.fmt_instant(valid_from),
            "valid_until": clock.fmt_instant(valid_until),
            "voided_at": None,
            "activated_at": None,
            "status": "PRINTED",
        },
    )
    return response.created(response.view("return_label", label))


@bp.post("/sharps/return-labels/<label_id>/void")
@endpoint(LABEL_WRITE_ROLES)
def void_label(label_id):
    validate.parse_body(VOID_LABEL_SCHEMA)
    label = lookup.require("label", label_id)
    if label["status"] != "PRINTED":
        fail(ERR_INVALID_LABEL_STATE)
    label["status"] = "VOIDED"
    label["voided_at"] = clock.now_iso()
    db.bump(label)
    return response.ok(response.view("return_label", label))


@bp.post("/sharps/return-labels/<label_id>/activate")
@endpoint(["LogisticsCoordinator"])
def activate_label(label_id):
    body, provided = validate.parse_body(ACTIVATE_SCHEMA)
    label = lookup.require("label", label_id)
    facility = lookup.require("facility", body["treatment_facility_id"])
    if label["status"] != "PRINTED":
        fail(ERR_INVALID_LABEL_STATE)

    kit = db.get("kits", label["kit_id"])
    patient = lookup.kit_patient(kit) if kit is not None else None
    state_rule = lookup.patient_state_rule(patient) if patient is not None else None
    spec = db.get("packaging_specs", label["packaging_spec_id"])

    # safety band
    if state_rule is None or not state_rule["mail_back_permitted"]:
        fail(ERR_STATE_MAILBACK_PROHIBITED)

    # constraint band, in the pinned order
    if spec is not None and body["declared_gross_weight_grams"] > spec["max_gross_weight_grams"]:
        fail(ERR_POSTAL_WEIGHT_EXCEEDED)
    if spec is not None and spec["requires_absorbent"]:
        if body.get("absorbent_declared") is not True:
            fail(ERR_ABSORBENT_MATERIAL_REQUIRED)
    if state_rule["requires_state_manifest"]:
        manifest = body.get("state_manifest_number")
        if manifest is None or manifest == "":
            fail(ERR_STATE_MANIFEST_REQUIRED)
    if spec is not None and spec["hazard_class"] not in facility["accepted_hazard_classes"]:
        fail(ERR_FACILITY_NOT_PERMITTED)
    if facility["status"] != "ACTIVE":
        fail(ERR_INVALID_FACILITY_STATE)
    intake_date = body["scheduled_intake_date"]
    units = kit["fill_units"] if kit is not None else 0
    booked = calc.booked_units(facility["id"], intake_date)
    if booked + units > facility["daily_intake_capacity_units"]:
        fail(ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED)

    # temporal band
    now = clock.now()
    if now > clock.parse_instant(label["valid_until"]):
        fail(ERR_LABEL_EXPIRED)

    label["status"] = "ACTIVATED"
    label["activated_at"] = clock.fmt_instant(now)
    db.bump(label)

    shipment = db.create_row(
        "shipments",
        {
            "kit_id": label["kit_id"],
            "return_label_id": label["id"],
            "treatment_facility_id": facility["id"],
            "scheduled_intake_date": intake_date,
            "declared_gross_weight_grams": body["declared_gross_weight_grams"],
            "observed_gross_weight_grams": None,
            "custody_units": units,
            "state_manifest_number": body.get("state_manifest_number"),
            "tendered_at": clock.fmt_instant(now),
            "delivered_at": None,
            "screened_by_user_id": None,
            "transport_status": "TENDERED",
            "conformance_status": "UNSCREENED",
        },
    )
    facility["pending_intake_units"] = facility["pending_intake_units"] + units
    db.touch(facility)
    return response.created(response.view("shipment", shipment))


@bp.get("/sharps/return-labels/<label_id>")
@endpoint(LABEL_READ_ROLES, mutating=False)
def get_label(label_id):
    row = lookup.require("label", label_id)
    return response.ok(response.view("return_label", row))


@bp.get("/sharps/return-labels")
@endpoint(LABEL_LIST_ROLES, mutating=False)
def list_labels():
    limit, offset = validate.pagination()
    kit_id = validate.qs_str("kit_id")
    spec_id = validate.qs_str("packaging_spec_id")
    status = validate.qs_enum("status", constants.LABEL_STATUSES)
    lookup.require_filter("kit", kit_id)
    lookup.require_filter("packaging_spec", spec_id)
    rows = db.ordered("return_labels")
    if kit_id is not None:
        rows = [r for r in rows if r["kit_id"] == kit_id]
    if spec_id is not None:
        rows = [r for r in rows if r["packaging_spec_id"] == spec_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("return_label", rows, limit, offset)
