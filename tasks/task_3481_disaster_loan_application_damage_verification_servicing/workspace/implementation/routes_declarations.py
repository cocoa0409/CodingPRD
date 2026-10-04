"""POST /disaster-relief/disaster-declarations (PRD 3.1)."""

from datetime import timedelta

from flask import Blueprint

import calc
from auth import require_roles
from body import json_body, req_dt, req_enum, req_str
from domain import new_common
from envelope import success
from errors import raise_err
from store import all_rows, put
from serializers import serialize

bp = Blueprint("declarations", __name__)

DISASTER_TYPES = {"HURRICANE", "FLOOD", "EARTHQUAKE", "TORNADO", "WILDFIRE"}
PURPOSES = {"PHYSICAL_DAMAGE", "ECONOMIC_INJURY"}


def _parse_counties(data):
    counties = data.get("counties")
    if not isinstance(counties, list) or len(counties) == 0:
        raise_err("ERR_INVALID_REQUEST", "counties must be a non-empty array")
    seen = set()
    parsed = []
    for entry in counties:
        if not isinstance(entry, dict):
            raise_err("ERR_INVALID_REQUEST", "each county entry must be an object")
        fips = entry.get("county_fips")
        if not isinstance(fips, str) or fips == "":
            raise_err("ERR_INVALID_REQUEST", "county_fips is required")
        if fips in seen:
            raise_err("ERR_INVALID_REQUEST", "county_fips values must be unique within a declaration")
        seen.add(fips)
        purposes = entry.get("eligible_purposes")
        if (not isinstance(purposes, list)
                or any(p not in PURPOSES for p in purposes)):
            raise_err("ERR_INVALID_REQUEST", "eligible_purposes must list PHYSICAL_DAMAGE / ECONOMIC_INJURY")
        parsed.append({"county_fips": fips, "eligible_purposes": list(purposes)})
    return parsed


@bp.post("/disaster-relief/disaster-declarations")
@require_roles("SystemAdmin")
def create_declaration():
    data = json_body()
    declaration_number = req_str(data, "declaration_number")
    disaster_type = req_enum(data, "disaster_type", DISASTER_TYPES)
    start = req_dt(data, "incident_start_date")
    end = req_dt(data, "incident_end_date")
    declared = req_dt(data, "declared_date")
    if end < start:
        raise_err("ERR_INVALID_REQUEST", "incident_end_date must be on or after incident_start_date")
    counties = _parse_counties(data)
    for d in all_rows("declarations"):
        if d["declaration_number"] == declaration_number:
            raise_err("ERR_INVALID_REQUEST", "declaration_number must be unique")
    # Geography may not be double-declared for overlapping time (inclusive windows).
    for other in all_rows("declarations"):
        for new_c in counties:
            for old_c in other["counties"]:
                if old_c["county_fips"] != new_c["county_fips"]:
                    continue
                if start <= other["incident_end_date"] and end >= other["incident_start_date"]:
                    raise_err("ERR_DECLARATION_WINDOW_OVERLAP",
                              "county %s already covered by an overlapping declaration" % new_c["county_fips"])
    row = new_common()
    row.update({
        "declaration_number": declaration_number,
        "disaster_type": disaster_type,
        "incident_start_date": start,
        "incident_end_date": end,
        "declared_date": declared,
        "counties": counties,
        "physical_filing_deadline": declared + timedelta(days=calc.PHYSICAL_FILING_WINDOW_DAYS),
        "economic_injury_filing_deadline": declared + timedelta(days=calc.EIDL_FILING_WINDOW_DAYS),
        "status": "OPEN",
    })
    put("declarations", row)
    return success(serialize(row), 201)
