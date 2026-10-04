"""IntegrationFeed endpoints: register, list, get, sync."""
from flask import Blueprint, request

from db import get_clock, new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import feed_out
from validators import body, req_enum, req_str

bp = Blueprint("feeds", __name__)

PLATFORMS = {"ASSESSMENT", "FOOD_SERVICE", "TRANSPORTATION", "LMS"}


def _get_feed_or_404(fid):
    f = store["feeds"].get(fid)
    if not f:
        raise ApiError("ERR_FEED_NOT_FOUND", 404,
                       "No integration feed with the given id")
    return f


@bp.post("/sis/integration-feeds")
def create_feed():
    _uid, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    platform = req_enum(data, "platform", PLATFORMS)
    require_role(role, {"DistrictAdmin"})
    district = store["districts"].get(district_id)
    if not district:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "district_id does not reference an existing district")
    for f in store["feeds"].values():
        if f["district_id"] == district_id and f["platform"] == platform:
            raise ApiError("ERR_DUPLICATE_FEED", 409,
                           "A feed for this platform already exists in the district")
    f = {"id": new_id(), "district_id": district_id, "platform": platform,
         "status": "PENDING", "last_synced_roster_count": None,
         "last_synced_at": None}
    stamp_new(f)
    store["feeds"][f["id"]] = f
    return ok_obj(feed_out(f), 201)


@bp.get("/sis/integration-feeds")
def list_feeds():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    district_id = request.args.get("district_id")
    platform = request.args.get("platform")
    status = request.args.get("status")
    items = [f for f in store["feeds"].values()
             if (district_id is None or f["district_id"] == district_id)
             and (platform is None or f["platform"] == platform)
             and (status is None or f["status"] == status)]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([feed_out(f) for f in page], total, limit, offset)


@bp.get("/sis/integration-feeds/<fid>")
def get_feed(fid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(feed_out(_get_feed_or_404(fid)))


@bp.post("/sis/integration-feeds/<fid>/sync")
def sync_feed(fid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    f = _get_feed_or_404(fid)
    district = store["districts"].get(f["district_id"])
    if district and district["status"] == "LIVE":
        # Success path: legal from PENDING, FAILED, and IN_SYNC (re-sync).
        f["status"] = "IN_SYNC"
        f["last_synced_roster_count"] = sum(
            1 for s in store["students"].values()
            if s["district_id"] == f["district_id"] and s["status"] == "ENROLLED")
        f["last_synced_at"] = get_clock()
    else:
        # District not LIVE -> FAILED as a plain business outcome, no error,
        # snapshot fields untouched.
        f["status"] = "FAILED"
    touch(f)
    return ok_obj(feed_out(f))
