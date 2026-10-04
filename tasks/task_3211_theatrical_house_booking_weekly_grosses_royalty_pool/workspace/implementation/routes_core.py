"""Companies, theatres (houses), productions."""
from flask import Blueprint, request

import errors as E
import services as S
from db import STORE
from middleware import require_roles, require_company_owns
from response import (new_common, ok_object, ok_array, paginate, require_field,
                      require_int, require_enum, get_json_body)

bp = Blueprint("core", __name__)

ANY = ("HouseManager", "CompanyRep", "BoxOfficeAgent")


# ---------------------------------------------------------------- companies

@bp.post("/theatres/companies")
def create_company():
    require_roles("HouseManager")
    body = get_json_body()
    name = require_field(body, "name")
    email = require_field(body, "contact_email")
    rec = new_common()
    rec.update({"name": name, "contact_email": email})
    STORE.companies[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/companies/<cid>")
def get_company(cid):
    require_roles(*ANY)
    rec = STORE.companies.get(cid)
    if not rec:
        raise E.not_found("Production company not found")
    return ok_object(rec)


@bp.get("/theatres/companies")
def list_companies():
    require_roles(*ANY)
    page, limit, offset, total = paginate(list(STORE.companies.values()), request.args)
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------- theatres

@bp.post("/theatres/houses")
def create_theatre():
    require_roles("HouseManager")
    body = get_json_body()
    name = require_field(body, "name")
    capacity = require_int(require_field(body, "capacity"), "capacity")
    size_class = require_enum(require_field(body, "size_class"), "size_class", S.SIZE_CLASSES)
    is_landmark = require_field(body, "is_landmark")
    rent = require_int(require_field(body, "base_weekly_rent_cents"), "base_weekly_rent_cents")
    if capacity <= 0:
        raise E.invalid_request("capacity must be > 0")
    if rent < 0:
        raise E.invalid_request("base_weekly_rent_cents must be >= 0")
    rec = new_common()
    rec.update({"name": name, "capacity": capacity, "size_class": size_class,
                "is_landmark": bool(is_landmark), "base_weekly_rent_cents": rent})
    STORE.theatres[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/houses/<tid>")
def get_theatre(tid):
    require_roles(*ANY)
    rec = STORE.theatres.get(tid)
    if not rec:
        raise E.not_found("Theatre not found")
    return ok_object(rec)


@bp.get("/theatres/houses")
def list_theatres():
    require_roles(*ANY)
    page, limit, offset, total = paginate(list(STORE.theatres.values()), request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/houses/<tid>/bookings")
def list_theatre_bookings(tid):
    require_roles(*ANY)
    if tid not in STORE.theatres:
        raise E.not_found("Theatre not found")
    items = [b for b in STORE.bookings.values() if b["theatre_id"] == tid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/houses/<tid>/capital-projects")
def list_theatre_projects(tid):
    require_roles(*ANY)
    if tid not in STORE.theatres:
        raise E.not_found("Theatre not found")
    items = [p for p in STORE.capital_projects.values() if p["theatre_id"] == tid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------- productions

@bp.post("/theatres/productions")
def create_production():
    user_id, _ = require_roles("CompanyRep")
    body = get_json_body()
    company_id = require_field(body, "company_id")
    company = STORE.companies.get(company_id)
    if not company:
        raise E.not_found("Production company not found")
    require_company_owns(STORE, user_id, company_id)
    title = require_field(body, "title")
    size_class = require_enum(require_field(body, "required_size_class"),
                              "required_size_class", S.SIZE_CLASSES)
    loadin = require_int(require_field(body, "required_loadin_hours"), "required_loadin_hours")
    loadout = require_int(require_field(body, "required_loadout_hours"), "required_loadout_hours")
    if loadin <= 0 or loadout <= 0:
        raise E.invalid_request("required_loadin_hours and required_loadout_hours must be > 0")
    rec = new_common()
    rec.update({"company_id": company_id, "title": title,
                "required_size_class": size_class,
                "required_loadin_hours": loadin, "required_loadout_hours": loadout})
    STORE.productions[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/productions/<pid>")
def get_production(pid):
    require_roles(*ANY)
    rec = STORE.productions.get(pid)
    if not rec:
        raise E.not_found("Production not found")
    return ok_object(rec)


@bp.get("/theatres/productions")
def list_productions():
    require_roles(*ANY)
    items = list(STORE.productions.values())
    company_id = request.args.get("company_id")
    if company_id:
        items = [p for p in items if p["company_id"] == company_id]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/productions/<pid>/royalty-participants")
def list_production_participants(pid):
    require_roles("HouseManager", "CompanyRep")
    if pid not in STORE.productions:
        raise E.not_found("Production not found")
    items = [p for p in STORE.royalty_participants.values() if p["production_id"] == pid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/productions/<pid>/discount-codes")
def list_production_codes(pid):
    require_roles(*ANY)
    if pid not in STORE.productions:
        raise E.not_found("Production not found")
    items = [c for c in STORE.discount_codes.values() if c["production_id"] == pid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)
