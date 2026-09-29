"""Compensating invariants: the money triple and case conservation.

Two ledger identities must survive the system's compensating actions. The money
triple — a member's three attributed counters summed — must always equal the
gross of that member's non-REVERSED accruals, before and after an upheld
dispute retracts one accrual component by component. Case conservation —
total_cases_ingested == matched_cases + unmatched_cases — must hold after
ingestion, after normalize, after accrue and after the compensating
renormalize, which closes both identities in the same call.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ANALYST_1,
    ARBITER_1,
    AccrualBasis,
    AccrualBlockReason,
    AccrualStatus,
    DisputeDecision,
    DisputeReasonCode,
    MatchStatus,
    NormalizationStatus,
    ReconciliationPosture,
    ReversalReason,
    api_client,
    assert_accrual,
    assert_case_conservation,
    assert_member_ledger,
    assert_money_triple,
    assert_purchase_batch,
    assert_purchase_line,
    assert_split,
    make_analyst_headers,
    make_arbiter_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

ANALYST = make_analyst_headers(ANALYST_1)
ARBITER = make_arbiter_headers(ARBITER_1)

# The tier the two design instances pin: the canonical ELITE tier with
# reversal_posture_limit forced to 1 instead of the PRD default of 2.
TIER_OVERRIDES = {"reversal_posture_limit": 1}

# ------------------------------------------------- accrual A: 30 cases ----
GROSS_A = 4500
FEE_A = 135
NET_A = 4365
SHARE_A = 3274
RETENTION_A = 1091
CASES_A = 30

# ------------------------------------------------- accrual B: 40 cases ----
GROSS_B = 6000
FEE_B = 180
NET_B = 5820
SHARE_B = 4365
RETENTION_B = 1455
CASES_B = 40

ADMIN_FEE_BPS_LOW = 300

# ------------------------------------------- the member's money triple ----
LEDGER_SHARE = 7639          # 3274 + 4365
LEDGER_RETENTION = 2546      # 1091 + 1455
LEDGER_FEE = 315             # 135 + 180
GROSS_TOTAL = 10500          # 4500 + 6000
GROSS_AFTER_REVERSAL = 6000  # accrual B alone

# --------------------------------------------------- case conservation ----
FRIES_CASES = 20
TOTAL_CASES = 90             # 30 + 40 + 20
MATCHED_CASES = 70           # the two beef lines
UNMATCHED_AFTER_NORMALIZE = 20


# =========================================================== local helpers ====
# test_helpers must not be edited, so the two helpers these instances need that
# fixtures.py does not offer live here.


def _accruals_for_line(line_id: str) -> list:
    """Every accrual ever written against one purchase line, newest first."""
    return [a for a in fx.list_accruals() if a["purchase_line_id"] == line_id]


def _live_accrual_for_line(line_id: str) -> dict:
    """The one accrual of a line that is not REVERSED.

    A renormalize/re-accrue cycle can leave a REVERSED accrual behind, so the
    live figure is selected by status rather than by assuming a single row.
    """
    rows = [a for a in _accruals_for_line(line_id)
            if a["status"] != AccrualStatus.REVERSED.value]
    assert len(rows) == 1, (
        f"expected exactly one non-REVERSED accrual for line {line_id}, got {len(rows)}"
    )
    return rows[0]


def _non_reversed_gross_total(member_id: str) -> int:
    """The sum of gross_rebate_cents over a member's non-REVERSED accruals."""
    return sum(
        a["gross_rebate_cents"]
        for a in fx.accruals_for_member(member_id)
        if a["status"] != AccrualStatus.REVERSED.value
    )


def _june_feed_with_excluded_fries_line() -> dict:
    """The June feed of the case-conservation instance, ingested only.

    Three lines: 30 and 40 beef cases against the ACTIVE PBC-2026 deal, plus 20
    fries cases whose only key candidate sits under a DRAFT second deal, so that
    line can only ever be EXCLUDED.
    """
    ctx = fx.setup_flat_program(tier_overrides=TIER_OVERRIDES)
    deal2 = fx.create_second_deal()
    ctx["deal2"] = deal2
    ctx["item2"] = fx.create_item(deal2["id"], payload=F.fries_item_payload(deal2["id"]))
    fx.ingest_june_feed(ctx)
    ctx["line_c"] = fx.create_line(
        ctx["batch_id"],
        ctx["member_id"],
        ctx["distributor_id"],
        payload=F.fries_line_payload(ctx["batch_id"], ctx["member_id"]),
    )
    return ctx


def _uphold_dispute(dispute_id: str):
    """The trigger call of the money-triple instance, returned raw.

    The arbiter's X-User-ID differs from the dispute's opened_by_user_id (the
    member id), from the accrual's validated_by_user_id (null) and from the
    batch's accrued_by_user_id (analyst-01).
    """
    return api_client.decide_dispute(
        dispute_id,
        {
            "decision": DisputeDecision.UPHOLD.value,
            "decision_note": "Cases restated from 30 to 24",
        },
        ARBITER,
    )


# ================================================================ money ======
# Instance: money_triple_reconciles_to_gross_after_dispute_reversal


def test_money_triple_reconciles_to_10500_after_both_accruals_post():
    """Accrue the June feed and check the money triple closes on the gross.

    PRD §3.4: "A member's three counters therefore always equal the summed
    components of its accruals whose `status` is one of `ACCRUED`, `VALIDATED`,
    `FLAGGED`, `DISPUTED` or `PAID` — reversed accruals having been subtracted
    out again." and "so the GPO's retention absorbs whatever the rounding left
    behind and the three parts reconstruct the gross to the cent."

    Design: Difficulty/compensating_invariant/money_triple_reconciles_to_gross_after_dispute_reversal
    """
    ctx = fx.setup_june_normalized(tier_overrides=TIER_OVERRIDES)

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["accrued_by_user_id"] == ANALYST_1

    accrual_a = _live_accrual_for_line(ctx["line_a"]["id"])
    accrual_b = _live_accrual_for_line(ctx["line_b"]["id"])
    assert_split(accrual_a, GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A)
    assert_split(accrual_b, GROSS_B, ADMIN_FEE_BPS_LOW, FEE_B, NET_B, SHARE_B, RETENTION_B)
    assert accrual_a["status"] == AccrualStatus.ACCRUED.value
    assert accrual_b["status"] == AccrualStatus.ACCRUED.value

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(member, LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE)
    assert_money_triple(member, GROSS_TOTAL)
    assert _non_reversed_gross_total(ctx["member_id"]) == GROSS_TOTAL


def test_money_triple_recloses_at_6000_after_upheld_dispute_reversal():
    """Uphold the dispute on the 4500-cent accrual: each counter drops by that
    accrual's own stored component and the triple recloses on the surviving gross.

    PRD §3.6 hop 3: "the member's `accrued_member_share_cents` is decremented by
    that accrual's stored `member_share_cents`, its
    `attributed_gpo_retention_cents` by the accrual's `gpo_retention_cents` and
    its `attributed_admin_fee_cents` by the accrual's `admin_fee_cents`, each by
    the exact stored component rather than a recomputed one"

    Design: Difficulty/compensating_invariant/money_triple_reconciles_to_gross_after_dispute_reversal
    """
    ctx = fx.setup_june_accrued(tier_overrides=TIER_OVERRIDES)
    assert_money_triple(fx.read_member(ctx["member_id"]), GROSS_TOTAL)
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.UNITS_MISMATCH.value,
        disputed_amount_cents=SHARE_A,
    )

    response = _uphold_dispute(ctx["dispute_id"])
    dispute = validate_success(response, 200)
    assert dispute["status"] == "UPHELD"
    assert dispute["decided_by_user_id"] == ARBITER_1

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == LEDGER_SHARE - SHARE_A == SHARE_B
    assert member["attributed_gpo_retention_cents"] == LEDGER_RETENTION - RETENTION_A == RETENTION_B
    assert member["attributed_admin_fee_cents"] == LEDGER_FEE - FEE_A == FEE_B
    assert_member_ledger(member, SHARE_B, RETENTION_B, FEE_B)
    assert_money_triple(member, GROSS_AFTER_REVERSAL)

    # 6000 is the gross of the member's non-REVERSED accruals: accrual B alone.
    live = [a for a in fx.accruals_for_member(ctx["member_id"])
            if a["status"] != AccrualStatus.REVERSED.value]
    assert [a["id"] for a in live] == [ctx["accrual_b"]["id"]]
    assert _non_reversed_gross_total(ctx["member_id"]) == GROSS_AFTER_REVERSAL


def test_reversed_accrual_keeps_its_own_stored_money_figures():
    """The reversed accrual's own four money fields are untouched by the
    reversal: only the member's counters moved, by exactly those stored figures.

    PRD §3.6 hop 2: "the accrual moves `DISPUTED → REVERSED` with
    `reversal_reason` set to `DISPUTE_UPHELD`." PRD §2.10: "the exact stored
    component values are subtracted, so that a reversal is the arithmetic inverse
    of the posting it undoes rather than a fresh computation that might land a
    cent away."

    Design: Difficulty/compensating_invariant/money_triple_reconciles_to_gross_after_dispute_reversal
    """
    ctx = fx.setup_june_accrued(tier_overrides=TIER_OVERRIDES)
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.UNITS_MISMATCH.value,
        disputed_amount_cents=SHARE_A,
    )
    validate_success(_uphold_dispute(ctx["dispute_id"]), 200)

    response = api_client.get_accrual(ctx["accrual_a"]["id"], ANALYST)
    accrual = validate_success(response, 200)
    assert_accrual(accrual)
    assert accrual["status"] == AccrualStatus.REVERSED.value
    assert accrual["reversal_reason"] == ReversalReason.DISPUTE_UPHELD.value
    assert_split(accrual, GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A)
    assert accrual["accrued_cases"] == CASES_A
    assert accrual["final_adjustment_cents"] == 0
    assert accrual["basis"] == AccrualBasis.MARGINAL_BATCH.value

    # The surviving accrual is equally untouched.
    survivor = validate_success(api_client.get_accrual(ctx["accrual_b"]["id"], ANALYST), 200)
    assert survivor["status"] == AccrualStatus.ACCRUED.value
    assert survivor["reversal_reason"] == ReversalReason.NONE.value
    assert_split(survivor, GROSS_B, ADMIN_FEE_BPS_LOW, FEE_B, NET_B, SHARE_B, RETENTION_B)


def test_savings_report_agrees_with_the_reduced_member_ledger():
    """After the reversal the June savings report reports 4365 cents of rebate,
    the same figure the member's own share counter now carries.

    PRD §3.9: "the sum of `member_share_cents` over that member's accruals in the
    period whose `status` is `ACCRUED`, `VALIDATED`, `FLAGGED`, `DISPUTED` or
    `PAID`. Accruals in `REVERSED` status never count toward realized savings."

    Design: Difficulty/compensating_invariant/money_triple_reconciles_to_gross_after_dispute_reversal
    """
    ctx = fx.setup_june_accrued(tier_overrides=TIER_OVERRIDES)
    fx.open_dispute_on(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.UNITS_MISMATCH.value,
        disputed_amount_cents=SHARE_A,
    )
    validate_success(_uphold_dispute(ctx["dispute_id"]), 200)

    response = api_client.get_savings_report(
        ctx["member_id"], ANALYST, F.savings_report_params(C.JUNE_START, C.JUNE_END)
    )
    report = validate_success(response, 200)
    assert report["rebate_member_share_cents"] == SHARE_B
    assert report["rebate_member_share_cents"] == (
        fx.read_member(ctx["member_id"])["accrued_member_share_cents"]
    )


# ====================================================== case conservation ====
# Instance: case_conservation_survives_normalize_accrue_and_renormalize


def _accrued_feed_with_excluded_fries_line() -> dict:
    """Normalize then accrue the three-line June feed, in two phased hops."""
    ctx = _june_feed_with_excluded_fries_line()
    ctx["batch"] = fx.normalize(ctx["batch_id"])
    ctx["batch"] = fx.accrue(ctx["batch_id"])
    ctx["accrual_a"] = _live_accrual_for_line(ctx["line_a"]["id"])
    ctx["accrual_b"] = _live_accrual_for_line(ctx["line_b"]["id"])
    return ctx


def test_case_conservation_holds_at_ingestion_normalize_and_accrue():
    """90 == 0 + 90 at ingestion, then 90 == 70 + 20 after normalize and again
    after accrue, with total_cases_ingested never recomputed.

    PRD §3.3: "Its arrival increments the batch's `line_count` by 1 and adds the
    line's `cases_shipped` to both `total_cases_ingested` and `unmatched_cases`."
    and "`total_cases_ingested` is never recomputed by normalization; it records
    what the distributor sent and stays fixed for the life of the batch."

    Design: Difficulty/compensating_invariant/case_conservation_survives_normalize_accrue_and_renormalize
    """
    ctx = _june_feed_with_excluded_fries_line()

    ingested = validate_success(api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200)
    assert_purchase_batch(ingested)
    assert ingested["line_count"] == 3
    assert ingested["total_cases_ingested"] == TOTAL_CASES
    assert ingested["matched_cases"] == 0
    assert ingested["unmatched_cases"] == TOTAL_CASES
    assert_case_conservation(ingested)

    normalized = validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)
    assert normalized["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert normalized["total_cases_ingested"] == TOTAL_CASES
    assert normalized["matched_cases"] == MATCHED_CASES
    assert normalized["unmatched_cases"] == UNMATCHED_AFTER_NORMALIZE
    assert_case_conservation(normalized)

    # The fries line is the whole of the unmatched 20: its only key candidate
    # sits under a DRAFT deal, so it is EXCLUDED rather than matched.
    fries = validate_success(api_client.get_purchase_line(ctx["line_c"]["id"], ANALYST), 200)
    assert_purchase_line(fries)
    assert fries["cases_shipped"] == FRIES_CASES
    assert fries["match_status"] == MatchStatus.EXCLUDED.value
    assert fries["accrual_block_reason"] == AccrualBlockReason.DEAL_NOT_ACTIVE.value

    accrued = validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)
    assert accrued["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert accrued["total_cases_ingested"] == TOTAL_CASES
    assert accrued["matched_cases"] == MATCHED_CASES
    assert accrued["unmatched_cases"] == UNMATCHED_AFTER_NORMALIZE
    assert_case_conservation(accrued)


def test_renormalize_drives_matched_to_zero_and_unmatched_back_to_ninety():
    """The compensating renormalize closes case conservation at 90 == 0 + 90 and
    resets all three lines, including the previously EXCLUDED fries line.

    PRD §3.3: "It sets the batch's `matched_cases` to 0 and its `unmatched_cases`
    to `total_cases_ingested`, leaving `total_cases_ingested` itself alone, and it
    clears `accrued_by_user_id` back to null." and "Either direction resets every
    line to `match_status` of `UNMATCHED` with `contracted_item_id` null and
    `accrual_block_reason` of `NONE`"

    Design: Difficulty/compensating_invariant/case_conservation_survives_normalize_accrue_and_renormalize
    """
    ctx = _accrued_feed_with_excluded_fries_line()
    assert ctx["batch"]["audit_status"] == "NOT_AUDITED"

    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["accrued_by_user_id"] is None
    assert batch["total_cases_ingested"] == TOTAL_CASES
    assert batch["matched_cases"] == 0
    assert batch["unmatched_cases"] == TOTAL_CASES
    assert_case_conservation(batch)

    for key in ("line_a", "line_b", "line_c"):
        line = validate_success(api_client.get_purchase_line(ctx[key]["id"], ANALYST), 200)
        assert line["match_status"] == MatchStatus.UNMATCHED.value, key
        assert line["contracted_item_id"] is None, key
        assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value, key


def test_renormalize_reverses_both_accruals_and_zeroes_the_money_triple():
    """The same renormalize call reverses both accruals with reversal_reason
    RENORMALIZED and returns all three member money counters to 0, so the money
    triple closes at 0 == 0 alongside case conservation.

    PRD §3.3: "Every accrual of the batch whose `status` is `ACCRUED` or
    `FLAGGED` moves to `REVERSED` with `reversal_reason` set to `RENORMALIZED`,
    and the owning member's `accrued_member_share_cents`,
    `attributed_gpo_retention_cents` and `attributed_admin_fee_cents` are each
    decremented by that accrual's own stored `member_share_cents`,
    `gpo_retention_cents` and `admin_fee_cents` respectively."

    Design: Difficulty/compensating_invariant/case_conservation_survives_normalize_accrue_and_renormalize
    """
    ctx = _accrued_feed_with_excluded_fries_line()
    assert_member_ledger(
        fx.read_member(ctx["member_id"]), LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE
    )

    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)
    validate_success(response, 200)

    for accrual_key, gross, fee, net, share, retention in (
        ("accrual_a", GROSS_A, FEE_A, NET_A, SHARE_A, RETENTION_A),
        ("accrual_b", GROSS_B, FEE_B, NET_B, SHARE_B, RETENTION_B),
    ):
        accrual = validate_success(
            api_client.get_accrual(ctx[accrual_key]["id"], ANALYST), 200
        )
        assert accrual["status"] == AccrualStatus.REVERSED.value, accrual_key
        assert accrual["reversal_reason"] == ReversalReason.RENORMALIZED.value, accrual_key
        # The reversal subtracts the stored components; it does not rewrite them.
        assert_split(accrual, gross, ADMIN_FEE_BPS_LOW, fee, net, share, retention)

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(member, 0, 0, 0)
    assert_money_triple(member, 0)
    assert _non_reversed_gross_total(ctx["member_id"]) == 0


def test_renormalize_is_not_a_dispute_reversal():
    """A renormalize reversal is bookkeeping: the member's dispute_reversal_count
    stays 0 and its reconciliation_posture stays CLEAR even on a tier whose
    reversal_posture_limit is 1.

    PRD §3.3: "This reversal is bookkeeping, not blame: the member's
    `dispute_reversal_count` is **not** incremented and its
    `reconciliation_posture` is **not** touched, which is exactly what separates
    an operational re-run from an upheld dispute."

    Design: Difficulty/compensating_invariant/case_conservation_survives_normalize_accrue_and_renormalize
    """
    ctx = _accrued_feed_with_excluded_fries_line()
    assert ctx["tier"]["reversal_posture_limit"] == 1
    before = fx.read_member(ctx["member_id"])
    assert before["dispute_reversal_count"] == 0
    assert before["reconciliation_posture"] == ReconciliationPosture.CLEAR.value

    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)
    validate_success(response, 200)

    member = fx.read_member(ctx["member_id"])
    assert member["dispute_reversal_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False


def test_rerunning_normalize_and_accrue_reproduces_the_same_figures():
    """Re-running the cycle after the compensating renormalize reproduces
    matched_cases 70 and the same accrual grosses 4500 and 6000.

    PRD §3.3: "A `RebateAnalyst` may drive a batch `NORMALIZED → RECEIVED`, and
    also `ACCRUED → RECEIVED`, which makes the sequence `RECEIVED → NORMALIZED →
    ACCRUED → RECEIVED` a cycle that may repeat as often as the data demands."

    Design: Difficulty/compensating_invariant/case_conservation_survives_normalize_accrue_and_renormalize
    """
    ctx = _accrued_feed_with_excluded_fries_line()
    fx.renormalize(ctx["batch_id"])

    renormalized = validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)
    assert renormalized["total_cases_ingested"] == TOTAL_CASES
    assert renormalized["matched_cases"] == MATCHED_CASES
    assert renormalized["unmatched_cases"] == UNMATCHED_AFTER_NORMALIZE
    assert_case_conservation(renormalized)

    reaccrued = validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)
    assert reaccrued["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert reaccrued["matched_cases"] == MATCHED_CASES
    assert reaccrued["unmatched_cases"] == UNMATCHED_AFTER_NORMALIZE
    assert_case_conservation(reaccrued)

    accrual_a = _live_accrual_for_line(ctx["line_a"]["id"])
    accrual_b = _live_accrual_for_line(ctx["line_b"]["id"])
    assert accrual_a["gross_rebate_cents"] == GROSS_A
    assert accrual_a["accrued_cases"] == CASES_A
    assert accrual_b["gross_rebate_cents"] == GROSS_B
    assert accrual_b["accrued_cases"] == CASES_B
    assert_split(accrual_a, GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A)
    assert_split(accrual_b, GROSS_B, ADMIN_FEE_BPS_LOW, FEE_B, NET_B, SHARE_B, RETENTION_B)

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(member, LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE)
    assert_money_triple(member, GROSS_TOTAL)
