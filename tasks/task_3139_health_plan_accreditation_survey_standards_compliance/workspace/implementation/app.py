"""Health Plan Accreditation Survey & Standards Compliance API.

Flask implementation derived from PRD.md + SCAFFOLD.yaml.
In-memory storage only; no seeding at startup.
"""
import os
import re
import uuid
import itertools
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


CLOCK = Clock()

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
_seq = itertools.count(1)

DB = {
    "health_plans": {},
    "product_line_scopes": {},
    "standards_editions": {},
    "standard_elements": {},
    "applications": {},
    "evidence_items": {},
    "file_review_samples": {},
    "file_review_cases": {},
    "surveys": {},
    "survey_sessions": {},
    "surveyors": {},
    "surveyor_questions": {},
    "element_scores": {},
    "quality_measure_results": {},
    "consumer_survey_scores": {},
    "corrective_action_plans": {},
    "outcomes": {},
    "annual_reports": {},
}


def _new_id():
    return str(uuid.uuid4())


def _ts(dt=None):
    """ISO 8601 UTC with 3 fractional digits and Z suffix."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _touch(ent):
    ent["updated_at"] = _ts()
    ent["version"] += 1


def _make_entity(fields):
    now = _ts()
    ent = {"id": _new_id(), "created_at": now, "updated_at": now, "version": 1,
           "_seq": next(_seq)}
    ent.update(fields)
    return ent


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + uuid.uuid4().hex[:24]


def ok_object(data, code=200):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def ok_list(items, total, limit, offset, code=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(items) < total,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _ts()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_exc(err):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Serialization (strip internal keys)
# ---------------------------------------------------------------------------
def pub(ent):
    if ent is None:
        return None
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def pub_list(ents):
    return [pub(e) for e in ents]


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "PlanCoordinator", "AccreditationOfficer", "Surveyor", "PublicViewer"}
ANY_ROLE = ["PlatformAdmin", "PlanCoordinator", "AccreditationOfficer", "Surveyor", "PublicViewer"]


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers must be present and role must be declared")
    return Ctx(uid, role)


def require_role(ctx, allowed):
    if ctx.role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role not permitted to call this endpoint")


def require_plan_ownership(ctx, plan_id):
    if ctx.role == "PlanCoordinator" and ctx.user_id != plan_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "PlanCoordinator X-User-ID must equal the owning HealthPlan id")


# ---------------------------------------------------------------------------
# Helpers: lookup with entity-specific 404
# ---------------------------------------------------------------------------
def get_or_404(store_key, entity_id, error_id):
    ent = DB[store_key].get(entity_id)
    if ent is None:
        raise ApiError(error_id, 404, f"{error_id}: {entity_id}")
    return ent


def get_plan(pid):
    return get_or_404("health_plans", pid, "ERR_HEALTH_PLAN_NOT_FOUND")


def get_scope(sid):
    return get_or_404("product_line_scopes", sid, "ERR_PRODUCT_LINE_SCOPE_NOT_FOUND")


def get_edition(eid):
    return get_or_404("standards_editions", eid, "ERR_STANDARDS_EDITION_NOT_FOUND")


def get_element(eid):
    return get_or_404("standard_elements", eid, "ERR_STANDARD_ELEMENT_NOT_FOUND")


def get_application(aid):
    return get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")


def get_evidence(eid):
    return get_or_404("evidence_items", eid, "ERR_EVIDENCE_ITEM_NOT_FOUND")


def get_sample(sid):
    return get_or_404("file_review_samples", sid, "ERR_FILE_REVIEW_SAMPLE_NOT_FOUND")


def get_case(cid):
    return get_or_404("file_review_cases", cid, "ERR_FILE_REVIEW_CASE_NOT_FOUND")


def get_survey(sid):
    return get_or_404("surveys", sid, "ERR_SURVEY_NOT_FOUND")


def get_session(sid):
    return get_or_404("survey_sessions", sid, "ERR_SURVEY_SESSION_NOT_FOUND")


def get_surveyor(sid):
    return get_or_404("surveyors", sid, "ERR_SURVEYOR_NOT_FOUND")


def get_question(qid):
    return get_or_404("surveyor_questions", qid, "ERR_SURVEYOR_QUESTION_NOT_FOUND")


def get_score(sid):
    return get_or_404("element_scores", sid, "ERR_ELEMENT_SCORE_NOT_FOUND")


def get_cap(cid):
    return get_or_404("corrective_action_plans", cid, "ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND")


def get_outcome(oid):
    return get_or_404("outcomes", oid, "ERR_ACCREDITATION_OUTCOME_NOT_FOUND")


def get_report(rid):
    return get_or_404("annual_reports", rid, "ERR_ANNUAL_REPORT_NOT_FOUND")


def get_qmr(rid):
    return get_or_404("quality_measure_results", rid, "ERR_QUALITY_MEASURE_RESULT_NOT_FOUND")


def get_css(rid):
    return get_or_404("consumer_survey_scores", rid, "ERR_ACCREDITATION_OUTCOME_NOT_FOUND")


# ---------------------------------------------------------------------------
# Request body parsing helpers
# ---------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    try:
        b = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def req_field(b, name):
    if name not in b or b[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
    return v


def req_int(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
    return v


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean")
    return v


def req_num(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a number")
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
    return v


ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(v, field):
    if not isinstance(v, str) or not ISO_DT_RE.match(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    return parse_dt(req_field(b, name), name)


def parse_date(v, field):
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a YYYY-MM-DD date")


def req_date(b, name):
    return parse_date(req_field(b, name), name)


def paginate(items):
    """Sorted by _seq ascending; apply limit/offset query params."""
    items = sorted(items, key=lambda e: e["_seq"])
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def D(v):
    return Decimal(str(v))


def r2(v):
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r4(v):
    return v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num2(v):
    """Decimal(2dp) -> JSON number (float)."""
    return float(r2(v))


def num4(v):
    return float(r4(v))


# ---------------------------------------------------------------------------
# Derived recomputations
# ---------------------------------------------------------------------------
def recompute_survey_minutes(survey):
    sessions = [s for s in DB["survey_sessions"].values() if s["survey_id"] == survey["id"]]
    survey["scheduled_minutes"] = sum(s["duration_minutes"] for s in sessions if s["status"] == "SCHEDULED")
    survey["completed_minutes"] = sum(s["duration_minutes"] for s in sessions if s["status"] == "COMPLETED")
    survey["cancelled_minutes"] = sum(s["duration_minutes"] for s in sessions if s["status"] == "CANCELLED")
    survey["active_minutes"] = survey["scheduled_minutes"] + survey["completed_minutes"]
    _touch(survey)


def recompute_app_totals(app):
    scores = [s for s in DB["element_scores"].values()
              if s["application_id"] == app["id"] and s["status"] == "FINAL"]
    app["total_awarded_points"] = num2(sum((D(s["awarded_points"]) for s in scores), Decimal("0")))
    app["total_forfeited_points"] = num2(sum((D(s["forfeited_points"]) for s in scores), Decimal("0")))
    _touch(app)


def cap_is_overdue(cap):
    if cap["status"] == "VERIFIED":
        return False
    due = parse_date(cap["due_date"], "due_date")
    return due < CLOCK.now().date()


def recompute_caps_overdue():
    for cap in DB["corrective_action_plans"].values():
        new = cap_is_overdue(cap)
        if cap["is_overdue"] != new:
            cap["is_overdue"] = new
            _touch(cap)


def outcome_is_publicly_displayed(outcome):
    if not outcome["published"]:
        return False
    if outcome["public_display_until"] is None:
        return False
    until = parse_dt(outcome["public_display_until"], "public_display_until")
    if CLOCK.now() > until:
        return False
    app = DB["applications"][outcome["application_id"]]
    scope_id = app["product_line_scope_id"]
    my_decided = parse_dt(outcome["decided_at"], "decided_at")
    for other in DB["outcomes"].values():
        if other["id"] == outcome["id"] or not other["published"]:
            continue
        oapp = DB["applications"][other["application_id"]]
        if oapp["product_line_scope_id"] != scope_id:
            continue
        o_decided = parse_dt(other["decided_at"], "decided_at")
        if o_decided > my_decided:
            return False
        if o_decided == my_decided and other["decision_sequence"] > outcome["decision_sequence"]:
            return False
    return True


def recompute_public_display():
    for o in DB["outcomes"].values():
        new = outcome_is_publicly_displayed(o)
        if o["is_publicly_displayed"] != new:
            o["is_publicly_displayed"] = new
            _touch(o)


def outcome_view(o):
    """Serialize an outcome with is_publicly_displayed computed live."""
    d = pub(o)
    d["is_publicly_displayed"] = outcome_is_publicly_displayed(o)
    return d


# ---------------------------------------------------------------------------
# Application status transitions (shared helper)
# ---------------------------------------------------------------------------
APP_NONTERMINAL_EXCLUDE = {"WITHDRAWN", "CLOSED"}


def app_transition(app, new_status):
    app["status"] = new_status
    _touch(app)


def withdraw_application(app):
    app_transition(app, "WITHDRAWN")
    for ev in DB["evidence_items"].values():
        if ev["application_id"] == app["id"] and ev["status"] == "SUBMITTED":
            ev["status"] = "VOIDED"
            _touch(ev)


# ---------------------------------------------------------------------------
# Element scoring calculations
# ---------------------------------------------------------------------------
CAT_WEIGHTS = {"UM": D("0.30"), "CR": D("0.30"), "MRR": D("0.20"), "QI": D("0.20")}


def category_scored_samples(app, category):
    return [s for s in DB["file_review_samples"].values()
            if s["application_id"] == app["id"] and s["category"] == category
            and s["status"] == "SCORED"]


def confirmed_gap_count(app, element_id):
    n = 0
    for q in DB["surveyor_questions"].values():
        sess = DB["survey_sessions"][q["survey_session_id"]]
        survey = DB["surveys"][sess["survey_id"]]
        if survey["application_id"] != app["id"]:
            continue
        if q["standard_element_id"] != element_id:
            continue
        if q["raises_gap"] and q["status"] == "ADJUDICATED" and q["gap_confirmed"] is True:
            n += 1
    return n


def open_gap_questions(app, element_id):
    for q in DB["surveyor_questions"].values():
        sess = DB["survey_sessions"][q["survey_session_id"]]
        survey = DB["surveys"][sess["survey_id"]]
        if survey["application_id"] != app["id"]:
            continue
        if q["standard_element_id"] != element_id:
            continue
        if q["raises_gap"] and q["status"] == "LOGGED":
            return True
    return False


def compute_element_score(app, element, include_gaps):
    """Returns (awarded, forfeited, sample_rate_used, evidence_count_used, gap_count_used)."""
    samples = category_scored_samples(app, element["category"])
    if samples:
        rates = [D(s["timeliness_rate"]) for s in samples]
        sample_rate = min(rates)
        sample_breached = any(s["must_pass_threshold_breached"] for s in samples)
    else:
        sample_rate = None
        sample_breached = False

    accepted = sum(1 for ev in DB["evidence_items"].values()
                   if ev["application_id"] == app["id"]
                   and ev["standard_element_id"] == element["id"]
                   and ev["status"] == "ACCEPTED")
    gap_count = confirmed_gap_count(app, element["id"]) if include_gaps else 0

    maxp = D(element["max_points"])
    if element["is_must_pass"] and sample_breached:
        awarded = Decimal("0")
    else:
        if sample_rate is None:
            file_points = r2(maxp * D("0.6"))
        else:
            file_points = r2(maxp * D("0.6") * sample_rate)
        if element["evidence_required_count"] == 0:
            evidence_points = r2(maxp * D("0.4"))
        else:
            ratio = D(accepted) / D(element["evidence_required_count"])
            if ratio > 1:
                ratio = D(1)
            evidence_points = r2(maxp * D("0.4") * ratio)
        gap_deduction = r2(maxp * D("0.1") * D(gap_count))
        raw = file_points + evidence_points - gap_deduction
        if raw < 0:
            raw = Decimal("0")
        if raw > maxp:
            raw = maxp
        awarded = r2(raw)
    forfeited = r2(maxp - awarded)
    return (awarded, forfeited,
            (num4(sample_rate) if sample_rate is not None else None),
            accepted, gap_count)


def completed_resurvey(app):
    rs = [s for s in DB["surveys"].values()
          if s["application_id"] == app["id"] and s["survey_type"] == "RESURVEY"
          and s["status"] == "COMPLETED"]
    if not rs:
        return None
    return max(rs, key=lambda s: s["_seq"])


def compute_resurvey_recovery(app, element, resurvey):
    """Returns (awarded, forfeited) using frozen snapshot, or None if not applicable."""
    caps = [c for c in DB["corrective_action_plans"].values()
            if c["application_id"] == app["id"] and c["standard_element_id"] == element["id"]]
    if not caps:
        return None
    snaps = resurvey.get("_freeze_snapshots") or {}
    snap = snaps.get(element["id"])
    if snap is None:
        return None
    rate = D(resurvey["frozen_cap_closure_rate"])
    recovery = r2(rate * D(snap["forfeited_at_freeze"]))
    awarded = r2(D(snap["awarded_at_freeze"]) + recovery)
    maxp = D(element["max_points"])
    if awarded > maxp:
        awarded = maxp
    forfeited = r2(maxp - awarded)
    return awarded, forfeited


# ---------------------------------------------------------------------------
# Composite / decision
# ---------------------------------------------------------------------------
def compute_decision(app):
    """Returns (composite_score, measure_bonus, must_pass_failure_count, status)."""
    edition_id = app["standards_edition_id"]
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == edition_id]
    final_scores = [s for s in DB["element_scores"].values()
                    if s["application_id"] == app["id"] and s["status"] == "FINAL"]

    base = Decimal("0")
    for cat in ("UM", "CR", "MRR", "QI"):
        cat_elements = [e for e in elements if e["category"] == cat]
        cat_scores = [s for s in final_scores if s["standard_element_id"] in
                      {e["id"] for e in cat_elements}]
        awarded_sum = sum((D(s["awarded_points"]) for s in cat_scores), Decimal("0"))
        max_sum = sum((D(e["max_points"]) for e in cat_elements
                       if any(s["standard_element_id"] == e["id"] for s in cat_scores)),
                      Decimal("0"))
        if max_sum > 0:
            ratio = r4(awarded_sum / max_sum)
        else:
            ratio = Decimal("0")
        base += ratio * CAT_WEIGHTS[cat]

    year = parse_dt(app["review_period_end"], "review_period_end").year
    scope_id = app["product_line_scope_id"]
    qmrs = [q for q in DB["quality_measure_results"].values()
            if q["product_line_scope_id"] == scope_id and q["is_reportable"]
            and q["measurement_year"] == year]
    if qmrs:
        avg_pct = sum((D(q["percentile"]) for q in qmrs), Decimal("0")) / D(len(qmrs))
    else:
        avg_pct = Decimal("0")
    quality_component = r2(avg_pct / D(100) * D("2.0"))

    csss = [c for c in DB["consumer_survey_scores"].values()
            if c["product_line_scope_id"] == scope_id and c["survey_year"] == year]
    if csss:
        avg_c = sum((D(c["composite_score"]) for c in csss), Decimal("0")) / D(len(csss))
    else:
        avg_c = Decimal("0")
    consumer_component = r2(avg_c / D(100) * D("2.0"))

    measure_bonus = quality_component + consumer_component
    composite = r2(base * D(100) + measure_bonus)

    mp_fail = 0
    for s in final_scores:
        el = DB["standard_elements"][s["standard_element_id"]]
        if el["is_must_pass"] and D(s["awarded_points"]) < D(el["max_points"]) / D(2):
            mp_fail += 1

    if composite < D("60.00") or mp_fail >= 2:
        status = "DENIED"
    elif mp_fail >= 1:
        status = "ACCREDITED_WITH_CAP"
    elif composite >= D("90.00"):
        status = "ACCREDITED"
    elif composite >= D("75.00"):
        status = "ACCREDITED_WITH_CAP"
    else:
        status = "PROVISIONAL"

    return (num2(composite), num2(measure_bonus), mp_fail, status)


def post_decision_cascade(app, decided_at):
    """Auto-create CAPs then re-evaluate DECIDED -> CORRECTIVE_ACTION | CLOSED."""
    edition_id = app["standards_edition_id"]
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == edition_id]
    final_scores = [s for s in DB["element_scores"].values()
                    if s["application_id"] == app["id"] and s["status"] == "FINAL"]
    decision_date = decided_at.date()
    due = decision_date + timedelta(days=90)
    for s in final_scores:
        el = next(e for e in elements if e["id"] == s["standard_element_id"])
        if D(s["awarded_points"]) < D(el["max_points"]) and \
                (el["is_must_pass"] or D(s["awarded_points"]) == 0):
            existing = [c for c in DB["corrective_action_plans"].values()
                        if c["application_id"] == app["id"]
                        and c["standard_element_id"] == el["id"]]
            if not existing:
                cap = _make_entity({
                    "application_id": app["id"],
                    "standard_element_id": el["id"],
                    "gap_description": "Auto-created corrective action plan",
                    "due_date": due.isoformat(),
                    "is_overdue": False,
                    "origin": "AUTO",
                    "status": "OPEN",
                })
                cap["is_overdue"] = cap_is_overdue(cap)
                DB["corrective_action_plans"][cap["id"]] = cap
    # Re-evaluate
    open_caps = [c for c in DB["corrective_action_plans"].values()
                 if c["application_id"] == app["id"]
                 and c["status"] in ("OPEN", "EVIDENCE_SUBMITTED")]
    if open_caps:
        app_transition(app, "CORRECTIVE_ACTION")
    else:
        app_transition(app, "CLOSED")


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    # days in month
    if m == 12:
        nextm = date(y + 1, 1, 1)
    else:
        nextm = date(y, m + 1, 1)
    last_day = (nextm - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Logical clock endpoint
# ---------------------------------------------------------------------------
@app.post("/accreditation/_clock/set_current_utc")
def set_clock():
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    b = body()
    dt = req_dt(b, "to_iso8601")
    CLOCK.set(dt)
    recompute_caps_overdue()
    recompute_public_display()
    return ok_object({"current_utc": _ts(CLOCK.now())})


# ---------------------------------------------------------------------------
# Standards editions & elements
# ---------------------------------------------------------------------------
PRODUCT_LINES = {"COMMERCIAL", "MEDICARE", "MEDICAID", "MARKETPLACE"}
CATEGORIES = {"UM", "CR", "MRR", "QI"}


@app.post("/accreditation/standards-editions")
def create_edition():
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    b = body()
    year = req_int(b, "edition_year")
    eff_from = req_dt(b, "effective_from")
    eff_until = req_dt(b, "effective_until")
    min_sample = req_int(b, "min_file_sample_per_category")
    threshold = req_num(b, "timeliness_threshold")
    if min_sample < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "min_file_sample_per_category must be >= 1")
    if not (D(threshold) > 0 and D(threshold) <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 400, "timeliness_threshold must be in (0, 1]")
    if any(e["edition_year"] == year for e in DB["standards_editions"].values()):
        raise ApiError("ERR_EDITION_YEAR_DUPLICATE", 409, "edition_year already in use")
    if eff_until <= eff_from:
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_until must be after effective_from")
    ed = _make_entity({
        "edition_year": year,
        "effective_from": _ts(eff_from),
        "effective_until": _ts(eff_until),
        "min_file_sample_per_category": min_sample,
        "timeliness_threshold": float(D(threshold)),
        "status": "DRAFT",
    })
    DB["standards_editions"][ed["id"]] = ed
    return ok_object(pub(ed), 201)


@app.get("/accreditation/standards-editions")
def list_editions():
    require_auth()
    page, total, limit, offset = paginate(list(DB["standards_editions"].values()))
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/standards-editions/<editionId>")
def get_edition_ep(editionId):
    require_auth()
    return ok_object(pub(get_edition(editionId)))


@app.post("/accreditation/standards-editions/<editionId>/publish")
def publish_edition(editionId):
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    ed = get_edition(editionId)
    if ed["status"] != "DRAFT":
        raise ApiError("ERR_EDITION_NOT_PUBLISHED", 409, "Edition is not DRAFT")
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == ed["id"]]
    if not elements:
        raise ApiError("ERR_EDITION_HAS_NO_ELEMENTS", 409, "Edition has no elements")
    ed["status"] = "PUBLISHED"
    _touch(ed)
    return ok_object(pub(ed))


@app.post("/accreditation/standards-editions/<editionId>/supersede")
def supersede_edition(editionId):
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    ed = get_edition(editionId)
    b = body()
    target_id = req_str(b, "superseded_by_edition_id")
    if target_id == editionId:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "superseded_by_edition_id must differ from path edition id")
    if ed["status"] != "PUBLISHED":
        raise ApiError("ERR_EDITION_NOT_SUPERSEDABLE", 409, "Edition is not PUBLISHED")
    target = DB["standards_editions"].get(target_id)
    if target is None or target["status"] != "PUBLISHED":
        raise ApiError("ERR_EDITION_NOT_PUBLISHED", 409,
                       "superseded_by_edition_id must reference a PUBLISHED edition")
    ed["status"] = "SUPERSEDED"
    _touch(ed)
    # Cascade: withdraw DRAFT applications on this edition
    for app_e in list(DB["applications"].values()):
        if app_e["standards_edition_id"] == ed["id"] and app_e["status"] == "DRAFT":
            withdraw_application(app_e)
    return ok_object(pub(ed))


@app.post("/accreditation/standards-editions/<editionId>/standard-elements")
def create_element(editionId):
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    ed = get_edition(editionId)
    b = body()
    code = req_str(b, "element_code")
    category = req_enum(b, "category", CATEGORIES)
    max_points = req_int(b, "max_points")
    is_must_pass = req_bool(b, "is_must_pass")
    ev_req = req_int(b, "evidence_required_count")
    if max_points < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_points must be >= 1")
    if ev_req < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "evidence_required_count must be >= 0")
    if ed["status"] != "DRAFT":
        raise ApiError("ERR_EDITION_NOT_PUBLISHED", 409, "Edition must be DRAFT to add elements")
    if any(e["standards_edition_id"] == ed["id"] and e["element_code"] == code
           for e in DB["standard_elements"].values()):
        raise ApiError("ERR_ELEMENT_CODE_DUPLICATE", 409, "element_code already exists in edition")
    el = _make_entity({
        "standards_edition_id": ed["id"],
        "element_code": code,
        "category": category,
        "max_points": max_points,
        "is_must_pass": is_must_pass,
        "evidence_required_count": ev_req,
    })
    DB["standard_elements"][el["id"]] = el
    return ok_object(pub(el), 201)


@app.get("/accreditation/standards-editions/<editionId>/standard-elements")
def list_elements_of_edition(editionId):
    require_auth()
    ed = get_edition(editionId)
    items = [e for e in DB["standard_elements"].values()
             if e["standards_edition_id"] == ed["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/standard-elements")
def list_elements():
    require_auth()
    items = list(DB["standard_elements"].values())
    fe = request.args.get("standards_edition_id")
    if fe is not None:
        items = [e for e in items if e["standards_edition_id"] == fe]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/standard-elements/<elementId>")
def get_element_ep(elementId):
    require_auth()
    return ok_object(pub(get_element(elementId)))


# ---------------------------------------------------------------------------
# Health plans & scopes
# ---------------------------------------------------------------------------
@app.post("/accreditation/health-plans")
def create_plan():
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    b = body()
    name = req_str(b, "name")
    code = req_str(b, "plan_code")
    if any(p["plan_code"] == code for p in DB["health_plans"].values()):
        raise ApiError("ERR_PLAN_CODE_DUPLICATE", 409, "plan_code already in use")
    plan = _make_entity({"name": name, "plan_code": code, "status": "ACTIVE"})
    DB["health_plans"][plan["id"]] = plan
    return ok_object(pub(plan), 201)


@app.get("/accreditation/health-plans")
def list_plans():
    require_auth()
    page, total, limit, offset = paginate(list(DB["health_plans"].values()))
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/health-plans/<planId>")
def get_plan_ep(planId):
    require_auth()
    return ok_object(pub(get_plan(planId)))


@app.post("/accreditation/health-plans/<planId>/retire")
def retire_plan(planId):
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    plan = get_plan(planId)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    for a in DB["applications"].values():
        if a["health_plan_id"] == plan["id"] and a["status"] not in ("WITHDRAWN", "CLOSED"):
            raise ApiError("ERR_ACTIVE_APPLICATIONS_EXIST", 409,
                           "Plan has applications in a non-terminal status")
    plan["status"] = "RETIRED"
    _touch(plan)
    return ok_object(pub(plan))


@app.post("/accreditation/health-plans/<planId>/product-line-scopes")
def create_scope(planId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    require_plan_ownership(ctx, planId)
    plan = get_plan(planId)
    b = body()
    pl = req_enum(b, "product_line", PRODUCT_LINES)
    state_codes = req_field(b, "state_codes")
    member_count = req_int(b, "member_count")
    if not isinstance(state_codes, list) or not state_codes or \
            any(not isinstance(s, str) or not re.match(r"^[A-Z]{2}$", s) for s in state_codes):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "state_codes must be a non-empty array of 2-letter codes")
    if member_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "member_count must be >= 1")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if any(s["health_plan_id"] == plan["id"] and s["product_line"] == pl
           for s in DB["product_line_scopes"].values()):
        raise ApiError("ERR_PRODUCT_LINE_DUPLICATE", 409,
                       "A scope for this (plan, product_line) already exists")
    scope = _make_entity({
        "health_plan_id": plan["id"],
        "product_line": pl,
        "state_codes": state_codes,
        "member_count": member_count,
    })
    DB["product_line_scopes"][scope["id"]] = scope
    return ok_object(pub(scope), 201)


@app.get("/accreditation/health-plans/<planId>/product-line-scopes")
def list_scopes_of_plan(planId):
    require_auth()
    plan = get_plan(planId)
    items = [s for s in DB["product_line_scopes"].values()
             if s["health_plan_id"] == plan["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/product-line-scopes")
def list_scopes():
    require_auth()
    items = list(DB["product_line_scopes"].values())
    fp = request.args.get("health_plan_id")
    if fp is not None:
        items = [s for s in items if s["health_plan_id"] == fp]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/product-line-scopes/<scopeId>")
def get_scope_ep(scopeId):
    require_auth()
    return ok_object(pub(get_scope(scopeId)))


# ---------------------------------------------------------------------------
# Surveyors
# ---------------------------------------------------------------------------
CRED_LEVELS = {"LEAD", "STAFF"}


@app.post("/accreditation/surveyors")
def create_surveyor():
    ctx = require_auth()
    require_role(ctx, ["PlatformAdmin"])
    b = body()
    name = req_str(b, "name")
    level = req_enum(b, "credential_level", CRED_LEVELS)
    sv = _make_entity({"name": name, "credential_level": level, "active": True})
    DB["surveyors"][sv["id"]] = sv
    return ok_object(pub(sv), 201)


@app.get("/accreditation/surveyors")
def list_surveyors():
    require_auth()
    page, total, limit, offset = paginate(list(DB["surveyors"].values()))
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/surveyors/<surveyorId>")
def get_surveyor_ep(surveyorId):
    require_auth()
    return ok_object(pub(get_surveyor(surveyorId)))


@app.get("/accreditation/surveyors/<surveyorId>/sessions")
def list_surveyor_sessions(surveyorId):
    require_auth()
    sv = get_surveyor(surveyorId)
    items = [s for s in DB["survey_sessions"].values() if s["surveyor_id"] == sv["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@app.post("/accreditation/health-plans/<planId>/applications")
def create_application(planId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    require_plan_ownership(ctx, planId)
    plan = get_plan(planId)
    b = body()
    scope_id = req_str(b, "product_line_scope_id")
    edition_id = req_str(b, "standards_edition_id")
    rps = req_dt(b, "review_period_start")
    rpe = req_dt(b, "review_period_end")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    scope = get_scope(scope_id)
    get_edition(edition_id)
    if scope["health_plan_id"] != plan["id"]:
        raise ApiError("ERR_SCOPE_PLAN_MISMATCH", 422,
                       "product_line_scope_id does not belong to the path's HealthPlan")
    if rpe <= rps:
        raise ApiError("ERR_REVIEW_PERIOD_INVALID", 422,
                       "review_period_end must be after review_period_start")
    app_e = _make_entity({
        "health_plan_id": plan["id"],
        "product_line_scope_id": scope_id,
        "standards_edition_id": edition_id,
        "review_period_start": _ts(rps),
        "review_period_end": _ts(rpe),
        "status": "DRAFT",
        "total_awarded_points": 0,
        "total_forfeited_points": 0,
    })
    DB["applications"][app_e["id"]] = app_e
    return ok_object(pub(app_e), 201)


@app.get("/accreditation/health-plans/<planId>/applications")
def list_plan_applications(planId):
    require_auth()
    plan = get_plan(planId)
    items = [a for a in DB["applications"].values() if a["health_plan_id"] == plan["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/applications")
def list_applications():
    require_auth()
    items = list(DB["applications"].values())
    for param, field in (("health_plan_id", "health_plan_id"),
                         ("product_line_scope_id", "product_line_scope_id"),
                         ("standards_edition_id", "standards_edition_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[field] == v]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/applications/<applicationId>")
def get_application_ep(applicationId):
    require_auth()
    return ok_object(pub(get_application(applicationId)))


def _check_occ(b, app_e):
    expected = b.get("expected_application_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "expected_application_version must be an integer")
        if expected != app_e["version"]:
            raise ApiError("ERR_STALE_VERSION", 412,
                           "expected_application_version does not match current version")


@app.post("/accreditation/applications/<applicationId>/submit")
def submit_application(applicationId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    app_e = get_application(applicationId)
    require_plan_ownership(ctx, app_e["health_plan_id"])
    b = body()
    req_field(b, "expected_application_version")
    # state check first (PRD §3.3 lists DRAFT-state check first among preconditions)
    if app_e["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not DRAFT")
    _check_occ(b, app_e)
    edition = DB["standards_editions"][app_e["standards_edition_id"]]
    if edition["status"] != "PUBLISHED":
        raise ApiError("ERR_EDITION_NOT_PUBLISHED", 409, "Edition is not PUBLISHED")
    for other in DB["applications"].values():
        if other["id"] == app_e["id"]:
            continue
        if other["product_line_scope_id"] == app_e["product_line_scope_id"] and \
                other["standards_edition_id"] == app_e["standards_edition_id"] and \
                other["status"] not in ("WITHDRAWN", "CLOSED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION", 409,
                           "A non-terminal application already exists for this scope and edition")
    app_transition(app_e, "SUBMITTED")
    return ok_object(pub(app_e))


@app.post("/accreditation/applications/<applicationId>/begin-evidence-review")
def begin_evidence_review(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    if app_e["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not SUBMITTED")
    app_transition(app_e, "EVIDENCE_REVIEW")
    return ok_object(pub(app_e))


@app.post("/accreditation/applications/<applicationId>/advance-to-survey-scheduling")
def advance_to_survey_scheduling(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    if app_e["status"] != "EVIDENCE_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not EVIDENCE_REVIEW")
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == app_e["standards_edition_id"]]
    for el in elements:
        if el["evidence_required_count"] > 0:
            cnt = sum(1 for ev in DB["evidence_items"].values()
                      if ev["application_id"] == app_e["id"]
                      and ev["standard_element_id"] == el["id"]
                      and ev["status"] == "ACCEPTED")
            if cnt < el["evidence_required_count"]:
                raise ApiError("ERR_EVIDENCE_COMPLETENESS_UNMET", 422,
                               "Evidence completeness unmet for element " + el["element_code"])
    app_transition(app_e, "SURVEY_SCHEDULING")
    return ok_object(pub(app_e))


@app.post("/accreditation/applications/<applicationId>/withdraw")
def withdraw_application_ep(applicationId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    app_e = get_application(applicationId)
    require_plan_ownership(ctx, app_e["health_plan_id"])
    if app_e["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not DRAFT or SUBMITTED")
    withdraw_application(app_e)
    return ok_object(pub(app_e))


# ---------------------------------------------------------------------------
# Evidence items
# ---------------------------------------------------------------------------
@app.post("/accreditation/applications/<applicationId>/evidence-items")
def create_evidence(applicationId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    app_e = get_application(applicationId)
    require_plan_ownership(ctx, app_e["health_plan_id"])
    b = body()
    element_id = req_str(b, "standard_element_id")
    title = req_str(b, "title")
    req_field(b, "expected_application_version")
    _check_occ(b, app_e)
    if app_e["status"] not in ("SUBMITTED", "EVIDENCE_REVIEW"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application must be SUBMITTED or EVIDENCE_REVIEW")
    element = get_element(element_id)
    if element["standards_edition_id"] != app_e["standards_edition_id"]:
        raise ApiError("ERR_ELEMENT_EDITION_MISMATCH", 422,
                       "Element does not belong to the application's edition")
    ev = _make_entity({
        "application_id": app_e["id"],
        "standard_element_id": element_id,
        "title": title,
        "review_note": None,
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    DB["evidence_items"][ev["id"]] = ev
    _touch(app_e)  # version bump side effect
    return ok_object(pub(ev), 201)


@app.get("/accreditation/applications/<applicationId>/evidence-items")
def list_evidence_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [e for e in DB["evidence_items"].values() if e["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/evidence-items")
def list_evidence():
    require_auth()
    items = list(DB["evidence_items"].values())
    fe = request.args.get("standard_element_id")
    if fe is not None:
        items = [e for e in items if e["standard_element_id"] == fe]
    fa = request.args.get("application_id")
    if fa is not None:
        items = [e for e in items if e["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/evidence-items/<evidenceItemId>")
def get_evidence_ep(evidenceItemId):
    require_auth()
    return ok_object(pub(get_evidence(evidenceItemId)))


def _evidence_review_guard(ev):
    if ev["status"] != "SUBMITTED":
        raise ApiError("ERR_EVIDENCE_NOT_REVIEWABLE", 409, "Evidence item is not SUBMITTED")
    app_e = DB["applications"][ev["application_id"]]
    if app_e["status"] != "EVIDENCE_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not EVIDENCE_REVIEW")
    return app_e


@app.post("/accreditation/evidence-items/<evidenceItemId>/accept")
def accept_evidence(evidenceItemId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    ev = get_evidence(evidenceItemId)
    b = body()
    note = opt_str(b, "review_note")
    _evidence_review_guard(ev)
    ev["status"] = "ACCEPTED"
    ev["review_note"] = note
    _touch(ev)
    return ok_object(pub(ev))


@app.post("/accreditation/evidence-items/<evidenceItemId>/reject")
def reject_evidence(evidenceItemId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    ev = get_evidence(evidenceItemId)
    b = body()
    note = req_str(b, "review_note")
    _evidence_review_guard(ev)
    ev["status"] = "REJECTED"
    ev["review_note"] = note
    _touch(ev)
    return ok_object(pub(ev))


@app.post("/accreditation/evidence-items/<evidenceItemId>/resubmit")
def resubmit_evidence(evidenceItemId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    ev = get_evidence(evidenceItemId)
    app_e = DB["applications"][ev["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    b = body()
    title = opt_str(b, "title")
    if ev["status"] != "REJECTED":
        raise ApiError("ERR_EVIDENCE_NOT_RESUBMITTABLE", 409,
                       "Evidence item is not REJECTED")
    if app_e["status"] != "EVIDENCE_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not EVIDENCE_REVIEW")
    ev["status"] = "SUBMITTED"
    ev["revision_count"] += 1
    ev["review_note"] = None
    if title is not None:
        ev["title"] = title
    _touch(ev)
    return ok_object(pub(ev))


# ---------------------------------------------------------------------------
# File review samples & cases
# ---------------------------------------------------------------------------
SAMPLE_TYPES = {"DENIAL", "APPEAL", "CREDENTIALING"}
TIMELINESS_BASES = {"DECISION_DATE", "RESOLUTION_DATE"}
SAMPLE_TYPE_CATEGORY = {"DENIAL": "UM", "APPEAL": "UM", "CREDENTIALING": "CR"}


@app.post("/accreditation/applications/<applicationId>/file-review-samples")
def create_sample(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    b = body()
    sample_type = req_enum(b, "sample_type", SAMPLE_TYPES)
    required_size = req_int(b, "required_size")
    basis = req_enum(b, "timeliness_basis", TIMELINESS_BASES)
    if app_e["status"] not in ("EVIDENCE_REVIEW", "SURVEY_SCHEDULING"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application must be EVIDENCE_REVIEW or SURVEY_SCHEDULING")
    edition = DB["standards_editions"][app_e["standards_edition_id"]]
    if required_size < edition["min_file_sample_per_category"]:
        raise ApiError("ERR_SAMPLE_SIZE_BELOW_MINIMUM", 422,
                       "required_size below edition minimum")
    smp = _make_entity({
        "application_id": app_e["id"],
        "sample_type": sample_type,
        "category": SAMPLE_TYPE_CATEGORY[sample_type],
        "required_size": required_size,
        "timeliness_basis": basis,
        "timely_case_count": 0,
        "timeliness_rate": None,
        "must_pass_threshold_breached": False,
        "status": "OPEN",
    })
    DB["file_review_samples"][smp["id"]] = smp
    return ok_object(pub(smp), 201)


@app.get("/accreditation/applications/<applicationId>/file-review-samples")
def list_samples_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [s for s in DB["file_review_samples"].values()
             if s["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/file-review-samples")
def list_samples():
    require_auth()
    items = list(DB["file_review_samples"].values())
    fa = request.args.get("application_id")
    if fa is not None:
        items = [s for s in items if s["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/file-review-samples/<sampleId>")
def get_sample_ep(sampleId):
    require_auth()
    return ok_object(pub(get_sample(sampleId)))


def _compute_case_timeliness(case, sample):
    svc = parse_dt(case["service_date"], "service_date")
    if sample["timeliness_basis"] == "DECISION_DATE":
        basis = parse_dt(case["decision_date"], "decision_date")
    else:
        basis = parse_dt(case["resolution_date"], "resolution_date")
    delta = basis - svc
    days = delta.days if delta.total_seconds() >= 0 else (delta.total_seconds() // 86400)
    days = int(days)
    case["days_to_basis"] = days
    case["is_timely"] = days <= case["required_turnaround_days"]


@app.post("/accreditation/file-review-samples/<sampleId>/cases")
def create_case(sampleId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    smp = get_sample(sampleId)
    app_e = DB["applications"][smp["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    b = body()
    case_ref = req_str(b, "case_reference")
    svc = req_dt(b, "service_date")
    dec = req_dt(b, "decision_date")
    res = req_dt(b, "resolution_date")
    turnaround = req_int(b, "required_turnaround_days")
    if smp["status"] != "OPEN":
        raise ApiError("ERR_SAMPLE_NOT_OPEN", 409, "Sample is not OPEN")
    if app_e["status"] not in ("EVIDENCE_REVIEW", "SURVEY_SCHEDULING"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application must be EVIDENCE_REVIEW or SURVEY_SCHEDULING")
    # PRD §2.5: temporal windows (item 10) are checked before uniqueness /
    # cardinality / aggregate constraints (item 11, ERR_INVALID_TURNAROUND_DAYS).
    rps = parse_dt(app_e["review_period_start"], "review_period_start")
    rpe = parse_dt(app_e["review_period_end"], "review_period_end")
    if svc < rps or svc > rpe:
        raise ApiError("ERR_CASE_OUTSIDE_REVIEW_PERIOD", 422,
                       "service_date outside the review period")
    if turnaround < 1:
        raise ApiError("ERR_INVALID_TURNAROUND_DAYS", 422,
                       "required_turnaround_days must be >= 1")
    case = _make_entity({
        "file_review_sample_id": smp["id"],
        "case_reference": case_ref,
        "service_date": _ts(svc),
        "decision_date": _ts(dec),
        "resolution_date": _ts(res),
        "required_turnaround_days": turnaround,
        "is_timely": None,
        "days_to_basis": None,
    })
    DB["file_review_cases"][case["id"]] = case
    return ok_object(pub(case), 201)


@app.get("/accreditation/file-review-samples/<sampleId>/cases")
def list_cases_of_sample(sampleId):
    require_auth()
    smp = get_sample(sampleId)
    items = [c for c in DB["file_review_cases"].values()
             if c["file_review_sample_id"] == smp["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/file-review-cases")
def list_cases():
    require_auth()
    items = list(DB["file_review_cases"].values())
    fs = request.args.get("file_review_sample_id")
    if fs is not None:
        items = [c for c in items if c["file_review_sample_id"] == fs]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/file-review-cases/<caseId>")
def get_case_ep(caseId):
    require_auth()
    return ok_object(pub(get_case(caseId)))


@app.post("/accreditation/file-review-samples/<sampleId>/submit")
def submit_sample(sampleId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    smp = get_sample(sampleId)
    app_e = DB["applications"][smp["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    if smp["status"] != "OPEN":
        raise ApiError("ERR_SAMPLE_NOT_OPEN", 409, "Sample is not OPEN")
    cnt = sum(1 for c in DB["file_review_cases"].values()
              if c["file_review_sample_id"] == smp["id"])
    if cnt < smp["required_size"]:
        raise ApiError("ERR_SAMPLE_INCOMPLETE", 422, "Case count below required_size")
    smp["status"] = "SUBMITTED"
    _touch(smp)
    return ok_object(pub(smp))


@app.post("/accreditation/file-review-samples/<sampleId>/score")
def score_sample(sampleId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    smp = get_sample(sampleId)
    if smp["status"] != "SUBMITTED":
        raise ApiError("ERR_SAMPLE_NOT_SUBMITTED", 409, "Sample is not SUBMITTED")
    app_e = DB["applications"][smp["application_id"]]
    cases = sorted([c for c in DB["file_review_cases"].values()
                    if c["file_review_sample_id"] == smp["id"]],
                   key=lambda c: c["_seq"])
    for c in cases:
        _compute_case_timeliness(c, smp)
        _touch(c)
    total = len(cases)
    timely = sum(1 for c in cases if c["is_timely"])
    smp["timely_case_count"] = timely
    rate = r4(D(timely) / D(total)) if total > 0 else Decimal("0")
    smp["timeliness_rate"] = num4(rate)
    edition = DB["standards_editions"][app_e["standards_edition_id"]]
    has_must_pass = any(e["standards_edition_id"] == edition["id"]
                        and e["category"] == smp["category"] and e["is_must_pass"]
                        for e in DB["standard_elements"].values())
    smp["must_pass_threshold_breached"] = bool(
        rate < D(edition["timeliness_threshold"]) and has_must_pass)
    smp["status"] = "SCORED"
    _touch(smp)
    return ok_object(pub(smp))


# ---------------------------------------------------------------------------
# Surveys & sessions
# ---------------------------------------------------------------------------
SURVEY_TYPES = {"FULL", "RESURVEY"}
SURVEY_MODES = {"VIRTUAL", "ONSITE", "HYBRID"}


@app.post("/accreditation/applications/<applicationId>/surveys")
def create_survey(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    b = body()
    stype = req_enum(b, "survey_type", SURVEY_TYPES)
    mode = req_enum(b, "mode", SURVEY_MODES)
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    hours = req_int(b, "budgeted_surveyor_hours")
    req_field(b, "expected_application_version")
    if hours < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "budgeted_surveyor_hours must be >= 1")
    _check_occ(b, app_e)
    if stype == "FULL":
        if app_e["status"] != "SURVEY_SCHEDULING":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "FULL survey requires application SURVEY_SCHEDULING")
    else:
        if app_e["status"] != "CORRECTIVE_ACTION":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "RESURVEY survey requires application CORRECTIVE_ACTION")
    if end < start:
        raise ApiError("ERR_SURVEY_WINDOW_INVALID", 422, "end_date before start_date")
    sv = _make_entity({
        "application_id": app_e["id"],
        "survey_type": stype,
        "mode": mode,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "budgeted_surveyor_hours": hours,
        "frozen_cap_closure_rate": None,
        "scheduled_minutes": 0,
        "completed_minutes": 0,
        "cancelled_minutes": 0,
        "active_minutes": 0,
        "status": "PLANNED",
    })
    DB["surveys"][sv["id"]] = sv
    _touch(app_e)
    return ok_object(pub(sv), 201)


@app.get("/accreditation/applications/<applicationId>/surveys")
def list_surveys_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [s for s in DB["surveys"].values() if s["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/surveys")
def list_surveys():
    require_auth()
    items = list(DB["surveys"].values())
    fa = request.args.get("application_id")
    if fa is not None:
        items = [s for s in items if s["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/surveys/<surveyId>")
def get_survey_ep(surveyId):
    require_auth()
    return ok_object(pub(get_survey(surveyId)))


@app.post("/accreditation/surveys/<surveyId>/confirm")
def confirm_survey(surveyId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sv = get_survey(surveyId)
    app_e = DB["applications"][sv["application_id"]]
    if sv["status"] != "PLANNED":
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409, "Survey is not PLANNED")
    sessions = [s for s in DB["survey_sessions"].values() if s["survey_id"] == sv["id"]]
    scheduled = [s for s in sessions if s["status"] == "SCHEDULED"]
    if not scheduled:
        raise ApiError("ERR_NO_SCHEDULED_SESSIONS", 409, "No SCHEDULED sessions")
    s_start = parse_date(sv["start_date"], "start_date")
    s_end = parse_date(sv["end_date"], "end_date")
    for s in scheduled:
        d = parse_date(s["session_date"], "session_date")
        if d < s_start or d > s_end:
            raise ApiError("ERR_SESSION_OUTSIDE_SURVEY_WINDOW", 422,
                           "SCHEDULED session outside survey window")
    if sv["survey_type"] == "FULL":
        if app_e["status"] != "SURVEY_SCHEDULING":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "FULL confirm requires SURVEY_SCHEDULING")
    else:
        if app_e["status"] != "CORRECTIVE_ACTION":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "RESURVEY confirm requires CORRECTIVE_ACTION")
        caps = [c for c in DB["corrective_action_plans"].values()
                if c["application_id"] == app_e["id"]]
        if any(c["status"] == "EVIDENCE_SUBMITTED" for c in caps):
            raise ApiError("ERR_CAP_REVIEW_PENDING", 422,
                           "A CAP is in EVIDENCE_SUBMITTED awaiting review")
        if any(cap_is_overdue(c) for c in caps):
            raise ApiError("ERR_CAP_OVERDUE", 422, "A CAP is overdue")
    # overlap check against other PLANNED/CONFIRMED surveys of same application
    for other in DB["surveys"].values():
        if other["id"] == sv["id"]:
            continue
        if other["application_id"] != app_e["id"]:
            continue
        if other["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        o_start = parse_date(other["start_date"], "start_date")
        o_end = parse_date(other["end_date"], "end_date")
        if s_start <= o_end and o_start <= s_end:
            raise ApiError("ERR_SURVEY_DATE_OVERLAP", 409,
                           "Survey date range overlaps another survey")
    # side effects
    if sv["survey_type"] == "FULL":
        app_transition(app_e, "SURVEY_IN_PROGRESS")
    else:
        caps = [c for c in DB["corrective_action_plans"].values()
                if c["application_id"] == app_e["id"]]
        verified = sum(1 for c in caps if c["status"] == "VERIFIED")
        total = len(caps)
        rate = r4(D(verified) / D(total)) if total > 0 else Decimal("0")
        sv["frozen_cap_closure_rate"] = num4(rate)
        # snapshot FINAL scores per CAP element
        snaps = {}
        for c in caps:
            el_id = c["standard_element_id"]
            if el_id in snaps:
                continue
            fs = [s for s in DB["element_scores"].values()
                  if s["application_id"] == app_e["id"]
                  and s["standard_element_id"] == el_id and s["status"] == "FINAL"]
            if fs:
                latest = max(fs, key=lambda s: s["_seq"])
                snaps[el_id] = {
                    "awarded_at_freeze": latest["awarded_points"],
                    "forfeited_at_freeze": latest["forfeited_points"],
                }
        sv["_freeze_snapshots"] = snaps
        app_transition(app_e, "RESURVEY_IN_PROGRESS")
    sv["status"] = "CONFIRMED"
    _touch(sv)
    return ok_object(pub(sv))


@app.post("/accreditation/surveys/<surveyId>/complete")
def complete_survey(surveyId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sv = get_survey(surveyId)
    app_e = DB["applications"][sv["application_id"]]
    if sv["status"] != "CONFIRMED":
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409, "Survey is not CONFIRMED")
    sessions = [s for s in DB["survey_sessions"].values() if s["survey_id"] == sv["id"]]
    if any(s["status"] == "SCHEDULED" for s in sessions):
        raise ApiError("ERR_SESSIONS_NOT_FINISHED", 409,
                       "A session is still SCHEDULED")
    if sv["survey_type"] == "FULL":
        app_transition(app_e, "SCORING")
    else:
        # Void FINAL scores of CAP elements
        cap_elements = {c["standard_element_id"]
                        for c in DB["corrective_action_plans"].values()
                        if c["application_id"] == app_e["id"]}
        for s in DB["element_scores"].values():
            if s["application_id"] == app_e["id"] and s["status"] == "FINAL" \
                    and s["standard_element_id"] in cap_elements:
                s["status"] = "VOIDED"
                _touch(s)
        app_transition(app_e, "SCORING")
    sv["status"] = "COMPLETED"
    _touch(sv)
    return ok_object(pub(sv))


@app.post("/accreditation/surveys/<surveyId>/cancel")
def cancel_survey(surveyId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sv = get_survey(surveyId)
    if sv["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409,
                       "Survey is not PLANNED or CONFIRMED")
    for s in DB["survey_sessions"].values():
        if s["survey_id"] == sv["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            _touch(s)
    sv["status"] = "CANCELLED"
    recompute_survey_minutes(sv)
    return ok_object(pub(sv))


def _check_session_overlap(surveyor_id, session_date, start_minute, end_minute, exclude_id=None):
    for s in DB["survey_sessions"].values():
        if s["surveyor_id"] != surveyor_id:
            continue
        if s["session_date"] != session_date:
            continue
        if s["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        # half-open [start, end) overlap: start < other_end AND other_start < end
        if start_minute < s["end_minute"] and s["start_minute"] < end_minute:
            raise ApiError("ERR_SURVEYOR_SESSION_OVERLAP", 409,
                           "Session overlaps another session of the same surveyor")


def _check_onsite(survey_id, session_date, is_onsite, exclude_id=None):
    if not is_onsite:
        return
    for s in DB["survey_sessions"].values():
        if s["survey_id"] != survey_id:
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["session_date"] == session_date and s["is_onsite"] and s["status"] != "CANCELLED":
            raise ApiError("ERR_ONSITE_SAME_DATE_CONFLICT", 409,
                           "Another on-site session exists on that date")


@app.post("/accreditation/surveys/<surveyId>/sessions")
def create_session(surveyId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sv = get_survey(surveyId)
    b = body()
    surveyor_id = req_str(b, "surveyor_id")
    session_date = req_date(b, "session_date")
    start_minute = req_int(b, "start_minute")
    end_minute = req_int(b, "end_minute")
    is_onsite = req_bool(b, "is_onsite")
    if not (0 <= start_minute <= 1439):
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_minute must be 0..1439")
    if not (1 <= end_minute <= 1440) or end_minute <= start_minute:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_minute must be start_minute < value <= 1440")
    get_surveyor(surveyor_id)
    if sv["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409,
                       "Survey is not PLANNED or CONFIRMED")
    s_start = parse_date(sv["start_date"], "start_date")
    s_end = parse_date(sv["end_date"], "end_date")
    if session_date < s_start or session_date > s_end:
        raise ApiError("ERR_SESSION_OUTSIDE_SURVEY_WINDOW", 422,
                       "Session date outside survey window")
    _check_session_overlap(surveyor_id, session_date.isoformat(), start_minute, end_minute)
    _check_onsite(sv["id"], session_date.isoformat(), is_onsite)
    sess = _make_entity({
        "survey_id": sv["id"],
        "surveyor_id": surveyor_id,
        "session_date": session_date.isoformat(),
        "start_minute": start_minute,
        "end_minute": end_minute,
        "is_onsite": is_onsite,
        "duration_minutes": end_minute - start_minute,
        "status": "SCHEDULED",
    })
    DB["survey_sessions"][sess["id"]] = sess
    recompute_survey_minutes(sv)
    return ok_object(pub(sess), 201)


@app.get("/accreditation/surveys/<surveyId>/sessions")
def list_sessions_of_survey(surveyId):
    require_auth()
    sv = get_survey(surveyId)
    items = [s for s in DB["survey_sessions"].values() if s["survey_id"] == sv["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/survey-sessions")
def list_sessions():
    require_auth()
    items = list(DB["survey_sessions"].values())
    fv = request.args.get("surveyor_id")
    if fv is not None:
        items = [s for s in items if s["surveyor_id"] == fv]
    fs = request.args.get("survey_id")
    if fs is not None:
        items = [s for s in items if s["survey_id"] == fs]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/survey-sessions/<sessionId>")
def get_session_ep(sessionId):
    require_auth()
    return ok_object(pub(get_session(sessionId)))


@app.post("/accreditation/survey-sessions/<sessionId>/complete")
def complete_session(sessionId):
    ctx = require_auth()
    require_role(ctx, ["Surveyor"])
    sess = get_session(sessionId)
    if ctx.user_id != sess["surveyor_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "X-User-ID must equal session.surveyor_id")
    if sess["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not SCHEDULED")
    sv = DB["surveys"][sess["survey_id"]]
    if sv["status"] != "CONFIRMED":
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409, "Survey is not CONFIRMED")
    sess["status"] = "COMPLETED"
    _touch(sess)
    recompute_survey_minutes(sv)
    return ok_object(pub(sess))


@app.post("/accreditation/survey-sessions/<sessionId>/cancel")
def cancel_session(sessionId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sess = get_session(sessionId)
    if sess["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not SCHEDULED")
    sess["status"] = "CANCELLED"
    _touch(sess)
    sv = DB["surveys"][sess["survey_id"]]
    recompute_survey_minutes(sv)
    return ok_object(pub(sess))


@app.post("/accreditation/survey-sessions/<sessionId>/reschedule")
def reschedule_session(sessionId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    sess = get_session(sessionId)
    b = body()
    new_date = req_date(b, "session_date")
    start_minute = req_int(b, "start_minute")
    end_minute = req_int(b, "end_minute")
    if not (0 <= start_minute <= 1439):
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_minute must be 0..1439")
    if not (1 <= end_minute <= 1440) or end_minute <= start_minute:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_minute must be start_minute < value <= 1440")
    if sess["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not SCHEDULED")
    sv = DB["surveys"][sess["survey_id"]]
    if sv["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409,
                       "Survey is not PLANNED or CONFIRMED")
    s_start = parse_date(sv["start_date"], "start_date")
    s_end = parse_date(sv["end_date"], "end_date")
    if new_date < s_start or new_date > s_end:
        raise ApiError("ERR_SESSION_OUTSIDE_SURVEY_WINDOW", 422,
                       "Session date outside survey window")
    _check_session_overlap(sess["surveyor_id"], new_date.isoformat(),
                           start_minute, end_minute, exclude_id=sess["id"])
    _check_onsite(sv["id"], new_date.isoformat(), sess["is_onsite"], exclude_id=sess["id"])
    sess["session_date"] = new_date.isoformat()
    sess["start_minute"] = start_minute
    sess["end_minute"] = end_minute
    sess["duration_minutes"] = end_minute - start_minute
    _touch(sess)
    recompute_survey_minutes(sv)
    return ok_object(pub(sess))


# ---------------------------------------------------------------------------
# Surveyor questions
# ---------------------------------------------------------------------------
@app.post("/accreditation/survey-sessions/<sessionId>/questions")
def create_question(sessionId):
    ctx = require_auth()
    require_role(ctx, ["Surveyor"])
    sess = get_session(sessionId)
    if ctx.user_id != sess["surveyor_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "X-User-ID must equal session.surveyor_id")
    b = body()
    element_id = req_str(b, "standard_element_id")
    text = req_str(b, "question_text")
    raises_gap = req_bool(b, "raises_gap")
    sv = DB["surveys"][sess["survey_id"]]
    if sv["status"] != "CONFIRMED":
        raise ApiError("ERR_SURVEY_INVALID_STATE", 409, "Survey is not CONFIRMED")
    app_e = DB["applications"][sv["application_id"]]
    element = get_element(element_id)
    if element["standards_edition_id"] != app_e["standards_edition_id"]:
        raise ApiError("ERR_ELEMENT_EDITION_MISMATCH", 422,
                       "Element does not belong to the application's edition")
    q = _make_entity({
        "survey_session_id": sess["id"],
        "standard_element_id": element_id,
        "question_text": text,
        "raises_gap": raises_gap,
        "gap_confirmed": None,
        "status": "LOGGED",
    })
    DB["surveyor_questions"][q["id"]] = q
    return ok_object(pub(q), 201)


@app.get("/accreditation/survey-sessions/<sessionId>/questions")
def list_questions_of_session(sessionId):
    require_auth()
    sess = get_session(sessionId)
    items = [q for q in DB["surveyor_questions"].values()
             if q["survey_session_id"] == sess["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/surveyor-questions")
def list_questions():
    require_auth()
    items = list(DB["surveyor_questions"].values())
    fe = request.args.get("standard_element_id")
    if fe is not None:
        items = [q for q in items if q["standard_element_id"] == fe]
    fs = request.args.get("survey_session_id")
    if fs is not None:
        items = [q for q in items if q["survey_session_id"] == fs]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/surveyor-questions/<questionId>")
def get_question_ep(questionId):
    require_auth()
    return ok_object(pub(get_question(questionId)))


@app.post("/accreditation/surveyor-questions/<questionId>/adjudicate")
def adjudicate_question(questionId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    q = get_question(questionId)
    b = body()
    gap_confirmed = req_bool(b, "gap_confirmed")
    if q["status"] != "LOGGED":
        raise ApiError("ERR_QUESTION_ALREADY_ADJUDICATED", 409,
                       "Question already ADJUDICATED")
    q["gap_confirmed"] = gap_confirmed
    q["status"] = "ADJUDICATED"
    _touch(q)
    return ok_object(pub(q))


# ---------------------------------------------------------------------------
# Element scores
# ---------------------------------------------------------------------------
SCORE_CREATABLE_STATES = {"EVIDENCE_REVIEW", "SURVEY_SCHEDULING", "SURVEY_IN_PROGRESS",
                          "SCORING", "RESURVEY_IN_PROGRESS"}


@app.post("/accreditation/applications/<applicationId>/element-scores")
def create_element_score(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    b = body()
    element_id = req_str(b, "standard_element_id")
    if app_e["status"] not in SCORE_CREATABLE_STATES:
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application state does not allow score creation")
    element = get_element(element_id)
    if element["standards_edition_id"] != app_e["standards_edition_id"]:
        raise ApiError("ERR_ELEMENT_EDITION_MISMATCH", 422,
                       "Element does not belong to the application's edition")
    for s in DB["element_scores"].values():
        if s["application_id"] == app_e["id"] and s["standard_element_id"] == element_id \
                and s["status"] != "VOIDED":
            raise ApiError("ERR_ELEMENT_SCORE_EXISTS", 409,
                           "A non-VOIDED score already exists for this element")
    resurvey = completed_resurvey(app_e)
    basis = "RESURVEY" if resurvey is not None else "FILE_REVIEW"
    if basis == "RESURVEY":
        recovery = compute_resurvey_recovery(app_e, element, resurvey)
    else:
        recovery = None
    if recovery is not None:
        awarded, forfeited = recovery
        # still record sample/evidence context
        samples = category_scored_samples(app_e, element["category"])
        sample_rate_used = num4(min(D(s["timeliness_rate"]) for s in samples)) if samples else None
        evidence_count_used = sum(1 for ev in DB["evidence_items"].values()
                                  if ev["application_id"] == app_e["id"]
                                  and ev["standard_element_id"] == element_id
                                  and ev["status"] == "ACCEPTED")
        gap_count_used = 0
    else:
        awarded, forfeited, sample_rate_used, evidence_count_used, gap_count_used = \
            compute_element_score(app_e, element, include_gaps=False)
    score = _make_entity({
        "application_id": app_e["id"],
        "standard_element_id": element_id,
        "scoring_basis": basis,
        "sample_rate_used": sample_rate_used,
        "evidence_count_used": evidence_count_used,
        "gap_count_used": gap_count_used,
        "awarded_points": num2(D(awarded)),
        "forfeited_points": num2(D(forfeited)),
        "status": "PROVISIONAL",
    })
    DB["element_scores"][score["id"]] = score
    return ok_object(pub(score), 201)


@app.get("/accreditation/applications/<applicationId>/element-scores")
def list_scores_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [s for s in DB["element_scores"].values()
             if s["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/element-scores")
def list_scores():
    require_auth()
    items = list(DB["element_scores"].values())
    fe = request.args.get("standard_element_id")
    if fe is not None:
        items = [s for s in items if s["standard_element_id"] == fe]
    fa = request.args.get("application_id")
    if fa is not None:
        items = [s for s in items if s["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/element-scores/<scoreId>")
def get_score_ep(scoreId):
    require_auth()
    return ok_object(pub(get_score(scoreId)))


@app.post("/accreditation/element-scores/<scoreId>/finalize")
def finalize_score(scoreId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    score = get_score(scoreId)
    if score["status"] != "PROVISIONAL":
        raise ApiError("ERR_SCORE_NOT_PROVISIONAL", 409, "Score is not PROVISIONAL")
    app_e = DB["applications"][score["application_id"]]
    if app_e["status"] != "SCORING":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not SCORING")
    element = DB["standard_elements"][score["standard_element_id"]]
    cat_samples = [s for s in DB["file_review_samples"].values()
                   if s["application_id"] == app_e["id"]
                   and s["category"] == element["category"]]
    if cat_samples and not any(s["status"] == "SCORED" for s in cat_samples):
        raise ApiError("ERR_SAMPLE_NOT_SCORED", 409,
                       "A file review sample for this category is not SCORED")
    if open_gap_questions(app_e, element["id"]):
        raise ApiError("ERR_OPEN_GAP_QUESTIONS_REMAIN", 422,
                       "Open gap-flagged questions remain for this element")
    # Resurvey-basis scores re-score under the recovery rule (PRD §3.9:
    # "re-scoring those elements under the resurvey recovery rule").
    resurvey = completed_resurvey(app_e)
    recovery = compute_resurvey_recovery(app_e, element, resurvey) \
        if score["scoring_basis"] == "RESURVEY" and resurvey is not None else None
    if recovery is not None:
        awarded, forfeited = recovery
        gap_count_used = score["gap_count_used"]
        samples = category_scored_samples(app_e, element["category"])
        sample_rate_used = num4(min(D(s["timeliness_rate"]) for s in samples)) if samples else None
        evidence_count_used = sum(1 for ev in DB["evidence_items"].values()
                                  if ev["application_id"] == app_e["id"]
                                  and ev["standard_element_id"] == element["id"]
                                  and ev["status"] == "ACCEPTED")
    else:
        awarded, forfeited, sample_rate_used, evidence_count_used, gap_count_used = \
            compute_element_score(app_e, element, include_gaps=True)
    score["awarded_points"] = num2(D(awarded))
    score["forfeited_points"] = num2(D(forfeited))
    score["sample_rate_used"] = sample_rate_used
    score["evidence_count_used"] = evidence_count_used
    score["gap_count_used"] = gap_count_used
    score["status"] = "FINAL"
    _touch(score)
    recompute_app_totals(app_e)
    return ok_object(pub(score))


@app.post("/accreditation/element-scores/<scoreId>/void")
def void_score(scoreId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    score = get_score(scoreId)
    if score["status"] != "PROVISIONAL":
        raise ApiError("ERR_SCORE_NOT_PROVISIONAL", 409, "Score is not PROVISIONAL")
    score["status"] = "VOIDED"
    _touch(score)
    return ok_object(pub(score))


# ---------------------------------------------------------------------------
# Quality measure results & consumer survey scores
# ---------------------------------------------------------------------------
@app.post("/accreditation/product-line-scopes/<scopeId>/quality-measure-results")
def create_qmr(scopeId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    scope = get_scope(scopeId)
    require_plan_ownership(ctx, scope["health_plan_id"])
    b = body()
    code = req_str(b, "measure_code")
    year = req_int(b, "measurement_year")
    percentile = req_int(b, "percentile")
    reportable = req_bool(b, "is_reportable")
    if not (0 <= percentile <= 100):
        raise ApiError("ERR_INVALID_REQUEST", 400, "percentile must be 0..100")
    for q in DB["quality_measure_results"].values():
        if q["product_line_scope_id"] == scope["id"] and q["measure_code"] == code \
                and q["measurement_year"] == year:
            raise ApiError("ERR_MEASURE_RESULT_DUPLICATE", 409,
                           "Result already exists for this (scope, measure_code, year)")
    qmr = _make_entity({
        "product_line_scope_id": scope["id"],
        "measure_code": code,
        "measurement_year": year,
        "percentile": percentile,
        "is_reportable": reportable,
    })
    DB["quality_measure_results"][qmr["id"]] = qmr
    return ok_object(pub(qmr), 201)


@app.get("/accreditation/product-line-scopes/<scopeId>/quality-measure-results")
def list_qmr_of_scope(scopeId):
    require_auth()
    scope = get_scope(scopeId)
    items = [q for q in DB["quality_measure_results"].values()
             if q["product_line_scope_id"] == scope["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/quality-measure-results")
def list_qmr():
    require_auth()
    items = list(DB["quality_measure_results"].values())
    fs = request.args.get("product_line_scope_id")
    if fs is not None:
        items = [q for q in items if q["product_line_scope_id"] == fs]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/quality-measure-results/<resultId>")
def get_qmr_ep(resultId):
    require_auth()
    return ok_object(pub(get_qmr(resultId)))


@app.post("/accreditation/product-line-scopes/<scopeId>/consumer-survey-scores")
def create_css(scopeId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    scope = get_scope(scopeId)
    require_plan_ownership(ctx, scope["health_plan_id"])
    b = body()
    year = req_int(b, "survey_year")
    composite = req_num(b, "composite_score")
    resp_count = req_int(b, "response_count")
    if D(composite) < 0 or D(composite) > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "composite_score must be 0..100")
    if resp_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "response_count must be >= 1")
    css = _make_entity({
        "product_line_scope_id": scope["id"],
        "survey_year": year,
        "composite_score": float(D(composite)),
        "response_count": resp_count,
    })
    DB["consumer_survey_scores"][css["id"]] = css
    return ok_object(pub(css), 201)


@app.get("/accreditation/product-line-scopes/<scopeId>/consumer-survey-scores")
def list_css_of_scope(scopeId):
    require_auth()
    scope = get_scope(scopeId)
    items = [c for c in DB["consumer_survey_scores"].values()
             if c["product_line_scope_id"] == scope["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/consumer-survey-scores")
def list_css():
    require_auth()
    items = list(DB["consumer_survey_scores"].values())
    fs = request.args.get("product_line_scope_id")
    if fs is not None:
        items = [c for c in items if c["product_line_scope_id"] == fs]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/consumer-survey-scores/<consumerSurveyScoreId>")
def get_css_ep(consumerSurveyScoreId):
    require_auth()
    return ok_object(pub(get_css(consumerSurveyScoreId)))


# ---------------------------------------------------------------------------
# Corrective action plans
# ---------------------------------------------------------------------------
@app.post("/accreditation/applications/<applicationId>/corrective-action-plans")
def create_cap(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    b = body()
    element_id = req_str(b, "standard_element_id")
    gap_desc = req_str(b, "gap_description")
    due = req_date(b, "due_date")
    if app_e["status"] not in ("DECIDED", "CORRECTIVE_ACTION"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application must be DECIDED or CORRECTIVE_ACTION")
    element = get_element(element_id)
    if element["standards_edition_id"] != app_e["standards_edition_id"]:
        raise ApiError("ERR_ELEMENT_EDITION_MISMATCH", 422,
                       "Element does not belong to the application's edition")
    for c in DB["corrective_action_plans"].values():
        if c["application_id"] == app_e["id"] and c["standard_element_id"] == element_id:
            raise ApiError("ERR_CAP_EXISTS", 409,
                           "A non-VOIDED CAP already exists for this element")
    cap = _make_entity({
        "application_id": app_e["id"],
        "standard_element_id": element_id,
        "gap_description": gap_desc,
        "due_date": due.isoformat(),
        "is_overdue": False,
        "origin": "MANUAL",
        "status": "OPEN",
    })
    cap["is_overdue"] = cap_is_overdue(cap)
    DB["corrective_action_plans"][cap["id"]] = cap
    return ok_object(pub(cap), 201)


@app.get("/accreditation/applications/<applicationId>/corrective-action-plans")
def list_caps_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [c for c in DB["corrective_action_plans"].values()
             if c["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/corrective-action-plans")
def list_caps():
    require_auth()
    items = list(DB["corrective_action_plans"].values())
    fe = request.args.get("standard_element_id")
    if fe is not None:
        items = [c for c in items if c["standard_element_id"] == fe]
    fa = request.args.get("application_id")
    if fa is not None:
        items = [c for c in items if c["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/corrective-action-plans/<capId>")
def get_cap_ep(capId):
    require_auth()
    return ok_object(pub(get_cap(capId)))


@app.post("/accreditation/corrective-action-plans/<capId>/submit-evidence")
def submit_cap_evidence(capId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    cap = get_cap(capId)
    app_e = DB["applications"][cap["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    body()  # evidence_summary accepted but not validated beyond shape
    if cap["status"] != "OPEN":
        raise ApiError("ERR_CAP_INVALID_STATE", 409, "CAP is not OPEN")
    if app_e["status"] != "CORRECTIVE_ACTION":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not CORRECTIVE_ACTION")
    cap["status"] = "EVIDENCE_SUBMITTED"
    _touch(cap)
    return ok_object(pub(cap))


@app.post("/accreditation/corrective-action-plans/<capId>/verify")
def verify_cap(capId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    cap = get_cap(capId)
    b = body()
    approved = req_bool(b, "approved")
    if cap["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError("ERR_CAP_INVALID_STATE", 409, "CAP is not EVIDENCE_SUBMITTED")
    cap["status"] = "VERIFIED" if approved else "OPEN"
    cap["is_overdue"] = cap_is_overdue(cap)
    _touch(cap)
    return ok_object(pub(cap))


# ---------------------------------------------------------------------------
# Outcomes & public display
# ---------------------------------------------------------------------------
@app.post("/accreditation/applications/<applicationId>/outcome")
def decide_outcome(applicationId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    app_e = get_application(applicationId)
    for o in DB["outcomes"].values():
        if o["application_id"] == app_e["id"]:
            raise ApiError("ERR_OUTCOME_ALREADY_EXISTS", 409,
                           "Application already has an outcome; use revise")
    if app_e["status"] != "SCORING":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not SCORING")
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == app_e["standards_edition_id"]]
    final_elements = {s["standard_element_id"]
                      for s in DB["element_scores"].values()
                      if s["application_id"] == app_e["id"] and s["status"] == "FINAL"}
    if any(e["id"] not in final_elements for e in elements):
        raise ApiError("ERR_ELEMENT_SCORES_INCOMPLETE", 422,
                       "Some edition element lacks a FINAL non-VOIDED score")
    samples = [s for s in DB["file_review_samples"].values()
               if s["application_id"] == app_e["id"]]
    if any(s["status"] != "SCORED" for s in samples):
        raise ApiError("ERR_SAMPLE_NOT_SCORED", 409, "A file review sample is not SCORED")
    composite, bonus, mp_fail, status = compute_decision(app_e)
    decided_at = _ts(CLOCK.now())
    outcome = _make_entity({
        "application_id": app_e["id"],
        "composite_score": composite,
        "measure_bonus": bonus,
        "must_pass_failure_count": mp_fail,
        "status": status,
        "decision_sequence": 1,
        "published": False,
        "public_display_until": None,
        "is_publicly_displayed": False,
        "decided_at": decided_at,
    })
    DB["outcomes"][outcome["id"]] = outcome
    app_transition(app_e, "DECIDED")
    post_decision_cascade(app_e, parse_dt(decided_at, "decided_at"))
    return ok_object(outcome_view(outcome), 201)


@app.get("/accreditation/applications/<applicationId>/outcome")
def get_app_outcome(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [o for o in DB["outcomes"].values() if o["application_id"] == app_e["id"]]
    items = sorted(items, key=lambda o: o["_seq"])
    return ok_list([outcome_view(o) for o in items], len(items), len(items) or 10, 0)


@app.get("/accreditation/outcomes")
def list_outcomes():
    require_auth()
    items = list(DB["outcomes"].values())
    fa = request.args.get("application_id")
    if fa is not None:
        items = [o for o in items if o["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list([outcome_view(o) for o in page], total, limit, offset)


@app.get("/accreditation/outcomes/<outcomeId>")
def get_outcome_ep(outcomeId):
    require_auth()
    return ok_object(outcome_view(get_outcome(outcomeId)))


@app.post("/accreditation/outcomes/<outcomeId>/revise")
def revise_outcome(outcomeId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    outcome = get_outcome(outcomeId)
    app_e = DB["applications"][outcome["application_id"]]
    if app_e["status"] != "SCORING":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not SCORING")
    elements = [e for e in DB["standard_elements"].values()
                if e["standards_edition_id"] == app_e["standards_edition_id"]]
    final_elements = {s["standard_element_id"]
                      for s in DB["element_scores"].values()
                      if s["application_id"] == app_e["id"] and s["status"] == "FINAL"}
    if any(e["id"] not in final_elements for e in elements):
        raise ApiError("ERR_ELEMENT_SCORES_INCOMPLETE", 422,
                       "Some edition element lacks a FINAL non-VOIDED score")
    samples = [s for s in DB["file_review_samples"].values()
               if s["application_id"] == app_e["id"]]
    if any(s["status"] != "SCORED" for s in samples):
        raise ApiError("ERR_SAMPLE_NOT_SCORED", 409, "A file review sample is not SCORED")
    composite, bonus, mp_fail, status = compute_decision(app_e)
    outcome["composite_score"] = composite
    outcome["measure_bonus"] = bonus
    outcome["must_pass_failure_count"] = mp_fail
    outcome["status"] = status
    outcome["decision_sequence"] += 1
    outcome["decided_at"] = _ts(CLOCK.now())
    _touch(outcome)
    app_transition(app_e, "DECIDED")
    post_decision_cascade(app_e, parse_dt(outcome["decided_at"], "decided_at"))
    return ok_object(outcome_view(outcome))


@app.post("/accreditation/outcomes/<outcomeId>/publish")
def publish_outcome(outcomeId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    outcome = get_outcome(outcomeId)
    decided = parse_dt(outcome["decided_at"], "decided_at")
    until = add_months(decided, 36)
    outcome["published"] = True
    outcome["public_display_until"] = _ts(until)
    _touch(outcome)
    recompute_public_display()
    return ok_object(outcome_view(outcome))


@app.get("/accreditation/public/plans/<planId>/accreditation-status")
def public_status(planId):
    require_auth()
    plan = get_plan(planId)
    scopes = [s for s in DB["product_line_scopes"].values()
              if s["health_plan_id"] == plan["id"]]
    scopes = sorted(scopes, key=lambda s: s["_seq"])
    out_scopes = []
    for scope in scopes:
        displayed = None
        for o in DB["outcomes"].values():
            oapp = DB["applications"][o["application_id"]]
            if oapp["product_line_scope_id"] != scope["id"]:
                continue
            if outcome_is_publicly_displayed(o):
                displayed = o
                break
        entry = {
            "product_line_scope_id": scope["id"],
            "product_line": scope["product_line"],
            "accreditation_status": displayed["status"] if displayed else None,
            "outcome_id": displayed["id"] if displayed else None,
        }
        out_scopes.append(entry)
    return ok_object({
        "plan_id": plan["id"],
        "plan_name": plan["name"],
        "scopes": out_scopes,
    })


# ---------------------------------------------------------------------------
# Annual reports
# ---------------------------------------------------------------------------
@app.post("/accreditation/applications/<applicationId>/annual-reports")
def create_report(applicationId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    app_e = get_application(applicationId)
    require_plan_ownership(ctx, app_e["health_plan_id"])
    b = body()
    year = req_int(b, "reporting_year")
    attestation = req_str(b, "attestation")
    if len(attestation) < 20:
        raise ApiError("ERR_INVALID_REQUEST", 400, "attestation must be >= 20 characters")
    # application must be CLOSED or CORRECTIVE_ACTION with decided ACCREDITED-ish outcome
    ok = False
    if app_e["status"] == "CLOSED":
        ok = True
    elif app_e["status"] == "CORRECTIVE_ACTION":
        for o in DB["outcomes"].values():
            if o["application_id"] == app_e["id"] and \
                    o["status"] in ("ACCREDITED", "ACCREDITED_WITH_CAP"):
                ok = True
                break
    if not ok:
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application must be CLOSED or CORRECTIVE_ACTION with an accredited outcome")
    for r in DB["annual_reports"].values():
        if r["application_id"] == app_e["id"] and r["reporting_year"] == year:
            raise ApiError("ERR_ANNUAL_REPORT_DUPLICATE", 409,
                           "A report already exists for this reporting_year")
    due = datetime(year + 1, 3, 31, 23, 59, 59, tzinfo=timezone.utc)
    rep = _make_entity({
        "application_id": app_e["id"],
        "reporting_year": year,
        "attestation": attestation,
        "due_date": _ts(due),
        "is_late": False,
        "status": "DRAFT",
    })
    DB["annual_reports"][rep["id"]] = rep
    return ok_object(pub(rep), 201)


@app.get("/accreditation/applications/<applicationId>/annual-reports")
def list_reports_of_app(applicationId):
    require_auth()
    app_e = get_application(applicationId)
    items = [r for r in DB["annual_reports"].values() if r["application_id"] == app_e["id"]]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/annual-reports")
def list_reports():
    require_auth()
    items = list(DB["annual_reports"].values())
    fa = request.args.get("application_id")
    if fa is not None:
        items = [r for r in items if r["application_id"] == fa]
    page, total, limit, offset = paginate(items)
    return ok_list(pub_list(page), total, limit, offset)


@app.get("/accreditation/annual-reports/<reportId>")
def get_report_ep(reportId):
    require_auth()
    return ok_object(pub(get_report(reportId)))


@app.post("/accreditation/annual-reports/<reportId>/submit")
def submit_report(reportId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    rep = get_report(reportId)
    app_e = DB["applications"][rep["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    if rep["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409, "Report is not DRAFT")
    due = parse_dt(rep["due_date"], "due_date")
    if CLOCK.now() > due:
        rep["status"] = "LATE"
        rep["is_late"] = True
    else:
        rep["status"] = "SUBMITTED"
        rep["is_late"] = False
    _touch(rep)
    return ok_object(pub(rep))


@app.post("/accreditation/annual-reports/<reportId>/review")
def review_report(reportId):
    ctx = require_auth()
    require_role(ctx, ["AccreditationOfficer"])
    rep = get_report(reportId)
    b = body()
    accepted = req_bool(b, "accepted")
    if rep["status"] not in ("SUBMITTED", "LATE"):
        raise ApiError("ERR_REPORT_INVALID_STATE", 409,
                       "Report is not SUBMITTED or LATE")
    rep["status"] = "ACCEPTED" if accepted else "RETURNED"
    _touch(rep)
    return ok_object(pub(rep))


@app.post("/accreditation/annual-reports/<reportId>/reopen")
def reopen_report(reportId):
    ctx = require_auth()
    require_role(ctx, ["PlanCoordinator"])
    rep = get_report(reportId)
    app_e = DB["applications"][rep["application_id"]]
    require_plan_ownership(ctx, app_e["health_plan_id"])
    if rep["status"] != "RETURNED":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409, "Report is not RETURNED")
    rep["status"] = "DRAFT"
    rep["is_late"] = False
    _touch(rep)
    return ok_object(pub(rep))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
