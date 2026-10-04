"""Drug shortages and the allocation waterfall."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services import shortage as shortage_service
from services.helpers import as_dt, as_enum, as_int, as_str
from utils import fmt_ts

READ_ROLES = ["NetworkAdmin", "PracticeAdmin", "NetworkAnalyst", "PlatformAdmin"]
METHODS = ("PRO_RATA_BASELINE", "PRIORITY_PATHWAY", "EQUAL_SPLIT")


@route("POST", "/networks/{networkId}/drug-shortages", roles=["NetworkAdmin"], status=201, write=True)
def report_shortage(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    product = helpers.product_or_404(as_str(ctx.body, "drug_product_id"))
    if product.get("network_id") != network["id"]:
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
    supply = as_int(ctx.body, "supply_available_units", required_=True, minimum=0)
    shortage = db.create(
        "drug_shortages",
        {
            "network_id": network["id"],
            "drug_product_id": product["id"],
            "reported_at": fmt_ts(as_dt(ctx.body, "reported_at", required_=True)),
            "supply_available_units": supply,
            "allocation_method": as_enum(ctx.body, "allocation_method", METHODS, required_=True),
            "allocated_units": 0,
            "unallocated_units": supply,
            "unclaimed_authorization_cents": 0,
            "status": "REPORTED",
        },
    )
    return serial(shortage), 201


@route("GET", "/networks/drug-shortages", roles=READ_ROLES)
def list_shortages(ctx):
    rows = filtered(
        db.all_records("drug_shortages"),
        ctx,
        {"network_id": "network_id", "drug_product_id": "drug_product_id", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/drug-shortages/{shortageId}", roles=READ_ROLES)
def get_shortage(ctx):
    return serial(helpers.shortage_or_404(ctx.path_id("shortageId")))


@route("GET", "/networks/drug-shortages/{shortageId}/allocations", roles=READ_ROLES)
def shortage_allocations(ctx):
    shortage = helpers.shortage_or_404(ctx.path_id("shortageId"))
    rows = filtered(
        db.where("shortage_allocations", shortage_id=shortage["id"]), ctx, {"status": "status"}
    )
    rows = sorted(rows, key=lambda g: (g.get("allocation_rank") or 0, g.get("_seq", 0)))
    return paginate(ctx, rows)


@route("POST", "/networks/drug-shortages/{shortageId}/allocate", roles=["NetworkAdmin"], write=True)
def allocate_shortage(ctx):
    shortage = helpers.shortage_or_404(ctx.path_id("shortageId"))
    if shortage["status"] not in ("REPORTED", "ALLOCATING"):
        raise ApiError("ERR_SHORTAGE_NOT_REPORTED")
    if int(shortage.get("supply_available_units") or 0) <= 0:
        raise ApiError("ERR_THRESHOLD_NOT_MET")
    if not shortage_service.eligible_practices(shortage["network_id"]):
        raise ApiError("ERR_NO_ELIGIBLE_PRACTICES")

    raw_map = ctx.body.get("practice_consumption_authorization_cents") or {}
    if not isinstance(raw_map, dict):
        raise ApiError(
            "ERR_INVALID_REQUEST", "practice_consumption_authorization_cents must be an object"
        )
    authorization = {}
    for key, value in raw_map.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "practice_consumption_authorization_cents values must be non-negative integers",
            )
        authorization[key] = value

    shortage["status"] = "ALLOCATING"
    shortage_service.allocate(shortage, authorization)
    db.touch(shortage)
    return serial(shortage)


@route("POST", "/networks/drug-shortages/{shortageId}/activate", roles=["NetworkAdmin"], write=True)
def activate_shortage(ctx):
    shortage = helpers.shortage_or_404(ctx.path_id("shortageId"))
    if shortage["status"] != "ALLOCATING":
        raise ApiError("ERR_SHORTAGE_NOT_ALLOCATING")
    granted = sum(
        int(g.get("allocated_units") or 0)
        for g in shortage_service.grants_of(shortage["id"])
        if g["status"] != "REVOKED"
    )
    if granted != int(shortage.get("supply_available_units") or 0):
        raise ApiError("ERR_ALLOCATION_INCOMPLETE")
    shortage["status"] = "ACTIVE"
    product = db.get("drug_products", shortage["drug_product_id"])
    if product is not None:
        product["status"] = "SHORTAGE_RESTRICTED"
        db.touch(product)
    db.touch(shortage)
    return serial(shortage)


@route("POST", "/networks/drug-shortages/{shortageId}/resolve", roles=["NetworkAdmin"], write=True)
def resolve_shortage(ctx):
    shortage = helpers.shortage_or_404(ctx.path_id("shortageId"))
    if shortage["status"] != "ACTIVE":
        raise ApiError("ERR_SHORTAGE_NOT_ACTIVE")
    shortage["status"] = "RESOLVED"
    for grant in shortage_service.grants_of(shortage["id"]):
        if grant["status"] in ("GRANTED", "PARTIALLY_COMMITTED"):
            shortage_service.expire_grant(grant)
    # The product returns to ACTIVE only when no other live shortage remains.
    others = [
        s
        for s in db.where("drug_shortages", drug_product_id=shortage["drug_product_id"])
        if s["id"] != shortage["id"] and s["status"] in ("REPORTED", "ALLOCATING", "ACTIVE")
    ]
    product = db.get("drug_products", shortage["drug_product_id"])
    if product is not None and not others and product["status"] == "SHORTAGE_RESTRICTED":
        product["status"] = "ACTIVE"
        db.touch(product)
    db.touch(shortage)
    return serial(shortage)


@route("GET", "/networks/shortage-allocations", roles=READ_ROLES)
def list_allocations(ctx):
    rows = filtered(
        db.all_records("shortage_allocations"),
        ctx,
        {"practice_id": "practice_id", "shortage_id": "shortage_id", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/shortage-allocations/{allocationId}", roles=READ_ROLES)
def get_allocation(ctx):
    return serial(helpers.allocation_or_404(ctx.path_id("allocationId")))


@route("GET", "/networks/shortage-allocations/{allocationId}/orders", roles=READ_ROLES)
def allocation_orders(ctx):
    allocation = helpers.allocation_or_404(ctx.path_id("allocationId"))
    rows = filtered(
        db.where("purchase_orders", shortage_allocation_id=allocation["id"]),
        ctx,
        {"status": "status"},
    )
    return paginate(ctx, rows)