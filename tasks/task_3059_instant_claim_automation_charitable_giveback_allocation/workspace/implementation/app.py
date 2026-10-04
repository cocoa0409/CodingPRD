"""Flask application — Instant Claim Giveback Insurance API."""
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from flask import Flask, request, jsonify

from store import db, now, set_clock, fmt_ts, parse_ts, new_id, req_id, rhu, dec
import errors as E
from errors import APIError
import serializers as S
import services as svc

app = Flask(__name__)

ROLES = {"Anonymous", "Policyholder", "UnderwritingAdmin", "ClaimsAdjuster", "FinanceOps", "PlatformAdmin"}

# Route table: rule -> (methods, roles)
ROUTES = {
    ("POST", "/_clock/set_current_utc"): ["PlatformAdmin"],
    ("POST", "/rate-filings"): ["UnderwritingAdmin"],
    ("GET", "/rate-filings"): ["UnderwritingAdmin", "PlatformAdmin", "FinanceOps"],
    ("GET", "/rate-filings/<rid>"): ["UnderwritingAdmin", "PlatformAdmin", "FinanceOps"],
    ("POST", "/rate-filings/<rid>/approve"): ["UnderwritingAdmin"],
    ("POST", "/rate-filings/<rid>/reject"): ["UnderwritingAdmin"],
    ("POST", "/fee-configs"): ["UnderwritingAdmin"],
    ("GET", "/fee-configs"): ["UnderwritingAdmin", "PlatformAdmin"],
    ("GET", "/fee-configs/<fid>"): ["UnderwritingAdmin", "PlatformAdmin"],
    ("GET", "/fee-configs/<fid>/policies"): ["UnderwritingAdmin", "PlatformAdmin"],
    ("POST", "/fee-configs/<fid>/update"): ["UnderwritingAdmin"],
    ("POST", "/fee-configs/<fid>/activate"): ["UnderwritingAdmin"],
    ("POST", "/fee-configs/<fid>/retire"): ["UnderwritingAdmin"],
    ("POST", "/reinsurance-treaties"): ["FinanceOps"],
    ("GET", "/reinsurance-treaties"): ["FinanceOps", "PlatformAdmin"],
    ("POST", "/reinsurance-treaties/<tid>/activate"): ["FinanceOps"],
    ("POST", "/reinsurance-treaties/<tid>/retire"): ["FinanceOps"],
    ("POST", "/causes"): ["PlatformAdmin"],
    ("GET", "/causes"): ["PlatformAdmin", "Policyholder", "FinanceOps", "UnderwritingAdmin", "ClaimsAdjuster"],
    ("GET", "/causes/<cid>"): ["PlatformAdmin", "Policyholder", "FinanceOps", "UnderwritingAdmin", "ClaimsAdjuster"],
    ("POST", "/causes/<cid>/retire"): ["PlatformAdmin"],
    ("GET", "/causes/<cid>/cohorts"): ["PlatformAdmin", "FinanceOps"],
    ("GET", "/causes/<cid>/policies"): ["PlatformAdmin", "FinanceOps"],
    ("POST", "/cohorts"): ["PlatformAdmin"],
    ("GET", "/cohorts"): ["PlatformAdmin", "FinanceOps", "UnderwritingAdmin", "ClaimsAdjuster"],
    ("GET", "/cohorts/<cid>"): ["PlatformAdmin", "FinanceOps", "UnderwritingAdmin", "ClaimsAdjuster"],
    ("POST", "/cohorts/<cid>/reinsurance"): ["FinanceOps"],
    ("POST", "/cohorts/<cid>/run-giveback"): ["FinanceOps"],
    ("POST", "/cohorts/<cid>/close"): ["PlatformAdmin"],
    ("GET", "/cohorts/<cid>/policies"): ["PlatformAdmin", "FinanceOps", "UnderwritingAdmin"],
    ("POST", "/policyholders"): ["Anonymous"],
    ("GET", "/policyholders/<pid>"): ["Policyholder", "PlatformAdmin", "UnderwritingAdmin", "ClaimsAdjuster"],
    ("GET", "/policyholders/<pid>/applications"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("GET", "/policyholders/<pid>/quotes"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("GET", "/policyholders/<pid>/policies"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("POST", "/quotes"): ["Policyholder"],
    ("GET", "/quotes/<qid>"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("GET", "/quotes/<qid>/policies"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("POST", "/quotes/<qid>/bind"): ["Policyholder"],
    ("GET", "/quotes/<qid>/applications"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("POST", "/applications"): ["Policyholder"],
    ("GET", "/applications/<aid>"): ["Policyholder", "UnderwritingAdmin", "PlatformAdmin"],
    ("POST", "/applications/<aid>/approve"): ["UnderwritingAdmin"],
    ("POST", "/applications/<aid>/decline"): ["UnderwritingAdmin"],
    ("POST", "/applications/<aid>/resubmit"): ["Policyholder"],
    ("GET", "/policies/<pid>"): ["Policyholder", "UnderwritingAdmin", "ClaimsAdjuster", "FinanceOps", "PlatformAdmin"],
    ("POST", "/policies/<pid>/cause-election"): ["Policyholder"],
    ("POST", "/policies/<pid>/premium-payments"): ["FinanceOps"],
    ("POST", "/policies/<pid>/cancel"): ["Policyholder"],
    ("POST", "/policies/<pid>/lapse"): ["FinanceOps"],
    ("GET", "/policies/<pid>/ledger"): ["Policyholder", "FinanceOps", "PlatformAdmin"],
    ("GET", "/policies/<pid>/claims"): ["Policyholder", "ClaimsAdjuster", "PlatformAdmin"],
    ("POST", "/claims"): ["Policyholder"],
    ("GET", "/claims"): ["ClaimsAdjuster", "PlatformAdmin", "FinanceOps"],
    ("GET", "/claims/<cid>"): ["Policyholder", "ClaimsAdjuster", "PlatformAdmin"],
    ("GET", "/claims/<cid>/payments"): ["Policyholder", "ClaimsAdjuster", "FinanceOps", "PlatformAdmin"],
    ("GET", "/claims/<cid>/ledger"): ["Policyholder", "ClaimsAdjuster", "FinanceOps", "PlatformAdmin"],
    ("POST", "/claims/<cid>/approve"): ["ClaimsAdjuster"],
    ("POST", "/claims/<cid>/deny"): ["ClaimsAdjuster"],
    ("POST", "/claims/<cid>/appeals"): ["Policyholder"],
    ("GET", "/claims/<cid>/appeals"): ["Policyholder", "ClaimsAdjuster", "PlatformAdmin"],
    ("GET", "/appeals/<aid>"): ["Policyholder", "ClaimsAdjuster", "PlatformAdmin"],
    ("POST", "/appeals/<aid>/uphold"): ["ClaimsAdjuster"],
    ("POST", "/appeals/<aid>/overturn"): ["ClaimsAdjuster"],
}


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def success_obj(data, status=200):
    return jsonify({
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": fmt_ts(now()),
        },
        "response_type": "object",
        "data": data,
    }), status


def success_list(items, limit, offset, total_count, status=200):
    return jsonify({
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": fmt_ts(now()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }), status


@app.errorhandler(APIError)
def handle_api_error(e):
    return jsonify({
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": fmt_ts(now()),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(E.err_not_found("Route not found"))


@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(E.err_not_found("Method not allowed"))


@app.errorhandler(Exception)
def handle_exc(e):
    return jsonify({
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": fmt_ts(now()),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }), 500


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        raise E.err_invalid_request("Request body must be valid JSON")
    if not isinstance(b, dict):
        raise E.err_invalid_request("Request body must be a JSON object")
    return b


def role():
    r = request.headers.get("X-User-Role")
    if r is None or r not in ROLES:
        raise E.err_unauthenticated()
    return r


def user_id():
    return request.headers.get("X-User-ID")


def require_role(*allowed):
    r = role()
    if r not in allowed:
        raise E.err_forbidden()
    return r


def pagination():
    qs = request.args
    try:
        limit = int(qs.get("limit", 10))
    except (TypeError, ValueError):
        raise E.err_invalid_request("limit must be an integer")
    try:
        offset = int(qs.get("offset", 0))
    except (TypeError, ValueError):
        raise E.err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise E.err_invalid_request("limit out of range [1,100]")
    if offset < 0:
        raise E.err_invalid_request("offset must be >= 0")
    return limit, offset


def page_slice(items, limit, offset):
    return items[offset:offset + limit]


def get_or_404(store, rid):
    r = store.get(rid)
    if r is None:
        raise E.err_not_found(f"Resource {rid} not found")
    return r


def require_int(b, key, min_val=None, allow_null=False):
    v = b.get(key)
    if v is None:
        if allow_null:
            return None
        raise E.err_invalid_request(f"missing field {key}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.err_invalid_request(f"{key} must be an integer")
    if min_val is not None and v < min_val:
        raise E.err_invalid_request(f"{key} must be >= {min_val}")
    return v


def require_number(b, key, allow_null=False):
    v = b.get(key)
    if v is None:
        if allow_null:
            return None
        raise E.err_invalid_request(f"missing field {key}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise E.err_invalid_request(f"{key} must be a number")
    return v


def require_str(b, key):
    v = b.get(key)
    if v is None or not isinstance(v, str):
        raise E.err_invalid_request(f"{key} must be a string")
    return v


def require_bool(b, key):
    v = b.get(key)
    if not isinstance(v, bool):
        raise E.err_invalid_request(f"{key} must be a boolean")
    return v


def sort_created(items):
    return sorted(items, key=lambda r: r["created_at"])


def behavioral_signals(vel, reuse, ipa):
    s = 0
    if vel < 8:
        s += 1
    if reuse >= 2:
        s += 1
    if ipa is False:
        s += 1
    return s


def lazy_quote_expiry(quote):
    if quote["status"] == "OPEN" and now() > quote["expires_at"]:
        quote["status"] = "EXPIRED"
        svc.touch(quote)


def lazy_cohort_transitions():
    for c in db.cohorts.values():
        if c["status"] != "OPEN":
            continue
        boundary_year = c["cohort_year"] + 1
        boundary = now().replace(year=boundary_year, month=7, day=1, hour=0, minute=0, second=0, microsecond=0)
        if now() >= boundary:
            has_policies = any(p["cohort_id"] == c["id"] for p in db.policies.values())
            c["status"] = "CLOSED" if has_policies else "EXPIRED"
            svc.touch(c)


@app.before_request
def auth_gate():
    if request.method == "OPTIONS":
        return None
    rule = request.url_rule.rule if request.url_rule else None
    if rule is None:
        return None  # 404 handler will fire
    key = (request.method, rule)
    allowed = ROUTES.get(key)
    if allowed is None:
        return None
    require_role(*allowed)
    return None


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def clock_set():
    b = body()
    iso = require_str(b, "to_iso8601")
    try:
        dt = parse_ts(iso)
    except Exception:
        raise E.err_invalid_request("to_iso8601 must be an ISO8601 timestamp")
    set_clock(dt)
    lazy_cohort_transitions()
    for q in db.quotes.values():
        lazy_quote_expiry(q)
    return success_obj({"current_utc": fmt_ts(now())})


# ---------------------------------------------------------------------------
# Rate filings
# ---------------------------------------------------------------------------
@app.post("/rate-filings")
def filing_create():
    b = body()
    sc = require_str(b, "state_code")
    pct = require_number(b, "max_flat_fee_pct")
    cap = b.get("max_flat_fee_cap_cents")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise E.err_invalid_request("max_flat_fee_cap_cents must be null or integer >= 0")
    mode = require_str(b, "filing_mode")
    if mode not in ("ABSOLUTE_CENTS", "PCT_OF_PREMIUM"):
        raise E.err_invalid_request("filing_mode invalid")
    fid = new_id()
    ts = now()
    r = {
        "id": fid, "state_code": sc, "max_flat_fee_pct": pct,
        "max_flat_fee_cap_cents": cap, "filing_mode": mode,
        "status": "SUBMITTED", "approved_at": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.rate_filings[fid] = r
    return success_obj(S.ser_rate_filing(r), 201)


@app.get("/rate-filings")
def filing_list():
    limit, offset = pagination()
    items = list(db.rate_filings.values())
    sc = request.args.get("state_code")
    st = request.args.get("status")
    if sc is not None:
        items = [r for r in items if r["state_code"] == sc]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_rate_filing(r) for r in page], limit, offset, total)


@app.get("/rate-filings/<rid>")
def filing_get(rid):
    r = get_or_404(db.rate_filings, rid)
    return success_obj(S.ser_rate_filing(r))


@app.post("/rate-filings/<rid>/approve")
def filing_approve(rid):
    r = get_or_404(db.rate_filings, rid)
    if r["status"] != "SUBMITTED":
        raise E.err_filing_not_submitted()
    for other in db.rate_filings.values():
        if other["id"] != rid and other["state_code"] == r["state_code"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            svc.touch(other)
    r["status"] = "APPROVED"
    r["approved_at"] = now()
    svc.touch(r)
    return success_obj(S.ser_rate_filing(r))


@app.post("/rate-filings/<rid>/reject")
def filing_reject(rid):
    r = get_or_404(db.rate_filings, rid)
    if r["status"] != "SUBMITTED":
        raise E.err_filing_not_submitted()
    r["status"] = "REJECTED"
    svc.touch(r)
    return success_obj(S.ser_rate_filing(r))


# ---------------------------------------------------------------------------
# Fee configs
# ---------------------------------------------------------------------------
def check_fee_vs_filing(filing, pct, cents):
    if filing["filing_mode"] == "ABSOLUTE_CENTS":
        cap = filing["max_flat_fee_cap_cents"]
        if cap is not None and cents > cap:
            raise E.err_flat_fee_violates_filing()
    else:  # PCT_OF_PREMIUM
        if dec(pct) > dec(filing["max_flat_fee_pct"]):
            raise E.err_flat_fee_violates_filing()


def validate_fee_config_creation(filing_id, pct, cents):
    filing = db.rate_filings.get(filing_id)
    if filing is None:
        raise E.err_not_found("filing not found")
    check_fee_vs_filing(filing, pct, cents)


@app.post("/fee-configs")
def fee_create():
    b = body()
    sc = require_str(b, "state_code")
    filing_id = require_str(b, "filing_id")
    pct = require_number(b, "flat_fee_pct")
    if dec(pct) <= 0 or dec(pct) > 1:
        raise E.err_invalid_request("flat_fee_pct must be in (0, 1]")
    cents = b.get("flat_fee_cents")
    if cents is None or isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
        raise E.err_invalid_request("flat_fee_cents must be a positive integer")
    validate_fee_config_creation(filing_id, pct, cents)
    fid = new_id()
    ts = now()
    r = {
        "id": fid, "state_code": sc, "filing_id": filing_id,
        "flat_fee_pct": pct, "flat_fee_cents": cents,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.fee_configs[fid] = r
    return success_obj(S.ser_fee_config(r), 201)


@app.get("/fee-configs")
def fee_list():
    limit, offset = pagination()
    items = list(db.fee_configs.values())
    sc = request.args.get("state_code")
    st = request.args.get("status")
    fid = request.args.get("filing_id")
    if sc is not None:
        items = [r for r in items if r["state_code"] == sc]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    if fid is not None:
        items = [r for r in items if r["filing_id"] == fid]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_fee_config(r) for r in page], limit, offset, total)


@app.get("/fee-configs/<fid>")
def fee_get(fid):
    r = get_or_404(db.fee_configs, fid)
    return success_obj(S.ser_fee_config(r))


@app.get("/fee-configs/<fid>/policies")
def fee_policies(fid):
    get_or_404(db.fee_configs, fid)
    limit, offset = pagination()
    items = sort_created([p for p in db.policies.values() if p["fee_config_id"] == fid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_policy(p) for p in page], limit, offset, total)


@app.post("/fee-configs/<fid>/update")
def fee_update(fid):
    r = get_or_404(db.fee_configs, fid)
    if r["status"] != "DRAFT":
        raise E.err_invalid_state("only DRAFT fee configs may be updated")
    b = body()
    exp = b.get("expected_fee_config_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        raise E.err_invalid_request("expected_fee_config_version required")
    if exp != r["version"]:
        raise E.err_stale_version()
    new_pct = r["flat_fee_pct"]
    new_cents = r["flat_fee_cents"]
    if "flat_fee_pct" in b and b["flat_fee_pct"] is not None:
        v = b["flat_fee_pct"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise E.err_invalid_request("flat_fee_pct must be a number")
        if dec(v) <= 0 or dec(v) > 1:
            raise E.err_invalid_request("flat_fee_pct out of range")
        new_pct = v
    if "flat_fee_cents" in b and b["flat_fee_cents"] is not None:
        v = b["flat_fee_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise E.err_invalid_request("flat_fee_cents must be positive integer")
        new_cents = v
    filing = db.rate_filings.get(r["filing_id"])
    if filing is None:
        raise E.err_not_found("filing not found")
    if filing["status"] != "APPROVED":
        raise E.err_rate_filing_not_approved()
    check_fee_vs_filing(filing, new_pct, new_cents)
    r["flat_fee_pct"] = new_pct
    r["flat_fee_cents"] = new_cents
    svc.touch(r)
    return success_obj(S.ser_fee_config(r))


@app.post("/fee-configs/<fid>/activate")
def fee_activate(fid):
    r = get_or_404(db.fee_configs, fid)
    if r["status"] != "DRAFT":
        raise E.err_invalid_state("only DRAFT fee configs may be activated")
    filing = db.rate_filings.get(r["filing_id"])
    if filing is None:
        raise E.err_not_found("filing not found")
    if filing["status"] != "APPROVED":
        raise E.err_rate_filing_not_approved()
    check_fee_vs_filing(filing, r["flat_fee_pct"], r["flat_fee_cents"])
    for other in db.fee_configs.values():
        if other["id"] != fid and other["state_code"] == r["state_code"] and other["status"] == "ACTIVE":
            raise E.err_fee_config_already_active()
    r["status"] = "ACTIVE"
    svc.touch(r)
    return success_obj(S.ser_fee_config(r))


@app.post("/fee-configs/<fid>/retire")
def fee_retire(fid):
    r = get_or_404(db.fee_configs, fid)
    if r["status"] != "ACTIVE":
        raise E.err_invalid_state("only ACTIVE fee configs may be retired")
    r["status"] = "RETIRED"
    svc.touch(r)
    return success_obj(S.ser_fee_config(r))


# ---------------------------------------------------------------------------
# Reinsurance treaties
# ---------------------------------------------------------------------------
@app.post("/reinsurance-treaties")
def treaty_create():
    b = body()
    name = require_str(b, "name")
    pct = require_number(b, "quota_share_pct")
    if dec(pct) <= 0 or dec(pct) >= 1:
        raise E.err_invalid_request("quota_share_pct must be in (0, 1)")
    tid = new_id()
    ts = now()
    r = {
        "id": tid, "name": name, "quota_share_pct": pct,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.treaties[tid] = r
    return success_obj(S.ser_treaty(r), 201)


@app.get("/reinsurance-treaties")
def treaty_list():
    limit, offset = pagination()
    items = list(db.treaties.values())
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_treaty(r) for r in page], limit, offset, total)


@app.post("/reinsurance-treaties/<tid>/activate")
def treaty_activate(tid):
    r = get_or_404(db.treaties, tid)
    if r["status"] != "DRAFT":
        raise E.err_invalid_state("only DRAFT treaties may be activated")
    r["status"] = "ACTIVE"
    svc.touch(r)
    return success_obj(S.ser_treaty(r))


@app.post("/reinsurance-treaties/<tid>/retire")
def treaty_retire(tid):
    r = get_or_404(db.treaties, tid)
    if r["status"] != "ACTIVE":
        raise E.err_invalid_state("only ACTIVE treaties may be retired")
    for cohort_id, attached in db.cohort_treaty.items():
        if attached == tid:
            raise E.err_treaty_in_use()
    r["status"] = "RETIRED"
    svc.touch(r)
    return success_obj(S.ser_treaty(r))


# ---------------------------------------------------------------------------
# Causes
# ---------------------------------------------------------------------------
@app.post("/causes")
def cause_create():
    b = body()
    name = require_str(b, "name")
    cid = new_id()
    ts = now()
    r = {"id": cid, "name": name, "status": "ACTIVE", "created_at": ts, "updated_at": ts, "version": 1}
    db.causes[cid] = r
    return success_obj(S.ser_cause(r), 201)


@app.get("/causes")
def cause_list():
    limit, offset = pagination()
    items = list(db.causes.values())
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_cause(r) for r in page], limit, offset, total)


@app.get("/causes/<cid>")
def cause_get(cid):
    r = get_or_404(db.causes, cid)
    return success_obj(S.ser_cause(r))


@app.post("/causes/<cid>/retire")
def cause_retire(cid):
    r = get_or_404(db.causes, cid)
    if r["status"] != "ACTIVE":
        raise E.err_invalid_state("only ACTIVE causes may be retired")
    r["status"] = "RETIRED"
    svc.touch(r)
    return success_obj(S.ser_cause(r))


@app.get("/causes/<cid>/cohorts")
def cause_cohorts(cid):
    get_or_404(db.causes, cid)
    limit, offset = pagination()
    items = sort_created([c for c in db.cohorts.values() if c["cause_id"] == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_cohort(c) for c in page], limit, offset, total)


@app.get("/causes/<cid>/policies")
def cause_policies(cid):
    get_or_404(db.causes, cid)
    limit, offset = pagination()
    items = sort_created([p for p in db.policies.values() if p["cause_id"] == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_policy(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------
@app.post("/cohorts")
def cohort_create():
    b = body()
    year = require_int(b, "cohort_year")
    cause_id = require_str(b, "cause_id")
    cause = db.causes.get(cause_id)
    if cause is None or cause["status"] != "ACTIVE":
        raise E.err_cause_not_active()
    for c in db.cohorts.values():
        if c["cohort_year"] == year:
            raise E.err_invalid_request("cohort_year must be unique")
    cid = new_id()
    ts = now()
    r = {
        "id": cid, "cohort_year": year, "cause_id": cause_id, "status": "OPEN",
        "premium_pool_cents": 0, "fee_retained_cents": 0, "reinsurance_ceded_cents": 0,
        "claims_pot_cents": 0, "retained_claims_actual_cents": 0,
        "retained_claims_reserved_cents": 0, "giveback_actual_cents": 0,
        "giveback_projected_cents": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.cohorts[cid] = r
    return success_obj(S.ser_cohort(r), 201)


@app.get("/cohorts")
def cohort_list():
    lazy_cohort_transitions()
    limit, offset = pagination()
    items = list(db.cohorts.values())
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_cohort(c) for c in page], limit, offset, total)


@app.get("/cohorts/<cid>")
def cohort_get(cid):
    lazy_cohort_transitions()
    r = get_or_404(db.cohorts, cid)
    return success_obj(S.ser_cohort(r))


@app.post("/cohorts/<cid>/reinsurance")
def cohort_reinsurance(cid):
    lazy_cohort_transitions()
    r = get_or_404(db.cohorts, cid)
    if r["status"] != "OPEN":
        raise E.err_cohort_closed()
    b = body()
    treaty_id = require_str(b, "treaty_id")
    treaty = db.treaties.get(treaty_id)
    if treaty is None:
        raise E.err_not_found("treaty not found")
    db.cohort_treaty[cid] = treaty_id
    # Retroactively recompute reinsurance_share on ESCALATED (reserve) and PAID (payout) claims
    if treaty["status"] == "ACTIVE":
        pct = dec(treaty["quota_share_pct"])
        for c in svc.claims_in_cohort(cid):
            if c["status"] == "ESCALATED" and c["reserve_cents"] is not None:
                c["reinsurance_share_cents"] = rhu(dec(c["reserve_cents"]) * pct)
                svc.touch(c)
            elif c["status"] == "PAID" and c["payout_cents"] is not None:
                c["reinsurance_share_cents"] = rhu(dec(c["payout_cents"]) * pct)
                svc.touch(c)
    svc.recompute_cohort(r)
    svc.touch(r)
    return success_obj(S.ser_cohort(r))


@app.post("/cohorts/<cid>/run-giveback")
def cohort_run_giveback(cid):
    lazy_cohort_transitions()
    r = get_or_404(db.cohorts, cid)
    if r["status"] != "CLOSED":
        raise E.err_cohort_not_closed()
    svc.recompute_cohort(r)
    alloc, cause_allocs, total = svc.giveback_allocations(r)
    r["status"] = "DONATED"
    svc.touch(r)
    return success_obj({
        "cohort_id": r["id"],
        "giveback_total_cents": total,
        "cause_allocations": cause_allocs,
    })


@app.post("/cohorts/<cid>/close")
def cohort_close(cid):
    lazy_cohort_transitions()
    r = get_or_404(db.cohorts, cid)
    if r["status"] != "OPEN":
        raise E.err_invalid_state("only OPEN cohorts may be closed")
    r["status"] = "CLOSED"
    svc.touch(r)
    return success_obj(S.ser_cohort(r))


@app.get("/cohorts/<cid>/policies")
def cohort_policies(cid):
    get_or_404(db.cohorts, cid)
    limit, offset = pagination()
    items = sort_created([p for p in db.policies.values() if p["cohort_id"] == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_policy(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Policyholders
# ---------------------------------------------------------------------------
@app.post("/policyholders")
def policyholder_create():
    b = body()
    email = require_str(b, "email")
    full_name = require_str(b, "full_name")
    state_code = require_str(b, "state_code")
    for p in db.policyholders.values():
        if p["email"] == email:
            raise E.err_invalid_request("email must be unique")
    pid = new_id()
    ts = now()
    r = {
        "id": pid, "email": email, "full_name": full_name, "state_code": state_code,
        "fraud_strike_count": 0, "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.policyholders[pid] = r
    return success_obj(S.ser_policyholder(r), 201)


@app.get("/policyholders/<pid>")
def policyholder_get(pid):
    r = get_or_404(db.policyholders, pid)
    if role() == "Policyholder" and user_id() != pid:
        raise E.err_forbidden()
    return success_obj(S.ser_policyholder(r))


@app.get("/policyholders/<pid>/applications")
def policyholder_applications(pid):
    get_or_404(db.policyholders, pid)
    if role() == "Policyholder" and user_id() != pid:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([a for a in db.applications.values() if a["policyholder_id"] == pid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_application(a) for a in page], limit, offset, total)


@app.get("/policyholders/<pid>/quotes")
def policyholder_quotes(pid):
    get_or_404(db.policyholders, pid)
    if role() == "Policyholder" and user_id() != pid:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([q for q in db.quotes.values() if q["policyholder_id"] == pid])
    for q in items:
        lazy_quote_expiry(q)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_quote(q) for q in page], limit, offset, total)


@app.get("/policyholders/<pid>/policies")
def policyholder_policies(pid):
    get_or_404(db.policyholders, pid)
    if role() == "Policyholder" and user_id() != pid:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([p for p in db.policies.values() if p["policyholder_id"] == pid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_policy(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------
@app.post("/quotes")
def quote_create():
    uid = user_id()
    if uid is None or uid not in db.policyholders:
        raise E.err_forbidden("acting policyholder not recognized")
    ph = db.policyholders[uid]
    b = body()
    coverage = require_int(b, "coverage_amount_cents", min_val=1)
    premium = require_int(b, "premium_cents", min_val=1)
    grace = b.get("premium_grace_days", 60)
    if grace is None:
        grace = 60
    if isinstance(grace, bool) or not isinstance(grace, int) or grace < 0:
        raise E.err_invalid_request("premium_grace_days must be integer >= 0")
    qid = new_id()
    ts = now()
    r = {
        "id": qid, "policyholder_id": ph["id"],
        "coverage_amount_cents": coverage, "premium_cents": premium,
        "state_code": ph["state_code"],
        "expires_at": ts + timedelta(days=30),
        "premium_grace_days": grace, "status": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.quotes[qid] = r
    return success_obj(S.ser_quote(r), 201)


@app.get("/quotes/<qid>")
def quote_get(qid):
    r = get_or_404(db.quotes, qid)
    lazy_quote_expiry(r)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    return success_obj(S.ser_quote(r))


@app.get("/quotes/<qid>/policies")
def quote_policies(qid):
    r = get_or_404(db.quotes, qid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([p for p in db.policies.values() if p["quote_id"] == qid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_policy(p) for p in page], limit, offset, total)


@app.get("/quotes/<qid>/applications")
def quote_applications(qid):
    r = get_or_404(db.quotes, qid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([a for a in db.applications.values() if a["quote_id"] == qid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_application(a) for a in page], limit, offset, total)


@app.post("/quotes/<qid>/bind")
def quote_bind(qid):
    r = get_or_404(db.quotes, qid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    lazy_quote_expiry(r)
    if r["status"] == "EXPIRED":
        raise E.err_quote_expired()
    if r["status"] != "OPEN":
        raise E.err_invalid_state("quote not OPEN")
    b = body()
    vel = require_int(b, "checkout_velocity_seconds", min_val=0)
    reuse = require_int(b, "device_reuse_count", min_val=0)
    ipa = require_bool(b, "answers_ipa_acknowledged")
    signals = behavioral_signals(vel, reuse, ipa)
    if signals > 0:
        raise E.err_application_auto_decline_required()
    ph = db.policyholders[r["policyholder_id"]]
    if ph["status"] != "ACTIVE":
        raise E.err_policyholder_debarred()
    policy = svc.bind_policy(r, 0)
    return success_obj(S.ser_policy(policy), 201)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@app.post("/applications")
def application_create():
    b = body()
    quote_id = require_str(b, "quote_id")
    vel = require_int(b, "checkout_velocity_seconds", min_val=0)
    reuse = require_int(b, "device_reuse_count", min_val=0)
    ipa = require_bool(b, "answers_ipa_acknowledged")
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise E.err_not_found("quote not found")
    if role() == "Policyholder" and user_id() != quote["policyholder_id"]:
        raise E.err_forbidden()
    lazy_quote_expiry(quote)
    if quote["status"] == "EXPIRED":
        raise E.err_quote_expired()
    if quote["status"] != "OPEN":
        raise E.err_invalid_state("quote not OPEN")
    ph = db.policyholders[quote["policyholder_id"]]
    if ph["status"] != "ACTIVE" or ph["fraud_strike_count"] >= 3:
        raise E.err_policyholder_debarred()
    signals = behavioral_signals(vel, reuse, ipa)
    aid = new_id()
    ts = now()
    status = "DECLINED" if signals >= 2 else "UNDER_REVIEW"
    r = {
        "id": aid, "policyholder_id": ph["id"], "quote_id": quote["id"],
        "checkout_velocity_seconds": vel, "device_reuse_count": reuse,
        "answers_ipa_acknowledged": ipa, "behavioral_signal_count": signals,
        "status": status, "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.applications[aid] = r
    return success_obj(S.ser_application(r), 201)


@app.get("/applications/<aid>")
def application_get(aid):
    r = get_or_404(db.applications, aid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    return success_obj(S.ser_application(r))


@app.post("/applications/<aid>/approve")
def application_approve(aid):
    r = get_or_404(db.applications, aid)
    if r["status"] != "UNDER_REVIEW":
        raise E.err_invalid_state("application not UNDER_REVIEW")
    ph = db.policyholders[r["policyholder_id"]]
    if ph["status"] != "ACTIVE":
        raise E.err_policyholder_debarred()
    if r["behavioral_signal_count"] >= 2:
        raise E.err_application_auto_decline_required()
    quote = db.quotes[r["quote_id"]]
    policy = svc.bind_policy(quote, r["behavioral_signal_count"])
    r["status"] = "APPROVED"
    svc.touch(r)
    return success_obj(S.ser_policy(policy))


@app.post("/applications/<aid>/decline")
def application_decline(aid):
    r = get_or_404(db.applications, aid)
    if r["status"] != "UNDER_REVIEW":
        raise E.err_invalid_state("application not UNDER_REVIEW")
    r["status"] = "DECLINED"
    svc.touch(r)
    return success_obj(S.ser_application(r))


@app.post("/applications/<aid>/resubmit")
def application_resubmit(aid):
    r = get_or_404(db.applications, aid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    if r["status"] != "DECLINED":
        raise E.err_invalid_state("only DECLINED applications may be resubmitted")
    b = body()
    vel = require_int(b, "checkout_velocity_seconds", min_val=0)
    reuse = require_int(b, "device_reuse_count", min_val=0)
    ipa = require_bool(b, "answers_ipa_acknowledged")
    quote = db.quotes[r["quote_id"]]
    lazy_quote_expiry(quote)
    if quote["status"] != "OPEN":
        raise E.err_quote_expired()
    signals = behavioral_signals(vel, reuse, ipa)
    r["checkout_velocity_seconds"] = vel
    r["device_reuse_count"] = reuse
    r["answers_ipa_acknowledged"] = ipa
    r["behavioral_signal_count"] = signals
    if signals < 2:
        r["status"] = "UNDER_REVIEW"
    svc.touch(r)
    return success_obj(S.ser_application(r))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
@app.get("/policies/<pid>")
def policy_get(pid):
    r = get_or_404(db.policies, pid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    return success_obj(S.ser_policy(r))


@app.post("/policies/<pid>/cause-election")
def policy_cause_election(pid):
    r = get_or_404(db.policies, pid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    b = body()
    cause_id = require_str(b, "cause_id")
    exp = b.get("expected_policy_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        raise E.err_invalid_request("expected_policy_version required")
    if exp != r["version"]:
        raise E.err_stale_version()
    cohort = db.cohorts.get(r["cohort_id"])
    if cohort is None:
        raise E.err_not_found("cohort not found")
    if cohort["status"] != "OPEN":
        raise E.err_cohort_closed()
    cause = db.causes.get(cause_id)
    if cause is None or cause["status"] != "ACTIVE":
        raise E.err_cause_not_active()
    r["cause_id"] = cause_id
    r["cause_election_version"] = r.get("cause_election_version", 0) + 1
    svc.touch(r)
    return success_obj(S.ser_policy(r))


@app.post("/policies/<pid>/premium-payments")
def policy_premium_payment(pid):
    r = get_or_404(db.policies, pid)
    if r["status"] != "ACTIVE":
        raise E.err_policy_not_active()
    b = body()
    amount = require_int(b, "amount_cents")
    if amount <= 0:
        raise E.err_invalid_request("amount_cents must be > 0")
    if r["premium_outstanding_cents"] <= 0:
        raise E.err_premium_already_paid()
    charge = min(amount, r["premium_outstanding_cents"])
    fee_config = db.fee_configs.get(r["fee_config_id"])
    if fee_config is None:
        raise E.err_not_found("fee config not found")
    filing = db.rate_filings.get(fee_config["filing_id"])
    if filing is None:
        raise E.err_not_found("filing not found")
    if filing["filing_mode"] == "ABSOLUTE_CENTS":
        fee = min(fee_config["flat_fee_cents"], charge)
    else:
        fee = rhu(dec(charge) * dec(fee_config["flat_fee_pct"]))
    treaty = svc.cohort_treaty(r["cohort_id"])
    ceded = 0
    if treaty:
        ceded = rhu(dec(charge - fee) * dec(treaty["quota_share_pct"]))
    e1 = svc.append_ledger(pid, "PREMIUM_CHARGE", charge)
    svc.append_ledger(pid, "FEE_RETAINED", fee)
    svc.append_ledger(pid, "REINSURANCE_CEDED", ceded)
    r["premium_paid_cents"] += charge
    r["premium_outstanding_cents"] = max(0, r["annual_premium_cents"] - r["premium_paid_cents"])
    svc.touch(r)
    cohort = db.cohorts.get(r["cohort_id"])
    if cohort is not None:
        svc.recompute_cohort(cohort)
        svc.touch(cohort)
    return success_obj(S.ser_ledger_entry(e1), 201)


@app.post("/policies/<pid>/cancel")
def policy_cancel(pid):
    r = get_or_404(db.policies, pid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    if r["status"] != "ACTIVE":
        raise E.err_invalid_state("only ACTIVE policies may be cancelled")
    r["status"] = "CANCELLED"
    svc.touch(r)
    return success_obj(S.ser_policy(r))


@app.post("/policies/<pid>/lapse")
def policy_lapse(pid):
    r = get_or_404(db.policies, pid)
    if r["status"] != "ACTIVE":
        raise E.err_invalid_state("only ACTIVE policies may be lapsed")
    if r["premium_outstanding_cents"] <= 0:
        raise E.err_invalid_request("nothing to lapse for")
    quote = db.quotes.get(r["quote_id"])
    grace = quote["premium_grace_days"] if quote else 60
    if now() < r["created_at"] + timedelta(days=grace):
        raise E.err_lapse_grace_not_elapsed()
    r["status"] = "LAPSED"
    svc.touch(r)
    return success_obj(S.ser_policy(r))


@app.get("/policies/<pid>/ledger")
def policy_ledger(pid):
    r = get_or_404(db.policies, pid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([e for e in db.ledger.values() if e["policy_id"] == pid])
    kind = request.args.get("kind")
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_ledger_entry(e) for e in page], limit, offset, total)


@app.get("/policies/<pid>/claims")
def policy_claims(pid):
    r = get_or_404(db.policies, pid)
    if role() == "Policyholder" and user_id() != r["policyholder_id"]:
        raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([c for c in db.claims.values() if c["policy_id"] == pid])
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_claim(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@app.post("/claims")
def claim_create():
    b = body()
    policy_id = require_str(b, "policy_id")
    video_ref = require_str(b, "video_statement_ref")
    claimed = require_int(b, "claimed_amount_cents", min_val=1)
    score = require_number(b, "fraud_score")
    if dec(score) < 0 or dec(score) > 1:
        raise E.err_invalid_request("fraud_score must be in [0, 1]")
    policy = db.policies.get(policy_id)
    if policy is None:
        raise E.err_not_found("policy not found")
    if role() == "Policyholder" and user_id() != policy["policyholder_id"]:
        raise E.err_forbidden()
    if policy["status"] != "ACTIVE":
        raise E.err_policy_not_active()
    cid = new_id()
    ts = now()
    auto = (
        dec(score) < dec("0.30")
        and claimed <= 250000
        and policy["fraud_flag"] is False
    )
    claim = {
        "id": cid, "policy_id": policy_id,
        "video_statement_ref": video_ref, "claimed_amount_cents": claimed,
        "fraud_score": score, "payout_cents": None,
        "reserve_cents": None, "reinsurance_share_cents": 0,
        "denial_reason": None, "denied_by_adjuster_id": None,
        "appeal_deadline": None, "appeal_count": 0,
        "status": "FNOL_SUBMITTED", "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.claims[cid] = claim
    if auto:
        claim["status"] = "AUTO_APPROVED"
        claim["payout_cents"] = claimed
        svc.pay_claim(claim, claimed)
    else:
        claim["status"] = "ESCALATED"
        claim["reserve_cents"] = claimed
        treaty = svc.cohort_treaty(policy["cohort_id"])
        if treaty:
            claim["reinsurance_share_cents"] = rhu(dec(claimed) * dec(treaty["quota_share_pct"]))
        svc.touch(claim)
        cohort = db.cohorts.get(policy["cohort_id"])
        if cohort is not None:
            svc.recompute_cohort(cohort)
            svc.touch(cohort)
    return success_obj(S.ser_claim(claim), 201)


@app.get("/claims")
def claim_list():
    limit, offset = pagination()
    items = list(db.claims.values())
    pid = request.args.get("policy_id")
    st = request.args.get("status")
    if pid is not None:
        items = [c for c in items if c["policy_id"] == pid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items = sort_created(items)
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_claim(c) for c in page], limit, offset, total)


@app.get("/claims/<cid>")
def claim_get(cid):
    r = get_or_404(db.claims, cid)
    if role() == "Policyholder":
        policy = db.policies.get(r["policy_id"])
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    return success_obj(S.ser_claim(r))


@app.get("/claims/<cid>/payments")
def claim_payments(cid):
    r = get_or_404(db.claims, cid)
    if role() == "Policyholder":
        policy = db.policies.get(r["policy_id"])
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([p for p in db.payments.values() if p["claim_id"] == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_payment(p) for p in page], limit, offset, total)


@app.get("/claims/<cid>/ledger")
def claim_ledger(cid):
    r = get_or_404(db.claims, cid)
    if role() == "Policyholder":
        policy = db.policies.get(r["policy_id"])
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([e for e in db.ledger.values() if e.get("claim_id") == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_ledger_entry(e) for e in page], limit, offset, total)


@app.post("/claims/<cid>/approve")
def claim_approve(cid):
    r = get_or_404(db.claims, cid)
    if r["status"] != "ESCALATED":
        raise E.err_invalid_state("only ESCALATED claims may be approved")
    b = body()
    payout = require_int(b, "payout_cents")
    exp = b.get("expected_claim_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        raise E.err_invalid_request("expected_claim_version required")
    if exp != r["version"]:
        raise E.err_stale_version()
    if payout <= 0:
        raise E.err_invalid_request("payout_cents must be > 0")
    svc.pay_claim(r, payout)
    return success_obj(S.ser_claim(r))


@app.post("/claims/<cid>/deny")
def claim_deny(cid):
    r = get_or_404(db.claims, cid)
    if r["status"] != "ESCALATED":
        raise E.err_invalid_state("only ESCALATED claims may be denied")
    b = body()
    reason = require_str(b, "denial_reason")
    exp = b.get("expected_claim_version")
    if exp is None or isinstance(exp, bool) or not isinstance(exp, int):
        raise E.err_invalid_request("expected_claim_version required")
    if exp != r["version"]:
        raise E.err_stale_version()
    if reason not in ("FRAUD", "COVERAGE", "OTHER"):
        raise E.err_invalid_request("denial_reason invalid")
    r["reserve_cents"] = None
    r["denial_reason"] = reason
    r["denied_by_adjuster_id"] = user_id()
    r["appeal_deadline"] = now() + timedelta(days=30)
    r["status"] = "DENIED"
    svc.touch(r)
    policy = db.policies.get(r["policy_id"])
    if policy is not None:
        cohort = db.cohorts.get(policy["cohort_id"])
        if cohort is not None:
            svc.recompute_cohort(cohort)
            svc.touch(cohort)
    if reason == "FRAUD" and policy is not None:
        ph = db.policyholders.get(policy["policyholder_id"])
        if ph is not None:
            ph["fraud_strike_count"] += 1
            if ph["fraud_strike_count"] >= 3:
                ph["status"] = "DEBARRED"
                for a in db.applications.values():
                    if a["policyholder_id"] == ph["id"] and a["status"] == "UNDER_REVIEW":
                        a["status"] = "DECLINED"
                        svc.touch(a)
            svc.touch(ph)
    return success_obj(S.ser_claim(r))


@app.post("/claims/<cid>/appeals")
def claim_appeal_create(cid):
    r = get_or_404(db.claims, cid)
    if r["status"] != "DENIED":
        raise E.err_invalid_state("only DENIED claims may be appealed")
    policy = db.policies.get(r["policy_id"])
    if role() == "Policyholder":
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    if r["appeal_count"] >= 1:
        raise E.err_appeal_limit_reached()
    if r["appeal_deadline"] is not None and now() > r["appeal_deadline"]:
        raise E.err_appeal_window_closed()
    b = body()
    statement = require_str(b, "statement")
    aid = new_id()
    ts = now()
    appeal = {
        "id": aid, "claim_id": cid, "statement": statement,
        "review_note": None, "status": "PENDING",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.appeals[aid] = appeal
    r["appeal_count"] += 1
    r["status"] = "APPEALED"
    svc.touch(r)
    return success_obj(S.ser_appeal(appeal), 201)


@app.get("/claims/<cid>/appeals")
def claim_appeals_list(cid):
    r = get_or_404(db.claims, cid)
    if role() == "Policyholder":
        policy = db.policies.get(r["policy_id"])
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    limit, offset = pagination()
    items = sort_created([a for a in db.appeals.values() if a["claim_id"] == cid])
    total = len(items)
    page = page_slice(items, limit, offset)
    return success_list([S.ser_appeal(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
@app.get("/appeals/<aid>")
def appeal_get(aid):
    r = get_or_404(db.appeals, aid)
    if role() == "Policyholder":
        claim = db.claims.get(r["claim_id"])
        policy = db.policies.get(claim["policy_id"]) if claim else None
        if policy is None or user_id() != policy["policyholder_id"]:
            raise E.err_forbidden()
    return success_obj(S.ser_appeal(r))


def _review_appeal_common(aid):
    r = get_or_404(db.appeals, aid)
    if r["status"] != "PENDING":
        raise E.err_invalid_state("appeal not PENDING")
    claim = db.claims.get(r["claim_id"])
    if claim is None:
        raise E.err_not_found("claim not found")
    if claim["denied_by_adjuster_id"] is not None and user_id() == claim["denied_by_adjuster_id"]:
        raise E.err_segregation_of_duties()
    return r, claim


@app.post("/appeals/<aid>/uphold")
def appeal_uphold(aid):
    r, claim = _review_appeal_common(aid)
    b = body()
    note = require_str(b, "review_note")
    r["review_note"] = note
    r["status"] = "UPHELD"
    svc.touch(r)
    claim["status"] = "DENIED"
    svc.touch(claim)
    return success_obj(S.ser_appeal(r))


@app.post("/appeals/<aid>/overturn")
def appeal_overturn(aid):
    r, claim = _review_appeal_common(aid)
    b = body()
    payout = require_int(b, "payout_cents")
    note = require_str(b, "review_note")
    if payout <= 0:
        raise E.err_invalid_request("payout_cents must be > 0")
    r["review_note"] = note
    r["status"] = "OVERTURNED"
    svc.touch(r)
    claim["denial_reason"] = None
    svc.pay_claim(claim, payout)
    return success_obj(S.ser_appeal(r))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
