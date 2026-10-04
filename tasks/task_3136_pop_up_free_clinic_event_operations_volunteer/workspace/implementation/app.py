#!/usr/bin/env python3
"""Pop-Up Free Clinic Event Operations & Volunteer Licensing API.

Flask implementation generated from PRD.md + SCAFFOLD.yaml.
In-memory store; the store starts empty on every boot.
"""

import os
import re
import uuid
import threading
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from functools import wraps

from flask import Flask, request, jsonify

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

ROLES = {
    "EventDirector", "LogisticsCoordinator", "VolunteerCoordinator",
    "CredentialingOfficer", "QueueMarshal", "StationLead",
    "SterilizationTech", "CommunityPartnerRep", "PlatformAdmin",
}

POSTURES = ["PLANNING", "SITE_LOCKED", "STAFFING", "READY", "IN_SERVICE",
            "TEARDOWN", "CLOSED", "CANCELLED"]

SITE_TYPES = {"ARENA", "FAIRGROUND", "SCHOOL"}
DISCIPLINES = {"DENTAL", "VISION", "MEDICAL", "GENERAL"}
SHIFT_CODES = {"FULL_DAY", "MORNING", "AFTERNOON"}
STATION_TYPES = {"TRIAGE", "DENTAL", "VISION", "MEDICAL", "GLASSES_LAB", "DENTURE_LAB"}
REQUESTED_SERVICES = {"DENTAL", "VISION", "MEDICAL"}
PRIORITY_TIERS = {"STANDARD", "VULNERABLE"}
ENCOUNTER_TYPES = {"TRIAGE", "EXTRACTION", "DENTURE_FIT", "EYE_EXAM",
                   "GLASSES_DISPENSE", "MEDICAL_CONSULT"}
REFERRAL_TYPES = {"DENTAL_FOLLOWUP", "VISION_FOLLOWUP", "MEDICAL_FOLLOWUP", "URGENT_CARE"}
URGENCIES = {"ROUTINE", "URGENT", "EMERGENT"}
DENIAL_CODES = {"LICENSE_EXPIRED", "STATE_MISMATCH", "UNVERIFIABLE", "DISCIPLINE_MISMATCH"}
TERMINAL_DENIAL_CODES = {"UNVERIFIABLE", "DISCIPLINE_MISMATCH"}
REPORT_VARIANTS = {"OBSERVED_ONLY", "WITH_EXTRAPOLATION"}

SITE_BASE_COST_CENTS = {"ARENA": 800000, "FAIRGROUND": 500000, "SCHOOL": 300000}
COVERAGE_MIN = Decimal("60")
WEIGHTS = {"DENTAL": Decimal("0.5"), "VISION": Decimal("0.3"), "MEDICAL": Decimal("0.2")}
AUTOCLAVE_BATCH_MAX = 24
STERILIZATION_BACKLOG_MAX = 6

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.sites = {}
        self.events = {}
        self.agreements = {}
        self.volunteers = {}
        self.verifications = {}
        self.assignments = {}
        self.stations = {}
        self.tickets = {}
        self.encounters = {}
        self.referrals = {}
        self.manifests = {}
        self.cycles = {}
        self.reports = {}
        self.handoffs = {}
        self.clock = None  # initialized after time helpers are defined


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------


def _parse_ts(s):
    if not isinstance(s, str):
        raise ValueError("not a timestamp")
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _try_parse_ts(s):
    try:
        return _parse_ts(s)
    except Exception:
        return None


def _parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def _try_parse_date(s):
    try:
        return _parse_date(s)
    except Exception:
        return None


def _fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return _fmt(db.clock)


db = Store()
db.clock = _parse_ts(DEFAULT_CLOCK)


# --------------------------------------------------------------------------
# Errors and envelope
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None, is_list=False):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_VALIDATION", 400, "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field, default=""):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, f"Field '{field}' must be a string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_VALIDATION", 400, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 400, f"Field '{field}' is required and must be an integer")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field '{field}' is required and must be a boolean")
    return v


def req_num(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 400, f"Field '{field}' is required and must be a number")
    return v


def parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def list_response(items, serializer):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serializer(r) for r in page], pagination=pagination, is_list=True)


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not isinstance(user_id, str):
                err("ERR_UNAUTHENTICATED", 401, "X-User-ID header is required")
            if not role or role not in ROLES:
                err("ERR_UNAUTHENTICATED", 401, "X-User-Role header is missing or unrecognized")
            if role not in roles:
                err("ERR_UNAUTHORIZED", 403, f"Role {role} is not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return deco


ALL_ROLES = tuple(sorted(ROLES))

# --------------------------------------------------------------------------
# Entity helpers
# --------------------------------------------------------------------------


def new_id():
    return uuid.uuid4().hex


def base_record(common=True):
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def get_event_or_404(eid):
    ev = db.events.get(eid)
    if ev is None:
        err("ERR_NOT_FOUND", 404, f"ClinicEvent {eid} not found")
    return ev


def child_or_404(table, cid, label):
    rec = table.get(cid)
    if rec is None:
        err("ERR_NOT_FOUND", 404, f"{label} {cid} not found")
    return rec


def check_belongs(rec, fk_field, parent_id, label):
    if rec.get(fk_field) != parent_id:
        err("ERR_REFERENCE_INVALID", 422, f"{label} does not belong to the addressed parent")


def event_children(table, event_id, fk="clinic_event_id"):
    return [r for r in table.values() if r.get(fk) == event_id]


def bump_event(ev):
    touch(ev)


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------


def host_cost_share(site, liability_cap_cents=None):
    """Waterfall cost share. Uncapped (provisional) when liability_cap_cents is None."""
    base = SITE_BASE_COST_CENTS[site["site_type"]]
    sqft = site["square_footage"]
    tier2 = Decimal(min(max(sqft - 10000, 0), 20000)) / Decimal(20000)
    tier3 = Decimal(1) if sqft >= 30000 else Decimal(0)
    surcharge = (Decimal(base) * (Decimal("0.15") * tier2 + Decimal("0.25") * tier3)
                 ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    raw = base + int(surcharge)
    if liability_cap_cents is None:
        return raw
    return min(raw, liability_cap_cents)


def _station_window_minutes_fraction(s):
    open_ts = _parse_ts(s["service_window_open_utc"])
    close_ts = _parse_ts(s["service_window_close_utc"])
    micros = int((close_ts - open_ts).total_seconds() * 1_000_000)
    return Fraction(micros, 60 * 1_000_000)


def projected_servable(ev, optimistic=False):
    total = 0
    for disc in ("DENTAL", "VISION", "MEDICAL"):
        for s in event_children(db.stations, ev["id"]):
            if s["station_type"] != disc or s["status"] not in ("OPERATIONAL", "DEGRADED"):
                continue
            if s["status"] == "OPERATIONAL" or optimistic:
                eff = s["chair_count"]
            else:
                eff = s["chair_count"] // 2
            window = _station_window_minutes_fraction(s)
            per = Fraction(eff) * window / s["minutes_per_patient"]
            total += per.numerator // per.denominator
    return total


def discipline_coverage_score(ev):
    score = Decimal("0")
    for disc in ("DENTAL", "VISION", "MEDICAL"):
        auth = 0
        for v in db.volunteers.values():
            if v["status"] != "AUTHORIZED" or v["discipline"] != disc:
                continue
            if any(a for a in event_children(db.assignments, ev["id"])
                   if a["volunteer_id"] == v["id"]
                   and a["status"] in ("ROSTERED", "CONFIRMED", "CHECKED_IN")):
                auth += 1
        stations = sum(1 for s in event_children(db.stations, ev["id"])
                       if s["station_type"] == disc
                       and s["status"] in ("SET_UP", "STERILIZATION_CLEARED",
                                           "OPERATIONAL", "DEGRADED"))
        coverage = min(Decimal(auth) / Decimal(max(stations, 1)), Decimal("1"))
        score += WEIGHTS[disc] * coverage
    return (score * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sterilization_pending_batches(ev):
    return sum(c["instrument_batch_size"] for c in event_children(db.cycles, ev["id"])
               if c["status"] in ("RUNNING", "FAILED"))


def sterilization_completed_count(ev):
    return sum(1 for c in event_children(db.cycles, ev["id"]) if c["status"] == "COMPLETED")


# --------------------------------------------------------------------------
# Posture recompute and derived reconciliation
# --------------------------------------------------------------------------


def recompute_derived(ev):
    """Recompute posture + projected_servable after any child mutation. Does NOT bump
    version itself; callers bump the event once per mutation."""
    p = ev["posture"]
    if p == "PLANNING":
        if any(a for a in event_children(db.agreements, ev["id"]) if a["status"] == "CONFIRMED"):
            ev["posture"] = "SITE_LOCKED"
            p = "SITE_LOCKED"
    if p == "SITE_LOCKED":
        has_station = any(event_children(db.stations, ev["id"]))
        has_verif = any(event_children(db.verifications, ev["id"]))
        if has_station and has_verif:
            ev["posture"] = "STAFFING"
            p = "STAFFING"
    if p == "STAFFING":
        if _ready_gates_pass(ev):
            ev["posture"] = "READY"
            p = "READY"
    elif p == "READY":
        if not _ready_gates_pass(ev):
            ev["posture"] = "STAFFING"
            p = "STAFFING"
    ev["projected_servable_patients"] = projected_servable(ev)


def _ready_gates_pass(ev):
    if any(s for s in event_children(db.stations, ev["id"]) if s["status"] == "PLANNED"):
        return False
    if any(v for v in event_children(db.verifications, ev["id"]) if v["status"] == "PENDING"):
        return False
    return discipline_coverage_score(ev) >= COVERAGE_MIN


def degrade_check(ev):
    """Apply sterilization backlog thresholds to requires_sterilization stations."""
    pending = sterilization_pending_batches(ev)
    for s in event_children(db.stations, ev["id"]):
        if not s.get("requires_sterilization"):
            continue
        if s["status"] == "OPERATIONAL" and pending > STERILIZATION_BACKLOG_MAX:
            s["status"] = "DEGRADED"
            touch(s)
        elif s["status"] == "DEGRADED" and pending <= STERILIZATION_BACKLOG_MAX:
            s["status"] = "OPERATIONAL"
            touch(s)


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------


def serialize_event(ev):
    eid = ev["id"]
    stations = event_children(db.stations, eid)
    tickets = event_children(db.tickets, eid)
    return {
        "id": eid,
        "event_code": ev["event_code"],
        "name": ev["name"],
        "host_state_code": ev["host_state_code"],
        "service_date": ev["service_date"],
        "doors_open_utc": ev["doors_open_utc"],
        "total_patient_capacity": ev["total_patient_capacity"],
        "posture": ev["posture"],
        "confirmed_site_agreement_id": ev["confirmed_site_agreement_id"],
        "dental_chair_count": sum(s["chair_count"] for s in stations
                                  if s["station_type"] == "DENTAL" and s["status"] == "OPERATIONAL"),
        "vision_lane_count": sum(s["chair_count"] for s in stations
                                 if s["station_type"] == "VISION" and s["status"] == "OPERATIONAL"),
        "medical_bay_count": sum(s["chair_count"] for s in stations
                                 if s["station_type"] == "MEDICAL" and s["status"] == "OPERATIONAL"),
        "verified_volunteer_count": sum(
            1 for v in db.volunteers.values()
            if v["status"] == "AUTHORIZED" and any(
                a for a in event_children(db.assignments, eid)
                if a["volunteer_id"] == v["id"] and a["status"] == "CONFIRMED")),
        "tickets_issued_count": sum(1 for t in tickets
                                    if t["status"] in ("QUEUED", "CALLED", "IN_SERVICE")),
        "tickets_served_count": sum(1 for t in tickets if t["status"] == "SERVED"),
        "unmet_demand_count": sum(1 for t in tickets if t["status"] == "TURNED_AWAY"),
        "projected_servable_patients": ev.get("projected_servable_patients", 0),
        "sterilization_cycles_completed": sterilization_completed_count(ev),
        "created_at": ev["created_at"],
        "updated_at": ev["updated_at"],
        "version": ev["version"],
    }


def serialize_site(s):
    return {k: s[k] for k in ("id", "site_name", "site_type", "state_code",
                              "square_footage", "has_loading_dock", "power_capacity_kw",
                              "sterilization_capable", "status",
                              "created_at", "updated_at", "version")}


def serialize_agreement(a):
    return {k: a[k] for k in ("id", "clinic_event_id", "site_id", "host_org_name",
                              "liability_cap_cents", "insurance_certificate_ref",
                              "cost_share_cents", "status", "supersedes_agreement_id",
                              "created_at", "updated_at", "version")}


def serialize_volunteer(v):
    return {k: v[k] for k in ("id", "full_name", "email", "discipline", "license_number",
                              "license_state_code", "license_expiry_date", "status",
                              "suspension_reason", "created_at", "updated_at", "version")}


def serialize_verification(v):
    return {k: v[k] for k in ("id", "volunteer_id", "clinic_event_id", "reviewer_notes",
                              "attempt_sequence", "status", "denial_code",
                              "created_at", "updated_at", "version")}


def serialize_assignment(a):
    return {k: a[k] for k in ("id", "clinic_event_id", "volunteer_id", "station_id",
                              "shift_code", "status",
                              "created_at", "updated_at", "version")}


def serialize_station(s):
    served = sum(1 for e in db.encounters.values()
                 if e.get("station_id") == s["id"] and e["status"] == "COMPLETED")
    return {
        "id": s["id"],
        "clinic_event_id": s["clinic_event_id"],
        "station_label": s["station_label"],
        "station_type": s["station_type"],
        "chair_count": s["chair_count"],
        "minutes_per_patient": s["minutes_per_patient"],
        "requires_sterilization": s["requires_sterilization"],
        "service_window_open_utc": s["service_window_open_utc"],
        "service_window_close_utc": s["service_window_close_utc"],
        "status": s["status"],
        "served_count": served,
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_ticket(t):
    return {k: t[k] for k in ("id", "clinic_event_id", "patient_ref", "arrival_utc",
                              "requested_service", "priority_tier", "queue_position",
                              "status", "turn_away_reason",
                              "created_at", "updated_at", "version")}


def serialize_encounter(e):
    return {k: e[k] for k in ("id", "clinic_event_id", "ticket_id", "station_id",
                              "volunteer_id", "encounter_type", "findings_summary",
                              "requires_followup", "status",
                              "created_at", "updated_at", "version")}


def serialize_referral(r):
    return {k: r[k] for k in ("id", "encounter_id", "clinic_event_id", "referral_type",
                              "partner_org_name", "urgency", "notes", "created_at")}


def serialize_manifest(m):
    return {k: m[k] for k in ("id", "clinic_event_id", "manifest_label", "item_count",
                              "weight_kg", "requires_loading_dock", "contains_sterilizer",
                              "status", "created_at", "updated_at", "version")}


def serialize_cycle(c):
    return {k: c[k] for k in ("id", "clinic_event_id", "cycle_sequence",
                              "instrument_batch_size", "started_utc", "completed_utc",
                              "status", "created_at", "updated_at", "version")}


def serialize_report(r):
    return {k: r[k] for k in ("id", "clinic_event_id", "generated_at_utc",
                              "turned_away_count", "estimated_unserved_beyond_queue",
                              "projected_shortfall_patients", "report_variant", "created_at")}


def serialize_handoff(h):
    return {k: h[k] for k in ("id", "clinic_event_id", "partner_org_name",
                              "referral_packet_count", "teardown_checklist_complete",
                              "status", "created_at", "updated_at", "version")}


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION", 400, str(e)))


@app.before_request
def _lock():
    db.lock.acquire()


@app.after_request
def _unlock(resp):
    try:
        db.lock.release()
    except RuntimeError:
        pass
    return resp


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


@app.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    target = body.get("to_iso8601")
    ts = _try_parse_ts(target)
    if ts is None:
        err("ERR_VALIDATION", 400, "to_iso8601 must be an ISO-8601 timestamp")
    db.clock = ts
    # Expire PENDING verifications whose event service_date has passed.
    for v in db.verifications.values():
        if v["status"] != "PENDING":
            continue
        ev = db.events.get(v["clinic_event_id"])
        if ev is None:
            continue
        sd = _try_parse_date(ev["service_date"])
        if sd is not None and db.clock.date() > sd:
            v["status"] = "EXPIRED_REVIEW"
            touch(v)
    return ok({"current_utc": _fmt(db.clock)})


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------


@app.post("/sites")
@require_roles("LogisticsCoordinator")
def create_site():
    body = get_body()
    site_name = req_str(body, "site_name")
    site_type = req_enum(body, "site_type", SITE_TYPES)
    state_code = req_str(body, "state_code")
    square_footage = req_int(body, "square_footage")
    has_loading_dock = req_bool(body, "has_loading_dock")
    power_capacity_kw = req_num(body, "power_capacity_kw")
    sterilization_capable = req_bool(body, "sterilization_capable")
    rec = base_record()
    rec.update({
        "site_name": site_name, "site_type": site_type, "state_code": state_code,
        "square_footage": square_footage, "has_loading_dock": has_loading_dock,
        "power_capacity_kw": power_capacity_kw,
        "sterilization_capable": sterilization_capable,
        "status": "PROSPECT",
    })
    db.sites[rec["id"]] = rec
    return ok(serialize_site(rec), status=201)


@app.get("/sites")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def list_sites():
    items = list(db.sites.values())
    for f in ("site_type", "state_code", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s[f] == val]
    return list_response(items, serialize_site)


@app.get("/sites/<sid>")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def get_site(sid):
    return ok(serialize_site(child_or_404(db.sites, sid, "Site")))


@app.post("/sites/<sid>/vet")
@require_roles("LogisticsCoordinator")
def vet_site(sid):
    site = child_or_404(db.sites, sid, "Site")
    if site["status"] != "PROSPECT":
        err("ERR_INVALID_STATE", 409, "Site must be PROSPECT to vet")
    if site["square_footage"] < 2000:
        err("ERR_SITE_TOO_SMALL", 422, "Site square_footage must be >= 2000")
    if not (site["power_capacity_kw"] > 0):
        err("ERR_VALIDATION", 400, "Site power_capacity_kw must be > 0")
    site["status"] = "VETTED"
    touch(site)
    return ok(serialize_site(site))


@app.post("/sites/<sid>/retire")
@require_roles("LogisticsCoordinator")
def retire_site(sid):
    site = child_or_404(db.sites, sid, "Site")
    if site["status"] != "VETTED":
        err("ERR_INVALID_STATE", 409, "Site must be VETTED to retire")
    if any(a for a in db.agreements.values()
           if a["site_id"] == sid and a["status"] in ("DRAFT", "NEGOTIATING", "CONFIRMED")):
        err("ERR_SITE_IN_USE", 422, "Site is referenced by live agreements")
    site["status"] = "RETIRED"
    touch(site)
    return ok(serialize_site(site))


# --------------------------------------------------------------------------
# Clinic events
# --------------------------------------------------------------------------


@app.post("/clinic-events")
@require_roles("EventDirector")
def create_event():
    body = get_body()
    event_code = req_str(body, "event_code")
    name = req_str(body, "name")
    host_state_code = req_str(body, "host_state_code")
    service_date = req_str(body, "service_date")
    if _try_parse_date(service_date) is None:
        err("ERR_VALIDATION", 400, "service_date must be an ISO-8601 date (YYYY-MM-DD)")
    doors_open_utc = req_str(body, "doors_open_utc")
    if _try_parse_ts(doors_open_utc) is None:
        err("ERR_VALIDATION", 400, "doors_open_utc must be an ISO-8601 timestamp")
    total_patient_capacity = req_int(body, "total_patient_capacity")
    if total_patient_capacity < 1:
        err("ERR_VALIDATION", 400, "total_patient_capacity must be >= 1")
    rec = base_record()
    rec.update({
        "event_code": event_code, "name": name, "host_state_code": host_state_code,
        "service_date": service_date, "doors_open_utc": doors_open_utc,
        "total_patient_capacity": total_patient_capacity,
        "posture": "PLANNING",
        "confirmed_site_agreement_id": None,
        "projected_servable_patients": 0,
        "_max_queue_position": 0,
        "_cycle_sequence": 0,
    })
    db.events[rec["id"]] = rec
    return ok(serialize_event(rec), status=201)


@app.get("/clinic-events")
@require_roles(*ALL_ROLES)
def list_events():
    items = list(db.events.values())
    posture = request.args.get("posture")
    if posture is not None:
        items = [e for e in items if e["posture"] == posture]
    hsc = request.args.get("host_state_code")
    if hsc is not None:
        items = [e for e in items if e["host_state_code"] == hsc]
    return list_response(items, serialize_event)


@app.get("/clinic-events/<eid>")
@require_roles(*ALL_ROLES)
def get_event(eid):
    return ok(serialize_event(get_event_or_404(eid)))


def _posture_gate(ev, allowed):
    if ev["posture"] not in allowed:
        err("ERR_EVENT_POSTURE_FORBIDS", 409,
            f"Event posture {ev['posture']} does not permit this operation")


def _event_state_gate(ev, allowed):
    # The event's own posture moves (open-doors, end-service, close, cancel)
    # fail their from-state check with ERR_INVALID_STATE, not the posture
    # gate — the posture gate applies to *child* operations gated on the
    # parent event's posture.
    if ev["posture"] not in allowed:
        err("ERR_INVALID_STATE", 409,
            f"Event posture {ev['posture']} does not permit this transition")


@app.post("/clinic-events/<eid>/open-doors")
@require_roles("EventDirector")
def open_doors(eid):
    ev = get_event_or_404(eid)
    _event_state_gate(ev, ("READY",))
    if any(m for m in event_children(db.manifests, eid) if m["status"] != "UNPACKED"):
        err("ERR_MANIFEST_NOT_UNPACKED", 422, "Every manifest must be UNPACKED before doors open")
    needs_ster = [s for s in event_children(db.stations, eid)
                  if s.get("requires_sterilization") and s["station_type"] in ("DENTAL", "MEDICAL")]
    if needs_ster and sterilization_completed_count(ev) < 1:
        err("ERR_STERILIZATION_NOT_CLEARED", 422,
            "Sterilization-requiring stations need a COMPLETED cycle before doors open")
    ev["posture"] = "IN_SERVICE"
    ev["projected_servable_patients"] = projected_servable(ev)
    bump_event(ev)
    return ok(serialize_event(ev))


@app.post("/clinic-events/<eid>/end-service")
@require_roles("EventDirector")
def end_service(eid):
    ev = get_event_or_404(eid)
    _event_state_gate(ev, ("IN_SERVICE",))
    if any(t for t in event_children(db.tickets, eid) if t["status"] in ("CALLED", "IN_SERVICE")):
        err("ERR_ACTIVE_ENCOUNTERS_REMAIN", 422,
            "Tickets remain CALLED or IN_SERVICE")
    for t in event_children(db.tickets, eid):
        if t["status"] == "QUEUED":
            t["status"] = "TURNED_AWAY"
            t["turn_away_reason"] = "EVENT_ENDED"
            touch(t)
    ev["posture"] = "TEARDOWN"
    bump_event(ev)
    return ok(serialize_event(ev))


@app.post("/clinic-events/<eid>/close")
@require_roles("EventDirector")
def close_event(eid):
    ev = get_event_or_404(eid)
    _event_state_gate(ev, ("TEARDOWN",))
    if any(s for s in event_children(db.stations, eid) if s["status"] != "DISMANTLED"):
        err("ERR_STATIONS_NOT_DISMANTLED", 422, "Every station must be DISMANTLED")
    if any(m for m in event_children(db.manifests, eid) if m["status"] != "REPACKED"):
        err("ERR_MANIFEST_NOT_REPACKED", 422, "Every manifest must be REPACKED")
    if not any(h for h in event_children(db.handoffs, eid) if h["status"] == "ACCEPTED"):
        err("ERR_HANDOFF_NOT_ACCEPTED", 422, "An ACCEPTED CommunityHandoff is required")
    ev["posture"] = "CLOSED"
    bump_event(ev)
    return ok(serialize_event(ev))


@app.post("/clinic-events/<eid>/cancel")
@require_roles("EventDirector")
def cancel_event(eid):
    ev = get_event_or_404(eid)
    _event_state_gate(ev, ("PLANNING", "SITE_LOCKED", "STAFFING", "READY"))
    for a in event_children(db.agreements, eid):
        if a["status"] in ("DRAFT", "NEGOTIATING", "CONFIRMED"):
            a["status"] = "REJECTED"
            touch(a)
    ev["confirmed_site_agreement_id"] = None
    for a in event_children(db.assignments, eid):
        if a["status"] in ("ROSTERED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)
    ev["posture"] = "CANCELLED"
    bump_event(ev)
    return ok(serialize_event(ev))


# --------------------------------------------------------------------------
# Site agreements
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/site-agreements")
@require_roles("LogisticsCoordinator")
def create_agreement(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    site_id = req_str(body, "site_id")
    host_org_name = req_str(body, "host_org_name")
    liability_cap_cents = req_int(body, "liability_cap_cents")
    insurance_certificate_ref = opt_str(body, "insurance_certificate_ref", "")
    expected_event_version = body.get("expected_event_version")
    if isinstance(expected_event_version, bool) or not isinstance(expected_event_version, int):
        err("ERR_VALIDATION", 400, "expected_event_version is required and must be an integer")
    supersedes = body.get("supersedes_agreement_id")

    # Referential integrity
    site = db.sites.get(site_id)
    if site is None:
        err("ERR_REFERENCE_INVALID", 422, f"Site {site_id} does not exist")
    if supersedes is not None:
        prior = db.agreements.get(supersedes)
        if (prior is None or prior["clinic_event_id"] != eid
                or prior["status"] != "CONFIRMED"):
            err("ERR_REFERENCE_INVALID", 422,
                "supersedes_agreement_id must reference a CONFIRMED agreement of this event")
    # Fiscal
    if liability_cap_cents < 0:
        err("ERR_FISCAL_RULE_VIOLATION", 422, "liability_cap_cents must be >= 0")
    # OCC (checked last)
    if expected_event_version != ev["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_event_version does not match the current event version")

    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "site_id": site_id,
        "host_org_name": host_org_name,
        "liability_cap_cents": liability_cap_cents,
        "insurance_certificate_ref": insurance_certificate_ref,
        "cost_share_cents": host_cost_share(site, None),  # provisional, uncapped
        "status": "DRAFT",
        "supersedes_agreement_id": supersedes,
    })
    db.agreements[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_agreement(rec), status=201)


@app.get("/clinic-events/<eid>/site-agreements")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def list_agreements_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.agreements, eid)
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, serialize_agreement)


@app.get("/site-agreements")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def list_agreements():
    items = list(db.agreements.values())
    for f in ("clinic_event_id", "site_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a[f] == val]
    return list_response(items, serialize_agreement)


def _get_agreement(eid, aid):
    ev = get_event_or_404(eid)
    ag = child_or_404(db.agreements, aid, "SiteAgreement")
    check_belongs(ag, "clinic_event_id", eid, "SiteAgreement")
    return ev, ag


@app.post("/clinic-events/<eid>/site-agreements/<aid>/submit")
@require_roles("LogisticsCoordinator")
def submit_agreement(eid, aid):
    ev, ag = _get_agreement(eid, aid)
    _posture_gate(ev, ("PLANNING", "SITE_LOCKED"))
    if ag["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Agreement must be DRAFT to submit")
    ag["status"] = "NEGOTIATING"
    touch(ag)
    return ok(serialize_agreement(ag))


@app.post("/clinic-events/<eid>/site-agreements/<aid>/confirm")
@require_roles("EventDirector")
def confirm_agreement(eid, aid):
    ev, ag = _get_agreement(eid, aid)
    if ag["status"] != "NEGOTIATING":
        err("ERR_INVALID_STATE", 409, "Agreement must be NEGOTIATING to confirm")
    site = db.sites.get(ag["site_id"])
    if site is None or site["status"] != "VETTED":
        err("ERR_SITE_NOT_VETTED", 422, "Referenced site must be VETTED")
    if site["state_code"] != ev["host_state_code"]:
        err("ERR_SITE_STATE_MISMATCH", 422,
            "Site state_code differs from event host_state_code")
    if not ag["insurance_certificate_ref"]:
        err("ERR_INSURANCE_MISSING", 422, "insurance_certificate_ref must be non-empty")
    _posture_gate(ev, ("PLANNING", "SITE_LOCKED"))

    ag["cost_share_cents"] = host_cost_share(site, ag["liability_cap_cents"])
    prior_id = ag.get("supersedes_agreement_id")
    if prior_id:
        prior = db.agreements.get(prior_id)
        if prior is not None and prior["status"] == "CONFIRMED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    ag["status"] = "CONFIRMED"
    touch(ag)
    ev["confirmed_site_agreement_id"] = ag["id"]
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_agreement(ag))


@app.post("/clinic-events/<eid>/site-agreements/<aid>/reject")
@require_roles("EventDirector")
def reject_agreement(eid, aid):
    ev, ag = _get_agreement(eid, aid)
    if ag["status"] != "NEGOTIATING":
        err("ERR_INVALID_STATE", 409, "Agreement must be NEGOTIATING to reject")
    ag["status"] = "REJECTED"
    touch(ag)
    return ok(serialize_agreement(ag))


# --------------------------------------------------------------------------
# Volunteers & licensing
# --------------------------------------------------------------------------


@app.post("/volunteers")
@require_roles("VolunteerCoordinator")
def create_volunteer():
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    discipline = req_enum(body, "discipline", DISCIPLINES)
    license_number = opt_str(body, "license_number", "")
    license_state_code = opt_str(body, "license_state_code", "")
    license_expiry_date = opt_str(body, "license_expiry_date", "")
    if license_expiry_date and _try_parse_date(license_expiry_date) is None:
        err("ERR_VALIDATION", 400, "license_expiry_date must be an ISO-8601 date")
    if any(v for v in db.volunteers.values() if v["email"] == email):
        err("ERR_DUPLICATE_EMAIL", 409, "Volunteer email already registered")
    rec = base_record()
    rec.update({
        "full_name": full_name, "email": email, "discipline": discipline,
        "license_number": license_number, "license_state_code": license_state_code,
        "license_expiry_date": license_expiry_date,
        "status": "REGISTERED",
        "suspension_reason": None,
        "_prev_status": None,
    })
    db.volunteers[rec["id"]] = rec
    return ok(serialize_volunteer(rec), status=201)


@app.get("/volunteers")
@require_roles("VolunteerCoordinator", "CredentialingOfficer", "EventDirector", "PlatformAdmin")
def list_volunteers():
    items = list(db.volunteers.values())
    for f in ("discipline", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [v for v in items if v[f] == val]
    return list_response(items, serialize_volunteer)


@app.get("/volunteers/<vid>")
@require_roles("VolunteerCoordinator", "CredentialingOfficer", "EventDirector", "PlatformAdmin")
def get_volunteer(vid):
    return ok(serialize_volunteer(child_or_404(db.volunteers, vid, "Volunteer")))


@app.post("/volunteers/<vid>/request-verification")
@require_roles("VolunteerCoordinator")
def request_verification(vid):
    vol = child_or_404(db.volunteers, vid, "Volunteer")
    body = get_body()
    event_id = req_str(body, "clinic_event_id")
    reviewer_notes = opt_str(body, "reviewer_notes", "")
    if vol["status"] not in ("REGISTERED", "VERIFIED"):
        err("ERR_INVALID_STATE", 409,
            "Volunteer must be REGISTERED or VERIFIED to request verification")
    ev = db.events.get(event_id)
    if ev is None:
        err("ERR_REFERENCE_INVALID", 422, f"ClinicEvent {event_id} does not exist")
    if vol["discipline"] != "GENERAL" and (
            not vol["license_number"] or not vol["license_state_code"]
            or not vol["license_expiry_date"]):
        err("ERR_LICENSE_FIELDS_REQUIRED", 422,
            "Clinical volunteers must supply license_number, license_state_code, license_expiry_date")
    attempt = 1 + sum(1 for v in db.verifications.values()
                      if v["volunteer_id"] == vid and v["clinic_event_id"] == event_id)
    rec = base_record()
    rec.update({
        "volunteer_id": vid,
        "clinic_event_id": event_id,
        "reviewer_notes": reviewer_notes,
        "attempt_sequence": attempt,
        "status": "PENDING",
        "denial_code": None,
    })
    db.verifications[rec["id"]] = rec
    vol["_prev_status"] = vol["status"]
    vol["status"] = "VERIFICATION_PENDING"
    touch(vol)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_verification(rec), status=201)


@app.get("/volunteers/<vid>/license-verifications")
@require_roles("VolunteerCoordinator", "CredentialingOfficer", "PlatformAdmin")
def list_verifications_for_volunteer(vid):
    child_or_404(db.volunteers, vid, "Volunteer")
    items = [v for v in db.verifications.values() if v["volunteer_id"] == vid]
    for f in ("clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [v for v in items if v[f] == val]
    return list_response(items, serialize_verification)


@app.get("/license-verifications")
@require_roles("VolunteerCoordinator", "CredentialingOfficer", "PlatformAdmin")
def list_verifications():
    items = list(db.verifications.values())
    for f in ("volunteer_id", "clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [v for v in items if v[f] == val]
    return list_response(items, serialize_verification)


def _get_verification(vid, lv_id):
    vol = child_or_404(db.volunteers, vid, "Volunteer")
    ver = child_or_404(db.verifications, lv_id, "LicenseVerification")
    check_belongs(ver, "volunteer_id", vid, "LicenseVerification")
    return vol, ver


def _resolve_denial(vol):
    if False:
        pass


@app.post("/volunteers/<vid>/license-verifications/<lv_id>/approve")
@require_roles("CredentialingOfficer")
def approve_verification(vid, lv_id):
    vol, ver = _get_verification(vid, lv_id)
    if ver["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Verification must be PENDING to approve")
    ev = db.events.get(ver["clinic_event_id"])
    # Auto-deny when the license is expired relative to the event service date.
    svc = _try_parse_date(ev["service_date"]) if ev else None
    exp = _try_parse_date(vol["license_expiry_date"])
    if vol["discipline"] != "GENERAL" and svc is not None and (
            exp is None or not (exp > svc)):
        ver["status"] = "DENIED"
        ver["denial_code"] = "LICENSE_EXPIRED"
        touch(ver)
        vol["status"] = vol.get("_prev_status") or "REGISTERED"
        touch(vol)
        if ev is not None:
            recompute_derived(ev)
            bump_event(ev)
        return ok(serialize_verification(ver))
    ver["status"] = "APPROVED"
    touch(ver)
    vol["status"] = "VERIFIED"
    vol["_prev_status"] = None
    touch(vol)
    if ev is not None:
        recompute_derived(ev)
        bump_event(ev)
    return ok(serialize_verification(ver))


@app.post("/volunteers/<vid>/license-verifications/<lv_id>/deny")
@require_roles("CredentialingOfficer")
def deny_verification(vid, lv_id):
    vol, ver = _get_verification(vid, lv_id)
    if ver["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Verification must be PENDING to deny")
    body = get_body()
    code = body.get("denial_code")
    if code not in DENIAL_CODES:
        err("ERR_VALIDATION", 400, "denial_code must be one of the declared codes")
    ver["status"] = "DENIED"
    ver["denial_code"] = code
    touch(ver)
    if code in TERMINAL_DENIAL_CODES:
        vol["status"] = "REJECTED"
    else:
        vol["status"] = vol.get("_prev_status") or "REGISTERED"
    vol["_prev_status"] = None
    touch(vol)
    ev = db.events.get(ver["clinic_event_id"])
    if ev is not None:
        recompute_derived(ev)
        bump_event(ev)
    return ok(serialize_verification(ver))


@app.post("/volunteers/<vid>/authorize")
@require_roles("VolunteerCoordinator")
def authorize_volunteer(vid):
    vol = child_or_404(db.volunteers, vid, "Volunteer")
    body = get_body()
    event_id = req_str(body, "clinic_event_id")
    expected_event_version = body.get("expected_event_version")
    if isinstance(expected_event_version, bool) or not isinstance(expected_event_version, int):
        err("ERR_VALIDATION", 400, "expected_event_version is required and must be an integer")
    if vol["status"] != "VERIFIED":
        err("ERR_INVALID_STATE", 409, "Volunteer must be VERIFIED to authorize")
    ev = db.events.get(event_id)
    if ev is None:
        err("ERR_REFERENCE_INVALID", 422, f"ClinicEvent {event_id} does not exist")
    approved = any(v for v in db.verifications.values()
                   if v["volunteer_id"] == vid and v["clinic_event_id"] == event_id
                   and v["status"] == "APPROVED")
    if not approved:
        err("ERR_REFERENCE_INVALID", 422,
            "An APPROVED LicenseVerification for this event is required")
    svc = _try_parse_date(ev["service_date"])
    exp = _try_parse_date(vol["license_expiry_date"])
    if vol["discipline"] != "GENERAL":
        if exp is None or svc is None or not (exp > svc):
            err("ERR_LICENSE_EXPIRED", 422,
                "license_expiry_date must be strictly after the event service_date")
        if vol["license_state_code"] != ev["host_state_code"]:
            err("ERR_STATE_PRACTICE_FORBIDDEN", 422,
                "license_state_code must equal the event host_state_code")
    if expected_event_version != ev["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_event_version does not match the current event version")
    vol["status"] = "AUTHORIZED"
    vol["suspension_reason"] = None
    touch(vol)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_volunteer(vol))


@app.post("/volunteers/<vid>/suspend")
@require_roles("VolunteerCoordinator")
def suspend_volunteer(vid):
    vol = child_or_404(db.volunteers, vid, "Volunteer")
    body = get_body()
    event_id = req_str(body, "clinic_event_id")
    reason = body.get("suspension_reason")
    if not isinstance(reason, str) or reason == "":
        err("ERR_VALIDATION", 400, "suspension_reason is required")
    if vol["status"] != "AUTHORIZED":
        err("ERR_INVALID_STATE", 409, "Volunteer must be AUTHORIZED to suspend")
    ev = db.events.get(event_id)
    if ev is None:
        err("ERR_REFERENCE_INVALID", 422, f"ClinicEvent {event_id} does not exist")
    vol["status"] = "SUSPENDED"
    vol["suspension_reason"] = reason
    touch(vol)
    for a in event_children(db.assignments, event_id):
        if a["volunteer_id"] == vid and a["status"] in ("ROSTERED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_volunteer(vol))


@app.post("/volunteers/<vid>/reinstate")
@require_roles("VolunteerCoordinator")
def reinstate_volunteer(vid):
    vol = child_or_404(db.volunteers, vid, "Volunteer")
    body = get_body()
    event_id = req_str(body, "clinic_event_id")
    if vol["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Volunteer must be SUSPENDED to reinstate")
    ev = db.events.get(event_id)
    if ev is None:
        err("ERR_REFERENCE_INVALID", 422, f"ClinicEvent {event_id} does not exist")
    approved = any(v for v in db.verifications.values()
                   if v["volunteer_id"] == vid and v["clinic_event_id"] == event_id
                   and v["status"] == "APPROVED")
    if not approved:
        err("ERR_INVALID_STATE", 409,
            "The authorizing LicenseVerification must remain APPROVED")
    vol["status"] = "VERIFIED"
    vol["suspension_reason"] = None
    touch(vol)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_volunteer(vol))


# --------------------------------------------------------------------------
# Discipline assignments
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/assignments")
@require_roles("VolunteerCoordinator")
def create_assignment(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    volunteer_id = req_str(body, "volunteer_id")
    shift_code = req_enum(body, "shift_code", SHIFT_CODES)
    station_id = body.get("station_id")
    if db.volunteers.get(volunteer_id) is None:
        err("ERR_REFERENCE_INVALID", 422, f"Volunteer {volunteer_id} does not exist")
    if station_id is not None:
        st = db.stations.get(station_id)
        if st is None or st["clinic_event_id"] != eid:
            err("ERR_REFERENCE_INVALID", 422,
                "station_id must reference a station of this event")
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "volunteer_id": volunteer_id,
        "station_id": station_id,
        "shift_code": shift_code,
        "status": "ROSTERED",
    })
    db.assignments[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_assignment(rec), status=201)


@app.get("/clinic-events/<eid>/assignments")
@require_roles("VolunteerCoordinator", "EventDirector", "StationLead", "PlatformAdmin")
def list_assignments_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.assignments, eid)
    for f in ("volunteer_id", "station_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a.get(f) == val]
    return list_response(items, serialize_assignment)


@app.get("/assignments")
@require_roles("VolunteerCoordinator", "EventDirector", "PlatformAdmin")
def list_assignments():
    items = list(db.assignments.values())
    for f in ("clinic_event_id", "volunteer_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a.get(f) == val]
    return list_response(items, serialize_assignment)


def _get_assignment(eid, aid):
    ev = get_event_or_404(eid)
    a = child_or_404(db.assignments, aid, "DisciplineAssignment")
    check_belongs(a, "clinic_event_id", eid, "DisciplineAssignment")
    return ev, a


@app.post("/clinic-events/<eid>/assignments/<aid>/confirm")
@require_roles("VolunteerCoordinator")
def confirm_assignment(eid, aid):
    ev, a = _get_assignment(eid, aid)
    if a["status"] != "ROSTERED":
        err("ERR_INVALID_STATE", 409, "Assignment must be ROSTERED to confirm")
    a["status"] = "CONFIRMED"
    touch(a)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_assignment(a))


@app.post("/clinic-events/<eid>/assignments/<aid>/check-in")
@require_roles("StationLead")
def check_in_assignment(eid, aid):
    ev, a = _get_assignment(eid, aid)
    if a["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Assignment must be CONFIRMED to check in")
    a["status"] = "CHECKED_IN"
    touch(a)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_assignment(a))


@app.post("/clinic-events/<eid>/assignments/<aid>/release")
@require_roles("VolunteerCoordinator")
def release_assignment(eid, aid):
    ev, a = _get_assignment(eid, aid)
    if a["status"] not in ("ROSTERED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Assignment must be ROSTERED or CONFIRMED to release")
    a["status"] = "RELEASED"
    touch(a)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_assignment(a))


# --------------------------------------------------------------------------
# Service stations
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/stations")
@require_roles("LogisticsCoordinator")
def create_station(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    station_label = req_str(body, "station_label")
    station_type = req_enum(body, "station_type", STATION_TYPES)
    chair_count = req_int(body, "chair_count")
    if chair_count < 1:
        err("ERR_VALIDATION", 400, "chair_count must be >= 1")
    minutes_per_patient = req_int(body, "minutes_per_patient")
    if minutes_per_patient < 5:
        err("ERR_VALIDATION", 400, "minutes_per_patient must be >= 5")
    requires_sterilization = req_bool(body, "requires_sterilization")
    open_utc = req_str(body, "service_window_open_utc")
    close_utc = req_str(body, "service_window_close_utc")
    open_ts = _try_parse_ts(open_utc)
    close_ts = _try_parse_ts(close_utc)
    if open_ts is None or close_ts is None:
        err("ERR_VALIDATION", 400, "service window bounds must be ISO-8601 timestamps")
    if not (close_ts > open_ts):
        err("ERR_TEMPORAL_WINDOW_INVALID", 422,
            "service_window_close_utc must be strictly after service_window_open_utc")
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "station_label": station_label,
        "station_type": station_type,
        "chair_count": chair_count,
        "minutes_per_patient": minutes_per_patient,
        "requires_sterilization": requires_sterilization,
        "service_window_open_utc": open_utc,
        "service_window_close_utc": close_utc,
        "status": "PLANNED",
        "_offline_at_cycles": 0,
    })
    db.stations[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_station(rec), status=201)


@app.get("/clinic-events/<eid>/stations")
@require_roles("LogisticsCoordinator", "EventDirector", "StationLead",
               "SterilizationTech", "PlatformAdmin")
def list_stations_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.stations, eid)
    for f in ("station_type", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s[f] == val]
    return list_response(items, serialize_station)


@app.get("/stations")
@require_roles("LogisticsCoordinator", "EventDirector", "StationLead", "PlatformAdmin")
def list_stations():
    items = list(db.stations.values())
    for f in ("clinic_event_id", "station_type", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s[f] == val]
    return list_response(items, serialize_station)


def _get_station(eid, sid):
    ev = get_event_or_404(eid)
    st = child_or_404(db.stations, sid, "ServiceStation")
    check_belongs(st, "clinic_event_id", eid, "ServiceStation")
    return ev, st


def _confirmed_site(ev):
    aid = ev.get("confirmed_site_agreement_id")
    if not aid:
        return None
    ag = db.agreements.get(aid)
    if ag is None:
        return None
    return db.sites.get(ag["site_id"])


@app.post("/clinic-events/<eid>/stations/<sid>/mark-set-up")
@require_roles("LogisticsCoordinator")
def mark_set_up(eid, sid):
    ev, st = _get_station(eid, sid)
    _posture_gate(ev, ("SITE_LOCKED", "STAFFING"))
    if st["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, "Station must be PLANNED to mark set up")
    site = _confirmed_site(ev)
    if site is not None:
        # Per-station power draw is not an input field; stations draw 0 kW.
        used = sum(0 for s in event_children(db.stations, eid)
                   if s["status"] not in ("PLANNED", "DISMANTLED"))
        if used + 0 > site["power_capacity_kw"]:
            err("ERR_POWER_CAPACITY_EXCEEDED", 422,
                "Confirmed site power budget would be exceeded")
    st["status"] = "SET_UP"
    touch(st)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_station(st))


@app.post("/clinic-events/<eid>/stations/<sid>/mark-operational")
@require_roles("StationLead")
def mark_operational(eid, sid):
    ev, st = _get_station(eid, sid)
    if st["status"] == "OFFLINE":
        if st.get("requires_sterilization"):
            if sterilization_completed_count(ev) <= st.get("_offline_at_cycles", 0):
                err("ERR_STERILIZATION_NOT_CLEARED", 422,
                    "A COMPLETED sterilization cycle since going OFFLINE is required")
    elif st["status"] == "SET_UP":
        if st.get("requires_sterilization"):
            err("ERR_STERILIZATION_NOT_CLEARED", 422,
                "Station requires sterilization clearance before OPERATIONAL")
        _posture_gate(ev, ("SITE_LOCKED", "STAFFING", "READY", "IN_SERVICE"))
    elif st["status"] == "STERILIZATION_CLEARED":
        _posture_gate(ev, ("SITE_LOCKED", "STAFFING", "READY", "IN_SERVICE"))
    else:
        err("ERR_INVALID_STATE", 409,
            "Station must be SET_UP, STERILIZATION_CLEARED, or OFFLINE to mark operational")
    st["status"] = "OPERATIONAL"
    touch(st)
    degrade_check(ev)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_station(st))


@app.post("/clinic-events/<eid>/stations/<sid>/take-offline")
@require_roles("StationLead")
def take_offline(eid, sid):
    ev, st = _get_station(eid, sid)
    if st["status"] not in ("OPERATIONAL", "DEGRADED"):
        err("ERR_INVALID_STATE", 409, "Station must be OPERATIONAL or DEGRADED to take offline")
    if any(e for e in event_children(db.encounters, eid)
           if e["station_id"] == sid and e["status"] == "OPEN"):
        err("ERR_ACTIVE_ENCOUNTERS_REMAIN", 422,
            "An OPEN encounter exists at this station")
    st["_offline_at_cycles"] = sterilization_completed_count(ev)
    st["status"] = "OFFLINE"
    touch(st)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_station(st))


@app.post("/clinic-events/<eid>/stations/<sid>/dismantle")
@require_roles("LogisticsCoordinator")
def dismantle_station(eid, sid):
    ev, st = _get_station(eid, sid)
    _posture_gate(ev, ("TEARDOWN",))
    if st["status"] not in ("OPERATIONAL", "DEGRADED", "OFFLINE"):
        err("ERR_INVALID_STATE", 409,
            "Station must be OPERATIONAL, DEGRADED, or OFFLINE to dismantle")
    st["status"] = "DISMANTLED"
    touch(st)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_station(st))


# --------------------------------------------------------------------------
# Patient tickets
# --------------------------------------------------------------------------


def _next_queue_position(ev):
    ev["_max_queue_position"] = ev.get("_max_queue_position", 0) + 1
    return ev["_max_queue_position"]


@app.post("/clinic-events/<eid>/tickets")
@require_roles("QueueMarshal")
def issue_ticket(eid):
    ev = get_event_or_404(eid)
    _posture_gate(ev, ("IN_SERVICE",))
    body = get_body()
    patient_ref = req_str(body, "patient_ref")
    arrival_utc = req_str(body, "arrival_utc")
    arrival = _try_parse_ts(arrival_utc)
    if arrival is None:
        err("ERR_VALIDATION", 400, "arrival_utc must be an ISO-8601 timestamp")
    requested_service = req_enum(body, "requested_service", REQUESTED_SERVICES)
    priority_tier = req_enum(body, "priority_tier", PRIORITY_TIERS)
    doors_open = _parse_ts(ev["doors_open_utc"])
    if not (doors_open <= arrival < doors_open + timedelta(hours=24)):
        err("ERR_TEMPORAL_WINDOW_INVALID", 422,
            "arrival_utc must fall within the service day window beginning at doors_open_utc")
    issued = sum(1 for t in event_children(db.tickets, eid)
                 if t["status"] in ("QUEUED", "CALLED", "IN_SERVICE"))
    if issued >= ev["total_patient_capacity"]:
        err("ERR_CAPACITY_EXHAUSTED", 422, "Event ticket capacity is exhausted")
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "patient_ref": patient_ref,
        "arrival_utc": arrival_utc,
        "requested_service": requested_service,
        "priority_tier": priority_tier,
        "queue_position": _next_queue_position(ev),
        "status": "QUEUED",
        "turn_away_reason": None,
        "requeue_count": 0,
    })
    db.tickets[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_ticket(rec), status=201)


@app.get("/clinic-events/<eid>/tickets")
@require_roles("QueueMarshal", "EventDirector", "StationLead", "PlatformAdmin")
def list_tickets_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.tickets, eid)
    for f in ("status", "requested_service", "priority_tier"):
        val = request.args.get(f)
        if val is not None:
            items = [t for t in items if t[f] == val]
    return list_response(items, serialize_ticket)


@app.get("/tickets")
@require_roles("QueueMarshal", "EventDirector", "PlatformAdmin")
def list_tickets():
    items = list(db.tickets.values())
    for f in ("clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [t for t in items if t[f] == val]
    return list_response(items, serialize_ticket)


def _get_ticket(eid, tid):
    ev = get_event_or_404(eid)
    t = child_or_404(db.tickets, tid, "PatientTicket")
    check_belongs(t, "clinic_event_id", eid, "PatientTicket")
    return ev, t


def _queue_head(ev, service):
    candidates = [t for t in event_children(db.tickets, ev["id"])
                  if t["status"] == "QUEUED" and t["requested_service"] == service]
    if not candidates:
        return None
    rank = {"VULNERABLE": 0, "STANDARD": 1}
    return min(candidates, key=lambda t: (rank[t["priority_tier"]],
                                          _parse_ts(t["arrival_utc"]),
                                          _parse_ts(t["created_at"])))


@app.post("/clinic-events/<eid>/tickets/<tid>/call")
@require_roles("QueueMarshal")
def call_ticket(eid, tid):
    ev, t = _get_ticket(eid, tid)
    _posture_gate(ev, ("IN_SERVICE",))
    if t["status"] != "QUEUED":
        err("ERR_INVALID_STATE", 409, "Ticket must be QUEUED to call")
    head = _queue_head(ev, t["requested_service"])
    if head is None or head["id"] != t["id"]:
        err("ERR_NOT_QUEUE_HEAD", 422,
            "Ticket is not the fair-sequence head for its requested_service")
    t["status"] = "CALLED"
    touch(t)
    return ok(serialize_ticket(t))


@app.post("/clinic-events/<eid>/tickets/<tid>/begin-service")
@require_roles("StationLead")
def begin_service(eid, tid):
    ev, t = _get_ticket(eid, tid)
    if t["status"] != "CALLED":
        err("ERR_INVALID_STATE", 409, "Ticket must be CALLED to begin service")
    body = get_body()
    station_id = req_str(body, "station_id")
    volunteer_id = req_str(body, "volunteer_id")
    encounter_type = req_enum(body, "encounter_type", ENCOUNTER_TYPES)
    findings_summary = opt_str(body, "findings_summary", "")
    requires_followup = req_bool(body, "requires_followup")
    station = db.stations.get(station_id)
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        err("ERR_REFERENCE_INVALID", 422, f"Volunteer {volunteer_id} does not exist")
    if vol["status"] != "AUTHORIZED":
        err("ERR_VOLUNTEER_NOT_AUTHORIZED", 422,
            "Treating volunteer must be AUTHORIZED")
    if vol["discipline"] != t["requested_service"]:
        err("ERR_DISCIPLINE_MISMATCH", 422,
            "Volunteer discipline does not match the requested service")
    window_open = False
    if station is not None and station["clinic_event_id"] == eid \
            and station["station_type"] == t["requested_service"] \
            and station["status"] == "OPERATIONAL":
        open_ts = _parse_ts(station["service_window_open_utc"])
        close_ts = _parse_ts(station["service_window_close_utc"])
        window_open = open_ts <= db.clock <= close_ts
    if not window_open:
        err("ERR_NO_STATION_AVAILABLE", 422,
            "No compatible OPERATIONAL station with an open service window")
    t["status"] = "IN_SERVICE"
    touch(t)
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "ticket_id": tid,
        "station_id": station_id,
        "volunteer_id": volunteer_id,
        "encounter_type": encounter_type,
        "findings_summary": findings_summary,
        "requires_followup": requires_followup,
        "status": "OPEN",
    })
    db.encounters[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_encounter(rec), status=201)


@app.post("/clinic-events/<eid>/tickets/<tid>/requeue")
@require_roles("QueueMarshal")
def requeue_ticket(eid, tid):
    ev, t = _get_ticket(eid, tid)
    if t["status"] != "CALLED":
        err("ERR_INVALID_STATE", 409, "Ticket must be CALLED to requeue")
    if t.get("requeue_count", 0) >= 1:
        err("ERR_REQUEUE_EXHAUSTED", 422, "Ticket has already been requeued once")
    t["requeue_count"] = t.get("requeue_count", 0) + 1
    t["queue_position"] = _next_queue_position(ev)
    t["status"] = "QUEUED"
    touch(t)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_ticket(t))


@app.post("/clinic-events/<eid>/tickets/<tid>/mark-no-show")
@require_roles("QueueMarshal")
def mark_no_show(eid, tid):
    ev, t = _get_ticket(eid, tid)
    if t["status"] != "CALLED":
        err("ERR_INVALID_STATE", 409, "Ticket must be CALLED to mark no-show")
    t["status"] = "NO_SHOW"
    touch(t)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_ticket(t))


@app.post("/clinic-events/<eid>/tickets/<tid>/withdraw")
@require_roles("QueueMarshal")
def withdraw_ticket(eid, tid):
    ev, t = _get_ticket(eid, tid)
    if t["status"] != "QUEUED":
        err("ERR_INVALID_STATE", 409, "Ticket must be QUEUED to withdraw")
    t["status"] = "WITHDRAWN"
    touch(t)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_ticket(t))


# --------------------------------------------------------------------------
# Encounters & referrals
# --------------------------------------------------------------------------


@app.get("/clinic-events/<eid>/encounters")
@require_roles("StationLead", "EventDirector", "PlatformAdmin")
def list_encounters_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.encounters, eid)
    for f in ("station_id", "volunteer_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [e for e in items if e[f] == val]
    return list_response(items, serialize_encounter)


@app.get("/encounters")
@require_roles("StationLead", "EventDirector", "PlatformAdmin")
def list_encounters():
    items = list(db.encounters.values())
    for f in ("clinic_event_id", "ticket_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [e for e in items if e[f] == val]
    return list_response(items, serialize_encounter)


def _get_encounter(eid, enc_id):
    ev = get_event_or_404(eid)
    enc = child_or_404(db.encounters, enc_id, "PatientEncounter")
    check_belongs(enc, "clinic_event_id", eid, "PatientEncounter")
    return ev, enc


@app.post("/clinic-events/<eid>/encounters/<enc_id>/complete")
@require_roles("StationLead")
def complete_encounter(eid, enc_id):
    ev, enc = _get_encounter(eid, enc_id)
    if enc["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Encounter must be OPEN to complete")
    body = get_body()
    referrals_in = body.get("referrals", [])
    if referrals_in is None:
        referrals_in = []
    if not isinstance(referrals_in, list):
        err("ERR_VALIDATION", 400, "referrals must be an array")
    vol = db.volunteers.get(enc["volunteer_id"])
    if vol is None or vol["status"] != "AUTHORIZED":
        err("ERR_VOLUNTEER_NOT_AUTHORIZED", 422,
            "Treating volunteer must be AUTHORIZED at completion")
    station = db.stations.get(enc["station_id"])
    if station is None or station["status"] not in ("OPERATIONAL", "DEGRADED"):
        err("ERR_STATION_NOT_SERVING", 422,
            "Station must be OPERATIONAL or DEGRADED to complete an encounter")
    if enc["requires_followup"] and len(referrals_in) < 1:
        err("ERR_REFERRAL_REQUIRED", 422,
            "A referral bundle is required when requires_followup is true")
    for r in referrals_in:
        if not isinstance(r, dict):
            err("ERR_VALIDATION", 400, "Each referral must be an object")
        if r.get("referral_type") not in REFERRAL_TYPES:
            err("ERR_VALIDATION", 400, "referral_type is invalid")
        if not isinstance(r.get("partner_org_name"), str) or not r.get("partner_org_name"):
            err("ERR_VALIDATION", 400, "partner_org_name is required")
        if r.get("urgency") not in URGENCIES:
            err("ERR_VALIDATION", 400, "urgency is invalid")
    enc["status"] = "COMPLETED"
    touch(enc)
    ticket = db.tickets.get(enc["ticket_id"])
    if ticket is not None and ticket["status"] == "IN_SERVICE":
        ticket["status"] = "SERVED"
        touch(ticket)
    for r in referrals_in:
        rec = base_record(common=False)
        rec.update({
            "encounter_id": enc_id,
            "clinic_event_id": eid,
            "referral_type": r["referral_type"],
            "partner_org_name": r["partner_org_name"],
            "urgency": r["urgency"],
            "notes": r.get("notes", "") if isinstance(r.get("notes", ""), str) else "",
        })
        db.referrals[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_encounter(enc))


@app.post("/clinic-events/<eid>/encounters/<enc_id>/abandon")
@require_roles("StationLead")
def abandon_encounter(eid, enc_id):
    ev, enc = _get_encounter(eid, enc_id)
    if enc["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Encounter must be OPEN to abandon")
    enc["status"] = "ABANDONED"
    touch(enc)
    ticket = db.tickets.get(enc["ticket_id"])
    if ticket is not None and ticket["status"] == "IN_SERVICE":
        ticket["status"] = "QUEUED"
        ticket["queue_position"] = _next_queue_position(ev)
        touch(ticket)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_encounter(enc))


@app.get("/clinic-events/<eid>/encounters/<enc_id>/referrals")
@require_roles("StationLead", "EventDirector", "CommunityPartnerRep", "PlatformAdmin")
def list_referrals_for_encounter(eid, enc_id):
    _get_encounter(eid, enc_id)
    items = [r for r in db.referrals.values() if r["encounter_id"] == enc_id]
    return list_response(items, serialize_referral)


@app.get("/referrals")
@require_roles("StationLead", "EventDirector", "CommunityPartnerRep", "PlatformAdmin")
def list_referrals():
    items = list(db.referrals.values())
    for f in ("clinic_event_id", "encounter_id", "referral_type"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if r[f] == val]
    return list_response(items, serialize_referral)


# --------------------------------------------------------------------------
# Equipment manifests
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/manifests")
@require_roles("LogisticsCoordinator")
def create_manifest(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    manifest_label = req_str(body, "manifest_label")
    item_count = req_int(body, "item_count")
    if item_count < 1:
        err("ERR_VALIDATION", 400, "item_count must be >= 1")
    weight_kg = req_num(body, "weight_kg")
    if not (weight_kg > 0):
        err("ERR_VALIDATION", 400, "weight_kg must be > 0")
    requires_loading_dock = req_bool(body, "requires_loading_dock")
    contains_sterilizer = req_bool(body, "contains_sterilizer")
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "manifest_label": manifest_label,
        "item_count": item_count,
        "weight_kg": weight_kg,
        "requires_loading_dock": requires_loading_dock,
        "contains_sterilizer": contains_sterilizer,
        "status": "PACKED",
    })
    db.manifests[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_manifest(rec), status=201)


@app.get("/clinic-events/<eid>/manifests")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def list_manifests_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.manifests, eid)
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(items, serialize_manifest)


@app.get("/manifests")
@require_roles("LogisticsCoordinator", "EventDirector", "PlatformAdmin")
def list_manifests():
    items = list(db.manifests.values())
    for f in ("clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [m for m in items if m[f] == val]
    return list_response(items, serialize_manifest)


def _get_manifest(eid, mid):
    ev = get_event_or_404(eid)
    m = child_or_404(db.manifests, mid, "EquipmentManifest")
    check_belongs(m, "clinic_event_id", eid, "EquipmentManifest")
    return ev, m


@app.post("/clinic-events/<eid>/manifests/<mid>/ship")
@require_roles("LogisticsCoordinator")
def ship_manifest(eid, mid):
    ev, m = _get_manifest(eid, mid)
    if m["status"] != "PACKED":
        err("ERR_INVALID_STATE", 409, "Manifest must be PACKED to ship")
    if ev.get("confirmed_site_agreement_id") is None or ev["posture"] == "PLANNING":
        err("ERR_EVENT_POSTURE_FORBIDS", 409,
            "A CONFIRMED site agreement is required before shipping")
    if m["requires_loading_dock"]:
        site = _confirmed_site(ev)
        if site is None or not site["has_loading_dock"]:
            err("ERR_LOADING_DOCK_REQUIRED", 422,
                "Confirmed site lacks a loading dock")
    m["status"] = "IN_TRANSIT"
    touch(m)
    return ok(serialize_manifest(m))


@app.post("/clinic-events/<eid>/manifests/<mid>/deliver")
@require_roles("LogisticsCoordinator")
def deliver_manifest(eid, mid):
    ev, m = _get_manifest(eid, mid)
    if m["status"] != "IN_TRANSIT":
        err("ERR_INVALID_STATE", 409, "Manifest must be IN_TRANSIT to deliver")
    m["status"] = "DELIVERED"
    touch(m)
    return ok(serialize_manifest(m))


@app.post("/clinic-events/<eid>/manifests/<mid>/unpack")
@require_roles("LogisticsCoordinator")
def unpack_manifest(eid, mid):
    ev, m = _get_manifest(eid, mid)
    if m["status"] != "DELIVERED":
        err("ERR_INVALID_STATE", 409, "Manifest must be DELIVERED to unpack")
    m["status"] = "UNPACKED"
    touch(m)
    return ok(serialize_manifest(m))


@app.post("/clinic-events/<eid>/manifests/<mid>/repack")
@require_roles("LogisticsCoordinator")
def repack_manifest(eid, mid):
    ev, m = _get_manifest(eid, mid)
    _posture_gate(ev, ("TEARDOWN",))
    if m["status"] != "UNPACKED":
        err("ERR_INVALID_STATE", 409, "Manifest must be UNPACKED to repack")
    m["status"] = "REPACKED"
    touch(m)
    return ok(serialize_manifest(m))


# --------------------------------------------------------------------------
# Sterilization cycles
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/sterilization-cycles")
@require_roles("SterilizationTech")
def create_cycle(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    batch = req_int(body, "instrument_batch_size")
    if batch < 1:
        err("ERR_VALIDATION", 400, "instrument_batch_size must be >= 1")
    if batch > AUTOCLAVE_BATCH_MAX:
        err("ERR_BATCH_TOO_LARGE", 422,
            f"instrument_batch_size must be <= {AUTOCLAVE_BATCH_MAX}")
    if not any(m for m in event_children(db.manifests, eid)
               if m["status"] == "UNPACKED" and m["contains_sterilizer"]):
        err("ERR_REFERENCE_INVALID", 422,
            "An UNPACKED manifest containing a sterilizer is required")
    ev["_cycle_sequence"] = ev.get("_cycle_sequence", 0) + 1
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "cycle_sequence": ev["_cycle_sequence"],
        "instrument_batch_size": batch,
        "started_utc": now_iso(),
        "completed_utc": None,
        "status": "RUNNING",
    })
    db.cycles[rec["id"]] = rec
    degrade_check(ev)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_cycle(rec), status=201)


@app.get("/clinic-events/<eid>/sterilization-cycles")
@require_roles("SterilizationTech", "StationLead", "EventDirector", "PlatformAdmin")
def list_cycles_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.cycles, eid)
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serialize_cycle)


@app.get("/sterilization-cycles")
@require_roles("SterilizationTech", "EventDirector", "PlatformAdmin")
def list_cycles():
    items = list(db.cycles.values())
    for f in ("clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [c for c in items if c[f] == val]
    return list_response(items, serialize_cycle)


def _get_cycle(eid, cid):
    ev = get_event_or_404(eid)
    c = child_or_404(db.cycles, cid, "SterilizationCycle")
    check_belongs(c, "clinic_event_id", eid, "SterilizationCycle")
    return ev, c


@app.post("/clinic-events/<eid>/sterilization-cycles/<cid>/complete")
@require_roles("SterilizationTech")
def complete_cycle(eid, cid):
    ev, c = _get_cycle(eid, cid)
    if c["status"] != "RUNNING":
        err("ERR_INVALID_STATE", 409, "Cycle must be RUNNING to complete")
    c["status"] = "COMPLETED"
    c["completed_utc"] = now_iso()
    touch(c)
    for s in event_children(db.stations, eid):
        if s.get("requires_sterilization") and s["status"] == "SET_UP":
            s["status"] = "STERILIZATION_CLEARED"
            touch(s)
    degrade_check(ev)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_cycle(c))


@app.post("/clinic-events/<eid>/sterilization-cycles/<cid>/fail")
@require_roles("SterilizationTech")
def fail_cycle(eid, cid):
    ev, c = _get_cycle(eid, cid)
    if c["status"] != "RUNNING":
        err("ERR_INVALID_STATE", 409, "Cycle must be RUNNING to fail")
    c["status"] = "FAILED"
    touch(c)
    degrade_check(ev)
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_cycle(c))


# --------------------------------------------------------------------------
# Unmet demand reports
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/unmet-demand-reports")
@require_roles("EventDirector")
def generate_report(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    variant = req_enum(body, "report_variant", REPORT_VARIANTS)
    tickets = event_children(db.tickets, eid)
    observed = sum(1 for t in tickets if t["status"] == "TURNED_AWAY")
    queue_at_close = sum(
        1 for t in tickets
        if t["status"] == "QUEUED"
        or (t["status"] == "TURNED_AWAY" and t.get("turn_away_reason") == "EVENT_ENDED"))
    served = sum(1 for t in tickets if t["status"] == "SERVED")
    if variant == "OBSERVED_ONLY":
        estimated = 0
    else:
        factor = Decimal(1) + Decimal(queue_at_close) / Decimal(max(served, 1))
        estimated = int((Decimal(observed) * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)) - observed
    projected = projected_servable(ev)  # pessimistic variant
    shortfall = observed + estimated + max(0, ev["total_patient_capacity"] - projected)
    rec = base_record(common=False)
    rec.update({
        "clinic_event_id": eid,
        "generated_at_utc": rec["created_at"],
        "turned_away_count": observed,
        "estimated_unserved_beyond_queue": estimated,
        "projected_shortfall_patients": shortfall,
        "report_variant": variant,
    })
    db.reports[rec["id"]] = rec
    return ok(serialize_report(rec), status=201)


@app.get("/clinic-events/<eid>/unmet-demand-reports")
@require_roles("EventDirector", "PlatformAdmin")
def list_reports(eid):
    get_event_or_404(eid)
    items = event_children(db.reports, eid)
    return list_response(items, serialize_report)


# --------------------------------------------------------------------------
# Community handoffs
# --------------------------------------------------------------------------


@app.post("/clinic-events/<eid>/handoffs")
@require_roles("EventDirector")
def create_handoff(eid):
    ev = get_event_or_404(eid)
    body = get_body()
    partner_org_name = req_str(body, "partner_org_name")
    teardown_checklist_complete = req_bool(body, "teardown_checklist_complete")
    rec = base_record()
    rec.update({
        "clinic_event_id": eid,
        "partner_org_name": partner_org_name,
        "referral_packet_count": 0,
        "teardown_checklist_complete": teardown_checklist_complete,
        "status": "DRAFT",
    })
    db.handoffs[rec["id"]] = rec
    recompute_derived(ev)
    bump_event(ev)
    return ok(serialize_handoff(rec), status=201)


@app.get("/clinic-events/<eid>/handoffs")
@require_roles("EventDirector", "CommunityPartnerRep", "PlatformAdmin")
def list_handoffs_for_event(eid):
    get_event_or_404(eid)
    items = event_children(db.handoffs, eid)
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(items, serialize_handoff)


@app.get("/handoffs")
@require_roles("EventDirector", "CommunityPartnerRep", "PlatformAdmin")
def list_handoffs():
    items = list(db.handoffs.values())
    for f in ("clinic_event_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [h for h in items if h[f] == val]
    return list_response(items, serialize_handoff)


def _get_handoff(eid, hid):
    ev = get_event_or_404(eid)
    h = child_or_404(db.handoffs, hid, "CommunityHandoff")
    check_belongs(h, "clinic_event_id", eid, "CommunityHandoff")
    return ev, h


@app.post("/clinic-events/<eid>/handoffs/<hid>/assemble-packet")
@require_roles("EventDirector")
def assemble_packet(eid, hid):
    ev, h = _get_handoff(eid, hid)
    _posture_gate(ev, ("IN_SERVICE", "TEARDOWN"))
    if h["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Handoff must be DRAFT to assemble the packet")
    h["status"] = "PACKET_ASSEMBLED"
    h["referral_packet_count"] = sum(1 for r in db.referrals.values()
                                     if r["clinic_event_id"] == eid)
    touch(h)
    return ok(serialize_handoff(h))


@app.post("/clinic-events/<eid>/handoffs/<hid>/accept")
@require_roles("CommunityPartnerRep")
def accept_handoff(eid, hid):
    ev, h = _get_handoff(eid, hid)
    if h["status"] != "PACKET_ASSEMBLED":
        err("ERR_INVALID_STATE", 409, "Handoff must be PACKET_ASSEMBLED to accept")
    if not h["teardown_checklist_complete"]:
        err("ERR_TEARDOWN_INCOMPLETE", 422,
            "teardown_checklist_complete must be true to accept")
    h["status"] = "ACCEPTED"
    touch(h)
    return ok(serialize_handoff(h))


@app.post("/clinic-events/<eid>/handoffs/<hid>/dispute")
@require_roles("CommunityPartnerRep")
def dispute_handoff(eid, hid):
    ev, h = _get_handoff(eid, hid)
    if h["status"] != "PACKET_ASSEMBLED":
        err("ERR_INVALID_STATE", 409, "Handoff must be PACKET_ASSEMBLED to dispute")
    h["status"] = "DISPUTED"
    touch(h)
    return ok(serialize_handoff(h))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
