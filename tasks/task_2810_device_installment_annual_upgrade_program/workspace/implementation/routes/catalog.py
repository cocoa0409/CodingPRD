"""Device catalog (PRD 3.1)."""
from flask import Blueprint

import db
import lookups
import response
import serialize
import validate
from constants import (
    DEFAULT_RESERVATION_CAPACITY, ROLE_COLLECTIONS_OFFICER, ROLE_CREDIT_UNDERWRITER,
    ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
)
from errors import ApiError
from middleware import require_roles

bp = Blueprint("catalog", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_CREDIT_UNDERWRITER,
              ROLE_SERVICE_TECHNICIAN, ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)


@bp.post("/device-models")
def create_device_model():
    require_roles(ROLE_PROGRAM_ADMIN)
    payload = validate.body()
    sku = validate.req_str(payload, "sku")
    display_name = validate.req_str(payload, "display_name")
    retail_price_cents = validate.req_int(payload, "retail_price_cents", minimum=1)
    premium_cents = validate.req_int(payload, "monthly_protection_premium_cents", minimum=0)
    base_credit_cents = validate.req_int(payload, "trade_in_base_credit_cents", minimum=0)
    generation_year = validate.req_int(payload, "generation_year")
    capacity = validate.opt_int(payload, "concurrent_reservation_capacity",
                                default=DEFAULT_RESERVATION_CAPACITY, minimum=0)
    active = validate.opt_bool(payload, "active", default=True)
    if db.find_one(db.device_models, sku=sku) is not None:
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "sku is already published.")
    record = db.insert(db.device_models, {
        "sku": sku,
        "display_name": display_name,
        "retail_price_cents": retail_price_cents,
        "monthly_protection_premium_cents": premium_cents,
        "trade_in_base_credit_cents": base_credit_cents,
        "concurrent_reservation_capacity": capacity,
        "generation_year": generation_year,
        "active": active,
    })
    return response.object_response(serialize.device_model(record), 201)


@bp.get("/device-models")
def list_device_models():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    active = validate.query_bool("active")
    generation_year = validate.query_int("generation_year")
    rows = db.values(db.device_models)
    if active is not None:
        rows = [r for r in rows if r["active"] == active]
    if generation_year is not None:
        rows = [r for r in rows if r["generation_year"] == generation_year]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.device_model(r) for r in page],
                                  limit, offset, total)


@bp.get("/device-models/<model_id>")
def read_device_model(model_id):
    require_roles(*READ_ROLES)
    record = lookups.device_model(model_id)
    return response.object_response(serialize.device_model(record))
