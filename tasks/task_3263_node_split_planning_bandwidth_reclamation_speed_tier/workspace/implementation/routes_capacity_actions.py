"""Routes: capacity actions and their lifecycle."""

from flask import Blueprint, request

import calcs
import db
from errors import raise_err
from middleware import body_json, require_roles
from response import paginate, sorted_by_created, success

bp = Blueprint("capacity_actions", __name__)

ACTION_TYPES = {"NODE_SPLIT", "SPECTRUM_RECLAIM", "MID_SPLIT_UPGRADE", "HIGH_SPLIT_UPGRADE"}
UPGRADE_TARGETS = {"MID_SPLIT", "HIGH_SPLIT"}
NEXT_UPGRADE = {"LEGACY": "MID_SPLIT", "MID_SPLIT": "HIGH_SPLIT"}


def _cancel_action_cascade(action):
    """Cancel side effects shared by manual cancel, revise, and supersede."""
    if action["action_type"] == "SPECTRUM_RECLAIM":
        for bid in action.get("target_block_ids") or []:
            block = db.spectrum_blocks.get(bid)
            if block is not None and block["status"] == "RECLAIM_PENDING":
                block["status"] = "VIDEO_ACTIVE"
                db.touch(block)
    for proj in db.node_split_projects.values():
        if proj["capacity_action_id"] == action["id"] and proj["status"] in (
                "PERMIT_REVIEW", "PERMIT_GRANTED", "PERMIT_DENIED", "SCHEDULED"):
            proj["status"] = "CANCELLED"
            db.touch(proj)
    for wave in db.migration_waves.values():
        if wave["capacity_action_id"] == action["id"] and wave["status"] == "PLANNED":
            wave["status"] = "CANCELLED"
            db.touch(wave)


@bp.post("/service-groups/<rid>/capacity-actions")
def create_capacity_action(rid):
    require_roles(["NetworkPlanner"])
    sg = db.get_or_404(db.service_groups, rid)
    data = body_json(
        required=[
            ("action_type", "str", ACTION_TYPES),
            ("expected_service_group_version", "int", None),
        ],
        optional=[
            ("target_block_ids", "array", None),
            ("target_upstream_config", "str", UPGRADE_TARGETS),
            ("note", "str", None),
        ],
    )
    node = db.optical_nodes[sg["optical_node_id"]]
    if node["status"] == "SPLIT_RETIRED":
        raise_err("ERR_NODE_RETIRED")
    # OCC (priority 5)
    if data["expected_service_group_version"] != sg["version"]:
        raise_err("ERR_STALE_VERSION")

    action_type = data["action_type"]
    target_block_ids = data["target_block_ids"]
    target_upstream = data["target_upstream_config"]

    if action_type == "SPECTRUM_RECLAIM":
        if not target_block_ids:
            raise_err("ERR_VALIDATION", "target_block_ids is required for SPECTRUM_RECLAIM")
        blocks = []
        for bid in target_block_ids:
            if not isinstance(bid, str):
                raise_err("ERR_VALIDATION", "target_block_ids entries must be strings")
            b = db.spectrum_blocks.get(bid)
            if b is None or b["optical_node_id"] != node["id"]:
                raise_err("ERR_NOT_FOUND", f"Spectrum block {bid} not found")
            blocks.append(b)
        for b in blocks:
            if b["status"] != "VIDEO_ACTIVE":
                raise_err("ERR_INVALID_STATE", "Target block is not VIDEO_ACTIVE")
        untargeted = [b for b in calcs.node_blocks(node["id"])
                      if b["status"] == "VIDEO_ACTIVE" and b["id"] not in set(target_block_ids)]
        if not untargeted:
            raise_err("ERR_LAST_VIDEO_BLOCK")
    elif action_type in ("MID_SPLIT_UPGRADE", "HIGH_SPLIT_UPGRADE"):
        if target_upstream is None:
            raise_err("ERR_VALIDATION", "target_upstream_config is required for upgrades")
        expected = NEXT_UPGRADE.get(node["upstream_config"])
        expected_type = ("MID_SPLIT_UPGRADE" if expected == "MID_SPLIT" else "HIGH_SPLIT_UPGRADE")
        if expected is None or target_upstream != expected or action_type != expected_type:
            raise_err("ERR_UPGRADE_PATH_INVALID")

    # Supersede existing PROPOSED actions of this service group
    new_id = db.new_id()
    for a in db.capacity_actions.values():
        if a["service_group_id"] == sg["id"] and a["status"] == "PROPOSED":
            a["status"] = "CANCELLED"
            a["superseded_by_id"] = new_id
            db.touch(a)
            _cancel_action_cascade(a)

    action = db.stamp_new({
        "id": new_id,
        "service_group_id": sg["id"],
        "action_type": action_type,
        "origin": "MANUAL",
        "status": "PROPOSED",
        "target_block_ids": target_block_ids,
        "target_upstream_config": target_upstream,
        "superseded_by_id": None,
        "note": data["note"],
    })
    db.capacity_actions[action["id"]] = action
    db.touch(sg)
    return success(action, 201)


@bp.get("/capacity-actions/<rid>")
def get_capacity_action(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.capacity_actions, rid)
    return success(rec, 200)


@bp.get("/service-groups/<rid>/capacity-actions")
def list_capacity_actions(rid):
    require_roles(["Any"])
    sg = db.get_or_404(db.service_groups, rid)
    status_filter = request.args.get("status")
    items = [a for a in db.capacity_actions.values() if a["service_group_id"] == sg["id"]]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.post("/capacity-actions/<rid>/approve")
def approve_capacity_action(rid):
    require_roles(["CapacityEngineer"])
    action = db.get_or_404(db.capacity_actions, rid)
    body_json()
    if action["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", "Only PROPOSED actions can be approved")
    sg = db.service_groups[action["service_group_id"]]
    if sg["posture"] == "SPLIT_RETIRED":
        raise_err("ERR_INVALID_STATE", "Service group is SPLIT_RETIRED")
    action["status"] = "APPROVED"
    db.touch(action)
    return success(action, 200)


@bp.post("/capacity-actions/<rid>/revise")
def revise_capacity_action(rid):
    require_roles(["CapacityEngineer"])
    action = db.get_or_404(db.capacity_actions, rid)
    data = body_json(optional=[("note", "str", None)])
    if action["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only APPROVED actions can be revised")
    action["status"] = "PROPOSED"
    if data.get("note") is not None:
        action["note"] = data["note"]
    _cancel_action_cascade(action)
    db.touch(action)
    return success(action, 200)


@bp.post("/capacity-actions/<rid>/begin")
def begin_capacity_action(rid):
    require_roles(["CapacityEngineer"])
    action = db.get_or_404(db.capacity_actions, rid)
    body_json()
    if action["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only APPROVED actions can be begun")
    sg = db.service_groups[action["service_group_id"]]
    node = db.optical_nodes[sg["optical_node_id"]]
    if action["action_type"] == "SPECTRUM_RECLAIM":
        for bid in action.get("target_block_ids") or []:
            b = db.spectrum_blocks.get(bid)
            if b is None or b["status"] != "VIDEO_ACTIVE":
                raise_err("ERR_INVALID_STATE", "Target block is not VIDEO_ACTIVE")
        untargeted = [b for b in calcs.node_blocks(node["id"])
                      if b["status"] == "VIDEO_ACTIVE"
                      and b["id"] not in set(action["target_block_ids"] or [])]
        if not untargeted:
            raise_err("ERR_LAST_VIDEO_BLOCK")
    elif action["action_type"] == "MID_SPLIT_UPGRADE":
        if node["upstream_config"] != "LEGACY":
            raise_err("ERR_UPGRADE_PATH_INVALID")
    elif action["action_type"] == "HIGH_SPLIT_UPGRADE":
        if node["upstream_config"] != "MID_SPLIT":
            raise_err("ERR_UPGRADE_PATH_INVALID")
    action["status"] = "IN_PROGRESS"
    db.touch(action)
    if action["action_type"] == "SPECTRUM_RECLAIM":
        for bid in action["target_block_ids"] or []:
            b = db.spectrum_blocks[bid]
            b["status"] = "RECLAIM_PENDING"
            b["capacity_mbps"] = 0
            db.touch(b)
        for s in calcs.node_service_groups(node["id"]):
            calcs.recompute_service_group(s)
    return success(action, 200)


@bp.post("/capacity-actions/<rid>/complete")
def complete_capacity_action(rid):
    require_roles(["CapacityEngineer"])
    action = db.get_or_404(db.capacity_actions, rid)
    body_json()
    if action["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Only IN_PROGRESS actions can be completed")
    sg = db.service_groups[action["service_group_id"]]
    node = db.optical_nodes[sg["optical_node_id"]]
    at = action["action_type"]
    if at == "NODE_SPLIT":
        raise_err("ERR_INVALID_STATE", "Node-split actions complete automatically at cutover")
    if at == "SPECTRUM_RECLAIM":
        waves = [w for w in db.migration_waves.values()
                 if w["capacity_action_id"] == action["id"]]
        if not all(w["status"] in ("EXECUTED", "CANCELLED") for w in waves):
            raise_err("ERR_INVALID_STATE", "All waves must be EXECUTED or CANCELLED")
        if not any(w["status"] == "EXECUTED" for w in waves):
            raise_err("ERR_INVALID_STATE", "At least one wave must be EXECUTED")
        for bid in action["target_block_ids"] or []:
            b = db.spectrum_blocks[bid]
            b["status"] = "DATA_ACTIVE"
            b["capacity_mbps"] = (b["mhz"] // 6) * 38
            db.touch(b)
        for s in calcs.node_service_groups(node["id"]):
            calcs.recompute_service_group(s)
    else:  # upgrades
        node["upstream_config"] = action["target_upstream_config"]
        db.touch(node)
        for s in calcs.node_service_groups(node["id"]):
            calcs.recompute_service_group(s)
    action["status"] = "COMPLETED"
    db.touch(action)
    return success(action, 200)


@bp.post("/capacity-actions/<rid>/cancel")
def cancel_capacity_action(rid):
    require_roles(["CapacityEngineer"])
    action = db.get_or_404(db.capacity_actions, rid)
    data = body_json(optional=[("reason", "str", None)])
    if action["status"] in ("COMPLETED", "CANCELLED"):
        raise_err("ERR_INVALID_STATE", "Action is already terminal")
    if action["status"] == "IN_PROGRESS":
        for proj in db.node_split_projects.values():
            if (proj["capacity_action_id"] == action["id"]
                    and proj["status"] == "IN_CONSTRUCTION"):
                raise_err("ERR_INVALID_STATE",
                          "IN_PROGRESS action with an IN_CONSTRUCTION project cannot be cancelled")
    if data.get("reason") is not None:
        action["note"] = data["reason"]
    _cancel_action_cascade(action)
    # restore capacity picture for reclaim cancels from IN_PROGRESS
    if action["action_type"] == "SPECTRUM_RECLAIM":
        sg = db.service_groups[action["service_group_id"]]
        node = db.optical_nodes[sg["optical_node_id"]]
        for s in calcs.node_service_groups(node["id"]):
            calcs.recompute_service_group(s)
    action["status"] = "CANCELLED"
    db.touch(action)
    return success(action, 200)
