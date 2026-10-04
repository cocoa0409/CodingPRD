"""Difficulty rule: priority_pair_validation_conflict — error precedence pairs."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, create_instructor,
    create_section_payload, create_enrollment_payload, reset_clock,
    setup_open_term_with_section, enroll_with_fresh_version, confirm_enrollment,
    grant_placement, get_section,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]


class TestStateBeatsPrerequisite:
    def _cancelled_section_setup(self):
        reset_clock()
        create_level(code="L1", allows_placement_bypass=False)
        lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                            allows_placement_bypass=True)
        term = create_term_draft()
        instructor = create_instructor()
        validate_success(api_client.open_scheduling(term["id"], PD))
        section = validate_success(api_client.create_section(
            create_section_payload(term["id"], lvl2["id"], instructor["id"],
                                   capacity=2), PD), 201)
        validate_success(api_client.cancel_section(section["id"], PD))
        student = create_student()
        return section, student

    def test_enroll_into_cancelled_section_returns_invalid_state_not_prerequisite(self):
        """PRD §2.7: "then whether the target entity's current state permits the
        requested transition (`ERR_INVALID_STATE`), then temporal rules against the
        logical clock (`ERR_DEADLINE_PASSED`), and only then business rules such as
        prerequisite satisfaction, instructor availability, venue conflicts,
        source-policy compliance, section capacity, scholarship balances, placement
        eligibility, and understudy eligibility."
        PRD §3.3: "a gap anywhere in the chain rejects the enrollment with
        `ERR_PREREQUISITE_NOT_MET` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_prerequisite_enroll_into_terminal_section
        """
        section, student = self._cancelled_section_setup()
        section_now = get_section(section["id"])
        resp = api_client.create_enrollment(
            create_enrollment_payload(student["id"], section["id"],
                                      section_now["version"]), REG)
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert data["error_id"] != "ERR_PREREQUISITE_NOT_MET"
        assert data["error_id"] != "ERR_STALE_VERSION"

    def test_prerequisite_alone_still_blocks_into_open_section(self):
        """PRD §3.3: "the union of the student's `completed_level_codes` and
        `placement_credit_codes` must contain the code of every level in the
        transitive prerequisite closure of the section's level within the same
        track; a gap anywhere in the chain rejects the enrollment with
        `ERR_PREREQUISITE_NOT_MET` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_prerequisite_enroll_into_terminal_section
        """
        reset_clock()
        create_level(code="L1", allows_placement_bypass=False)
        lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                            allows_placement_bypass=True)
        term2 = create_term_draft(name="T2")
        instructor = create_instructor()
        validate_success(api_client.open_scheduling(term2["id"], PD))
        section2 = validate_success(api_client.create_section(
            create_section_payload(term2["id"], lvl2["id"], instructor["id"],
                                   capacity=2), PD), 201)
        validate_success(api_client.open_enrollment(term2["id"], PD))
        student = create_student()
        section_now = get_section(section2["id"])
        resp = api_client.create_enrollment(
            create_enrollment_payload(student["id"], section2["id"],
                                      section_now["version"]), REG)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET, 422)


class TestPrerequisiteBeatsSectionFull:
    def _full_l2_section_setup(self):
        """L2 section capacity=1 filled by a placement-credited student; s2 has no credit."""
        reset_clock()
        create_level(code="L1", allows_placement_bypass=False)
        lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                            allows_placement_bypass=True)
        term = create_term_draft()
        instructor = create_instructor()
        validate_success(api_client.open_scheduling(term["id"], PD))
        section = validate_success(api_client.create_section(
            create_section_payload(term["id"], lvl2["id"], instructor["id"],
                                   capacity=1), PD), 201)
        validate_success(api_client.open_enrollment(term["id"], PD))
        s1 = create_student()
        s2 = create_student()
        grant_placement(s1["id"], lvl2["id"])
        e1 = enroll_with_fresh_version(s1["id"], section["id"])
        confirm_enrollment(e1["id"])
        return section, s1, s2, lvl2

    def test_prerequisite_not_met_returned_even_when_section_full(self):
        """PRD §2.7: "and only then business rules such as prerequisite
        satisfaction, instructor availability, venue conflicts, source-policy
        compliance, section capacity, scholarship balances, placement eligibility,
        and understudy eligibility."
        PRD §3.3: "a gap anywhere in the chain rejects the enrollment with
        `ERR_PREREQUISITE_NOT_MET` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/prerequisite_vs_section_full_enroll_blocks
        """
        section, s1, s2, lvl2 = self._full_l2_section_setup()
        section_now = get_section(section["id"])
        resp = api_client.create_enrollment(
            create_enrollment_payload(s2["id"], section["id"],
                                      section_now["version"]), REG)
        data = validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET, 422)
        assert data["error_id"] != "ERR_SECTION_FULL"

    def test_waitlist_birth_with_prerequisite_satisfied(self):
        """PRD §3.3: "If the section's `enrolled_count` has reached `capacity`, the
        new enrollment is born directly into `WAITLISTED` and the section's
        `waitlist_count` rises by 1."

        Design: Difficulty/priority_pair_validation_conflict/prerequisite_vs_section_full_enroll_blocks
        """
        section, s1, s2, lvl2 = self._full_l2_section_setup()
        # Give s2 the same placement credit so prerequisites are satisfied, then
        # confirm the section-full path produces a WAITLISTED enrollment (no error).
        grant_placement(s2["id"], lvl2["id"])
        section_now = get_section(section["id"])
        e2 = validate_success(api_client.create_enrollment(
            create_enrollment_payload(s2["id"], section["id"],
                                      section_now["version"]), REG), 201)
        assert e2["status"] == "WAITLISTED"
