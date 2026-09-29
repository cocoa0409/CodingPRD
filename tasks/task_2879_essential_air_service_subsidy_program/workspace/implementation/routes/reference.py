"""Logical clock plus the four reference registers and community eligibility."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, ELIGIBILITY_ANALYST,
                  PROGRAM_ADMIN, SELECTION_OFFICER, endpoint)
from db import base_row, by_seq, fmt_ts, now_iso, store, touch

clock_bp = Blueprint("clock", __name__)
bp = Blueprint("reference", __name__)

CODE_PATTERN = r"^[A-Z]{3}$"
STATE_PATTERN = r"^[A-Z]{2}$"
AIRCRAFT_CODE_PATTERN = r"^[A-Z0-9]{3,5}$"

COMMUNITY_STATUSES = ("REGISTERED", "ELIGIBLE", "INELIGIBLE", "SUBSIDIZED",
                      "HOLD_IN", "TERMINATED")
DETERMINABLE_STATUSES = ("REGISTERED", "ELIGIBLE", "INELIGIBLE")
CARRIER_STANDING_ACTIONS = ("PLACE_ON_PROBATION", "SUSPEND", "DEBAR", "REINSTATE")


# =========================================================================
# the program's logical clock (PRD 2.5)
# =========================================================================
@clock_bp.route("/set_current_utc", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def set_current_utc():
    data = v.body()
    moment = v.datetime_field(data, "to_iso8601")
    store.clock = moment
    return response.ok({"current_utc": now_iso()})


# =========================================================================
# communities (PRD 3.1)
# =========================================================================
@bp.route("/communities", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_community():
    data = v.body()
    code = v.str_field(data, "code", min_len=3, max_len=3, pattern=CODE_PATTERN)
    name = v.str_field(data, "name", min_len=1, max_len=120)
    state_code = v.str_field(data, "state_code", min_len=2, max_len=2,
                             pattern=STATE_PATTERN)
    miles = v.num_field(data, "driving_miles_to_nearest_hub", places=1, minimum=0)
    enplanements = v.int_field(data, "enplanements_prior_year", minimum=0)
    min_rt = v.int_field(data, "min_required_weekly_round_trips", minimum=1, maximum=21)
    min_seats = v.int_field(data, "min_required_weekly_seats", minimum=0)

    for row in store.communities.values():
        if row["code"] == code:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE,
                        "A community with code %s already exists." % code)

    community = base_row(True)
    community.update({
        "code": code,
        "name": name,
        "state_code": state_code,
        "driving_miles_to_nearest_hub": miles,
        "enplanements_prior_year": enplanements,
        "min_required_weekly_round_trips": min_rt,
        "min_required_weekly_seats": min_seats,
        "status": "REGISTERED",
        "distance_band": None,
        "subsidy_per_passenger_cap_usd": None,
        "latest_determination_outcome": None,
        "active_agreement_count": 0,
    })
    store.communities[community["id"]] = community
    return response.created(serializers.community(community))


@bp.route("/communities/<cid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, ELIGIBILITY_ANALYST, SELECTION_OFFICER,
          COMMUNITY_REPRESENTATIVE, CARRIER)
def read_community(cid):
    return response.ok(serializers.community(lookups.community(cid)))


@bp.route("/communities", methods=["GET"])
@endpoint(PROGRAM_ADMIN, ELIGIBILITY_ANALYST, SELECTION_OFFICER)
def list_communities():
    rows = list(store.communities.values())
    status = request.args.get("status")
    state_code = request.args.get("state_code")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    rows = list(reversed(by_seq(rows)))
    return response.paginate(rows, serializers.community)


# =========================================================================
# eligibility determinations (PRD 3.2)
# =========================================================================
@bp.route("/communities/<cid>/eligibility-determinations", methods=["POST"])
@endpoint(ELIGIBILITY_ANALYST)
def create_determination(cid):
    data = v.body()
    waiver = v.bool_field(data, "waiver_requested", required=False, default=False)
    community = lookups.community(cid)

    if community["status"] not in DETERMINABLE_STATUSES:
        errors.fail(errors.ERR_COMMUNITY_NOT_ELIGIBLE,
                    "A community in status %s may not be re-determined."
                    % community["status"])

    assessment = calc.community_eligibility_assessment(community, waiver)

    row = base_row(False)
    row.update({
        "community_id": community["id"],
        "waiver_requested": waiver,
        "driving_miles_at_determination": assessment["driving_miles_at_determination"],
        "avg_daily_enplanements": assessment["avg_daily_enplanements"],
        "distance_band": assessment["distance_band"],
        "subsidy_per_passenger_cap_usd": assessment["subsidy_per_passenger_cap_usd"],
        "outcome": assessment["outcome"],
        "certified_by_user_id": auth.user_id(),
        "effective_at": now_iso(),
    })
    store.determinations[row["id"]] = row

    community["distance_band"] = assessment["distance_band"]
    community["latest_determination_outcome"] = assessment["outcome"]
    if assessment["outcome"] in ("ELIGIBLE", "ELIGIBLE_WITH_WAIVER"):
        community["subsidy_per_passenger_cap_usd"] = \
            assessment["subsidy_per_passenger_cap_usd"]
        community["status"] = "ELIGIBLE"
    else:
        community["status"] = "INELIGIBLE"
    touch(community)

    return response.created(serializers.determination(row))


@bp.route("/communities/<cid>/eligibility-determinations", methods=["GET"])
@endpoint(PROGRAM_ADMIN, ELIGIBILITY_ANALYST, SELECTION_OFFICER,
          COMMUNITY_REPRESENTATIVE)
def list_determinations(cid):
    community = lookups.community(cid)
    rows = [d for d in store.determinations.values()
            if d["community_id"] == community["id"]]
    outcome = request.args.get("outcome")
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return response.paginate(by_seq(rows), serializers.determination)


@bp.route("/communities/<cid>/solicitations", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_community_solicitations(cid):
    community = lookups.community(cid)
    rows = [s for s in store.solicitations.values()
            if s["community_id"] == community["id"]]
    status = request.args.get("status")
    reason = request.args.get("created_reason")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason is not None:
        rows = [r for r in rows if r["created_reason"] == reason]
    return response.paginate(by_seq(rows), serializers.solicitation)


# =========================================================================
# carriers (PRD 3.1, 3.8)
# =========================================================================
@bp.route("/carriers", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_carrier():
    data = v.body()
    name = v.str_field(data, "name", min_len=1, max_len=120)
    certificate_number = v.str_field(data, "certificate_number", min_len=1, max_len=32)

    for row in store.carriers.values():
        if row["certificate_number"] == certificate_number:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE,
                        "A carrier with certificate number %s already exists."
                        % certificate_number)

    carrier = base_row(True)
    carrier.update({
        "name": name,
        "certificate_number": certificate_number,
        "status": "ACTIVE",
        "latest_completion_factor": None,
        "latest_quality_score": None,
        "latest_performance_tier": None,
        "consecutive_watch_count": 0,
    })
    store.carriers[carrier["id"]] = carrier
    return response.created(serializers.carrier(carrier))


@bp.route("/carriers/<cid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, ELIGIBILITY_ANALYST, SELECTION_OFFICER,
          COMMUNITY_REPRESENTATIVE, CARRIER)
def read_carrier(cid):
    return response.ok(serializers.carrier(lookups.carrier(cid)))


@bp.route("/carriers/<cid>/standing", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def carrier_standing(cid):
    data = v.body()
    action = v.enum_field(data, "action", CARRIER_STANDING_ACTIONS)
    v.str_field(data, "note", required=False, min_len=0, max_len=2000)
    carrier = lookups.carrier(cid)
    status = carrier["status"]

    if action == "PLACE_ON_PROBATION":
        if status != "ACTIVE":
            errors.fail(errors.ERR_CARRIER_NOT_ACTIONABLE,
                        "Only an ACTIVE carrier may be placed on probation.")
        carrier["status"] = "PROBATION"
    elif action == "SUSPEND":
        if status not in ("ACTIVE", "PROBATION"):
            errors.fail(errors.ERR_CARRIER_NOT_ACTIONABLE,
                        "A carrier in status %s may not be suspended." % status)
        carrier["status"] = "SUSPENDED"
        for agreement in lookups.agreements_of_carrier(carrier["id"]):
            if agreement["status"] == "ACTIVE":
                agreement["status"] = "SUSPENDED"
                touch(agreement)
    elif action == "DEBAR":
        if status not in ("ACTIVE", "PROBATION", "SUSPENDED"):
            errors.fail(errors.ERR_CARRIER_NOT_ACTIONABLE,
                        "A carrier in status %s may not be debarred." % status)
        carrier["status"] = "DEBARRED"
        for proposal in store.proposals.values():
            if (proposal["carrier_id"] == carrier["id"]
                    and proposal["submission_state"] == "DRAFT"):
                proposal["submission_state"] = "WITHDRAWN"
                touch(proposal)
    else:
        if status not in ("PROBATION", "SUSPENDED"):
            errors.fail(errors.ERR_CARRIER_NOT_ACTIONABLE,
                        "A carrier in status %s may not be reinstated." % status)
        carrier["status"] = "ACTIVE"
        carrier["consecutive_watch_count"] = 0

    touch(carrier)
    return response.ok(serializers.carrier(carrier))


# =========================================================================
# aircraft types (PRD 3.1)
# =========================================================================
@bp.route("/aircraft-types", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_aircraft_type():
    data = v.body()
    code = v.str_field(data, "code", min_len=3, max_len=5,
                       pattern=AIRCRAFT_CODE_PATTERN)
    name = v.str_field(data, "name", min_len=1, max_len=120)
    seats = v.int_field(data, "seats", minimum=1, maximum=100)
    is_jet = v.bool_field(data, "is_jet")
    fuel_burn = v.num_field(data, "fuel_burn_gal_per_hour", places=1,
                            exclusive_minimum=0)
    hourly_cost = v.num_field(data, "hourly_operating_cost_usd", places=2,
                              exclusive_minimum=0)

    for row in store.aircraft_types.values():
        if row["code"] == code:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE,
                        "An aircraft type with code %s already exists." % code)

    aircraft = base_row(True)
    aircraft.update({
        "code": code,
        "name": name,
        "seats": seats,
        "is_jet": is_jet,
        "fuel_burn_gal_per_hour": fuel_burn,
        "hourly_operating_cost_usd": hourly_cost,
        "is_retired": False,
    })
    store.aircraft_types[aircraft["id"]] = aircraft
    return response.created(serializers.aircraft_type(aircraft))


@bp.route("/aircraft-types/<cid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def read_aircraft_type(cid):
    return response.ok(serializers.aircraft_type(lookups.aircraft_type(cid)))


@bp.route("/aircraft-types/<cid>/retire", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def retire_aircraft_type(cid):
    data = v.body(required=False)
    v.str_field(data, "note", required=False, min_len=0, max_len=2000)
    aircraft = lookups.aircraft_type(cid)
    aircraft["is_retired"] = True
    touch(aircraft)
    return response.ok(serializers.aircraft_type(aircraft))


# =========================================================================
# fuel indices (PRD 3.1)
# =========================================================================
@bp.route("/fuel-indices", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_fuel_index():
    data = v.body()
    index_month = v.month_field(data, "index_month")
    price = v.num_field(data, "price_per_gallon_usd", places=4, exclusive_minimum=0)

    if lookups.fuel_index_for_month(index_month) is not None:
        errors.fail(errors.ERR_DUPLICATE_RESOURCE,
                    "A fuel index for %s already exists." % index_month)

    row = base_row(False)
    row.update({"index_month": index_month, "price_per_gallon_usd": price})
    store.fuel_indices[row["id"]] = row
    return response.created(serializers.fuel_index(row))


@bp.route("/fuel-indices", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def list_fuel_indices():
    rows = list(store.fuel_indices.values())
    index_month = request.args.get("index_month")
    if index_month is not None:
        rows = [r for r in rows if r["index_month"] == index_month]
    rows.sort(key=lambda r: (r["index_month"], r["_seq"]))
    return response.paginate(rows, serializers.fuel_index)
