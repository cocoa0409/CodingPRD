"""Difficulty rule: cross_entity_state_dependency — term gating on sections and
cast lock gating on venue slot."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, create_instructor,
    create_section_payload, reset_clock, get_term, get_section, get_venue_slot,
    get_cast, create_venue_slot, create_ensemble_cast_payload,
    create_evaluated_audition,
)

PD = TEST_USERS["program_director_headers"]
CD = TEST_USERS["casting_director_headers"]


class TestTermOpenEnrollmentGate:
    def _setup_unstaffed(self):
        reset_clock()
        level = create_level()
        term = create_term_draft()
        instructor = create_instructor()
        validate_success(api_client.open_scheduling(term["id"], PD))
        sec_a = validate_success(api_client.create_section(
            create_section_payload(term["id"], level["id"], instructor["id"],
                                   capacity=2), PD), 201)
        payload = create_section_payload(term["id"], level["id"], None, capacity=2)
        payload.pop("instructor_id")
        sec_b = validate_success(api_client.create_section(payload, PD), 201)
        return term, sec_a, sec_b

    def test_open_enrollment_with_unstaffed_section_rejected(self):
        """PRD §3.1: "Opening enrollment moves it `SCHEDULING → ENROLLMENT_OPEN`,
        but only after a staffing audit: every non-cancelled section in the term
        must have an instructor assigned, and if any does not, the transition is
        refused with `ERR_SECTION_UNSTAFFED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/term_open_enrollment_gates_section_draft_to_open
        """
        term, sec_a, sec_b = self._setup_unstaffed()
        resp = api_client.open_enrollment(term["id"], PD)
        validate_error(resp, ApiErrorId.ERR_SECTION_UNSTAFFED, 409)

    def test_failed_open_enrollment_leaves_states_unchanged(self):
        """PRD §3.1: "When the audit passes, every section of the term still in
        `DRAFT` cascades to `OPEN` in the same operation."

        Design: Difficulty/cross_entity_state_dependency/term_open_enrollment_gates_section_draft_to_open
        """
        term, sec_a, sec_b = self._setup_unstaffed()
        validate_error(api_client.open_enrollment(term["id"], PD),
                       ApiErrorId.ERR_SECTION_UNSTAFFED, 409)
        assert get_term(term["id"])["status"] == "SCHEDULING"
        assert get_section(sec_a["id"])["status"] == "DRAFT"


class TestLockCastVenueGate:
    def _setup_casting_full_unbooked(self):
        reset_clock()
        slot = create_venue_slot()
        cast = validate_success(api_client.create_ensemble_cast(
            create_ensemble_cast_payload(slot["id"], cast_size=1,
                                         understudy_slots=0), CD), 201)
        student = create_student()
        create_evaluated_audition(student["id"], "ENSEMBLE",
                                  ensemble_cast_id=cast["id"],
                                  rubric_scores={"scene_work": 9, "characters": 9,
                                                 "musicality": 9, "game": 9})
        validate_success(api_client.open_casting(cast["id"], CD))
        cast = validate_success(api_client.cast_ensemble(cast["id"], CD))
        return cast, slot

    def test_lock_cast_with_unbooked_slot_rejected(self):
        """PRD §3.8: "Locking also requires the roster to be complete — exactly
        `cast_size` principals and exactly `understudy_slots` understudies — and the
        opening-night venue slot to be `BOOKED`"

        Design: Difficulty/cross_entity_state_dependency/ensemble_lock_cast_gates_on_venue_slot_booked
        """
        cast, slot = self._setup_casting_full_unbooked()
        resp = api_client.lock_cast(cast["id"], cast["version"], CD)
        assert resp.status_code == 409
        assert get_cast(cast["id"])["status"] == "CASTING"
        assert get_venue_slot(slot["id"])["status"] == "AVAILABLE"

    def test_casting_selector_filled_principal_ids(self):
        """PRD §3.8: "The top `cast_size` candidates become principals and the next
        `understudy_slots` become understudies, populating `principal_ids` and
        `understudy_ids`; each chosen audition transitions to `SELECTED`."

        Design: Difficulty/cross_entity_state_dependency/ensemble_lock_cast_gates_on_venue_slot_booked
        """
        cast, slot = self._setup_casting_full_unbooked()
        assert len(cast["principal_ids"]) == 1
        assert len(cast["understudy_ids"]) == 0
