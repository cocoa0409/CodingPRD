"""Page routes: creation, retrieval, listing."""
from flask import Blueprint, request

from db import db
from helpers import base_entity, get_body, require_fields, list_response, lookup
from middleware import require_roles
from response import success_object
from services import expire_protections

bp = Blueprint("pages", __name__)

TOPIC_AREAS = {"GENERAL", "POLITICS", "HEALTH", "BIOGRAPHY", "HISTORY"}


@bp.post("/wiki/pages")
def create_page():
    user_id, _role = require_roles("VolunteerEditor")
    body = get_body()
    require_fields(body, ["title", "topic_area"])
    from errors import ApiError, ERR_INVALID_REQUEST
    if body["topic_area"] not in TOPIC_AREAS:
        raise ApiError(ERR_INVALID_REQUEST,
                       "topic_area must be one of GENERAL, POLITICS, HEALTH, "
                       "BIOGRAPHY, HISTORY", 400)
    p = base_entity()
    p.update({
        "title": body["title"],
        "topic_area": body["topic_area"],
        "protection_level": "NONE",
        "current_revision_id": None,
        "content_score": 0,
        "dispute_level": "NONE",
    })
    db.pages[p["id"]] = p
    return success_object(p, status=201)


@bp.get("/wiki/pages")
def list_pages():
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel",
                  "Anonymous", "PlatformAdmin")
    expire_protections()
    return list_response(db.pages, filters={
        "topic_area": request.args.get("topic_area"),
        "protection_level": request.args.get("protection_level"),
        "current_revision_id": request.args.get("current_revision_id"),
    })


@bp.get("/wiki/pages/<pageId>")
def get_page(pageId):
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel", "Anonymous")
    expire_protections()
    return success_object(lookup(db.pages, pageId, "Page"))
