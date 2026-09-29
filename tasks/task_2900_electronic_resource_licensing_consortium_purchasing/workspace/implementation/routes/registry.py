"""Section 3.1 - members, vendors and products."""

from flask import Blueprint, request

import auth
import envelope
import shape
import store

bp = Blueprint("registry", __name__)

ALL = auth.ALL_ROLES


@bp.post("/erm/members")
def create_member():
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    data = shape.body()
    row = store.new_row({
        "name": shape.req_string(data, "name"),
        "fte_count": shape.req_int(data, "fte_count", minimum=1),
        "carnegie_class": shape.req_enum(data, "carnegie_class", shape.CARNEGIE_CLASSES),
        "budget_ceiling_cents": shape.req_int(data, "budget_ceiling_cents", minimum=0),
        "annual_committed_cents": 0,
        "standing": "IN_GOOD_STANDING",
    })
    store.members[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/members/<member_id>")
def read_member(member_id):
    auth.require_roles(*ALL)
    row = auth.get_member(member_id)
    return envelope.object_response(store.serialize(row))


@bp.post("/erm/vendors")
def create_vendor():
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    data = shape.body()
    row = store.new_row({
        "name": shape.req_string(data, "name"),
        "archival_agency_code": shape.opt_enum(
            data, "archival_agency_code", shape.ARCHIVAL_AGENCIES, None
        ),
        "vpat_on_file": shape.opt_bool(data, "vpat_on_file", False),
    })
    store.vendors[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/vendors/<vendor_id>")
def read_vendor(vendor_id):
    auth.require_roles(*ALL)
    row = auth.get_vendor(vendor_id)
    return envelope.object_response(store.serialize(row))


@bp.post("/erm/products")
def create_product():
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    data = shape.body()
    # priority 4 - the body foreign key resolves before the shape is inspected
    if shape.present(data, "vendor_id"):
        auth.get_vendor(data["vendor_id"])
    row = store.new_row({
        "vendor_id": shape.req_string(data, "vendor_id"),
        "name": shape.req_string(data, "name"),
        "base_list_price_cents": shape.req_int(data, "base_list_price_cents", minimum=1),
        "title_count": shape.req_int(data, "title_count", minimum=1),
        "inflation_cap_pct": shape.req_number(data, "inflation_cap_pct", minimum=0, maximum=25),
        "cancellation_notice_days": shape.req_int(data, "cancellation_notice_days", minimum=0),
        "perpetual_access_mode_offered": shape.req_enum(
            data, "perpetual_access_mode_offered", shape.PERPETUAL_MODES
        ),
        "ill_mode_offered": shape.req_enum(data, "ill_mode_offered", shape.ILL_MODES),
        "text_mining_offered": shape.req_bool(data, "text_mining_offered"),
        "tier_bands": shape.req_tier_bands(data),
    })
    store.products[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/products/<product_id>")
def read_product(product_id):
    auth.require_roles(*ALL)
    row = auth.get_product(product_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/products")
def list_products():
    auth.require_roles(*ALL)
    rows = list(store.products.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    return envelope.paged(rows)
