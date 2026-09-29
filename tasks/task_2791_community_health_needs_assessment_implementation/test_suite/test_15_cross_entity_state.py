"""Gates that read the state of a sibling entity rather than the request."""

from test_helpers import (
    BOARD,
    OFFICER,
    ApiErrorId,
    ApprovalState,
    CandidateStatus,
    CommitmentStatus,
    CycleStatus,
    DataState,
    FundingState,
    PostingStatus,
    SignatorySide,
    Subgroup,
    SignatureState,
    ValuationBasis,
    add_agreement,
    add_candidate,
    add_data_point,
    add_indicator,
    add_internal_party,
    add_interview,
    add_partner_party,
    advance_to,
    assert_close,
    build_scenario,
    complete_interview,
    create_cycle,
    make_indicator_sufficient,
    make_partner_representative_headers,
    open_report,
    validate_error,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F



def _cycle_with_two_indicators(api):
    """One indicator with two subgroups and one with a single subgroup."""
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)

    sufficient = add_indicator(api, cycle["id"], name="Adult depression prevalence")
    make_indicator_sufficient(api, sufficient["id"])

    insufficient = add_indicator(api, cycle["id"], name="Adult anxiety prevalence")
    add_data_point(
        api, insufficient["id"], population_subgroup=Subgroup.OVERALL, value=9.0
    )
    add_data_point(
        api, insufficient["id"], population_subgroup=Subgroup.BLACK_NH, value=12.0
    )

    facilitator = add_internal_party(api)["id"]
    advance_to(api, cycle["id"], CycleStatus.INPUT_GATHERING)
    interview = add_interview(api, cycle["id"], facilitator)
    complete_interview(api, interview["id"])
    advance_to(api, cycle["id"], CycleStatus.PRIORITIZATION)

    candidates = {
        "sufficient": add_candidate(api, cycle["id"], sufficient["id"])["id"],
        "insufficient": add_candidate(api, cycle["id"], insufficient["id"])["id"],
    }
    return cycle, {"sufficient": sufficient["id"], "insufficient": insufficient["id"]}, candidates


def test_scoring_is_refused_while_the_indicator_holds_a_single_subgroup(api):
    """PRD §3.4: "The candidate's indicator must have `data_state` equal to
    `SUFFICIENT`, or the run fails with `ERR_INDICATOR_DATA_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/candidate_score_blocked_when_indicator_data_insufficient
    """
    _cycle, indicators, candidates = _cycle_with_two_indicators(api)

    indicator = validate_success(api.get_indicator(indicators["insufficient"]))
    assert indicator["data_state"] == DataState.INSUFFICIENT
    assert indicator["subgroup_count"] == 1
    assert indicator["disparity_ratio"] is None
    # Severity alone is not enough to score: 9.0 / 12.0 * 50 = 37.50.
    assert_close(indicator["severity_score"], 37.50, "severity_score")

    validate_error(
        api.score_candidate(candidates["insufficient"], "EQUAL_WEIGHT"),
        ApiErrorId.INDICATOR_DATA_INSUFFICIENT,
    )

    candidate = validate_success(api.get_candidate(candidates["insufficient"]))
    assert candidate["status"] == CandidateStatus.DRAFT
    assert candidate["composite_score"] is None
    assert candidate["severity_input"] is None
    assert candidate["community_concern_index"] is None


def test_the_sibling_candidate_on_a_sufficient_indicator_scores_normally(api):
    """PRD §3.2: "Finally `data_state` is `SUFFICIENT` when `latest_overall_value`
    is not null *and* `subgroup_count` is at least 2, and `INSUFFICIENT` in every
    other case."

    Design: Difficulty/cross_entity_state_dependency/candidate_score_blocked_when_indicator_data_insufficient
    """
    cycle, indicators, candidates = _cycle_with_two_indicators(api)

    validate_error(
        api.score_candidate(candidates["insufficient"], "EQUAL_WEIGHT"),
        ApiErrorId.INDICATOR_DATA_INSUFFICIENT,
    )

    scored = validate_success(api.score_candidate(candidates["sufficient"], "EQUAL_WEIGHT"))
    assert scored["status"] == CandidateStatus.SCORED
    assert_close(scored["composite_score"], C.EXPECTED_COMPOSITE_EQUAL_WEIGHT, "composite_score")

    assert validate_success(api.get_indicator(indicators["sufficient"]))["data_state"] == (
        DataState.SUFFICIENT
    )
    assert validate_success(api.get_cycle(cycle["id"]))["sufficient_indicator_count"] == 1


def test_a_posting_naming_a_submitted_strategy_is_refused(api):
    """PRD §3.9: "When a `strategy_id` is supplied it must name an implementation
    strategy whose `approval_state` is `APPROVED`; attaching community benefit
    spending to a strategy the board never approved is rejected with
    `ERR_STRATEGY_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/posting_with_strategy_requires_strategy_approved
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")
    report = open_report(api, sc.cycle_id)
    assert sc.strategy()["approval_state"] == ApprovalState.SUBMITTED

    validate_error(
        api.create_posting(
            F.cost_based_posting_payload(
                report["id"], report["version"], 850000, strategy_id=sc.strategy_id
            )
        ),
        ApiErrorId.STRATEGY_NOT_APPROVED,
    )

    unchanged = validate_success(api.get_report(report["id"]))
    assert unchanged["total_valued_cents"] == 0
    assert unchanged["version"] == report["version"]


def test_the_identical_posting_body_is_accepted_once_the_board_approves(api):
    """PRD §2.5: "Conversely, an operation that is rejected by any rule in this
    document changes nothing and increments no `version`."

    Design: Difficulty/cross_entity_state_dependency/posting_with_strategy_requires_strategy_approved
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")
    report = open_report(api, sc.cycle_id)
    payload = F.cost_based_posting_payload(
        report["id"], report["version"], 850000, strategy_id=sc.strategy_id
    )
    validate_error(api.create_posting(payload), ApiErrorId.STRATEGY_NOT_APPROVED)

    validate_success(api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD))
    assert sc.strategy()["approval_state"] == ApprovalState.APPROVED

    # Identical body, identical expected_report_version.
    posting = validate_success(api.create_posting(payload), 201)
    assert posting["status"] == PostingStatus.POSTED
    assert posting["valued_cents"] == 850000
    assert posting["ratio_applied"] is None
    assert posting["valuation_basis_at_posting"] == ValuationBasis.PROVISIONAL

    stored = validate_success(api.get_report(report["id"]))
    assert stored["community_health_improvement_cents"] == 850000
    assert stored["total_valued_cents"] == 850000
    assert_close(stored["overhead_rate"], 0.05, "overhead_rate")
    assert stored["indirect_allocation_cents"] == 42500
    assert stored["grand_total_cents"] == 892500
    assert_close(stored["benefit_pct_of_expense"], 0.74, "benefit_pct_of_expense")


def test_a_commitment_drawn_from_a_half_signed_agreement_is_refused(api):
    """PRD §3.6: "First, when `partnership_id` is supplied, the named agreement's
    `signature_state` must be `EXECUTED` — funding may only be drawn from an
    agreement both sides have signed — or the create fails with
    `ERR_PARTNERSHIP_NOT_EXECUTED`."

    Design: Difficulty/cross_entity_state_dependency/commitment_with_partnership_requires_agreement_executed
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    partner = add_partner_party(api)
    agreement = add_agreement(api, sc.cycle_id, partner["id"])
    half_signed = validate_success(
        api.sign_agreement(agreement["id"], SignatorySide.HOSPITAL, headers=OFFICER)
    )
    assert half_signed["signature_state"] == SignatureState.HOSPITAL_SIGNED
    assert half_signed["funding_state"] == FundingState.UNFUNDED

    validate_error(
        api.create_commitment(
            F.commitment_payload(sc.strategy_id, partner["id"], agreement["id"])
        ),
        ApiErrorId.PARTNERSHIP_NOT_EXECUTED,
    )

    # The rejection encumbered nothing.
    assert validate_success(api.get_party(partner["id"]))["committed_fte_bp"] == 0
    assert sc.strategy()["budget_available_cents"] == C.AUTHORIZED_BUDGET_CENTS


def test_the_countersignature_admits_the_identical_commitment_body(api):
    """PRD §3.6: "A commitment starts with `status` at `PENDING` and
    `committed_at`, `released_at` and `release_reason` all null."

    Design: Difficulty/cross_entity_state_dependency/commitment_with_partnership_requires_agreement_executed
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    partner = add_partner_party(api)
    agreement = add_agreement(api, sc.cycle_id, partner["id"])
    validate_success(api.sign_agreement(agreement["id"], SignatorySide.HOSPITAL, headers=OFFICER))
    payload = F.commitment_payload(sc.strategy_id, partner["id"], agreement["id"])
    validate_error(api.create_commitment(payload), ApiErrorId.PARTNERSHIP_NOT_EXECUTED)

    executed = validate_success(
        api.sign_agreement(
            agreement["id"],
            SignatorySide.PARTNER,
            headers=make_partner_representative_headers(partner["id"]),
        )
    )
    assert executed["signature_state"] == SignatureState.EXECUTED
    assert executed["funding_state"] == FundingState.PLEDGED
    assert executed["hospital_signed_at"] is not None
    assert executed["partner_signed_at"] is not None

    commitment = validate_success(api.create_commitment(payload), 201)
    assert commitment["status"] == CommitmentStatus.PENDING
    assert commitment["committed_at"] is None

    # A PENDING commitment already encumbers both conserved quantities.
    assert validate_success(api.get_party(partner["id"]))["committed_fte_bp"] == C.COMMITMENT_FTE_BP
    assert sc.strategy()["budget_available_cents"] == (
        C.AUTHORIZED_BUDGET_CENTS - C.COMMITMENT_FUNDING_CENTS
    )
    # Funding only lands at board adoption, not at commitment creation.
    after = validate_success(api.get_agreement(agreement["id"]))
    assert after["funded_cents"] == 0
    assert after["funding_state"] == FundingState.PLEDGED
