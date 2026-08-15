"""Shared helpers: validation, serialization, exposure/availability/recompute logic."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone

import errors as E
from errors import ApiError

import clock
import db


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def mint_id() -> str:
    return str(uuid.uuid4())


def stamp_now() -> str:
    return clock.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def stamp_clock() -> str:
    """Format the current logical-clock instant for non-created_at/updated_at
    fields (sealed_at, opened_at, last_baked_at, last_shipped_at). PRD §2.8
    requires three fractional digits only for created_at/updated_at; other
    clock-stamped fields use a plain seconds-precision ISO form when the
    logical clock sits on a whole-second instant."""
    dt = clock.now()
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def parse_iso_datetime(value):
    """Parse an ISO-8601 datetime (with time) into an aware UTC datetime. None on failure."""
    if not isinstance(value, str):
        return None
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_iso_date(value):
    """Parse a strict YYYY-MM-DD date into a datetime.date. None on failure."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


_DATE_CODE_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def valid_date_code(value) -> bool:
    return isinstance(value, str) and bool(_DATE_CODE_RE.fullmatch(value))


def months_elapsed(date_code: str, now: datetime) -> int:
    """Whole calendar months between a YYYYMM date code and now."""
    dc_year = int(date_code[0:4])
    dc_month = int(date_code[4:6])
    return (now.year - dc_year) * 12 + (now.month - dc_month)


def whole_days_between(a: datetime, b: datetime) -> int:
    """Whole (floored) days from a to b."""
    delta = b - a
    return delta.days if delta.total_seconds() >= 0 else -((-delta.total_seconds()) // 86400) - 1


def whole_hours_between(a: datetime, b: datetime) -> int:
    """Whole (floored) hours from a to b (b >= a)."""
    return int((b - a).total_seconds() // 3600)


def get_json_body():
    """Return the request JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    from flask import request

    if not request.is_json:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Request body must be JSON.")
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing or invalid required field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Invalid field: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing or invalid required field: {field}")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Invalid field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing or invalid enum field: {field}")
    return v


def req_date(body, field):
    v = body.get(field)
    d = parse_iso_date(v)
    if d is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing or invalid date field: {field}")
    return d


def opt_positive_qty(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Field must be a positive integer: {field}")
    return v


def pagination_params():
    """Read limit/offset query params with scaffold defaults (limit 10, min 1, max 100)."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid limit parameter.")
        if limit < 1 or limit > 100:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid limit parameter.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid offset parameter.")
        if offset < 0:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid offset parameter.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def check_buyer_body_ownership(user_id, role, customer_id):
    if role == "CustomerBuyer" and customer_id != user_id:
        raise ApiError(
            E.ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "CustomerBuyer may only act on their own customer account's resources.",
        )


# ---------------------------------------------------------------------------
# entity lookups
# ---------------------------------------------------------------------------

def get_line_or_404(line_id):
    obj = db.manufacturer_lines.get(line_id)
    if obj is None:
        raise ApiError(E.ERR_MANUFACTURER_LINE_NOT_FOUND, 404, "Manufacturer line not found.")
    return obj


def get_part_or_404(part_id):
    obj = db.parts.get(part_id)
    if obj is None:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")
    return obj


def get_customer_or_404(customer_id):
    obj = db.customers.get(customer_id)
    if obj is None:
        raise ApiError(E.ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found.")
    return obj


def get_order_or_404(order_id):
    obj = db.orders.get(order_id)
    if obj is None:
        raise ApiError(E.ERR_ORDER_NOT_FOUND, 404, "Order not found.")
    return obj


def get_order_line_or_404(line_id):
    obj = db.order_lines.get(line_id)
    if obj is None:
        raise ApiError(E.ERR_ORDER_LINE_NOT_FOUND, 404, "Order line not found.")
    return obj


def get_lot_or_404(lot_id):
    obj = db.inventory_lots.get(lot_id)
    if obj is None:
        raise ApiError(E.ERR_LOT_NOT_FOUND, 404, "Lot not found.")
    return obj


def get_registration_or_404(registration_id):
    obj = db.design_registrations.get(registration_id)
    if obj is None:
        raise ApiError(E.ERR_REGISTRATION_NOT_FOUND, 404, "Design registration not found.")
    return obj


def get_claim_or_404(claim_id):
    obj = db.claims.get(claim_id)
    if obj is None:
        raise ApiError(E.ERR_CLAIM_NOT_FOUND, 404, "Claim not found.")
    return obj


def get_buyback_or_404(buyback_id):
    obj = db.buy_backs.get(buyback_id)
    if obj is None:
        raise ApiError(E.ERR_BUYBACK_NOT_FOUND, 404, "Buy-back request not found.")
    return obj


def get_allocation_run_or_404(run_id):
    obj = db.allocation_runs.get(run_id)
    if obj is None:
        raise ApiError(E.ERR_ALLOCATION_RUN_NOT_FOUND, 404, "Allocation run not found.")
    return obj


def get_alternate_or_404(approval_id):
    obj = db.alternate_approvals.get(approval_id)
    if obj is None:
        raise ApiError(E.ERR_ALTERNATE_APPROVAL_NOT_FOUND, 404, "Alternate part approval not found.")
    return obj


# ---------------------------------------------------------------------------
# computed/derived logic
# ---------------------------------------------------------------------------

def compute_msl_exposure_hours(lot) -> int:
    """Whole hours accrued over intervals after last_baked_at (null bake counts all)."""
    total = 0.0
    now = clock.now()
    for exp in db.moisture_exposures.values():
        if exp["lot_id"] != lot["id"]:
            continue
        opened_at = exp["_opened_at"]
        if lot["_last_baked_at"] is not None and opened_at <= lot["_last_baked_at"]:
            continue
        end = exp["_sealed_at"] if exp["_sealed_at"] is not None else now
        delta = (end - opened_at).total_seconds()
        if delta > 0:
            total += delta
    return int(total // 3600)


def available_supply(part_id) -> int:
    return sum(
        lot["qty_on_hand"]
        for lot in db.inventory_lots.values()
        if lot["part_id"] == part_id and lot["status"] == "AVAILABLE"
    )


def recompute_part_availability(part_id):
    part = db.parts.get(part_id)
    if part is None:
        return
    part["qty_on_hand"] = sum(
        lot["qty_on_hand"]
        for lot in db.inventory_lots.values()
        if lot["part_id"] == part_id and lot["status"] == "AVAILABLE"
    )
    part["qty_reserved"] = sum(
        lot["qty_reserved"]
        for lot in db.inventory_lots.values()
        if lot["part_id"] == part_id and lot["status"] == "AVAILABLE"
    )
    demand = 0
    for line in db.order_lines.values():
        if line["part_id"] != part_id or line["status"] != "OPEN":
            continue
        order = db.orders.get(line["order_id"])
        if order is not None and order["status"] == "ACKNOWLEDGED":
            demand += line["quantity"]
    part["open_demand_qty"] = demand


def touch_order(order):
    order["updated_at"] = stamp_now()
    order["version"] += 1


def recompute_order_totals(order, bump=True):
    open_exposure = 0
    allocated_value = 0
    for line in db.order_lines.values():
        if line["order_id"] != order["id"]:
            continue
        if line["status"] in ("OPEN", "ALLOCATED"):
            open_exposure += (line["quantity"] - line["shipped_qty"]) * line["unit_price_cents"]
        allocated_value += line["allocated_qty"] * line["unit_price_cents"]
    order["open_exposure_cents"] = open_exposure
    order["allocated_value_cents"] = allocated_value
    if bump:
        touch_order(order)


def fefo_lots_available(part_id):
    """AVAILABLE lots of the part ordered (date_code ASC, created_at ASC, seq ASC)."""
    lots = [
        lot
        for lot in db.inventory_lots.values()
        if lot["part_id"] == part_id and lot["status"] == "AVAILABLE"
    ]
    lots.sort(key=lambda l: (l["date_code"], l["created_at"], l["_seq"]))
    return lots


def fefo_lots_reserved(part_id):
    """Lots of the part with qty_reserved > 0 ordered (date_code ASC, created_at ASC, seq ASC)."""
    lots = [
        lot
        for lot in db.inventory_lots.values()
        if lot["part_id"] == part_id and lot["qty_reserved"] > 0
    ]
    lots.sort(key=lambda l: (l["date_code"], l["created_at"], l["_seq"]))
    return lots


def reserve_lots_fefo(part_id, amount):
    """Move `amount` units qty_on_hand -> qty_reserved across AVAILABLE lots FEFO."""
    remaining = amount
    for lot in fefo_lots_available(part_id):
        if remaining <= 0:
            break
        take = min(remaining, lot["qty_on_hand"])
        if take > 0:
            lot["qty_on_hand"] -= take
            lot["qty_reserved"] += take
            remaining -= take


def release_lots_fefo(part_id, amount):
    """Move `amount` units qty_reserved -> qty_on_hand across lots with reservations FEFO."""
    remaining = amount
    for lot in fefo_lots_reserved(part_id):
        if remaining <= 0:
            break
        take = min(remaining, lot["qty_reserved"])
        if take > 0:
            lot["qty_reserved"] -= take
            lot["qty_on_hand"] += take
            remaining -= take


def maybe_deplete_lot(lot):
    if (
        lot["qty_on_hand"] == 0
        and lot["qty_reserved"] == 0
        and lot["qty_shipped"] == lot["qty_received"]
        and lot["status"] != "DEPLETED"
    ):
        lot["status"] = "DEPLETED"
        lot["updated_at"] = stamp_now()
        lot["version"] += 1


def maybe_complete_order(order):
    """Automatic order transitions driven by line states."""
    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    if not lines:
        return
    if order["status"] == "PARTIALLY_SHIPPED":
        if all(l["status"] in ("SHIPPED", "CANCELLED") for l in lines) and any(
            l["status"] == "SHIPPED" for l in lines
        ):
            order["status"] = "COMPLETED"
    elif order["status"] == "ACKNOWLEDGED":
        if all(l["status"] == "CANCELLED" for l in lines) and not any(
            l["shipped_qty"] > 0 for l in lines
        ):
            order["status"] = "CANCELLED"
            order["open_exposure_cents"] = 0
            order["allocated_value_cents"] = 0


def quarantine_cascade(lot):
    """Quarantine `lot` (assumed AVAILABLE -> QUARANTINED) and unwind its reservations."""
    lot["status"] = "QUARANTINED"
    lot["updated_at"] = stamp_now()
    lot["version"] += 1
    released = lot["qty_reserved"]
    lot["qty_on_hand"] += lot["qty_reserved"]
    lot["qty_reserved"] = 0

    part_id = lot["part_id"]
    if released > 0:
        # Claw back from ALLOCATED lines of this part, newest first
        # (created_at DESC, tie ship_date DESC).
        lines = [
            l
            for l in db.order_lines.values()
            if l["part_id"] == part_id and l["status"] == "ALLOCATED"
        ]
        lines.sort(key=lambda l: (l["created_at"], l["ship_date"], l["_seq"]), reverse=True)
        touched_orders = []
        remaining = released
        for line in lines:
            if remaining <= 0:
                break
            dec = min(remaining, line["allocated_qty"])
            if dec <= 0:
                continue
            line["allocated_qty"] -= dec
            remaining -= dec
            line["updated_at"] = stamp_now()
            line["version"] += 1
            if line["allocated_qty"] == 0:
                line["status"] = "OPEN"
            order = db.orders.get(line["order_id"])
            if order is not None and order["id"] not in touched_orders:
                touched_orders.append(order["id"])
        for oid in touched_orders:
            order = db.orders.get(oid)
            if order is not None:
                recompute_order_totals(order, bump=True)
    recompute_part_availability(part_id)


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def serialize_manufacturer_line(l):
    return {
        "id": l["id"],
        "line_code": l["line_code"],
        "name": l["name"],
        "sourcing_channel": l["sourcing_channel"],
        "ncnr": l["ncnr"],
        "cancel_window_days": l["cancel_window_days"],
        "reschedule_window_days": l["reschedule_window_days"],
        "allocation_policy": l["allocation_policy"],
        "open_debit_balance_cents": l["open_debit_balance_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_part(p):
    return {
        "id": p["id"],
        "manufacturer_line_id": p["manufacturer_line_id"],
        "part_number": p["part_number"],
        "msl_level": p["msl_level"],
        "floor_life_hours": p["floor_life_hours"],
        "date_code_limit_months": p["date_code_limit_months"],
        "standard_cost_cents": p["standard_cost_cents"],
        "book_price_cents": p["book_price_cents"],
        "qty_on_hand": p["qty_on_hand"],
        "qty_reserved": p["qty_reserved"],
        "open_demand_qty": p["open_demand_qty"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "open_balance_cents": c["open_balance_cents"],
        "trailing_12mo_purchases_cents": c["trailing_12mo_purchases_cents"],
        "trailing_12mo_component_usage_units": c["trailing_12mo_component_usage_units"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_registration(r):
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "part_id": r["part_id"],
        "end_customer_name": r["end_customer_name"],
        "registered_cost_cents": r["registered_cost_cents"],
        "max_registered_qty": r["max_registered_qty"],
        "registered_qty_remaining": r["registered_qty_remaining"],
        "valid_from": r["valid_from"],
        "valid_to": r["valid_to"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "note": o["note"],
        "status": o["status"],
        "open_exposure_cents": o["open_exposure_cents"],
        "allocated_value_cents": o["allocated_value_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_order_line(l):
    return {
        "id": l["id"],
        "order_id": l["order_id"],
        "part_id": l["part_id"],
        "quantity": l["quantity"],
        "ship_date": l["ship_date"],
        "unit_price_cents": l["unit_price_cents"],
        "ncnr_snapshot": l["ncnr_snapshot"],
        "cancel_window_days_snapshot": l["cancel_window_days_snapshot"],
        "reschedule_window_days_snapshot": l["reschedule_window_days_snapshot"],
        "cancel_by_date": l["cancel_by_date"],
        "allocated_qty": l["allocated_qty"],
        "shipped_qty": l["shipped_qty"],
        "returned_qty": l["returned_qty"],
        "last_shipped_at": l["last_shipped_at"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_lot(lot):
    return {
        "id": lot["id"],
        "part_id": lot["part_id"],
        "date_code": lot["date_code"],
        "qty_received": lot["qty_received"],
        "qty_on_hand": lot["qty_on_hand"],
        "qty_reserved": lot["qty_reserved"],
        "qty_shipped": lot["qty_shipped"],
        "source_type": lot["source_type"],
        "authenticity": lot["authenticity"],
        "msl_exposure_hours": compute_msl_exposure_hours(lot),
        "last_baked_at": lot["last_baked_at"],
        "received_by_user_id": lot["received_by_user_id"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def serialize_exposure(e):
    return {
        "id": e["id"],
        "lot_id": e["lot_id"],
        "opened_at": e["opened_at"],
        "sealed_at": e["sealed_at"],
        "note": e["note"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_alternate(a):
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "primary_part_id": a["primary_part_id"],
        "alternate_part_id": a["alternate_part_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_run(r):
    return {
        "id": r["id"],
        "part_id": r["part_id"],
        "basis": r["basis"],
        "total_supply_qty": r["total_supply_qty"],
        "total_demand_qty": r["total_demand_qty"],
        "lines": [
            {"order_line_id": x["order_line_id"], "allocated_qty": x["allocated_qty"]}
            for x in r["lines"]
        ],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "registration_id": c["registration_id"],
        "order_line_id": c["order_line_id"],
        "qty": c["qty"],
        "standard_cost_cents": c["standard_cost_cents"],
        "registered_cost_cents": c["registered_cost_cents"],
        "amount_provisional_cents": c["amount_provisional_cents"],
        "audited_cost_cents": c["audited_cost_cents"],
        "amount_final_cents": c["amount_final_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_buyback(b):
    return {
        "id": b["id"],
        "customer_id": b["customer_id"],
        "order_line_id": b["order_line_id"],
        "kind": b["kind"],
        "qty": b["qty"],
        "price_basis_cents": b["price_basis_cents"],
        "fee_pct": b["fee_pct"],
        "provisional_credit_cents": b["provisional_credit_cents"],
        "received_qty": b["received_qty"],
        "final_credit_cents": b["final_credit_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }
