"""Hazard-tree endpoints."""
from flask import Blueprint, request

import calc
import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, actor_id, endpoint
from errors import ApiError

bp = Blueprint("hazard", __name__)


def _score(tree, circuit):
    strike, score, removal = calc.hazard_risk(
        tree["species"], tree["defect_class"], tree["height_ft"], tree["offset_ft"],
        circuit["voltage_class"])
    tree["strike_potential"] = strike
    tree["risk_score"] = score
    tree["removal_required"] = removal


@bp.post("/vm/hazard-trees")
@endpoint(["CertifiedArborist"])
def create_tree():
    data = V.body()
    circuit = V.body_fk(data, "circuit_id", store.circuits, "ERR_CIRCUIT_NOT_FOUND")
    work_order = V.body_fk(data, "work_order_id", store.work_orders,
                           "ERR_WORK_ORDER_NOT_FOUND")
    if circuit is None:
        V.require(data, "circuit_id")
    species = V.as_enum(data, "species", C.SPECIES)
    defect_class = V.as_enum(data, "defect_class", C.DEFECT_CLASSES)
    height = V.as_number(data, "height_ft", minimum=0, exclusive_min=True)
    offset = V.as_number(data, "offset_ft", minimum=0)

    rec = store.new_record()
    rec.update({
        "circuit_id": circuit["id"],
        "work_order_id": work_order["id"] if work_order else None,
        "customer_notification_id": None,
        "species": species,
        "defect_class": defect_class,
        "height_ft": height,
        "offset_ft": offset,
        "strike_potential": False,
        "risk_score": 0.00,
        "removal_required": False,
        "identified_by_user_id": actor_id(),
        "assessed_by_user_id": None,
        "status": "IDENTIFIED",
    })
    _score(rec, circuit)
    store.hazard_trees[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/hazard-trees/<tid>/assess")
@endpoint(["CertifiedArborist"])
def assess_tree(tid):
    known = store.hazard_trees.get(tid)
    if known is not None and known.get("identified_by_user_id") == actor_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the assessing arborist may not be the identifying arborist")
    tree = V.find(store.hazard_trees, tid, "ERR_HAZARD_TREE_NOT_FOUND")
    data = V.body()
    note = V.body_fk(data, "customer_notification_id", store.customer_notifications,
                     "ERR_NOTIFICATION_NOT_FOUND")
    defect_class = V.as_enum(data, "defect_class", C.DEFECT_CLASSES, required=False)
    height = V.as_number(data, "height_ft", required=False, minimum=0, exclusive_min=True)
    offset = V.as_number(data, "offset_ft", required=False, minimum=0)
    services.require_state(tree, "hazard_tree", ["IDENTIFIED", "DEFERRED"])

    if defect_class is not None:
        tree["defect_class"] = defect_class
    if height is not None:
        tree["height_ft"] = height
    if offset is not None:
        tree["offset_ft"] = offset
    if note is not None:
        tree["customer_notification_id"] = note["id"]
    tree["assessed_by_user_id"] = actor_id()
    tree["status"] = "ASSESSED"
    _score(tree, store.circuits.get(tree["circuit_id"]))
    store.touch(tree)
    return envelope.ok(store.public(tree))


@bp.post("/vm/hazard-trees/<tid>/decision")
@endpoint(["UtilityForester"])
def decide_tree(tid):
    tree = V.find(store.hazard_trees, tid, "ERR_HAZARD_TREE_NOT_FOUND")
    data = V.body()
    outcome = V.as_enum(data, "outcome", ["APPROVE_REMOVAL", "DECLINE", "DEFER"])
    services.require_state(tree, "hazard_tree", ["ASSESSED"])

    if outcome == "APPROVE_REMOVAL":
        if not tree.get("strike_potential"):
            raise ApiError("ERR_NO_STRIKE_POTENTIAL", "the tree cannot reach the line")
        if calc.dec(tree.get("risk_score") or 0) < calc.REMOVAL_RISK_THRESHOLD:
            raise ApiError("ERR_HAZARD_RISK_BELOW_THRESHOLD",
                           "risk_score is below the removal threshold")
        if calc.dec(tree.get("offset_ft") or 0) > 0:
            note = store.customer_notifications.get(tree.get("customer_notification_id"))
            if note is None or note.get("status") != "ACKNOWLEDGED":
                raise ApiError("ERR_OFF_ROW_CONSENT_REQUIRED",
                               "off-right-of-way removal requires acknowledged consent")
        tree["status"] = "APPROVED_REMOVAL"
    elif outcome == "DECLINE":
        tree["status"] = "DECLINED"
    else:
        tree["status"] = "DEFERRED"
    store.touch(tree)
    return envelope.ok(store.public(tree))


@bp.post("/vm/hazard-trees/<tid>/remove")
@endpoint(["CrewForeman"])
def remove_tree(tid):
    known = store.hazard_trees.get(tid)
    if known is not None:
        holds = False
        for assignment in services.order_assignments(known.get("work_order_id")):
            if (assignment.get("status") == "ACTIVE"
                    and assignment.get("crew_id") == actor_id()):
                holds = True
                break
        if not holds:
            raise ApiError("ERR_NOT_CREW_OWNER",
                           "the acting crew holds no ACTIVE booking on this span")
    tree = V.find(store.hazard_trees, tid, "ERR_HAZARD_TREE_NOT_FOUND")
    services.require_state(tree, "hazard_tree", ["APPROVED_REMOVAL"])
    work_order = store.work_orders.get(tree.get("work_order_id"))
    if work_order is None or work_order.get("execution_status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "the span is not in progress")
    tree["status"] = "REMOVED"
    store.touch(tree)
    return envelope.ok(store.public(tree))


@bp.get("/vm/hazard-trees/<tid>")
@endpoint(ALL_ROLES)
def get_tree(tid):
    return envelope.ok(store.public(
        V.find(store.hazard_trees, tid, "ERR_HAZARD_TREE_NOT_FOUND")))


@bp.get("/vm/hazard-trees")
@endpoint(ALL_ROLES)
def list_trees():
    return envelope.list_response(list(store.hazard_trees.values()), {
        "circuit_id": request.args.get("circuit_id"),
        "work_order_id": request.args.get("work_order_id"),
        "customer_notification_id": request.args.get("customer_notification_id"),
        "status": request.args.get("status"),
    })
