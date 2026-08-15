"""PartyProfile directory endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE_RESOURCE
from middleware import authorized, STAFF_READ_ROLES, ALL_ROLES
from response import success_list, success_object
from services.core import (
    new_record, public, get_pagination, sort_items, apply_filters, ROLE_TYPES,
)
from validate import get_body, req_str, req_enum, opt_bool, require_path

bp = Blueprint("profiles", __name__)


@bp.post("/party-profiles")
def create_profile():
    authorized(["CaseAdministrator", "TitleIXCoordinator"])
    body = get_body()
    # Tier 7: university_id uniqueness (before schema, per priority order, when
    # the field is present and typed).
    uid = body.get("university_id")
    if isinstance(uid, str):
        if any(p["university_id"] == uid for p in db["party_profiles"].values()):
            raise_error(ERR_DUPLICATE_RESOURCE,
                        f"university_id already registered: {uid}")
    # Tier 11: schema.
    full_name = req_str(body, "full_name")
    university_id = req_str(body, "university_id")
    role_type = req_enum(body, "role_type", ROLE_TYPES)
    email = req_str(body, "email")
    advisor_eligible = opt_bool(body, "advisor_eligible", False)
    rec = new_record("party_profiles", {
        "full_name": full_name,
        "university_id": university_id,
        "role_type": role_type,
        "email": email,
        "advisor_eligible": advisor_eligible,
    })
    return success_object(public(rec), 201)


@bp.get("/party-profiles")
def list_profiles():
    authorized(STAFF_READ_ROLES)
    items = list(db["party_profiles"].values())
    filters = {"role_type": request.args.get("role_type")}
    eligible_raw = request.args.get("advisor_eligible")
    eligible = None
    if eligible_raw is not None and eligible_raw != "":
        eligible = eligible_raw.lower() == "true"
    filters["advisor_eligible"] = eligible
    items = apply_filters(items, filters)
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/party-profiles/<rid>")
def get_profile(rid):
    authorized(list(ALL_ROLES))
    rec = require_path("party_profiles", rid)
    return success_object(public(rec))
