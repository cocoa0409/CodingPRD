#!/usr/bin/env python3
"""Endorsement-based zero-interest microloan crowdfunding API (Kiva U.S. style).

Single-file Flask implementation of the PRD in workspace/PRD.md.
In-memory store; the logical clock defaults to 2026-09-01T00:00:00Z.
"""
import calendar
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._lock = threading.Lock()
        self._now = DEFAULT_CLOCK

    def now(self):
        with self._lock:
            return self._now

    def current(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt


CLOCK = LogicalClock()


def fmt_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value):
    if not isinstance(value, str):
        raise ValueError("not a timestamp string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Whole months elapsed from start to end."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    return months


def round_half_up_int(numer, denom):
    """round_half_up(numer / denom) to an integer (denom > 0)."""
    return (2 * numer + denom) // (2 * denom)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Caller is not permitted to perform this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed or missing request field"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Resource state does not permit this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(CLOCK.now()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.status


@app.errorhandler(404)
def _handle_404(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def _handle_500(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

STORE_LOCK = threading.RLock()
_seq = {"n": 0}

DB = {
    "borrowers": {},
    "lenders": {},
    "trustees": {},
    "applications": {},
    "invites": {},
    "endorsements": {},
    "contributions": {},
    "loans": {},
    "installments": {},
    "payments": {},
    "impact_reports": {},
}


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def ser_borrower(b):
    return {
        "id": b["id"],
        "legal_name": b["legal_name"],
        "business_name": b["business_name"],
        "email": b["email"],
        "business_tenure_months": b["business_tenure_months"],
        "prior_repaid_loans_count": b["prior_repaid_loans_count"],
        "status": b["status"],
        "social_underwriting_score": b["social_underwriting_score"],
        "underwriting_variant": b["underwriting_variant"],
        "completed_loan_count": b["completed_loan_count"],
        "defaulted_loan_count": b["defaulted_loan_count"],
        "restricted_since": fmt_ts(b["restricted_since"]),
        "created_at": fmt_ts(b["created_at"]),
        "updated_at": fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def ser_invite(inv):
    return {
        "id": inv["id"],
        "borrower_id": inv["borrower_id"],
        "invitee_email": inv["invitee_email"],
        "invite_token": inv["invite_token"],
        "status": inv["status"],
        "responded_at": fmt_ts(inv["responded_at"]),
        "created_at": fmt_ts(inv["created_at"]),
    }


def ser_lender(l):
    return {
        "id": l["id"],
        "display_name": l["display_name"],
        "email": l["email"],
        "lending_balance_cents": l["lending_balance_cents"],
        "total_deposited_cents": l["total_deposited_cents"],
        "lifetime_lent_cents": l["lifetime_lent_cents"],
        "lifetime_repaid_cents": l["lifetime_repaid_cents"],
        "created_at": fmt_ts(l["created_at"]),
        "updated_at": fmt_ts(l["updated_at"]),
        "version": l["version"],
    }


def ser_trustee(t):
    return {
        "id": t["id"],
        "org_name": t["org_name"],
        "endorsement_limit_cents": t["endorsement_limit_cents"],
        "status": t["status"],
        "suspension_reason": t["suspension_reason"],
        "active_endorsement_exposure_cents": t["active_endorsement_exposure_cents"],
        "endorsed_terminal_count": t["endorsed_terminal_count"],
        "endorsed_defaulted_count": t["endorsed_defaulted_count"],
        "default_rate_bps": t["default_rate_bps"],
        "created_at": fmt_ts(t["created_at"]),
        "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "borrower_id": a["borrower_id"],
        "trustee_id": a["trustee_id"],
        "requested_amount_cents": a["requested_amount_cents"],
        "term_months": a["term_months"],
        "business_purpose": a["business_purpose"],
        "endorsement_mode": a["endorsement_mode"],
        "required_endorser_count": a["required_endorser_count"],
        "distinct_endorser_count": a["distinct_endorser_count"],
        "private_total_cents": a["private_total_cents"],
        "public_total_cents": a["public_total_cents"],
        "funded_total_cents": a["funded_total_cents"],
        "status": a["status"],
        "review_notes": a["review_notes"],
        "private_started_at": fmt_ts(a["private_started_at"]),
        "private_deadline": fmt_ts(a["private_deadline"]),
        "public_started_at": fmt_ts(a["public_started_at"]),
        "public_deadline": fmt_ts(a["public_deadline"]),
        "funded_at": fmt_ts(a["funded_at"]),
        "terminal_at": fmt_ts(a["terminal_at"]),
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_endorsement(e):
    return {
        "id": e["id"],
        "loan_application_id": e["loan_application_id"],
        "lender_id": e["lender_id"],
        "amount_cents": e["amount_cents"],
        "is_trustee_endorsement": e["is_trustee_endorsement"],
        "trustee_id": e["trustee_id"],
        "status": e["status"],
        "resolved_at": fmt_ts(e["resolved_at"]),
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_contribution(c):
    return {
        "id": c["id"],
        "loan_application_id": c["loan_application_id"],
        "lender_id": c["lender_id"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "resolved_at": fmt_ts(c["resolved_at"]),
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_loan(loan):
    return {
        "id": loan["id"],
        "loan_application_id": loan["loan_application_id"],
        "borrower_id": loan["borrower_id"],
        "principal_cents": loan["principal_cents"],
        "term_months": loan["term_months"],
        "disbursed_at": fmt_ts(loan["disbursed_at"]),
        "status": loan["status"],
        "schedule_status": loan["schedule_status"],
        "provisional_base_cents": loan["provisional_base_cents"],
        "final_base_cents": loan["final_base_cents"],
        "final_first_cents": loan["final_first_cents"],
        "outstanding_cents": loan["outstanding_cents"],
        "delinquent_since": fmt_ts(loan["delinquent_since"]),
        "defaulted_at": fmt_ts(loan["defaulted_at"]),
        "created_at": fmt_ts(loan["created_at"]),
        "updated_at": fmt_ts(loan["updated_at"]),
        "version": loan["version"],
    }


def ser_installment(i):
    return {
        "id": i["id"],
        "loan_id": i["loan_id"],
        "installment_number": i["installment_number"],
        "due_date": fmt_ts(i["due_date"]),
        "amount_due_cents": i["amount_due_cents"],
        "amount_paid_cents": i["amount_paid_cents"],
        "remaining_cents": i["remaining_cents"],
        "status": i["status"],
        "paid_at": fmt_ts(i["paid_at"]),
        "created_at": fmt_ts(i["created_at"]),
        "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "borrower_id": p["borrower_id"],
        "amount_cents": p["amount_cents"],
        "paid_at": fmt_ts(p["paid_at"]),
        "created_at": fmt_ts(p["created_at"]),
    }


def ser_impact_report(r):
    return {
        "id": r["id"],
        "loan_id": r["loan_id"],
        "borrower_id": r["borrower_id"],
        "months_after_disbursement": r["months_after_disbursement"],
        "revenue_change_pct": r["revenue_change_pct"],
        "jobs_created": r["jobs_created"],
        "narrative": r["narrative"],
        "is_mid_term": r["is_mid_term"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def touch(entity):
    entity["updated_at"] = CLOCK.now()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

DECLARED_ROLES = {"Anonymous", "Borrower", "Lender", "Trustee", "PlatformAdmin"}
ENTITY_ROLES = {"Borrower", "Lender", "Trustee"}

ANONYMOUS_ENDPOINTS = {
    ("POST", "/borrowers"),
    ("POST", "/lenders"),
}


def caller():
    """Authenticate the request. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in DECLARED_ROLES:
        raise err_unauthenticated("X-User-Role header missing or not a declared role")
    if role in ENTITY_ROLES and not user_id:
        raise err_unauthenticated("X-User-ID header required for entity-backed roles")
    return role, user_id


def require_roles(role, allowed):
    if role not in allowed:
        raise err_forbidden(f"Role {role} may not perform this operation")


def recompute_exposure(trustee):
    trustee["active_endorsement_exposure_cents"] = sum(
        e["amount_cents"]
        for e in DB["endorsements"].values()
        if e["is_trustee_endorsement"]
        and e["trustee_id"] == trustee["id"]
        and e["status"] == "ACTIVE"
    )


def recompute_app_totals(app):
    endorsements = [
        e
        for e in DB["endorsements"].values()
        if e["loan_application_id"] == app["id"] and e["status"] == "ACTIVE"
    ]
    contributions = [
        c
        for c in DB["contributions"].values()
        if c["loan_application_id"] == app["id"] and c["status"] == "ACTIVE"
    ]
    app["private_total_cents"] = sum(e["amount_cents"] for e in endorsements)
    app["public_total_cents"] = sum(c["amount_cents"] for c in contributions)
    app["funded_total_cents"] = app["private_total_cents"] + app["public_total_cents"]
    distinct_lenders = {
        e["lender_id"] for e in endorsements if not e["is_trustee_endorsement"]
    }
    trustee_count = sum(1 for e in endorsements if e["is_trustee_endorsement"])
    app["distinct_endorser_count"] = len(distinct_lenders) + trustee_count


def get_borrower_or_404(borrower_id):
    b = DB["borrowers"].get(borrower_id)
    if b is None:
        raise err_not_found("Borrower not found")
    return b


def get_lender_or_404(lender_id):
    l = DB["lenders"].get(lender_id)
    if l is None:
        raise err_not_found("Lender not found")
    return l


def get_trustee_or_404(trustee_id):
    t = DB["trustees"].get(trustee_id)
    if t is None:
        raise err_not_found("Trustee not found")
    return t


def get_app_or_404(app_id):
    a = DB["applications"].get(app_id)
    if a is None:
        raise err_not_found("LoanApplication not found")
    return a


def get_loan_or_404(loan_id):
    loan = DB["loans"].get(loan_id)
    if loan is None:
        raise err_not_found("Loan not found")
    return loan


def body_json():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise err_invalid_request("Request body is not valid JSON")
        if not isinstance(data, dict):
            raise err_invalid_request("Request body must be a JSON object")
        return data
    return {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise err_invalid_request(f"Field '{field}' must be a non-empty string")
    return v


def opt_str(data, field):
    if field not in data or data[field] is None:
        return None
    return req_str(data, field)


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field '{field}' must be an integer")
    return v


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    return req_int(data, field)


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    # PRD 2.3: limit defaults to 10, min 1, max 100; offset defaults to 0.
    limit = 10 if raw_limit is None else None
    try:
        if limit is None:
            limit = int(raw_limit)
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be non-negative")
    return limit, offset


def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Clock / sweep endpoints
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    data = body_json()
    raw = data.get("current_utc")
    if not isinstance(raw, str):
        raise err_invalid_request("current_utc must be an ISO 8601 string")
    try:
        dt = parse_ts(raw)
    except ValueError:
        raise err_invalid_request("current_utc is not a valid timestamp")
    CLOCK.set(dt)
    return ok({"current_utc": fmt_ts(CLOCK.current())})


def _sweep_expire_invites(now):
    count = 0
    for inv in DB["invites"].values():
        if inv["status"] == "SENT" and inv["created_at"] <= now - timedelta(days=30):
            inv["status"] = "EXPIRED"
            inv["responded_at"] = now
            count += 1
    return count


def _refund_endorsement(e, when, new_status):
    e["status"] = new_status
    e["resolved_at"] = when
    touch(e)
    if not e["is_trustee_endorsement"] and e["lender_id"]:
        lender = DB["lenders"].get(e["lender_id"])
        if lender is not None:
            lender["lending_balance_cents"] += e["amount_cents"]
            touch(lender)
    else:
        trustee = DB["trustees"].get(e["trustee_id"])
        if trustee is not None:
            recompute_exposure(trustee)
            touch(trustee)


def _refund_contribution(c, when):
    c["status"] = "REFUNDED"
    c["resolved_at"] = when
    touch(c)
    lender = DB["lenders"].get(c["lender_id"])
    if lender is not None:
        lender["lending_balance_cents"] += c["amount_cents"]
        touch(lender)


def _sweep_expire_applications(now):
    count = 0
    for app_rec in DB["applications"].values():
        if (
            app_rec["status"] == "PRIVATE_FUNDRAISING"
            and app_rec["private_deadline"] is not None
            and now > app_rec["private_deadline"]
        ):
            app_rec["status"] = "EXPIRED_PRIVATE"
            app_rec["terminal_at"] = now
            for e in DB["endorsements"].values():
                if (
                    e["loan_application_id"] == app_rec["id"]
                    and e["status"] == "ACTIVE"
                ):
                    _refund_endorsement(e, now, "REFUNDED")
            recompute_app_totals(app_rec)
            touch(app_rec)
            count += 1
        elif (
            app_rec["status"] == "PUBLIC_FUNDRAISING"
            and app_rec["public_deadline"] is not None
            and now > app_rec["public_deadline"]
            and app_rec["funded_total_cents"] < app_rec["requested_amount_cents"]
        ):
            app_rec["status"] = "EXPIRED_PUBLIC"
            app_rec["terminal_at"] = now
            for e in DB["endorsements"].values():
                if (
                    e["loan_application_id"] == app_rec["id"]
                    and e["status"] == "ACTIVE"
                ):
                    _refund_endorsement(e, now, "REFUNDED")
            for c in DB["contributions"].values():
                if (
                    c["loan_application_id"] == app_rec["id"]
                    and c["status"] == "ACTIVE"
                ):
                    _refund_contribution(c, now)
            recompute_app_totals(app_rec)
            touch(app_rec)
            count += 1
    return count


def _sweep_installment_labels(now):
    for inst in DB["installments"].values():
        if inst["status"] == "PAID":
            continue
        due = inst["due_date"]
        if inst["status"] == "PENDING" and due - timedelta(days=7) <= now < due:
            inst["status"] = "DUE"
            touch(inst)
        if (
            inst["status"] in ("DUE", "PARTIAL")
            and now >= due
            and inst["remaining_cents"] > 0
        ):
            inst["status"] = "LATE"
            touch(inst)


def _loan_installments(loan_id):
    return sorted(
        (i for i in DB["installments"].values() if i["loan_id"] == loan_id),
        key=lambda i: i["installment_number"],
    )


def _earliest_non_paid(loan_id):
    for inst in _loan_installments(loan_id):
        if inst["status"] != "PAID":
            return inst
    return None


def _recompute_trustee_default_rate(trustee):
    if trustee["endorsed_terminal_count"] == 0:
        trustee["default_rate_bps"] = 0
    else:
        trustee["default_rate_bps"] = round_half_up_int(
            10000 * trustee["endorsed_defaulted_count"],
            trustee["endorsed_terminal_count"],
        )


def _default_loan(loan, now):
    loan["status"] = "DEFAULTED"
    loan["defaulted_at"] = now
    touch(loan)
    borrower = DB["borrowers"].get(loan["borrower_id"])
    if borrower is not None:
        borrower["status"] = "RESTRICTED"
        borrower["restricted_since"] = now
        borrower["defaulted_loan_count"] += 1
        touch(borrower)
    app_rec = DB["applications"].get(loan["loan_application_id"])
    if app_rec is not None and app_rec.get("trustee_id"):
        trustee = DB["trustees"].get(app_rec["trustee_id"])
        if trustee is not None:
            trustee["endorsed_terminal_count"] += 1
            trustee["endorsed_defaulted_count"] += 1
            _recompute_trustee_default_rate(trustee)
            touch(trustee)


def _sweep_loans(now):
    delinquent = 0
    defaulted = 0
    for loan in DB["loans"].values():
        inst = _earliest_non_paid(loan["id"])
        if inst is None:
            continue
        # A loan deep enough past due goes REPAYING -> DELINQUENT -> DEFAULTED
        # within a single sweep pass.
        if loan["status"] == "REPAYING":
            if inst["due_date"] < now - timedelta(days=14):
                loan["status"] = "DELINQUENT"
                loan["delinquent_since"] = now
                touch(loan)
                delinquent += 1
        if loan["status"] == "DELINQUENT":
            if inst["due_date"] < now - timedelta(days=74):
                _default_loan(loan, now)
                defaulted += 1
    return delinquent, defaulted


def _sweep_trustees():
    suspended = 0
    for trustee in DB["trustees"].values():
        if (
            trustee["status"] == "ACTIVE"
            and trustee["default_rate_bps"] > 2000
            and trustee["endorsed_terminal_count"] >= 3
        ):
            trustee["status"] = "SUSPENDED"
            trustee["suspension_reason"] = "DEFAULT_RATE"
            touch(trustee)
            suspended += 1
    return suspended


@app.route("/_sweeps/run", methods=["POST"])
def run_sweeps():
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    now = CLOCK.current()
    invites_expired = _sweep_expire_invites(now)
    applications_expired = _sweep_expire_applications(now)
    _sweep_installment_labels(now)
    loans_delinquent, loans_defaulted = _sweep_loans(now)
    trustees_suspended = _sweep_trustees()
    return ok(
        {
            "invites_expired": invites_expired,
            "applications_expired": applications_expired,
            "loans_delinquent": loans_delinquent,
            "loans_defaulted": loans_defaulted,
            "trustees_suspended": trustees_suspended,
        }
    )


# ---------------------------------------------------------------------------
# Borrowers
# ---------------------------------------------------------------------------


@app.route("/borrowers", methods=["POST"])
def create_borrower():
    data = body_json()
    legal_name = req_str(data, "legal_name")
    business_name = req_str(data, "business_name")
    email = req_str(data, "email")
    tenure = req_int(data, "business_tenure_months")
    prior = opt_int(data, "prior_repaid_loans_count")
    if prior is None:
        prior = 0
    if tenure < 0 or prior < 0:
        raise err_invalid_request("tenure and prior loan counts must be >= 0")
    if any(b["email"] == email for b in DB["borrowers"].values()):
        raise ApiError("ERR_DUPLICATE", 409, "A borrower with this email exists")
    now = CLOCK.now()
    borrower = {
        "id": new_id(),
        "legal_name": legal_name,
        "business_name": business_name,
        "email": email,
        "business_tenure_months": tenure,
        "prior_repaid_loans_count": prior,
        "status": "REGISTERED",
        "social_underwriting_score": 0,
        "underwriting_variant": "NONE",
        "completed_loan_count": 0,
        "defaulted_loan_count": 0,
        "restricted_since": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["borrowers"][borrower["id"]] = borrower
    return ok(ser_borrower(borrower), 201)


@app.route("/borrowers/<borrower_id>", methods=["GET"])
def get_borrower(borrower_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "PlatformAdmin", "Trustee", "Lender"})
    borrower = get_borrower_or_404(borrower_id)
    return ok(ser_borrower(borrower))


@app.route("/borrowers/<borrower_id>", methods=["PATCH"])
def update_borrower(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only update their own profile")
    borrower = get_borrower_or_404(borrower_id)
    data = body_json()
    if "legal_name" in data and data["legal_name"] is not None:
        borrower["legal_name"] = req_str(data, "legal_name")
    if "business_name" in data and data["business_name"] is not None:
        borrower["business_name"] = req_str(data, "business_name")
    if "business_tenure_months" in data and data["business_tenure_months"] is not None:
        v = req_int(data, "business_tenure_months")
        if v < 0:
            raise err_invalid_request("business_tenure_months must be >= 0")
        borrower["business_tenure_months"] = v
    if "prior_repaid_loans_count" in data and data["prior_repaid_loans_count"] is not None:
        v = req_int(data, "prior_repaid_loans_count")
        if v < 0:
            raise err_invalid_request("prior_repaid_loans_count must be >= 0")
        borrower["prior_repaid_loans_count"] = v
    touch(borrower)
    return ok(ser_borrower(borrower))


@app.route("/borrowers/<borrower_id>/underwriting-invites", methods=["GET"])
def list_borrower_invites(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only list their own invites")
    get_borrower_or_404(borrower_id)
    limit, offset = pagination_params()
    invites = [
        i for i in DB["invites"].values() if i["borrower_id"] == borrower_id
    ]
    return ok_list([ser_invite(i) for i in sorted_by_creation(invites)], limit, offset)


@app.route("/borrowers/<borrower_id>/underwriting-invites", methods=["POST"])
def create_invite(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    if user_id != borrower_id:
        raise err_forbidden("Borrowers may only invite for themselves")
    get_borrower_or_404(borrower_id)
    data = body_json()
    invitee_email = req_str(data, "invitee_email")
    if any(
        i["borrower_id"] == borrower_id and i["invitee_email"] == invitee_email
        for i in DB["invites"].values()
    ):
        raise ApiError(
            "ERR_DUPLICATE", 409, "This invitee has already been invited"
        )
    now = CLOCK.now()
    invite = {
        "id": new_id(),
        "borrower_id": borrower_id,
        "invitee_email": invitee_email,
        "invite_token": uuid.uuid4().hex,
        "status": "SENT",
        "responded_at": None,
        "created_at": now,
        "_seq": _next_seq(),
    }
    DB["invites"][invite["id"]] = invite
    return ok(ser_invite(invite), 201)


@app.route("/borrowers/<borrower_id>/loan-applications", methods=["GET"])
def list_borrower_applications(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only list their own applications")
    get_borrower_or_404(borrower_id)
    limit, offset = pagination_params()
    apps = [a for a in DB["applications"].values() if a["borrower_id"] == borrower_id]
    return ok_list([ser_application(a) for a in sorted_by_creation(apps)], limit, offset)


@app.route("/borrowers/<borrower_id>/loans", methods=["GET"])
def list_borrower_loans(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only list their own loans")
    get_borrower_or_404(borrower_id)
    limit, offset = pagination_params()
    loans = [l for l in DB["loans"].values() if l["borrower_id"] == borrower_id]
    return ok_list([ser_loan(l) for l in sorted_by_creation(loans)], limit, offset)


@app.route("/borrowers/<borrower_id>/impact-reports", methods=["GET"])
def list_borrower_impact_reports(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only list their own impact reports")
    get_borrower_or_404(borrower_id)
    limit, offset = pagination_params()
    reports = [
        r for r in DB["impact_reports"].values() if r["borrower_id"] == borrower_id
    ]
    return ok_list(
        [ser_impact_report(r) for r in sorted_by_creation(reports)], limit, offset
    )


@app.route("/borrowers/<borrower_id>/payments", methods=["GET"])
def list_borrower_payments(borrower_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    if role == "Borrower" and user_id != borrower_id:
        raise err_forbidden("Borrowers may only list their own payments")
    get_borrower_or_404(borrower_id)
    limit, offset = pagination_params()
    payments = [
        p for p in DB["payments"].values() if p["borrower_id"] == borrower_id
    ]
    return ok_list(
        [ser_payment(p) for p in sorted_by_creation(payments)], limit, offset
    )


# ---------------------------------------------------------------------------
# Invite resolution (anonymous)
# ---------------------------------------------------------------------------


def _resolve_invite(token, target):
    invite = next(
        (i for i in DB["invites"].values() if i["invite_token"] == token), None
    )
    if invite is None:
        raise err_not_found("Invite not found")
    if invite["status"] != "SENT":
        raise ApiError(
            "ERR_INVITE_NOT_PENDING", 409, "Invite has already been resolved"
        )
    invite["status"] = target
    invite["responded_at"] = CLOCK.now()
    return invite


@app.route("/underwriting-invites/<token>/accept", methods=["POST"])
def accept_invite(token):
    return ok(ser_invite(_resolve_invite(token, "ACCEPTED")))


@app.route("/underwriting-invites/<token>/decline", methods=["POST"])
def decline_invite(token):
    return ok(ser_invite(_resolve_invite(token, "DECLINED")))


# ---------------------------------------------------------------------------
# Lenders
# ---------------------------------------------------------------------------


@app.route("/lenders", methods=["POST"])
def create_lender():
    data = body_json()
    display_name = req_str(data, "display_name")
    email = req_str(data, "email")
    if any(l["email"] == email for l in DB["lenders"].values()):
        raise ApiError("ERR_DUPLICATE", 409, "A lender with this email exists")
    now = CLOCK.now()
    lender = {
        "id": new_id(),
        "display_name": display_name,
        "email": email,
        "lending_balance_cents": 0,
        "total_deposited_cents": 0,
        "lifetime_lent_cents": 0,
        "lifetime_repaid_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["lenders"][lender["id"]] = lender
    return ok(ser_lender(lender), 201)


@app.route("/lenders/<lender_id>", methods=["GET"])
def get_lender(lender_id):
    role, user_id = caller()
    require_roles(role, {"Lender", "PlatformAdmin"})
    if role == "Lender" and user_id != lender_id:
        raise err_forbidden("Lenders may only view their own account")
    lender = get_lender_or_404(lender_id)
    return ok(ser_lender(lender))


@app.route("/lenders/<lender_id>/deposits", methods=["POST"])
def deposit(lender_id):
    role, user_id = caller()
    require_roles(role, {"Lender", "PlatformAdmin"})
    if role == "Lender" and user_id != lender_id:
        raise err_forbidden("Lenders may only deposit into their own account")
    lender = get_lender_or_404(lender_id)
    data = body_json()
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be positive")
    lender["lending_balance_cents"] += amount
    lender["total_deposited_cents"] += amount
    touch(lender)
    return ok(ser_lender(lender), 201)


@app.route("/lenders/<lender_id>/endorsements", methods=["GET"])
def list_lender_endorsements(lender_id):
    role, user_id = caller()
    require_roles(role, {"Lender", "PlatformAdmin"})
    if role == "Lender" and user_id != lender_id:
        raise err_forbidden("Lenders may only list their own endorsements")
    get_lender_or_404(lender_id)
    limit, offset = pagination_params()
    records = [
        e
        for e in DB["endorsements"].values()
        if not e["is_trustee_endorsement"] and e["lender_id"] == lender_id
    ]
    return ok_list(
        [ser_endorsement(e) for e in sorted_by_creation(records)], limit, offset
    )


@app.route("/lenders/<lender_id>/contributions", methods=["GET"])
def list_lender_contributions(lender_id):
    role, user_id = caller()
    require_roles(role, {"Lender", "PlatformAdmin"})
    if role == "Lender" and user_id != lender_id:
        raise err_forbidden("Lenders may only list their own contributions")
    get_lender_or_404(lender_id)
    limit, offset = pagination_params()
    records = [
        c for c in DB["contributions"].values() if c["lender_id"] == lender_id
    ]
    return ok_list(
        [ser_contribution(c) for c in sorted_by_creation(records)], limit, offset
    )


@app.route("/lenders/<lender_id>/impact", methods=["GET"])
def lender_impact(lender_id):
    role, user_id = caller()
    require_roles(role, {"Lender", "PlatformAdmin"})
    if role == "Lender" and user_id != lender_id:
        raise err_forbidden("Lenders may only view their own impact")
    get_lender_or_404(lender_id)

    # Applications this lender helped fund (converted endorsement/contribution).
    app_ids = set()
    for e in DB["endorsements"].values():
        if (
            not e["is_trustee_endorsement"]
            and e["lender_id"] == lender_id
            and e["status"] == "CONVERTED"
        ):
            app_ids.add(e["loan_application_id"])
    for c in DB["contributions"].values():
        if c["lender_id"] == lender_id and c["status"] == "CONVERTED":
            app_ids.add(c["loan_application_id"])

    loan_by_app = {l["loan_application_id"]: l for l in DB["loans"].values()}
    loans = [loan_by_app[a] for a in app_ids if a in loan_by_app]
    loan_ids = {l["id"] for l in loans}

    candidates = [
        r for r in DB["impact_reports"].values() if r["loan_id"] in loan_ids
    ]
    report_count = len(candidates)
    if report_count == 0:
        return ok(
            {
                "report_count": 0,
                "jobs_created_weighted": 0,
                "revenue_change_pct_weighted": 0,
            }
        )

    if all(r["is_mid_term"] for r in candidates):
        # Simple unweighted mean, rounded half-up.
        jobs = round_half_up_int(
            sum(r["jobs_created"] for r in candidates), report_count
        )
        revenue = round_half_up_int(
            sum(r["revenue_change_pct"] for r in candidates), report_count
        )
    else:
        loan_map = {l["id"]: l for l in loans}

        def weight(report):
            loan = loan_map[report["loan_id"]]
            total = 0
            for e in DB["endorsements"].values():
                if (
                    not e["is_trustee_endorsement"]
                    and e["lender_id"] == lender_id
                    and e["status"] == "CONVERTED"
                    and e["loan_application_id"] == loan["loan_application_id"]
                ):
                    total += e["amount_cents"]
            for c in DB["contributions"].values():
                if (
                    c["lender_id"] == lender_id
                    and c["status"] == "CONVERTED"
                    and c["loan_application_id"] == loan["loan_application_id"]
                ):
                    total += c["amount_cents"]
            return total

        weights = [weight(r) for r in candidates]
        total_weight = sum(weights)
        # Principal-share weighted means, rounded half-up.
        jobs = round_half_up_int(
            sum(w * r["jobs_created"] for w, r in zip(weights, candidates)),
            total_weight,
        )
        revenue = round_half_up_int(
            sum(w * r["revenue_change_pct"] for w, r in zip(weights, candidates)),
            total_weight,
        )
    return ok(
        {
            "report_count": report_count,
            "jobs_created_weighted": jobs,
            "revenue_change_pct_weighted": revenue,
        }
    )


# ---------------------------------------------------------------------------
# Trustees
# ---------------------------------------------------------------------------


@app.route("/trustees", methods=["POST"])
def create_trustee():
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    data = body_json()
    org_name = req_str(data, "org_name")
    limit = req_int(data, "endorsement_limit_cents")
    if limit < 0:
        raise err_invalid_request("endorsement_limit_cents must be >= 0")
    now = CLOCK.now()
    trustee = {
        "id": new_id(),
        "org_name": org_name,
        "endorsement_limit_cents": limit,
        "status": "ACTIVE",
        "suspension_reason": "NONE",
        "active_endorsement_exposure_cents": 0,
        "endorsed_terminal_count": 0,
        "endorsed_defaulted_count": 0,
        "default_rate_bps": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["trustees"][trustee["id"]] = trustee
    return ok(ser_trustee(trustee), 201)


@app.route("/trustees/<trustee_id>", methods=["GET"])
def get_trustee(trustee_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin", "Trustee", "Borrower"})
    trustee = get_trustee_or_404(trustee_id)
    return ok(ser_trustee(trustee))


@app.route("/trustees/<trustee_id>/suspend", methods=["POST"])
def suspend_trustee(trustee_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    trustee = get_trustee_or_404(trustee_id)
    if trustee["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE trustee can be suspended")
    trustee["status"] = "SUSPENDED"
    trustee["suspension_reason"] = "MANUAL"
    touch(trustee)
    return ok(ser_trustee(trustee))


@app.route("/trustees/<trustee_id>/reinstate", methods=["POST"])
def reinstate_trustee(trustee_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    trustee = get_trustee_or_404(trustee_id)
    if trustee["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED trustee can be reinstated")
    trustee["status"] = "ACTIVE"
    trustee["suspension_reason"] = "NONE"
    touch(trustee)
    return ok(ser_trustee(trustee))


@app.route("/trustees/<trustee_id>/endorsements", methods=["POST"])
def trustee_endorse(trustee_id):
    role, user_id = caller()
    require_roles(role, {"Trustee"})
    if user_id != trustee_id:
        raise err_forbidden("A trustee may only endorse as itself")
    trustee = get_trustee_or_404(trustee_id)
    data = body_json()
    app_id = data.get("loan_application_id")
    if not isinstance(app_id, str):
        raise err_invalid_request("loan_application_id is required")
    app_rec = get_app_or_404(app_id)
    if app_rec["status"] != "PRIVATE_FUNDRAISING":
        raise err_invalid_state(
            "Trustee endorsements require PRIVATE_FUNDRAISING status"
        )
    amount = req_int(data, "amount_cents")
    if amount < 2500:
        raise ApiError(
            "ERR_MIN_CONTRIBUTION", 422, "Endorsement amount must be >= 2500 cents"
        )
    if trustee["status"] != "ACTIVE":
        raise ApiError("ERR_TRUSTEE_SUSPENDED", 409, "Trustee is suspended")
    if trustee["active_endorsement_exposure_cents"] + amount > trustee[
        "endorsement_limit_cents"
    ]:
        raise ApiError(
            "ERR_TRUSTEE_LIMIT_EXCEEDED",
            422,
            "Trustee endorsement cap would be exceeded",
        )
    now = CLOCK.now()
    endorsement = {
        "id": new_id(),
        "loan_application_id": app_rec["id"],
        "lender_id": None,
        "amount_cents": amount,
        "is_trustee_endorsement": True,
        "trustee_id": trustee["id"],
        "status": "ACTIVE",
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["endorsements"][endorsement["id"]] = endorsement
    recompute_exposure(trustee)
    touch(trustee)
    recompute_app_totals(app_rec)
    touch(app_rec)
    return ok(ser_endorsement(endorsement), 201)


@app.route("/trustees/<trustee_id>/endorsements", methods=["GET"])
def list_trustee_endorsements(trustee_id):
    role, user_id = caller()
    require_roles(role, {"Trustee", "PlatformAdmin"})
    if role == "Trustee" and user_id != trustee_id:
        raise err_forbidden("Trustees may only list their own endorsements")
    get_trustee_or_404(trustee_id)
    limit, offset = pagination_params()
    records = [
        e
        for e in DB["endorsements"].values()
        if e["is_trustee_endorsement"] and e["trustee_id"] == trustee_id
    ]
    return ok_list(
        [ser_endorsement(e) for e in sorted_by_creation(records)], limit, offset
    )


@app.route("/trustees/<trustee_id>/loan-applications", methods=["GET"])
def list_trustee_applications(trustee_id):
    role, user_id = caller()
    require_roles(role, {"Trustee", "PlatformAdmin"})
    if role == "Trustee" and user_id != trustee_id:
        raise err_forbidden("Trustees may only list their own applications")
    get_trustee_or_404(trustee_id)
    limit, offset = pagination_params()
    app_ids = {
        e["loan_application_id"]
        for e in DB["endorsements"].values()
        if e["is_trustee_endorsement"] and e["trustee_id"] == trustee_id
    }
    apps = [a for a in DB["applications"].values() if a["id"] in app_ids]
    return ok_list(
        [ser_application(a) for a in sorted_by_creation(apps)], limit, offset
    )


# ---------------------------------------------------------------------------
# Loan applications
# ---------------------------------------------------------------------------


@app.route("/loan-applications", methods=["POST"])
def create_application():
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    data = body_json()
    borrower_id = data.get("borrower_id")
    if not isinstance(borrower_id, str):
        raise err_invalid_request("borrower_id is required")
    if user_id != borrower_id:
        raise err_forbidden("Borrowers may only create applications for themselves")
    get_borrower_or_404(borrower_id)
    amount = req_int(data, "requested_amount_cents")
    if amount <= 0 or amount % 100 != 0:
        raise err_invalid_request(
            "requested_amount_cents must be a positive multiple of 100"
        )
    term = req_int(data, "term_months")
    if term < 3 or term > 36:
        raise err_invalid_request("term_months must be between 3 and 36")
    purpose = req_str(data, "business_purpose")
    now = CLOCK.now()
    app_rec = {
        "id": new_id(),
        "borrower_id": borrower_id,
        "trustee_id": None,
        "requested_amount_cents": amount,
        "term_months": term,
        "business_purpose": purpose,
        "endorsement_mode": None,
        "required_endorser_count": None,
        "distinct_endorser_count": 0,
        "private_total_cents": 0,
        "public_total_cents": 0,
        "funded_total_cents": 0,
        "status": "DRAFT",
        "review_notes": None,
        "private_started_at": None,
        "private_deadline": None,
        "public_started_at": None,
        "public_deadline": None,
        "funded_at": None,
        "terminal_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["applications"][app_rec["id"]] = app_rec
    return ok(ser_application(app_rec), 201)


@app.route("/loan-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    return ok(ser_application(app_rec))


@app.route("/loan-applications", methods=["GET"])
def list_applications():
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    limit, offset = pagination_params()
    apps = list(DB["applications"].values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        apps = [a for a in apps if a["status"] == status_filter]
    borrower_filter = request.args.get("borrower_id")
    if borrower_filter is not None:
        apps = [a for a in apps if a["borrower_id"] == borrower_filter]
    return ok_list(
        [ser_application(a) for a in sorted_by_creation(apps)], limit, offset
    )


@app.route("/loan-applications/<app_id>", methods=["PATCH"])
def update_application(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower", "PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    if role == "Borrower" and user_id != app_rec["borrower_id"]:
        raise err_forbidden("Borrowers may only edit their own applications")
    if app_rec["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT applications can be edited")
    data = body_json()
    if "requested_amount_cents" in data and data["requested_amount_cents"] is not None:
        amount = req_int(data, "requested_amount_cents")
        if amount <= 0 or amount % 100 != 0:
            raise err_invalid_request(
                "requested_amount_cents must be a positive multiple of 100"
            )
        app_rec["requested_amount_cents"] = amount
    if "term_months" in data and data["term_months"] is not None:
        term = req_int(data, "term_months")
        if term < 3 or term > 36:
            raise err_invalid_request("term_months must be between 3 and 36")
        app_rec["term_months"] = term
    if "business_purpose" in data and data["business_purpose"] is not None:
        app_rec["business_purpose"] = req_str(data, "business_purpose")
    touch(app_rec)
    return ok(ser_application(app_rec))


def _compute_score(borrower, trustee_vouched):
    tenure_component = 20 * min(borrower["business_tenure_months"], 24) / 24
    accepted = sum(
        1
        for i in DB["invites"].values()
        if i["borrower_id"] == borrower["id"] and i["status"] == "ACCEPTED"
    )
    community_component = 30 * min(accepted, 10) / 10
    trustee_component = 25 if trustee_vouched else 0
    if trustee_vouched:
        repayment_component = 0
    else:
        repayment_component = 25 * min(borrower["prior_repaid_loans_count"], 2) / 2
    total = (
        tenure_component
        + community_component
        + trustee_component
        + repayment_component
    )
    # round half up, clamp to [0, 100]
    score = int(total * 2 + 1) // 2
    return max(0, min(100, score))


@app.route("/loan-applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    app_rec = get_app_or_404(app_id)
    if user_id != app_rec["borrower_id"]:
        raise err_forbidden("Only the owning borrower may submit")
    data = body_json()
    trustee_id = data.get("trustee_id")
    if trustee_id is not None and not isinstance(trustee_id, str):
        raise err_invalid_request("trustee_id must be a string")
    trustee = None
    if trustee_id is not None:
        trustee = get_trustee_or_404(trustee_id)
    if app_rec["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT applications can be submitted")
    borrower = DB["borrowers"][app_rec["borrower_id"]]
    if borrower["status"] != "REGISTERED":
        raise ApiError(
            "ERR_BORROWER_RESTRICTED", 409, "Borrower is restricted from borrowing"
        )
    live = {
        "DRAFT",
        "IN_REVIEW",
        "APPROVED_PENDING_FUNDRAISE",
        "PRIVATE_FUNDRAISING",
        "PUBLIC_FUNDRAISING",
        "FUNDED",
    }
    if any(
        a["borrower_id"] == borrower["id"]
        and a["id"] != app_rec["id"]
        and a["status"] in live
        for a in DB["applications"].values()
    ):
        raise ApiError(
            "ERR_ACTIVE_APPLICATION_EXISTS",
            409,
            "Borrower already has a live application",
        )
    accepted = sum(
        1
        for i in DB["invites"].values()
        if i["borrower_id"] == borrower["id"] and i["status"] == "ACCEPTED"
    )
    required_accepts = max(3, app_rec["requested_amount_cents"] // 1_000_000)
    if accepted < required_accepts:
        raise ApiError(
            "ERR_UNDERWRITING_ACCEPTANCE_QUOTA",
            409,
            "Not enough accepted underwriting invites",
        )
    if trustee is not None:
        if trustee["status"] != "ACTIVE":
            raise ApiError("ERR_TRUSTEE_SUSPENDED", 409, "Trustee is suspended")
        if (
            app_rec["requested_amount_cents"]
            + trustee["active_endorsement_exposure_cents"]
            > trustee["endorsement_limit_cents"]
        ):
            raise ApiError(
                "ERR_TRUSTEE_LIMIT_EXCEEDED",
                422,
                "Trustee endorsement cap would be exceeded",
            )
    expected = data.get("expected_application_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_application_version is required")
    if expected != app_rec["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "Application version is stale"
        )
    app_rec["endorsement_mode"] = (
        "TRUSTEE_VOUCHED" if trustee is not None else "SELF_ENDORSED"
    )
    app_rec["required_endorser_count"] = 5 if trustee is not None else 15
    app_rec["trustee_id"] = trustee["id"] if trustee is not None else None
    app_rec["status"] = "IN_REVIEW"
    touch(app_rec)
    borrower["social_underwriting_score"] = _compute_score(
        borrower, trustee is not None
    )
    borrower["underwriting_variant"] = (
        "TRUSTEE_AUGMENTED" if trustee is not None else "STANDARD"
    )
    touch(borrower)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/approve", methods=["POST"])
def approve_application(app_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    if app_rec["status"] != "IN_REVIEW":
        raise err_invalid_state("Only IN_REVIEW applications can be approved")
    data = body_json()
    borrower = DB["borrowers"][app_rec["borrower_id"]]
    # Approval requires the borrower's social_underwriting_score to be at
    # least 60, in every endorsement mode.
    if borrower["social_underwriting_score"] < 60:
        raise ApiError(
            "ERR_SCORE_TOO_LOW", 409, "Social underwriting score is below 60"
        )
    notes = opt_str(data, "notes")
    app_rec["status"] = "APPROVED_PENDING_FUNDRAISE"
    if notes is not None:
        app_rec["review_notes"] = notes
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/reject", methods=["POST"])
def reject_application(app_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    if app_rec["status"] != "IN_REVIEW":
        raise err_invalid_state("Only IN_REVIEW applications can be rejected")
    data = body_json()
    notes = opt_str(data, "notes")
    app_rec["status"] = "REJECTED"
    app_rec["terminal_at"] = CLOCK.now()
    if notes is not None:
        app_rec["review_notes"] = notes
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/request-changes", methods=["POST"])
def request_changes(app_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    if app_rec["status"] != "IN_REVIEW":
        raise err_invalid_state("Only IN_REVIEW applications can be returned")
    data = body_json()
    notes = opt_str(data, "notes")
    app_rec["status"] = "DRAFT"
    if notes is not None:
        app_rec["review_notes"] = notes
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/open-private", methods=["POST"])
def open_private(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    app_rec = get_app_or_404(app_id)
    if user_id != app_rec["borrower_id"]:
        raise err_forbidden("Only the owning borrower may open fundraising")
    if app_rec["status"] != "APPROVED_PENDING_FUNDRAISE":
        raise err_invalid_state(
            "Only APPROVED_PENDING_FUNDRAISE applications can open private fundraising"
        )
    now = CLOCK.now()
    app_rec["status"] = "PRIVATE_FUNDRAISING"
    app_rec["private_started_at"] = now
    app_rec["private_deadline"] = now + timedelta(days=15)
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/open-public", methods=["POST"])
def open_public(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    app_rec = get_app_or_404(app_id)
    if user_id != app_rec["borrower_id"]:
        raise err_forbidden("Only the owning borrower may open the public campaign")
    if app_rec["status"] != "PRIVATE_FUNDRAISING":
        raise err_invalid_state(
            "Only PRIVATE_FUNDRAISING applications can open the public campaign"
        )
    if app_rec["distinct_endorser_count"] < app_rec["required_endorser_count"]:
        raise ApiError(
            "ERR_QUORUM_NOT_MET", 409, "Endorser quorum has not been met"
        )
    now = CLOCK.now()
    app_rec["status"] = "PUBLIC_FUNDRAISING"
    app_rec["public_started_at"] = now
    app_rec["public_deadline"] = now + timedelta(days=30)
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/withdraw", methods=["POST"])
def withdraw_application(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    app_rec = get_app_or_404(app_id)
    if user_id != app_rec["borrower_id"]:
        raise err_forbidden("Only the owning borrower may withdraw")
    allowed = {"DRAFT", "IN_REVIEW", "APPROVED_PENDING_FUNDRAISE", "PRIVATE_FUNDRAISING"}
    if app_rec["status"] not in allowed:
        raise err_invalid_state("Application cannot be withdrawn from this state")
    now = CLOCK.now()
    if app_rec["status"] == "PRIVATE_FUNDRAISING":
        for e in DB["endorsements"].values():
            if e["loan_application_id"] == app_rec["id"] and e["status"] == "ACTIVE":
                _refund_endorsement(e, now, "CANCELLED")
        recompute_app_totals(app_rec)
    app_rec["status"] = "WITHDRAWN"
    app_rec["terminal_at"] = now
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/cancel", methods=["POST"])
def cancel_application(app_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    app_rec = get_app_or_404(app_id)
    if user_id != app_rec["borrower_id"]:
        raise err_forbidden("Only the owning borrower may cancel")
    if app_rec["status"] != "FUNDED":
        raise err_invalid_state("Only FUNDED applications can be cancelled")
    if any(l["loan_application_id"] == app_rec["id"] for l in DB["loans"].values()):
        raise err_invalid_state("A loan already exists for this application")
    now = CLOCK.now()
    for e in DB["endorsements"].values():
        if e["loan_application_id"] == app_rec["id"] and e["status"] == "ACTIVE":
            _refund_endorsement(e, now, "REFUNDED")
    for c in DB["contributions"].values():
        if c["loan_application_id"] == app_rec["id"] and c["status"] == "ACTIVE":
            _refund_contribution(c, now)
    recompute_app_totals(app_rec)
    app_rec["status"] = "CANCELLED"
    app_rec["terminal_at"] = now
    touch(app_rec)
    return ok(ser_application(app_rec))


@app.route("/loan-applications/<app_id>/disburse", methods=["POST"])
def disburse_application(app_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    app_rec = get_app_or_404(app_id)
    if app_rec["status"] != "FUNDED":
        raise ApiError(
            "ERR_APPLICATION_NOT_FUNDED", 409, "Application is not FUNDED"
        )
    if any(l["loan_application_id"] == app_rec["id"] for l in DB["loans"].values()):
        raise err_invalid_state("A loan already exists for this application")
    data = body_json()
    expected = data.get("expected_application_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_application_version is required")
    if expected != app_rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Application version is stale")

    now = CLOCK.now()
    principal = app_rec["requested_amount_cents"]
    term = app_rec["term_months"]
    provisional_base = principal // term

    endorsements = [
        e
        for e in DB["endorsements"].values()
        if e["loan_application_id"] == app_rec["id"] and e["status"] == "ACTIVE"
    ]
    contributions = [
        c
        for c in DB["contributions"].values()
        if c["loan_application_id"] == app_rec["id"] and c["status"] == "ACTIVE"
    ]

    loan = {
        "id": new_id(),
        "loan_application_id": app_rec["id"],
        "borrower_id": app_rec["borrower_id"],
        "principal_cents": principal,
        "term_months": term,
        "disbursed_at": now,
        "status": "REPAYING",
        "schedule_status": "PROVISIONAL",
        "provisional_base_cents": provisional_base,
        "final_base_cents": None,
        "final_first_cents": None,
        "outstanding_cents": principal,
        "delinquent_since": None,
        "defaulted_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["loans"][loan["id"]] = loan

    for n in range(1, term + 1):
        if n < term:
            due_amount = provisional_base
        else:
            due_amount = principal - (term - 1) * provisional_base
        inst = {
            "id": new_id(),
            "loan_id": loan["id"],
            "installment_number": n,
            "due_date": add_months(now, n),
            "amount_due_cents": due_amount,
            "amount_paid_cents": 0,
            "remaining_cents": due_amount,
            "status": "PENDING",
            "paid_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": _next_seq(),
        }
        DB["installments"][inst["id"]] = inst

    lent_by_lender = {}
    for e in endorsements:
        e["status"] = "CONVERTED"
        e["resolved_at"] = now
        touch(e)
        if not e["is_trustee_endorsement"] and e["lender_id"]:
            lent_by_lender[e["lender_id"]] = (
                lent_by_lender.get(e["lender_id"], 0) + e["amount_cents"]
            )
    for c in contributions:
        c["status"] = "CONVERTED"
        c["resolved_at"] = now
        touch(c)
        lent_by_lender[c["lender_id"]] = (
            lent_by_lender.get(c["lender_id"], 0) + c["amount_cents"]
        )
    for lender_id, amount in lent_by_lender.items():
        lender = DB["lenders"].get(lender_id)
        if lender is not None:
            lender["lifetime_lent_cents"] += amount
            touch(lender)
    touch(app_rec)
    return ok(ser_loan(loan))


@app.route("/loan-applications/<app_id>/endorsements", methods=["GET"])
def list_app_endorsements(app_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_app_or_404(app_id)
    limit, offset = pagination_params()
    records = [
        e for e in DB["endorsements"].values() if e["loan_application_id"] == app_id
    ]
    return ok_list(
        [ser_endorsement(e) for e in sorted_by_creation(records)], limit, offset
    )


@app.route("/loan-applications/<app_id>/contributions", methods=["GET"])
def list_app_contributions(app_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_app_or_404(app_id)
    limit, offset = pagination_params()
    records = [
        c for c in DB["contributions"].values() if c["loan_application_id"] == app_id
    ]
    return ok_list(
        [ser_contribution(c) for c in sorted_by_creation(records)], limit, offset
    )


@app.route("/loan-applications/<app_id>/loan", methods=["GET"])
def get_app_loan(app_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_app_or_404(app_id)
    limit, offset = pagination_params()
    loans = [l for l in DB["loans"].values() if l["loan_application_id"] == app_id]
    return ok_list([ser_loan(l) for l in sorted_by_creation(loans)], limit, offset)


@app.route("/loan-applications/<app_id>/endorsements", methods=["POST"])
def create_endorsement(app_id):
    role, user_id = caller()
    require_roles(role, {"Lender"})
    app_rec = get_app_or_404(app_id)
    data = body_json()
    lender_id = data.get("lender_id")
    if not isinstance(lender_id, str):
        raise err_invalid_request("lender_id is required")
    lender = get_lender_or_404(lender_id)
    if user_id != lender_id:
        raise err_forbidden("Lenders may only endorse as themselves")
    if app_rec["status"] != "PRIVATE_FUNDRAISING":
        raise err_invalid_state(
            "Endorsements require PRIVATE_FUNDRAISING status"
        )
    amount = req_int(data, "amount_cents")
    if amount < 2500:
        raise ApiError(
            "ERR_MIN_CONTRIBUTION", 422, "Endorsement amount must be >= 2500 cents"
        )
    if any(
        e["loan_application_id"] == app_rec["id"]
        and not e["is_trustee_endorsement"]
        and e["lender_id"] == lender_id
        and e["status"] == "ACTIVE"
        for e in DB["endorsements"].values()
    ):
        raise ApiError(
            "ERR_DUPLICATE",
            409,
            "Lender already holds an ACTIVE endorsement on this application",
        )
    if lender["lending_balance_cents"] < amount:
        raise ApiError(
            "ERR_INSUFFICIENT_BALANCE", 422, "Lending balance is insufficient"
        )
    now = CLOCK.now()
    endorsement = {
        "id": new_id(),
        "loan_application_id": app_rec["id"],
        "lender_id": lender_id,
        "amount_cents": amount,
        "is_trustee_endorsement": False,
        "trustee_id": None,
        "status": "ACTIVE",
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["endorsements"][endorsement["id"]] = endorsement
    lender["lending_balance_cents"] -= amount
    touch(lender)
    recompute_app_totals(app_rec)
    touch(app_rec)
    return ok(ser_endorsement(endorsement), 201)


@app.route("/loan-applications/<app_id>/contributions", methods=["POST"])
def create_contribution(app_id):
    role, user_id = caller()
    require_roles(role, {"Lender"})
    app_rec = get_app_or_404(app_id)
    data = body_json()
    lender_id = data.get("lender_id")
    if not isinstance(lender_id, str):
        raise err_invalid_request("lender_id is required")
    lender = get_lender_or_404(lender_id)
    if user_id != lender_id:
        raise err_forbidden("Lenders may only contribute as themselves")
    if app_rec["status"] != "PUBLIC_FUNDRAISING":
        raise err_invalid_state(
            "Contributions require PUBLIC_FUNDRAISING status"
        )
    amount = req_int(data, "amount_cents")
    if amount < 2500:
        raise ApiError(
            "ERR_MIN_CONTRIBUTION", 422, "Contribution amount must be >= 2500 cents"
        )
    if lender["lending_balance_cents"] < amount:
        raise ApiError(
            "ERR_INSUFFICIENT_BALANCE", 422, "Lending balance is insufficient"
        )
    # Overfunding is impossible by construction: a contribution that would
    # push funded_total_cents above requested_amount_cents is rejected.
    funded_before = app_rec["funded_total_cents"]
    if funded_before + amount > app_rec["requested_amount_cents"]:
        raise ApiError(
            "ERR_OVERFUND", 422, "Contribution would overfund the application"
        )
    now = CLOCK.now()
    contribution = {
        "id": new_id(),
        "loan_application_id": app_rec["id"],
        "lender_id": lender_id,
        "amount_cents": amount,
        "status": "ACTIVE",
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["contributions"][contribution["id"]] = contribution
    lender["lending_balance_cents"] -= amount
    touch(lender)
    app_rec["public_total_cents"] += amount
    app_rec["funded_total_cents"] += amount
    if app_rec["funded_total_cents"] == app_rec["requested_amount_cents"]:
        app_rec["status"] = "FUNDED"
        app_rec["funded_at"] = now
    touch(app_rec)
    return ok(ser_contribution(contribution), 201)


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------


@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    loan = get_loan_or_404(loan_id)
    return ok(ser_loan(loan))


@app.route("/loans/<loan_id>/finalize-schedule", methods=["POST"])
def finalize_schedule(loan_id):
    role, _ = caller()
    require_roles(role, {"PlatformAdmin"})
    loan = get_loan_or_404(loan_id)
    data = body_json()
    expected = data.get("expected_loan_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_loan_version is required")
    if (
        loan["status"] != "REPAYING"
        or loan["schedule_status"] != "PROVISIONAL"
        or any(
            i["amount_paid_cents"] != 0
            for i in DB["installments"].values()
            if i["loan_id"] == loan["id"]
        )
    ):
        raise ApiError(
            "ERR_SCHEDULE_ALREADY_FINAL",
            409,
            "Schedule can only be finalized once, before any payment, while REPAYING",
        )
    if expected != loan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Loan version is stale")
    principal = loan["principal_cents"]
    term = loan["term_months"]
    final_base = (principal - 100) // term
    final_first = principal - (term - 1) * final_base
    loan["final_base_cents"] = final_base
    loan["final_first_cents"] = final_first
    loan["schedule_status"] = "FINAL"
    for inst in _loan_installments(loan["id"]):
        inst["amount_due_cents"] = (
            final_first if inst["installment_number"] == 1 else final_base
        )
        inst["remaining_cents"] = max(
            0, inst["amount_due_cents"] - inst["amount_paid_cents"]
        )
        touch(inst)
    loan["outstanding_cents"] = sum(
        i["remaining_cents"]
        for i in DB["installments"].values()
        if i["loan_id"] == loan["id"]
    )
    touch(loan)
    return ok(ser_loan(loan))


@app.route("/loans/<loan_id>/payments", methods=["POST"])
def make_payment(loan_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    loan = get_loan_or_404(loan_id)
    if user_id != loan["borrower_id"]:
        raise err_forbidden("Only the owning borrower may repay this loan")
    if loan["status"] not in ("REPAYING", "DELINQUENT"):
        raise err_invalid_state("This loan no longer accepts payments")
    data = body_json()
    amount = req_int(data, "amount_cents")
    if amount < 100:
        raise err_invalid_request("Payment amount_cents must be at least 100")

    now = CLOCK.now()
    payment = {
        "id": new_id(),
        "loan_id": loan["id"],
        "borrower_id": loan["borrower_id"],
        "amount_cents": amount,
        "paid_at": now,
        "created_at": now,
        "_seq": _next_seq(),
    }
    DB["payments"][payment["id"]] = payment

    # Waterfall: oldest installment first, skip PAID.
    remaining_payment = amount
    installments = _loan_installments(loan["id"])
    for inst in installments:
        if inst["status"] == "PAID":
            continue
        apply_amt = min(remaining_payment, inst["remaining_cents"])
        if apply_amt <= 0:
            continue
        inst["amount_paid_cents"] += apply_amt
        inst["remaining_cents"] -= apply_amt
        remaining_payment -= apply_amt
        if inst["remaining_cents"] == 0:
            inst["status"] = "PAID"
            inst["paid_at"] = now
        else:
            inst["status"] = "PARTIAL"
        touch(inst)
    if remaining_payment > 0 and installments:
        last = installments[-1]
        last["amount_paid_cents"] += remaining_payment
        touch(last)

    loan["outstanding_cents"] = sum(
        i["remaining_cents"]
        for i in DB["installments"].values()
        if i["loan_id"] == loan["id"]
    )

    # Repayment distribution: pro-rata principal credit per lender.
    app_rec = DB["applications"].get(loan["loan_application_id"])
    if app_rec is not None:
        conversions = []
        for e in DB["endorsements"].values():
            if (
                e["loan_application_id"] == app_rec["id"]
                and e["status"] == "CONVERTED"
                and not e["is_trustee_endorsement"]
                and e["lender_id"]
            ):
                conversions.append(e)
        for c in DB["contributions"].values():
            if (
                c["loan_application_id"] == app_rec["id"]
                and c["status"] == "CONVERTED"
            ):
                conversions.append(c)
        lent = {}
        first_conv = {}
        for conv in conversions:
            lid = conv["lender_id"]
            lent[lid] = lent.get(lid, 0) + conv["amount_cents"]
            key = (conv["created_at"], conv["_seq"])
            if lid not in first_conv or key < first_conv[lid]:
                first_conv[lid] = key
        ordered = sorted(
            lent.keys(),
            key=lambda lid: (
                first_conv[lid],
                DB["lenders"][lid]["display_name"] if lid in DB["lenders"] else "",
            ),
        )
        total_lent = loan["principal_cents"]
        for lid in ordered:
            share = (amount * lent[lid]) // total_lent
            if share > 0:
                lender = DB["lenders"].get(lid)
                if lender is not None:
                    lender["lending_balance_cents"] += share
                    lender["lifetime_repaid_cents"] += share
                    touch(lender)

    # Automatic loan transitions.
    if loan["outstanding_cents"] == 0:
        was_terminal = loan["status"] in ("PAID_OFF", "DEFAULTED")
        if not was_terminal:
            loan["status"] = "PAID_OFF"
            loan["delinquent_since"] = None
            borrower = DB["borrowers"].get(loan["borrower_id"])
            if borrower is not None:
                borrower["completed_loan_count"] += 1
                touch(borrower)
            if app_rec is not None and app_rec.get("trustee_id"):
                trustee = DB["trustees"].get(app_rec["trustee_id"])
                if trustee is not None:
                    trustee["endorsed_terminal_count"] += 1
                    _recompute_trustee_default_rate(trustee)
                    touch(trustee)
    elif loan["status"] == "DELINQUENT":
        now2 = CLOCK.current()
        overdue = False
        for inst in _loan_installments(loan["id"]):
            if inst["status"] != "PAID" and inst["due_date"] < now2 - timedelta(
                days=14
            ):
                overdue = True
                break
        if not overdue:
            loan["status"] = "REPAYING"
            loan["delinquent_since"] = None
    touch(loan)
    return ok(ser_payment(payment), 201)


@app.route("/loans/<loan_id>/installments", methods=["GET"])
def list_loan_installments(loan_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_loan_or_404(loan_id)
    limit, offset = pagination_params()
    records = _loan_installments(loan_id)
    return ok_list([ser_installment(i) for i in records], limit, offset)


@app.route("/loans/<loan_id>/payments", methods=["GET"])
def list_loan_payments(loan_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_loan_or_404(loan_id)
    limit, offset = pagination_params()
    records = [p for p in DB["payments"].values() if p["loan_id"] == loan_id]
    return ok_list([ser_payment(p) for p in sorted_by_creation(records)], limit, offset)


@app.route("/loans/<loan_id>/impact-reports", methods=["GET"])
def list_loan_impact_reports(loan_id):
    role, _ = caller()
    require_roles(role, {"Borrower", "Lender", "Trustee", "PlatformAdmin"})
    get_loan_or_404(loan_id)
    limit, offset = pagination_params()
    records = [r for r in DB["impact_reports"].values() if r["loan_id"] == loan_id]
    return ok_list(
        [ser_impact_report(r) for r in sorted_by_creation(records)], limit, offset
    )


@app.route("/loans/<loan_id>/impact-reports", methods=["POST"])
def create_impact_report(loan_id):
    role, user_id = caller()
    require_roles(role, {"Borrower"})
    loan = get_loan_or_404(loan_id)
    if user_id != loan["borrower_id"]:
        raise err_forbidden("Only the owning borrower may file impact reports")
    data = body_json()
    months = req_int(data, "months_after_disbursement")
    revenue = req_int(data, "revenue_change_pct")
    jobs = req_int(data, "jobs_created")
    narrative = req_str(data, "narrative")
    if months < 0:
        raise err_invalid_request("months_after_disbursement must be >= 0")
    if revenue < -100 or revenue > 1000:
        raise err_invalid_request("revenue_change_pct must be between -100 and 1000")
    if jobs < 0 or jobs > 100:
        raise err_invalid_request("jobs_created must be between 0 and 100")
    elapsed = whole_months_between(loan["disbursed_at"], CLOCK.current())
    if months != elapsed:
        raise ApiError(
            "ERR_TIMING_MISMATCH",
            409,
            "months_after_disbursement does not match elapsed whole months",
        )
    now = CLOCK.now()
    report = {
        "id": new_id(),
        "loan_id": loan["id"],
        "borrower_id": loan["borrower_id"],
        "months_after_disbursement": months,
        "revenue_change_pct": revenue,
        "jobs_created": jobs,
        "narrative": narrative,
        "is_mid_term": months <= loan["term_months"] // 2,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    DB["impact_reports"][report["id"]] = report
    return ok(ser_impact_report(report), 201)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
