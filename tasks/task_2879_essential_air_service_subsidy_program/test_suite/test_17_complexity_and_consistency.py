"""Complexity and consistency corners: optimistic concurrency on the preference
filing, the declared tie-break chain behind the selection order, and the fact
that every award effect is already visible in the awarding response.

The harness restarts the API against an empty database before every test, so
each test builds all of its own preconditions through declared endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_one_decimal,
    assert_ratio,
    assert_score,
    assert_versioned_row,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    COMMUNITY_SUBSIDIZED,
    DEFAULT_CLOCK,
    EVAL_NOT_SELECTED,
    EVAL_SELECTED,
    EVAL_UNDER_EVALUATION,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    PROPOSAL_SUBMITTED,
    SERVICE_LEVEL_ENHANCED,
    SOLICITATION_AWARDED,
)
from test_helpers.test_users import ADMIN, ANALYST, OFFICER


# Proposal B offers one more weekly round trip at a price that lands on exactly
# the same subsidy per passenger as proposal A, so the composites tie.
TIED_SECOND_BID = {
    "service_level": SERVICE_LEVEL_ENHANCED,
    "weekly_round_trips": 13,
    "annual_subsidy_request_usd": 1733362.02,
    "payment_basis": PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
}

CHEAPER_SECOND_BID = {
    "service_level": SERVICE_LEVEL_ENHANCED,
    "weekly_round_trips": 13,
    "annual_subsidy_request_usd": 1700000.00,
}


def _two_ranked_candidates(api: ApiClient, second_overrides):
    """A CLOSED solicitation with two submitted candidates and no filing yet."""
    return fx.build_two_candidate_solicitation(
        api,
        clock=DEFAULT_CLOCK,
        second_overrides=dict(second_overrides),
        close=True,
    )


# ─── complexity_layers / preference_filing_rejects_a_stale_solicitation_version

def test_a_preference_filing_replayed_on_a_stale_version_is_refused(api: ApiClient):
    """The filing bumps the solicitation version, so the replay is a stale view.

    "This is exactly why the filing must carry `expected_solicitation_version` and why a mismatch is rejected with `ERR_STALE_VERSION` — a representative working from a stale read would otherwise silently displace a ranking it never saw."

    Design: Corner/complexity_layers/preference_filing_rejects_a_stale_solicitation_version
    """
    built = _two_ranked_candidates(api, CHEAPER_SECOND_BID)
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]
    community_headers = built["ref"].community_headers

    first_read = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )
    stale_version = first_read["version"]

    filed = validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                stale_version,
                f.ranking_entries(proposal_a_id, proposal_b_id),
                rationale="first filing",
            ),
            community_headers,
        ),
        201,
    )
    assert filed["preference_filing_count"] == 1
    assert filed["version"] == stale_version + 1

    replay = api.file_preferences(
        solicitation_id,
        f.preference_filing_payload(
            stale_version,
            f.ranking_entries(proposal_b_id, proposal_a_id),
            rationale="replayed on the stale version",
        ),
        community_headers,
    )
    validate_error(replay, E.ERR_STALE_VERSION, 412)

    unchanged = validate_success(api.get_solicitation(solicitation_id, ADMIN))
    assert unchanged["preference_filing_count"] == 1
    assert unchanged["version"] == stale_version + 1
    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation_id, ADMIN)
    )
    assert meta["total_count"] == 2
    assert [row["proposal_id"] for row in rows] == [proposal_a_id, proposal_b_id]
    assert {row["filing_sequence"] for row in rows} == {1}
    assert {row["rationale"] for row in rows} == {"first filing"}


def test_re_reading_the_solicitation_lets_the_superseding_filing_through(api: ApiClient):
    """The same payload succeeds once the representative files on the fresh version.

    "An accepted filing increments the solicitation's `preference_filing_count` by 1, creates one preference row per ranking entry stamped with a `filing_sequence` equal to that new count, records `filed_by_user_id` as the acting `X-User-ID` — which is the community's own `id` — and increments the solicitation's `version` by 1."

    Design: Corner/complexity_layers/preference_filing_rejects_a_stale_solicitation_version
    """
    built = _two_ranked_candidates(api, CHEAPER_SECOND_BID)
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]
    community_headers = built["ref"].community_headers

    first_version = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )["version"]
    validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                first_version,
                f.ranking_entries(proposal_a_id, proposal_b_id),
                rationale="first filing",
            ),
            community_headers,
        ),
        201,
    )

    second_read = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )
    assert second_read["version"] == first_version + 1

    refiled = validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                second_read["version"],
                f.ranking_entries(proposal_b_id, proposal_a_id),
                rationale="re-filed after re-reading",
            ),
            community_headers,
        ),
        201,
    )
    assert refiled["preference_filing_count"] == 2
    assert refiled["version"] == first_version + 2

    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation_id, ADMIN)
    )
    assert meta["total_count"] == 4
    assert [(row["filing_sequence"], row["rank"]) for row in rows] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
    ]
    current = [row for row in rows if row["filing_sequence"] == 2]
    assert [row["proposal_id"] for row in current] == [proposal_b_id, proposal_a_id]
    for row in current:
        assert row["filed_by_user_id"] == built["ref"].community_id
        assert row["rationale"] == "re-filed after re-reading"


# ─── complexity_layers / selector_policy_breaks_a_composite_score_tie_by_cost

def test_two_bids_at_the_same_cost_per_passenger_tie_on_the_composite_score(api: ApiClient):
    """Different sizes, identical per-passenger price, identical composite score.

    "The `composite_score` is the weighted sum of those three rounded components — preference points weighted 0.40, subsidy points weighted 0.35, service points weighted 0.25 — with the sum itself rounded half-up to four decimal places."

    Design: Corner/complexity_layers/selector_policy_breaks_a_composite_score_tie_by_cost
    """
    built = _two_ranked_candidates(api, TIED_SECOND_BID)
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]

    first = validate_success(api.get_proposal(proposal_a_id, ADMIN))
    second = validate_success(api.get_proposal(proposal_b_id, ADMIN))
    assert first["projected_annual_passengers"] == 8892
    assert second["projected_annual_passengers"] == 9633
    assert_money(first["subsidy_per_passenger_usd"], 179.94, "subsidy_per_passenger_usd")
    assert_money(second["subsidy_per_passenger_usd"], 179.94, "subsidy_per_passenger_usd")
    assert first["evaluation_state"] == EVAL_UNDER_EVALUATION
    assert second["evaluation_state"] == EVAL_UNDER_EVALUATION

    ranking = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert ranking["candidate_count"] == 2
    assert ranking["excluded_proposal_ids"] == []
    assert_score(ranking["top_composite_score"], 60.0000, "top_composite_score")
    assert ranking["top_proposal_id"] == proposal_a_id
    assert ranking["ranked_proposal_ids"] == [proposal_a_id, proposal_b_id]


def test_the_composite_tie_is_broken_by_the_lower_requested_subsidy(api: ApiClient):
    """The cheaper ask wins the tie, and its own terms are what the award books.

    "Ties are broken deterministically and in this order: the lower `annual_subsidy_request_usd` wins; if those tie, the greater `weekly_round_trips` wins; if those still tie, the earlier `created_at` wins."

    Design: Corner/complexity_layers/selector_policy_breaks_a_composite_score_tie_by_cost
    """
    built = _two_ranked_candidates(api, TIED_SECOND_BID)
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]

    agreement = validate_success(
        api.create_selection_order(
            solicitation_id,
            f.selection_order_payload(order_note="tie broken on requested subsidy"),
            OFFICER,
        ),
        201,
    )

    winner = validate_success(api.get_proposal(proposal_a_id, ADMIN))
    loser = validate_success(api.get_proposal(proposal_b_id, ADMIN))
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert loser["evaluation_state"] == EVAL_NOT_SELECTED
    assert_score(winner["composite_score"], 60.0000, "composite_score")
    assert_score(loser["composite_score"], 60.0000, "composite_score")

    assert agreement["proposal_id"] == proposal_a_id
    assert agreement["carrier_id"] == built["ref"].carrier_id
    assert_money(agreement["annual_subsidy_usd"], 1600000.00, "annual_subsidy_usd")
    assert agreement["payment_basis"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert agreement["min_weekly_round_trips"] == 12

    awarded = validate_success(api.get_solicitation(solicitation_id, ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["selected_proposal_id"] == proposal_a_id
    assert awarded["candidate_count_at_award"] == 2


# ─── consistency_model / award_effects_are_visible_in_the_awarding_response_itself

def _sole_candidate_closed_solicitation(api: ApiClient):
    fx.set_clock(api, DEFAULT_CLOCK)
    fx.publish_fuel_index(api, "2026-08", 2.4000)
    community = validate_success(
        api.create_community(f.community_payload(), ADMIN), 201
    )
    validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        ),
        201,
    )
    aircraft = validate_success(
        api.create_aircraft_type(f.aircraft_type_payload(), ADMIN), 201
    )
    carrier = validate_success(api.create_carrier(f.carrier_payload(), ADMIN), 201)
    solicitation = fx.open_solicitation(api, community["id"])
    proposal = fx.submitted_proposal(
        api, solicitation["id"], carrier["id"], aircraft["id"]
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    return {
        "community": community,
        "carrier": carrier,
        "solicitation": solicitation,
        "proposal": proposal,
    }


def test_the_award_response_already_carries_the_whole_agreement_ledger(api: ApiClient):
    """The 201 body is complete: derived terms, rate interval and open ledger.

    "It stamps `rate_effective_from` with the logical clock reading at award and computes `rate_effective_to` as that instant advanced by `term_months` calendar months; together they form the half-open rate interval that starts at `rate_effective_from` and stops short of `rate_effective_to`."

    Design: Corner/consistency_model/award_effects_are_visible_in_the_awarding_response_itself
    """
    setup = _sole_candidate_closed_solicitation(api)

    agreement = validate_success(
        api.create_selection_order(
            setup["solicitation"]["id"],
            f.selection_order_payload(order_note="award to sole candidate"),
            OFFICER,
        ),
        201,
    )
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement["min_weekly_round_trips"] == 12
    assert agreement["min_monthly_seats"] == 1976
    assert agreement["term_months"] == 24
    assert_one_decimal(agreement["annual_block_hours"], 1872.0, "annual_block_hours")
    assert_ratio(
        agreement["baseline_fuel_index_usd"], 2.4000, "baseline_fuel_index_usd"
    )
    assert_instant(
        agreement["rate_effective_from"], "2026-08-01T00:00:00Z", "rate_effective_from"
    )
    assert_instant(
        agreement["rate_effective_to"], "2028-08-01T00:00:00Z", "rate_effective_to"
    )
    assert_money(agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_money(agreement["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )
    assert_money(agreement["hold_in_premium_paid_usd"], 0.00, "hold_in_premium_paid_usd")
    assert agreement["cumulative_scheduled_departures"] == 0
    assert agreement["cumulative_completed_departures"] == 0
    assert agreement["predecessor_agreement_id"] is None
    assert agreement["terminated_at"] is None
    assert_versioned_row(agreement, expected_version=1)
    assert_obligation_identity(agreement)

    read_back = validate_success(api.get_service_agreement(agreement["id"], ADMIN))
    for field, value in agreement.items():
        assert read_back[field] == value, f"{field} differs from the award response"


def test_the_award_cascade_is_visible_to_the_reads_that_follow(api: ApiClient):
    """Solicitation, proposal and community are already in their post-award state.

    "If the community is `ELIGIBLE` it moves `ELIGIBLE → SUBSIDIZED`; if it was already `SUBSIDIZED` and this is an additional, non-overlapping agreement it stays `SUBSIDIZED`; in both cases `active_agreement_count` increases by 1."

    Design: Corner/consistency_model/award_effects_are_visible_in_the_awarding_response_itself
    """
    setup = _sole_candidate_closed_solicitation(api)
    community_id = setup["community"]["id"]

    agreement = validate_success(
        api.create_selection_order(
            setup["solicitation"]["id"],
            f.selection_order_payload(order_note="award to sole candidate"),
            OFFICER,
        ),
        201,
    )

    awarded = validate_success(
        api.get_solicitation(setup["solicitation"]["id"], OFFICER)
    )
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["selected_proposal_id"] == setup["proposal"]["id"]
    assert awarded["candidate_count_at_award"] == 1

    selected = validate_success(api.get_proposal(setup["proposal"]["id"], OFFICER))
    assert selected["submission_state"] == PROPOSAL_SUBMITTED
    assert selected["evaluation_state"] == EVAL_SELECTED
    assert_score(selected["composite_score"], 60.0000, "composite_score")

    community = validate_success(api.get_community(community_id, OFFICER))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1

    rows, meta = validate_paginated(
        api.list_service_agreements(
            ADMIN, {"community_id": community_id, "status": AGREEMENT_ACTIVE}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [agreement["id"]]
