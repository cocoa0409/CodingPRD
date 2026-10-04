"""Drug products, recalls, and the product-scoped reads."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services import shortage as shortage_service
from services.helpers import as_bool, as_enum, as_int, as_str

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route("POST", "/networks/{networkId}/drug-products", roles=["NetworkAdmin"], status=201, write=True)
def create_product(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    data = ctx.body
    ndc = as_str(data, "ndc")
    duplicate = any(
        p.get("ndc") == ndc for p in db.where("drug_products", network_id=network["id"])
    )
    if duplicate:
        raise ApiError("ERR_INVALID_REQUEST", "ndc must be unique within the network")
    product = db.create(
        "drug_products",
        {
            "network_id": network["id"],
            "ndc": ndc,
            "brand_name": as_str(data, "brand_name"),
            "generic_name": as_str(data, "generic_name"),
            "therapeutic_class": as_enum(
                data,
                "therapeutic_class",
                ("CYTOTOXIC", "IMMUNOTHERAPY", "SUPPORTIVE_CARE", "ORAL_TARGETED"),
                required_=True,
            ),
            "unit_type": as_enum(
                data, "unit_type", ("VIAL", "MG", "TABLET"), required_=True
            ),
            "network_base_price_cents": as_int(
                data, "network_base_price_cents", required_=True, minimum=0
            ),
            "is_shortage_candidate": as_bool(data, "is_shortage_candidate", default=False),
            "status": "ACTIVE",
        },
    )
    return serial(product), 201


@route("GET", "/networks/drug-products", roles=READ_ROLES)
def list_products(ctx):
    rows = filtered(
        db.all_records("drug_products"),
        ctx,
        {
            "network_id": "network_id",
            "status": "status",
            "therapeutic_class": "therapeutic_class",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/drug-products/{productId}", roles=READ_ROLES)
def get_product(ctx):
    return serial(helpers.product_or_404(ctx.path_id("productId")))


@route("GET", "/networks/drug-products/{productId}/shortages", roles=READ_ROLES)
def product_shortages(ctx):
    product = helpers.product_or_404(ctx.path_id("productId"))
    rows = filtered(
        db.where("drug_shortages", drug_product_id=product["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route("GET", "/networks/drug-products/{productId}/treatments", roles=READ_ROLES)
def product_treatments(ctx):
    product = helpers.product_or_404(ctx.path_id("productId"))
    rows = filtered(
        db.where("treatments", drug_product_id=product["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route("POST", "/networks/drug-products/{productId}/recall", roles=["NetworkAdmin"], write=True)
def recall_product(ctx):
    product = helpers.product_or_404(ctx.path_id("productId"))
    if product["status"] == "RECALLED":
        raise ApiError("ERR_INVALID_STATE")
    live = shortage_service.live_shortage_for_product(product["id"])
    if live is not None:
        raise ApiError("ERR_SHORTAGE_NOT_ACTIVE")
    product["status"] = "RECALLED"
    db.touch(product)
    return serial(product)