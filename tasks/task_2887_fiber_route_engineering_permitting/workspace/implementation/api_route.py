"""Route and RouteSegment endpoints."""

from flask import Blueprint

import calc
import domain
import serialize
import validate as v
from auth import ALL_ROLES, ROLE_NETWORK_RECORDS_ADMIN, ROLE_ROUTE_ENGINEER, acting_user_id, endpoint
from envelope import filter_value, object_response, paginate
from errors import ApiError
from store import db, new_record, now_iso, sort_by_created, touch

bp = Blueprint("route", __name__)

ROUTE_CREATE_FIELDS = ("name", "topology_objective", "target_in_service_date",
                       "budget_authorized_cents")
SEGMENT_CREATE_FIELDS = ("route_id", "sequence_index", "street_name", "municipality_code",
                         "length_feet", "terrain_class", "planned_work_start_on",
                         "planned_work_end_on", "predecessor_segment_id",
                         "existing_conduit_available")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@bp.route("/routes", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def create_route():
    payload = v.body()
    v.check_body(payload, ROUTE_CREATE_FIELDS)
    name = v.req_str(payload, "name", min_len=1, max_len=120)
    objective = v.req_enum(payload, "topology_objective", calc.TOPOLOGY_OBJECTIVES)
    target_date = v.req_date(payload, "target_in_service_date")
    authorized = v.req_int(payload, "budget_authorized_cents",
                           minimum=calc.MIN_AUTHORIZED_BUDGET_CENTS)

    rec = new_record()
    rec.update({
        "name": name,
        "topology_objective": objective,
        "target_in_service_date": target_date,
        "budget_authorized_cents": authorized,
        "budget_committed_cents": 0,
        "budget_available_cents": authorized,
        "status": "PLANNING",
        "segment_count": 0,
        "planned_complexity_index": None,
        "live_complexity_index": None,
        "total_preliminary_cost_cents": 0,
        "total_bid_ready_cost_cents": 0,
        "design_total_length_feet": 0,
        "scope_locked_at": None,
    })
    db.routes[rec["id"]] = rec
    return object_response(serialize.route(rec), 201)


@bp.route("/routes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_routes():
    status = filter_value("status")
    objective = filter_value("topology_objective")
    rows = list(db.routes.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if objective is not None:
        rows = [r for r in rows if r["topology_objective"] == objective]
    return paginate(sort_by_created(rows), serialize.route)


@bp.route("/routes/<route_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_route(route_id):
    return object_response(serialize.route(domain.get_route(route_id)))


@bp.route("/routes/<route_id>/budget-adjustments", methods=["POST"])
@endpoint([ROLE_NETWORK_RECORDS_ADMIN])
def adjust_budget(route_id):
    payload = v.body()
    v.check_body(payload, ("delta_cents", "reason"))
    delta = v.req_int(payload, "delta_cents")
    v.req_str(payload, "reason", min_len=0)

    route = domain.get_route(route_id)
    proposed = route["budget_authorized_cents"] + delta
    if proposed < route["budget_committed_cents"]:
        raise ApiError(
            "ERR_BUDGET_EXCEEDED",
            "The adjustment would drive the authorized budget below the committed budget.",
        )
    route["budget_authorized_cents"] = proposed
    domain.recompute_route_budget(route)
    touch(route)
    return object_response(serialize.route(route))


@bp.route("/routes/<route_id>/lock-scope", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def lock_scope(route_id):
    v.check_body(v.body(), ())
    route = domain.get_route(route_id)

    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_ROUTE_STATE",
                       "Scope locking requires the route to be in PLANNING.")
    segments = domain.segments_of_route(route["id"])
    if not segments:
        raise ApiError("ERR_ROUTE_HAS_NO_SEGMENTS")
    if any(s["engineering_status"] == "DRAFT" for s in segments):
        raise ApiError("ERR_WALKOUT_NOT_ACCEPTED")
    if route["budget_authorized_cents"] < calc.MIN_AUTHORIZED_BUDGET_CENTS:
        raise ApiError("ERR_BUDGET_EXCEEDED",
                       "Scope locking requires an authorized budget of at least 1 cent.")

    route["status"] = "SCOPE_LOCKED"
    route["scope_locked_at"] = now_iso()
    index = domain.compute_planned_complexity_index(route)
    route["planned_complexity_index"] = index
    route["live_complexity_index"] = index
    touch(route)
    return object_response(serialize.route(route))


@bp.route("/routes/<route_id>/segments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_route_segments(route_id):
    route = domain.get_route(route_id)
    rows = domain.segments_of_route(route["id"])
    engineering_status = filter_value("engineering_status")
    permit_status = filter_value("permit_status")
    if engineering_status is not None:
        rows = [r for r in rows if r["engineering_status"] == engineering_status]
    if permit_status is not None:
        rows = [r for r in rows if r["permit_status"] == permit_status]
    return paginate(rows, serialize.segment)


@bp.route("/routes/<route_id>/design-packages", methods=["GET"])
@endpoint(ALL_ROLES)
def list_route_designs(route_id):
    route = domain.get_route(route_id)
    rows = domain.designs_of_route(route["id"])
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serialize.design)


@bp.route("/routes/<route_id>/as-built-records", methods=["GET"])
@endpoint(ALL_ROLES)
def list_route_as_builts(route_id):
    route = domain.get_route(route_id)
    rows = domain.as_builts_of_route(route["id"])
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serialize.as_built)


# ---------------------------------------------------------------------------
# RouteSegment
# ---------------------------------------------------------------------------


@bp.route("/segments", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def create_segment():
    payload = v.body()
    v.check_body(payload, SEGMENT_CREATE_FIELDS)
    route_id = v.req_id(payload, "route_id")
    sequence_index = v.req_int(payload, "sequence_index", minimum=1)
    street_name = v.req_str(payload, "street_name")
    municipality_code = v.req_str(payload, "municipality_code")
    length_feet = v.req_int(payload, "length_feet", minimum=1)
    terrain_class = v.req_enum(payload, "terrain_class", calc.TERRAIN_CLASSES)
    start_on = v.req_date(payload, "planned_work_start_on")
    end_on = v.req_date(payload, "planned_work_end_on")
    v.order_dates(start_on, end_on, "planned_work_start_on", "planned_work_end_on")
    predecessor_id = v.opt_id(payload, "predecessor_segment_id")
    conduit = v.opt_bool(payload, "existing_conduit_available", default=False)

    # body foreign keys resolve in declaration order: route_id, then predecessor
    route = domain.get_route(route_id)
    predecessor = None
    if predecessor_id is not None:
        predecessor = domain.get_segment(predecessor_id)

    if predecessor is not None:
        if (predecessor["route_id"] != route["id"]
                or predecessor["sequence_index"] >= sequence_index):
            raise ApiError("ERR_PREDECESSOR_SEGMENT_MISMATCH")

    for existing in domain.segments_of_route(route["id"]):
        if existing["sequence_index"] == sequence_index:
            raise ApiError("ERR_SEQUENCE_INDEX_TAKEN")

    if route["status"] != "PLANNING":
        if route["status"] == "RECORDS_UPDATED":
            raise ApiError("ERR_INVALID_ROUTE_STATE",
                           "The route's records are closed; no segment may be added.")
        raise ApiError("ERR_SCOPE_LOCKED")

    rec = new_record()
    rec.update({
        "route_id": route["id"],
        "predecessor_segment_id": predecessor["id"] if predecessor is not None else None,
        "sequence_index": sequence_index,
        "street_name": street_name,
        "municipality_code": municipality_code,
        "length_feet": length_feet,
        "terrain_class": terrain_class,
        "existing_conduit_available": conduit,
        "planned_work_start_on": start_on,
        "planned_work_end_on": end_on,
        "construction_method": None,
        "engineering_status": "DRAFT",
        "permit_status": "NOT_REQUIRED",
        "required_authority_type": calc.AUTHORITY_BY_TERRAIN[terrain_class],
        "accepted_obstruction_count": 0,
        "moratorium_class": "NONE",
        "restoration_cost_cents": 0,
        "preliminary_cost_cents": None,
        "bid_ready_cost_cents": None,
    })
    db.segments[rec["id"]] = rec

    domain.recompute_route_segment_rollups(route)
    touch(route)
    return object_response(serialize.segment(rec), 201)


@bp.route("/segments/<segment_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_segment(segment_id):
    return object_response(serialize.segment(domain.get_segment(segment_id)))


@bp.route("/segments/<segment_id>/downstream-segments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_downstream_segments(segment_id):
    segment = domain.get_segment(segment_id)
    return paginate(domain.downstream_segments(segment["id"]), serialize.segment)


@bp.route("/segments/<segment_id>/walkouts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_segment_walkouts(segment_id):
    segment = domain.get_segment(segment_id)
    rows = domain.walkouts_of_segment(segment["id"])
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serialize.walkout)


@bp.route("/segments/<segment_id>/pole-attachment-applications", methods=["GET"])
@endpoint(ALL_ROLES)
def list_segment_pole_apps(segment_id):
    segment = domain.get_segment(segment_id)
    rows = domain.pole_apps_of_segment(segment["id"])
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serialize.pole_app)


@bp.route("/segments/<segment_id>/permit-applications", methods=["GET"])
@endpoint(ALL_ROLES)
def list_segment_permits(segment_id):
    segment = domain.get_segment(segment_id)
    rows = domain.permits_of_segment(segment["id"])
    status = filter_value("status")
    authority_type = filter_value("authority_type")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if authority_type is not None:
        rows = [r for r in rows if r["authority_type"] == authority_type]
    return paginate(rows, serialize.permit)


@bp.route("/segments/<segment_id>/splice-points", methods=["GET"])
@endpoint(ALL_ROLES)
def list_segment_splice_points(segment_id):
    segment = domain.get_segment(segment_id)
    rows = domain.splice_points_of_segment(segment["id"])
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serialize.splice_point)


@bp.route("/segments/<segment_id>/construction-method", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def select_construction_method(segment_id):
    payload = v.body()
    v.check_body(payload, ("method", "expected_route_version"))
    method = v.req_enum(payload, "method", calc.CONSTRUCTION_METHODS)
    expected_version = v.req_int(payload, "expected_route_version")

    segment = domain.get_segment(segment_id)
    route = domain.route_of_segment(segment)

    if route["version"] != expected_version:
        raise ApiError("ERR_STALE_ROUTE_VERSION")

    if segment["engineering_status"] not in ("WALKED", "METHOD_SELECTED"):
        raise ApiError("ERR_INVALID_SEGMENT_ENGINEERING_STATE")

    # moratorium resolution runs first: it can veto the selection outright
    moratorium_class = domain.resolve_moratorium_class(segment)
    if method == "TRENCH" and moratorium_class == "NO_OPEN_CUT":
        raise ApiError("ERR_OPEN_CUT_PROHIBITED")

    segment["construction_method"] = method
    segment["moratorium_class"] = moratorium_class
    segment["restoration_cost_cents"] = calc.restoration_cost_cents(
        segment["length_feet"], method, moratorium_class
    )
    segment["preliminary_cost_cents"] = calc.preliminary_cost_cents(
        segment["length_feet"], method, segment["terrain_class"]
    )
    segment["bid_ready_cost_cents"] = None
    segment["engineering_status"] = "METHOD_SELECTED"
    touch(segment)

    domain.recompute_route_cost_rollups(route)
    touch(route)
    return object_response(serialize.segment(segment))


@bp.route("/segments/<segment_id>/bid-ready-estimate", methods=["POST"])
@endpoint([ROLE_ROUTE_ENGINEER])
def bid_ready_estimate(segment_id):
    v.check_body(v.body(), ())
    segment = domain.get_segment(segment_id)

    if segment["engineering_status"] != "METHOD_SELECTED" or segment["construction_method"] is None:
        raise ApiError("ERR_INVALID_SEGMENT_ENGINEERING_STATE")

    segment["bid_ready_cost_cents"] = domain.compute_segment_bid_ready(segment)
    segment["engineering_status"] = "DESIGN_LOCKED"
    touch(segment)

    route = domain.route_of_segment(segment)
    domain.recompute_route_bid_ready_rollup(route)
    touch(route)
    return object_response(serialize.segment(segment))
