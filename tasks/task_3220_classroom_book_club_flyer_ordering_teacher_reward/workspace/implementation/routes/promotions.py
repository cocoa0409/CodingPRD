"""Promotion endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import new_record, serialize_promotion, parse_date, GRADE_BANDS
from routes.common import get_body, path_get, ref_get, req_field, req_int, req_enum, opt_enum

bp = Blueprint("promotions", __name__)


@bp.post("/club/promotions")
@require_roles("ClubAdmin")
def create_promotion():
    body = get_body()
    name = req_field(body, "name")
    kind = req_enum(body, "kind", {"BONUS_POINTS", "TITLE_INCENTIVE"})
    grade_band = opt_enum(body, "grade_band", GRADE_BANDS)
    title_id = body.get("title_id")
    multiplier_bp = body.get("multiplier_bp")
    bonus_per_unit = body.get("bonus_points_per_unit")
    starts_on = req_field(body, "starts_on")
    ends_on = req_field(body, "ends_on")
    if not isinstance(name, str):
        raise_err("ERR_INVALID_REQUEST", "name must be a string")
    starts = parse_date(starts_on, "starts_on")
    ends = parse_date(ends_on, "ends_on")
    # Priority 16: window sanity before shape (priority 17).
    if ends <= starts or ends <= db.clock.date:
        raise_err("ERR_PROMO_WINDOW_INVALID", "ends_on must be > starts_on and > current clock date")
    if title_id is not None:
        ref_get(db.titles, title_id, "Title")
    if kind == "BONUS_POINTS":
        if title_id is not None or not isinstance(multiplier_bp, int) or isinstance(multiplier_bp, bool) \
                or multiplier_bp < 100 or bonus_per_unit is not None:
            raise_err("ERR_PROMO_SHAPE_INVALID",
                      "BONUS_POINTS requires multiplier_bp >= 100 and title_id null")
    else:  # TITLE_INCENTIVE
        if title_id is None or not isinstance(bonus_per_unit, int) or isinstance(bonus_per_unit, bool) \
                or bonus_per_unit < 0 or multiplier_bp is not None:
            raise_err("ERR_PROMO_SHAPE_INVALID",
                      "TITLE_INCENTIVE requires title_id and bonus_points_per_unit >= 0")
    promo = new_record({
        "name": name,
        "kind": kind,
        "grade_band": grade_band,
        "title_id": title_id,
        "multiplier_bp": multiplier_bp,
        "bonus_points_per_unit": bonus_per_unit,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "_starts": starts,
        "_ends": ends,
    })
    db.promotions[promo["id"]] = promo
    return object_response(serialize_promotion(promo), 201)


@bp.get("/club/promotions")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def list_promotions():
    from services import promotion_status
    items = list(db.promotions.values())
    kind = request.args.get("kind")
    st = request.args.get("status")
    if kind:
        items = [p for p in items if p["kind"] == kind]
    if st:
        items = [p for p in items if promotion_status(p) == st]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_promotion(p) for p in page], total, limit, offset))


@bp.get("/club/promotions/<pid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def get_promotion(pid):
    return object_response(serialize_promotion(path_get(db.promotions, pid, "Promotion")))
