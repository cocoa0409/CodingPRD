"""Difficulty rule: compensating_invariant — enrolled_count conservation and
paid/refund cash conservation."""
from test_helpers import (
    TEST_USERS, api_client, validate_success,
    create_student, set_clock, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, drop_enrollment, get_section,
    invoice_id_for_enrollment, pay_invoice, get_invoice,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
FO = TEST_USERS["finance_officer_headers"]


class TestEnrolledCountConservation:
    def test_confirm_increments_enrolled_count_by_one(self):
        """PRD §3.3: "Confirmation moves the enrollment `REGISTERED → CONFIRMED`,
        raises the section's `enrolled_count` by 1, and increments the section's
        `version`."

        Design: Difficulty/compensating_invariant/enrollment_confirm_drop_conserves_enrolled_count
        """
        ctx = setup_open_term_with_section(capacity=4)
        assert ctx["section"]["enrolled_count"] == 0
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        section = get_section(ctx["section"]["id"])
        assert section["enrolled_count"] == 1

    def test_confirm_then_drop_restores_enrolled_count(self):
        """PRD §3.3: "Before the term's `drop_deadline_utc`, a drop is early: a
        `CONFIRMED` enrollment moves to `DROPPED_EARLY`, the section's
        `enrolled_count` falls by 1, the attached invoice is refunded in full (100%
        of what was paid), and the vacancy triggers the seat-allocation waterfall
        below."

        Design: Difficulty/compensating_invariant/enrollment_confirm_drop_conserves_enrolled_count
        """
        ctx = setup_open_term_with_section(capacity=4)
        initial = ctx["section"]["enrolled_count"]
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        assert get_section(ctx["section"]["id"])["enrolled_count"] == initial + 1
        drop_enrollment(enr["id"])
        assert get_section(ctx["section"]["id"])["enrolled_count"] == initial


class TestInvoiceCashConservation:
    def test_early_drop_full_refund_nets_zero(self):
        """PRD §3.4: "When the refund cascades from an early drop or a section
        cancellation, the invoice goes to `REFUNDED` and `refunded_cents` covers
        everything — the full `paid_cents` plus the `scholarship_applied_cents`
        portion is unwound."

        Design: Difficulty/compensating_invariant/tuition_invoice_pay_refund_conserves_cash_total
        """
        ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        inv = invoice_id_for_enrollment(enr["id"])
        pay_invoice(inv, 10000)
        set_clock("2027-01-10T00:00:00Z")  # before drop deadline
        drop_enrollment(enr["id"])
        invoice = get_invoice(inv)
        assert invoice["paid_cents"] == 10000
        assert invoice["refunded_cents"] == 10000
        assert invoice["paid_cents"] - invoice["refunded_cents"] == 0

    def test_early_drop_refunded_invoice_terminal(self):
        """PRD §3.4: "the invoice goes to `REFUNDED` and `refunded_cents` covers
        everything — the full `paid_cents` plus the `scholarship_applied_cents`
        portion is unwound."

        Design: Difficulty/compensating_invariant/tuition_invoice_pay_refund_conserves_cash_total
        """
        ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        inv = invoice_id_for_enrollment(enr["id"])
        pay_invoice(inv, 10000)
        set_clock("2027-01-10T00:00:00Z")
        drop_enrollment(enr["id"])
        invoice = get_invoice(inv)
        assert invoice["status"] == "REFUNDED"
