"""Solicitation rounds, community preference filings, ranking and the award."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import cascades
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, PROGRAM_ADMIN,
                  SELECTION_OFFICER, endpoint)
from db import (add_days, add_months, base_row, by_seq, dec, floor_int, fmt_ts,
                month_of, now, now_iso, q, q2, store, touch)

bp = Blueprint("solicitations", __name__)

SOLICITABLE_COMMUNITY_STATUSES = ("ELIGIBLE", "SUBSIDIZED", "HOLD_IN")
SOLICITATION_ACTIONS = ("CLOSE", "REOPEN", "CANCEL")


# =========================================================================
# solicitation rounds (PRD 3.3)
# =========================================================================
@bp.route("/solicitations", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_solicitation():
    data = v.body()
    community_id = v.id_field(data, "community_id")
    closes_at = v.datetime_field(data, "closes_at")
    community = lookups.community(community_id)

    if community["status"] not in SOLICITABLE_COMMUNITY_STATUSES:
        errors.fail(errors.ERR_COMMUNITY_NOT_ELIGIBLE,
                    "A community in status %s may not be solicited."
                    % community["status"])

    row = cascades.new_solicitation(community["id"], fmt_ts(closes_at), "INITIAL")
    return response.created(serializers.solicitation(row))


@bp.route("/solicitations/<sid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def read_solicitation(sid):
    return response.ok(serializers.solicitation(lookups.solicitation(sid)))


def _proposals_of(solicitation_id):
    return by_seq([p for p in store.proposals.values()
                   if p["solicitation_id"] == solicitation_id])


@bp.route("/solicitations/<sid>/actions", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def solicitation_actions(sid):
    data = v.body()
    action = v.enum_field(data, "action", SOLICITATION_ACTIONS)
    v.str_field(data, "note", required=False, min_len=0, max_len=2000)
    solicitation = lookups.solicitation(sid)
    status = solicitation["status"]

    if action == "CLOSE":
        if status != "OPEN":
            errors.fail(errors.ERR_SOLICITATION_NOT_OPEN,
                        "A solicitation in status %s may not be closed." % status)
        solicitation["status"] = "CLOSED"
        for proposal in _proposals_of(solicitation["id"]):
            if (proposal["submission_state"] == "SUBMITTED"
                    and proposal["evaluation_state"] == "NOT_EVALUATED"):
                proposal["evaluation_state"] = "UNDER_EVALUATION"
                touch(proposal)
    elif action == "REOPEN":
        if status != "CLOSED":
            errors.fail(errors.ERR_SOLICITATION_NOT_CLOSED,
                        "A solicitation in status %s may not be reopened." % status)
        solicitation["status"] = "OPEN"
        solicitation["round_number"] = solicitation["round_number"] + 1
        for proposal in _proposals_of(solicitation["id"]):
            if proposal["evaluation_state"] == "UNDER_EVALUATION":
                proposal["evaluation_state"] = "EXPIRED"
                touch(proposal)
    else:
        if status not in ("OPEN", "CLOSED"):
            errors.fail(errors.ERR_SOLICITATION_NOT_CLOSED,
                        "A solicitation in status %s may not be cancelled." % status)
        solicitation["status"] = "CANCELLED"
        for proposal in _proposals_of(solicitation["id"]):
            if proposal["evaluation_state"] in ("NOT_EVALUATED", "UNDER_EVALUATION"):
                proposal["evaluation_state"] = "EXPIRED"
                touch(proposal)

    touch(solicitation)
    return response.ok(serializers.solicitation(solicitation))


# =========================================================================
# community preference filings (PRD 3.4)
# =========================================================================
@bp.route("/solicitations/<sid>/preferences", methods=["POST"])
@endpoint(COMMUNITY_REPRESENTATIVE)
def file_preferences(sid):
    data = v.body()
    expected_version = v.int_field(data, "expected_solicitation_version", minimum=0)
    rankings = v.list_field(data, "rankings")
    rationale = v.str_field(data, "rationale", required=False, min_len=0,
                            max_len=2000, default="")

    entries = []
    for entry in rankings:
        if not isinstance(entry, dict):
            v.bad("Every rankings entry must be an object.")
        proposal_id = v.id_field(entry, "proposal_id")
        rank = v.int_field(entry, "rank", minimum=1)
        entries.append((proposal_id, rank))

    solicitation = lookups.solicitation(sid)
    resolved = [(lookups.proposal(pid), rank) for pid, rank in entries]

    auth.require_owner(solicitation["community_id"])

    if expected_version != solicitation["version"]:
        errors.fail(errors.ERR_STALE_VERSION,
                    "The solicitation has moved on to version %d."
                    % solicitation["version"])

    for proposal, _rank in resolved:
        if (proposal["solicitation_id"] != solicitation["id"]
                or proposal["submission_state"] != "SUBMITTED"):
            errors.fail(errors.ERR_PROPOSAL_NOT_IN_SOLICITATION,
                        "Proposal %s is not a submitted proposal of this solicitation."
                        % proposal["id"])

    submitted = [p for p in _proposals_of(solicitation["id"])
                 if p["submission_state"] == "SUBMITTED"]
    expected_ids = set(p["id"] for p in submitted)
    named_ids = [p["id"] for p, _ in resolved]
    ranks = sorted(rank for _, rank in resolved)
    if (len(named_ids) != len(expected_ids)
            or set(named_ids) != expected_ids
            or len(set(named_ids)) != len(named_ids)
            or ranks != list(range(1, len(submitted) + 1))):
        errors.fail(errors.ERR_INVALID_PREFERENCE_RANKING,
                    "The ranking must name every submitted proposal exactly once "
                    "with contiguous ranks starting at 1.")

    sequence = solicitation["preference_filing_count"] + 1
    solicitation["preference_filing_count"] = sequence
    for proposal, rank in resolved:
        row = base_row(False)
        row.update({
            "solicitation_id": solicitation["id"],
            "proposal_id": proposal["id"],
            "rank": rank,
            "filing_sequence": sequence,
            "rationale": rationale,
            "filed_by_user_id": auth.user_id(),
        })
        store.preferences[row["id"]] = row
    touch(solicitation)

    return response.created(serializers.solicitation(solicitation))


@bp.route("/solicitations/<sid>/preferences", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE)
def list_solicitation_preferences(sid):
    solicitation = lookups.solicitation(sid)
    rows = [p for p in store.preferences.values()
            if p["solicitation_id"] == solicitation["id"]]
    raw_sequence = request.args.get("filing_sequence")
    if raw_sequence is not None:
        wanted = response._as_int(raw_sequence)
        rows = [r for r in rows if r["filing_sequence"] == wanted]
    rows.sort(key=lambda r: (r["filing_sequence"], r["rank"], r["_seq"]))
    return response.paginate(rows, serializers.preference)


# =========================================================================
# the ranking preview (PRD 3.5) -- persists nothing
# =========================================================================
@bp.route("/solicitations/<sid>/ranking", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER)
def ranking_preview(sid):
    solicitation = lookups.solicitation(sid)
    community = lookups.community(solicitation["community_id"])
    candidates, excluded = calc.candidate_set(solicitation)
    scores = calc.score_candidates(solicitation, community, candidates)
    ranked = calc.rank_candidates(candidates, scores)

    payload = {
        "candidate_count": len(candidates),
        "top_proposal_id": ranked[0]["id"] if ranked else None,
        "top_composite_score": (scores[ranked[0]["id"]]["composite_score"]
                                if ranked else None),
        "ranked_proposal_ids": [p["id"] for p in ranked],
        "excluded_proposal_ids": [p["id"] for p in excluded],
    }
    return response.ok(payload)


# =========================================================================
# the selection order, the award and agreement booking (PRD 3.5)
# =========================================================================
def _hold_in_agreement(community_id):
    rows = [a for a in lookups.agreements_of_community(community_id)
            if a["status"] == "HOLD_IN"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[0] if rows else None


def _intervals_intersect(a_from, a_to, b_from, b_to):
    """Half-open intervals; merely touching is not an intersection."""
    return a_from < b_to and b_from < a_to


@bp.route("/solicitations/<sid>/selection-order", methods=["POST"])
@endpoint(SELECTION_OFFICER)
def selection_order(sid):
    data = v.body(required=False)
    v.str_field(data, "order_note", required=False, min_len=0, max_len=2000)
    solicitation = lookups.solicitation(sid)

    if solicitation["status"] != "CLOSED":
        errors.fail(errors.ERR_SOLICITATION_NOT_CLOSED,
                    "A solicitation in status %s may not be awarded."
                    % solicitation["status"])

    community = lookups.community(solicitation["community_id"])
    determination = lookups.latest_determination(community["id"])
    if (determination is not None
            and determination["certified_by_user_id"] == auth.user_id()):
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The analyst who certified this community's eligibility may "
                    "not issue its selection order.")

    candidates, _excluded = calc.candidate_set(solicitation)
    if not candidates:
        errors.fail(errors.ERR_NO_ELIGIBLE_PROPOSALS,
                    "No proposal of this solicitation qualifies for selection.")

    scores = calc.score_candidates(solicitation, community, candidates)
    ranked = calc.rank_candidates(candidates, scores)
    winner = ranked[0]

    moment = now()
    rate_effective_from = moment
    rate_effective_to = add_months(moment, winner["term_months"])

    for other in lookups.agreements_of_community(community["id"]):
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        other_from = v.parse_stamp(other["rate_effective_from"])
        other_to = v.parse_stamp(other["rate_effective_to"])
        if _intervals_intersect(rate_effective_from, rate_effective_to,
                                other_from, other_to):
            errors.fail(errors.ERR_RATE_INTERVAL_OVERLAP,
                        "The new rate interval intersects an agreement already in "
                        "force for this community.")

    buffer_ends = None
    for other in lookups.agreements_of_community(community["id"]):
        if (other["carrier_id"] != winner["carrier_id"]
                or other["status"] != "TERMINATED"
                or not other.get("terminated_at")):
            continue
        candidate_end = add_days(v.parse_stamp(other["terminated_at"]),
                                 calc.CARRIER_REENTRY_BUFFER_DAYS)
        if buffer_ends is None or candidate_end > buffer_ends:
            buffer_ends = candidate_end
    if buffer_ends is not None and moment < buffer_ends:
        errors.fail(errors.ERR_CARRIER_REENTRY_BUFFER,
                    "The carrier's re-entry buffer for this community has not "
                    "yet elapsed.")

    # ---- the award itself -------------------------------------------------
    for proposal in candidates:
        proposal["composite_score"] = scores[proposal["id"]]["composite_score"]
        proposal["evaluation_state"] = (
            "SELECTED" if proposal["id"] == winner["id"] else "NOT_SELECTED")
        touch(proposal)

    solicitation["status"] = "AWARDED"
    solicitation["selected_proposal_id"] = winner["id"]
    solicitation["candidate_count_at_award"] = len(candidates)
    touch(solicitation)

    predecessor = None
    if community["status"] == "HOLD_IN":
        predecessor = _hold_in_agreement(community["id"])

    round_trips = winner["weekly_round_trips"]
    seats = winner["seats_per_departure"]
    annual_subsidy = dec(winner["annual_subsidy_request_usd"])
    term_months = winner["term_months"]

    min_monthly_seats = floor_int(
        dec(round_trips) * Decimal("2") * dec(seats) * Decimal("52") / Decimal("12"))
    annual_block_hours = q(floor_int(
        dec(round_trips) * Decimal("2") * Decimal("52")
        * calc.BLOCK_HOURS_PER_DEPARTURE), 1)
    total_committed = q2(annual_subsidy * dec(term_months) / Decimal("12"))

    index_row = lookups.fuel_index_for_month(month_of(rate_effective_from))
    baseline = dec(index_row["price_per_gallon_usd"]) if index_row else None

    agreement = base_row(True)
    agreement.update({
        "community_id": community["id"],
        "carrier_id": winner["carrier_id"],
        "proposal_id": winner["id"],
        "predecessor_agreement_id": predecessor["id"] if predecessor else None,
        "min_weekly_round_trips": round_trips,
        "min_monthly_seats": min_monthly_seats,
        "annual_subsidy_usd": q2(annual_subsidy),
        "payment_basis": winner["payment_basis"],
        "term_months": term_months,
        "rate_effective_from": fmt_ts(rate_effective_from),
        "rate_effective_to": fmt_ts(rate_effective_to),
        "baseline_fuel_index_usd": baseline,
        "annual_block_hours": annual_block_hours,
        "total_committed_usd": total_committed,
        "disbursed_to_date_usd": Decimal("0.00"),
        "obligated_remaining_usd": q2(total_committed),
        "hold_in_premium_paid_usd": Decimal("0.00"),
        "cumulative_scheduled_departures": 0,
        "cumulative_completed_departures": 0,
        "cumulative_cancelled_carrier_departures": 0,
        "cumulative_cancelled_weather_departures": 0,
        "status": "ACTIVE",
        "terminated_at": None,
    })
    store.agreements[agreement["id"]] = agreement

    if predecessor is not None:
        cascades.release_hold_in_predecessor(predecessor, community)

    community["status"] = "SUBSIDIZED"
    cascades.increment_active_agreements(community)
    touch(community)

    return response.created(serializers.agreement(agreement))
