"""Geocoding the secured property and assigning a census tract (PRD 3.4)."""

from flask import Blueprint

import calc
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import object_response
from validate import Field, check, json_body, lookup

bp = Blueprint("geocodes", __name__)

CREATE_FIELDS = [
    Field("application_id", "string", required=True),
    Field("expected_application_version", "integer", required=True),
    Field("street_address", "string", required=True),
    Field("city", "string", required=True),
    Field("state_code", "string", required=True),
    Field("zip_code", "string", required=True),
    Field("county_fips", "string", required=True),
    Field("submitted_tract_code", "string"),
]

OVERRIDE_FIELDS = [
    Field("census_tract_id", "string", required=True),
    Field("override_reason", "string", required=True),
]


@bp.route("/hmda/geocode-assignments", methods=["POST"])
def create_geocode_assignment():
    authenticate(["LoanOfficer"])
    body = check(json_body(), CREATE_FIELDS)
    app = lookup(store.applications, body["application_id"], "ERR_APPLICATION_NOT_FOUND")

    # step 7 -- optimistic concurrency on the parent Application version
    if body["expected_application_version"] != app["version"]:
        fail("ERR_STALE_APPLICATION_VERSION")

    row = store.new_row()
    row.update({
        "application_id": app["id"],
        "census_tract_id": None,
        "street_address": body["street_address"],
        "city": body["city"],
        "state_code": body["state_code"],
        "zip_code": body["zip_code"],
        "county_fips": body["county_fips"],
        "submitted_tract_code": body.get("submitted_tract_code"),
        "candidate_count": 0,
        "msa_md_code": None,
        "override_reason": None,
        "is_current": True,
        "status": "PENDING",
    })
    calc.geocode_match_resolution(row)

    for existing in store.geocode_assignments.values():
        if existing["application_id"] == app["id"] and existing["is_current"]:
            existing["is_current"] = False
            store.bump(existing)

    store.geocode_assignments[row["id"]] = row
    store.bump(app)
    return object_response(S.geocode_assignment(row), 201)


@bp.route("/hmda/geocode-assignments/<assignment_id>/manual-override", methods=["POST"])
def manual_override(assignment_id):
    authenticate(["ComplianceAnalyst"])
    row = lookup(store.geocode_assignments, assignment_id, "ERR_GEOCODE_ASSIGNMENT_NOT_FOUND")
    body = check(json_body(), OVERRIDE_FIELDS)
    tract = lookup(store.census_tracts, body["census_tract_id"], "ERR_CENSUS_TRACT_NOT_FOUND")

    # step 8 -- state precondition
    if row["status"] not in ("AMBIGUOUS", "NOT_MATCHED"):
        fail("ERR_GEOCODE_NOT_OVERRIDABLE")

    # step 12 -- cross-field referential accuracy
    if tract["county_fips"] != row["county_fips"] or tract["state_code"] != row["state_code"]:
        fail("ERR_GEOCODE_TRACT_MISMATCH")

    row["status"] = "MANUAL_OVERRIDE"
    row["census_tract_id"] = tract["id"]
    row["msa_md_code"] = tract["msa_md_code"]
    row["override_reason"] = body["override_reason"]
    store.bump(row)
    return object_response(S.geocode_assignment(row))
