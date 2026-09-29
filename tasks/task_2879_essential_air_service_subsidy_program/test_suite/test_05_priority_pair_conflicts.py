"""Rejection precedence when a single submit call violates two rungs at once.

Each pair is exercised twice: once with only the lower-priority rule broken, so
it is shown to fire on its own, and once with both broken, so the ladder's
answer is unambiguous.
"""


from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import (
    CARRIER_ACTIVE,
    CARRIER_SUSPENDED,
    DEFAULT_CLOCK,
    EVAL_NOT_EVALUATED,
    PROPOSAL_DRAFT,
    PROPOSAL_SUBMIT,
    PROPOSAL_WITHDRAW,
    PROPOSAL_WITHDRAWN,
    SOLICITATION_OPEN,
    STANDING_SUSPEND,
)
from test_helpers.test_users import ADMIN

# The bid whose economics breach the CAPPED community's 200.00 ceiling:
# 12 round trips at 19 seats projects 8892 annual passengers, so a
# 1,800,000.00 request prices out at 202.43 per passenger.
_OVER_CAP_BID = {
    "weekly_round_trips": 12,
    "seats_per_departure": 19,
    "annual_subsidy_request_usd": 1800000.00,
}


# ─── proposal_state_gate_precedes_per_passenger_cap ───────────────────

def test_over_cap_draft_submission_is_refused_on_the_cap_alone(api):
    """With only the fiscal rule broken, the per-passenger cap answers the submit.

    "Finally the per-passenger price is re-derived at submission time, so that a community's cap is applied to the figures actually on the proposal: when the community's `subsidy_per_passenger_cap_usd` is set, the proposal's `subsidy_per_passenger_usd` must not exceed it, and a value exactly equal to the cap is accepted while anything above it is refused with `ERR_SUBSIDY_PER_PASSENGER_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/proposal_state_gate_precedes_per_passenger_cap
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    assert_money(
        ref.community["subsidy_per_passenger_cap_usd"],
        200.00,
        "subsidy_per_passenger_cap_usd",
    )
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        **_OVER_CAP_BID,
    )
    assert proposal["submission_state"] == PROPOSAL_DRAFT
    assert_money(
        proposal["subsidy_per_passenger_usd"], 202.43, "subsidy_per_passenger_usd"
    )

    response = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.carrier_headers,
    )
    validate_error(response, E.ERR_SUBSIDY_PER_PASSENGER_CAP_EXCEEDED, 422)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT
    assert unchanged["evaluation_state"] == EVAL_NOT_EVALUATED


def test_withdrawn_over_cap_proposal_is_refused_on_the_state_gate(api):
    """When the row is also out of DRAFT, the state gate outranks the cap breach.

    "When a request violates more than one rule, exactly one error is returned, and which one is fully determined by the ladder below."

    Design: Difficulty/priority_pair_validation_conflict/proposal_state_gate_precedes_per_passenger_cap
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        **_OVER_CAP_BID,
    )
    assert_money(
        proposal["subsidy_per_passenger_usd"], 202.43, "subsidy_per_passenger_usd"
    )
    withdrawn = get_success_data(
        api.proposal_action(
            proposal["id"],
            f.proposal_action_payload(PROPOSAL_WITHDRAW),
            ref.carrier_headers,
        )
    )
    assert withdrawn["submission_state"] == PROPOSAL_WITHDRAWN

    response = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.carrier_headers,
    )
    validate_error(response, E.ERR_PROPOSAL_NOT_SUBMITTABLE, 409)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_WITHDRAWN
    assert unchanged["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── carrier_standing_precedes_retired_aircraft_reference ─────────────

def _drafts_on_a_type_that_is_then_retired(api):
    """Two drafts on one aircraft type, after which the type is retired.

    Returns (ref, solicitation, draft_of_first_carrier, draft_of_second_carrier).
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    first = fx.draft_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    second = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        ref.aircraft_type_id,
        annual_subsidy_request_usd=1620000.00,
    )
    retired = get_success_data(
        api.retire_aircraft_type(
            ref.aircraft_type_id,
            f.retire_payload(note="type withdrawn from the fleet"),
            ADMIN,
        )
    )
    assert retired["is_retired"] is True
    return ref, solicitation, first, second


def test_retired_equipment_alone_refuses_a_good_standing_carrier(api):
    """With the carrier in good standing, the retired-equipment rule answers the submit.

    "The named aircraft type must not have been retired, or the refusal is `ERR_AIRCRAFT_TYPE_RETIRED`."

    Design: Difficulty/priority_pair_validation_conflict/carrier_standing_precedes_retired_aircraft_reference
    """
    ref, _solicitation, _first, second = _drafts_on_a_type_that_is_then_retired(api)
    standing = validate_success(api.get_carrier(ref.second_carrier_id, ADMIN))
    assert standing["status"] == CARRIER_ACTIVE

    response = api.proposal_action(
        second["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.second_carrier_headers,
    )
    validate_error(response, E.ERR_AIRCRAFT_TYPE_RETIRED, 422)

    unchanged = validate_success(api.get_proposal(second["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT


def test_suspended_carrier_hears_about_its_standing_before_the_equipment(api):
    """A suspended carrier bidding retired equipment is told about its standing first.

    "Because carrier standing (rung 8) precedes the equipment, frequency, seat and cap gates, a suspended carrier submitting an under-frequency proposal on retired equipment is told about its standing first."

    Design: Difficulty/priority_pair_validation_conflict/carrier_standing_precedes_retired_aircraft_reference
    """
    ref, _solicitation, first, _second = _drafts_on_a_type_that_is_then_retired(api)
    suspended = get_success_data(
        api.carrier_standing_action(
            ref.carrier_id,
            f.carrier_standing_payload(
                STANDING_SUSPEND, note="certificate action pending"
            ),
            ADMIN,
        )
    )
    assert suspended["status"] == CARRIER_SUSPENDED

    # A SUSPEND does not withdraw drafts, so both rules are live on this row.
    still_draft = validate_success(api.get_proposal(first["id"], ADMIN))
    assert still_draft["submission_state"] == PROPOSAL_DRAFT

    response = api.proposal_action(
        first["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.carrier_headers,
    )
    validate_error(response, E.ERR_CARRIER_NOT_IN_GOOD_STANDING, 409)

    unchanged = validate_success(api.get_proposal(first["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT
    assert unchanged["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── closed_window_precedes_frequency_floor ───────────────────────────

def _under_frequency_draft(api):
    """A DRAFT offering 10 weekly round trips against a floor of 12.

    Returns (ref, solicitation, proposal).
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    assert ref.community["min_required_weekly_round_trips"] == 12
    assert ref.community["min_required_weekly_seats"] == 400
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        weekly_round_trips=10,
        seats_per_departure=19,
        annual_subsidy_request_usd=1200000.00,
    )
    assert proposal["weekly_round_trips"] == 10
    return ref, solicitation, proposal


def test_inside_the_window_only_the_frequency_floor_bites(api):
    """Before the closing instant the frequency floor is the only broken rule.

    "The offered `weekly_round_trips` must be at least the community's `min_required_weekly_round_trips`, or the submission is refused with `ERR_FREQUENCY_BELOW_MINIMUM`."

    Design: Difficulty/priority_pair_validation_conflict/closed_window_precedes_frequency_floor
    """
    ref, solicitation, proposal = _under_frequency_draft(api)
    assert solicitation["status"] == SOLICITATION_OPEN

    response = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.carrier_headers,
    )
    validate_error(response, E.ERR_FREQUENCY_BELOW_MINIMUM, 422)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT


def test_past_closes_at_the_window_rule_answers_the_same_row(api):
    """Once the clock passes closes_at the temporal rule outranks the frequency floor.

    "The logical clock must be at or before the solicitation's `closes_at` — an attempt exactly at the closing instant is accepted, one strictly after it is refused with `ERR_SOLICITATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_window_precedes_frequency_floor
    """
    ref, solicitation, proposal = _under_frequency_draft(api)
    fx.set_clock(api, "2026-08-21T00:00:00Z")

    response = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        ref.carrier_headers,
    )
    validate_error(response, E.ERR_SOLICITATION_WINDOW_CLOSED, 422)

    # Neither the round nor the row moved, so the state gates never applied.
    still_open = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert still_open["status"] == SOLICITATION_OPEN
    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT
    assert unchanged["weekly_round_trips"] == 10
