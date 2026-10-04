"""Facilities and filling lines."""
from flask import Blueprint

from store import db
from helpers import (
    body, created, find, init_common, list_ok, ok, require_roles,
    v_bool, v_enum, v_int, v_str,
)
from serializers import facility_out, line_out

bp = Blueprint("facilities", __name__)

FACILITY_KINDS = ("OWNED", "PARTNER")
SUPPORTED_ROASTS = ("LIGHT", "MEDIUM", "DARK", "UNIVERSAL")
MATERIAL_CAPS = ("CONVENTIONAL", "RECYCLABLE", "BOTH")


@bp.post("/facilities")
@require_roles("OperationsDirector")
def create_facility():
    b = body()
    facility = init_common({
        "name": v_str(b, "name"),
        "kind": v_enum(b, "kind", FACILITY_KINDS),
        "region": v_str(b, "region"),
    })
    db["facilities"][facility["id"]] = facility
    return created(facility_out(facility))


@bp.get("/facilities/<rid>")
@require_roles("OperationsDirector", "ProductionPlanner")
def get_facility(rid):
    return ok(facility_out(find("facilities", rid)))


@bp.post("/facilities/<rid>/filling-lines")
@require_roles("OperationsDirector")
def create_line(rid):
    facility = find("facilities", rid)
    b = body()
    line = init_common({
        "facility_id": facility["id"],
        "line_code": v_str(b, "line_code"),
        "supported_roast": v_enum(b, "supported_roast", SUPPORTED_ROASTS),
        "supports_flavored": v_bool(b, "supports_flavored"),
        "material_capability": v_enum(b, "material_capability", MATERIAL_CAPS),
        "capacity_pods_per_day": v_int(b, "capacity_pods_per_day"),
        "changeover_hours": v_int(b, "changeover_hours"),
    })
    db["lines"][line["id"]] = line
    return created(line_out(line))


@bp.get("/facilities/<rid>/filling-lines")
@require_roles("OperationsDirector", "ProductionPlanner")
def list_lines(rid):
    facility = find("facilities", rid)
    items = [l for l in db["lines"].values() if l["facility_id"] == facility["id"]]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return list_ok(items, line_out)
