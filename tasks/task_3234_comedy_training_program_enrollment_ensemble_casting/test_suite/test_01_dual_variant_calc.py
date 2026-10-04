"""Difficulty rule: dual_variant_calc — placement variant and refund variant tests."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, reset_clock,
    create_placement_evaluation_payload, get_student, get_placement,
    setup_open_term_with_section, enroll_with_fresh_version, confirm_enrollment,
    drop_enrollment, invoice_id_for_enrollment, pay_invoice, get_invoice,
    get_enrollment, set_clock,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
FO = TEST_USERS["finance_officer_headers"]


def _placement_variant_setup():
    """L1 (no bypass) + L2 (bypass). Two students, two evaluations."""
    reset_clock()
    lvl1 = create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    s1 = create_student()
    s2 = create_student()
    pe1 = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(s1["id"], lvl2["id"],
                                            prior_institution="UCB", portfolio_score=0), PO), 201)
    pe2 = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(s2["id"], lvl2["id"],
                                            prior_institution="Unknown School", portfolio_score=0), PO), 201)
    return lvl1, lvl2, s1, s2, pe1, pe2


class TestPlacementCreditVariants:
    def test_audition_bypass_variant_grants_with_zero_portfolio(self):
        """PRD §3.3: "Granting an `AUDITION_BYPASS` petition requires the institution
        to be one of the four recognized names — otherwise `ERR_UNRECOGNIZED_INSTITUTION`
        (HTTP 422) — and ignores the portfolio score entirely, granting on
        institutional reputation alone."
        PRD §3.3: "On a grant, the server computes `granted_level_codes` as the
        target level plus every prerequisite level below it in the same track,
        walking the `requires_level_code` chain transitively, and unions those codes
        into the student's `placement_credit_codes`."

        Design: Difficulty/dual_variant_calc/placement_credit_audition_bypass_vs_portfolio_review
        """
        lvl1, lvl2, s1, s2, pe1, pe2 = _placement_variant_setup()
        assert pe1["variant"] == "AUDITION_BYPASS"
        validate_success(api_client.begin_review_placement(pe1["id"], PO))
        granted = validate_success(api_client.grant_placement(pe1["id"], PO))
        assert granted["decision"] == "GRANTED"
        stu = get_student(s1["id"])
        assert "L1" in stu["placement_credit_codes"]
        assert "L2" in stu["placement_credit_codes"]

    def test_portfolio_review_variant_zero_score_cannot_be_granted(self):
        """PRD §3.3: "Granting a `PORTFOLIO_REVIEW` petition requires a
        `portfolio_score` of at least 70 — below that threshold the grant fails with
        `ERR_PORTFOLIO_SCORE_TOO_LOW` (HTTP 422)."
        PRD §3.3: "when the institution is one of iO, UCB, Groundlings, or Second
        City (another campus), the variant is `AUDITION_BYPASS`; otherwise —
        including an empty institution string — it is `PORTFOLIO_REVIEW`."

        Design: Difficulty/dual_variant_calc/placement_credit_audition_bypass_vs_portfolio_review
        """
        lvl1, lvl2, s1, s2, pe1, pe2 = _placement_variant_setup()
        assert pe2["variant"] == "PORTFOLIO_REVIEW"
        validate_success(api_client.begin_review_placement(pe2["id"], PO))
        resp = api_client.grant_placement(pe2["id"], PO)
        validate_error(resp, ApiErrorId.ERR_PORTFOLIO_SCORE_TOO_LOW, 422)
        denied = validate_success(api_client.deny_placement(pe2["id"], PO))
        assert denied["decision"] == "DENIED"
        stu = get_student(s2["id"])
        assert stu["placement_credit_codes"] == []


def _refund_setup():
    """Open term + section, two students enrolled & confirmed, both invoices paid $100."""
    ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
    s1 = create_student()
    s2 = create_student()
    e1 = enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
    e2 = enroll_with_fresh_version(s2["id"], ctx["section"]["id"])
    confirm_enrollment(e1["id"])
    confirm_enrollment(e2["id"])
    inv1 = invoice_id_for_enrollment(e1["id"])
    inv2 = invoice_id_for_enrollment(e2["id"])
    pay_invoice(inv1, 10000)
    pay_invoice(inv2, 10000)
    return ctx, e1, e2, inv1, inv2


class TestTuitionRefundVariants:
    def test_early_drop_refunds_full_amount(self):
        """PRD §3.3: "Before the term's `drop_deadline_utc`, a drop is early: a
        `CONFIRMED` enrollment moves to `DROPPED_EARLY`, the section's
        `enrolled_count` falls by 1, the attached invoice is refunded in full (100%
        of what was paid), and the vacancy triggers the seat-allocation waterfall
        below."

        Design: Difficulty/dual_variant_calc/tuition_refund_early_drop_vs_late_drop
        """
        ctx, e1, e2, inv1, inv2 = _refund_setup()
        set_clock("2027-01-10T00:00:00Z")  # before drop_deadline 2027-01-12
        dropped = drop_enrollment(e1["id"])
        assert dropped["status"] == "DROPPED_EARLY"
        invoice = get_invoice(inv1)
        assert invoice["status"] == "REFUNDED"
        assert invoice["refunded_cents"] == 10000

    def test_late_drop_refunds_quarter_at_half_to_three_quarters_elapsed(self):
        """PRD §3.4: "If the elapsed fraction is under one quarter of the term, the
        student is refunded three quarters of `paid_cents`; from one quarter up to
        one half, one half of `paid_cents`; from one half up to three quarters, one
        quarter of `paid_cents`; at three quarters or beyond, nothing."
        PRD §3.3: "After the deadline, only a `CONFIRMED` enrollment may drop; it
        becomes `DROPPED_LATE`, the section's `enrolled_count` falls by 1, the
        invoice is refunded on the tiered schedule described in §3.4, and the
        waterfall runs."

        Design: Difficulty/dual_variant_calc/tuition_refund_early_drop_vs_late_drop
        """
        ctx, e1, e2, inv1, inv2 = _refund_setup()
        # 2027-02-20 is (46/69) ≈ 0.667 elapsed -> tier [0.50, 0.75) -> refund 25%
        set_clock("2027-02-20T00:00:00Z")
        dropped = drop_enrollment(e2["id"])
        assert dropped["status"] == "DROPPED_LATE"
        invoice = get_invoice(inv2)
        assert invoice["status"] == "REFUNDED"
        assert invoice["refunded_cents"] == 2500
