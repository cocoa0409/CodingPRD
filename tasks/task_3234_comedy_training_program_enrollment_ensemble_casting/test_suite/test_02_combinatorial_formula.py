"""Difficulty rule: combinatorial_formula — composite score and tuition balance."""
import pytest
from test_helpers import (
    TEST_USERS, api_client, validate_success, ApiErrorId,
    create_student, reset_clock, create_audition_payload,
    setup_open_term_with_section, enroll_with_fresh_version,
    invoice_id_for_enrollment, get_invoice, get_scholarship,
    create_scholarship_payload,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
CD = TEST_USERS["casting_director_headers"]
FO = TEST_USERS["finance_officer_headers"]


class TestEnsembleCompositeScore:
    def test_full_rubric_weighted_score(self):
        """PRD §3.7: "each dimension's rubric score is multiplied by that
        dimension's weight — scene work counts for 40%, characters for 25%,
        musicality for 20%, and game for 15% — the products are summed, dimensions
        missing from the rubric contribute zero, and the total is rounded half-up to
        two decimal places."

        Design: Difficulty/combinatorial_formula/ensemble_composite_score_weighted_multi_input
        """
        reset_clock()
        student = create_student()
        aud = validate_success(api_client.create_audition(
            create_audition_payload(student["id"], "ENSEMBLE",
                                    rubric_scores={"scene_work": 8, "characters": 7,
                                                   "musicality": 9, "game": 6}), CD), 201)
        evaluated = validate_success(api_client.evaluate_audition(aud["id"], CD))
        assert evaluated["outcome"] == "EVALUATED"
        # 0.4*8 + 0.25*7 + 0.2*9 + 0.15*6 = 3.2+1.75+1.8+0.9 = 7.65
        assert evaluated["composite_score"] == pytest.approx(7.65, abs=0.001)

    def test_missing_dimension_contributes_zero(self):
        """PRD §3.7: "each dimension's rubric score is multiplied by that
        dimension's weight — scene work counts for 40%, characters for 25%,
        musicality for 20%, and game for 15% — the products are summed, dimensions
        missing from the rubric contribute zero, and the total is rounded half-up to
        two decimal places."

        Design: Difficulty/combinatorial_formula/ensemble_composite_score_weighted_multi_input
        """
        reset_clock()
        student = create_student()
        aud = validate_success(api_client.create_audition(
            create_audition_payload(student["id"], "ENSEMBLE",
                                    rubric_scores={"scene_work": 8, "characters": 7,
                                                   "musicality": 9}), CD), 201)
        evaluated = validate_success(api_client.evaluate_audition(aud["id"], CD))
        assert evaluated["outcome"] == "EVALUATED"
        # 3.2 + 1.75 + 1.8 + 0.15*0 = 6.75
        assert evaluated["composite_score"] == pytest.approx(6.75, abs=0.001)


class TestTuitionBalanceFifoDisbursement:
    def _setup_with_two_awards(self):
        ctx = setup_open_term_with_section(capacity=4, tuition_cents=5000)
        student = create_student()
        sch1 = validate_success(api_client.create_scholarship(
            create_scholarship_payload(student["id"], kind="NEED_BASED",
                                       amount_cents=2000), FO), 201)
        sch2 = validate_success(api_client.create_scholarship(
            create_scholarship_payload(student["id"], kind="DIVERSITY",
                                       amount_cents=1500), FO), 201)
        validate_success(api_client.award_scholarship(sch1["id"], FO))
        validate_success(api_client.award_scholarship(sch2["id"], FO))
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        return ctx, student, sch1, sch2, enr

    def test_fifo_disbursement_applies_both_awards(self):
        """PRD §3.4: "scholarships in `AWARDED` or `DISBURSED` status are applied
        oldest-first by award `created_at`, each application limited so that the
        cumulative `disbursed_cents` of an award never exceeds its `amount_cents`"

        Design: Difficulty/combinatorial_formula/tuition_balance_evaluation_order_circular
        """
        ctx, student, sch1, sch2, enr = self._setup_with_two_awards()
        inv_id = invoice_id_for_enrollment(enr["id"])
        invoice = get_invoice(inv_id)
        assert invoice["base_amount_cents"] == 5000
        assert invoice["scholarship_applied_cents"] == 3500
        assert invoice["amount_due_cents"] == 1500

    def test_disbursed_amounts_and_statuses_update(self):
        """PRD §3.4: "An award disburses automatically — `AWARDED → DISBURSED` —
        when an invoice is issued against the student while that student holds the
        award and has an invoice outstanding in `ISSUED` or `PARTIALLY_PAID`; the
        award's `disbursed_cents` rises by the amount applied and the invoice's
        `scholarship_applied_cents` and `amount_due_cents` recompute as above."

        Design: Difficulty/combinatorial_formula/tuition_balance_evaluation_order_circular
        """
        ctx, student, sch1, sch2, enr = self._setup_with_two_awards()
        invoice_id_for_enrollment(enr["id"])  # ensure the invoice exists
        s1 = get_scholarship(sch1["id"])
        s2 = get_scholarship(sch2["id"])
        assert s1["disbursed_cents"] == 2000
        assert s2["disbursed_cents"] == 1500
        assert s1["status"] == "DISBURSED"
        assert s2["status"] == "DISBURSED"
