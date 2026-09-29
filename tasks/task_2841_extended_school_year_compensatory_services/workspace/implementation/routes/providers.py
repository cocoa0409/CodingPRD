"""Provider roster (PRD section 3.5)."""
from flask import Blueprint

from auth import (COMPLIANCE_OFFICER, PROGRAM_COORDINATOR,
                  RELATED_SERVICE_PROVIDER, SPED_DIRECTOR, endpoint)
from envelope import created, ok, ok_list, paginate
from resolve import path_ref
from serialize import many, public
from store import creation_order, db, new_record, touch
from validate import body, opt_date, opt_enum, opt_int, req_date, req_enum, req_int, req_str

bp = Blueprint("providers", __name__)

ROLE_TYPES = ("SPED_TEACHER", "SLP", "OT", "PT", "COUNSELOR", "PARAEDUCATOR")
PROVIDER_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")
READ_ROLES = (PROGRAM_COORDINATOR, SPED_DIRECTOR, COMPLIANCE_OFFICER,
              RELATED_SERVICE_PROVIDER)


@bp.post("/esy/providers")
@endpoint((PROGRAM_COORDINATOR,))
def create_provider():
    data = body()
    provider = new_record("Provider", {
        "full_name": req_str(data, "full_name", 1, 60),
        "role_type": req_enum(data, "role_type", ROLE_TYPES),
        "credential_expires_on": req_date(data, "credential_expires_on"),
        "rate_cents_per_minute": req_int(data, "rate_cents_per_minute", 1, 2000),
        "max_weekly_minutes": req_int(data, "max_weekly_minutes", 1, 3000),
        "assigned_weekly_minutes": 0,
        "status": "ACTIVE",
    })
    db.providers[provider["id"]] = provider
    return created(public(provider))


@bp.patch("/esy/providers/<provider_id>")
@endpoint((PROGRAM_COORDINATOR,))
def update_provider(provider_id):
    provider = path_ref("provider", provider_id)
    data = body()
    status = opt_enum(data, "status", PROVIDER_STATUSES)
    credential = opt_date(data, "credential_expires_on")
    ceiling = opt_int(data, "max_weekly_minutes", 1, 3000)

    if status is not None:
        provider["status"] = status
    if credential is not None:
        provider["credential_expires_on"] = credential
    if ceiling is not None:
        provider["max_weekly_minutes"] = ceiling
    touch(provider)
    return ok(public(provider))


@bp.get("/esy/providers/<provider_id>")
@endpoint(READ_ROLES)
def get_provider(provider_id):
    return ok(public(path_ref("provider", provider_id)))


@bp.get("/esy/providers/<provider_id>/provider-assignments")
@endpoint(READ_ROLES)
def list_provider_assignments(provider_id):
    path_ref("provider", provider_id)
    rows = creation_order([a for a in db.assignments.values()
                           if a["provider_id"] == provider_id])
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)
