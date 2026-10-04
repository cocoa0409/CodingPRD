"""The two compensation award variants: the PROVISIONAL estimate frozen at
creation versus the FINAL_VERIFIED award at approval, and the pinned
evaluation order (enhancement, then cap, then fees)."""
from test_helpers import (
    ANCHOR_CAP_CENTS,
    ANCHOR_BITING_CAP_CENTS,
    ANCHOR_CONVICTION_DATE,
    ANCHOR_EXONERATION_CLOCK,
    ANCHOR_FEES_CENTS,
    ANCHOR_FINAL_AWARD_CENTS,
    ANCHOR_CAPPED_FINAL_AWARD_CENTS,
    ANCHOR_PROVISIONAL_CENTS,
    assert_compensation_claim,
    assert_integer_cents,
    create_compensation_claim,
    file_claim,
    record_claim_decision,
    setup_exonerated_case,
)


def _anchor_case(jurisdiction_overrides):
    """Exonerated case matching the PRD's worked anchor facts: conviction
    2016-03-15, exoneration 2026-11-20 (3902 days -> 10 verified years), and
    the exculpatory flag set by a database HIT."""
    return setup_exonerated_case(
        jurisdiction_overrides=jurisdiction_overrides,
        intake_overrides={
            "conviction_date": ANCHOR_CONVICTION_DATE,
            "years_served": 10,
        },
        exoneration_clock=ANCHOR_EXONERATION_CLOCK,
        db_hit=True,
    )


def test_provisional_and_final_awards_are_distinct_variants(api):
    """PRD section 3.8: "With a conviction date of 2016-03-15 and an
    exoneration date of 2026-11-20, the day count is 3902 and the verified
    duration 10 years; with 10 years claimed, a 10 percent enhancement with
    the exculpatory flag set, a cap of 100,000,000 cents, and 3,000,000 cents
    of documented fees, the provisional estimate is 50,000,000 cents, while
    the final award is the enhanced base of 68,750,000 (under the cap) plus
    the capped 2,500,000 of fees: 71,250,000 cents."

    Design: Difficulty/dual_variant_calc/compensation_provisional_vs_final_award
    """
    ctx = _anchor_case({
        "state_code": "TX", "name": "Texas",
        "compensation_cap_cents": ANCHOR_CAP_CENTS,
        "actual_innocence_enhancement_pct": 10,
    })
    assert ctx["case"]["exculpatory_evidence_flag"] is True

    claim = create_compensation_claim(
        ctx["case"]["id"],
        years_incarcerated_claimed=10,
        documented_legal_fees_cents=ANCHOR_FEES_CENTS,
    )
    # PROVISIONAL: flat 5,000,000 x 10 DECLARED years; the 100,000,000 cap
    # does not bind; no enhancement, no fees.
    assert claim["provisional_estimate_cents"] == ANCHOR_PROVISIONAL_CENTS
    assert claim["final_award_cents"] is None

    file_claim(claim["id"])
    approved = record_claim_decision(claim["id"], "APPROVED")
    # FINAL_VERIFIED: 62,500,000 tiered base x 1.10 = 68,750,000 (under the
    # cap), plus min(3,000,000 fees, 2,500,000 ceiling) = 71,250,000.
    assert approved["final_award_cents"] == ANCHOR_FINAL_AWARD_CENTS
    assert approved["final_award_cents"] != claim["provisional_estimate_cents"], (
        "identical case data, two variant-legal answers"
    )


def test_provisional_uses_declared_years_final_uses_verified(api):
    """PRD section 3.8: "The provisional estimate is deliberately simple: a
    flat 5,000,000 cents per claimed year, capped at the jurisdiction's
    `compensation_cap_cents` when that cap is not null — with no exculpatory
    enhancement and no fee reimbursement."
    PRD section 3.8: "`verified_years` is the whole-year floor of the days
    between the intake request's `conviction_date` and the case's
    `exoneration_date`, reached through the case's `intake_request_id`,
    dividing the UTC day count by 365 and discarding the remainder."

    Design: Difficulty/dual_variant_calc/compensation_provisional_vs_final_award
    """
    ctx = _anchor_case({
        "state_code": "TX", "name": "Texas",
        "compensation_cap_cents": ANCHOR_CAP_CENTS,
        "actual_innocence_enhancement_pct": 10,
    })
    assert ctx["case"]["exoneration_date"] is not None
    assert ctx["case"]["exoneration_date"].startswith("2026-11-20T00:00:00")

    claim = create_compensation_claim(
        ctx["case"]["id"],
        years_incarcerated_claimed=10,
        documented_legal_fees_cents=ANCHOR_FEES_CENTS,
    )
    assert_compensation_claim(claim)
    assert_integer_cents(claim["provisional_estimate_cents"])

    file_claim(claim["id"])
    approved = record_claim_decision(claim["id"], "APPROVED")
    assert_integer_cents(approved["final_award_cents"])
    assert approved["final_award_cents"] == 71_250_000
    # floor(3902 / 365) == 10 verified years, matching the declared 10 here;
    # the VARIANTS still differ because the rates and fee/enhancement rules do.
    assert approved["provisional_estimate_cents"] == 50_000_000


def test_final_award_evaluation_order_cap_bites_before_fees(api):
    """PRD section 3.8: "With the same facts but a cap of 60,000,000 cents,
    the cap bites the enhanced base first and the fees still ride on top:
    60,000,000 plus 2,500,000 equals 62,500,000 cents."
    PRD section 3.8: "the fee reimbursement is added: the lesser of
    `documented_legal_fees_cents` and the 2,500,000-cent reimbursement
    ceiling. The cap never eats the fee reimbursement."

    Design: Difficulty/combinatorial_formula/compensation_tiered_cap_fee_ordering
    """
    ctx = _anchor_case({
        "state_code": "OH", "name": "Ohio",
        "compensation_cap_cents": ANCHOR_BITING_CAP_CENTS,
        "actual_innocence_enhancement_pct": 10,
    })
    claim = create_compensation_claim(
        ctx["case"]["id"],
        years_incarcerated_claimed=10,
        documented_legal_fees_cents=ANCHOR_FEES_CENTS,
    )
    file_claim(claim["id"])
    approved = record_claim_decision(claim["id"], "APPROVED")
    # min(68,750,000 enhanced, 60,000,000 cap) = 60,000,000; + 2,500,000 fees
    # AFTER the cap. A fees-before-cap reading yields 60,000,000; a flat-rate
    # reading yields 52,500,000 + fees — both are wrong.
    assert approved["final_award_cents"] == ANCHOR_CAPPED_FINAL_AWARD_CENTS


def test_final_award_cap_bites_enhanced_base_not_provisional(api):
    """PRD section 3.8: "the award before fees is the lesser of the enhanced
    tiered base and `compensation_cap_cents`, or the enhanced base itself when
    the cap is null."
    PRD section 3.8: "The provisional estimate is deliberately simple: a flat
    5,000,000 cents per claimed year, capped at the jurisdiction's
    `compensation_cap_cents` when that cap is not null — with no exculpatory
    enhancement and no fee reimbursement."

    Design: Difficulty/combinatorial_formula/compensation_tiered_cap_fee_ordering
    """
    ctx = _anchor_case({
        "state_code": "OH", "name": "Ohio",
        "compensation_cap_cents": ANCHOR_BITING_CAP_CENTS,
        "actual_innocence_enhancement_pct": 10,
    })
    claim = create_compensation_claim(
        ctx["case"]["id"],
        years_incarcerated_claimed=10,
        documented_legal_fees_cents=ANCHOR_FEES_CENTS,
    )
    # The 60,000,000 cap does not bind the provisional estimate (50,000,000).
    assert claim["provisional_estimate_cents"] == 50_000_000

    file_claim(claim["id"])
    approved = record_claim_decision(claim["id"], "APPROVED")
    assert approved["status"] == "APPROVED"
    assert approved["final_award_cents"] == 62_500_000
    assert approved["paid_amount_cents"] is None
