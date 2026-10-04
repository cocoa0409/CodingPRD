"""Single-file Flask implementation of the Retail Shopper Insights API.

All domain state lives in module-level dicts, initialized empty on boot.
The logical clock is a module-level value defaulting to 2026-09-01T00:00:00Z.
"""

import math
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

# --------------------------------------------------------------------------
# Constants (contract-pinned)
# --------------------------------------------------------------------------

MIN_CELL_SIZE = 20
MIN_SEGMENT_SIZE = 25

CREDIT_COSTS = {"CATEGORY": 1, "BRAND_OWN": 2, "COMPETITOR_BLIND": 3}
TIER_ALLOWED_REPORT_TYPES = {
    "TIER_CATEGORY": {"CATEGORY"},
    "TIER_BRAND": {"CATEGORY", "BRAND_OWN"},
    "TIER_PORTFOLIO": {"CATEGORY", "BRAND_OWN", "COMPETITOR_BLIND"},
}
REDISTRIBUTION_CLASSES = {
    "CATEGORY": "SHAREABLE_AGGREGATE",
    "BRAND_OWN": "INTERNAL_ONLY",
    "COMPETITOR_BLIND": "MODELED_DERIVED",
}

RATE_CENTS_PER_HOUSEHOLD = 2.5
REACH_RATES = {"COUPON": 0.8, "RETAIL_MEDIA": 0.5}
CHANNEL_MULTIPLIERS = {"COUPON": 1.0, "RETAIL_MEDIA": 1.3}
ALLOWED_CHANNELS = ("COUPON", "RETAIL_MEDIA")
MEASUREMENT_WINDOW_DAYS = 28

COMPLIANCE_SCORE_INITIAL = 1000
LATE_SUBMISSION_PENALTY = 10
MISSED_DELIVERABLE_PENALTY = 25

MAX_QUERY_COST = 100
QUERY_COST_MINIMUM = 1
ROWS_PER_UNIT = 1000
TIER_MULTIPLIERS = {"TIER_CATEGORY": 1.0, "TIER_BRAND": 1.25, "TIER_PORTFOLIO": 1.5}

COVARIATE_WEIGHT = 0.5

CYCLE_OPEN_LEAD_DAYS = 14
CYCLE_GAP_MIN_DAYS = 7

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

ROLES = ("RetailerAdmin", "CategoryManager", "InsightsScientist", "SupplierAnalyst", "DataSteward")
ANY_ROLE = set(ROLES)

# --------------------------------------------------------------------------
# In-memory store (starts empty every boot; no seeding)
# --------------------------------------------------------------------------

STORE = {
    "supplier_accounts": {},
    "subscription_contracts": {},
    "category_scopes": {},
    "panel_households": {},
    "panel_order": [],
    "insight_reports": {},
    "audience_segments": {},
    "segment_activations": {},
    "incrementality_studies": {},
    "clean_room_grants": {},
    "clean_room_queries": {},
    "line_review_cycles": {},
    "review_deliverables": {},
    "new_item_forecasts": {},
    "audit_events": {},
}

CLOCK = {"now": DEFAULT_CLOCK}

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_auth(msg="X-User-ID and X-User-Role headers must be present and well-formed"):
    raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_forbidden(msg="Role not permitted for this endpoint"):
    raise ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_not_found(msg="Resource not found"):
    raise ApiError("ERR_RESOURCE_NOT_FOUND", msg, 404)


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d{1,6})?Z$")


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def parse_ts(value):
    """Parse 'YYYY-MM-DDTHH:MM:SS[.fff]Z' into an aware datetime. Raise ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _TS_RE.match(value)
    if not m:
        raise ValueError("bad timestamp")
    base, frac = m.group(1), m.group(2)
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if frac:
        digits = frac[1:].ljust(6, "0")[:6]
        dt = dt.replace(microsecond=int(digits))
    return dt


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(value):
    """Parse an ISO date 'YYYY-MM-DD' into a date. Raise ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.strptime(value, "%Y-%m-%d").date()


def clock_now():
    return parse_ts(CLOCK["now"])


def date_to_dt(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------


def _strip_private(record):
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if not k.startswith("_")}
    return record


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    if isinstance(data, list):
        data = [_strip_private(d) for d in data]
    else:
        data = _strip_private(data)
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
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


def paginate(items):
    """Apply limit/offset per contract; sort by created_at ascending."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda x: x["created_at"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------


def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        err_auth()
    if not role or role not in ROLES:
        err_auth()
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        err_forbidden()


def require_analyst_owns_account(uid, role, supplier_account_id):
    """SupplierAnalyst writes: X-User-ID must equal the owning account id."""
    if role == "SupplierAnalyst" and uid != supplier_account_id:
        err_forbidden("SupplierAnalyst X-User-ID must equal the owning SupplierAccount id")


# --------------------------------------------------------------------------
# Common-field helpers
# --------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, common=True):
    record["id"] = new_id()
    record["created_at"] = now_iso()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def write_audit(event_type, actor_role, actor_user_id, subject_type, subject_id, detail=""):
    ev = stamp_new({
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "detail": detail,
    }, common=False)
    STORE["audit_events"][ev["id"]] = ev
    return ev


# --------------------------------------------------------------------------
# JSON body helpers
# --------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        err_invalid(f"{field} is required and must be a non-empty string")
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err_invalid(f"{field} is required and must be an integer")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        err_invalid(f"{field} is required and must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        err_invalid(f"{field} must be one of {sorted(allowed)}")
    return v


def req_list(data, field, allow_empty=False):
    v = data.get(field)
    if not isinstance(v, list) or (not allow_empty and not v):
        err_invalid(f"{field} is required and must be a non-empty array")
    return v


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err_invalid(f"{field} must be an integer when provided")
    return v


def opt_str(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if not isinstance(v, str) or not v:
        err_invalid(f"{field} must be a non-empty string when provided")
    return v


# --------------------------------------------------------------------------
# Lookup helpers (existence checks)
# --------------------------------------------------------------------------


def get_or_404(bucket, rid):
    rec = STORE[bucket].get(rid)
    if rec is None:
        err_not_found(f"{bucket[:-1]} {rid} not found")
    return rec


def contract_of_report(report):
    return STORE["subscription_contracts"].get(report["contract_id"])


def contract_of_segment(segment):
    return STORE["subscription_contracts"].get(segment["contract_id"])


def segment_of_activation(act):
    return STORE["audience_segments"].get(act["segment_id"])


def account_of_contract(contract):
    return contract["supplier_account_id"]


def category_scopes_of(contract_id):
    return [s for s in STORE["category_scopes"].values() if s["contract_id"] == contract_id]


def category_in_scope(contract, category_code):
    return any(s["category_code"] == category_code for s in category_scopes_of(contract["id"]))


def scope_brand_codes(contract, category_code):
    for s in category_scopes_of(contract["id"]):
        if s["category_code"] == category_code:
            return list(s.get("brand_codes") or [])
    return []


def derived_contract_fields(contract):
    contract["report_credits_available"] = (
        contract["report_credit_allowance"]
        - contract["report_credits_reserved"]
        - contract["report_credits_consumed"]
    )


def contract_view(contract):
    derived_contract_fields(contract)
    return contract


def grant_view(grant):
    grant["query_budget_remaining"] = grant["query_budget_total"] - grant["query_budget_consumed"]
    return grant


# --------------------------------------------------------------------------
# Lazy clock-driven transitions
# --------------------------------------------------------------------------


def lazy_cycle(cycle):
    if cycle["status"] == "SCHEDULED" and clock_now() >= parse_ts(cycle["open_at"]):
        cycle["status"] = "OPEN"
        touch(cycle)


def lazy_grant(grant):
    if grant["status"] == "APPROVED" and clock_now() >= parse_ts(grant["valid_until"]):
        grant["status"] = "EXPIRED"
        touch(grant)


def _brand_metric(household, brand_code):
    for entry in household.get("brand_metrics") or []:
        if entry.get("brand_code") == brand_code:
            return entry
    return None


def _compute_study_analysis(study):
    brand = study["brand_code"]
    test_spends, control_spends = [], []
    test_bases, control_bases = [], []
    for pair in study["matched_pairs"]:
        t = next((h for h in STORE["panel_households"].values() if h["household_ref"] == pair["test_household_ref"]), None)
        c = next((h for h in STORE["panel_households"].values() if h["household_ref"] == pair["control_household_ref"]), None)
        if t is not None:
            m = _brand_metric(t, brand)
            if m:
                test_spends.append(m.get("campaign_spend_cents", 0))
                test_bases.append(m.get("baseline_spend_cents", 0))
        if c is not None:
            m = _brand_metric(c, brand)
            if m:
                control_spends.append(m.get("campaign_spend_cents", 0))
                control_bases.append(m.get("baseline_spend_cents", 0))
    if not test_spends or not control_spends:
        study["test_avg_spend_cents"] = 0
        study["control_avg_spend_cents"] = 0
        study["provisional_lift_pct"] = 0.0
        study["final_lift_pct"] = 0.0
        return
    test_avg = sum(test_spends) / len(test_spends)
    control_avg = sum(control_spends) / len(control_spends)
    test_base_avg = sum(test_bases) / len(test_bases)
    control_base_avg = sum(control_bases) / len(control_bases)
    study["test_avg_spend_cents"] = test_avg
    study["control_avg_spend_cents"] = control_avg
    if control_avg == 0:
        study["provisional_lift_pct"] = 0.0
        study["final_lift_pct"] = 0.0
        return
    provisional = (test_avg - control_avg) / control_avg * 100
    bias = COVARIATE_WEIGHT * (test_base_avg - control_base_avg)
    final = (test_avg - control_avg - bias) / control_avg * 100
    study["provisional_lift_pct"] = round2(provisional)
    study["final_lift_pct"] = round2(final)


def lazy_study(study):
    if study["status"] == "RUNNING":
        try:
            window_end_dt = date_to_dt(parse_date(study["window_end"]))
        except ValueError:
            return
        if clock_now() >= window_end_dt:
            _compute_study_analysis(study)
            study["status"] = "ANALYSIS"
            touch(study)


def lazy_activation(act):
    if act["status"] == "LAUNCHED" and act.get("launched_at"):
        deadline = parse_ts(act["launched_at"]) + timedelta(days=MEASUREMENT_WINDOW_DAYS)
        if clock_now() >= deadline:
            act["status"] = "COMPLETED"
            touch(act)


def round2(value):
    """Round half-up to 2 decimal places."""
    return math.floor(value * 100 + 0.5) / 100.0


# --------------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 400))


# ==========================================================================
# Logical clock
# ==========================================================================


@app.post("/shopper-insights/_clock/set_current_utc")
def set_clock():
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    to_iso = data.get("to_iso8601")
    try:
        dt = parse_ts(to_iso)
    except (ValueError, TypeError):
        err_invalid("to_iso8601 must be an ISO 8601 UTC timestamp")
    CLOCK["now"] = fmt_ts(dt)
    return ok({"current_utc": CLOCK["now"]})


# ==========================================================================
# Supplier accounts
# ==========================================================================


@app.post("/shopper-insights/supplier-accounts")
def create_account():
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    account = stamp_new({
        "account_name": req_str(data, "account_name"),
        "region": req_str(data, "region"),
        "status": "ACTIVE",
    })
    STORE["supplier_accounts"][account["id"]] = account
    return ok(account, 201)


@app.get("/shopper-insights/supplier-accounts/<account_id>")
def get_account(account_id):
    actor()
    account = get_or_404("supplier_accounts", account_id)
    return ok(account)


@app.get("/shopper-insights/supplier-accounts/<account_id>/subscription-contracts")
def list_account_contracts(account_id):
    actor()
    get_or_404("supplier_accounts", account_id)
    items = [c for c in STORE["subscription_contracts"].values() if c["supplier_account_id"] == account_id]
    for c in items:
        derived_contract_fields(c)
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.get("/shopper-insights/supplier-accounts/<account_id>/clean-room-grants")
def list_account_grants(account_id):
    actor()
    get_or_404("supplier_accounts", account_id)
    items = [g for g in STORE["clean_room_grants"].values() if g["supplier_account_id"] == account_id]
    for g in items:
        lazy_grant(g)
        grant_view(g)
    page, meta = paginate(items)
    return ok(page, pagination=meta)


# ==========================================================================
# Subscription contracts
# ==========================================================================


@app.post("/shopper-insights/supplier-accounts/<account_id>/subscription-contracts")
def create_contract(account_id):
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    tier = req_enum(data, "tier", TIER_ALLOWED_REPORT_TYPES.keys())
    allowance = req_int(data, "report_credit_allowance")
    budget = req_int(data, "activation_budget_cents")
    redistribution = req_bool(data, "redistribution_allowed")
    modeled = req_bool(data, "modeled_derivation_allowed")
    account = get_or_404("supplier_accounts", account_id)
    existing_active = any(
        c for c in STORE["subscription_contracts"].values()
        if c["supplier_account_id"] == account_id and c["status"] == "ACTIVE"
    )
    if existing_active:
        raise ApiError("ERR_ACCOUNT_HAS_ACTIVE_CONTRACT", "Account already has an ACTIVE contract", 422)
    contract = stamp_new({
        "supplier_account_id": account["id"],
        "tier": tier,
        "status": "ACTIVE",
        "report_credit_allowance": allowance,
        "report_credits_reserved": 0,
        "report_credits_consumed": 0,
        "activation_budget_cents": budget,
        "activation_budget_spent_cents": 0,
        "compliance_score": COMPLIANCE_SCORE_INITIAL,
        "redistribution_allowed": redistribution,
        "modeled_derivation_allowed": modeled,
    })
    derived_contract_fields(contract)
    STORE["subscription_contracts"][contract["id"]] = contract
    return ok(contract_view(contract), 201)


@app.get("/shopper-insights/subscription-contracts/<contract_id>")
def get_contract(contract_id):
    actor()
    contract = get_or_404("subscription_contracts", contract_id)
    return ok(contract_view(contract))


@app.post("/shopper-insights/subscription-contracts/<contract_id>/amend")
def amend_contract(contract_id):
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    expected = data.get("expected_contract_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        err_invalid("expected_contract_version is required and must be an integer")
    contract = get_or_404("subscription_contracts", contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Amend requires contract status ACTIVE", 409)
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION", "expected_contract_version does not match current version", 412)
    delta = data.get("credit_allowance_delta")
    if delta is not None:
        if isinstance(delta, bool) or not isinstance(delta, int):
            err_invalid("credit_allowance_delta must be an integer")
        new_allowance = contract["report_credit_allowance"] + delta
        if contract["report_credits_consumed"] + contract["report_credits_reserved"] > new_allowance:
            raise ApiError("ERR_ALLOWANCE_BELOW_CONSUMED", "Amendment would set allowance below consumed + reserved", 402)
        contract["report_credit_allowance"] = new_allowance
    new_tier = data.get("tier")
    if new_tier is not None:
        if new_tier not in TIER_ALLOWED_REPORT_TYPES:
            err_invalid("tier must be one of TIER_CATEGORY, TIER_BRAND, TIER_PORTFOLIO")
        contract["tier"] = new_tier
    add_codes = data.get("add_category_codes") or []
    remove_codes = data.get("remove_category_codes") or []
    if not isinstance(add_codes, list) or not isinstance(remove_codes, list):
        err_invalid("add_category_codes and remove_category_codes must be arrays")
    for code in add_codes:
        if not category_in_scope(contract, code):
            scope = stamp_new({
                "contract_id": contract["id"],
                "category_code": code,
                "brand_codes": [],
            }, common=False)
            STORE["category_scopes"][scope["id"]] = scope
    for code in remove_codes:
        for scope in list(STORE["category_scopes"].values()):
            if scope["contract_id"] == contract["id"] and scope["category_code"] == code:
                del STORE["category_scopes"][scope["id"]]
    touch(contract)
    derived_contract_fields(contract)
    return ok(contract_view(contract))


@app.post("/shopper-insights/subscription-contracts/<contract_id>/suspend")
def suspend_contract(contract_id):
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    contract = get_or_404("subscription_contracts", contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Suspend requires contract status ACTIVE", 409)
    contract["status"] = "SUSPENDED"
    touch(contract)
    # Cascade B: cancel open reports of this contract with refund
    cancelled_report_ids = []
    for report in STORE["insight_reports"].values():
        if report["contract_id"] == contract["id"] and report["status"] in ("REQUESTED", "GENERATING"):
            report["status"] = "CANCELLED"
            contract["report_credits_reserved"] -= report["credit_cost"]
            touch(report)
            cancelled_report_ids.append(report["id"])
    # Cascade C: block PLANNED deliverables backed by cancelled reports
    for d in STORE["review_deliverables"].values():
        if d["insight_report_id"] in cancelled_report_ids and d["status"] == "PLANNED":
            d["status"] = "BLOCKED"
            touch(d)
            # Cascade D: decrement the owning cycle's planned_open_count
            cycle = STORE["line_review_cycles"].get(d["cycle_id"])
            if cycle is not None:
                cycle["planned_open_count"] -= 1
                touch(cycle)
    derived_contract_fields(contract)
    return ok(contract_view(contract))


@app.post("/shopper-insights/subscription-contracts/<contract_id>/terminate")
def terminate_contract(contract_id):
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    contract = get_or_404("subscription_contracts", contract_id)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Terminate requires contract status ACTIVE or SUSPENDED", 409)
    contract["status"] = "TERMINATED"
    touch(contract)
    derived_contract_fields(contract)
    return ok(contract_view(contract))


# ==========================================================================
# Category scopes
# ==========================================================================


@app.post("/shopper-insights/subscription-contracts/<contract_id>/category-scopes")
def add_category_scope(contract_id):
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    category_code = req_str(data, "category_code")
    brand_codes = req_list(data, "brand_codes", allow_empty=True)
    contract = get_or_404("subscription_contracts", contract_id)
    scope = stamp_new({
        "contract_id": contract["id"],
        "category_code": category_code,
        "brand_codes": brand_codes,
    }, common=False)
    STORE["category_scopes"][scope["id"]] = scope
    return ok(scope, 201)


@app.get("/shopper-insights/subscription-contracts/<contract_id>/category-scopes")
def list_category_scopes(contract_id):
    actor()
    get_or_404("subscription_contracts", contract_id)
    items = [s for s in STORE["category_scopes"].values() if s["contract_id"] == contract_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.get("/shopper-insights/subscription-contracts/<contract_id>/insight-reports")
def list_contract_reports(contract_id):
    actor()
    get_or_404("subscription_contracts", contract_id)
    items = [r for r in STORE["insight_reports"].values() if r["contract_id"] == contract_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.get("/shopper-insights/subscription-contracts/<contract_id>/audience-segments")
def list_contract_segments(contract_id):
    actor()
    get_or_404("subscription_contracts", contract_id)
    items = [s for s in STORE["audience_segments"].values() if s["contract_id"] == contract_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.get("/shopper-insights/subscription-contracts/<contract_id>/review-deliverables")
def list_contract_deliverables(contract_id):
    actor()
    get_or_404("subscription_contracts", contract_id)
    items = [d for d in STORE["review_deliverables"].values() if d["contract_id"] == contract_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.get("/shopper-insights/subscription-contracts/<contract_id>/new-item-forecasts")
def list_contract_forecasts(contract_id):
    actor()
    get_or_404("subscription_contracts", contract_id)
    items = [f for f in STORE["new_item_forecasts"].values() if f["contract_id"] == contract_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


# ==========================================================================
# Panel households (bulk ingest)
# ==========================================================================


_HOUSEHOLD_INT_FIELDS = ("recency_days", "frequency_12m", "monetary_12m_cents")


@app.post("/shopper-insights/panel-households")
def ingest_households():
    uid, role = actor()
    require_roles(role, {"RetailerAdmin"})
    data = body()
    items = req_list(data, "households", allow_empty=True)
    rejected = []
    ingested = 0
    for idx, item in enumerate(items):
        try:
            if not isinstance(item, dict):
                err_invalid("household entry must be an object")
            ref = item.get("household_ref")
            if not isinstance(ref, str) or not ref:
                err_invalid("household_ref is required and must be a non-empty string")
            record = {
                "household_ref": ref,
                "region": item.get("region", "NA"),
                "category_codes": item.get("category_codes", []),
                "recency_days": item.get("recency_days", 0),
                "frequency_12m": item.get("frequency_12m", 0),
                "monetary_12m_cents": item.get("monetary_12m_cents", 0),
                "exposed_brands": item.get("exposed_brands", []),
                "brand_metrics": item.get("brand_metrics", []),
            }
            if not isinstance(record["region"], str):
                err_invalid("region must be a string")
            if not isinstance(record["category_codes"], list):
                err_invalid("category_codes must be an array")
            if not isinstance(record["exposed_brands"], list):
                err_invalid("exposed_brands must be an array")
            if not isinstance(record["brand_metrics"], list):
                err_invalid("brand_metrics must be an array")
            for f in _HOUSEHOLD_INT_FIELDS:
                v = record[f]
                if isinstance(v, bool) or not isinstance(v, int):
                    err_invalid(f"{f} must be an integer")
            rec = stamp_new(record, common=False)
            rec["_seq"] = len(STORE["panel_order"])
            STORE["panel_households"][rec["id"]] = rec
            STORE["panel_order"].append(rec["id"])
            ingested += 1
        except ApiError as e:
            rejected.append({"index": idx, "error_id": e.error_id, "message": e.message})
    return ok({"ingested_count": ingested, "rejected": rejected})


# ==========================================================================
# Insight reports
# ==========================================================================


def _report_counts(contract, category_code):
    households = [
        h for h in (STORE["panel_households"][hid] for hid in STORE["panel_order"])
        if category_code in (h.get("category_codes") or [])
    ]
    brand_codes = set(scope_brand_codes(contract, category_code))
    household_count = len(households)
    own = sum(
        1 for h in households
        if any((m.get("brand_code") in brand_codes) for m in (h.get("brand_metrics") or []))
    )
    return household_count, own


@app.post("/shopper-insights/insight-reports")
def create_report():
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    data = body()
    contract_id = req_str(data, "contract_id")
    report_type = req_enum(data, "report_type", CREDIT_COSTS.keys())
    category_code = req_str(data, "category_code")
    period_start = req_str(data, "period_start")
    period_end = req_str(data, "period_end")
    contract = get_or_404("subscription_contracts", contract_id)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Report creation requires an ACTIVE contract", 409)
    # Referential checks: scope precedes tier (PRD 3.2)
    if not category_in_scope(contract, category_code):
        raise ApiError("ERR_CATEGORY_OUT_OF_SCOPE", "category_code not covered by contract scopes", 422)
    if report_type not in TIER_ALLOWED_REPORT_TYPES[contract["tier"]]:
        raise ApiError("ERR_TIER_INSUFFICIENT", "Contract tier does not permit this report_type", 422)
    credit_cost = CREDIT_COSTS[report_type]
    derived_contract_fields(contract)
    if contract["report_credits_available"] < credit_cost:
        raise ApiError("ERR_INSUFFICIENT_REPORT_CREDITS", "Reservation exceeds available report credits", 402)
    report = stamp_new({
        "contract_id": contract["id"],
        "report_type": report_type,
        "category_code": category_code,
        "period_start": period_start,
        "period_end": period_end,
        "status": "REQUESTED",
        "credit_cost": credit_cost,
        "household_count": None,
        "own_brand_households": None,
        "other_supplier_aggregate_households": None,
        "redistribution_class": None,
    })
    STORE["insight_reports"][report["id"]] = report
    contract["report_credits_reserved"] += credit_cost
    touch(contract)
    return ok(report, 201)


@app.get("/shopper-insights/insight-reports/<report_id>")
def get_report(report_id):
    actor()
    report = get_or_404("insight_reports", report_id)
    return ok(report)


@app.get("/shopper-insights/insight-reports/<report_id>/review-deliverables")
def list_report_deliverables(report_id):
    actor()
    get_or_404("insight_reports", report_id)
    items = [d for d in STORE["review_deliverables"].values() if d["insight_report_id"] == report_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.post("/shopper-insights/insight-reports/<report_id>/generate")
def generate_report(report_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    report = get_or_404("insight_reports", report_id)
    contract = contract_of_report(report)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if report["status"] not in ("REQUESTED", "SUPPRESSED"):
        raise ApiError("ERR_REPORT_NOT_GENERATABLE", "Generate requires report status REQUESTED or SUPPRESSED", 409)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Generate requires an ACTIVE contract", 409)
    if report["status"] == "SUPPRESSED":
        derived_contract_fields(contract)
        if contract["report_credits_available"] < report["credit_cost"]:
            raise ApiError("ERR_INSUFFICIENT_REPORT_CREDITS", "Regeneration re-reserve exceeds available credits", 402)
        contract["report_credits_reserved"] += report["credit_cost"]
        touch(contract)
    # Compute cells
    household_count, own = _report_counts(contract, report["category_code"])
    report["household_count"] = household_count
    report["own_brand_households"] = own
    if report["report_type"] == "COMPETITOR_BLIND":
        report["other_supplier_aggregate_households"] = household_count - own
    else:
        report["other_supplier_aggregate_households"] = None
    report["redistribution_class"] = REDISTRIBUTION_CLASSES[report["report_type"]]
    # Privacy threshold: only cells reported for this report_type are gated.
    # CATEGORY reports the plain household_count; BRAND_OWN and
    # COMPETITOR_BLIND additionally gate the brand-split cells.
    if report["report_type"] == "CATEGORY":
        cells = [household_count]
    elif report["report_type"] == "BRAND_OWN":
        cells = [household_count, own]
    else:
        cells = [household_count, own, report["other_supplier_aggregate_households"]]
    if any(c < MIN_CELL_SIZE for c in cells):
        report["status"] = "SUPPRESSED"
        contract["report_credits_reserved"] -= report["credit_cost"]
    else:
        report["status"] = "READY"
        contract["report_credits_reserved"] -= report["credit_cost"]
        contract["report_credits_consumed"] += report["credit_cost"]
    touch(report)
    touch(contract)
    return ok(report)


@app.post("/shopper-insights/insight-reports/<report_id>/cancel")
def cancel_report(report_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    report = get_or_404("insight_reports", report_id)
    contract = contract_of_report(report)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if report["status"] != "REQUESTED":
        raise ApiError("ERR_REPORT_NOT_CANCELLABLE", "Cancel requires report status REQUESTED", 409)
    report["status"] = "CANCELLED"
    contract["report_credits_reserved"] -= report["credit_cost"]
    touch(report)
    touch(contract)
    return ok(report)


@app.post("/shopper-insights/insight-reports/<report_id>/export")
def export_report(report_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    report = get_or_404("insight_reports", report_id)
    contract = contract_of_report(report)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if report["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "Export requires report status READY", 409)
    if not contract["redistribution_allowed"]:
        raise ApiError("ERR_REDISTRIBUTION_RESTRICTED", "Contract redistribution_allowed is false", 403)
    if report["redistribution_class"] == "MODELED_DERIVED" and not contract["modeled_derivation_allowed"]:
        raise ApiError("ERR_REDISTRIBUTION_RESTRICTED", "Contract modeled_derivation_allowed is false", 403)
    report["status"] = "DELIVERED"
    touch(report)
    write_audit("REPORT_EXPORTED", role, uid, "InsightReport", report["id"], "Report exported")
    return ok(report)


# ==========================================================================
# Audience segments
# ==========================================================================


def _compute_segment_size(segment):
    count = 0
    for hid in STORE["panel_order"]:
        h = STORE["panel_households"][hid]
        if segment["category_code"] not in (h.get("category_codes") or []):
            continue
        if segment.get("min_frequency") is not None and h["frequency_12m"] < segment["min_frequency"]:
            continue
        if segment.get("min_monetary_cents") is not None and h["monetary_12m_cents"] < segment["min_monetary_cents"]:
            continue
        if segment.get("region") is not None and h["region"] != segment["region"]:
            continue
        count += 1
    return count


@app.post("/shopper-insights/audience-segments")
def create_segment():
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    data = body()
    contract_id = req_str(data, "contract_id")
    segment_name = req_str(data, "segment_name")
    category_code = req_str(data, "category_code")
    min_frequency = opt_int(data, "min_frequency")
    min_monetary_cents = opt_int(data, "min_monetary_cents")
    region = opt_str(data, "region")
    contract = get_or_404("subscription_contracts", contract_id)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Segment creation requires an ACTIVE contract", 409)
    if not category_in_scope(contract, category_code):
        raise ApiError("ERR_CATEGORY_OUT_OF_SCOPE", "category_code not covered by contract scopes", 422)
    segment = stamp_new({
        "contract_id": contract["id"],
        "segment_name": segment_name,
        "category_code": category_code,
        "min_frequency": min_frequency,
        "min_monetary_cents": min_monetary_cents,
        "region": region,
        "size": 0,
        "status": "DRAFT",
    })
    segment["size"] = _compute_segment_size(segment)
    STORE["audience_segments"][segment["id"]] = segment
    return ok(segment, 201)


@app.get("/shopper-insights/audience-segments/<segment_id>")
def get_segment(segment_id):
    actor()
    segment = get_or_404("audience_segments", segment_id)
    return ok(segment)


@app.post("/shopper-insights/audience-segments/<segment_id>/submit")
def submit_segment(segment_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    segment = get_or_404("audience_segments", segment_id)
    contract = contract_of_segment(segment)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if segment["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_SEGMENT_NOT_SUBMITTABLE", "Submit requires status DRAFT or REJECTED", 409)
    segment["size"] = _compute_segment_size(segment)
    if segment["size"] == 0:
        raise ApiError("ERR_SEGMENT_EMPTY", "Segment size is zero at submit", 422)
    segment["status"] = "PENDING_APPROVAL"
    touch(segment)
    return ok(segment)


@app.post("/shopper-insights/audience-segments/<segment_id>/approve")
def approve_segment(segment_id):
    uid, role = actor()
    require_roles(role, {"DataSteward"})
    segment = get_or_404("audience_segments", segment_id)
    if segment["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Approve requires segment status PENDING_APPROVAL", 409)
    if segment["size"] < MIN_SEGMENT_SIZE:
        raise ApiError("ERR_SEGMENT_BELOW_MINIMUM", "Segment size below minimum at approve", 422)
    segment["status"] = "APPROVED"
    touch(segment)
    return ok(segment)


@app.post("/shopper-insights/audience-segments/<segment_id>/reject")
def reject_segment(segment_id):
    uid, role = actor()
    require_roles(role, {"DataSteward"})
    segment = get_or_404("audience_segments", segment_id)
    if segment["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Reject requires segment status PENDING_APPROVAL", 409)
    segment["status"] = "REJECTED"
    touch(segment)
    return ok(segment)


# ==========================================================================
# Segment activations
# ==========================================================================


@app.get("/shopper-insights/audience-segments/<segment_id>/activations")
def list_segment_activations(segment_id):
    actor()
    get_or_404("audience_segments", segment_id)
    items = [a for a in STORE["segment_activations"].values() if a["segment_id"] == segment_id]
    for a in items:
        lazy_activation(a)
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.post("/shopper-insights/audience-segments/<segment_id>/activations")
def create_activation(segment_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    data = body()
    expected = data.get("expected_segment_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        err_invalid("expected_segment_version is required and must be an integer")
    channels = req_list(data, "channels")
    for ch in channels:
        if ch not in ALLOWED_CHANNELS:
            err_invalid(f"channels entries must be drawn from {list(ALLOWED_CHANNELS)}")
    segment = get_or_404("audience_segments", segment_id)
    contract = contract_of_segment(segment)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if expected != segment["version"]:
        raise ApiError("ERR_STALE_SEGMENT_VERSION", "expected_segment_version does not match current version", 412)
    if segment["status"] != "APPROVED":
        raise ApiError("ERR_SEGMENT_NOT_APPROVED", "Activation requires segment status APPROVED", 409)
    if not category_in_scope(contract, segment["category_code"]):
        raise ApiError("ERR_CATEGORY_OUT_OF_SCOPE", "Segment category no longer in contract scope", 422)
    # Compute lines (per-line round then sum; rounding order pinned)
    lines = []
    total_fee = 0
    for ch in channels:
        reached = math.floor(segment["size"] * REACH_RATES[ch])
        line_fee = int(math.floor(reached * RATE_CENTS_PER_HOUSEHOLD * CHANNEL_MULTIPLIERS[ch] + 0.5))
        lines.append({"channel": ch, "households_reached": reached, "line_fee_cents": line_fee})
        total_fee += line_fee
    remaining_budget = contract["activation_budget_cents"] - contract["activation_budget_spent_cents"]
    if total_fee > remaining_budget:
        raise ApiError("ERR_ACTIVATION_BUDGET_EXCEEDED", "Activation fee exceeds remaining activation budget", 402)
    activation = stamp_new({
        "segment_id": segment["id"],
        "channels": list(channels),
        "channel_lines": lines,
        "total_fee_cents": total_fee,
        "status": "PENDING",
        "launched_at": None,
    })
    STORE["segment_activations"][activation["id"]] = activation
    contract["activation_budget_spent_cents"] += total_fee
    touch(contract)
    touch(segment)  # activation pins the segment
    return ok(activation, 201)


@app.post("/shopper-insights/segment-activations/<activation_id>/launch")
def launch_activation(activation_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    act = get_or_404("segment_activations", activation_id)
    segment = segment_of_activation(act)
    contract = contract_of_segment(segment)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if act["status"] != "PENDING":
        raise ApiError("ERR_ACTIVATION_NOT_LAUNCHABLE", "Launch requires activation status PENDING", 409)
    if segment["status"] != "APPROVED":
        raise ApiError("ERR_SEGMENT_NOT_APPROVED", "Launch requires segment status APPROVED", 409)
    if not category_in_scope(contract, segment["category_code"]):
        raise ApiError("ERR_CATEGORY_OUT_OF_SCOPE", "Segment category no longer in contract scope", 422)
    act["status"] = "LAUNCHED"
    act["launched_at"] = CLOCK["now"]
    touch(act)
    write_audit("ACTIVATION_LAUNCHED", role, uid, "SegmentActivation", act["id"], "Activation launched")
    return ok(act)


@app.post("/shopper-insights/segment-activations/<activation_id>/halt")
def halt_activation(activation_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    act = get_or_404("segment_activations", activation_id)
    segment = segment_of_activation(act)
    contract = contract_of_segment(segment)
    require_analyst_owns_account(uid, role, contract["supplier_account_id"])
    if act["status"] != "LAUNCHED":
        raise ApiError("ERR_INVALID_STATE", "Halt requires activation status LAUNCHED", 409)
    act["status"] = "HALTED"
    touch(act)
    return ok(act)


# ==========================================================================
# Incrementality studies
# ==========================================================================


def _run_matching(study):
    brand = study["brand_code"]
    category = study["category_code"]
    panel = [STORE["panel_households"][hid] for hid in STORE["panel_order"]]
    treated = [h for h in panel if category in (h.get("category_codes") or []) and brand in (h.get("exposed_brands") or [])]
    controls = [h for h in panel if category in (h.get("category_codes") or []) and brand not in (h.get("exposed_brands") or [])]
    treated.sort(key=lambda h: h["_seq"])
    controls.sort(key=lambda h: h["_seq"])
    chosen = set()
    pairs = []
    for t in treated:
        best = None
        best_key = None
        for c in controls:
            if c["id"] in chosen:
                continue
            dist = (
                abs(t["recency_days"] - c["recency_days"])
                + abs(t["frequency_12m"] - c["frequency_12m"])
                + abs(t["monetary_12m_cents"] - c["monetary_12m_cents"]) / 1000.0
            )
            key = (dist, c["_seq"])
            if best_key is None or key < best_key:
                best_key = key
                best = c
        if best is None:
            break  # control pool exhausted; drop remaining treated
        chosen.add(best["id"])
        pairs.append({
            "test_household_ref": t["household_ref"],
            "control_household_ref": best["household_ref"],
        })
    study["matched_pairs"] = pairs


@app.post("/shopper-insights/incrementality-studies")
def create_study():
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    data = body()
    study = stamp_new({
        "brand_code": req_str(data, "brand_code"),
        "category_code": req_str(data, "category_code"),
        "window_start": req_str(data, "window_start"),
        "window_end": req_str(data, "window_end"),
        "status": "DRAFT",
        "matched_pairs": [],
        "test_avg_spend_cents": None,
        "control_avg_spend_cents": None,
        "provisional_lift_pct": None,
        "final_lift_pct": None,
    })
    STORE["incrementality_studies"][study["id"]] = study
    return ok(study, 201)


@app.get("/shopper-insights/incrementality-studies/<study_id>")
def get_study(study_id):
    actor()
    study = get_or_404("incrementality_studies", study_id)
    lazy_study(study)
    return ok(study)


@app.post("/shopper-insights/incrementality-studies/<study_id>/start")
def start_study(study_id):
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    study = get_or_404("incrementality_studies", study_id)
    if study["status"] != "DRAFT":
        raise ApiError("ERR_STUDY_INVALID_TRANSITION", "Start requires study status DRAFT", 409)
    _run_matching(study)
    study["status"] = "RUNNING"
    touch(study)
    lazy_study(study)
    return ok(study)


@app.post("/shopper-insights/incrementality-studies/<study_id>/submit-review")
def submit_review_study(study_id):
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    study = get_or_404("incrementality_studies", study_id)
    lazy_study(study)
    if study["status"] != "ANALYSIS":
        raise ApiError("ERR_STUDY_INVALID_TRANSITION", "Submit-review requires study status ANALYSIS", 409)
    study["status"] = "IN_REVIEW"
    touch(study)
    return ok(study)


@app.post("/shopper-insights/incrementality-studies/<study_id>/publish")
def publish_study(study_id):
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    study = get_or_404("incrementality_studies", study_id)
    lazy_study(study)
    if study["status"] != "IN_REVIEW":
        raise ApiError("ERR_STUDY_INVALID_TRANSITION", "Publish requires study status IN_REVIEW", 409)
    study["status"] = "PUBLISHED"
    touch(study)
    return ok(study)


@app.post("/shopper-insights/incrementality-studies/<study_id>/revise")
def revise_study(study_id):
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    study = get_or_404("incrementality_studies", study_id)
    lazy_study(study)
    if study["status"] != "IN_REVIEW":
        raise ApiError("ERR_STUDY_INVALID_TRANSITION", "Revise requires study status IN_REVIEW", 409)
    _run_matching(study)
    study["status"] = "RUNNING"
    touch(study)
    # The lazy RUNNING -> ANALYSIS auto-transition fires on subsequent reads,
    # not within this response: revise visibly returns the study to RUNNING.
    return ok(study)


# ==========================================================================
# Clean-room grants and queries
# ==========================================================================


def _parse_window(data, field):
    value = data.get(field)
    try:
        dt = parse_ts(value)
    except (ValueError, TypeError):
        err_invalid(f"{field} must be an ISO 8601 UTC timestamp")
    return value, dt


@app.post("/shopper-insights/clean-room-grants")
def create_grant():
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    data = body()
    account_id = req_str(data, "supplier_account_id")
    valid_from_str, valid_from_dt = _parse_window(data, "valid_from")
    valid_until_str, valid_until_dt = _parse_window(data, "valid_until")
    budget_total = req_int(data, "query_budget_total")
    account = get_or_404("supplier_accounts", account_id)
    require_analyst_owns_account(uid, role, account_id)
    # Temporal: half-open windows must not overlap existing REQUESTED/APPROVED for the account
    for g in STORE["clean_room_grants"].values():
        if g["supplier_account_id"] != account_id or g["status"] not in ("REQUESTED", "APPROVED"):
            continue
        g_from = parse_ts(g["valid_from"])
        g_until = parse_ts(g["valid_until"])
        if valid_from_dt < g_until and g_from < valid_until_dt:
            raise ApiError("ERR_WINDOW_OVERLAP", "Grant window overlaps an existing grant window", 409)
    grant = stamp_new({
        "supplier_account_id": account["id"],
        "requested_by_user_id": uid,
        "valid_from": valid_from_str,
        "valid_until": valid_until_str,
        "query_budget_total": budget_total,
        "query_budget_consumed": 0,
        "status": "REQUESTED",
        "denial_reason": None,
    })
    STORE["clean_room_grants"][grant["id"]] = grant
    return ok(grant_view(grant), 201)


@app.get("/shopper-insights/clean-room-grants/<grant_id>")
def get_grant(grant_id):
    actor()
    grant = get_or_404("clean_room_grants", grant_id)
    lazy_grant(grant)
    return ok(grant_view(grant))


@app.post("/shopper-insights/clean-room-grants/<grant_id>/approve")
def approve_grant(grant_id):
    uid, role = actor()
    require_roles(role, {"DataSteward"})
    grant = get_or_404("clean_room_grants", grant_id)
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_GRANT_NOT_APPROVABLE", "Approve requires grant status REQUESTED", 409)
    if uid == grant["requested_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", "Approver must differ from the requesting analyst", 403)
    grant["status"] = "APPROVED"
    touch(grant)
    write_audit("GRANT_APPROVED", role, uid, "CleanRoomGrant", grant["id"], "Grant approved")
    return ok(grant_view(grant))


@app.post("/shopper-insights/clean-room-grants/<grant_id>/deny")
def deny_grant(grant_id):
    uid, role = actor()
    require_roles(role, {"DataSteward"})
    data = body()
    reason = req_str(data, "reason")
    grant = get_or_404("clean_room_grants", grant_id)
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_GRANT_NOT_APPROVABLE", "Deny requires grant status REQUESTED", 409)
    grant["status"] = "DENIED"
    grant["denial_reason"] = reason
    touch(grant)
    write_audit("GRANT_DENIED", role, uid, "CleanRoomGrant", grant["id"], f"Grant denied: {reason}")
    return ok(grant_view(grant))


@app.post("/shopper-insights/clean-room-grants/<grant_id>/revoke")
def revoke_grant(grant_id):
    uid, role = actor()
    require_roles(role, {"DataSteward"})
    grant = get_or_404("clean_room_grants", grant_id)
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Revoke requires grant status APPROVED", 409)
    grant["status"] = "REVOKED"
    touch(grant)
    write_audit("GRANT_REVOKED", role, uid, "CleanRoomGrant", grant["id"], "Grant revoked")
    return ok(grant_view(grant))


def _query_cost(grant, estimated_rows, dataset_joins):
    row_units = math.ceil(estimated_rows / ROWS_PER_UNIT) if estimated_rows > 0 else 0
    join_factor = max(1.0, 1.0 + 0.25 * (len(dataset_joins) - 1))
    contract = next(
        (c for c in STORE["subscription_contracts"].values()
         if c["supplier_account_id"] == grant["supplier_account_id"] and c["status"] == "ACTIVE"),
        None,
    )
    tier_mult = TIER_MULTIPLIERS[contract["tier"]] if contract is not None else 1.0
    raw = row_units * join_factor * tier_mult
    return min(MAX_QUERY_COST, max(QUERY_COST_MINIMUM, math.ceil(raw)))


@app.post("/shopper-insights/clean-room-grants/<grant_id>/queries")
def submit_query(grant_id):
    uid, role = actor()
    require_roles(role, {"SupplierAnalyst"})
    data = body()
    dataset_joins = req_list(data, "dataset_joins")
    estimated_rows = req_int(data, "estimated_rows")
    if estimated_rows < 0:
        err_invalid("estimated_rows must be non-negative")
    grant = get_or_404("clean_room_grants", grant_id)
    require_analyst_owns_account(uid, role, grant["supplier_account_id"])
    if grant["status"] == "APPROVED" and clock_now() >= parse_ts(grant["valid_until"]):
        grant["status"] = "EXPIRED"
        touch(grant)
        raise ApiError("ERR_GRANT_EXPIRED", "Query submitted at or after the grant window end", 409)
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_GRANT_NOT_QUERYABLE", "Grant is not in APPROVED status", 409)
    cost = _query_cost(grant, estimated_rows, dataset_joins)
    remaining = grant["query_budget_total"] - grant["query_budget_consumed"]
    if cost > remaining:
        raise ApiError("ERR_INSUFFICIENT_QUERY_BUDGET", "Query cost exceeds remaining query budget", 402)
    result_rows = estimated_rows
    if result_rows >= MIN_CELL_SIZE:
        status = "EXECUTED"
        grant["query_budget_consumed"] += cost
        touch(grant)
        event_type = "QUERY_EXECUTED"
    else:
        status = "SUPPRESSED"
        # Charged then refunded in full: net zero on query_budget_consumed
        event_type = "QUERY_SUPPRESSED"
    query = stamp_new({
        "grant_id": grant["id"],
        "dataset_joins": list(dataset_joins),
        "estimated_rows": estimated_rows,
        "query_cost": cost,
        "result_rows": result_rows,
        "status": status,
    }, common=False)
    STORE["clean_room_queries"][query["id"]] = query
    write_audit(event_type, role, uid, "CleanRoomQuery", query["id"], f"Query {status.lower()}")
    return ok(query, 201)


@app.get("/shopper-insights/clean-room-grants/<grant_id>/queries")
def list_grant_queries(grant_id):
    actor()
    get_or_404("clean_room_grants", grant_id)
    items = [q for q in STORE["clean_room_queries"].values() if q["grant_id"] == grant_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


# ==========================================================================
# Line review cycles and deliverables
# ==========================================================================


@app.post("/shopper-insights/line-review-cycles")
def create_cycle():
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    data = body()
    category_code = req_str(data, "category_code")
    window_start_str = req_str(data, "window_start")
    window_end_str = req_str(data, "window_end")
    try:
        window_start = parse_date(window_start_str)
        window_end = parse_date(window_end_str)
    except ValueError:
        err_invalid("window_start and window_end must be ISO dates")
    # Gap check: new window must start >= 7 days after each existing non-COMPLETED
    # cycle's closed window for the same category.
    for c in STORE["line_review_cycles"].values():
        if c["category_code"] != category_code or c["status"] == "COMPLETED":
            continue
        existing_end = parse_date(c["window_end"])
        if (window_start - existing_end).days < CYCLE_GAP_MIN_DAYS:
            raise ApiError("ERR_CYCLE_GAP_VIOLATION", "New cycle window begins less than 7 days after an existing window", 409)
    open_at_dt = date_to_dt(window_start) - timedelta(days=CYCLE_OPEN_LEAD_DAYS)
    cycle = stamp_new({
        "category_code": category_code,
        "window_start": window_start_str,
        "window_end": window_end_str,
        "open_at": fmt_ts(open_at_dt),
        "planned_open_count": 0,
        "status": "SCHEDULED",
    })
    STORE["line_review_cycles"][cycle["id"]] = cycle
    return ok(cycle, 201)


@app.get("/shopper-insights/line-review-cycles/<cycle_id>")
def get_cycle(cycle_id):
    actor()
    cycle = get_or_404("line_review_cycles", cycle_id)
    lazy_cycle(cycle)
    return ok(cycle)


@app.post("/shopper-insights/line-review-cycles/<cycle_id>/lock")
def lock_cycle(cycle_id):
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    cycle = get_or_404("line_review_cycles", cycle_id)
    lazy_cycle(cycle)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_LOCKABLE", "Lock requires cycle status OPEN", 409)
    cycle["status"] = "LOCKED"
    touch(cycle)
    for d in STORE["review_deliverables"].values():
        if d["cycle_id"] == cycle["id"] and d["status"] == "PLANNED":
            d["status"] = "MISSED"
            touch(d)
            cycle["planned_open_count"] -= 1
            contract = STORE["subscription_contracts"].get(d["contract_id"])
            if contract is not None:
                contract["compliance_score"] = max(0, contract["compliance_score"] - MISSED_DELIVERABLE_PENALTY)
                touch(contract)
    return ok(cycle)


@app.post("/shopper-insights/line-review-cycles/<cycle_id>/complete")
def complete_cycle(cycle_id):
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    cycle = get_or_404("line_review_cycles", cycle_id)
    lazy_cycle(cycle)
    if cycle["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Complete requires cycle status LOCKED", 409)
    cycle["status"] = "COMPLETED"
    touch(cycle)
    return ok(cycle)


@app.post("/shopper-insights/line-review-cycles/<cycle_id>/deliverables")
def create_deliverable(cycle_id):
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    data = body()
    contract_id = req_str(data, "contract_id")
    report_id = req_str(data, "insight_report_id")
    due_at_str = data.get("due_at")
    try:
        due_at_dt = parse_ts(due_at_str)
    except (ValueError, TypeError):
        err_invalid("due_at must be an ISO 8601 UTC timestamp")
    cycle = get_or_404("line_review_cycles", cycle_id)
    contract = get_or_404("subscription_contracts", contract_id)
    report = get_or_404("insight_reports", report_id)
    lazy_cycle(cycle)
    if due_at_dt >= date_to_dt(parse_date(cycle["window_start"])):
        err_invalid("due_at must fall strictly before the cycle window_start")
    deliverable = stamp_new({
        "cycle_id": cycle["id"],
        "contract_id": contract["id"],
        "insight_report_id": report["id"],
        "due_at": due_at_str,
        "is_late": False,
        "status": "PLANNED",
    })
    STORE["review_deliverables"][deliverable["id"]] = deliverable
    cycle["planned_open_count"] += 1
    touch(cycle)
    return ok(deliverable, 201)


@app.get("/shopper-insights/line-review-cycles/<cycle_id>/deliverables")
def list_cycle_deliverables(cycle_id):
    actor()
    get_or_404("line_review_cycles", cycle_id)
    items = [d for d in STORE["review_deliverables"].values() if d["cycle_id"] == cycle_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


@app.post("/shopper-insights/review-deliverables/<deliverable_id>/submit")
def submit_deliverable(deliverable_id):
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    d = get_or_404("review_deliverables", deliverable_id)
    if d["status"] not in ("PLANNED", "REJECTED"):
        raise ApiError("ERR_DELIVERABLE_NOT_SUBMITTABLE", "Submit requires status PLANNED or REJECTED", 409)
    cycle = STORE["line_review_cycles"].get(d["cycle_id"])
    if cycle is None:
        err_not_found("cycle not found")
    lazy_cycle(cycle)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", "Submit requires cycle status OPEN", 409)
    report = STORE["insight_reports"].get(d["insight_report_id"])
    if report is None or report["status"] not in ("READY", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE", "Backing report must be READY or DELIVERED", 409)
    d["status"] = "SUBMITTED"
    if clock_now() > parse_ts(d["due_at"]):
        d["is_late"] = True
        contract = STORE["subscription_contracts"].get(d["contract_id"])
        if contract is not None:
            contract["compliance_score"] = max(0, contract["compliance_score"] - LATE_SUBMISSION_PENALTY)
            touch(contract)
    touch(d)
    return ok(d)


@app.post("/shopper-insights/review-deliverables/<deliverable_id>/accept")
def accept_deliverable(deliverable_id):
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    d = get_or_404("review_deliverables", deliverable_id)
    if d["status"] != "SUBMITTED":
        raise ApiError("ERR_DELIVERABLE_NOT_REVIEWABLE", "Accept requires deliverable status SUBMITTED", 409)
    d["status"] = "ACCEPTED"
    touch(d)
    cycle = STORE["line_review_cycles"].get(d["cycle_id"])
    if cycle is not None:
        cycle["planned_open_count"] -= 1
        touch(cycle)
    return ok(d)


@app.post("/shopper-insights/review-deliverables/<deliverable_id>/reject")
def reject_deliverable(deliverable_id):
    uid, role = actor()
    require_roles(role, {"CategoryManager"})
    d = get_or_404("review_deliverables", deliverable_id)
    if d["status"] != "SUBMITTED":
        raise ApiError("ERR_DELIVERABLE_NOT_REVIEWABLE", "Reject requires deliverable status SUBMITTED", 409)
    d["status"] = "REJECTED"
    touch(d)
    return ok(d)


# ==========================================================================
# New-item forecasts
# ==========================================================================


@app.post("/shopper-insights/new-item-forecasts")
def create_forecast():
    uid, role = actor()
    require_roles(role, {"InsightsScientist"})
    data = body()
    contract_id = req_str(data, "contract_id")
    product_ref = req_str(data, "product_ref")
    analogs = req_list(data, "analogs")
    for a in analogs:
        if not isinstance(a, dict):
            err_invalid("analogs entries must be objects")
        if not isinstance(a.get("analog_ref"), str) or not a["analog_ref"]:
            err_invalid("analog_ref is required")
        sim = a.get("similarity_score")
        if isinstance(sim, bool) or not isinstance(sim, (int, float)):
            err_invalid("similarity_score must be numeric")
        units = a.get("observed_week4_units")
        if isinstance(units, bool) or not isinstance(units, (int, float)):
            err_invalid("observed_week4_units must be numeric")
    variant = req_enum(data, "variant", ("SIMPLE_AVERAGE", "SIMILARITY_WEIGHTED"))
    contract = get_or_404("subscription_contracts", contract_id)
    if not contract["modeled_derivation_allowed"]:
        raise ApiError("ERR_MODELED_DERIVATION_FORBIDDEN", "Contract modeled_derivation_allowed is false", 422)
    units = [a["observed_week4_units"] for a in analogs]
    simple_avg = round2(sum(units) / len(units))
    sim_sum = sum(a["similarity_score"] for a in analogs)
    if sim_sum:
        weighted = round2(sum(a["similarity_score"] * a["observed_week4_units"] for a in analogs) / sim_sum)
    else:
        weighted = 0.0
    selected = simple_avg if variant == "SIMPLE_AVERAGE" else weighted
    # Supersede prior PUBLISHED forecasts for the same product_ref
    for f in STORE["new_item_forecasts"].values():
        if f["product_ref"] == product_ref and f["status"] == "PUBLISHED":
            f["status"] = "SUPERSEDED"
            touch(f)
    forecast = stamp_new({
        "contract_id": contract["id"],
        "product_ref": product_ref,
        "analogs": list(analogs),
        "variant": variant,
        "forecast_simple_avg_units": simple_avg,
        "forecast_weighted_units": weighted,
        "forecast_selected_units": selected,
        "status": "PUBLISHED",
    })
    STORE["new_item_forecasts"][forecast["id"]] = forecast
    return ok(forecast, 201)


# ==========================================================================
# Audit events
# ==========================================================================


@app.get("/shopper-insights/audit-events")
def list_audit_events():
    actor()
    items = list(STORE["audit_events"].values())
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    page, meta = paginate(items)
    return ok(page, pagination=meta)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
