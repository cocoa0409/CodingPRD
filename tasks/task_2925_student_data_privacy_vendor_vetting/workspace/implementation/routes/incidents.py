"""Vendor incidents: two independent status axes (PRD 3.9)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("incidents", __name__)


@bp.post("/vendor-incidents")
def report_incident():
    user_id, role = auth.actor("VendorLiaison", "PrivacyOfficeAdmin")
    data = validate.body([
        F("vendor_id", "str"),
        F("incident_type", "enum", members=set(logic.INCIDENT_TYPES)),
        F("detected_at", "instant"),
        F("affected_student_count", "int", lo=0, hi=500000),
        F("max_data_tier", "int", lo=1, hi=4),
    ])
    now = store.clock()
    if data["detected_at"] > now:
        validate.bad("detected_at must be at or before the current logical clock.")

    vendor = auth.need("vendor", data["vendor_id"])
    if role == "VendorLiaison":
        auth.owner_or_403(user_id == vendor["id"])

    # Rung 32: closed, doubly-buffered window collision -- self-reports only.
    start = data["detected_at"]
    end = start + store.hours(logic.INCIDENT_WINDOW_HOURS)
    if logic.incident_window_conflict(vendor["id"], start, end):
        raise ApiError("ERR_INCIDENT_WINDOW_BUFFER_CONFLICT")

    severity = logic.incident_severity(data["affected_student_count"], data["max_data_tier"])
    row = store.new_row({
        "vendor_id": vendor["id"],
        "incident_type": data["incident_type"],
        "detected_at": data["detected_at"],
        "reported_at": now,
        "contained_at": None,
        "affected_student_count": data["affected_student_count"],
        "max_data_tier": data["max_data_tier"],
        "severity": severity,
        "notification_due_at": logic.notification_due_at(
            data["detected_at"], severity, vendor["breach_notification_hours"]),
        "notification_sent_at": None,
        "response_status": "REPORTED",
        "notification_status": "PENDING",
        "notified_party_count": 0,
        "remediation_note": None,
    })
    store.incidents[row["id"]] = row
    logic.recompute_vendor(vendor, counts=True)
    return envelope.created(serialize.incident(row))


@bp.get("/vendor-incidents")
def list_incidents():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    filters = envelope.query_filters({
        "vendor_id": None,
        "response_status": set(logic.RESPONSE_STATUSES),
        "notification_status": set(logic.NOTIFICATION_STATUSES),
        "severity": set(logic.SEVERITIES),
    })
    rows = list(store.incidents.values())
    for key in ("vendor_id", "response_status", "notification_status", "severity"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.incident)


@bp.get("/vendor-incidents/<incident_id>")
def read_incident(incident_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    return envelope.ok(serialize.incident(auth.need("incident", incident_id)))


@bp.post("/vendor-incidents/<incident_id>/contain")
def contain_incident(incident_id):
    user_id, role = auth.actor("VendorLiaison", "PrivacyOfficeAdmin")
    data = validate.body([
        F("contained_at", "instant", required=False),
        F("remediation_note", "str", required=False),
    ])
    row = auth.need("incident", incident_id)
    now = store.clock()
    contained_at = data.get("contained_at", now)
    if contained_at < row["detected_at"]:
        validate.bad("contained_at must be at or after detected_at.")
    if contained_at > now:
        validate.bad("contained_at must be at or before the current logical clock.")

    if role == "VendorLiaison":
        auth.owner_or_403(user_id == row["vendor_id"])
    if row["response_status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_STATE_INVALID")

    row["response_status"] = "CONTAINED"
    row["contained_at"] = contained_at
    if "remediation_note" in data:
        row["remediation_note"] = data["remediation_note"]
    # The notification dimension is deliberately left untouched.
    store.bump(row)
    logic.recompute_vendor(store.vendors[row["vendor_id"]], counts=True)
    return envelope.ok(serialize.incident(row))


@bp.post("/vendor-incidents/<incident_id>/send-notification")
def send_notification(incident_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("notified_party_count", "int", lo=0)])
    row = auth.need("incident", incident_id)
    if row["notification_status"] not in ("PENDING", "OVERDUE"):
        raise ApiError("ERR_NOTIFICATION_ALREADY_SENT")

    now = store.clock()
    row["notification_sent_at"] = now
    row["notified_party_count"] = data["notified_party_count"]
    # The landing state is chosen purely from the clock (PRD 3.9).
    row["notification_status"] = "SENT" if now <= row["notification_due_at"] else "SENT_LATE"
    store.bump(row)
    logic.recompute_vendor(store.vendors[row["vendor_id"]], counts=True)
    return envelope.ok(serialize.incident(row))


@bp.post("/vendor-incidents/<incident_id>/resolve")
def resolve_incident(incident_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("disposition", "enum", members={"REMEDIATE", "ESCALATE"}),
        F("remediation_note", "str", required=False),
    ])
    row = auth.need("incident", incident_id)
    if row["response_status"] != "CONTAINED":
        raise ApiError("ERR_INCIDENT_STATE_INVALID")

    row["response_status"] = "REMEDIATED" if data["disposition"] == "REMEDIATE" else "ESCALATED"
    if "remediation_note" in data:
        row["remediation_note"] = data["remediation_note"]
    store.bump(row)
    logic.recompute_vendor(store.vendors[row["vendor_id"]], counts=True)
    return envelope.ok(serialize.incident(row))
