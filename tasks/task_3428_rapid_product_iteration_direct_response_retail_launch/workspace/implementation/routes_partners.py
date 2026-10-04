"""SourcingManager domain: factory partners and the terminal suspend cascade."""

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from errors import ApiError
from serializers import ser_partner
from services import get_or_404, suspend_partner_cascade
from state import DB, base_fields, bump
from util import body, ok_object, req_int, req_string

bp = Blueprint("partners", __name__)

SOURCING = ("SourcingManager",)


@bp.post("/factory-partners")
def create_partner():
    require_roles(SOURCING)
    data = body()
    name = req_string(data, "name")
    capacity = req_int(data, "capacity_units_total", min_v=1)
    p = base_fields()
    p.update({
        "name": name,
        "capacity_units_total": capacity,
        "status": "ACTIVE",
    })
    DB.partners[p["id"]] = p
    return ok_object(ser_partner(p), 201)


@bp.get("/factory-partners/<pid>")
def get_partner(pid):
    require_roles(ALL_ROLES)
    return ok_object(ser_partner(get_or_404(DB.partners, pid, "ERR_PARTNER_NOT_FOUND")))


@bp.post("/factory-partners/<pid>/suspend")
def suspend_partner(pid):
    require_roles(SOURCING)
    p = get_or_404(DB.partners, pid, "ERR_PARTNER_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "SUSPENDED is terminal")
    p["status"] = "SUSPENDED"
    bump(p)
    suspend_partner_cascade(p)
    return ok_object(ser_partner(p))
