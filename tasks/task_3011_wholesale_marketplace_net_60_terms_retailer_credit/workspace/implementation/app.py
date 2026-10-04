#!/usr/bin/env python3
"""Wholesale Marketplace Net-60 Terms & Retailer Credit API (task 3011).

In-memory Flask implementation of workspace/PRD.md + SCAFFOLD.yaml.
No seeding: the store starts empty on every boot; all state is built by
clients through the declared API surface.
"""

import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5) — starts at 2026-09-01T00:00:00Z, never wall clock
# ---------------------------------------------------------------------------
CLOCK = [datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)]


def now():
    return CLOCK[0]


def ts(dt):
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return base + f".{dt.microsecond // 1000:03d}Z"
    return base + "Z"


def parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        d = datetime.fromisoformat(txt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# In-memory store (starts empty; never seeded)
# ---------------------------------------------------------------------------
DB = {
    "retailers": {},
    "brands": {},
    "credit_accounts": {},
    "orders": {},
    "order_lines": {},
    "invoices": {},
    "payments": {},
    "return_auths": {},
    "return_lines": {},
    "payouts": {},
    "grants": {},
    "fraud_flags": {},
}
SEQ = [0]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ[0] += 1
    return SEQ[0]


def make_record(fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts(now())
    rec["_created_dt"] = now()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = ts(now())
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Errors & response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def meta_block():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts(now())}


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": meta_block(), "response_type": response_type, "data": data}
    if pagination:
        body["meta"].update(pagination)
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth (PRD §2.1; validations priority 1-3)
# ---------------------------------------------------------------------------
ROLES = ("Anonymous", "PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")


def auth_context():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        err("ERR_UNAUTHENTICATED", 401,
            "Missing or invalid X-User-Role / X-User-ID headers.")
    return role, uid


def require_roles(*allowed):
    role, uid = auth_context()
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint.")
    return role, uid


def forbid_mismatch(owner_id, uid):
    if owner_id != uid:
        err("ERR_FORBIDDEN", 403, "Caller does not own the target resource.")


# ---------------------------------------------------------------------------
# Body validation (validations priority 5)
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "int": is_int,
    "bool": lambda v: isinstance(v, bool),
    "num": is_num,
    "datetime": lambda v: parse_dt(v) is not None,
    "any": lambda v: True,
}


def get_body(schema):
    """schema: {field: (type_name, required)}. Returns validated dict."""
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    for key in raw:
        if key not in schema:
            err("ERR_INVALID_REQUEST", 400, f"Unknown field: {key}")
    out = {}
    for field, (tname, required) in schema.items():
        if field not in raw or raw[field] is None:
            if required:
                err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
            out[field] = None
            continue
        val = raw[field]
        if not TYPE_CHECKS[tname](val):
            err("ERR_INVALID_REQUEST", 400, f"Malformed value for field: {field}")
        out[field] = val
    return out


def ignore_body():
    request.get_json(silent=True)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    total = len(items)
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Invalid limit parameter.")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Invalid offset parameter.")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def sorted_items(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(items, filters=None, args=None):
    if filters and args:
        for key, field in filters.items():
            val = args.get(key)
            if val is not None:
                items = [r for r in items if str(r.get(field)) == val]
    items = sorted_items(items)
    page, pagination = paginate(items)
    return ok([public(r) for r in page], 200, "array", pagination)


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lazy time evaluation (PRD §2.5)
# ---------------------------------------------------------------------------
def lazy_invoice(inv):
    """OPEN -> OVERDUE once logical now > due_date with balance remaining."""
    if inv["status"] == "OPEN" and now() > inv["_due_dt"] and inv["balance_cents"] > 0:
        inv["status"] = "OVERDUE"
        touch(inv)


def lazy_grant(grant):
    """ACTIVE -> EXPIRED once logical now >= ends_at."""
    if grant["status"] == "ACTIVE" and now() >= grant["_ends_dt"]:
        grant["status"] = "EXPIRED"
        touch(grant)


# ---------------------------------------------------------------------------
# Lookups & derived helpers
# ---------------------------------------------------------------------------
def get_or_404(store, ident, label):
    rec = DB[store].get(ident)
    if rec is None:
        err("ERR_NOT_FOUND", 404, f"{label} not found.")
    return rec


def invoices_of_retailer(retailer_id):
    out = []
    for inv in DB["invoices"].values():
        order = DB["orders"].get(inv["order_id"])
        if order and order["retailer_id"] == retailer_id:
            lazy_invoice(inv)
            out.append(inv)
    out.sort(key=lambda i: (i["created_at"], i["_due_dt"], i["_seq"]))
    return out


def account_of_retailer(retailer_id):
    for ca in DB["credit_accounts"].values():
        if ca["retailer_id"] == retailer_id:
            return ca
    return None


def compute_available(retailer_id, limit_cents):
    outstanding = sum(inv["balance_cents"]
                      for inv in invoices_of_retailer(retailer_id)
                      if inv["status"] in ("OPEN", "OVERDUE"))
    return limit_cents - outstanding


def sync_account_available(retailer_id):
    ca = account_of_retailer(retailer_id)
    if ca is not None:
        ca["available_cents"] = compute_available(retailer_id, ca["limit_cents"])
        # Derived fields changed; advance the account version so OCC-guarded
        # limit reviews observe the new posture (PRD §2.8).
        touch(ca)


def underwriting(retailer):
    """credit_limit_underwriting (calculations §3.3). Returns (limit, risk_tier)."""
    base = {"BRICK_AND_MORTAR": 250000, "ONLINE": 150000, "HYBRID": 200000}[
        retailer["store_type"]]
    paid_on_time = 0
    late_or_wo = 0
    for inv in invoices_of_retailer(retailer["id"]):
        if inv["status"] == "WRITTEN_OFF":
            late_or_wo += 1
        elif inv["status"] == "PAID":
            settle = inv.get("_settled_at")
            if settle is not None and settle <= inv["_due_dt"]:
                paid_on_time += 1
            else:
                late_or_wo += 1
    limit = base + paid_on_time * 50000 - late_or_wo * 100000
    limit = max(50000, min(1000000, limit))
    if limit <= 100000:
        tier = "HIGH"
    elif limit <= 400000:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return limit, tier


def recompute_risk_tier(retailer):
    limit, tier = underwriting(retailer)
    retailer["risk_tier"] = tier
    return limit, tier


def recompute_return_rate(retailer):
    """return_rate (calculations): received returned units / net sold units."""
    returned_units = 0
    for ra in DB["return_auths"].values():
        if ra["status"] != "RECEIVED":
            continue
        order = DB["orders"].get(ra["order_id"])
        if not order or order["retailer_id"] != retailer["id"]:
            continue
        for rl in DB["return_lines"].values():
            if rl["return_auth_id"] == ra["id"]:
                returned_units += rl["qty"]
    net_sold = 0
    for ol in DB["order_lines"].values():
        order = DB["orders"].get(ol["order_id"])
        if order and order["retailer_id"] == retailer["id"] \
                and order["status"] != "CANCELLED":
            net_sold += ol["net_sold_qty"]
    if net_sold == 0:
        rate = Decimal("0")
    else:
        rate = (Decimal(returned_units) / Decimal(net_sold)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    retailer["return_rate"] = float(rate)
    return rate


def provisional_return_rate(retailer):
    return Decimal(str(retailer.get("return_rate", 0))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_int(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def has_open_fraud_flag(retailer_id):
    return any(f["retailer_id"] == retailer_id and f["status"] == "OPEN"
               for f in DB["fraud_flags"].values())


# ---------------------------------------------------------------------------
# Clock endpoint (§4)
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body({"to_iso8601": ("datetime", True)})
    CLOCK[0] = parse_dt(body["to_iso8601"])
    return ok({"now_iso8601": ts(CLOCK[0])})


# ---------------------------------------------------------------------------
# Retailers
# ---------------------------------------------------------------------------
@app.post("/wholesale/retailers")
def create_retailer():
    require_roles("Anonymous")
    body = get_body({
        "legal_name": ("str", True),
        "store_type": ("str", True),
        "address": ("str", True),
        "lat": ("num", True),
        "lng": ("num", True),
        "storefront_proof_url": ("str", True),
        "resale_certificate_no": ("str", True),
        "referral_code": ("str", False),
    })
    if body["store_type"] not in ("BRICK_AND_MORTAR", "ONLINE", "HYBRID"):
        err("ERR_INVALID_REQUEST", 400, "Invalid store_type.")
    referred_brand_id = None
    if body.get("referral_code"):
        for b in DB["brands"].values():
            if b["referral_code"] == body["referral_code"]:
                referred_brand_id = b["id"]
                break
    rec = make_record({
        "legal_name": body["legal_name"],
        "store_type": body["store_type"],
        "address": body["address"],
        "lat": body["lat"],
        "lng": body["lng"],
        "storefront_proof_url": body["storefront_proof_url"],
        "resale_certificate_no": body["resale_certificate_no"],
        "storefront_proof_status": "PENDING",
        "resale_cert_status": "PENDING",
        "verification_status": "PENDING",
        "verification_resubmission_count": 0,
        "risk_tier": None,
        "return_rate": 0,
    })
    rec["_referred_brand_id"] = referred_brand_id
    DB["retailers"][rec["id"]] = rec
    return ok(public(rec), 201)


@app.get("/wholesale/retailers")
def list_retailers():
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    return list_response(
        list(DB["retailers"].values()),
        {"verification_status": "verification_status", "store_type": "store_type"},
        request.args)


@app.get("/wholesale/retailers/<rid>")
def get_retailer(rid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    rec = get_or_404("retailers", rid, "Retailer")
    return ok(public(rec))


@app.post("/wholesale/retailers/<rid>/documents/review")
def review_document(rid):
    require_roles("PlatformAdmin")
    rec = get_or_404("retailers", rid, "Retailer")
    body = get_body({"document_type": ("str", True), "decision": ("str", True)})
    doc = body["document_type"]
    if doc in ("storefront_proof", "STOREFRONT_PROOF"):
        field = "storefront_proof_status"
    elif doc in ("resale_certificate", "RESALE_CERTIFICATE",
                 "resale_cert", "RESALE_CERT"):
        field = "resale_cert_status"
    else:
        err("ERR_INVALID_REQUEST", 400, "Invalid document_type.")
    if body["decision"] in ("CONFIRM", "CONFIRMED"):
        rec[field] = "CONFIRMED"
    elif body["decision"] in ("REJECT", "REJECTED"):
        rec[field] = "REJECTED"
    else:
        err("ERR_INVALID_REQUEST", 400, "Invalid decision.")
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/retailers/<rid>/verify")
def verify_retailer(rid):
    require_roles("PlatformAdmin")
    rec = get_or_404("retailers", rid, "Retailer")
    body = get_body({"decision": ("str", True)})
    approve_values = ("APPROVE", "approve", "APPROVED")
    reject_values = ("REJECT", "reject", "REJECTED")
    if body["decision"] not in approve_values + reject_values:
        err("ERR_INVALID_REQUEST", 400, "Invalid decision.")
    if rec["verification_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "Retailer is not in PENDING verification status.")
    if body["decision"] in approve_values:
        if rec["storefront_proof_status"] != "CONFIRMED" \
                or rec["resale_cert_status"] != "CONFIRMED":
            err("ERR_VERIFICATION_INCOMPLETE", 422,
                "Both verification documents must be CONFIRMED before approval.")
        rec["verification_status"] = "VERIFIED"
    else:
        rec["verification_status"] = "REJECTED"
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/retailers/<rid>/request-more-info")
def request_more_info(rid):
    require_roles("PlatformAdmin")
    rec = get_or_404("retailers", rid, "Retailer")
    get_body({"reason": ("str", False)})
    if rec["verification_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "Retailer is not in PENDING verification status.")
    rec["verification_status"] = "MORE_INFO_REQUESTED"
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/retailers/<rid>/verification/resubmit")
def resubmit_verification(rid):
    role, uid = require_roles("Retailer")
    rec = get_or_404("retailers", rid, "Retailer")
    forbid_mismatch(rec["id"], uid)
    body = get_body({
        "storefront_proof_url": ("str", True),
        "resale_certificate_no": ("str", True),
    })
    if rec["verification_status"] != "MORE_INFO_REQUESTED":
        err("ERR_INVALID_STATE", 409,
            "Retailer is not in MORE_INFO_REQUESTED status.")
    if rec["verification_resubmission_count"] >= 3:
        err("ERR_RESUBMISSION_LIMIT", 422,
            "Resubmission limit of 3 has been reached.")
    rec["storefront_proof_url"] = body["storefront_proof_url"]
    rec["resale_certificate_no"] = body["resale_certificate_no"]
    rec["verification_status"] = "PENDING"
    rec["storefront_proof_status"] = "PENDING"
    rec["resale_cert_status"] = "PENDING"
    rec["verification_resubmission_count"] += 1
    touch(rec)
    return ok(public(rec))


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
@app.post("/wholesale/brands")
def create_brand():
    require_roles("Brand")
    body = get_body({
        "name": ("str", True),
        "contact_email": ("str", True),
        "min_order_value_cents": ("int", True),
        "default_case_pack_size": ("int", True),
        "lead_time_days": ("int", True),
        "payout_delay_days": ("int", True),
    })
    rec = make_record({
        "name": body["name"],
        "contact_email": body["contact_email"],
        "onboarding_status": "DRAFT",
        "min_order_value_cents": body["min_order_value_cents"],
        "default_case_pack_size": body["default_case_pack_size"],
        "lead_time_days": body["lead_time_days"],
        "payout_delay_days": body["payout_delay_days"],
        "referral_code": "REF-" + uuid.uuid4().hex[:12].upper(),
        "payout_balance_cents": 0,
        "abuse_flags": 0,
    })
    DB["brands"][rec["id"]] = rec
    return ok(public(rec), 201)


@app.get("/wholesale/brands")
def list_brands():
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    return list_response(list(DB["brands"].values()),
                         {"onboarding_status": "onboarding_status"},
                         request.args)


@app.get("/wholesale/brands/<bid>")
def get_brand(bid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    rec = get_or_404("brands", bid, "Brand")
    return ok(public(rec))


@app.post("/wholesale/brands/<bid>/activate")
def activate_brand(bid):
    role, uid = require_roles("Brand")
    rec = get_or_404("brands", bid, "Brand")
    forbid_mismatch(rec["id"], uid)
    ignore_body()
    if rec["onboarding_status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Brand is not in DRAFT.")
    if not (rec["min_order_value_cents"] > 0
            and rec["default_case_pack_size"] >= 1
            and rec["lead_time_days"] >= 0
            and rec["payout_delay_days"] >= 1):
        err("ERR_INVALID_REQUEST", 400, "Brand configuration is incomplete.")
    rec["onboarding_status"] = "ACTIVE"
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/brands/<bid>/reinstate")
def reinstate_brand(bid):
    require_roles("PlatformAdmin")
    rec = get_or_404("brands", bid, "Brand")
    ignore_body()
    if rec["onboarding_status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Brand is not SUSPENDED.")
    rec["onboarding_status"] = "ACTIVE"
    touch(rec)
    return ok(public(rec))


# ---------------------------------------------------------------------------
# Credit accounts
# ---------------------------------------------------------------------------
@app.post("/wholesale/credit-accounts")
def create_credit_account():
    require_roles("PlatformAdmin")
    body = get_body({"retailer_id": ("str", True)})
    retailer = get_or_404("retailers", body["retailer_id"], "Retailer")
    if retailer["verification_status"] != "VERIFIED":
        err("ERR_INVALID_STATE", 409, "Retailer is not VERIFIED.")
    if account_of_retailer(retailer["id"]) is not None:
        err("ERR_INVALID_STATE", 409, "Retailer already has a credit account.")
    limit, tier = underwriting(retailer)
    retailer["risk_tier"] = tier
    rec = make_record({
        "retailer_id": retailer["id"],
        "limit_cents": limit,
        "available_cents": limit,
        "status": "ACTIVE",
    })
    DB["credit_accounts"][rec["id"]] = rec
    return ok(public(rec), 201)


@app.get("/wholesale/credit-accounts")
def list_credit_accounts():
    require_roles("PlatformAdmin", "RiskAnalyst")
    return list_response(list(DB["credit_accounts"].values()),
                         {"retailer_id": "retailer_id", "status": "status"},
                         request.args)


@app.get("/wholesale/credit-accounts/<cid>")
def get_credit_account(cid):
    require_roles("PlatformAdmin", "RiskAnalyst")
    rec = get_or_404("credit_accounts", cid, "CreditAccount")
    return ok(public(rec))


@app.post("/wholesale/credit-accounts/<cid>/limit-review")
def limit_review(cid):
    require_roles("PlatformAdmin")
    rec = get_or_404("credit_accounts", cid, "CreditAccount")
    body = get_body({"expected_credit_account_version": ("int", True)})
    if body["expected_credit_account_version"] != rec["version"]:
        err("ERR_STALE_VERSION", 412,
            "Credit account version has advanced since the reviewer's snapshot.")
    retailer = get_or_404("retailers", rec["retailer_id"], "Retailer")
    limit, tier = underwriting(retailer)
    rec["limit_cents"] = limit
    rec["available_cents"] = compute_available(retailer["id"], limit)
    retailer["risk_tier"] = tier
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/credit-accounts/<cid>/unfreeze")
def unfreeze_account(cid):
    require_roles("PlatformAdmin")
    rec = get_or_404("credit_accounts", cid, "CreditAccount")
    ignore_body()
    if rec["status"] != "FROZEN":
        err("ERR_INVALID_STATE", 409, "Credit account is not FROZEN.")
    retailer = get_or_404("retailers", rec["retailer_id"], "Retailer")
    if retailer["verification_status"] != "VERIFIED":
        err("ERR_INVALID_STATE", 409, "Linked retailer is not VERIFIED.")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(public(rec))


@app.post("/wholesale/credit-accounts/<cid>/close")
def close_account(cid):
    require_roles("PlatformAdmin")
    rec = get_or_404("credit_accounts", cid, "CreditAccount")
    ignore_body()
    if rec["status"] != "FROZEN":
        err("ERR_INVALID_STATE", 409, "Credit account is not FROZEN.")
    for inv in invoices_of_retailer(rec["retailer_id"]):
        if inv["status"] == "OVERDUE":
            err("ERR_INVALID_STATE", 409,
                "Retailer has overdue invoices; account cannot be closed.")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(public(rec))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.post("/wholesale/orders")
def create_order():
    role, uid = require_roles("Retailer")
    body = get_body({
        "retailer_id": ("str", True),
        "brand_id": ("str", True),
        "lines": ("any", True),
    })
    retailer = get_or_404("retailers", body["retailer_id"], "Retailer")
    brand = get_or_404("brands", body["brand_id"], "Brand")
    forbid_mismatch(retailer["id"], uid)
    lines_in = body["lines"]
    if not isinstance(lines_in, list) or not lines_in:
        err("ERR_INVALID_REQUEST", 400, "lines must be a non-empty array.")
    clean_lines = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            err("ERR_INVALID_REQUEST", 400, "Each line must be an object.")
        for k in ln:
            if k not in ("sku", "unit_price_cents", "qty"):
                err("ERR_INVALID_REQUEST", 400, f"Unknown line field: {k}")
        if not isinstance(ln.get("sku"), str):
            err("ERR_INVALID_REQUEST", 400, "Line sku must be a string.")
        if not is_int(ln.get("unit_price_cents")) or ln["unit_price_cents"] < 0:
            err("ERR_INVALID_REQUEST", 400, "Line unit_price_cents must be a non-negative integer.")
        if not is_int(ln.get("qty")):
            err("ERR_INVALID_REQUEST", 400, "Line qty must be an integer.")
        clean_lines.append(ln)
    # business ladder: fraud gate -> case pack/brand -> territory -> min order -> credit
    if has_open_fraud_flag(retailer["id"]) \
            or retailer["verification_status"] != "VERIFIED":
        err("ERR_FRAUD_HOLD", 422,
            "Retailer has an open fraud flag or is not VERIFIED.")
    if brand["onboarding_status"] != "ACTIVE":
        err("ERR_CASE_PACK_VIOLATION", 422, "Brand is not ACTIVE.")
    for ln in clean_lines:
        if ln["qty"] <= 0 or ln["qty"] % brand["default_case_pack_size"] != 0:
            err("ERR_CASE_PACK_VIOLATION", 422,
                "Line qty must be a positive multiple of the brand's case pack size.")
    for g in DB["grants"].values():
        lazy_grant(g)
        if g["brand_id"] != brand["id"] or g["status"] != "ACTIVE":
            continue
        if not (g["_starts_dt"] <= now() < g["_ends_dt"]):
            continue
        if retailer["id"] == g["retailer_id"]:
            continue
        dist = haversine_km(g["center_lat"], g["center_lng"],
                            retailer["lat"], retailer["lng"])
        if dist < g["radius_km"]:
            err("ERR_TERRITORY_CONFLICT", 422,
                "An active exclusivity grant covers this retailer's territory.")
    subtotal = sum(ln["qty"] * ln["unit_price_cents"] for ln in clean_lines)
    if subtotal < brand["min_order_value_cents"]:
        err("ERR_MIN_ORDER_VALUE", 422,
            "Order subtotal is below the brand's minimum order value.")
    account = account_of_retailer(retailer["id"])
    if account is None or account["status"] != "ACTIVE" \
            or account["available_cents"] < subtotal:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 422,
            "Credit account is not ACTIVE or available credit is insufficient.")
    attribution = "BRAND_REFERRED" \
        if retailer.get("_referred_brand_id") == brand["id"] else "MARKETPLACE"
    pair_count = sum(1 for o in DB["orders"].values()
                     if o["retailer_id"] == retailer["id"]
                     and o["brand_id"] == brand["id"])
    order = make_record({
        "retailer_id": retailer["id"],
        "brand_id": brand["id"],
        "attribution": attribution,
        "order_seq": pair_count + 1,
        "subtotal_cents": subtotal,
        "status": "PLACED",
    })
    DB["orders"][order["id"]] = order
    for ln in clean_lines:
        ol = make_record({
            "order_id": order["id"],
            "sku": ln["sku"],
            "unit_price_cents": ln["unit_price_cents"],
            "qty": ln["qty"],
            "amount_cents": ln["qty"] * ln["unit_price_cents"],
            "net_sold_qty": ln["qty"],
        })
        DB["order_lines"][ol["id"]] = ol
    # Placement adds net-sold units, a unit-affecting mutation (PRD §3.6).
    recompute_return_rate(retailer)
    return ok(public(order), 201)


@app.get("/wholesale/orders")
def list_orders():
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    return list_response(list(DB["orders"].values()),
                         {"retailer_id": "retailer_id",
                          "brand_id": "brand_id", "status": "status"},
                         request.args)


@app.get("/wholesale/orders/<oid>")
def get_order(oid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    rec = get_or_404("orders", oid, "Order")
    return ok(public(rec))


@app.get("/wholesale/orders/<oid>/lines")
def list_order_lines(oid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    order = get_or_404("orders", oid, "Order")
    lines = [ol for ol in DB["order_lines"].values() if ol["order_id"] == order["id"]]
    return list_response(lines)


@app.get("/wholesale/orders/<oid>/invoice")
def get_order_invoice(oid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    order = get_or_404("orders", oid, "Order")
    invs = [inv for inv in DB["invoices"].values() if inv["order_id"] == order["id"]]
    for inv in invs:
        lazy_invoice(inv)
    return list_response(invs)


@app.get("/wholesale/orders/<oid>/return-authorizations")
def list_order_return_auths(oid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    order = get_or_404("orders", oid, "Order")
    ras = [ra for ra in DB["return_auths"].values() if ra["order_id"] == order["id"]]
    return list_response(ras)


@app.post("/wholesale/orders/<oid>/ship")
def ship_order(oid):
    role, uid = require_roles("Brand")
    order = get_or_404("orders", oid, "Order")
    forbid_mismatch(order["brand_id"], uid)
    ignore_body()
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "Order is not PLACED.")
    brand = get_or_404("brands", order["brand_id"], "Brand")
    if brand["onboarding_status"] != "ACTIVE":
        err("ERR_BRAND_SUSPENDED", 422, "Brand is not ACTIVE.")
    retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
    if retailer["verification_status"] != "VERIFIED":
        err("ERR_FRAUD_HOLD", 422, "Retailer is not VERIFIED.")
    if now() < order["_created_dt"] + timedelta(days=brand["lead_time_days"]):
        err("ERR_LEAD_TIME_NOT_MET", 422,
            "Brand lead time has not elapsed since order placement.")
    ship_now = now()
    order["status"] = "SHIPPED"
    touch(order)
    inv = make_record({
        "order_id": order["id"],
        "amount_due_cents": order["subtotal_cents"],
        "due_date": ts(ship_now + timedelta(days=60)),
        "paid_amount_cents": 0,
        "balance_cents": order["subtotal_cents"],
        "status": "OPEN",
    })
    inv["_due_dt"] = ship_now + timedelta(days=60)
    inv["_settled_at"] = None
    DB["invoices"][inv["id"]] = inv
    if order["attribution"] == "BRAND_REFERRED":
        bps = 0
    elif order["order_seq"] == 1:
        bps = 2500
    else:
        bps = 1500
    commission = round_half_up_int(
        Decimal(order["subtotal_cents"]) * Decimal(bps) / Decimal(10000))
    net = order["subtotal_cents"] - commission
    payout = make_record({
        "brand_id": brand["id"],
        "order_id": order["id"],
        "gross_cents": order["subtotal_cents"],
        "commission_bps": bps,
        "commission_cents": commission,
        "net_cents": net,
        "scheduled_date": ts(ship_now + timedelta(days=brand["payout_delay_days"])),
        "status": "SCHEDULED",
    })
    payout["_scheduled_dt"] = ship_now + timedelta(days=brand["payout_delay_days"])
    DB["payouts"][payout["id"]] = payout
    brand["payout_balance_cents"] += net
    touch(brand)
    sync_account_available(retailer["id"])
    return ok(public(order))


@app.post("/wholesale/orders/<oid>/deliver")
def deliver_order(oid):
    role, uid = require_roles("Brand")
    order = get_or_404("orders", oid, "Order")
    forbid_mismatch(order["brand_id"], uid)
    ignore_body()
    if order["status"] != "SHIPPED":
        err("ERR_INVALID_STATE", 409, "Order is not SHIPPED.")
    order["status"] = "DELIVERED"
    touch(order)
    return ok(public(order))


@app.post("/wholesale/orders/<oid>/cancel")
def cancel_order(oid):
    role, uid = require_roles("Retailer")
    order = get_or_404("orders", oid, "Order")
    forbid_mismatch(order["retailer_id"], uid)
    ignore_body()
    if order["status"] != "PLACED":
        err("ERR_INVALID_STATE", 409, "Order is not PLACED.")
    order["status"] = "CANCELLED"
    touch(order)
    # Cancellation removes the order's units from the return-rate denominator,
    # a unit-affecting mutation (PRD §3.6).
    retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
    recompute_return_rate(retailer)
    return ok(public(order))


# ---------------------------------------------------------------------------
# Invoices & payments
# ---------------------------------------------------------------------------
@app.get("/wholesale/invoices/<iid>")
def get_invoice(iid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    inv = get_or_404("invoices", iid, "Invoice")
    lazy_invoice(inv)
    return ok(public(inv))


@app.post("/wholesale/invoices/<iid>/payments")
def record_payment(iid):
    role, uid = require_roles("Retailer")
    inv = get_or_404("invoices", iid, "Invoice")
    lazy_invoice(inv)
    order = get_or_404("orders", inv["order_id"], "Order")
    forbid_mismatch(order["retailer_id"], uid)
    body = get_body({"amount_cents": ("int", True)})
    if inv["status"] not in ("OPEN", "OVERDUE"):
        err("ERR_INVALID_STATE", 409, "Invoice is not payable.")
    amount = body["amount_cents"]
    if amount <= 0 or amount > inv["balance_cents"]:
        err("ERR_OVERPAYMENT", 422,
            "Payment must be positive and not exceed the invoice balance.")
    pay = make_record({
        "invoice_id": inv["id"],
        "amount_cents": amount,
        "paid_at": ts(now()),
    }, with_version=False)
    DB["payments"][pay["id"]] = pay
    inv["paid_amount_cents"] += amount
    inv["balance_cents"] = inv["amount_due_cents"] - inv["paid_amount_cents"]
    if inv["balance_cents"] == 0:
        inv["status"] = "PAID"
        inv["_settled_at"] = now()
    touch(inv)
    sync_account_available(order["retailer_id"])
    return ok(public(pay), 201)


@app.get("/wholesale/invoices/<iid>/payments")
def list_invoice_payments(iid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    inv = get_or_404("invoices", iid, "Invoice")
    pays = [p for p in DB["payments"].values() if p["invoice_id"] == inv["id"]]
    return list_response(pays)


@app.post("/wholesale/invoices/<iid>/write-off")
def write_off_invoice(iid):
    require_roles("PlatformAdmin")
    inv = get_or_404("invoices", iid, "Invoice")
    lazy_invoice(inv)
    ignore_body()
    if inv["status"] != "OVERDUE":
        err("ERR_WRITE_OFF_TOO_EARLY", 422, "Invoice is not OVERDUE.")
    if now() < inv["_due_dt"] + timedelta(days=30):
        err("ERR_WRITE_OFF_TOO_EARLY", 422,
            "Write-off is allowed no earlier than 30 days past due.")
    inv["status"] = "WRITTEN_OFF"
    touch(inv)
    order = get_or_404("orders", inv["order_id"], "Order")
    retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
    sync_account_available(retailer["id"])
    recompute_risk_tier(retailer)
    return ok(public(inv))


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------
@app.post("/wholesale/return-authorizations")
def create_return_auth():
    role, uid = require_roles("Retailer")
    body = get_body({
        "order_id": ("str", True),
        "lines": ("any", True),
    })
    order = get_or_404("orders", body["order_id"], "Order")
    lines_in = body["lines"]
    if not isinstance(lines_in, list) or not lines_in:
        err("ERR_INVALID_REQUEST", 400, "lines must be a non-empty array.")
    clean = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            err("ERR_INVALID_REQUEST", 400, "Each line must be an object.")
        for k in ln:
            if k not in ("order_line_id", "qty"):
                err("ERR_INVALID_REQUEST", 400, f"Unknown line field: {k}")
        if not isinstance(ln.get("order_line_id"), str):
            err("ERR_INVALID_REQUEST", 400, "order_line_id must be a string.")
        if not is_int(ln.get("qty")) or ln["qty"] <= 0:
            err("ERR_INVALID_REQUEST", 400, "qty must be a positive integer.")
        ol = get_or_404("order_lines", ln["order_line_id"], "OrderLine")
        if ol["order_id"] != order["id"]:
            err("ERR_INVALID_REQUEST", 400,
                "order_line_id does not belong to the referenced order.")
        clean.append(ln)
    retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
    forbid_mismatch(retailer["id"], uid)
    if has_open_fraud_flag(retailer["id"]) \
            or retailer["verification_status"] != "VERIFIED":
        err("ERR_FRAUD_HOLD", 422,
            "Retailer has an open fraud flag or is not VERIFIED.")
    ra = make_record({
        "order_id": order["id"],
        "is_opening_order": order["order_seq"] == 1,
        "return_fee_cents": 0,
        "credit_cents": 0,
        "status": "REQUESTED",
    })
    DB["return_auths"][ra["id"]] = ra
    for ln in clean:
        rl = make_record({
            "return_auth_id": ra["id"],
            "order_line_id": ln["order_line_id"],
            "qty": ln["qty"],
        })
        DB["return_lines"][rl["id"]] = rl
    return ok(public(ra), 201)


@app.get("/wholesale/return-authorizations/<rid>")
def get_return_auth(rid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    ra = get_or_404("return_auths", rid, "ReturnAuthorization")
    return ok(public(ra))


@app.get("/wholesale/return-authorizations/<rid>/lines")
def list_return_auth_lines(rid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    ra = get_or_404("return_auths", rid, "ReturnAuthorization")
    lines = [rl for rl in DB["return_lines"].values()
             if rl["return_auth_id"] == ra["id"]]
    return list_response(lines)


@app.get("/wholesale/order-lines/<lid>")
def get_order_line(lid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    ol = get_or_404("order_lines", lid, "OrderLine")
    return ok(public(ol))


@app.get("/wholesale/order-lines/<lid>/return-lines")
def list_order_line_return_lines(lid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    ol = get_or_404("order_lines", lid, "OrderLine")
    lines = [rl for rl in DB["return_lines"].values()
             if rl["order_line_id"] == ol["id"]]
    return list_response(lines)


@app.post("/wholesale/return-authorizations/<rid>/review")
def review_return_auth(rid):
    role, uid = require_roles("Brand")
    ra = get_or_404("return_auths", rid, "ReturnAuthorization")
    body = get_body({"decision": ("str", True)})
    approve_values = ("APPROVE", "approve", "APPROVED")
    reject_values = ("REJECT", "reject", "REJECTED")
    if body["decision"] not in approve_values + reject_values:
        err("ERR_INVALID_REQUEST", 400, "Invalid decision.")
    order = get_or_404("orders", ra["order_id"], "Order")
    forbid_mismatch(order["brand_id"], uid)
    if ra["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Return authorization is not REQUESTED.")
    if body["decision"] in reject_values:
        ra["status"] = "REJECTED"
    else:
        if order["status"] not in ("DELIVERED", "PARTIALLY_RETURNED"):
            err("ERR_INVALID_STATE", 409,
                "Referenced order is not returnable in its current status.")
        retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
        recompute_return_rate(retailer)
        if provisional_return_rate(retailer) >= Decimal("0.20"):
            err("ERR_RETURN_ABUSE_GUARD", 422,
                "Retailer return rate is at or above the abuse threshold.")
        ra["status"] = "APPROVED"
    touch(ra)
    return ok(public(ra))


@app.post("/wholesale/return-authorizations/<rid>/receive")
def receive_return_auth(rid):
    require_roles("PlatformAdmin")
    ra = get_or_404("return_auths", rid, "ReturnAuthorization")
    ignore_body()
    if ra["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Return authorization is not APPROVED.")
    order = get_or_404("orders", ra["order_id"], "Order")
    if order["status"] not in ("DELIVERED", "PARTIALLY_RETURNED"):
        err("ERR_INVALID_STATE", 409,
            "Referenced order is not in a returnable status.")
    ra_lines = [rl for rl in DB["return_lines"].values()
                if rl["return_auth_id"] == ra["id"]]
    # atomic precondition: cumulative received qty per line must not exceed net_sold_qty
    for rl in ra_lines:
        ol = get_or_404("order_lines", rl["order_line_id"], "OrderLine")
        if rl["qty"] > ol["net_sold_qty"]:
            err("ERR_RETURN_QTY_EXCEEDED", 422,
                "Cumulative received returns would exceed the line's net_sold_qty.")
    # pinned evaluation order: merchandise -> fee (from merchandise) -> credit clamp
    merchandise = 0
    for rl in ra_lines:
        ol = DB["order_lines"][rl["order_line_id"]]
        merchandise += rl["qty"] * ol["unit_price_cents"]
    if ra["is_opening_order"]:
        fee = 0
    else:
        fee = round_half_up_int(Decimal(merchandise) * Decimal("0.15"))
    raw_credit = merchandise - fee
    invs = [inv for inv in DB["invoices"].values() if inv["order_id"] == order["id"]]
    inv = invs[0] if invs else None
    if inv is not None:
        lazy_invoice(inv)
        credit = min(max(raw_credit, 0), inv["amount_due_cents"])
    else:
        credit = max(raw_credit, 0)
    ra["return_fee_cents"] = fee
    ra["credit_cents"] = credit
    for rl in ra_lines:
        ol = DB["order_lines"][rl["order_line_id"]]
        ol["net_sold_qty"] -= rl["qty"]
        touch(ol)
    if inv is not None:
        inv["amount_due_cents"] = max(0, inv["amount_due_cents"] - credit)
        inv["balance_cents"] = inv["amount_due_cents"] - inv["paid_amount_cents"]
        if inv["balance_cents"] == 0 and inv["status"] in ("OPEN", "OVERDUE"):
            inv["status"] = "PAID"
            inv["_settled_at"] = now()
        touch(inv)
    order_lines = [ol for ol in DB["order_lines"].values()
                   if ol["order_id"] == order["id"]]
    if all(ol["net_sold_qty"] == 0 for ol in order_lines):
        order["status"] = "RETURNED"
    else:
        order["status"] = "PARTIALLY_RETURNED"
    touch(order)
    # mark RECEIVED before the final-variant recompute so this authorization's
    # units are included in the numerator
    ra["status"] = "RECEIVED"
    touch(ra)
    retailer = get_or_404("retailers", order["retailer_id"], "Retailer")
    recompute_return_rate(retailer)
    sync_account_available(retailer["id"])
    return ok(public(ra))


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------
@app.get("/wholesale/payouts")
def list_payouts():
    require_roles("PlatformAdmin", "RiskAnalyst", "Brand")
    return list_response(list(DB["payouts"].values()),
                         {"brand_id": "brand_id", "order_id": "order_id",
                          "status": "status"},
                         request.args)


@app.get("/wholesale/payouts/<pid>")
def get_payout(pid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Brand")
    rec = get_or_404("payouts", pid, "Payout")
    return ok(public(rec))


@app.post("/wholesale/payouts/process-due")
def process_due_payouts():
    require_roles("PlatformAdmin")
    ignore_body()
    due = [p for p in sorted_items(list(DB["payouts"].values()))
           if p["status"] == "SCHEDULED" and p["_scheduled_dt"] <= now()]
    processed = []
    for p in due:
        p["status"] = "PROCESSING"
        touch(p)
        brand = get_or_404("brands", p["brand_id"], "Brand")
        brand["payout_balance_cents"] -= p["net_cents"]
        touch(brand)
        processed.append(p)
    page, pagination = paginate(processed)
    return ok([public(p) for p in page], 200, "array", pagination)


@app.post("/wholesale/payouts/<pid>/complete")
def complete_payout(pid):
    require_roles("PlatformAdmin")
    p = get_or_404("payouts", pid, "Payout")
    ignore_body()
    if p["status"] != "PROCESSING":
        err("ERR_INVALID_STATE", 409, "Payout is not PROCESSING.")
    p["status"] = "PAID"
    touch(p)
    return ok(public(p))


@app.post("/wholesale/payouts/<pid>/fail")
def fail_payout(pid):
    require_roles("PlatformAdmin")
    p = get_or_404("payouts", pid, "Payout")
    ignore_body()
    if p["status"] != "PROCESSING":
        err("ERR_INVALID_STATE", 409, "Payout is not PROCESSING.")
    p["status"] = "SCHEDULED"
    touch(p)
    brand = get_or_404("brands", p["brand_id"], "Brand")
    brand["payout_balance_cents"] += p["net_cents"]
    touch(brand)
    return ok(public(p))


# ---------------------------------------------------------------------------
# Exclusivity grants
# ---------------------------------------------------------------------------
@app.post("/wholesale/exclusivity-grants")
def create_grant():
    role, uid = require_roles("Brand")
    body = get_body({
        "brand_id": ("str", True),
        "retailer_id": ("str", True),
        "center_lat": ("num", True),
        "center_lng": ("num", True),
        "radius_km": ("num", False),
        "starts_at": ("datetime", True),
        "ends_at": ("datetime", True),
        "expected_brand_version": ("int", True),
    })
    brand = get_or_404("brands", body["brand_id"], "Brand")
    retailer = get_or_404("retailers", body["retailer_id"], "Retailer")
    forbid_mismatch(brand["id"], uid)
    if body["expected_brand_version"] != brand["version"]:
        err("ERR_STALE_VERSION", 412,
            "Brand version has advanced since the client's snapshot.")
    starts = parse_dt(body["starts_at"])
    ends = parse_dt(body["ends_at"])
    if not ends > starts:
        err("ERR_GRANT_OVERLAP", 422, "ends_at must be after starts_at.")
    for g in DB["grants"].values():
        lazy_grant(g)
        if g["brand_id"] != brand["id"] or g["retailer_id"] != retailer["id"]:
            continue
        if g["status"] != "ACTIVE":
            continue
        if g["_starts_dt"] < ends and starts < g["_ends_dt"]:
            err("ERR_GRANT_OVERLAP", 422,
                "Grant overlaps an existing ACTIVE grant for this brand and retailer.")
    rec = make_record({
        "brand_id": brand["id"],
        "retailer_id": retailer["id"],
        "center_lat": body["center_lat"],
        "center_lng": body["center_lng"],
        "radius_km": body["radius_km"] if body.get("radius_km") is not None else 5,
        "starts_at": ts(starts),
        "ends_at": ts(ends),
        "status": "ACTIVE",
    })
    rec["_starts_dt"] = starts
    rec["_ends_dt"] = ends
    DB["grants"][rec["id"]] = rec
    touch(brand)
    return ok(public(rec), 201)


@app.get("/wholesale/exclusivity-grants")
def list_grants():
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    items = []
    for g in DB["grants"].values():
        lazy_grant(g)
        items.append(g)
    return list_response(items,
                         {"brand_id": "brand_id", "retailer_id": "retailer_id",
                          "status": "status"},
                         request.args)


@app.get("/wholesale/exclusivity-grants/<gid>")
def get_grant(gid):
    require_roles("PlatformAdmin", "RiskAnalyst", "Retailer", "Brand")
    rec = get_or_404("grants", gid, "ExclusivityGrant")
    lazy_grant(rec)
    return ok(public(rec))


@app.post("/wholesale/exclusivity-grants/<gid>/revoke")
def revoke_grant(gid):
    role, uid = require_roles("Brand")
    rec = get_or_404("grants", gid, "ExclusivityGrant")
    forbid_mismatch(rec["brand_id"], uid)
    ignore_body()
    lazy_grant(rec)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Grant is not ACTIVE.")
    rec["status"] = "REVOKED"
    touch(rec)
    return ok(public(rec))


# ---------------------------------------------------------------------------
# Fraud flags
# ---------------------------------------------------------------------------
@app.post("/wholesale/fraud-flags")
def create_fraud_flag():
    require_roles("RiskAnalyst")
    body = get_body({
        "retailer_id": ("str", True),
        "flag_type": ("str", True),
        "order_id": ("str", False),
    })
    retailer = get_or_404("retailers", body["retailer_id"], "Retailer")
    if body["flag_type"] not in ("STRAW_STOREFRONT", "CONSUMER_RESELLER", "RETURN_ABUSE"):
        err("ERR_INVALID_REQUEST", 400, "Invalid flag_type.")
    order_id = body.get("order_id") or ""
    if order_id:
        get_or_404("orders", order_id, "Order")
    rec = make_record({
        "retailer_id": retailer["id"],
        "order_id": order_id,
        "flag_type": body["flag_type"],
        "status": "OPEN",
    })
    DB["fraud_flags"][rec["id"]] = rec
    return ok(public(rec), 201)


@app.get("/wholesale/fraud-flags")
def list_fraud_flags():
    require_roles("PlatformAdmin", "RiskAnalyst")
    return list_response(list(DB["fraud_flags"].values()),
                         {"retailer_id": "retailer_id", "order_id": "order_id",
                          "status": "status"},
                         request.args)


@app.get("/wholesale/fraud-flags/<fid>")
def get_fraud_flag(fid):
    require_roles("PlatformAdmin", "RiskAnalyst")
    rec = get_or_404("fraud_flags", fid, "FraudFlag")
    return ok(public(rec))


def _issue_compensating_payout(order):
    brand = get_or_404("brands", order["brand_id"], "Brand")
    payout = make_record({
        "brand_id": brand["id"],
        "order_id": order["id"],
        "gross_cents": order["subtotal_cents"],
        "commission_bps": 0,
        "commission_cents": 0,
        "net_cents": order["subtotal_cents"],
        "scheduled_date": ts(now()),
        "status": "PAID",
    })
    payout["_scheduled_dt"] = now()
    DB["payouts"][payout["id"]] = payout
    brand["payout_balance_cents"] += payout["net_cents"]
    touch(brand)


@app.post("/wholesale/fraud-flags/<fid>/confirm")
def confirm_fraud_flag(fid):
    require_roles("PlatformAdmin")
    flag = get_or_404("fraud_flags", fid, "FraudFlag")
    ignore_body()
    if flag["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Fraud flag is not OPEN.")
    flag["status"] = "CONFIRMED"
    touch(flag)
    if flag["flag_type"] in ("STRAW_STOREFRONT", "CONSUMER_RESELLER"):
        retailer = get_or_404("retailers", flag["retailer_id"], "Retailer")
        if retailer["verification_status"] == "VERIFIED":
            retailer["verification_status"] = "SUSPENDED"
            touch(retailer)
        account = account_of_retailer(retailer["id"])
        if account is not None and account["status"] == "ACTIVE":
            account["status"] = "FROZEN"
            touch(account)
        for order in sorted_items(
                [o for o in DB["orders"].values()
                 if o["retailer_id"] == retailer["id"] and o["status"] == "PLACED"]):
            order["status"] = "CANCELLED"
            touch(order)
            _issue_compensating_payout(order)
        # Cancellations remove units from the return-rate denominator.
        recompute_return_rate(retailer)
    elif flag["flag_type"] == "RETURN_ABUSE":
        order = DB["orders"].get(flag.get("order_id") or "")
        if order is not None:
            brand = get_or_404("brands", order["brand_id"], "Brand")
            brand["abuse_flags"] += 1
            brand["payout_balance_cents"] -= 5000
            if brand["abuse_flags"] >= 5 and brand["onboarding_status"] == "ACTIVE":
                brand["onboarding_status"] = "SUSPENDED"
            touch(brand)
    return ok(public(flag))


@app.post("/wholesale/fraud-flags/<fid>/dismiss")
def dismiss_fraud_flag(fid):
    require_roles("PlatformAdmin")
    flag = get_or_404("fraud_flags", fid, "FraudFlag")
    ignore_body()
    if flag["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Fraud flag is not OPEN.")
    flag["status"] = "DISMISSED"
    touch(flag)
    return ok(public(flag))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
