"""Par lines: the per-product stock definitions of a break room (PRD 3.2)."""
from flask import Blueprint

import calc
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_ROUTE_TECHNICIAN,
                  authenticate)
from envelope import created, ok
from errors import ApiError
from store import bump, db, insert, now

bp = Blueprint("parlevels", __name__)


@bp.post("/ocs/par-levels")
def create_par_level():
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    site_id = fields.string("site_id", min_len=1)
    product_id = fields.string("product_id", min_len=1)
    par_units = fields.integer("par_units", minimum=0)
    reorder_units = fields.integer("reorder_point_units", minimum=0)
    if reorder_units > par_units:
        raise ApiError("ERR_VALIDATION",
                       "Field 'reorder_point_units' must not exceed 'par_units'.")
    lookup.site(site_id)
    lookup.product_item(product_id)
    if calc.par_line_for(site_id, product_id) is not None:
        raise ApiError("ERR_DUPLICATE_PAR_LEVEL",
                       "A par line already exists for this site and product.")
    row = insert(db.par_levels, {
        "site_id": site_id,
        "product_id": product_id,
        "par_units": par_units,
        "reorder_point_units": reorder_units,
        "source": "MANUAL",
        "on_hand_units": 0,
        "cumulative_delivered_units": 0,
        "cumulative_consumed_units": 0,
        "last_service_at": now(),
        "stock_status": "STOCKOUT",
    })
    return created(serializers.par_level(row))


@bp.get("/ocs/par-levels")
def list_par_levels():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_ROUTE_TECHNICIAN, ROLE_BILLING_SPECIALIST))
    rows = lookup.eq_filter(list(db.par_levels.values()), "site_id")
    rows = lookup.eq_filter(rows, "product_id")
    rows = lookup.eq_filter(rows, "stock_status")
    rows = lookup.eq_filter(rows, "source")
    return lookup.listing(rows, serializers.par_level)


@bp.get("/ocs/par-levels/<par_level_id>")
def read_par_level(par_level_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_ROUTE_TECHNICIAN, ROLE_BILLING_SPECIALIST))
    return ok(serializers.par_level(lookup.par_level(par_level_id)))


@bp.patch("/ocs/par-levels/<par_level_id>")
def update_par_level(par_level_id):
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    par_units = fields.integer("par_units", required=False, minimum=0)
    reorder_units = fields.integer("reorder_point_units", required=False, minimum=0)
    line = lookup.par_level(par_level_id)
    if par_units is not None:
        line["par_units"] = par_units
    if reorder_units is not None:
        line["reorder_point_units"] = reorder_units
    # An overridden forecast line is thereafter protected from planning.
    line["source"] = "MANUAL"
    line["stock_status"] = calc.stock_status(line["on_hand_units"],
                                            line["reorder_point_units"])
    bump(line)
    return ok(serializers.par_level(line))
