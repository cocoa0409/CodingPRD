"""Corner coverage: entity creation defaults, retrieval, listing, not-found,
required fields, defaults, computed and system fields, type constraints, and
parent relationships."""
from test_helpers import (
    ADMIN,
    COORD,
    TC,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_course_session_payload,
    create_guidelines_version_payload,
    create_instructor_payload,
    create_scheduled_session,
    create_site_payload,
    create_training_center_payload,
    enroll_student,
    get_success_data,
    set_clock_start,
    setup_teaching_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_guidelines_version


class TestTrainingCenterCreation:
    def test_training_center_create_returns_defaults_and_system_fields(self, api):
        """PRD §3.1: "The new center starts in `PROVISIONAL` status with
        `cards_issued_count` and `active_card_count` both at zero,
        `probation_started_at` null, and `last_audit_opened_at` null until the
        first audit is opened against it."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/training_center_create_returns_defaults_and_system_fields
        """
        set_clock_start()
        resp = api.create_training_center(
            create_training_center_payload(
                legal_name="Prairie Heart Training Center",
                region="MIDWEST", contact_email="ops@prairie-htc.example"),
            ADMIN)
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        data = body["data"]
        assert data["status"] == "PROVISIONAL"
        assert data["cards_issued_count"] == 0
        assert data["active_card_count"] == 0
        assert data["probation_started_at"] is None
        assert data["last_audit_opened_at"] is None
        # PRD §2.7: version increments by 1 on every mutation, so a fresh row
        # is at its initial value (1).
        assert data["version"] == 1


class TestGuidelinesVersionRetrieval:
    def test_guidelines_version_get_roundtrips_all_fields(self, api):
        """PRD §3.9: "The national office publishes a `GuidelinesVersion` by
        supplying a unique `code` (for example `G2020` or `G2025`), a
        human-readable `title`, the `published_at` publication timestamp, and a
        `transition_deadline_at` instant after which `SCHEDULED` sessions on
        the superseded version are cancelled. A new version starts in `DRAFT`
        status."

        Design: Corner/entities/guidelines_version_get_roundtrips_all_fields
        """
        set_clock_start()
        created = get_success_data(api.create_guidelines_version(
            create_guidelines_version_payload(
                code="G2025", title="2025 AHA Guidelines",
                published_at="2025-10-01T00:00:00Z",
                transition_deadline_at="2027-03-01T00:00:00Z"), ADMIN))
        data = validate_success(api.get_guidelines_version(created["id"], COORD))
        assert_guidelines_version(data)
        assert data["code"] == "G2025"
        assert data["status"] == "DRAFT"
        assert data["title"] == "2025 AHA Guidelines"
        assert data["published_at"] == "2025-10-01T00:00:00Z"
        assert data["transition_deadline_at"] == "2027-03-01T00:00:00Z"


class TestSessionListingPagination:
    def test_sessions_list_paginates_total_count_and_has_more(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; if not provided, it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0."

        Design: Corner/entities/sessions_list_paginates_total_count_and_has_more
        """
        ctx = setup_teaching_scenario()
        for day in (10, 11, 12):
            create_scheduled_session(
                ctx, start_at=f"2026-10-{day}T14:00:00Z",
                end_at=f"2026-10-{day}T18:00:00Z")

        data, meta = validate_paginated(api.list_center_sessions(
            ctx["center"]["id"], TC, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(api.list_center_sessions(
            ctx["center"]["id"], TC, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        data3, meta3 = validate_paginated(
            api.list_center_sessions(ctx["center"]["id"], TC))
        assert len(data3) == 3
        assert meta3["total_count"] == 3

        data4, meta4 = validate_paginated(api.list_center_sessions(
            ctx["center"]["id"], TC, params={"status": "SCHEDULED"}))
        assert len(data4) == 3
        data5, meta5 = validate_paginated(api.list_center_sessions(
            ctx["center"]["id"], TC, params={"status": "CANCELLED"}))
        assert len(data5) == 0
        assert meta5["total_count"] == 0


class TestInstructorNotFound:
    def test_instructor_get_with_unknown_id_returns_instructor_not_found(self, api):
        """PRD §2.6: "the system validates the existence of each identifier in
        left-to-right order along the path. The request is rejected immediately
        with the 404 `error_id` corresponding to the *first* path identifier
        that does not resolve — ... `ERR_INSTRUCTOR_NOT_FOUND` for an
        instructor."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/instructor_get_with_unknown_id_returns_instructor_not_found
        """
        set_clock_start()
        resp = api.get_instructor(NON_EXISTENT_UUID, TC)
        err = validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_FOUND)
        assert "message" in err


class TestSessionCreateRequiredFields:
    def test_session_create_missing_capacity_returns_invalid_request(self, api):
        """PRD §3.4: "A `TCCoordinator` schedules a `CourseSession` by
        supplying ... the `capacity` (an integer of at least 1)."
        PRD §2.5: "4. **Request shape.** Required fields present, enum members
        drawn from the declared sets, integer fields carrying integer values
        within sane ranges, and `end_at` strictly after `start_at`. Failures
        yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/session_create_missing_capacity_returns_invalid_request
        """
        ctx = setup_teaching_scenario()
        payload = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"])
        del payload["capacity"]
        resp = api.create_course_session(payload, COORD)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert err["error_id"] != ApiErrorId.ERR_CAPACITY_EXCEEDS_SITE
        _, meta = validate_paginated(
            api.list_center_sessions(ctx["center"]["id"], TC))
        assert meta["total_count"] == 0


class TestRosterEntryDefaults:
    def test_roster_entry_omitting_prior_card_defaults_to_non_renewal(self, api):
        """PRD §3.7: "the `prior_card_id` copied from the roster entry when
        this is a renewal (otherwise null); an `is_renewal` boolean set to
        `true` exactly when `prior_card_id` is set."
        PRD §3.6: "Enrollment creates a `RosterEntry` — its `course_session_id`
        is taken from the path — in `ENROLLED` status with `remediation_used`
        initially `false`."

        Design: Corner/entities/roster_entry_omitting_prior_card_defaults_to_non_renewal
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        assert entry["prior_card_id"] is None
        assert entry["remediation_used"] is False
        assert entry["status"] == "ENROLLED"


class TestComputedAndSystemFields:
    def test_seats_available_is_computed_and_client_value_ignored(self, api):
        """PRD §3.4: "The session is created in `SCHEDULED` status with
        `seats_available` initialized to `capacity` and `cancel_reason` null."
        PRD §3.11: "Seat conservation: for every session, `seats_available`
        plus the number of roster entries on that session whose status is
        `ENROLLED` equals the session's `capacity`."

        Design: Corner/entities/seats_available_is_computed_and_client_value_ignored
        """
        ctx = setup_teaching_scenario()
        payload = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"], capacity=6)
        payload["seats_available"] = 0  # client smuggle must be ignored
        data = validate_success(
            api.create_course_session(payload, COORD), expected_status=201)
        assert data["seats_available"] == 6
        assert data["status"] == "SCHEDULED"

    def test_session_create_system_fields_status_and_version_are_server_owned(self, api):
        """PRD §3.4: "The session is created in `SCHEDULED` status with
        `seats_available` initialized to `capacity` and `cancel_reason` null."
        PRD §2.7: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource."

        Design: Corner/entities/session_create_system_fields_status_and_version_are_server_owned
        """
        ctx = setup_teaching_scenario()
        payload = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"], capacity=6)
        payload["status"] = "IN_PROGRESS"  # client smuggle must be ignored
        payload["version"] = 99
        data = validate_success(
            api.create_course_session(payload, COORD), expected_status=201)
        assert data["status"] == "SCHEDULED"
        assert data["version"] == 1
        assert data["cancel_reason"] is None


class TestInstructorTypeConstraints:
    def test_instructor_create_with_out_of_enum_discipline_returns_invalid_request(self, api):
        """PRD §3.2: "Instructors enter the system through a `NationalAdmin`
        registration carrying `full_name`, `email`, a `discipline` drawn from
        `BLS`, `ACLS`, `PALS`, or `HEARTSAVER`, and the
        `home_training_center_id` of their home center."
        PRD §2.5: "Required fields present, enum members drawn from the
        declared sets, integer fields carrying integer values within sane
        ranges, and `end_at` strictly after `start_at`. Failures yield
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/instructor_create_with_out_of_enum_discipline_returns_invalid_request
        """
        from test_helpers import create_center
        center = create_center()
        resp = api.create_instructor(
            create_instructor_payload(
                center["id"], full_name="Ned Newbie", email="ned@x.example",
                discipline="FIRST_AID"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(
            api.list_center_instructors(center["id"], TC))
        assert meta["total_count"] == 0


class TestParentRelationships:
    def test_site_create_under_unknown_center_returns_center_not_found(self, api):
        """PRD §2.6: "A request for a site under a non-existent center is
        rejected with `ERR_TRAINING_CENTER_NOT_FOUND` before the site lookup is
        even attempted."

        Design: Corner/entities/site_create_under_unknown_center_returns_center_not_found
        """
        set_clock_start()
        resp = api.create_site(
            NON_EXISTENT_UUID,
            create_site_payload(name="Ghost Lab",
                                street_address="1 Nowhere Rd",
                                capacity_students=10),
            TC)
        validate_error(resp, ApiErrorId.ERR_TRAINING_CENTER_NOT_FOUND)
