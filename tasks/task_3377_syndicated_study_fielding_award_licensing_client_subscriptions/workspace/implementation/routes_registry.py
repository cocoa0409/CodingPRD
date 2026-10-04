"""Client and Brand registry endpoints."""
from flask import Blueprint

from db import store
from envelope import ok_object, paginated
from errors import fail
from middleware import require
from records import new_record, ser_brand, ser_client
from validation import Body

bp = Blueprint("registry", __name__, url_prefix="/research")

BRAND_READ_ROLES = (
    "StudyAdmin",
    "MethodologyLead",
    "FieldOps",
    "AwardsOfficer",
    "LicensingManager",
    "ClientUser",
)


@bp.post("/clients")
@require("StudyAdmin", "LicensingManager")
def create_client():
    b = Body()
    name = b.str_("name")
    client_type = b.enum_("client_type", ("BRAND", "AGENCY"))
    country = b.str_("country")
    brand_id = b.str_("brand_id", required=False)
    if brand_id is not None and brand_id not in store.brands:
        fail("ERR_NOT_FOUND", "brand_id does not reference an existing brand")
    b.finalize()
    rec = new_record()
    rec.update({
        "name": name,
        "client_type": client_type,
        "country": country,
        "brand_id": brand_id,
    })
    store.clients[rec["id"]] = rec
    return ok_object(ser_client(rec), 201)


@bp.get("/brands/<bid>/clients")
@require("StudyAdmin", "LicensingManager")
def list_brand_clients(bid):
    brand = store.brands.get(bid)
    if brand is None:
        fail("ERR_NOT_FOUND", "Brand not found")
    items = [c for c in store.clients.values() if c["brand_id"] == bid]
    return paginated(items, ser_client)


@bp.post("/brands")
@require("StudyAdmin")
def create_brand():
    b = Body()
    name = b.str_("name")
    industry = b.str_("industry_code")
    b.finalize()
    rec = new_record()
    rec.update({"name": name, "industry_code": industry})
    store.brands[rec["id"]] = rec
    return ok_object(ser_brand(rec), 201)


@bp.get("/brands/<bid>")
@require(*BRAND_READ_ROLES)
def get_brand(bid):
    brand = store.brands.get(bid)
    if brand is None:
        fail("ERR_NOT_FOUND", "Brand not found")
    return ok_object(ser_brand(brand))
