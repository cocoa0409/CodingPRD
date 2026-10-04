#!/usr/bin/env python3
"""Driver Safety Camera Coaching API — Flask implementation.

Derived from workspace/PRD.md and SCAFFOLD.yaml.
In-memory store; empty at boot; logical clock starts at 2026-09-01T00:00:00Z.
"""

import os
import re
import uuid
import random
import string
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

ALL_ROLES = [
    "PlatformAdmin", "TelematicsIngest", "SafetyManager",
    "ClaimsAdjuster", "Driver", "FleetAdmin",
]

SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 3, "HIGH": 6, "CRITICAL": 10}
TIER_MULT = {"LOW": 1, "STANDARD": 2, "HIGH": 3}
COLLISION_BOOST = 1000
PENALTY_FACTOR = Decimal("2.5")
AGED_FACTOR = Decimal("0.33")
TIER_AMOUNT = {"GOLD": 50000, "SILVER": 25000, "BRONZE": 10000, "NONE": 0}

EVENT_TYPES = ["HARSH_BRAKE", "FOLLOWING_DISTANCE", "DISTRACTION", "SEAT_BELT", "COLLISION"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

Q2 = Decimal("0.01")

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.clock = DEFAULT_CLOCK
        self.clock_set = False
        self.entities = {k: {} for k in [
            "fleets", "terminals", "union_agreements", "drivers", "vehicles",
            "camera_policies", "safety_events", "footage_clips",
            "review_decisions", "coaching_sessions", "escalation_cases",
            "exoneration_claims", "litigation_holds", "score_snapshots",
            "incentive_awards",
        ]}
        self._create_seq = 0

    def next_seq(self):
        self._create_seq += 1
        return self._create_seq


DB = Store()

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)

# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an ISO 8601 datetime; returns naive-UTC comparable datetime."""
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", 400, f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION", 400, f"{field} is not a parseable datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_dt(dt):
    """Format datetime as ISO 8601 UTC with exactly 3 fractional digits + Z."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def now_logical():
    return DB.clock


def wall_ts():
    dt = datetime.now(timezone.utc).replace(tzinfo=None)
    return fmt_dt(dt)

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def ok(data, status=200, is_list=False, pagination=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": wall_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data if data is not None else ([] if is_list else {}),
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", "0"))
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": (offset + limit) < total}

# ---------------------------------------------------------------------------
# Auth middleware (before_request)
# ---------------------------------------------------------------------------

# route table entry: (method, path) -> (roles_allowed, ownership_check_name or None)
ROUTE_TABLE = {}

def register_route(method, path, roles, ownership=None):
    ROUTE_TABLE[(method, path)] = (roles, ownership)


def build_routes():
    R = ROUTE_TABLE
    READ = list(ALL_ROLES)
    entries = [
        ("POST", "/api/_clock/set_current_utc", ["PlatformAdmin"], None),
        ("POST", "/api/fleets", ["PlatformAdmin"], None),
        ("GET", "/api/fleets/{id}", READ, None),
        ("POST", "/api/fleets/{id}/posture", ["PlatformAdmin"], None),
        ("GET", "/api/fleets/{id}/leaderboard", READ, None),
        ("POST", "/api/fleets/{id}/run-maintenance", ["PlatformAdmin"], None),
        ("GET", "/api/fleets/{id}/terminals", READ, None),
        ("GET", "/api/fleets/{id}/camera-policies", READ, None),
        ("GET", "/api/fleets/{id}/safety-events", READ, None),
        ("GET", "/api/fleets/{id}/litigation-holds", READ, None),
        ("GET", "/api/fleets/{id}/score-snapshots", READ, None),
        ("GET", "/api/fleets/{id}/incentive-awards", READ, None),
        ("POST", "/api/fleets/{id}/score-snapshots/compute", ["FleetAdmin"], None),

        ("POST", "/api/terminals", ["PlatformAdmin"], None),
        ("GET", "/api/terminals/{id}", READ, None),
        ("GET", "/api/terminals/{id}/drivers", READ, None),
        ("GET", "/api/terminals/{id}/vehicles", READ, None),
        ("GET", "/api/terminals/{id}/union-agreements", READ, None),

        ("POST", "/api/union-agreements", ["PlatformAdmin"], None),
        ("GET", "/api/union-agreements/{id}", READ, None),
        ("POST", "/api/union-agreements/{id}/ratify", ["PlatformAdmin"], None),
        ("POST", "/api/union-agreements/{id}/expire", ["PlatformAdmin"], None),

        ("POST", "/api/drivers", ["PlatformAdmin"], None),
        ("GET", "/api/drivers/{id}", READ, None),
        ("POST", "/api/drivers/{id}/status", ["SafetyManager"], None),
        ("GET", "/api/drivers/{id}/safety-events", READ, None),
        ("GET", "/api/drivers/{id}/coaching-sessions", READ, None),
        ("POST", "/api/drivers/{id}/coaching-sessions", ["SafetyManager"], None),
        ("GET", "/api/drivers/{id}/escalation-cases", READ, None),
        ("GET", "/api/drivers/{id}/exoneration-claims", READ, None),
        ("GET", "/api/drivers/{id}/litigation-holds", READ, None),
        ("GET", "/api/drivers/{id}/incentive-awards", READ, None),
        ("GET", "/api/drivers/{id}/score-snapshots", READ, None),

        ("POST", "/api/vehicles", ["PlatformAdmin"], None),
        ("GET", "/api/vehicles/{id}", READ, None),
        ("POST", "/api/vehicles/{id}/decommission", ["PlatformAdmin"], None),
        ("GET", "/api/vehicles/{id}/safety-events", READ, None),

        ("POST", "/api/camera-policies", ["PlatformAdmin"], None),
        ("GET", "/api/camera-policies/{id}", READ, None),
        ("PATCH", "/api/camera-policies/{id}", ["PlatformAdmin"], None),
        ("POST", "/api/camera-policies/{id}/activate", ["PlatformAdmin"], None),
        ("POST", "/api/camera-policies/{id}/archive", ["PlatformAdmin"], None),

        ("POST", "/api/safety-events", ["TelematicsIngest"], None),
        ("GET", "/api/safety-events/{id}", READ, None),
        ("POST", "/api/safety-events/{id}/review", ["SafetyManager"], None),
        ("GET", "/api/safety-events/{id}/footage-clips", READ, None),
        ("GET", "/api/safety-events/{id}/review-decisions", READ, None),
        ("GET", "/api/safety-events/{id}/coaching-sessions", READ, None),
        ("GET", "/api/safety-events/{id}/escalation-cases", READ, None),
        ("POST", "/api/safety-events/{id}/exoneration-claims", ["Driver"], "own_event"),
        ("GET", "/api/safety-events/{id}/exoneration-claims", READ, None),
        ("GET", "/api/safety-events/{id}/litigation-holds", READ, None),

        ("POST", "/api/footage-clips", ["TelematicsIngest"], None),
        ("GET", "/api/footage-clips/{id}", READ, None),
        ("POST", "/api/footage-clips/{id}/upload-begin", ["TelematicsIngest"], None),
        ("POST", "/api/footage-clips/{id}/upload-complete", ["TelematicsIngest"], None),
        ("POST", "/api/footage-clips/{id}/purge", ["SafetyManager"], None),

        ("GET", "/api/coaching-sessions/{id}", READ, None),
        ("POST", "/api/coaching-sessions/{id}/acknowledge", ["Driver"], "own_session"),
        ("POST", "/api/coaching-sessions/{id}/complete", ["SafetyManager"], None),
        ("POST", "/api/coaching-sessions/{id}/reassign", ["SafetyManager"], None),
        ("POST", "/api/coaching-sessions/{id}/cancel", ["SafetyManager"], None),

        ("GET", "/api/escalation-cases/{id}", READ, None),
        ("POST", "/api/escalation-cases/{id}/review", ["SafetyManager"], None),
        ("POST", "/api/escalation-cases/{id}/send-back", ["SafetyManager"], None),
        ("POST", "/api/escalation-cases/{id}/resolve", ["SafetyManager"], None),

        ("GET", "/api/exoneration-claims/{id}", READ, None),
        ("POST", "/api/exoneration-claims/{id}/begin-review", ["ClaimsAdjuster"], None),
        ("POST", "/api/exoneration-claims/{id}/decide", ["ClaimsAdjuster"], None),

        ("POST", "/api/litigation-holds", ["SafetyManager"], None),
        ("GET", "/api/litigation-holds/{id}", READ, None),
        ("POST", "/api/litigation-holds/{id}/release", ["SafetyManager"], None),

        ("GET", "/api/score-snapshots/{id}", READ, None),
        ("GET", "/api/score-snapshots/{id}/incentive-awards", READ, None),
        ("GET", "/api/incentive-awards/{id}", READ, None),
        ("POST", "/api/incentive-awards/{id}/approve", ["FleetAdmin"], None),
        ("POST", "/api/incentive-awards/{id}/pay", ["FleetAdmin"], None),
    ]
    for m, p, roles, own in entries:
        register_route(m, p, roles, own)


build_routes()


def _match_route(method, path):
    """Return (roles, ownership, path_params) or None."""
    segs = [s for s in path.split("/") if s != ""]
    for (m, pat), (roles, own) in ROUTE_TABLE.items():
        if m != method:
            continue
        psegs = [s for s in pat.split("/") if s != ""]
        if len(segs) != len(psegs):
            continue
        params = {}
        okk = True
        for ps, s in zip(psegs, segs):
            if ps.startswith("{") and ps.endswith("}"):
                params[ps[1:-1]] = s
            elif ps != s:
                okk = False
                break
        if okk:
            return roles, own, params
    return None


def check_auth():
    """Priority 1 & 2: authentication + role authorization + Driver ownership."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise err("ERR_UNAUTHENTICATED", 401, "X-User-Role and X-User-ID headers are required")
    if role not in ALL_ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Unknown role")
    matched = _match_route(request.method, request.path)
    if matched is None:
        # let Flask routing produce 404; no auth decision here
        request.environ["_params"] = {}
        return
    roles, ownership, params = matched
    request.environ["_params"] = params
    if role not in roles:
        raise err("ERR_FORBIDDEN", 403, "Role not authorized for this endpoint")
    if ownership == "own_event" and role == "Driver":
        ev = DB.entities["safety_events"].get(params.get("id"))
        if ev is not None and ev["driver_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "Drivers may act only on their own events")
    elif ownership == "own_session" and role == "Driver":
        sess = DB.entities["coaching_sessions"].get(params.get("id"))
        if sess is not None and sess["driver_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "Drivers may acknowledge only their own sessions")


def param(name):
    return request.environ.get("_params", {}).get(name)

# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def body():
    if request.method in ("GET", "HEAD"):
        return {}
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", 400, "Request body is not valid JSON")
    if data is None:
        raise err("ERR_VALIDATION", 400, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err("ERR_VALIDATION", 400, f"Missing required field: {name}")
    return data[name]


def req_string(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", 400, f"{name} must be a string")
    return v


def opt_string(data, name):
    v = data.get(name)
    if v is not None and not isinstance(v, str):
        raise err("ERR_VALIDATION", 400, f"{name} must be a string")
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", 400, f"{name} must be a boolean")
    return v


def opt_bool(data, name):
    v = data.get(name)
    if v is not None and not isinstance(v, bool):
        raise err("ERR_VALIDATION", 400, f"{name} must be a boolean")
    return v


def req_int(data, name, min_val=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", 400, f"{name} must be an integer")
    if min_val is not None and v < min_val:
        raise err("ERR_VALIDATION", 400, f"{name} must be >= {min_val}")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION", 400, f"{name} must be one of {allowed}")
    return v


def opt_enum(data, name, allowed):
    v = data.get(name)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        raise err("ERR_VALIDATION", 400, f"{name} must be one of {allowed}")
    return v

# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

NOT_FOUND_MAP = {
    "fleets": "ERR_FLEET_NOT_FOUND",
    "terminals": "ERR_TERMINAL_NOT_FOUND",
    "union_agreements": "ERR_AGREEMENT_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "vehicles": "ERR_VEHICLE_NOT_FOUND",
    "camera_policies": "ERR_POLICY_NOT_FOUND",
    "safety_events": "ERR_EVENT_NOT_FOUND",
    "footage_clips": "ERR_CLIP_NOT_FOUND",
    "coaching_sessions": "ERR_SESSION_NOT_FOUND",
    "escalation_cases": "ERR_CASE_NOT_FOUND",
    "exoneration_claims": "ERR_CLAIM_NOT_FOUND",
    "litigation_holds": "ERR_HOLD_NOT_FOUND",
    "score_snapshots": "ERR_SNAPSHOT_NOT_FOUND",
    "incentive_awards": "ERR_AWARD_NOT_FOUND",
}


def new_entity(kind, common=True):
    seq = DB.next_seq()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now_logical(),
        "_seq": seq,
    }
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    DB.entities[kind][e["id"]] = e
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = now_logical()


def get_or_404(kind, eid):
    e = DB.entities[kind].get(eid)
    if e is None:
        raise err(NOT_FOUND_MAP[kind], 404, f"{kind[:-1]} not found: {eid}")
    return e

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_fleet(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "incentive_budget_cents": e["incentive_budget_cents"],
        "posture": e["posture"],
        "ops_run_index": e["ops_run_index"],
        "retention_used_mb": retention_used_mb(e["id"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_terminal(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "name": e["name"],
        "region_code": e["region_code"],
        "safety_score_cached": float(terminal_score(e["id"])),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_agreement(e):
    return {
        "id": e["id"],
        "terminal_id": e["terminal_id"],
        "agreement_code": e["agreement_code"],
        "inward_camera_allowed": e["inward_camera_allowed"],
        "live_view_allowed": e["live_view_allowed"],
        "audio_recording_allowed": e["audio_recording_allowed"],
        "coaching_requires_steward_present": e["coaching_requires_steward_present"],
        "effective_from": fmt_dt(e["effective_from"]),
        "effective_until": fmt_dt(e["effective_until"]),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_driver(e):
    final = driver_score(e["id"], "final")
    prov = driver_score(e["id"], "provisional")
    return {
        "id": e["id"],
        "terminal_id": e["terminal_id"],
        "employee_ref": e["employee_ref"],
        "name": e["name"],
        "hire_date": fmt_dt(e["hire_date"]),
        "inward_camera_consent": e["inward_camera_consent"],
        "status": e["status"],
        "confirmed_events_90d": confirmed_count(e["id"]),
        "safety_score_provisional": float(prov),
        "safety_score_final": float(final),
        "incentive_tier": price_tier(final),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_vehicle(e):
    return {
        "id": e["id"],
        "terminal_id": e["terminal_id"],
        "vin": e["vin"],
        "camera_unit_id": e["camera_unit_id"],
        "bandwidth_tier": e["bandwidth_tier"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_policy(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "name": e["name"],
        "retention_days_standard": e["retention_days_standard"],
        "retention_days_collision": e["retention_days_collision"],
        "daily_upload_cap_mb": e["daily_upload_cap_mb"],
        "inward_capture_enabled": e["inward_capture_enabled"],
        "distraction_detection_enabled": e["distraction_detection_enabled"],
        "seatbelt_detection_enabled": e["seatbelt_detection_enabled"],
        "effective_from": fmt_dt(e["effective_from"]),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "driver_id": e["driver_id"],
        "vehicle_id": e["vehicle_id"],
        "event_type": e["event_type"],
        "severity": e["severity"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "detected_at": fmt_dt(e["detected_at"]),
        "status": e["status"],
        "upload_priority_score": e["upload_priority_score"],
        "confirmed_at": fmt_dt(e["confirmed_at"]) if e["confirmed_at"] else None,
        "review_count": e["review_count"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_clip(e):
    return {
        "id": e["id"],
        "event_id": e["event_id"],
        "camera_angle": e["camera_angle"],
        "size_mb": e["size_mb"],
        "captured_at": fmt_dt(e["captured_at"]),
        "upload_status": e["upload_status"],
        "retention_class": e["retention_class"],
        "uploaded_at": fmt_dt(e["uploaded_at"]) if e["uploaded_at"] else None,
        "purged_at": fmt_dt(e["purged_at"]) if e["purged_at"] else None,
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_decision(e):
    return {
        "id": e["id"],
        "event_id": e["event_id"],
        "reviewer_id": e["reviewer_id"],
        "action": e["action"],
        "prior_event_type": e["prior_event_type"],
        "new_event_type": e["new_event_type"],
        "prior_severity": e["prior_severity"],
        "new_severity": e["new_severity"],
        "rationale": e["rationale"],
        "decided_at": fmt_dt(e["decided_at"]),
        "created_at": fmt_dt(e["created_at"]),
    }


def ser_session(e):
    return {
        "id": e["id"],
        "driver_id": e["driver_id"],
        "event_id": e["event_id"],
        "assigned_by": e["assigned_by"],
        "starts_at": fmt_dt(e["starts_at"]),
        "ends_at": fmt_dt(e["ends_at"]),
        "due_at": fmt_dt(e["due_at"]),
        "status": e["status"],
        "outcome": e["outcome"],
        "reassign_count": e["reassign_count"],
        "steward_required": steward_required(e),
        "completed_at": fmt_dt(e["completed_at"]) if e["completed_at"] else None,
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_case(e):
    return {
        "id": e["id"],
        "driver_id": e["driver_id"],
        "trigger_event_id": e["trigger_event_id"],
        "offense_count": e["offense_count"],
        "window_days": e["window_days"],
        "status": e["status"],
        "resolution_note": e["resolution_note"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_claim(e):
    return {
        "id": e["id"],
        "event_id": e["event_id"],
        "driver_id": e["driver_id"],
        "claim_ref": e["claim_ref"],
        "police_report_ref": e["police_report_ref"],
        "status": e["status"],
        "submitted_at": fmt_dt(e["submitted_at"]),
        "decided_at": fmt_dt(e["decided_at"]) if e["decided_at"] else None,
        "decided_by": e["decided_by"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_hold(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "driver_id": e["driver_id"],
        "event_id": e["event_id"],
        "scope": e["scope"],
        "reason": e["reason"],
        "status": e["status"],
        "placed_at": fmt_dt(e["placed_at"]),
        "released_at": fmt_dt(e["released_at"]) if e["released_at"] else None,
        "placed_by": e["placed_by"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_snapshot(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "scope_type": e["scope_type"],
        "scope_id": e["scope_id"],
        "period_start": fmt_dt(e["period_start"]),
        "period_end": fmt_dt(e["period_end"]),
        "status": e["status"],
        "score": float(e["score"]),
        "rank": e["rank"],
        "computed_at": fmt_dt(e["computed_at"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_award(e):
    return {
        "id": e["id"],
        "fleet_id": e["fleet_id"],
        "driver_id": e["driver_id"],
        "snapshot_id": e["snapshot_id"],
        "period_start": fmt_dt(e["period_start"]),
        "period_end": fmt_dt(e["period_end"]),
        "tier": e["tier"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }

# ---------------------------------------------------------------------------
# Domain queries & calculations
# ---------------------------------------------------------------------------

def fleet_of_terminal(tid):
    t = DB.entities["terminals"].get(tid)
    return t["fleet_id"] if t else None


def active_policy(fleet_id):
    for p in DB.entities["camera_policies"].values():
        if p["fleet_id"] == fleet_id and p["status"] == "ACTIVE":
            return p
    return None


def ratified_agreement_covering(terminal_id, instant):
    """RATIFIED agreement of the terminal whose closed window covers instant."""
    for a in DB.entities["union_agreements"].values():
        if (a["terminal_id"] == terminal_id and a["status"] == "RATIFIED"
                and a["effective_from"] <= instant <= a["effective_until"]):
            return a
    return None


def inward_gate_check(event_or_driver_id, fleet_id):
    """Raise ERR_INWARD_FOOTAGE_RESTRICTED unless the three switches all permit."""
    policy = active_policy(fleet_id)
    if policy is None or not policy["inward_capture_enabled"]:
        raise err("ERR_INWARD_FOOTAGE_RESTRICTED", 422,
                  "Inward-facing capture is not permitted by the active camera policy")
    driver = DB.entities["drivers"][event_or_driver_id]
    agr = ratified_agreement_covering(driver["terminal_id"], now_logical())
    if agr is not None and not agr["inward_camera_allowed"]:
        raise err("ERR_INWARD_FOOTAGE_RESTRICTED", 422,
                  "Inward-facing footage is not allowed by the covering union agreement")
    if not driver["inward_camera_consent"]:
        raise err("ERR_INWARD_FOOTAGE_RESTRICTED", 422,
                  "Driver has not consented to inward-facing capture")


def driver_events(driver_id):
    return [e for e in DB.entities["safety_events"].values() if e["driver_id"] == driver_id]


def confirmed_count(driver_id, clock=None):
    clock = clock or now_logical()
    lo = clock - timedelta(days=90)
    n = 0
    for e in driver_events(driver_id):
        if e["status"] == "CONFIRMED" and lo <= e["occurred_at"] <= clock:
            n += 1
    return n


def driver_score(driver_id, variant, clock=None):
    """Compute driver safety score (Decimal, 2dp). variant in {provisional, final}."""
    clock = clock or now_logical()
    statuses = {"IN_REVIEW", "CONFIRMED", "RECLASSIFIED"} if variant == "provisional" else {"CONFIRMED"}
    total = Decimal("0")
    for e in driver_events(driver_id):
        if e["status"] not in statuses:
            continue
        age = clock - e["occurred_at"]
        if age < timedelta(0):
            continue
        if age <= timedelta(days=30):
            factor = Decimal("1.00")
        elif age <= timedelta(days=90):
            factor = AGED_FACTOR
        else:
            continue
        raw = Decimal(SEVERITY_WEIGHT[e["severity"]]) * PENALTY_FACTOR * factor
        total += raw.quantize(Q2, rounding=ROUND_HALF_UP)
    score = Decimal("100") - total
    if score < Decimal("0"):
        score = Decimal("0")
    if score > Decimal("100"):
        score = Decimal("100")
    return score.quantize(Q2, rounding=ROUND_HALF_UP)


def terminal_score(terminal_id):
    finals = []
    for d in DB.entities["drivers"].values():
        if d["terminal_id"] == terminal_id and d["status"] in ("ACTIVE", "SUSPENDED", "COACHING_HOLD"):
            finals.append(driver_score(d["id"], "final"))
    if not finals:
        return Decimal("100.00")
    mean = sum(finals) / Decimal(len(finals))
    return mean.quantize(Q2, rounding=ROUND_HALF_UP)


def fleet_score(fleet_id):
    scores = []
    for t in DB.entities["terminals"].values():
        if t["fleet_id"] != fleet_id:
            continue
        has_driver = any(
            d["terminal_id"] == t["id"] and d["status"] != "INACTIVE"
            for d in DB.entities["drivers"].values()
        )
        if has_driver:
            scores.append(terminal_score(t["id"]))
    if not scores:
        return Decimal("100.00")
    mean = sum(scores) / Decimal(len(scores))
    return mean.quantize(Q2, rounding=ROUND_HALF_UP)


def price_tier(score):
    score = Decimal(score)
    if score >= Decimal("95.00"):
        return "GOLD"
    if score >= Decimal("90.00"):
        return "SILVER"
    if score >= Decimal("80.00"):
        return "BRONZE"
    return "NONE"


def retention_used_mb(fleet_id):
    total = 0
    for c in DB.entities["footage_clips"].values():
        ev = DB.entities["safety_events"].get(c["event_id"])
        if ev and ev["fleet_id"] == fleet_id and c["upload_status"] != "PURGED":
            total += c["size_mb"]
    return total


def daily_used_mb(fleet_id, clock):
    day = clock.date()
    total = 0
    for c in DB.entities["footage_clips"].values():
        ev = DB.entities["safety_events"].get(c["event_id"])
        if ev and ev["fleet_id"] == fleet_id and c["uploaded_at"] is not None \
                and c["uploaded_at"].date() == day:
            total += c["size_mb"]
    return total


def hold_covers(hold, clip):
    """True when ACTIVE hold covers clip's event or its driver."""
    ev = DB.entities["safety_events"].get(clip["event_id"])
    if ev is None:
        return False
    if hold["scope"] == "EVENT":
        return hold["event_id"] == ev["id"]
    return hold["driver_id"] == ev["driver_id"]


def clip_has_active_hold(clip, excluding_hold_id=None):
    for h in DB.entities["litigation_holds"].values():
        if h["status"] == "ACTIVE" and h["id"] != excluding_hold_id and hold_covers(h, clip):
            return True
    return False


def deterministic_class(event):
    return "COLLISION" if event["event_type"] == "COLLISION" else "STANDARD"


def clips_covered_by_hold(hold):
    out = []
    for c in DB.entities["footage_clips"].values():
        if hold_covers(hold, c):
            out.append(c)
    return out


def steward_required(session):
    driver = DB.entities["drivers"].get(session["driver_id"])
    if driver is None:
        return False
    agr = ratified_agreement_covering(driver["terminal_id"], session["starts_at"])
    return bool(agr and agr["coaching_requires_steward_present"])


def occupying_sessions(driver_id, exclude_id=None):
    return [s for s in DB.entities["coaching_sessions"].values()
            if s["driver_id"] == driver_id and s["id"] != exclude_id
            and s["status"] in ("ASSIGNED", "ACKNOWLEDGED", "OVERDUE")]


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def open_cases_for_driver(driver_id):
    return [c for c in DB.entities["escalation_cases"].values()
            if c["driver_id"] == driver_id and c["status"] in ("OPEN", "UNDER_REVIEW")]

# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_sessions_for_event(event_id):
    for s in DB.entities["coaching_sessions"].values():
        if s["event_id"] == event_id and s["status"] in ("ASSIGNED", "ACKNOWLEDGED", "OVERDUE"):
            s["status"] = "CANCELLED"
            touch(s)


def unwind_escalation_if_below_threshold(driver_id):
    driver = DB.entities["drivers"][driver_id]
    if confirmed_count(driver_id) >= 3:
        return
    for c in list(DB.entities["escalation_cases"].values()):
        if c["driver_id"] == driver_id and c["status"] in ("OPEN", "UNDER_REVIEW"):
            c["status"] = "RESOLVED_NO_ACTION"
            touch(c)
    if driver["status"] == "COACHING_HOLD" and not open_cases_for_driver(driver_id):
        driver["status"] = "ACTIVE"
        touch(driver)


def maybe_release_hold(driver_id):
    driver = DB.entities["drivers"][driver_id]
    if driver["status"] == "COACHING_HOLD" and not open_cases_for_driver(driver_id):
        driver["status"] = "ACTIVE"
        touch(driver)


def apply_exoneration(event):
    """SafetyEvent CONFIRMED -> EXONERATED with the full compensation cascade."""
    event["status"] = "EXONERATED"
    event["confirmed_at"] = None
    touch(event)
    cancel_sessions_for_event(event["id"])
    unwind_escalation_if_below_threshold(event["driver_id"])


def recompute_ranks(fleet_id, period_start, period_end):
    """Recompute rank over DRIVER-scope FINAL snapshots of fleet+period."""
    cands = [s for s in DB.entities["score_snapshots"].values()
             if s["fleet_id"] == fleet_id and s["scope_type"] == "DRIVER"
             and s["status"] == "FINAL"
             and s["period_start"] == period_start and s["period_end"] == period_end]

    def period_confirmed_count(snapshot):
        d = DB.entities["drivers"].get(snapshot["scope_id"])
        if d is None:
            return 0
        n = 0
        for e in driver_events(d["id"]):
            if e["status"] == "CONFIRMED" and period_start <= e["occurred_at"] <= period_end:
                n += 1
        return n

    info = {}
    for s in cands:
        d = DB.entities["drivers"].get(s["scope_id"])
        info[s["id"]] = (period_confirmed_count(s), d["created_at"] if d else DEFAULT_CLOCK)

    for s in cands:
        my = info[s["id"]]
        rank = 1
        for o in cands:
            if o["id"] == s["id"]:
                continue
            oo = info[o["id"]]
            if o["score"] > s["score"]:
                rank += 1
            elif o["score"] == s["score"]:
                if oo[0] < my[0]:
                    rank += 1
                elif oo[0] == my[0] and oo[1] < my[1]:
                    rank += 1
        if s["rank"] != rank:
            s["rank"] = rank
            touch(s)


def upsert_award(snapshot):
    """DRIVER-scope snapshot pricing: create/reprice IncentiveAward for (driver, period)."""
    tier = price_tier(snapshot["score"])
    amount = TIER_AMOUNT[tier]
    award = None
    for a in DB.entities["incentive_awards"].values():
        if (a["driver_id"] == snapshot["scope_id"]
                and a["period_start"] == snapshot["period_start"]
                and a["period_end"] == snapshot["period_end"]):
            award = a
            break
    if award is None:
        award = new_entity("incentive_awards")
        award.update({
            "fleet_id": snapshot["fleet_id"],
            "driver_id": snapshot["scope_id"],
            "snapshot_id": snapshot["id"],
            "period_start": snapshot["period_start"],
            "period_end": snapshot["period_end"],
            "tier": tier,
            "amount_cents": amount,
            "status": "FORFEITED" if (snapshot["status"] == "FINAL" and tier == "NONE") else "PROJECTED",
        })
    else:
        changed = (award["tier"] != tier or award["amount_cents"] != amount
                   or award["snapshot_id"] != snapshot["id"])
        award["tier"] = tier
        award["amount_cents"] = amount
        award["snapshot_id"] = snapshot["id"]
        if snapshot["status"] == "FINAL" and tier == "NONE" and award["status"] == "PROJECTED":
            award["status"] = "FORFEITED"
            changed = True
        if changed:
            touch(award)
    return award

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.before_request
def _before():
    if request.path.startswith("/api"):
        check_auth()


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _nf(e):
    return error_response(err("ERR_VALIDATION", 404, "Not found"))


@app.errorhandler(405)
def _mna(e):
    return error_response(err("ERR_VALIDATION", 405, "Method not allowed"))


@app.errorhandler(Exception)
def _generic(e):
    if isinstance(e, ApiError):
        return error_response(e)
    app.logger.exception("unhandled")
    return error_response(err("ERR_VALIDATION", 500, f"Internal error: {e}"))

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route("/api/_clock/set_current_utc", methods=["POST"])
def clock_set():
    data = body()
    to = req_field(data, "to_iso8601")
    new_clock = parse_dt(to, "to_iso8601")
    DB.clock = new_clock
    DB.clock_set = True
    return ok({"current_utc": fmt_dt(DB.clock)})

# ---------------------------------------------------------------------------
# Fleets
# ---------------------------------------------------------------------------

@app.route("/api/fleets", methods=["POST"])
def fleet_create():
    data = body()
    name = req_string(data, "name")
    budget = req_int(data, "incentive_budget_cents", min_val=0)
    f = new_entity("fleets")
    f.update({"name": name, "incentive_budget_cents": budget,
              "posture": "NORMAL", "ops_run_index": 0})
    return ok(ser_fleet(f), 201)


@app.route("/api/fleets/<id>", methods=["GET"])
def fleet_get(id):
    return ok(ser_fleet(get_or_404("fleets", id)))


@app.route("/api/fleets/<id>/posture", methods=["POST"])
def fleet_posture(id):
    data = body()
    posture = req_enum(data, "posture", ["NORMAL", "INCIDENT_LOCKDOWN"])
    opt_string(data, "note")
    f = get_or_404("fleets", id)
    if f["posture"] != posture:
        f["posture"] = posture
        touch(f)
    return ok(ser_fleet(f))


@app.route("/api/fleets/<id>/leaderboard", methods=["GET"])
def fleet_leaderboard(id):
    get_or_404("fleets", id)
    ps_raw = request.args.get("period_start")
    pe_raw = request.args.get("period_end")
    if ps_raw is None or pe_raw is None:
        raise err("ERR_VALIDATION", 400, "period_start and period_end are required")
    ps = parse_dt(ps_raw, "period_start")
    pe = parse_dt(pe_raw, "period_end")
    rows = [s for s in DB.entities["score_snapshots"].values()
            if s["fleet_id"] == id and s["scope_type"] == "DRIVER" and s["status"] == "FINAL"
            and s["period_start"] == ps and s["period_end"] == pe]
    rows.sort(key=lambda s: (s["rank"] if s["rank"] is not None else 1 << 30, s["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_snapshot(s) for s in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/run-maintenance", methods=["POST"])
def fleet_run_maintenance(id):
    f = get_or_404("fleets", id)
    clock = now_logical()
    f["ops_run_index"] += 1
    # sweep overdue sessions of this fleet, ordered due_at ASC, created_at ASC
    sessions = []
    for s in DB.entities["coaching_sessions"].values():
        d = DB.entities["drivers"].get(s["driver_id"])
        if d is None:
            continue
        t = DB.entities["terminals"].get(d["terminal_id"])
        if t is None or t["fleet_id"] != id:
            continue
        if s["status"] in ("ASSIGNED", "ACKNOWLEDGED") and s["due_at"] < clock:
            sessions.append(s)
    sessions.sort(key=lambda s: (s["due_at"], s["created_at"], s["_seq"]))
    for s in sessions:
        s["status"] = "OVERDUE"
        touch(s)
    touch(f)
    return ok(ser_fleet(f))


@app.route("/api/fleets/<id>/terminals", methods=["GET"])
def fleet_terminals(id):
    get_or_404("fleets", id)
    rows = sorted([t for t in DB.entities["terminals"].values() if t["fleet_id"] == id],
                  key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_terminal(t) for t in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/camera-policies", methods=["GET"])
def fleet_policies(id):
    get_or_404("fleets", id)
    status = request.args.get("status")
    rows = [p for p in DB.entities["camera_policies"].values() if p["fleet_id"] == id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_policy(p) for p in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/safety-events", methods=["GET"])
def fleet_events(id):
    get_or_404("fleets", id)
    rows = [e for e in DB.entities["safety_events"].values() if e["fleet_id"] == id]
    status = request.args.get("status")
    etype = request.args.get("event_type")
    did = request.args.get("driver_id")
    vid = request.args.get("vehicle_id")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    if etype is not None:
        rows = [e for e in rows if e["event_type"] == etype]
    if did is not None:
        rows = [e for e in rows if e["driver_id"] == did]
    if vid is not None:
        rows = [e for e in rows if e["vehicle_id"] == vid]
    rows.sort(key=lambda e: (-e["upload_priority_score"], e["occurred_at"], e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_event(e) for e in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/litigation-holds", methods=["GET"])
def fleet_holds(id):
    get_or_404("fleets", id)
    rows = [h for h in DB.entities["litigation_holds"].values() if h["fleet_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_hold(h) for h in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/score-snapshots", methods=["GET"])
def fleet_snapshots(id):
    get_or_404("fleets", id)
    rows = [s for s in DB.entities["score_snapshots"].values() if s["fleet_id"] == id]
    status = request.args.get("status")
    scope = request.args.get("scope_type")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if scope is not None:
        rows = [s for s in rows if s["scope_type"] == scope]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_snapshot(s) for s in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/incentive-awards", methods=["GET"])
def fleet_awards(id):
    get_or_404("fleets", id)
    rows = [a for a in DB.entities["incentive_awards"].values() if a["fleet_id"] == id]
    status = request.args.get("status")
    tier = request.args.get("tier")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if tier is not None:
        rows = [a for a in rows if a["tier"] == tier]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_award(a) for a in page], is_list=True, pagination=pg)


@app.route("/api/fleets/<id>/score-snapshots/compute", methods=["POST"])
def fleet_snapshot_compute(id):
    data = body()
    scope_type = req_enum(data, "scope_type", ["DRIVER", "TERMINAL", "FLEET"])
    ps = parse_dt(req_field(data, "period_start"), "period_start")
    pe = parse_dt(req_field(data, "period_end"), "period_end")
    if pe < ps:
        raise err("ERR_VALIDATION", 400, "period_end must be >= period_start")
    finalize = opt_bool(data, "finalize")
    if finalize is None:
        finalize = False
    scope_id = data.get("scope_id")
    if scope_type == "FLEET":
        scope_id = None
    else:
        if scope_id is None:
            raise err("ERR_VALIDATION", 400, "scope_id is required for DRIVER/TERMINAL scope")
        if not isinstance(scope_id, str):
            raise err("ERR_VALIDATION", 400, "scope_id must be a string")
    f = get_or_404("fleets", id)
    if f["posture"] != "NORMAL":
        raise err("ERR_FLEET_LOCKED", 409, "Fleet is in INCIDENT_LOCKDOWN")
    if scope_type == "DRIVER":
        d = DB.entities["drivers"].get(scope_id)
        if d is None:
            raise err("ERR_DRIVER_NOT_FOUND", 404, "driver not found")
        score = driver_score(scope_id, "final" if finalize else "provisional")
    elif scope_type == "TERMINAL":
        t = DB.entities["terminals"].get(scope_id)
        if t is None:
            raise err("ERR_TERMINAL_NOT_FOUND", 404, "terminal not found")
        score = terminal_score(scope_id)
    else:
        score = fleet_score(id)
    snap = new_entity("score_snapshots")
    snap.update({
        "fleet_id": id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "period_start": ps,
        "period_end": pe,
        "status": "FINAL" if finalize else "PROVISIONAL",
        "score": score,
        "rank": None,
        "computed_at": now_logical(),
    })
    if scope_type == "DRIVER":
        upsert_award(snap)
        if finalize:
            recompute_ranks(id, ps, pe)
    return ok(ser_snapshot(snap), 201)

# ---------------------------------------------------------------------------
# Terminals
# ---------------------------------------------------------------------------

@app.route("/api/terminals", methods=["POST"])
def terminal_create():
    data = body()
    fleet_id = req_string(data, "fleet_id")
    name = req_string(data, "name")
    region = req_string(data, "region_code")
    get_or_404("fleets", fleet_id)
    t = new_entity("terminals")
    t.update({"fleet_id": fleet_id, "name": name, "region_code": region})
    return ok(ser_terminal(t), 201)


@app.route("/api/terminals/<id>", methods=["GET"])
def terminal_get(id):
    return ok(ser_terminal(get_or_404("terminals", id)))


def _list_by(items, ser):
    rows = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page, pg = paginate(rows)
    return ok([ser(x) for x in page], is_list=True, pagination=pg)


@app.route("/api/terminals/<id>/drivers", methods=["GET"])
def terminal_drivers(id):
    get_or_404("terminals", id)
    rows = [d for d in DB.entities["drivers"].values() if d["terminal_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return _list_by(rows, ser_driver)


@app.route("/api/terminals/<id>/vehicles", methods=["GET"])
def terminal_vehicles(id):
    get_or_404("terminals", id)
    rows = [v for v in DB.entities["vehicles"].values() if v["terminal_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    return _list_by(rows, ser_vehicle)


@app.route("/api/terminals/<id>/union-agreements", methods=["GET"])
def terminal_agreements(id):
    get_or_404("terminals", id)
    rows = [a for a in DB.entities["union_agreements"].values() if a["terminal_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return _list_by(rows, ser_agreement)

# ---------------------------------------------------------------------------
# Union agreements
# ---------------------------------------------------------------------------

@app.route("/api/union-agreements", methods=["POST"])
def agreement_create():
    data = body()
    terminal_id = req_string(data, "terminal_id")
    code = req_string(data, "agreement_code")
    inward = req_bool(data, "inward_camera_allowed")
    live = req_bool(data, "live_view_allowed")
    audio = req_bool(data, "audio_recording_allowed")
    steward = req_bool(data, "coaching_requires_steward_present")
    ef = parse_dt(req_field(data, "effective_from"), "effective_from")
    eu = parse_dt(req_field(data, "effective_until"), "effective_until")
    if eu <= ef:
        raise err("ERR_VALIDATION", 400, "effective_until must be strictly after effective_from")
    get_or_404("terminals", terminal_id)
    for a in DB.entities["union_agreements"].values():
        if a["terminal_id"] == terminal_id and a["agreement_code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", 409, "agreement_code already used in this terminal")
    a = new_entity("union_agreements")
    a.update({
        "terminal_id": terminal_id, "agreement_code": code,
        "inward_camera_allowed": inward, "live_view_allowed": live,
        "audio_recording_allowed": audio,
        "coaching_requires_steward_present": steward,
        "effective_from": ef, "effective_until": eu,
        "status": "DRAFT",
    })
    return ok(ser_agreement(a), 201)


@app.route("/api/union-agreements/<id>", methods=["GET"])
def agreement_get(id):
    return ok(ser_agreement(get_or_404("union_agreements", id)))


@app.route("/api/union-agreements/<id>/ratify", methods=["POST"])
def agreement_ratify(id):
    a = get_or_404("union_agreements", id)
    if a["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Only a DRAFT agreement may be ratified")
    for o in DB.entities["union_agreements"].values():
        if (o["id"] != a["id"] and o["terminal_id"] == a["terminal_id"]
                and o["status"] == "RATIFIED"
                and o["effective_from"] <= a["effective_until"]
                and a["effective_from"] <= o["effective_until"]):
            raise err("ERR_AGREEMENT_WINDOW_OVERLAP", 409,
                      "Another RATIFIED agreement of this terminal overlaps this window")
    a["status"] = "RATIFIED"
    touch(a)
    return ok(ser_agreement(a))


@app.route("/api/union-agreements/<id>/expire", methods=["POST"])
def agreement_expire(id):
    a = get_or_404("union_agreements", id)
    if a["status"] != "RATIFIED":
        raise err("ERR_INVALID_STATE", 409, "Only a RATIFIED agreement may be expired")
    a["status"] = "EXPIRED"
    touch(a)
    return ok(ser_agreement(a))

# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

@app.route("/api/drivers", methods=["POST"])
def driver_create():
    data = body()
    terminal_id = req_string(data, "terminal_id")
    employee_ref = req_string(data, "employee_ref")
    name = req_string(data, "name")
    hire = parse_dt(req_field(data, "hire_date"), "hire_date")
    consent = req_bool(data, "inward_camera_consent")
    t = get_or_404("terminals", terminal_id)
    for d in DB.entities["drivers"].values():
        dt = DB.entities["terminals"].get(d["terminal_id"])
        if dt and dt["fleet_id"] == t["fleet_id"] and d["employee_ref"] == employee_ref:
            raise err("ERR_DUPLICATE_RESOURCE", 409, "employee_ref already used within the fleet")
    d = new_entity("drivers")
    d.update({"terminal_id": terminal_id, "employee_ref": employee_ref, "name": name,
              "hire_date": hire, "inward_camera_consent": consent, "status": "ACTIVE"})
    return ok(ser_driver(d), 201)


@app.route("/api/drivers/<id>", methods=["GET"])
def driver_get(id):
    return ok(ser_driver(get_or_404("drivers", id)))


@app.route("/api/drivers/<id>/status", methods=["POST"])
def driver_status(id):
    data = body()
    to_status = req_enum(data, "to_status", ["ACTIVE", "SUSPENDED", "INACTIVE"])
    opt_string(data, "reason")
    d = get_or_404("drivers", id)
    allowed = {
        ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "INACTIVE"), ("SUSPENDED", "INACTIVE"),
    }
    if (d["status"], to_status) not in allowed:
        raise err("ERR_INVALID_STATE", 409,
                  f"Cannot transition driver from {d['status']} to {to_status}")
    d["status"] = to_status
    touch(d)
    return ok(ser_driver(d))


@app.route("/api/drivers/<id>/safety-events", methods=["GET"])
def driver_events_list(id):
    get_or_404("drivers", id)
    rows = [e for e in DB.entities["safety_events"].values() if e["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return _list_by(rows, ser_event)


@app.route("/api/drivers/<id>/coaching-sessions", methods=["GET"])
def driver_sessions_list(id):
    get_or_404("drivers", id)
    rows = [s for s in DB.entities["coaching_sessions"].values() if s["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return _list_by(rows, ser_session)


@app.route("/api/drivers/<id>/coaching-sessions", methods=["POST"])
def driver_session_create(id):
    data = body()
    event_id = req_string(data, "event_id")
    starts = parse_dt(req_field(data, "starts_at"), "starts_at")
    ends = parse_dt(req_field(data, "ends_at"), "ends_at")
    due = parse_dt(req_field(data, "due_at"), "due_at")
    if not starts < ends:
        raise err("ERR_VALIDATION", 400, "starts_at must be strictly before ends_at")
    if due < ends:
        raise err("ERR_VALIDATION", 400, "due_at must be >= ends_at")
    d = get_or_404("drivers", id)
    ev = get_or_404("safety_events", event_id)
    if ev["status"] != "CONFIRMED":
        raise err("ERR_EVENT_NOT_CONFIRMED", 409, "Coaching session requires a CONFIRMED event")
    for s in occupying_sessions(id):
        if windows_overlap(starts, ends, s["starts_at"], s["ends_at"]):
            raise err("ERR_SESSION_WINDOW_OVERLAP", 409,
                      "Session window overlaps another occupying session")
    sess = new_entity("coaching_sessions")
    sess.update({
        "driver_id": id, "event_id": event_id,
        "assigned_by": request.headers.get("X-User-ID"),
        "starts_at": starts, "ends_at": ends, "due_at": due,
        "status": "ASSIGNED", "outcome": None, "reassign_count": 0,
        "completed_at": None,
    })
    return ok(ser_session(sess), 201)


@app.route("/api/drivers/<id>/escalation-cases", methods=["GET"])
def driver_cases_list(id):
    get_or_404("drivers", id)
    rows = [c for c in DB.entities["escalation_cases"].values() if c["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return _list_by(rows, ser_case)


@app.route("/api/drivers/<id>/exoneration-claims", methods=["GET"])
def driver_claims_list(id):
    get_or_404("drivers", id)
    rows = [c for c in DB.entities["exoneration_claims"].values() if c["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return _list_by(rows, ser_claim)


@app.route("/api/drivers/<id>/litigation-holds", methods=["GET"])
def driver_holds_list(id):
    get_or_404("drivers", id)
    rows = [h for h in DB.entities["litigation_holds"].values() if h["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    return _list_by(rows, ser_hold)


@app.route("/api/drivers/<id>/incentive-awards", methods=["GET"])
def driver_awards_list(id):
    get_or_404("drivers", id)
    rows = [a for a in DB.entities["incentive_awards"].values() if a["driver_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return _list_by(rows, ser_award)


@app.route("/api/drivers/<id>/score-snapshots", methods=["GET"])
def driver_snapshots_list(id):
    get_or_404("drivers", id)
    rows = [s for s in DB.entities["score_snapshots"].values()
            if s["scope_type"] == "DRIVER" and s["scope_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return _list_by(rows, ser_snapshot)

# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

@app.route("/api/vehicles", methods=["POST"])
def vehicle_create():
    data = body()
    terminal_id = req_string(data, "terminal_id")
    vin = req_string(data, "vin")
    cam = req_string(data, "camera_unit_id")
    tier = req_enum(data, "bandwidth_tier", ["LOW", "STANDARD", "HIGH"])
    t = get_or_404("terminals", terminal_id)
    for v in DB.entities["vehicles"].values():
        vt = DB.entities["terminals"].get(v["terminal_id"])
        if vt and vt["fleet_id"] == t["fleet_id"] and v["vin"] == vin:
            raise err("ERR_DUPLICATE_RESOURCE", 409, "vin already used within the fleet")
    v = new_entity("vehicles")
    v.update({"terminal_id": terminal_id, "vin": vin, "camera_unit_id": cam,
              "bandwidth_tier": tier, "status": "ACTIVE"})
    return ok(ser_vehicle(v), 201)


@app.route("/api/vehicles/<id>", methods=["GET"])
def vehicle_get(id):
    return ok(ser_vehicle(get_or_404("vehicles", id)))


@app.route("/api/vehicles/<id>/decommission", methods=["POST"])
def vehicle_decommission(id):
    v = get_or_404("vehicles", id)
    if v["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Only an ACTIVE vehicle may be decommissioned")
    for e in DB.entities["safety_events"].values():
        if e["vehicle_id"] == id and e["status"] in ("DETECTED", "IN_REVIEW"):
            raise err("ERR_INVALID_STATE", 409,
                      "Vehicle has events in DETECTED or IN_REVIEW")
    v["status"] = "DECOMMISSIONED"
    touch(v)
    return ok(ser_vehicle(v))


@app.route("/api/vehicles/<id>/safety-events", methods=["GET"])
def vehicle_events_list(id):
    get_or_404("vehicles", id)
    rows = [e for e in DB.entities["safety_events"].values() if e["vehicle_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return _list_by(rows, ser_event)

# ---------------------------------------------------------------------------
# Camera policies
# ---------------------------------------------------------------------------

POLICY_FIELDS = [
    "name", "retention_days_standard", "retention_days_collision",
    "daily_upload_cap_mb", "inward_capture_enabled",
    "distraction_detection_enabled", "seatbelt_detection_enabled", "effective_from",
]


def _validate_policy_field(name, value):
    if name == "name":
        if not isinstance(value, str):
            raise err("ERR_VALIDATION", 400, "name must be a string")
        return value
    if name in ("retention_days_standard", "retention_days_collision", "daily_upload_cap_mb"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise err("ERR_VALIDATION", 400, f"{name} must be an integer")
        return value
    if name in ("inward_capture_enabled", "distraction_detection_enabled", "seatbelt_detection_enabled"):
        if not isinstance(value, bool):
            raise err("ERR_VALIDATION", 400, f"{name} must be a boolean")
        return value
    if name == "effective_from":
        return parse_dt(value, "effective_from")
    raise err("ERR_VALIDATION", 400, f"Unknown field {name}")


def _check_policy_ranges(p):
    if p["retention_days_standard"] < 1:
        raise err("ERR_VALIDATION", 400, "retention_days_standard must be >= 1")
    if p["retention_days_collision"] < p["retention_days_standard"]:
        raise err("ERR_VALIDATION", 400,
                  "retention_days_collision must be >= retention_days_standard")
    if p["daily_upload_cap_mb"] < 1:
        raise err("ERR_VALIDATION", 400, "daily_upload_cap_mb must be >= 1")


@app.route("/api/camera-policies", methods=["POST"])
def policy_create():
    data = body()
    fleet_id = req_string(data, "fleet_id")
    name = req_string(data, "name")
    rds = req_int(data, "retention_days_standard")
    rdc = req_int(data, "retention_days_collision")
    cap = req_int(data, "daily_upload_cap_mb")
    inward = req_bool(data, "inward_capture_enabled")
    dist = req_bool(data, "distraction_detection_enabled")
    seat = req_bool(data, "seatbelt_detection_enabled")
    ef = parse_dt(req_field(data, "effective_from"), "effective_from")
    tmp = {"retention_days_standard": rds, "retention_days_collision": rdc,
           "daily_upload_cap_mb": cap}
    _check_policy_ranges(tmp)
    get_or_404("fleets", fleet_id)
    p = new_entity("camera_policies")
    p.update({
        "fleet_id": fleet_id, "name": name,
        "retention_days_standard": rds, "retention_days_collision": rdc,
        "daily_upload_cap_mb": cap, "inward_capture_enabled": inward,
        "distraction_detection_enabled": dist, "seatbelt_detection_enabled": seat,
        "effective_from": ef, "status": "DRAFT",
    })
    return ok(ser_policy(p), 201)


@app.route("/api/camera-policies/<id>", methods=["GET"])
def policy_get(id):
    return ok(ser_policy(get_or_404("camera_policies", id)))


@app.route("/api/camera-policies/<id>", methods=["PATCH"])
def policy_patch(id):
    data = body()
    expected = req_int(data, "expected_policy_version")
    p = get_or_404("camera_policies", id)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Only a DRAFT policy may be patched")
    if expected != p["version"]:
        raise err("ERR_STALE_POLICY_VERSION", 412, "expected_policy_version is stale")
    merged = dict(p)
    for f in POLICY_FIELDS:
        if f in data:
            merged[f] = _validate_policy_field(f, data[f])
    _check_policy_ranges(merged)
    for f in POLICY_FIELDS:
        if f in data:
            p[f] = merged[f]
    touch(p)
    return ok(ser_policy(p))


@app.route("/api/camera-policies/<id>/activate", methods=["POST"])
def policy_activate(id):
    p = get_or_404("camera_policies", id)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Only a DRAFT policy may be activated")
    for o in DB.entities["camera_policies"].values():
        if o["fleet_id"] == p["fleet_id"] and o["status"] == "ACTIVE":
            o["status"] = "ARCHIVED"
            touch(o)
    p["status"] = "ACTIVE"
    touch(p)
    return ok(ser_policy(p))


@app.route("/api/camera-policies/<id>/archive", methods=["POST"])
def policy_archive(id):
    p = get_or_404("camera_policies", id)
    if p["status"] == "ACTIVE":
        raise err("ERR_POLICY_IN_USE", 409, "The ACTIVE policy cannot be archived directly")
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Only a DRAFT policy may be archived")
    p["status"] = "ARCHIVED"
    touch(p)
    return ok(ser_policy(p))

# ---------------------------------------------------------------------------
# Safety events
# ---------------------------------------------------------------------------

def compute_upload_priority(event_type, severity, occurred_at, detected_at, bandwidth_tier):
    age_secs = (detected_at - occurred_at).total_seconds()
    age_hours = int(age_secs // 3600)
    if age_hours <= 6:
        age_step = 4
    elif age_hours <= 24:
        age_step = 2
    else:
        age_step = 1
    base = SEVERITY_WEIGHT[severity] * age_step * TIER_MULT[bandwidth_tier]
    if event_type == "COLLISION":
        base += COLLISION_BOOST
    return base


@app.route("/api/safety-events", methods=["POST"])
def event_create():
    data = body()
    fleet_id = req_string(data, "fleet_id")
    driver_id = req_string(data, "driver_id")
    vehicle_id = req_string(data, "vehicle_id")
    etype = req_enum(data, "event_type", EVENT_TYPES)
    severity = req_enum(data, "severity", SEVERITIES)
    occurred = parse_dt(req_field(data, "occurred_at"), "occurred_at")
    get_or_404("fleets", fleet_id)
    d = get_or_404("drivers", driver_id)
    v = get_or_404("vehicles", vehicle_id)
    clock = now_logical()
    if occurred > clock:
        raise err("ERR_EVENT_IN_FUTURE", 422, "occurred_at must not be after the logical clock")
    policy = active_policy(fleet_id)
    if policy is not None:
        if etype == "DISTRACTION" and not policy["distraction_detection_enabled"]:
            raise err("ERR_EVENT_TYPE_DISABLED", 422, "DISTRACTION detection is disabled")
        if etype == "SEAT_BELT" and not policy["seatbelt_detection_enabled"]:
            raise err("ERR_EVENT_TYPE_DISABLED", 422, "SEAT_BELT detection is disabled")
    score = compute_upload_priority(etype, severity, occurred, clock, v["bandwidth_tier"])
    e = new_entity("safety_events")
    e.update({
        "fleet_id": fleet_id, "driver_id": driver_id, "vehicle_id": vehicle_id,
        "event_type": etype, "severity": severity,
        "occurred_at": occurred, "detected_at": clock,
        "status": "DETECTED", "upload_priority_score": score,
        "confirmed_at": None, "review_count": 0,
    })
    return ok(ser_event(e), 201)


@app.route("/api/safety-events/<id>", methods=["GET"])
def event_get(id):
    return ok(ser_event(get_or_404("safety_events", id)))


@app.route("/api/safety-events/<id>/review", methods=["POST"])
def event_review(id):
    data = body()
    action = req_enum(data, "action", ["CONFIRM", "DISMISS", "RECLASSIFY", "REOPEN"])
    rationale = req_string(data, "rationale")
    expected = req_int(data, "expected_event_version")
    new_etype = opt_enum(data, "new_event_type", EVENT_TYPES)
    new_sev = opt_enum(data, "new_severity", SEVERITIES)
    e = get_or_404("safety_events", id)
    # state legality (priority 6)
    if action == "CONFIRM":
        if e["status"] != "IN_REVIEW":
            raise err("ERR_INVALID_STATE", 409, "CONFIRM requires status IN_REVIEW")
    elif action == "DISMISS":
        if e["status"] != "IN_REVIEW":
            raise err("ERR_INVALID_STATE", 409, "DISMISS requires status IN_REVIEW")
    elif action == "RECLASSIFY":
        if e["status"] != "IN_REVIEW":
            raise err("ERR_INVALID_STATE", 409, "RECLASSIFY requires status IN_REVIEW")
        applied_etype = new_etype if new_etype is not None else e["event_type"]
        applied_sev = new_sev if new_sev is not None else e["severity"]
        if applied_etype == e["event_type"] and applied_sev == e["severity"]:
            raise err("ERR_INVALID_STATE", 409,
                      "RECLASSIFY requires a changed new_event_type or new_severity")
    elif action == "REOPEN":
        if e["status"] not in ("RECLASSIFIED", "DISMISSED"):
            raise err("ERR_INVALID_STATE", 409, "REOPEN requires status RECLASSIFIED or DISMISSED")
    # safety/privacy gate (priority 7) — inward review gate
    if action == "CONFIRM":
        has_inward = any(
            c["event_id"] == e["id"] and c["camera_angle"] == "INWARD"
            for c in DB.entities["footage_clips"].values()
        )
        if has_inward:
            inward_gate_check(e["driver_id"], e["fleet_id"])
    # temporal rules (priority 8): none on review
    # OCC check
    if expected != e["version"]:
        raise err("ERR_STALE_EVENT_VERSION", 412, "expected_event_version is stale")
    # referenced-entity state (priority 9) for CONFIRM
    if action == "CONFIRM":
        f = DB.entities["fleets"][e["fleet_id"]]
        if f["posture"] != "NORMAL":
            raise err("ERR_FLEET_LOCKED", 409, "Fleet is in INCIDENT_LOCKDOWN")
        d = DB.entities["drivers"][e["driver_id"]]
        if d["status"] not in ("ACTIVE", "COACHING_HOLD"):
            raise err("ERR_DRIVER_NOT_ACTIVE", 409,
                      "CONFIRM requires driver ACTIVE or COACHING_HOLD")

    reviewer = request.headers.get("X-User-ID")
    clock = now_logical()

    # append decision
    dec = new_entity("review_decisions", common=False)
    dec.update({
        "event_id": e["id"],
        "reviewer_id": reviewer,
        "action": action,
        "prior_event_type": e["event_type"],
        "new_event_type": new_etype if action == "RECLASSIFY" else None,
        "prior_severity": e["severity"],
        "new_severity": new_sev if action == "RECLASSIFY" else None,
        "rationale": rationale,
        "decided_at": clock,
    })

    if action == "CONFIRM":
        e["status"] = "CONFIRMED"
        e["confirmed_at"] = clock
        e["review_count"] += 1
        touch(e)
        # link 1: auto coaching session on HIGH/CRITICAL
        if e["severity"] in ("HIGH", "CRITICAL"):
            sess = new_entity("coaching_sessions")
            end = clock + timedelta(days=7)
            sess.update({
                "driver_id": e["driver_id"], "event_id": e["id"],
                "assigned_by": "SYSTEM",
                "starts_at": clock, "ends_at": end, "due_at": end,
                "status": "ASSIGNED", "outcome": None, "reassign_count": 0,
                "completed_at": None,
            })
        # link 2: scores recomputed on read — nothing stored
        # link 3+4: escalation threshold crossing (exactly 2 -> >= 3)
        driver = DB.entities["drivers"][e["driver_id"]]
        new_count = confirmed_count(e["driver_id"])
        if new_count >= 3 and (new_count - 1) == 2 and driver["status"] == "ACTIVE":
            case = new_entity("escalation_cases")
            case.update({
                "driver_id": e["driver_id"], "trigger_event_id": e["id"],
                "offense_count": new_count, "window_days": 90,
                "status": "OPEN", "resolution_note": None,
            })
            driver["status"] = "COACHING_HOLD"
            touch(driver)
    elif action == "DISMISS":
        e["status"] = "DISMISSED"
        e["review_count"] += 1
        touch(e)
    elif action == "RECLASSIFY":
        if new_etype is not None:
            e["event_type"] = new_etype
        if new_sev is not None:
            e["severity"] = new_sev
        e["status"] = "RECLASSIFIED"
        e["review_count"] += 1
        touch(e)
    elif action == "REOPEN":
        e["status"] = "IN_REVIEW"
        e["review_count"] += 1
        touch(e)
    return ok(ser_event(e))


@app.route("/api/safety-events/<id>/footage-clips", methods=["GET"])
def event_clips_list(id):
    get_or_404("safety_events", id)
    rows = [c for c in DB.entities["footage_clips"].values() if c["event_id"] == id]
    return _list_by(rows, ser_clip)


@app.route("/api/safety-events/<id>/review-decisions", methods=["GET"])
def event_decisions_list(id):
    get_or_404("safety_events", id)
    rows = [d for d in DB.entities["review_decisions"].values() if d["event_id"] == id]
    rows.sort(key=lambda d: (d["decided_at"], d["created_at"], d["_seq"]))
    page, pg = paginate(rows)
    return ok([ser_decision(d) for d in page], is_list=True, pagination=pg)


@app.route("/api/safety-events/<id>/coaching-sessions", methods=["GET"])
def event_sessions_list(id):
    get_or_404("safety_events", id)
    rows = [s for s in DB.entities["coaching_sessions"].values() if s["event_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return _list_by(rows, ser_session)


@app.route("/api/safety-events/<id>/escalation-cases", methods=["GET"])
def event_cases_list(id):
    get_or_404("safety_events", id)
    rows = [c for c in DB.entities["escalation_cases"].values() if c["trigger_event_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return _list_by(rows, ser_case)


@app.route("/api/safety-events/<id>/exoneration-claims", methods=["POST"])
def event_claim_create(id):
    data = body()
    claim_ref = req_string(data, "claim_ref")
    police = opt_string(data, "police_report_ref")
    e = get_or_404("safety_events", id)
    clock = now_logical()
    # temporal window (priority 8)
    if e["confirmed_at"] is not None and clock > e["confirmed_at"] + timedelta(days=30):
        raise err("ERR_EXONERATION_WINDOW_EXPIRED", 422,
                  "Claim submitted more than 30 days after confirmation")
    # referenced-entity state (priority 9)
    if e["status"] != "CONFIRMED" or e["event_type"] != "COLLISION":
        raise err("ERR_CLAIM_REQUIRES_CONFIRMED_COLLISION", 409,
                  "Claim requires a CONFIRMED COLLISION event")
    # uniqueness (priority 10)
    for c in DB.entities["exoneration_claims"].values():
        if c["event_id"] == id and c["status"] != "REJECTED":
            raise err("ERR_DUPLICATE_CLAIM", 409, "A non-REJECTED claim already exists")
    c = new_entity("exoneration_claims")
    c.update({
        "event_id": id, "driver_id": e["driver_id"],
        "claim_ref": claim_ref, "police_report_ref": police,
        "status": "SUBMITTED", "submitted_at": clock,
        "decided_at": None, "decided_by": None,
    })
    return ok(ser_claim(c), 201)


@app.route("/api/safety-events/<id>/exoneration-claims", methods=["GET"])
def event_claims_list(id):
    get_or_404("safety_events", id)
    rows = [c for c in DB.entities["exoneration_claims"].values() if c["event_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return _list_by(rows, ser_claim)


@app.route("/api/safety-events/<id>/litigation-holds", methods=["GET"])
def event_holds_list(id):
    get_or_404("safety_events", id)
    rows = [h for h in DB.entities["litigation_holds"].values() if h["event_id"] == id]
    status = request.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    return _list_by(rows, ser_hold)

# ---------------------------------------------------------------------------
# Footage clips
# ---------------------------------------------------------------------------

@app.route("/api/footage-clips", methods=["POST"])
def clip_create():
    data = body()
    event_id = req_string(data, "event_id")
    angle = req_enum(data, "camera_angle", ["FORWARD", "INWARD", "SIDE"])
    size = req_int(data, "size_mb", min_val=1)
    captured = parse_dt(req_field(data, "captured_at"), "captured_at")
    ev = get_or_404("safety_events", event_id)
    # safety gate (priority 7) for INWARD
    if angle == "INWARD":
        inward_gate_check(ev["driver_id"], ev["fleet_id"])
    clock = now_logical()
    if captured > clock:
        raise err("ERR_EVENT_IN_FUTURE", 422, "captured_at must not be after the logical clock")
    c = new_entity("footage_clips")
    c.update({
        "event_id": event_id, "camera_angle": angle, "size_mb": size,
        "captured_at": captured,
        "upload_status": "QUEUED",
        "retention_class": "COLLISION" if ev["event_type"] == "COLLISION" else "STANDARD",
        "uploaded_at": None, "purged_at": None,
    })
    return ok(ser_clip(c), 201)


@app.route("/api/footage-clips/<id>", methods=["GET"])
def clip_get(id):
    return ok(ser_clip(get_or_404("footage_clips", id)))


@app.route("/api/footage-clips/<id>/upload-begin", methods=["POST"])
def clip_upload_begin(id):
    c = get_or_404("footage_clips", id)
    if c["upload_status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", 409, "upload-begin requires QUEUED")
    c["upload_status"] = "UPLOADING"
    touch(c)
    return ok(ser_clip(c))


@app.route("/api/footage-clips/<id>/upload-complete", methods=["POST"])
def clip_upload_complete(id):
    c = get_or_404("footage_clips", id)
    if c["upload_status"] != "UPLOADING":
        raise err("ERR_INVALID_STATE", 409, "upload-complete requires UPLOADING")
    ev = DB.entities["safety_events"][c["event_id"]]
    policy = active_policy(ev["fleet_id"])
    if policy is None:
        raise err("ERR_ACTIVE_POLICY_REQUIRED", 409,
                  "An ACTIVE camera policy is required to complete uploads")
    clock = now_logical()
    if daily_used_mb(ev["fleet_id"], clock) + c["size_mb"] > policy["daily_upload_cap_mb"]:
        raise err("ERR_DAILY_UPLOAD_CAP_EXCEEDED", 422, "Daily upload cap exceeded")
    c["upload_status"] = "UPLOADED"
    c["uploaded_at"] = clock
    touch(c)
    # bubble up: first clip of event to upload -> DETECTED -> IN_REVIEW
    if ev["status"] == "DETECTED":
        ev["status"] = "IN_REVIEW"
        touch(ev)
    return ok(ser_clip(c))


@app.route("/api/footage-clips/<id>/purge", methods=["POST"])
def clip_purge(id):
    c = get_or_404("footage_clips", id)
    if c["upload_status"] != "UPLOADED":
        raise err("ERR_INVALID_STATE", 409, "purge requires UPLOADED")
    ev = DB.entities["safety_events"][c["event_id"]]
    # litigation-hold block (priority 7)
    if c["retention_class"] == "LITIGATION_HOLD" or clip_has_active_hold(c):
        raise err("ERR_LITIGATION_HOLD_ACTIVE", 409,
                  "Clip is covered by an ACTIVE litigation hold")
    # retention expiry requires an ACTIVE policy
    policy = active_policy(ev["fleet_id"])
    if policy is None:
        raise err("ERR_ACTIVE_POLICY_REQUIRED", 409,
                  "An ACTIVE camera policy is required to evaluate retention")
    days = (policy["retention_days_standard"] if c["retention_class"] == "STANDARD"
            else policy["retention_days_collision"])
    clock = now_logical()
    if clock < c["captured_at"] + timedelta(days=days):
        raise err("ERR_RETENTION_NOT_EXPIRED", 409, "Retention period has not expired")
    c["upload_status"] = "PURGED"
    c["purged_at"] = clock
    touch(c)
    return ok(ser_clip(c))

# ---------------------------------------------------------------------------
# Coaching sessions
# ---------------------------------------------------------------------------

def fleet_of_session(sess):
    d = DB.entities["drivers"].get(sess["driver_id"])
    if d is None:
        return None
    t = DB.entities["terminals"].get(d["terminal_id"])
    if t is None:
        return None
    return DB.entities["fleets"].get(t["fleet_id"])


@app.route("/api/coaching-sessions/<id>", methods=["GET"])
def session_get(id):
    return ok(ser_session(get_or_404("coaching_sessions", id)))


@app.route("/api/coaching-sessions/<id>/acknowledge", methods=["POST"])
def session_ack(id):
    s = get_or_404("coaching_sessions", id)
    if request.headers.get("X-User-ID") != s["driver_id"]:
        raise err("ERR_FORBIDDEN", 403, "Drivers may acknowledge only their own sessions")
    if s["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", 409, "acknowledge requires ASSIGNED")
    s["status"] = "ACKNOWLEDGED"
    touch(s)
    return ok(ser_session(s))


@app.route("/api/coaching-sessions/<id>/complete", methods=["POST"])
def session_complete(id):
    data = body()
    outcome = req_enum(data, "outcome", ["PASS", "FAIL"])
    opt_string(data, "notes")
    s = get_or_404("coaching_sessions", id)
    if s["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", 409, "complete requires ACKNOWLEDGED")
    f = fleet_of_session(s)
    if f is not None and f["posture"] != "NORMAL":
        raise err("ERR_FLEET_LOCKED", 409, "Fleet is in INCIDENT_LOCKDOWN")
    s["status"] = "COMPLETED"
    s["outcome"] = outcome
    s["completed_at"] = now_logical()
    touch(s)
    return ok(ser_session(s))


@app.route("/api/coaching-sessions/<id>/reassign", methods=["POST"])
def session_reassign(id):
    data = body()
    starts = parse_dt(req_field(data, "starts_at"), "starts_at")
    ends = parse_dt(req_field(data, "ends_at"), "ends_at")
    due = parse_dt(req_field(data, "due_at"), "due_at")
    opt_string(data, "reason")
    if not starts < ends:
        raise err("ERR_VALIDATION", 400, "starts_at must be strictly before ends_at")
    if due < ends:
        raise err("ERR_VALIDATION", 400, "due_at must be >= ends_at")
    s = get_or_404("coaching_sessions", id)
    if s["status"] != "OVERDUE":
        raise err("ERR_INVALID_STATE", 409, "reassign requires OVERDUE")
    for o in occupying_sessions(s["driver_id"], exclude_id=s["id"]):
        if windows_overlap(starts, ends, o["starts_at"], o["ends_at"]):
            raise err("ERR_SESSION_WINDOW_OVERLAP", 409,
                      "Session window overlaps another occupying session")
    s["starts_at"] = starts
    s["ends_at"] = ends
    s["due_at"] = due
    s["reassign_count"] += 1
    s["status"] = "ASSIGNED"
    touch(s)
    return ok(ser_session(s))


@app.route("/api/coaching-sessions/<id>/cancel", methods=["POST"])
def session_cancel(id):
    data = body()
    opt_string(data, "reason")
    s = get_or_404("coaching_sessions", id)
    if s["status"] not in ("ASSIGNED", "OVERDUE"):
        raise err("ERR_INVALID_STATE", 409, "cancel requires ASSIGNED or OVERDUE")
    s["status"] = "CANCELLED"
    touch(s)
    return ok(ser_session(s))

# ---------------------------------------------------------------------------
# Escalation cases
# ---------------------------------------------------------------------------

@app.route("/api/escalation-cases/<id>", methods=["GET"])
def case_get(id):
    return ok(ser_case(get_or_404("escalation_cases", id)))


@app.route("/api/escalation-cases/<id>/review", methods=["POST"])
def case_review(id):
    c = get_or_404("escalation_cases", id)
    if c["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "review requires OPEN")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok(ser_case(c))


@app.route("/api/escalation-cases/<id>/send-back", methods=["POST"])
def case_send_back(id):
    c = get_or_404("escalation_cases", id)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "send-back requires UNDER_REVIEW")
    c["status"] = "OPEN"
    touch(c)
    return ok(ser_case(c))


@app.route("/api/escalation-cases/<id>/resolve", methods=["POST"])
def case_resolve(id):
    data = body()
    resolution = req_enum(data, "resolution", ["ACTION_TAKEN", "CLOSED_NO_ACTION"])
    note = opt_string(data, "note")
    c = get_or_404("escalation_cases", id)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "resolve requires UNDER_REVIEW")
    driver = DB.entities["drivers"][c["driver_id"]]
    if resolution == "ACTION_TAKEN":
        c["status"] = "RESOLVED_ACTION"
        c["resolution_note"] = note
        touch(c)
        if driver["status"] == "COACHING_HOLD":
            driver["status"] = "SUSPENDED"
            touch(driver)
    else:
        c["status"] = "RESOLVED_NO_ACTION"
        c["resolution_note"] = note
        touch(c)
        if driver["status"] == "COACHING_HOLD" and not open_cases_for_driver(c["driver_id"]):
            driver["status"] = "ACTIVE"
            touch(driver)
    return ok(ser_case(c))

# ---------------------------------------------------------------------------
# Exoneration claims
# ---------------------------------------------------------------------------

@app.route("/api/exoneration-claims/<id>", methods=["GET"])
def claim_get(id):
    return ok(ser_claim(get_or_404("exoneration_claims", id)))


@app.route("/api/exoneration-claims/<id>/begin-review", methods=["POST"])
def claim_begin_review(id):
    c = get_or_404("exoneration_claims", id)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "begin-review requires SUBMITTED")
    c["status"] = "EVIDENCE_REVIEW"
    touch(c)
    return ok(ser_claim(c))


@app.route("/api/exoneration-claims/<id>/decide", methods=["POST"])
def claim_decide(id):
    data = body()
    decision = req_enum(data, "decision", ["EXONERATE", "REJECT"])
    req_string(data, "rationale")
    c = get_or_404("exoneration_claims", id)
    if c["status"] != "EVIDENCE_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "decide requires EVIDENCE_REVIEW")
    # segregation of duties (priority 7)
    uid = request.headers.get("X-User-ID")
    confirm_dec = None
    for d in DB.entities["review_decisions"].values():
        if d["event_id"] == c["event_id"] and d["action"] == "CONFIRM":
            if confirm_dec is None or (d["decided_at"], d["_seq"]) > (confirm_dec["decided_at"], confirm_dec["_seq"]):
                confirm_dec = d
    if confirm_dec is not None and confirm_dec["reviewer_id"] == uid:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403,
                  "The deciding adjuster must differ from the confirming reviewer")
    clock = now_logical()
    c["decided_at"] = clock
    c["decided_by"] = uid
    if decision == "EXONERATE":
        c["status"] = "EXONERATED"
        touch(c)
        ev = DB.entities["safety_events"][c["event_id"]]
        if ev["status"] == "CONFIRMED":
            apply_exoneration(ev)
    else:
        c["status"] = "REJECTED"
        touch(c)
    return ok(ser_claim(c))

# ---------------------------------------------------------------------------
# Litigation holds
# ---------------------------------------------------------------------------

@app.route("/api/litigation-holds", methods=["POST"])
def hold_create():
    data = body()
    fleet_id = req_string(data, "fleet_id")
    scope = req_enum(data, "scope", ["DRIVER", "EVENT"])
    reason = req_string(data, "reason")
    driver_id = data.get("driver_id")
    event_id = data.get("event_id")
    if scope == "DRIVER":
        if driver_id is None or not isinstance(driver_id, str):
            raise err("ERR_VALIDATION", 400, "driver_id is required for scope DRIVER")
        event_id = None
    else:
        if event_id is None or not isinstance(event_id, str):
            raise err("ERR_VALIDATION", 400, "event_id is required for scope EVENT")
        driver_id = None
    get_or_404("fleets", fleet_id)
    if scope == "DRIVER":
        get_or_404("drivers", driver_id)
        for h in DB.entities["litigation_holds"].values():
            if h["scope"] == "DRIVER" and h["driver_id"] == driver_id and h["status"] == "ACTIVE":
                raise err("ERR_ACTIVE_HOLD_EXISTS", 409,
                          "An ACTIVE hold already exists for this driver")
    else:
        get_or_404("safety_events", event_id)
        for h in DB.entities["litigation_holds"].values():
            if h["scope"] == "EVENT" and h["event_id"] == event_id and h["status"] == "ACTIVE":
                raise err("ERR_ACTIVE_HOLD_EXISTS", 409,
                          "An ACTIVE hold already exists for this event")
    h = new_entity("litigation_holds")
    h.update({
        "fleet_id": fleet_id, "driver_id": driver_id, "event_id": event_id,
        "scope": scope, "reason": reason, "status": "ACTIVE",
        "placed_at": now_logical(), "released_at": None,
        "placed_by": request.headers.get("X-User-ID"),
    })
    # covered, non-purged clips -> LITIGATION_HOLD
    for c in DB.entities["footage_clips"].values():
        if c["upload_status"] == "PURGED":
            continue
        if hold_covers(h, c) and c["retention_class"] != "LITIGATION_HOLD":
            c["retention_class"] = "LITIGATION_HOLD"
            touch(c)
    return ok(ser_hold(h), 201)


@app.route("/api/litigation-holds/<id>", methods=["GET"])
def hold_get(id):
    return ok(ser_hold(get_or_404("litigation_holds", id)))


@app.route("/api/litigation-holds/<id>/release", methods=["POST"])
def hold_release(id):
    h = get_or_404("litigation_holds", id)
    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "release requires ACTIVE")
    h["status"] = "RELEASED"
    h["released_at"] = now_logical()
    touch(h)
    for c in DB.entities["footage_clips"].values():
        if c["retention_class"] != "LITIGATION_HOLD":
            continue
        if not hold_covers(h, c):
            continue
        if clip_has_active_hold(c, excluding_hold_id=h["id"]):
            continue
        ev = DB.entities["safety_events"].get(c["event_id"])
        if ev is None:
            continue
        c["retention_class"] = deterministic_class(ev)
        touch(c)
    return ok(ser_hold(h))

# ---------------------------------------------------------------------------
# Snapshots & awards
# ---------------------------------------------------------------------------

@app.route("/api/score-snapshots/<id>", methods=["GET"])
def snapshot_get(id):
    return ok(ser_snapshot(get_or_404("score_snapshots", id)))


@app.route("/api/score-snapshots/<id>/incentive-awards", methods=["GET"])
def snapshot_awards(id):
    get_or_404("score_snapshots", id)
    rows = [a for a in DB.entities["incentive_awards"].values() if a["snapshot_id"] == id]
    return _list_by(rows, ser_award)


@app.route("/api/incentive-awards/<id>", methods=["GET"])
def award_get(id):
    return ok(ser_award(get_or_404("incentive_awards", id)))


@app.route("/api/incentive-awards/<id>/approve", methods=["POST"])
def award_approve(id):
    a = get_or_404("incentive_awards", id)
    if a["status"] != "PROJECTED":
        raise err("ERR_INVALID_STATE", 409, "approve requires PROJECTED")
    snap = DB.entities["score_snapshots"].get(a["snapshot_id"])
    if snap is None or snap["status"] != "FINAL":
        raise err("ERR_SNAPSHOT_NOT_FINAL", 409, "The pricing snapshot is not FINAL")
    if a["tier"] == "NONE":
        raise err("ERR_INVALID_STATE", 409, "Awards with tier NONE cannot be approved")
    a["status"] = "APPROVED"
    touch(a)
    return ok(ser_award(a))


@app.route("/api/incentive-awards/<id>/pay", methods=["POST"])
def award_pay(id):
    a = get_or_404("incentive_awards", id)
    if a["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", 409, "pay requires APPROVED")
    fleet = DB.entities["fleets"][a["fleet_id"]]
    total = sum(
        x["amount_cents"] for x in DB.entities["incentive_awards"].values()
        if x["fleet_id"] == a["fleet_id"] and x["status"] in ("APPROVED", "PAID")
    )
    if total > fleet["incentive_budget_cents"]:
        raise err("ERR_INCENTIVE_BUDGET_EXCEEDED", 402,
                  "Paying this award would exceed the fleet incentive budget")
    a["status"] = "PAID"
    touch(a)
    return ok(ser_award(a))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
