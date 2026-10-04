"""Master data endpoints: sites, bioreactor trains, material lots (PRD 3.1)."""
from decimal import Decimal
from flask import Blueprint, request

import envelope
import serialize
import store
from auth import require_auth
from constants import AUTHORITIES, MOLECULE_TYPES
from errors import err
from validate import (
    body, must_get, paginate, req_bool, req_enum, req_int, req_list, req_num,
    req_str,
)

bp = Blueprint("master", __name__)


@bp.route("/sites", methods=["POST"])
def create_site():
    require_auth(("PlatformAdmin",))
    d = body()
    name = req_str(d, "name")
    region = req_str(d, "region")
    cap_h = req_int(d, "monthly_capacity_hours", min_value=1)
    cap_u = req_int(d, "cold_storage_capacity_units", min_value=1)
    auths = req_list(d, "licensed_authorities")
    for a in auths:
        if a not in AUTHORITIES:
            err("ERR_INVALID_REQUEST", f"licensed_authorities member {a} invalid")
    rec = store.create_rec("sites", {
        "name": name,
        "region": region,
        "monthly_capacity_hours": cap_h,
        "cold_storage_capacity_units": cap_u,
        "licensed_authorities": list(auths),
        "release_posture": "CLEAR",
        "open_critical_deviation_count": 0,
        "open_critical_finding_count": 0,
    })
    return envelope.ok(serialize.site(rec), 201)


@bp.route("/sites/<sid>", methods=["GET"])
def get_site(sid):
    require_auth(("Any",))
    return envelope.ok(serialize.site(must_get("site", sid)), 200)


@bp.route("/sites/<sid>/trains", methods=["POST"])
def create_train(sid):
    require_auth(("PlatformAdmin",))
    site_rec = must_get("site", sid)
    d = body()
    code = req_str(d, "train_code")
    cap = req_int(d, "capacity_liters", min_value=1)
    types = req_list(d, "supported_molecule_types", min_len=1)
    for t in types:
        if t not in MOLECULE_TYPES:
            err("ERR_INVALID_REQUEST", f"supported_molecule_types member {t} invalid")
    for other in store.all_recs("trains"):
        if other["site_id"] == site_rec["id"] and other["train_code"] == code:
            err("ERR_INVALID_REQUEST", "train_code must be unique within the site")
    rec = store.create_rec("trains", {
        "site_id": site_rec["id"],
        "train_code": code,
        "capacity_liters": cap,
        "supported_molecule_types": list(types),
    })
    return envelope.ok(serialize.train(rec), 201)


@bp.route("/sites/<sid>/trains", methods=["GET"])
def list_trains(sid):
    require_auth(("Any",))
    must_get("site", sid)
    recs = [t for t in store.all_recs("trains") if t["site_id"] == sid]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.train(t) for t in page], total, limit, offset)


@bp.route("/sites/<sid>/materials", methods=["POST"])
def create_material(sid):
    require_auth(("PlatformAdmin",))
    site_rec = must_get("site", sid)
    d = body()
    name = req_str(d, "material_name")
    single = req_bool(d, "is_single_source")
    qty = req_num(d, "quantity")
    rec = store.create_rec("materials", {
        "site_id": site_rec["id"],
        "material_name": name,
        "is_single_source": single,
        "quantity_available": Decimal(str(qty)),
        "status": "AVAILABLE",
    })
    return envelope.ok(serialize.material(rec), 201)


@bp.route("/sites/<sid>/materials", methods=["GET"])
def list_materials(sid):
    require_auth(("Any",))
    must_get("site", sid)
    recs = [m for m in store.all_recs("materials") if m["site_id"] == sid]
    name_f = request.args.get("material_name")
    status_f = request.args.get("status")
    if name_f is not None:
        recs = [m for m in recs if m["material_name"] == name_f]
    if status_f is not None:
        recs = [m for m in recs if m["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.material(m) for m in page], total, limit, offset)


@bp.route("/materials/<mid>/hold", methods=["POST"])
def hold_material(mid):
    require_auth(("PlatformAdmin",))
    rec = must_get("material", mid)
    d = body()
    q = req_bool(d, "quarantined")
    rec["status"] = "QUARANTINED" if q else "AVAILABLE"
    store.touch(rec)
    return envelope.ok(serialize.material(rec), 200)
