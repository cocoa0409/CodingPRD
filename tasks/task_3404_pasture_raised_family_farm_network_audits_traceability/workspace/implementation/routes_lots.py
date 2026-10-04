"""Egg lots, grading, quality holds, carton packing, traceability (PRD 3.6).

GET  /farm-network/lots                       (PO, QM, NM, 200)
GET  /farm-network/lots/{id}                  (PO, QM, NM, 200)
POST /farm-network/lots/{id}/grade            (QualityManager, 200)
POST /farm-network/lots/{id}/resolve-hold     (QualityManager, 200)
POST /farm-network/lots/{id}/cartons          (PlantOperator, 201 -> Carton[])
GET  /farm-network/lots/{id}/cartons          (PO, QM, NM, 200)
GET  /farm-network/cartons/{code}             (all six roles, 200)
"""
from flask import Blueprint, request

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_array, ok_list
from serialize import lot_out, carton_out
from validation import get_body, f_num, f_enum, f_int, pagination

bp = Blueprint("lots", __name__, url_prefix="/farm-network")

_LOT_READ = ("PlantOperator", "QualityManager", "NetworkManager")


@bp.route("/lots", methods=["GET"])
def list_lots():
    uid, role = authenticate()
    authorize(role, _LOT_READ)
    limit, offset = pagination()
    farm_id = request.args.get("farm_id")
    route_id = request.args.get("route_id")
    status = request.args.get("status")
    rows = list(store.lots.values())
    if farm_id is not None:
        rows = [l for l in rows if l["farm_id"] == farm_id]
    if route_id is not None:
        rows = [l for l in rows if l["route_id"] == route_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([lot_out(l) for l in page], limit, offset, total)


@bp.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    uid, role = authenticate()
    authorize(role, _LOT_READ)
    return ok(lot_out(domain.get_lot_or_404(lid)))


@bp.route("/lots/<lid>/grade", methods=["POST"])
def grade_lot(lid):
    uid, role = authenticate()
    authorize(role, ("QualityManager",))
    lot = domain.get_lot_or_404(lid)
    data = get_body()
    score = f_num(data, "quality_score", minimum=0, maximum=100)
    if lot["status"] != "RECEIVED":
        raise ApiError("ERR_LOT_NOT_GRADABLE", 409, "lot is not in RECEIVED")
    # Inclusive thresholds (PRD 3.6): 95.0 -> AA, 85.0 -> A, 70.0 -> B;
    # below 70.0 the grade stays NONE and the lot falls ON_HOLD.
    if score >= C.GRADE_AA_MIN:
        grade, status = "AA", "GRADED"
    elif score >= C.GRADE_A_MIN:
        grade, status = "A", "GRADED"
    elif score >= C.GRADE_B_MIN:
        grade, status = "B", "GRADED"
    else:
        grade, status = "NONE", "ON_HOLD"
    lot["grade"] = grade
    lot["status"] = status
    lot["quality_score"] = score
    lot["graded_at"] = now()
    lot["version"] += 1
    lot["updated_at"] = now()
    return ok(lot_out(lot))


@bp.route("/lots/<lid>/resolve-hold", methods=["POST"])
def resolve_hold(lid):
    uid, role = authenticate()
    authorize(role, ("QualityManager",))
    lot = domain.get_lot_or_404(lid)
    data = get_body()
    disposition = f_enum(data, "disposition", C.HOLD_DISPOSITIONS)
    if lot["status"] != "ON_HOLD":
        raise ApiError("ERR_LOT_NOT_ON_HOLD", 409, "lot is not ON_HOLD")
    if disposition == "RELEASE":
        lot["status"] = "RELEASED"
        lot["grade"] = "B"  # salvage grade regardless of original score
    else:  # REJECT destroys everything that remained
        lot["status"] = "REJECTED"
        lot["destroyed_dozens"] = lot["remaining_dozens"]
        lot["remaining_dozens"] = 0
    lot["version"] += 1
    lot["updated_at"] = now()
    return ok(lot_out(lot))


@bp.route("/lots/<lid>/cartons", methods=["POST"])
def pack_cartons(lid):
    uid, role = authenticate()
    authorize(role, ("PlantOperator",))
    lot = domain.get_lot_or_404(lid)
    data = get_body()
    count = f_int(data, "carton_count", minimum=1)
    pack_size = f_enum(data, "pack_size", C.PACK_SIZES)
    if lot["status"] not in ("GRADED", "RELEASED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a GRADED or RELEASED lot can be packed")
    if count > lot["remaining_dozens"]:
        raise ApiError("ERR_INSUFFICIENT_LOT_DOZENS", 422,
                       "carton_count exceeds the lot's remaining_dozens")
    ts = now()
    farm = store.farms.get(lot["farm_id"])
    created = []
    for _ in range(count):
        code = "%s-C%03d" % (lot["lot_code"], lot["_carton_seq"])
        lot["_carton_seq"] += 1
        carton = {
            "id": domain.new_id(),
            "carton_code": code,
            "lot_id": lot["id"],
            "pack_size": pack_size,
            "dozens": C.DOZENS_PER_CARTON,
            "source_farm_id": farm["id"] if farm else lot["farm_id"],
            "source_farm_name": farm["name"] if farm else None,
            "packed_at": ts,
            "created_at": ts,
            "_seq": store.next_seq(),
        }
        store.cartons[code] = carton
        created.append(carton)
    lot["remaining_dozens"] -= count
    lot["packed_dozens"] += count
    if lot["remaining_dozens"] == 0:
        lot["status"] = "PACKED"
    lot["version"] += 1
    lot["updated_at"] = ts
    return ok_array([carton_out(c) for c in created], 201)


@bp.route("/lots/<lid>/cartons", methods=["GET"])
def list_cartons(lid):
    uid, role = authenticate()
    authorize(role, _LOT_READ)
    lot = domain.get_lot_or_404(lid)
    limit, offset = pagination()
    rows = [c for c in store.cartons.values() if c["lot_id"] == lot["id"]]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([carton_out(c) for c in page], limit, offset, total)


@bp.route("/cartons/<code>", methods=["GET"])
def get_carton(code):
    # The one read open to every one of the six roles (PRD 3.6).
    uid, role = authenticate()
    carton = domain.get_carton_or_404(code)
    return ok(carton_out(carton))
