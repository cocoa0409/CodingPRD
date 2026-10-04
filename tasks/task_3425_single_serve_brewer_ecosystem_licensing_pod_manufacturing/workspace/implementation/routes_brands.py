"""Brand registration."""
from flask import Blueprint

from store import db
from helpers import body, created, init_common, v_enum, v_str, require_roles
from serializers import brand_out

bp = Blueprint("brands", __name__)

BRAND_KINDS = ("PLATFORM_OWNED", "LICENSED", "UNLICENSED_COMPATIBLE")


@bp.post("/brands")
@require_roles("PlatformAdmin")
def create_brand():
    b = body()
    brand = init_common({
        "name": v_str(b, "name"),
        "kind": v_enum(b, "kind", BRAND_KINDS),
        "home_region": v_str(b, "home_region"),
    })
    db["brands"][brand["id"]] = brand
    return created(brand_out(brand))
