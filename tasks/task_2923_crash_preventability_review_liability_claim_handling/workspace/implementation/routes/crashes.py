"""Crash notification intake, the regulatory filing clock, driver statements
and evidence custody."""

from flask import Blueprint

import calc
import serializers
from auth import require, SAFETY_READ
from common import claim_for_crash, filtered, lookup, paginate
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, touch

bp = Blueprint("crashes", __name__)

CRASH_SPEC = [
    f("driver_id", "string", required=True),
    f("terminal_id", "string", required=True),
    f("occurred_at", "instant", required=True),
    f("notified_at", "instant", required=True),
    f("location_text", "string", required=True),
    f("severity", "string", required=True, enum=calc.SEVERITIES),
    f("route_class", "string", required=True, enum=calc.ROUTE_CLASSES),
    f("tow_away", "bool", required=True),
    f("tow_reason", "string", required=True, enum=calc.TOW_REASONS),
    f("injury_transported_count", "int", required=True, minimum=0),
    f("fatality_count", "int", required=True, minimum=0),
    f("hazmat_release", "bool", required=True),
    f("mechanical_factor", "bool", required=True),
    f("third_party_at_fault", "bool", required=True),
]


@bp.post("/crashes")
def create_crash():
    require("Dispatcher", "SafetyAdmin")
    values = read_body(CRASH_SPEC)
    driver = lookup("drivers", values["driver_id"])
    lookup("terminals", values["terminal_id"])
    occurred_at = values["occurred_at"]
    notified_at = given(values, "notified_at", db.now)
    if occurred_at > db.now:
        fail("ERR_FUTURE_TIMESTAMP", "occurred_at may not be in the future")
    if notified_at > db.now:
        fail("ERR_FUTURE_TIMESTAMP", "notified_at may not be in the future")
    if notified_at < occurred_at:
        fail("ERR_FUTURE_TIMESTAMP", "notified_at may not precede occurred_at")
    row = base_row()
    row["driver_id"] = driver["id"]
    row["terminal_id"] = driver["terminal_id"]
    row["occurred_at"] = occurred_at
    row["notified_at"] = db.now
    row["location_text"] = values["location_text"]
    row["severity"] = values["severity"]
    row["route_class"] = values["route_class"]
    row["tow_away"] = values["tow_away"]
    row["tow_reason"] = values["tow_reason"]
    row["injury_transported_count"] = values["injury_transported_count"]
    row["fatality_count"] = values["fatality_count"]
    row["hazmat_release"] = values["hazmat_release"]
    row["mechanical_factor"] = values["mechanical_factor"]
    row["third_party_at_fault"] = values["third_party_at_fault"]
    calc.apply_recordability(row)
    row["filing_reference"] = None
    row["filed_at"] = None
    row["preventability_status"] = "REPORTED"
    row["appeals_exhausted"] = False
    db.crashes[row["id"]] = row
    return created(serializers.crash(row))


@bp.get("/crashes/<entity_id>")
def read_crash(entity_id):
    require(*SAFETY_READ)
    return ok(serializers.crash(lookup("crashes", entity_id)))


@bp.get("/crashes")
def list_crashes():
    require(*SAFETY_READ)
    criteria = filters({
        "driver_id": None,
        "terminal_id": None,
        "preventability_status": calc.PREVENTABILITY,
        "reporting_status": calc.REPORTING_STATUSES,
        "route_class": calc.ROUTE_CLASSES,
        "severity": calc.SEVERITIES,
    })
    return paginate(filtered("crashes", criteria), serializers.crash)


@bp.post("/crashes/<entity_id>/regulatory-report")
def file_report(entity_id):
    require("SafetyManager")
    values = read_body([f("filing_reference", "string", required=True)])
    crash = lookup("crashes", entity_id)
    if not crash["dot_recordable"] or crash["reporting_status"] != "PENDING_FILING":
        fail("ERR_CRASH_STATE_INVALID",
             "This crash is not awaiting a regulatory filing")
    crash["filing_reference"] = values["filing_reference"]
    crash["filed_at"] = db.now
    crash["reporting_status"] = ("FILED" if db.now <= crash["report_due_at"]
                                 else "LATE_FILED")
    touch(crash)
    return ok(serializers.crash(crash))


# ---------------------------------------------------------------------------
# Driver statements
# ---------------------------------------------------------------------------
@bp.post("/crashes/<entity_id>/driver-statements")
def create_statement(entity_id):
    user_id, _role = require("Driver")
    driver = db.drivers.get(user_id)
    if driver is None:
        fail("ERR_UNAUTHORIZED",
             "X-User-ID does not identify an existing driver")
    crash = db.crashes.get(entity_id)
    if crash is not None and crash["driver_id"] != driver["id"]:
        fail("ERR_UNAUTHORIZED",
             "A driver may only file a statement about his own crash")
    values = read_body([
        f("narrative", "string", required=True, min_length=1, maximum=4000),
        f("conditions_note", "string"),
        f("attested", "bool", required=True),
    ])
    crash = lookup("crashes", entity_id)
    if not values["attested"]:
        fail("ERR_STATEMENT_NOT_ATTESTED",
             "A driver statement must be attested to be accepted")
    row = base_row(with_version=False)
    row["crash_id"] = crash["id"]
    row["narrative"] = values["narrative"]
    row["conditions_note"] = given(values, "conditions_note")
    row["attested"] = True
    row["submitted_by_driver_id"] = driver["id"]
    row["submitted_at"] = db.now
    db.driver_statements[row["id"]] = row
    return created(serializers.driver_statement(row))


@bp.get("/crashes/<entity_id>/driver-statements")
def list_statements(entity_id):
    require(*SAFETY_READ)
    crash = lookup("crashes", entity_id)
    return paginate(filtered("driver_statements", {"crash_id": crash["id"]}),
                    serializers.driver_statement)


# ---------------------------------------------------------------------------
# Evidence items
# ---------------------------------------------------------------------------
EVIDENCE_SPEC = [
    f("kind", "string", required=True, enum=calc.EVIDENCE_KINDS),
    f("source_device_id", "string", required=True),
    f("window_start_at", "instant", required=True),
    f("window_end_at", "instant", required=True),
    f("retention_deadline_at", "instant", required=True),
    f("evidence_hash", "string"),
]


@bp.post("/crashes/<entity_id>/evidence-items")
def create_evidence(entity_id):
    require("Dispatcher", "SafetyAdmin")
    values = read_body(EVIDENCE_SPEC)
    crash = lookup("crashes", entity_id)
    start = values["window_start_at"]
    end = values["window_end_at"]
    if start >= end:
        fail("ERR_EVIDENCE_WINDOW_CONFLICT",
             "window_start_at must be strictly earlier than window_end_at")
    if values["retention_deadline_at"] <= db.now:
        fail("ERR_EVIDENCE_WINDOW_CONFLICT",
             "retention_deadline_at must lie in the future")
    kind = values["kind"]
    if kind in calc.DUPLICATION_KINDS:
        for item in calc.crash_evidence_items(crash["id"]):
            if item["kind"] != kind:
                continue
            if item["preservation_state"] not in ("REQUESTED", "PRESERVED"):
                continue
            if start < item["window_end_at"] and item["window_start_at"] < end:
                fail("ERR_EVIDENCE_WINDOW_CONFLICT",
                     "An existing %s item already covers this window" % kind)
    row = base_row()
    row["crash_id"] = crash["id"]
    row["kind"] = kind
    row["source_device_id"] = values["source_device_id"]
    row["window_start_at"] = start
    row["window_end_at"] = end
    row["retention_deadline_at"] = values["retention_deadline_at"]
    row["preservation_state"] = "REQUESTED"
    row["evidence_hash"] = given(values, "evidence_hash")
    row["preserved_copy_uri"] = None
    row["preserved_at"] = None
    row["purge_reason"] = None
    db.evidence_items[row["id"]] = row
    return created(serializers.evidence_item(row))


@bp.get("/crashes/<entity_id>/evidence-items")
def list_crash_evidence(entity_id):
    require(*SAFETY_READ)
    crash = lookup("crashes", entity_id)
    criteria = filters({
        "kind": calc.EVIDENCE_KINDS,
        "preservation_state": calc.PRESERVATION_STATES,
    })
    criteria["crash_id"] = crash["id"]
    return paginate(filtered("evidence_items", criteria),
                    serializers.evidence_item)


@bp.get("/evidence-items/<entity_id>")
def read_evidence(entity_id):
    require(*SAFETY_READ)
    return ok(serializers.evidence_item(lookup("evidence_items", entity_id)))


@bp.get("/evidence-items")
def list_evidence():
    require(*SAFETY_READ)
    criteria = filters({
        "crash_id": None,
        "kind": calc.EVIDENCE_KINDS,
        "preservation_state": calc.PRESERVATION_STATES,
    })
    return paginate(filtered("evidence_items", criteria),
                    serializers.evidence_item)


@bp.post("/evidence-items/<entity_id>/preserve")
def preserve_evidence(entity_id):
    require("Dispatcher", "SafetyAdmin")
    values = read_body([
        f("preserved_copy_uri", "string", required=True),
        f("evidence_hash", "string", required=True),
    ])
    item = lookup("evidence_items", entity_id)
    if item["preservation_state"] != "REQUESTED":
        fail("ERR_EVIDENCE_ITEM_STATE_INVALID",
             "Only a REQUESTED evidence item may be preserved")
    if db.now > item["retention_deadline_at"]:
        fail("ERR_RETENTION_DEADLINE_PASSED",
             "The retention deadline for this artifact has already passed")
    item["preservation_state"] = "PRESERVED"
    item["preserved_copy_uri"] = values["preserved_copy_uri"]
    item["evidence_hash"] = values["evidence_hash"]
    item["preserved_at"] = db.now
    touch(item)
    return ok(serializers.evidence_item(item))


@bp.post("/evidence-items/<entity_id>/purge")
def purge_evidence(entity_id):
    require("SafetyAdmin")
    values = read_body([f("purge_reason", "string", required=True)])
    item = lookup("evidence_items", entity_id)
    state = item["preservation_state"]
    if state not in ("REQUESTED", "PRESERVED"):
        fail("ERR_EVIDENCE_ITEM_STATE_INVALID",
             "This evidence item has already been purged or released")
    if state == "PRESERVED":
        claim = claim_for_crash(item["crash_id"])
        if claim is not None and claim["handling_status"] != "CLOSED":
            fail("ERR_LITIGATION_HOLD_ACTIVE",
                 "The litigation hold on this artifact has not lifted")
        item["preservation_state"] = "RELEASED"
    else:
        item["preservation_state"] = "PURGED_BEFORE_HOLD"
    item["purge_reason"] = values["purge_reason"]
    touch(item)
    return ok(serializers.evidence_item(item))
