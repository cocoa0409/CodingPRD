"""Applicant and WatersSite endpoints (PRD §3.1)."""

from flask import Blueprint

from db import STORE, new_entity
from errors import api_err
from helpers import (RESOURCE_TYPES, get_body, req_enum, req_number,
                     req_str, req_str_list)
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import applicant_out, site_out

bp = Blueprint("applicants_sites", __name__)

ORG_TYPES = ("INDIVIDUAL", "CORPORATION", "GOVERNMENT", "NONPROFIT")
ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")


@bp.post("/wetland-permits/applicants")
def create_applicant():
    require_roles(["SystemAdmin"])
    body = get_body()
    legal_name = req_str(body, "legal_name")
    organization_type = req_enum(body, "organization_type", ORG_TYPES)
    contact_email = req_str(body, "contact_email")
    applicant = new_entity({
        "legal_name": legal_name,
        "organization_type": organization_type,
        "contact_email": contact_email,
        # prior_violation_count is computed on read; initialized at 0.
    })
    STORE["applicants"][applicant["id"]] = applicant
    return success_obj(applicant_out(applicant), 201)


@bp.get("/wetland-permits/applicants/<id>")
def get_applicant(id):
    user_id, role = require_roles(["SystemAdmin", "Applicant"])
    applicant = STORE["applicants"].get(id)
    if applicant is None:
        raise api_err("ERR_APPLICANT_NOT_FOUND", "No Applicant with id %s" % id)
    # An Applicant-role caller may only read its own record.
    check_ownership(user_id, role, id)
    return success_obj(applicant_out(applicant))


@bp.post("/wetland-permits/sites")
def create_site():
    require_roles(["SystemAdmin"])
    body = get_body()
    # Tier 5: body FK existence.
    applicant_id = req_str(body, "applicant_id")
    if applicant_id not in STORE["applicants"]:
        raise api_err("ERR_APPLICANT_NOT_FOUND",
                      "No Applicant with id %s" % applicant_id)
    # Tier 6: shape.
    site_name = req_str(body, "site_name")
    state_code = req_str(body, "state_code")
    watershed_code = req_str(body, "watershed_code")
    total_acres = req_number(body, "total_acres", minimum=0,
                             min_exclusive=True)
    resource_types = req_str_list(body, "resource_types_present",
                                  non_empty=True)
    for rtype in resource_types:
        if rtype not in RESOURCE_TYPES:
            raise api_err(
                "ERR_INVALID_REQUEST",
                "resource_types_present must be a subset of %s"
                % ", ".join(RESOURCE_TYPES))
    site = new_entity({
        "applicant_id": applicant_id,
        "site_name": site_name,
        "state_code": state_code,
        "watershed_code": watershed_code,
        "total_acres": total_acres,
        "resource_types_present": resource_types,
    })
    STORE["sites"][site["id"]] = site
    return success_obj(site_out(site), 201)


@bp.get("/wetland-permits/sites")
def list_sites():
    require_roles(list(ALL_ROLES))
    sites = apply_filters(STORE["sites"].values(),
                          {"applicant_id": "applicant_id"})
    return list_response(sites, site_out)


@bp.get("/wetland-permits/sites/<id>")
def get_site(id):
    require_roles(list(ALL_ROLES))
    site = STORE["sites"].get(id)
    if site is None:
        raise api_err("ERR_SITE_NOT_FOUND", "No WatersSite with id %s" % id)
    return success_obj(site_out(site))
