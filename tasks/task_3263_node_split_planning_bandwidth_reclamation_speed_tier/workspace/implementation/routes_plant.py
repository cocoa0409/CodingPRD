"""Routes: franchise areas, optical nodes, spectrum blocks, service groups, samples."""

from flask import Blueprint

import calcs
import db
from errors import raise_err
from middleware import body_json, require_roles
from response import paginate, sorted_by_created, success

bp = Blueprint("plant", __name__)

UPSTREAM_CONFIGS = {"LEGACY", "MID_SPLIT", "HIGH_SPLIT"}
BLOCK_TYPES = {"LEGACY_VIDEO", "DATA"}
UTIL_METHODS = {"PEAK_PCT95", "SUSTAINED_AVG"}


# ---------------------------------------------------------- Clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    data = body_json(required=[("current_utc", "datetime", None)])
    dt = db.parse_dt(data["current_utc"])
    db.set_clock(dt)
    return success({}, 200)


# ---------------------------------------------------------- Franchise areas

@bp.post("/franchise-areas")
def create_franchise_area():
    require_roles(["PlatformAdmin"])
    data = body_json(
        required=[
            ("name", "str", None),
            ("region_code", "str", None),
            ("obligation_homes_required", "int", None),
            ("obligation_deadline", "datetime", None),
        ],
        optional=[("blackout_windows", "array", None)],
    )
    blackouts = data["blackout_windows"] or []
    # Validate blackout entries shape
    for bw in blackouts:
        if not isinstance(bw, dict) or "start" not in bw or "end" not in bw:
            raise_err("ERR_VALIDATION", "blackout_windows entries must have start and end")
        try:
            db.parse_dt(bw["start"])
            db.parse_dt(bw["end"])
        except (ValueError, TypeError):
            raise_err("ERR_VALIDATION", "blackout_windows entries must be ISO8601 datetimes")
    rec = db.stamp_new({
        "id": db.new_id(),
        "name": data["name"],
        "region_code": data["region_code"],
        "obligation_homes_required": data["obligation_homes_required"],
        "obligation_deadline": data["obligation_deadline"],
        "blackout_windows": blackouts,
        "homes_built_progress": 0,
    })
    db.franchise_areas[rec["id"]] = rec
    return success(_fa_view(rec), 201)


def _fa_view(rec):
    out = dict(rec)
    out["homes_built_progress"] = calcs.franchise_homes_progress(rec["id"])
    return out


@bp.get("/franchise-areas/<rid>")
def get_franchise_area(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.franchise_areas, rid)
    return success(_fa_view(rec), 200)


@bp.get("/franchise-areas")
def list_franchise_areas():
    require_roles(["Any"])
    items = sorted_by_created([_fa_view(r) for r in db.franchise_areas.values()])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


# ---------------------------------------------------------- Optical nodes

@bp.post("/franchise-areas/<rid>/optical-nodes")
def create_optical_node(rid):
    require_roles(["NetworkPlanner"])
    fa = db.get_or_404(db.franchise_areas, rid)
    data = body_json(
        required=[
            ("node_code", "str", None),
            ("homes_passed", "int", None),
            ("downstream_spectrum_mhz", "int", None),
        ],
        optional=[("upstream_config", "str", UPSTREAM_CONFIGS)],
    )
    rec = db.stamp_new({
        "id": db.new_id(),
        "franchise_area_id": fa["id"],
        "node_code": data["node_code"],
        "homes_passed": data["homes_passed"],
        "downstream_spectrum_mhz": data["downstream_spectrum_mhz"],
        "upstream_config": data["upstream_config"] or "LEGACY",
        "status": "ACTIVE",
    })
    db.optical_nodes[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/optical-nodes/<rid>")
def get_optical_node(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.optical_nodes, rid)
    return success(rec, 200)


@bp.get("/franchise-areas/<rid>/optical-nodes")
def list_optical_nodes(rid):
    require_roles(["Any"])
    fa = db.get_or_404(db.franchise_areas, rid)
    items = sorted_by_created(
        [n for n in db.optical_nodes.values() if n["franchise_area_id"] == fa["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


# ---------------------------------------------------------- Spectrum blocks

@bp.post("/optical-nodes/<rid>/spectrum-blocks")
def create_spectrum_block(rid):
    require_roles(["CapacityEngineer"])
    node = db.get_or_404(db.optical_nodes, rid)
    data = body_json(
        required=[("block_type", "str", BLOCK_TYPES), ("mhz", "int", None)],
    )
    if node["status"] == "SPLIT_RETIRED":
        raise_err("ERR_NODE_RETIRED")
    used = sum(b["mhz"] for b in calcs.node_blocks(node["id"]))
    if used + data["mhz"] > node["downstream_spectrum_mhz"]:
        raise_err("ERR_SPECTRUM_OVERALLOCATED")
    status = "DATA_ACTIVE" if data["block_type"] == "DATA" else "VIDEO_ACTIVE"
    rec = db.stamp_new({
        "id": db.new_id(),
        "optical_node_id": node["id"],
        "block_type": data["block_type"],
        "mhz": data["mhz"],
        "status": status,
        "channels": data["mhz"] // 6,
        "capacity_mbps": (data["mhz"] // 6) * 38 if status == "DATA_ACTIVE" else 0,
    })
    db.spectrum_blocks[rec["id"]] = rec
    # DATA blocks immediately contribute capacity to the node's service groups
    if status == "DATA_ACTIVE":
        for sg in calcs.node_service_groups(node["id"]):
            calcs.recompute_service_group(sg)
    return success(rec, 201)


@bp.get("/spectrum-blocks/<rid>")
def get_spectrum_block(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.spectrum_blocks, rid)
    return success(rec, 200)


@bp.get("/optical-nodes/<rid>/spectrum-blocks")
def list_spectrum_blocks(rid):
    require_roles(["Any"])
    node = db.get_or_404(db.optical_nodes, rid)
    items = sorted_by_created(calcs.node_blocks(node["id"]))
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


# ---------------------------------------------------------- Service groups

@bp.post("/optical-nodes/<rid>/service-groups")
def create_service_group(rid):
    require_roles(["CapacityEngineer"])
    node = db.get_or_404(db.optical_nodes, rid)
    data = body_json(
        required=[
            ("sg_code", "str", None),
            ("homes_passed", "int", None),
            ("warn_threshold_pct", "int", None),
            ("critical_threshold_pct", "int", None),
            ("utilization_method", "str", UTIL_METHODS),
        ],
    )
    if node["status"] == "SPLIT_RETIRED":
        raise_err("ERR_NODE_RETIRED")
    existing = sum(
        s["homes_passed"] for s in calcs.node_service_groups(node["id"])
        if s["posture"] != "SPLIT_RETIRED"
    )
    if existing + data["homes_passed"] > node["homes_passed"]:
        raise_err("ERR_HOMES_EXCEED_NODE")
    rec = db.stamp_new({
        "id": db.new_id(),
        "optical_node_id": node["id"],
        "sg_code": data["sg_code"],
        "homes_passed": data["homes_passed"],
        "warn_threshold_pct": data["warn_threshold_pct"],
        "critical_threshold_pct": data["critical_threshold_pct"],
        "utilization_method": data["utilization_method"],
        "downstream_capacity_mbps": calcs.node_downstream_capacity(node["id"]),
        "upstream_capacity_mbps": calcs.UPSTREAM_CAPACITY[node["upstream_config"]],
        "provisioned_downstream_mbps": 0,
        "current_load_mbps": 0,
        "current_utilization_pct": 0.0,
        "posture": "NORMAL",
    })
    db.service_groups[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/service-groups/<rid>")
def get_service_group(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.service_groups, rid)
    return success(rec, 200)


@bp.get("/optical-nodes/<rid>/service-groups")
def list_service_groups(rid):
    require_roles(["Any"])
    node = db.get_or_404(db.optical_nodes, rid)
    items = sorted_by_created(calcs.node_service_groups(node["id"]))
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


# ---------------------------------------------------------- Utilization samples

@bp.post("/service-groups/<rid>/utilization-samples")
def create_utilization_sample(rid):
    require_roles(["PlatformAdmin"])
    sg = db.get_or_404(db.service_groups, rid)
    data = body_json(
        required=[
            ("measured_at", "datetime", None),
            ("downstream_mbps", "int", None),
            ("upstream_mbps", "int", None),
        ],
    )
    rec = {
        "id": db.new_id(),
        "service_group_id": sg["id"],
        "measured_at": data["measured_at"],
        "downstream_mbps": data["downstream_mbps"],
        "upstream_mbps": data["upstream_mbps"],
    }
    db.stamp_new(rec, with_version=False)
    db.utilization_samples[rec["id"]] = rec
    calcs.recompute_service_group(sg)
    return success(rec, 201)


@bp.get("/service-groups/<rid>/utilization-samples")
def list_utilization_samples(rid):
    require_roles(["Any"])
    sg = db.get_or_404(db.service_groups, rid)
    items = sorted_by_created(
        [s for s in db.utilization_samples.values() if s["service_group_id"] == sg["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)
