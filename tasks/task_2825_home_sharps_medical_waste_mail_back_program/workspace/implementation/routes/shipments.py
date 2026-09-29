"""Transport scans, intake screening, notification and remediation (PRD 3.6, 3.7)."""
from datetime import timedelta

from flask import Blueprint

import clock
import constants
import db
import middleware
import response
import validate
from errors import (
    ERR_INVALID_NONCONFORMANCE_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SHIPMENT_STATE,
    ERR_NOTIFICATION_DEADLINE_PASSED,
    ERR_POSTAL_WEIGHT_EXCEEDED,
    ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE,
    ERR_SHIPMENT_ALREADY_SCREENED,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import accounting, calc, kits as kit_svc, lookup, patients as patient_svc
from validate import Field

bp = Blueprint("shipments", __name__)

SHIPMENT_READ_ROLES = (
    "ProgramAdmin",
    "LogisticsCoordinator",
    "IntakeTechnician",
    "DestructionOfficer",
)

TRANSPORT_SCHEMA = [
    Field("event_type", "enum", required=True, values=constants.TRANSPORT_EVENT_TYPES)
]

SCREENING_SCHEMA = [
    Field("outcome", "enum", required=True, values=constants.SCREENING_OUTCOMES),
    Field("observed_gross_weight_grams", "int", required=True),
    Field("reason_code", "enum", default=None, values=constants.REASON_CODES),
]

NOTIFY_SCHEMA = [
    Field("notification_channel", "enum", required=True, values=constants.NOTIFICATION_CHANNELS)
]

REMEDIATE_SCHEMA = [
    Field("remediation_action", "enum", required=True, values=constants.REMEDIATION_ACTIONS)
]

LEGAL_TRANSPORT_FROM = {
    "IN_TRANSIT": ("TENDERED",),
    "DELIVERED": ("IN_TRANSIT",),
    "LOST": ("TENDERED", "IN_TRANSIT"),
}


def _release_facility_units(shipment):
    facility = lookup.shipment_facility(shipment)
    if facility is None:
        return
    facility["pending_intake_units"] = facility["pending_intake_units"] - shipment["custody_units"]
    db.touch(facility)


@bp.post("/sharps/shipments/<shipment_id>/transport-events")
@endpoint(["LogisticsCoordinator"])
def transport_event(shipment_id):
    body, _provided = validate.parse_body(TRANSPORT_SCHEMA)
    shipment = lookup.require("shipment", shipment_id)
    event_type = body["event_type"]
    if shipment["transport_status"] not in LEGAL_TRANSPORT_FROM[event_type]:
        fail(ERR_INVALID_SHIPMENT_STATE)

    kit = lookup.shipment_kit(shipment)
    if event_type == "IN_TRANSIT":
        shipment["transport_status"] = "IN_TRANSIT"
        if kit is not None and kit["status"] == "SEALED":
            kit["status"] = "IN_TRANSIT"
            db.bump(kit)
    elif event_type == "DELIVERED":
        shipment["transport_status"] = "DELIVERED"
        shipment["delivered_at"] = clock.now_iso()
        if kit is not None and kit["status"] == "IN_TRANSIT":
            kit["status"] = "RECEIVED"
            db.bump(kit)
    else:
        # LOST: the four-hop cascade of PRD 3.6.
        shipment["transport_status"] = "LOST"
        label = lookup.shipment_label(shipment)
        if label is not None and label["status"] == "ACTIVATED":
            label["status"] = "VOIDED"
            label["voided_at"] = clock.now_iso()
            db.bump(label)
        if kit is not None and kit["status"] in ("SEALED", "IN_TRANSIT"):
            program = kit_svc.void_kit(kit, kit_svc.VOID_SHIPMENT_LOST, accounting.MEMO_SHIPMENT_LOST)
            _release_facility_units(shipment)
            accounting.recompute_program(program)
            enrollment = lookup.kit_enrollment(kit)
            if enrollment is not None:
                kit_svc.recompute_kits_issued(enrollment)
                db.touch(enrollment)
        else:
            _release_facility_units(shipment)
    db.bump(shipment)
    return response.ok(response.view("shipment", shipment))


@bp.post("/sharps/shipments/<shipment_id>/conformance-screening")
@endpoint(["IntakeTechnician"])
def conformance_screening(shipment_id):
    body, _provided = validate.parse_body(SCREENING_SCHEMA)
    outcome = body["outcome"]
    if outcome == "NON_CONFORMING" and body["reason_code"] is None:
        fail(ERR_INVALID_REQUEST, "Field 'reason_code' is required on a NON_CONFORMING outcome.")

    shipment = lookup.require("shipment", shipment_id)
    if shipment["transport_status"] != "DELIVERED":
        fail(ERR_INVALID_SHIPMENT_STATE)
    observed = body["observed_gross_weight_grams"]
    if outcome == "CONFORMING":
        spec = lookup.shipment_spec(shipment)
        if spec is not None and observed > spec["max_gross_weight_grams"]:
            fail(ERR_POSTAL_WEIGHT_EXCEEDED)
    if shipment["conformance_status"] != "UNSCREENED":
        fail(ERR_SHIPMENT_ALREADY_SCREENED)

    shipment["observed_gross_weight_grams"] = observed
    shipment["screened_by_user_id"] = middleware.user_id()
    patient = lookup.shipment_patient(shipment)

    if outcome == "CONFORMING":
        shipment["conformance_status"] = "CONFORMING"
        if patient is not None:
            calc.refresh_screening_score(patient)
            db.touch(patient)
    else:
        shipment["conformance_status"] = "NON_CONFORMING"
        state_rule = lookup.patient_state_rule(patient) if patient is not None else None
        hours = state_rule["notification_deadline_hours"] if state_rule is not None else 72
        created_at = clock.now()
        event = db.create_row(
            "nonconformance_events",
            {
                "shipment_id": shipment["id"],
                "reason_code": body["reason_code"],
                "notification_deadline_at": clock.fmt_instant(created_at + timedelta(hours=hours)),
                "notified_at": None,
                "notification_channel": None,
                "remediation_action": None,
                "status": "OPEN",
            },
        )
        event["notification_deadline_at"] = clock.fmt_instant(
            clock.parse_instant(event["created_at"]) + timedelta(hours=hours)
        )
        if patient is not None:
            score = calc.refresh_screening_score(patient)
            db.touch(patient)
            if score >= constants.RISK_SUSPEND_THRESHOLD and patient["status"] == "ENROLLED":
                patient_svc.suspend_patient(patient)
    db.bump(shipment)
    return response.ok(response.view("shipment", shipment))


# ---- non-conformance events ---------------------------------------------

@bp.post("/sharps/non-conformance-events/<event_id>/notify-customer")
@endpoint(["IntakeTechnician", "ProgramAdmin"])
def notify_customer(event_id):
    body, _provided = validate.parse_body(NOTIFY_SCHEMA)
    event = lookup.require("nonconformance_event", event_id)
    if event["status"] != "OPEN":
        fail(ERR_INVALID_NONCONFORMANCE_STATE)
    deadline = clock.parse_instant(event["notification_deadline_at"])
    if deadline is not None and clock.now() > deadline:
        fail(ERR_NOTIFICATION_DEADLINE_PASSED)
    event["status"] = "CUSTOMER_NOTIFIED"
    event["notified_at"] = clock.now_iso()
    event["notification_channel"] = body["notification_channel"]
    db.bump(event)
    return response.ok(response.view("nonconformance_event", event))


@bp.post("/sharps/non-conformance-events/<event_id>/remediate")
@endpoint(["IntakeTechnician", "ProgramAdmin"])
def remediate(event_id):
    body, _provided = validate.parse_body(REMEDIATE_SCHEMA)
    event = lookup.require("nonconformance_event", event_id)
    if event["status"] != "CUSTOMER_NOTIFIED":
        fail(ERR_INVALID_NONCONFORMANCE_STATE)

    action = body["remediation_action"]
    shipment = db.get("shipments", event["shipment_id"])
    patient = lookup.shipment_patient(shipment) if shipment is not None else None
    state_rule = lookup.patient_state_rule(patient) if patient is not None else None
    facility = lookup.shipment_facility(shipment) if shipment is not None else None

    if action == "RETURN_TO_PATIENT":
        if state_rule is not None and (
            state_rule["household_sharps_classification"] == "REGULATED_MEDICAL_WASTE"
        ):
            fail(ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE)
    elif action == "DISPOSE_AS_RMW":
        if facility is None or (
            "UN3291_REGULATED_MEDICAL_WASTE" not in facility["accepted_hazard_classes"]
        ):
            fail(ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE)

    event["status"] = "RESOLVED"
    event["remediation_action"] = action
    db.bump(event)

    if shipment is not None:
        shipment["conformance_status"] = "REMEDIATED"
        db.bump(shipment)
        if action == "RETURN_TO_PATIENT":
            kit = lookup.shipment_kit(shipment)
            if kit is not None and kit["status"] == "RECEIVED":
                kit["status"] = "RETURNED_TO_PATIENT"
                db.bump(kit)
            _release_facility_units(shipment)
            label = lookup.shipment_label(shipment)
            if label is not None and label["status"] == "ACTIVATED":
                label["status"] = "VOIDED"
                label["voided_at"] = clock.now_iso()
                db.bump(label)
    return response.ok(response.view("nonconformance_event", event))


# ---- reads --------------------------------------------------------------

@bp.get("/sharps/shipments/<shipment_id>")
@endpoint(SHIPMENT_READ_ROLES, mutating=False)
def get_shipment(shipment_id):
    row = lookup.require("shipment", shipment_id)
    return response.ok(response.view("shipment", row))


@bp.get("/sharps/shipments")
@endpoint(SHIPMENT_READ_ROLES, mutating=False)
def list_shipments():
    limit, offset = validate.pagination()
    kit_id = validate.qs_str("kit_id")
    label_id = validate.qs_str("return_label_id")
    facility_id = validate.qs_str("treatment_facility_id")
    transport_status = validate.qs_enum("transport_status", constants.TRANSPORT_STATUSES)
    conformance_status = validate.qs_enum("conformance_status", constants.CONFORMANCE_STATUSES)
    intake_date = validate.qs_date("scheduled_intake_date")
    lookup.require_filter("kit", kit_id)
    lookup.require_filter("label", label_id)
    lookup.require_filter("facility", facility_id)
    rows = db.ordered("shipments")
    if kit_id is not None:
        rows = [r for r in rows if r["kit_id"] == kit_id]
    if label_id is not None:
        rows = [r for r in rows if r["return_label_id"] == label_id]
    if facility_id is not None:
        rows = [r for r in rows if r["treatment_facility_id"] == facility_id]
    if transport_status is not None:
        rows = [r for r in rows if r["transport_status"] == transport_status]
    if conformance_status is not None:
        rows = [r for r in rows if r["conformance_status"] == conformance_status]
    if intake_date is not None:
        rows = [r for r in rows if r["scheduled_intake_date"] == intake_date]
    return page("shipment", rows, limit, offset)


@bp.get("/sharps/shipments/<shipment_id>/non-conformance-events")
@endpoint(SHIPMENT_READ_ROLES, mutating=False)
def list_shipment_events(shipment_id):
    limit, offset = validate.pagination()
    status = validate.qs_enum("status", constants.NONCONFORMANCE_STATUSES)
    lookup.require("shipment", shipment_id)
    rows = lookup.shipment_events(shipment_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("nonconformance_event", rows, limit, offset)


@bp.get("/sharps/non-conformance-events/<event_id>")
@endpoint(SHIPMENT_READ_ROLES, mutating=False)
def get_event(event_id):
    row = lookup.require("nonconformance_event", event_id)
    return response.ok(response.view("nonconformance_event", row))


@bp.get("/sharps/non-conformance-events")
@endpoint(SHIPMENT_READ_ROLES, mutating=False)
def list_events():
    limit, offset = validate.pagination()
    shipment_id = validate.qs_str("shipment_id")
    reason_code = validate.qs_enum("reason_code", constants.REASON_CODES)
    status = validate.qs_enum("status", constants.NONCONFORMANCE_STATUSES)
    rows = db.ordered("nonconformance_events")
    if shipment_id is not None:
        rows = [r for r in rows if r["shipment_id"] == shipment_id]
    if reason_code is not None:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("nonconformance_event", rows, limit, offset)
