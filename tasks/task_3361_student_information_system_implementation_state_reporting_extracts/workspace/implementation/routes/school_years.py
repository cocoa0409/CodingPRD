"""SchoolYear endpoints: create/list/get, open, close-for-reporting, archive."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import year_out
from validators import body, req_dt, req_int, req_str

bp = Blueprint("school_years", __name__)


def _get_year_or_404(yid):
    y = store["school_years"].get(yid)
    if not y:
        raise ApiError("ERR_SCHOOL_YEAR_NOT_FOUND", 404,
                       "No school year with the given id")
    return y


@bp.post("/sis/school-years")
def create_year():
    _uid, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    label = req_str(data, "label")
    start_date = req_dt(data, "start_date")
    end_date = req_dt(data, "end_date")
    instructional_days = req_int(data, "instructional_days")
    count_date = req_dt(data, "count_date")
    if instructional_days <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "instructional_days must be > 0")
    require_role(role, {"DistrictAdmin"})
    district = store["districts"].get(district_id)
    if not district:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "district_id does not reference an existing district")
    if not (end_date > start_date):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "end_date must be after start_date")
    if not (start_date <= count_date < end_date):
        raise ApiError("ERR_COUNT_DATE_OUTSIDE_YEAR", 422,
                       "count_date must lie within [start_date, end_date)")
    # Half-open windows of one district must not overlap; adjacency is allowed.
    for y in store["school_years"].values():
        if y["district_id"] != district_id:
            continue
        if start_date < y["end_date"] and y["start_date"] < end_date:
            raise ApiError("ERR_YEAR_WINDOW_OVERLAP", 409,
                           "School year window overlaps an existing year of the district")
    y = {"id": new_id(), "district_id": district_id, "label": label,
         "start_date": start_date, "end_date": end_date,
         "instructional_days": instructional_days, "count_date": count_date,
         "status": "PLANNING"}
    stamp_new(y)
    store["school_years"][y["id"]] = y
    return ok_obj(year_out(y), 201)


@bp.get("/sis/school-years")
def list_years():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    items = [y for y in store["school_years"].values()
             if (district_id is None or y["district_id"] == district_id)
             and (status is None or y["status"] == status)]
    items.sort(key=lambda y: (y["created_at"], y["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([year_out(y) for y in page], total, limit, offset)


@bp.get("/sis/school-years/<yid>")
def get_year(yid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(year_out(_get_year_or_404(yid)))


@bp.post("/sis/school-years/<yid>/open")
def open_year(yid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    y = _get_year_or_404(yid)
    if y["status"] != "PLANNING":
        raise ApiError("ERR_YEAR_NOT_PLANNING", 409,
                       "Open requires year PLANNING")
    district = store["districts"].get(y["district_id"])
    if not district or district["status"] != "LIVE":
        raise ApiError("ERR_DISTRICT_NOT_LIVE", 409,
                       "Opening a year requires district LIVE")
    y["status"] = "OPEN"
    touch(y)
    return ok_obj(year_out(y))


@bp.post("/sis/school-years/<yid>/close-for-reporting")
def close_year(yid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    y = _get_year_or_404(yid)
    if y["status"] != "OPEN":
        raise ApiError("ERR_YEAR_NOT_OPEN", 409,
                       "Close-for-reporting requires year OPEN")
    y["status"] = "CLOSED_FOR_REPORTING"
    touch(y)
    return ok_obj(year_out(y))


@bp.post("/sis/school-years/<yid>/archive")
def archive_year(yid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    y = _get_year_or_404(yid)
    if y["status"] != "ROLLED_OVER":
        raise ApiError("ERR_YEAR_NOT_ROLLED_OVER", 409,
                       "Archive requires year ROLLED_OVER")
    y["status"] = "ARCHIVED"
    touch(y)
    return ok_obj(year_out(y))
