"""Multi-row state-machine cascades: termination, period close, dispute reject
and the logical-clock sweep.

Four corner instances live here, each one asserted twice or three times so the
primary transition and its dependent rows are checked separately:

  * terminating a member revokes only its ACTIVE letters and recomputes each
    distributor's own counter,
  * closing a period pays only the VALIDATED accrual, rebases both, and
    rewrites the member's frozen admin-fee snapshot,
  * rejecting a dispute restores the accrual to its captured prior status and
    moves no money at all, and
  * one clock advance expires an authorization letter on instant semantics and
    two rate cards on calendar-date semantics.

The database is empty before every test, so every precondition below is built
through API calls and nothing is shared between tests.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST_1,
    ANALYST_2,
    ARBITER_1,
    AccrualBasis,
    AccrualStatus,
    ApiErrorId,
    ClaimStatus,
    CountersignDecision,
    DealStatus,
    DisputeDecision,
    DisputeReasonCode,
    DisputeStatus,
    LetterScope,
    LetterStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    RateType,
    ReconciliationPosture,
    ReversalReason,
    api_client,
    assert_accrual,
    assert_authorization_letter,
    assert_instants_equal,
    assert_member,
    assert_member_ledger,
    assert_split,
    make_analyst_headers,
    make_arbiter_headers,
    make_gpo_admin_headers,
)
from test_helpers import constants as C
from test_helpers import fixtures as fx

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers(ANALYST_1)
ANALYST_2_HEADERS = make_analyst_headers(ANALYST_2)
ARBITER = make_arbiter_headers(ARBITER_1)

WIDE = {"limit": C.MAX_LIMIT}

# --- instance literals: the second distributor of the termination cascade ----
SECOND_DISTRIBUTOR_NAME = "Sysco Northeast"
SECOND_DISTRIBUTOR_DBA_CODE = "SYSCO-02"
SECOND_DISTRIBUTOR_MARKUP_BPS = 600

# The third letter of the termination cascade: it merely touches the first
# letter's end, so it is accepted and then DECLINED into a terminal state.
DECLINED_LETTER_FROM = "2028-01-01T00:00:00.000Z"
DECLINED_LETTER_TO = "2029-01-01T00:00:00.000Z"

# --- instance literals: the canonical June claim ----------------------------
CLAIMED_UNITS = 70
CLAIMED_AMOUNT_CENTS = 10500

# --- instance literals: the June accrual split, pre-computed by the design --
ADMIN_FEE_BPS_APPLIED = 300
GROSS_A_CENTS = 4500
FEE_A_CENTS = 135
NET_A_CENTS = 4365
SHARE_A_CENTS = 3274
RETENTION_A_CENTS = 1091

GROSS_B_CENTS = 6000
FEE_B_CENTS = 180
NET_B_CENTS = 5820
SHARE_B_CENTS = 4365
RETENTION_B_CENTS = 1455

LEDGER_SHARE_CENTS = 7639
LEDGER_RETENTION_CENTS = 2546
LEDGER_FEE_CENTS = 315
YTD_NET_SNAPSHOT_CENTS = 10185

REJECT_DECISION_NOTE = "Rate card applied correctly at 150 cents per case"

# --- instance literals: the clock-advance sweep -----------------------------
LETTER_TO_AT_ADVANCE = "2026-09-01T00:00:00.000Z"
CLOCK_ADVANCED_TO = "2026-09-01T00:00:00.000Z"
CARD_FROM_DATED = "2026-01-01"
CARD_TO_DATED = "2026-08-31"
BRISKET_SKU = "PBC-BRISKET-WHOLE"
BRISKET_KEY = "BEEF-BRISKET-CS20"
BRISKET_PACK_SIZE = 20
BRISKET_BASELINE_UNIT_COST_CENTS = 14200
BRISKET_CONTRACT_UNIT_COST_CENTS = 13100
BRISKET_FLAT_RATE_CENTS_PER_CASE = 220


# ======================================================= local setup helpers ==

def _member_with_three_letters() -> dict:
    """Harbor Grill ACTIVE with two ACTIVE letters and one DECLINED letter.

    METRO-01 holds an ACTIVE letter and a later DECLINED one; SYSCO-02 holds
    the second ACTIVE letter, so each distributor's counter stands at 1 and the
    member's at 2.
    """
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    distributor_2 = fx.create_distributor(
        name=SECOND_DISTRIBUTOR_NAME,
        dba_code=SECOND_DISTRIBUTOR_DBA_CODE,
        contracted_markup_bps=SECOND_DISTRIBUTOR_MARKUP_BPS,
    )
    member = fx.create_member(tier["id"])

    loa1 = fx.submit_letter(member["id"], distributor["id"])
    loa1 = fx.countersign_letter(loa1["id"], distributor["id"])

    loa2 = fx.submit_letter(
        member["id"],
        distributor_2["id"],
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
    )
    loa2 = fx.countersign_letter(loa2["id"], distributor_2["id"])

    # Touching windows do not overlap, so this later letter is accepted and
    # then declined into a terminal state the cascade must leave alone.
    loa3 = fx.submit_letter(
        member["id"],
        distributor["id"],
        effective_from=DECLINED_LETTER_FROM,
        effective_to=DECLINED_LETTER_TO,
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
    )
    loa3 = fx.countersign_letter(
        loa3["id"], distributor["id"], decision=CountersignDecision.DECLINE.value
    )

    member = fx.activate_member(member["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "distributor_2": distributor_2,
        "member": member,
        "member_id": member["id"],
        "loa1": loa1,
        "loa2": loa2,
        "loa3": loa3,
    }


def _june_accrued_with_validated_accrual() -> dict:
    """The full June chain with a1 VALIDATED against a RECONCILED claim.

    PER_CASE 150 cents on the beef item, two lines of 30 and 40 cases accrued
    by analyst-01, a 70 unit / 10500 cent claim reconciled at variance 0, and
    accrual a1 validated by analyst-02 so the deciding arbiter later collides
    with nobody.
    """
    ctx = fx.setup_flat_program()
    fx.ingest_june_feed(ctx)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)

    # Read the deal version before the claim create advances it.
    ctx["deal_version_before_claim"] = fx.deal_version(ctx["deal_id"])
    fx.reconciled_claim_for_june(ctx, CLAIMED_UNITS, CLAIMED_AMOUNT_CENTS)

    ctx["accrual_a"] = fx.validate_accrual(
        ctx["accrual_a"]["id"], ctx["claim_id"], headers=ANALYST_2_HEADERS
    )
    ctx["accrual_b"] = fx.read_accrual(ctx["accrual_b"]["id"])
    ctx["member"] = fx.read_member(ctx["member_id"])
    return ctx


def _dated_cards_and_expiring_letter() -> dict:
    """A DRAFT deal with one APPROVED and one PROPOSED card, both dated to
    2026-08-31, plus an ACTIVE letter whose window ends at 2026-09-01T00:00Z."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])

    letter = fx.submit_letter(
        member["id"], distributor["id"], effective_to=LETTER_TO_AT_ADVANCE
    )
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])

    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card_1 = fx.create_card(
        item["id"],
        RateType.PER_CASE.value,
        effective_from=CARD_FROM_DATED,
        effective_to=CARD_TO_DATED,
    )
    card_1 = fx.approve_card(card_1["id"])

    item_2 = fx.create_item(
        deal["id"],
        manufacturer_sku=BRISKET_SKU,
        normalized_item_key=BRISKET_KEY,
        pack_size=BRISKET_PACK_SIZE,
        baseline_unit_cost_cents=BRISKET_BASELINE_UNIT_COST_CENTS,
        contract_unit_cost_cents=BRISKET_CONTRACT_UNIT_COST_CENTS,
    )
    card_2 = fx.create_card(
        item_2["id"],
        RateType.PER_CASE.value,
        flat_rate_cents_per_case=BRISKET_FLAT_RATE_CENTS_PER_CASE,
        effective_from=CARD_FROM_DATED,
        effective_to=CARD_TO_DATED,
    )
    return {
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "member": member,
        "member_id": member["id"],
        "letter": letter,
        "deal": deal,
        "deal_id": deal["id"],
        "item": item,
        "item_2": item_2,
        "card_1": card_1,
        "card_2": card_2,
    }


def _letters_of_member(member_id: str) -> list:
    """Every authorization letter of one member, read with a wide page."""
    params = dict(WIDE)
    params["member_id"] = member_id
    return validate_success(
        api_client.list_authorization_letters(ADMIN, params), 200
    )


# ===================================================================== 1 =====
# member_terminate_cascades_every_active_letter_to_revoked

def test_terminate_sets_terminated_and_holds_payout_and_revokes_active_letters():
    """Terminating the member is the primary transition, and hop 1 revokes the
    two ACTIVE letters while leaving the DECLINED one untouched.

    "It sets `enrollment_status` to `TERMINATED`, sets `payout_hold` to true,
    and runs a two-hop cascade. In hop 1, every authorization letter of that
    member whose `status` is `ACTIVE` moves `ACTIVE → REVOKED`."

    Design: Corner/state_machines/member_terminate_cascades_every_active_letter_to_revoked
    """
    ctx = _member_with_three_letters()

    # Before the trigger: two live letters, one per distributor.
    assert ctx["member"]["active_letter_count"] == 2
    assert fx.read_distributor(ctx["distributor"]["id"])["active_letter_count"] == 1
    assert fx.read_distributor(ctx["distributor_2"]["id"])["active_letter_count"] == 1

    response = api_client.terminate_member(ctx["member_id"], ADMIN)
    member = validate_success(response, 200)
    assert_member(member)
    assert member["enrollment_status"] == MemberEnrollmentStatus.TERMINATED.value
    assert member["payout_hold"] is True

    loa1 = validate_success(
        api_client.get_authorization_letter(ctx["loa1"]["id"], ADMIN), 200
    )
    loa2 = validate_success(
        api_client.get_authorization_letter(ctx["loa2"]["id"], ADMIN), 200
    )
    loa3 = validate_success(
        api_client.get_authorization_letter(ctx["loa3"]["id"], ADMIN), 200
    )
    for letter in (loa1, loa2, loa3):
        assert_authorization_letter(letter)
    assert loa1["status"] == LetterStatus.REVOKED.value
    assert loa2["status"] == LetterStatus.REVOKED.value
    # The cascade is scoped to ACTIVE letters, so the terminal one is untouched.
    assert loa3["status"] == LetterStatus.DECLINED.value


def test_terminate_recomputes_each_distributors_own_letter_counter():
    """Hop 2 is the dependent-row consequence: the member's counter and every
    distributor that lost a letter are recomputed separately, and exactly two
    letters of the member end up REVOKED.

    "In hop 2, caused by hop 1, the member's `active_letter_count` and the
    `active_letter_count` of each distributor that lost a letter are recomputed
    as the count of that side's letters whose `status` is `ACTIVE`."

    Design: Corner/state_machines/member_terminate_cascades_every_active_letter_to_revoked
    """
    ctx = _member_with_three_letters()

    validate_success(api_client.terminate_member(ctx["member_id"], ADMIN), 200)

    member = fx.read_member(ctx["member_id"])
    assert member["active_letter_count"] == 0
    # Each distributor was recomputed on its own, not as one shared total.
    assert fx.read_distributor(ctx["distributor"]["id"])["active_letter_count"] == 0
    assert fx.read_distributor(ctx["distributor_2"]["id"])["active_letter_count"] == 0

    letters = _letters_of_member(ctx["member_id"])
    revoked = [row for row in letters if row["status"] == LetterStatus.REVOKED.value]
    declined = [row for row in letters if row["status"] == LetterStatus.DECLINED.value]
    assert len(revoked) == 2, f"expected 2 REVOKED letters, got {len(revoked)}"
    assert len(declined) == 1, f"expected 1 DECLINED letter, got {len(declined)}"
    assert {row["id"] for row in revoked} == {ctx["loa1"]["id"], ctx["loa2"]["id"]}


# ===================================================================== 2 =====
# close_period_pays_validated_accruals_and_rewrites_the_snapshot

def test_close_period_pays_the_validated_accrual_and_stamps_the_blended_basis():
    """The primary transition: the VALIDATED June accrual moves to PAID, its
    basis is rebased to BLENDED_PERIOD with a zero final adjustment, and on a
    PER_CASE card not one cent of the split moves.

    "Every touched accrual whose `status` is `VALIDATED` and whose member has
    `payout_hold` false moves `VALIDATED → PAID`."

    Design: Corner/state_machines/close_period_pays_validated_accruals_and_rewrites_the_snapshot
    """
    ctx = _june_accrued_with_validated_accrual()
    deal_version_before = ctx["deal_version_before_claim"]

    # Before the trigger: the claim reconciled at variance 0 and a1 carries
    # analyst-02's validation while a2 is merely ACCRUED.
    claim = fx.read_claim(ctx["claim_id"])
    assert claim["status"] == ClaimStatus.RECONCILED.value
    assert claim["accrued_amount_cents"] == CLAIMED_AMOUNT_CENTS
    assert claim["variance_bps"] == 0
    assert ctx["accrual_a"]["status"] == AccrualStatus.VALIDATED.value
    assert ctx["accrual_a"]["validated_by_user_id"] == ANALYST_2
    assert ctx["accrual_a"]["basis"] == AccrualBasis.MARGINAL_BATCH.value
    assert ctx["accrual_b"]["status"] == AccrualStatus.ACCRUED.value

    response = api_client.close_period(
        ctx["deal_id"],
        {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
        ADMIN,
    )
    validate_success(response, 200)

    accrual_a = fx.read_accrual(ctx["accrual_a"]["id"])
    assert_accrual(accrual_a)
    assert accrual_a["status"] == AccrualStatus.PAID.value
    assert accrual_a["basis"] == AccrualBasis.BLENDED_PERIOD.value
    assert accrual_a["final_adjustment_cents"] == 0
    assert_split(
        accrual_a,
        gross_rebate_cents=GROSS_A_CENTS,
        admin_fee_bps_applied=ADMIN_FEE_BPS_APPLIED,
        admin_fee_cents=FEE_A_CENTS,
        net_distributable_cents=NET_A_CENTS,
        member_share_cents=SHARE_A_CENTS,
        gpo_retention_cents=RETENTION_A_CENTS,
    )
    assert accrual_a["reversal_reason"] == ReversalReason.NONE.value

    # A close leaves the deal's status alone but advances its version, once for
    # the claim create and once for this close.
    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.ACTIVE.value
    assert deal["version"] == deal_version_before + 2


def test_close_period_leaves_the_unvalidated_accrual_accrued_but_rebased():
    """The dependent row: the accrual nobody validated is rebased and stamped
    BLENDED_PERIOD like its sibling, yet it is not paid, and both accruals reuse
    the administration-fee band frozen at accrue time.

    "An accrual left in `ACCRUED` or `FLAGGED` status is not paid — it was never
    validated against a reconciled claim". "The accrual's already-frozen
    `admin_fee_bps_applied` is reused verbatim".

    Design: Corner/state_machines/close_period_pays_validated_accruals_and_rewrites_the_snapshot
    """
    ctx = _june_accrued_with_validated_accrual()
    assert ctx["accrual_a"]["admin_fee_bps_applied"] == ADMIN_FEE_BPS_APPLIED
    assert ctx["accrual_b"]["admin_fee_bps_applied"] == ADMIN_FEE_BPS_APPLIED

    validate_success(
        api_client.close_period(
            ctx["deal_id"],
            {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
            ADMIN,
        ),
        200,
    )

    accrual_b = fx.read_accrual(ctx["accrual_b"]["id"])
    assert_accrual(accrual_b)
    assert accrual_b["status"] == AccrualStatus.ACCRUED.value
    assert accrual_b["basis"] == AccrualBasis.BLENDED_PERIOD.value
    assert accrual_b["final_adjustment_cents"] == 0
    assert_split(
        accrual_b,
        gross_rebate_cents=GROSS_B_CENTS,
        admin_fee_bps_applied=ADMIN_FEE_BPS_APPLIED,
        admin_fee_cents=FEE_B_CENTS,
        net_distributable_cents=NET_B_CENTS,
        member_share_cents=SHARE_B_CENTS,
        gpo_retention_cents=RETENTION_B_CENTS,
    )
    # The band was reused, not re-selected, on both accruals.
    accrual_a = fx.read_accrual(ctx["accrual_a"]["id"])
    assert accrual_a["admin_fee_bps_applied"] == ADMIN_FEE_BPS_APPLIED
    assert accrual_b["admin_fee_bps_applied"] == ADMIN_FEE_BPS_APPLIED


def test_close_period_rewrites_the_snapshot_and_locks_renormalization_out():
    """The other dependent rows: the member's three counters are untouched by a
    PER_CASE rebase while its frozen snapshot is rewritten to share plus
    retention, and the paid accrual now blocks a renormalization.

    "Each affected member's `ytd_net_snapshot_cents` is rewritten to that
    member's post-close attributed net total, namely its
    `accrued_member_share_cents` plus its `attributed_gpo_retention_cents`".

    Design: Corner/state_machines/close_period_pays_validated_accruals_and_rewrites_the_snapshot
    """
    ctx = _june_accrued_with_validated_accrual()
    assert ctx["member"]["ytd_net_snapshot_cents"] == 0

    validate_success(
        api_client.close_period(
            ctx["deal_id"],
            {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
            ADMIN,
        ),
        200,
    )

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    # A PER_CASE rebase moves no money, so the three counters stand still.
    assert_member_ledger(
        member,
        accrued_member_share_cents=LEDGER_SHARE_CENTS,
        attributed_gpo_retention_cents=LEDGER_RETENTION_CENTS,
        attributed_admin_fee_cents=LEDGER_FEE_CENTS,
    )
    assert member["ytd_net_snapshot_cents"] == YTD_NET_SNAPSHOT_CENTS
    assert member["ytd_net_snapshot_cents"] == (
        LEDGER_SHARE_CENTS + LEDGER_RETENTION_CENTS
    )
    # Still strictly below the band break, so later accruals keep the low band.
    assert member["ytd_net_snapshot_cents"] < C.ADMIN_FEE_BAND_BREAK_CENTS

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    # "it is likewise refused when the batch's normalization_status is ACCRUED
    # and any accrual of that batch has status of VALIDATED, DISPUTED or PAID"
    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409


# ===================================================================== 3 =====
# dispute_reject_restores_the_accrual_to_its_prior_status

def test_reject_restores_the_accrual_to_the_captured_validated_status():
    """The primary transition: REJECT closes the dispute and puts the accrual
    back at the status captured in accrual_status_before — VALIDATED, not the
    initial ACCRUED — with its validation record intact.

    "The dispute moves `OPEN → REJECTED` and the accrual returns from
    `DISPUTED` to exactly the status recorded in `accrual_status_before` ...
    with the accrual's `validated_by_user_id` preserved where it had one."

    Design: Corner/state_machines/dispute_reject_restores_the_accrual_to_its_prior_status
    """
    ctx = _june_accrued_with_validated_accrual()
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.RATE_MISMATCH.value,
        disputed_amount_cents=SHARE_A_CENTS,
        claim_id=ctx["claim_id"],
    )

    # Before the trigger: the accrual is DISPUTED and the dispute remembers the
    # completed validation it must restore.
    dispute = fx.read_dispute(ctx["dispute_id"])
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["accrual_status_before"] == AccrualStatus.VALIDATED.value
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert fx.read_accrual(ctx["accrual_a"]["id"])["status"] == (
        AccrualStatus.DISPUTED.value
    )

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {
            "decision": DisputeDecision.REJECT.value,
            "decision_note": REJECT_DECISION_NOTE,
        },
        ARBITER,
    )
    decided = validate_success(response, 200)
    assert decided["status"] == DisputeStatus.REJECTED.value
    assert decided["decided_by_user_id"] == ARBITER_1
    assert decided["decision_note"] == REJECT_DECISION_NOTE

    accrual_a = fx.read_accrual(ctx["accrual_a"]["id"])
    assert_accrual(accrual_a)
    # Restored to accrual_status_before, not to the initial ACCRUED.
    assert accrual_a["status"] == AccrualStatus.VALIDATED.value
    assert accrual_a["validated_by_user_id"] == ANALYST_2
    assert accrual_a["reversal_reason"] == ReversalReason.NONE.value


def test_reject_moves_no_money_and_leaves_the_dispute_terminal():
    """The dependent rows: a rejection touches no member counter, no posture,
    no batch hold, and the decided dispute cannot be decided a second time.

    "Not one money field and not one counter anywhere in the system changes."
    "Both `UPHELD` and `REJECTED` are terminal dispute states".

    Design: Corner/state_machines/dispute_reject_restores_the_accrual_to_its_prior_status
    """
    ctx = _june_accrued_with_validated_accrual()
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.RATE_MISMATCH.value,
        disputed_amount_cents=SHARE_A_CENTS,
        claim_id=ctx["claim_id"],
    )

    validate_success(
        api_client.decide_dispute(
            ctx["dispute_id"],
            {
                "decision": DisputeDecision.REJECT.value,
                "decision_note": REJECT_DECISION_NOTE,
            },
            ARBITER,
        ),
        200,
    )

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert_member_ledger(
        member,
        accrued_member_share_cents=LEDGER_SHARE_CENTS,
        attributed_gpo_retention_cents=LEDGER_RETENTION_CENTS,
        attributed_admin_fee_cents=LEDGER_FEE_CENTS,
    )
    assert member["dispute_reversal_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["payout_hold"] is False

    # REJECTED is terminal: only the OPEN state accepts a decision.
    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {
            "decision": DisputeDecision.REJECT.value,
            "decision_note": REJECT_DECISION_NOTE,
        },
        ARBITER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409


# ===================================================================== 4 =====
# clock_advance_expires_the_active_letter_and_the_dated_cards

def test_clock_advance_expires_the_letter_at_its_effective_to_instant():
    """The primary transition: one clock move to the letter's own effective_to
    expires it on at-or-past instant semantics, decrements both counters, and
    reports the sweep counts — while the member stays enrolled.

    "Advancing the clock expires every authorization letter whose `status` is
    `ACTIVE` and whose `effective_to` is at or before the new instant,
    decrementing the member's and the distributor's `active_letter_count` for
    each".

    Design: Corner/state_machines/clock_advance_expires_the_active_letter_and_the_dated_cards
    """
    ctx = _dated_cards_and_expiring_letter()
    assert ctx["letter"]["status"] == LetterStatus.ACTIVE.value
    assert ctx["member"]["active_letter_count"] == 1

    response = api_client.set_clock(CLOCK_ADVANCED_TO, ADMIN)
    swept = validate_success(response, 200)
    assert_instants_equal(swept["current_utc"], CLOCK_ADVANCED_TO)
    assert swept["letters_expired"] == 1
    assert swept["rate_cards_expired"] == 2

    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter"]["id"], ADMIN), 200
    )
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.EXPIRED.value

    member = fx.read_member(ctx["member_id"])
    assert member["active_letter_count"] == 0
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 0
    # Expiry ages out the authorization, it does not un-enroll the member.
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value


def test_clock_advance_expires_both_dated_cards_but_decrements_only_the_approved():
    """The dependent rows: the same move expires the APPROVED and the PROPOSED
    card on strictly-past calendar-date semantics, and only the approved one
    decrements its item's counter.

    "expires every rate card whose `status` is `PROPOSED` or `APPROVED` and
    whose `effective_to` calendar date lies strictly before the new instant's
    calendar date, decrementing the owning item's `approved_rate_card_count`
    for each card that had been approved".

    Design: Corner/state_machines/clock_advance_expires_the_active_letter_and_the_dated_cards
    """
    ctx = _dated_cards_and_expiring_letter()
    assert ctx["card_1"]["status"] == RateCardStatus.APPROVED.value
    assert ctx["card_2"]["status"] == RateCardStatus.PROPOSED.value
    assert fx.read_item(ctx["item"]["id"])["approved_rate_card_count"] == 1
    assert fx.read_item(ctx["item_2"]["id"])["approved_rate_card_count"] == 0

    validate_success(api_client.set_clock(CLOCK_ADVANCED_TO, ADMIN), 200)

    card_1 = validate_success(
        api_client.get_rate_card(ctx["card_1"]["id"], ADMIN), 200
    )
    card_2 = validate_success(
        api_client.get_rate_card(ctx["card_2"]["id"], ADMIN), 200
    )
    assert card_1["status"] == RateCardStatus.EXPIRED.value
    assert card_2["status"] == RateCardStatus.EXPIRED.value

    # The APPROVED card decremented its item; the PROPOSED card never counted,
    # so nothing decrements below zero.
    assert fx.read_item(ctx["item"]["id"])["approved_rate_card_count"] == 0
    assert fx.read_item(ctx["item_2"]["id"])["approved_rate_card_count"] == 0


def test_clock_rewind_reverses_nothing_and_the_deal_can_no_longer_activate():
    """The last dependent rows: moving the clock back sweeps nothing and
    restores nothing, and because the deal's only APPROVED card expired the
    DRAFT deal can no longer be activated.

    "Moving the clock backwards is permitted and reverses nothing that has
    already expired." "at least one of the deal's items must have `status` of
    `ACTIVE` and an `approved_rate_card_count` of at least 1, and a deal that
    cannot show one is rejected with `ERR_DEAL_HAS_NO_APPROVED_RATES`."

    Design: Corner/state_machines/clock_advance_expires_the_active_letter_and_the_dated_cards
    """
    ctx = _dated_cards_and_expiring_letter()
    validate_success(api_client.set_clock(CLOCK_ADVANCED_TO, ADMIN), 200)

    rewound = validate_success(api_client.set_clock(C.CLOCK_EPOCH, ADMIN), 200)
    assert_instants_equal(rewound["current_utc"], C.CLOCK_EPOCH)
    assert rewound["letters_expired"] == 0
    assert rewound["rate_cards_expired"] == 0

    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter"]["id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.EXPIRED.value

    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.DRAFT.value
    response = api_client.activate_deal(ctx["deal_id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_DEAL_HAS_NO_APPROVED_RATES)
    assert response.status_code == 422
