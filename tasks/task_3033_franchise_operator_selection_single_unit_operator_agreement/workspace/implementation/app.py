#!/usr/bin/env python3
"""Franchise Operator Selection & Single-Unit Operator Agreement API.

Implements the PRD in workspace/PRD.md / SCAFFOLD.yaml. In-memory store; the
store starts empty on every boot. The logical clock starts at exactly
2026-09-01T00:00:00Z until set via POST /franchise/_clock/set_current_utc.
"""

import math
import os
import re
import secrets
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)
lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

CAPITAL_REFERENCE_CENTS = 1000000
SCREENING_PASS_SCORE = 60
MIN_INTERVIEW_ROUNDS = 2
INTERVIEW_PASS_SCORE = 70
PROJECTION_REFERENCE_CENTS = 500000000
ASSESSMENT_PASS_SCORE = 55
LABOR_DOLLAR_PER_HOUR_CENTS = 15000
BRAND_FEE_BPS = 1500
OCCUPANCY_BPS = 800
SHARE_TIER1_CENTS = 50000000
TIER2_DISCOUNT_BPS = 500
APPLICATION_TTL_DAYS = 30
COMMITTEE_QUORUM = 3
MIN_NOTICE_DAYS = 30
SCORECARD_FINALIZE_GRACE_DAYS = 7
INITIAL_COMMITMENT_CENTS = 1000000

W_FOOD_NUM, W_FOOD_DEN = 5, 10
W_SPEED_NUM, W_SPEED_DEN = 3, 10
W_COMMUNITY_NUM, W_COMMUNITY_DEN = 2, 10
RATING_EXCEEDS_MIN = 90
RATING_MEETS_MIN = 70
RATING_BELOW_MIN = 50

ALL_ROLES = {
    "SystemAdmin",
    "Candidate",
    "FieldConsultant",
    "SelectionCommittee",
    "Operator",
    "FinanceAdmin",
}

APPLICATION_PRETERMINAL = {
    "SUBMITTED", "SCREENING", "INTERVIEWS",
    "BUSINESS_ASSESSMENT", "IN_RESTAURANT", "COMMITTEE_REVIEW",
}
APPLICATION_TERMINAL = {"APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED"}
EXIT_NONTERMINAL = {"OPEN", "SUCCESSOR_PENDING", "SUCCESSOR_APPROVED"}
SCORECARD_OVERLAP_STATUSES = {"PUBLISHED", "DISPUTED", "FINAL"}

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.candidates = {}
        self.applications = {}
        self.interview_rounds = {}
        self.assessments = {}
        self.restaurants = {}
        self.experiences = {}
        self.operators = {}
        self.agreements = {}
        self.weeks = {}
        self.scorecards = {}
        self.relocation_requests = {}
        self.exit_cases = {}
        self.statements = {}
        self.committee_votes = {}
        self.clock = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.clock_ever_set = False


store = Store()

# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits)
                            for _ in range(20))


def _wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta():
    return {"api_request_id": _request_id(),
            "api_request_timestamp": _wall_now_iso()}


def ok_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def err_resp(error_id, status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


@app.errorhandler(ApiError)
def _api_error(e):
    return err_resp(e.error_id, e.status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return err_resp("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return err_resp("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return err_resp(e.error_id, e.status, e.message)
    return err_resp("ERR_INVALID_REQUEST", 400, "malformed request")


# ---------------------------------------------------------------------------
# Datetime / math helpers
# ---------------------------------------------------------------------------


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round_half_up_frac(num, den):
    """round_half_up(num/den) for non-negative ints; negative num rounds away."""
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def ceil_div(num, den):
    return -(-num // den)


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------


def new_resource():
    now = fmt_dt(store.clock)
    return {"id": str(uuid.uuid4()), "created_at": now,
            "updated_at": now, "version": 1}


def bump(res):
    res["version"] += 1
    res["updated_at"] = fmt_dt(store.clock)


def get_or_404(table, rid):
    res = table.get(rid)
    if res is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return res


def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be JSON")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be an object")
    return body


def req_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} is required")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} must be a boolean")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} below minimum")
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} must be an ISO8601 timestamp")
    return dt


def parse_limit_offset():
    args = request.args
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset


def list_response(records, filters):
    items = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = parse_limit_offset()
    page = items[offset:offset + limit]
    return ok_list([public(r) for r in page], limit, offset, total)


def public(res):
    return dict(res)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------


def authorize(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "missing or malformed X-User-Role / X-User-ID headers")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "role not permitted for the endpoint")
    return role, uid


def require_self(role, uid, owner_id):
    if owner_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "cannot act on another party's record")


# ---------------------------------------------------------------------------
# Clock + scheduled transitions
# ---------------------------------------------------------------------------


def run_scheduled_transitions():
    """Re-evaluate all automatic logical-clock transitions."""
    now = store.clock

    # Application expiry: SUBMITTED older than APPLICATION_TTL_DAYS.
    for app_rec in list(store.applications.values()):
        if app_rec["stage"] != "SUBMITTED":
            continue
        submitted = parse_dt(app_rec["submitted_at"])
        if submitted is not None and now > submitted + timedelta(days=APPLICATION_TTL_DAYS):
            app_rec["stage"] = "EXPIRED"
            bump(app_rec)
            cand = store.candidates.get(app_rec["candidate_id"])
            if cand and cand["candidate_status"] == "IN_SELECTION":
                cand["candidate_status"] = "REGISTERED"
                cand["active_application_id"] = None
                bump(cand)

    # Experiences: start and shortfall.
    for exp in list(store.experiences.values()):
        starts = parse_dt(exp["starts_on"])
        ends = parse_dt(exp["ends_on"])
        if starts is None or ends is None:
            continue
        if exp["status"] == "SCHEDULED" and now >= starts:
            exp["status"] = "IN_PROGRESS"
            bump(exp)
        if exp["status"] == "IN_PROGRESS" and now >= ends + timedelta(days=1):
            if exp["completed_shift_count"] < exp["required_shift_count"]:
                exp["status"] = "SHORTFALL"
                bump(exp)
                app_rec = store.applications.get(exp["application_id"])
                if app_rec and app_rec["stage"] not in APPLICATION_TERMINAL:
                    app_rec["experience_verdict"] = "FAIL"
                    bump(app_rec)

    # Operating weeks: open at week_start_on.
    for week in list(store.weeks.values()):
        if week["week_status"] != "PLANNED":
            continue
        start = parse_dt(week["week_start_on"])
        if start is not None and now >= start:
            week["week_status"] = "OPEN"
            bump(week)


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


def compute_screening_score(cand, target_market_code):
    capital = min(cand["liquid_capital_cents"], CAPITAL_REFERENCE_CENTS)
    capital_component = capital * 40 // CAPITAL_REFERENCE_CENTS
    if target_market_code == cand["home_market_code"]:
        market_component = 40
    elif cand["relocation_willing"]:
        market_component = 20
    else:
        market_component = 0
    name_component = min(len(cand["legal_name"]), 20)
    return capital_component + market_component + name_component


def recompute_interview_average(app_rec):
    scores = [r["score"] for r in store.interview_rounds.values()
              if r["application_id"] == app_rec["id"] and r["status"] == "SUBMITTED"]
    if scores:
        total = sum(scores)
        n = len(scores)
        app_rec["interview_average"] = round_half_up_frac(total * 100, n) / 100.0
    else:
        app_rec["interview_average"] = None


def compute_rubric_score(assessment):
    plan_len = min(len(assessment["market_plan_text"]), 2000)
    plan_component = plan_len * 50 // 2000
    proj = min(assessment["financial_projection_cents"], PROJECTION_REFERENCE_CENTS)
    projection_component = proj * 50 // PROJECTION_REFERENCE_CENTS
    return plan_component + projection_component


def count_operating_days(starts_on, ends_on):
    """Count dates in [starts_on, ends_on] whose weekday is not Sunday."""
    d = starts_on.date()
    end = ends_on.date()
    count = 0
    while d <= end:
        if d.weekday() != 6:  # Sunday == 6
            count += 1
        d += timedelta(days=1)
    return count


def compute_week_forecast(restaurant):
    closed = [w for w in store.weeks.values()
              if w["restaurant_id"] == restaurant["id"]
              and w["week_status"] == "CLOSED"]
    if closed:
        closed.sort(key=lambda w: w["week_start_on"], reverse=True)
        recent = closed[:4]
        total = sum(w["actual_revenue_cents"] for w in recent)
        forecast = round_half_up_frac(total, len(recent))
    else:
        forecast = round_half_up_frac(restaurant["baseline_weekly_revenue_cents"] * 6, 7)
    labor = ceil_div(forecast, LABOR_DOLLAR_PER_HOUR_CENTS)
    return forecast, labor


def compute_revenue_share(gross, base_share_bps):
    brand_fee = round_half_up_frac(gross * BRAND_FEE_BPS, 10000)
    net_after_fee = gross - brand_fee
    occupancy = round_half_up_frac(net_after_fee * OCCUPANCY_BPS, 10000)
    shareable = net_after_fee - occupancy
    tier1 = min(shareable, SHARE_TIER1_CENTS)
    tier2 = shareable - tier1
    tier1_bps = base_share_bps
    tier2_bps = max(base_share_bps - TIER2_DISCOUNT_BPS, 0)
    share = (round_half_up_frac(tier1 * tier1_bps, 10000)
             + round_half_up_frac(tier2 * tier2_bps, 10000))
    return brand_fee, occupancy, share


def compute_composite(sc):
    value = (sc["food_safety_score"] * W_FOOD_NUM // W_FOOD_DEN
             + sc["service_speed_score"] * W_SPEED_NUM // W_SPEED_DEN
             + sc["community_engagement_score"] * W_COMMUNITY_NUM // W_COMMUNITY_DEN)
    if value >= RATING_EXCEEDS_MIN:
        rating = "EXCEEDS"
    elif value >= RATING_MEETS_MIN:
        rating = "MEETS"
    elif value >= RATING_BELOW_MIN:
        rating = "BELOW"
    else:
        rating = "CRITICAL"
    return value, rating


def issue_statement(operator_id, week, kind):
    """Issue a revenue share statement for (operator, week); returns statement."""
    for st in store.statements.values():
        if (st["operator_id"] == operator_id
                and st["operating_week_id"] == week["id"]):
            raise ApiError("ERR_DUPLICATE_STATEMENT", 409,
                           "a statement already exists for this operator and operating week")
    operator = store.operators[operator_id]
    agreement = store.agreements.get(operator["agreement_id"])
    gross = week["actual_revenue_cents"]
    brand_fee, occupancy, share = compute_revenue_share(gross, agreement["base_share_bps"])
    st = new_resource()
    st.update({
        "operator_id": operator_id,
        "operating_week_id": week["id"],
        "gross_revenue_cents": gross,
        "brand_fee_cents": brand_fee,
        "occupancy_charge_cents": occupancy,
        "operator_share_cents": share,
        "statement_kind": kind,
        "statement_status": "ISSUED",
    })
    store.statements[st["id"]] = st
    return st


def assigned_restaurant_count(operator):
    """Count ASSIGNED restaurants with current_operator_id == operator."""
    return sum(1 for r in store.restaurants.values()
               if r["restaurant_status"] == "ASSIGNED"
               and r["current_operator_id"] == operator["id"])


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.post("/franchise/_clock/set_current_utc")
def set_clock():
    authorize({"SystemAdmin"})
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    with lock:
        store.clock = dt
        store.clock_ever_set = True
        run_scheduled_transitions()
        current = fmt_dt(store.clock)
    return ok_obj({"current_utc": current}, 200)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@app.post("/franchise/candidates")
def create_candidate():
    authorize({"SystemAdmin"})
    body = get_body()
    legal_name = req_string(body, "legal_name")
    email = req_string(body, "email")
    home_market_code = req_string(body, "home_market_code")
    relocation_willing = req_bool(body, "relocation_willing")
    liquid_capital_cents = req_int(body, "liquid_capital_cents", minimum=0)
    with lock:
        for c in store.candidates.values():
            if c["email"] == email:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "email already registered")
        cand = new_resource()
        cand.update({
            "legal_name": legal_name,
            "email": email,
            "home_market_code": home_market_code,
            "relocation_willing": relocation_willing,
            "liquid_capital_cents": liquid_capital_cents,
            "candidate_status": "REGISTERED",
            "active_application_id": None,
        })
        store.candidates[cand["id"]] = cand
    return ok_obj(public(cand), 201)


@app.get("/franchise/candidates/<candidate_id>")
def get_candidate(candidate_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        cand = get_or_404(store.candidates, candidate_id)
        if role == "Candidate":
            require_self(role, uid, cand["id"])
        return ok_obj(public(cand))


@app.get("/franchise/candidates")
def list_candidates():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee"})
    filters = {}
    for key in ("candidate_status", "home_market_code", "active_application_id"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.candidates.values(), filters)


@app.post("/franchise/candidates/<candidate_id>/withdraw")
def withdraw_candidate(candidate_id):
    role, uid = authorize({"Candidate"})
    with lock:
        cand = get_or_404(store.candidates, candidate_id)
        require_self(role, uid, cand["id"])
        if cand["candidate_status"] not in ("REGISTERED", "IN_SELECTION"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "candidate cannot be withdrawn from current status")
        if cand["candidate_status"] == "REGISTERED":
            if cand["active_application_id"] is not None:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "candidate has a live application")
            cand["candidate_status"] = "WITHDRAWN"
            bump(cand)
        else:  # IN_SELECTION
            cand["candidate_status"] = "WITHDRAWN"
            bump(cand)
            app_id = cand["active_application_id"]
            cand["active_application_id"] = None
            if app_id:
                _cascade_application_withdrawal(store.applications[app_id])
        return ok_obj(public(cand))


@app.post("/franchise/candidates/<candidate_id>/disqualify")
def disqualify_candidate(candidate_id):
    authorize({"FieldConsultant"})
    with lock:
        cand = get_or_404(store.candidates, candidate_id)
        if cand["candidate_status"] != "IN_SELECTION":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only IN_SELECTION candidates can be disqualified")
        cand["candidate_status"] = "DISQUALIFIED"
        bump(cand)
        app_id = cand["active_application_id"]
        cand["active_application_id"] = None
        if app_id:
            app_rec = store.applications[app_id]
            app_rec["stage"] = "REJECTED"
            bump(app_rec)
        return ok_obj(public(cand))


def _cascade_application_withdrawal(app_rec):
    """Withdrawal side effects per stage; app assumed pre-terminal."""
    stage = app_rec["stage"]
    app_rec["stage"] = "WITHDRAWN"
    bump(app_rec)
    if stage == "INTERVIEWS":
        for r in store.interview_rounds.values():
            if r["application_id"] == app_rec["id"] and r["status"] == "SCHEDULED":
                r["status"] = "CANCELLED"
        # committee votes are immutable-style; rounds have common fields
        for r in store.interview_rounds.values():
            if r["application_id"] == app_rec["id"]:
                r["updated_at"] = fmt_dt(store.clock)
    elif stage == "IN_RESTAURANT":
        for e in store.experiences.values():
            if (e["application_id"] == app_rec["id"]
                    and e["status"] in ("SCHEDULED", "IN_PROGRESS")):
                e["status"] = "CANCELLED"
                bump(e)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@app.post("/franchise/candidates/<candidate_id>/applications")
def create_application(candidate_id):
    role, uid = authorize({"Candidate"})
    with lock:
        cand = get_or_404(store.candidates, candidate_id)
        require_self(role, uid, cand["id"])
        body = get_body()
        target_market_code = req_string(body, "target_market_code")
        if cand["active_application_id"] is not None:
            raise ApiError("ERR_DUPLICATE_APPLICATION", 409,
                           "candidate already has a non-terminal application")
        if cand["candidate_status"] != "REGISTERED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "candidate is not REGISTERED")
        app_rec = new_resource()
        app_rec.update({
            "candidate_id": cand["id"],
            "target_market_code": target_market_code,
            "stage": "SUBMITTED",
            "screening_score": compute_screening_score(cand, target_market_code),
            "interview_average": None,
            "assessment_verdict": "PENDING",
            "experience_verdict": "PENDING",
            "committee_decision": "NONE",
            "application_fee_cents": None,
            "submitted_at": fmt_dt(store.clock),
        })
        store.applications[app_rec["id"]] = app_rec
        cand["candidate_status"] = "IN_SELECTION"
        cand["active_application_id"] = app_rec["id"]
        bump(cand)
        return ok_obj(public(app_rec), 201)


@app.get("/franchise/applications/<application_id>")
def get_application(application_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        if role == "Candidate":
            require_self(role, uid, app_rec["candidate_id"])
        return ok_obj(public(app_rec))


@app.get("/franchise/applications")
def list_applications():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee"})
    filters = {}
    for key in ("candidate_id", "stage", "target_market_code"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.applications.values(), filters)


@app.post("/franchise/applications/<application_id>/advance")
def advance_application(application_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        stage = app_rec["stage"]
        if stage == "SUBMITTED":
            if app_rec["screening_score"] < SCREENING_PASS_SCORE:
                raise ApiError("ERR_SCREENING_BELOW_THRESHOLD", 422,
                               "screening_score below SCREENING_PASS_SCORE")
            app_rec["stage"] = "SCREENING"
        elif stage == "SCREENING":
            app_rec["stage"] = "INTERVIEWS"
        elif stage == "INTERVIEWS":
            rounds = [r for r in store.interview_rounds.values()
                      if r["application_id"] == app_rec["id"]]
            if (len(rounds) < MIN_INTERVIEW_ROUNDS
                    or any(r["status"] != "SUBMITTED" for r in rounds)
                    or app_rec["interview_average"] is None
                    or app_rec["interview_average"] < INTERVIEW_PASS_SCORE):
                raise ApiError("ERR_INTERVIEW_GATE", 422,
                               "interview gate not satisfied")
            app_rec["stage"] = "BUSINESS_ASSESSMENT"
        elif stage == "BUSINESS_ASSESSMENT":
            assessments = [a for a in store.assessments.values()
                           if a["application_id"] == app_rec["id"]]
            evaluated = [a for a in assessments if a["status"] == "EVALUATED"]
            if not evaluated or app_rec["assessment_verdict"] != "PASS":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "an EVALUATED assessment with PASS verdict is required")
            app_rec["stage"] = "IN_RESTAURANT"
        elif stage == "IN_RESTAURANT":
            experiences = [e for e in store.experiences.values()
                           if e["application_id"] == app_rec["id"]]
            completed = [e for e in experiences if e["status"] == "COMPLETED"]
            if not completed or app_rec["experience_verdict"] != "PASS":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "a COMPLETED experience with PASS verdict is required")
            app_rec["stage"] = "COMMITTEE_REVIEW"
            app_rec["application_fee_cents"] = INITIAL_COMMITMENT_CENTS
        else:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "application cannot be advanced from its current stage")
        bump(app_rec)
        return ok_obj(public(app_rec))


def _bubble_candidate_registered(app_rec):
    cand = store.candidates.get(app_rec["candidate_id"])
    if cand and cand["candidate_status"] == "IN_SELECTION":
        cand["candidate_status"] = "REGISTERED"
        cand["active_application_id"] = None
        bump(cand)


@app.post("/franchise/applications/<application_id>/reject")
def reject_application(application_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        if app_rec["stage"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only SUBMITTED applications can be rejected")
        app_rec["stage"] = "REJECTED"
        bump(app_rec)
        _bubble_candidate_registered(app_rec)
        return ok_obj(public(app_rec))


@app.post("/franchise/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    role, uid = authorize({"Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        require_self(role, uid, app_rec["candidate_id"])
        if app_rec["stage"] not in APPLICATION_PRETERMINAL:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "application cannot be withdrawn from its current stage")
        _cascade_application_withdrawal(app_rec)
        _bubble_candidate_registered(app_rec)
        return ok_obj(public(app_rec))


@app.post("/franchise/applications/<application_id>/committee-decision")
def committee_decision(application_id):
    authorize({"SelectionCommittee"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        body = get_body()
        decision = body.get("decision")
        if decision not in ("APPROVE", "REJECT"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "decision must be APPROVE or REJECT")
        if app_rec["stage"] != "COMMITTEE_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "application is not in COMMITTEE_REVIEW")
        expected = body.get("expected_application_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "expected_application_version must be an integer")
            if expected != app_rec["version"]:
                raise ApiError("ERR_STALE_VERSION", 412,
                               "expected_application_version does not match")
        app_rec["committee_decision"] = decision
        cand = store.candidates.get(app_rec["candidate_id"])
        if decision == "APPROVE":
            app_rec["stage"] = "APPROVED"
            if cand and cand["candidate_status"] == "IN_SELECTION":
                cand["candidate_status"] = "SELECTED"
                cand["active_application_id"] = None
                bump(cand)
        else:
            app_rec["stage"] = "REJECTED"
            if cand and cand["candidate_status"] == "IN_SELECTION":
                cand["candidate_status"] = "REGISTERED"
                cand["active_application_id"] = None
                bump(cand)
        bump(app_rec)
        return ok_obj(public(app_rec))


# ---------------------------------------------------------------------------
# Interview rounds
# ---------------------------------------------------------------------------


@app.post("/franchise/applications/<application_id>/interviews")
def create_interview(application_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        body = get_body()
        interviewer_id = req_string(body, "interviewer_id")
        scheduled_for = req_dt(body, "scheduled_for")
        if app_rec["stage"] != "INTERVIEWS":
            raise ApiError("ERR_STAGE_MISMATCH", 409,
                           "application must be in INTERVIEWS to schedule rounds")
        existing = [r for r in store.interview_rounds.values()
                    if r["application_id"] == app_rec["id"]]
        rnd = new_resource()
        rnd.update({
            "application_id": app_rec["id"],
            "round_index": len(existing) + 1,
            "interviewer_id": interviewer_id,
            "scheduled_for": fmt_dt(scheduled_for),
            "score": None,
            "status": "SCHEDULED",
        })
        store.interview_rounds[rnd["id"]] = rnd
        return ok_obj(public(rnd), 201)


@app.get("/franchise/applications/<application_id>/interviews")
def list_application_interviews(application_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        if role == "Candidate":
            require_self(role, uid, app_rec["candidate_id"])
        return list_response(
            [r for r in store.interview_rounds.values()
             if r["application_id"] == application_id], {})


@app.get("/franchise/interviews")
def list_interviews():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    filters = {}
    for key in ("application_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.interview_rounds.values(), filters)


@app.get("/franchise/interviews/<round_id>")
def get_interview(round_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        rnd = get_or_404(store.interview_rounds, round_id)
        return ok_obj(public(rnd))


@app.post("/franchise/applications/<application_id>/interviews/<round_id>/score")
def score_interview(application_id, round_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        rnd = store.interview_rounds.get(round_id)
        if rnd is None or rnd["application_id"] != application_id:
            raise ApiError("ERR_NOT_FOUND", 404, "interview round not found")
        body = get_body()
        score = body.get("score")
        if isinstance(score, bool) or not isinstance(score, int):
            raise ApiError("ERR_INVALID_REQUEST", 400, "score must be an integer")
        if rnd["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SCHEDULED round can be scored")
        if app_rec["stage"] != "INTERVIEWS":
            raise ApiError("ERR_STAGE_MISMATCH", 409,
                           "application must be in INTERVIEWS to score rounds")
        if score < 0 or score > 100:
            raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                           "score must be between 0 and 100 inclusive")
        rnd["score"] = score
        rnd["status"] = "SUBMITTED"
        bump(rnd)
        recompute_interview_average(app_rec)
        bump(app_rec)
        return ok_obj(public(rnd))


@app.post("/franchise/applications/<application_id>/interviews/<round_id>/cancel")
def cancel_interview(application_id, round_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        rnd = store.interview_rounds.get(round_id)
        if rnd is None or rnd["application_id"] != application_id:
            raise ApiError("ERR_NOT_FOUND", 404, "interview round not found")
        if rnd["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SCHEDULED round can be cancelled")
        rnd["status"] = "CANCELLED"
        bump(rnd)
        recompute_interview_average(app_rec)
        bump(app_rec)
        return ok_obj(public(rnd))


# ---------------------------------------------------------------------------
# Business assessments
# ---------------------------------------------------------------------------


@app.post("/franchise/applications/<application_id>/assessment")
def create_assessment(application_id):
    role, uid = authorize({"Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        require_self(role, uid, app_rec["candidate_id"])
        body = get_body()
        market_plan_text = body.get("market_plan_text")
        if not isinstance(market_plan_text, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "market_plan_text must be a string")
        financial_projection_cents = req_int(body, "financial_projection_cents",
                                             minimum=1)
        if app_rec["stage"] != "BUSINESS_ASSESSMENT":
            raise ApiError("ERR_STAGE_MISMATCH", 409,
                           "application must be in BUSINESS_ASSESSMENT")
        assessment = new_resource()
        assessment.update({
            "application_id": app_rec["id"],
            "market_plan_text": market_plan_text,
            "financial_projection_cents": financial_projection_cents,
            "rubric_score": None,
            "status": "DRAFT",
        })
        store.assessments[assessment["id"]] = assessment
        return ok_obj(public(assessment), 201)


@app.get("/franchise/applications/<application_id>/assessment")
def get_application_assessment(application_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        if role == "Candidate":
            require_self(role, uid, app_rec["candidate_id"])
        return list_response(
            [a for a in store.assessments.values()
             if a["application_id"] == application_id], {})


@app.get("/franchise/assessments")
def list_assessments():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    filters = {}
    for key in ("application_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.assessments.values(), filters)


@app.get("/franchise/assessments/<assessment_id>")
def get_assessment(assessment_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        assessment = get_or_404(store.assessments, assessment_id)
        return ok_obj(public(assessment))


def _sole_assessment(app_id):
    items = [a for a in store.assessments.values() if a["application_id"] == app_id]
    if not items:
        raise ApiError("ERR_NOT_FOUND", 404, "assessment not found")
    return items[0]


@app.post("/franchise/applications/<application_id>/assessment/submit")
def submit_assessment(application_id):
    role, uid = authorize({"Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        require_self(role, uid, app_rec["candidate_id"])
        assessment = _sole_assessment(application_id)
        if assessment["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a DRAFT assessment can be submitted")
        if app_rec["stage"] != "BUSINESS_ASSESSMENT":
            raise ApiError("ERR_STAGE_MISMATCH", 409,
                           "application must be in BUSINESS_ASSESSMENT")
        if not assessment["market_plan_text"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "market_plan_text must be non-empty")
        if assessment["financial_projection_cents"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "financial_projection_cents must be positive")
        assessment["status"] = "SUBMITTED"
        bump(assessment)
        return ok_obj(public(assessment))


@app.post("/franchise/applications/<application_id>/assessment/evaluate")
def evaluate_assessment(application_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        assessment = _sole_assessment(application_id)
        if assessment["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SUBMITTED assessment can be evaluated")
        assessment["rubric_score"] = compute_rubric_score(assessment)
        assessment["status"] = "EVALUATED"
        bump(assessment)
        app_rec["assessment_verdict"] = (
            "PASS" if assessment["rubric_score"] >= ASSESSMENT_PASS_SCORE else "FAIL")
        bump(app_rec)
        return ok_obj(public(assessment))


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------


@app.post("/franchise/restaurants")
def create_restaurant():
    authorize({"SystemAdmin"})
    body = get_body()
    site_code = req_string(body, "site_code")
    market_code = req_string(body, "market_code")
    baseline = req_int(body, "baseline_weekly_revenue_cents", minimum=1)
    equipment = req_int(body, "equipment_value_cents", minimum=0)
    with lock:
        for r in store.restaurants.values():
            if r["site_code"] == site_code:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "site_code already registered")
        rest = new_resource()
        rest.update({
            "site_code": site_code,
            "market_code": market_code,
            "baseline_weekly_revenue_cents": baseline,
            "restaurant_status": "PIPELINE",
            "current_operator_id": None,
            "equipment_value_cents": equipment,
            "sunday_closed": True,
        })
        store.restaurants[rest["id"]] = rest
        return ok_obj(public(rest), 201)


@app.get("/franchise/restaurants/<restaurant_id>")
def get_restaurant(restaurant_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        rest = get_or_404(store.restaurants, restaurant_id)
        return ok_obj(public(rest))


@app.get("/franchise/restaurants")
def list_restaurants():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee"})
    filters = {}
    for key in ("market_code", "restaurant_status", "current_operator_id"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.restaurants.values(), filters)


@app.post("/franchise/restaurants/<restaurant_id>/make-available")
def make_restaurant_available(restaurant_id):
    authorize({"SystemAdmin"})
    with lock:
        rest = get_or_404(store.restaurants, restaurant_id)
        if rest["restaurant_status"] != "PIPELINE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a PIPELINE restaurant can be made available")
        rest["restaurant_status"] = "AVAILABLE"
        bump(rest)
        return ok_obj(public(rest))


# ---------------------------------------------------------------------------
# In-restaurant experiences
# ---------------------------------------------------------------------------


@app.post("/franchise/applications/<application_id>/experiences")
def create_experience(application_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        body = get_body()
        host_restaurant_id = req_string(body, "host_restaurant_id")
        starts_on = req_dt(body, "starts_on")
        ends_on = req_dt(body, "ends_on")
        if app_rec["stage"] != "IN_RESTAURANT":
            raise ApiError("ERR_STAGE_MISMATCH", 409,
                           "application must be in IN_RESTAURANT")
        get_or_404(store.restaurants, host_restaurant_id)
        if ends_on < starts_on:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "ends_on must not precede starts_on")
        required = count_operating_days(starts_on, ends_on)
        if required == 0:
            raise ApiError("ERR_NO_OPERATING_DAYS", 422,
                           "experience block contains no non-Sunday operating day")
        exp = new_resource()
        exp.update({
            "application_id": app_rec["id"],
            "host_restaurant_id": host_restaurant_id,
            "starts_on": fmt_dt(starts_on),
            "ends_on": fmt_dt(ends_on),
            "required_shift_count": required,
            "completed_shift_count": 0,
            "status": "SCHEDULED",
        })
        store.experiences[exp["id"]] = exp
        return ok_obj(public(exp), 201)


@app.get("/franchise/applications/<application_id>/experiences")
def list_application_experiences(application_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        app_rec = get_or_404(store.applications, application_id)
        if role == "Candidate":
            require_self(role, uid, app_rec["candidate_id"])
        return list_response(
            [e for e in store.experiences.values()
             if e["application_id"] == application_id], {})


@app.get("/franchise/experiences")
def list_experiences():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    filters = {}
    for key in ("application_id", "host_restaurant_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.experiences.values(), filters)


@app.get("/franchise/experiences/<experience_id>")
def get_experience(experience_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Candidate"})
    with lock:
        exp = get_or_404(store.experiences, experience_id)
        return ok_obj(public(exp))


def _get_experience_scoped(application_id, experience_id):
    app_rec = get_or_404(store.applications, application_id)
    exp = store.experiences.get(experience_id)
    if exp is None or exp["application_id"] != application_id:
        raise ApiError("ERR_NOT_FOUND", 404, "experience not found")
    return app_rec, exp


@app.post("/franchise/applications/<application_id>/experiences/<experience_id>/signoff")
def signoff_experience(application_id, experience_id):
    authorize({"FieldConsultant"})
    with lock:
        _, exp = _get_experience_scoped(application_id, experience_id)
        if exp["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an IN_PROGRESS experience accepts sign-offs")
        if exp["completed_shift_count"] < exp["required_shift_count"]:
            exp["completed_shift_count"] += 1
        bump(exp)
        return ok_obj(public(exp))


@app.post("/franchise/applications/<application_id>/experiences/<experience_id>/complete")
def complete_experience(application_id, experience_id):
    authorize({"FieldConsultant"})
    with lock:
        app_rec, exp = _get_experience_scoped(application_id, experience_id)
        if exp["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an IN_PROGRESS experience can be completed")
        if exp["completed_shift_count"] < exp["required_shift_count"]:
            raise ApiError("ERR_SHIFT_SHORTFALL", 409,
                           "completed_shift_count below required_shift_count")
        exp["status"] = "COMPLETED"
        bump(exp)
        app_rec["experience_verdict"] = "PASS"
        bump(app_rec)
        return ok_obj(public(exp))


@app.post("/franchise/applications/<application_id>/experiences/<experience_id>/cancel")
def cancel_experience(application_id, experience_id):
    authorize({"FieldConsultant"})
    with lock:
        _, exp = _get_experience_scoped(application_id, experience_id)
        if exp["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SCHEDULED experience can be cancelled")
        exp["status"] = "CANCELLED"
        bump(exp)
        return ok_obj(public(exp))


# ---------------------------------------------------------------------------
# Operators & agreements
# ---------------------------------------------------------------------------


@app.post("/franchise/operators")
def create_operator():
    authorize({"SelectionCommittee"})
    body = get_body()
    candidate_id = req_string(body, "candidate_id")
    restaurant_id = req_string(body, "restaurant_id")
    base_share_bps = req_int(body, "base_share_bps", minimum=0)
    effective_from = req_dt(body, "effective_from")
    with lock:
        cand = get_or_404(store.candidates, candidate_id)
        rest = get_or_404(store.restaurants, restaurant_id)
        if cand["candidate_status"] != "SELECTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "candidate must be SELECTED")
        for op in store.operators.values():
            if op["candidate_id"] == candidate_id:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "candidate already has an operator record")
        if rest["restaurant_status"] != "AVAILABLE":
            raise ApiError("ERR_RESTAURANT_NOT_AVAILABLE", 409,
                           "restaurant is not AVAILABLE for assignment")
        if effective_from < store.clock:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "effective_from must not be in the past")
        operator = new_resource()
        agreement = new_resource()
        agreement.update({
            "operator_id": operator["id"],
            "restaurant_id": rest["id"],
            "transferable": False,
            "equity_stake_bps": 0,
            "base_share_bps": base_share_bps,
            "agreement_status": "DRAFT",
            "effective_from": fmt_dt(effective_from),
        })
        store.agreements[agreement["id"]] = agreement
        operator.update({
            "candidate_id": cand["id"],
            "agreement_id": agreement["id"],
            "restaurant_id": rest["id"],
            "operator_status": "ONBOARDING",
            "residency_verified": False,
            "full_time_attested": False,
            "lifetime_revenue_share_cents": 0,
        })
        store.operators[operator["id"]] = operator
        return ok_obj(public(operator), 201)


@app.get("/franchise/operators/<operator_id>")
def get_operator(operator_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        if role == "Operator":
            require_self(role, uid, op["id"])
        return ok_obj(public(op))


@app.get("/franchise/operators")
def list_operators():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee"})
    filters = {}
    for key in ("operator_status", "restaurant_id", "candidate_id", "agreement_id"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.operators.values(), filters)


@app.post("/franchise/operators/<operator_id>/attest")
def attest_operator(operator_id):
    role, uid = authorize({"Operator"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        require_self(role, uid, op["id"])
        body = get_body()
        residency = req_bool(body, "residency_verified")
        full_time = req_bool(body, "full_time_attested")
        if op["operator_status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "operator cannot attest in its current status")
        op["residency_verified"] = residency
        op["full_time_attested"] = full_time
        bump(op)
        return ok_obj(public(op))


@app.post("/franchise/operators/<operator_id>/agreement/execute")
def execute_agreement(operator_id):
    authorize({"SelectionCommittee"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        agreement = store.agreements.get(op["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_NOT_FOUND", 404, "agreement not found")
        body = get_body()
        if body.get("transferable") is True or (
                isinstance(body.get("equity_stake_bps"), int)
                and not isinstance(body.get("equity_stake_bps"), bool)
                and body.get("equity_stake_bps") != 0):
            raise ApiError("ERR_AGREEMENT_IMMUTABLE", 422,
                           "agreements are non-transferable and carry no equity")
        if agreement["agreement_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a DRAFT agreement can be executed")
        if op["operator_status"] != "ONBOARDING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "operator must be ONBOARDING")
        effective = parse_dt(agreement["effective_from"])
        if effective is not None and effective < store.clock:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "agreement effective_from is in the past")
        rest = store.restaurants.get(agreement["restaurant_id"])
        if rest is None or rest["restaurant_status"] != "AVAILABLE":
            raise ApiError("ERR_RESTAURANT_NOT_AVAILABLE", 409,
                           "restaurant is not AVAILABLE for assignment")
        agreement["agreement_status"] = "EXECUTED"
        bump(agreement)
        rest["restaurant_status"] = "ASSIGNED"
        rest["current_operator_id"] = op["id"]
        bump(rest)
        return ok_obj(public(agreement))


@app.get("/franchise/operators/<operator_id>/agreement")
def get_operator_agreement(operator_id):
    role, uid = authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        if role == "Operator":
            require_self(role, uid, op["id"])
        return list_response(
            [a for a in store.agreements.values()
             if a["operator_id"] == operator_id], {})


@app.get("/franchise/agreements")
def list_agreements():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    filters = {}
    for key in ("operator_id", "restaurant_id", "agreement_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.agreements.values(), filters)


@app.get("/franchise/agreements/<agreement_id>")
def get_agreement(agreement_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        agreement = get_or_404(store.agreements, agreement_id)
        return ok_obj(public(agreement))


@app.post("/franchise/operators/<operator_id>/activate")
def activate_operator(operator_id):
    authorize({"FieldConsultant"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        if op["operator_status"] != "ONBOARDING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an ONBOARDING operator can be activated")
        if not (op["residency_verified"] and op["full_time_attested"]):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "residency and full-time attestation required")
        agreement = store.agreements.get(op["agreement_id"])
        if agreement is None or agreement["agreement_status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "agreement must be EXECUTED")
        rest = store.restaurants.get(op["restaurant_id"])
        if (rest is None or rest["restaurant_status"] != "ASSIGNED"
                or rest["current_operator_id"] != op["id"]):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "restaurant must be ASSIGNED to this operator")
        op["operator_status"] = "ACTIVE"
        bump(op)
        return ok_obj(public(op))


@app.post("/franchise/operators/<operator_id>/suspend")
def suspend_operator(operator_id):
    authorize({"FieldConsultant"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        if op["operator_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an ACTIVE operator can be suspended")
        _suspend_operator(op)
        return ok_obj(public(op))


def _suspend_operator(op):
    op["operator_status"] = "SUSPENDED"
    bump(op)
    agreement = store.agreements.get(op["agreement_id"])
    if agreement and agreement["agreement_status"] == "EXECUTED":
        agreement["agreement_status"] = "SUSPENDED"
        bump(agreement)


@app.post("/franchise/operators/<operator_id>/reinstate")
def reinstate_operator(operator_id):
    authorize({"FieldConsultant"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        if op["operator_status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SUSPENDED operator can be reinstated")
        if not op["residency_verified"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "residency must be verified to reinstate")
        op["operator_status"] = "ACTIVE"
        bump(op)
        agreement = store.agreements.get(op["agreement_id"])
        if agreement and agreement["agreement_status"] == "SUSPENDED":
            agreement["agreement_status"] = "EXECUTED"
            bump(agreement)
        return ok_obj(public(op))


# ---------------------------------------------------------------------------
# Operating weeks
# ---------------------------------------------------------------------------


@app.post("/franchise/restaurants/<restaurant_id>/weeks")
def create_week(restaurant_id):
    authorize({"FieldConsultant"})
    with lock:
        rest = get_or_404(store.restaurants, restaurant_id)
        body = get_body()
        week_start_on = req_dt(body, "week_start_on")
        week_start_iso = fmt_dt(week_start_on)
        for w in store.weeks.values():
            if (w["restaurant_id"] == restaurant_id
                    and w["week_start_on"] == week_start_iso):
                raise ApiError("ERR_DUPLICATE_WEEK", 409,
                               "an OperatingWeek already exists for this week_start_on")
        forecast, labor = compute_week_forecast(rest)
        week = new_resource()
        week.update({
            "restaurant_id": restaurant_id,
            "week_start_on": week_start_iso,
            "operating_day_count": 6,
            "forecast_revenue_cents": forecast,
            "planned_labor_hours": labor,
            "actual_revenue_cents": None,
            "week_status": "PLANNED",
        })
        store.weeks[week["id"]] = week
        return ok_obj(public(week), 201)


@app.get("/franchise/restaurants/<restaurant_id>/weeks")
def list_restaurant_weeks(restaurant_id):
    authorize({"SystemAdmin", "FieldConsultant", "Operator"})
    with lock:
        get_or_404(store.restaurants, restaurant_id)
        filters = {}
        v = request.args.get("week_status")
        if v is not None:
            filters["week_status"] = v
        return list_response(
            [w for w in store.weeks.values()
             if w["restaurant_id"] == restaurant_id], filters)


@app.get("/franchise/weeks")
def list_weeks():
    authorize({"SystemAdmin", "FieldConsultant", "Operator"})
    filters = {}
    for key in ("restaurant_id", "week_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.weeks.values(), filters)


@app.get("/franchise/weeks/<week_id>")
def get_week(week_id):
    authorize({"SystemAdmin", "FieldConsultant", "Operator"})
    with lock:
        week = get_or_404(store.weeks, week_id)
        return ok_obj(public(week))


@app.post("/franchise/restaurants/<restaurant_id>/weeks/<week_id>/close")
def close_week(restaurant_id, week_id):
    authorize({"FieldConsultant"})
    with lock:
        rest = get_or_404(store.restaurants, restaurant_id)
        week = store.weeks.get(week_id)
        if week is None or week["restaurant_id"] != restaurant_id:
            raise ApiError("ERR_NOT_FOUND", 404, "week not found")
        if week["week_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an OPEN week can be closed")
        body = get_body()
        actual = body.get("actual_revenue_cents")
        if actual is None:
            raise ApiError("ERR_MISSING_ACTUALS", 400,
                           "actual_revenue_cents is required")
        if isinstance(actual, bool) or not isinstance(actual, int) or actual < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "actual_revenue_cents must be a non-negative integer")
        start = parse_dt(week["week_start_on"])
        if start is None or store.clock < start + timedelta(days=6):
            raise ApiError("ERR_WEEK_NOT_ELAPSED", 409,
                           "the six operating days have not elapsed")
        expected = body.get("expected_week_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "expected_week_version must be an integer")
            if expected != week["version"]:
                raise ApiError("ERR_STALE_VERSION", 412,
                               "expected_week_version does not match")
        week["actual_revenue_cents"] = actual
        week["week_status"] = "CLOSED"
        bump(week)
        if rest["current_operator_id"]:
            issue_statement(rest["current_operator_id"], week, "PROVISIONAL")
        return ok_obj(public(week))


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------


@app.post("/franchise/operators/<operator_id>/scorecards")
def create_scorecard(operator_id):
    authorize({"FieldConsultant"})
    with lock:
        get_or_404(store.operators, operator_id)
        body = get_body()
        period_start = req_dt(body, "period_start_on")
        period_end = req_dt(body, "period_end_on")
        food = req_int(body, "food_safety_score")
        speed = req_int(body, "service_speed_score")
        community = req_int(body, "community_engagement_score")
        for name, v in (("food_safety_score", food),
                        ("service_speed_score", speed),
                        ("community_engagement_score", community)):
            if v < 0 or v > 100:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               f"{name} must be between 0 and 100")
        sc = new_resource()
        sc.update({
            "operator_id": operator_id,
            "period_start_on": fmt_dt(period_start),
            "period_end_on": fmt_dt(period_end),
            "food_safety_score": food,
            "service_speed_score": speed,
            "community_engagement_score": community,
            "composite_score": None,
            "rating": None,
            "scorecard_status": "DRAFT",
        })
        store.scorecards[sc["id"]] = sc
        return ok_obj(public(sc), 201)


@app.get("/franchise/operators/<operator_id>/scorecards")
def list_operator_scorecards(operator_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        get_or_404(store.operators, operator_id)
        filters = {}
        v = request.args.get("scorecard_status")
        if v is not None:
            filters["scorecard_status"] = v
        return list_response(
            [s for s in store.scorecards.values()
             if s["operator_id"] == operator_id], filters)


@app.get("/franchise/scorecards")
def list_scorecards():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    filters = {}
    for key in ("operator_id", "scorecard_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.scorecards.values(), filters)


@app.get("/franchise/scorecards/<scorecard_id>")
def get_scorecard(scorecard_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        sc = get_or_404(store.scorecards, scorecard_id)
        return ok_obj(public(sc))


def _get_scorecard_scoped(operator_id, scorecard_id):
    op = get_or_404(store.operators, operator_id)
    sc = store.scorecards.get(scorecard_id)
    if sc is None or sc["operator_id"] != operator_id:
        raise ApiError("ERR_NOT_FOUND", 404, "scorecard not found")
    return op, sc


def _periods_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end + 1 day) overlap."""
    a_lo = parse_dt(a_start)
    a_hi = parse_dt(a_end) + timedelta(days=1)
    b_lo = parse_dt(b_start)
    b_hi = parse_dt(b_end) + timedelta(days=1)
    return a_lo < b_hi and b_lo < a_hi


@app.post("/franchise/operators/<operator_id>/scorecards/<scorecard_id>/publish")
def publish_scorecard(operator_id, scorecard_id):
    authorize({"FieldConsultant"})
    with lock:
        op, sc = _get_scorecard_scoped(operator_id, scorecard_id)
        if sc["scorecard_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a DRAFT scorecard can be published")
        if op["operator_status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_OPERATOR_NOT_SCORABLE", 409,
                           "operator must be ACTIVE or SUSPENDED to publish")
        for other in store.scorecards.values():
            if (other["operator_id"] == operator_id
                    and other["id"] != sc["id"]
                    and other["scorecard_status"] in SCORECARD_OVERLAP_STATUSES
                    and _periods_overlap(sc["period_start_on"], sc["period_end_on"],
                                         other["period_start_on"], other["period_end_on"])):
                raise ApiError("ERR_SCORECARD_OVERLAP", 409,
                               "scorecard period overlaps an existing scorecard")
        composite, rating = compute_composite(sc)
        sc["composite_score"] = composite
        sc["rating"] = rating
        sc["scorecard_status"] = "PUBLISHED"
        bump(sc)
        if rating == "CRITICAL" and op["operator_status"] == "ACTIVE":
            _suspend_operator(op)
        return ok_obj(public(sc))


@app.post("/franchise/operators/<operator_id>/scorecards/<scorecard_id>/dispute")
def dispute_scorecard(operator_id, scorecard_id):
    role, uid = authorize({"Operator"})
    with lock:
        op, sc = _get_scorecard_scoped(operator_id, scorecard_id)
        require_self(role, uid, op["id"])
        if sc["scorecard_status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a PUBLISHED scorecard can be disputed")
        sc["scorecard_status"] = "DISPUTED"
        bump(sc)
        return ok_obj(public(sc))


@app.post("/franchise/operators/<operator_id>/scorecards/<scorecard_id>/republish")
def republish_scorecard(operator_id, scorecard_id):
    authorize({"FieldConsultant"})
    with lock:
        op, sc = _get_scorecard_scoped(operator_id, scorecard_id)
        if sc["scorecard_status"] != "DISPUTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a DISPUTED scorecard can be republished")
        composite, rating = compute_composite(sc)
        sc["composite_score"] = composite
        sc["rating"] = rating
        sc["scorecard_status"] = "PUBLISHED"
        bump(sc)
        return ok_obj(public(sc))


@app.post("/franchise/operators/<operator_id>/scorecards/<scorecard_id>/finalize")
def finalize_scorecard(operator_id, scorecard_id):
    authorize({"FieldConsultant"})
    with lock:
        _, sc = _get_scorecard_scoped(operator_id, scorecard_id)
        if sc["scorecard_status"] not in ("PUBLISHED", "DISPUTED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a PUBLISHED or DISPUTED scorecard can be finalized")
        period_end = parse_dt(sc["period_end_on"])
        if (period_end is None or store.clock < period_end
                + timedelta(days=SCORECARD_FINALIZE_GRACE_DAYS)):
            raise ApiError("ERR_FINALIZE_TOO_EARLY", 409,
                           "grace period has not elapsed")
        sc["scorecard_status"] = "FINAL"
        bump(sc)
        return ok_obj(public(sc))


# ---------------------------------------------------------------------------
# Relocation requests & committee votes
# ---------------------------------------------------------------------------


@app.post("/franchise/operators/<operator_id>/relocation-requests")
def create_relocation_request(operator_id):
    role, uid = authorize({"Operator"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        require_self(role, uid, op["id"])
        body = get_body()
        kind = body.get("kind")
        if kind not in ("RELOCATION", "SECOND_LOCATION"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "kind must be RELOCATION or SECOND_LOCATION")
        target_restaurant_id = req_string(body, "target_restaurant_id")
        reason_text = req_string(body, "reason_text")
        get_or_404(store.restaurants, target_restaurant_id)
        rr = new_resource()
        rr.update({
            "operator_id": operator_id,
            "kind": kind,
            "target_restaurant_id": target_restaurant_id,
            "reason_text": reason_text,
            "request_status": "SUBMITTED",
            "votes_for": 0,
            "votes_against": 0,
        })
        store.relocation_requests[rr["id"]] = rr
        return ok_obj(public(rr), 201)


@app.get("/franchise/operators/<operator_id>/relocation-requests")
def list_operator_relocations(operator_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        get_or_404(store.operators, operator_id)
        return list_response(
            [r for r in store.relocation_requests.values()
             if r["operator_id"] == operator_id], {})


@app.get("/franchise/relocation-requests")
def list_relocations():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    filters = {}
    for key in ("operator_id", "target_restaurant_id", "request_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.relocation_requests.values(), filters)


@app.get("/franchise/relocation-requests/<request_id>")
def get_relocation(request_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        rr = get_or_404(store.relocation_requests, request_id)
        return ok_obj(public(rr))


def _get_relocation_scoped(operator_id, request_id):
    op = get_or_404(store.operators, operator_id)
    rr = store.relocation_requests.get(request_id)
    if rr is None or rr["operator_id"] != operator_id:
        raise ApiError("ERR_NOT_FOUND", 404, "relocation request not found")
    return op, rr


@app.post("/franchise/operators/<operator_id>/relocation-requests/<request_id>/open-review")
def open_relocation_review(operator_id, request_id):
    authorize({"SelectionCommittee"})
    with lock:
        op, rr = _get_relocation_scoped(operator_id, request_id)
        if rr["request_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SUBMITTED request can enter committee review")
        if op["operator_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "operator must be ACTIVE")
        target = store.restaurants.get(rr["target_restaurant_id"])
        if target is None or target["restaurant_status"] != "AVAILABLE":
            raise ApiError("ERR_RESTAURANT_NOT_AVAILABLE", 409,
                           "target restaurant is not AVAILABLE")
        rr["request_status"] = "COMMITTEE_REVIEW"
        bump(rr)
        return ok_obj(public(rr))


@app.post("/franchise/operators/<operator_id>/relocation-requests/<request_id>/votes")
def cast_vote(operator_id, request_id):
    authorize({"SelectionCommittee"})
    with lock:
        _, rr = _get_relocation_scoped(operator_id, request_id)
        body = get_body()
        member_id = req_string(body, "committee_member_id")
        vote = body.get("vote")
        if vote not in ("FOR", "AGAINST"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "vote must be FOR or AGAINST")
        if rr["request_status"] != "COMMITTEE_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "request is not in COMMITTEE_REVIEW")
        for v in store.committee_votes.values():
            if (v["relocation_request_id"] == request_id
                    and v["committee_member_id"] == member_id):
                raise ApiError("ERR_DUPLICATE_VOTE", 409,
                               "committee member has already voted on this request")
        ballot = {
            "id": str(uuid.uuid4()),
            "created_at": fmt_dt(store.clock),
            "relocation_request_id": request_id,
            "committee_member_id": member_id,
            "vote": vote,
            "cast_at": fmt_dt(store.clock),
        }
        store.committee_votes[ballot["id"]] = ballot
        if vote == "FOR":
            rr["votes_for"] += 1
        else:
            rr["votes_against"] += 1
        bump(rr)
        return ok_obj(dict(ballot), 201)


@app.get("/franchise/relocation-requests/<request_id>/votes")
def list_request_votes(request_id):
    authorize({"SystemAdmin", "SelectionCommittee"})
    with lock:
        get_or_404(store.relocation_requests, request_id)
        return list_response(
            [v for v in store.committee_votes.values()
             if v["relocation_request_id"] == request_id], {})


@app.get("/franchise/committee-votes")
def list_committee_votes():
    authorize({"SystemAdmin", "SelectionCommittee"})
    filters = {}
    for key in ("relocation_request_id", "committee_member_id"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.committee_votes.values(), filters)


@app.get("/franchise/committee-votes/<vote_id>")
def get_committee_vote(vote_id):
    authorize({"SystemAdmin", "SelectionCommittee"})
    with lock:
        ballot = get_or_404(store.committee_votes, vote_id)
        return ok_obj(public(ballot))


@app.post("/franchise/operators/<operator_id>/relocation-requests/<request_id>/decide")
def decide_relocation(operator_id, request_id):
    authorize({"SelectionCommittee"})
    with lock:
        op, rr = _get_relocation_scoped(operator_id, request_id)
        if rr["request_status"] != "COMMITTEE_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "request is not in COMMITTEE_REVIEW")
        votes_for = rr["votes_for"]
        votes_against = rr["votes_against"]
        if votes_for >= COMMITTEE_QUORUM and votes_for > votes_against:
            decision = "APPROVED"
        elif votes_against >= COMMITTEE_QUORUM or votes_for <= votes_against:
            decision = "DENIED"
        else:
            raise ApiError("ERR_QUORUM_NOT_MET", 409,
                           "neither side has reached quorum")
        if decision == "APPROVED":
            target = store.restaurants.get(rr["target_restaurant_id"])
            if target is None or target["restaurant_status"] != "AVAILABLE":
                raise ApiError("ERR_RESTAURANT_NOT_AVAILABLE", 409,
                               "target restaurant is not AVAILABLE")
            if rr["kind"] == "RELOCATION":
                source = store.restaurants.get(op["restaurant_id"])
                if source is not None:
                    source["restaurant_status"] = "AVAILABLE"
                    source["current_operator_id"] = None
                    bump(source)
                op["restaurant_id"] = target["id"]
                bump(op)
                target["restaurant_status"] = "ASSIGNED"
                target["current_operator_id"] = op["id"]
                bump(target)
            else:  # SECOND_LOCATION
                if assigned_restaurant_count(op) != 1:
                    raise ApiError("ERR_SINGLE_UNIT_VIOLATION", 422,
                                   "second location requires exactly one current restaurant")
                target["restaurant_status"] = "ASSIGNED"
                target["current_operator_id"] = op["id"]
                bump(target)
        rr["request_status"] = decision
        bump(rr)
        return ok_obj(public(rr))


@app.post("/franchise/operators/<operator_id>/relocation-requests/<request_id>/withdraw")
def withdraw_relocation(operator_id, request_id):
    role, uid = authorize({"Operator"})
    with lock:
        op, rr = _get_relocation_scoped(operator_id, request_id)
        require_self(role, uid, op["id"])
        if rr["request_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a SUBMITTED request can be withdrawn")
        rr["request_status"] = "WITHDRAWN"
        bump(rr)
        return ok_obj(public(rr))


# ---------------------------------------------------------------------------
# Exit cases
# ---------------------------------------------------------------------------


@app.post("/franchise/operators/<operator_id>/exits")
def create_exit(operator_id):
    role, uid = authorize({"Operator"})
    with lock:
        op = get_or_404(store.operators, operator_id)
        require_self(role, uid, op["id"])
        body = get_body()
        reason = body.get("reason")
        if reason not in ("VOLUNTARY", "INVOLUNTARY", "NON_RENEWAL"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "reason must be VOLUNTARY, INVOLUNTARY, or NON_RENEWAL")
        effective_on = req_dt(body, "effective_on")
        for ex in store.exit_cases.values():
            if (ex["operator_id"] == operator_id
                    and ex["exit_status"] in EXIT_NONTERMINAL):
                raise ApiError("ERR_EXIT_ALREADY_OPEN", 409,
                               "operator already has a non-terminal exit case")
        if op["operator_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an ACTIVE operator can open an exit case")
        notice = store.clock
        if effective_on < notice + timedelta(days=MIN_NOTICE_DAYS):
            raise ApiError("ERR_NOTICE_TOO_SHORT", 422,
                           "effective_on earlier than notice date + MIN_NOTICE_DAYS")
        ex = new_resource()
        ex.update({
            "operator_id": operator_id,
            "reason": reason,
            "notice_given_on": fmt_dt(notice),
            "effective_on": fmt_dt(effective_on),
            "successor_candidate_id": None,
            "final_statement_id": None,
            "exit_status": "OPEN",
        })
        store.exit_cases[ex["id"]] = ex
        op["operator_status"] = "EXITING"
        bump(op)
        return ok_obj(public(ex), 201)


@app.get("/franchise/operators/<operator_id>/exits")
def list_operator_exits(operator_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        get_or_404(store.operators, operator_id)
        return list_response(
            [e for e in store.exit_cases.values()
             if e["operator_id"] == operator_id], {})


@app.get("/franchise/exits")
def list_exits():
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    filters = {}
    for key in ("operator_id", "successor_candidate_id", "final_statement_id",
                "exit_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.exit_cases.values(), filters)


@app.get("/franchise/exits/<exit_id>")
def get_exit(exit_id):
    authorize({"SystemAdmin", "FieldConsultant", "SelectionCommittee", "Operator"})
    with lock:
        ex = get_or_404(store.exit_cases, exit_id)
        return ok_obj(public(ex))


def _get_exit_scoped(operator_id, exit_id):
    op = get_or_404(store.operators, operator_id)
    ex = store.exit_cases.get(exit_id)
    if ex is None or ex["operator_id"] != operator_id:
        raise ApiError("ERR_NOT_FOUND", 404, "exit case not found")
    return op, ex


@app.post("/franchise/operators/<operator_id>/exits/<exit_id>/propose-successor")
def propose_successor(operator_id, exit_id):
    authorize({"FieldConsultant"})
    with lock:
        op, ex = _get_exit_scoped(operator_id, exit_id)
        body = get_body()
        successor_id = req_string(body, "successor_candidate_id")
        if ex["exit_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an OPEN exit case accepts a successor proposal")
        cand = get_or_404(store.candidates, successor_id)
        eligible = False
        if cand["candidate_status"] == "SELECTED":
            rest = store.restaurants.get(op["restaurant_id"])
            for app_rec in store.applications.values():
                if (app_rec["candidate_id"] == cand["id"]
                        and app_rec["stage"] == "APPROVED"
                        and rest is not None
                        and app_rec["target_market_code"] == rest["market_code"]):
                    eligible = True
                    break
        if not eligible:
            raise ApiError("ERR_SUCCESSOR_INELIGIBLE", 422,
                           "successor must be SELECTED for this restaurant's market")
        ex["successor_candidate_id"] = successor_id
        ex["exit_status"] = "SUCCESSOR_PENDING"
        bump(ex)
        return ok_obj(public(ex))


@app.post("/franchise/operators/<operator_id>/exits/<exit_id>/approve-successor")
def approve_successor(operator_id, exit_id):
    authorize({"SelectionCommittee"})
    with lock:
        _, ex = _get_exit_scoped(operator_id, exit_id)
        if ex["exit_status"] != "SUCCESSOR_PENDING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "exit case is not SUCCESSOR_PENDING")
        ex["exit_status"] = "SUCCESSOR_APPROVED"
        bump(ex)
        return ok_obj(public(ex))


@app.post("/franchise/operators/<operator_id>/exits/<exit_id>/reject-successor")
def reject_successor(operator_id, exit_id):
    authorize({"SelectionCommittee"})
    with lock:
        _, ex = _get_exit_scoped(operator_id, exit_id)
        if ex["exit_status"] != "SUCCESSOR_PENDING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "exit case is not SUCCESSOR_PENDING")
        ex["successor_candidate_id"] = None
        ex["exit_status"] = "OPEN"
        bump(ex)
        return ok_obj(public(ex))


@app.post("/franchise/operators/<operator_id>/exits/<exit_id>/complete")
def complete_exit(operator_id, exit_id):
    authorize({"FieldConsultant"})
    with lock:
        op, ex = _get_exit_scoped(operator_id, exit_id)
        if ex["exit_status"] != "SUCCESSOR_APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "exit case is not SUCCESSOR_APPROVED")
        effective = parse_dt(ex["effective_on"])
        if effective is None or store.clock < effective:
            raise ApiError("ERR_EXIT_NOT_COMPLETABLE", 409,
                           "effective_on has not been reached")
        closed_weeks = [w for w in store.weeks.values()
                        if w["restaurant_id"] == op["restaurant_id"]
                        and w["week_status"] == "CLOSED"]
        closed_weeks.sort(key=lambda w: w["week_start_on"], reverse=True)
        final_stmt = None
        if closed_weeks:
            most_recent = closed_weeks[0]
            for st in store.statements.values():
                if (st["operator_id"] == operator_id
                        and st["operating_week_id"] == most_recent["id"]
                        and st["statement_kind"] == "FINAL"):
                    final_stmt = st
                    break
        if final_stmt is None:
            raise ApiError("ERR_EXIT_NOT_COMPLETABLE", 409,
                           "no FINAL statement on file for the most recent CLOSED week")
        ex["final_statement_id"] = final_stmt["id"]
        ex["exit_status"] = "COMPLETED"
        bump(ex)
        op["operator_status"] = "EXITED"
        bump(op)
        agreement = store.agreements.get(op["agreement_id"])
        if agreement and agreement["agreement_status"] in ("EXECUTED", "SUSPENDED"):
            agreement["agreement_status"] = "TERMINATED"
            bump(agreement)
        rest = store.restaurants.get(op["restaurant_id"])
        if rest is not None:
            rest["restaurant_status"] = "AVAILABLE"
            rest["current_operator_id"] = None
            bump(rest)
        # Create the successor operator + fresh DRAFT agreement.
        successor_id = ex.get("successor_candidate_id")
        if successor_id and successor_id in store.candidates:
            has_operator = any(o["candidate_id"] == successor_id
                               for o in store.operators.values())
            if not has_operator and rest is not None:
                new_op = new_resource()
                new_agreement = new_resource()
                new_agreement.update({
                    "operator_id": new_op["id"],
                    "restaurant_id": rest["id"],
                    "transferable": False,
                    "equity_stake_bps": 0,
                    "base_share_bps": agreement["base_share_bps"] if agreement else 0,
                    "agreement_status": "DRAFT",
                    "effective_from": fmt_dt(store.clock),
                })
                store.agreements[new_agreement["id"]] = new_agreement
                new_op.update({
                    "candidate_id": successor_id,
                    "agreement_id": new_agreement["id"],
                    "restaurant_id": rest["id"],
                    "operator_status": "ONBOARDING",
                    "residency_verified": False,
                    "full_time_attested": False,
                    "lifetime_revenue_share_cents": 0,
                })
                store.operators[new_op["id"]] = new_op
        return ok_obj(public(ex))


@app.post("/franchise/operators/<operator_id>/exits/<exit_id>/cancel")
def cancel_exit(operator_id, exit_id):
    role, uid = authorize({"Operator"})
    with lock:
        op, ex = _get_exit_scoped(operator_id, exit_id)
        require_self(role, uid, op["id"])
        if ex["exit_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an OPEN exit case can be cancelled")
        ex["exit_status"] = "CANCELLED"
        bump(ex)
        op["operator_status"] = "ACTIVE"
        bump(op)
        return ok_obj(public(ex))


# ---------------------------------------------------------------------------
# Revenue share statements
# ---------------------------------------------------------------------------


@app.get("/franchise/operators/<operator_id>/statements")
def list_operator_statements(operator_id):
    authorize({"SystemAdmin", "FinanceAdmin", "Operator"})
    with lock:
        get_or_404(store.operators, operator_id)
        filters = {}
        for key in ("statement_kind", "statement_status", "operating_week_id"):
            v = request.args.get(key)
            if v is not None:
                filters[key] = v
        return list_response(
            [s for s in store.statements.values()
             if s["operator_id"] == operator_id], filters)


@app.get("/franchise/statements")
def list_statements():
    authorize({"SystemAdmin", "FinanceAdmin", "Operator"})
    filters = {}
    for key in ("operator_id", "operating_week_id", "statement_kind",
                "statement_status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    with lock:
        return list_response(store.statements.values(), filters)


@app.get("/franchise/statements/<statement_id>")
def get_statement(statement_id):
    authorize({"SystemAdmin", "FinanceAdmin", "Operator"})
    with lock:
        st = get_or_404(store.statements, statement_id)
        return ok_obj(public(st))


@app.post("/franchise/statements/<statement_id>/settle")
def settle_statement(statement_id):
    authorize({"FinanceAdmin"})
    with lock:
        st = get_or_404(store.statements, statement_id)
        if st["statement_status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an ISSUED statement can be settled")
        st["statement_status"] = "SETTLED"
        bump(st)
        op = store.operators.get(st["operator_id"])
        if op is not None:
            op["lifetime_revenue_share_cents"] += st["operator_share_cents"]
            bump(op)
        return ok_obj(public(st))


@app.post("/franchise/statements/<statement_id>/void")
def void_statement(statement_id):
    authorize({"FinanceAdmin"})
    with lock:
        st = get_or_404(store.statements, statement_id)
        if st["statement_status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only an ISSUED statement can be voided")
        if st["statement_kind"] != "PROVISIONAL":
            raise ApiError("ERR_STATEMENT_NOT_VOIDABLE", 409,
                           "FINAL statements cannot be voided")
        st["statement_status"] = "VOID"
        bump(st)
        return ok_obj(public(st))


@app.post("/franchise/statements/<statement_id>/finalize")
def finalize_statement(statement_id):
    authorize({"FinanceAdmin"})
    with lock:
        st = get_or_404(store.statements, statement_id)
        if st["statement_kind"] != "PROVISIONAL":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "only a PROVISIONAL statement can be re-issued as FINAL")
        has_open_exit = any(
            e["operator_id"] == st["operator_id"]
            and e["exit_status"] in EXIT_NONTERMINAL
            for e in store.exit_cases.values())
        if not has_open_exit:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "an open exit case is required to finalize a statement")
        st["statement_kind"] = "FINAL"
        bump(st)
        return ok_obj(public(st))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
