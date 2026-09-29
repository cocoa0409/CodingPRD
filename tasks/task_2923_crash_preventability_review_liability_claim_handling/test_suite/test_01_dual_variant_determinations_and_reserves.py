"""Determinations and reserves computed through their two interchangeable variants."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_multiplier,
    assert_points_1dp,
    assert_score_2dp,
)
from test_helpers.constants import (
    ACTION_TIER_SUSPENSION,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIMANT_TYPE_PROPERTY,
    DECISION_BASIS_UNWEIGHTED_MAJORITY,
    DECISION_BASIS_WEIGHTED_CRITERIA,
    DETERMINATION_NON_PREVENTABLE,
    DETERMINATION_PREVENTABLE,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_COMPROMISED,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    PREVENTABILITY_PREVENTABLE,
    PRESERVATION_PURGED_BEFORE_HOLD,
    RESERVE_BASIS_DEMAND_BASED,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    RESERVE_STATUS_REVISED,
    REVIEW_STATE_CLOSED_FINAL,
    REVIEW_STATE_DECIDED,
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
    COMMITTEE_ONE,
    COMMITTEE_THREE,
    COMMITTEE_TWO,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_driver,
    build_review_case,
    build_terminal,
    open_deliberation,
    preserve_evidence,
    request_evidence,
)

EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T13:00:00Z",
    "window_end_at": "2026-07-30T15:00:00Z",
    "retention_deadline_at": "2026-09-30T00:00:00Z",
}

BALLOTS = (
    (
        COMMITTEE_ONE,
        BALLOT_DISPOSITION_NON_PREVENTABLE,
        {
            "speed_and_spacing": 3,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 2,
            "regulatory_compliance": 3,
            "evasive_action": 2,
        },
        2.75,
    ),
    (
        COMMITTEE_TWO,
        BALLOT_DISPOSITION_NON_PREVENTABLE,
        {
            "speed_and_spacing": 2,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 3,
            "regulatory_compliance": 2,
            "evasive_action": 3,
        },
        2.50,
    ),
    (
        COMMITTEE_THREE,
        BALLOT_DISPOSITION_PREVENTABLE,
        {
            "speed_and_spacing": 4,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 2,
            "regulatory_compliance": 3,
            "evasive_action": 1,
        },
        2.95,
    ),
)

EXPECTED_COMMITTEE_SCORE = 2.73


def _severe_case_ready_to_decide(api: ApiClient) -> dict:
    """A severe crash with a complete record and three ballots already cast."""
    terminal = build_terminal(
        api,
        name="Ashland Terminal",
        terminal_code="ASH01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1001",
        full_name="Ray Vance",
        cdl_number="OH-CDL-1001",
        hire_date="2019-03-04",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T15:00:00Z",
        location_text="I-71 MM 128 northbound",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
        third_party_at_fault=True,
    )

    preserved = {}
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ELD-77120"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-F-77120"),
        (EVIDENCE_ELD_LOG, "ELD-77120"),
    ):
        requested = request_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **EVIDENCE_WINDOW
        )
        preserved[kind] = preserve_evidence(api, requested["id"])

    scene_photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-DISP-01",
        window_start_at="2026-07-30T15:30:00Z",
        window_end_at="2026-07-30T16:00:00Z",
        retention_deadline_at="2026-09-30T00:00:00Z",
    )

    case = build_review_case(
        api,
        crash["id"],
        committee_name="Ashland Preventability Committee",
        statement_waiver_reason=(
            "driver hospitalised at intake; statement waived by the safety manager"
        ),
    )
    current = open_deliberation(api, case["id"])
    for headers, vote, scores, _ in BALLOTS:
        current = validate_success(
            api.cast_vote(
                case["id"],
                factories.vote_payload(current["version"], vote=vote, scores=scores),
                headers,
            ),
            201,
        )

    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": current,
        "scene_photo": scene_photo,
        "preserved": preserved,
    }


class TestPreventabilityVariantDivergence:
    """The same three ballots decided under each of the two determination rules."""

    def test_complete_record_decides_by_unweighted_majority(self, api: ApiClient):
        """A complete evidence record makes the ballot count dispositive.

        PRD: "On a `COMPLETE` evidence record the basis is `UNWEIGHTED_MAJORITY`:
        the determination is `PREVENTABLE` when the count of live `PREVENTABLE`
        ballots strictly exceeds the count of live `NON_PREVENTABLE` ballots, and
        `NON_PREVENTABLE` otherwise"

        Design: Difficulty/dual_variant_calc/preventability_variant_divergence_weighted_vs_majority
        """
        context = _severe_case_ready_to_decide(api)

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

        decided = validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert decided["determination"] == DETERMINATION_NON_PREVENTABLE
        assert_score_2dp(decided["committee_score"], EXPECTED_COMMITTEE_SCORE, "committee_score")
        assert decided["status"] == REVIEW_STATE_DECIDED
        assert decided["appeal_round"] == 0

    def test_spoliation_flips_the_same_ballots_to_preventable(self, api: ApiClient):
        """Purging a never-preserved artifact switches the determination rule.

        PRD: "On a `COMPROMISED` evidence record the basis is
        `WEIGHTED_CRITERIA`: the determination is `PREVENTABLE` when
        `committee_score` is at least 2.50 and `NON_PREVENTABLE` when it falls
        below that threshold."

        Design: Difficulty/dual_variant_calc/preventability_variant_divergence_weighted_vs_majority
        """
        context = _severe_case_ready_to_decide(api)
        case_id = context["review_case"]["id"]

        first = validate_success(api.decide_review_case(case_id, headers=SAFETY_MANAGER))
        validate_success(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds=(
                        "the committee was not given the reconstruction memo before voting"
                    ),
                    appeal_grounds_code="PROCEDURAL",
                ),
                APPEALS_MANAGER,
            )
        )

        purged = validate_success(
            api.purge_evidence_item(
                context["scene_photo"]["id"],
                factories.purge_payload(
                    purge_reason=(
                        "scene photos auto-expired from the dispatcher handset "
                        "before the hold letter issued"
                    )
                ),
                SAFETY_ADMIN,
            )
        )
        assert purged["preservation_state"] == PRESERVATION_PURGED_BEFORE_HOLD

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPROMISED

        second = validate_success(api.decide_review_case(case_id, headers=SAFETY_MANAGER))

        assert second["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA
        assert second["determination"] == DETERMINATION_PREVENTABLE
        assert second["determination"] != first["determination"]
        assert_score_2dp(second["committee_score"], EXPECTED_COMMITTEE_SCORE, "committee_score")
        assert second["committee_score"] == first["committee_score"]
        assert second["status"] == REVIEW_STATE_CLOSED_FINAL

        settled_crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert settled_crash["appeals_exhausted"] is True
        assert settled_crash["preventability_status"] == PREVENTABILITY_PREVENTABLE

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert_points_1dp(driver["preventable_points"], 8.0, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_SUSPENSION

    def test_every_ballot_keeps_its_own_rounded_weighted_score(self, api: ApiClient):
        """The mean is taken over the already-rounded per-ballot scores.

        PRD: "`committee_score` is the mean of the *already-rounded*
        `weighted_member_score` values of the live, non-abstaining ballots, and
        that mean is itself rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/preventability_variant_divergence_weighted_vs_majority
        """
        context = _severe_case_ready_to_decide(api)

        rows, meta = validate_paginated(
            api.list_votes(context["review_case"]["id"], SAFETY_MANAGER)
        )

        assert meta["total_count"] == 3
        assert [row["sequence_number"] for row in rows] == [1, 2, 3]
        assert all(row["superseded"] is False for row in rows)
        for row, (_, _, _, expected_score) in zip(rows, BALLOTS):
            assert_score_2dp(
                row["weighted_member_score"], expected_score, "weighted_member_score"
            )


def _claim_on_moderate_crash(api: ApiClient) -> dict:
    """A moderate crash with no evidence at all and a claim opened on it."""
    terminal = build_terminal(
        api,
        name="Brookville Terminal",
        terminal_code="BRK01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-2001",
        full_name="Ines Ruiz",
        cdl_number="OH-CDL-2001",
        hire_date="2018-06-11",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T09:00:00Z",
        notified_at="2026-07-30T09:45:00Z",
        location_text="US-42 at Diamond Mill Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    claim = build_claim(
        api,
        crash["id"],
        claimant_notice_date="2026-07-31",
        adjuster_note="third-party fence and gate damage reported by the property owner",
    )
    return {"terminal": terminal, "driver": driver, "crash": crash, "claim": claim}


class TestClaimReserveVariantDivergence:
    """One claim re-reserved first from the crash and then from the written demand."""

    def test_provisional_refresh_reproduces_the_severity_estimate(self, api: ApiClient):
        """The provisional variant re-runs the severity ladder unchanged.

        PRD: "A `basis` of `PROVISIONAL_REFRESH` re-runs the severity estimate at
        the claim's current multiplier and counsel state"

        Design: Difficulty/dual_variant_calc/claim_reserve_provisional_refresh_vs_demand_based
        """
        context = _claim_on_moderate_crash(api)
        claim = context["claim"]

        assert_cents(claim["provisional_reserve_cents"], 2_500_000, "provisional_reserve_cents")
        assert claim["litigation_risk_score"] == 10
        assert_multiplier(claim["litigation_risk_multiplier"], 1.00)
        assert claim["counsel_required"] is False

        revised = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="45-day file review, no new information",
                ),
                CLAIMS_ADJUSTER,
            )
        )

        assert_cents(revised["revised_reserve_cents"], 2_500_000, "revised_reserve_cents")
        assert_cents(
            revised["outstanding_reserve_cents"], 2_500_000, "outstanding_reserve_cents"
        )
        assert revised["reserve_status"] == RESERVE_STATUS_REVISED
        assert revised["version"] == claim["version"] + 1

    def test_demand_based_rebases_the_same_claim_onto_the_written_demand(
        self, api: ApiClient
    ):
        """The demand-weighted variant discards the severity proxy entirely.

        PRD: "The demand-weighted variant replaces the severity proxy entirely
        once written demands exist: the gross exposure is the sum, over every
        demand on the claim, of that demand's `settlement_total_cents` when the
        demand has already reached `SETTLED` or `CLOSED_PAID`, and of its
        original `demand_amount_cents` otherwise."

        Design: Difficulty/dual_variant_calc/claim_reserve_provisional_refresh_vs_demand_based
        """
        context = _claim_on_moderate_crash(api)
        claim = context["claim"]

        from_crash = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"], basis=RESERVE_BASIS_PROVISIONAL_REFRESH
                ),
                CLAIMS_ADJUSTER,
            )
        )

        validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Marcia Odell",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=20_000_000,
                    represented_by_counsel=False,
                    demand_received_at="2026-07-31T12:00:00Z",
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )

        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        from_demand = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    observed["version"],
                    basis=RESERVE_BASIS_DEMAND_BASED,
                    revision_note="written demand received, re-reserving to the demand",
                ),
                CLAIMS_ADJUSTER,
            )
        )

        assert_cents(from_demand["revised_reserve_cents"], 20_000_000, "revised_reserve_cents")
        assert_cents(
            from_demand["outstanding_reserve_cents"], 20_000_000, "outstanding_reserve_cents"
        )
        assert (
            from_demand["revised_reserve_cents"] - from_crash["revised_reserve_cents"]
            == 17_500_000
        )
        assert_cents(
            from_demand["provisional_reserve_cents"],
            2_500_000,
            "provisional_reserve_cents",
        )
        assert from_demand["reserve_status"] == RESERVE_STATUS_REVISED
        assert from_demand["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert_cents(from_demand["claim_exposure_cents"], 20_000_000, "claim_exposure_cents")

    def test_the_conserved_exposure_moves_only_on_a_revision(self, api: ApiClient):
        """A reserve revision is the one operation licensed to change exposure.

        PRD: "This is the single operation in the system licensed to change
        `claim_exposure_cents`, and it is expected to: re-basing an estimate is
        exactly what changing exposure means."

        Design: Difficulty/dual_variant_calc/claim_reserve_provisional_refresh_vs_demand_based
        """
        context = _claim_on_moderate_crash(api)
        claim = context["claim"]
        assert_cents(claim["claim_exposure_cents"], 2_500_000, "claim_exposure_cents")

        validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Marcia Odell",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=20_000_000,
                    demand_received_at="2026-07-31T12:00:00Z",
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )

        after_demand = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert_cents(
            after_demand["claim_exposure_cents"], 2_500_000, "claim_exposure_cents"
        )

        after_revision = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    after_demand["version"], basis=RESERVE_BASIS_DEMAND_BASED
                ),
                CLAIMS_ADJUSTER,
            )
        )
        assert_cents(
            after_revision["claim_exposure_cents"], 20_000_000, "claim_exposure_cents"
        )
