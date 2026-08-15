"""Forward contracts and allocations (PRD section 3.6)."""

from flask import Blueprint, request

from store import TABLES
from helpers import (
    auth, own_or_fail, success, err, get_body, req_str, req_num,
    req_positive_num, req_positive_int, req_int, req_date, parse_iso_date,
    paginate, sorted_by_created, stamp_new, touch, path_get, require_ref, find,
    num_out, dec, q2, current_logical_week_monday, recompute_customer_exposure,
)
from routes_sheets import allocation_public, cancel_allocation, allocation_has_open_shipments

bp = Blueprint("trading", __name__)

TRADER = ["Trader"]
RISK = ["RiskOfficer"]
CUSTREP = ["CustomerRep"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]


# ---------------------------------------------------------------------------
# Forward contracts
# ---------------------------------------------------------------------------

def contract_public(c):
    return {
        "id": c["id"],
        "contract_number": c["contract_number"],
        "customer_id": c["customer_id"],
        "product_id": c["product_id"],
        "committed_lbs": c["committed_lbs"],
        "fixed_price_per_lb_cents": c["fixed_price_per_lb_cents"],
        "delivery_week_start": c["delivery_week_start"],
        "delivered_lbs": num_out(c["delivered_lbs"]),
        "earmarked_lbs": num_out(c["earmarked_lbs"]),
        "amendment_round": c["amendment_round"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def check_delivery_week(week_str):
    """Temporal rules (priority 12): Monday, and not earlier than the current
    logical week."""
    d = parse_iso_date(week_str, "delivery_week_start")
    if d.weekday() != 0:
        err("ERR_INVALID_WEEK_START", 422, "delivery_week_start must be a Monday")
    if d < current_logical_week_monday():
        err("ERR_FORWARD_WEEK_PASSED", 422,
            "delivery_week_start may not be earlier than the current logical week")


@bp.route("/api/forward-contracts", methods=["POST"])
def create_contract():
    auth(TRADER)
    body = get_body()
    number = req_str(body, "contract_number")
    customer_id = req_str(body, "customer_id")
    product_id = req_str(body, "product_id")
    committed = req_positive_int(body, "committed_lbs")
    price = req_positive_int(body, "fixed_price_per_lb_cents")
    week = req_date(body, "delivery_week_start")
    # Body FK existence (priority 6).
    require_ref("customers", customer_id, "customer_id")
    require_ref("products", product_id, "product_id")
    # Uniqueness (priority 10).
    for c in TABLES["forward_contracts"].values():
        if c["contract_number"] == number:
            err("ERR_DUPLICATE_CODE", 409, f"contract_number already exists: {number}")
    # Temporal (priority 12).
    check_delivery_week(week)
    rec = {
        "contract_number": number,
        "customer_id": customer_id,
        "product_id": product_id,
        "committed_lbs": committed,
        "fixed_price_per_lb_cents": price,
        "delivery_week_start": week,
        "delivered_lbs": q2(dec(0)),
        "earmarked_lbs": q2(dec(0)),
        "amendment_round": 0,
        "status": "OPEN",
    }
    stamp_new(rec)
    TABLES["forward_contracts"][rec["id"]] = rec
    return success(contract_public(rec), code=201)


@bp.route("/api/forward-contracts", methods=["GET"])
def list_contracts():
    auth(ALL)
    items = sorted_by_created(TABLES["forward_contracts"].values())
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if product_id is not None:
        items = [c for c in items if c["product_id"] == product_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([contract_public(c) for c in page], response_type="array",
                   pagination=meta)


@bp.route("/api/forward-contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    auth(ALL)
    c = path_get("forward_contracts", contractId, "ERR_FORWARD_CONTRACT_NOT_FOUND")
    return success(contract_public(c))


@bp.route("/api/forward-contracts/<contractId>/amend", methods=["POST"])
def amend_contract(contractId):
    auth(TRADER)
    body = get_body()
    committed = req_positive_int(body, "committed_lbs")
    price = req_positive_int(body, "fixed_price_per_lb_cents")
    week = req_date(body, "delivery_week_start")
    expected = req_int(body, "expected_contract_version")
    c = path_get("forward_contracts", contractId, "ERR_FORWARD_CONTRACT_NOT_FOUND")
    # Target state (priority 7).
    if c["status"] != "OPEN":
        err("ERR_CONTRACT_NOT_OPEN", 409, "Only an OPEN contract may be amended")
    # Temporal (priority 12).
    check_delivery_week(week)
    # Optimistic concurrency (priority 15).
    if expected != c["version"]:
        err("ERR_STALE_CONTRACT_VERSION", 412,
            "expected_contract_version does not match the contract's current version")
    c["committed_lbs"] = committed
    c["fixed_price_per_lb_cents"] = price
    c["delivery_week_start"] = week
    c["amendment_round"] += 1
    touch(c)
    return success(contract_public(c))


@bp.route("/api/forward-contracts/<contractId>/cancel", methods=["POST"])
def cancel_contract(contractId):
    auth(RISK)
    c = path_get("forward_contracts", contractId, "ERR_FORWARD_CONTRACT_NOT_FOUND")
    if c["status"] != "OPEN":
        err("ERR_CONTRACT_NOT_OPEN", 409, "Only an OPEN contract may be cancelled")
    for a in TABLES["allocations"].values():
        if a.get("forward_contract_id") == c["id"] and a["status"] == "CONFIRMED":
            err("ERR_CONTRACT_HAS_CONFIRMED_ALLOCATIONS", 409,
                "Contract has CONFIRMED earmarked allocations")
    # Cascade: still-REQUESTED earmarked allocations are cancelled.
    for a in sorted_by_created(TABLES["allocations"].values()):
        if a.get("forward_contract_id") == c["id"] and a["status"] == "REQUESTED":
            cancel_allocation(a, "CONTRACT_CANCELLED")
    c["status"] = "CANCELLED"
    touch(c)
    return success(contract_public(c))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

@bp.route("/api/allocations", methods=["POST"])
def create_allocation():
    uid, _ = auth(CUSTREP)
    body = get_body()
    # Ownership (priority 3): the request's customer must be the caller.
    raw_customer = body.get("customer_id")
    if isinstance(raw_customer, str) and raw_customer != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "CustomerRep may only request allocations for its own customer")
    # Request shape (priority 4).
    customer_id = req_str(body, "customer_id")
    line_id = req_str(body, "price_sheet_line_id")
    requested = req_positive_num(body, "requested_lbs")
    contract_id = req_str(body, "forward_contract_id", optional=True)
    # Body FK existence (priority 6).
    customer = require_ref("customers", customer_id, "customer_id")
    line = require_ref("price_sheet_lines", line_id, "price_sheet_line_id")
    contract = None
    if contract_id is not None:
        contract = require_ref("forward_contracts", contract_id, "forward_contract_id")
    # Cross-entity state (priority 8): the line's sheet must be PUBLISHED.
    sheet = find("price_sheets", line["price_sheet_id"])
    if sheet is None or sheet["status"] != "PUBLISHED":
        err("ERR_PRICE_SHEET_NOT_PUBLISHED", 409,
            "The allocation's line must sit on a PUBLISHED sheet")
    # Kind / reference compatibility (priority 13): the earmark trio.
    if contract is not None:
        if contract["customer_id"] != customer_id:
            err("ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH", 422,
                "Earmarked contract belongs to a different customer")
        if contract["product_id"] != line["product_id"]:
            err("ERR_PRODUCT_KIND_MISMATCH", 422,
                "Earmarked contract product differs from the line's product")
        if contract["delivery_week_start"] != sheet["week_start_date"]:
            err("ERR_FORWARD_CONTRACT_WEEK_MISMATCH", 422,
                "Earmarked contract delivery week differs from the sheet week")
    # Credit gate (priority 14).
    if customer["status"] != "ACTIVE":
        err("ERR_CUSTOMER_CREDIT_HOLD", 402,
            "Customer on CREDIT_HOLD may not request allocations")
    rec = {
        "customer_id": customer_id,
        "price_sheet_line_id": line_id,
        "forward_contract_id": contract_id,
        "requested_lbs": q2(requested),
        "allocated_lbs": q2(dec(0)),
        "unit_price_cents": None,
        "status": "REQUESTED",
        "cancel_reason": None,
    }
    stamp_new(rec)
    TABLES["allocations"][rec["id"]] = rec
    return success(allocation_public(rec), code=201)


@bp.route("/api/allocations", methods=["GET"])
def list_allocations():
    auth(ALL)
    items = sorted_by_created(TABLES["allocations"].values())
    for param in ("customer_id", "price_sheet_line_id", "forward_contract_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    page, meta = paginate(items)
    return success([allocation_public(a) for a in page], response_type="array",
                   pagination=meta)


@bp.route("/api/allocations/<allocationId>", methods=["GET"])
def get_allocation(allocationId):
    auth(ALL)
    a = path_get("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")
    return success(allocation_public(a))


@bp.route("/api/allocations/<allocationId>/cancel", methods=["POST"])
def cancel_allocation_endpoint(allocationId):
    uid, _ = auth(CUSTREP)
    alloc = TABLES["allocations"].get(allocationId)
    # Ownership (priority 3) — evaluated when the resource exists; a missing
    # allocation falls through to the 404 path-existence check.
    if alloc is not None:
        own_or_fail(alloc["customer_id"], uid)
    if alloc is None:
        err("ERR_ALLOCATION_NOT_FOUND", 404, f"Allocation {allocationId} not found")
    if alloc["status"] == "REQUESTED":
        alloc["status"] = "CANCELLED"
        alloc["cancel_reason"] = "MANUAL"
        touch(alloc)
        return success(allocation_public(alloc))
    if alloc["status"] == "CONFIRMED":
        if allocation_has_open_shipments(alloc):
            err("ERR_ALLOCATION_NOT_CANCELLABLE", 409,
                "CONFIRMED allocation has STAGING or IN_TRANSIT shipments")
        cancel_allocation(alloc, "MANUAL")
        return success(allocation_public(alloc))
    err("ERR_ALLOCATION_NOT_REQUESTED", 409,
        "Allocation is not in a cancellable state")
