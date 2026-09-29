"""PRD 3.5 — routing a link through the pathway: plenum, separation, continuity, fill."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (CERTIFIER, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import D, base_record, db, r2, touch
from validation import Field, body

link_routes_bp = Blueprint("link_routes", __name__)

ROUTE_STATES = ("OCCUPYING", "WITHDRAWN", "SUSPENDED")
READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, TEST_TECHNICIAN, CERTIFIER)


@link_routes_bp.route("/cabling/link-routes", methods=["POST"])
@require(DESIGN_ENGINEER)
def create_route():
    values = body([
        Field("link_id", "string"),
        Field("pathway_segment_id", "string"),
        Field("sequence_index", "integer", minimum=1),
        Field("expected_segment_version", "integer"),
    ])
    link = lookup.link(values["link_id"])
    segment = lookup.segment(values["pathway_segment_id"])
    if link["install_state"] != "DESIGNED":
        raise ApiError("ERR_INVALID_LINK_STATE",
                       "Routings may only be created while the link is DESIGNED.")
    if segment["pathway_state"] != "SERVICEABLE":
        raise ApiError("ERR_SEGMENT_CONDEMNED",
                       "A condemned segment accepts no new routings.")
    if values["expected_segment_version"] != segment["version"]:
        raise ApiError("ERR_STALE_PATHWAY_VERSION",
                       "expected_segment_version does not match the segment's version.")
    cable_type = db.cable_types.get(link["cable_type_id"])
    if cable_type is None:
        raise ApiError("ERR_CABLE_TYPE_NOT_FOUND")
    if segment["in_plenum_space"] and cable_type["jacket_rating"] not in calc.PLENUM_RATINGS:
        raise ApiError("ERR_PLENUM_RATING_REQUIRED",
                       "A plenum cavity requires a CMP or LSZH jacket.")
    if segment["shared_with_power"]:
        required = calc.required_separation_mm(cable_type)
        if segment["power_separation_mm"] < required:
            raise ApiError("ERR_POWER_SEPARATION_INSUFFICIENT",
                           "power_separation_mm is below the requirement for this cable.")
    if link["project_id"] != segment["project_id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "The link and the pathway segment belong to different projects.")

    occupying = [r for r in rollups.link_routes(link["id"])
                 if r["route_state"] == "OCCUPYING"]
    index = values["sequence_index"]
    if any(r["sequence_index"] == index for r in occupying):
        raise ApiError("ERR_ROUTE_SEQUENCE_GAP",
                       "That sequence_index is already occupied by this link.")
    if index > 1:
        previous = [r for r in occupying if r["sequence_index"] == index - 1]
        if not previous:
            raise ApiError("ERR_ROUTE_SEQUENCE_GAP",
                           "The chain must be walked one hop at a time with no gaps.")
        if segment["upstream_segment_id"] != previous[0]["pathway_segment_id"]:
            raise ApiError("ERR_ROUTE_SEQUENCE_GAP",
                           "The segment is not a child of the previous segment in the chain.")

    candidate_area = D(cable_type["cross_section_area_sq_mm"])
    resulting_count = segment["occupying_route_count"] + 1
    allowed_pct = calc.allowed_fill_pct(segment["pathway_type"], resulting_count,
                                        segment["bend_count"])
    used_area = r2(D(segment["fill_area_used_sq_mm"]) + candidate_area)
    allowed_area = calc.allowed_fill_area_sq_mm(segment["usable_area_sq_mm"], allowed_pct)
    if used_area > allowed_area:
        raise ApiError("ERR_PATHWAY_FILL_EXCEEDED",
                       "The routing would push the segment past its code fill limit.")

    route = base_record()
    route.update({
        "link_id": link["id"],
        "pathway_segment_id": segment["id"],
        "sequence_index": index,
        "consumed_area_sq_mm": r2(candidate_area),
        "route_state": "OCCUPYING",
    })
    db.routes[route["id"]] = route
    rollups.recompute_segment_fill(segment)
    touch(segment)
    rollups.recompute_link_routed_count(link)
    touch(link)
    return created(serial.public(route))


@link_routes_bp.route("/cabling/link-routes/<route_id>", methods=["GET"])
@require(*READ_ROLES)
def read_route(route_id):
    return ok(serial.public(lookup.route(route_id)))


@link_routes_bp.route("/cabling/link-routes", methods=["GET"])
@require(*READ_ROLES)
def list_routes():
    link_id = request.args.get("link_id")
    pathway_segment_id = request.args.get("pathway_segment_id")
    route_state = enum_filter(request.args, "route_state", ROUTE_STATES)
    rows = []
    for route in db.routes.values():
        if link_id is not None and route["link_id"] != link_id:
            continue
        if (pathway_segment_id is not None
                and route["pathway_segment_id"] != pathway_segment_id):
            continue
        if route_state is not None and route["route_state"] != route_state:
            continue
        rows.append(route)
    return paginate(rows, request.args, serial.public)


@link_routes_bp.route("/cabling/link-routes/<route_id>/withdraw", methods=["POST"])
@require(DESIGN_ENGINEER)
def withdraw_route(route_id):
    values = body([Field("expected_segment_version", "integer")])
    route = lookup.route(route_id)
    segment = db.segments.get(route["pathway_segment_id"])
    link = db.links.get(route["link_id"])
    if route["route_state"] != "OCCUPYING":
        raise ApiError("ERR_INVALID_ROUTE_STATE",
                       "Only an OCCUPYING routing can be withdrawn.")
    if link is not None and link["install_state"] != "DESIGNED":
        raise ApiError("ERR_INVALID_LINK_STATE",
                       "A pulled cable cannot have its path deleted from under it.")
    if segment is not None and values["expected_segment_version"] != segment["version"]:
        raise ApiError("ERR_STALE_PATHWAY_VERSION",
                       "expected_segment_version does not match the segment's version.")
    route["route_state"] = "WITHDRAWN"
    touch(route)
    if segment is not None:
        rollups.recompute_segment_fill(segment)
        touch(segment)
    if link is not None:
        rollups.recompute_link_routed_count(link)
        touch(link)
    return ok(serial.public(route))
