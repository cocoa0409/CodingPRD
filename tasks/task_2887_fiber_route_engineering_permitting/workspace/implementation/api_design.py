"""DesignPackage, SplicePoint and AsBuiltRecord endpoints."""

from flask import Blueprint

import calc
import domain
import serialize
import validate as v
from auth import ALL_ROLES, ROLE_FIELD_SURVEYOR, ROLE_ROUTE_ENGINEER, acting_user_id, endpoint
from envelope import filter_value, object_response, paginate
from errors import ApiError
from store import db, new_record, now_iso, touch

bp = Blueprint("design", __name__)

DESIGN_CREATE_FIELDS = ("route_id", "fiber_count_allocated", "express_fiber_count",
                        "expected_route_version")
SPLICE_CREATE_FIELDS = ("design_id", "segment_id", "station_feet", "enclosure_type",
                        "fiber_count_dropped")
AS_BUILT_CREATE_FIELDS = ("route_id", "design_revision", "as_built_length_feet",
                          "splice_point_count_field_verified", "records_system_reference")

DESIGN_ROUTE_STATUSES = ("SCOPE_LOCKED", "PERMITTING", "CONSTRUCTION_READY")


# ---------------------------------------------------------------------------
# DesignPackage
# ---------------------------------------------------------------------------


@bp.route("/design-packages", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def create_design_package():
    payload = v.body()
    v.check_body(payload, DESIGN_CREATE_FIELDS)
    route_id = v.req_id(payload, "route_id")
    allocated = v.req_int_in(payload, "fiber_count_allocated", calc.FIBER_COUNTS_ALLOWED)
    express = v.req_int(payload, "express_fiber_count", minimum=0)
    expected_version = v.req_int(payload, "expected_route_version")
    if express >= allocated:
        v.bad("Field 'express_fiber_count' must be strictly less than 'fiber_count_allocated'.")

    route = domain.get_route(route_id)

    if route["version"] != expected_version:
        raise ApiError("ERR_STALE_ROUTE_VERSION")

    if route["status"] not in DESIGN_ROUTE_STATUSES:
        raise ApiError("ERR_INVALID_ROUTE_STATE",
                       "A design package requires the route to have locked its scope.")

    revision = 1 + len(domain.designs_of_route(route["id"]))
    rec = new_record()
    rec.update({
        "route_id": route["id"],
        "revision": revision,
        "status": "DRAFT",
        "fiber_count_allocated": allocated,
        "express_fiber_count": express,
        "assigned_drop_fiber_count": 0,
        "reserve_fiber_count": 0,
        "spare_ratio_bp": 0,
        "splice_point_count": 0,
        "handhole_count": 0,
        "submitted_by_user_id": None,
        "stamped_by_user_id": None,
        "stamped_at": None,
        "stamp_voided_at": None,
        "return_note": None,
    })
    db.designs[rec["id"]] = rec
    domain.recompute_design_rollups(rec)

    touch(route)
    return object_response(serialize.design(rec), 201)


@bp.route("/design-packages/<design_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_design_package(design_id):
    return object_response(serialize.design(domain.get_design(design_id)))


@bp.route("/design-packages/<design_id>/splice-points", methods=["GET"])
@endpoint(ALL_ROLES)
def list_design_splice_points(design_id):
    design = domain.get_design(design_id)
    rows = domain.splice_points_of_design(design["id"])
    status = filter_value("status")
    enclosure_type = filter_value("enclosure_type")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if enclosure_type is not None:
        rows = [r for r in rows if r["enclosure_type"] == enclosure_type]
    return paginate(rows, serialize.splice_point)


@bp.route("/design-packages/<design_id>/submit-for-review", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def submit_design_for_review(design_id):
    v.check_body(v.body(), ())
    design = domain.get_design(design_id)

    if design["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DESIGN_STATE")

    placed = [s for s in domain.splice_points_of_design(design["id"]) if s["status"] == "PLACED"]
    if not placed:
        raise ApiError("ERR_DESIGN_HAS_NO_SPLICE_POINTS")

    design["status"] = "IN_REVIEW"
    design["submitted_by_user_id"] = acting_user_id()
    touch(design)
    return object_response(serialize.design(design))


@bp.route("/design-packages/<design_id>/stamp", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def stamp_design(design_id):
    v.check_body(v.body(), ())
    design = domain.get_design(design_id)

    if design["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_DESIGN_STATE")

    if acting_user_id() == design["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The engineer who submitted this package may not stamp it.")

    route = db.routes[design["route_id"]]
    segments = domain.segments_of_route(route["id"])
    if any(s["permit_status"] != "CLEARED" for s in segments):
        raise ApiError("ERR_PERMIT_NOT_CLEARED")

    if design["spare_ratio_bp"] < calc.MIN_SPARE_RATIO_BP:
        raise ApiError("ERR_SPARE_RATIO_BELOW_MINIMUM")

    design["status"] = "STAMPED"
    design["stamped_by_user_id"] = acting_user_id()
    design["stamped_at"] = now_iso()
    design["stamp_voided_at"] = None
    touch(design)

    for other in domain.designs_of_route(route["id"]):
        if other["id"] == design["id"]:
            continue
        if other["status"] == "STAMPED":
            other["status"] = "SUPERSEDED"
            touch(other)

    domain.try_advance_route_to_construction_ready(route)
    touch(route)
    return object_response(serialize.design(design))


@bp.route("/design-packages/<design_id>/return-to-draft", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def return_design_to_draft(design_id):
    payload = v.body()
    v.check_body(payload, ("return_note",))
    return_note = v.req_str(payload, "return_note", min_len=1)

    design = domain.get_design(design_id)
    if design["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_DESIGN_STATE")

    design["status"] = "DRAFT"
    design["return_note"] = return_note
    design["submitted_by_user_id"] = None
    touch(design)
    return object_response(serialize.design(design))


# ---------------------------------------------------------------------------
# SplicePoint
# ---------------------------------------------------------------------------


@bp.route("/splice-points", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def create_splice_point():
    payload = v.body()
    v.check_body(payload, SPLICE_CREATE_FIELDS)
    design_id = v.req_id(payload, "design_id")
    segment_id = v.req_id(payload, "segment_id")
    station_feet = v.req_int(payload, "station_feet", minimum=0)
    enclosure_type = v.req_enum(payload, "enclosure_type", calc.ENCLOSURE_TYPES)
    fiber_dropped = v.req_int(payload, "fiber_count_dropped", minimum=0)

    # the station ceiling is a body-shape rule, so it reports before the
    # foreign-key resolution below whenever the segment can be resolved at all
    probe_segment = db.segments.get(segment_id)
    if probe_segment is not None and station_feet > probe_segment["length_feet"]:
        v.bad("Field 'station_feet' must not exceed the addressed segment's length_feet.")

    design = domain.get_design(design_id)
    segment = domain.get_segment(segment_id)

    if design["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DESIGN_STATE")

    for sibling in domain.splice_points_of_design(design["id"]):
        if sibling["status"] != "PLACED" or sibling["segment_id"] != segment["id"]:
            continue
        if abs(sibling["station_feet"] - station_feet) < calc.MIN_SPLICE_SPACING_FEET:
            raise ApiError("ERR_SPLICE_SPACING_VIOLATION")

    if design["reserve_fiber_count"] - fiber_dropped < 0:
        raise ApiError("ERR_FIBER_ALLOCATION_EXCEEDED")

    rec = new_record()
    rec.update({
        "design_id": design["id"],
        "segment_id": segment["id"],
        "station_feet": station_feet,
        "enclosure_type": enclosure_type,
        "fiber_count_dropped": fiber_dropped,
        "status": "PLACED",
        "voided_at": None,
    })
    db.splice_points[rec["id"]] = rec

    domain.recompute_design_rollups(design)
    touch(design)
    return object_response(serialize.splice_point(rec), 201)


@bp.route("/splice-points/<splice_id>/void", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def void_splice_point(splice_id):
    v.check_body(v.body(), ())
    splice = domain.get_splice_point(splice_id)

    if splice["status"] != "PLACED":
        raise ApiError("ERR_INVALID_SPLICE_POINT_STATE")

    design = db.designs[splice["design_id"]]
    if design["status"] not in ("DRAFT", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_DESIGN_STATE")

    splice["status"] = "VOIDED"
    splice["voided_at"] = now_iso()
    touch(splice)

    domain.recompute_design_rollups(design)
    touch(design)
    return object_response(serialize.splice_point(splice))


# ---------------------------------------------------------------------------
# AsBuiltRecord
# ---------------------------------------------------------------------------


@bp.route("/as-built-records", methods=["POST"])
@endpoint([ROLE_FIELD_SURVEYOR])
def create_as_built_record():
    payload = v.body()
    v.check_body(payload, AS_BUILT_CREATE_FIELDS)
    route_id = v.req_id(payload, "route_id")
    design_revision = v.req_int(payload, "design_revision", minimum=1)
    as_built_length = v.req_int(payload, "as_built_length_feet", minimum=1)
    verified_count = v.req_int(payload, "splice_point_count_field_verified", minimum=0)
    records_reference = v.req_str(payload, "records_system_reference")

    route = domain.get_route(route_id)

    if route["status"] != "CONSTRUCTION_READY":
        raise ApiError("ERR_INVALID_ROUTE_STATE",
                       "As-built filing requires the route to stand at CONSTRUCTION_READY.")

    if domain.stamped_design_with_revision(route["id"], design_revision) is None:
        raise ApiError("ERR_DESIGN_NOT_STAMPED")

    rec = new_record()
    rec.update({
        "route_id": route["id"],
        "design_revision": design_revision,
        "as_built_length_feet": as_built_length,
        "splice_point_count_field_verified": verified_count,
        "records_system_reference": records_reference,
        "status": "SUBMITTED",
        "submitted_by_user_id": acting_user_id(),
        "certified_by_user_id": None,
        "length_variance_bp": calc.length_variance_bp(
            as_built_length, route["design_total_length_feet"]
        ),
        "certification_note": None,
    })
    db.as_builts[rec["id"]] = rec
    return object_response(serialize.as_built(rec), 201)


@bp.route("/as-built-records/<as_built_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_as_built_record(as_built_id):
    return object_response(serialize.as_built(domain.get_as_built(as_built_id)))


@bp.route("/as-built-records/<as_built_id>/certify", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def certify_as_built_record(as_built_id):
    payload = v.body()
    v.check_body(payload, ("decision", "certification_note"))
    decision = v.req_enum(payload, "decision", calc.AS_BUILT_DECISIONS)
    certification_note = v.opt_str(payload, "certification_note", default=None)

    record = domain.get_as_built(as_built_id)
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AS_BUILT_STATE")

    design = domain.design_with_revision(record["route_id"], record["design_revision"])
    if design is not None and design["stamped_by_user_id"] is not None:
        if acting_user_id() == design["stamped_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The engineer who stamped this design may not certify its as-built record.",
            )

    if decision == "ACCEPTED" and record["length_variance_bp"] > calc.MAX_AS_BUILT_VARIANCE_BP:
        raise ApiError("ERR_AS_BUILT_VARIANCE_EXCEEDED")

    record["status"] = decision
    record["certified_by_user_id"] = acting_user_id()
    if certification_note is not None:
        record["certification_note"] = certification_note
    touch(record)

    if decision == "ACCEPTED":
        route = db.routes[record["route_id"]]
        if route["status"] == "CONSTRUCTION_READY":
            route["status"] = "RECORDS_UPDATED"
            touch(route)

    return object_response(serialize.as_built(record))
