"""Validation-ladder priority pairs and numeric/cardinality boundary points.

Two rules are exercised here, each through the design instances that own it:

  * ``priority_pair_validation_conflict`` — one request that violates two
    ladder rungs at once must report the earlier rung, and the later rung must
    still be reachable once the earlier defect is repaired.
  * ``boundary_precision_check`` — the compliance ratio at exactly the tier
    minimum, at the minimum minus one cent of spend, and deep below the warn
    band; plus a derived accruable set whose cardinality is zero even though a
    MATCHED line is present.

Every precondition is built through the API because the database is empty
before each test.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST_1,
    ANALYST_2,
    ApiErrorId,
    api_client,
    assert_accrual,
    assert_compliance_review,
    assert_member,
    assert_purchase_batch,
    assert_purchase_line,
    assert_split,
    make_analyst_headers,
    make_distributor_feed_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.types import (
    AccrualBasis,
    AccrualBlockReason,
    AccrualStatus,
    ClaimStatus,
    ComplianceResult,
    DealStatus,
    DisputeDecision,
    DisputeReasonCode,
    ItemStatus,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    ReconciliationPosture,
    ReversalReason,
)

# The design pins the ELITE tier's reversal_posture_limit to 1 so that a single
# upheld dispute is enough to harden the member's posture.
POSTURE_LIMIT_ONE = {"reversal_posture_limit": 1}

# --------------------------------------------------------------------------
# instance: p12_member_not_enrolled_beats_p29_invalid_case_quantity
# --------------------------------------------------------------------------


def _pending_member_with_countersigned_letter() -> dict:
    """A PENDING member holding one ACTIVE letter, plus a RECEIVED June feed.

    The letter is countersigned but the member is never activated, so ladder
    rung 15 (LOA in force) and rung 11 (batch still accepting lines) are both
    satisfied and only rungs 12 and 29 are left violated by the trigger.
    """
    tier = fx.create_tier(**POSTURE_LIMIT_ONE)
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"], legal_name="Cove Diner LLC")
    letter = fx.submit_letter(member["id"], distributor["id"], signatory_name="B Osei")
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    batch = fx.create_batch(distributor["id"])
    return {
        "tier": tier,
        "distributor_id": distributor["id"],
        "member_id": member["id"],
        "letter_id": letter["id"],
        "batch_id": batch["id"],
        "distributor_headers": make_distributor_feed_headers(distributor["id"]),
    }


def _zero_case_line_payload(ctx: dict) -> dict:
    """The doubly-invalid line: a PENDING member and cases_shipped of 0."""
    return F.purchase_line_payload(
        ctx["batch_id"],
        ctx["member_id"],
        cases_shipped=0,
        invoice_unit_cost_cents=C.INVOICE_UNIT_COST_CENTS,
        distributor_base_cost_cents=C.LINE_A_BASE_COST_CENTS,
        invoice_date=C.LINE_A_INVOICE_DATE,
    )


def test_member_not_enrolled_outranks_invalid_case_quantity_on_purchase_line():
    """A line citing a PENDING member with cases_shipped 0 violates rung 12 and
    rung 29 at once; the 409 state error must win and nothing may be written.

    PRD 2.7: "Requests are validated as an ordered ladder, and the **first**
    check that fails determines the response. No later check runs, so a request
    that would fail three ways reports only the earliest failure."
    PRD 2.7 rung 12: "The referenced member has `enrollment_status` of
    `ACTIVE` — otherwise `ERR_MEMBER_NOT_ENROLLED`."

    Design: Difficulty/priority_pair_validation_conflict/p12_member_not_enrolled_beats_p29_invalid_case_quantity
    """
    ctx = _pending_member_with_countersigned_letter()

    response = api_client.create_purchase_line(
        _zero_case_line_payload(ctx), ctx["distributor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ENROLLED, 409)

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["line_count"] == 0, "no PurchaseLine row may be created"
    assert batch["total_cases_ingested"] == 0
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value

    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], fx.ADMIN)
    )
    assert letter["status"] == LetterStatus.ACTIVE.value

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    assert member["active_letter_count"] == 1


def test_invalid_case_quantity_surfaces_once_the_member_is_activated():
    """Repairing only the higher-priority defect — activating the member — lets
    the identical zero-case line fall through to rung 29's 422.

    PRD 2.7 rung 29: "A purchase line's quantity and cost figures are each at
    least 1 — otherwise `ERR_INVALID_CASE_QUANTITY`."

    Design: Difficulty/priority_pair_validation_conflict/p12_member_not_enrolled_beats_p29_invalid_case_quantity
    """
    ctx = _pending_member_with_countersigned_letter()
    payload = _zero_case_line_payload(ctx)

    validate_error(
        api_client.create_purchase_line(payload, ctx["distributor_headers"]),
        ApiErrorId.ERR_MEMBER_NOT_ENROLLED,
        409,
    )

    member = fx.activate_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value

    response = api_client.create_purchase_line(payload, ctx["distributor_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_CASE_QUANTITY, 422)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["line_count"] == 0, "the 422 rejection still writes no line"
    assert batch["total_cases_ingested"] == 0


# --------------------------------------------------------------------------
# instance: p16_claim_not_reconciled_beats_p41_member_payout_held
# --------------------------------------------------------------------------


def _payout_held_member_with_unreconciled_claim() -> dict:
    """Accrued June feed, a SUBMITTED (never reconciled) claim, and a member
    whose upheld dispute on the FIRST accrual left it under a payout hold.

    The SECOND accrual stays ACCRUED, which is the legal source state for
    validate, so rung 11 is satisfied and only rungs 16 and 41 remain violated.
    """
    ctx = fx.setup_june_accrued(tier_overrides=POSTURE_LIMIT_ONE)
    # 30-case accrual: gross 4500, member_share 3274. 40-case accrual: gross
    # 6000, member_share 4365.
    claim = fx.create_claim(ctx["deal_id"], 70, 10500)
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    # The design's reason_code "CASES_OVERSTATED" is not in the PRD's set; the
    # PRD's own symbol for a case-count grievance is UNITS_MISMATCH.
    fx.open_dispute_on(ctx, ctx["accrual_a"], DisputeReasonCode.UNITS_MISMATCH.value)
    fx.decide_dispute(
        ctx["dispute_id"],
        DisputeDecision.UPHOLD.value,
        "Cases restated downward by the distributor",
    )
    ctx["member"] = fx.read_member(ctx["member_id"])
    assert ctx["member"]["payout_hold"] is True
    assert (
        ctx["member"]["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value
    )
    return ctx


def test_claim_not_reconciled_outranks_member_payout_held_on_validate():
    """Validating an ACCRUED accrual against a SUBMITTED claim while the member
    is genuinely on payout hold must report rung 16, not rung 41 — both are 409,
    so only the error_id distinguishes them.

    PRD 3.5: "a cited claim whose `status` is `SUBMITTED`, `VARIANCE_FLAGGED` or
    `SUPERSEDED` rather than `RECONCILED` is refused with
    `ERR_CLAIM_NOT_RECONCILED`, and an accrual whose member has `payout_hold`
    set to true is refused with `ERR_MEMBER_PAYOUT_HELD`."

    Design: Difficulty/priority_pair_validation_conflict/p16_claim_not_reconciled_beats_p41_member_payout_held
    """
    ctx = _payout_held_member_with_unreconciled_claim()

    response = api_client.validate_accrual(
        ctx["accrual_b"]["id"],
        {"claim_id": ctx["claim_id"]},
        make_analyst_headers(ANALYST_2),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_RECONCILED, 409)

    member = fx.read_member(ctx["member_id"])
    assert member["payout_hold"] is True, "rung 41 was genuinely violated too"
    assert member["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value

    accrual_b = fx.read_accrual(ctx["accrual_b"]["id"])
    assert_accrual(accrual_b)
    assert accrual_b["status"] == AccrualStatus.ACCRUED.value
    assert accrual_b["validated_by_user_id"] is None
    assert accrual_b["reversal_reason"] == ReversalReason.NONE.value

    claim = fx.read_claim(ctx["claim_id"])
    assert claim["status"] == ClaimStatus.SUBMITTED.value
    # The PRD stores variance_bps as 0 on a fresh filing (the design instance
    # says "null"); reconciled_at is what stays null until reconciliation.
    assert claim["variance_bps"] == 0
    assert claim["reconciled_at"] is None


def test_member_payout_held_surfaces_once_a_reconciled_claim_backs_the_validate():
    """With rung 16 repaired — a restated claim reconciled at 0 bps variance —
    the identical validate call falls through to rung 41's 409.

    PRD 3.5: "an accrual whose member has `payout_hold` set to true is refused
    with `ERR_MEMBER_PAYOUT_HELD`." PRD 3.5 also fixes the repair path: "Only a
    `RECONCILED` claim can back an accrual validation, so a flagged claim must be
    restated by a fresh filing rather than argued about in place."

    Design: Difficulty/priority_pair_validation_conflict/p16_claim_not_reconciled_beats_p41_member_payout_held
    """
    ctx = _payout_held_member_with_unreconciled_claim()

    validate_error(
        api_client.validate_accrual(
            ctx["accrual_b"]["id"],
            {"claim_id": ctx["claim_id"]},
            make_analyst_headers(ANALYST_2),
        ),
        ApiErrorId.ERR_CLAIM_NOT_RECONCILED,
        409,
    )

    # The upheld dispute reversed the 4500-cent accrual, and PRD 3.5 excludes
    # REVERSED accruals from accrued_amount_cents, so only the 6000-cent accrual
    # remains: a restatement at 6000 cents reconciles at exactly 0 bps.
    restated = fx.create_claim(ctx["deal_id"], 70, 6000)
    superseded = fx.read_claim(ctx["claim_id"])
    assert superseded["status"] == ClaimStatus.SUPERSEDED.value
    restated = fx.reconcile_claim(restated["id"])
    assert restated["status"] == ClaimStatus.RECONCILED.value
    assert restated["accrued_amount_cents"] == 6000
    assert restated["variance_bps"] == 0

    response = api_client.validate_accrual(
        ctx["accrual_b"]["id"],
        {"claim_id": restated["id"]},
        make_analyst_headers(ANALYST_2),
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_PAYOUT_HELD, 409)

    accrual_b = fx.read_accrual(ctx["accrual_b"]["id"])
    assert accrual_b["status"] == AccrualStatus.ACCRUED.value
    assert accrual_b["validated_by_user_id"] is None

    member = fx.read_member(ctx["member_id"])
    assert member["payout_hold"] is True
    assert member["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value


# --------------------------------------------------------------------------
# instance: compliance_ratio_exact_minimum_passes_and_floor_at_minimum_minus_one
# --------------------------------------------------------------------------

REVIEW_WINDOW_START = "2026-05-20"
REVIEW_WINDOW_END = "2026-07-31"
REVIEW_WINDOW_DAYS = 73
REVIEW_PRORATED_COMMITMENT_CENTS = 4_000_000
REVIEW_DEAL_WIDE_SPEND_CENTS = 8_791_999

MEMBER_A_SPEND_CENTS = 3_200_000      # 400 cases at 8000 -> exactly 8000 bps
MEMBER_B_SPEND_CENTS = 3_199_999      # 7999.9975 bps, floors to 7999
MEMBER_C_SPEND_CENTS = 2_392_000      # 5980 bps, below the warn band


def _three_member_ratio_fixture() -> dict:
    """Three ACTIVE ELITE members on one NORMALIZED June feed whose matched
    spend lands exactly at, one cent below, and far below the tier minimum."""
    tier = fx.create_tier(**POSTURE_LIMIT_ONE)
    distributor = fx.create_distributor()

    members = {}
    for key, legal_name, signatory in (
        ("a", "Harbor Grill LLC", "A Ruiz"),
        ("b", "Cove Diner LLC", "B Osei"),
        ("c", "Pier Nine Cafe LLC", "C Nakamura"),
    ):
        member = fx.create_member(tier["id"], legal_name=legal_name)
        letter = fx.submit_letter(
            member["id"], distributor["id"], signatory_name=signatory
        )
        fx.countersign_letter(letter["id"], distributor["id"])
        members[key] = fx.activate_member(member["id"])

    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    fx.approved_card(item["id"])
    deal = fx.activate_deal(deal["id"])

    batch = fx.create_batch(distributor["id"])
    for member_key, cases, unit_cost, invoice_date in (
        ("a", 400, 8000, "2026-06-05"),
        ("b", 399, 8000, "2026-06-05"),
        ("b", 1, 7999, "2026-06-06"),
        ("c", 299, 8000, "2026-06-05"),
    ):
        fx.create_line(
            batch["id"],
            members[member_key]["id"],
            distributor["id"],
            cases_shipped=cases,
            invoice_unit_cost_cents=unit_cost,
            distributor_base_cost_cents=7400,
            invoice_date=invoice_date,
        )
    batch = fx.normalize(batch["id"])
    assert batch["matched_cases"] == 1099, "every line must match the beef item"

    return {
        "tier": tier,
        "deal": deal,
        "deal_id": deal["id"],
        "item_id": item["id"],
        "batch": batch,
        "member_a": members["a"],
        "member_b": members["b"],
        "member_c": members["c"],
    }


def _run_review(member_id: str, deal_id: str):
    """POST /compliance-reviews over the canonical 73-day window."""
    return api_client.create_compliance_review(
        F.compliance_review_payload(
            member_id, deal_id, REVIEW_WINDOW_START, REVIEW_WINDOW_END
        ),
        fx.ANALYST,
    )


def _assert_window_figures(review: dict):
    """The three figures every review in this instance shares."""
    assert_compliance_review(review)
    assert review["window_days"] == REVIEW_WINDOW_DAYS
    assert review["committed_spend_prorated_cents"] == REVIEW_PRORATED_COMMITMENT_CENTS
    assert review["deal_wide_contracted_spend_cents"] == REVIEW_DEAL_WIDE_SPEND_CENTS
    assert review["triggered_deal_loss"] is False


def test_compliance_ratio_exactly_at_the_tier_minimum_passes():
    """3200000 cents of matched spend against a 4000000-cent prorated promise is
    exactly 8000 bps, and the inclusive comparator must return PASS.

    PRD 3.8: "`PASS` is the verdict when `purchase_ratio_bps` is at or above the
    tier's `compliance_min_ratio_bps` — a ratio exactly equal to the minimum
    passes."

    Design: Difficulty/boundary_precision_check/compliance_ratio_exact_minimum_passes_and_floor_at_minimum_minus_one
    """
    ctx = _three_member_ratio_fixture()

    response = _run_review(ctx["member_a"]["id"], ctx["deal_id"])
    review = validate_success(response, 201)
    _assert_window_figures(review)
    assert review["contracted_spend_cents"] == MEMBER_A_SPEND_CENTS
    assert review["purchase_ratio_bps"] == 8000
    assert review["result"] == ComplianceResult.PASS.value

    member_a = fx.read_member(ctx["member_a"]["id"])
    assert member_a["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert member_a["payout_hold"] is False

    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.ACTIVE.value


def test_compliance_ratio_one_cent_below_the_minimum_floors_into_the_warn_band():
    """3199999 cents is 7999.9975 bps: flooring — never rounding — records 7999,
    which misses the 8000 bar and lands in the five-point warn band.

    PRD 3.8: "`purchase_ratio_bps` ... is `contracted_spend_cents` multiplied by
    10000, divided by `committed_spend_prorated_cents`, and **floored**, so a
    true ratio of 7999.9 basis points is recorded as 7999 and does not reach an
    8000-basis-point minimum."
    PRD 3.8: "`WARN` is the verdict when `purchase_ratio_bps` is at or above the
    tier's `compliance_min_ratio_bps` less 500 basis points".

    Design: Difficulty/boundary_precision_check/compliance_ratio_exact_minimum_passes_and_floor_at_minimum_minus_one
    """
    ctx = _three_member_ratio_fixture()

    response = _run_review(ctx["member_b"]["id"], ctx["deal_id"])
    review = validate_success(response, 201)
    _assert_window_figures(review)
    assert review["contracted_spend_cents"] == MEMBER_B_SPEND_CENTS
    assert review["purchase_ratio_bps"] == 7999, "floor, not round half up"
    assert review["result"] == ComplianceResult.WARN.value

    member_b = fx.read_member(ctx["member_b"]["id"])
    assert member_b["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert member_b["payout_hold"] is False, "a WARN changes nothing on the member"


def test_compliance_ratio_below_the_warn_band_breaches_and_suspends_the_member():
    """2392000 cents is 5980 bps, below 8000 - 500, so the verdict is BREACH and
    only that verdict cascades into the member's standing.

    PRD 3.8: "A `BREACH` costs the member its standing: it moves
    `ACTIVE → SUSPENDED`, its `payout_hold` is set to true and its `version` is
    incremented by 1".

    Design: Difficulty/boundary_precision_check/compliance_ratio_exact_minimum_passes_and_floor_at_minimum_minus_one
    """
    ctx = _three_member_ratio_fixture()
    version_before = ctx["member_c"]["version"]

    response = _run_review(ctx["member_c"]["id"], ctx["deal_id"])
    review = validate_success(response, 201)
    _assert_window_figures(review)
    assert review["contracted_spend_cents"] == MEMBER_C_SPEND_CENTS
    assert review["purchase_ratio_bps"] == 5980
    assert review["result"] == ComplianceResult.BREACH.value

    member_c = fx.read_member(ctx["member_c"]["id"])
    assert_member(member_c)
    assert member_c["enrollment_status"] == MemberEnrollmentStatus.SUSPENDED.value
    assert member_c["payout_hold"] is True
    assert member_c["version"] == version_before + 1

    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.ACTIVE.value, (
        "DEAL_LOST never fires while deal-wide contracted spend is non-zero"
    )


# --------------------------------------------------------------------------
# instance: accruable_set_cardinality_zero_with_a_matched_line_present
# --------------------------------------------------------------------------


def _matched_line_priced_only_by_a_proposed_card() -> dict:
    """A NORMALIZED June feed whose single line is MATCHED to an item carrying
    exactly one rate card, and that card is still PROPOSED.

    The deal is ACTIVE on the strength of a second item's APPROVED card, so the
    accruable set is empty while a MATCHED line is genuinely present.
    """
    tier = fx.create_tier(**POSTURE_LIMIT_ONE)
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])

    deal = fx.create_deal()
    beef_item = fx.create_item(deal["id"])
    fx.approved_card(beef_item["id"])
    chicken_item = fx.create_item(deal["id"], payload=F.chicken_item_payload(deal["id"]))
    chicken_card = fx.create_card(chicken_item["id"], flat_rate_cents_per_case=100)
    deal = fx.activate_deal(deal["id"])

    batch = fx.create_batch(distributor["id"])
    line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        payload=F.chicken_line_payload(batch["id"], member["id"]),
    )
    batch = fx.normalize(batch["id"])
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["matched_cases"] == 25 and batch["unmatched_cases"] == 0

    return {
        "member_id": member["id"],
        "deal_id": deal["id"],
        "chicken_item_id": chicken_item["id"],
        "chicken_card_id": chicken_card["id"],
        "batch_id": batch["id"],
        "line_id": line["id"],
    }


def test_accrue_refused_when_the_only_matched_line_resolves_no_approved_card():
    """The batch holds a MATCHED line, yet its item's only card is PROPOSED, so
    the accruable set is empty and the whole call fails atomically at 422.

    PRD 3.4: "a normalized batch in which not one `MATCHED` line resolves an
    approved rate card for its own `invoice_date` is refused with
    `ERR_NO_ACCRUABLE_LINES`, because an accrual run that would produce nothing
    should not advance the batch's state."

    Design: Difficulty/boundary_precision_check/accruable_set_cardinality_zero_with_a_matched_line_present
    """
    ctx = _matched_line_priced_only_by_a_proposed_card()

    response = api_client.accrue_batch(ctx["batch_id"], make_analyst_headers(ANALYST_1))
    validate_error(response, ApiErrorId.ERR_NO_ACCRUABLE_LINES, 422)

    line = fx.read_line(ctx["line_id"])
    assert_purchase_line(line)
    assert line["match_status"] == MatchStatus.MATCHED.value
    assert line["contracted_item_id"] == ctx["chicken_item_id"]
    # PRD 2.7: "No later check runs" — the rejected call wrote nothing at all,
    # not even the NO_RATE_CARD block reason the accrual run itself would write.
    assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value

    card = validate_success(
        api_client.get_rate_card(ctx["chicken_card_id"], fx.ADMIN)
    )
    assert card["status"] == RateCardStatus.PROPOSED.value

    item = fx.read_item(ctx["chicken_item_id"])
    assert item["status"] == ItemStatus.ACTIVE.value
    assert item["approved_rate_card_count"] == 0

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["accrued_by_user_id"] is None

    assert fx.list_accruals(purchase_line_id=ctx["line_id"]) == []
    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == 0


def test_accrue_succeeds_once_the_single_card_is_approved():
    """Approving that one card lifts the accruable set's cardinality to 1, and
    the identical accrue call posts exactly one accrual through the waterfall.

    PRD 3.4: "The candidates are the rate cards whose `contracted_item_id` is the
    line's resolved item, whose `status` is `APPROVED`, and whose closed
    `effective_from` through `effective_to` range contains the line's
    `invoice_date`". Cards "in `PROPOSED`, `SUPERSEDED` or `EXPIRED` status are
    never selectable no matter how well their dates fit."

    Design: Difficulty/boundary_precision_check/accruable_set_cardinality_zero_with_a_matched_line_present
    """
    ctx = _matched_line_priced_only_by_a_proposed_card()

    validate_error(
        api_client.accrue_batch(ctx["batch_id"], make_analyst_headers(ANALYST_1)),
        ApiErrorId.ERR_NO_ACCRUABLE_LINES,
        422,
    )

    card = fx.approve_card(ctx["chicken_card_id"])
    assert card["status"] == RateCardStatus.APPROVED.value
    assert fx.read_item(ctx["chicken_item_id"])["approved_rate_card_count"] == 1

    response = api_client.accrue_batch(ctx["batch_id"], make_analyst_headers(ANALYST_1))
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["accrued_by_user_id"] == ANALYST_1

    accruals = fx.list_accruals(purchase_line_id=ctx["line_id"])
    assert len(accruals) == 1, "exactly one accrual per accruable line"
    accrual = accruals[0]
    assert_accrual(accrual)
    assert accrual["accrued_cases"] == 25
    assert accrual["rate_card_id"] == ctx["chicken_card_id"]
    assert accrual["status"] == AccrualStatus.ACCRUED.value
    assert accrual["basis"] == AccrualBasis.MARGINAL_BATCH.value
    assert accrual["reversal_reason"] == ReversalReason.NONE.value
    assert accrual["final_adjustment_cents"] == 0
    assert_split(
        accrual,
        gross_rebate_cents=2500,
        admin_fee_bps_applied=C.ELITE_TIER["admin_fee_bps_low"],
        admin_fee_cents=75,
        net_distributable_cents=2425,
        member_share_cents=1819,
        gpo_retention_cents=606,
    )

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == 1819
    assert member["attributed_gpo_retention_cents"] == 606
    assert member["attributed_admin_fee_cents"] == 75
