"""A review case that cycles backwards, and a claim that advances on two axes."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_score_2dp
from test_helpers.constants import (
    APPEAL_CODE_CRITERIA_MISAPPLICATION,
    APPEAL_CODE_PROCEDURAL,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_CLOSED,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETTLEMENT_COMPLETE,
    CLAIM_HANDLING_SETUP,
    CLAIMANT_TYPE_PROPERTY,
    DECISION_BASIS_NOT_APPLICABLE,
    DEMAND_STATE_CLOSED_PAID,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_SIR,
    PREVENTABILITY_UNDER_REVIEW,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    RESERVE_STATUS_FINAL,
    RESERVE_STATUS_PROVISIONAL,
    RESERVE_STATUS_REVISED,
    REVIEW_STATE_CLOSED_FINAL,
    REVIEW_STATE_DECIDED,
    REVIEW_STATE_DELIBERATION,
    ROUND_OUTCOME_ACCEPTED,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    APPEALS_MANAGER,
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    COMMITTEE_ONE,
    COMMITTEE_THREE,
    COMMITTEE_TWO,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_demand,
    build_driver,
    build_policy_layer,
    build_preserved_evidence,
    build_review_case,
    build_terminal,
    make_offer,
    open_deliberation,
    revise_reserve,
    settle,
)

SEVERE_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T13:00:00Z",
    "window_end_at": "2026-07-30T15:00:00Z",
    "retention_deadline_at": "2026-09-30T00:00:00Z",
}

APPEAL_CYCLE_BALLOTS = (
    (COMMITTEE_ONE, BALLOT_DISPOSITION_PREVENTABLE, 4),
    (COMMITTEE_TWO, BALLOT_DISPOSITION_PREVENTABLE, 3),
    (COMMITTEE_THREE, BALLOT_DISPOSITION_NON_PREVENTABLE, 1),
)

EXPECTED_APPEAL_CYCLE_SCORE = 2.67


def _decided_case(api: ApiClient) -> dict:
    """A severe crash decided preventable on three live ballots."""
    terminal = build_terminal(
        api,
        name="Elkhart Terminal",
        terminal_code="ELK01",
        region_code="IN",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5001",
        full_name="Sal Ibarra",
        cdl_number="IN-CDL-5001",
        hire_date="2015-04-13",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:10:00Z",
        location_text="I-80/90 MM 92 eastbound",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ELD-50110"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-F-50110"),
        (EVIDENCE_ELD_LOG, "ELD-50110"),
    ):
        build_preserved_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **SEVERE_EVIDENCE_WINDOW
        )

    case = build_review_case(
        api,
        crash["id"],
        committee_name="Elkhart Preventability Committee",
        statement_waiver_reason="driver declined to give a statement on counsel's advice",
    )
    current = open_deliberation(api, case["id"])
    for headers, vote, score in APPEAL_CYCLE_BALLOTS:
        current = validate_success(
            api.cast_vote(
                case["id"],
                factories.vote_payload(
                    current["version"],
                    vote=vote,
                    scores=factories.uniform_criterion_scores(score),
                ),
                headers,
            ),
            201,
        )
    decided = validate_success(api.decide_review_case(case["id"], headers=SAFETY_MANAGER))
    return {"crash": crash, "driver": driver, "review_case": decided}


class TestReviewCaseAppealCycle:
    """The case walks forwards, backwards, and then out through the other branch."""

    def test_an_appeal_returns_a_decided_case_to_deliberation(self, api: ApiClient):
        """The vacated determination is unwound and the ballots survive.

        PRD: "An accepted appeal moves the case `DECIDED → DELIBERATION`,
        increases `appeal_round` by 1, records `appeal_grounds`,
        `appeal_grounds_code` and — where cited — `appeal_evidence_item_id`, and
        resets the decision fields: `determination` back to `PENDING`,
        `decision_basis` back to `NOT_APPLICABLE`, `committee_score` back to
        null, and both `decided_by_user_id` and `decided_at` back to null."

        Design: Difficulty/non_linear_state_machine/review_case_appeal_cycle_returns_to_deliberation
        """
        context = _decided_case(api)
        case_id = context["review_case"]["id"]
        assert context["review_case"]["status"] == REVIEW_STATE_DECIDED
        assert_score_2dp(
            context["review_case"]["committee_score"],
            EXPECTED_APPEAL_CYCLE_SCORE,
            "committee_score",
        )

        appealed = validate_success(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds=(
                        "the committee applied the hazard-recognition criterion "
                        "to a hazard that was not visible"
                    ),
                    appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
                ),
                APPEALS_MANAGER,
            )
        )

        assert appealed["status"] == REVIEW_STATE_DELIBERATION
        assert appealed["appeal_round"] == 1
        assert appealed["determination"] == DETERMINATION_PENDING
        assert appealed["decision_basis"] == DECISION_BASIS_NOT_APPLICABLE
        assert appealed["committee_score"] is None
        assert appealed["decided_at"] is None
        assert appealed["decided_by_user_id"] is None

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["preventability_status"] == PREVENTABILITY_UNDER_REVIEW
        assert crash["appeals_exhausted"] is False

        rows, meta = validate_paginated(api.list_votes(case_id, SAFETY_MANAGER))
        assert meta["total_count"] == 3
        assert all(row["superseded"] is False for row in rows)

    def test_the_same_trigger_closes_the_case_once_the_appeal_is_spent(
        self, api: ApiClient
    ):
        """The second determination takes the other branch on the same trigger.

        PRD: "When `appeal_round` has already reached the permitted maximum of 1,
        the case moves `DELIBERATION → CLOSED_FINAL` instead, recording exactly
        the same five fields with exactly the same values, moving the crash
        exactly as the other branch does, incrementing `version` by 1 — and
        additionally setting the crash's `appeals_exhausted` to true"

        Design: Difficulty/non_linear_state_machine/review_case_appeal_cycle_returns_to_deliberation
        """
        context = _decided_case(api)
        case_id = context["review_case"]["id"]

        validate_success(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="the hazard-recognition criterion was misapplied",
                    appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
                ),
                APPEALS_MANAGER,
            )
        )
        final = validate_success(api.decide_review_case(case_id, headers=SAFETY_MANAGER))

        assert final["status"] == REVIEW_STATE_CLOSED_FINAL
        assert final["status"] != REVIEW_STATE_DECIDED
        assert final["determination"] == DETERMINATION_PREVENTABLE
        assert_score_2dp(
            final["committee_score"], EXPECTED_APPEAL_CYCLE_SCORE, "committee_score"
        )

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["appeals_exhausted"] is True

    def test_a_second_appeal_is_refused_once_the_case_is_closed(self, api: ApiClient):
        """One appeal per case, and the closed state is what ends the cycle.

        The second determination lands the case in `CLOSED_FINAL`, so the state
        guard speaks before the exhaustion guard is ever consulted.

        PRD: "The case must be in `DECIDED`; appealing a case in `DRAFT`, in
        `DELIBERATION` or in `CLOSED_FINAL` is `ERR_REVIEW_CASE_STATE_INVALID`."
        Its guards "run in the ladder's order", and the ladder places "**State
        legality.** The addressed entity is in a state from which the requested
        transition is declared" above "**Appeal exhaustion.** An appeal is
        refused once the crash's appeals are exhausted or the case has already
        used its permitted appeal round — `ERR_APPEALS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/review_case_appeal_cycle_returns_to_deliberation
        """
        context = _decided_case(api)
        case_id = context["review_case"]["id"]

        validate_success(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="the hazard-recognition criterion was misapplied",
                    appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
                ),
                APPEALS_MANAGER,
            )
        )
        validate_success(api.decide_review_case(case_id, headers=SAFETY_MANAGER))

        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="second bite at the apple",
                    appeal_grounds_code=APPEAL_CODE_PROCEDURAL,
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.REVIEW_CASE_STATE_INVALID.value,
            409,
        )

        unchanged = validate_success(api.get_review_case(case_id, SAFETY_MANAGER))
        assert unchanged["status"] == REVIEW_STATE_CLOSED_FINAL
        assert unchanged["appeal_round"] == 1


def _claim_at_setup(api: ApiClient) -> dict:
    """A moderate crash with a single-layer tower and a freshly opened claim."""
    terminal = build_terminal(
        api,
        name="Findlay Terminal",
        terminal_code="FIN01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6001",
        full_name="Tomas Reddick",
        cdl_number="OH-CDL-6001",
        hire_date="2014-11-30",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T06:00:00Z",
        notified_at="2026-07-30T06:20:00Z",
        location_text="SR-15 at Township Rd 99",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    retention = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=10_000_000,
        insurer_name="Self-Insured Retention",
    )
    claim = build_claim(
        api,
        crash["id"],
        claimant_notice_date="2026-07-31",
        adjuster_note="guardrail and signage damage",
    )
    return {"crash": crash, "retention": retention, "claim": claim}


def _demand_settled_on_that_claim(api: ApiClient, context: dict) -> dict:
    """Record a demand, put the whole amount on the table and settle it."""
    demand = build_demand(
        api,
        context["claim"]["id"],
        claimant_name="Hancock County Engineer",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=1_000_000,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T09:00:00Z",
    )
    round_row = make_offer(api, demand["id"], 1_000_000)
    settled = settle(api, demand["id"], settlement_reference="SET-2026-FIN-0001")
    return {"demand": demand, "round": round_row, "settled": settled}


class TestClaimParallelDimensions:
    """Handling status and reserve status advance independently on one row."""

    def test_the_reserve_dimension_advances_while_handling_stays_at_setup(
        self, api: ApiClient
    ):
        """A revision moves the reserve axis and leaves the handling axis alone.

        PRD: "An accepted revision writes the selected variant's output to
        `revised_reserve_cents`, moves `reserve_status` `PROVISIONAL → REVISED` on
        the first revision and holds it at `REVISED` on every subsequent one"

        Design: Difficulty/non_linear_state_machine/claim_parallel_handling_and_reserve_dimensions
        """
        context = _claim_at_setup(api)
        claim = context["claim"]
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL

        revised = revise_reserve(
            api,
            claim["id"],
            claim["version"],
            basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
            revision_note="supervisor review at file opening",
        )

        assert revised["handling_status"] == CLAIM_HANDLING_SETUP
        assert revised["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(revised["outstanding_reserve_cents"], 2_500_000, "outstanding_reserve_cents")

    def test_the_handling_dimension_advances_while_the_reserve_axis_holds(
        self, api: ApiClient
    ):
        """A demand and then a settlement move only the handling axis.

        PRD: "The parent claim reacts on both branches: the first demand moves
        the claim `SETUP → NEGOTIATION`, while each additional demand accumulates
        without leaving `NEGOTIATION`, and in both cases the claim's `version`
        increases by 1 and its reserve dimension is untouched."

        Design: Difficulty/non_linear_state_machine/claim_parallel_handling_and_reserve_dimensions
        """
        context = _claim_at_setup(api)
        claim = context["claim"]
        revise_reserve(
            api, claim["id"], claim["version"], basis=RESERVE_BASIS_PROVISIONAL_REFRESH
        )

        negotiated = _demand_settled_on_that_claim(api, context)

        assert_cents(negotiated["settled"]["alae_cents"], 80_000, "alae_cents")
        assert_cents(
            negotiated["settled"]["settlement_total_cents"], 1_080_000, "settlement_total_cents"
        )

        after_settlement = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert after_settlement["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert after_settlement["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(
            after_settlement["outstanding_reserve_cents"],
            1_420_000,
            "outstanding_reserve_cents",
        )

    def test_a_demand_alone_moves_handling_without_touching_the_reserve(
        self, api: ApiClient
    ):
        """Recording the first demand is a handling-axis move only.

        PRD: "the first demand moves the claim `SETUP → NEGOTIATION`"

        Design: Difficulty/non_linear_state_machine/claim_parallel_handling_and_reserve_dimensions
        """
        context = _claim_at_setup(api)
        claim = context["claim"]
        revise_reserve(
            api, claim["id"], claim["version"], basis=RESERVE_BASIS_PROVISIONAL_REFRESH
        )

        build_demand(
            api,
            claim["id"],
            claimant_name="Hancock County Engineer",
            claimant_type=CLAIMANT_TYPE_PROPERTY,
            demand_amount_cents=1_000_000,
            represented_by_counsel=False,
            demand_received_at="2026-07-31T09:00:00Z",
        )

        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert observed["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert observed["reserve_status"] == RESERVE_STATUS_REVISED

    def test_closure_is_the_only_request_that_moves_both_dimensions(self, api: ApiClient):
        """Closing the file advances handling and reserve in one request.

        PRD: "Both set `closed_at` from the clock and both drive the reserve
        dimension to `FINAL` — from `REVISED` when the reserve was re-estimated
        at least once, or straight from `PROVISIONAL` when it never was. The
        whole residual `outstanding_reserve_cents` is moved into
        `reserve_released_cents`, so `outstanding_reserve_cents` becomes 0 while
        `claim_exposure_cents` is unchanged"

        Design: Difficulty/non_linear_state_machine/claim_parallel_handling_and_reserve_dimensions
        """
        context = _claim_at_setup(api)
        claim = context["claim"]
        revise_reserve(
            api, claim["id"], claim["version"], basis=RESERVE_BASIS_PROVISIONAL_REFRESH
        )
        negotiated = _demand_settled_on_that_claim(api, context)

        closed = validate_success(api.close_claim(claim["id"], headers=CLAIMS_MANAGER))

        assert closed["handling_status"] == CLAIM_HANDLING_CLOSED
        assert closed["reserve_status"] == RESERVE_STATUS_FINAL
        assert_cents(closed["outstanding_reserve_cents"], 0, "outstanding_reserve_cents")
        assert_cents(closed["reserve_released_cents"], 1_420_000, "reserve_released_cents")
        assert_cents(closed["claim_exposure_cents"], 2_500_000, "claim_exposure_cents")
        assert_cents(closed["sir_eroded_cents"], 1_080_000, "sir_eroded_cents")
        assert len(closed["layer_allocations"]) == 1
        assert closed["layer_allocations"][0]["policy_layer_id"] == context["retention"]["id"]
        assert_cents(
            closed["layer_allocations"][0]["allocated_cents"], 1_080_000, "allocated_cents"
        )

        demand = validate_success(
            api.get_demand(negotiated["demand"]["id"], CLAIMS_ADJUSTER)
        )
        assert demand["status"] == DEMAND_STATE_CLOSED_PAID

        rounds, _ = validate_paginated(
            api.list_negotiation_rounds(negotiated["demand"]["id"], CLAIMS_ADJUSTER)
        )
        assert rounds[0]["outcome"] == ROUND_OUTCOME_ACCEPTED
