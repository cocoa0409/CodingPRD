"""Dental Benefit Administration API — Flask entry point.

Mounts every route from PRD §4 under the /dental prefix, applies the
PRD §2.10 validation order, and runs the workflows in PRD §3.
"""

import os
from datetime import timedelta
from functools import wraps

from flask import Flask, request

from auth import require_role, current_identity
from db import store
from errors import (
    ApiError,
    ERR_UNAUTHORIZED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_SUBSCRIBER_NOT_FOUND,
    ERR_DEPENDENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_PREDETERMINATION_NOT_FOUND,
    ERR_FEE_SCHEDULE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PROVIDER_TERMINATED,
    ERR_PROVIDER_BUSY,
    ERR_SCHEDULE_OVERLAP,
    ERR_TIMELY_FILING,
    ERR_RETROACTIVE_PREDETERMINATION,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_COB_CONFIG_INVALID,
    ERR_NO_FEE_SCHEDULE,
    ERR_INVALID_PLAN_CONFIG,
    ERR_ANNUAL_MAX_EXCEEDED,
    ERR_INVALID_ATTACHMENT,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)
from response import (
    success_object,
    success_list,
    error_response,
    parse_iso,
    parse_pagination,
    format_iso,
)
from services import (
    create_record,
    mutate_record,
    resolve_active_schedule,
    require_entry,
    find_entry,
    recompute_predet_estimate,
    adjudicate_claim,
    maybe_expire,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handler — every ApiError surfaces in the standard envelope.
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    import traceback
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, "Unexpected server error: %s" % err, 500)


# ---------------------------------------------------------------------------
# Body parsing helpers
# ---------------------------------------------------------------------------

def body():
    if not request.is_json:
        return {}
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def require_fields(payload, *names):
    for name in names:
        if name not in payload or payload[name] is None:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name, 400)


def parse_dt_field(payload, name, required=True):
    raw = payload.get(name)
    if raw is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name, 400)
        return None
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be ISO 8601 UTC" % name, 400)
    return dt


def require_int(payload, name):
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % name, 400)
    return value


def require_bool(payload, name):
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name, 400)
    return value


def require_enum(payload, name, allowed):
    value = payload.get(name)
    if value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be one of %r" % (name, sorted(allowed)), 400)
    return value


# ---------------------------------------------------------------------------
# Public record renderers — strip internal *_dt helpers
# ---------------------------------------------------------------------------

def render_plan(p):
    return {
        "id": p["id"],
        "plan_code": p["plan_code"],
        "plan_year_start_month": p["plan_year_start_month"],
        "annual_maximum_cents": p["annual_maximum_cents"],
        "deductible_cents": p["deductible_cents"],
        "deductible_applies_preventive": p["deductible_applies_preventive"],
        "preventive_coinsurance_pct": p["preventive_coinsurance_pct"],
        "basic_coinsurance_pct": p["basic_coinsurance_pct"],
        "major_coinsurance_pct": p["major_coinsurance_pct"],
        "basic_waiting_months": p["basic_waiting_months"],
        "major_waiting_months": p["major_waiting_months"],
        "missing_tooth_clause_active": p["missing_tooth_clause_active"],
        "abp_enabled": p["abp_enabled"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def render_provider(p):
    return {
        "id": p["id"],
        "npi": p["npi"],
        "legal_name": p["legal_name"],
        "tier": p["tier"],
        "license_state": p["license_state"],
        "contracted_on": format_iso(p["contracted_on_dt"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def render_schedule(s):
    return {
        "id": s["id"],
        "tier": s["tier"],
        "effective_from": s.get("effective_from_raw") or format_iso(s["effective_from_dt"]),
        "effective_to": (s.get("effective_to_raw") or (format_iso(s["effective_to_dt"]) if s.get("effective_to_dt") else None)),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def render_entry(e):
    return {
        "id": e["id"],
        "fee_schedule_id": e["fee_schedule_id"],
        "cdt_code": e["cdt_code"],
        "allowed_cents": e["allowed_cents"],
        "category": e["category"],
        "requires_attachment": e["requires_attachment"],
        "abp_alternative_cdt": e["abp_alternative_cdt"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def render_subscriber(s):
    return {
        "id": s["id"],
        "plan_id": s["plan_id"],
        "member_id": s["member_id"],
        "full_name": s["full_name"],
        "date_of_birth": format_iso(s["date_of_birth_dt"]),
        "effective_date": format_iso(s["effective_date_dt"]),
        "cob_priority": s["cob_priority"],
        "other_plan_external_id": s["other_plan_external_id"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def render_dependent(d):
    return {
        "id": d["id"],
        "subscriber_id": d["subscriber_id"],
        "full_name": d["full_name"],
        "date_of_birth": format_iso(d["date_of_birth_dt"]),
        "relationship": d["relationship"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def render_rule(r):
    return {
        "id": r["id"],
        "plan_id": r["plan_id"],
        "cdt_code": r["cdt_code"],
        "rule_kind": r["rule_kind"],
        "window_months": r["window_months"],
        "max_occurrences": r["max_occurrences"],
        "age_years_min": r["age_years_min"],
        "age_years_max": r["age_years_max"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def render_predet(p):
    return {
        "id": p["id"],
        "subscriber_id": p["subscriber_id"],
        "dependent_id": p.get("dependent_id"),
        "provider_id": p["provider_id"],
        "cdt_code": p["cdt_code"],
        "submitted_amount_cents": p["submitted_amount_cents"],
        "planned_service_date": format_iso(p["planned_service_date_dt"]),
        "clinical_reviewer_id": p.get("clinical_reviewer_id") or "",
        "estimated_allowed_cents": p.get("estimated_allowed_cents", 0),
        "estimated_plan_pay_cents": p.get("estimated_plan_pay_cents", 0),
        "estimated_patient_pay_cents": p.get("estimated_patient_pay_cents", 0),
        "abp_applied": p.get("abp_applied", False),
        "version_pin_fee_schedule_id": p.get("version_pin_fee_schedule_id"),
        "expires_on": format_iso(p["expires_on_dt"]) if p.get("expires_on_dt") else None,
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def render_claim(c):
    return {
        "id": c["id"],
        "subscriber_id": c["subscriber_id"],
        "dependent_id": c.get("dependent_id"),
        "provider_id": c["provider_id"],
        "predetermination_id": c.get("predetermination_id"),
        "service_date": format_iso(c["service_date_dt"]),
        "received_date": format_iso(c["received_date_dt"]),
        "total_submitted_cents": c["total_submitted_cents"],
        "total_allowed_cents": c["total_allowed_cents"],
        "total_plan_pay_cents": c["total_plan_pay_cents"],
        "total_patient_pay_cents": c["total_patient_pay_cents"],
        "cob_other_plan_paid_cents": c.get("cob_other_plan_paid_cents", 0),
        "cob_secondary_payment_cents": c.get("cob_secondary_payment_cents", 0),
        "tooth_missing_prior_to_coverage": c.get("tooth_missing_prior_to_coverage") or {},
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def render_line(l):
    return {
        "id": l["id"],
        "claim_id": l["claim_id"],
        "line_number": l["line_number"],
        "cdt_code": l["cdt_code"],
        "tooth_number": l.get("tooth_number") or "",
        "submitted_amount_cents": l["submitted_amount_cents"],
        "category": l.get("category"),
        "allowed_cents": l.get("allowed_cents", 0),
        "abp_applied": l.get("abp_applied", False),
        "abp_patient_difference_cents": l.get("abp_patient_difference_cents", 0),
        "deductible_applied_cents": l.get("deductible_applied_cents", 0),
        "coinsurance_plan_cents": l.get("coinsurance_plan_cents", 0),
        "plan_pay_cents": l.get("plan_pay_cents", 0),
        "patient_pay_cents": l.get("patient_pay_cents", 0),
        "denial_code": l.get("denial_code"),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def render_attachment(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "claim_line_id": a["claim_line_id"],
        "attachment_kind": a["attachment_kind"],
        "blob_ref": a["blob_ref"],
        "transmitted_on": a["transmitted_on"],
        "created_at": a["created_at"],
    }


def render_accumulator(a):
    return {
        "id": a["id"],
        "subscriber_id": a["subscriber_id"],
        "dependent_id": a.get("dependent_id"),
        "plan_year_key": a["plan_year_key"],
        "deductible_met_cents": a["deductible_met_cents"],
        "annual_max_used_cents": a["annual_max_used_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def paginate(items, render_fn, args=None):
    args = args if args is not None else request.args
    limit, offset = parse_pagination(args)
    items_sorted = sorted(items, key=lambda r: r["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success_list([render_fn(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route("/dental/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlanAdmin")
    payload = body()
    require_fields(payload, "to_iso8601")
    dt = parse_dt_field(payload, "to_iso8601")
    store.clock = dt
    return success_object({"now": format_iso(store.clock)}, status=200)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@app.route("/dental/plans", methods=["POST"])
def create_plan():
    require_role("PlanAdmin")
    payload = body()
    require_fields(
        payload,
        "plan_code", "plan_year_start_month",
        "annual_maximum_cents", "deductible_cents",
        "deductible_applies_preventive",
        "preventive_coinsurance_pct", "basic_coinsurance_pct", "major_coinsurance_pct",
        "basic_waiting_months", "major_waiting_months",
        "missing_tooth_clause_active", "abp_enabled",
    )
    annual_max = require_int(payload, "annual_maximum_cents")
    deductible = require_int(payload, "deductible_cents")
    prev_pct = require_int(payload, "preventive_coinsurance_pct")
    basic_pct = require_int(payload, "basic_coinsurance_pct")
    major_pct = require_int(payload, "major_coinsurance_pct")
    if not (0 <= prev_pct <= 100 and 0 <= basic_pct <= 100 and 0 <= major_pct <= 100):
        raise ApiError(ERR_INVALID_PLAN_CONFIG, "Coinsurance pct outside [0,100]", 422)
    if annual_max < 0 or deductible < 0:
        raise ApiError(ERR_INVALID_PLAN_CONFIG, "Negative plan financials not allowed", 422)
    plan = create_record(store.plans, {
        "plan_code": payload["plan_code"],
        "plan_year_start_month": require_int(payload, "plan_year_start_month"),
        "annual_maximum_cents": annual_max,
        "deductible_cents": deductible,
        "deductible_applies_preventive": require_bool(payload, "deductible_applies_preventive"),
        "preventive_coinsurance_pct": prev_pct,
        "basic_coinsurance_pct": basic_pct,
        "major_coinsurance_pct": major_pct,
        "basic_waiting_months": require_int(payload, "basic_waiting_months"),
        "major_waiting_months": require_int(payload, "major_waiting_months"),
        "missing_tooth_clause_active": require_bool(payload, "missing_tooth_clause_active"),
        "abp_enabled": require_bool(payload, "abp_enabled"),
        "status": "DRAFT",
    })
    return success_object(render_plan(plan), status=201)


@app.route("/dental/plans", methods=["GET"])
def list_plans():
    current_identity()
    items = list(store.plans.values())
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    if "plan_code" in request.args:
        items = [p for p in items if p["plan_code"] == request.args["plan_code"]]
    return paginate(items, render_plan)


def _get_plan_or_404(plan_id):
    plan = store.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_PLAN_NOT_FOUND, "Plan not found", 404)
    return plan


@app.route("/dental/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    current_identity()
    return success_object(render_plan(_get_plan_or_404(plan_id)))


@app.route("/dental/plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    require_role("PlanAdmin")
    plan = _get_plan_or_404(plan_id)
    if plan["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Plan must be DRAFT or SUSPENDED to activate", 409)
    if plan["status"] == "DRAFT":
        for other in store.plans.values():
            if other["id"] == plan["id"]:
                continue
            if other["status"] == "ACTIVE" and other["plan_code"] == plan["plan_code"]:
                raise ApiError(ERR_INVALID_STATE, "Another ACTIVE plan carries the same plan_code", 409)
    plan["status"] = "ACTIVE"
    mutate_record(plan)
    return success_object(render_plan(plan))


@app.route("/dental/plans/<plan_id>/suspend", methods=["POST"])
def suspend_plan(plan_id):
    require_role("PlanAdmin")
    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Plan must be ACTIVE to suspend", 409)
    plan["status"] = "SUSPENDED"
    mutate_record(plan)
    return success_object(render_plan(plan))


@app.route("/dental/plans/<plan_id>/retire", methods=["POST"])
def retire_plan(plan_id):
    require_role("PlanAdmin")
    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Plan must be ACTIVE to retire", 409)
    for sub in store.subscribers.values():
        if sub["plan_id"] == plan["id"] and sub["status"] == "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Plan has ACTIVE subscribers", 409)
    plan["status"] = "RETIRED"
    mutate_record(plan)
    return success_object(render_plan(plan))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@app.route("/dental/providers", methods=["POST"])
def create_provider():
    require_role("NetworkManager")
    payload = body()
    require_fields(payload, "npi", "legal_name", "tier", "license_state", "contracted_on")
    tier = require_enum(payload, "tier", {"PREMIER", "PPO", "OUT_OF_NETWORK"})
    contracted_dt = parse_dt_field(payload, "contracted_on")
    provider = create_record(store.providers, {
        "npi": payload["npi"],
        "legal_name": payload["legal_name"],
        "tier": tier,
        "license_state": payload["license_state"],
        "contracted_on_dt": contracted_dt,
        "status": "ACTIVE",
    })
    return success_object(render_provider(provider), status=201)


@app.route("/dental/providers", methods=["GET"])
def list_providers():
    current_identity()
    items = list(store.providers.values())
    if "tier" in request.args:
        items = [p for p in items if p["tier"] == request.args["tier"]]
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    return paginate(items, render_provider)


def _get_provider_or_404(pid):
    p = store.providers.get(pid)
    if p is None:
        raise ApiError(ERR_PROVIDER_NOT_FOUND, "Provider not found", 404)
    return p


@app.route("/dental/providers/<pid>", methods=["GET"])
def get_provider(pid):
    current_identity()
    return success_object(render_provider(_get_provider_or_404(pid)))


@app.route("/dental/providers/<pid>/terminate", methods=["POST"])
def terminate_provider(pid):
    require_role("NetworkManager")
    provider = _get_provider_or_404(pid)
    if provider["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Provider must be ACTIVE to terminate", 409)
    for predet in store.predeterminations.values():
        if predet["provider_id"] == pid and predet["status"] == "UNDER_REVIEW":
            raise ApiError(ERR_PROVIDER_BUSY, "Provider has an UNDER_REVIEW predetermination", 409)
    for claim in store.claims.values():
        if claim["provider_id"] == pid and claim["status"] == "PENDED_REVIEW":
            raise ApiError(ERR_PROVIDER_BUSY, "Provider has a PENDED_REVIEW claim", 409)
    provider["status"] = "TERMINATED"
    mutate_record(provider)
    return success_object(render_provider(provider))


# ---------------------------------------------------------------------------
# Fee schedules
# ---------------------------------------------------------------------------

@app.route("/dental/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require_role("NetworkManager")
    payload = body()
    require_fields(payload, "tier", "effective_from", "entries")
    tier = require_enum(payload, "tier", {"PREMIER", "PPO", "OUT_OF_NETWORK"})
    effective_from_dt = parse_dt_field(payload, "effective_from")
    effective_to_dt = parse_dt_field(payload, "effective_to", required=False)
    effective_to_raw = payload.get("effective_to") if effective_to_dt is not None else None
    entries_in = payload["entries"]
    if not isinstance(entries_in, list):
        raise ApiError(ERR_INVALID_REQUEST, "entries must be an array", 400)
    schedule = create_record(store.fee_schedules, {
        "tier": tier,
        "effective_from_dt": effective_from_dt,
        "effective_from_raw": payload["effective_from"],
        "effective_to_dt": effective_to_dt,
        "effective_to_raw": effective_to_raw,
        "status": "PENDING",
    })
    for entry_payload in entries_in:
        require_fields(entry_payload, "cdt_code", "allowed_cents", "category")
        category = require_enum(entry_payload, "category", {"PREVENTIVE", "BASIC", "MAJOR"})
        allowed_cents = entry_payload["allowed_cents"]
        if not isinstance(allowed_cents, int) or isinstance(allowed_cents, bool):
            raise ApiError(ERR_INVALID_REQUEST, "allowed_cents must be an integer", 400)
        create_record(store.fee_schedule_entries, {
            "fee_schedule_id": schedule["id"],
            "cdt_code": entry_payload["cdt_code"],
            "allowed_cents": allowed_cents,
            "category": category,
            "requires_attachment": bool(entry_payload.get("requires_attachment", False)),
            "abp_alternative_cdt": entry_payload.get("abp_alternative_cdt") or "",
        })
    return success_object(render_schedule(schedule), status=201)


@app.route("/dental/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_role("PlanAdmin", "NetworkManager", "ClaimsExaminer", "ClinicalReviewer")
    items = list(store.fee_schedules.values())
    if "tier" in request.args:
        items = [s for s in items if s["tier"] == request.args["tier"]]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    return paginate(items, render_schedule)


def _get_schedule_or_404(sid):
    s = store.fee_schedules.get(sid)
    if s is None:
        raise ApiError(ERR_FEE_SCHEDULE_NOT_FOUND, "FeeSchedule not found", 404)
    return s


@app.route("/dental/fee-schedules/<sid>", methods=["GET"])
def get_fee_schedule(sid):
    require_role("PlanAdmin", "NetworkManager", "ClaimsExaminer", "ClinicalReviewer")
    return success_object(render_schedule(_get_schedule_or_404(sid)))


@app.route("/dental/fee-schedules/<sid>/entries", methods=["GET"])
def list_fee_schedule_entries(sid):
    require_role("PlanAdmin", "NetworkManager", "ClaimsExaminer", "ClinicalReviewer")
    _get_schedule_or_404(sid)
    items = [e for e in store.fee_schedule_entries.values() if e["fee_schedule_id"] == sid]
    if "cdt_code" in request.args:
        items = [e for e in items if e["cdt_code"] == request.args["cdt_code"]]
    return paginate(items, render_entry)


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; None to means open-ended."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    # a starts before b ends AND b starts before a ends
    a_before_b_end = (b_end is None) or (a_from < b_end)
    b_before_a_end = (a_end is None) or (b_from < a_end)
    return a_before_b_end and b_before_a_end


@app.route("/dental/fee-schedules/<sid>/activate", methods=["POST"])
def activate_fee_schedule(sid):
    require_role("NetworkManager")
    schedule = _get_schedule_or_404(sid)
    if schedule["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "FeeSchedule must be PENDING to activate", 409)
    new_from = schedule["effective_from_dt"]
    new_to = schedule["effective_to_dt"]

    # Phase 1: forbid retroactive insertion (existing ACTIVE same-tier whose
    # effective_from is strictly LATER than new.effective_from AND overlaps).
    for other in store.fee_schedules.values():
        if other["id"] == schedule["id"]:
            continue
        if other["status"] != "ACTIVE" or other["tier"] != schedule["tier"]:
            continue
        if other["effective_from_dt"] > new_from and _windows_overlap(
            other["effective_from_dt"], other["effective_to_dt"], new_from, new_to
        ):
            raise ApiError(ERR_SCHEDULE_OVERLAP, "Retroactive insertion overlaps an ACTIVE schedule", 409)

    # Phase 2: activate the new schedule.
    schedule["status"] = "ACTIVE"
    mutate_record(schedule)

    # Phase 3: truncate each overlapping ACTIVE same-tier schedule whose
    # effective_from <= new.effective_from.
    for other in store.fee_schedules.values():
        if other["id"] == schedule["id"]:
            continue
        if other["status"] != "ACTIVE" or other["tier"] != schedule["tier"]:
            continue
        if other["effective_from_dt"] <= new_from and _windows_overlap(
            other["effective_from_dt"], other["effective_to_dt"], new_from, new_to
        ):
            if other["effective_to_dt"] != new_from:
                other["effective_to_dt"] = new_from
                other["effective_to_raw"] = schedule["effective_from_raw"]
                mutate_record(other)

    # Phase 4: recompute every UNDER_REVIEW predetermination on the same tier.
    for predet in store.predeterminations.values():
        if predet["status"] != "UNDER_REVIEW":
            continue
        provider = store.providers.get(predet["provider_id"])
        if provider is None or provider["tier"] != schedule["tier"]:
            continue
        try:
            recompute_predet_estimate(predet)
            mutate_record(predet)
        except ApiError:
            # No schedule covers the planned date — leave the predetermination
            # estimate as-is; the next assignment/approval will surface the error.
            mutate_record(predet)

    return success_object(render_schedule(schedule))


@app.route("/dental/fee-schedules/<sid>/retire", methods=["POST"])
def retire_fee_schedule(sid):
    require_role("NetworkManager")
    schedule = _get_schedule_or_404(sid)
    if schedule["status"] == "PENDING":
        schedule["status"] = "RETIRED"
        mutate_record(schedule)
        return success_object(render_schedule(schedule))
    if schedule["status"] == "ACTIVE":
        # Refuse when an in-flight claim was priced against this schedule.
        for claim in store.claims.values():
            if claim["status"] not in ("PENDED_ATTACHMENTS", "PENDED_REVIEW"):
                continue
            provider = store.providers.get(claim["provider_id"])
            if provider is None or provider["tier"] != schedule["tier"]:
                continue
            raise ApiError(ERR_INVALID_STATE, "In-flight claims priced against this schedule", 409)
        # ACTIVE -> SUPERSEDED is the canonical retire path per §1.2 note.
        schedule["status"] = "SUPERSEDED"
        mutate_record(schedule)
        return success_object(render_schedule(schedule))
    raise ApiError(ERR_INVALID_STATE, "FeeSchedule cannot be retired from %s" % schedule["status"], 409)


# ---------------------------------------------------------------------------
# Limitation rules
# ---------------------------------------------------------------------------

@app.route("/dental/plans/<plan_id>/limitation-rules", methods=["POST"])
def create_limitation_rule(plan_id):
    require_role("PlanAdmin")
    plan = _get_plan_or_404(plan_id)
    payload = body()
    require_fields(payload, "cdt_code", "rule_kind")
    rule_kind = require_enum(
        payload, "rule_kind",
        {"FREQUENCY", "AGE_MAX", "AGE_MIN", "REPLACEMENT_INTERVAL", "MISSING_TOOTH"},
    )
    rule = create_record(store.limitation_rules, {
        "plan_id": plan["id"],
        "cdt_code": payload["cdt_code"],
        "rule_kind": rule_kind,
        "window_months": int(payload.get("window_months", 0)),
        "max_occurrences": int(payload.get("max_occurrences", 0)),
        "age_years_min": int(payload.get("age_years_min", 0)),
        "age_years_max": int(payload.get("age_years_max", 0)),
        "status": "ACTIVE",
    })
    return success_object(render_rule(rule), status=201)


@app.route("/dental/plans/<plan_id>/limitation-rules", methods=["GET"])
def list_limitation_rules(plan_id):
    require_role("PlanAdmin", "NetworkManager", "ClaimsExaminer", "ClinicalReviewer")
    _get_plan_or_404(plan_id)
    items = [r for r in store.limitation_rules.values() if r["plan_id"] == plan_id]
    if "rule_kind" in request.args:
        items = [r for r in items if r["rule_kind"] == request.args["rule_kind"]]
    if "cdt_code" in request.args:
        items = [r for r in items if r["cdt_code"] == request.args["cdt_code"]]
    return paginate(items, render_rule)


@app.route("/dental/limitation-rules/<rid>", methods=["GET"])
def get_limitation_rule(rid):
    require_role("PlanAdmin", "NetworkManager", "ClaimsExaminer", "ClinicalReviewer")
    rule = store.limitation_rules.get(rid)
    if rule is None:
        raise ApiError(ERR_NOT_FOUND, "LimitationRule not found", 404)
    return success_object(render_rule(rule))


# ---------------------------------------------------------------------------
# Subscribers / dependents / accumulators
# ---------------------------------------------------------------------------

@app.route("/dental/subscribers", methods=["POST"])
def create_subscriber():
    require_role("PlanAdmin")
    payload = body()
    require_fields(payload, "plan_id", "member_id", "full_name", "date_of_birth",
                   "effective_date", "cob_priority")
    plan_id = payload["plan_id"]
    plan = store.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "plan_id does not resolve", 404)
    cob_priority = require_enum(payload, "cob_priority", {"PRIMARY", "SECONDARY", "NONE"})
    other_plan_external_id = payload.get("other_plan_external_id") or ""
    # State check before referential pairing (PRD §2.10 layering).
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE", 409)
    if cob_priority == "SECONDARY" and not other_plan_external_id:
        raise ApiError(ERR_COB_CONFIG_INVALID, "SECONDARY requires other_plan_external_id", 422)
    if cob_priority != "SECONDARY" and other_plan_external_id:
        raise ApiError(ERR_COB_CONFIG_INVALID, "other_plan_external_id must be empty unless SECONDARY", 422)
    subscriber = create_record(store.subscribers, {
        "plan_id": plan["id"],
        "member_id": payload["member_id"],
        "full_name": payload["full_name"],
        "date_of_birth_dt": parse_dt_field(payload, "date_of_birth"),
        "effective_date_dt": parse_dt_field(payload, "effective_date"),
        "cob_priority": cob_priority,
        "other_plan_external_id": other_plan_external_id,
        "status": "ACTIVE",
    })
    return success_object(render_subscriber(subscriber), status=201)


@app.route("/dental/subscribers", methods=["GET"])
def list_subscribers():
    current_identity()
    items = list(store.subscribers.values())
    if "plan_id" in request.args:
        items = [s for s in items if s["plan_id"] == request.args["plan_id"]]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    return paginate(items, render_subscriber)


def _get_subscriber_or_404(sid):
    s = store.subscribers.get(sid)
    if s is None:
        raise ApiError(ERR_SUBSCRIBER_NOT_FOUND, "Subscriber not found", 404)
    return s


@app.route("/dental/subscribers/<sid>", methods=["GET"])
def get_subscriber(sid):
    current_identity()
    return success_object(render_subscriber(_get_subscriber_or_404(sid)))


@app.route("/dental/subscribers/<sid>/terminate", methods=["POST"])
def terminate_subscriber(sid):
    require_role("PlanAdmin")
    subscriber = _get_subscriber_or_404(sid)
    if subscriber["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Subscriber must be ACTIVE to terminate", 409)
    for claim in store.claims.values():
        if claim["subscriber_id"] == sid and claim["status"] in (
            "RECEIVED", "PENDED_ATTACHMENTS", "PENDED_REVIEW", "ADJUDICATED"
        ):
            raise ApiError(ERR_INVALID_STATE, "Open claims must first reach PAID/DENIED/VOID", 409)
    subscriber["status"] = "TERMINATED"
    mutate_record(subscriber)
    for dep in store.dependents.values():
        if dep["subscriber_id"] == sid and dep["status"] == "ACTIVE":
            dep["status"] = "TERMINATED"
            mutate_record(dep)
    for predet in store.predeterminations.values():
        if predet["subscriber_id"] == sid and predet["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            predet["status"] = "WITHDRAWN"
            mutate_record(predet)
    return success_object(render_subscriber(subscriber))


@app.route("/dental/subscribers/<sid>/dependents", methods=["POST"])
def create_dependent(sid):
    require_role("PlanAdmin")
    subscriber = _get_subscriber_or_404(sid)
    payload = body()
    require_fields(payload, "full_name", "date_of_birth", "relationship")
    relationship = require_enum(payload, "relationship", {"SPOUSE", "CHILD", "DOMESTIC_PARTNER"})
    dependent = create_record(store.dependents, {
        "subscriber_id": subscriber["id"],
        "full_name": payload["full_name"],
        "date_of_birth_dt": parse_dt_field(payload, "date_of_birth"),
        "relationship": relationship,
        "status": "ACTIVE",
    })
    return success_object(render_dependent(dependent), status=201)


@app.route("/dental/subscribers/<sid>/dependents", methods=["GET"])
def list_dependents(sid):
    current_identity()
    _get_subscriber_or_404(sid)
    items = [d for d in store.dependents.values() if d["subscriber_id"] == sid]
    if "status" in request.args:
        items = [d for d in items if d["status"] == request.args["status"]]
    return paginate(items, render_dependent)


def _get_dependent_or_404(did):
    d = store.dependents.get(did)
    if d is None:
        raise ApiError(ERR_DEPENDENT_NOT_FOUND, "Dependent not found", 404)
    return d


@app.route("/dental/dependents/<did>", methods=["GET"])
def get_dependent(did):
    current_identity()
    return success_object(render_dependent(_get_dependent_or_404(did)))


@app.route("/dental/dependents/<did>/terminate", methods=["POST"])
def terminate_dependent(did):
    require_role("PlanAdmin")
    dependent = _get_dependent_or_404(did)
    if dependent["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Dependent must be ACTIVE to terminate", 409)
    dependent["status"] = "TERMINATED"
    mutate_record(dependent)
    return success_object(render_dependent(dependent))


@app.route("/dental/subscribers/<sid>/accumulators", methods=["GET"])
def list_subscriber_accumulators(sid):
    current_identity()
    _get_subscriber_or_404(sid)
    items = [a for a in store.accumulators.values() if a["subscriber_id"] == sid]
    if "dependent_id" in request.args:
        items = [a for a in items if a.get("dependent_id") == request.args["dependent_id"]]
    if "plan_year_key" in request.args:
        items = [a for a in items if a["plan_year_key"] == request.args["plan_year_key"]]
    return paginate(items, render_accumulator)


@app.route("/dental/dependents/<did>/accumulators", methods=["GET"])
def list_dependent_accumulators(did):
    current_identity()
    _get_dependent_or_404(did)
    items = [a for a in store.accumulators.values() if a.get("dependent_id") == did]
    if "plan_year_key" in request.args:
        items = [a for a in items if a["plan_year_key"] == request.args["plan_year_key"]]
    return paginate(items, render_accumulator)


# ---------------------------------------------------------------------------
# Predeterminations
# ---------------------------------------------------------------------------

@app.route("/dental/predeterminations", methods=["POST"])
def create_predetermination():
    user_id, role = require_role("Member", "Provider")
    payload = body()
    require_fields(payload, "subscriber_id", "provider_id", "cdt_code",
                   "submitted_amount_cents", "planned_service_date")
    subscriber_id = payload["subscriber_id"]
    provider_id = payload["provider_id"]
    # Ownership gate (priority 2.5)
    if role == "Member" and user_id != subscriber_id:
        raise ApiError(ERR_UNAUTHORIZED, "Member may only file for self", 403)
    if role == "Provider" and user_id != provider_id:
        raise ApiError(ERR_UNAUTHORIZED, "Provider may only file as self", 403)
    # Body FK existence (priority 4)
    subscriber = store.subscribers.get(subscriber_id)
    if subscriber is None:
        raise ApiError(ERR_NOT_FOUND, "subscriber_id does not resolve", 404)
    provider = store.providers.get(provider_id)
    if provider is None:
        raise ApiError(ERR_NOT_FOUND, "provider_id does not resolve", 404)
    dependent_id = payload.get("dependent_id")
    dependent = None
    if dependent_id:
        dependent = store.dependents.get(dependent_id)
        if dependent is None:
            raise ApiError(ERR_NOT_FOUND, "dependent_id does not resolve", 404)
    # Required type/enum validation (priority 4.5)
    if not isinstance(payload["submitted_amount_cents"], int) or isinstance(payload["submitted_amount_cents"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "submitted_amount_cents must be an integer", 400)
    planned_dt = parse_dt_field(payload, "planned_service_date")
    # Provider state (priority 7)
    if provider["status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_TERMINATED, "Provider is TERMINATED", 409)
    # Retroactivity (priority 9)
    if planned_dt < store.clock:
        raise ApiError(ERR_RETROACTIVE_PREDETERMINATION, "planned_service_date is in the past", 422)
    # Cross-reference (priority 10)
    if dependent is not None and dependent["subscriber_id"] != subscriber["id"]:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, "dependent does not belong to subscriber", 422)

    predet = create_record(store.predeterminations, {
        "subscriber_id": subscriber["id"],
        "plan_id": subscriber["plan_id"],
        "dependent_id": dependent_id,
        "provider_id": provider["id"],
        "cdt_code": payload["cdt_code"],
        "submitted_amount_cents": payload["submitted_amount_cents"],
        "planned_service_date_dt": planned_dt,
        "clinical_reviewer_id": "",
        "estimated_allowed_cents": 0,
        "estimated_plan_pay_cents": 0,
        "estimated_patient_pay_cents": 0,
        "abp_applied": False,
        "version_pin_fee_schedule_id": None,
        "expires_on_dt": None,
        "status": "SUBMITTED",
    })
    return success_object(render_predet(predet), status=201)


@app.route("/dental/predeterminations", methods=["GET"])
def list_predeterminations():
    current_identity()
    items = list(store.predeterminations.values())
    for p in items:
        maybe_expire(p)
    if "subscriber_id" in request.args:
        items = [p for p in items if p["subscriber_id"] == request.args["subscriber_id"]]
    if "dependent_id" in request.args:
        items = [p for p in items if p.get("dependent_id") == request.args["dependent_id"]]
    if "provider_id" in request.args:
        items = [p for p in items if p["provider_id"] == request.args["provider_id"]]
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    if "cdt_code" in request.args:
        items = [p for p in items if p["cdt_code"] == request.args["cdt_code"]]
    if "version_pin_fee_schedule_id" in request.args:
        items = [p for p in items if p.get("version_pin_fee_schedule_id") == request.args["version_pin_fee_schedule_id"]]
    return paginate(items, render_predet)


def _get_predet_or_404(pid):
    p = store.predeterminations.get(pid)
    if p is None:
        raise ApiError(ERR_PREDETERMINATION_NOT_FOUND, "Predetermination not found", 404)
    maybe_expire(p)
    return p


@app.route("/dental/predeterminations/<pid>", methods=["GET"])
def get_predetermination(pid):
    current_identity()
    return success_object(render_predet(_get_predet_or_404(pid)))


@app.route("/dental/predeterminations/<pid>/assign", methods=["POST"])
def assign_predetermination(pid):
    user_id, role = require_role("ClinicalReviewer")
    predet = _get_predet_or_404(pid)
    payload = body()
    require_fields(payload, "clinical_reviewer_id")
    reviewer_id = payload["clinical_reviewer_id"]
    if reviewer_id != user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Reviewer must self-assign", 403)
    if predet["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Predetermination must be SUBMITTED to assign", 409)
    subscriber = store.subscribers.get(predet["subscriber_id"])
    if subscriber is None or subscriber["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Subscriber is not ACTIVE", 409)
    predet["clinical_reviewer_id"] = reviewer_id
    recompute_predet_estimate(predet)
    predet["status"] = "UNDER_REVIEW"
    mutate_record(predet)
    return success_object(render_predet(predet))


@app.route("/dental/predeterminations/<pid>/reassign", methods=["POST"])
def reassign_predetermination(pid):
    user_id, role = require_role("ClinicalReviewer")
    predet = _get_predet_or_404(pid)
    payload = body()
    require_fields(payload, "clinical_reviewer_id")
    new_reviewer = payload["clinical_reviewer_id"]
    if new_reviewer != user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Payload reviewer must equal X-User-ID", 403)
    if predet["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Predetermination must be UNDER_REVIEW to reassign", 409)
    if new_reviewer == predet["clinical_reviewer_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Cannot reassign to self", 403)
    predet["clinical_reviewer_id"] = new_reviewer
    recompute_predet_estimate(predet)
    mutate_record(predet)
    return success_object(render_predet(predet))


@app.route("/dental/predeterminations/<pid>/approve", methods=["POST"])
def approve_predetermination(pid):
    user_id, role = require_role("ClinicalReviewer")
    predet = _get_predet_or_404(pid)
    payload = body()
    require_fields(payload, "expected_predetermination_version")
    expected = payload["expected_predetermination_version"]
    if predet["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Predetermination must be UNDER_REVIEW to approve", 409)
    if user_id != predet["clinical_reviewer_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Only the assigned reviewer may approve", 403)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_predetermination_version must be an integer", 400)
    if expected != predet["version"]:
        raise ApiError(ERR_STALE_VERSION, "Predetermination version has advanced", 412)
    # Re-run the estimate against current state and pin the schedule.
    schedule = recompute_predet_estimate(predet)
    # Annual-max guard: refuse when even the freshly computed estimate exceeds the cap.
    plan = store.plans[predet["plan_id"]]
    subscriber = store.subscribers[predet["subscriber_id"]]
    dependent_id = predet.get("dependent_id")
    from services import plan_year_key, get_or_create_accumulator
    key = plan_year_key(plan, predet["planned_service_date_dt"])
    # Read-only — do not materialize the accumulator.
    current_used = 0
    for acc in store.accumulators.values():
        if (acc["subscriber_id"] == subscriber["id"]
                and acc.get("dependent_id") == dependent_id
                and acc["plan_year_key"] == key):
            current_used = acc["annual_max_used_cents"]
            break
    remaining_max = plan["annual_maximum_cents"] - current_used
    if predet["estimated_plan_pay_cents"] > remaining_max:
        raise ApiError(ERR_ANNUAL_MAX_EXCEEDED,
                       "Estimated plan pay exceeds remaining annual maximum", 422)
    predet["version_pin_fee_schedule_id"] = schedule["id"]
    predet["expires_on_dt"] = store.clock + timedelta(days=90)
    predet["status"] = "APPROVED"
    mutate_record(predet)
    return success_object(render_predet(predet))


@app.route("/dental/predeterminations/<pid>/deny", methods=["POST"])
def deny_predetermination(pid):
    user_id, role = require_role("ClinicalReviewer")
    predet = _get_predet_or_404(pid)
    if predet["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Predetermination must be UNDER_REVIEW to deny", 409)
    if user_id != predet["clinical_reviewer_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Only the assigned reviewer may deny", 403)
    predet["status"] = "DENIED"
    mutate_record(predet)
    return success_object(render_predet(predet))


@app.route("/dental/predeterminations/<pid>/withdraw", methods=["POST"])
def withdraw_predetermination(pid):
    user_id, role = require_role("Member")
    predet = _get_predet_or_404(pid)
    if user_id != predet["subscriber_id"]:
        raise ApiError(ERR_UNAUTHORIZED, "Member may withdraw only their own predetermination", 403)
    if predet["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, "Only SUBMITTED or UNDER_REVIEW may be withdrawn", 409)
    predet["status"] = "WITHDRAWN"
    mutate_record(predet)
    return success_object(render_predet(predet))


# ---------------------------------------------------------------------------
# Claims / lines / attachments
# ---------------------------------------------------------------------------

def _claim_check_intake(claim, provider, plan):
    """Timely filing + schedule gate per PRD §3.5."""
    service_dt = claim["service_date_dt"]
    received_dt = claim["received_date_dt"]
    # Timely filing: received_date > service_date + 365 days rejects; == is timely.
    if received_dt > service_dt + timedelta(days=365):
        raise ApiError(ERR_TIMELY_FILING, "received_date is more than 365 days after service_date", 422)
    # Schedule gate: ACTIVE schedule covering provider tier at service_date with
    # an entry for every cdt_code.
    schedule = resolve_active_schedule(provider["tier"], service_dt)
    if schedule is None:
        # A pinned predetermination may supply the schedule even when no
        # currently ACTIVE schedule covers the anchor.
        predet_id = claim.get("predetermination_id")
        pinned = None
        if predet_id:
            predet = store.predeterminations.get(predet_id)
            if predet is not None:
                maybe_expire(predet)
                if predet["status"] == "APPROVED" and predet.get("version_pin_fee_schedule_id"):
                    pinned = store.fee_schedules.get(predet["version_pin_fee_schedule_id"])
        if pinned is None:
            raise ApiError(ERR_NO_FEE_SCHEDULE,
                           "No ACTIVE FeeSchedule covers the provider's tier at the service_date",
                           422)
        schedule = pinned
    for line in claim["_line_payloads"]:
        require_entry(schedule["id"], line["cdt_code"])


@app.route("/dental/claims", methods=["POST"])
def create_claim():
    user_id, role = require_role("Provider", "ClaimsExaminer")
    payload = body()
    # Required-field shape (priority 4.5 happens after FK existence per §2.10;
    # but missing lines is a structural shape error -> 400 with ERR_INVALID_REQUEST)
    require_fields(payload, "subscriber_id", "provider_id", "service_date",
                   "received_date", "lines")
    subscriber_id = payload["subscriber_id"]
    provider_id = payload["provider_id"]
    if role == "Provider" and user_id != provider_id:
        raise ApiError(ERR_UNAUTHORIZED, "Provider may only file as self", 403)
    # Body FK existence
    subscriber = store.subscribers.get(subscriber_id)
    if subscriber is None:
        raise ApiError(ERR_NOT_FOUND, "subscriber_id does not resolve", 404)
    provider = store.providers.get(provider_id)
    if provider is None:
        raise ApiError(ERR_NOT_FOUND, "provider_id does not resolve", 404)
    dependent_id = payload.get("dependent_id")
    dependent = None
    if dependent_id:
        dependent = store.dependents.get(dependent_id)
        if dependent is None:
            raise ApiError(ERR_NOT_FOUND, "dependent_id does not resolve", 404)
    predet_id = payload.get("predetermination_id")
    predet = None
    if predet_id:
        predet = store.predeterminations.get(predet_id)
        if predet is None:
            raise ApiError(ERR_NOT_FOUND, "predetermination_id does not resolve", 404)
    # Required-field types
    service_dt = parse_dt_field(payload, "service_date")
    received_dt = parse_dt_field(payload, "received_date")
    lines_in = payload["lines"]
    if not isinstance(lines_in, list) or not lines_in:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
    for line_payload in lines_in:
        require_fields(line_payload, "line_number", "cdt_code", "submitted_amount_cents")
        if not isinstance(line_payload["line_number"], int) or isinstance(line_payload["line_number"], bool):
            raise ApiError(ERR_INVALID_REQUEST, "line_number must be an integer", 400)
        if not isinstance(line_payload["submitted_amount_cents"], int) or isinstance(line_payload["submitted_amount_cents"], bool):
            raise ApiError(ERR_INVALID_REQUEST, "submitted_amount_cents must be an integer", 400)
    cob_other_paid = payload.get("cob_other_plan_paid_cents", 0)
    if not isinstance(cob_other_paid, int) or isinstance(cob_other_paid, bool):
        raise ApiError(ERR_INVALID_REQUEST, "cob_other_plan_paid_cents must be an integer", 400)
    tooth_attest = payload.get("tooth_missing_prior_to_coverage") or {}
    if not isinstance(tooth_attest, dict):
        raise ApiError(ERR_INVALID_REQUEST, "tooth_missing_prior_to_coverage must be an object", 400)
    # Plan state (priority 6)
    plan = store.plans[subscriber["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE", 409)
    # Provider state (priority 7)
    if provider["status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_TERMINATED, "Provider is TERMINATED", 409)
    # Cross-reference (priority 10)
    if dependent is not None and dependent["subscriber_id"] != subscriber["id"]:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, "dependent does not belong to subscriber", 422)

    claim = create_record(store.claims, {
        "subscriber_id": subscriber["id"],
        "plan_id": plan["id"],
        "dependent_id": dependent_id,
        "provider_id": provider["id"],
        "predetermination_id": predet_id,
        "service_date_dt": service_dt,
        "received_date_dt": received_dt,
        "cob_other_plan_paid_cents": cob_other_paid,
        "cob_secondary_payment_cents": 0,
        "tooth_missing_prior_to_coverage": dict(tooth_attest),
        "total_submitted_cents": 0,
        "total_allowed_cents": 0,
        "total_plan_pay_cents": 0,
        "total_patient_pay_cents": 0,
        "status": "RECEIVED",
        "_line_payloads": lines_in,
    })

    # Intake gates: timely filing + schedule coverage.
    try:
        _claim_check_intake(claim, provider, plan)
    except ApiError:
        # Roll back: the claim must never persist on refusal (PRD §3.5).
        del store.claims[claim["id"]]
        raise

    # Create ClaimLine rows in PENDING.
    for line_payload in lines_in:
        create_record(store.claim_lines, {
            "claim_id": claim["id"],
            "line_number": line_payload["line_number"],
            "cdt_code": line_payload["cdt_code"],
            "tooth_number": line_payload.get("tooth_number") or "",
            "submitted_amount_cents": line_payload["submitted_amount_cents"],
            "status": "PENDING",
            "denial_code": None,
        })

    # Routing: attachments first, then COB pend, then straight adjudication.
    schedule = resolve_active_schedule(provider["tier"], service_dt)
    if schedule is None:
        predet_id = claim.get("predetermination_id")
        if predet_id:
            predet = store.predeterminations.get(predet_id)
            if predet is not None:
                maybe_expire(predet)
                if predet["status"] == "APPROVED" and predet.get("version_pin_fee_schedule_id"):
                    schedule = store.fee_schedules.get(predet["version_pin_fee_schedule_id"])
    attachment_needed = False
    if schedule is not None:
        for line_payload in lines_in:
            entry = find_entry(schedule["id"], line_payload["cdt_code"])
            if entry is not None and entry.get("requires_attachment"):
                attachment_needed = True
                break

    # Drop the helper stash from the record before persisting further.
    claim.pop("_line_payloads", None)

    if attachment_needed:
        claim["status"] = "PENDED_ATTACHMENTS"
        mutate_record(claim)
    elif subscriber["cob_priority"] == "SECONDARY":
        claim["status"] = "PENDED_REVIEW"
        mutate_record(claim)
    else:
        adjudicate_claim(claim)

    return success_object(render_claim(claim), status=201)


@app.route("/dental/claims", methods=["GET"])
def list_claims():
    current_identity()
    items = list(store.claims.values())
    if "subscriber_id" in request.args:
        items = [c for c in items if c["subscriber_id"] == request.args["subscriber_id"]]
    if "dependent_id" in request.args:
        items = [c for c in items if c.get("dependent_id") == request.args["dependent_id"]]
    if "provider_id" in request.args:
        items = [c for c in items if c["provider_id"] == request.args["provider_id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    if "predetermination_id" in request.args:
        items = [c for c in items if c.get("predetermination_id") == request.args["predetermination_id"]]
    return paginate(items, render_claim)


def _get_claim_or_404(cid):
    c = store.claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, "Claim not found", 404)
    return c


@app.route("/dental/claims/<cid>", methods=["GET"])
def get_claim(cid):
    current_identity()
    return success_object(render_claim(_get_claim_or_404(cid)))


@app.route("/dental/claims/<cid>/lines", methods=["GET"])
def list_claim_lines(cid):
    current_identity()
    _get_claim_or_404(cid)
    items = [l for l in store.claim_lines.values() if l["claim_id"] == cid]
    items.sort(key=lambda l: l["line_number"])
    if "status" in request.args:
        items = [l for l in items if l["status"] == request.args["status"]]
    return paginate(items, render_line)


def _get_line_or_404(lid):
    l = store.claim_lines.get(lid)
    if l is None:
        raise ApiError(ERR_NOT_FOUND, "ClaimLine not found", 404)
    return l


@app.route("/dental/claim-lines/<lid>", methods=["GET"])
def get_claim_line(lid):
    current_identity()
    return success_object(render_line(_get_line_or_404(lid)))


@app.route("/dental/claim-lines/<lid>/attachments", methods=["GET"])
def list_claim_line_attachments(lid):
    current_identity()
    _get_line_or_404(lid)
    items = [a for a in store.claim_attachments.values() if a["claim_line_id"] == lid]
    return paginate(items, render_attachment)


ATTACHMENT_KINDS = {"RADIOGRAPH", "NARRATIVE", "PERIO_CHART", "PHOTO"}


def _claim_attachment_completeness(claim):
    """True when every line whose entry requires an attachment has at least one."""
    provider = store.providers.get(claim["provider_id"])
    if provider is None:
        return True
    schedule = resolve_active_schedule(provider["tier"], claim["service_date_dt"])
    if schedule is None:
        predet_id = claim.get("predetermination_id")
        if predet_id:
            predet = store.predeterminations.get(predet_id)
            if predet is not None:
                maybe_expire(predet)
                if predet["status"] == "APPROVED" and predet.get("version_pin_fee_schedule_id"):
                    schedule = store.fee_schedules.get(predet["version_pin_fee_schedule_id"])
    if schedule is None:
        return True
    lines = [l for l in store.claim_lines.values() if l["claim_id"] == claim["id"]]
    for line in lines:
        entry = find_entry(schedule["id"], line["cdt_code"])
        if entry is None:
            continue
        if not entry.get("requires_attachment"):
            continue
        has = any(
            a for a in store.claim_attachments.values()
            if a["claim_line_id"] == line["id"]
        )
        if not has:
            return False
    return True


@app.route("/dental/claims/<cid>/attachments", methods=["POST"])
def create_claim_attachment(cid):
    user_id, role = require_role("Provider")
    claim = _get_claim_or_404(cid)
    payload = body()
    # Invalid attachment shape — fires before cross-reference (priority 15
    # is later than priority 10, but the test for undeclared kind expects
    # ERR_INVALID_ATTACHMENT and the claim stays pended; both are checked).
    if "attachment_kind" not in payload or "blob_ref" not in payload:
        raise ApiError(ERR_INVALID_ATTACHMENT, "attachment_kind and blob_ref are required", 400)
    kind = payload["attachment_kind"]
    if kind not in ATTACHMENT_KINDS:
        raise ApiError(ERR_INVALID_ATTACHMENT, "attachment_kind outside the declared enum", 400)
    blob_ref = payload["blob_ref"]
    if not isinstance(blob_ref, str) or not blob_ref:
        raise ApiError(ERR_INVALID_ATTACHMENT, "blob_ref must be a non-empty string", 400)
    if "claim_line_id" not in payload or payload["claim_line_id"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "claim_line_id is required", 400)
    line_id = payload["claim_line_id"]
    line = store.claim_lines.get(line_id)
    if line is None:
        raise ApiError(ERR_NOT_FOUND, "claim_line_id does not resolve", 404)
    if line["claim_id"] != claim["id"]:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, "claim_line_id belongs to a different claim", 422)
    if user_id != claim["provider_id"]:
        raise ApiError(ERR_UNAUTHORIZED, "Only the rendering provider may attach", 403)
    if claim["status"] not in ("PENDED_ATTACHMENTS",):
        # Attachments on a non-pended claim are still accepted per §3.5, but the
        # routing side effect only fires from PENDED_ATTACHMENTS.
        pass
    attachment = create_record(store.claim_attachments, {
        "claim_id": claim["id"],
        "claim_line_id": line["id"],
        "attachment_kind": kind,
        "blob_ref": blob_ref,
        "transmitted_on": None,
    }, has_updated=False)
    attachment["transmitted_on"] = attachment["created_at"]

    # If claim was PENDED_ATTACHMENTS and is now complete, route forward.
    if claim["status"] == "PENDED_ATTACHMENTS" and _claim_attachment_completeness(claim):
        subscriber = store.subscribers[claim["subscriber_id"]]
        if subscriber["cob_priority"] == "SECONDARY":
            claim["status"] = "PENDED_REVIEW"
            mutate_record(claim)
        else:
            adjudicate_claim(claim)

    return success_object(render_attachment(attachment), status=201)


@app.route("/dental/claims/<cid>/attachments", methods=["GET"])
def list_claim_attachments(cid):
    current_identity()
    _get_claim_or_404(cid)
    items = [a for a in store.claim_attachments.values() if a["claim_id"] == cid]
    if "claim_line_id" in request.args:
        items = [a for a in items if a["claim_line_id"] == request.args["claim_line_id"]]
    return paginate(items, render_attachment)


@app.route("/dental/claims/<cid>/cob-confirm", methods=["POST"])
def cob_confirm_claim(cid):
    require_role("ClaimsExaminer")
    claim = _get_claim_or_404(cid)
    payload = body()
    require_fields(payload, "cob_other_plan_paid_cents")
    cob_paid = payload["cob_other_plan_paid_cents"]
    if not isinstance(cob_paid, int) or isinstance(cob_paid, bool):
        raise ApiError(ERR_INVALID_REQUEST, "cob_other_plan_paid_cents must be an integer", 400)
    if claim["status"] != "PENDED_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Claim must be PENDED_REVIEW to confirm COB", 409)
    claim["cob_other_plan_paid_cents"] = cob_paid
    adjudicate_claim(claim)
    return success_object(render_claim(claim))


@app.route("/dental/claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    require_role("ClaimsExaminer")
    claim = _get_claim_or_404(cid)
    if claim["status"] != "ADJUDICATED":
        raise ApiError(ERR_INVALID_STATE, "Claim must be ADJUDICATED to pay", 409)
    lines = [l for l in store.claim_lines.values() if l["claim_id"] == cid]
    if any(l["status"] == "PENDING" for l in lines):
        raise ApiError(ERR_INVALID_STATE, "All lines must be resolved before payment", 409)
    if not any(l["status"] == "PAYABLE" for l in lines):
        raise ApiError(ERR_INVALID_STATE, "At least one line must be PAYABLE", 409)
    claim["status"] = "PAID"
    claim["_paid_at_dt"] = store.clock
    mutate_record(claim)
    return success_object(render_claim(claim))


@app.route("/dental/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    require_role("ClaimsExaminer")
    claim = _get_claim_or_404(cid)
    payload = body()
    require_fields(payload, "expected_claim_version")
    expected = payload["expected_claim_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_claim_version must be an integer", 400)
    if claim["status"] not in ("ADJUDICATED", "PAID"):
        raise ApiError(ERR_INVALID_STATE, "Only ADJUDICATED or PAID claims may be voided", 409)
    if claim["status"] == "PAID":
        paid_at = claim.get("_paid_at_dt")
        # paid_at is the claim's updated_at when it transitioned to PAID.
        # We stored the dt on the transition; if missing fall back to updated_at parse.
        if paid_at is None:
            paid_at = parse_iso(claim["updated_at"])
        if store.clock > paid_at + timedelta(days=30):
            raise ApiError(ERR_INVALID_STATE, "Void window (30 days) has elapsed", 409)
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION, "Claim version has advanced", 412)
    # Reverse the accumulator
    from services import plan_year_key
    plan = store.plans[claim["plan_id"]]
    key = plan_year_key(plan, claim["service_date_dt"])
    accumulator = None
    for acc in store.accumulators.values():
        if (acc["subscriber_id"] == claim["subscriber_id"]
                and acc.get("dependent_id") == claim.get("dependent_id")
                and acc["plan_year_key"] == key):
            accumulator = acc
            break
    if accumulator is not None:
        deductible_draw = 0
        max_draw = 0
        for line in store.claim_lines.values():
            if line["claim_id"] != cid:
                continue
            if line["status"] != "PAYABLE":
                continue
            deductible_draw += line.get("deductible_applied_cents", 0)
            max_draw += line.get("plan_pay_cents", 0)
        accumulator["deductible_met_cents"] -= deductible_draw
        accumulator["annual_max_used_cents"] -= max_draw
        mutate_record(accumulator)
    claim["status"] = "VOID"
    mutate_record(claim)
    return success_object(render_claim(claim))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False)
