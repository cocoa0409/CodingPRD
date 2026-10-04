"""Partner libraries and works."""
from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE, ERR_INVALID_STATE, ERR_LIBRARY_HAS_ACTIVE_LOANS, not_found,
    raise_err, validation,
)
from middleware import require_roles
from models import serialize_library, serialize_work, stamp_new, touch
from response import success_object

bp = Blueprint("libraries_works", __name__)


@bp.post("/archive/partner-libraries")
def create_library():
    require_roles("LibraryAdmin")
    body = request.get_json(silent=True) or {}
    code = body.get("library_code")
    name = body.get("display_name")
    years = body.get("storage_commitment_years")
    if not isinstance(code, str) or not code:
        validation("library_code is required")
    if not isinstance(name, str) or not name:
        validation("display_name is required")
    if isinstance(years, bool) or not isinstance(years, int) or years < 5:
        validation("storage_commitment_years must be an integer >= 5")
    if any(l["library_code"] == code for l in db.libraries.values()):
        raise_err(ERR_DUPLICATE, "A partner library with this code already exists")
    lib = stamp_new()
    lib.update({
        "library_code": code,
        "display_name": name,
        "storage_commitment_years": years,
        "status": "ACTIVE",
    })
    db.libraries[lib["id"]] = lib
    return success_object(serialize_library(lib), status=201)


@bp.get("/archive/partner-libraries/<lid>")
def get_library(lid):
    require_roles("Admin", "LibraryAdmin")
    lib = db.libraries.get(lid)
    if lib is None:
        not_found("Partner library not found")
    return success_object(serialize_library(lib))


@bp.post("/archive/partner-libraries/<lid>/withdraw")
def withdraw_library(lid):
    require_roles("LibraryAdmin")
    lib = db.libraries.get(lid)
    if lib is None:
        not_found("Partner library not found")
    if lib["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Library is not ACTIVE")
    if any(
        it["owning_library_id"] == lid and it["status"] == "ON_LOAN"
        for it in db.items.values()
    ):
        raise_err(ERR_LIBRARY_HAS_ACTIVE_LOANS, "Library has items on loan")
    lib["status"] = "WITHDRAWN"
    touch(lib)
    for it in db.items.values():
        if it["owning_library_id"] == lid and it["status"] in ("LENDABLE", "DEPOSITED"):
            it["status"] = "RETIRED"
            touch(it)
    return success_object(serialize_library(lib))


@bp.post("/archive/works")
def create_work():
    require_roles("Admin")
    body = request.get_json(silent=True) or {}
    title = body.get("title")
    author = body.get("author")
    year = body.get("publication_year")
    if not isinstance(title, str) or not title:
        validation("title is required")
    if not isinstance(author, str) or not author:
        validation("author is required")
    if isinstance(year, bool) or not isinstance(year, int) or not (1450 <= year <= 2100):
        validation("publication_year must be an integer in 1450..2100")
    w = stamp_new()
    w.update({
        "title": title,
        "author": author,
        "publication_year": year,
        "_availability_cache": "AVAILABLE",
    })
    db.works[w["id"]] = w
    return success_object(serialize_work(w), status=201)


@bp.get("/archive/works/<wid>")
def get_work(wid):
    require_roles("Admin", "LibraryAdmin", "Patron")
    w = db.works.get(wid)
    if w is None:
        not_found("Work not found")
    return success_object(serialize_work(w))
