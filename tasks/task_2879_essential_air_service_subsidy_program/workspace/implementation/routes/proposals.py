"""Carrier proposals and the submission dimension (PRD 3.3)."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, PROGRAM_ADMIN,
                  SELECTION_OFFICER, endpoint)
from db import base_row, by_seq, dec, now, store, touch

bp = Blueprint("proposals", __name__)

SERVICE_LEVELS = ("ESSENTIAL_MINIMUM", "ENHANCED", "HUB_CONNECT")
PAYMENT_BASES = ("COMPLETED_FLIGHT_PRORATION", "SCHEDULED_FLIGHT_FLAT")
TERM_MONTHS = (12, 24, 36, 48)
PROPOSAL_ACTIONS = ("SUBMIT", "WITHDRAW")
GOOD_STANDING = ("ACTIVE", "PROBATION")


@bp.route("/proposals", methods=["POST"])
@endpoint(CARRIER)
def create_proposal():
    data = v.body()
    solicitation_id = v.id_field(data, "solicitation_id")
    carrier_id = v.id_field(data, "carrier_id")
    aircraft_type_id = v.id_field(data, "aircraft_type_id")
    service_level = v.enum_field(data, "service_level", SERVICE_LEVELS)
    round_trips = v.int_field(data, "weekly_round_trips", minimum=1, maximum=21)
    seats = v.int_field(data, "seats_per_departure", minimum=1, maximum=100)
    request_usd = v.num_field(data, "annual_subsidy_request_usd", places=2,
                              exclusive_minimum=0)
    term_months = v.int_field(data, "term_months", allowed=TERM_MONTHS)
    payment_basis = v.enum_field(data, "payment_basis", PAYMENT_BASES)

    carrier = lookups.carrier(carrier_id)
    lookups.aircraft_type(aircraft_type_id)
    solicitation = lookups.solicitation(solicitation_id)

    auth.require_owner(carrier["id"])

    projected, per_passenger = calc.proposal_pricing(round_trips, seats, request_usd)

    proposal = base_row(True)
    proposal.update({
        "solicitation_id": solicitation["id"],
        "carrier_id": carrier["id"],
        "aircraft_type_id": aircraft_type_id,
        "service_level": service_level,
        "weekly_round_trips": round_trips,
        "seats_per_departure": seats,
        "annual_subsidy_request_usd": request_usd,
        "term_months": term_months,
        "payment_basis": payment_basis,
        "projected_annual_passengers": projected,
        "subsidy_per_passenger_usd": per_passenger,
        "submission_state": "DRAFT",
        "evaluation_state": "NOT_EVALUATED",
        "composite_score": None,
    })
    store.proposals[proposal["id"]] = proposal
    return response.created(serializers.proposal(proposal))


@bp.route("/proposals/<pid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def read_proposal(pid):
    return response.ok(serializers.proposal(lookups.proposal(pid)))


@bp.route("/proposals", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_proposals():
    rows = list(store.proposals.values())
    for field in ("solicitation_id", "carrier_id", "aircraft_type_id",
                  "submission_state", "evaluation_state"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return response.paginate(by_seq(rows), serializers.proposal)


@bp.route("/proposals/<pid>/actions", methods=["POST"])
@endpoint(CARRIER)
def proposal_actions(pid):
    data = v.body()
    action = v.enum_field(data, "action", PROPOSAL_ACTIONS)
    v.str_field(data, "note", required=False, min_len=0, max_len=2000)
    proposal = lookups.proposal(pid)

    auth.require_owner(proposal["carrier_id"])

    if action == "WITHDRAW":
        if proposal["submission_state"] not in ("DRAFT", "SUBMITTED"):
            errors.fail(errors.ERR_PROPOSAL_NOT_SUBMITTABLE,
                        "A proposal already WITHDRAWN cannot be withdrawn again.")
        proposal["submission_state"] = "WITHDRAWN"
        touch(proposal)
        return response.ok(serializers.proposal(proposal))

    # --- SUBMIT: the most heavily gated carrier operation -------------------
    if proposal["submission_state"] != "DRAFT":
        errors.fail(errors.ERR_PROPOSAL_NOT_SUBMITTABLE,
                    "Only a DRAFT proposal may be submitted.")

    solicitation = lookups.solicitation(proposal["solicitation_id"])
    if solicitation["status"] != "OPEN":
        errors.fail(errors.ERR_SOLICITATION_NOT_OPEN,
                    "A solicitation in status %s accepts no submissions."
                    % solicitation["status"])

    carrier = lookups.carrier(proposal["carrier_id"])
    if carrier["status"] not in GOOD_STANDING:
        errors.fail(errors.ERR_CARRIER_NOT_IN_GOOD_STANDING,
                    "A carrier in standing %s may not submit a proposal."
                    % carrier["status"])

    aircraft = lookups.aircraft_type(proposal["aircraft_type_id"])
    if aircraft["is_retired"]:
        errors.fail(errors.ERR_AIRCRAFT_TYPE_RETIRED,
                    "Aircraft type %s has been retired from the program."
                    % aircraft["code"])

    closes_at = v.parse_stamp(solicitation["closes_at"])
    if now() > closes_at:
        errors.fail(errors.ERR_SOLICITATION_WINDOW_CLOSED,
                    "The solicitation's submission window closed at %s."
                    % solicitation["closes_at"])

    community = lookups.community(solicitation["community_id"])
    if proposal["weekly_round_trips"] < community["min_required_weekly_round_trips"]:
        errors.fail(errors.ERR_FREQUENCY_BELOW_MINIMUM,
                    "The community requires at least %d weekly round trips."
                    % community["min_required_weekly_round_trips"])

    weekly_seats = proposal["weekly_round_trips"] * 2 * proposal["seats_per_departure"]
    if (weekly_seats < community["min_required_weekly_seats"]
            or proposal["seats_per_departure"] > aircraft["seats"]):
        errors.fail(errors.ERR_SEATS_BELOW_MINIMUM,
                    "The offered seats do not satisfy the community minimum or "
                    "exceed the certificated seat count.")

    cap = community.get("subsidy_per_passenger_cap_usd")
    if cap is not None:
        projected, per_passenger = calc.proposal_pricing(
            proposal["weekly_round_trips"], proposal["seats_per_departure"],
            proposal["annual_subsidy_request_usd"])
        proposal["projected_annual_passengers"] = projected
        proposal["subsidy_per_passenger_usd"] = per_passenger
        if per_passenger is not None and per_passenger > dec(cap):
            errors.fail(errors.ERR_SUBSIDY_PER_PASSENGER_CAP_EXCEEDED,
                        "The per-passenger subsidy exceeds the community's cap of %s."
                        % cap)

    proposal["submission_state"] = "SUBMITTED"
    touch(proposal)
    return response.ok(serializers.proposal(proposal))


@bp.route("/proposals/<pid>/preferences", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_proposal_preferences(pid):
    proposal = lookups.proposal(pid)
    rows = [p for p in store.preferences.values()
            if p["proposal_id"] == proposal["id"]]
    rows.sort(key=lambda r: (r["filing_sequence"], r["_seq"]))
    return response.paginate(rows, serializers.preference)
