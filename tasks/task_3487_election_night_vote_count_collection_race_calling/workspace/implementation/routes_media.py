"""Media customers, result deliveries, and monthly invoicing (PRD §3.8)."""
import re

from flask import Blueprint, request

from auth import require_roles, body
from envelope import ok_object, paginate
from errors import raise_err
from loaders import get_customer, get_contest, base_record, versioned_record
from serializers import customer_json, delivery_json, invoice_json
from services_delivery import invoice_aggregate
from store import db
from util import nonblank

bp = Blueprint("media", __name__)

CUSTOMER_ROLES = ("ElectionOpsAdmin", "MediaCustomer")
LICENSE_TIERS = ("BASIC", "STANDARD", "PREMIUM")
CONTENT_TYPES = ("VOTE_UPDATE", "CALL", "CALL_CREDIT")
DELIVERY_STATUSES = ("SENT", "STALE")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _own_customer_only(uid, role, customer_id):
    """Priority 3 ownership: a MediaCustomer may touch only their own path;
    a failed check surfaces as ERR_UNAUTHORIZED_ROLE. Runs before existence
    (priority 3 precedes priority 4)."""
    if role == "MediaCustomer" and uid != customer_id:
        raise_err(
            "ERR_UNAUTHORIZED_ROLE",
            "A media customer may only access their own resources",
        )


@bp.post("/media-customers")
def create_customer():
    require_roles("ElectionOpsAdmin")
    data = body()
    for f in ("customer_name", "license_tier", "licensed_states"):
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not nonblank(data["customer_name"]):
        raise_err("ERR_INVALID_REQUEST", "customer_name must be a non-blank string")
    if data["license_tier"] not in LICENSE_TIERS:
        raise_err("ERR_INVALID_REQUEST", "license_tier out of range")
    states = data["licensed_states"]
    if (not isinstance(states, list) or not states
            or any(not nonblank(s) for s in states)):
        raise_err("ERR_INVALID_REQUEST", "licensed_states must be a non-empty array")
    rec = versioned_record()
    rec.update({
        "customer_name": data["customer_name"],
        "license_tier": data["license_tier"],
        "licensed_states": list(states),
    })
    db["customers"][rec["id"]] = rec
    return ok_object(customer_json(rec), 201)


@bp.get("/media-customers/<rid>")
def read_customer(rid):
    uid, role = require_roles(*CUSTOMER_ROLES)
    _own_customer_only(uid, role, rid)
    return ok_object(customer_json(get_customer(rid)))


@bp.get("/media-customers/<rid>/deliveries")
def list_deliveries(rid):
    uid, role = require_roles(*CUSTOMER_ROLES)
    _own_customer_only(uid, role, rid)
    customer = get_customer(rid)
    content_type = request.args.get("content_type")
    status = request.args.get("status")
    if content_type is not None and content_type not in CONTENT_TYPES:
        raise_err("ERR_INVALID_REQUEST", "content_type filter out of range")
    if status is not None and status not in DELIVERY_STATUSES:
        raise_err("ERR_INVALID_REQUEST", "status filter out of range")
    # Priority 20: license gating — a BASIC customer's feed may not be
    # queried for CALL or CALL_CREDIT content.
    if customer["license_tier"] == "BASIC" and content_type in ("CALL", "CALL_CREDIT"):
        raise_err(
            "ERR_LICENSE_TIER_FORBIDS",
            "BASIC tier may not query CALL or CALL_CREDIT content",
        )
    rows = [d for d in db["deliveries"].values() if d["customer_id"] == customer["id"]]
    if content_type is not None:
        rows = [d for d in rows if d["content_type"] == content_type]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return paginate(rows, delivery_json)


@bp.get("/contests/<rid>/deliveries")
def list_deliveries_of_contest(rid):
    require_roles("ElectionOpsAdmin", "TabulationClerk")
    contest = get_contest(rid)
    rows = [d for d in db["deliveries"].values() if d["contest_id"] == contest["id"]]
    return paginate(rows, delivery_json)


@bp.post("/media-customers/<rid>/invoices")
def create_invoice(rid):
    uid, role = require_roles(*CUSTOMER_ROLES)
    _own_customer_only(uid, role, rid)
    customer = get_customer(rid)
    data = body()
    period = data.get("period")
    if period is None or not isinstance(period, str) or not PERIOD_RE.match(period.strip()):
        raise_err("ERR_INVALID_REQUEST", "period must be a billing month YYYY-MM")
    period = period.strip()
    # Priority 17: at most one invoice per (customer, period).
    for inv in db["invoices"].values():
        if inv["customer_id"] == customer["id"] and inv["period"] == period:
            raise_err(
                "ERR_DUPLICATE_INVOICE",
                "An invoice already exists for this customer and period",
            )
    count, total = invoice_aggregate(customer["id"], period)
    rec = base_record()
    rec.update({
        "customer_id": customer["id"],
        "period": period,
        "delivery_count": count,
        "total_fee_cents": total,
    })
    db["invoices"][rec["id"]] = rec
    return ok_object(invoice_json(rec), 201)


@bp.get("/media-customers/<rid>/invoices")
def list_invoices(rid):
    uid, role = require_roles(*CUSTOMER_ROLES)
    _own_customer_only(uid, role, rid)
    customer = get_customer(rid)
    rows = [i for i in db["invoices"].values() if i["customer_id"] == customer["id"]]
    return paginate(rows, invoice_json)
