"""Community preschool sites (PRD section 3.1)."""
from flask import Blueprint

from db import base_row, db
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import derive, rules
from validation import (
    SITE_STATUS,
    bad,
    body,
    opt_bool,
    opt_enum,
    opt_lang_list,
    q_bool,
    q_enum,
    q_str,
    req_int,
    req_str,
)

bp = Blueprint("sites", __name__)

READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "DistrictAdmin",
)


@bp.post("/community-sites")
@endpoint("PlacementAdministrator", "DistrictAdmin")
def create_site():
    data = body()
    name = req_str(data, "name")
    region_code = req_str(data, "region_code", max_len=20)
    licensed_capacity = req_int(data, "licensed_capacity", minimum=1)
    iep_seat_capacity = req_int(data, "iep_seat_capacity", minimum=1)
    languages_supported = opt_lang_list(data, "languages_supported", ["en"])
    screening_host_approved = opt_bool(data, "screening_host_approved", False)
    status = opt_enum(data, "status", SITE_STATUS, "ACTIVE")

    if iep_seat_capacity > licensed_capacity:
        bad("Field 'iep_seat_capacity' must not exceed licensed_capacity")

    row = base_row()
    row.update(
        {
            "name": name,
            "region_code": region_code,
            "licensed_capacity": licensed_capacity,
            "iep_seat_capacity": iep_seat_capacity,
            "languages_supported": languages_supported,
            "screening_host_approved": screening_host_approved,
            "status": status,
        }
    )
    db.community_sites[row["id"]] = row
    return object_response(derive.site_out(row), 201)


@bp.get("/community-sites/<site_id>")
@endpoint(*READ_ROLES)
def get_site(site_id):
    return object_response(derive.site_out(rules.fetch("community_sites", site_id)))


@bp.get("/community-sites")
@endpoint(*READ_ROLES)
def list_sites():
    region = q_str("region_code")
    host_approved = q_bool("screening_host_approved")
    status = q_enum("status", SITE_STATUS)
    rows = [
        r
        for r in db.community_sites.values()
        if matches(r, "region_code", region)
        and (host_approved is None or r["screening_host_approved"] == host_approved)
        and matches(r, "status", status)
    ]
    return paged(rows, derive.site_out)
