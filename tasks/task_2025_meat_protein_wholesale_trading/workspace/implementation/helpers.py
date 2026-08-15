"""Shared helpers: errors, response envelope, decimals, validation primitives,
pagination, domain calculations (cutout, unit value, exposure, occupancy,
sheet selectors), and cascade bookkeeping."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, date, timezone, timedelta

from flask import request, jsonify

import store
from store import TABLES, wall_now_iso, new_request_id, new_id, next_seq, clock_now


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
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------

def success(data, code=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


# ---------------------------------------------------------------------------
# Decimal discipline (PRD section 2.6)
# ---------------------------------------------------------------------------

D0 = Decimal("0")
CENT = Decimal("0.01")


def dec(value):
    """Exact Decimal from an int/float/str JSON number."""
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number")


def q2(value):
    """Quantize a weight (lbs) to two decimal places, half-up."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round half up to whole cents; returns int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(value):
    """Serialize a Decimal weight/percent as a JSON number."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = dec(value)
    return float(value)


# ---------------------------------------------------------------------------
# Request shape validation primitives (priority 4 -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, optional=False):
    if not _present(body, field):
        if optional:
            return None
        err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def req_int(body, field, optional=False):
    if not _present(body, field):
        if optional:
            return None
        err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def req_num(body, field, optional=False):
    if not _present(body, field):
        if optional:
            return None
        err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    v = body[field]
    try:
        return dec(v)
    except (ValueError, InvalidOperation):
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")


def req_enum(body, field, allowed, optional=False):
    v = req_str(body, field, optional=optional)
    if v is None:
        return None
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_positive_num(body, field):
    v = req_num(body, field)
    if v <= 0:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be positive")
    return v


def req_positive_int(body, field):
    v = req_int(body, field)
    if v <= 0:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be positive")
    return v


def req_nonneg_int(body, field):
    v = req_int(body, field)
    if v < 0:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be non-negative")
    return v


def parse_iso_date(value, field):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO date (YYYY-MM-DD)")


def req_date(body, field, optional=False):
    v = req_str(body, field, optional=optional)
    if v is None:
        return None
    parse_iso_date(v, field)
    return v


def parse_iso_datetime(value, field):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10 (min 1, max 100), offset 0
# ---------------------------------------------------------------------------

def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
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
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Resource mutation bookkeeping (PRD section 2.5 / 2.11)
# ---------------------------------------------------------------------------

def touch(record):
    """Bump version + refresh updated_at on a mutation. No-op for the four
    light resources (Product, YieldSpec, TemperatureReading,
    InspectionCertificate) which carry neither field."""
    if "version" in record:
        record["version"] += 1
    if "updated_at" in record:
        record["updated_at"] = wall_now_iso()


def stamp_new(record, common=True):
    record["id"] = new_id()
    record["created_at"] = wall_now_iso()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


# ---------------------------------------------------------------------------
# Roles / auth context (PRD section 2.1, pipeline stages 1-3)
# ---------------------------------------------------------------------------

ALL_ROLES = {
    "DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
    "WarehouseOperator", "ClaimsAdjuster", "CustomerRep",
}


def auth(allowed_roles):
    """Stages 1 and 2 of the validation pipeline."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and the role must be declared")
    if role not in allowed_roles:
        err("ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint")
    return uid, role


def own_or_fail(owner_customer_id, uid):
    """Stage 3: CustomerRep ownership check."""
    if owner_customer_id is not None and owner_customer_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "X-User-ID does not match the customer that owns this resource")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find(table, rid):
    return TABLES[table].get(rid)


def path_get(table, rid, error_id):
    rec = TABLES[table].get(rid)
    if rec is None:
        err(error_id, 404, f"Resource {rid} not found")
    return rec


def ref_get(table, rid):
    if rid is None:
        return None
    return TABLES[table].get(rid)


def require_ref(table, rid, field):
    rec = TABLES[table].get(rid) if isinstance(rid, str) else None
    if rec is None:
        err("ERR_REFERENCE_NOT_FOUND", 422, f"Referenced {field} does not exist: {rid}")
    return rec


# ---------------------------------------------------------------------------
# Domain time helpers
# ---------------------------------------------------------------------------

def current_logical_week_monday():
    d = clock_now().date()
    return d - timedelta(days=d.weekday())


def lot_age_days(lot):
    prod = date.fromisoformat(lot["production_date"])
    return (clock_now().date() - prod).days


# ---------------------------------------------------------------------------
# Published-sheet selector (PRD section 2.7)
# ---------------------------------------------------------------------------

def latest_published_sheet():
    """Among PUBLISHED sheets: max week_start_date, tie-break max
    published_at, then min created_at (creation sequence)."""
    best = None
    for s in sorted_by_created(TABLES["price_sheets"].values()):
        if s["status"] != "PUBLISHED":
            continue
        if best is None:
            best = s
            continue
        key = (s["week_start_date"], s.get("published_at") or "")
        best_key = (best["week_start_date"], best.get("published_at") or "")
        if key > best_key:
            best = s
    return best


def sheet_line_for(sheet, product_id):
    if sheet is None:
        return None
    for line in TABLES["price_sheet_lines"].values():
        if line["price_sheet_id"] == sheet["id"] and line["product_id"] == product_id:
            return line
    return None


def latest_published_line_for(product_id):
    """The most recently published sheet's line for the product (None if the
    selected sheet carries no line for it)."""
    sheet = latest_published_sheet()
    return sheet_line_for(sheet, product_id)


# ---------------------------------------------------------------------------
# Calculation: cutout_value (PRD sections 3.3 / 3.4) — per-line round, then sum
# ---------------------------------------------------------------------------

def compute_cutout(product, basis_weight_lbs, sheet):
    """sheet may be None (no published sheet): every line contributes 0."""
    basis = dec(basis_weight_lbs) if not isinstance(basis_weight_lbs, Decimal) else basis_weight_lbs
    total = 0
    if product["kind"] == "CARCASS":
        specs = [ys for ys in sorted_by_created(TABLES["yield_specs"].values())
                 if ys["carcass_product_id"] == product["id"]]
        for ys in specs:
            line = sheet_line_for(sheet, ys["output_product_id"])
            if line is None:
                continue
            line_lbs = basis * dec(ys["expected_yield_pct"]) / Decimal("100")
            total += round_half_up_int(line_lbs * line["price_per_lb_cents"])
    else:  # PRIMAL: single line
        line = sheet_line_for(sheet, product["id"])
        if line is not None:
            total = round_half_up_int(basis * line["price_per_lb_cents"])
    return total


def cutout_at_booking(product, ordered_weight_lbs):
    return compute_cutout(product, ordered_weight_lbs, latest_published_sheet())


def cutout_at_grading(po, product, received_weight_lbs, issue_date_str):
    """Sheet whose half-open week contains the certificate issue_date
    (PUBLISHED, CLOSED or SUPERSEDED). Fallback: the booking estimate."""
    issue = date.fromisoformat(issue_date_str)
    chosen = None
    for s in sorted_by_created(TABLES["price_sheets"].values()):
        if s["status"] not in ("PUBLISHED", "CLOSED", "SUPERSEDED"):
            continue
        start = date.fromisoformat(s["week_start_date"])
        if start <= issue < start + timedelta(days=7):
            if chosen is None:
                chosen = s
                continue
            key = (s.get("published_at") or "",)
            best_key = (chosen.get("published_at") or "",)
            if key > best_key:
                chosen = s
    if chosen is None:
        return po["estimated_cutout_value_cents"]
    return compute_cutout(product, received_weight_lbs, chosen)


# ---------------------------------------------------------------------------
# Calculation: aging_adjusted_unit_value (PRD section 3.4) — single final
# rounding, no intermediate rounding
# ---------------------------------------------------------------------------

GRADE_MULT = {
    "PRIME": Decimal("1.08"),
    "CHOICE": Decimal("1.00"),
    "SELECT": Decimal("0.94"),
    "STANDARD": Decimal("0.90"),
    "NO_ROLL": Decimal("0.85"),
    "UNGRADED": Decimal("0.97"),
}


def age_multiplier(age_days):
    if age_days <= 7:
        return Decimal("1.00")
    if age_days <= 14:
        return Decimal("0.95")
    if age_days <= 21:
        return Decimal("0.88")
    return Decimal("0.75")


def compute_unit_value(lot):
    line = latest_published_line_for(lot["product_id"])
    base = line["price_per_lb_cents"] if line is not None else 0
    g = GRADE_MULT[lot["usda_grade"]]
    a = age_multiplier(lot_age_days(lot))
    return round_half_up_int(Decimal(base) * g * a)


def recompute_lot_value(lot):
    """Recompute the aging/grade-adjusted value, but only for lots that have
    been graded at least once (value is null until graded)."""
    if lot.get("unit_value_cents_per_lb") is not None:
        lot["unit_value_cents_per_lb"] = compute_unit_value(lot)


# ---------------------------------------------------------------------------
# Calculation: customer_credit_exposure (PRD section 2.10) + auto CREDIT_HOLD
# ---------------------------------------------------------------------------

def claim_customer_id(claim):
    shipment = find("shipments", claim["shipment_id"])
    if shipment is None:
        return None
    alloc = find("allocations", shipment["allocation_id"])
    return alloc["customer_id"] if alloc else None


def shipment_customer_id(shipment):
    alloc = find("allocations", shipment["allocation_id"])
    return alloc["customer_id"] if alloc else None


def recompute_customer_exposure(customer):
    total = Decimal(0)
    for a in TABLES["allocations"].values():
        if a["customer_id"] == customer["id"] and a["status"] in ("CONFIRMED", "SHIPPED"):
            total += dec(a["allocated_lbs"]) * a["unit_price_cents"]
    for c in TABLES["claims"].values():
        if c["status"] == "SETTLED_PAID" and claim_customer_id(c) == customer["id"]:
            total -= c["final_settlement_cents"] or 0
    if total < 0:
        total = Decimal(0)
    new_exposure = round_half_up_int(total)
    changed = customer["outstanding_exposure_cents"] != new_exposure
    customer["outstanding_exposure_cents"] = new_exposure
    # Strict comparison: exposure > limit -> CREDIT_HOLD; <= limit -> ACTIVE.
    if new_exposure > customer["credit_limit_cents"]:
        new_status = "CREDIT_HOLD"
    else:
        new_status = "ACTIVE"
    if customer["status"] != new_status:
        customer["status"] = new_status
        changed = True
    if changed:
        touch(customer)


# ---------------------------------------------------------------------------
# Calculation: warehouse_occupancy (PRD section 2.11)
# ---------------------------------------------------------------------------

COUNTED_LOT_STATUSES = ("IN_INSPECTION", "AVAILABLE", "QUARANTINED")


def recompute_warehouse(warehouse_id):
    wh = find("warehouses", warehouse_id)
    if wh is None:
        return
    occ = Decimal(0)
    for lot in TABLES["inventory_lots"].values():
        if lot["warehouse_id"] == warehouse_id and lot["status"] in COUNTED_LOT_STATUSES:
            occ += dec(lot["current_weight_lbs"])
    occ = q2(occ)
    if dec(wh["occupied_lbs"]) != occ:
        wh["occupied_lbs"] = occ
        touch(wh)


def recompute_all_warehouses():
    for wid in list(TABLES["warehouses"].keys()):
        recompute_warehouse(wid)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def lot_public(lot):
    return {
        "id": lot["id"],
        "lot_code": lot["lot_code"],
        "po_id": lot["po_id"],
        "parent_lot_id": lot["parent_lot_id"],
        "fabrication_batch_id": lot["fabrication_batch_id"],
        "product_id": lot["product_id"],
        "warehouse_id": lot["warehouse_id"],
        "received_weight_lbs": num_out(lot["received_weight_lbs"]),
        "current_weight_lbs": num_out(lot["current_weight_lbs"]),
        "production_date": lot["production_date"],
        "age_days": lot_age_days(lot),
        "usda_grade": lot["usda_grade"],
        "measured_fat_pct": num_out(lot["measured_fat_pct"]),
        "spec_compliant": lot["spec_compliant"],
        "unit_value_cents_per_lb": lot["unit_value_cents_per_lb"],
        "quarantine_reason": lot["quarantine_reason"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def make_lot(lot_code, product_id, warehouse_id, weight_lbs, production_date,
             po_id=None, parent_lot_id=None, fabrication_batch_id=None,
             status="IN_INSPECTION", quarantine_reason=None):
    w = q2(dec(weight_lbs))
    lot = {
        "lot_code": lot_code,
        "po_id": po_id,
        "parent_lot_id": parent_lot_id,
        "fabrication_batch_id": fabrication_batch_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "received_weight_lbs": w,
        "current_weight_lbs": w,
        "production_date": production_date,
        "usda_grade": "UNGRADED",
        "measured_fat_pct": None,
        "spec_compliant": None,
        "unit_value_cents_per_lb": None,
        "quarantine_reason": quarantine_reason,
        "status": status,
    }
    stamp_new(lot, common=True)
    TABLES["inventory_lots"][lot["id"]] = lot
    return lot
