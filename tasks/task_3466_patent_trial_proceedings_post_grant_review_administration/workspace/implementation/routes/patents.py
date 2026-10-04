"""Patent registration and reads, plus docketing litigation matters beneath a
patent (PRD 3.1 and 3.2)."""

from flask import Blueprint

from db import store, strip_internal, parse_iso
from errors import raise_err, ERR_VALIDATION
from helpers import (
    require_roles, get_body, req_string, req_int, success_object,
    list_response, request_arg, ALL_ROLES,
)
from lookups import get_party, get_patent

bp = Blueprint("patents", __name__)


@bp.post("/ptab/patents")
def create_patent():
    require_roles("PlatformAdmin")
    body = get_body()
    patent_number = req_string(body, "patent_number")
    title = req_string(body, "title")
    issue_date = req_string(body, "issue_date")
    try:
        parse_iso(issue_date)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, "issue_date must be a valid ISO 8601 datetime")
    owner_id = req_string(body, "owner_id")
    total_claims = req_int(body, "total_claims", minimum=1)

    # Body FK existence (priority 3), then party-type rule (priority 5).
    owner = get_party(owner_id)
    if owner["party_type"] != "PATENT_OWNER":
        raise_err(ERR_VALIDATION, "owner_id must reference a PATENT_OWNER party")

    patent = store.new_common()
    patent.update({
        "patent_number": patent_number,
        "title": title,
        "issue_date": issue_date,
        "owner_id": owner_id,
        "total_claims": total_claims,
        "status": "ISSUED",
        "claims_alive": total_claims,
        "claims_cancelled_count": 0,
        "claims_amended_count": 0,
    })
    for existing in store.patents.values():
        if existing["patent_number"] == patent_number:
            raise_err(ERR_VALIDATION,
                      "patent_number must be unique across the system")
    store.patents[patent["id"]] = patent
    return success_object(strip_internal(patent), status=201)


@bp.get("/ptab/patents")
def list_patents():
    require_roles(*ALL_ROLES)
    owner_id = request_arg("owner_id")
    status = request_arg("status")
    items = store.patents.values()
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(list(items))


@bp.get("/ptab/patents/<patentId>")
def get_patent_route(patentId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_patent(patentId)))


@bp.post("/ptab/patents/<patentId>/litigation-matters")
def create_matter(patentId):
    require_roles("PlatformAdmin")
    # Path resource first (left-to-right), then body FK references.
    patent = get_patent(patentId)
    body = get_body()
    defendant_party_id = req_string(body, "defendant_party_id")
    court_name = req_string(body, "court_name")
    docket_number = req_string(body, "docket_number")
    complaint_served_date = req_string(body, "complaint_served_date")
    get_party(defendant_party_id)
    try:
        served_dt = parse_iso(complaint_served_date)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION,
                  "complaint_served_date must be a valid ISO 8601 datetime")
    trial_date = body.get("trial_date")
    trial_dt = None
    if trial_date is not None:
        if not isinstance(trial_date, str):
            raise_err(ERR_VALIDATION, "trial_date must be an ISO 8601 datetime")
        try:
            trial_dt = parse_iso(trial_date)
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION,
                      "trial_date must be a valid ISO 8601 datetime")

    matter = store.new_common()
    matter.update({
        "patent_id": patent["id"],
        "defendant_party_id": defendant_party_id,
        "court_name": court_name,
        "docket_number": docket_number,
        "complaint_served_date": complaint_served_date,
        "trial_date": trial_date,
        "status": "ACTIVE",
        "stay_reason": None,
        "estoppel_claims": [],
        "_served_dt": served_dt,
        "_trial_dt": trial_dt,
    })
    store.matters[matter["id"]] = matter
    return success_object(strip_internal(matter), status=201)
