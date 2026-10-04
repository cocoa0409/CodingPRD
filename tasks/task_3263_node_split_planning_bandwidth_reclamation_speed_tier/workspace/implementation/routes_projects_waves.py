"""Routes: node-split projects and migration waves."""

from datetime import timedelta

from flask import Blueprint

import calcs
import db
from errors import raise_err
from middleware import body_json, require_roles
from response import paginate, sorted_by_created, success

bp = Blueprint("projects_waves", __name__)

DECISIONS = {"GRANTED", "DENIED"}


def _action_node(action):
    sg = db.service_groups[action["service_group_id"]]
    return sg, db.optical_nodes[sg["optical_node_id"]]


# ------------------------------------------------------------ Node split projects

@bp.post("/capacity-actions/<rid>/node-split-projects")
def create_node_split_project(rid):
    require_roles(["NetworkPlanner"])
    action = db.get_or_404(db.capacity_actions, rid)
    data = body_json(
        required=[
            ("child_count", "int", None),
            ("min_homes_per_child", "int", None),
            ("max_homes_per_child", "int", None),
        ],
    )
    if action["action_type"] != "NODE_SPLIT":
        raise_err("ERR_ACTION_TYPE_MISMATCH")
    if data["child_count"] < 2 or data["child_count"] > 4:
        raise_err("ERR_VALIDATION", "child_count must be between 2 and 4")
    if data["min_homes_per_child"] < 0 or data["max_homes_per_child"] < data["min_homes_per_child"]:
        raise_err("ERR_VALIDATION", "invalid min/max homes per child")
    rec = db.stamp_new({
        "id": db.new_id(),
        "capacity_action_id": action["id"],
        "child_count": data["child_count"],
        "min_homes_per_child": data["min_homes_per_child"],
        "max_homes_per_child": data["max_homes_per_child"],
        "status": "PERMIT_REVIEW",
        "window_start": None,
        "window_end": None,
        "child_allocations": None,
        "child_node_id": None,
        "child_service_group_ids": [],
    })
    db.node_split_projects[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/node-split-projects/<rid>")
def get_node_split_project(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.node_split_projects, rid)
    return success(rec, 200)


@bp.get("/capacity-actions/<rid>/node-split-projects")
def list_node_split_projects(rid):
    require_roles(["Any"])
    action = db.get_or_404(db.capacity_actions, rid)
    items = sorted_by_created(
        [p for p in db.node_split_projects.values() if p["capacity_action_id"] == action["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.post("/node-split-projects/<rid>/adjudicate-permit")
def adjudicate_permit(rid):
    require_roles(["FranchiseAdmin"])
    proj = db.get_or_404(db.node_split_projects, rid)
    data = body_json(required=[("decision", "str", DECISIONS)])
    if proj["status"] != "PERMIT_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only PERMIT_REVIEW projects can be adjudicated")
    proj["status"] = "PERMIT_GRANTED" if data["decision"] == "GRANTED" else "PERMIT_DENIED"
    db.touch(proj)
    return success(proj, 200)


@bp.post("/node-split-projects/<rid>/refile-permit")
def refile_permit(rid):
    require_roles(["FranchiseAdmin"])
    proj = db.get_or_404(db.node_split_projects, rid)
    body_json()
    if proj["status"] != "PERMIT_DENIED":
        raise_err("ERR_INVALID_STATE", "Only PERMIT_DENIED projects can be refiled")
    proj["status"] = "PERMIT_REVIEW"
    db.touch(proj)
    return success(proj, 200)


@bp.post("/node-split-projects/<rid>/schedule")
def schedule_project(rid):
    require_roles(["NetworkPlanner"])
    proj = db.get_or_404(db.node_split_projects, rid)
    data = body_json(
        required=[
            ("window_start", "datetime", None),
            ("window_end", "datetime", None),
            ("expected_node_split_project_version", "int", None),
        ],
    )
    # Lifecycle guard first: permit must be granted
    if proj["status"] != "PERMIT_GRANTED":
        raise_err("ERR_PERMIT_NOT_GRANTED")
    # OCC
    if data["expected_node_split_project_version"] != proj["version"]:
        raise_err("ERR_STALE_VERSION")
    ws = db.parse_dt(data["window_start"])
    we = db.parse_dt(data["window_end"])
    if ws >= we:
        raise_err("ERR_VALIDATION", "window_start must be strictly before window_end")

    action = db.capacity_actions[proj["capacity_action_id"]]
    sg, node = _action_node(action)
    fa = db.franchise_areas[node["franchise_area_id"]]

    # Half-open overlap against other SCHEDULED/IN_CONSTRUCTION projects in the area
    for other in db.node_split_projects.values():
        if other["id"] == proj["id"] or other["status"] not in ("SCHEDULED", "IN_CONSTRUCTION"):
            continue
        if other["window_start"] is None:
            continue
        o_action = db.capacity_actions.get(other["capacity_action_id"])
        if o_action is None:
            continue
        o_sg = db.service_groups[o_action["service_group_id"]]
        o_node = db.optical_nodes[o_sg["optical_node_id"]]
        if o_node["franchise_area_id"] != fa["id"]:
            continue
        ows = db.parse_dt(other["window_start"])
        owe = db.parse_dt(other["window_end"])
        # half-open overlap: ws < owe and ows < we
        if ws < owe and ows < we:
            raise_err("ERR_WINDOW_CONFLICT", "Construction window overlaps another project window")

    # Closed-interval blackout intersection: [ws, we] vs [bs, be]
    for bw in fa.get("blackout_windows") or []:
        bs = db.parse_dt(bw["start"])
        be = db.parse_dt(bw["end"])
        if ws <= be and bs <= we:
            raise_err("ERR_WINDOW_CONFLICT", "Construction window intersects a blackout window")

    proj["window_start"] = data["window_start"]
    proj["window_end"] = data["window_end"]
    proj["status"] = "SCHEDULED"
    db.touch(proj)
    return success(proj, 200)


@bp.post("/node-split-projects/<rid>/begin-construction")
def begin_construction(rid):
    require_roles(["FieldOpsCoordinator"])
    proj = db.get_or_404(db.node_split_projects, rid)
    body_json()
    if proj["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Only SCHEDULED projects can begin construction")
    action = db.capacity_actions[proj["capacity_action_id"]]
    if action["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Parent capacity action must be IN_PROGRESS")
    proj["status"] = "IN_CONSTRUCTION"
    db.touch(proj)
    return success(proj, 200)


@bp.post("/node-split-projects/<rid>/cutover")
def cutover(rid):
    require_roles(["FieldOpsCoordinator"])
    proj = db.get_or_404(db.node_split_projects, rid)
    body_json()
    if proj["status"] != "IN_CONSTRUCTION":
        raise_err("ERR_INVALID_STATE", "Only IN_CONSTRUCTION projects can cut over")
    action = db.capacity_actions[proj["capacity_action_id"]]
    parent_sg, parent_node = _action_node(action)

    live_sgs = [s for s in calcs.node_service_groups(parent_node["id"])
                if s["posture"] != "SPLIT_RETIRED"]
    if len(live_sgs) != 1:
        raise_err("ERR_INVALID_STATE",
                  "The split source node must have exactly one non-retired service group")

    allocs = calcs.homes_allocation(
        parent_sg["homes_passed"], proj["child_count"],
        proj["min_homes_per_child"], proj["max_homes_per_child"])

    # Create the child node
    child_node = db.stamp_new({
        "id": db.new_id(),
        "franchise_area_id": parent_node["franchise_area_id"],
        "node_code": parent_node["node_code"] + "-S1",
        "homes_passed": parent_sg["homes_passed"],
        "downstream_spectrum_mhz": parent_node["downstream_spectrum_mhz"],
        "upstream_config": parent_node["upstream_config"],
        "status": "ACTIVE",
    })
    db.optical_nodes[child_node["id"]] = child_node

    # Duplicate blocks preserving status
    for b in calcs.node_blocks(parent_node["id"]):
        nb = db.stamp_new({
            "id": db.new_id(),
            "optical_node_id": child_node["id"],
            "block_type": b["block_type"],
            "mhz": b["mhz"],
            "status": b["status"],
            "channels": b["mhz"] // 6,
            "capacity_mbps": (b["mhz"] // 6) * 38 if b["status"] == "DATA_ACTIVE" else 0,
        })
        db.spectrum_blocks[nb["id"]] = nb

    # Create child service groups
    child_sg_ids = []
    for i, homes in enumerate(allocs, start=1):
        child = db.stamp_new({
            "id": db.new_id(),
            "optical_node_id": child_node["id"],
            "sg_code": f"{parent_sg['sg_code']}-S{i}",
            "homes_passed": homes,
            "warn_threshold_pct": parent_sg["warn_threshold_pct"],
            "critical_threshold_pct": parent_sg["critical_threshold_pct"],
            "utilization_method": parent_sg["utilization_method"],
            "downstream_capacity_mbps": calcs.node_downstream_capacity(child_node["id"]),
            "upstream_capacity_mbps": calcs.UPSTREAM_CAPACITY[child_node["upstream_config"]],
            "provisioned_downstream_mbps": 0,
            "current_load_mbps": 0,
            "current_utilization_pct": 0.0,
            "posture": "NORMAL",
        })
        db.service_groups[child["id"]] = child
        child_sg_ids.append(child["id"])

    # Retire parent service group and node
    parent_sg["homes_passed"] = 0
    parent_sg["current_load_mbps"] = 0
    parent_sg["current_utilization_pct"] = 0.0
    parent_sg["posture"] = "SPLIT_RETIRED"
    db.touch(parent_sg)

    parent_node["status"] = "SPLIT_RETIRED"
    db.touch(parent_node)

    action["status"] = "COMPLETED"
    db.touch(action)

    proj["child_allocations"] = allocs
    proj["child_node_id"] = child_node["id"]
    proj["child_service_group_ids"] = child_sg_ids
    proj["status"] = "COMPLETED"
    db.touch(proj)
    return success(proj, 200)


# ------------------------------------------------------------ Migration waves

@bp.post("/capacity-actions/<rid>/migration-waves")
def create_migration_wave(rid):
    require_roles(["NetworkPlanner"])
    action = db.get_or_404(db.capacity_actions, rid)
    data = body_json(
        required=[
            ("wave_code", "str", None),
            ("window_start", "datetime", None),
            ("window_end", "datetime", None),
            ("target_cpe_ids", "array", None),
        ],
    )
    if action["action_type"] != "SPECTRUM_RECLAIM":
        raise_err("ERR_ACTION_TYPE_MISMATCH")
    ws = db.parse_dt(data["window_start"])
    we = db.parse_dt(data["window_end"])
    if ws >= we:
        raise_err("ERR_VALIDATION", "window_start must be strictly before window_end")

    gap = timedelta(days=7)
    for w in db.migration_waves.values():
        if w["capacity_action_id"] != action["id"] or w["status"] not in ("PLANNED", "EXECUTED"):
            continue
        aws = db.parse_dt(w["window_start"])
        awe = db.parse_dt(w["window_end"])
        if not (ws >= awe + gap or we <= aws - gap):
            raise_err("ERR_WAVE_GAP_VIOLATION")

    rec = db.stamp_new({
        "id": db.new_id(),
        "capacity_action_id": action["id"],
        "wave_code": data["wave_code"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "target_cpe_ids": list(data["target_cpe_ids"]),
        "migrated_count": 0,
        "status": "PLANNED",
    })
    db.migration_waves[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/migration-waves/<rid>")
def get_migration_wave(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.migration_waves, rid)
    return success(rec, 200)


@bp.get("/capacity-actions/<rid>/migration-waves")
def list_migration_waves(rid):
    require_roles(["Any"])
    action = db.get_or_404(db.capacity_actions, rid)
    items = sorted_by_created(
        [w for w in db.migration_waves.values() if w["capacity_action_id"] == action["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.post("/migration-waves/<rid>/execute")
def execute_wave(rid):
    require_roles(["FieldOpsCoordinator"])
    wave = db.get_or_404(db.migration_waves, rid)
    body_json()
    if wave["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Only PLANNED waves can be executed")
    action = db.capacity_actions[wave["capacity_action_id"]]
    if action["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Parent capacity action must be IN_PROGRESS")
    for cid in wave["target_cpe_ids"]:
        cpe = db.customer_equipment.get(cid)
        if cpe is None:
            raise_err("ERR_NOT_FOUND", f"Equipment {cid} not found")
    for cid in wave["target_cpe_ids"]:
        cpe = db.customer_equipment[cid]
        if cpe["status"] != "ACTIVE" or not cpe["video_legacy"]:
            raise_err("ERR_CPE_NOT_ELIGIBLE")
    for cid in wave["target_cpe_ids"]:
        cpe = db.customer_equipment[cid]
        cpe["video_legacy"] = False
        db.touch(cpe)
    wave["migrated_count"] = len(wave["target_cpe_ids"])
    wave["status"] = "EXECUTED"
    db.touch(wave)
    return success(wave, 200)


@bp.post("/migration-waves/<rid>/cancel")
def cancel_wave(rid):
    require_roles(["FieldOpsCoordinator"])
    wave = db.get_or_404(db.migration_waves, rid)
    body_json()
    if wave["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Only PLANNED waves can be cancelled")
    wave["status"] = "CANCELLED"
    db.touch(wave)
    return success(wave, 200)
