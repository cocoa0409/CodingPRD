"""Difficulty rule: boundary_precision_check — drop deadline and section capacity."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_student, set_clock, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, drop_enrollment,
    invoice_id_for_enrollment, pay_invoice, get_invoice, get_enrollment, get_section,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
FO = TEST_USERS["finance_officer_headers"]


class TestDropDeadlineBoundary:
    def test_drop_at_exactly_deadline_is_early_with_full_refund(self):
        """PRD §3.3: "Before the term's `drop_deadline_utc`, a drop is early: a
        `CONFIRMED` enrollment moves to `DROPPED_EARLY`, the section's
        `enrolled_count` falls by 1, the attached invoice is refunded in full (100%
        of what was paid)"

        Design: Difficulty/boundary_precision_check/drop_deadline_boundary_at_exactly_deadline
        """
        ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        inv = invoice_id_for_enrollment(enr["id"])
        pay_invoice(inv, 10000)
        # Clock exactly at drop_deadline (inclusive of deadline -> early)
        set_clock("2027-01-12T00:00:00Z")
        dropped = drop_enrollment(enr["id"])
        assert dropped["status"] == "DROPPED_EARLY"
        invoice = get_invoice(inv)
        assert invoice["refunded_cents"] == 10000

    def test_drop_after_deadline_is_late(self):
        """PRD §3.3: "After the deadline, only a `CONFIRMED` enrollment may drop; it
        becomes `DROPPED_LATE`, the section's `enrolled_count` falls by 1, the
        invoice is refunded on the tiered schedule described in §3.4, and the
        waterfall runs."

        Design: Difficulty/boundary_precision_check/drop_deadline_boundary_at_exactly_deadline
        """
        ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
        student = create_student()
        enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
        confirm_enrollment(enr["id"])
        set_clock("2027-01-12T00:00:01Z")  # one second past the deadline
        dropped = drop_enrollment(enr["id"])
        assert dropped["status"] == "DROPPED_LATE"


class TestSectionCapacityBoundary:
    def _setup(self):
        """capacity=1; s1 CONFIRMED fills the section; s2 REGISTERED after promotion."""
        ctx = setup_open_term_with_section(capacity=1)
        s1 = create_student()
        s2 = create_student()
        e1 = enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
        confirm_enrollment(e1["id"])
        e2 = enroll_with_fresh_version(s2["id"], ctx["section"]["id"])
        assert e2["status"] == "WAITLISTED"
        # Free the seat: s1 drops -> s2 promoted to REGISTERED
        drop_enrollment(e1["id"])
        assert get_enrollment(e2["id"])["status"] == "REGISTERED"
        # Re-enroll s1 (vacancy exists again: enrolled_count==0)
        e1b = enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
        assert e1b["status"] == "REGISTERED"
        # Confirm s2 to reach exactly capacity
        confirm_enrollment(e2["id"])
        return ctx, s1, s2, e2, e1b

    def test_confirm_into_section_at_exact_capacity_rejected(self):
        """PRD §3.3: "A `REGISTERED` enrollment is confirmed by the owning student
        or the Registrar, but only while the section is `OPEN` or `LOCKED` and still
        has a vacant seat; confirming into a full section fails with
        `ERR_SECTION_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/section_capacity_boundary_full_at_exactly_capacity
        """
        ctx, s1, s2, e2, e1b = self._setup()
        resp = api_client.confirm_enrollment(e1b["id"], REG)
        validate_error(resp, ApiErrorId.ERR_SECTION_FULL, 409)

    def test_failed_confirm_leaves_enrollment_and_counts_unchanged(self):
        """PRD §3.2: "Sections track two computed occupancy counters:
        `enrolled_count`, the number of enrollments in `REGISTERED` or `CONFIRMED`,
        and `waitlist_count`, the number in `WAITLISTED`. Both counters move only as
        enrollment events dictate."

        Design: Difficulty/boundary_precision_check/section_capacity_boundary_full_at_exactly_capacity
        """
        ctx, s1, s2, e2, e1b = self._setup()
        validate_error(api_client.confirm_enrollment(e1b["id"], REG),
                       ApiErrorId.ERR_SECTION_FULL, 409)
        assert get_enrollment(e1b["id"])["status"] == "REGISTERED"
        section = get_section(ctx["section"]["id"])
        assert section["enrolled_count"] == 1  # exactly capacity
