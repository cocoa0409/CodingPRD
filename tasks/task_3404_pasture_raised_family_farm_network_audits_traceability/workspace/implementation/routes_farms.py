"""Farm recruitment and lifecycle (PRD 3.1).

POST /farm-network/farms                     (NetworkManager, 201)
GET  /farm-network/farms/{id}                (NM, QM, PO, PA, 200)
PATCH /farm-network/farms/{id}               (NetworkManager, 200)
POST /farm-network/farms/{id}/activate       (NetworkManager, 200)
POST /farm-network/farms/{id}/reinstate      (NetworkManager, 200)
POST /farm-network/farms/{id}/remove         (NetworkManager, 200)
"""
from flask import Blueprint

import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok
from serialize import farm_out
from validation import MISSING, get_body, f_str, f_int, f_num

bp = Blueprint("farms", __name__, url_prefix="/farm-network")

_NM = ("NetworkManager",)


@bp.route("/farms", methods=["POST"])
def create_farm():
    uid, role = authenticate()
    authorize(role, _NM)
    data = get_body()
    name = f_str(data, "name")
    region = f_str(data, "region")
    pasture = f_num(data, "pasture_sqft", minimum=0, min_exclusive=True)
    barn = f_num(data, "barn_sqft", minimum=0, min_exclusive=True)
    nests = f_int(data, "nest_box_count", minimum=0)
    birds = f_int(data, "declared_bird_count", minimum=1)
    ts = now()
    farm = {
        "id": domain.new_id(),
        "name": name,
        "region": region,
        "pasture_sqft": pasture,
        "barn_sqft": barn,
        "nest_box_count": nests,
        "declared_bird_count": birds,
        "status": "ONBOARDING",
        "effective_bird_capacity": domain.compute_effective_bird_capacity(pasture, barn, nests),
        "last_passed_audit_at": None,
        "removal_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.farms[farm["id"]] = farm
    return ok(farm_out(farm), 201)


@bp.route("/farms/<fid>", methods=["GET"])
def get_farm(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "QualityManager", "PlantOperator", "PlatformAdmin"))
    farm = domain.get_farm_or_404(fid)
    return ok(farm_out(farm))


@bp.route("/farms/<fid>", methods=["PATCH"])
def patch_farm(fid):
    uid, role = authenticate()
    authorize(role, _NM)
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    # Body well-formedness (priority 6) is validated before state (priority 7).
    updates = {}
    for field in ("name", "region"):
        v = f_str(data, field, required=False)
        if v is not MISSING:
            updates[field] = v
    for field in ("pasture_sqft", "barn_sqft"):
        v = f_num(data, field, required=False, minimum=0, min_exclusive=True)
        if v is not MISSING:
            updates[field] = v
    v = f_int(data, "nest_box_count", required=False, minimum=0)
    if v is not MISSING:
        updates["nest_box_count"] = v
    v = f_int(data, "declared_bird_count", required=False, minimum=1)
    if v is not MISSING:
        updates["declared_bird_count"] = v
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    if farm["status"] not in ("ONBOARDING", "PROBATION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "farm may only be amended while ONBOARDING or PROBATION")
    farm.update(updates)
    if any(k in updates for k in ("pasture_sqft", "barn_sqft", "nest_box_count")):
        farm["effective_bird_capacity"] = domain.compute_effective_bird_capacity(
            farm["pasture_sqft"], farm["barn_sqft"], farm["nest_box_count"])
    farm["version"] += 1
    farm["updated_at"] = now()
    return ok(farm_out(farm))


@bp.route("/farms/<fid>/activate", methods=["POST"])
def activate_farm(fid):
    uid, role = authenticate()
    authorize(role, _NM)
    farm = domain.get_farm_or_404(fid)
    # State legality (priority 7)
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    if farm["status"] != "ONBOARDING":
        raise ApiError("ERR_INVALID_STATE", 409, "only an ONBOARDING farm can be activated")
    # Certification gate (priority 9)
    if domain.derive_certification_status(farm) != "CERTIFIED":
        raise ApiError("ERR_CERTIFICATION_REQUIRED", 422,
                       "activation requires certification_status CERTIFIED")
    # Covering ACTIVE contract (priority 10)
    today = now().date()
    if domain.find_covering_contract(farm["id"], today, require_active=True) is None:
        raise ApiError("ERR_CONTRACT_REQUIRED", 422,
                       "no ACTIVE contract covers the current date")
    # Capacity (priority 13); equality permitted
    if farm["declared_bird_count"] > farm["effective_bird_capacity"]:
        raise ApiError("ERR_BIRD_CAPACITY_INSUFFICIENT", 422,
                       "declared_bird_count exceeds effective_bird_capacity")
    farm["status"] = "ACTIVE"
    farm["version"] += 1
    farm["updated_at"] = now()
    return ok(farm_out(farm))


@bp.route("/farms/<fid>/reinstate", methods=["POST"])
def reinstate_farm(fid):
    uid, role = authenticate()
    authorize(role, _NM)
    farm = domain.get_farm_or_404(fid)
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    if farm["status"] not in ("PROBATION", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a PROBATION or SUSPENDED farm can be reinstated")
    farm_audit_ids = {a["id"] for a in store.audits.values() if a["farm_id"] == farm["id"]}
    for ca in store.corrective_actions.values():
        if ca["audit_id"] in farm_audit_ids and ca["status"] in ("OPEN", "OVERDUE", "SUBMITTED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "farm has non-terminal corrective actions")
    for inc in store.incidents.values():
        if inc["farm_id"] == farm["id"] and inc["status"] == "REPORTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "farm has an unresolved welfare incident")
    farm["status"] = "ACTIVE"
    farm["version"] += 1
    farm["updated_at"] = now()
    return ok(farm_out(farm))


@bp.route("/farms/<fid>/remove", methods=["POST"])
def remove_farm(fid):
    uid, role = authenticate()
    authorize(role, _NM)
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    reason = f_str(data, "reason")
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is already REMOVED")
    domain.run_removal_cascade(farm, reason)
    return ok(farm_out(farm))
