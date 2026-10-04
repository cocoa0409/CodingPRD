"""RetailerAccount routes: onboard, read."""

from flask import Blueprint

from db import db
from domain import TIERS, get_retailer, ser_retailer
from middleware import authorize, ROLE_PLATFORM_ADMIN, ALL_ROLES
from programs import _create_entity
from respond import ok, created
from validate import json_body, v_str, v_int, v_enum

bp = Blueprint("retailers", __name__)


@bp.post("/confection/retailer-accounts")
def create_retailer():
    data = json_body()
    name = v_str(data, "name")
    region = v_str(data, "region")
    tier = v_enum(data, "tier", TIERS)
    max_seasonal_units = v_int(data, "max_seasonal_units", min_v=1)
    baseline = v_int(data, "everyday_baseline_weekly_units", min_v=1)

    authorize(ROLE_PLATFORM_ADMIN)

    retailer = _create_entity(db.retailers, {
        "name": name,
        "region": region,
        "tier": tier,
        "max_seasonal_units": max_seasonal_units,
        "everyday_baseline_weekly_units": baseline,
        "credit_balance_cents": 0,
    })
    return created(ser_retailer(retailer))


@bp.get("/confection/retailer-accounts/<retailer_id>")
def read_retailer(retailer_id):
    authorize(*ALL_ROLES)
    return ok(ser_retailer(get_retailer(retailer_id)))
