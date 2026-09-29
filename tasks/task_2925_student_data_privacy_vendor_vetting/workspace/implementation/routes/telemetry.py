"""Telemetry detections and their triage (PRD 3.8)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("telemetry", __name__)


@bp.post("/telemetry-detections")
def ingest_detection():
    auth.actor("TelemetryAgent")
    data = validate.body([
        F("observed_domain", "str", lo=1, hi=253, nonblank=True),
        F("application_id", "str", required=False),
        F("school_code", "str", lo=1, hi=16, nonblank=True),
        F("source", "enum", members=set(logic.TELEMETRY_SOURCES)),
        F("observed_at", "instant"),
        F("distinct_user_count", "int", lo=0, hi=100000),
        F("session_count", "int", lo=0, hi=1000000),
    ])
    if data["observed_at"] > store.clock():
        validate.bad("observed_at must be at or before the current logical clock.")

    application_id = None
    if "application_id" in data:
        application_id = auth.need("application", data["application_id"])["id"]

    classification, matched = logic.detection_classification(application_id, data["observed_at"])
    row = store.new_row({
        "observed_domain": data["observed_domain"],
        "application_id": application_id,
        "matched_catalog_entry_id": matched,
        "school_code": data["school_code"],
        "source": data["source"],
        "observed_at": data["observed_at"],
        "distinct_user_count": data["distinct_user_count"],
        "session_count": data["session_count"],
        "classification": classification,
        "exposure_score": logic.detection_exposure_score(
            classification, data["distinct_user_count"], data["session_count"]),
        "status": "NEW",
        "triaged_by_user_id": None,
        "linked_incident_id": None,
    })
    store.detections[row["id"]] = row
    return envelope.created(serialize.detection(row))


@bp.get("/telemetry-detections")
def list_detections():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    filters = envelope.query_filters({
        "application_id": None,
        "matched_catalog_entry_id": None,
        "linked_incident_id": None,
        "classification": set(logic.DETECTION_CLASSIFICATIONS),
        "status": set(logic.DETECTION_STATUSES),
        "school_code": None,
    })
    rows = list(store.detections.values())
    for key in ("application_id", "matched_catalog_entry_id", "linked_incident_id",
                "classification", "status", "school_code"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.detection)


@bp.get("/telemetry-detections/<detection_id>")
def read_detection(detection_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    return envelope.ok(serialize.detection(auth.need("detection", detection_id)))


@bp.post("/telemetry-detections/<detection_id>/triage")
def triage_detection(detection_id):
    user_id, _role = auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    data = validate.body([
        F("disposition", "enum",
          members={"CONFIRM_AUTHORIZED", "BLOCK", "WHITELIST", "ESCALATE"}),
        F("note", "str", required=False),
        F("affected_student_count", "int", required=False, lo=0, hi=500000),
        F("max_data_tier", "int", required=False, lo=1, hi=4),
    ])
    row = auth.need("detection", detection_id)
    if row["status"] != "NEW":
        raise ApiError("ERR_DETECTION_ALREADY_TRIAGED")

    disposition = data["disposition"]
    classification = row["classification"]

    # Rung 30 sits above applicability: the whitelist gate reads the matched
    # entry's state at the CURRENT logical clock (PRD 3.8).
    if disposition == "WHITELIST":
        entry = None
        if row["matched_catalog_entry_id"] is not None:
            entry = store.catalog_entries.get(row["matched_catalog_entry_id"])
        if entry is None or entry["status"] not in logic.VISIBLE_STATUSES:
            raise ApiError("ERR_WHITELIST_REQUIRES_ACTIVE_ENTRY")

    # Rung 41: each disposition's applicability condition.
    if disposition == "CONFIRM_AUTHORIZED" and classification != "AUTHORIZED":
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition == "BLOCK" and classification not in (
            "UNAUTHORIZED", "EXPIRED_AUTHORIZATION", "UNKNOWN_DOMAIN"):
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition in ("WHITELIST", "ESCALATE") and classification not in (
            "UNAUTHORIZED", "EXPIRED_AUTHORIZATION"):
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition == "ESCALATE" and row["application_id"] is None:
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")

    row["status"] = {
        "CONFIRM_AUTHORIZED": "CONFIRMED_AUTHORIZED",
        "BLOCK": "BLOCKED",
        "WHITELIST": "WHITELISTED",
        "ESCALATE": "ESCALATED",
    }[disposition]
    # Recorded verbatim, never compared to a stored id.
    row["triaged_by_user_id"] = user_id
    if "note" in data:
        row["_triage_note"] = data["note"]

    if disposition == "ESCALATE":
        application = store.applications[row["application_id"]]
        vendor = store.vendors[application["vendor_id"]]
        affected = data.get("affected_student_count", row["distinct_user_count"])
        tier = data.get("max_data_tier", 3)
        severity = logic.incident_severity(affected, tier)
        incident = store.new_row({
            "vendor_id": vendor["id"],
            "incident_type": "UNAUTHORIZED_DISCLOSURE",
            "detected_at": row["observed_at"],
            "reported_at": store.clock(),
            "contained_at": None,
            "affected_student_count": affected,
            "max_data_tier": tier,
            "severity": severity,
            "notification_due_at": logic.notification_due_at(
                row["observed_at"], severity, vendor["breach_notification_hours"]),
            "notification_sent_at": None,
            "response_status": "REPORTED",
            "notification_status": "PENDING",
            "notified_party_count": 0,
            "remediation_note": None,
        })
        # Deliberate exemption: an escalation never consults the buffered window.
        store.incidents[incident["id"]] = incident
        row["linked_incident_id"] = incident["id"]
        store.bump(row)
        logic.recompute_vendor(vendor, counts=True)
        return envelope.ok(serialize.detection(row))

    store.bump(row)
    return envelope.ok(serialize.detection(row))
