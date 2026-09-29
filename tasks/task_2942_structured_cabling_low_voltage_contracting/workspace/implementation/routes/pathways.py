"""PRD 3.3 — the pathway graph, re-pointing it and Cascade B condemnation."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import base_record, db, r2, r4, touch
from validation import Field, body

pathways_bp = Blueprint("pathways", __name__)

PATHWAY_STATES = ("SERVICEABLE", "CONDEMNED")
MAX_PATHWAY_DEPTH = 8

READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, TEST_TECHNICIAN,
              CERTIFIER, CLIENT)


@pathways_bp.route("/cabling/pathway-segments", methods=["POST"])
@require(DESIGN_ENGINEER)
def design_segment():
    values = body([
        Field("project_id", "string"),
        Field("segment_code", "string", min_len=1),
        Field("pathway_type", "enum", enum=calc.PATHWAY_TYPES),
        Field("usable_area_sq_mm", "number", exclusive_min=0),
        Field("length_m", "number", exclusive_min=0),
        Field("bend_count", "integer", required=False, default=0, minimum=0),
        Field("in_plenum_space", "bool", required=False, default=False),
        Field("shared_with_power", "bool", required=False, default=False),
        Field("power_separation_mm", "integer", required=False, default=0, minimum=0),
        Field("upstream_segment_id", "string", required=False, default=None,
              nullable=True),
    ])
    project = lookup.project(values["project_id"])
    upstream = lookup.segment(values["upstream_segment_id"])
    if upstream is not None:
        if upstream["project_id"] != project["id"]:
            raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                           "upstream_segment_id belongs to a different project.")
        depth = rollups.segment_depth(upstream) + 1
        if depth > MAX_PATHWAY_DEPTH:
            raise ApiError("ERR_PATHWAY_CYCLE",
                           "The parent pointer would push the segment past the 8-hop ceiling.")
    else:
        depth = 0
    for existing in db.segments.values():
        if (existing["project_id"] == project["id"]
                and existing["segment_code"] == values["segment_code"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "segment_code must be unique within the project.")

    segment = base_record()
    segment.update({
        "project_id": project["id"],
        "segment_code": values["segment_code"],
        "pathway_type": values["pathway_type"],
        "usable_area_sq_mm": values["usable_area_sq_mm"],
        "length_m": values["length_m"],
        "bend_count": values["bend_count"],
        "in_plenum_space": values["in_plenum_space"],
        "shared_with_power": values["shared_with_power"],
        "power_separation_mm": values["power_separation_mm"],
        "upstream_segment_id": upstream["id"] if upstream is not None else None,
        "pathway_depth": depth,
        "occupying_route_count": 0,
        "fill_area_used_sq_mm": r2(0),
        "allowed_fill_pct": 0,
        "fill_ratio": r4(0),
        "pathway_state": "SERVICEABLE",
        "condemned_reason": None,
    })
    segment["allowed_fill_pct"] = calc.segment_allowed_fill_pct(segment)
    db.segments[segment["id"]] = segment
    return created(serial.public(segment))


@pathways_bp.route("/cabling/pathway-segments/<segment_id>", methods=["GET"])
@require(*READ_ROLES)
def read_segment(segment_id):
    return ok(serial.public(lookup.segment(segment_id)))


@pathways_bp.route("/cabling/pathway-segments", methods=["GET"])
@require(*READ_ROLES)
def list_segments():
    project_id = request.args.get("project_id")
    upstream_segment_id = request.args.get("upstream_segment_id")
    pathway_state = enum_filter(request.args, "pathway_state", PATHWAY_STATES)
    pathway_type = enum_filter(request.args, "pathway_type", calc.PATHWAY_TYPES)
    rows = []
    for segment in db.segments.values():
        if project_id is not None and segment["project_id"] != project_id:
            continue
        if (upstream_segment_id is not None
                and segment["upstream_segment_id"] != upstream_segment_id):
            continue
        if pathway_state is not None and segment["pathway_state"] != pathway_state:
            continue
        if pathway_type is not None and segment["pathway_type"] != pathway_type:
            continue
        rows.append(segment)
    return paginate(rows, request.args, serial.public)


@pathways_bp.route("/cabling/pathway-segments/<segment_id>/condemn", methods=["POST"])
@require(PROJECT_MANAGER)
def condemn_segment(segment_id):
    values = body([Field("condemned_reason", "string")])
    segment = lookup.segment(segment_id)
    if segment["pathway_state"] != "SERVICEABLE":
        raise ApiError("ERR_SEGMENT_CONDEMNED",
                       "The segment is already condemned; CONDEMNED is terminal.")
    rollups.cascade_b_condemn(segment, values["condemned_reason"])
    return ok(serial.public(segment))


@pathways_bp.route("/cabling/pathway-segments/<segment_id>/reparent", methods=["POST"])
@require(DESIGN_ENGINEER)
def reparent_segment(segment_id):
    values = body([
        Field("upstream_segment_id", "string", nullable=True),
        Field("expected_segment_version", "integer"),
    ])
    segment = lookup.segment(segment_id)
    upstream = lookup.segment(values["upstream_segment_id"])
    if segment["pathway_state"] != "SERVICEABLE":
        raise ApiError("ERR_SEGMENT_CONDEMNED",
                       "A condemned segment accepts no re-pointing.")
    if values["expected_segment_version"] != segment["version"]:
        raise ApiError("ERR_STALE_PATHWAY_VERSION",
                       "expected_segment_version does not match the segment's version.")
    if upstream is not None:
        if upstream["id"] == segment["id"]:
            raise ApiError("ERR_PATHWAY_CYCLE",
                           "A segment may not be its own upstream segment.")
        chain = rollups.upstream_chain_ids(upstream)
        if segment["id"] in chain:
            raise ApiError("ERR_PATHWAY_CYCLE",
                           "The proposed parent sits downstream of this segment.")
        depth = rollups.segment_depth(upstream) + 1
        if depth > MAX_PATHWAY_DEPTH:
            raise ApiError("ERR_PATHWAY_CYCLE",
                           "The move would push the chain past the 8-hop ceiling.")
    else:
        depth = 0
    segment["upstream_segment_id"] = upstream["id"] if upstream is not None else None
    segment["pathway_depth"] = depth
    touch(segment)
    rollups.recompute_descendant_depths(segment)
    return ok(serial.public(segment))
