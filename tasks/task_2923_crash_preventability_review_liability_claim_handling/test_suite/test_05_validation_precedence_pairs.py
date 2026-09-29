"""Requests that break two rules at once and must report the higher one."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_points_1dp
from test_helpers.constants import (
    ACTION_TIER_NONE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIMANT_TYPE_PROPERTY,
    DECISION_BASIS_NOT_APPLICABLE,
    DEMAND_STATE_SETTLED,
    DETERMINATION_PENDING,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    PREVENTABILITY_UNDER_REVIEW,
    RESERVE_BASIS_DEMAND_BASED,
    REVIEW_STATE_DELIBERATION,
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
    COMMITTEE_TWO,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_demand,
    build_driver,
    build_policy_layer,
    build_review_case,
    build_terminal,
    cast_ballot,
    make_offer,
    open_deliberation,
    preserve_evidence,
    request_evidence,
    revise_reserve,
    settle,
)

EXHAUSTED_TOWER_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T13:00:00Z",
    "window_end_at": "2026-07-30T15:00:00Z",
    "retention_deadline_at": "2026-09-30T00:00:00Z",
}

FIRST_REFERENCE = "SET-2026-IRN-0001"
SECOND_REFERENCE = "SET-2026-IRN-0002"

DEMAND_AMOUNT_CENTS = 20_000_000
OFFER_CENTS = 13_392_857
ALAE_CENTS = 1_607_143
SETTLEMENT_TOTAL_CENTS = 15_000_000
SIR_LIMIT_CENTS = 10_000_000
PRIMARY_LIMIT_CENTS = 5_000_000


def _claim_whose_tower_is_spent_to_the_cent(api: ApiClient) -> dict:
    """A settled demand that consumed the tower's entire 15,000,000 capacity."""
    terminal = build_terminal(
        api,
        name="Ironton Terminal",
        terminal_code="IRN01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-9001",
        full_name="Yuri Halstead",
        cdl_number="OH-CDL-9001",
        hire_date="2011-01-24",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T07:00:00Z",
        notified_at="2026-07-30T07:15:00Z",
        location_text="SR-93 at Storms Creek",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=SIR_LIMIT_CENTS,
        insurer_name="Self-Insured Retention",
    )
    build_policy_layer(
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
        adjuster_note="single third-party property claimant",
    )
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Storms Creek Holdings",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=DEMAND_AMOUNT_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T08:00:00Z",
    )
    observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
    revise_reserve(
        api,
        claim["id"],
        observed["version"],
        basis=RESERVE_BASIS_DEMAND_BASED,
        revision_note="reserving to the written demand",
    )
    make_offer(api, demand["id"], OFFER_CENTS)
    settled = settle(api, demand["id"], settlement_reference=FIRST_REFERENCE)
    after_settlement = validate_success(api.get_claim(claim["id"], CLAIMS_MANAGER))
    return {
        "claim": after_settlement,
        "demand": settled,
    }


class TestSettlingASettledDemand:
    """The state check outranks both money checks on the same request."""

    def test_the_state_error_wins_over_the_exhausted_tower(self, api: ApiClient):
        """Two money guards are also violated and neither is reported.

        PRD: "It means the claimant has accepted the standing carrier offer, so
        it is legal from exactly one demand state: `OFFER_OUTSTANDING → SETTLED`.
        Settling while the claimant's counter is the last word — that is, from
        `COUNTER_OUTSTANDING` — is not a declared transition, and neither is
        settling a `DEMANDED`, `SETTLED` or `CLOSED_PAID` demand; every one of
        those is `ERR_DEMAND_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/settle_settled_demand_state_beats_fiscal_coverage
        """
        context = _claim_whose_tower_is_spent_to_the_cent(api)
        assert context["demand"]["status"] == DEMAND_STATE_SETTLED
        assert_cents(
            context["demand"]["settlement_total_cents"],
            SETTLEMENT_TOTAL_CENTS,
            "settlement_total_cents",
        )
        assert_cents(
            context["claim"]["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS - SETTLEMENT_TOTAL_CENTS,
            "outstanding_reserve_cents",
        )

        body = validate_error(
            api.settle_demand(
                context["demand"]["id"],
                factories.settle_payload(settlement_reference=SECOND_REFERENCE),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.DEMAND_STATE_INVALID.value,
        )
        assert body["error_id"] != ApiErrorId.COVERAGE_EXHAUSTED.value
        assert body["error_id"] != ApiErrorId.RESERVE_INSUFFICIENT.value

    def test_the_refused_settlement_writes_nothing_to_the_demand_or_the_claim(
        self, api: ApiClient
    ):
        """A rejected request is inert across both records.

        PRD: "If anything is still unallocated after the last layer, the entire
        settlement is refused with `ERR_COVERAGE_EXHAUSTED` and no field on the
        demand, the claim or any layer is modified — settlement is all-or-nothing,
        never partial."

        Design: Difficulty/priority_pair_validation_conflict/settle_settled_demand_state_beats_fiscal_coverage
        """
        context = _claim_whose_tower_is_spent_to_the_cent(api)
        claim_id = context["claim"]["id"]
        demand_id = context["demand"]["id"]

        validate_error(
            api.settle_demand(
                demand_id,
                factories.settle_payload(settlement_reference=SECOND_REFERENCE),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.DEMAND_STATE_INVALID.value,
        )

        demand = validate_success(api.get_demand(demand_id, CLAIMS_MANAGER))
        assert demand["settlement_reference"] == FIRST_REFERENCE
        assert demand["rescission_count"] == 0
        assert demand["version"] == context["demand"]["version"]

        claim = validate_success(api.get_claim(claim_id, CLAIMS_MANAGER))
        assert_cents(claim["indemnity_paid_cents"], OFFER_CENTS, "indemnity_paid_cents")
        assert_cents(claim["alae_paid_cents"], ALAE_CENTS, "alae_paid_cents")
        assert_cents(claim["sir_eroded_cents"], SIR_LIMIT_CENTS, "sir_eroded_cents")
        assert_cents(claim["insured_paid_cents"], PRIMARY_LIMIT_CENTS, "insured_paid_cents")
        assert_cents(
            claim["claim_exposure_cents"], DEMAND_AMOUNT_CENTS, "claim_exposure_cents"
        )
        assert claim["version"] == context["claim"]["version"]
        assert len(claim["layer_allocations"]) == 2


def _partial_record_two_ballots(api: ApiClient) -> dict:
    """A severe crash with one preserved artifact and only two live ballots."""
    terminal = build_terminal(
        api,
        name="Jackson Terminal",
        terminal_code="JAX01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1101",
        full_name="Zane Coyle",
        cdl_number="OH-CDL-1101",
        hire_date="2010-10-04",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:15:00Z",
        location_text="US-35 at Coalton Rd",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    telematics = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ELD-11010",
        **EXHAUSTED_TOWER_EVIDENCE_WINDOW,
    )
    for kind, device in (
        (EVIDENCE_FORWARD_CAMERA, "CAM-F-11010"),
        (EVIDENCE_ELD_LOG, "ELD-11010"),
    ):
        request_evidence(
            api,
            crash["id"],
            kind=kind,
            source_device_id=device,
            **EXHAUSTED_TOWER_EVIDENCE_WINDOW,
        )
    preserve_evidence(
        api,
        telematics["id"],
        preserved_copy_uri="s3://evidence/2923e/tel-11010.json",
        evidence_hash="9a8b7c6d5e4f3021",
    )

    case = build_review_case(
        api,
        crash["id"],
        committee_name="Jackson Preventability Committee",
        statement_waiver_reason="statement waived pending medical clearance",
    )
    current = open_deliberation(api, case["id"])
    for headers in (COMMITTEE_ONE, COMMITTEE_TWO):
        current = cast_ballot(
            api,
            case["id"],
            current["version"],
            headers,
            vote=BALLOT_DISPOSITION_PREVENTABLE,
            scores=factories.uniform_criterion_scores(3),
        )
    return {
        "crash": crash,
        "driver": driver,
        "review_case": current,
    }


class TestDecidingOnAPartialRecordWithoutQuorum:
    """Evidentiary integrity outranks committee arithmetic."""

    def test_the_partial_record_is_reported_and_not_the_missing_quorum(
        self, api: ApiClient
    ):
        """Both guards fail and the higher-priority evidence guard answers.

        PRD: "The crash's `evidence_posture` must be `COMPLETE` or `COMPROMISED`,
        and a merely `PARTIAL` record is refused with
        `ERR_EVIDENCE_POSTURE_INSUFFICIENT`. And the case must have at least three
        live, non-abstaining ballots, or the response is `ERR_QUORUM_NOT_MET` ...
        The evidence check outranks the quorum check, so a case that both lacks
        quorum and rests on a partial record reports the evidence failure."

        Design: Difficulty/priority_pair_validation_conflict/decide_partial_posture_safety_beats_constraint_quorum
        """
        context = _partial_record_two_ballots(api)
        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert context["review_case"]["active_vote_count"] == 2

        body = validate_error(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER),
            ApiErrorId.EVIDENCE_POSTURE_INSUFFICIENT.value,
        )
        assert body["error_id"] != ApiErrorId.QUORUM_NOT_MET.value
        assert body["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES.value

    def test_the_refused_decision_leaves_the_case_crash_and_driver_alone(
        self, api: ApiClient
    ):
        """None of the cascade's three records moves on a rejected decision.

        PRD: "When `appeal_round` is still below the single permitted appeal
        round, the case moves `DELIBERATION → DECIDED`, recording
        `determination`, `decision_basis`, `committee_score`,
        `decided_by_user_id` from the acting operator and `decided_at` from the
        logical clock, and the case's `version` increases by 1."

        Design: Difficulty/priority_pair_validation_conflict/decide_partial_posture_safety_beats_constraint_quorum
        """
        context = _partial_record_two_ballots(api)
        case_id = context["review_case"]["id"]

        validate_error(
            api.decide_review_case(case_id, headers=SAFETY_MANAGER),
            ApiErrorId.EVIDENCE_POSTURE_INSUFFICIENT.value,
        )

        case = validate_success(api.get_review_case(case_id, SAFETY_MANAGER))
        assert case["status"] == REVIEW_STATE_DELIBERATION
        assert case["determination"] == DETERMINATION_PENDING
        assert case["decision_basis"] == DECISION_BASIS_NOT_APPLICABLE
        assert case["committee_score"] is None
        assert case["decided_at"] is None
        assert case["decided_by_user_id"] is None
        assert case["version"] == context["review_case"]["version"]

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["preventability_status"] == PREVENTABILITY_UNDER_REVIEW

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], 0.0, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_NONE
