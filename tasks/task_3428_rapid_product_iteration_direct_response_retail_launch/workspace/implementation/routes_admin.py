"""PlatformAdmin domain: logical clock, launch seasons (+ freeze/unfreeze/close/
run-review), and category workspaces."""

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from errors import ApiError
from serializers import ser_agreement, ser_case, ser_category, ser_season
from services import (get_or_404, posture_gate, recompute_category, req_fk,
                      run_review, season_of_category)
from state import DB, base_fields, bump, touch
from util import body, by_creation, ok_object, paginate, req_int, req_string, req_dt

bp = Blueprint("admin", __name__)

ADMIN = ("PlatformAdmin",)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(ADMIN)
    dt = req_dt(body(), "to_iso8601")
    DB.clock = dt
    return ok_object({}, 200)


# ---------------------------------------------------------------------------
# launch seasons
# ---------------------------------------------------------------------------


@bp.post("/launch-seasons")
def create_season():
    require_roles(ADMIN)
    code = req_string(body(), "season_code")
    for s in DB.seasons.values():
        if s["season_code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", 400, "season_code must be unique")
    s = base_fields()
    s.update({
        "season_code": code,
        "posture": "SEASON_OPEN",
        "review_index": 0,
        "frozen_at_review_index": None,
        "guarded_since_review_index": None,
        "last_review_at": None,
        "penalty_accrual_cents": 0,
    })
    DB.seasons[s["id"]] = s
    return ok_object(ser_season(s), 201)


@bp.get("/launch-seasons/<sid>")
def get_season(sid):
    require_roles(ALL_ROLES)
    return ok_object(ser_season(get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")))


@bp.get("/launch-seasons/<sid>/categories")
def list_season_categories(sid):
    require_roles(ALL_ROLES)
    get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")
    items = [ser_category(c) for c in by_creation(DB.categories.values())
             if c["season_id"] == sid]
    return paginate(items)


@bp.post("/launch-seasons/<sid>/freeze")
def freeze_season(sid):
    require_roles(ADMIN)
    s = get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")
    if s["posture"] not in ("SEASON_OPEN", "SEASON_GUARDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SEASON_OPEN or SEASON_GUARDED season can be frozen")
    s["posture"] = "SEASON_FROZEN"
    s["frozen_at_review_index"] = s["review_index"]
    bump(s)
    return ok_object(ser_season(s))


@bp.post("/launch-seasons/<sid>/unfreeze")
def unfreeze_season(sid):
    require_roles(ADMIN)
    s = get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")
    if s["posture"] != "SEASON_FROZEN":
        raise ApiError("ERR_INVALID_STATE", 409, "season is not SEASON_FROZEN")
    if not s["review_index"] > s["frozen_at_review_index"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "at least one full run-review must complete after the freeze")
    if any(c["season_id"] == s["id"] and c["exposure_level"] == "SEVERE"
           for c in DB.categories.values()):
        raise ApiError("ERR_INVALID_STATE", 409, "a linked category is still SEVERE")
    s["posture"] = "SEASON_OPEN"
    s["frozen_at_review_index"] = None
    bump(s)
    return ok_object(ser_season(s))


@bp.post("/launch-seasons/<sid>/close")
def close_season(sid):
    require_roles(ADMIN)
    s = get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")
    if s["posture"] != "SEASON_OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SEASON_OPEN season can be closed")
    cat_ids = {c["id"] for c in DB.categories.values() if c["season_id"] == s["id"]}
    concept_ids = {c["id"] for c in DB.concepts.values() if c["category_id"] in cat_ids}
    variant_ids = {v["id"] for v in DB.variants.values() if v["concept_id"] in concept_ids}
    live = ("DRAFT", "TOOLED", "DR_TESTING", "RETAIL_LIVE", "REFRESH_CANDIDATE")
    if any(v["id"] in variant_ids and v["lifecycle"] in live
           for v in DB.variants.values()):
        raise ApiError("ERR_CLOSE_PRECONDITIONS_UNMET", 409,
                       "a variant in this season is still live")
    if any(c["variant_id"] in variant_ids and c["status"] == "OPEN"
           for c in DB.commitments.values()):
        raise ApiError("ERR_CLOSE_PRECONDITIONS_UNMET", 409,
                       "an OPEN commitment exists in this season")
    if any(r["variant_id"] in variant_ids and r["status"] == "OPEN"
           for r in DB.replenishments.values()):
        raise ApiError("ERR_CLOSE_PRECONDITIONS_UNMET", 409,
                       "an OPEN replenishment order exists in this season")
    if any(c["category_id"] in cat_ids and c["status"] in ("FILED", "ACTIVE")
           for c in DB.cases.values()):
        raise ApiError("ERR_CLOSE_PRECONDITIONS_UNMET", 409,
                       "a FILED or ACTIVE patent case exists in this season")
    s["posture"] = "SEASON_CLOSED"
    bump(s)
    return ok_object(ser_season(s))


@bp.post("/launch-seasons/<sid>/run-review")
def run_review_endpoint(sid):
    require_roles(ADMIN)
    s = get_or_404(DB.seasons, sid, "ERR_SEASON_NOT_FOUND")
    if s["posture"] == "SEASON_CLOSED":
        raise ApiError("ERR_SEASON_CLOSED", 409, "season is SEASON_CLOSED")
    run_review(s)
    return ok_object(ser_season(s))


# ---------------------------------------------------------------------------
# categories
# ---------------------------------------------------------------------------


@bp.post("/categories")
def create_category():
    require_roles(ADMIN)
    data = body()
    season = req_fk(data, "season_id", DB.seasons, "ERR_SEASON_NOT_FOUND")
    name = req_string(data, "name")
    crowding_base = req_int(data, "crowding_base", min_v=0, max_v=10)
    # category creation is the admin repair path: exempt from FROZEN, not CLOSED
    posture_gate(season, category_create=True)
    c = base_fields()
    c.update({
        "season_id": season["id"],
        "name": name,
        "crowding_base": crowding_base,
        "exposure_index": 0,
        "exposure_level": "CLEAR",
        "active_reserve_cents": 0,
    })
    DB.categories[c["id"]] = c
    # exposure is live from creation: index = crowding_base, banded immediately,
    # and a brand-new SEVERE category guards its season at once
    recompute_category(c)
    return ok_object(ser_category(c), 201)


@bp.get("/categories/<cid>")
def get_category(cid):
    require_roles(ALL_ROLES)
    return ok_object(ser_category(get_or_404(DB.categories, cid, "ERR_CATEGORY_NOT_FOUND")))


@bp.get("/categories/<cid>/retail-agreements")
def list_category_agreements(cid):
    require_roles(ALL_ROLES)
    get_or_404(DB.categories, cid, "ERR_CATEGORY_NOT_FOUND")
    items = [ser_agreement(a) for a in by_creation(DB.agreements.values())
             if a["category_id"] == cid]
    return paginate(items)


@bp.get("/categories/<cid>/patent-cases")
def list_category_cases(cid):
    require_roles(ALL_ROLES)
    get_or_404(DB.categories, cid, "ERR_CATEGORY_NOT_FOUND")
    items = [ser_case(c) for c in by_creation(DB.cases.values())
             if c["category_id"] == cid]
    return paginate(items)
