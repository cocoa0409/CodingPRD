"""Logical clock, verification standards, counties and the voter roll."""

from flask import Blueprint

import response
import validation as v
from db import (db, get_county, get_standard, get_voter_record, new_config,
                parse_instant, serialize)
from errors import ApiError
from middleware import require_auth, require_county_match

ALL_ROLES = ("SosAdmin", "ElectionsExaminer", "TitleExaminer", "Proponent",
             "CountyClerk", "CirculatorAgent", "Challenger")

REGISTRATION_STATUSES = ("ACTIVE", "INACTIVE", "CANCELLED", "PENDING")

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["SosAdmin"])
    body = v.body()
    _, parsed = v.as_instant(v.required(body, "current_utc"), "current_utc")
    db.clock = parsed
    return response.empty()


# ---------------------------------------------------------------------------
# verification standards
# ---------------------------------------------------------------------------
@bp.route("/verification-standards", methods=["POST"])
def create_standard():
    require_auth(["SosAdmin"])
    body = v.body()
    jurisdiction_code = v.as_string(v.required(body, "jurisdiction_code"),
                                    "jurisdiction_code", min_len=2, max_len=8)
    gubernatorial_vote_total = v.as_int(v.required(body, "gubernatorial_vote_total"),
                                        "gubernatorial_vote_total", minimum=1)
    signature_pct_bps = v.as_int(v.required(body, "signature_pct_bps"),
                                 "signature_pct_bps", minimum=1, maximum=10000)
    sample_pct_bps = v.as_int(v.required(body, "sample_pct_bps"),
                              "sample_pct_bps", minimum=1, maximum=10000)
    sample_min_count = v.as_int(v.required(body, "sample_min_count"),
                                "sample_min_count", minimum=1)
    sufficiency_upper_bps = v.as_int(v.required(body, "sufficiency_upper_bps"),
                                     "sufficiency_upper_bps", minimum=10000)
    sufficiency_lower_bps = v.as_int(v.required(body, "sufficiency_lower_bps"),
                                     "sufficiency_lower_bps", minimum=1, maximum=10000)
    stratification_mode = v.as_enum(v.required(body, "stratification_mode"),
                                    "stratification_mode", ("POOLED", "STRATIFIED"))
    county_distribution_pct_bps = v.as_int(v.required(body, "county_distribution_pct_bps"),
                                           "county_distribution_pct_bps",
                                           minimum=1, maximum=10000)
    required_qualifying_counties = v.as_int(v.required(body, "required_qualifying_counties"),
                                             "required_qualifying_counties", minimum=1)
    rate_millicents = v.as_int(
        v.required(body, "verification_rate_millicents_per_signature"),
        "verification_rate_millicents_per_signature", minimum=1)
    county_surcharge_bps = v.as_int(v.required(body, "county_surcharge_bps"),
                                    "county_surcharge_bps", minimum=0, maximum=10000)
    cure_allowed = v.as_bool(v.optional(body, "cure_allowed", True), "cure_allowed")
    cure_window_days = v.as_int(v.optional(body, "cure_window_days", 30),
                                "cure_window_days", minimum=1)
    cure_eligibility_floor_bps = v.as_int(
        v.optional(body, "cure_eligibility_floor_bps", 8000),
        "cure_eligibility_floor_bps", minimum=0)
    circulation_window_days = v.as_int(v.optional(body, "circulation_window_days", 180),
                                       "circulation_window_days", minimum=1)

    for existing in db.standards.values():
        if existing["jurisdiction_code"] == jurisdiction_code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION_CODE")

    standard = new_config({
        "jurisdiction_code": jurisdiction_code,
        "gubernatorial_vote_total": gubernatorial_vote_total,
        "signature_pct_bps": signature_pct_bps,
        "sample_pct_bps": sample_pct_bps,
        "sample_min_count": sample_min_count,
        "sufficiency_upper_bps": sufficiency_upper_bps,
        "sufficiency_lower_bps": sufficiency_lower_bps,
        "stratification_mode": stratification_mode,
        "county_distribution_pct_bps": county_distribution_pct_bps,
        "required_qualifying_counties": required_qualifying_counties,
        "cure_allowed": cure_allowed,
        "cure_window_days": cure_window_days,
        "cure_eligibility_floor_bps": cure_eligibility_floor_bps,
        "circulation_window_days": circulation_window_days,
        "verification_rate_millicents_per_signature": rate_millicents,
        "county_surcharge_bps": county_surcharge_bps,
    })
    db.standards[standard["id"]] = standard
    return response.single(serialize(standard), 201)


@bp.route("/verification-standards/<standard_id>", methods=["GET"])
def read_standard(standard_id):
    require_auth(ALL_ROLES)
    return response.single(serialize(get_standard(standard_id)))


@bp.route("/verification-standards", methods=["GET"])
def list_standards():
    require_auth(ALL_ROLES)
    return response.listing(list(db.standards.values()), {
        "jurisdiction_code": ("str", "jurisdiction_code"),
        "stratification_mode": ("str", "stratification_mode"),
    })


# ---------------------------------------------------------------------------
# counties
# ---------------------------------------------------------------------------
@bp.route("/counties", methods=["POST"])
def create_county():
    require_auth(["SosAdmin"])
    body = v.body()
    county_code = v.as_string(v.required(body, "county_code"), "county_code",
                              min_len=2, max_len=12, upper=True)
    name = v.as_string(v.required(body, "name"), "name")
    registered_voter_count = v.as_int(v.required(body, "registered_voter_count"),
                                      "registered_voter_count", minimum=1)
    for existing in db.counties.values():
        if existing["county_code"] == county_code:
            raise ApiError("ERR_DUPLICATE_COUNTY_CODE")
    county = new_config({
        "county_code": county_code,
        "name": name,
        "registered_voter_count": registered_voter_count,
    })
    db.counties[county["id"]] = county
    return response.single(serialize(county), 201)


@bp.route("/counties/<county_id>", methods=["GET"])
def read_county(county_id):
    require_auth(ALL_ROLES)
    return response.single(serialize(get_county(county_id)))


@bp.route("/counties", methods=["GET"])
def list_counties():
    require_auth(ALL_ROLES)
    return response.listing(list(db.counties.values()),
                            {"county_code": ("str", "county_code")})


# ---------------------------------------------------------------------------
# voter roll
# ---------------------------------------------------------------------------
@bp.route("/voter-records", methods=["POST"])
def create_voter_record():
    user_id, role = require_auth(["SosAdmin", "CountyClerk"])
    body = v.body()
    county_id = v.as_id(v.required(body, "county_id"), "county_id")
    voter_id_number = v.as_string(v.required(body, "voter_id_number"), "voter_id_number")
    full_name = v.as_string(v.required(body, "full_name"), "full_name")
    signature_on_file_hash = v.as_string(v.required(body, "signature_on_file_hash"),
                                         "signature_on_file_hash")
    registration_date, registration_dt = v.as_instant(
        v.required(body, "registration_date"), "registration_date")
    registration_status = v.as_enum(v.optional(body, "registration_status", "ACTIVE"),
                                    "registration_status", REGISTRATION_STATUSES)
    county = get_county(county_id)
    require_county_match(county["id"], user_id, role)
    for existing in db.voter_records.values():
        if existing["voter_id_number"] == voter_id_number:
            raise ApiError("ERR_DUPLICATE_VOTER_ID_NUMBER")
    record = new_config({
        "county_id": county["id"],
        "voter_id_number": voter_id_number,
        "full_name": full_name,
        "registration_status": registration_status,
        "signature_on_file_hash": signature_on_file_hash,
        "registration_date": registration_date,
        "_registration_dt": registration_dt,
    })
    db.voter_records[record["id"]] = record
    return response.single(serialize(record), 201)


@bp.route("/voter-records/<voter_record_id>", methods=["GET"])
def read_voter_record(voter_record_id):
    require_auth(["SosAdmin", "ElectionsExaminer", "CountyClerk"])
    return response.single(serialize(get_voter_record(voter_record_id)))


@bp.route("/voter-records", methods=["GET"])
def list_voter_records():
    require_auth(["SosAdmin", "ElectionsExaminer", "CountyClerk"])
    return response.listing(list(db.voter_records.values()), {
        "county_id": ("str", "county_id"),
        "voter_id_number": ("str", "voter_id_number"),
        "registration_status": ("str", "registration_status"),
    })


@bp.route("/voter-records/<voter_record_id>/registration-status", methods=["PUT"])
def update_registration_status(voter_record_id):
    user_id, role = require_auth(["SosAdmin", "CountyClerk"])
    body = v.body()
    registration_status = v.as_enum(v.required(body, "registration_status"),
                                    "registration_status", REGISTRATION_STATUSES)
    record = get_voter_record(voter_record_id)
    require_county_match(record["county_id"], user_id, role)
    record["registration_status"] = registration_status
    return response.single(serialize(record))
