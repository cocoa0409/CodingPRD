"""Suppression cascades, the empty-pool capability limit, batch-sequence
monotonicity, and the RBAC denials."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    create_merchant_in_state,
    create_and_accept_merchant,
    create_and_activate_merchant,
    create_active_cardmember,
    create_offer,
    create_redemption_pool,
    submit_offer_review,
    request_offer_consent,
    capture_settlement,
    finalize_batch,
    mark_merchant_dormant,
    suppress_merchant,
    archive_merchant,
    get_success_data,
    set_member_spend,
    get_settlement,
    get_offer,
    get_merchant,
    set_clock,
    TEST_USERS,
)
from test_helpers.fixtures import (
    ACQ,
    SETTLE,
    COMPLIANCE,
    STEWARD,
    get_offer_pool,
    setup_live_offer_with_pool,
    make_merchant_headers,
    make_cardmember_headers,
)


# ═══ Difficulty: depth-2 suppression cascade ═════════════

def test_suppressing_an_active_merchant_reverses_its_captured_settlements(api):
    """PRD §3.2: "and where the merchant was `ACTIVE`, all its settlements that
    are `CAPTURED` or `IN_FUNDING` are moved to `REVERSED`."

    Design: Difficulty/transitive_cascade/payment_reversal_cascade_depth2
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"], merchant_name="Cascade Merchant 2")
    settlement = capture_settlement(
        merchant["id"], settlement_cycle=1, gross_volume_cents=500000, refund_volume_cents=0)
    assert get_settlement(settlement["id"])["settlement_status"] == "CAPTURED"

    suppressed = get_success_data(suppress_merchant(merchant["id"]))
    assert suppressed["acceptance_status"] == "SUPPRESSED"

    after = get_settlement(settlement["id"])
    assert after["settlement_status"] == "REVERSED", (
        "the suppression cascade reverses the merchant's in-flight settlements")


def test_suppression_reversal_clears_the_sealed_funding_figures(api):
    """PRD §3.3: "Suppression while a settlement is `CAPTURED` or `IN_FUNDING`
    reverses it outright, clearing the same three sealed figures."

    Design: Difficulty/transitive_cascade/payment_reversal_cascade_depth2
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"], merchant_name="Cascade Merchant 2")
    settlement = capture_settlement(
        merchant["id"], settlement_cycle=1, gross_volume_cents=500000, refund_volume_cents=0)
    suppress_merchant(merchant["id"])

    after = get_settlement(settlement["id"])
    assert after["net_funding_cents"] == 0
    assert after["final_discount_fee_cents"] == 0
    assert after["final_reserve_withholding_cents"] == 0


# ═══ Difficulty: depth-3 dispute cascade ═════════════════

def test_lost_dispute_advances_the_separate_representment_axis(api):
    """PRD §3.7: "A `LOST` dispute whose stage is `NONE` advances to
    `FIRST_ROUND` and the network opens a re-presentment round against the
    merchant"

    Design: Difficulty/transitive_cascade/dispute_loss_cascade_depth3
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="Cascade Merchant")
    member = create_active_cardmember()
    from test_helpers import open_dispute, respond_to_dispute, resolve_dispute
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=100000)
    respond_to_dispute(dispute, merchant["id"])
    resolved = resolve_dispute(dispute["id"], "LOST")

    assert resolved["dispute_status"] == "LOST"
    assert resolved["representment_stage"] == "FIRST_ROUND", (
        "a first-round loss opens the re-presentment round")


def test_a_lost_dispute_is_terminal_and_rejects_a_second_resolution(api):
    """PRD §3.7: "Resolution against the merchant on the `MERCHANT_RESPONDED`
    branch produces the terminal `LOST` state"

    Design: Difficulty/transitive_cascade/dispute_loss_cascade_depth3
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="Cascade Merchant")
    member = create_active_cardmember()
    from test_helpers import open_dispute, respond_to_dispute, resolve_dispute
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=100000)
    respond_to_dispute(dispute, merchant["id"])
    resolve_dispute(dispute["id"], "LOST")

    res = api_client.resolve_dispute(
        dispute["id"], {"outcome": "LOST"},
        TEST_USERS["network_dispute_ops_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_lost_dispute_raises_the_final_merchants_chargeback_count(api):
    """PRD §3.7: "Every `LOST` outcome also raises the final merchant's rolling
    chargeback count by one and lowers its `unresolved_chargeback_count` by one."

    Design: Difficulty/transitive_cascade/dispute_loss_cascade_depth3
    """
    set_clock()
    from test_helpers import open_dispute, respond_to_dispute, resolve_dispute, get_merchant_risk_state
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="Cascade Merchant")
    member = create_active_cardmember()
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=100000)
    before = get_merchant_risk_state(merchant["id"])["unresolved_chargeback_count"]

    respond_to_dispute(dispute, merchant["id"])
    resolve_dispute(dispute["id"], "LOST")

    after = get_merchant_risk_state(merchant["id"])
    assert after["rolling_chargeback_count"] == 1
    assert after["unresolved_chargeback_count"] == before - 1


# ═══ Difficulty: capability limit beats privacy quorum ═══

def test_an_unfunded_pool_blocks_acceptance_before_the_privacy_check(api):
    """PRD §3.5: "an approval that would consume a pool which does not exist, or
    whose `balance_cents` cannot cover the approved backing, is refused with
    `ERR_POOL_INSUFFICIENT_RESERVE` (HTTP 402)."
    PRD §2.10: "Fifth, consuming a redemption pool that does not exist or whose
    balance cannot cover the redemption yields `ERR_POOL_INSUFFICIENT_RESERVE`
    (402)."

    Design: Difficulty/priority_pair_validation_conflict/pool_fiscal_check_beats_privacy_quorum
    """
    set_clock()
    # The pool draw happens at approval, not at acceptance: acceptance alone is
    # a recorded intent and moves no pool money (PRD §3.5).
    _, merchant, member, offer, _ = setup_live_offer_with_pool(
        merchant_state="ACTIVE", pool_initial_funded_cents=0)
    acceptance = get_success_data(api_client.accept_offer(
        offer["id"],
        {"cardmember_id": member["id"], "trigger_amount_cents": 100000},
        make_cardmember_headers(member["id"])))

    # Empty pool: the capability limit refuses the draw.
    res = api_client.approve_offer_acceptance(acceptance["id"], STEWARD)
    error_data = validate_error(
        res, ApiErrorId.ERR_POOL_INSUFFICIENT_RESERVE.value, expected_status=402)
    assert error_data["error_id"] != ApiErrorId.ERR_PRIVACY_VIOLATION.value
    assert error_data["error_id"] != ApiErrorId.ERR_INVALID_STATE.value


def test_an_empty_pool_rejects_acceptance_without_surfacing_member_spend(api):
    """PRD §2.10: "Fifth, consuming a redemption pool that does not exist or
    whose balance cannot cover the redemption yields
    `ERR_POOL_INSUFFICIENT_RESERVE` (402)."

    Design: Difficulty/priority_pair_validation_conflict/pool_fiscal_check_beats_privacy_quorum
    """
    set_clock()
    _, merchant, member, offer, _ = setup_live_offer_with_pool(
        merchant_state="ACTIVE", pool_initial_funded_cents=0)
    acceptance = get_success_data(api_client.accept_offer(
        offer["id"],
        {"cardmember_id": member["id"], "trigger_amount_cents": 100000},
        make_cardmember_headers(member["id"])))

    res = api_client.approve_offer_acceptance(acceptance["id"], STEWARD)
    validate_error(res, ApiErrorId.ERR_POOL_INSUFFICIENT_RESERVE.value, expected_status=402)
    # The refusal leaves the redemption pending and no reserve consumed.
    assert get_success_data(
        api_client.get_offer_acceptance(acceptance["id"], STEWARD)
    )["acceptance_status"] == "PENDING"
    assert get_offer_pool(offer["id"])["consumed_total_cents"] == 0


# ═══ Difficulty: activation capability limit vs state ════

def test_a_suppression_flagged_dormant_merchant_cannot_be_activated(api):
    """PRD §3.1: "Activation moves `ACCEPTED` to `ACTIVE` and requires that the
    merchant be `ACCEPTED` and that its `suppression_flag` be false"
    PRD §2.10: "Seventh, a merchant that has crossed the unresolved-chargeback-count
    ceiling `UNRESOLVED_CB_CEILING` or the chargeback-ratio ceiling yields
    `ERR_MERCHANT_RISK_SUPPRESSED` (409) on activation, suppression, and
    settlement capture."

    Design: Difficulty/priority_pair_validation_conflict/activation_risk_flag_beats_invalid_state
    """
    set_clock()
    from test_helpers import open_dispute, get_merchant_risk_state
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="Priority Merchant")
    mark_merchant_dormant(merchant)
    member = create_active_cardmember()
    open_dispute(member["id"], merchant["id"], amount_cents=100000)
    open_dispute(member["id"], merchant["id"], amount_cents=100000)

    res = api_client.activate_merchant(merchant["id"], ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_activation_of_a_dormant_outlet_is_rejected_even_without_open_chargebacks(api):
    """PRD §3.1: "Activation moves `ACCEPTED` to `ACTIVE` and requires that the
    merchant be `ACCEPTED`"

    Design: Difficulty/priority_pair_validation_conflict/activation_risk_flag_beats_invalid_state
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="Priority Merchant 1b")
    dormant = mark_merchant_dormant(merchant)
    assert dormant["acceptance_status"] == "DORMANT"

    res = api_client.activate_merchant(merchant["id"], ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ═══ Corner: batch sequence monotonicity ═════════════════

def test_finalizing_a_batch_at_or_below_the_last_finalized_sequence_fails(api):
    """PRD §2.10: "Ninth, a funding batch finalized at or below the merchant's
    highest already-finalized batch sequence yields `ERR_BATCH_SEQ_NOT_MONOTONE`
    (409)."

    Design: Corner/validations/settlement_finalize_non_monotone_batch_returns_sequence_error
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"], merchant_name="Validation Merchant 2")
    capture_settlement(merchant["id"], settlement_cycle=1, gross_volume_cents=500000,
                       refund_volume_cents=0)
    capture_settlement(merchant["id"], settlement_cycle=2, gross_volume_cents=500000,
                       refund_volume_cents=0)
    finalize_batch(merchant["id"], 2)

    res = api_client.finalize_funding_batch(merchant["id"], 1, SETTLE)
    validate_error(res, ApiErrorId.ERR_BATCH_SEQ_NOT_MONOTONE.value, expected_status=409)


# ═══ Difficulty: exact boundary on finalize gates ════════

def test_finalize_gate_boundary_at_the_merchants_own_highest_sequence(api):
    """PRD §3.3: "a settlement is thus promoted only by the finalize of a
    strictly later batch ordinal, never by another settlement in its own batch."

    Design: Difficulty/cross_entity_state_dependency/settlement_funding_gated_by_merchant_acceptance_state
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"], merchant_name="Dependency Merchant 3")
    settlement = capture_settlement(
        merchant["id"], settlement_cycle=1, gross_volume_cents=500000, refund_volume_cents=0)
    dormant = mark_merchant_dormant(merchant)
    assert dormant["acceptance_status"] == "DORMANT"

    res = api_client.finalize_funding_batch(merchant["id"], 1, SETTLE)
    error_data = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert error_data["error_id"] != ApiErrorId.ERR_BATCH_SEQ_NOT_MONOTONE.value

    unfunded = get_settlement(settlement["id"])
    assert unfunded["settlement_status"] == "CAPTURED", "the settlement was not funded"
    assert unfunded["final_discount_fee_cents"] == 0
    assert unfunded["finalized_at_batch_seq"] == 0


def test_a_second_finalize_of_the_same_batch_is_not_monotone(api):
    """PRD §3.3: "Finalizing a batch is the transition that seals money."
    PRD §2.10: "Ninth, a funding batch finalized at or below the merchant's
    highest already-finalized batch sequence yields
    `ERR_BATCH_SEQ_NOT_MONOTONE` (409)."

    Design: Corner/validations/settlement_finalize_non_monotone_batch_returns_sequence_error
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"], merchant_name="Validation Merchant 2b")
    capture_settlement(merchant["id"], settlement_cycle=1, gross_volume_cents=500000,
                       refund_volume_cents=0)
    finalize_batch(merchant["id"], 1)

    res = api_client.finalize_funding_batch(merchant["id"], 1, SETTLE)
    validate_error(res, ApiErrorId.ERR_BATCH_SEQ_NOT_MONOTONE.value, expected_status=409)


# ═══ Corner: RBAC denials ════════════════════════════════

def test_the_settlement_operator_cannot_suppress_a_merchant(api):
    """PRD §2.1: "Authorization is a segregation-of-duties model: the role that
    onboards a merchant is not the role that suppresses it, and the role that
    authors an offer is not the role that consents to it. Presenting an
    authenticated role that is not permitted for the operation is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/settlement_operator_cannot_suppress_a_merchant
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], merchant_name="RBAC Merchant 1")

    res = api_client.suppress_merchant(merchant["id"], SETTLE)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert get_merchant(merchant["id"])["acceptance_status"] == "PROSPECT"


def test_a_merchant_cannot_read_another_merchants_settlement(api):
    """PRD §2.1: "A merchant that authenticated successfully but is addressing a
    resource belonging to a different merchant receives `ERR_FORBIDDEN`, not a
    not-found error."

    Design: Corner/rbac/merchant_cannot_read_another_merchants_settlement
    """
    set_clock()
    category = create_industry_category()
    merchant_a = create_and_activate_merchant(category["id"], merchant_name="RBAC Merchant 2")
    merchant_b = create_and_activate_merchant(category["id"], merchant_name="RBAC Merchant 3")
    settlement = capture_settlement(
        merchant_a["id"], settlement_cycle=1, gross_volume_cents=500000, refund_volume_cents=0)

    res = api_client.get_settlement(
        settlement["id"], make_merchant_headers(merchant_b["id"]))
    error_data = validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert "gross_volume_cents" not in error_data


def test_the_dispute_operator_cannot_respond_as_a_merchant(api):
    """PRD §2.1: "Authorization is a segregation-of-duties model: the role that
    onboards a merchant is not the role that suppresses it, and the role that
    authors an offer is not the role that consents to it. Presenting an
    authenticated role that is not permitted for the operation is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/dispute_operator_cannot_respond_as_a_merchant
    """
    set_clock()
    from test_helpers import open_dispute
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"], merchant_name="RBAC Merchant 4")
    member = create_active_cardmember()
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=100000)

    res = api_client.respond_to_dispute(
        dispute["id"], TEST_USERS["network_dispute_ops_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    from test_helpers import get_dispute
    assert get_dispute(dispute["id"])["dispute_status"] == "OPEN"


# ═══ Corner: archive already-terminal ════════════════════

def test_archiving_an_already_suppressed_merchant_is_already_terminal(api):
    """PRD §3.2: "A suppression attempted against a merchant already `SUPPRESSED`
    is refused with `ERR_SUPPRESS_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/errors/archive_already_suppressed_merchant_returns_already_terminal
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], merchant_name="Error Merchant")
    archive_merchant(merchant["id"])

    res = api_client.archive_merchant(merchant["id"], COMPLIANCE)
    validate_error(
        res, ApiErrorId.ERR_SUPPRESS_ALREADY_TERMINAL.value, expected_status=409)