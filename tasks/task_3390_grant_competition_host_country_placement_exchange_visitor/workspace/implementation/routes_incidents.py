"""EmergencyIncident endpoints: declare (ProgramOfficer), list, resolve."""

from flask import Blueprint

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_PLATFORM_ADMIN,
)
from errors import ApiError
from store import STORE, stamp_new, bump, now, now_iso
from timeutil import parse_iso
from validate import (
    body,
    check_unknown,
    req,
    as_text,
    as_enum,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("incidents", __name__)

INCIDENT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)
INCIDENT_CATEGORIES = ("MEDICAL", "SECURITY", "NATURAL_DISASTER", "CIVIL_UNREST")
INCIDENT_OUTCOMES = ("RESUME", "TERMINATE")


@bp.post("/exchange/grants/<gid>/incidents")
def create_incident(gid):
    _, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER])
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    payload = body()
    check_unknown(payload, {"category", "description"})
    category = as_enum(req(payload, "category"), "category", INCIDENT_CATEGORIES)
    description = as_text(req(payload, "description"), "description")
    # Priority 9: at most one OPEN incident per grant.
    for i in STORE.incidents.values():
        if i["grant_id"] == gid and i["status"] == "OPEN":
            raise ApiError(
                "ERR_ACTIVE_INCIDENT_EXISTS",
                409,
                "Grant already has an OPEN emergency incident",
            )
    # Priority 10: incidents are declared on ACTIVE grants.
    if grant["status"] != "ACTIVE":
        raise ApiError(
            "ERR_GRANT_NOT_ACTIVE", 409, "Incident declaration requires the grant to be ACTIVE"
        )
    incident = {
        "grant_id": gid,
        "category": category,
        "description": description,
        "status": "OPEN",
        "opened_at": now_iso(),
        "resolved_at": None,
        "outcome": None,
        "suspension_days": None,
    }
    stamp_new(incident)
    STORE.incidents[incident["id"]] = incident
    # Declaration suspends the grant in the same step.
    grant["status"] = "SUSPENDED"
    bump(grant)
    return envelope.ok(serialize.incident_out(incident), 201)


@bp.get("/exchange/grants/<gid>/incidents")
def list_incidents(gid):
    user, role = auth()
    require_roles(role, INCIDENT_READ_ROLES)
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    limit, offset = pagination()
    items = [i for i in STORE.incidents.values() if i["grant_id"] == gid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.incident_out(i) for i in page], total, limit, offset)


@bp.post("/exchange/incidents/<iid>/resolve")
def resolve_incident(iid):
    _, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER])
    incident = STORE.incidents.get(iid)
    if incident is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "No incident with the given id")
    payload = body()
    check_unknown(payload, {"outcome"})
    outcome = as_enum(req(payload, "outcome"), "outcome", INCIDENT_OUTCOMES)
    # Priority 6: the incident must be OPEN.
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an OPEN incident can be resolved")
    grant = STORE.grants[incident["grant_id"]]
    if outcome == "TERMINATE":
        # Early termination requires the clock strictly before end_date.
        if grant["end_date"] is not None and now() >= parse_iso(grant["end_date"]):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "The grant end_date has been reached; use COMPLETE instead",
            )
    domain.resolve_incident(incident, outcome)
    return envelope.ok(serialize.incident_out(incident))
