#!/usr/bin/env python3
"""Charitable Medical Debt Abolishment API.

In-memory Flask implementation built from PRD.md + SCAFFOLD.yaml.
All money is integer cents; all timestamps come from a server-side logical
clock (never wall-clock). The store starts empty on every boot.
"""

import os
import re
import uuid
import threading
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00.000Z"

FPL_BASE_CENTS = 1565000
FPL_INCREMENT_CENTS = 556000

TIER1_LIMIT_CENTS = 100000000
TIER1_RATE = Decimal("0.025")
TIER2_LIMIT_CENTS = 400000000
TIER2_RATE = Decimal("0.015")
TIER3_RATE = Decimal("0.008")
ORG_FACTOR = {
    "HOSPITAL": Decimal("1.0"),
    "PHYSICIAN_GROUP": Decimal("0.9"),
    "DEBT_BUYER": Decimal("0.75"),
}

FEE_PCT = Decimal("0.029")

MAX_LETTER_ATTEMPTS = 3
MAX_CDR_RESUBMISSIONS = 2

ROLES = [
    "PlatformAdmin",
    "PortfolioAnalyst",
    "EligibilityOfficer",
    "ContractManager",
    "FinanceOfficer",
    "DonorRelationsOfficer",
    "ComplianceAuditor",
    "HospitalPartner",
]

ORG_TYPES = ["HOSPITAL", "PHYSICIAN_GROUP", "DEBT_BUYER"]
BUREAUS = ["EQUIFAX", "EXPERIAN", "TRANSUNION"]
EARMARK_TYPES = ["GEOGRAPHY", "HOSPITAL", "GENERAL"]
REPORT_SCOPES = ["GLOBAL", "GEOGRAPHY", "HOSPITAL"]
COUNTING_VARIANTS = ["PER_ACCOUNT", "DEDUPED_HOUSEHOLD"]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$")

ENTITY_LABELS = {
    "orgs": "SourceOrganization",
    "policies": "EligibilityPolicy",
    "portfolios": "Portfolio",
    "accounts": "DebtAccount",
    "screening_runs": "ScreeningRun",
    "contracts": "PurchaseContract",
    "campaigns": "DonorCampaign",
    "donations": "Donation",
    "batches": "AbolishmentBatch",
    "letters": "NotificationLetter",
    "cdrs": "CreditDeletionRequest",
    "tax_records": "TaxReliefRecord",
    "partnerships": "HospitalPartnership",
    "milestones": "PartnershipMilestone",
    "reports": "ImpactReport",
}


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = {k: {} for k in ENTITY_LABELS}
        # seq per store-key: preserves creation order for ties in sort
        self.seq = {k: 0 for k in ENTITY_LABELS}
        self.clock = self._parse_iso(CLOCK_DEFAULT_ISO)

    @staticmethod
    def _parse_iso(s):
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

    def now(self):
        return self.clock

    def now_iso(self):
        iso = self.clock.isoformat(timespec="milliseconds")
        if iso.endswith("+00:00"):
            iso = iso[:-6] + "Z"
        return iso

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self, key):
        self.seq[key] += 1
        return self.seq[key]


store = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# ---------------------------------------------------------------------------
# Flask app + envelope helpers
# ---------------------------------------------------------------------------

app = Flask(__name__)


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + limit < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def _handle_500(e):
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


# ---------------------------------------------------------------------------
# Request parsing / auth helpers
# ---------------------------------------------------------------------------

def get_body():
    if not request.is_json:
        raise err("Request body must be valid JSON")
    try:
        body = request.get_json()
    except Exception:
        raise err("Request body must be valid JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("Request body must be a JSON object")
    return body


def auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")


def forbidden(msg="Forbidden"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Invalid state for the requested transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="expected_portfolio_version does not match the portfolio's current version"):
    raise ApiError("ERR_STALE_VERSION", 412, msg)


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

def req_field(body, field):
    if field not in body or body[field] is None:
        raise err("Missing required field: %s" % field)
    return body[field]


def req_str(body, field):
    v = req_field(body, field)
    if not isinstance(v, str) or not isinstance(v, str) or v == "":
        raise err("Field %s must be a non-empty string" % field)
    return v


def req_bool(body, field):
    v = req_field(body, field)
    if not isinstance(v, bool):
        raise err("Field %s must be a boolean" % field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None):
    v = req_field(body, field)
    if not _is_int(v):
        raise err("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("Field %s is out of range" % field)
    return v


def req_enum(body, field, allowed):
    v = req_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err("Field %s must be one of %s" % (field, ", ".join(allowed)))
    return v


def _parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("bad date")
    return dt.date.fromisoformat(s)


def req_date(body, field):
    v = req_field(body, field)
    try:
        return _parse_date(v)
    except (ValueError, TypeError):
        raise err("Field %s must be a date YYYY-MM-DD" % field)


def req_number(body, field):
    v = req_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("Field %s must be a number" % field)
    return Decimal(str(v))


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v == "":
        raise err("Field %s must be a non-empty string when present" % field)
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise err("Field %s must be an integer when present" % field)
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise err("Field %s must be one of %s" % (field, ", ".join(allowed)))
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err("Field %s must be a boolean when present" % field)
    return v


# ---------------------------------------------------------------------------
# Common resource plumbing
# ---------------------------------------------------------------------------

def new_resource(key, fields):
    rid = store.new_id()
    now = store.now_iso()
    res = dict(fields)
    res["id"] = rid
    res["created_at"] = now
    res["updated_at"] = now
    res["version"] = 1
    res["_seq"] = store.next_seq(key)
    store.data[key][rid] = res
    return res


def public(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}


def bump(res):
    res["version"] += 1
    res["updated_at"] = store.now_iso()


def get_res(key, rid):
    res = store.data[key].get(rid)
    if res is None:
        not_found("%s not found" % ENTITY_LABELS[key])
    return res


def list_endpoint(key, filters):
    """filters: list of (query_param, resolver(value)->bool(resource))."""
    items = list(store.data[key].values())
    args = request.args
    for param, pred in filters:
        raw = args.get(param)
        if raw is None:
            continue
        items = [r for r in items if pred(raw)(r)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("offset must be an integer")
        if offset < 0:
            raise err("offset must be >= 0")
    page = items[offset:offset + limit]
    return ok_list([public(r) for r in page], total, limit, offset)


def _f_str(field):
    def pred(v):
        return lambda r: r.get(field) == v
    return pred


def recompute_portfolio_eligible(portfolio, touch=True):
    accounts = [
        a for a in store.data["accounts"].values()
        if a["portfolio_id"] == portfolio["id"] and a["eligibility_status"] == "ELIGIBLE"
    ]
    portfolio["eligible_face_value_cents"] = sum(a["balance_cents"] for a in accounts)
    portfolio["eligible_account_count"] = len(accounts)
    if touch:
        bump(portfolio)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    raw = req_field(body, "to_iso8601")
    if not isinstance(raw, str) or not ISO_INSTANT_RE.match(raw):
        raise err("to_iso8601 must be an ISO 8601 timestamp string")
    try:
        new_clock = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise err("to_iso8601 must be an ISO 8601 timestamp string")
    if new_clock.tzinfo is None:
        new_clock = new_clock.replace(tzinfo=dt.timezone.utc)
    store.clock = new_clock.astimezone(dt.timezone.utc)
    return ok_object({"current_utc": store.now_iso()})


# ---------------------------------------------------------------------------
# SourceOrganization
# ---------------------------------------------------------------------------

@app.route("/api/source-organizations", methods=["POST"])
def create_source_org():
    body = get_body()
    auth()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    name = req_str(body, "name")
    org_type = req_enum(body, "org_type", ORG_TYPES)
    state_code = req_str(body, "state_code")
    contact_email = req_str(body, "contact_email")
    org = new_resource("orgs", {
        "name": name,
        "org_type": org_type,
        "state_code": state_code,
        "contact_email": contact_email,
        "status": "ACTIVE",
    })
    return ok_object(public(org), 201)


@app.route("/api/source-organizations/<org_id>", methods=["GET"])
def get_source_org(org_id):
    auth()
    org = get_res("orgs", org_id)
    return ok_object(public(org))


@app.route("/api/source-organizations", methods=["GET"])
def list_source_orgs():
    auth()
    return list_endpoint("orgs", [
        ("org_type", _f_str("org_type")),
        ("state_code", _f_str("state_code")),
        ("status", _f_str("status")),
    ])


@app.route("/api/source-organizations/<org_id>/suspend", methods=["POST"])
def suspend_source_org(org_id):
    get_body()
    auth()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    org = get_res("orgs", org_id)
    if org["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE organization can be suspended")
    org["status"] = "SUSPENDED"
    bump(org)
    return ok_object(public(org))


@app.route("/api/source-organizations/<org_id>/reactivate", methods=["POST"])
def reactivate_source_org(org_id):
    get_body()
    auth()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    org = get_res("orgs", org_id)
    if org["status"] != "SUSPENDED":
        invalid_state("Only a SUSPENDED organization can be reactivated")
    org["status"] = "ACTIVE"
    bump(org)
    return ok_object(public(org))


# ---------------------------------------------------------------------------
# EligibilityPolicy
# ---------------------------------------------------------------------------

@app.route("/api/eligibility-policies", methods=["POST"])
def create_policy():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer", "PlatformAdmin"])
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    fpl_multiplier = req_number(body, "fpl_multiplier")
    if fpl_multiplier <= 0:
        raise err("fpl_multiplier must be > 0")
    insolvency_qualifies = req_bool(body, "insolvency_qualifies")
    eff_from = req_date(body, "effective_from")
    eff_to = req_date(body, "effective_to")
    if eff_to <= eff_from:
        raise err("effective_to must be after effective_from")
    policy = new_resource("policies", {
        "name": name,
        "state_code": state_code,
        "fpl_multiplier": float(fpl_multiplier),
        "insolvency_qualifies": insolvency_qualifies,
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat(),
        "status": "DRAFT",
    })
    return ok_object(public(policy), 201)


@app.route("/api/eligibility-policies/<pid>", methods=["GET"])
def get_policy(pid):
    auth()
    return ok_object(public(get_res("policies", pid)))


@app.route("/api/eligibility-policies", methods=["GET"])
def list_policies():
    auth()
    return list_endpoint("policies", [
        ("state_code", _f_str("state_code")),
        ("status", _f_str("status")),
    ])


@app.route("/api/eligibility-policies/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer"])
    policy = get_res("policies", pid)
    if policy["status"] != "DRAFT":
        invalid_state("Only a DRAFT policy can be activated")
    p_from = dt.date.fromisoformat(policy["effective_from"])
    p_to = dt.date.fromisoformat(policy["effective_to"])
    for other in store.data["policies"].values():
        if other["id"] == policy["id"]:
            continue
        if other["state_code"] != policy["state_code"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        o_from = dt.date.fromisoformat(other["effective_from"])
        o_to = dt.date.fromisoformat(other["effective_to"])
        # half-open overlap; adjacency allowed
        if p_from < o_to and o_from < p_to:
            raise ApiError("ERR_POLICY_WINDOW_OVERLAP", 409,
                           "ACTIVE policy window overlaps another ACTIVE policy in the same state_code")
    policy["status"] = "ACTIVE"
    bump(policy)
    return ok_object(public(policy))


@app.route("/api/eligibility-policies/<pid>/retire", methods=["POST"])
def retire_policy(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer"])
    policy = get_res("policies", pid)
    if policy["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE policy can be retired")
    policy["status"] = "RETIRED"
    bump(policy)
    return ok_object(public(policy))


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@app.route("/api/portfolios", methods=["POST"])
def create_portfolio():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["PortfolioAnalyst"])
    source_org_id = req_str(body, "source_org_id")
    label = req_str(body, "label")
    face_value_cents = req_int(body, "face_value_cents")
    asking_price_cents = req_int(body, "asking_price_cents")
    org = store.data["orgs"].get(source_org_id)
    if org is None:
        raise ApiError("ERR_SOURCE_ORG_NOT_FOUND", 404, "source_org_id does not exist")
    portfolio = new_resource("portfolios", {
        "source_org_id": source_org_id,
        "label": label,
        "face_value_cents": face_value_cents,
        "asking_price_cents": asking_price_cents,
        "status": "DRAFT",
        "eligible_face_value_cents": 0,
        "eligible_account_count": 0,
        "quoted_price_cents": None,
        "purchased_price_cents": None,
        "abolished_face_value_cents": 0,
    })
    return ok_object(public(portfolio), 201)


@app.route("/api/portfolios/<pid>", methods=["GET"])
def get_portfolio(pid):
    auth()
    return ok_object(public(get_res("portfolios", pid)))


@app.route("/api/portfolios", methods=["GET"])
def list_portfolios():
    auth()
    return list_endpoint("portfolios", [
        ("source_org_id", _f_str("source_org_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/portfolios/<pid>/submit", methods=["POST"])
def submit_portfolio(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["PortfolioAnalyst"])
    portfolio = get_res("portfolios", pid)
    if portfolio["status"] != "DRAFT":
        invalid_state("Only a DRAFT portfolio can be submitted")
    org = get_res("orgs", portfolio["source_org_id"])
    if org["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_ORG_SUSPENDED", 409, "Source org SUSPENDED blocks portfolio submit")
    count = sum(1 for a in store.data["accounts"].values() if a["portfolio_id"] == pid)
    if count == 0:
        raise ApiError("ERR_BATCH_EMPTY", 422, "Portfolio submit requires at least one imported account")
    portfolio["status"] = "SUBMITTED"
    bump(portfolio)
    return ok_object(public(portfolio))


@app.route("/api/portfolios/<pid>/cancel", methods=["POST"])
def cancel_portfolio(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["PortfolioAnalyst"])
    portfolio = get_res("portfolios", pid)
    if portfolio["status"] not in ("DRAFT", "SUBMITTED", "SCREENING", "PRICED"):
        invalid_state("Portfolio cannot be cancelled from its current state")
    if portfolio["status"] == "PRICED":
        for c in store.data["contracts"].values():
            if c["portfolio_id"] == pid and c["status"] in ("DRAFT", "EXECUTED"):
                invalid_state("A DRAFT or EXECUTED contract exists for this portfolio")
    portfolio["status"] = "CANCELLED"
    bump(portfolio)
    return ok_object(public(portfolio))


def compute_price_quote(portfolio):
    face = portfolio["eligible_face_value_cents"]
    tier1 = Decimal(min(face, TIER1_LIMIT_CENTS)) * TIER1_RATE
    tier2 = Decimal(min(max(face - TIER1_LIMIT_CENTS, 0), TIER2_LIMIT_CENTS)) * TIER2_RATE
    tier3 = Decimal(max(face - TIER1_LIMIT_CENTS - TIER2_LIMIT_CENTS, 0)) * TIER3_RATE
    raw = tier1 + tier2 + tier3
    org = get_res("orgs", portfolio["source_org_id"])
    factor = ORG_FACTOR[org["org_type"]]
    return int((raw * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.route("/api/portfolios/<pid>/price-quote", methods=["POST"])
def price_quote(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["PortfolioAnalyst"])
    portfolio = get_res("portfolios", pid)
    if portfolio["status"] not in ("SCREENING", "PRICED"):
        invalid_state("Price quote requires portfolio in SCREENING or PRICED")
    completed = any(
        r["portfolio_id"] == pid and r["status"] == "COMPLETED"
        for r in store.data["screening_runs"].values()
    )
    pending_review = any(
        a["portfolio_id"] == pid and a["eligibility_status"] in ("UNSCREENED", "NEEDS_REVIEW")
        for a in store.data["accounts"].values()
    )
    if not completed or pending_review:
        raise ApiError("ERR_SCREENING_INCOMPLETE", 409,
                       "Price quote requires a COMPLETED run and zero UNSCREENED/NEEDS_REVIEW accounts")
    portfolio["quoted_price_cents"] = compute_price_quote(portfolio)
    portfolio["status"] = "PRICED"
    bump(portfolio)
    return ok_object(public(portfolio))


@app.route("/api/portfolios/<pid>/accounts", methods=["POST"])
def import_accounts(pid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["PortfolioAnalyst"])
    portfolio = get_res("portfolios", pid)
    if portfolio["status"] != "DRAFT":
        invalid_state("Accounts may only be imported while the portfolio is DRAFT")
    items = req_field(body, "accounts")
    if not isinstance(items, list):
        raise err("accounts must be an array")

    prepared = []
    for item in items:
        if not isinstance(item, dict):
            raise err("each account must be an object")
        external_ref = req_str(item, "external_ref")
        debtor_household_key = req_str(item, "debtor_household_key")
        debtor_zip = req_str(item, "debtor_zip")
        debtor_state = req_str(item, "debtor_state")
        household_size = opt_int(item, "household_size")
        annual_income_cents = opt_int(item, "annual_income_cents")
        is_insolvent = opt_bool(item, "is_insolvent", False)
        balance_cents = req_int(item, "balance_cents")
        accrued_adjustment_cents = opt_int(item, "accrued_adjustment_cents")
        if accrued_adjustment_cents is None:
            accrued_adjustment_cents = 0
        reported_to_bureau = opt_bool(item, "reported_to_bureau", False)
        bureau_name = item.get("bureau_name")
        if reported_to_bureau:
            if not isinstance(bureau_name, str) or bureau_name not in BUREAUS:
                raise err("bureau_name is required and must be a valid bureau when reported_to_bureau is true")
        else:
            if bureau_name is not None:
                raise err("bureau_name must be absent when reported_to_bureau is false")
        mailing_address = opt_str(item, "mailing_address")
        if household_size is not None and household_size < 1:
            raise ApiError("ERR_INVALID_HOUSEHOLD_DATA", 422,
                           "household_size present but < 1 at account import")
        prepared.append({
            "portfolio_id": pid,
            "external_ref": external_ref,
            "debtor_household_key": debtor_household_key,
            "debtor_zip": debtor_zip,
            "debtor_state": debtor_state,
            "household_size": household_size,
            "annual_income_cents": annual_income_cents,
            "is_insolvent": is_insolvent,
            "balance_cents": balance_cents,
            "accrued_adjustment_cents": accrued_adjustment_cents,
            "reported_to_bureau": reported_to_bureau,
            "bureau_name": bureau_name,
            "mailing_address": mailing_address,
            "eligibility_status": "UNSCREENED",
            "lifecycle_status": "AVAILABLE",
            "bureau_status": "REPORTED" if reported_to_bureau else "NOT_REPORTED",
            "abolished_amount_cents": None,
            "abolished_at": None,
            "abolished_batch_id": None,
        })

    created = [new_resource("accounts", fields) for fields in prepared]
    return ok_list_response_in_order(created, 201)


def ok_list_response_in_order(resources, code):
    # bulk import: response array preserves request order, no pagination meta
    body = {"meta": _meta(), "response_type": "array", "data": [public(r) for r in resources]}
    return jsonify(body), code


# ---------------------------------------------------------------------------
# DebtAccount
# ---------------------------------------------------------------------------

@app.route("/api/accounts/<aid>", methods=["GET"])
def get_account(aid):
    auth()
    return ok_object(public(get_res("accounts", aid)))


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    auth()
    return list_endpoint("accounts", [
        ("portfolio_id", _f_str("portfolio_id")),
        ("eligibility_status", _f_str("eligibility_status")),
        ("lifecycle_status", _f_str("lifecycle_status")),
        ("bureau_status", _f_str("bureau_status")),
        ("abolished_batch_id", _f_str("abolished_batch_id")),
    ])


@app.route("/api/accounts/<aid>/review", methods=["POST"])
def review_account(aid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer"])
    account = get_res("accounts", aid)
    decision = req_enum(body, "decision", ["ELIGIBLE", "INELIGIBLE"])
    if account["eligibility_status"] != "NEEDS_REVIEW":
        invalid_state("Review is allowed only from NEEDS_REVIEW")
    account["eligibility_status"] = decision
    bump(account)
    if decision == "ELIGIBLE":
        portfolio = get_res("portfolios", account["portfolio_id"])
        recompute_portfolio_eligible(portfolio)
    return ok_object(public(account))


# ---------------------------------------------------------------------------
# ScreeningRun
# ---------------------------------------------------------------------------

@app.route("/api/portfolios/<pid>/screening-runs", methods=["POST"])
def create_screening_run(pid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer"])
    portfolio = get_res("portfolios", pid)
    policy_id = req_str(body, "policy_id")
    policy = store.data["policies"].get(policy_id)
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND", 404, "policy_id does not exist")
    if portfolio["status"] not in ("SUBMITTED", "SCREENING", "PRICED"):
        invalid_state("Screening runs require portfolio in SUBMITTED, SCREENING or PRICED")
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", 409, "Screening run requires an ACTIVE policy")
    run = new_resource("screening_runs", {
        "portfolio_id": pid,
        "policy_id": policy_id,
        "status": "PENDING",
        "eligible_count": 0,
        "ineligible_count": 0,
        "needs_review_count": 0,
        "executed_at": None,
    })
    portfolio["status"] = "SCREENING"
    bump(portfolio)
    return ok_object(public(run), 201)


@app.route("/api/screening-runs/<rid>", methods=["GET"])
def get_screening_run(rid):
    auth()
    return ok_object(public(get_res("screening_runs", rid)))


@app.route("/api/screening-runs", methods=["GET"])
def list_screening_runs():
    auth()
    return list_endpoint("screening_runs", [
        ("portfolio_id", _f_str("portfolio_id")),
        ("policy_id", _f_str("policy_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/screening-runs/<rid>/execute", methods=["POST"])
def execute_screening_run(rid):
    get_body()
    user_id, role = auth()
    require_role(role, ["EligibilityOfficer"])
    run = get_res("screening_runs", rid)
    if run["status"] != "PENDING":
        invalid_state("Only a PENDING run can be executed")
    policy = get_res("policies", run["policy_id"])
    portfolio = get_res("portfolios", run["portfolio_id"])
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", 409, "Screening execution requires an ACTIVE policy")
    if portfolio["status"] != "SCREENING":
        invalid_state("Screening execution requires the portfolio to be in SCREENING")

    fpl_multiplier = Decimal(str(policy["fpl_multiplier"]))
    insolvency_qualifies = policy["insolvency_qualifies"]

    eligible_count = 0
    ineligible_count = 0
    needs_review_count = 0

    accounts = [a for a in store.data["accounts"].values() if a["portfolio_id"] == portfolio["id"]]
    for account in accounts:
        hs = account["household_size"]
        income = account["annual_income_cents"]
        if hs is None or hs < 1:
            result = "NEEDS_REVIEW"
        else:
            cap = int(((Decimal(FPL_BASE_CENTS) + (Decimal(hs) - 1) * Decimal(FPL_INCREMENT_CENTS))
                       * fpl_multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if income is None:
                if account["is_insolvent"] and insolvency_qualifies:
                    result = "ELIGIBLE"
                else:
                    result = "NEEDS_REVIEW"
            elif income <= cap:
                result = "ELIGIBLE"
            elif account["is_insolvent"] and insolvency_qualifies:
                result = "ELIGIBLE"
            else:
                result = "INELIGIBLE"
        if account["eligibility_status"] != result:
            account["eligibility_status"] = result
            bump(account)
        if result == "ELIGIBLE":
            eligible_count += 1
        elif result == "INELIGIBLE":
            ineligible_count += 1
        else:
            needs_review_count += 1

    run["status"] = "COMPLETED"
    run["eligible_count"] = eligible_count
    run["ineligible_count"] = ineligible_count
    run["needs_review_count"] = needs_review_count
    run["executed_at"] = store.now_iso()
    bump(run)

    recompute_portfolio_eligible(portfolio)
    return ok_object(public(run))


# ---------------------------------------------------------------------------
# PurchaseContract
# ---------------------------------------------------------------------------

@app.route("/api/portfolios/<pid>/contracts", methods=["POST"])
def create_contract(pid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["ContractManager"])
    portfolio = get_res("portfolios", pid)
    collection_prohibition = req_bool(body, "collection_prohibition")
    no_resale = req_bool(body, "no_resale")
    expected_version = req_int(body, "expected_portfolio_version")
    if portfolio["status"] != "PRICED":
        invalid_state("Contracts may only be created against a PRICED portfolio")
    if expected_version != portfolio["version"]:
        stale_version()
    contract = new_resource("contracts", {
        "portfolio_id": pid,
        "contract_price_cents": portfolio["quoted_price_cents"],
        "collection_prohibition": collection_prohibition,
        "no_resale": no_resale,
        "status": "DRAFT",
        "executed_by": None,
        "settled_by": None,
        "terminated_reason": None,
    })
    bump(portfolio)
    return ok_object(public(contract), 201)


@app.route("/api/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    auth()
    return ok_object(public(get_res("contracts", cid)))


@app.route("/api/contracts", methods=["GET"])
def list_contracts():
    auth()
    return list_endpoint("contracts", [
        ("portfolio_id", _f_str("portfolio_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/contracts/<cid>/execute", methods=["POST"])
def execute_contract(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["ContractManager"])
    contract = get_res("contracts", cid)
    if contract["status"] != "DRAFT":
        invalid_state("Only a DRAFT contract can be executed")
    portfolio = get_res("portfolios", contract["portfolio_id"])
    if portfolio["status"] != "PRICED":
        invalid_state("Contract execution requires the portfolio to be PRICED")
    if not (contract["collection_prohibition"] and contract["no_resale"]):
        raise ApiError("ERR_COLLECTION_COVENANT_MISSING", 422,
                       "Contract execute requires collection_prohibition == true AND no_resale == true")
    if portfolio["quoted_price_cents"] != contract["contract_price_cents"]:
        raise ApiError("ERR_PRICE_DRIFT", 409,
                       "Portfolio quoted price no longer equals the contract's pinned price")
    contract["status"] = "EXECUTED"
    contract["executed_by"] = user_id
    bump(contract)
    portfolio["status"] = "CONTRACTED"
    bump(portfolio)
    return ok_object(public(contract))


@app.route("/api/contracts/<cid>/settle", methods=["POST"])
def settle_contract(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    contract = get_res("contracts", cid)
    if contract["status"] != "EXECUTED":
        invalid_state("Only an EXECUTED contract can be settled")
    if user_id == contract["executed_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Contract settler X-User-ID must differ from executed_by")
    portfolio = get_res("portfolios", contract["portfolio_id"])
    contract["status"] = "SETTLED"
    contract["settled_by"] = user_id
    bump(contract)
    portfolio["purchased_price_cents"] = contract["contract_price_cents"]
    portfolio["status"] = "SETTLED"
    bump(portfolio)
    for account in store.data["accounts"].values():
        if account["portfolio_id"] != portfolio["id"]:
            continue
        account["lifecycle_status"] = "PURCHASED" if account["eligibility_status"] == "ELIGIBLE" else "EXCLUDED"
        bump(account)
    return ok_object(public(contract))


@app.route("/api/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["ContractManager"])
    contract = get_res("contracts", cid)
    reason = req_str(body, "reason")
    if contract["status"] != "EXECUTED":
        invalid_state("Only an EXECUTED contract can be terminated")
    portfolio = get_res("portfolios", contract["portfolio_id"])
    contract["status"] = "TERMINATED"
    contract["terminated_reason"] = reason
    bump(contract)
    if portfolio["status"] == "CONTRACTED":
        portfolio["status"] = "PRICED"
    bump(portfolio)
    return ok_object(public(contract))


# ---------------------------------------------------------------------------
# DonorCampaign / Donation
# ---------------------------------------------------------------------------

@app.route("/api/donor-campaigns", methods=["POST"])
def create_campaign():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    name = req_str(body, "name")
    earmark_type = req_enum(body, "earmark_type", EARMARK_TYPES)
    goal_cents = req_int(body, "goal_cents")
    earmark_state_code = opt_str(body, "earmark_state_code")
    earmark_source_org_id = body.get("earmark_source_org_id")
    if earmark_source_org_id is not None and (not isinstance(earmark_source_org_id, str) or earmark_source_org_id == ""):
        raise err("earmark_source_org_id must be a string when present")

    if earmark_type == "GEOGRAPHY":
        if earmark_state_code is None:
            raise err("earmark_state_code is required for a GEOGRAPHY earmark")
        if earmark_source_org_id is not None:
            raise err("earmark_source_org_id must be null for a GEOGRAPHY earmark")
    elif earmark_type == "HOSPITAL":
        if earmark_source_org_id is None:
            raise err("earmark_source_org_id is required for a HOSPITAL earmark")
        if earmark_state_code is not None:
            raise err("earmark_state_code must be null for a HOSPITAL earmark")
        org = store.data["orgs"].get(earmark_source_org_id)
        if org is None:
            raise ApiError("ERR_SOURCE_ORG_NOT_FOUND", 404, "earmark_source_org_id does not exist")
        if org["status"] == "SUSPENDED":
            raise ApiError("ERR_EARMARK_TARGET_SUSPENDED", 409,
                           "HOSPITAL-earmarked campaign references a SUSPENDED org")
        if org["org_type"] != "HOSPITAL":
            raise ApiError("ERR_EARMARK_TARGET_NOT_HOSPITAL", 422,
                           "HOSPITAL-earmarked campaign references a non-HOSPITAL org")
    else:  # GENERAL
        if earmark_state_code is not None or earmark_source_org_id is not None:
            raise err("GENERAL campaigns carry no earmark fields")

    campaign = new_resource("campaigns", {
        "name": name,
        "earmark_type": earmark_type,
        "earmark_state_code": earmark_state_code,
        "earmark_source_org_id": earmark_source_org_id,
        "goal_cents": goal_cents,
        "raised_cents": 0,
        "committed_cents": 0,
        "spent_cents": 0,
        "status": "OPEN",
    })
    return ok_object(public(campaign), 201)


@app.route("/api/donor-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    auth()
    return ok_object(public(get_res("campaigns", cid)))


@app.route("/api/donor-campaigns", methods=["GET"])
def list_campaigns():
    auth()
    return list_endpoint("campaigns", [
        ("earmark_type", _f_str("earmark_type")),
        ("earmark_source_org_id", _f_str("earmark_source_org_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/donor-campaigns/<cid>/close", methods=["POST"])
def close_campaign(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    campaign = get_res("campaigns", cid)
    if campaign["status"] not in ("OPEN", "FUNDED"):
        invalid_state("Only an OPEN or FUNDED campaign can be closed")
    campaign["status"] = "CLOSED"
    bump(campaign)
    return ok_object(public(campaign))


@app.route("/api/donor-campaigns/<cid>/donations", methods=["POST"])
def create_donation(cid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    donor_name = req_str(body, "donor_name")
    donor_email = req_str(body, "donor_email")
    gross_cents = req_int(body, "gross_cents")
    campaign = get_res("campaigns", cid)
    if campaign["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_CLOSED", 409, "Donations to a CLOSED campaign are rejected")
    if gross_cents <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "gross_cents must be > 0")
    fee_cents = int((Decimal(gross_cents) * FEE_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    donation = new_resource("donations", {
        "campaign_id": cid,
        "donor_name": donor_name,
        "donor_email": donor_email,
        "gross_cents": gross_cents,
        "fee_cents": fee_cents,
        "net_cents": gross_cents - fee_cents,
        "status": "PLEDGED",
    })
    return ok_object(public(donation), 201)


@app.route("/api/donations/<did>", methods=["GET"])
def get_donation(did):
    auth()
    return ok_object(public(get_res("donations", did)))


@app.route("/api/donations", methods=["GET"])
def list_donations():
    auth()
    return list_endpoint("donations", [
        ("campaign_id", _f_str("campaign_id")),
        ("status", _f_str("status")),
    ])


def _campaign_threshold_update(campaign):
    if campaign["raised_cents"] >= campaign["goal_cents"] and campaign["status"] == "OPEN":
        campaign["status"] = "FUNDED"
    elif campaign["raised_cents"] < campaign["goal_cents"] and campaign["status"] == "FUNDED":
        campaign["status"] = "OPEN"


@app.route("/api/donations/<did>/receive", methods=["POST"])
def receive_donation(did):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    donation = get_res("donations", did)
    if donation["status"] != "PLEDGED":
        invalid_state("Only a PLEDGED donation can be received")
    donation["status"] = "RECEIVED"
    bump(donation)
    campaign = get_res("campaigns", donation["campaign_id"])
    campaign["raised_cents"] += donation["net_cents"]
    _campaign_threshold_update(campaign)
    bump(campaign)
    return ok_object(public(donation))


@app.route("/api/donations/<did>/refund", methods=["POST"])
def refund_donation(did):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    donation = get_res("donations", did)
    if donation["status"] != "RECEIVED":
        invalid_state("Only a RECEIVED donation can be refunded")
    donation["status"] = "REFUNDED"
    bump(donation)
    campaign = get_res("campaigns", donation["campaign_id"])
    campaign["raised_cents"] -= donation["net_cents"]
    _campaign_threshold_update(campaign)
    bump(campaign)
    return ok_object(public(donation))


# ---------------------------------------------------------------------------
# AbolishmentBatch
# ---------------------------------------------------------------------------

@app.route("/api/portfolios/<pid>/abolishment-batches", methods=["POST"])
def create_batch(pid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    portfolio = get_res("portfolios", pid)
    account_ids = req_field(body, "account_ids")
    if not isinstance(account_ids, list):
        raise err("account_ids must be an array")
    expected_version = req_int(body, "expected_portfolio_version")

    if len(account_ids) == 0:
        raise ApiError("ERR_BATCH_EMPTY", 422, "Batch account_ids must be non-empty")
    for aid in account_ids:
        if not isinstance(aid, str):
            raise err("account_ids entries must be strings")

    accounts = []
    for aid in account_ids:
        account = store.data["accounts"].get(aid)
        if account is None:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account_ids entry does not exist")
        accounts.append(account)

    if portfolio["status"] not in ("SETTLED", "ABOLISHING"):
        raise ApiError("ERR_PORTFOLIO_NOT_SETTLED", 409,
                       "Batch create/commit requires portfolio SETTLED or ABOLISHING")
    for account in accounts:
        if account["portfolio_id"] != pid:
            raise ApiError("ERR_BATCH_ACCOUNT_FOREIGN", 409,
                           "Batch account_ids include an account of a different portfolio")
    for account in accounts:
        if account["lifecycle_status"] != "PURCHASED":
            raise ApiError("ERR_ACCOUNT_NOT_PURCHASED", 409,
                           "Batch account_ids must all be lifecycle PURCHASED")

    if expected_version != portfolio["version"]:
        stale_version()

    total = sum(a["balance_cents"] + a["accrued_adjustment_cents"] for a in accounts)
    batch = new_resource("batches", {
        "portfolio_id": pid,
        "account_ids": list(account_ids),
        "account_count": len(account_ids),
        "total_abolished_cents": total,
        "funding_allocations": [],
        "status": "STAGING",
        "reversed_reason": None,
    })
    bump(portfolio)
    return ok_object(public(batch), 201)


@app.route("/api/abolishment-batches/<bid>", methods=["GET"])
def get_batch(bid):
    auth()
    return ok_object(public(get_res("batches", bid)))


@app.route("/api/abolishment-batches", methods=["GET"])
def list_batches():
    auth()
    return list_endpoint("batches", [
        ("portfolio_id", _f_str("portfolio_id")),
        ("status", _f_str("status")),
    ])


def _waterfall(portfolio, need):
    """Return list of (campaign, amount) in draw order, or raise ERR_INSUFFICIENT_FUNDING."""
    org = get_res("orgs", portfolio["source_org_id"])

    def class_rank(c):
        if c["earmark_type"] == "HOSPITAL" and c["earmark_source_org_id"] == portfolio["source_org_id"]:
            return 0
        if c["earmark_type"] == "GEOGRAPHY" and c["earmark_state_code"] == org["state_code"]:
            return 1
        if c["earmark_type"] == "GENERAL":
            return 2
        return None

    candidates = []
    for c in store.data["campaigns"].values():
        if c["status"] not in ("OPEN", "FUNDED"):
            continue
        rank = class_rank(c)
        if rank is None:
            continue
        candidates.append((rank, c["created_at"], c["_seq"], c))
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))

    remaining = need
    allocations = []
    for _, _, _, c in candidates:
        if remaining == 0:
            break
        available = c["raised_cents"] - c["committed_cents"]
        if available <= 0:
            continue
        draw = min(remaining, available)
        allocations.append((c, draw))
        remaining -= draw
    if remaining > 0:
        raise ApiError("ERR_INSUFFICIENT_FUNDING", 402,
                       "Funding waterfall cannot cover total_abolished_cents")
    return allocations


@app.route("/api/abolishment-batches/<bid>/commit", methods=["POST"])
def commit_batch(bid):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    batch = get_res("batches", bid)
    if batch["status"] != "STAGING":
        invalid_state("Only a STAGING batch can be committed")
    portfolio = get_res("portfolios", batch["portfolio_id"])
    if portfolio["status"] not in ("SETTLED", "ABOLISHING"):
        raise ApiError("ERR_PORTFOLIO_NOT_SETTLED", 409,
                       "Batch create/commit requires portfolio SETTLED or ABOLISHING")

    # Waterfall is atomic: compute all allocations first, then commit.
    allocations = _waterfall(portfolio, batch["total_abolished_cents"])

    batch["funding_allocations"] = [
        {"campaign_id": c["id"], "amount_cents": amount} for c, amount in allocations
    ]
    batch["status"] = "COMMITTED"
    bump(batch)
    for c, amount in allocations:
        c["committed_cents"] += amount
        bump(c)
    if portfolio["status"] == "SETTLED":
        portfolio["status"] = "ABOLISHING"
    bump(portfolio)
    return ok_object(public(batch))


@app.route("/api/abolishment-batches/<bid>/uncommit", methods=["POST"])
def uncommit_batch(bid):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    batch = get_res("batches", bid)
    if batch["status"] != "COMMITTED":
        invalid_state("Only a COMMITTED batch can be uncommitted")
    for alloc in batch["funding_allocations"]:
        campaign = get_res("campaigns", alloc["campaign_id"])
        campaign["committed_cents"] -= alloc["amount_cents"]
        bump(campaign)
    batch["funding_allocations"] = []
    batch["status"] = "STAGING"
    bump(batch)
    return ok_object(public(batch))


def _maybe_auto_close(portfolio):
    if portfolio["status"] != "ABOLISHING":
        return
    has_purchased = any(
        a["portfolio_id"] == portfolio["id"] and a["lifecycle_status"] == "PURCHASED"
        for a in store.data["accounts"].values()
    )
    has_open_batch = any(
        b["portfolio_id"] == portfolio["id"] and b["status"] in ("STAGING", "COMMITTED")
        for b in store.data["batches"].values()
    )
    if not has_purchased and not has_open_batch:
        portfolio["status"] = "CLOSED"


@app.route("/api/abolishment-batches/<bid>/finalize", methods=["POST"])
def finalize_batch(bid):
    get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    batch = get_res("batches", bid)
    if batch["status"] != "COMMITTED":
        invalid_state("Only a COMMITTED batch can be finalized")
    portfolio = get_res("portfolios", batch["portfolio_id"])
    now = store.now_iso()

    for aid in batch["account_ids"]:
        account = store.data["accounts"][aid]
        final_value = account["balance_cents"] + account["accrued_adjustment_cents"]
        account["lifecycle_status"] = "ABOLISHED"
        account["abolished_amount_cents"] = final_value
        account["abolished_at"] = now
        account["abolished_batch_id"] = batch["id"]
        if account["bureau_status"] == "REPORTED":
            cdr = new_resource("cdrs", {
                "account_id": account["id"],
                "batch_id": batch["id"],
                "bureau": account["bureau_name"],
                "status": "SUBMITTED",
                "resubmission_count": 0,
                "rejection_reason": None,
            })
            account["bureau_status"] = "DELETION_REQUESTED"
        new_resource("letters", {
            "account_id": account["id"],
            "batch_id": batch["id"],
            "channel": "MAIL",
            "mailing_address": account["mailing_address"],
            "status": "QUEUED",
            "attempt_count": 0,
            "sent_at": None,
        })
        new_resource("tax_records", {
            "account_id": account["id"],
            "relief_amount_cents": final_value,
            "insolvency_exclusion_cents": None,
            "reportable_amount_cents": None,
            "status": "PENDING",
        })
        bump(account)

    for alloc in batch["funding_allocations"]:
        campaign = get_res("campaigns", alloc["campaign_id"])
        campaign["committed_cents"] -= alloc["amount_cents"]
        campaign["spent_cents"] += alloc["amount_cents"]
        bump(campaign)

    batch["status"] = "FINALIZED"
    bump(batch)

    portfolio["abolished_face_value_cents"] += batch["total_abolished_cents"]
    _maybe_auto_close(portfolio)
    bump(portfolio)
    return ok_object(public(batch))


@app.route("/api/abolishment-batches/<bid>/reverse", methods=["POST"])
def reverse_batch(bid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["FinanceOfficer"])
    batch = get_res("batches", bid)
    reason = req_str(body, "reason")
    if batch["status"] != "FINALIZED":
        invalid_state("Only a FINALIZED batch can be reversed")

    letters = [l for l in store.data["letters"].values() if l["batch_id"] == bid]
    cdrs = [c for c in store.data["cdrs"].values() if c["batch_id"] == bid]
    account_id_set = set(batch["account_ids"])
    tax_records = [
        t for t in store.data["tax_records"].values() if t["account_id"] in account_id_set
    ]

    irreversible = (
        any(l["status"] in ("SENT", "DELIVERED", "UNDELIVERABLE") for l in letters)
        or any(c["status"] == "ACKNOWLEDGED" for c in cdrs)
        or any(t["status"] in ("FILED", "EXEMPT") for t in tax_records)
    )
    if irreversible:
        raise ApiError("ERR_BATCH_IRREVERSIBLE", 409,
                       "Reverse blocked by an irreversible artifact")

    portfolio = get_res("portfolios", batch["portfolio_id"])

    for letter in letters:
        if letter["status"] in ("QUEUED", "BOUNCED"):
            letter["status"] = "CANCELLED"
            bump(letter)
    for cdr in cdrs:
        if cdr["status"] in ("DRAFT", "SUBMITTED", "REJECTED"):
            account = store.data["accounts"].get(cdr["account_id"])
            cdr["status"] = "CANCELLED"
            bump(cdr)
            if account is not None and account["bureau_status"] == "DELETION_REQUESTED":
                account["bureau_status"] = "REPORTED"
    for tax in tax_records:
        if tax["status"] in ("PENDING", "ASSESSED"):
            tax["status"] = "CANCELLED"
            bump(tax)

    for aid in batch["account_ids"]:
        account = store.data["accounts"][aid]
        account["lifecycle_status"] = "PURCHASED"
        account["abolished_amount_cents"] = None
        account["abolished_at"] = None
        account["abolished_batch_id"] = None
        bump(account)

    for alloc in batch["funding_allocations"]:
        campaign = get_res("campaigns", alloc["campaign_id"])
        campaign["spent_cents"] -= alloc["amount_cents"]
        bump(campaign)

    batch["status"] = "REVERSED"
    batch["reversed_reason"] = reason
    bump(batch)

    portfolio["abolished_face_value_cents"] -= batch["total_abolished_cents"]
    bump(portfolio)
    return ok_object(public(batch))


# ---------------------------------------------------------------------------
# NotificationLetter
# ---------------------------------------------------------------------------

@app.route("/api/notification-letters/<lid>", methods=["GET"])
def get_letter(lid):
    auth()
    return ok_object(public(get_res("letters", lid)))


@app.route("/api/notification-letters", methods=["GET"])
def list_letters():
    auth()
    return list_endpoint("letters", [
        ("account_id", _f_str("account_id")),
        ("batch_id", _f_str("batch_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/notification-letters/<lid>/send", methods=["POST"])
def send_letter(lid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    letter = get_res("letters", lid)
    if letter["status"] != "QUEUED":
        invalid_state("Only a QUEUED letter can be sent")
    batch = get_res("batches", letter["batch_id"])
    if batch["status"] != "FINALIZED":
        invalid_state("Letter send requires the parent batch to be FINALIZED")
    letter["status"] = "SENT"
    letter["sent_at"] = store.now_iso()
    bump(letter)
    return ok_object(public(letter))


@app.route("/api/notification-letters/<lid>/mark-delivered", methods=["POST"])
def mark_letter_delivered(lid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    letter = get_res("letters", lid)
    if letter["status"] != "SENT":
        invalid_state("Only a SENT letter can be marked delivered")
    letter["status"] = "DELIVERED"
    bump(letter)
    return ok_object(public(letter))


@app.route("/api/notification-letters/<lid>/mark-bounced", methods=["POST"])
def mark_letter_bounced(lid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    letter = get_res("letters", lid)
    if letter["status"] != "SENT":
        invalid_state("Only a SENT letter can be marked bounced")
    letter["attempt_count"] += 1
    if letter["attempt_count"] >= MAX_LETTER_ATTEMPTS:
        letter["status"] = "UNDELIVERABLE"
    else:
        letter["status"] = "BOUNCED"
    bump(letter)
    return ok_object(public(letter))


@app.route("/api/notification-letters/<lid>/requeue", methods=["POST"])
def requeue_letter(lid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    letter = get_res("letters", lid)
    corrected_address = opt_str(body, "corrected_address")
    if letter["status"] != "BOUNCED":
        invalid_state("Only a BOUNCED letter can be requeued")
    if letter["attempt_count"] >= MAX_LETTER_ATTEMPTS:
        raise ApiError("ERR_DELIVERY_ATTEMPTS_EXHAUSTED", 409,
                       "Requeue attempted when attempt_count >= MAX_LETTER_ATTEMPTS")
    if corrected_address is not None:
        letter["mailing_address"] = corrected_address
    letter["status"] = "QUEUED"
    bump(letter)
    return ok_object(public(letter))


# ---------------------------------------------------------------------------
# CreditDeletionRequest
# ---------------------------------------------------------------------------

@app.route("/api/accounts/<aid>/credit-deletion-requests", methods=["POST"])
def create_cdr(aid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    account = get_res("accounts", aid)
    bureau = req_enum(body, "bureau", BUREAUS)
    if account["lifecycle_status"] != "ABOLISHED":
        raise ApiError("ERR_ACCOUNT_NOT_ABOLISHED", 409,
                       "Manual CDR creation requires an ABOLISHED account")
    if account["bureau_status"] != "REPORTED":
        raise ApiError("ERR_BUREAU_NOT_REPORTED", 409,
                       "CDR creation requires account bureau_status == REPORTED")
    cdr = new_resource("cdrs", {
        "account_id": aid,
        "batch_id": None,
        "bureau": bureau,
        "status": "DRAFT",
        "resubmission_count": 0,
        "rejection_reason": None,
    })
    return ok_object(public(cdr), 201)


@app.route("/api/credit-deletion-requests/<cid>", methods=["GET"])
def get_cdr(cid):
    auth()
    return ok_object(public(get_res("cdrs", cid)))


@app.route("/api/credit-deletion-requests", methods=["GET"])
def list_cdrs():
    auth()
    return list_endpoint("cdrs", [
        ("account_id", _f_str("account_id")),
        ("batch_id", _f_str("batch_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/credit-deletion-requests/<cid>/submit", methods=["POST"])
def submit_cdr(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    cdr = get_res("cdrs", cid)
    if cdr["status"] != "DRAFT":
        invalid_state("Only a DRAFT deletion request can be submitted")
    account = get_res("accounts", cdr["account_id"])
    if account["lifecycle_status"] != "ABOLISHED":
        raise ApiError("ERR_ACCOUNT_NOT_ABOLISHED", 409,
                       "CDR submit requires an ABOLISHED account")
    if account["bureau_status"] != "REPORTED":
        raise ApiError("ERR_BUREAU_NOT_REPORTED", 409,
                       "CDR submit requires account bureau_status == REPORTED")
    cdr["status"] = "SUBMITTED"
    bump(cdr)
    account["bureau_status"] = "DELETION_REQUESTED"
    bump(account)
    return ok_object(public(cdr))


@app.route("/api/credit-deletion-requests/<cid>/acknowledge", methods=["POST"])
def acknowledge_cdr(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    cdr = get_res("cdrs", cid)
    if cdr["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED deletion request can be acknowledged")
    cdr["status"] = "ACKNOWLEDGED"
    bump(cdr)
    account = get_res("accounts", cdr["account_id"])
    account["bureau_status"] = "DELETED"
    bump(account)
    return ok_object(public(cdr))


@app.route("/api/credit-deletion-requests/<cid>/reject", methods=["POST"])
def reject_cdr(cid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    cdr = get_res("cdrs", cid)
    rejection_reason = req_str(body, "rejection_reason")
    if cdr["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED deletion request can be rejected")
    account = get_res("accounts", cdr["account_id"])
    cdr["rejection_reason"] = rejection_reason
    if cdr["resubmission_count"] >= MAX_CDR_RESUBMISSIONS:
        cdr["status"] = "FAILED"
        account["bureau_status"] = "DELETION_FAILED"
    else:
        cdr["status"] = "REJECTED"
        account["bureau_status"] = "REPORTED"
    bump(cdr)
    bump(account)
    return ok_object(public(cdr))


@app.route("/api/credit-deletion-requests/<cid>/resubmit", methods=["POST"])
def resubmit_cdr(cid):
    get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    cdr = get_res("cdrs", cid)
    if cdr["status"] != "REJECTED":
        invalid_state("Only a REJECTED deletion request can be resubmitted")
    if cdr["resubmission_count"] >= MAX_CDR_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT", 409,
                       "CDR resubmit attempted when resubmission_count >= MAX_CDR_RESUBMISSIONS")
    cdr["status"] = "SUBMITTED"
    cdr["resubmission_count"] += 1
    bump(cdr)
    account = get_res("accounts", cdr["account_id"])
    account["bureau_status"] = "DELETION_REQUESTED"
    bump(account)
    return ok_object(public(cdr))


# ---------------------------------------------------------------------------
# TaxReliefRecord
# ---------------------------------------------------------------------------

@app.route("/api/tax-relief-records/<tid>", methods=["GET"])
def get_tax_record(tid):
    auth()
    return ok_object(public(get_res("tax_records", tid)))


@app.route("/api/tax-relief-records", methods=["GET"])
def list_tax_records():
    auth()
    return list_endpoint("tax_records", [
        ("account_id", _f_str("account_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/tax-relief-records/<tid>/assess", methods=["POST"])
def assess_tax_record(tid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    record = get_res("tax_records", tid)
    exclusion = req_int(body, "insolvency_exclusion_cents")
    if record["status"] != "PENDING":
        invalid_state("Only a PENDING tax relief record can be assessed")
    if exclusion < 0 or exclusion > record["relief_amount_cents"]:
        raise ApiError("ERR_INVALID_AMOUNT", 422,
                       "insolvency_exclusion_cents outside [0, relief_amount_cents]")
    reportable = record["relief_amount_cents"] - exclusion
    record["insolvency_exclusion_cents"] = exclusion
    record["reportable_amount_cents"] = reportable
    record["status"] = "EXEMPT" if reportable == 0 else "ASSESSED"
    bump(record)
    return ok_object(public(record))


@app.route("/api/tax-relief-records/<tid>/file", methods=["POST"])
def file_tax_record(tid):
    get_body()
    user_id, role = auth()
    require_role(role, ["ComplianceAuditor"])
    record = get_res("tax_records", tid)
    if record["status"] != "ASSESSED":
        invalid_state("Only an ASSESSED tax relief record can be filed")
    record["status"] = "FILED"
    bump(record)
    return ok_object(public(record))


# ---------------------------------------------------------------------------
# HospitalPartnership / PartnershipMilestone
# ---------------------------------------------------------------------------

@app.route("/api/hospital-partnerships", methods=["POST"])
def create_partnership():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    source_org_id = req_str(body, "source_org_id")
    baseline = req_int(body, "fap_baseline_score")
    target = req_int(body, "fap_target_score")
    if baseline < 0 or baseline > 100 or target < 0 or target > 100:
        raise err("fap scores must be integers 0..100")
    if target <= baseline:
        raise err("fap_target_score must be > fap_baseline_score")
    org = store.data["orgs"].get(source_org_id)
    if org is None:
        raise ApiError("ERR_SOURCE_ORG_NOT_FOUND", 404, "source_org_id does not exist")
    if org["org_type"] != "HOSPITAL":
        raise ApiError("ERR_PARTNERSHIP_NOT_HOSPITAL", 422,
                       "Partnership source org must be org_type HOSPITAL")
    partnership = new_resource("partnerships", {
        "source_org_id": source_org_id,
        "fap_baseline_score": baseline,
        "fap_target_score": target,
        "fap_current_score": baseline,
        "status": "PROPOSED",
    })
    return ok_object(public(partnership), 201)


@app.route("/api/hospital-partnerships/<pid>", methods=["GET"])
def get_partnership(pid):
    auth()
    return ok_object(public(get_res("partnerships", pid)))


@app.route("/api/hospital-partnerships", methods=["GET"])
def list_partnerships():
    auth()
    return list_endpoint("partnerships", [
        ("source_org_id", _f_str("source_org_id")),
        ("status", _f_str("status")),
    ])


def _partnership_transition(pid, expected, target):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    partnership = get_res("partnerships", pid)
    if partnership["status"] != expected:
        invalid_state("Partnership must be %s for this transition" % expected)
    partnership["status"] = target
    bump(partnership)
    return ok_object(public(partnership))


@app.route("/api/hospital-partnerships/<pid>/activate", methods=["POST"])
def activate_partnership(pid):
    return _partnership_transition(pid, "PROPOSED", "ACTIVE")


@app.route("/api/hospital-partnerships/<pid>/suspend", methods=["POST"])
def suspend_partnership(pid):
    return _partnership_transition(pid, "ACTIVE", "SUSPENDED")


@app.route("/api/hospital-partnerships/<pid>/resume", methods=["POST"])
def resume_partnership(pid):
    return _partnership_transition(pid, "SUSPENDED", "ACTIVE")


@app.route("/api/hospital-partnerships/<pid>/complete", methods=["POST"])
def complete_partnership(pid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    partnership = get_res("partnerships", pid)
    if partnership["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE partnership can be completed")
    milestones = [
        m for m in store.data["milestones"].values() if m["partnership_id"] == pid
    ]
    if any(m["status"] not in ("MET", "MISSED", "WAIVED") for m in milestones):
        raise ApiError("ERR_MILESTONE_NOT_TERMINAL", 409,
                       "Partnership complete requires every milestone in {MET, MISSED, WAIVED}")
    if partnership["fap_current_score"] < partnership["fap_target_score"]:
        raise ApiError("ERR_FAP_TARGET_NOT_MET", 409,
                       "Partnership complete requires fap_current_score >= fap_target_score")
    partnership["status"] = "COMPLETED"
    bump(partnership)
    return ok_object(public(partnership))


def recompute_fap(partnership):
    milestones = [
        m for m in store.data["milestones"].values()
        if m["partnership_id"] == partnership["id"]
    ]
    denom = sum(m["weight"] for m in milestones if m["status"] != "WAIVED")
    if denom == 0:
        partnership["fap_current_score"] = partnership["fap_baseline_score"]
    else:
        numer = sum(m["weight"] for m in milestones if m["status"] == "MET")
        score = (Decimal(100) * Decimal(numer) / Decimal(denom)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        partnership["fap_current_score"] = int(score)


@app.route("/api/hospital-partnerships/<pid>/milestones", methods=["POST"])
def create_milestone(pid):
    body = get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer", "HospitalPartner"])
    partnership = get_res("partnerships", pid)
    if role == "HospitalPartner" and user_id != partnership["source_org_id"]:
        forbidden("HospitalPartner may act only on its own org's partnership")
    code = req_str(body, "code")
    description = req_str(body, "description")
    weight = req_int(body, "weight")
    if weight <= 0:
        raise err("weight must be > 0")
    due_date = req_date(body, "due_date")
    for m in store.data["milestones"].values():
        if m["partnership_id"] == pid and m["code"] == code:
            raise ApiError("ERR_DUPLICATE_MILESTONE_CODE", 409,
                           "Milestone code already used within the partnership")
    milestone = new_resource("milestones", {
        "partnership_id": pid,
        "code": code,
        "description": description,
        "weight": weight,
        "due_date": due_date.isoformat(),
        "status": "PENDING",
    })
    recompute_fap(partnership)
    bump(partnership)
    return ok_object(public(milestone), 201)


@app.route("/api/partnership-milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    auth()
    return ok_object(public(get_res("milestones", mid)))


@app.route("/api/partnership-milestones", methods=["GET"])
def list_milestones():
    auth()
    return list_endpoint("milestones", [
        ("partnership_id", _f_str("partnership_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/partnership-milestones/<mid>/mark-met", methods=["POST"])
def mark_milestone_met(mid):
    get_body()
    user_id, role = auth()
    require_role(role, ["HospitalPartner", "DonorRelationsOfficer"])
    milestone = get_res("milestones", mid)
    partnership = get_res("partnerships", milestone["partnership_id"])
    if role == "HospitalPartner" and user_id != partnership["source_org_id"]:
        forbidden("HospitalPartner may act only on its own org's milestones")
    if milestone["status"] not in ("PENDING", "MISSED"):
        invalid_state("Only a PENDING or MISSED milestone can be marked met")
    if partnership["status"] != "ACTIVE":
        invalid_state("Milestone transitions require an ACTIVE partnership")
    milestone["status"] = "MET"
    bump(milestone)
    recompute_fap(partnership)
    bump(partnership)
    return ok_object(public(milestone))


@app.route("/api/partnership-milestones/<mid>/mark-missed", methods=["POST"])
def mark_milestone_missed(mid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    milestone = get_res("milestones", mid)
    partnership = get_res("partnerships", milestone["partnership_id"])
    if milestone["status"] != "PENDING":
        invalid_state("Only a PENDING milestone can be marked missed")
    if partnership["status"] != "ACTIVE":
        invalid_state("Milestone transitions require an ACTIVE partnership")
    due = dt.date.fromisoformat(milestone["due_date"])
    if store.now().date() <= due:
        invalid_state("Milestone may be marked missed only once its due_date has passed")
    milestone["status"] = "MISSED"
    bump(milestone)
    return ok_object(public(milestone))


@app.route("/api/partnership-milestones/<mid>/waive", methods=["POST"])
def waive_milestone(mid):
    get_body()
    user_id, role = auth()
    require_role(role, ["DonorRelationsOfficer"])
    milestone = get_res("milestones", mid)
    partnership = get_res("partnerships", milestone["partnership_id"])
    if milestone["status"] not in ("PENDING", "MISSED"):
        invalid_state("Only a PENDING or MISSED milestone can be waived")
    if partnership["status"] != "ACTIVE":
        invalid_state("Milestone transitions require an ACTIVE partnership")
    milestone["status"] = "WAIVED"
    bump(milestone)
    recompute_fap(partnership)
    bump(partnership)
    return ok_object(public(milestone))


# ---------------------------------------------------------------------------
# ImpactReport
# ---------------------------------------------------------------------------

@app.route("/api/impact-reports", methods=["POST"])
def create_impact_report():
    body = get_body()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin", "ComplianceAuditor"])
    scope = req_enum(body, "scope", REPORT_SCOPES)
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    counting_variant = req_enum(body, "counting_variant", COUNTING_VARIANTS)
    scope_state_code = opt_str(body, "scope_state_code")
    scope_source_org_id = body.get("scope_source_org_id")
    if scope_source_org_id is not None and (not isinstance(scope_source_org_id, str) or scope_source_org_id == ""):
        raise err("scope_source_org_id must be a string when present")
    if period_end < period_start:
        raise err("period_end must be >= period_start")

    if scope == "GEOGRAPHY":
        if scope_state_code is None:
            raise err("scope_state_code is required for scope GEOGRAPHY")
        if scope_source_org_id is not None:
            raise err("scope_source_org_id must be null for scope GEOGRAPHY")
    elif scope == "HOSPITAL":
        if scope_source_org_id is None:
            raise err("scope_source_org_id is required for scope HOSPITAL")
        if scope_state_code is not None:
            raise err("scope_state_code must be null for scope HOSPITAL")
        org = store.data["orgs"].get(scope_source_org_id)
        if org is None:
            raise ApiError("ERR_SOURCE_ORG_NOT_FOUND", 404, "scope_source_org_id does not exist")
    else:  # GLOBAL
        if scope_state_code is not None or scope_source_org_id is not None:
            raise err("GLOBAL reports carry no scope key fields")

    in_scope = []
    for account in store.data["accounts"].values():
        if account["lifecycle_status"] != "ABOLISHED":
            continue
        abolished_at = account["abolished_at"]
        if not abolished_at:
            continue
        abolished_date = Store._parse_iso(abolished_at).date()
        if not (period_start <= abolished_date <= period_end):
            continue
        if scope == "GEOGRAPHY" and account["debtor_state"] != scope_state_code:
            continue
        if scope == "HOSPITAL":
            portfolio = store.data["portfolios"].get(account["portfolio_id"])
            if portfolio is None or portfolio["source_org_id"] != scope_source_org_id:
                continue
        in_scope.append(account)

    dollars = sum(a["abolished_amount_cents"] or 0 for a in in_scope)
    if counting_variant == "PER_ACCOUNT":
        households = len(in_scope)
    else:
        households = len({a["debtor_household_key"] for a in in_scope})

    report = new_resource("reports", {
        "scope": scope,
        "scope_state_code": scope_state_code,
        "scope_source_org_id": scope_source_org_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "counting_variant": counting_variant,
        "households_relieved": households,
        "dollars_abolished_cents": dollars,
        "status": "DRAFT",
    })
    return ok_object(public(report), 201)


@app.route("/api/impact-reports/<rid>", methods=["GET"])
def get_impact_report(rid):
    auth()
    return ok_object(public(get_res("reports", rid)))


@app.route("/api/impact-reports", methods=["GET"])
def list_impact_reports():
    auth()
    return list_endpoint("reports", [
        ("scope", _f_str("scope")),
        ("scope_source_org_id", _f_str("scope_source_org_id")),
        ("status", _f_str("status")),
    ])


@app.route("/api/impact-reports/<rid>/publish", methods=["POST"])
def publish_impact_report(rid):
    get_body()
    user_id, role = auth()
    require_role(role, ["PlatformAdmin", "ComplianceAuditor"])
    report = get_res("reports", rid)
    if report["status"] != "DRAFT":
        invalid_state("Only a DRAFT report can be published")
    p_start = dt.date.fromisoformat(report["period_start"])
    p_end = dt.date.fromisoformat(report["period_end"])
    for other in store.data["reports"].values():
        if other["id"] == report["id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if other["scope"] != report["scope"]:
            continue
        if other["scope_state_code"] != report["scope_state_code"]:
            continue
        if other["scope_source_org_id"] != report["scope_source_org_id"]:
            continue
        o_start = dt.date.fromisoformat(other["period_start"])
        o_end = dt.date.fromisoformat(other["period_end"])
        # closed interval overlap; sharing a boundary date counts
        if p_start <= o_end and o_start <= p_end:
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                           "PUBLISHED report period overlaps another PUBLISHED report with the same scope key")
    report["status"] = "PUBLISHED"
    bump(report)
    return ok_object(public(report))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
