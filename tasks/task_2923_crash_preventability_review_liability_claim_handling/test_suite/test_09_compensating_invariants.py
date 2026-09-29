"""Two compensations, each measured against a conserved quantity it must restore.

One conserves a cents-denominated ledger; the other conserves a bundle of
safety scores and headcounts whose correct restore point is a non-zero baseline.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_points_1dp,
    assert_rate,
    assert_score_2dp,
)
from test_helpers.constants import (
    ACTION_STATE_ISSUED,
    ACTION_STATE_VOIDED,
    ACTION_TIER_COACHING,
    ACTION_TIER_SUSPENSION,
    ACTION_TYPE_SUSPENSION,
    ANALYTICS_BASIS_AS_REPORTED,
    APPEAL_CODE_CRITERIA_MISAPPLICATION,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETTLEMENT_COMPLETE,
    CLAIMANT_TYPE_PROPERTY,
    DECISION_BASIS_NOT_APPLICABLE,
    DEMAND_STATE_OFFER_OUTSTANDING,
    DEMAND_STATE_SETTLED,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_ACTIVE,
    DRIVER_STATUS_SUSPENDED_PENDING_ACTION,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    PREVENTABILITY_PREVENTABLE,
    PREVENTABILITY_REPORTED,
    PREVENTABILITY_UNDER_REVIEW,
    RESERVE_BASIS_DEMAND_BASED,
    RESERVE_STATUS_REVISED,
    RETRAINING_STATUS_NOT_REQUIRED,
    RETRAINING_STATUS_PENDING,
    REVIEW_STATE_DECIDED,
    REVIEW_STATE_DELIBERATION,
    RISK_TIER_CRITICAL,
    RISK_TIER_ELEVATED,
    ROUND_OUTCOME_ACCEPTED,
    ROUND_OUTCOME_OPEN,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_CRITICAL,
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
    build_discipline,
    build_driver,
    build_policy_layer,
    build_preserved_evidence,
    build_review_case,
    build_statement,
    build_subrogation_demand,
    build_terminal,
    cast_quorum,
    decide_case,
    grant_appeal,
    make_offer,
    open_deliberation,
    rescind,
    revise_reserve,
    settle,
)

# The tower is 15,000,000 of capacity in two layers.
QCY_SIR_LIMIT_CENTS = 10_000_000
QCY_PRIMARY_LIMIT_CENTS = 5_000_000

QCY_DEMAND_CENTS = 20_000_000
QCY_OFFER_CENTS = 12_000_000
QCY_ALAE_CENTS = 1_440_000
QCY_SETTLEMENT_TOTAL_CENTS = 13_440_000
QCY_OUTSTANDING_AFTER_SETTLEMENT_CENTS = 6_560_000
QCY_PRIMARY_ALLOCATION_CENTS = 3_440_000

QCY_AT_FAULT_PERCENTAGE = 35
QCY_RECOVERABLE_BASE_CENTS = 13_440_000
QCY_MAX_RECOVERABLE_CENTS = 4_704_000

# A REPORTED crash on a PARTIAL record scores 5 + 5 and multiplies at 1.00.
QCY_RISK_SCORE = 10
QCY_RISK_MULTIPLIER = 1.00

SETTLEMENT_REFERENCE = "SET-2026-QCY-0001"
RESCISSION_REASON = "release agreement was executed by an unauthorised representative"


def _claim_ready_to_settle_on_a_two_layer_tower(api: ApiClient) -> dict:
    """A demand-based reserve of 20,000,000 with a 12,000,000 offer on the table."""
    terminal = build_terminal(
        api,
        name="Quincy Terminal",
        terminal_code="QCY01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1801",
        full_name="Gareth Ollivant",
        cdl_number="OH-CDL-1801",
        hire_date="2011-09-19",
    )
    sir_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=QCY_SIR_LIMIT_CENTS,
        insurer_name="Self-Insured Retention",
    )
    primary_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=2,
        layer_type=LAYER_KIND_PRIMARY,
        attachment_point_cents=QCY_SIR_LIMIT_CENTS,
        limit_cents=QCY_PRIMARY_LIMIT_CENTS,
        insurer_name="Continental Freight Casualty",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-28T08:00:00Z",
        notified_at="2026-07-28T08:30:00Z",
        location_text="SR-3 at Bethel Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        third_party_at_fault=True,
    )
    claim = build_claim(
        api,
        crash["id"],
        claimant_notice_date="2026-07-29",
        adjuster_note="third-party property damage, other unit ran the stop sign",
    )
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Adams County Grain Co",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=QCY_DEMAND_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-30T12:00:00Z",
    )
    observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
    reserved = revise_reserve(
        api,
        claim["id"],
        observed["version"],
        basis=RESERVE_BASIS_DEMAND_BASED,
        revision_note="reserving to the demand before any payment",
    )
    round_row = make_offer(api, demand["id"], QCY_OFFER_CENTS)
    subrogation = build_subrogation_demand(
        api,
        claim["id"],
        third_party_name="Bracken Hauling LLC",
        at_fault_percentage=QCY_AT_FAULT_PERCENTAGE,
        basis_note="third party failed to yield at a posted stop",
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "claim": reserved,
        "demand": demand,
        "round": round_row,
        "subrogation": subrogation,
        "sir_layer": sir_layer,
        "primary_layer": primary_layer,
    }


class TestRescindingASettlementConservesTheClaimLedger:
    """claim_exposure_cents reads 20,000,000 before, during and after."""

    def test_the_exposure_total_holds_while_its_four_components_move_and_move_back(
        self, api: ApiClient
    ):
        """The conserved total is the sum of the four money buckets.

        PRD: "`claim_exposure_cents` is defined as the sum of
        `outstanding_reserve_cents`, `indemnity_paid_cents`, `alae_paid_cents`
        and `reserve_released_cents`, and it is deliberately unchanged by
        settlement, by rescission, by subrogation recovery and by claim closure.
        Settlement moves cents out of the outstanding reserve and into the paid
        buckets; rescission moves them back"

        Design: Difficulty/compensating_invariant/rescind_settlement_restores_claim_ledger_and_layer_capacity
        """
        context = _claim_ready_to_settle_on_a_two_layer_tower(api)
        claim_id = context["claim"]["id"]

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_ADMIN))
        assert crash["preventability_status"] == PREVENTABILITY_REPORTED
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        before = validate_success(api.get_claim(claim_id, CLAIMS_ADJUSTER))
        assert before["litigation_risk_score"] == QCY_RISK_SCORE
        assert float(before["litigation_risk_multiplier"]) == QCY_RISK_MULTIPLIER
        assert before["counsel_required"] is False
        assert_cents(before["claim_exposure_cents"], QCY_DEMAND_CENTS, "claim_exposure_cents")
        assert_cents(
            before["outstanding_reserve_cents"], QCY_DEMAND_CENTS, "outstanding_reserve_cents"
        )
        assert_cents(before["indemnity_paid_cents"], 0, "indemnity_paid_cents")
        assert_cents(before["alae_paid_cents"], 0, "alae_paid_cents")
        assert_cents(before["total_incurred_cents"], QCY_DEMAND_CENTS, "total_incurred_cents")

        settle(api, context["demand"]["id"], settlement_reference=SETTLEMENT_REFERENCE)
        mid = validate_success(api.get_claim(claim_id, CLAIMS_ADJUSTER))
        assert mid["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert_cents(mid["claim_exposure_cents"], QCY_DEMAND_CENTS, "claim_exposure_cents")
        assert_cents(
            mid["outstanding_reserve_cents"],
            QCY_OUTSTANDING_AFTER_SETTLEMENT_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(mid["indemnity_paid_cents"], QCY_OFFER_CENTS, "indemnity_paid_cents")
        assert_cents(mid["alae_paid_cents"], QCY_ALAE_CENTS, "alae_paid_cents")
        assert_cents(mid["total_incurred_cents"], QCY_DEMAND_CENTS, "total_incurred_cents")

        rescind(api, context["demand"]["id"], rescission_reason=RESCISSION_REASON)
        after = validate_success(api.get_claim(claim_id, CLAIMS_ADJUSTER))
        assert_cents(after["claim_exposure_cents"], QCY_DEMAND_CENTS, "claim_exposure_cents")
        assert_cents(
            after["outstanding_reserve_cents"], QCY_DEMAND_CENTS, "outstanding_reserve_cents"
        )
        assert_cents(after["indemnity_paid_cents"], 0, "indemnity_paid_cents")
        assert_cents(after["alae_paid_cents"], 0, "alae_paid_cents")
        assert_cents(after["reserve_released_cents"], 0, "reserve_released_cents")
        assert_cents(after["total_incurred_cents"], QCY_DEMAND_CENTS, "total_incurred_cents")
        assert after["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert after["reserve_status"] == RESERVE_STATUS_REVISED

    def test_the_demand_is_cleared_and_the_accepted_round_stands_open_again(
        self, api: ApiClient
    ):
        """The offer is neither deleted nor duplicated; it simply stands again.

        PRD: "The demand returns `SETTLED → OFFER_OUTSTANDING`, clears
        `settled_amount_cents`, `alae_cents`, `settlement_total_cents`,
        `settled_at` and `settlement_reference` back to null, increases
        `rescission_count` by 1 and increases its `version` by 1. The accepted
        round flips its `outcome` `ACCEPTED → OPEN`, so the very same offer stands
        again and may be re-accepted or superseded by a higher offer."

        Design: Difficulty/compensating_invariant/rescind_settlement_restores_claim_ledger_and_layer_capacity
        """
        context = _claim_ready_to_settle_on_a_two_layer_tower(api)
        demand_id = context["demand"]["id"]

        settled = settle(api, demand_id, settlement_reference=SETTLEMENT_REFERENCE)
        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(settled["settled_amount_cents"], QCY_OFFER_CENTS, "settled_amount_cents")
        assert_cents(settled["alae_cents"], QCY_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"],
            QCY_SETTLEMENT_TOTAL_CENTS,
            "settlement_total_cents",
        )

        rescinded = rescind(api, demand_id, rescission_reason=RESCISSION_REASON)

        assert rescinded["status"] == DEMAND_STATE_OFFER_OUTSTANDING
        assert rescinded["settled_amount_cents"] is None
        assert rescinded["alae_cents"] is None
        assert rescinded["settlement_total_cents"] is None
        assert rescinded["settled_at"] is None
        assert rescinded["settlement_reference"] is None
        assert rescinded["rescission_count"] == 1

        rounds, meta = validate_paginated(
            api.list_negotiation_rounds(demand_id, CLAIMS_ADJUSTER)
        )
        assert meta["total_count"] == 1
        assert rounds[0]["id"] == context["round"]["id"]
        assert rounds[0]["round_index"] == 1
        assert_cents(rounds[0]["carrier_offer_cents"], QCY_OFFER_CENTS, "carrier_offer_cents")
        assert rounds[0]["outcome"] == ROUND_OUTCOME_OPEN
        assert rounds[0]["outcome"] != ROUND_OUTCOME_ACCEPTED

    def test_the_layer_capacity_and_the_subrogation_ceiling_are_both_released(
        self, api: ApiClient
    ):
        """Both allocations are subtracted and the recovery file un-freezes.

        PRD: "the rescinded demand's allocations are subtracted from
        `layer_allocations`, `sir_eroded_cents` and `insured_paid_cents`, which
        restores the consumed capacity of every layer it touched so a later
        settlement can use it again; ... every subrogation demand on the claim in
        `READY_TO_PURSUE` returns to `DRAFT` with `recoverable_base_cents` and
        `max_recoverable_cents` reset to null"

        Design: Difficulty/compensating_invariant/rescind_settlement_restores_claim_ledger_and_layer_capacity
        """
        context = _claim_ready_to_settle_on_a_two_layer_tower(api)
        assert context["subrogation"]["status"] == SUBROGATION_STATE_DRAFT
        assert context["subrogation"]["recoverable_base_cents"] is None

        settle(api, context["demand"]["id"], settlement_reference=SETTLEMENT_REFERENCE)
        mid = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        allocations = mid["layer_allocations"]
        assert len(allocations) == 2
        assert allocations[0]["policy_layer_id"] == context["sir_layer"]["id"]
        assert_cents(
            allocations[0]["allocated_cents"], QCY_SIR_LIMIT_CENTS, "sir allocated_cents"
        )
        assert allocations[1]["policy_layer_id"] == context["primary_layer"]["id"]
        assert_cents(
            allocations[1]["allocated_cents"],
            QCY_PRIMARY_ALLOCATION_CENTS,
            "primary allocated_cents",
        )
        assert_cents(mid["sir_eroded_cents"], QCY_SIR_LIMIT_CENTS, "sir_eroded_cents")
        assert_cents(
            mid["insured_paid_cents"], QCY_PRIMARY_ALLOCATION_CENTS, "insured_paid_cents"
        )
        promoted = validate_success(
            api.get_subrogation_demand(context["subrogation"]["id"], CLAIMS_ADJUSTER)
        )
        assert promoted["status"] == SUBROGATION_STATE_READY_TO_PURSUE
        assert_cents(
            promoted["recoverable_base_cents"],
            QCY_RECOVERABLE_BASE_CENTS,
            "recoverable_base_cents",
        )
        assert_cents(
            promoted["max_recoverable_cents"],
            QCY_MAX_RECOVERABLE_CENTS,
            "max_recoverable_cents",
        )

        rescind(api, context["demand"]["id"], rescission_reason=RESCISSION_REASON)

        after = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert after["layer_allocations"] == []
        assert_cents(after["sir_eroded_cents"], 0, "sir_eroded_cents")
        assert_cents(after["insured_paid_cents"], 0, "insured_paid_cents")

        released = validate_success(
            api.get_subrogation_demand(context["subrogation"]["id"], CLAIMS_ADJUSTER)
        )
        assert released["status"] == SUBROGATION_STATE_DRAFT
        assert released["recoverable_base_cents"] is None
        assert released["max_recoverable_cents"] is None
        assert released["version"] == promoted["version"] + 1

        sir_layer = validate_success(
            api.get_policy_layer(context["sir_layer"]["id"], CLAIMS_MANAGER)
        )
        primary_layer = validate_success(
            api.get_policy_layer(context["primary_layer"]["id"], CLAIMS_MANAGER)
        )
        assert_cents(sir_layer["limit_cents"], QCY_SIR_LIMIT_CENTS, "sir limit_cents")
        assert_cents(
            primary_layer["limit_cents"], QCY_PRIMARY_LIMIT_CENTS, "primary limit_cents"
        )


RVN_ANNUAL_MILES_MILLIONS = 0.6666

PRIOR_EVIDENCE_WINDOW = {
    "window_start_at": "2026-06-15T10:00:00Z",
    "window_end_at": "2026-06-15T12:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}
NEW_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T03:00:00Z",
    "window_end_at": "2026-07-30T05:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}

# mechanical_factor is false on the prior crash, so the vehicle criterion is
# renormalised away: (3*0.30 + 3*0.25 + 3*0.20 + 3*0.10) / 0.85 == 3.00.
PRIOR_BALLOT_SCORE = 3.00
# mechanical_factor is true on the new crash, so all five criteria carry:
# 3*0.30 + 4*0.25 + 4*0.20 + 3*0.15 + 3*0.10 == 3.45.
NEW_BALLOT_SCORE = 3.45

BASELINE_POINTS = 2.0
APPLIED_POINTS = 10.0
BASELINE_RATE = 1.500
APPLIED_RATE = 3.000

NEW_SUSPENSION_START = "2026-08-03T00:00:00Z"
NEW_SUSPENSION_END = "2026-08-10T00:00:00Z"

APPEAL_GROUNDS = (
    "The committee applied the hazard-recognition criterion to a mechanical "
    "failure the driver could not have detected."
)


def _one_prior_crash_and_one_balloted_case(api: ApiClient) -> dict:
    """A driver already carrying one older preventable crash and its 2.0 points."""
    terminal = build_terminal(
        api,
        name="Ravenna Terminal",
        terminal_code="RVN01",
        region_code="OH",
        annual_miles_millions=RVN_ANNUAL_MILES_MILLIONS,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1901",
        full_name="Hollis Barnaby",
        cdl_number="OH-CDL-1901",
        hire_date="2011-09-19",
    )
    prior_crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-06-15T11:00:00Z",
        notified_at="2026-06-15T11:20:00Z",
        location_text="SR-44 at Diagonal Rd",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        mechanical_factor=False,
    )
    build_preserved_evidence(
        api,
        prior_crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6601",
        **PRIOR_EVIDENCE_WINDOW,
    )
    build_statement(
        api,
        prior_crash["id"],
        driver["id"],
        narrative="I clipped a bollard while backing into the dock.",
        conditions_note=None,
    )
    prior_case = build_review_case(
        api, prior_crash["id"], committee_name="Ravenna Safety Review Committee"
    )
    prior_opened = open_deliberation(api, prior_case["id"])
    cast_quorum(
        api,
        prior_opened,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    prior_decided = decide_case(api, prior_case["id"])

    new_crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T04:00:00Z",
        notified_at="2026-07-30T04:35:00Z",
        location_text="SR-5 at Lake Rockwell",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ECM-6602"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-6602"),
        (EVIDENCE_ELD_LOG, "ELD-6602"),
    ):
        build_preserved_evidence(
            api, new_crash["id"], kind=kind, source_device_id=device, **NEW_EVIDENCE_WINDOW
        )
    build_statement(
        api,
        new_crash["id"],
        driver["id"],
        narrative="I lost the trailer on a wet curve and struck the barrier.",
        conditions_note=None,
    )
    new_case = build_review_case(
        api, new_crash["id"], committee_name="Ravenna Safety Review Committee"
    )
    new_opened = open_deliberation(api, new_case["id"])
    cast_quorum(
        api,
        new_opened,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.criterion_scores(
            speed_and_spacing=3,
            hazard_recognition=4,
            regulatory_compliance=4,
            vehicle_condition_precheck=3,
            evasive_action=3,
        ),
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "prior_crash": prior_crash,
        "prior_case": prior_decided,
        "new_crash": new_crash,
        "new_case": new_case,
    }


def _decide_and_suspend(api: ApiClient, context: dict) -> dict:
    """Decide the new case preventable and pull the driver out of service."""
    decided = decide_case(api, context["new_case"]["id"])
    action = build_discipline(
        api,
        context["driver"]["id"],
        context["new_crash"]["id"],
        action_type=ACTION_TYPE_SUSPENSION,
        action_note="Loss of control on a wet curve, second preventable crash",
        suspension_start_at=NEW_SUSPENSION_START,
        suspension_end_at=NEW_SUSPENSION_END,
        retraining_course_code="SKID-1-2026",
    )
    return {"decided": decided, "action": action}


class TestGrantingAnAppealConservesPointsAndHeadcounts:
    """The restore point is a non-zero baseline, not the empty state."""

    def test_the_older_preventable_crash_establishes_that_non_zero_baseline(
        self, api: ApiClient
    ):
        """A renormalised all-threes ballot scores exactly 3.00 and rules preventable.

        PRD: "the same crash at a terminal with 0.6666 gives the half-up rounding
        of 1.50015 to three places, namely 1.500, which is exactly the `ELEVATED`
        boundary and so tiers as `ELEVATED`"

        Design: Difficulty/compensating_invariant/appeal_grant_restores_driver_points_and_terminal_counters
        """
        context = _one_prior_crash_and_one_balloted_case(api)
        assert_score_2dp(
            context["prior_case"]["committee_score"], PRIOR_BALLOT_SCORE, "committee_score"
        )
        assert context["prior_case"]["determination"] == DETERMINATION_PREVENTABLE

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], BASELINE_POINTS, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_COACHING
        assert driver["status"] == DRIVER_STATUS_ACTIVE
        assert driver["tenure_band"] == TENURE_OVER_36_MONTHS

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 1
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            BASELINE_RATE,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_ELEVATED
        assert terminal["active_driver_count"] == 1
        assert terminal["suspended_driver_count"] == 0
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

    def test_the_second_determination_and_its_suspension_move_every_figure(
        self, api: ApiClient
    ):
        """Both crashes now contribute at full value and the tier reaches suspension.

        PRD: "Each contributing crash yields a base figure from its `severity` —
        2 points for a `MINOR` crash, 4 for a `MODERATE` one, 8 for a `SEVERE` one
        and 12 for a `CATASTROPHIC` one — multiplied by a decay factor selected
        from the crash's age."

        Design: Difficulty/compensating_invariant/appeal_grant_restores_driver_points_and_terminal_counters
        """
        context = _one_prior_crash_and_one_balloted_case(api)
        applied = _decide_and_suspend(api, context)

        assert_score_2dp(
            applied["decided"]["committee_score"], NEW_BALLOT_SCORE, "committee_score"
        )
        assert applied["decided"]["determination"] == DETERMINATION_PREVENTABLE
        assert applied["action"]["status"] == ACTION_STATE_ISSUED
        assert applied["action"]["retraining_status"] == RETRAINING_STATUS_PENDING

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], APPLIED_POINTS, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_SUSPENSION
        assert driver["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 2
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            APPLIED_RATE,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_CRITICAL
        assert terminal["active_driver_count"] == 1
        assert terminal["suspended_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_CRITICAL

    def test_the_appeal_vacates_the_determination_and_voids_the_action(
        self, api: ApiClient
    ):
        """The action is neither deleted nor left pending; it is voided outright.

        PRD: "Every disciplinary action on the appealed crash that is still in
        `ISSUED` state moves `ISSUED → VOIDED` with its `retraining_status` reset
        to `NOT_REQUIRED`, releasing that action's suspension window so a later
        suspension may legitimately reuse the same interval"

        Design: Difficulty/compensating_invariant/appeal_grant_restores_driver_points_and_terminal_counters
        """
        context = _one_prior_crash_and_one_balloted_case(api)
        applied = _decide_and_suspend(api, context)

        appealed = grant_appeal(
            api,
            context["new_case"]["id"],
            appeal_grounds=APPEAL_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
        )

        assert appealed["status"] == REVIEW_STATE_DELIBERATION
        assert appealed["appeal_round"] == 1
        assert appealed["determination"] == DETERMINATION_PENDING
        assert appealed["committee_score"] is None
        assert appealed["decision_basis"] == DECISION_BASIS_NOT_APPLICABLE

        crash = validate_success(api.get_crash(context["new_crash"]["id"], SAFETY_ADMIN))
        assert crash["preventability_status"] == PREVENTABILITY_UNDER_REVIEW
        assert crash["appeals_exhausted"] is False
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

        action = validate_success(
            api.get_disciplinary_action(applied["action"]["id"], SAFETY_ADMIN)
        )
        assert action["status"] == ACTION_STATE_VOIDED
        assert action["retraining_status"] == RETRAINING_STATUS_NOT_REQUIRED

    def test_every_conserved_figure_lands_back_on_the_non_zero_baseline(
        self, api: ApiClient
    ):
        """Not zero and not the applied value: exactly the pre-decision figures.

        PRD: "Evaluated at a fixed logical clock, the pairing of a determination
        and the appeal that vacates it leaves the driver's points, both terminal
        headcounts and the terminal's preventable crash count exactly where they
        started."

        Design: Difficulty/compensating_invariant/appeal_grant_restores_driver_points_and_terminal_counters
        """
        context = _one_prior_crash_and_one_balloted_case(api)
        _decide_and_suspend(api, context)
        grant_appeal(
            api,
            context["new_case"]["id"],
            appeal_grounds=APPEAL_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
        )

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], BASELINE_POINTS, "preventable_points")
        assert driver["preventable_points"] != APPLIED_POINTS
        assert driver["required_action_tier"] == ACTION_TIER_COACHING
        assert driver["status"] == DRIVER_STATUS_ACTIVE

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 1
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            BASELINE_RATE,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_ELEVATED
        assert terminal["active_driver_count"] == 1
        assert terminal["suspended_driver_count"] == 0
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

    def test_the_prior_record_the_ballots_and_the_reported_basis_all_survive(
        self, api: ApiClient
    ):
        """The compensation adjusted determinations rather than destroying records.

        PRD: "Under `AS_REPORTED` every notified crash in the window is counted
        regardless of determination."

        Design: Difficulty/compensating_invariant/appeal_grant_restores_driver_points_and_terminal_counters
        """
        context = _one_prior_crash_and_one_balloted_case(api)
        _decide_and_suspend(api, context)
        grant_appeal(
            api,
            context["new_case"]["id"],
            appeal_grounds=APPEAL_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
        )

        prior_crash = validate_success(
            api.get_crash(context["prior_crash"]["id"], SAFETY_ADMIN)
        )
        assert prior_crash["preventability_status"] == PREVENTABILITY_PREVENTABLE
        prior_case = validate_success(
            api.get_review_case(context["prior_case"]["id"], SAFETY_MANAGER)
        )
        assert prior_case["status"] == REVIEW_STATE_DECIDED

        rows, meta = validate_paginated(
            api.list_votes(context["new_case"]["id"], SAFETY_MANAGER)
        )
        assert meta["total_count"] == 3
        assert all(row["superseded"] is False for row in rows)
        for row in rows:
            assert_score_2dp(
                row["weighted_member_score"], NEW_BALLOT_SCORE, "weighted_member_score"
            )

        analytics = validate_success(
            api.get_crash_analytics(
                context["terminal"]["id"],
                SAFETY_ADMIN,
                {"basis": ANALYTICS_BASIS_AS_REPORTED},
            )
        )
        assert analytics["basis"] == ANALYTICS_BASIS_AS_REPORTED
        assert analytics["crash_count"] == 2
        assert analytics["preventable_crash_count"] == 2
        assert_rate(
            analytics["crash_rate_per_million_miles"],
            APPLIED_RATE,
            "crash_rate_per_million_miles",
        )
        assert analytics["risk_tier"] == RISK_TIER_CRITICAL
