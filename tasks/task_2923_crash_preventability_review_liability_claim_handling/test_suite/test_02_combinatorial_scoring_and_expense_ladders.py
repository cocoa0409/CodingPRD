"""Nested rounding on ballots and the pinned expense ladder on a settlement."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_instants_equal, assert_score_2dp
from test_helpers.constants import (
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
    LAYER_KIND_SIR,
    PREVENTABILITY_PREVENTABLE,
    RESERVE_BASIS_DEMAND_BASED,
    ROUND_OUTCOME_ACCEPTED,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
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
)

MECHANICAL_FREE_BALLOTS = (
    (
        COMMITTEE_ONE,
        {
            "speed_and_spacing": 0,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 0,
            "regulatory_compliance": 2,
            "evasive_action": 4,
        },
        1.82,
    ),
    (
        COMMITTEE_TWO,
        {
            "speed_and_spacing": 2,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 0,
            "regulatory_compliance": 3,
            "evasive_action": 4,
        },
        2.76,
    ),
    (
        COMMITTEE_THREE,
        {
            "speed_and_spacing": 4,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 0,
            "regulatory_compliance": 4,
            "evasive_action": 3,
        },
        3.59,
    ),
)

EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T13:30:00Z",
    "window_end_at": "2026-07-30T14:30:00Z",
    "retention_deadline_at": "2026-09-30T00:00:00Z",
}


def _case_with_renormalised_ballots(api: ApiClient) -> dict:
    """A severe crash with no mechanical factor and three substantive ballots."""
    terminal = build_terminal(
        api,
        name="Corydon Terminal",
        terminal_code="CRY01",
        region_code="IN",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3001",
        full_name="Owen Marsh",
        cdl_number="IN-CDL-3001",
        hire_date="2017-02-20",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:20:00Z",
        location_text="I-64 MM 105 westbound",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=False,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ELD-30110"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-F-30110"),
        (EVIDENCE_ELD_LOG, "ELD-30110"),
    ):
        build_preserved_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **EVIDENCE_WINDOW
        )

    case = build_review_case(
        api,
        crash["id"],
        committee_name="Corydon Preventability Committee",
        statement_waiver_reason="driver on FMLA leave; statement waived",
    )
    current = open_deliberation(api, case["id"])
    for headers, scores, _ in MECHANICAL_FREE_BALLOTS:
        current = validate_success(
            api.cast_vote(
                case["id"],
                factories.vote_payload(
                    current["version"],
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=scores,
                ),
                headers,
            ),
            201,
        )
    return {"crash": crash, "driver": driver, "review_case": current}


class TestMemberScoreRoundingOrder:
    """Per-ballot rounding happens before the mean, on a renormalised denominator."""

    def test_ballots_renormalise_the_inapplicable_criterion(self, api: ApiClient):
        """A non-mechanical crash divides by 0.85 rather than scoring a zero.

        PRD: "the denominator is the sum of the weights of the applicable
        criteria, which is 0.85 in the four-criterion case and 1.00 in the
        five-criterion case"

        Design: Difficulty/combinatorial_formula/member_score_round_then_mean_ordering
        """
        context = _case_with_renormalised_ballots(api)

        rows, meta = validate_paginated(
            api.list_votes(context["review_case"]["id"], SAFETY_MANAGER)
        )

        assert meta["total_count"] == 3
        assert [row["sequence_number"] for row in rows] == [1, 2, 3]
        for row, (_, _, expected_score) in zip(rows, MECHANICAL_FREE_BALLOTS):
            assert_score_2dp(
                row["weighted_member_score"], expected_score, "weighted_member_score"
            )

    def test_committee_score_is_the_mean_of_the_rounded_ballots(self, api: ApiClient):
        """Averaging the unrounded quotients would produce the wrong figure.

        PRD: "Three ballots whose unrounded quotients are 1.82352941, 2.76470588
        and 3.58823529 round to 1.82, 2.76 and 3.59, whose mean rounds to 2.72;
        averaging the unrounded quotients instead would yield 2.73, and that
        figure is wrong."

        Design: Difficulty/combinatorial_formula/member_score_round_then_mean_ordering
        """
        context = _case_with_renormalised_ballots(api)

        decided = validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        assert_score_2dp(decided["committee_score"], 2.72, "committee_score")
        assert float(decided["committee_score"]) != 2.73
        assert float(decided["committee_score"]) != 2.32
        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert decided["determination"] == DETERMINATION_PREVENTABLE

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["preventability_status"] == PREVENTABILITY_PREVENTABLE
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE


def _claim_with_standing_offer(api: ApiClient) -> dict:
    """A property-damage demand reserved to its full amount with an offer standing."""
    terminal = build_terminal(
        api,
        name="Dayton Terminal",
        terminal_code="DAY01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4001",
        full_name="Pia Kohl",
        cdl_number="OH-CDL-4001",
        hire_date="2016-09-05",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T08:00:00Z",
        notified_at="2026-07-30T08:30:00Z",
        location_text="SR-4 at Needmore Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LOCAL,
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
        api, crash["id"], claimant_notice_date="2026-07-31", adjuster_note="property damage only"
    )
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Needmore Auto Body",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=6_000_000,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T10:00:00Z",
    )
    observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
    reserved = revise_reserve(
        api,
        claim["id"],
        observed["version"],
        basis=RESERVE_BASIS_DEMAND_BASED,
        revision_note="reserving to the written demand ahead of settlement authority",
    )
    round_row = make_offer(api, demand["id"], 4_900_000)
    return {
        "retention": retention,
        "claim": reserved,
        "demand": demand,
        "round": round_row,
    }


class TestExpenseTierKeyedOnIndemnity:
    """The expense rate is chosen from the indemnity, never from the total."""

    def test_expense_rate_is_selected_from_the_indemnity_alone(self, api: ApiClient):
        """An offer just under the tier edge stays in the lower expense band.

        PRD: "Worked: an indemnity of 4,900,000 is under 5,000,000, so the rate
        is 0.08, `alae_cents` is 392,000 and `settlement_total_cents` is
        5,292,000 — whereas keying the tier on the total would wrongly reach the
        0.12 rate for an expense of 588,000 and a total of 5,488,000."

        Design: Difficulty/combinatorial_formula/alae_tier_keyed_on_indemnity_then_total
        """
        context = _claim_with_standing_offer(api)
        assert_cents(
            context["claim"]["outstanding_reserve_cents"],
            6_000_000,
            "outstanding_reserve_cents",
        )

        settled = validate_success(
            api.settle_demand(
                context["demand"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-DAY-0001"),
                CLAIMS_MANAGER,
            )
        )

        assert_cents(settled["settled_amount_cents"], 4_900_000, "settled_amount_cents")
        assert_cents(settled["alae_cents"], 392_000, "alae_cents")
        assert_cents(settled["settlement_total_cents"], 5_292_000, "settlement_total_cents")
        assert settled["alae_cents"] != 588_000
        assert settled["settlement_total_cents"] != 5_488_000
        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_instants_equal(settled["settled_at"], CLOCK_EPOCH, "settled_at")

    def test_the_settlement_walks_the_retention_and_holds_exposure(self, api: ApiClient):
        """The whole total lands in the retention and exposure is unchanged.

        PRD: "increases `sir_eroded_cents` by the allocations to the `SIR` layer
        and `insured_paid_cents` by the allocations to `PRIMARY` and `EXCESS`
        layers, and increases its own `version` by 1. `claim_exposure_cents` is
        unchanged throughout, because paying a claim moves money between buckets
        rather than creating or destroying exposure."

        Design: Difficulty/combinatorial_formula/alae_tier_keyed_on_indemnity_then_total
        """
        context = _claim_with_standing_offer(api)

        validate_success(
            api.settle_demand(
                context["demand"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-DAY-0001"),
                CLAIMS_MANAGER,
            )
        )

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        allocations = claim["layer_allocations"]
        assert len(allocations) == 1
        assert allocations[0]["policy_layer_id"] == context["retention"]["id"]
        assert allocations[0]["layer_index"] == 1
        assert allocations[0]["layer_type"] == LAYER_KIND_SIR
        assert_cents(allocations[0]["allocated_cents"], 5_292_000, "allocated_cents")

        assert_cents(claim["sir_eroded_cents"], 5_292_000, "sir_eroded_cents")
        assert_cents(claim["insured_paid_cents"], 0, "insured_paid_cents")
        assert_cents(claim["indemnity_paid_cents"], 4_900_000, "indemnity_paid_cents")
        assert_cents(claim["alae_paid_cents"], 392_000, "alae_paid_cents")
        assert_cents(claim["outstanding_reserve_cents"], 708_000, "outstanding_reserve_cents")
        assert_cents(claim["claim_exposure_cents"], 6_000_000, "claim_exposure_cents")
        assert claim["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE

        rounds, meta = validate_paginated(
            api.list_negotiation_rounds(context["demand"]["id"], CLAIMS_ADJUSTER)
        )
        assert meta["total_count"] == 1
        assert rounds[0]["outcome"] == ROUND_OUTCOME_ACCEPTED
