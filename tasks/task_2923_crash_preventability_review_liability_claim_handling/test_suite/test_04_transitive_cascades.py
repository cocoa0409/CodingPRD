"""Cascades that reach several links past the request that started them."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_instants_equal,
    assert_points_1dp,
    assert_rate,
    assert_score_2dp,
)
from test_helpers.constants import (
    ACTION_TIER_NONE,
    ACTION_TIER_SUSPENSION,
    ANALYTICS_BASIS_AS_DETERMINED,
    ANALYTICS_BASIS_AS_REPORTED,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_SETTLEMENT_COMPLETE,
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    DECISION_BASIS_UNWEIGHTED_MAJORITY,
    DEMAND_STATE_SETTLED,
    DETERMINATION_PREVENTABLE,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    OPERATOR_IDS,
    PREVENTABILITY_PREVENTABLE,
    RESERVE_BASIS_DEMAND_BASED,
    REVIEW_STATE_DECIDED,
    RISK_TIER_CRITICAL,
    RISK_TIER_STANDARD,
    ROUND_OUTCOME_ACCEPTED,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_OK,
    SUBROGATION_STATE_DRAFT,
    SUBROGATION_STATE_READY_TO_PURSUE,
    TENURE_OVER_36_MONTHS,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_demand,
    build_driver,
    build_policy_layer,
    build_preserved_evidence,
    build_review_case,
    build_subrogation_demand,
    build_terminal,
    cast_quorum,
    make_offer,
    open_deliberation,
    revise_reserve,
    settle,
)

CASCADE_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T13:00:00Z",
    "window_end_at": "2026-07-30T15:00:00Z",
    "retention_deadline_at": "2026-09-30T00:00:00Z",
}

EXPECTED_CASCADE_SCORE = 4.00
EXPECTED_CASCADE_RATE = 4.000
EXPECTED_CASCADE_POINTS = 8.0

SETTLED_INDEMNITY_CENTS = 13_392_857
SETTLED_ALAE_CENTS = 1_607_143
SETTLED_TOTAL_CENTS = 15_000_000
DEMAND_AMOUNT_CENTS = 20_000_000
SIR_LIMIT_CENTS = 10_000_000
PRIMARY_LIMIT_CENTS = 10_000_000
AT_FAULT_PERCENTAGE = 40
EXPECTED_RECOVERABLE_BASE_CENTS = 15_000_000
EXPECTED_MAX_RECOVERABLE_CENTS = 6_000_000


def _case_ready_on_a_low_mileage_terminal(api: ApiClient) -> dict:
    """A single severe preventable-bound crash at a 0.25-million-mile terminal."""
    terminal = build_terminal(
        api,
        name="Gallipolis Terminal",
        terminal_code="GAL01",
        region_code="OH",
        annual_miles_millions=0.25,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-7001",
        full_name="Vince Okoro",
        cdl_number="OH-CDL-7001",
        hire_date="2013-05-06",
    )
    before = validate_success(api.get_terminal(terminal["id"], SAFETY_ADMIN))
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:05:00Z",
        location_text="US-35 at Chickamauga Creek",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ELD-70110"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-F-70110"),
        (EVIDENCE_ELD_LOG, "ELD-70110"),
    ):
        build_preserved_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **CASCADE_EVIDENCE_WINDOW
        )

    case = build_review_case(
        api,
        crash["id"],
        committee_name="Gallipolis Preventability Committee",
        statement_waiver_reason="statement waived, driver still off duty",
    )
    opened = open_deliberation(api, case["id"])
    balloted = cast_quorum(
        api,
        opened,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(4),
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": balloted,
        "terminal_before": before,
    }


class TestDeterminationCascadeReachesTheTerminalRiskTier:
    """One decision travels case to crash to terminal count to terminal tier."""

    def test_the_decision_drags_the_terminal_all_the_way_to_a_critical_tier(
        self, api: ApiClient
    ):
        """Four links fire off one request, each caused by the one before it.

        PRD: "Either branch drives the determination cascade. The crash moves
        `UNDER_REVIEW → PREVENTABLE` or `UNDER_REVIEW → NON_PREVENTABLE`
        according to the determination, and its `version` increases by 1.
        Because the crash's preventability changed, the driver's decayed point
        total and required action tier are re-derived ... and the terminal's
        preventable crash count, crash rate and risk tier follow on their next
        read."

        Design: Difficulty/transitive_cascade/decide_preventable_cascade_depth4_terminal_risk_tier
        """
        context = _case_ready_on_a_low_mileage_terminal(api)
        before = context["terminal_before"]
        assert before["preventable_crash_count"] == 0
        assert_rate(before["crash_rate_per_million_miles"], 0.000)
        assert before["risk_tier"] == RISK_TIER_STANDARD

        # The crash was already bumped once when the case opened deliberation,
        # so the "+1" the PRD promises is measured against the version standing
        # immediately before the determination, not against the intake snapshot.
        crash_before = validate_success(
            api.get_crash(context["crash"]["id"], SAFETY_MANAGER)
        )

        decided = validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        assert decided["status"] == REVIEW_STATE_DECIDED
        assert decided["determination"] == DETERMINATION_PREVENTABLE
        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert_score_2dp(decided["committee_score"], EXPECTED_CASCADE_SCORE, "committee_score")
        assert decided["decided_by_user_id"] == OPERATOR_IDS["safety_manager_decider"]
        assert_instants_equal(decided["decided_at"], CLOCK_EPOCH, "decided_at")

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["preventability_status"] == PREVENTABILITY_PREVENTABLE
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE
        assert crash["version"] == crash_before["version"] + 1

        after = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert after["preventable_crash_count"] == 1
        assert_rate(
            after["crash_rate_per_million_miles"],
            EXPECTED_CASCADE_RATE,
            "crash_rate_per_million_miles",
        )
        assert after["risk_tier"] == RISK_TIER_CRITICAL

    def test_the_driver_point_branch_hangs_off_the_preventability_link(
        self, api: ApiClient
    ):
        """The severity base survives undecayed and lifts the action tier.

        PRD: "Each contributing crash yields a base figure from its `severity` —
        2 points for a `MINOR` crash, 4 for a `MODERATE` one, 8 for a `SEVERE`
        one and 12 for a `CATASTROPHIC` one — multiplied by a decay factor
        selected from the crash's age. ... A crash fewer than 365 days old keeps
        its full value at a factor of 1.0."

        Design: Difficulty/transitive_cascade/decide_preventable_cascade_depth4_terminal_risk_tier
        """
        context = _case_ready_on_a_low_mileage_terminal(api)
        driver_id = context["driver"]["id"]
        before = validate_success(api.get_driver(driver_id, SAFETY_ADMIN))
        assert_points_1dp(before["preventable_points"], 0.0, "preventable_points")
        assert before["required_action_tier"] == ACTION_TIER_NONE
        assert before["tenure_band"] == TENURE_OVER_36_MONTHS

        validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        after = validate_success(api.get_driver(driver_id, SAFETY_ADMIN))
        assert_points_1dp(
            after["preventable_points"], EXPECTED_CASCADE_POINTS, "preventable_points"
        )
        assert after["required_action_tier"] == ACTION_TIER_SUSPENSION

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["suspended_driver_count"] == 0
        assert terminal["active_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

    def test_both_analytics_bases_agree_while_the_lone_crash_is_preventable(
        self, api: ApiClient
    ):
        """A single decided crash counts identically under either basis.

        PRD: "Under `AS_DETERMINED` only crashes whose `preventability_status` is
        `PREVENTABLE` are counted, so a crash awaiting determination or found
        non-preventable contributes nothing. Under `AS_REPORTED` every notified
        crash in the window is counted regardless of determination."

        Design: Difficulty/transitive_cascade/decide_preventable_cascade_depth4_terminal_risk_tier
        """
        context = _case_ready_on_a_low_mileage_terminal(api)
        terminal_id = context["terminal"]["id"]
        validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        for basis in (ANALYTICS_BASIS_AS_REPORTED, ANALYTICS_BASIS_AS_DETERMINED):
            analytics = validate_success(
                api.get_crash_analytics(terminal_id, SAFETY_ADMIN, {"basis": basis})
            )
            assert analytics["basis"] == basis
            assert analytics["terminal_id"] == terminal_id
            assert analytics["crash_count"] == 1
            assert analytics["preventable_crash_count"] == 1
            assert_rate(
                analytics["crash_rate_per_million_miles"],
                EXPECTED_CASCADE_RATE,
                f"{basis} crash_rate_per_million_miles",
            )
            assert analytics["risk_tier"] == RISK_TIER_CRITICAL

        route_rows = {
            row["route_class"]: row
            for row in validate_success(
                api.get_crash_analytics(terminal_id, SAFETY_ADMIN)
            )["by_route_class"]
        }
        assert route_rows[ROUTE_CLASS_LINEHAUL]["crash_count"] == 1
        assert route_rows[ROUTE_CLASS_LINEHAUL]["preventable_crash_count"] == 1


def _claim_with_a_waiting_subrogation_demand(api: ApiClient) -> dict:
    """A fully reserved claim with a standing offer and a DRAFT recovery file."""
    terminal = build_terminal(
        api,
        name="Hillsboro Terminal",
        terminal_code="HIL01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-8001",
        full_name="Wanda Pike",
        cdl_number="OH-CDL-8001",
        hire_date="2012-08-19",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T11:00:00Z",
        notified_at="2026-07-30T11:30:00Z",
        location_text="US-50 at Careytown Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        third_party_at_fault=True,
    )
    sir_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=SIR_LIMIT_CENTS,
        insurer_name="Self-Insured Retention",
    )
    primary_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=2,
        layer_type=LAYER_KIND_PRIMARY,
        attachment_point_cents=SIR_LIMIT_CENTS,
        limit_cents=PRIMARY_LIMIT_CENTS,
        insurer_name="Continental Freight Casualty",
    )
    claim = build_claim(
        api,
        crash["id"],
        claimant_notice_date="2026-07-31",
        adjuster_note="third-party vehicle destroyed; other driver ran the stop sign",
    )
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Careytown Produce LLC",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=DEMAND_AMOUNT_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T14:00:00Z",
    )
    subrogation = build_subrogation_demand(
        api,
        claim["id"],
        third_party_name="Ora Lindquist",
        at_fault_percentage=AT_FAULT_PERCENTAGE,
        basis_note="police report assigns 40 percent of fault to the third party",
    )
    observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
    reserved = revise_reserve(
        api,
        claim["id"],
        observed["version"],
        basis=RESERVE_BASIS_DEMAND_BASED,
        revision_note="reserving to the written demand before requesting settlement authority",
    )
    round_row = make_offer(api, demand["id"], SETTLED_INDEMNITY_CENTS)
    return {
        "claim": reserved,
        "demand": demand,
        "subrogation": subrogation,
        "round": round_row,
        "sir_layer": sir_layer,
        "primary_layer": primary_layer,
    }


class TestSettlementCascadeReachesTheSubrogationCeiling:
    """One settlement travels demand to claim buckets to recovery ceiling."""

    def test_the_settlement_freezes_the_indemnity_expense_and_accepted_round(
        self, api: ApiClient
    ):
        """The first link keys the expense off the offer, not the demand.

        PRD: "The indemnity, `settled_amount_cents`, is exactly the standing
        round's `carrier_offer_cents` — never the demand amount and never the
        claimant's last counter. ... an indemnity of 5,000,000 cents or more but
        under 25,000,000 takes 0.12"

        Design: Difficulty/transitive_cascade/settle_demand_cascade_depth3_subrogation_ready
        """
        context = _claim_with_a_waiting_subrogation_demand(api)
        assert context["subrogation"]["status"] == SUBROGATION_STATE_DRAFT
        assert context["subrogation"]["recoverable_base_cents"] is None
        assert_cents(
            context["claim"]["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS,
            "outstanding_reserve_cents",
        )

        settled = settle(api, context["demand"]["id"], settlement_reference="SET-2026-HIL-0001")

        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(
            settled["settled_amount_cents"], SETTLED_INDEMNITY_CENTS, "settled_amount_cents"
        )
        assert_cents(settled["alae_cents"], SETTLED_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"], SETTLED_TOTAL_CENTS, "settlement_total_cents"
        )
        assert settled["settlement_reference"] == "SET-2026-HIL-0001"
        assert_instants_equal(settled["settled_at"], CLOCK_EPOCH, "settled_at")

        rounds, _ = validate_paginated(
            api.list_negotiation_rounds(context["demand"]["id"], CLAIMS_MANAGER)
        )
        accepted = [row for row in rounds if row["id"] == context["round"]["id"]]
        assert len(accepted) == 1
        assert accepted[0]["outcome"] == ROUND_OUTCOME_ACCEPTED

    def test_the_claim_absorbs_the_settlement_and_walks_the_two_layer_tower(
        self, api: ApiClient
    ):
        """The second link is the claim ledger and the ascending waterfall.

        PRD: "The claim moves the indemnity into `indemnity_paid_cents` and the
        expense into `alae_paid_cents`, reduces `outstanding_reserve_cents` by
        exactly `settlement_total_cents` ... increases `sir_eroded_cents` by the
        allocations to the `SIR` layer and `insured_paid_cents` by the
        allocations to `PRIMARY` and `EXCESS` layers"

        Design: Difficulty/transitive_cascade/settle_demand_cascade_depth3_subrogation_ready
        """
        context = _claim_with_a_waiting_subrogation_demand(api)
        settle(api, context["demand"]["id"], settlement_reference="SET-2026-HIL-0001")

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert claim["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert_cents(
            claim["indemnity_paid_cents"], SETTLED_INDEMNITY_CENTS, "indemnity_paid_cents"
        )
        assert_cents(claim["alae_paid_cents"], SETTLED_ALAE_CENTS, "alae_paid_cents")
        assert_cents(
            claim["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS - SETTLED_TOTAL_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            claim["claim_exposure_cents"], DEMAND_AMOUNT_CENTS, "claim_exposure_cents"
        )

        allocations = claim["layer_allocations"]
        assert len(allocations) == 2
        assert allocations[0]["policy_layer_id"] == context["sir_layer"]["id"]
        assert allocations[0]["layer_index"] == 1
        assert allocations[0]["layer_type"] == LAYER_KIND_SIR
        assert_cents(allocations[0]["allocated_cents"], SIR_LIMIT_CENTS, "sir allocated_cents")
        assert allocations[1]["policy_layer_id"] == context["primary_layer"]["id"]
        assert allocations[1]["layer_index"] == 2
        assert allocations[1]["layer_type"] == LAYER_KIND_PRIMARY
        assert_cents(
            allocations[1]["allocated_cents"],
            SETTLED_TOTAL_CENTS - SIR_LIMIT_CENTS,
            "primary allocated_cents",
        )
        assert_cents(claim["sir_eroded_cents"], SIR_LIMIT_CENTS, "sir_eroded_cents")
        assert_cents(
            claim["insured_paid_cents"],
            SETTLED_TOTAL_CENTS - SIR_LIMIT_CENTS,
            "insured_paid_cents",
        )

    def test_the_draft_recovery_file_is_promoted_from_the_buckets_just_written(
        self, api: ApiClient
    ):
        """The third link reads the paid buckets the second link had just set.

        PRD: "`recoverable_base_cents` is the claim's `indemnity_paid_cents` plus
        `alae_paid_cents` at the instant of promotion, and `max_recoverable_cents`
        is that base multiplied by `at_fault_percentage` and divided by 100,
        rounded half up to a whole cent."

        Design: Difficulty/transitive_cascade/settle_demand_cascade_depth3_subrogation_ready
        """
        context = _claim_with_a_waiting_subrogation_demand(api)
        settle(api, context["demand"]["id"], settlement_reference="SET-2026-HIL-0001")

        promoted = validate_success(
            api.get_subrogation_demand(context["subrogation"]["id"], CLAIMS_MANAGER)
        )
        assert promoted["status"] == SUBROGATION_STATE_READY_TO_PURSUE
        assert_cents(
            promoted["recoverable_base_cents"],
            EXPECTED_RECOVERABLE_BASE_CENTS,
            "recoverable_base_cents",
        )
        assert_cents(
            promoted["max_recoverable_cents"],
            EXPECTED_MAX_RECOVERABLE_CENTS,
            "max_recoverable_cents",
        )
        assert promoted["recovered_amount_cents"] is None
        assert promoted["resolved_at"] is None
        assert promoted["version"] == context["subrogation"]["version"] + 1

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert_cents(
            claim["total_incurred_cents"], DEMAND_AMOUNT_CENTS, "total_incurred_cents"
        )
        assert_cents(claim["subrogation_recovered_cents"], 0, "subrogation_recovered_cents")
