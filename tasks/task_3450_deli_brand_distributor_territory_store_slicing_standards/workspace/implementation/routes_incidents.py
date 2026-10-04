"""Incident endpoints (PRD SS3.8) and the unprefixed logical-clock endpoint."""
from flask import Blueprint, request

import store
from domain import incident_confirm_recall, incident_resolve, touch
from errors import fail
from serializers import ser_incident
from store import db
from util import (auth, body, list_response, new_id, ok, req_array, req_dt,
                  req_enum, req_str, sort_std)

bp = Blueprint("incidents", __name__)

INCIDENT_READERS = ("BrandAdmin", "PlantScheduler", "SafetyOfficer")
INCIDENT_STATES = {"REPORTED", "TRIAGED", "CONFIRMED_RECALL", "CONTAINED", "RESOLVED", "CLOSED"}
SEVERITIES = {"LOW", "HIGH", "CRITICAL"}

# Incident lifecycle: REPORTED -> TRIAGED -> CONFIRMED_RECALL -> CONTAINED ->
# RESOLVED -> CLOSED, plus TRIAGED -> CLOSED (early false alarm) and the
# cyclic CONTAINED -> TRIAGED reopen on new evidence.
ALLOWED_TRANSITIONS = {
    "REPORTED": {"TRIAGED"},
    "TRIAGED": {"CONFIRMED_RECALL", "CLOSED"},
    "CONFIRMED_RECALL": {"CONTAINED"},
    "CONTAINED": {"TRIAGED", "RESOLVED"},
    "RESOLVED": {"CLOSED"},
}


def _get_incident(iid):
    i = db["incidents"].get(iid)
    if i is None:
        fail("ERR_NOT_FOUND", 404, "incident not found")
    return i


@bp.post("/api/incidents")
def create_incident():
    auth("SafetyOfficer")
    b = body()
    plant_id = req_str(b, "plant_id")
    title = req_str(b, "title")
    severity = req_enum(b, "severity", SEVERITIES)
    affected = req_array(b, "affected_run_ids")
    for rid in affected:
        if not isinstance(rid, str):
            fail("ERR_VALIDATION", 400, "affected_run_ids must contain only strings")
    if db["plants"].get(plant_id) is None:
        fail("ERR_NOT_FOUND", 404, "plant not found")
    for rid in affected:
        if db["runs"].get(rid) is None:
            fail("ERR_NOT_FOUND", 404, "production run not found")
    now = store.now()
    i = {
        "id": new_id(), "_seq": store.next_seq(), "plant_id": plant_id,
        "title": title, "severity": severity,
        "affected_run_ids": list(affected),
        "status": "REPORTED", "resolution_outcome": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["incidents"][i["id"]] = i
    return ok(ser_incident(i), 201)


@bp.get("/api/incidents")
def list_incidents():
    auth(*INCIDENT_READERS)
    items = sort_std(db["incidents"].values())
    plant_id = request.args.get("plant_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    if plant_id is not None:
        items = [i for i in items if i["plant_id"] == plant_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    return list_response([ser_incident(i) for i in items])


@bp.get("/api/incidents/<iid>")
def get_incident(iid):
    auth(*INCIDENT_READERS)
    return ok(ser_incident(_get_incident(iid)))


@bp.post("/api/incidents/<iid>/transition")
def transition_incident(iid):
    auth("SafetyOfficer")
    b = body()
    to = req_enum(b, "to", INCIDENT_STATES)
    resolution_outcome = b.get("resolution_outcome")
    if resolution_outcome is not None and resolution_outcome not in ("CONFIRMED", "FALSE_ALARM"):
        fail("ERR_VALIDATION", 400, "resolution_outcome must be CONFIRMED or FALSE_ALARM")
    i = _get_incident(iid)
    if i["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", 409, "incident is CLOSED")
    if to not in ALLOWED_TRANSITIONS[i["status"]]:
        fail("ERR_INVALID_STATE", 409,
             "cannot transition incident from " + i["status"] + " to " + to)
    if to == "RESOLVED" and resolution_outcome is None:
        fail("ERR_VALIDATION", 400, "resolution_outcome is required when resolving")
    # cascades fire per transition; all are idempotent on entities already in
    # the target state, so repeated loops never double-apply an effect
    if i["status"] == "TRIAGED" and to == "CONFIRMED_RECALL":
        incident_confirm_recall(i)
    elif i["status"] == "CONTAINED" and to == "RESOLVED":
        incident_resolve(i, resolution_outcome)
    elif i["status"] == "TRIAGED" and to == "CLOSED":
        i["resolution_outcome"] = "FALSE_ALARM"  # early false alarm
    i["status"] = to
    touch(i)
    return ok(ser_incident(i))


# ---------------------------------------------------------------------------
# logical clock — UNPREFIXED (not under /api); startup default is exactly
# 2026-09-01T00:00:00Z and never falls back to wall-clock time (PRD SS2.5)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth("BrandAdmin")
    b = body()
    to = req_dt(b, "to_iso8601")
    store.set_clock(to)
    return ok({}, 200)
