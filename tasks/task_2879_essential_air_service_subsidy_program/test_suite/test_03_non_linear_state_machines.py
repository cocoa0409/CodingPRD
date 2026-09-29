"""Non-linear state machines: revisitable cycles and parallel state dimensions.

Three machines in this program refuse to behave like a straight line. A
solicitation loops CLOSED -> OPEN -> CLOSED without bound, but every lap burns
the candidates it carried. A proposal advances two dimensions independently, so
a withdrawal freezes one of them mid-flight. A rate renegotiation loops
REQUESTED <-> COUNTERED under an explicit revision counter that terminates it.
"""


from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_ratio,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    EVAL_EXPIRED,
    EVAL_SELECTED,
    EVAL_UNDER_EVALUATION,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    PROPOSAL_SUBMITTED,
    PROPOSAL_WITHDRAW,
    PROPOSAL_WITHDRAWN,
    RENEG_ACCEPT,
    RENEG_ACCEPTED,
    RENEG_COUNTER,
    RENEG_COUNTERED,
    RENEG_REQUESTED,
    RENEG_REVISE,
    REVISION_LIMIT,
    SERVICE_LEVEL_ENHANCED,
    SOLICITATION_AWARDED,
    SOLICITATION_CLOSED,
    SOLICITATION_OPEN,
    SOLICITATION_REOPEN,
)
from test_helpers.test_users import ADMIN, ADMIN_NEGOTIATOR, OFFICER


# ─── solicitation_reopen_cycle_expires_candidacy_permanently ─────────

def test_reopen_lap_expires_the_round_one_candidate_permanently(api):
    """Reopening a round expires its UNDER_EVALUATION bid and re-closing cannot revive it.

    "**Reopening** a round moves it `CLOSED → OPEN`, is refused with `ERR_SOLICITATION_NOT_CLOSED` from any other status, increments `round_number` by 1, and moves every proposal of that solicitation whose `evaluation_state` is `UNDER_EVALUATION` to `EXPIRED` while leaving each proposal's `submission_state` untouched."

    Design: Difficulty/non_linear_state_machine/solicitation_reopen_cycle_expires_candidacy_permanently
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )

    closed = fx.close_solicitation(api, solicitation["id"])
    assert closed["status"] == SOLICITATION_CLOSED
    assert closed["round_number"] == 1
    row = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert row["evaluation_state"] == EVAL_UNDER_EVALUATION

    reopened = validate_success(
        api.solicitation_action(
            solicitation["id"],
            f.solicitation_action_payload(
                SOLICITATION_REOPEN, note="insufficient competition"
            ),
            ADMIN,
        )
    )
    assert reopened["status"] == SOLICITATION_OPEN
    assert reopened["round_number"] == 2

    row = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert row["evaluation_state"] == EVAL_EXPIRED
    assert row["submission_state"] == PROPOSAL_SUBMITTED

    reclosed = fx.close_solicitation(api, solicitation["id"])
    assert reclosed["status"] == SOLICITATION_CLOSED
    assert reclosed["round_number"] == 2

    row = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert row["evaluation_state"] == EVAL_EXPIRED
    assert row["submission_state"] == PROPOSAL_SUBMITTED


def test_selection_order_over_an_all_expired_pool_is_refused(api):
    """A re-closed round whose only bid expired has an empty candidate set.

    "If the filter leaves nothing, the order is refused with `ERR_NO_ELIGIBLE_PROPOSALS`."

    Design: Difficulty/non_linear_state_machine/solicitation_reopen_cycle_expires_candidacy_permanently
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    fx.close_solicitation(api, solicitation["id"])
    get_success_data(
        api.solicitation_action(
            solicitation["id"],
            f.solicitation_action_payload(SOLICITATION_REOPEN),
            ADMIN,
        )
    )
    fx.close_solicitation(api, solicitation["id"])

    response = api.create_selection_order(
        solicitation["id"],
        f.selection_order_payload(order_note="attempt award on an all-expired pool"),
        OFFICER,
    )
    validate_error(response, E.ERR_NO_ELIGIBLE_PROPOSALS, 409)

    row = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert row["status"] == SOLICITATION_CLOSED
    assert row.get("selected_proposal_id") is None
    assert row.get("candidate_count_at_award") is None
    assert (
        validate_success(api.get_proposal(proposal["id"], ADMIN))["evaluation_state"]
        == EVAL_EXPIRED
    )


def test_round_three_entrant_wins_while_the_expired_bid_never_scores(api):
    """After two reopen laps only the fresh round-three bid is a candidate.

    "The winning proposal moves `UNDER_EVALUATION → SELECTED` while every other candidate moves `UNDER_EVALUATION → NOT_SELECTED`, and the solicitation moves `CLOSED → AWARDED` recording `selected_proposal_id` as the winner and `candidate_count_at_award` as the size of the candidate set that was evaluated."

    Design: Difficulty/non_linear_state_machine/solicitation_reopen_cycle_expires_candidacy_permanently
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    first = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    fx.close_solicitation(api, solicitation["id"])
    get_success_data(
        api.solicitation_action(
            solicitation["id"],
            f.solicitation_action_payload(SOLICITATION_REOPEN),
            ADMIN,
        )
    )
    fx.close_solicitation(api, solicitation["id"])
    reopened = validate_success(
        api.solicitation_action(
            solicitation["id"],
            f.solicitation_action_payload(SOLICITATION_REOPEN, note="reopen for round 3"),
            ADMIN,
        )
    )
    assert reopened["round_number"] == 3

    second = fx.submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        ref.aircraft_type_id,
        weekly_round_trips=13,
        annual_subsidy_request_usd=1700000.00,
    )
    fx.close_solicitation(api, solicitation["id"])
    assert (
        validate_success(api.get_proposal(second["id"], ADMIN))["evaluation_state"]
        == EVAL_UNDER_EVALUATION
    )

    agreement = validate_success(
        api.create_selection_order(
            solicitation["id"],
            f.selection_order_payload(order_note="award to the round-3 entrant"),
            OFFICER,
        ),
        201,
    )

    awarded = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["candidate_count_at_award"] == 1
    assert awarded["selected_proposal_id"] == second["id"]

    loser = validate_success(api.get_proposal(first["id"], ADMIN))
    assert loser["evaluation_state"] == EVAL_EXPIRED
    assert loser.get("composite_score") is None

    winner = validate_success(api.get_proposal(second["id"], ADMIN))
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert agreement["carrier_id"] == ref.second_carrier_id


# ─── proposal_withdrawal_leaves_evaluation_dimension_frozen ──────────

def test_withdrawal_freezes_the_evaluation_dimension_mid_flight(api):
    """A withdrawn bid keeps the live UNDER_EVALUATION state it held when the round closed.

    "A `SUBMITTED` proposal remains `NOT_EVALUATED` until its solicitation closes; a withdrawal never touches `evaluation_state`, so a proposal can legitimately sit at `submission_state` `WITHDRAWN` while its `evaluation_state` is still `UNDER_EVALUATION`."

    Design: Difficulty/non_linear_state_machine/proposal_withdrawal_leaves_evaluation_dimension_frozen
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    larger = validate_success(
        api.create_aircraft_type(f.larger_aircraft_type_payload(), ADMIN), 201
    )
    solicitation = fx.open_solicitation(api, ref.community_id)
    first = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    second = fx.submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        larger["id"],
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        seats_per_departure=30,
        annual_subsidy_request_usd=2900000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    fx.file_preferences(api, solicitation, [first["id"], second["id"]])

    withdrawn = validate_success(
        api.proposal_action(
            first["id"],
            f.proposal_action_payload(PROPOSAL_WITHDRAW),
            ref.carrier_headers,
        )
    )
    assert withdrawn["submission_state"] == PROPOSAL_WITHDRAWN
    assert withdrawn["evaluation_state"] == EVAL_UNDER_EVALUATION

    row = validate_success(api.get_proposal(first["id"], ADMIN))
    assert row["submission_state"] == PROPOSAL_WITHDRAWN
    assert row["evaluation_state"] == EVAL_UNDER_EVALUATION
    assert (
        validate_success(api.get_proposal(second["id"], ADMIN))["submission_state"]
        == PROPOSAL_SUBMITTED
    )


def test_ranking_preview_drops_the_withdrawn_front_runner(api):
    """The candidate filter removes the withdrawn bid and leaves the runner-up alone on top.

    "Such a proposal simply drops out of contention, because the candidate filter of the selection ranking demands a `submission_state` of `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/proposal_withdrawal_leaves_evaluation_dimension_frozen
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    larger = validate_success(
        api.create_aircraft_type(f.larger_aircraft_type_payload(), ADMIN), 201
    )
    solicitation = fx.open_solicitation(api, ref.community_id)
    first = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    second = fx.submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        larger["id"],
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        seats_per_departure=30,
        annual_subsidy_request_usd=2900000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    fx.file_preferences(api, solicitation, [first["id"], second["id"]])
    get_success_data(
        api.proposal_action(
            first["id"],
            f.proposal_action_payload(PROPOSAL_WITHDRAW),
            ref.carrier_headers,
        )
    )

    preview = validate_success(api.get_ranking(solicitation["id"], OFFICER))
    assert preview["candidate_count"] == 1
    assert preview["top_proposal_id"] == second["id"]
    assert_ratio(preview["top_composite_score"], 80.0000, "top_composite_score")
    assert preview["ranked_proposal_ids"] == [second["id"]]
    assert first["id"] in preview["excluded_proposal_ids"]

    # The preview persists nothing, so the withdrawn row is still unscored.
    row = validate_success(api.get_proposal(first["id"], ADMIN))
    assert row.get("composite_score") is None
    assert row["evaluation_state"] == EVAL_UNDER_EVALUATION


def test_award_goes_to_the_runner_up_and_the_frozen_row_never_scores(api):
    """The award skips the withdrawn front runner and leaves its evaluation state frozen.

    "The `composite_score` is the weighted sum of those three rounded components — preference points weighted 0.40, subsidy points weighted 0.35, service points weighted 0.25 — with the sum itself rounded half-up to four decimal places."

    Design: Difficulty/non_linear_state_machine/proposal_withdrawal_leaves_evaluation_dimension_frozen
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    larger = validate_success(
        api.create_aircraft_type(f.larger_aircraft_type_payload(), ADMIN), 201
    )
    solicitation = fx.open_solicitation(api, ref.community_id)
    first = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    second = fx.submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        larger["id"],
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        seats_per_departure=30,
        annual_subsidy_request_usd=2900000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    fx.file_preferences(api, solicitation, [first["id"], second["id"]])
    get_success_data(
        api.proposal_action(
            first["id"],
            f.proposal_action_payload(PROPOSAL_WITHDRAW),
            ref.carrier_headers,
        )
    )

    agreement = validate_success(
        api.create_selection_order(
            solicitation["id"],
            f.selection_order_payload(order_note="award after the front runner withdrew"),
            OFFICER,
        ),
        201,
    )

    awarded = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["candidate_count_at_award"] == 1
    assert awarded["selected_proposal_id"] == second["id"]

    winner = validate_success(api.get_proposal(second["id"], ADMIN))
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert_ratio(winner["composite_score"], 80.0000, "composite_score")

    frozen = validate_success(api.get_proposal(first["id"], ADMIN))
    assert frozen["submission_state"] == PROPOSAL_WITHDRAWN
    assert frozen["evaluation_state"] == EVAL_UNDER_EVALUATION
    assert frozen.get("composite_score") is None

    assert agreement["carrier_id"] == ref.second_carrier_id
    assert_money(agreement["annual_subsidy_usd"], 2900000.00, "annual_subsidy_usd")


# ─── renegotiation_counter_revise_cycle_bounded_at_three_laps ────────

def test_three_counter_revise_laps_recompute_the_same_ceiling(api):
    """Each lap of the negotiation loop bumps revision_count and re-derives the ceiling.

    "The `Carrier` **revises** a `COUNTERED` renegotiation, which moves it `COUNTERED → REQUESTED`; the revision must carry `revised_annual_subsidy_usd`, which replaces `requested_annual_subsidy_usd` and causes `justified_delta_usd` and `ceiling_annual_subsidy_usd` to be recomputed from scratch, and it increases `revision_count` by 1."

    Design: Difficulty/non_linear_state_machine/renegotiation_counter_revise_cycle_bounded_at_three_laps
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.publish_fuel_index(api, "2027-02", 3.1000)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    renegotiation = fx.file_fuel_renegotiation(api, award, "2027-02", 1750000.00)

    assert renegotiation["status"] == RENEG_REQUESTED
    assert renegotiation["revision_count"] == 0
    assert_ratio(renegotiation["current_fuel_index_usd"], 3.1000, "current_fuel_index_usd")
    assert_money(renegotiation["fuel_cost_delta_usd"], 89107.20, "fuel_cost_delta_usd")
    assert_money(renegotiation["justified_delta_usd"], 71285.76, "justified_delta_usd")
    assert_money(
        renegotiation["ceiling_annual_subsidy_usd"],
        1671285.76,
        "ceiling_annual_subsidy_usd",
    )

    for lap, revised_amount in enumerate([1740000.00, 1730000.00, 1700000.00], start=1):
        countered = validate_success(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(
                    RENEG_COUNTER, action_note="lap %d counter" % lap
                ),
                ADMIN_NEGOTIATOR,
            )
        )
        assert countered["status"] == RENEG_COUNTERED
        assert countered["revision_count"] == lap - 1
        assert_money(
            countered["countered_annual_subsidy_usd"],
            1671285.76,
            "countered_annual_subsidy_usd",
        )

        revised = validate_success(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(
                    RENEG_REVISE,
                    revised_annual_subsidy_usd=revised_amount,
                    action_note="lap %d revision" % lap,
                ),
                award.carrier_headers,
            )
        )
        assert revised["status"] == RENEG_REQUESTED
        assert revised["revision_count"] == lap
        assert_money(
            revised["requested_annual_subsidy_usd"],
            revised_amount,
            "requested_annual_subsidy_usd",
        )
        assert_money(
            revised["ceiling_annual_subsidy_usd"],
            1671285.76,
            "ceiling_annual_subsidy_usd",
        )

    # The rate in force is untouched while the loop runs.
    assert_money(award.reload()["annual_subsidy_usd"], 1600000.00, "annual_subsidy_usd")


def test_fourth_revision_is_refused_and_parks_the_row_in_countered(api):
    """The loop counter caps the negotiation at three revisions.

    "Only three revisions are permitted: a revision attempted when `revision_count` already stands at 3, or one that omits `revised_annual_subsidy_usd`, is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/renegotiation_counter_revise_cycle_bounded_at_three_laps
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.publish_fuel_index(api, "2027-02", 3.1000)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    renegotiation = fx.file_fuel_renegotiation(api, award, "2027-02", 1750000.00)

    for revised_amount in [1740000.00, 1730000.00, 1700000.00]:
        get_success_data(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(RENEG_COUNTER),
                ADMIN_NEGOTIATOR,
            )
        )
        get_success_data(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(
                    RENEG_REVISE, revised_annual_subsidy_usd=revised_amount
                ),
                award.carrier_headers,
            )
        )

    fourth_counter = validate_success(
        api.renegotiation_action(
            renegotiation["id"],
            f.renegotiation_action_payload(RENEG_COUNTER, action_note="lap 4 counter"),
            ADMIN_NEGOTIATOR,
        )
    )
    assert fourth_counter["status"] == RENEG_COUNTERED
    assert fourth_counter["revision_count"] == REVISION_LIMIT

    response = api.renegotiation_action(
        renegotiation["id"],
        f.renegotiation_action_payload(
            RENEG_REVISE,
            revised_annual_subsidy_usd=1690000.00,
            action_note="lap 4 revision is refused",
        ),
        award.carrier_headers,
    )
    validate_error(response, E.ERR_REVISION_LIMIT_EXCEEDED, 422)

    parked = validate_success(api.get_rate_renegotiation(renegotiation["id"], ADMIN))
    assert parked["status"] == RENEG_COUNTERED
    assert parked["revision_count"] == REVISION_LIMIT
    assert_money(
        parked["requested_annual_subsidy_usd"], 1700000.00, "requested_annual_subsidy_usd"
    )


def test_acceptance_after_the_bounded_cycle_reprices_the_agreement(api):
    """Settling the parked negotiation at the ceiling repriices the unserved term.

    "That delta is pro-rated over the remaining months — multiplied by the remaining months and divided by 12, rounded half-up to cents *before* it is applied — then added to `total_committed_usd`, which is rounded again to cents."

    Design: Difficulty/non_linear_state_machine/renegotiation_counter_revise_cycle_bounded_at_three_laps
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    assert_money(award.agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    fx.publish_fuel_index(api, "2027-02", 3.1000)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    renegotiation = fx.file_fuel_renegotiation(api, award, "2027-02", 1750000.00)

    for revised_amount in [1740000.00, 1730000.00, 1700000.00]:
        get_success_data(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(RENEG_COUNTER),
                ADMIN_NEGOTIATOR,
            )
        )
        get_success_data(
            api.renegotiation_action(
                renegotiation["id"],
                f.renegotiation_action_payload(
                    RENEG_REVISE, revised_annual_subsidy_usd=revised_amount
                ),
                award.carrier_headers,
            )
        )
    get_success_data(
        api.renegotiation_action(
            renegotiation["id"],
            f.renegotiation_action_payload(RENEG_COUNTER),
            ADMIN_NEGOTIATOR,
        )
    )

    accepted = validate_success(
        api.renegotiation_action(
            renegotiation["id"],
            f.renegotiation_action_payload(
                RENEG_ACCEPT, action_note="settle at the ceiling"
            ),
            ADMIN_NEGOTIATOR,
        )
    )
    assert accepted["status"] == RENEG_ACCEPTED
    assert accepted["revision_count"] == REVISION_LIMIT
    assert_money(
        accepted["approved_annual_subsidy_usd"],
        1671285.76,
        "approved_annual_subsidy_usd",
    )
    assert_instant(accepted["effective_at"], "2027-02-01T00:00:00Z", "effective_at")

    agreement = award.reload()
    assert_money(agreement["annual_subsidy_usd"], 1671285.76, "annual_subsidy_usd")
    assert_instant(
        agreement["rate_effective_from"], "2027-02-01T00:00:00Z", "rate_effective_from"
    )
    assert_instant(
        agreement["rate_effective_to"], "2028-08-01T00:00:00Z", "rate_effective_to"
    )
    assert_money(agreement["total_committed_usd"], 3342571.52, "total_committed_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3342571.52, "obligated_remaining_usd"
    )
    assert_obligation_identity(agreement)
