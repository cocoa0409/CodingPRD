"""Territory routes: create, get, list-for-sale."""
from flask import Blueprint

import auth
import store
import validators as V
from constants import ROLE_COMPANY_ADMIN
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, raise_err,
)
from response import ok_object, body

bp = Blueprint("territories", __name__)

ADMIN = (ROLE_COMPANY_ADMIN,)


@bp.route("/territories", methods=["POST"])
def create_territory():
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    data = body()
    area_code = V.get_str(data, "area_code")
    list_price = V.get_int(data, "list_price_cents", minimum=1)
    for existing in store.all_of("territories"):
        if existing["area_code"] == area_code:
            raise_err(ERR_INVALID_REQUEST,
                      f"area_code {area_code} is already registered")
    territory = store.insert("territories", {
        "area_code": area_code,
        "list_price_cents": list_price,
        "status": "AVAILABLE",
    })
    return ok_object(territory, 201)


@bp.route("/territories/<rid>", methods=["GET"])
def get_territory(rid):
    auth.caller()
    territory = store.get("territories", rid)
    if territory is None:
        raise_err(ERR_NOT_FOUND, "Territory not found")
    return ok_object(territory)


@bp.route("/territories/<rid>/list-for-sale", methods=["POST"])
def list_for_sale(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    territory = store.get("territories", rid)
    if territory is None:
        raise_err(ERR_NOT_FOUND, "Territory not found")
    if territory["status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE,
                  "Only an AVAILABLE territory can be listed for sale")
    territory["status"] = "LISTED"
    store.touch(territory)
    return ok_object(territory)
