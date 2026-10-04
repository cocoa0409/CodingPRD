"""Chapter create / read."""

import re

from flask import Blueprint

from auth import require_roles
from db import STORE, new_entity
from errors import ApiError
from resp import ok, created
from serialize import ser_chapter
from util import body_json, req_str, req_int, req_field, bad

bp = Blueprint("chapters", __name__)

_PREFIX_RE = re.compile(r"^\d{1,5}$")


@bp.post("/wish-grant/chapters")
@require_roles("NationalAdmin")
def create_chapter():
    body = body_json()
    name = req_str(body, "name")
    prefixes = req_field(body, "territory_zip_prefixes")
    if not isinstance(prefixes, list) or len(prefixes) == 0:
        bad("territory_zip_prefixes must be a non-empty array")
    for p in prefixes:
        if not isinstance(p, str) or not _PREFIX_RE.match(p):
            bad("each territory_zip_prefixes entry must be a string of 1-5 digits")
    budget = req_int(body, "fiscal_year_budget_cents")
    if budget <= 0:
        bad("fiscal_year_budget_cents must be > 0")
    target = req_int(body, "target_avg_cost_per_wish_cents")
    if target <= 0:
        bad("target_avg_cost_per_wish_cents must be > 0")
    ch = new_entity(
        name=name,
        territory_zip_prefixes=list(prefixes),
        fiscal_year_budget_cents=budget,
        target_avg_cost_per_wish_cents=target,
    )
    STORE["chapters"][ch["id"]] = ch
    return created(ser_chapter(ch))


@bp.get("/wish-grant/chapters/<cid>")
@require_roles(
    "NationalAdmin", "WishCoordinator", "ChapterDirector",
    "NationalDirector", "InKindOfficer", "EligibilityReviewer",
)
def get_chapter(cid):
    ch = STORE["chapters"].get(cid)
    if ch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chapter not found")
    return ok(ser_chapter(ch))
