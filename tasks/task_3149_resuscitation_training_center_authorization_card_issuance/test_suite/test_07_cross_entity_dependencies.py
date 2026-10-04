"""Cross-entity state dependencies: parent state gates child operations."""
from test_helpers import (
    ADMIN,
    COORD,
    TC,
    ApiErrorId,
    align_center_site,
    align_instructor,
    certify_candidate,
    create_center_with_faculty,
    create_course_session_payload,
    create_guidelines_version_active,
    create_instructor_payload,
    create_site_payload,
    get_success_data,
    setup_teaching_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    create_scheduled_session,
)


class TestSessionCreateRequiresCenterActive:
    def test_provisional_center_rejects_session_create(self, api):
        """PRD §3.4: "The center gate runs first. The session's center must be
        in a status that permits scheduling; a `SUSPENDED` or `REVOKED` center
        rejects with `ERR_CENTER_SUSPENDED`, and a `PROVISIONAL` or `PROBATION`
        center rejects with `ERR_CENTER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/session_create_requires_center_active
        """
        # Full chain EXCEPT the center is never activated (alignment under
        # PROVISIONAL is legal per PRD §3.1).
        center, faculty = create_center_with_faculty()
        site = get_success_data(api.create_site(
            center["id"], create_site_payload(), TC))
        align_center_site(center["id"], site["id"])
        gv = create_guidelines_version_active()
        lead = certify_candidate(center["id"], faculty["id"])
        align_instructor(center["id"], lead["id"])

        payload = create_course_session_payload(
            center["id"], site["id"], lead["id"], gv["id"])
        resp = api.create_course_session(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_CENTER_NOT_ACTIVE)

        center_now = validate_success(api.get_training_center(center["id"], TC))
        assert center_now["status"] == "PROVISIONAL"
        _, meta = validate_paginated(
            api.list_center_sessions(center["id"], TC))
        assert meta["total_count"] == 0

    def test_session_create_succeeds_after_activation(self, api):
        """PRD §3.1: "Only once at least one site is `ALIGNED` may a
        `NationalAdmin` activate the center, moving it from `PROVISIONAL` to
        `ACTIVE`."
        PRD §3.4: "The session is created in `SCHEDULED` status with
        `seats_available` initialized to `capacity` and `cancel_reason` null."

        Design: Difficulty/cross_entity_state_dependency/session_create_requires_center_active
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        assert session["status"] == "SCHEDULED"
        assert session["seats_available"] == 6
        assert session["cancel_reason"] is None


class TestAlignmentCreateRequiresInstructorCertified:
    def test_candidate_alignment_rejected(self, api):
        """PRD §3.1: "Alignments are created by a `TCAdmin` with the
        `instructor_id` of a certified instructor and an optional `as_faculty`
        flag (defaulting to `false`)."
        PRD §2.5: "instructor is `CERTIFIED` and unexpired
        (`ERR_INSTRUCTOR_NOT_CERTIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/alignment_create_requires_instructor_certified
        """
        from test_helpers import create_center
        center = create_center()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        assert cand["status"] == "CANDIDATE"

        resp = api.create_alignment(
            center["id"],
            {"instructor_id": cand["id"], "as_faculty": False}, TC)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED)

        _, meta_c = validate_paginated(
            api.list_center_alignments(center["id"], TC))
        assert meta_c["total_count"] == 0
        _, meta_i = validate_paginated(
            api.list_instructor_alignments(cand["id"], TC))
        assert meta_i["total_count"] == 0

    def test_alignment_succeeds_after_certification(self, api):
        """PRD §3.1: "each alignment starts in `ACTIVE`."
        PRD §3.2: "Third, a `TCAdmin` certifies the candidate. Certification
        requires the instructor to currently be in `MONITORED` status
        (otherwise `ERR_INSTRUCTOR_NOT_MONITORED`)."

        Design: Difficulty/cross_entity_state_dependency/alignment_create_requires_instructor_certified
        """
        center, faculty = create_center_with_faculty()
        cand = certify_candidate(center["id"], faculty["id"])
        assert cand["status"] == "CERTIFIED"
        alignment = validate_success(
            api.create_alignment(
                center["id"],
                {"instructor_id": cand["id"], "as_faculty": False}, TC),
            expected_status=201)
        assert alignment["status"] == "ACTIVE"
        assert alignment["instructor_id"] == cand["id"]
        assert alignment["training_center_id"] == center["id"]
