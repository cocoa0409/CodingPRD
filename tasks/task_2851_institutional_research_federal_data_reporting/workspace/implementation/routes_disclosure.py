"""DataRequest and DisclosureCell routes (disclosure-avoidance pipeline)."""
from flask import Blueprint

from auth import actor, require_roles
from db import (AVOIDANCE_METHODS, DISCLOSURE_READ_ROLES, REQUESTER_TYPES, public,
                stamp_new, store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import cells_of, get_cell, get_cycle, get_data_request
from svc_cycle import require_frozen
from svc_disclosure import aggregate_raw_count, cell_sort_key, screen
from validation import (get_body, opt_enum, opt_int, opt_string, req_enum, req_int,
                        req_string)

bp = Blueprint("disclosure", __name__)


def serialize_request(row):
    return public(row)


def serialize_cell(row):
    return public(row)


@bp.post("/reporting-cycles/<cycle_id>/data-requests")
def create_request(cycle_id):
    require_roles("DisclosureOfficer")
    body = get_body()
    requester_org = req_string(body, "requester_org", 3, 120)
    requester_type = req_enum(body, "requester_type", REQUESTER_TYPES)
    requested_metric_key = req_string(body, "requested_metric_key", 3, 64)
    avoidance_method = opt_enum(body, "avoidance_method", AVOIDANCE_METHODS,
                                default="SMALL_CELL_SUPPRESSION")
    min_cell_size = opt_int(body, "min_cell_size", 2, 10, default=5)
    cycle = get_cycle(cycle_id)
    require_frozen(cycle)
    row = {
        "cycle_id": cycle_id,
        "requester_org": requester_org,
        "requester_type": requester_type,
        "requested_metric_key": requested_metric_key,
        "avoidance_method": avoidance_method,
        "min_cell_size": min_cell_size,
        "status": "RECEIVED",
        "cell_count": 0,
        "suppressed_cell_count": 0,
        "released_cell_count": 0,
        "residual_disclosure_risk": False,
        "refusal_reason": None,
        "screened_at": None,
        "screened_by_user_id": None,
        "release_note": None,
    }
    stamp_new(row)
    store.data_requests[row["id"]] = row
    return created(serialize_request(row))


@bp.get("/data-requests/<request_id>")
def read_request(request_id):
    require_roles(*DISCLOSURE_READ_ROLES)
    return ok(serialize_request(get_data_request(request_id)))


@bp.get("/data-requests")
def list_requests():
    require_roles(*DISCLOSURE_READ_ROLES)
    rows = sorted(store.data_requests.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "status": "status",
                            "requester_type": "requester_type"})
    return paginate(rows, serialize_request)


@bp.post("/data-requests/<request_id>/screen")
def screen_request(request_id):
    require_roles("DisclosureOfficer")
    data_request = get_data_request(request_id)
    cycle = get_cycle(data_request["cycle_id"])
    require_frozen(cycle)
    if data_request["status"] != "RECEIVED":
        fail("ERR_INVALID_DATA_REQUEST_STATE",
             "only a RECEIVED data request can be screened")
    if data_request["cell_count"] < 1:
        fail("ERR_NO_CELLS_TO_SCREEN", "the request carries no crosstab cells")
    if aggregate_raw_count(data_request) < data_request["min_cell_size"]:
        data_request["status"] = "REFUSED"
        data_request["refusal_reason"] = "AGGREGATE_BELOW_MINIMUM"
    else:
        screen(data_request)
        data_request["status"] = "SCREENED"
    data_request["screened_at"] = store.now_iso()
    data_request["screened_by_user_id"] = actor()
    touch(data_request)
    return ok(serialize_request(data_request))


@bp.post("/data-requests/<request_id>/release")
def release_request(request_id):
    require_roles("DisclosureOfficer")
    body = get_body()
    note = opt_string(body, "release_note", 1, 2000)
    data_request = get_data_request(request_id)
    cycle = get_cycle(data_request["cycle_id"])
    require_frozen(cycle)
    if data_request["status"] != "SCREENED":
        fail("ERR_INVALID_DATA_REQUEST_STATE",
             "only a SCREENED data request can be released")
    if data_request["residual_disclosure_risk"] and \
            data_request["requester_type"] in ("EXTERNAL", "MEDIA"):
        fail("ERR_SMALL_CELL_DISCLOSURE",
             "a residual small-cell risk cannot be released outside the institution")
    data_request["status"] = "RELEASED" if data_request["released_cell_count"] >= 1 \
        else "SUPPRESSED_RELEASE"
    data_request["release_note"] = note
    touch(data_request)
    return ok(serialize_request(data_request))


# ---------------------------------------------------------------- DisclosureCell


@bp.post("/data-requests/<request_id>/cells")
def create_cell(request_id):
    require_roles("DisclosureOfficer")
    body = get_body()
    dimension_group = req_string(body, "dimension_group", 2, 64)
    dimension_key = req_string(body, "dimension_key", 1, 64)
    raw_count = req_int(body, "raw_count", 0, None)
    data_request = get_data_request(request_id)
    if data_request["status"] != "RECEIVED":
        fail("ERR_INVALID_DATA_REQUEST_STATE",
             "crosstab cells may only be added while the request is RECEIVED")
    for peer in cells_of(request_id):
        if (peer["dimension_group"] == dimension_group
                and peer["dimension_key"] == dimension_key):
            fail("ERR_DUPLICATE_CELL",
                 "this category is already present in the dimension group")
    row = {
        "request_id": request_id,
        "dimension_group": dimension_group,
        "dimension_key": dimension_key,
        "raw_count": raw_count,
        "suppression_state": "PENDING",
        "released_count": None,
    }
    stamp_new(row)
    store.cells[row["id"]] = row
    data_request["cell_count"] = len(cells_of(request_id))
    touch(data_request)
    return created(serialize_cell(row))


@bp.get("/disclosure-cells/<cell_id>")
def read_cell(cell_id):
    require_roles(*DISCLOSURE_READ_ROLES)
    return ok(serialize_cell(get_cell(cell_id)))


@bp.get("/disclosure-cells")
def list_cells():
    require_roles(*DISCLOSURE_READ_ROLES)
    rows = sorted(store.cells.values(),
                  key=lambda r: (cell_sort_key(r), r.get("_seq") or 0))
    rows = filter_eq(rows, {"request_id": "request_id",
                            "dimension_group": "dimension_group",
                            "suppression_state": "suppression_state"})
    return paginate(rows, serialize_cell)
