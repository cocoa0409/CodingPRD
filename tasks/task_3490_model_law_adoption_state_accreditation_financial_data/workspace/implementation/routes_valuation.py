"""Valuation and reserving standards (PRD 3.5) — segregation of duties."""

from flask import Blueprint

from auth import authenticate, require_role, ROLE_ACTUARY
from db import store, base_record, touch
from errors import ApiError
from serialize import serialize_standard
from util import get_body, req_str, ok_object

bp = Blueprint("valuation_standards", __name__)


@bp.post("/naic/valuation-standards")
def create_standard():
    principal = authenticate()
    require_role(principal, {ROLE_ACTUARY})
    body = get_body()
    code = req_str(body, "code")
    version_label = req_str(body, "version_label")
    guidance_text = req_str(body, "guidance_text")
    for s in store.standards.values():
        if s["code"] == code and s["version_label"] == version_label:
            raise ApiError(
                "ERR_DUPLICATE_STANDARD_VERSION",
                "A standard already exists for (%s, %s)" % (code, version_label),
                409,
            )
    rec = base_record()
    rec.update({
        "code": code,
        "version_label": version_label,
        "guidance_text": guidance_text,
        "author_user_id": principal.user_id,
        "status": "DRAFT",
    })
    store.standards[rec["id"]] = rec
    return ok_object(serialize_standard(rec), 201)


@bp.post("/naic/valuation-standards/<standard_id>/activate")
def activate_standard(standard_id):
    principal = authenticate()
    require_role(principal, {ROLE_ACTUARY})
    std = store.standards.get(standard_id)
    if std is None:
        raise ApiError(
            "ERR_VALUATION_STANDARD_NOT_FOUND",
            "Valuation standard not found: %s" % standard_id,
            404,
        )
    # State gate first, then the self-activation ban (PRD 3.5).
    if std["status"] != "DRAFT":
        raise ApiError(
            "ERR_STANDARD_NOT_DRAFT",
            "Standard %s is not DRAFT" % standard_id,
            409,
        )
    if principal.user_id == std["author_user_id"]:
        raise ApiError(
            "ERR_SELF_ACTIVATION_FORBIDDEN",
            "The author of a standard may not activate it",
            422,
        )
    # Cascade: any other ACTIVE version of the same code retires.
    for s in store.standards.values():
        if s["id"] != standard_id and s["code"] == std["code"] and s["status"] == "ACTIVE":
            s["status"] = "RETIRED"
            touch(s)
    std["status"] = "ACTIVE"
    touch(std)
    return ok_object(serialize_standard(std), 200)
