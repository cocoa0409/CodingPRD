"""Advisory Loss Cost Bureau API — reference implementation.

In-memory only. No seeding, no disk persistence. The logical clock starts at
2026-09-01T00:00:00Z and only moves via POST /bureau/_clock/set_current_utc.
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

ROLES = {"BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser"}

TREND_RATE_PER_PERIOD = 0.04
TREND_PERIODS = 2.5
TARGET_LOSS_RATIO = 0.60
EXP_FACTOR = (1.0 + TREND_RATE_PER_PERIOD) ** TREND_PERIODS
LIN_FACTOR = 1.0 + TREND_RATE_PER_PERIOD * TREND_PERIODS

ERROR_PENALTY_BPS = 200
WARNING_PENALTY_BPS = 50
DECAY_BASE = 0.5

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

db = {
    "insurers": {},
    "statistical_plans": {},
    "submissions": {},
    "findings": {},
    "filings": {},
    "cells": {},
    "objections": {},
    "departments": {},
    "adoptions": {},
    "forms": {},
    "variants": {},
    "circulars": {},
    "agreements": {},
    "class_plans": {},
    "class_plan_revisions": {},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def parse_iso(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_clock_value(value):
    """Parse the logical clock value into a datetime.

    Supports plain ISO 8601 plus a small day-offset suffix grammar
    (e.g. "2026-09-01T00:00:00Z+31d") used by some harnesses.
    """
    m = re.match(r"^(.*?)(?:([+-])(\d+)d)?$", value.strip())
    base = parse_iso(m.group(1))
    if m.group(2) is not None:
        days = int(m.group(3))
        if m.group(2) == "-":
            days = -days
        base = base + timedelta(days=days)
    return base


def logical_clock():
    raw = db.get("_clock", DEFAULT_CLOCK_ISO)
    return parse_clock_value(raw)


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id():
    return uuid.uuid4().hex


def touch(record):
    record["updated_at"] = wall_now_iso()
    record["version"] = record.get("version", 1) + 1


def new_record(with_version=True):
    now = wall_now_iso()
    rec = {"id": new_id(), "created_at": now}
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": wall_now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, code=200, paginate=False):
    meta = meta_base()
    data = items
    if paginate:
        limit_raw = request.args.get("limit", "10")
        offset_raw = request.args.get("offset", "0")
        try:
            limit = int(limit_raw)
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid pagination parameters")
        if limit < 1 or limit > 100 or offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "pagination parameters out of range")
        total = len(items)
        data = items[offset : offset + limit]
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total
        meta["has_more"] = offset + limit < total
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), code


app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return handle_api_error(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------


def caller():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role not in ROLES or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unknown credentials")
    return {"role": role, "id": uid}


def require_roles(*roles):
    c = caller()
    if c["role"] not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")
    return c


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def body():
    return request.get_json(silent=True) or {}


def req_str(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be a string")
    return v


def req_int(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be an integer")
    return v


def req_enum(data, field, allowed, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} out of enum")
    return v


def req_dt(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be ISO 8601 datetime")
    return v


def get_or_404(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"resource not found: {rid}")
    return rec


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r["id"]))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_insurer(r):
    return {
        "id": r["id"],
        "insurer_code": r["insurer_code"],
        "legal_name": r["legal_name"],
        "insurer_status": r["insurer_status"],
        "quality_score_bps": r["quality_score_bps"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_plan(r):
    return {
        "id": r["id"],
        "plan_code": r["plan_code"],
        "line_of_business": r["line_of_business"],
        "min_premium_cents": r["min_premium_cents"],
        "max_record_age_months": r["max_record_age_months"],
        "plan_status": r["plan_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_submission(r):
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "plan_id": r["plan_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "record_count": r["record_count"],
        "written_premium_cents": r["written_premium_cents"],
        "submission_status": r["submission_status"],
        "accepted_record_count": r["accepted_record_count"],
        "error_finding_count": r["error_finding_count"],
        "warning_finding_count": r["warning_finding_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_finding(r):
    return {
        "id": r["id"],
        "submission_id": r["submission_id"],
        "edit_code": r["edit_code"],
        "severity": r["severity"],
        "affected_records": r["affected_records"],
        "created_at": r["created_at"],
    }


def ser_filing(r):
    return {
        "id": r["id"],
        "filing_code": r["filing_code"],
        "state_code": r["state_code"],
        "line_of_business": r["line_of_business"],
        "filing_version": r["filing_version"],
        "supersedes_filing_id": r["supersedes_filing_id"],
        "trend_selection": r["trend_selection"],
        "review_notes": r["review_notes"],
        "filing_status": r["filing_status"],
        "last_submitted_by_admin_id": r["last_submitted_by_admin_id"],
        "filed_at": r["filed_at"],
        "indicated_change_pct": r["indicated_change_pct"],
        "effective_date": r["effective_date"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_cell(r):
    return {
        "id": r["id"],
        "filing_id": r["filing_id"],
        "class_code": r["class_code"],
        "earned_premium_cents": r["earned_premium_cents"],
        "incurred_loss_cents": r["incurred_loss_cents"],
        "weight_pct": r["weight_pct"],
        "current_loss_cost_cents": r["current_loss_cost_cents"],
        "created_at": r["created_at"],
    }


def ser_objection(r):
    return {
        "id": r["id"],
        "filing_id": r["filing_id"],
        "department_id": r["department_id"],
        "objection_code": r["objection_code"],
        "objection_text": r["objection_text"],
        "raised_at": r["raised_at"],
        "created_at": r["created_at"],
    }


def ser_department(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "department_name": r["department_name"],
        "objection_window_days": r["objection_window_days"],
        "max_lcm_deviation_pct": r["max_lcm_deviation_pct"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_adoption(r):
    stale = False
    filing = db["filings"].get(r["filing_id"])
    if r["adoption_status"] == "AUTHORIZED" and filing is not None:
        for plan in db["class_plans"].values():
            if plan["line_of_business"] != filing["line_of_business"]:
                continue
            rev_id = plan.get("current_revision_id")
            if rev_id is None:
                continue
            rev = db["class_plan_revisions"].get(rev_id)
            if rev and rev["revision_status"] == "ACTIVATED":
                if (rev["activated_at"] or "") > (r["authorized_at"] or ""):
                    stale = True
                    break
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "filing_id": r["filing_id"],
        "multiplier_pct": r["multiplier_pct"],
        "adoption_status": r["adoption_status"],
        "authorized_premium_cents": r["authorized_premium_cents"],
        "rating_engine_stale": stale,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_form(r):
    return {
        "id": r["id"],
        "form_number": r["form_number"],
        "form_title": r["form_title"],
        "form_kind": r["form_kind"],
        "form_status": r["form_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_variant(r):
    return {
        "id": r["id"],
        "form_id": r["form_id"],
        "state_code": r["state_code"],
        "variant_text_ref": r["variant_text_ref"],
        "review_status": r["review_status"],
        "publication_status": r["publication_status"],
        "effective_from": r["effective_from"],
        "effective_to": r["effective_to"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_circular(r):
    return {
        "id": r["id"],
        "circular_number": r["circular_number"],
        "subject": r["subject"],
        "implementation_date": r["implementation_date"],
        "form_ids": list(r.get("form_ids", [])),
        "supersedes_circular_id": r["supersedes_circular_id"],
        "circular_status": r["circular_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_agreement(r):
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "coverage_start": r["coverage_start"],
        "coverage_end": r["coverage_end"],
        "royalty_rate_bps": r["royalty_rate_bps"],
        "agreement_status": r["agreement_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_class_plan(r):
    return {
        "id": r["id"],
        "class_plan_code": r["class_plan_code"],
        "line_of_business": r["line_of_business"],
        "current_revision_id": r["current_revision_id"],
        "plan_status": r["plan_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_revision(r):
    return {
        "id": r["id"],
        "class_plan_id": r["class_plan_id"],
        "revision_number": r["revision_number"],
        "class_count": r["class_count"],
        "revision_status": r["revision_status"],
        "activates_at": r["activates_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Business helpers
# ---------------------------------------------------------------------------


def withdraw_pending_adoptions(insurer_id, reason):
    for ad in db["adoptions"].values():
        if ad["insurer_id"] == insurer_id and ad["adoption_status"] == "PENDING":
            ad["adoption_status"] = "WITHDRAWN"
            ad["withdraw_reason"] = reason
            touch(ad)


def evaluate_lapse(agreement):
    """Lazy lapse evaluation on read / consultation. License coverage uses
    day-granularity date comparison (§2.9), so the agreement lapses once the
    logical clock's date is strictly later than the coverage_end date."""
    if agreement["agreement_status"] == "ACTIVE":
        if logical_clock().date() > parse_iso(agreement["coverage_end"]).date():
            agreement["agreement_status"] = "LAPSED"
            touch(agreement)
            withdraw_pending_adoptions(agreement["insurer_id"], "LICENCE_LAPSED")


def refresh_scheduled_variants():
    """Lazily move SCHEDULED variants to LIVE when their circular's
    implementation_date has been reached by the logical clock. The gate is
    the parent circular's implementation_date itself (§1.2 FormVariant), so
    a circular that has since been SUPERSEDED still drives the transition."""
    now = logical_clock()
    for circ in db["circulars"].values():
        if circ["circular_status"] not in ("PUBLISHED", "SUPERSEDED"):
            continue
        impl = parse_iso(circ["implementation_date"])
        if now < impl:
            continue
        for form_id in circ.get("form_ids", []):
            for var in db["variants"].values():
                if (
                    var["form_id"] == form_id
                    and var["publication_status"] == "SCHEDULED"
                ):
                    var["publication_status"] = "LIVE"
                    touch(var)


def covering_active_license(insurer_id):
    """Return a covering ACTIVE agreement for the insurer at the logical clock
    date (closed interval, day granularity), evaluating lapse lazily."""
    today = logical_clock().date()
    for ag in db["agreements"].values():
        if ag["insurer_id"] != insurer_id:
            continue
        evaluate_lapse(ag)
        if ag["agreement_status"] != "ACTIVE":
            continue
        start = parse_iso(ag["coverage_start"]).date()
        end = parse_iso(ag["coverage_end"]).date()
        if start <= today <= end:
            return ag
    return None


def compute_quality_score(insurer_id):
    terminal = [
        s
        for s in db["submissions"].values()
        if s["insurer_id"] == insurer_id
        and s["submission_status"] in ("ACCEPTED", "ACCEPTED_WITH_WARNINGS", "REJECTED")
    ]
    if not terminal:
        return 10000
    terminal.sort(key=lambda s: (s["updated_at"], s["created_at"], s["id"]))
    num = 0.0
    den = 0.0
    n = len(terminal)
    for idx, sub in enumerate(terminal):
        points = 10000 - ERROR_PENALTY_BPS * sub["error_finding_count"] - WARNING_PENALTY_BPS * sub["warning_finding_count"]
        points = max(0, points)
        k = n - idx  # most recent => k=1
        weight = DECAY_BASE ** (k - 1)
        num += points * weight
        den += weight
    score = int((num / den) + 0.5)
    return max(0, min(10000, score))


def compute_indicated_change(filing):
    cells = [c for c in db["cells"].values() if c["filing_id"] == filing["id"]]
    cells = sort_by_created(cells)
    inds = []
    for c in cells:
        raw = c["incurred_loss_cents"] / c["earned_premium_cents"]
        if filing["trend_selection"] == "EXPONENTIAL_LEAST_SQUARES":
            trended = raw * EXP_FACTOR
        else:
            trended = raw * LIN_FACTOR
        inds.append((trended / TARGET_LOSS_RATIO - 1.0) * 100.0)
    weight_sum = sum(c["weight_pct"] for c in cells)
    if weight_sum > 100:
        scale = 100.0 / weight_sum
        weights = [c["weight_pct"] * scale for c in cells]
    else:
        weights = [float(c["weight_pct"]) for c in cells]
    total = sum(w * i for w, i in zip(weights, inds)) / 100.0
    return round_half_up_4dp(total)


def round_half_up_4dp(x):
    scaled = x * 10000.0
    flo = scaled // 1  # floor
    frac = scaled - flo
    if frac >= 0.5:
        flo += 1.0
    return flo / 10000.0


def round_half_up_cents(x):
    flo = x // 1
    if x - flo >= 0.5:
        flo += 1
    return int(flo)


def department_for_state(state_code):
    for d in db["departments"].values():
        if d["state_code"] == state_code:
            return d
    return None


def variant_window_conflict(variant):
    a_from = parse_iso(variant["effective_from"])
    a_to = parse_iso(variant["effective_to"]) if variant["effective_to"] else None
    for sib in db["variants"].values():
        if sib["id"] == variant["id"]:
            continue
        if sib["form_id"] != variant["form_id"]:
            continue
        if sib["state_code"] != variant["state_code"]:
            continue
        if sib["review_status"] != "CLEARED":
            continue
        if sib["publication_status"] == "RETIRED":
            continue
        b_from = parse_iso(sib["effective_from"])
        b_to = parse_iso(sib["effective_to"]) if sib["effective_to"] else None
        if a_from < (b_to if b_to else datetime.max.replace(tzinfo=timezone.utc)) and \
           b_from < (a_to if a_to else datetime.max.replace(tzinfo=timezone.utc)):
            return True
    return False


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.post("/bureau/_clock/set_current_utc")
def set_clock():
    require_roles("BureauAdmin")
    data = body()
    to = req_str(data, "to_iso8601")
    try:
        parse_clock_value(to)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be ISO 8601")
    db["_clock"] = to
    return ok_object({"current_utc": to})


# ---------------------------------------------------------------------------
# MemberInsurer
# ---------------------------------------------------------------------------


@app.post("/bureau/insurers")
def create_insurer():
    require_roles("BureauAdmin")
    data = body()
    code = req_str(data, "insurer_code")
    name = req_str(data, "legal_name")
    rec = new_record()
    rec.update(
        insurer_code=code,
        legal_name=name,
        insurer_status="ACTIVE",
        quality_score_bps=10000,
    )
    db["insurers"][rec["id"]] = rec
    return ok_object(ser_insurer(rec), 201)


@app.get("/bureau/insurers/<iid>")
def get_insurer(iid):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser")
    rec = get_or_404("insurers", iid)
    return ok_object(ser_insurer(rec))


@app.get("/bureau/insurers")
def list_insurers():
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst")
    items = list(db["insurers"].values())
    status = request.args.get("insurer_status")
    if status is not None:
        items = [r for r in items if r["insurer_status"] == status]
    items = sort_by_created(items)
    return ok_array([ser_insurer(r) for r in items], paginate=True)


@app.post("/bureau/insurers/<iid>/suspend")
def suspend_insurer(iid):
    require_roles("BureauAdmin")
    rec = get_or_404("insurers", iid)
    if rec["insurer_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "insurer not ACTIVE")
    rec["insurer_status"] = "SUSPENDED"
    touch(rec)
    return ok_object(ser_insurer(rec))


@app.post("/bureau/insurers/<iid>/reinstate")
def reinstate_insurer(iid):
    require_roles("BureauAdmin")
    rec = get_or_404("insurers", iid)
    if rec["insurer_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "insurer not SUSPENDED")
    rec["insurer_status"] = "ACTIVE"
    touch(rec)
    return ok_object(ser_insurer(rec))


@app.post("/bureau/insurers/<iid>/withdraw-membership")
def withdraw_insurer(iid):
    require_roles("BureauAdmin")
    rec = get_or_404("insurers", iid)
    if rec["insurer_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "insurer not in a withdrawable state")
    for ag in db["agreements"].values():
        if ag["insurer_id"] == iid:
            evaluate_lapse(ag)
            if ag["agreement_status"] == "ACTIVE":
                raise ApiError(
                    "ERR_INVALID_STATE", 409, "insurer has ACTIVE license agreements"
                )
    for ad in db["adoptions"].values():
        if ad["insurer_id"] == iid and ad["adoption_status"] in ("PENDING", "AUTHORIZED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "insurer has PENDING or AUTHORIZED adoptions"
            )
    rec["insurer_status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(ser_insurer(rec))


@app.get("/bureau/insurers/<iid>/agreements")
def list_insurer_agreements(iid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    get_or_404("insurers", iid)
    items = [a for a in db["agreements"].values() if a["insurer_id"] == iid]
    for a in items:
        evaluate_lapse(a)
    items = sort_by_created(items)
    return ok_array([ser_agreement(a) for a in items], paginate=True)


# ---------------------------------------------------------------------------
# StatisticalPlan
# ---------------------------------------------------------------------------


@app.post("/bureau/statistical-plans")
def create_statistical_plan():
    require_roles("BureauAdmin")
    data = body()
    code = req_str(data, "plan_code")
    lob = req_str(data, "line_of_business")
    min_prem = req_int(data, "min_premium_cents")
    max_age = req_int(data, "max_record_age_months")
    rec = new_record()
    rec.update(
        plan_code=code,
        line_of_business=lob,
        min_premium_cents=min_prem,
        max_record_age_months=max_age,
        plan_status="DRAFT",
    )
    db["statistical_plans"][rec["id"]] = rec
    return ok_object(ser_plan(rec), 201)


@app.get("/bureau/statistical-plans/<pid>")
def get_statistical_plan(pid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("statistical_plans", pid)
    return ok_object(ser_plan(rec))


@app.post("/bureau/statistical-plans/<pid>/activate")
def activate_statistical_plan(pid):
    require_roles("BureauAdmin")
    rec = get_or_404("statistical_plans", pid)
    if rec["plan_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not DRAFT")
    rec["plan_status"] = "ACTIVE"
    touch(rec)
    return ok_object(ser_plan(rec))


# ---------------------------------------------------------------------------
# StatisticalSubmission / SubmissionEditFinding
# ---------------------------------------------------------------------------


@app.post("/bureau/submissions")
def create_submission():
    c = require_roles("InsurerUser")
    data = body()
    insurer_id = data.get("insurer_id")
    if insurer_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: insurer_id")
    insurer = get_or_404("insurers", insurer_id)
    plan_id = data.get("plan_id")
    if plan_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: plan_id")
    get_or_404("statistical_plans", plan_id)
    if insurer["insurer_status"] == "SUSPENDED":
        raise ApiError("ERR_INSURER_SUSPENDED", 409, "insurer is SUSPENDED")
    if insurer["insurer_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "insurer not ACTIVE")
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    record_count = req_int(data, "record_count")
    written_premium = req_int(data, "written_premium_cents")
    if record_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "record_count must be >= 1")
    if written_premium < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "written_premium_cents must be >= 0")
    rec = new_record()
    rec.update(
        insurer_id=insurer_id,
        plan_id=plan_id,
        period_start=period_start,
        period_end=period_end,
        record_count=record_count,
        written_premium_cents=written_premium,
        submission_status="RECEIVED",
        accepted_record_count=0,
        error_finding_count=0,
        warning_finding_count=0,
    )
    db["submissions"][rec["id"]] = rec
    return ok_object(ser_submission(rec), 201)


@app.get("/bureau/submissions/<sid>")
def get_submission(sid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("submissions", sid)
    return ok_object(ser_submission(rec))


@app.get("/bureau/submissions")
def list_submissions():
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    items = list(db["submissions"].values())
    f = request.args.get("insurer_id")
    if f is not None:
        items = [r for r in items if r["insurer_id"] == f]
    f = request.args.get("plan_id")
    if f is not None:
        items = [r for r in items if r["plan_id"] == f]
    f = request.args.get("submission_status")
    if f is not None:
        items = [r for r in items if r["submission_status"] == f]
    items = sort_by_created(items)
    return ok_array([ser_submission(r) for r in items], paginate=True)


@app.post("/bureau/submissions/<sid>/begin-edit")
def begin_edit_submission(sid):
    require_roles("BureauAdmin")
    rec = get_or_404("submissions", sid)
    if rec["submission_status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "submission not RECEIVED")
    rec["submission_status"] = "EDITING"
    touch(rec)
    return ok_object(ser_submission(rec))


@app.post("/bureau/submissions/<sid>/findings")
def create_finding(sid):
    require_roles("BureauAdmin")
    rec = get_or_404("submissions", sid)
    if rec["submission_status"] != "EDITING":
        raise ApiError("ERR_INVALID_STATE", 409, "submission not EDITING")
    data = body()
    edit_code = req_str(data, "edit_code")
    severity = req_enum(data, "severity", ("ERROR", "WARNING"))
    affected = req_int(data, "affected_records")
    if affected < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "affected_records must be >= 1")
    f = new_record(with_version=False)
    f.update(
        submission_id=sid,
        edit_code=edit_code,
        severity=severity,
        affected_records=affected,
    )
    db["findings"][f["id"]] = f
    return ok_object(ser_finding(f), 201)


@app.get("/bureau/submissions/<sid>/findings")
def list_findings(sid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    get_or_404("submissions", sid)
    items = [f for f in db["findings"].values() if f["submission_id"] == sid]
    items = sort_by_created(items)
    return ok_array([ser_finding(f) for f in items], paginate=True)


@app.post("/bureau/submissions/<sid>/dispose")
def dispose_submission(sid):
    require_roles("BureauAdmin")
    rec = get_or_404("submissions", sid)
    data = body()
    fast_reject = data.get("fast_reject") is True
    status = rec["submission_status"]
    if status == "EDITING":
        findings = [f for f in db["findings"].values() if f["submission_id"] == sid]
        errors = sum(1 for f in findings if f["severity"] == "ERROR")
        warnings = sum(1 for f in findings if f["severity"] == "WARNING")
        rec["error_finding_count"] = errors
        rec["warning_finding_count"] = warnings
        rec["accepted_record_count"] = rec["record_count"] - errors
        if errors > 0:
            rec["submission_status"] = "REJECTED"
        elif warnings > 0:
            rec["submission_status"] = "ACCEPTED_WITH_WARNINGS"
        else:
            rec["submission_status"] = "ACCEPTED"
    elif status == "RECEIVED" and fast_reject:
        rec["submission_status"] = "REJECTED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "submission not in a disposable state")
    touch(rec)
    insurer = db["insurers"].get(rec["insurer_id"])
    if insurer is not None:
        insurer["quality_score_bps"] = compute_quality_score(insurer["id"])
        touch(insurer)
    return ok_object(ser_submission(rec))


# ---------------------------------------------------------------------------
# StateDepartment
# ---------------------------------------------------------------------------


@app.post("/bureau/departments")
def create_department():
    require_roles("BureauAdmin")
    data = body()
    state_code = req_str(data, "state_code")
    name = req_str(data, "department_name")
    window = req_int(data, "objection_window_days")
    max_dev = req_int(data, "max_lcm_deviation_pct")
    if window <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "objection_window_days must be > 0")
    if max_dev < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_lcm_deviation_pct must be >= 0")
    rec = new_record()
    rec.update(
        state_code=state_code,
        department_name=name,
        objection_window_days=window,
        max_lcm_deviation_pct=max_dev,
    )
    db["departments"][rec["id"]] = rec
    return ok_object(ser_department(rec), 201)


@app.get("/bureau/departments/<did>")
def get_department(did):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser")
    rec = get_or_404("departments", did)
    return ok_object(ser_department(rec))


@app.get("/bureau/departments/<did>/objections")
def list_department_objections(did):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst")
    get_or_404("departments", did)
    items = [o for o in db["objections"].values() if o["department_id"] == did]
    items = sort_by_created(items)
    return ok_array([ser_objection(o) for o in items], paginate=True)


# ---------------------------------------------------------------------------
# LossCostFiling / LossCostCell / RegulatoryObjection
# ---------------------------------------------------------------------------


@app.post("/bureau/filings")
def create_filing():
    require_roles("BureauAdmin")
    data = body()
    filing_code = req_str(data, "filing_code")
    state_code = req_str(data, "state_code")
    lob = req_str(data, "line_of_business")
    trend = req_enum(
        data, "trend_selection", ("EXPONENTIAL_LEAST_SQUARES", "LINEAR_LEAST_SQUARES")
    )
    review_notes = data.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "review_notes must be a string")
    effective_date = req_dt(data, "effective_date", nullable=True)
    supersedes_id = data.get("supersedes_filing_id")
    filing_version = 1
    if supersedes_id is not None:
        superseded = get_or_404("filings", supersedes_id)
        expected = data.get("expected_superseded_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "expected_superseded_version must be an integer"
                )
            if expected != superseded["version"]:
                raise ApiError(
                    "ERR_STALE_VERSION", 412, "superseded filing version is stale"
                )
        if superseded["filing_status"] != "OBJECTED":
            raise ApiError(
                "ERR_SUPERSEDE_CHAIN_BROKEN", 422, "superseded filing is not OBJECTED"
            )
        # The resubmission continues the superseded filing's version chain
        # (§3.3): the new node carries the chain root's filing_code.
        filing_code = superseded["filing_code"]
        filing_version = superseded["filing_version"] + 1
        superseded["filing_status"] = "WITHDRAWN"
        touch(superseded)
    rec = new_record()
    rec.update(
        filing_code=filing_code,
        state_code=state_code,
        line_of_business=lob,
        filing_version=filing_version,
        supersedes_filing_id=supersedes_id,
        trend_selection=trend,
        review_notes=review_notes,
        filing_status="DRAFT",
        last_submitted_by_admin_id=None,
        filed_at=None,
        indicated_change_pct=None,
        effective_date=effective_date,
    )
    db["filings"][rec["id"]] = rec
    return ok_object(ser_filing(rec), 201)


@app.get("/bureau/filings/<fid>")
def get_filing(fid):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser")
    rec = get_or_404("filings", fid)
    return ok_object(ser_filing(rec))


@app.get("/bureau/filings")
def list_filings():
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser")
    items = list(db["filings"].values())
    f = request.args.get("state_code")
    if f is not None:
        items = [r for r in items if r["state_code"] == f]
    f = request.args.get("line_of_business")
    if f is not None:
        items = [r for r in items if r["line_of_business"] == f]
    f = request.args.get("filing_status")
    if f is not None:
        items = [r for r in items if r["filing_status"] == f]
    f = request.args.get("supersedes_filing_id")
    if f is not None:
        items = [r for r in items if r["supersedes_filing_id"] == f]
    items = sort_by_created(items)
    return ok_array([ser_filing(r) for r in items], paginate=True)


@app.post("/bureau/filings/<fid>/cells")
def create_cell(fid):
    require_roles("BureauAdmin")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not DRAFT")
    data = body()
    class_code = req_str(data, "class_code")
    earned = req_int(data, "earned_premium_cents")
    incurred = req_int(data, "incurred_loss_cents")
    weight = req_int(data, "weight_pct")
    current = req_int(data, "current_loss_cost_cents")
    if earned <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "earned_premium_cents must be > 0")
    if incurred < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "incurred_loss_cents must be >= 0")
    if weight < 1 or weight > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight_pct must be in 1..100")
    if current <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "current_loss_cost_cents must be > 0")
    rec = new_record(with_version=False)
    rec.update(
        filing_id=fid,
        class_code=class_code,
        earned_premium_cents=earned,
        incurred_loss_cents=incurred,
        weight_pct=weight,
        current_loss_cost_cents=current,
    )
    db["cells"][rec["id"]] = rec
    return ok_object(ser_cell(rec), 201)


@app.get("/bureau/filings/<fid>/cells")
def list_cells(fid):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst", "InsurerUser")
    get_or_404("filings", fid)
    items = [c for c in db["cells"].values() if c["filing_id"] == fid]
    items = sort_by_created(items)
    return ok_array([ser_cell(c) for c in items], paginate=True)


@app.post("/bureau/filings/<fid>/submit-review")
def submit_filing_review(fid):
    c = require_roles("BureauAdmin")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not DRAFT")
    cells = [x for x in db["cells"].values() if x["filing_id"] == fid]
    if not cells:
        raise ApiError("ERR_INVALID_STATE", 409, "filing has no loss cost cells")
    filing["filing_status"] = "IN_ACTUARIAL_REVIEW"
    filing["last_submitted_by_admin_id"] = c["id"]
    touch(filing)
    return ok_object(ser_filing(filing))


@app.post("/bureau/filings/<fid>/complete-review")
def complete_filing_review(fid):
    c = require_roles("BureauActuary")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "IN_ACTUARIAL_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not IN_ACTUARIAL_REVIEW")
    if filing["last_submitted_by_admin_id"] == c["id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "completing actuary matches the submitting admin identity",
        )
    filing["indicated_change_pct"] = compute_indicated_change(filing)
    filing["filing_status"] = "REVIEWED"
    touch(filing)
    return ok_object(ser_filing(filing))


@app.post("/bureau/filings/<fid>/file")
def file_filing(fid):
    require_roles("BureauAdmin")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "REVIEWED":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not REVIEWED")
    if filing["effective_date"] is None:
        raise ApiError("ERR_INVALID_STATE", 409, "effective_date is not set")
    if parse_iso(filing["effective_date"]) <= logical_clock():
        raise ApiError(
            "ERR_INVALID_STATE", 409, "effective_date must be strictly after the logical clock"
        )
    if department_for_state(filing["state_code"]) is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "no StateDepartment exists for the filing's state_code"
        )
    filing["filing_status"] = "FILED"
    filing["filed_at"] = iso_z(logical_clock())
    touch(filing)
    return ok_object(ser_filing(filing))


@app.post("/bureau/filings/<fid>/objections")
def create_objection(fid):
    c = require_roles("RegulatorAnalyst")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not FILED")
    data = body()
    department_id = data.get("department_id")
    if department_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: department_id")
    dept = get_or_404("departments", department_id)
    if dept["state_code"] != filing["state_code"]:
        raise ApiError(
            "ERR_JURISDICTION_MISMATCH",
            422,
            "department state_code differs from the filing's state_code",
        )
    deadline = parse_iso(filing["filed_at"]) + timedelta(days=dept["objection_window_days"])
    if logical_clock() > deadline:
        raise ApiError("ERR_OBJECTION_WINDOW_CLOSED", 422, "objection window has closed")
    code = req_str(data, "objection_code")
    text = req_str(data, "objection_text")
    rec = new_record(with_version=False)
    rec.update(
        filing_id=fid,
        department_id=department_id,
        objection_code=code,
        objection_text=text,
        raised_at=iso_z(logical_clock()),
    )
    db["objections"][rec["id"]] = rec
    filing["filing_status"] = "OBJECTED"
    touch(filing)
    return ok_object(ser_objection(rec), 201)


@app.get("/bureau/filings/<fid>/objections")
def list_filing_objections(fid):
    require_roles("BureauAdmin", "BureauActuary", "RegulatorAnalyst")
    get_or_404("filings", fid)
    items = [o for o in db["objections"].values() if o["filing_id"] == fid]
    items = sort_by_created(items)
    return ok_array([ser_objection(o) for o in items], paginate=True)


@app.post("/bureau/filings/<fid>/finalize")
def finalize_filing(fid):
    require_roles("BureauAdmin")
    filing = get_or_404("filings", fid)
    if filing["filing_status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "filing not FILED")
    dept = department_for_state(filing["state_code"])
    if dept is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "no StateDepartment exists for the filing's state_code"
        )
    deadline = parse_iso(filing["filed_at"]) + timedelta(days=dept["objection_window_days"])
    if logical_clock() <= deadline:
        raise ApiError("ERR_INVALID_STATE", 409, "objection window has not lapsed")
    objections = [o for o in db["objections"].values() if o["filing_id"] == fid]
    if objections:
        raise ApiError("ERR_INVALID_STATE", 409, "filing has objection rows")
    filing["filing_status"] = "EFFECTIVE"
    touch(filing)
    return ok_object(ser_filing(filing))


@app.post("/bureau/filings/<fid>/withdraw")
def withdraw_filing(fid):
    require_roles("BureauAdmin")
    filing = get_or_404("filings", fid)
    status = filing["filing_status"]
    if status in ("DRAFT", "IN_ACTUARIAL_REVIEW", "REVIEWED"):
        pass
    elif status == "FILED":
        objections = [o for o in db["objections"].values() if o["filing_id"] == fid]
        if objections:
            raise ApiError("ERR_INVALID_STATE", 409, "FILED filing has objection rows")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "filing not in a withdrawable state")
    filing["filing_status"] = "WITHDRAWN"
    touch(filing)
    return ok_object(ser_filing(filing))


# ---------------------------------------------------------------------------
# LossCostMultiplierAdoption
# ---------------------------------------------------------------------------


@app.post("/bureau/adoptions")
def create_adoption():
    require_roles("InsurerUser")
    data = body()
    insurer_id = data.get("insurer_id")
    if insurer_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: insurer_id")
    get_or_404("insurers", insurer_id)
    filing_id = data.get("filing_id")
    if filing_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: filing_id")
    filing = get_or_404("filings", filing_id)
    if filing["filing_status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "filing is not EFFECTIVE")
    multiplier = req_int(data, "multiplier_pct")
    expected = req_int(data, "expected_filing_version")
    if multiplier < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "multiplier_pct must be >= 1")
    if expected != filing["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "filing version is stale")
    if data.get("immediate_authorization") is True:
        dept = department_for_state(filing["state_code"])
        if dept is not None and multiplier - 100 > dept["max_lcm_deviation_pct"]:
            raise ApiError(
                "ERR_LCM_BAND_EXCEEDED",
                422,
                "multiplier deviation exceeds the department's max_lcm_deviation_pct",
            )
    rec = new_record()
    rec.update(
        insurer_id=insurer_id,
        filing_id=filing_id,
        multiplier_pct=multiplier,
        adoption_status="PENDING",
        authorized_premium_cents=None,
        authorized_at=None,
        withdraw_reason=None,
    )
    db["adoptions"][rec["id"]] = rec
    return ok_object(ser_adoption(rec), 201)


@app.get("/bureau/adoptions/<aid>")
def get_adoption(aid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("adoptions", aid)
    return ok_object(ser_adoption(rec))


@app.get("/bureau/adoptions")
def list_adoptions():
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    items = list(db["adoptions"].values())
    f = request.args.get("insurer_id")
    if f is not None:
        items = [r for r in items if r["insurer_id"] == f]
    f = request.args.get("filing_id")
    if f is not None:
        items = [r for r in items if r["filing_id"] == f]
    f = request.args.get("adoption_status")
    if f is not None:
        items = [r for r in items if r["adoption_status"] == f]
    items = sort_by_created(items)
    return ok_array([ser_adoption(r) for r in items], paginate=True)


@app.post("/bureau/adoptions/<aid>/authorize")
def authorize_adoption(aid):
    require_roles("BureauAdmin")
    rec = get_or_404("adoptions", aid)
    if rec["adoption_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "adoption not PENDING")
    insurer = db["insurers"].get(rec["insurer_id"])
    if insurer is None or insurer["insurer_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "insurer is not ACTIVE")
    if covering_active_license(rec["insurer_id"]) is None:
        raise ApiError(
            "ERR_LICENSE_NOT_COVERING",
            422,
            "no ACTIVE license agreement covers the logical clock date",
        )
    filing = db["filings"][rec["filing_id"]]
    dept = department_for_state(filing["state_code"])
    max_dev = dept["max_lcm_deviation_pct"] if dept is not None else 0
    if rec["multiplier_pct"] - 100 > max_dev:
        rec["adoption_status"] = "REJECTED_BAND"
        touch(rec)
        return ok_object(ser_adoption(rec))
    total = 0
    for cell in db["cells"].values():
        if cell["filing_id"] != rec["filing_id"]:
            continue
        total += round_half_up_cents(
            cell["current_loss_cost_cents"] * rec["multiplier_pct"] / 100.0
        )
    rec["adoption_status"] = "AUTHORIZED"
    rec["authorized_premium_cents"] = total
    rec["authorized_at"] = rec["updated_at"]  # will be refreshed by touch below
    touch(rec)
    rec["authorized_at"] = rec["updated_at"]
    return ok_object(ser_adoption(rec))


@app.post("/bureau/adoptions/<aid>/withdraw")
def withdraw_adoption(aid):
    c = require_roles("InsurerUser")
    rec = get_or_404("adoptions", aid)
    if rec["adoption_status"] not in ("PENDING", "AUTHORIZED"):
        raise ApiError("ERR_INVALID_STATE", 409, "adoption not in a withdrawable state")
    if c["id"] != rec["insurer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "adoption belongs to another insurer")
    rec["adoption_status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(ser_adoption(rec))


# ---------------------------------------------------------------------------
# PolicyForm / FormVariant
# ---------------------------------------------------------------------------


@app.post("/bureau/forms")
def create_form():
    require_roles("BureauAdmin")
    data = body()
    number = req_str(data, "form_number")
    title = req_str(data, "form_title")
    kind = req_enum(data, "form_kind", ("POLICY_FORM", "ENDORSEMENT"))
    rec = new_record()
    rec.update(
        form_number=number,
        form_title=title,
        form_kind=kind,
        form_status="DRAFTING",
    )
    db["forms"][rec["id"]] = rec
    return ok_object(ser_form(rec), 201)


@app.get("/bureau/forms/<fid>")
def get_form(fid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("forms", fid)
    return ok_object(ser_form(rec))


@app.post("/bureau/forms/<fid>/variants")
def create_variant(fid):
    require_roles("BureauAdmin")
    get_or_404("forms", fid)
    data = body()
    state_code = req_str(data, "state_code")
    text_ref = req_str(data, "variant_text_ref")
    eff_from = req_dt(data, "effective_from")
    eff_to = req_dt(data, "effective_to", nullable=True)
    rec = new_record()
    rec.update(
        form_id=fid,
        state_code=state_code,
        variant_text_ref=text_ref,
        review_status="PENDING",
        publication_status="UNPUBLISHED",
        effective_from=eff_from,
        effective_to=eff_to,
    )
    db["variants"][rec["id"]] = rec
    return ok_object(ser_variant(rec), 201)


@app.get("/bureau/forms/<fid>/variants")
def list_form_variants(fid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    get_or_404("forms", fid)
    refresh_scheduled_variants()
    items = [v for v in db["variants"].values() if v["form_id"] == fid]
    f = request.args.get("state_code")
    if f is not None:
        items = [v for v in items if v["state_code"] == f]
    items = sort_by_created(items)
    return ok_array([ser_variant(v) for v in items], paginate=True)


@app.get("/bureau/variants/<vid>")
def get_variant(vid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    refresh_scheduled_variants()
    rec = get_or_404("variants", vid)
    return ok_object(ser_variant(rec))


@app.post("/bureau/variants/<vid>/clear")
def clear_variant(vid):
    require_roles("BureauActuary")
    rec = get_or_404("variants", vid)
    if rec["review_status"] != "PENDING" or rec["publication_status"] != "UNPUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "variant not clearable")
    if variant_window_conflict(rec):
        raise ApiError(
            "ERR_VARIANT_WINDOW_OVERLAP",
            422,
            "usability window overlaps a sibling variant",
        )
    rec["review_status"] = "CLEARED"
    touch(rec)
    return ok_object(ser_variant(rec))


@app.post("/bureau/variants/<vid>/block")
def block_variant(vid):
    require_roles("BureauActuary")
    rec = get_or_404("variants", vid)
    if rec["review_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "variant not PENDING")
    rec["review_status"] = "BLOCKED"
    touch(rec)
    return ok_object(ser_variant(rec))


@app.post("/bureau/variants/<vid>/unblock")
def unblock_variant(vid):
    require_roles("BureauActuary")
    rec = get_or_404("variants", vid)
    if rec["review_status"] != "BLOCKED" or rec["publication_status"] != "UNPUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "variant not unblockable")
    rec["review_status"] = "PENDING"
    touch(rec)
    return ok_object(ser_variant(rec))


@app.post("/bureau/variants/<vid>/retire")
def retire_variant(vid):
    require_roles("BureauAdmin")
    refresh_scheduled_variants()
    rec = get_or_404("variants", vid)
    if rec["publication_status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "variant not LIVE")
    rec["publication_status"] = "RETIRED"
    touch(rec)
    return ok_object(ser_variant(rec))


@app.post("/bureau/forms/<fid>/submit-review")
def submit_form_review(fid):
    require_roles("BureauAdmin")
    form = get_or_404("forms", fid)
    if form["form_status"] != "DRAFTING":
        raise ApiError("ERR_INVALID_STATE", 409, "form not DRAFTING")
    cw = [v for v in db["variants"].values() if v["form_id"] == fid and v["state_code"] == "CW"]
    if not cw:
        raise ApiError("ERR_INVALID_STATE", 409, "form has no CW variant")
    form["form_status"] = "IN_REVIEW"
    touch(form)
    return ok_object(ser_form(form))


@app.post("/bureau/forms/<fid>/approve")
def approve_form(fid):
    require_roles("BureauActuary")
    form = get_or_404("forms", fid)
    if form["form_status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "form not IN_REVIEW")
    variants = [v for v in db["variants"].values() if v["form_id"] == fid]
    if not variants or any(v["review_status"] != "CLEARED" for v in variants):
        raise ApiError("ERR_INVALID_STATE", 409, "not every variant is CLEARED")
    form["form_status"] = "APPROVED"
    touch(form)
    return ok_object(ser_form(form))


@app.post("/bureau/forms/<fid>/return-to-drafting")
def return_form_to_drafting(fid):
    require_roles("BureauActuary")
    form = get_or_404("forms", fid)
    if form["form_status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "form not IN_REVIEW")
    for v in db["variants"].values():
        if v["form_id"] == fid and v["review_status"] == "CLEARED":
            v["review_status"] = "PENDING"
            touch(v)
    form["form_status"] = "DRAFTING"
    touch(form)
    return ok_object(ser_form(form))


@app.post("/bureau/forms/<fid>/withdraw")
def withdraw_form(fid):
    require_roles("BureauAdmin")
    form = get_or_404("forms", fid)
    if form["form_status"] not in ("DRAFTING", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "form not in a withdrawable state")
    form["form_status"] = "WITHDRAWN"
    touch(form)
    return ok_object(ser_form(form))


# ---------------------------------------------------------------------------
# Circular
# ---------------------------------------------------------------------------


@app.post("/bureau/circulars")
def create_circular():
    require_roles("BureauAdmin")
    data = body()
    number = req_str(data, "circular_number")
    subject = req_str(data, "subject")
    impl_date = req_dt(data, "implementation_date")
    form_ids = data.get("form_ids")
    if form_ids is None:
        form_ids = []
    if not isinstance(form_ids, list) or any(not isinstance(x, str) for x in form_ids):
        raise ApiError("ERR_INVALID_REQUEST", 400, "form_ids must be a list of strings")
    supersedes_id = data.get("supersedes_circular_id")
    if supersedes_id is not None:
        pred = get_or_404("circulars", supersedes_id)
        if pred["circular_status"] != "PUBLISHED":
            raise ApiError(
                "ERR_SUPERSEDE_CHAIN_BROKEN", 422, "superseded circular is not PUBLISHED"
            )
    rec = new_record()
    rec.update(
        circular_number=number,
        subject=subject,
        implementation_date=impl_date,
        form_ids=list(form_ids),
        supersedes_circular_id=supersedes_id,
        circular_status="DRAFT",
    )
    db["circulars"][rec["id"]] = rec
    return ok_object(ser_circular(rec), 201)


@app.get("/bureau/circulars/<cid>")
def get_circular(cid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("circulars", cid)
    return ok_object(ser_circular(rec))


@app.get("/bureau/circulars")
def list_circulars():
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    items = list(db["circulars"].values())
    f = request.args.get("circular_status")
    if f is not None:
        items = [r for r in items if r["circular_status"] == f]
    f = request.args.get("supersedes_circular_id")
    if f is not None:
        items = [r for r in items if r["supersedes_circular_id"] == f]
    items = sort_by_created(items)
    return ok_array([ser_circular(r) for r in items], paginate=True)


@app.post("/bureau/circulars/<cid>/publish")
def publish_circular(cid):
    require_roles("BureauAdmin")
    rec = get_or_404("circulars", cid)
    if rec["circular_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "circular not DRAFT")
    if parse_iso(rec["implementation_date"]) <= logical_clock():
        raise ApiError(
            "ERR_INVALID_STATE", 409, "implementation_date must be strictly after the logical clock"
        )
    rec["circular_status"] = "PUBLISHED"
    touch(rec)
    for form_id in rec.get("form_ids", []):
        form = db["forms"].get(form_id)
        if form is not None and form["form_status"] == "APPROVED":
            form["form_status"] = "PUBLISHED"
            touch(form)
            for v in db["variants"].values():
                if (
                    v["form_id"] == form_id
                    and v["review_status"] == "CLEARED"
                    and v["publication_status"] == "UNPUBLISHED"
                ):
                    v["publication_status"] = "SCHEDULED"
                    touch(v)
    if rec["supersedes_circular_id"] is not None:
        pred = db["circulars"].get(rec["supersedes_circular_id"])
        if pred is not None and pred["circular_status"] == "PUBLISHED":
            pred["circular_status"] = "SUPERSEDED"
            touch(pred)
    return ok_object(ser_circular(rec))


# ---------------------------------------------------------------------------
# LicenseAgreement
# ---------------------------------------------------------------------------


@app.post("/bureau/agreements")
def create_agreement():
    require_roles("BureauAdmin")
    data = body()
    insurer_id = data.get("insurer_id")
    if insurer_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: insurer_id")
    get_or_404("insurers", insurer_id)
    coverage_start = req_dt(data, "coverage_start")
    coverage_end = req_dt(data, "coverage_end")
    rate = req_int(data, "royalty_rate_bps")
    if rate < 0 or rate > 5000:
        raise ApiError("ERR_INVALID_REQUEST", 400, "royalty_rate_bps must be in 0..5000")
    rec = new_record()
    rec.update(
        insurer_id=insurer_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        royalty_rate_bps=rate,
        agreement_status="ACTIVE",
    )
    db["agreements"][rec["id"]] = rec
    return ok_object(ser_agreement(rec), 201)


@app.get("/bureau/agreements/<aid>")
def get_agreement(aid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("agreements", aid)
    evaluate_lapse(rec)
    return ok_object(ser_agreement(rec))


@app.get("/bureau/agreements/<aid>/royalty")
def get_agreement_royalty(aid):
    require_roles("BureauAdmin", "BureauActuary")
    rec = get_or_404("agreements", aid)
    evaluate_lapse(rec)
    total = 0
    for ad in db["adoptions"].values():
        if ad["insurer_id"] != rec["insurer_id"]:
            continue
        if ad["adoption_status"] != "AUTHORIZED":
            continue
        filing = db["filings"].get(ad["filing_id"])
        if filing is None or filing["filing_status"] != "EFFECTIVE":
            continue
        eff = parse_iso(filing["updated_at"]).date()
        start = parse_iso(rec["coverage_start"]).date()
        end = parse_iso(rec["coverage_end"]).date()
        if start <= eff <= end:
            total += ad["authorized_premium_cents"] or 0
    royalty = round_half_up_cents(total * rec["royalty_rate_bps"] / 10000.0)
    return ok_object({"royalty_due_cents": royalty})


@app.post("/bureau/agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_roles("BureauAdmin")
    rec = get_or_404("agreements", aid)
    evaluate_lapse(rec)
    if rec["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "agreement not ACTIVE")
    for ad in db["adoptions"].values():
        if ad["insurer_id"] == rec["insurer_id"] and ad["adoption_status"] == "AUTHORIZED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "insurer has AUTHORIZED adoptions"
            )
    rec["agreement_status"] = "TERMINATED"
    touch(rec)
    withdraw_pending_adoptions(rec["insurer_id"], "LICENCE_TERMINATED")
    return ok_object(ser_agreement(rec))


# ---------------------------------------------------------------------------
# ClassPlan / ClassPlanRevision
# ---------------------------------------------------------------------------


@app.post("/bureau/class-plans")
def create_class_plan():
    require_roles("BureauAdmin")
    data = body()
    code = req_str(data, "class_plan_code")
    lob = req_str(data, "line_of_business")
    rec = new_record()
    rec.update(
        class_plan_code=code,
        line_of_business=lob,
        current_revision_id=None,
        plan_status="OPEN",
    )
    db["class_plans"][rec["id"]] = rec
    return ok_object(ser_class_plan(rec), 201)


@app.get("/bureau/class-plans/<pid>")
def get_class_plan(pid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("class_plans", pid)
    return ok_object(ser_class_plan(rec))


@app.get("/bureau/class-plans")
def list_class_plans():
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    items = list(db["class_plans"].values())
    f = request.args.get("current_revision_id")
    if f is not None:
        items = [r for r in items if r["current_revision_id"] == f]
    f = request.args.get("line_of_business")
    if f is not None:
        items = [r for r in items if r["line_of_business"] == f]
    items = sort_by_created(items)
    return ok_array([ser_class_plan(r) for r in items], paginate=True)


@app.post("/bureau/class-plans/<pid>/revisions")
def create_revision(pid):
    require_roles("BureauAdmin")
    get_or_404("class_plans", pid)
    data = body()
    class_count = req_int(data, "class_count")
    activates_at = req_dt(data, "activates_at")
    if class_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "class_count must be >= 1")
    existing = [r for r in db["class_plan_revisions"].values() if r["class_plan_id"] == pid]
    number = max((r["revision_number"] for r in existing), default=0) + 1
    rec = new_record()
    rec.update(
        class_plan_id=pid,
        revision_number=number,
        class_count=class_count,
        revision_status="STAGED",
        activates_at=activates_at,
        activated_at=None,
    )
    db["class_plan_revisions"][rec["id"]] = rec
    return ok_object(ser_revision(rec), 201)


@app.get("/bureau/class-plans/<pid>/revisions")
def list_revisions(pid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    get_or_404("class_plans", pid)
    items = [r for r in db["class_plan_revisions"].values() if r["class_plan_id"] == pid]
    items = sort_by_created(items)
    return ok_array([ser_revision(r) for r in items], paginate=True)


@app.get("/bureau/class-plan-revisions/<rid>")
def get_revision(rid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    rec = get_or_404("class_plan_revisions", rid)
    return ok_object(ser_revision(rec))


@app.get("/bureau/class-plan-revisions/<rid>/in-force-for")
def revision_in_force_for(rid):
    require_roles("BureauAdmin", "BureauActuary", "InsurerUser")
    get_or_404("class_plan_revisions", rid)
    items = [p for p in db["class_plans"].values() if p["current_revision_id"] == rid]
    items = sort_by_created(items)
    return ok_array([ser_class_plan(p) for p in items], paginate=True)


@app.post("/bureau/class-plan-revisions/<rid>/activate")
def activate_revision(rid):
    require_roles("BureauAdmin")
    rec = get_or_404("class_plan_revisions", rid)
    if rec["revision_status"] != "STAGED":
        raise ApiError("ERR_INVALID_STATE", 409, "revision not STAGED")
    if logical_clock() < parse_iso(rec["activates_at"]):
        raise ApiError("ERR_INVALID_STATE", 409, "activates_at not yet reached")
    plan = db["class_plans"].get(rec["class_plan_id"])
    if plan is None or plan["plan_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "parent class plan is not OPEN")
    for other in db["class_plan_revisions"].values():
        if (
            other["class_plan_id"] == rec["class_plan_id"]
            and other["revision_status"] == "ACTIVATED"
        ):
            other["revision_status"] = "SUPERSEDED"
            touch(other)
    rec["revision_status"] = "ACTIVATED"
    touch(rec)
    rec["activated_at"] = rec["updated_at"]
    plan["current_revision_id"] = rec["id"]
    touch(plan)
    return ok_object(ser_revision(rec))


@app.post("/bureau/class-plans/<pid>/lock")
def lock_class_plan(pid):
    require_roles("BureauAdmin")
    plan = get_or_404("class_plans", pid)
    if plan["plan_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not OPEN")
    if plan["current_revision_id"] is None:
        raise ApiError("ERR_INVALID_STATE", 409, "plan has no current revision")
    staged = [
        r
        for r in db["class_plan_revisions"].values()
        if r["class_plan_id"] == pid and r["revision_status"] == "STAGED"
    ]
    if staged:
        raise ApiError("ERR_INVALID_STATE", 409, "plan has STAGED revisions")
    plan["plan_status"] = "LOCKED"
    touch(plan)
    return ok_object(ser_class_plan(plan))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
