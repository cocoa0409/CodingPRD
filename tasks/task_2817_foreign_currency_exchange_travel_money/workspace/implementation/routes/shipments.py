"""Cash logistics: armored movement, dispatch, arrival variance and reconciliation."""
from flask import Blueprint

import calc
from core import (
    D,
    body,
    clock,
    endpoint,
    fail,
    listing,
    need,
    need_currency,
    ok,
    opt_list,
    parse_note_lines,
    parse_dt,
    public,
    req_dt,
    req_enum,
    req_list,
    req_str,
    require_not_restricted,
    require_standard_denominations,
    touch,
)

bp = Blueprint("shipments", __name__)

READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager")


@bp.post("/cash-shipments")
@endpoint(["TreasuryOfficer", "BranchManager"])
def create_shipment():
    b = body()
    branch = need("Branch", req_str(b, "branch_id"))
    currency_code = req_str(b, "currency_code")
    profile = need_currency(currency_code)
    direction = req_enum(b, "direction", ("REPLENISHMENT", "REPATRIATION"))
    lines = parse_note_lines(
        req_list(b, "manifest_denominations"), "manifest_denominations", min_count=1
    )
    require_standard_denominations(lines, profile, "manifest_denominations")
    # rank 7 - a RESTRICTED vault refuses cash coming in
    if direction == "REPLENISHMENT":
        require_not_restricted(branch)
    row = calc.create_shipment(branch, currency_code, direction, lines, auto_generated=False)
    return ok(public(row), 201)


@bp.post("/cash-shipments/<shipment_id>/schedule")
@endpoint(["TreasuryOfficer"])
def schedule_shipment(shipment_id):
    shipment = need("CashShipment", shipment_id)
    b = body()
    route = need("ArmoredRoute", req_str(b, "armored_route_id"))
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    start_dt = parse_dt(window_start)
    end_dt = parse_dt(window_end)
    if end_dt <= start_dt:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    # rank 5
    if shipment["status"] != "REQUESTED":
        fail("ERR_SHIPMENT_INVALID_STATE")
    branch = need("Branch", shipment["branch_id"])
    # rank 10 - closed transport windows, 45 minute separation
    if calc.route_window_conflict(route["id"], shipment["id"], start_dt, end_dt):
        fail("ERR_ROUTE_WINDOW_CONFLICT")
    # rank 11
    if route["status"] != "ACTIVE":
        fail("ERR_ROUTE_SUSPENDED")
    if route["region_code"] != branch["region_code"]:
        fail("ERR_ROUTE_BRANCH_NOT_SERVICED")
    # rank 13
    if calc.route_day_capacity_exceeded(route, shipment, start_dt):
        fail("ERR_ROUTE_CAPACITY_EXCEEDED")

    shipment["armored_route_id"] = route["id"]
    shipment["window_start"] = window_start
    shipment["window_end"] = window_end
    shipment["status"] = "SCHEDULED"
    touch(shipment)
    return ok(public(shipment))


@bp.post("/cash-shipments/<shipment_id>/dispatch")
@endpoint(["TreasuryOfficer"])
def dispatch_shipment(shipment_id):
    shipment = need("CashShipment", shipment_id)
    if shipment["status"] != "SCHEDULED":
        fail("ERR_SHIPMENT_INVALID_STATE")
    if clock() < D(shipment["window_start"]):
        fail("ERR_SHIPMENT_WINDOW_NOT_OPEN")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return ok(public(shipment))


@bp.post("/cash-shipments/<shipment_id>/arrive")
@endpoint(["BranchManager"])
def arrive_shipment(shipment_id):
    shipment = need("CashShipment", shipment_id)
    b = body()
    raw = opt_list(b, "delivered_denominations")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "delivered_denominations is required.")
    lines = parse_note_lines(raw, "delivered_denominations", min_count=0)
    profile = need_currency(shipment["currency_code"])
    require_standard_denominations(lines, profile, "delivered_denominations")
    if shipment["status"] != "IN_TRANSIT":
        fail("ERR_SHIPMENT_INVALID_STATE")
    branch = need("Branch", shipment["branch_id"])

    delivered = calc.fx_gross(lines)
    variance = shipment["manifest_minor_units"] - delivered
    shipment["delivered_minor_units"] = delivered
    shipment["variance_minor_units"] = variance
    if variance == 0:
        shipment["status"] = "DELIVERED"
        shipment["exception_reason"] = None
    else:
        shipment["status"] = "EXCEPTION"
        shipment["exception_reason"] = "MANIFEST_VARIANCE"
    touch(shipment)

    # only the notes actually counted ever move
    position = calc.branch_position(branch["id"], shipment["currency_code"])
    if position is not None:
        for line in lines:
            entry = calc.ensure_mix_entry(position, line["denomination_minor_units"])
            if shipment["direction"] == "REPLENISHMENT":
                entry["available_note_count"] += line["note_count"]
            else:
                entry["available_note_count"] -= line["note_count"]
        calc.inventory_cascade(position, branch)
    if shipment["direction"] == "REPATRIATION" and shipment["status"] == "DELIVERED":
        branch["repatriation_pending"] = False
    touch(branch)
    return ok(public(shipment))


@bp.post("/cash-shipments/<shipment_id>/reconcile")
@endpoint(["TreasuryOfficer"])
def reconcile_shipment(shipment_id):
    shipment = need("CashShipment", shipment_id)
    if shipment["status"] not in ("DELIVERED", "EXCEPTION"):
        fail("ERR_SHIPMENT_INVALID_STATE")
    from_exception = shipment["status"] == "EXCEPTION"
    shipment["written_off_minor_units"] = shipment["variance_minor_units"] if from_exception else 0
    shipment["status"] = "RECONCILED"
    touch(shipment)
    if from_exception and shipment["direction"] == "REPATRIATION":
        branch = need("Branch", shipment["branch_id"])
        if branch["repatriation_pending"]:
            branch["repatriation_pending"] = False
            touch(branch)
    return ok(public(shipment))


@bp.get("/cash-shipments/<shipment_id>")
@endpoint(READERS)
def read_shipment(shipment_id):
    return ok(public(need("CashShipment", shipment_id)))


@bp.get("/cash-shipments")
@endpoint(READERS)
def list_shipments():
    return listing(
        "CashShipment",
        {
            "branch_id": "branch_id",
            "armored_route_id": "armored_route_id",
            "direction": "direction",
            "status": "status",
        },
        {"auto_generated": "auto_generated"},
    )
