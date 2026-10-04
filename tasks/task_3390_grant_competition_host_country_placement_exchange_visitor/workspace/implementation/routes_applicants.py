"""Applicant registration / read, and per-applicant alumni profile listing."""

from flask import Blueprint

import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_ANONYMOUS,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_APPLICANT,
    READ_ROLES,
)
from errors import ApiError
from store import STORE, stamp_new
from validate import (
    body,
    check_unknown,
    req,
    as_str,
    as_enum,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("applicants", __name__)

APPLICANT_TYPES = ("ENROLLED_STUDENT", "INDEPENDENT")
ALUMNI_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)


@bp.post("/exchange/applicants")
def register_applicant():
    _, role = auth()
    require_roles(role, [ROLE_ANONYMOUS])
    payload = body()
    check_unknown(
        payload,
        {"full_name", "email", "applicant_type", "home_institution_name", "citizenship_country_code"},
    )
    full_name = as_str(req(payload, "full_name"), "full_name")
    email = as_str(req(payload, "email"), "email")
    applicant_type = as_enum(req(payload, "applicant_type"), "applicant_type", APPLICANT_TYPES)
    citizenship = as_str(req(payload, "citizenship_country_code"), "citizenship_country_code")
    home_institution = payload.get("home_institution_name")
    if applicant_type == "ENROLLED_STUDENT":
        if home_institution is None:
            raise V("home_institution_name is required for ENROLLED_STUDENT")
        home_institution = as_str(home_institution, "home_institution_name")
    else:
        if home_institution is not None:
            raise V("home_institution_name must be omitted for INDEPENDENT applicants")
    if any(a["email"] == email for a in STORE.applicants.values()):
        raise ApiError("ERR_DUPLICATE_EMAIL", 409, "An applicant with this email already exists")
    applicant = {
        "full_name": full_name,
        "email": email,
        "applicant_type": applicant_type,
        "home_institution_name": home_institution,
        "citizenship_country_code": citizenship,
    }
    stamp_new(applicant)
    STORE.applicants[applicant["id"]] = applicant
    return envelope.ok(serialize.applicant_out(applicant), 201)


@bp.get("/exchange/applicants/<aid>")
def get_applicant(aid):
    user, role = auth()
    require_roles(role, READ_ROLES)
    applicant = STORE.applicants.get(aid)
    if applicant is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND", 404, "No applicant with the given id")
    check_owner(role, user, applicant["id"])
    return envelope.ok(serialize.applicant_out(applicant))


@bp.get("/exchange/applicants/<aid>/alumni-profiles")
def list_alumni_by_applicant(aid):
    user, role = auth()
    require_roles(role, ALUMNI_READ_ROLES)
    applicant = STORE.applicants.get(aid)
    if applicant is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND", 404, "No applicant with the given id")
    check_owner(role, user, applicant["id"])
    limit, offset = pagination()
    items = [p for p in STORE.alumni.values() if p["applicant_id"] == aid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.alumni_out(p) for p in page], total, limit, offset)
