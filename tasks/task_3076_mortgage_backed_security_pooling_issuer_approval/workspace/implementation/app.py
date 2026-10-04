"""MBS Pooling & Issuer Approval API — in-memory implementation.

Single-file Flask app. Storage is in-memory dicts only; the store starts empty
on every boot. The logical clock defaults to 2026-09-01T00:00:00Z and is only
changed via POST /_clock/set_current_utc.
"""

import re
import threading
import uuid
from datetime import datetime, date

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD/SCAFFOLD calculation rules)
# ---------------------------------------------------------------------------

MIN_NET_WORTH_CENTS = 250000000
PER_BRANCH_NET_WORTH_CENTS = 25000000
VOLUME_NET_WORTH_BPS = 10

LIQUIDITY_MONITOR_THRESHOLD_BPS = 500
LIQUIDITY_HARD_FLOOR_BPS = 300

PASS_THROUGH_MONTHS = 12

POOL_DELINQUENCY_THRESHOLD_BPS = 500

ESCROW_TAX_SHARE_BPS = 6000

MIN_POOL_PRINCIPAL_CENTS = 100000000
MAX_LOANS_PER_POOL = {"SINGLE_FAMILY": 3, "MANUFACTURED_HOME": 3, "MULTIFAMILY": 2}

POOL_TYPE_TERMS = {
    "SINGLE_FAMILY": {360, 180},
    "MANUFACTURED_HOME": {240},
    "MULTIFAMILY": {360},
}

GOVERNMENT_INSURANCE_VALUES = {"FHA", "VA", "USDA", "PIH"}
POOL_TYPES = set(POOL_TYPE_TERMS.keys())
ACCOUNT_TYPES = {"P_AND_I", "T_AND_I"}
TRANSACTION_COMPONENTS = {"PRINCIPAL", "INTEREST", "TAX", "INSURANCE", "ESCROW"}
CERT_DECISIONS = {"CERTIFIED", "EXCEPTION"}
LOAN_STATUSES = {"CURRENT", "DELINQ_30", "DELINQ_60", "DELINQ_90_PLUS", "FORECLOSURE", "PAID_OFF"}
DELINQUENT_SET = {"DELINQ_60", "DELINQ_90_PLUS", "FORECLOSURE"}

VALID_ROLES = {
    "ApplicantOfficer",
    "AgencyReviewer",
    "IssuerOfficer",
    "DocumentCustodian",
    "PlatformAdmin",
}

CLOCK_START_DEFAULT = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

lock = threading.RLock()

db = {
    "issuer_applications": {},
    "issuers": {},
    "document_custodians": {},
    "custodian_engagements": {},
    "pools": {},
    "loans": {},
    "custodial_accounts": {},
    "account_transactions": {},
    "loan_file_certifications": {},
    "investor_reports": {},
    "pass_through_payments": {},
    "liquidity_advances": {},
    "delinquency_breaches": {},
    "corrective_action_plans": {},
    "portfolio_transfers": {},
}

clock = {"current_utc": CLOCK_START_DEFAULT}

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
# Helpers
# ---------------------------------------------------------------------------


def now_iso():
    """api_request_timestamp: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:24], "api_request_timestamp": now_iso()}


def success_object(data, status=200):
    body = {"meta": request_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(500)
def handle_500(e):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Internal server error"},
    }
    return jsonify(body), 500


def get_auth():
    """Validate auth headers; returns (user_id, role). Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "X-User-ID / X-User-Role missing or role unrecognized")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE", 403, "Role not permitted for this endpoint")


def parse_body(required_fields=None, optional_fields=None):
    """Parse JSON body; validate required fields present and no type errors at shape level."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    if required_fields:
        for f in required_fields:
            if f not in data or data[f] is None:
                raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {f}")
    return data


def req_str(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
        return None
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a non-empty string")
    return v


def req_int(data, field, required=True, min_value=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= {min_value}")
    return v


def req_enum(data, field, allowed, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
        return None
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(allowed)}")
    return v


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def req_date(data, field, required=True):
    v = req_str(data, field, required=required)
    if v is None:
        return None
    if not DATE_RE.match(v):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a YYYY-MM-DD date")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a valid date")
    return v


def req_month(data, field, required=True):
    v = req_str(data, field, required=required)
    if v is None:
        return None
    if not MONTH_RE.match(v):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a YYYY-MM month")
    y, m = int(v[:4]), int(v[5:7])
    if m < 1 or m > 12:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a valid month")
    return v


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def current_clock_date():
    """Return the logical clock date as YYYY-MM-DD."""
    return clock["current_utc"][:10]


def current_clock_month():
    return clock["current_utc"][:7]


# ---------------------------------------------------------------------------
# Entity serializers
# ---------------------------------------------------------------------------


def ser_application(a):
    return {
        "id": a["id"],
        "legal_name": a["legal_name"],
        "net_worth_cents": a["net_worth_cents"],
        "liquid_assets_cents": a["liquid_assets_cents"],
        "unused_credit_lines_cents": a["unused_credit_lines_cents"],
        "origination_experience_months": a["origination_experience_months"],
        "branch_count": a["branch_count"],
        "annual_origination_volume_cents": a["annual_origination_volume_cents"],
        "net_worth_requirement_cents": a["net_worth_requirement_cents"],
        "status": a["status"],
        "approved_issuer_id": a["approved_issuer_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def issuer_advance_obligation(issuer_id):
    return sum(
        adv["amount_cents"]
        for adv in db["liquidity_advances"].values()
        if adv["issuer_id"] == issuer_id and adv["status"] == "OPEN"
    )


def ser_issuer(i):
    obligation = issuer_advance_obligation(i["id"])
    if obligation == 0:
        ratio_excl = None
        ratio_incl = None
    else:
        ratio_excl = (i["liquid_assets_cents"] * 10000) // obligation
        ratio_incl = ((i["liquid_assets_cents"] + i["unused_credit_lines_cents"]) * 10000) // obligation
    return {
        "id": i["id"],
        "application_id": i["application_id"],
        "legal_name": i["legal_name"],
        "net_worth_cents": i["net_worth_cents"],
        "liquid_assets_cents": i["liquid_assets_cents"],
        "unused_credit_lines_cents": i["unused_credit_lines_cents"],
        "advance_obligation_cents": obligation,
        "liquidity_ratio_excluding_credit_bps": ratio_excl,
        "liquidity_ratio_including_credit_bps": ratio_incl,
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_custodian(c):
    return {
        "id": c["id"],
        "firm_name": c["firm_name"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_engagement(e):
    return {
        "id": e["id"],
        "custodian_id": e["custodian_id"],
        "issuer_id": e["issuer_id"],
        "window_start": e["window_start"],
        "window_end": e["window_end"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def pool_loans(pool_id):
    return [l for l in db["loans"].values() if l["pool_id"] == pool_id]


def pool_aggregate_principal(pool_id):
    return sum(l["principal_balance_cents"] for l in pool_loans(pool_id) if l["status"] != "PAID_OFF")


def round_half_up_div(numer, denom):
    """round_half_up(numer / denom) for non-negative integers."""
    if denom == 0:
        return 0
    return (2 * numer + denom) // (2 * denom)


def pool_delinquency_rate(pool_id):
    denom = pool_aggregate_principal(pool_id)
    if denom == 0:
        return 0
    numer = sum(
        l["principal_balance_cents"]
        for l in pool_loans(pool_id)
        if l["status"] in DELINQUENT_SET
    )
    return round_half_up_div(numer * 10000, denom)


def ser_pool(p):
    return {
        "id": p["id"],
        "issuer_id": p["issuer_id"],
        "custodian_id": p["custodian_id"],
        "pool_type": p["pool_type"],
        "term_months": p["term_months"],
        "note_rate_bps": p["note_rate_bps"],
        "aggregate_principal_cents": pool_aggregate_principal(p["id"]),
        "delinquency_rate_bps": pool_delinquency_rate(p["id"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_loan(l):
    return {
        "id": l["id"],
        "pool_id": l["pool_id"],
        "principal_balance_cents": l["principal_balance_cents"],
        "note_rate_bps": l["note_rate_bps"],
        "government_insurance": l["government_insurance"],
        "escrow_monthly_cents": l["escrow_monthly_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def account_balances(acct):
    """Recompute component balances from the transaction ledger."""
    principal = interest = tax = insurance = 0
    for txn in db["account_transactions"].values():
        if txn["account_id"] != acct["id"]:
            continue
        comp = txn["component"]
        amt = txn["amount_cents"]
        sign = 1 if txn["direction"] == "DEPOSIT" else -1
        if comp == "PRINCIPAL":
            principal += sign * amt
        elif comp == "INTEREST":
            interest += sign * amt
        elif comp == "TAX":
            tax += sign * amt
        elif comp == "INSURANCE":
            insurance += sign * amt
        elif comp == "ESCROW":
            # ESCROW only ever appears as DEPOSIT on T_AND_I; use stored splits
            tax += sign * (txn.get("tax_split_cents") or 0)
            insurance += sign * (txn.get("insurance_split_cents") or 0)
    return principal, interest, tax, insurance


def ser_account(acct):
    principal, interest, tax, insurance = account_balances(acct)
    if acct["account_type"] == "P_AND_I":
        balance = principal + interest
    else:
        balance = tax + insurance
    return {
        "id": acct["id"],
        "issuer_id": acct["issuer_id"],
        "account_type": acct["account_type"],
        "principal_balance_cents": principal,
        "interest_balance_cents": interest,
        "tax_balance_cents": tax,
        "insurance_balance_cents": insurance,
        "balance_cents": balance,
        "status": acct["status"],
        "created_at": acct["created_at"],
        "updated_at": acct["updated_at"],
        "version": acct["version"],
    }


def ser_transaction(t):
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "direction": t["direction"],
        "component": t["component"],
        "amount_cents": t["amount_cents"],
        "loan_id": t.get("loan_id"),
        "tax_split_cents": t.get("tax_split_cents"),
        "insurance_split_cents": t.get("insurance_split_cents"),
        "created_at": t["created_at"],
    }


def ser_certification(c):
    return {
        "id": c["id"],
        "pool_id": c["pool_id"],
        "custodian_id": c["custodian_id"],
        "decision": c["decision"],
        "exception_loan_ids": c["exception_loan_ids"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "pool_id": r["pool_id"],
        "period_month": r["period_month"],
        "scheduled_payment_cents": r["scheduled_payment_cents"],
        "actual_collected_cents": r["actual_collected_cents"],
        "advance_required_cents": r["advance_required_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "report_id": p["report_id"],
        "amount_cents": p["amount_cents"],
        "funding_source": p["funding_source"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_advance(a):
    return {
        "id": a["id"],
        "issuer_id": a["issuer_id"],
        "payment_id": a["payment_id"],
        "amount_cents": a["amount_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_breach(b):
    return {
        "id": b["id"],
        "issuer_id": b["issuer_id"],
        "pool_id": b["pool_id"],
        "delinquency_rate_bps_at_breach": b["delinquency_rate_bps_at_breach"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "breach_id": p["breach_id"],
        "plan_summary": p["plan_summary"],
        "target_cure_month": p["target_cure_month"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "defaulted_issuer_id": t["defaulted_issuer_id"],
        "successor_issuer_id": t["successor_issuer_id"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Business logic helpers
# ---------------------------------------------------------------------------


def compute_net_worth_requirement(branch_count, annual_origination_volume_cents):
    branch_component = (branch_count - 1) * PER_BRANCH_NET_WORTH_CENTS
    volume_component = (annual_origination_volume_cents * VOLUME_NET_WORTH_BPS) // 100
    return max(MIN_NET_WORTH_CENTS + branch_component, volume_component)


def get_issuer_or_404(issuer_id):
    i = db["issuers"].get(issuer_id)
    if i is None:
        raise err("ERR_ISSUER_NOT_FOUND", 404, "Issuer id does not exist")
    return i


def get_pool_or_404(pool_id):
    p = db["pools"].get(pool_id)
    if p is None:
        raise err("ERR_POOL_NOT_FOUND", 404, "Pool id does not exist")
    return p


def get_application_or_404(app_id):
    a = db["issuer_applications"].get(app_id)
    if a is None:
        raise err("ERR_APPLICATION_NOT_FOUND", 404, "IssuerApplication id does not exist")
    return a


def get_custodian_or_404(custodian_id):
    c = db["document_custodians"].get(custodian_id)
    if c is None:
        raise err("ERR_CUSTODIAN_NOT_FOUND", 404, "DocumentCustodian id does not exist")
    return c


def get_engagement_or_404(eng_id):
    e = db["custodian_engagements"].get(eng_id)
    if e is None:
        raise err("ERR_ENGAGEMENT_NOT_FOUND", 404, "CustodianEngagement id does not exist")
    return e


def get_loan_or_404(loan_id):
    l = db["loans"].get(loan_id)
    if l is None:
        raise err("ERR_LOAN_NOT_FOUND", 404, "Loan id does not exist")
    return l


def get_account_or_404(account_id):
    a = db["custodial_accounts"].get(account_id)
    if a is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", 404, "CustodialAccount id does not exist")
    return a


def get_report_or_404(report_id):
    r = db["investor_reports"].get(report_id)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", 404, "InvestorReport id does not exist")
    return r


def get_payment_or_404(payment_id):
    p = db["pass_through_payments"].get(payment_id)
    if p is None:
        raise err("ERR_PAYMENT_NOT_FOUND", 404, "PassThroughPayment id does not exist")
    return p


def get_advance_or_404(advance_id):
    a = db["liquidity_advances"].get(advance_id)
    if a is None:
        raise err("ERR_ADVANCE_NOT_FOUND", 404, "LiquidityAdvance id does not exist")
    return a


def get_breach_or_404(breach_id):
    b = db["delinquency_breaches"].get(breach_id)
    if b is None:
        raise err("ERR_BREACH_NOT_FOUND", 404, "DelinquencyBreach id does not exist")
    return b


def get_plan_or_404(plan_id):
    p = db["corrective_action_plans"].get(plan_id)
    if p is None:
        raise err("ERR_PLAN_NOT_FOUND", 404, "CorrectiveActionPlan id does not exist")
    return p


def get_transfer_or_404(transfer_id):
    t = db["portfolio_transfers"].get(transfer_id)
    if t is None:
        raise err("ERR_TRANSFER_NOT_FOUND", 404, "PortfolioTransfer id does not exist")
    return t


def issuer_officer_owns(user_id, issuer_id):
    if user_id != issuer_id:
        raise err("ERR_NOT_RESOURCE_OWNER", 403, "IssuerOfficer X-User-ID does not own the target resource")


def engagement_coverage_exists(custodian_id, issuer_id, req_date):
    for e in db["custodian_engagements"].values():
        if (
            e["custodian_id"] == custodian_id
            and e["issuer_id"] == issuer_id
            and e["status"] == "ACTIVE"
            and e["window_start"] <= req_date < e["window_end"]
        ):
            return True
    return False


def require_engagement_coverage(custodian_id, issuer_id):
    req_date = current_clock_date()
    if not engagement_coverage_exists(custodian_id, issuer_id, req_date):
        raise err(
            "ERR_CUSTODIAN_ENGAGEMENT_GAP",
            422,
            "No ACTIVE engagement covers the request date for (pool.custodian_id, pool.issuer_id)",
        )


def freeze_issuer_accounts(issuer_id):
    for acct in db["custodial_accounts"].values():
        if acct["issuer_id"] == issuer_id and acct["status"] == "ACTIVE":
            acct["status"] = "FROZEN"
            touch(acct)


def thaw_issuer_accounts(issuer_id):
    for acct in db["custodial_accounts"].values():
        if acct["issuer_id"] == issuer_id and acct["status"] == "FROZEN":
            acct["status"] = "ACTIVE"
            touch(acct)


def close_issuer_accounts(issuer_id):
    for acct in db["custodial_accounts"].values():
        if acct["issuer_id"] == issuer_id and acct["status"] == "FROZEN":
            acct["status"] = "CLOSED"
            touch(acct)


def issuer_open_breaches(issuer_id):
    return [
        b
        for b in db["delinquency_breaches"].values()
        if b["issuer_id"] == issuer_id and b["status"] in ("OPEN", "MITIGATING")
    ]


def liquidity_threshold_evaluation(issuer):
    """Runs after every liquidity ratio recompute for the issuer."""
    obligation = issuer_advance_obligation(issuer["id"])
    ratio_excl = None if obligation == 0 else (issuer["liquid_assets_cents"] * 10000) // obligation

    if issuer["status"] in ("ACTIVE", "WATCH"):
        if ratio_excl is not None and ratio_excl < LIQUIDITY_HARD_FLOOR_BPS:
            issuer["status"] = "SUSPENDED"
            freeze_issuer_accounts(issuer["id"])
            touch(issuer)
    elif issuer["status"] == "SUSPENDED":
        # Recovery: ratio restored to >= hard floor
        restored = ratio_excl is None or ratio_excl >= LIQUIDITY_HARD_FLOOR_BPS
        if restored:
            if issuer_open_breaches(issuer["id"]):
                issuer["status"] = "WATCH"
            else:
                issuer["status"] = "ACTIVE"
            thaw_issuer_accounts(issuer["id"])
            touch(issuer)


def pool_threshold_evaluation(pool):
    """Runs after every delinquency rate recompute for the pool."""
    rate = pool_delinquency_rate(pool["id"])
    if rate >= POOL_DELINQUENCY_THRESHOLD_BPS:
        breach_exists = any(
            b["pool_id"] == pool["id"] and b["status"] in ("OPEN", "MITIGATING")
            for b in db["delinquency_breaches"].values()
        )
        if not breach_exists:
            issuer = db["issuers"].get(pool["issuer_id"])
            b = {
                "id": new_id(),
                "issuer_id": pool["issuer_id"],
                "pool_id": pool["id"],
                "delinquency_rate_bps_at_breach": rate,
                "status": "OPEN",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "version": 1,
            }
            db["delinquency_breaches"][b["id"]] = b
            if issuer is not None and issuer["status"] == "ACTIVE":
                issuer["status"] = "WATCH"
                touch(issuer)


def reevaluate_issuer_from_breach(issuer):
    """After CAP accept or breach close: WATCH -> ACTIVE if clear."""
    if issuer["status"] == "WATCH":
        if not issuer_open_breaches(issuer["id"]):
            obligation = issuer_advance_obligation(issuer["id"])
            ratio_excl = (
                None if obligation == 0 else (issuer["liquid_assets_cents"] * 10000) // obligation
            )
            if ratio_excl is None or ratio_excl >= LIQUIDITY_HARD_FLOOR_BPS:
                issuer["status"] = "ACTIVE"
                touch(issuer)


def compute_pass_through(pool, collection_rate_bps):
    """Returns (scheduled_payment_cents, actual_collected_cents, advance_required_cents)."""
    rate_bps = pool["note_rate_bps"]
    scheduled = 0
    unrounded_sum = 0  # in units of cents*bps (principal * note_rate_bps), divided later
    for l in pool_loans(pool["id"]):
        if l["status"] == "PAID_OFF":
            continue
        # per-loan scheduled interest floored, then summed
        per_loan = (l["principal_balance_cents"] * rate_bps) // 10000 // PASS_THROUGH_MONTHS
        scheduled += per_loan
        unrounded_sum += l["principal_balance_cents"] * rate_bps
    # actual: unrounded aggregate ratio scaled by collection rate, floored once
    # aggregate_ratio = unrounded_sum / 10000 / 12 ; actual = floor(aggregate_ratio * collection / 10000)
    # Keep integer-exact: floor(unrounded_sum * collection / (10000 * 12 * 10000))
    actual = (unrounded_sum * collection_rate_bps) // (10000 * PASS_THROUGH_MONTHS * 10000)
    advance = scheduled - actual
    return scheduled, actual, advance


def create_investor_report(pool_id, period_month, collection_rate_bps):
    pool = db["pools"][pool_id]
    scheduled, actual, advance = compute_pass_through(pool, collection_rate_bps)
    r = {
        "id": new_id(),
        "pool_id": pool_id,
        "period_month": period_month,
        "scheduled_payment_cents": scheduled,
        "actual_collected_cents": actual,
        "advance_required_cents": advance,
        "status": "DRAFT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db["investor_reports"][r["id"]] = r
    return r


def find_pandi_account(issuer_id):
    for acct in db["custodial_accounts"].values():
        if acct["issuer_id"] == issuer_id and acct["account_type"] == "P_AND_I":
            return acct
    return None


def post_transaction(account_id, direction, component, amount_cents, loan_id=None,
                     tax_split_cents=None, insurance_split_cents=None):
    t = {
        "id": new_id(),
        "account_id": account_id,
        "direction": direction,
        "component": component,
        "amount_cents": amount_cents,
        "loan_id": loan_id,
        "tax_split_cents": tax_split_cents,
        "insurance_split_cents": insurance_split_cents,
        "created_at": now_iso(),
    }
    db["account_transactions"][t["id"]] = t
    return t


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    data = parse_body(["current_utc"])
    v = data["current_utc"]
    if not isinstance(v, str) or not TS_RE.match(v):
        raise err("ERR_INVALID_REQUEST", 400, "current_utc must be an ISO 8601 UTC timestamp")
    clock["current_utc"] = v
    return success_object({"current_utc": v})


# ---------------------------------------------------------------------------
# IssuerApplication endpoints
# ---------------------------------------------------------------------------


@app.route("/issuer-applications", methods=["POST"])
def create_application():
    user_id, role = get_auth()
    require_role(role, {"ApplicantOfficer"})
    data = parse_body([
        "legal_name",
        "net_worth_cents",
        "liquid_assets_cents",
        "origination_experience_months",
        "branch_count",
        "annual_origination_volume_cents",
    ])
    legal_name = req_str(data, "legal_name")
    net_worth = req_int(data, "net_worth_cents", min_value=0)
    liquid = req_int(data, "liquid_assets_cents", min_value=0)
    credit = req_int(data, "unused_credit_lines_cents", required=False, min_value=0)
    if credit is None:
        credit = 0
    experience = req_int(data, "origination_experience_months", min_value=0)
    branches = req_int(data, "branch_count", min_value=1)
    volume = req_int(data, "annual_origination_volume_cents", min_value=0)

    requirement = compute_net_worth_requirement(branches, volume)
    now = now_iso()
    a = {
        "id": new_id(),
        "legal_name": legal_name,
        "net_worth_cents": net_worth,
        "liquid_assets_cents": liquid,
        "unused_credit_lines_cents": credit,
        "origination_experience_months": experience,
        "branch_count": branches,
        "annual_origination_volume_cents": volume,
        "net_worth_requirement_cents": requirement,
        "status": "DRAFT",
        "approved_issuer_id": None,
        "submitted_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["issuer_applications"][a["id"]] = a
    return success_object(ser_application(a), status=201)


@app.route("/issuer-applications", methods=["GET"])
def list_applications():
    user_id, role = get_auth()
    require_role(role, {"ApplicantOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = sorted(db["issuer_applications"].values(), key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_application(a) for a in page], total, limit, offset)


@app.route("/issuer-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"ApplicantOfficer", "AgencyReviewer", "PlatformAdmin"})
    a = get_application_or_404(app_id)
    return success_object(ser_application(a))


APPLICATION_PATCH_FIELDS = [
    "legal_name",
    "net_worth_cents",
    "liquid_assets_cents",
    "unused_credit_lines_cents",
    "origination_experience_months",
    "branch_count",
    "annual_origination_volume_cents",
]


@app.route("/issuer-applications/<app_id>", methods=["PATCH"])
def patch_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"ApplicantOfficer"})
    a = get_application_or_404(app_id)
    if a["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in a state permitting edit")
    data = parse_body(["expected_application_version"])
    expected = req_int(data, "expected_application_version")
    if expected != a["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_application_version does not match current version")

    for f in APPLICATION_PATCH_FIELDS:
        if f in data and data[f] is not None:
            if f == "legal_name":
                a[f] = req_str(data, f)
            elif f == "branch_count":
                a[f] = req_int(data, f, min_value=1)
            else:
                a[f] = req_int(data, f, min_value=0)

    a["net_worth_requirement_cents"] = compute_net_worth_requirement(
        a["branch_count"], a["annual_origination_volume_cents"]
    )
    if a["status"] == "REVISION_REQUESTED":
        a["status"] = "DRAFT"
    touch(a)
    return success_object(ser_application(a))


@app.route("/issuer-applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"ApplicantOfficer"})
    a = get_application_or_404(app_id)
    if a["status"] != "DRAFT":
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in DRAFT")
    if a["net_worth_cents"] < a["net_worth_requirement_cents"]:
        raise err("ERR_NET_WORTH_DEFICIENT", 422, "net_worth_cents below tiered requirement at submit")
    if a["liquid_assets_cents"] > a["net_worth_cents"]:
        raise err("ERR_LIQUIDITY_EXCEEDS_NET_WORTH", 422, "liquid_assets_cents exceeds net_worth_cents at submit")
    if a["origination_experience_months"] < 24:
        raise err("ERR_INSUFFICIENT_EXPERIENCE", 422, "origination_experience_months < 24 at submit")
    a["status"] = "SUBMITTED"
    a["submitted_by"] = user_id
    touch(a)
    return success_object(ser_application(a))


@app.route("/issuer-applications/<app_id>/review", methods=["POST"])
def review_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    a = get_application_or_404(app_id)
    if a["status"] != "SUBMITTED":
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in SUBMITTED")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(ser_application(a))


@app.route("/issuer-applications/<app_id>/request-revision", methods=["POST"])
def request_revision_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    a = get_application_or_404(app_id)
    if a["status"] != "UNDER_REVIEW":
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in UNDER_REVIEW")
    a["status"] = "REVISION_REQUESTED"
    touch(a)
    return success_object(ser_application(a))


def _check_segregation(a, user_id):
    if a.get("submitted_by") is not None and a["submitted_by"] == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Reviewer approving/denying an application submitted by the same user id",
        )


@app.route("/issuer-applications/<app_id>/approve", methods=["POST"])
def approve_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    a = get_application_or_404(app_id)
    if a["status"] != "UNDER_REVIEW":
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in UNDER_REVIEW")
    _check_segregation(a, user_id)
    a["status"] = "APPROVED"
    now = now_iso()
    issuer = {
        "id": new_id(),
        "application_id": a["id"],
        "legal_name": a["legal_name"],
        "net_worth_cents": a["net_worth_cents"],
        "liquid_assets_cents": a["liquid_assets_cents"],
        "unused_credit_lines_cents": a["unused_credit_lines_cents"],
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["issuers"][issuer["id"]] = issuer
    a["approved_issuer_id"] = issuer["id"]
    touch(a)
    return success_object(ser_application(a))


@app.route("/issuer-applications/<app_id>/deny", methods=["POST"])
def deny_application(app_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    a = get_application_or_404(app_id)
    if a["status"] != "UNDER_REVIEW":
        raise err("ERR_APPLICATION_INVALID_STATE", 409, "Application not in UNDER_REVIEW")
    _check_segregation(a, user_id)
    a["status"] = "DENIED"
    touch(a)
    return success_object(ser_application(a))


# ---------------------------------------------------------------------------
# Issuer endpoints
# ---------------------------------------------------------------------------


@app.route("/issuers", methods=["GET"])
def list_issuers():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    limit, offset = parse_pagination()
    app_filter = request.args.get("application_id")
    items = sorted(db["issuers"].values(), key=lambda x: x["created_at"])
    if app_filter is not None:
        items = [i for i in items if i["application_id"] == app_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_issuer(i) for i in page], total, limit, offset)


@app.route("/issuers/<issuer_id>", methods=["GET"])
def get_issuer(issuer_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    i = get_issuer_or_404(issuer_id)
    return success_object(ser_issuer(i))


@app.route("/issuers/<issuer_id>/financials", methods=["PATCH"])
def patch_issuer_financials(issuer_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    issuer = get_issuer_or_404(issuer_id)
    issuer_officer_owns(user_id, issuer["id"])
    data = parse_body(["expected_issuer_version"])
    expected = req_int(data, "expected_issuer_version")
    if expected != issuer["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_issuer_version does not match current version")
    if "liquid_assets_cents" in data and data["liquid_assets_cents"] is not None:
        issuer["liquid_assets_cents"] = req_int(data, "liquid_assets_cents", min_value=0)
    if "unused_credit_lines_cents" in data and data["unused_credit_lines_cents"] is not None:
        issuer["unused_credit_lines_cents"] = req_int(data, "unused_credit_lines_cents", min_value=0)
    touch(issuer)
    liquidity_threshold_evaluation(issuer)
    return success_object(ser_issuer(issuer))


@app.route("/issuers/<issuer_id>/default", methods=["POST"])
def default_issuer(issuer_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    issuer = get_issuer_or_404(issuer_id)
    if issuer["status"] not in ("ACTIVE", "WATCH", "SUSPENDED"):
        raise err("ERR_ISSUER_INVALID_STATE", 409, "Issuer not in a state permitting default")
    issuer["status"] = "DEFAULTED"
    freeze_issuer_accounts(issuer["id"])
    touch(issuer)
    return success_object(ser_issuer(issuer))


# ---------------------------------------------------------------------------
# DocumentCustodian endpoints
# ---------------------------------------------------------------------------


@app.route("/document-custodians", methods=["POST"])
def create_custodian():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    data = parse_body(["firm_name"])
    firm_name = req_str(data, "firm_name")
    now = now_iso()
    c = {
        "id": new_id(),
        "firm_name": firm_name,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["document_custodians"][c["id"]] = c
    return success_object(ser_custodian(c), status=201)


@app.route("/document-custodians", methods=["GET"])
def list_custodians():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin", "AgencyReviewer", "IssuerOfficer", "DocumentCustodian"})
    limit, offset = parse_pagination()
    items = sorted(db["document_custodians"].values(), key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_custodian(c) for c in page], total, limit, offset)


@app.route("/document-custodians/<custodian_id>", methods=["GET"])
def get_custodian(custodian_id):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin", "AgencyReviewer", "IssuerOfficer", "DocumentCustodian"})
    c = get_custodian_or_404(custodian_id)
    return success_object(ser_custodian(c))


# ---------------------------------------------------------------------------
# CustodianEngagement endpoints
# ---------------------------------------------------------------------------


@app.route("/custodian-engagements", methods=["POST"])
def create_engagement():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    custodian_id = req_str(data, "custodian_id")
    issuer_id = req_str(data, "issuer_id")

    get_custodian_or_404(custodian_id)
    issuer = get_issuer_or_404(issuer_id)
    issuer_officer_owns(user_id, issuer["id"])

    window_start = req_date(data, "window_start")
    window_end = req_date(data, "window_end")

    if issuer["status"] != "ACTIVE":
        raise err("ERR_ISSUER_NOT_ACTIVE", 422, "Issuer not ACTIVE blocks engagement creation")

    # Disjointness of ACTIVE windows on the same (custodian, issuer) pair
    for e in db["custodian_engagements"].values():
        if (
            e["custodian_id"] == custodian_id
            and e["issuer_id"] == issuer_id
            and e["status"] == "ACTIVE"
        ):
            # overlap iff window_start < e.window_end and e.window_start < window_end
            if window_start < e["window_end"] and e["window_start"] < window_end:
                raise err(
                    "ERR_ENGAGEMENT_WINDOW_OVERLAP",
                    422,
                    "Engagement half-open window overlaps another ACTIVE engagement for the same (custodian, issuer)",
                )

    now = now_iso()
    e = {
        "id": new_id(),
        "custodian_id": custodian_id,
        "issuer_id": issuer_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["custodian_engagements"][e["id"]] = e
    return success_object(ser_engagement(e), status=201)


@app.route("/custodian-engagements", methods=["GET"])
def list_engagements():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    limit, offset = parse_pagination()
    custodian_filter = request.args.get("custodian_id")
    issuer_filter = request.args.get("issuer_id")
    items = sorted(db["custodian_engagements"].values(), key=lambda x: x["created_at"])
    if custodian_filter is not None:
        items = [e for e in items if e["custodian_id"] == custodian_filter]
    if issuer_filter is not None:
        items = [e for e in items if e["issuer_id"] == issuer_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_engagement(e) for e in page], total, limit, offset)


@app.route("/custodian-engagements/<eng_id>", methods=["GET"])
def get_engagement(eng_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    e = get_engagement_or_404(eng_id)
    return success_object(ser_engagement(e))


@app.route("/custodian-engagements/<eng_id>/end", methods=["POST"])
def end_engagement(eng_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    e = get_engagement_or_404(eng_id)
    issuer_officer_owns(user_id, e["issuer_id"])
    if e["status"] != "ACTIVE":
        raise err("ERR_ENGAGEMENT_INVALID_STATE", 409, "Engagement already ENDED")
    req_date = current_clock_date()
    if e["window_end"] > req_date:
        e["window_end"] = req_date
    e["status"] = "ENDED"
    touch(e)
    return success_object(ser_engagement(e))


# ---------------------------------------------------------------------------
# Pool endpoints
# ---------------------------------------------------------------------------


@app.route("/pools", methods=["POST"])
def create_pool():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    issuer_id = req_str(data, "issuer_id")
    custodian_id = req_str(data, "custodian_id")

    issuer = get_issuer_or_404(issuer_id)
    get_custodian_or_404(custodian_id)
    issuer_officer_owns(user_id, issuer["id"])

    expected = req_int(data, "expected_issuer_version")
    if expected != issuer["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_issuer_version does not match current version")

    pool_type = req_enum(data, "pool_type", POOL_TYPES)
    term_months = req_int(data, "term_months")
    note_rate_bps = req_int(data, "note_rate_bps", min_value=0)

    if term_months not in POOL_TYPE_TERMS[pool_type]:
        raise err("ERR_POOL_TERM_INVALID", 422, "term_months not in the allowed set for pool_type")

    require_engagement_coverage(custodian_id, issuer_id)

    now = now_iso()
    p = {
        "id": new_id(),
        "issuer_id": issuer_id,
        "custodian_id": custodian_id,
        "pool_type": pool_type,
        "term_months": term_months,
        "note_rate_bps": note_rate_bps,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["pools"][p["id"]] = p
    touch(issuer)  # creating a pool increments the issuing issuer's version
    return success_object(ser_pool(p), status=201)


@app.route("/pools", methods=["GET"])
def list_pools():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    limit, offset = parse_pagination()
    issuer_filter = request.args.get("issuer_id")
    custodian_filter = request.args.get("custodian_id")
    items = sorted(db["pools"].values(), key=lambda x: x["created_at"])
    if issuer_filter is not None:
        items = [p for p in items if p["issuer_id"] == issuer_filter]
    if custodian_filter is not None:
        items = [p for p in items if p["custodian_id"] == custodian_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_pool(p) for p in page], total, limit, offset)


@app.route("/pools/<pool_id>", methods=["GET"])
def get_pool(pool_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    p = get_pool_or_404(pool_id)
    return success_object(ser_pool(p))


@app.route("/pools/<pool_id>/assemble", methods=["POST"])
def assemble_pool(pool_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    p = get_pool_or_404(pool_id)
    issuer_officer_owns(user_id, p["issuer_id"])
    if p["status"] != "DRAFT":
        raise err("ERR_POOL_INVALID_STATE", 409, "Pool not in DRAFT")
    issuer = get_issuer_or_404(p["issuer_id"])
    if issuer["status"] != "ACTIVE":
        raise err("ERR_ISSUER_NOT_ACTIVE", 422, "Issuer not ACTIVE blocks pool assemble")
    loans = pool_loans(p["id"])
    if len(loans) == 0:
        raise err("ERR_POOL_EMPTY", 422, "Assemble requires at least one loan")
    if len(loans) > MAX_LOANS_PER_POOL[p["pool_type"]]:
        raise err("ERR_POOL_LOAN_COUNT_EXCEEDED", 422, "Loan count exceeds MAX_LOANS_PER_POOL for pool_type")
    if pool_aggregate_principal(p["id"]) < MIN_POOL_PRINCIPAL_CENTS:
        raise err("ERR_POOL_BELOW_MINIMUM_PRINCIPAL", 422, "aggregate_principal_cents below minimum at assemble")
    p["status"] = "ASSEMBLED"
    touch(p)
    return success_object(ser_pool(p))


@app.route("/pools/<pool_id>/certifications", methods=["POST"])
def create_certification(pool_id):
    user_id, role = get_auth()
    require_role(role, {"DocumentCustodian"})
    p = get_pool_or_404(pool_id)
    if p["status"] != "ASSEMBLED":
        raise err("ERR_POOL_INVALID_STATE", 409, "Pool not in ASSEMBLED")
    data = parse_body(["decision"])
    decision = req_enum(data, "decision", CERT_DECISIONS)
    exception_loan_ids = data.get("exception_loan_ids")
    if exception_loan_ids is None:
        exception_loan_ids = []
    if not isinstance(exception_loan_ids, list) or not all(isinstance(x, str) for x in exception_loan_ids):
        raise err("ERR_INVALID_REQUEST", 400, "exception_loan_ids must be an array of strings")

    require_engagement_coverage(p["custodian_id"], p["issuer_id"])

    now = now_iso()
    c = {
        "id": new_id(),
        "pool_id": p["id"],
        "custodian_id": p["custodian_id"],
        "decision": decision,
        "exception_loan_ids": exception_loan_ids,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["loan_file_certifications"][c["id"]] = c
    if decision == "CERTIFIED":
        p["status"] = "CERTIFIED"
        touch(p)
    # EXCEPTION: pool stays ASSEMBLED
    return success_object(ser_certification(c), status=201)


@app.route("/pools/<pool_id>/certifications", methods=["GET"])
def list_certifications(pool_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    p = get_pool_or_404(pool_id)
    limit, offset = parse_pagination()
    items = sorted(
        [c for c in db["loan_file_certifications"].values() if c["pool_id"] == p["id"]],
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_certification(c) for c in page], total, limit, offset)


@app.route("/pools/<pool_id>/activate", methods=["POST"])
def activate_pool(pool_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    p = get_pool_or_404(pool_id)
    issuer_officer_owns(user_id, p["issuer_id"])
    if p["status"] == "ASSEMBLED":
        # never certified
        raise err("ERR_CERTIFICATION_REQUIRED", 422, "Activate requires pool CERTIFIED")
    if p["status"] != "CERTIFIED":
        raise err("ERR_POOL_INVALID_STATE", 409, "Pool not in CERTIFIED")
    issuer = get_issuer_or_404(p["issuer_id"])
    if issuer["status"] != "ACTIVE":
        raise err("ERR_ISSUER_NOT_ACTIVE", 422, "Issuer not ACTIVE blocks pool activate")
    p["status"] = "LIVE"
    touch(p)
    # Create first monthly investor report in DRAFT for current clock month, collection 10000 bps
    create_investor_report(p["id"], current_clock_month(), 10000)
    return success_object(ser_pool(p))


@app.route("/pools/<pool_id>/terminate", methods=["POST"])
def terminate_pool(pool_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    p = get_pool_or_404(pool_id)
    issuer_officer_owns(user_id, p["issuer_id"])
    if p["status"] != "LIVE":
        raise err("ERR_POOL_INVALID_STATE", 409, "Pool not in LIVE")
    if pool_aggregate_principal(p["id"]) != 0:
        raise err("ERR_POOL_NOT_FULLY_PAID", 422, "Terminate requires aggregate_principal_cents == 0")
    open_reports = [
        r
        for r in db["investor_reports"].values()
        if r["pool_id"] == p["id"] and r["status"] in ("DRAFT", "SUBMITTED")
    ]
    if open_reports:
        raise err("ERR_UNRESOLVED_RECORDS_EXIST", 422, "DRAFT/SUBMITTED InvestorReports block pool termination")
    p["status"] = "TERMINATED"
    touch(p)
    return success_object(ser_pool(p))


# ---------------------------------------------------------------------------
# Loan endpoints
# ---------------------------------------------------------------------------


@app.route("/loans", methods=["POST"])
def create_loan():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    pool_id = req_str(data, "pool_id")

    p = get_pool_or_404(pool_id)
    issuer_officer_owns(user_id, p["issuer_id"])
    if p["status"] != "DRAFT":
        raise err("ERR_POOL_INVALID_STATE", 409, "Loans may only be added to a DRAFT pool")

    principal = req_int(data, "principal_balance_cents", min_value=1)
    note_rate = req_int(data, "note_rate_bps", min_value=0)
    insurance = req_enum(data, "government_insurance", GOVERNMENT_INSURANCE_VALUES)
    escrow = req_int(data, "escrow_monthly_cents", min_value=0)

    if p["pool_type"] == "MULTIFAMILY" and insurance != "FHA":
        raise err("ERR_INSURER_NOT_ALLOWED", 422, "government_insurance not allowed for pool_type (MULTIFAMILY requires FHA)")
    low = p["note_rate_bps"] + 50
    high = p["note_rate_bps"] + 150
    if note_rate < low or note_rate > high:
        raise err("ERR_LOAN_NOTE_RATE_OUT_OF_RANGE", 422, "loan note_rate_bps outside [pool note_rate_bps + 50, + 150] inclusive")

    now = now_iso()
    l = {
        "id": new_id(),
        "pool_id": pool_id,
        "principal_balance_cents": principal,
        "note_rate_bps": note_rate,
        "government_insurance": insurance,
        "escrow_monthly_cents": escrow,
        "status": "CURRENT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["loans"][l["id"]] = l
    return success_object(ser_loan(l), status=201)


@app.route("/loans", methods=["GET"])
def list_loans():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    limit, offset = parse_pagination()
    pool_filter = request.args.get("pool_id")
    items = sorted(db["loans"].values(), key=lambda x: x["created_at"])
    if pool_filter is not None:
        items = [l for l in items if l["pool_id"] == pool_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_loan(l) for l in page], total, limit, offset)


@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin", "DocumentCustodian"})
    l = get_loan_or_404(loan_id)
    return success_object(ser_loan(l))


LOAN_TRANSITIONS = {
    ("CURRENT", "DELINQ_30"),
    ("DELINQ_30", "DELINQ_60"),
    ("DELINQ_60", "DELINQ_90_PLUS"),
    ("DELINQ_90_PLUS", "FORECLOSURE"),
    ("DELINQ_30", "CURRENT"),
    ("DELINQ_60", "CURRENT"),
    ("DELINQ_90_PLUS", "CURRENT"),
}


@app.route("/loans/<loan_id>/delinquency-status", methods=["POST"])
def loan_delinquency_status(loan_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    l = get_loan_or_404(loan_id)
    p = get_pool_or_404(l["pool_id"])
    issuer_officer_owns(user_id, p["issuer_id"])
    data = parse_body(["to_status"])
    to_status = req_enum(data, "to_status", LOAN_STATUSES)

    from_status = l["status"]
    if to_status == "PAID_OFF":
        if from_status == "PAID_OFF":
            raise err("ERR_LOAN_INVALID_STATE", 409, "Loan delinquency transition invalid from current status")
    else:
        if (from_status, to_status) not in LOAN_TRANSITIONS:
            raise err("ERR_LOAN_INVALID_STATE", 409, "Loan delinquency transition invalid from current status")

    l["status"] = to_status
    touch(l)
    pool_threshold_evaluation(p)
    return success_object(ser_loan(l))


# ---------------------------------------------------------------------------
# CustodialAccount endpoints
# ---------------------------------------------------------------------------


@app.route("/custodial-accounts", methods=["POST"])
def create_account():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    issuer_id = req_str(data, "issuer_id")

    issuer = get_issuer_or_404(issuer_id)
    issuer_officer_owns(user_id, issuer["id"])

    account_type = req_enum(data, "account_type", ACCOUNT_TYPES)

    for acct in db["custodial_accounts"].values():
        if acct["issuer_id"] == issuer_id and acct["account_type"] == account_type:
            raise err("ERR_ACCOUNT_TYPE_DUPLICATE", 422, "Issuer already has a custodial account of this type")

    now = now_iso()
    acct = {
        "id": new_id(),
        "issuer_id": issuer_id,
        "account_type": account_type,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["custodial_accounts"][acct["id"]] = acct
    return success_object(ser_account(acct), status=201)


@app.route("/custodial-accounts", methods=["GET"])
def list_accounts():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    issuer_filter = request.args.get("issuer_id")
    items = sorted(db["custodial_accounts"].values(), key=lambda x: x["created_at"])
    if issuer_filter is not None:
        items = [a for a in items if a["issuer_id"] == issuer_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_account(a) for a in page], total, limit, offset)


@app.route("/custodial-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    acct = get_account_or_404(account_id)
    return success_object(ser_account(acct))


@app.route("/custodial-accounts/<account_id>/transactions", methods=["POST"])
def create_transaction(account_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    acct = get_account_or_404(account_id)
    issuer_officer_owns(user_id, acct["issuer_id"])
    data = parse_body(["component", "amount_cents"])
    component = req_enum(data, "component", TRANSACTION_COMPONENTS)
    amount = req_int(data, "amount_cents", min_value=1)
    loan_id = data.get("loan_id")
    if loan_id is not None and not isinstance(loan_id, str):
        raise err("ERR_INVALID_REQUEST", 400, "loan_id must be a string")

    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_FROZEN", 422, "Custodial account FROZEN or CLOSED blocks deposits/disbursements")

    principal, interest, tax, insurance = account_balances(acct)

    # Component validity per account type
    if acct["account_type"] == "P_AND_I":
        if component in ("TAX", "INSURANCE", "ESCROW"):
            raise err("ERR_INVALID_REQUEST", 400, f"Component {component} not valid for P_AND_I account")
    else:  # T_AND_I
        if component in ("PRINCIPAL", "INTEREST"):
            raise err("ERR_INVALID_REQUEST", 400, f"Component {component} not valid for T_AND_I account")

    tax_split = None
    insurance_split = None
    if component == "ESCROW":
        # ESCROW is a deposit-only split component on T_AND_I
        tax_split = (amount * ESCROW_TAX_SHARE_BPS) // 10000
        insurance_split = amount - tax_split
        txn = post_transaction(
            acct["id"], "DEPOSIT", "ESCROW", amount, loan_id=loan_id,
            tax_split_cents=tax_split, insurance_split_cents=insurance_split,
        )
        return success_object(ser_transaction(txn), status=201)

    # Raw deposit/disbursement: direction derived from payload? PRD: direction is system-set.
    # For raw postings, the caller supplies "direction" implicitly via... The entity table says
    # direction is source: system. Raw postings are deposits unless a disbursement is requested.
    # The endpoint input list is [component, amount_cents, "loan_id?"] — no direction input.
    # DISBURSEMENT arises from a negative scenario: "A raw disbursement that exceeds the targeted
    # component's balance is rejected". Direction must come from the payload to allow disbursements.
    direction_raw = data.get("direction")
    if direction_raw is None:
        direction = "DEPOSIT"
    else:
        if direction_raw not in ("DEPOSIT", "DISBURSEMENT"):
            raise err("ERR_INVALID_REQUEST", 400, "direction must be DEPOSIT or DISBURSEMENT")
        direction = direction_raw

    if direction == "DISBURSEMENT":
        available = {
            "PRINCIPAL": principal,
            "INTEREST": interest,
            "TAX": tax,
            "INSURANCE": insurance,
        }[component]
        if amount > available:
            raise err(
                "ERR_INSUFFICIENT_CUSTODIAL_FUNDS",
                422,
                "Raw DISBURSEMENT transaction exceeds the targeted custodial component balance",
            )

    txn = post_transaction(acct["id"], direction, component, amount, loan_id=loan_id)
    return success_object(ser_transaction(txn), status=201)


@app.route("/custodial-accounts/<account_id>/transactions", methods=["GET"])
def list_transactions(account_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    acct = get_account_or_404(account_id)
    limit, offset = parse_pagination()
    items = sorted(
        [t for t in db["account_transactions"].values() if t["account_id"] == acct["id"]],
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_transaction(t) for t in page], total, limit, offset)


# ---------------------------------------------------------------------------
# InvestorReport endpoints
# ---------------------------------------------------------------------------


@app.route("/investor-reports", methods=["POST"])
def create_report():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    pool_id = req_str(data, "pool_id")

    p = get_pool_or_404(pool_id)
    issuer_officer_owns(user_id, p["issuer_id"])

    expected = req_int(data, "expected_pool_version")
    if expected != p["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_pool_version does not match current version")

    period_month = req_month(data, "period_month")
    collection_rate_bps = req_int(data, "collection_rate_bps", min_value=0)

    for r in db["investor_reports"].values():
        if r["pool_id"] == p["id"] and r["period_month"] == period_month:
            raise err("ERR_DUPLICATE_REPORT_PERIOD", 422, "An InvestorReport already exists for this pool and period_month")

    r = create_investor_report(p["id"], period_month, collection_rate_bps)
    return success_object(ser_report(r), status=201)


@app.route("/investor-reports", methods=["GET"])
def list_reports():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    pool_filter = request.args.get("pool_id")
    items = sorted(db["investor_reports"].values(), key=lambda x: x["created_at"])
    if pool_filter is not None:
        items = [r for r in items if r["pool_id"] == pool_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_report(r) for r in page], total, limit, offset)


@app.route("/investor-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    r = get_report_or_404(report_id)
    return success_object(ser_report(r))


@app.route("/investor-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    r = get_report_or_404(report_id)
    p = get_pool_or_404(r["pool_id"])
    if p["issuer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", 403, "IssuerOfficer X-User-ID does not own the target resource")
    if p["status"] not in ("CERTIFIED", "LIVE"):
        raise err("ERR_POOL_INVALID_STATE", 409, "Pool not in a state permitting report submission")
    if r["status"] != "DRAFT":
        raise err("ERR_REPORT_INVALID_STATE", 409, "Report not in DRAFT")
    for other in db["investor_reports"].values():
        if (
            other["id"] != r["id"]
            and other["pool_id"] == r["pool_id"]
            and other["period_month"] == r["period_month"]
        ):
            raise err("ERR_DUPLICATE_REPORT_PERIOD", 422, "An InvestorReport already exists for this pool and period_month")
    r["status"] = "SUBMITTED"
    touch(r)
    return success_object(ser_report(r))


@app.route("/investor-reports/<report_id>/accept", methods=["POST"])
def accept_report(report_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    r = get_report_or_404(report_id)
    if r["status"] != "SUBMITTED":
        raise err("ERR_REPORT_INVALID_STATE", 409, "Report not in SUBMITTED")
    r["status"] = "ACCEPTED"
    touch(r)
    now = now_iso()
    payment = {
        "id": new_id(),
        "report_id": r["id"],
        "amount_cents": r["scheduled_payment_cents"],
        "funding_source": None,
        "status": "DUE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["pass_through_payments"][payment["id"]] = payment
    return success_object(ser_report(r))


@app.route("/investor-reports/<report_id>/reject", methods=["POST"])
def reject_report(report_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    r = get_report_or_404(report_id)
    if r["status"] != "SUBMITTED":
        raise err("ERR_REPORT_INVALID_STATE", 409, "Report not in SUBMITTED")
    r["status"] = "REJECTED"
    touch(r)
    return success_object(ser_report(r))


# ---------------------------------------------------------------------------
# PassThroughPayment endpoints
# ---------------------------------------------------------------------------


@app.route("/pass-through-payments", methods=["GET"])
def list_payments():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    report_filter = request.args.get("report_id")
    items = sorted(db["pass_through_payments"].values(), key=lambda x: x["created_at"])
    if report_filter is not None:
        items = [p for p in items if p["report_id"] == report_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_payment(p) for p in page], total, limit, offset)


@app.route("/pass-through-payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    p = get_payment_or_404(payment_id)
    return success_object(ser_payment(p))


@app.route("/pass-through-payments/<payment_id>/settle", methods=["POST"])
def settle_payment(payment_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    payment = get_payment_or_404(payment_id)
    report = get_report_or_404(payment["report_id"])
    pool = get_pool_or_404(report["pool_id"])
    issuer_officer_owns(user_id, pool["issuer_id"])
    if payment["status"] != "DUE":
        raise err("ERR_PAYMENT_INVALID_STATE", 409, "Payment not DUE")

    issuer = get_issuer_or_404(pool["issuer_id"])
    pandi = find_pandi_account(issuer["id"])
    amount = payment["amount_cents"]

    custodial_available = False
    if pandi is not None and pandi["status"] == "ACTIVE":
        principal, interest, _tax, _ins = account_balances(pandi)
        if principal + interest >= amount:
            custodial_available = True

    if custodial_available:
        # interest bucket drains first, then principal
        interest_draw = min(amount, interest)
        principal_draw = amount - interest_draw
        if interest_draw > 0:
            post_transaction(pandi["id"], "DISBURSEMENT", "INTEREST", interest_draw)
        if principal_draw > 0:
            post_transaction(pandi["id"], "DISBURSEMENT", "PRINCIPAL", principal_draw)
        payment["funding_source"] = "CUSTODIAL"
        payment["status"] = "PAID"
        touch(payment)
    else:
        payment["funding_source"] = "ADVANCE"
        payment["status"] = "ADVANCED"
        touch(payment)
        now = now_iso()
        advance = {
            "id": new_id(),
            "issuer_id": issuer["id"],
            "payment_id": payment["id"],
            "amount_cents": amount,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db["liquidity_advances"][advance["id"]] = advance
        liquidity_threshold_evaluation(issuer)

    return success_object(ser_payment(payment))


# ---------------------------------------------------------------------------
# LiquidityAdvance endpoints
# ---------------------------------------------------------------------------


@app.route("/liquidity-advances", methods=["GET"])
def list_advances():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    issuer_filter = request.args.get("issuer_id")
    payment_filter = request.args.get("payment_id")
    items = sorted(db["liquidity_advances"].values(), key=lambda x: x["created_at"])
    if issuer_filter is not None:
        items = [a for a in items if a["issuer_id"] == issuer_filter]
    if payment_filter is not None:
        items = [a for a in items if a["payment_id"] == payment_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_advance(a) for a in page], total, limit, offset)


@app.route("/liquidity-advances/<advance_id>", methods=["GET"])
def get_advance(advance_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    a = get_advance_or_404(advance_id)
    return success_object(ser_advance(a))


@app.route("/liquidity-advances/<advance_id>/reimburse", methods=["POST"])
def reimburse_advance(advance_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    a = get_advance_or_404(advance_id)
    issuer_officer_owns(user_id, a["issuer_id"])
    if a["status"] != "OPEN":
        raise err("ERR_ADVANCE_INVALID_STATE", 409, "Advance not OPEN")
    a["status"] = "REIMBURSED"
    touch(a)
    issuer = get_issuer_or_404(a["issuer_id"])
    liquidity_threshold_evaluation(issuer)
    return success_object(ser_advance(a))


# ---------------------------------------------------------------------------
# DelinquencyBreach endpoints
# ---------------------------------------------------------------------------


@app.route("/delinquency-breaches", methods=["GET"])
def list_breaches():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    issuer_filter = request.args.get("issuer_id")
    pool_filter = request.args.get("pool_id")
    items = sorted(db["delinquency_breaches"].values(), key=lambda x: x["created_at"])
    if issuer_filter is not None:
        items = [b for b in items if b["issuer_id"] == issuer_filter]
    if pool_filter is not None:
        items = [b for b in items if b["pool_id"] == pool_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_breach(b) for b in page], total, limit, offset)


@app.route("/delinquency-breaches/<breach_id>", methods=["GET"])
def get_breach(breach_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    b = get_breach_or_404(breach_id)
    return success_object(ser_breach(b))


@app.route("/delinquency-breaches/<breach_id>/close", methods=["POST"])
def close_breach(breach_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    b = get_breach_or_404(breach_id)
    if b["status"] not in ("OPEN", "MITIGATING"):
        raise err("ERR_BREACH_INVALID_STATE", 409, "Breach not in a state permitting close")
    rate = pool_delinquency_rate(b["pool_id"])
    if rate >= POOL_DELINQUENCY_THRESHOLD_BPS:
        raise err("ERR_BREACH_STILL_BREACHING", 422, "Pool delinquency_rate_bps still >= threshold at breach close")
    b["status"] = "CLOSED"
    touch(b)
    issuer = db["issuers"].get(b["issuer_id"])
    if issuer is not None:
        reevaluate_issuer_from_breach(issuer)
    return success_object(ser_breach(b))


# ---------------------------------------------------------------------------
# CorrectiveActionPlan endpoints
# ---------------------------------------------------------------------------


@app.route("/corrective-action-plans", methods=["POST"])
def create_plan():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer"})
    data = parse_body()
    breach_id = req_str(data, "breach_id")

    b = get_breach_or_404(breach_id)
    issuer_officer_owns(user_id, b["issuer_id"])

    plan_summary = req_str(data, "plan_summary")
    target_cure_month = req_month(data, "target_cure_month")

    now = now_iso()
    plan = {
        "id": new_id(),
        "breach_id": b["id"],
        "plan_summary": plan_summary,
        "target_cure_month": target_cure_month,
        "status": "SUBMITTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["corrective_action_plans"][plan["id"]] = plan
    return success_object(ser_plan(plan), status=201)


@app.route("/corrective-action-plans", methods=["GET"])
def list_plans():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    breach_filter = request.args.get("breach_id")
    items = sorted(db["corrective_action_plans"].values(), key=lambda x: x["created_at"])
    if breach_filter is not None:
        items = [p for p in items if p["breach_id"] == breach_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_plan(p) for p in page], total, limit, offset)


@app.route("/corrective-action-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    p = get_plan_or_404(plan_id)
    return success_object(ser_plan(p))


@app.route("/corrective-action-plans/<plan_id>/accept", methods=["POST"])
def accept_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "SUBMITTED":
        raise err("ERR_PLAN_INVALID_STATE", 409, "Plan not SUBMITTED")
    plan["status"] = "ACCEPTED"
    touch(plan)
    breach = db["delinquency_breaches"].get(plan["breach_id"])
    if breach is not None and breach["status"] == "OPEN":
        breach["status"] = "MITIGATING"
        touch(breach)
    if breach is not None:
        issuer = db["issuers"].get(breach["issuer_id"])
        if issuer is not None:
            reevaluate_issuer_from_breach(issuer)
    return success_object(ser_plan(plan))


@app.route("/corrective-action-plans/<plan_id>/reject", methods=["POST"])
def reject_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "SUBMITTED":
        raise err("ERR_PLAN_INVALID_STATE", 409, "Plan not SUBMITTED")
    plan["status"] = "REJECTED"
    touch(plan)
    return success_object(ser_plan(plan))


# ---------------------------------------------------------------------------
# PortfolioTransfer endpoints
# ---------------------------------------------------------------------------


@app.route("/portfolio-transfers", methods=["POST"])
def create_transfer():
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    data = parse_body()
    defaulted_issuer_id = req_str(data, "defaulted_issuer_id")
    successor_issuer_id = req_str(data, "successor_issuer_id")

    defaulted = get_issuer_or_404(defaulted_issuer_id)
    get_issuer_or_404(successor_issuer_id)

    expected = req_int(data, "expected_defaulted_issuer_version")
    if expected != defaulted["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_defaulted_issuer_version does not match current version")

    now = now_iso()
    t = {
        "id": new_id(),
        "defaulted_issuer_id": defaulted_issuer_id,
        "successor_issuer_id": successor_issuer_id,
        "status": "INITIATED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db["portfolio_transfers"][t["id"]] = t

    # Park every LIVE pool of the defaulted issuer into TRANSFER_PENDING
    for p in db["pools"].values():
        if p["issuer_id"] == defaulted_issuer_id and p["status"] == "LIVE":
            p["status"] = "TRANSFER_PENDING"
            touch(p)

    touch(defaulted)
    return success_object(ser_transfer(t), status=201)


@app.route("/portfolio-transfers", methods=["GET"])
def list_transfers():
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    defaulted_filter = request.args.get("defaulted_issuer_id")
    successor_filter = request.args.get("successor_issuer_id")
    items = sorted(db["portfolio_transfers"].values(), key=lambda x: x["created_at"])
    if defaulted_filter is not None:
        items = [t for t in items if t["defaulted_issuer_id"] == defaulted_filter]
    if successor_filter is not None:
        items = [t for t in items if t["successor_issuer_id"] == successor_filter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_transfer(t) for t in page], total, limit, offset)


@app.route("/portfolio-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    user_id, role = get_auth()
    require_role(role, {"IssuerOfficer", "AgencyReviewer", "PlatformAdmin"})
    t = get_transfer_or_404(transfer_id)
    return success_object(ser_transfer(t))


@app.route("/portfolio-transfers/<transfer_id>/accept", methods=["POST"])
def accept_transfer(transfer_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "INITIATED":
        raise err("ERR_TRANSFER_INVALID_STATE", 409, "Transfer not INITIATED")

    successor = get_issuer_or_404(t["successor_issuer_id"])
    defaulted = get_issuer_or_404(t["defaulted_issuer_id"])

    if successor["status"] != "ACTIVE":
        raise err("ERR_SUCCESSOR_NOT_ACTIVE", 422, "Successor issuer not ACTIVE at transfer accept")

    # Successor capitalization: after assuming defaulted issuer's OPEN advances,
    # liquidity_ratio_including_credit_bps >= LIQUIDITY_MONITOR_THRESHOLD_BPS
    defaulted_obligation = issuer_advance_obligation(defaulted["id"])
    successor_obligation = issuer_advance_obligation(successor["id"])
    combined_obligation = successor_obligation + defaulted_obligation
    if combined_obligation > 0:
        ratio_incl = ((successor["liquid_assets_cents"] + successor["unused_credit_lines_cents"]) * 10000) // combined_obligation
        if ratio_incl < LIQUIDITY_MONITOR_THRESHOLD_BPS:
            raise err(
                "ERR_SUCCESSOR_UNDERCAPITALIZED",
                422,
                "Successor liquidity_ratio_including_credit_bps would fall below LIQUIDITY_MONITOR_THRESHOLD_BPS after assuming obligations",
            )

    t["status"] = "COMPLETED"
    touch(t)

    # Pools: TRANSFER_PENDING -> LIVE with issuer reassigned
    for p in db["pools"].values():
        if p["issuer_id"] == defaulted["id"] and p["status"] == "TRANSFER_PENDING":
            p["issuer_id"] = successor["id"]
            p["status"] = "LIVE"
            touch(p)

    # Advances: reassign OPEN advances from defaulted to successor
    for adv in db["liquidity_advances"].values():
        if adv["issuer_id"] == defaulted["id"] and adv["status"] == "OPEN":
            adv["issuer_id"] = successor["id"]
            touch(adv)

    # Defaulted issuer -> EXTINGUISHED; accounts FROZEN -> CLOSED
    defaulted["status"] = "EXTINGUISHED"
    close_issuer_accounts(defaulted["id"])
    touch(defaulted)

    # Successor ratios recomputed; threshold evaluation runs
    liquidity_threshold_evaluation(successor)

    return success_object(ser_transfer(t))


@app.route("/portfolio-transfers/<transfer_id>/reject", methods=["POST"])
def reject_transfer(transfer_id):
    user_id, role = get_auth()
    require_role(role, {"AgencyReviewer"})
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "INITIATED":
        raise err("ERR_TRANSFER_INVALID_STATE", 409, "Transfer not INITIATED")

    defaulted = get_issuer_or_404(t["defaulted_issuer_id"])

    t["status"] = "REJECTED"
    touch(t)

    # Pools TRANSFER_PENDING -> TERMINATED
    for p in db["pools"].values():
        if p["issuer_id"] == defaulted["id"] and p["status"] == "TRANSFER_PENDING":
            p["status"] = "TERMINATED"
            touch(p)

    # Defaulted issuer -> EXTINGUISHED; accounts FROZEN -> CLOSED; OPEN advances -> WRITTEN_OFF
    defaulted["status"] = "EXTINGUISHED"
    close_issuer_accounts(defaulted["id"])
    for adv in db["liquidity_advances"].values():
        if adv["issuer_id"] == defaulted["id"] and adv["status"] == "OPEN":
            adv["status"] = "WRITTEN_OFF"
            touch(adv)
    touch(defaulted)

    return success_object(ser_transfer(t))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
