"""Product master endpoints (PRD 3.1)."""
from flask import Blueprint

import envelope
import serialize
import store
from auth import require_auth
from constants import MARKET_SCOPES, MOLECULE_TYPES
from errors import err
from validate import body, must_get, opt_list, req_bool, req_enum, req_int, req_num, req_str

bp = Blueprint("products", __name__)


@bp.route("/products", methods=["POST"])
def create_product():
    require_auth(("PlatformAdmin",))
    d = body()
    code = req_str(d, "product_code")
    mol = req_enum(d, "molecule_type", MOLECULE_TYPES)
    scope = req_enum(d, "market_scope", MARKET_SCOPES)
    cold = req_bool(d, "requires_cold_chain")
    tmin = req_num(d, "min_storage_temp_c")
    tmax = req_num(d, "max_storage_temp_c")
    if not tmax > tmin:
        err("ERR_INVALID_REQUEST", "max_storage_temp_c must be > min_storage_temp_c")
    shelf = req_int(d, "shelf_life_hours", min_value=1)
    changeover = req_int(d, "changeover_hours", min_value=0)
    turnaround = req_int(d, "same_product_turnaround_hours", min_value=0)
    materials = opt_list(d, "required_materials")
    for entry in materials:
        if not isinstance(entry, dict):
            err("ERR_INVALID_REQUEST", "required_materials entries must be objects")
        req_str(entry, "material_name")
        req_num(entry, "base_quantity")
        req_bool(entry, "is_single_source")
    for other in store.all_recs("products"):
        if other["product_code"] == code:
            err("ERR_INVALID_REQUEST", "product_code must be unique")
    rec = store.create_rec("products", {
        "product_code": code,
        "molecule_type": mol,
        "market_scope": scope,
        "requires_cold_chain": cold,
        "min_storage_temp_c": tmin,
        "max_storage_temp_c": tmax,
        "shelf_life_hours": shelf,
        "changeover_hours": changeover,
        "same_product_turnaround_hours": turnaround,
        "required_materials": [dict(e) for e in materials],
    })
    return envelope.ok(serialize.product(rec), 201)


@bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    require_auth(("Any",))
    return envelope.ok(serialize.product(must_get("product", pid)), 200)
