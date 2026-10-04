"""District endpoints: create/list/get, activate, suspend."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import district_out
from validators import body, req_str

bp = Blueprint("districts", __name__)


def _get_district_or_404(did):
    d = store["districts"].get(did)
    if not d:
        raise ApiError("ERR_DISTRICT_NOT_FOUND", 404, "No district with the given id")
    return d


@bp.post("/sis/districts")
def create_district():
    _uid, role = auth_context()
    data = body()
    name = req_str(data, "name")
    state_code = req_str(data, "state_code")
    require_role(role, {"PlatformAdmin"})
    d = {"id": new_id(), "name": name, "state_code": state_code,
         "status": "IMPLEMENTATION"}
    stamp_new(d)
    store["districts"][d["id"]] = d
    return ok_obj(district_out(d), 201)


@bp.get("/sis/districts")
def list_districts():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = [d for d in store["districts"].values()
             if status is None or d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([district_out(d) for d in page], total, limit, offset)


@bp.get("/sis/districts/<did>")
def get_district(did):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(district_out(_get_district_or_404(did)))


@bp.post("/sis/districts/<did>/activate")
def activate_district(did):
    _uid, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    d = _get_district_or_404(did)
    if d["status"] not in ("IMPLEMENTATION", "SUSPENDED"):
        raise ApiError("ERR_DISTRICT_NOT_ACTIVATABLE", 409,
                       "Activate requires district IMPLEMENTATION or SUSPENDED")
    d["status"] = "LIVE"
    touch(d)
    return ok_obj(district_out(d))


@bp.post("/sis/districts/<did>/suspend")
def suspend_district(did):
    _uid, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    d = _get_district_or_404(did)
    if d["status"] != "LIVE":
        raise ApiError("ERR_DISTRICT_NOT_LIVE", 409,
                       "Suspend requires district LIVE")
    d["status"] = "SUSPENDED"
    touch(d)
    return ok_obj(district_out(d))
