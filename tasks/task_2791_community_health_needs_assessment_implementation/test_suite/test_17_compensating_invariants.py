"""Compensating actions: release and void must restore conserved quantities exactly."""

from test_helpers import (
    COMPLIANCE,
    OFFICER,
    ApiErrorId,
    ApprovalState,
    CommitmentStatus,
    CycleStatus,
    ExecutionState,
    FundingState,
    ObjectiveStatus,
    PostingStatus,
    Posture,
    ReportStatus,
    SignatureState,
    ValuationBasis,
    add_commitment,
    assert_close,
    assert_posture,
    build_scenario,
    create_cycle,
    open_report,
    post_charge_based,
    post_cost_based,
    validate_error,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_releasing_a_pending_commitment_restores_the_whole_envelope(api):
    """PRD §3.6: "The invariant is that the strategy's `budget_available_cents`
    plus that encumbered sum always equals its `authorized_budget_cents`, after
    every forward action and after every compensating release."

    Design: Difficulty/compensating_invariant/pending_commitment_release_restores_strategy_budget_identity
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    commitment = add_commitment(api, sc.strategy_id, sc.facilitator_party_id)
    assert sc.strategy()["budget_available_cents"] == 3500000
    assert validate_success(api.get_party(sc.facilitator_party_id))["committed_fte_bp"] == 2500

    validate_error(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=100, funding_cents=4000000
            )
        ),
        ApiErrorId.STRATEGY_BUDGET_EXCEEDED,
    )

    released = validate_success(
        api.release_commitment(commitment["id"], "Partner withdrew the in-kind staffing offer")
    )
    assert released["status"] == CommitmentStatus.RELEASED
    assert released["released_at"] is not None
    assert released["release_reason"] == "Partner withdrew the in-kind staffing offer"

    assert sc.strategy()["budget_available_cents"] == C.AUTHORIZED_BUDGET_CENTS
    assert validate_success(api.get_party(sc.facilitator_party_id))["committed_fte_bp"] == 0


def test_a_second_release_does_not_credit_the_envelope_twice(api):
    """PRD §3.6: "It is permitted while the commitment's `status` is `PENDING` or
    `COMMITTED`, rejecting a second release with `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/pending_commitment_release_restores_strategy_budget_identity
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    commitment = add_commitment(api, sc.strategy_id, sc.facilitator_party_id)
    validate_success(api.release_commitment(commitment["id"], "Offer withdrawn"))

    # The freed capacity is genuinely re-usable.
    replacement = add_commitment(
        api, sc.strategy_id, sc.facilitator_party_id, fte_bp=100, funding_cents=4000000
    )
    assert replacement["status"] == CommitmentStatus.PENDING
    assert sc.strategy()["budget_available_cents"] == 1000000

    validate_error(
        api.release_commitment(commitment["id"], "Duplicate release attempt"),
        ApiErrorId.INVALID_STATE,
    )
    assert sc.strategy()["budget_available_cents"] == 1000000
    assert validate_success(api.get_party(sc.facilitator_party_id))["committed_fte_bp"] == 100


def test_releasing_a_committed_commitment_unwinds_the_partnership_funding(api):
    """PRD §3.6: "When `partnership_id` is supplied *and* the row being released
    had reached `COMMITTED`, the agreement's `funded_cents` is reduced by the same
    `funding_cents`, and once `funded_cents` reaches 0 the agreement's
    `funding_state` moves `FUNDED` to `RELEASED`."

    Design: Difficulty/compensating_invariant/committed_commitment_release_restores_partnership_funding_and_party_fte
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    assert sc.commitment()["status"] == CommitmentStatus.COMMITTED
    assert sc.agreement()["funded_cents"] == C.COMMITMENT_FUNDING_CENTS
    assert sc.agreement()["funding_state"] == FundingState.FUNDED

    released = validate_success(
        api.release_commitment(
            sc.commitment_id, "Coalition merged and the funded post was withdrawn"
        )
    )
    assert released["status"] == CommitmentStatus.RELEASED
    assert released["released_at"] is not None
    # committed_at is retained, not cleared.
    assert released["committed_at"] is not None

    assert validate_success(api.get_party(sc.partner_party_id))["committed_fte_bp"] == 0
    assert sc.strategy()["budget_available_cents"] == C.AUTHORIZED_BUDGET_CENTS

    agreement = sc.agreement()
    assert agreement["funded_cents"] == 0
    assert agreement["funding_state"] == FundingState.RELEASED
    assert agreement["pledged_cents"] == C.PLEDGED_CENTS
    assert agreement["signature_state"] == SignatureState.EXECUTED


def test_the_release_leaves_the_rest_of_the_adopted_state_alone(api):
    """PRD §3.6: "For a party starting at zero, the sequence create-commitment,
    activate, release must return `committed_fte_bp` to exactly zero."

    Design: Difficulty/compensating_invariant/committed_commitment_release_restores_partnership_funding_and_party_fte
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)

    validate_success(api.release_commitment(sc.commitment_id, "Funded post withdrawn"))

    assert validate_success(api.get_party(sc.partner_party_id))["committed_fte_bp"] == 0
    assert sc.objective()["status"] == ObjectiveStatus.ACTIVE
    strategy = sc.strategy()
    assert strategy["approval_state"] == ApprovalState.APPROVED
    assert strategy["execution_state"] == ExecutionState.ON_TRACK
    cycle = sc.cycle()
    assert cycle["status"] == CycleStatus.ADOPTED
    assert cycle["review_flag_count"] == 0
    assert_posture(cycle, Posture.OPEN)


def test_voiding_a_posting_reselects_the_tier_from_the_reduced_base(api):
    """PRD §3.9: "On success the supplied reason is stored in `void_reason`,
    `voided_by_user_id` records the actor, `status` moves `POSTED` to `VOID`, and
    every one of the report's totals — the five categories, `total_valued_cents`,
    `overhead_rate`, `indirect_allocation_cents`, `grand_total_cents` and
    `benefit_pct_of_expense` — is recomputed so that the report returns to exactly
    the values it held before that posting was ever entered."

    Design: Difficulty/compensating_invariant/posting_void_restores_report_totals_identity
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    first = post_charge_based(api, report["id"], 1234567)
    second = post_cost_based(api, report["id"], 850000)

    before = validate_success(api.get_report(report["id"]))
    assert before["total_valued_cents"] == 1245061
    assert before["indirect_allocation_cents"] == 62253
    assert before["grand_total_cents"] == 1307314
    assert_close(before["benefit_pct_of_expense"], 1.09, "benefit_pct_of_expense")

    voided = validate_success(
        api.void_posting(
            second["id"], "Grant expense reclassified to the operating budget", headers=COMPLIANCE
        )
    )
    assert voided["status"] == PostingStatus.VOID
    assert voided["voided_by_user_id"] == COMPLIANCE["X-User-ID"]

    after = validate_success(api.get_report(report["id"]))
    assert after["community_health_improvement_cents"] == 0
    assert after["financial_assistance_cents"] == 395061
    assert after["total_valued_cents"] == 395061
    assert_close(after["overhead_rate"], 0.05, "overhead_rate")
    # The tier is re-selected from the reduced base, not credited back.
    assert after["indirect_allocation_cents"] == 19753
    assert after["grand_total_cents"] == 414814
    assert_close(after["benefit_pct_of_expense"], 0.35, "benefit_pct_of_expense")
    assert first["id"] != second["id"]


def test_an_all_void_report_is_treated_as_empty_and_never_credited_twice(api):
    """PRD §3.9: "the report must hold at least one posting whose `status` is
    `POSTED`, because an empty report has nothing to certify — that rejection is
    `ERR_REPORT_EMPTY`, and a report whose only postings have all been voided
    counts as empty."

    Design: Difficulty/compensating_invariant/posting_void_restores_report_totals_identity
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    charge_posting = post_charge_based(api, report["id"], 1234567)
    cost_posting = post_cost_based(api, report["id"], 850000)

    validate_success(api.void_posting(cost_posting["id"], "Reclassified", headers=COMPLIANCE))
    # VOID is terminal, so the totals are not credited twice.
    validate_error(
        api.void_posting(cost_posting["id"], "Duplicate void attempt", headers=COMPLIANCE),
        ApiErrorId.INVALID_STATE,
    )
    # The officer who entered the posting may not void it.
    validate_error(
        api.void_posting(charge_posting["id"], "Self-void attempt", headers=OFFICER),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    assert validate_success(api.get_posting(charge_posting["id"]))["status"] == PostingStatus.POSTED
    assert validate_success(api.get_report(report["id"]))["total_valued_cents"] == 395061

    validate_success(
        api.void_posting(
            charge_posting["id"], "Charity care case reopened and rebilled", headers=COMPLIANCE
        )
    )
    emptied = validate_success(api.get_report(report["id"]))
    assert emptied["total_valued_cents"] == 0
    assert emptied["indirect_allocation_cents"] == 0
    assert emptied["grand_total_cents"] == 0
    assert_close(emptied["benefit_pct_of_expense"], 0.00, "benefit_pct_of_expense")

    validate_error(
        api.finalize_report(report["id"], C.AUDITED_RATIO, headers=COMPLIANCE),
        ApiErrorId.REPORT_EMPTY,
    )
    final = validate_success(api.get_report(report["id"]))
    assert final["status"] == ReportStatus.OPEN
    assert final["valuation_basis"] == ValuationBasis.PROVISIONAL
    assert_close(final["cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "cost_to_charge_ratio")
