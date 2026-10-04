"""Studio and StudioFilm endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_STUDIO_NOT_FOUND, ERR_FILM_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_int, req_list, parse_pagination, paginate,
    success_object, success_list, stamp_new, touch, sort_by_created,
    parse_iso_datetime, iso_format,
)
from domain import (
    serialize_studio, serialize_film, serialize_conversion_order, serialize_screen_slot,
)

bp = Blueprint("studios", __name__)

VALID_FORMATS = {"PREMIUM_2D", "PREMIUM_3D", "PREMIUM_70MM"}


def get_studio_or_404(studio_id):
    s = db.studios.get(studio_id)
    if s is None:
        raise not_found(ERR_STUDIO_NOT_FOUND, f"Studio {studio_id} not found")
    return s


def get_film_or_404(film_id):
    f = db.films.get(film_id)
    if f is None:
        raise not_found(ERR_FILM_NOT_FOUND, f"Film {film_id} not found")
    return f


# -------------------- Studios --------------------

@bp.post("/v1/studios")
def create_studio():
    require_role("StudioRelationshipManager")
    body = get_body()
    studio_legal_name = req_str(body, "studio_legal_name")
    contact_email = req_str(body, "contact_email")
    s = {
        "studio_legal_name": studio_legal_name,
        "contact_email": contact_email,
        "status": "ONBOARDING",
    }
    stamp_new(s)
    db.studios[s["id"]] = s
    return success_object(serialize_studio(s), 201)


@bp.get("/v1/studios")
def list_studios():
    require_role("StudioRelationshipManager", "PostProductionScheduler", "ReleaseScheduler")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.studios.values()))
    status = request.args.get("status")
    if status:
        items = [s for s in items if s.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_studio(s) for s in page], total, limit, offset)


@bp.get("/v1/studios/<studio_id>")
def get_studio(studio_id):
    require_role("StudioRelationshipManager", "PostProductionScheduler", "ReleaseScheduler")
    s = get_studio_or_404(studio_id)
    return success_object(serialize_studio(s))


@bp.post("/v1/studios/<studio_id>/activate")
def activate_studio(studio_id):
    require_role("StudioRelationshipManager")
    s = get_studio_or_404(studio_id)
    if s.get("status") not in ("ONBOARDING", "SUSPENDED"):
        raise conflict(ERR_INVALID_STATE, f"Studio in state {s.get('status')} cannot be activated")
    s["status"] = "ACTIVE"
    touch(s)
    return success_object(serialize_studio(s))


@bp.post("/v1/studios/<studio_id>/suspend")
def suspend_studio(studio_id):
    require_role("StudioRelationshipManager")
    s = get_studio_or_404(studio_id)
    if s.get("status") != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, f"Studio in state {s.get('status')} cannot be suspended")
    s["status"] = "SUSPENDED"
    touch(s)
    # cascade: cancel SUBMITTED conversion orders on this studio's films
    film_ids = {f["id"] for f in db.films.values() if f.get("studio_id") == s["id"]}
    for co in db.conversion_orders.values():
        if co.get("studio_film_id") in film_ids and co.get("status") == "SUBMITTED":
            co["status"] = "CANCELLED"
            touch(co)
    return success_object(serialize_studio(s))


@bp.post("/v1/studios/<studio_id>/terminate")
def terminate_studio(studio_id):
    require_role("StudioRelationshipManager")
    s = get_studio_or_404(studio_id)
    if s.get("status") != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, f"Studio in state {s.get('status')} cannot be terminated")
    s["status"] = "TERMINATED"
    touch(s)
    film_ids = {f["id"] for f in db.films.values() if f.get("studio_id") == s["id"]}
    for co in db.conversion_orders.values():
        if co.get("studio_film_id") in film_ids and co.get("status") not in ("DELIVERED", "CANCELLED"):
            co["status"] = "CANCELLED"
            touch(co)
    return success_object(serialize_studio(s))


@bp.get("/v1/studios/<studio_id>/films")
def list_studio_films(studio_id):
    require_role("StudioRelationshipManager", "PostProductionScheduler", "ReleaseScheduler")
    s = get_studio_or_404(studio_id)
    limit, offset = parse_pagination()
    items = [f for f in db.films.values() if f.get("studio_id") == s["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_film(f) for f in page], total, limit, offset)


# -------------------- Films --------------------

@bp.post("/v1/films")
def create_film():
    require_role("StudioRelationshipManager")
    body = get_body()
    studio_id = req_str(body, "studio_id")
    title = req_str(body, "title")
    runtime_minutes = req_int(body, "runtime_minutes")
    if runtime_minutes <= 0:
        raise bad_request(ERR_INVALID_REQUEST, "runtime_minutes must be > 0")
    worldwide_release_date_raw = body.get("worldwide_release_date")
    wrd = parse_iso_datetime(worldwide_release_date_raw, "worldwide_release_date")
    format_targets = req_list(body, "format_targets")
    for f in format_targets:
        if f not in VALID_FORMATS:
            raise bad_request(ERR_INVALID_REQUEST, f"format_targets entry {f} invalid")
    if studio_id not in db.studios:
        raise not_found(ERR_STUDIO_NOT_FOUND, f"Studio {studio_id} not found")
    film = {
        "studio_id": studio_id,
        "title": title,
        "runtime_minutes": runtime_minutes,
        "worldwide_release_date": iso_format(wrd),
        "_worldwide_release_date_dt": wrd,
        "format_targets": format_targets,
        "status": "ANNOUNCED",
    }
    stamp_new(film)
    db.films[film["id"]] = film
    return success_object(serialize_film(film), 201)


@bp.get("/v1/films")
def list_films():
    require_role("StudioRelationshipManager", "PostProductionScheduler", "ReleaseScheduler", "BoxOfficeAnalyst")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.films.values()))
    studio_id = request.args.get("studio_id")
    status = request.args.get("status")
    if studio_id:
        items = [f for f in items if f.get("studio_id") == studio_id]
    if status:
        items = [f for f in items if f.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_film(f) for f in page], total, limit, offset)


@bp.get("/v1/films/<film_id>")
def get_film(film_id):
    require_role("StudioRelationshipManager", "PostProductionScheduler", "ReleaseScheduler", "BoxOfficeAnalyst")
    f = get_film_or_404(film_id)
    return success_object(serialize_film(f))


@bp.post("/v1/films/<film_id>/archive")
def archive_film(film_id):
    require_role("StudioRelationshipManager")
    f = get_film_or_404(film_id)
    if f.get("status") != "OUT_OF_WINDOW":
        raise conflict(ERR_INVALID_STATE, f"Film in state {f.get('status')} cannot be archived")
    f["status"] = "ARCHIVED"
    touch(f)
    return success_object(serialize_film(f))


@bp.get("/v1/films/<film_id>/conversion-orders")
def list_film_conversion_orders(film_id):
    require_role("StudioRelationshipManager", "PostProductionScheduler", "QualityAssuranceReviewer", "ReleaseScheduler")
    f = get_film_or_404(film_id)
    limit, offset = parse_pagination()
    items = [o for o in db.conversion_orders.values() if o.get("studio_film_id") == f["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_conversion_order(o) for o in page], total, limit, offset)


@bp.get("/v1/films/<film_id>/screen-slots")
def list_film_screen_slots(film_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "StudioRelationshipManager")
    f = get_film_or_404(film_id)
    limit, offset = parse_pagination()
    items = [s for s in db.screen_slots.values() if s.get("studio_film_id") == f["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_screen_slot(s) for s in page], total, limit, offset)
