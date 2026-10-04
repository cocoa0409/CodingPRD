import calendar
import math

import db
from helpers import (
    active_plan, active_policy, add_days, format_dt, iso_now, parse_dt,
    touch, write_audit, write_custody, SYSTEM_ACTOR,
)

RETENTION_DAYS = {
    "INCIDENT": 180,
    "ARREST": 1095,
    "TRAFFIC_STOP": 90,
    "TRAINING": 30,
    "TEST": 7,
}

CASE_LINKED_EXTENSION_DAYS = {
    "INCIDENT": 730,
    "ARREST": 2555,
    "TRAFFIC_STOP": 365,
    "TRAINING": 30,
    "TEST": 7,
}

CATEGORIES = list(RETENTION_DAYS.keys())
TRIGGERS = ["MANUAL", "LIGHTBAR", "TASER_ARMED", "GUNSHOT_DETECTION", "DOOR_OPEN"]

GIB = 1073741824.0

CHARGE_RATE_PCT_PER_HOUR = 10

SINGLE_PASS_MIN_PER_MEDIA_MIN = 2
MULTI_PASS_MIN_PER_MEDIA_MIN = 5
LONG_FORM_THRESHOLD_MIN = 120
LONG_FORM_SURCHARGE_MIN = 30

COUNTED_STORAGE_STATES = ("ACTIVE", "RETENTION_DUE", "UNDER_REVIEW")


# ---------------------------------------------------------------- redaction

def redaction_effort_minutes(duration_seconds, scope_face, scope_audio, passes):
    duration_minutes = math.ceil(duration_seconds / 60.0)
    scope_count = (1 if scope_face else 0) + (1 if scope_audio else 0)
    if passes == "SINGLE_PASS":
        base = duration_minutes * SINGLE_PASS_MIN_PER_MEDIA_MIN
        multiplier = 1.0 if scope_count == 1 else 1.5
        return math.ceil(base * multiplier)
    # MULTI_PASS
    base = duration_minutes * MULTI_PASS_MIN_PER_MEDIA_MIN
    multiplier = 1.0 if scope_count == 1 else 2.0
    estimate = math.ceil(base * multiplier)
    if duration_minutes > LONG_FORM_THRESHOLD_MIN:
        estimate += LONG_FORM_SURCHARGE_MIN
    return estimate


# ---------------------------------------------------------------- storage

def storage_full_month_cost_cents(storage_used_bytes, plan):
    gib = storage_used_bytes / GIB
    return math.ceil(gib * plan["cost_per_gb_month_cents"])


def storage_projection_cost_cents(storage_used_bytes, plan):
    return storage_full_month_cost_cents(storage_used_bytes, plan)


def storage_accrued_cost_cents(storage_used_bytes, plan, now_dt):
    full = storage_full_month_cost_cents(storage_used_bytes, plan)
    days_in_month = calendar.monthrange(now_dt.year, now_dt.month)[1]
    day_index = now_dt.day
    return math.floor(full * day_index / days_in_month)


def recompute_agency_storage(agency):
    total = 0
    for r in db.collection("recordings").values():
        if r["agency_id"] == agency["id"] and r["upload_status"] in COUNTED_STORAGE_STATES:
            total += r["size_bytes"]
    changed = agency["storage_used_bytes"] != total
    agency["storage_used_bytes"] = total
    recompute_posture(agency)
    return changed


def recompute_posture(agency):
    plan = active_plan(agency["id"])
    if plan is None:
        posture = "OK"
    else:
        projected = storage_projection_cost_cents(agency["storage_used_bytes"], plan)
        if projected > plan["monthly_budget_cents"]:
            posture = "OVER_BUDGET"
        elif projected >= math.floor(plan["monthly_budget_cents"] * plan["alert_threshold_pct"] / 100):
            posture = "WARNING"
        else:
            posture = "OK"
    agency["storage_posture"] = posture


def touch_agency(agency):
    recompute_agency_storage(agency)
    touch(agency)


# ---------------------------------------------------------------- retention

def compute_recording_retention(recording):
    """Recompute retention_due_at from the recording's upload completion time
    (created_at) plus base category days, extended by any LINKED case links."""
    if recording.get("category") is None:
        recording["retention_due_at"] = None
        return
    base = RETENTION_DAYS[recording["category"]]
    due = parse_dt(recording["created_at"]) and add_days(recording["created_at"], base)
    ext_days = CASE_LINKED_EXTENSION_DAYS[recording["category"]]
    for link in db.collection("links").values():
        if link["recording_id"] == recording["id"] and link["status"] == "LINKED":
            candidate = add_days(link["created_at"], ext_days)
            if parse_dt(candidate) > parse_dt(due):
                due = candidate
    recording["retention_due_at"] = due


def recompute_case_rollup(case):
    links = [l for l in db.collection("links").values()
             if l["case_id"] == case["id"] and l["status"] == "LINKED"]
    case["evidence_count"] = len(links)
    total_bytes = 0
    dues = []
    for link in links:
        r = db.collection("recordings").get(link["recording_id"])
        if r is None:
            continue
        if r["upload_status"] != "PURGED":
            total_bytes += r["size_bytes"]
            if r.get("retention_due_at"):
                dues.append(r["retention_due_at"])
    case["total_evidence_bytes"] = total_bytes
    case["retention_due_at"] = max(dues) if dues else None


def touch_case(case):
    recompute_case_rollup(case)
    touch(case)


def linked_recordings(case_id):
    out = []
    for link in db.collection("links").values():
        if link["case_id"] == case_id and link["status"] == "LINKED":
            r = db.collection("recordings").get(link["recording_id"])
            if r is not None:
                out.append(r)
    return out


# ---------------------------------------------------------------- officers

def recompute_officer_metrics(officer):
    uploaded = 0
    pending = 0
    for r in db.collection("recordings").values():
        if r["officer_id"] == officer["id"]:
            if r["upload_status"] != "PURGED":
                uploaded += 1
            if r["review_status"] == "PENDING_REVIEW":
                pending += 1
    officer["recordings_uploaded_count"] = uploaded
    officer["pending_review_count"] = pending


def touch_officer(officer):
    recompute_officer_metrics(officer)
    touch(officer)


# ---------------------------------------------------------------- sampling

def apply_supervisor_sampling(recording, policy, officer):
    """Apply sampling rule at the INTEGRITY_VERIFIED -> ACTIVE transition.
    The officer's recordings_uploaded_count has already been incremented."""
    rate = policy["supervisor_review_rate_pct"]
    if rate == 0:
        recording["review_status"] = "NOT_FLAGGED"
        return
    modulus = 100 // rate
    ordinal = officer["recordings_uploaded_count"]
    if modulus > 0 and ordinal % modulus == 0:
        recording["review_status"] = "PENDING_REVIEW"
    else:
        recording["review_status"] = "NOT_FLAGGED"


# ---------------------------------------------------------------- legal holds

def recompute_legal_hold_count(recording):
    count = 0
    for h in db.collection("legal_holds").values():
        if h["agency_id"] != recording["agency_id"] or h["status"] != "ACTIVE":
            continue
        if h["scope_type"] == "RECORDING" and h.get("recording_id") == recording["id"]:
            count += 1
        elif h["scope_type"] == "CASE":
            for link in db.collection("links").values():
                if (link["recording_id"] == recording["id"]
                        and link["case_id"] == h.get("case_id")
                        and link["status"] == "LINKED"):
                    count += 1
                    break
    recording["legal_hold_count"] = count


def recompute_holds_for_case_recordings(case_id):
    for r in linked_recordings(case_id):
        recompute_legal_hold_count(r)
        touch(r)


# ---------------------------------------------------------------- dock charge

def dock_charge_gain(device, now_dt):
    docked_at = parse_dt(device.get("docked_at"))
    if docked_at is None or device.get("battery_pct_at_dock") is None:
        # Device was registered already DOCKED and never went through a dock
        # transition: no open charging session, so no gain.
        device["battery_pct"] = min(100, max(0, device["battery_pct"]))
        return 0
    elapsed_seconds = (now_dt - docked_at).total_seconds()
    elapsed_hours = int(elapsed_seconds // 3600)
    gain = min(elapsed_hours * CHARGE_RATE_PCT_PER_HOUR,
               100 - device["battery_pct_at_dock"])
    if gain < 0:
        gain = 0
    device["battery_pct"] = min(100, device["battery_pct_at_dock"] + gain)
    return gain
