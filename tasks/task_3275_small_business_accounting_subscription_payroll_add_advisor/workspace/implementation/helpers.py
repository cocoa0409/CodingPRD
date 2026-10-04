"""Shared helpers: validation utilities, enum checks, pagination, serialization."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import request
import db
from errors import ApiError, invalid_request, not_found, invalid_enum


def round_half_up_int(value):
    """Round a Decimal / numeric to the nearest integer cents, half-up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def body_json():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Body must be a JSON object")
    return data


def req_str(data, name):
    v = data.get(name)
    if v is None:
        raise invalid_request(f"Missing required field: {name}")
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"Field {name} must be a non-empty string")
    return v


def req_int(data, name):
    v = data.get(name)
    if v is None:
        raise invalid_request(f"Missing required field: {name}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def opt_bool(data, name, default=None):
    if name not in data or data.get(name) is None:
        return default
    v = data.get(name)
    if not isinstance(v, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return v


def req_number(data, name):
    v = data.get(name)
    if v is None:
        raise invalid_request(f"Missing required field: {name}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {name} must be a number")
    return v


def enum_check(value, allowed, field):
    if value not in allowed:
        raise invalid_enum(field, value)
    return value


def get_or_404(table, entity_id):
    rec = db.TABLES[table].get(entity_id)
    if rec is None:
        not_found(f"{table} {entity_id} not found")
    return rec


def paginate(items):
    """Apply limit/offset query params; returns (page_items, limit, offset, total)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda r: r.get("created_at") or "")


def filter_items(items, filters):
    """filters: list of (query_param, record_field) — match query string values."""
    out = []
    args = request.args
    for it in items:
        ok = True
        for qparam, field in filters:
            v = args.get(qparam)
            if v is None:
                continue
            if str(it.get(field)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


def company_subscription(company_id):
    for s in db.TABLES["Subscription"].values():
        if s["company_id"] == company_id:
            return s
    return None


def subscription_plan(plan_id):
    return db.TABLES["SubscriptionPlan"].get(plan_id)


def company_payroll(company_id):
    """The (at most one non-terminal) payroll addon for the company's subscription."""
    sub = company_subscription(company_id)
    if sub is None:
        return None
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"]:
            return p
    return None


def company_of_user(user):
    return db.TABLES["ClientCompany"].get(user["company_id"])


def check_subscription_writable(company_id):
    """Mutating endpoints under /companies/{id}: lifecycle gate."""
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found for company")
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        raise ApiError("ERR_SUBSCRIPTION_NOT_WRITABLE", 400,
                       "Subscription not writable")


def company_not_read_only(company_id):
    c = db.TABLES["ClientCompany"].get(company_id)
    if c is None:
        not_found("Company not found")
    if c.get("company_status") == "READ_ONLY":
        raise ApiError("ERR_COMPANY_READ_ONLY", 400, "Company is READ_ONLY")


def iso_now_str():
    return db.fmt(db.now())


def parse_dt_field(data, name, required=True):
    v = data.get(name)
    if v is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field {name} must be an ISO 8601 string")
    dt = db.parse_iso(v)
    if dt is None:
        raise invalid_request(f"Field {name} is not a valid datetime")
    return dt
