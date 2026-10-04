"""Title endpoints: acquisition, renegotiation (OCC), reverse listings."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import (
    new_record, touch, serialize_title, serialize_promotion, serialize_offering,
    serialize_fair_title, serialize_donation, serialize_redemption,
    title_license_status, GRADE_BANDS, TITLE_FORMATS,
)
from routes.common import get_body, path_get, req_field, req_int, req_enum

bp = Blueprint("titles", __name__)


@bp.post("/club/titles")
@require_roles("ClubAdmin")
def create_title():
    body = get_body()
    isbn = req_field(body, "isbn")
    name = req_field(body, "name")
    fmt = req_enum(body, "format", TITLE_FORMATS)
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    base_price = req_int(body, "base_price_cents")
    points_cost = req_int(body, "points_cost")
    rights_holder = req_field(body, "rights_holder")
    royalty_cap = req_int(body, "royalty_cap_cents")
    if not isinstance(isbn, str) or not isinstance(name, str) or not isinstance(rights_holder, str):
        raise_err("ERR_INVALID_REQUEST", "isbn, name, rights_holder must be strings")
    for t in db.titles.values():
        if t["isbn"] == isbn:
            raise_err("ERR_INVALID_REQUEST", "isbn must be unique across all titles")
    if base_price <= 0 or points_cost <= 0 or royalty_cap <= 0:
        raise_err("ERR_INVALID_REQUEST", "base_price_cents, points_cost, royalty_cap_cents must be > 0")
    if royalty_cap < 0:  # validated against accrued (0 at creation)
        raise_err("ERR_ROYALTY_CAP_INVALID", "royalty_cap_cents below current royalty_accrued_cents")
    title = new_record({
        "isbn": isbn,
        "name": name,
        "format": fmt,
        "grade_band": grade_band,
        "base_price_cents": base_price,
        "points_cost": points_cost,
        "rights_holder": rights_holder,
        "royalty_cap_cents": royalty_cap,
        "royalty_accrued_cents": 0,
    })
    db.titles[title["id"]] = title
    return object_response(serialize_title(title), 201)


@bp.post("/club/titles/<tid>/acquire")
@require_roles("ClubAdmin")
def reacquire_title(tid):
    title = path_get(db.titles, tid, "Title")
    body = get_body()
    new_cap = req_int(body, "royalty_cap_cents")
    expected = req_int(body, "expected_title_version")
    if new_cap <= 0:
        raise_err("ERR_INVALID_REQUEST", "royalty_cap_cents must be > 0")
    if new_cap < title["royalty_accrued_cents"]:
        raise_err("ERR_ROYALTY_CAP_INVALID", "royalty_cap_cents below current royalty_accrued_cents")
    if expected != title["version"]:
        raise_err("ERR_STALE_VERSION", "expected_title_version does not match current version")
    title["royalty_cap_cents"] = new_cap
    # license_status derived; may flip SUSPENDED <-> ACTIVE with the new cap.
    title_license_status(title)
    touch(title)
    return object_response(serialize_title(title))


@bp.get("/club/titles")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent", "Donor")
def list_titles():
    from flask import request
    items = list(db.titles.values())
    gb = request.args.get("grade_band")
    fmt = request.args.get("format")
    ls = request.args.get("license_status")
    if gb:
        items = [t for t in items if t["grade_band"] == gb]
    if fmt:
        items = [t for t in items if t["format"] == fmt]
    if ls:
        items = [t for t in items if title_license_status(t) == ls]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_title(t) for t in page], total, limit, offset))


@bp.get("/club/titles/<tid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent", "Donor")
def get_title(tid):
    return object_response(serialize_title(path_get(db.titles, tid, "Title")))


@bp.get("/club/titles/<tid>/promotions")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def title_promotions(tid):
    path_get(db.titles, tid, "Title")
    items = sorted((p for p in db.promotions.values() if p["title_id"] == tid),
                   key=lambda p: (p["created_at"], p["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_promotion(p) for p in page], total, limit, offset))


@bp.get("/club/titles/<tid>/offerings")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def title_offerings(tid):
    path_get(db.titles, tid, "Title")
    items = sorted((o for o in db.offerings.values() if o["title_id"] == tid),
                   key=lambda o: (o["created_at"], o["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_offering(o) for o in page], total, limit, offset))


@bp.get("/club/titles/<tid>/fair-titles")
@require_roles("ClubAdmin", "SchoolAdmin")
def title_fair_titles(tid):
    path_get(db.titles, tid, "Title")
    items = sorted((ft for ft in db.fair_titles.values() if ft["title_id"] == tid),
                   key=lambda ft: (ft["created_at"], ft["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_fair_title(ft) for ft in page], total, limit, offset))


@bp.get("/club/titles/<tid>/donation-requests")
@require_roles("ClubAdmin", "SchoolAdmin", "Donor")
def title_donations(tid):
    path_get(db.titles, tid, "Title")
    items = sorted((d for d in db.donation_requests.values() if d["title_id"] == tid),
                   key=lambda d: (d["created_at"], d["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_donation(d) for d in page], total, limit, offset))


@bp.get("/club/titles/<tid>/redemptions")
@require_roles("ClubAdmin")
def title_redemptions(tid):
    path_get(db.titles, tid, "Title")
    items = sorted((r for r in db.redemptions.values() if r["title_id"] == tid),
                   key=lambda r: (r["created_at"], r["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_redemption(r) for r in page], total, limit, offset))
