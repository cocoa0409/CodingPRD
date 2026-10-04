"""Diagnostic reports, vehicles, service appointments and mobile visits."""

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import (
    body, bool_field, check_version, instant_field, int_field, number_field, paged,
    require_owner, text_field,
    counted,
)
from services import entitlements as entitlement_service
from services import service_ops

bp = Blueprint("service", __name__)

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# --- RemoteDiagnosticReport ---

@bp.post("/vehicles/<vehicle_id>/diagnostic-reports")
def create_report(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    payload = body()
    severity = text_field(payload, "severity")
    if severity not in SEVERITIES:
        fail("ERR_INVALID_REQUEST", "severity must be LOW, MEDIUM, HIGH or CRITICAL.")
    report = service_ops.create_report(
        vehicle,
        text_field(payload, "fault_code"),
        severity,
        bool_field(payload, "is_driveable", True),
    )
    return object_response(serialize(report), 201)


@bp.get("/diagnostic-reports")
def list_reports():
    rows = [r for r in DB.reports.values()
            if matches(request.args, "vehicle_id", r["vehicle_id"])
            and matches(request.args, "triage_outcome", r["triage_outcome"])
            and matches(request.args, "severity", r["severity"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/diagnostic-reports/<report_id>")
def get_report(report_id):
    return object_response(serialize(get("report", report_id)))


# --- Vehicle ---

@bp.get("/vehicles")
def list_vehicles():
    rows = [r for r in DB.vehicles.values()
            if matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "status", r["status"])
            and matches(request.args, "service_hold_state", r["service_hold_state"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    return object_response(serialize(get("vehicle", vehicle_id)))


@bp.get("/vehicles/<vehicle_id>/diagnostic-reports")
def vehicle_reports(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    rows = [r for r in DB.reports.values()
            if r["vehicle_id"] == vehicle["id"]
            and matches(request.args, "triage_outcome", r["triage_outcome"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicles/<vehicle_id>/service-appointments")
def vehicle_service_appointments(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    rows = [r for r in DB.service_appointments.values()
            if r["vehicle_id"] == vehicle["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicles/<vehicle_id>/mobile-service-visits")
def vehicle_visits(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    rows = [r for r in DB.visits.values()
            if r["vehicle_id"] == vehicle["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicles/<vehicle_id>/software-entitlements")
def vehicle_entitlements(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    rows = [r for r in DB.entitlements.values()
            if r["vehicle_id"] == vehicle["id"]
            and matches(request.args, "status", r["status"])
            and matches(request.args, "entitlement_source", r["entitlement_source"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/vehicles/<vehicle_id>/issue-notes")
def vehicle_notes(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    rows = [r for r in DB.notes.values()
            if r["vehicle_id"] == vehicle["id"]
            and matches(request.args, "status", r["status"])]
    blocked = request.args.get("blocked_handover")
    if blocked not in (None, ""):
        truthy = str(blocked).strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r["blocked_handover"]) is truthy]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.post("/vehicles/<vehicle_id>/retire")
def retire_vehicle(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    return object_response(serialize(entitlement_service.retire_vehicle(vehicle)))


# --- ServiceAppointment ---

@bp.post("/service-appointments")
def open_service_appointment():
    payload = body()
    vehicle = get("vehicle", text_field(payload, "vehicle_id"))
    report = get("report", text_field(payload, "diagnostic_report_id"))
    if report["vehicle_id"] != vehicle["id"]:
        fail("ERR_REPORT_NOT_FOUND")
    center = get("center", text_field(payload, "service_center_id"))
    appointment = service_ops.open_service_appointment(
        vehicle, report, center,
        instant_field(payload, "scheduled_start"),
        instant_field(payload, "scheduled_end"))
    return object_response(serialize(appointment), 201)


@bp.get("/service-appointments")
def list_service_appointments():
    rows = [r for r in DB.service_appointments.values()
            if matches(request.args, "vehicle_id", r["vehicle_id"])
            and matches(request.args, "service_center_id", r["service_center_id"])
            and matches(request.args, "diagnostic_report_id", r["diagnostic_report_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/service-appointments/<appointment_id>")
def get_service_appointment(appointment_id):
    return object_response(serialize(get("service_appointment", appointment_id)))


@bp.post("/service-appointments/<appointment_id>/schedule-center")
def schedule_center(appointment_id):
    appointment = get("service_appointment", appointment_id)
    payload = body()
    report = get("report", appointment["diagnostic_report_id"])
    updated = service_ops.schedule_center(
        appointment, report,
        instant_field(payload, "scheduled_start"),
        instant_field(payload, "scheduled_end"))
    return object_response(serialize(updated))


@bp.post("/service-appointments/<appointment_id>/cancel")
def cancel_service_appointment(appointment_id):
    appointment = get("service_appointment", appointment_id)
    return object_response(serialize(service_ops.cancel_service_appointment(appointment)))


# --- MobileServiceVisit ---

@bp.post("/mobile-service-visits")
def dispatch_visit():
    payload = body()
    appointment = get("service_appointment", text_field(payload, "service_appointment_id"))
    check_version(payload, "expected_service_appointment_version", appointment)
    report = get("report", appointment["diagnostic_report_id"])
    vehicle = get("vehicle", appointment["vehicle_id"])
    hub = get("center", text_field(payload, "parts_hub_id"))
    visit = service_ops.dispatch_visit(
        appointment, report, vehicle, hub,
        text_field(payload, "van_code"),
        instant_field(payload, "visit_start"),
        instant_field(payload, "visit_end"),
        number_field(payload, "labor_hours", 0),
        int_field(payload, "parts_cost_cents", 0),
        int_field(payload, "visit_miles", 0))
    return object_response(serialize(visit), 201)


@bp.get("/mobile-service-visits")
def list_visits():
    rows = [r for r in DB.visits.values()
            if matches(request.args, "vehicle_id", r["vehicle_id"])
            and matches(request.args, "service_appointment_id", r["service_appointment_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/mobile-service-visits/<visit_id>")
def get_visit(visit_id):
    return object_response(serialize(get("visit", visit_id)))


@bp.post("/mobile-service-visits/<visit_id>/reserve-parts")
def reserve_parts(visit_id):
    visit = get("visit", visit_id)
    return object_response(serialize(service_ops.reserve_parts(visit)))


@bp.post("/mobile-service-visits/<visit_id>/confirm-parts-shipment")
def confirm_parts_shipment(visit_id):
    visit = get("visit", visit_id)
    return object_response(serialize(service_ops.confirm_parts_shipment(visit)))


@bp.post("/mobile-service-visits/<visit_id>/start")
def start_visit(visit_id):
    visit = get("visit", visit_id)
    return object_response(serialize(service_ops.start_visit(visit)))


@bp.post("/mobile-service-visits/<visit_id>/complete")
def complete_visit(visit_id):
    visit = get("visit", visit_id)
    return object_response(serialize(service_ops.complete_visit(visit)))


@bp.post("/mobile-service-visits/<visit_id>/cancel")
def cancel_visit(visit_id):
    visit = get("visit", visit_id)
    return object_response(serialize(service_ops.cancel_visit(visit)))


@bp.post("/mobile-service-visits/<visit_id>/reschedule")
def reschedule_visit(visit_id):
    visit = get("visit", visit_id)
    payload = body()
    updated = service_ops.reschedule_visit(
        visit,
        instant_field(payload, "visit_start"),
        instant_field(payload, "visit_end"))
    return object_response(serialize(updated))


# --- SoftwareEntitlement ---

@bp.post("/vehicles/<vehicle_id>/software-entitlements")
def grant_entitlements(vehicle_id):
    vehicle = get("vehicle", vehicle_id)
    payload = body()
    entries = payload.get("feature_entries")
    if not isinstance(entries, list) or not entries:
        fail("ERR_INVALID_REQUEST", "feature_entries must be a non-empty array.")
    source = text_field(payload, "entitlement_source")
    rows = entitlement_service.grant_bundle(
        vehicle, entries, source,
        int_field(payload, "trial_days", 0),
        text_field(payload, "basis_version", None))
    return object_response([serialize(r) for r in rows], 201)


@bp.get("/software-entitlements")
def list_entitlements():
    rows = [r for r in DB.entitlements.values()
            if matches(request.args, "vehicle_id", r["vehicle_id"])
            and matches(request.args, "status", r["status"])
            and matches(request.args, "entitlement_source", r["entitlement_source"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/software-entitlements/<entitlement_id>")
def get_entitlement(entitlement_id):
    return object_response(serialize(get("entitlement", entitlement_id)))


@bp.post("/vehicles/<vehicle_id>/software-entitlements/<entitlement_id>/revoke")
def revoke_entitlement(vehicle_id, entitlement_id):
    vehicle = get("vehicle", vehicle_id)
    entitlement = get("entitlement", entitlement_id)
    if entitlement["vehicle_id"] != vehicle["id"]:
        fail("ERR_ENTITLEMENT_NOT_FOUND")
    return object_response(serialize(entitlement_service.revoke(entitlement)))


# --- VehicleIssueNote ---

@bp.get("/issue-notes")
def list_notes():
    rows = [r for r in DB.notes.values()
            if matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "vehicle_id", r["vehicle_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/issue-notes/<note_id>")
def get_note(note_id):
    return object_response(serialize(get("note", note_id)))


@bp.post("/issue-notes/<note_id>/resolve")
def resolve_note(note_id):
    from services import delivery
    return object_response(serialize(delivery.resolve_note(get("note", note_id))))


@bp.post("/issue-notes/<note_id>/waive")
def waive_note(note_id):
    from services import delivery
    payload = body()
    reason = payload.get("waiver_reason")
    if not isinstance(reason, str) or not reason.strip():
        fail("ERR_INVALID_REQUEST", "waiver_reason must be non-empty.")
    return object_response(serialize(delivery.waive_note(get("note", note_id))))