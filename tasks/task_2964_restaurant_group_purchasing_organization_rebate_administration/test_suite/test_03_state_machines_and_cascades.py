"""Non-linear state machines and transitive cascades.

Two families of behaviour live here, each translated from one design instance:

  * ``non_linear_state_machine`` — a PurchaseBatch carrying two parallel state
    dimensions that advance independently but couple on rollback, and a dispute
    whose evidence loop returns an accrual to exactly ``accrual_status_before``.
  * ``transitive_cascade`` — the four-hop ledger/posture cascade of an upheld
    dispute, and the four-hop delisting cascade of a computed DEAL_LOST verdict.

Every precondition is built through the API because the database is empty
before each test; nothing here is module-level state.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ANALYST_1, ARBITER_1, ApiErrorId, api_client
from test_helpers import constants as C  # noqa: F401  (canonical literals)
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import (
    AccrualBlockReason,
    AccrualStatus,
    AuditStatus,
    DealStatus,
    DisputeDecision,
    DisputeReasonCode,
    DisputeStatus,
    ItemStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    RateType,
    ReconciliationPosture,
    ReversalReason,
    ComplianceResult,
    make_analyst_headers,
    make_arbiter_headers,
    make_gpo_admin_headers,
)

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers()          # analyst-01 accrues and validates
ARBITER = make_arbiter_headers()          # arbiter-01 decides, never accrued

# --------------------------------------------------------------------------
# Pre-computed expectations, copied from the design instances verbatim.
# --------------------------------------------------------------------------

# The canonical June feed: 30 cases on base 8533 and 40 cases on base 8540,
# both invoiced at 9140, so the markup audit finds overbilling.
TOTAL_CASES = 70
LINE_A_OVERBILLED_CENTS = 300
LINE_B_OVERBILLED_CENTS = 80
BATCH_OVERBILLED_CENTS = 380

# TIERED_VOLUME 0/50/200 ladder under the accrue-time MARGINAL_BATCH variant.
TIERED_GROSS_A_CENTS = 3600
TIERED_GROSS_B_CENTS = 6000

# PER_CASE 150 cents/case split by the ELITE waterfall (fee 300 bps).
FLAT_MEMBER_SHARE_A_CENTS = 3274
FLAT_MEMBER_SHARE_B_CENTS = 4365
LEDGER_MEMBER_SHARE_CENTS = 7639
LEDGER_RETENTION_CENTS = 2546
LEDGER_ADMIN_FEE_CENTS = 315
REVERSED_LEDGER_MEMBER_SHARE_CENTS = 4365
REVERSED_LEDGER_RETENTION_CENTS = 1455
REVERSED_LEDGER_ADMIN_FEE_CENTS = 180

# The June claim that reconciles at variance 0 bps.
CLAIMED_UNITS = 70
CLAIMED_AMOUNT_CENTS = 10500

EVIDENCE_NOTE_ROUND_1 = "Distributor invoice PDF attached, round 1"
EVIDENCE_NOTE_ROUND_2 = "Corrected case counts, round 2"
REJECT_NOTE = "Rate card applied correctly for the invoice date"
UPHOLD_NOTE = "Distributor restated 30 cases to 24; accrual withdrawn"

# The closed compliance window that clears required_purchase_window_days 60.
REVIEW_WINDOW_START = "2026-04-01"
REVIEW_WINDOW_END = "2026-05-31"
REVIEW_WINDOW_DAYS = 61

POSTURE_LIMIT_ONE = {"reversal_posture_limit": 1}


# --------------------------------------------------------------------------
# Local composites. Each performs one phase and returns, so a test can
# interpose its own trigger call without a bundled helper stepping past a
# state gate it needs to observe.
# --------------------------------------------------------------------------

def _overbilled_tiered_june_batch() -> dict:
    """A June feed at (NORMALIZED, AUDIT_OVERBILLED) on the tiered ladder."""
    ctx = fx.setup_program(RateType.TIERED_VOLUME.value, tier_overrides=POSTURE_LIMIT_ONE)
    fx.ingest_june_feed(ctx)
    fx.normalize_june_feed(ctx)
    fx.audited_june_feed(ctx)
    batch = ctx["batch"]
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert batch["overbilled_cents"] == BATCH_OVERBILLED_CENTS
    return ctx


def _validated_accrual_under_evidence_cycle() -> dict:
    """The June feed accrued and reconciled, accrual A validated by analyst-01,
    then a dispute cycled OPEN -> EVIDENCE_REQUESTED -> OPEN twice."""
    ctx = fx.setup_june_accrued(tier_overrides=POSTURE_LIMIT_ONE)
    fx.reconciled_claim_for_june(ctx, CLAIMED_UNITS, CLAIMED_AMOUNT_CENTS)
    ctx["accrual_a"] = fx.validate_accrual(ctx["accrual_a"]["id"], ctx["claim_id"])
    assert ctx["accrual_a"]["status"] == AccrualStatus.VALIDATED.value
    assert ctx["accrual_a"]["validated_by_user_id"] == ANALYST_1
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.RATE_MISMATCH.value,
        disputed_amount_cents=FLAT_MEMBER_SHARE_A_CENTS,
        claim_id=ctx["claim_id"],
    )
    accrual_id = ctx["accrual_a"]["id"]
    seen = [fx.read_accrual(accrual_id)["status"]]
    dispute_states = [ctx["dispute"]["status"]]
    for note in (EVIDENCE_NOTE_ROUND_1, EVIDENCE_NOTE_ROUND_2):
        dispute_states.append(fx.request_evidence(ctx["dispute_id"])["status"])
        seen.append(fx.read_accrual(accrual_id)["status"])
        dispute_states.append(
            fx.submit_evidence(ctx["dispute_id"], ctx["member_id"], note)["status"]
        )
        seen.append(fx.read_accrual(accrual_id)["status"])
    ctx["accrual_statuses_during_cycle"] = seen
    ctx["dispute_states"] = dispute_states
    ctx["dispute"] = fx.read_dispute(ctx["dispute_id"])
    return ctx


def _open_dispute_on_accrued_june(reason_code: str) -> dict:
    """The accrued June feed with an OPEN dispute on the 30-case accrual, filed
    by the member for the accrual's full member share."""
    ctx = fx.setup_june_accrued(tier_overrides=POSTURE_LIMIT_ONE)
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        reason_code,
        disputed_amount_cents=FLAT_MEMBER_SHARE_A_CENTS,
    )
    assert ctx["dispute"]["status"] == DisputeStatus.OPEN.value
    assert ctx["dispute"]["opened_by_user_id"] == ctx["member_id"]
    assert ctx["batch"]["accrued_by_user_id"] == ANALYST_1
    return ctx


def _normalized_june_batch_for_review() -> dict:
    """June feed NORMALIZED but deliberately not accrued: hop 3b only touches
    lines whose batch sits at normalization_status NORMALIZED."""
    ctx = fx.setup_june_normalized(
        RateType.TIERED_VOLUME.value, tier_overrides=POSTURE_LIMIT_ONE
    )
    batch = ctx["batch"]
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["matched_cases"] == TOTAL_CASES
    assert batch["unmatched_cases"] == 0
    return ctx


def _run_review(ctx: dict):
    """Run the compliance review that computes the DEAL_LOST verdict."""
    return api_client.create_compliance_review(
        F.compliance_review_payload(
            ctx["member_id"], ctx["deal_id"], REVIEW_WINDOW_START, REVIEW_WINDOW_END
        ),
        ANALYST,
    )


# ==========================================================================
# non_linear_state_machine — purchase_batch_two_independent_dimensions_interleaved
# ==========================================================================

def test_accrue_advances_normalization_without_disturbing_the_audit_dimension():
    """Accruing a batch already sitting at AUDIT_OVERBILLED advances only the
    normalization dimension: the audit verdict, the batch total and both lines'
    overbilled figures survive the call untouched.
    PRD: "Advancing one dimension never reads or writes the other, with two
    explicit exceptions stated where they arise: the markup audit requires the
    feed to have been normalized before it will run, and once the audit
    dimension has passed into recovery the normalization dimension can no longer
    be unwound."
    Design: Difficulty/non_linear_state_machine/purchase_batch_two_independent_dimensions_interleaved
    """
    ctx = _overbilled_tiered_june_batch()

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)

    batch = validate_success(response, 200)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert batch["overbilled_cents"] == BATCH_OVERBILLED_CENTS
    assert batch["matched_cases"] == TOTAL_CASES
    assert batch["total_cases_ingested"] == TOTAL_CASES
    assert batch["accrued_by_user_id"] == ANALYST_1

    line_a = fx.read_line(ctx["line_a"]["id"])
    line_b = fx.read_line(ctx["line_b"]["id"])
    assert line_a["overbilled_cents"] == LINE_A_OVERBILLED_CENTS
    assert line_b["overbilled_cents"] == LINE_B_OVERBILLED_CENTS

    # Accrual arithmetic never consulted audit_status.
    assert fx.accrual_for_line(line_a["id"])["gross_rebate_cents"] == TIERED_GROSS_A_CENTS
    assert fx.accrual_for_line(line_b["id"])["gross_rebate_cents"] == TIERED_GROSS_B_CENTS


def test_request_recovery_advances_audit_without_disturbing_normalization():
    """Opening the recovery demand on the accrued batch drives the audit
    dimension to RECOVERY_REQUESTED while normalization_status stays ACCRUED, so
    the row rests in a combined state no single ladder can express.
    PRD: "A `RebateAnalyst` opens the demand, moving the batch
    `AUDIT_OVERBILLED → RECOVERY_REQUESTED` and incrementing the batch's
    `version` by 1"
    Design: Difficulty/non_linear_state_machine/purchase_batch_two_independent_dimensions_interleaved
    """
    ctx = _overbilled_tiered_june_batch()
    accrued = fx.accrue(ctx["batch_id"])
    assert accrued["normalization_status"] == NormalizationStatus.ACCRUED.value

    response = api_client.request_recovery(ctx["batch_id"], ANALYST)

    batch = validate_success(response, 200)
    assert batch["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["overbilled_cents"] == BATCH_OVERBILLED_CENTS
    assert batch["matched_cases"] == TOTAL_CASES
    assert batch["total_cases_ingested"] == TOTAL_CASES
    assert batch["version"] == accrued["version"] + 1


def test_renormalize_is_refused_once_the_audit_dimension_reached_recovery():
    """The two dimensions are independent going forward but coupled on
    rollback: with the audit dimension at RECOVERY_REQUESTED, unwinding the
    normalization dimension is refused.
    PRD: "Renormalization is refused with `ERR_INVALID_STATE` when the batch's
    `audit_status` has already reached `RECOVERY_REQUESTED`, `RECOVERED` or
    `WRITTEN_OFF`"
    Design: Difficulty/non_linear_state_machine/purchase_batch_two_independent_dimensions_interleaved
    """
    ctx = _overbilled_tiered_june_batch()
    fx.accrue(ctx["batch_id"])
    demanded = fx.request_recovery(ctx["batch_id"])
    assert demanded["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value

    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    unchanged = fx.read_batch(ctx["batch_id"])
    assert unchanged["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert unchanged["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert unchanged["matched_cases"] == TOTAL_CASES


# ==========================================================================
# non_linear_state_machine — dispute_evidence_cycle_restores_validated_accrual
# ==========================================================================

def test_reject_after_two_evidence_rounds_restores_accrual_status_before_exactly():
    """Two nested evidence cycles leave evidence_round_count at 2 with the
    accrual parked in DISPUTED throughout, and the REJECT returns it to exactly
    accrual_status_before == VALIDATED with no money movement anywhere.
    PRD: "The dispute moves `OPEN → REJECTED` and the accrual returns from
    `DISPUTED` to exactly the status recorded in `accrual_status_before` —
    `DISPUTED → ACCRUED`, `DISPUTED → VALIDATED` or `DISPUTED → FLAGGED` as the
    case may be — with the accrual's `validated_by_user_id` preserved where it
    had one. Not one money field and not one counter anywhere in the system
    changes."
    Design: Difficulty/non_linear_state_machine/dispute_evidence_cycle_restores_validated_accrual
    """
    ctx = _validated_accrual_under_evidence_cycle()
    # accrual_status_before was captured at dispute creation, not at decision time.
    assert ctx["dispute"]["accrual_status_before"] == AccrualStatus.VALIDATED.value
    assert ctx["dispute"]["evidence_round_count"] == 2
    assert ctx["dispute"]["status"] == DisputeStatus.OPEN.value
    assert ctx["dispute_states"] == [
        DisputeStatus.OPEN.value,
        DisputeStatus.EVIDENCE_REQUESTED.value,
        DisputeStatus.OPEN.value,
        DisputeStatus.EVIDENCE_REQUESTED.value,
        DisputeStatus.OPEN.value,
    ]
    # The accrual stayed DISPUTED on every intermediate read while it cycled.
    assert set(ctx["accrual_statuses_during_cycle"]) == {AccrualStatus.DISPUTED.value}

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.REJECT.value, "decision_note": REJECT_NOTE},
        ARBITER,
    )

    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.REJECTED.value
    assert dispute["decided_by_user_id"] == ARBITER_1
    assert dispute["decision_note"] == REJECT_NOTE

    accrual = fx.read_accrual(ctx["accrual_a"]["id"])
    assert accrual["status"] == AccrualStatus.VALIDATED.value
    assert accrual["validated_by_user_id"] == ANALYST_1
    assert accrual["member_share_cents"] == FLAT_MEMBER_SHARE_A_CENTS
    assert accrual["reversal_reason"] == ReversalReason.NONE.value

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == LEDGER_MEMBER_SHARE_CENTS
    assert member["dispute_reversal_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False


def test_second_decide_on_a_rejected_dispute_is_refused_as_invalid_state():
    """REJECTED is terminal, so the arbiter cannot rule twice on the same
    dispute even though the accrual it restored is contestable again.
    PRD: "Both `UPHELD` and `REJECTED` are terminal dispute states: a decided
    dispute is never reopened"
    Design: Difficulty/non_linear_state_machine/dispute_evidence_cycle_restores_validated_accrual
    """
    ctx = _validated_accrual_under_evidence_cycle()
    decided = fx.decide_dispute(
        ctx["dispute_id"], DisputeDecision.REJECT.value, REJECT_NOTE
    )
    assert decided["status"] == DisputeStatus.REJECTED.value

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.REJECT.value, "decision_note": REJECT_NOTE},
        ARBITER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    dispute = fx.read_dispute(ctx["dispute_id"])
    assert dispute["status"] == DisputeStatus.REJECTED.value
    assert dispute["evidence_round_count"] == 2
    assert fx.read_accrual(ctx["accrual_a"]["id"])["status"] == AccrualStatus.VALIDATED.value


# ==========================================================================
# transitive_cascade — dispute_upheld_four_hop_ledger_and_posture_cascade
# ==========================================================================

def test_upheld_dispute_reverses_the_accrual_and_retracts_the_exact_components():
    """Hops 1 to 3 of the upheld cascade: the dispute is UPHELD, the disputed
    accrual is REVERSED as DISPUTE_UPHELD, and the member's three counters drop
    by that accrual's exact stored components while the sibling accrual and the
    reversed accrual's own money fields stay as they were.
    PRD: "the member's `accrued_member_share_cents` is decremented by that
    accrual's stored `member_share_cents`, its `attributed_gpo_retention_cents`
    by the accrual's `gpo_retention_cents` and its `attributed_admin_fee_cents`
    by the accrual's `admin_fee_cents`, each by the exact stored component rather
    than a recomputed one, and the member's `dispute_reversal_count` is
    incremented by 1."
    Design: Difficulty/transitive_cascade/dispute_upheld_four_hop_ledger_and_posture_cascade
    """
    ctx = _open_dispute_on_accrued_june(DisputeReasonCode.UNITS_MISMATCH.value)
    before = fx.read_member(ctx["member_id"])
    assert before["accrued_member_share_cents"] == LEDGER_MEMBER_SHARE_CENTS
    assert before["attributed_gpo_retention_cents"] == LEDGER_RETENTION_CENTS
    assert before["attributed_admin_fee_cents"] == LEDGER_ADMIN_FEE_CENTS

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.UPHOLD.value, "decision_note": UPHOLD_NOTE},
        ARBITER,
    )

    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.UPHELD.value
    assert dispute["decided_by_user_id"] == ARBITER_1
    assert dispute["decision_note"] == UPHOLD_NOTE

    accrual_a = fx.read_accrual(ctx["accrual_a"]["id"])
    assert accrual_a["status"] == AccrualStatus.REVERSED.value
    assert accrual_a["reversal_reason"] == ReversalReason.DISPUTE_UPHELD.value
    # Reversal moves state and member counters; it does not zero the accrual's
    # own money fields.
    assert accrual_a["member_share_cents"] == FLAT_MEMBER_SHARE_A_CENTS

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == REVERSED_LEDGER_MEMBER_SHARE_CENTS
    assert member["attributed_gpo_retention_cents"] == REVERSED_LEDGER_RETENTION_CENTS
    assert member["attributed_admin_fee_cents"] == REVERSED_LEDGER_ADMIN_FEE_CENTS
    assert member["dispute_reversal_count"] == 1

    # The cascade is scoped to the disputed accrual.
    accrual_b = fx.read_accrual(ctx["accrual_b"]["id"])
    assert accrual_b["status"] == AccrualStatus.ACCRUED.value
    assert accrual_b["member_share_cents"] == FLAT_MEMBER_SHARE_B_CENTS


def test_upheld_dispute_hop_four_restricts_the_member_and_holds_its_accrued_batch():
    """Hop 4 is threshold-gated: with reversal_posture_limit 1 the single
    reversal restricts the member, holds its payouts and re-enters the batch,
    whose own payout_hold flips because it is ACCRUED and holds the member's line.
    PRD: "the member's `reconciliation_posture` moves `CLEAR → RESTRICTED`, its
    `payout_hold` is set to true, and every purchase batch that holds at least
    one purchase line of that member and whose `normalization_status` is
    `ACCRUED` has its own `payout_hold` set to true with its `version`
    incremented by 1."
    Design: Difficulty/transitive_cascade/dispute_upheld_four_hop_ledger_and_posture_cascade
    """
    ctx = _open_dispute_on_accrued_june(DisputeReasonCode.UNITS_MISMATCH.value)
    assert ctx["tier"]["reversal_posture_limit"] == 1
    batch_before = fx.read_batch(ctx["batch_id"])
    assert batch_before["payout_hold"] is False

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.UPHOLD.value, "decision_note": UPHOLD_NOTE},
        ARBITER,
    )

    validate_success(response, 200)
    member = fx.read_member(ctx["member_id"])
    assert member["dispute_reversal_count"] == 1
    assert member["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value
    assert member["payout_hold"] is True
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["payout_hold"] is True
    assert batch["version"] == batch_before["version"] + 1


# ==========================================================================
# transitive_cascade — deal_loss_four_hop_delisting_cascade_into_batch_recount
# ==========================================================================

def test_deal_loss_verdict_is_computed_and_costs_the_deal_but_not_the_member():
    """A 61-day closed window with no deal-wide contracted spend returns
    DEAL_LOST rather than BREACH, so hop 1 moves the deal to LOST and flags the
    review while the member keeps its standing.
    PRD: "`DEAL_LOST` is the verdict when `deal_wide_contracted_spend_cents` is
    0, `window_days` is at least the deal's `required_purchase_window_days`, and
    the deal's `status` is `ACTIVE`." — and a breach, which this is not, is the
    only verdict that "costs the member its standing: it moves
    `ACTIVE → SUSPENDED`, its `payout_hold` is set to true".
    Design: Difficulty/transitive_cascade/deal_loss_four_hop_delisting_cascade_into_batch_recount
    """
    ctx = _normalized_june_batch_for_review()
    assert ctx["deal"]["required_purchase_window_days"] == 60

    response = _run_review(ctx)

    review = validate_success(response, 201)
    assert review["window_days"] == REVIEW_WINDOW_DAYS
    assert review["contracted_spend_cents"] == 0
    assert review["deal_wide_contracted_spend_cents"] == 0
    assert review["purchase_ratio_bps"] == 0
    assert review["result"] == ComplianceResult.DEAL_LOST.value
    assert review["triggered_deal_loss"] is True

    assert fx.read_deal(ctx["deal_id"])["status"] == DealStatus.LOST.value

    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert member["payout_hold"] is False


def test_deal_loss_delists_items_expires_cards_excludes_lines_and_recounts_cases():
    """Hops 2 to 4 fork out of the lost deal: the item is DELISTED, its card
    EXPIRED, both matched June lines EXCLUDED as ITEM_DELISTED, and the batch
    recounts its cases while total_cases_ingested is left alone.
    PRD: "every purchase line whose resolved item is one of the newly delisted
    ones and whose batch has `normalization_status` of `NORMALIZED` moves
    `MATCHED → EXCLUDED`, with `accrual_block_reason` set to `ITEM_DELISTED` and
    `contracted_item_id` cleared to null" — then "each affected purchase batch
    recomputes its `matched_cases` and `unmatched_cases`, while
    `total_cases_ingested` is left exactly as it was."
    Design: Difficulty/transitive_cascade/deal_loss_four_hop_delisting_cascade_into_batch_recount
    """
    ctx = _normalized_june_batch_for_review()
    review = validate_success(_run_review(ctx), 201)
    assert review["result"] == ComplianceResult.DEAL_LOST.value

    # hop 2
    item = fx.read_item(ctx["item_id"])
    assert item["status"] == ItemStatus.DELISTED.value
    assert fx.read_deal(ctx["deal_id"])["contracted_item_count"] == 0

    # hop 3
    card = validate_success(api_client.get_rate_card(ctx["card"]["id"], ADMIN), 200)
    assert card["status"] == RateCardStatus.EXPIRED.value
    assert item["approved_rate_card_count"] == 0

    # hop 3b
    for line_key in ("line_a", "line_b"):
        line = fx.read_line(ctx[line_key]["id"])
        assert line["match_status"] == MatchStatus.EXCLUDED.value
        assert line["accrual_block_reason"] == AccrualBlockReason.ITEM_DELISTED.value
        assert line["contracted_item_id"] is None

    # hop 4
    batch = fx.read_batch(ctx["batch_id"])
    assert batch["matched_cases"] == 0
    assert batch["unmatched_cases"] == TOTAL_CASES
    assert batch["total_cases_ingested"] == TOTAL_CASES


def test_accrue_after_the_delisting_cascade_has_nothing_accruable_left():
    """The cascade left the normalized batch without a single MATCHED line, so
    the accrual run is refused rather than advancing the batch's state.
    PRD: "a normalized batch in which not one `MATCHED` line resolves an approved
    rate card for its own `invoice_date` is refused with
    `ERR_NO_ACCRUABLE_LINES`, because an accrual run that would produce nothing
    should not advance the batch's state."
    Design: Difficulty/transitive_cascade/deal_loss_four_hop_delisting_cascade_into_batch_recount
    """
    ctx = _normalized_june_batch_for_review()
    review = validate_success(_run_review(ctx), 201)
    assert review["result"] == ComplianceResult.DEAL_LOST.value

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_NO_ACCRUABLE_LINES, 422)
    batch = fx.read_batch(ctx["batch_id"])
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["accrued_by_user_id"] is None
    assert fx.list_accruals() == []
