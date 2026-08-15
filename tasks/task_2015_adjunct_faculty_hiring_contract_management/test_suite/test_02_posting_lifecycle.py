"""Posting state machine: draft gate, terminal lockdown, close/archive cascades,
and the logical clock's default reading (PRD Sections 2.4, 3.3)."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_department,
    create_fall_term,
    create_open_posting,
    create_posting,
    get_success_data,
    set_clock,
    start_review,
    validate_error,
    validate_success,
)


def _dept_and_term(code):
    dept = create_department(code=code, contact_hour_value=1.00)
    create_fall_term()
    return dept


class TestPostingDraftGate:
    def test_posting_initial_state_is_draft(self, api, chair_headers, hr_reviewer_1_headers):
        """PRD Section 3.3: "A `DepartmentChair` opens a hiring round by creating a
        pool posting in `DRAFT`"
        PRD Section 3.3: "The filing window is strict: the posting must be in `OPEN`
        status and the current logical date must fall within the inclusive window
        from `open_date` to `close_date`, or the filing is refused with
        `ERR_POSTING_NOT_OPEN`."

        Design: Corner/state_machines/posting_initial_state_is_draft
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = _dept_and_term("DRFT")
        posting = create_posting(dept["id"], term_code="2026FA", title="Draft Pool",
                                 min_education_tier="BACHELORS")
        assert posting["posting_status"] == "DRAFT"

        filed = api.create_application(
            {
                "posting_id": posting["id"],
                "applicant_name": "Pia Adjunct",
                "applicant_email": "pia@x.edu",
                "claimed_education_tier": "BACHELORS",
            },
            hr_reviewer_1_headers,
        )
        validate_error(filed, ApiErrorId.ERR_POSTING_NOT_OPEN)


class TestPostingArchivedLockdown:
    def test_posting_terminal_archived_lockdown(self, api, chair_headers):
        """PRD Section 3.3: "Finally, a `CLOSED` posting may be archived into
        `ARCHIVED` — the terminal state"
        PRD Section 2.8: "`ERR_INVALID_STATE` (409) — the requested action exists as
        a transition from the target entity's current state. This single state error
        covers terminal-state lockdown and repeated-action (double-action) failures"

        Design: Corner/state_machines/posting_terminal_archived_lockdown
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = _dept_and_term("ARCH")
        posting = create_open_posting(dept["id"], term_code="2026FA",
                                      min_education_tier="BACHELORS")
        get_success_data(api.close_posting(posting["id"], chair_headers))
        archived = get_success_data(api.archive_posting(posting["id"], chair_headers))
        assert archived["posting_status"] == "ARCHIVED"

        suspend = api.suspend_posting(posting["id"], chair_headers)
        validate_error(suspend, ApiErrorId.ERR_INVALID_STATE)
        publish = api.publish_posting(posting["id"], chair_headers)
        validate_error(publish, ApiErrorId.ERR_INVALID_STATE)


class TestPostingCloseAndArchive:
    def test_posting_archive_blocked_by_in_flight_application(
        self, api, chair_headers, hr_reviewer_1_headers
    ):
        """PRD Section 3.3: "a `CLOSED` posting may be archived into `ARCHIVED` —
        the terminal state — but only while none of its applications remains in
        `UNDER_REVIEW` or `RETURNED_FOR_REVISION`; an in-flight application blocks
        archival with `ERR_REFERENCE_IN_USE`."

        Design: Corner/state_machines/posting_archive_blocked_by_in_flight_application
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = _dept_and_term("BLCK")
        posting = create_open_posting(dept["id"], term_code="2026FA",
                                      min_education_tier="BACHELORS")
        application = create_application(
            posting["id"], applicant_name="Quinn Adjunct",
            applicant_email="quinn@x.edu", claimed_education_tier="BACHELORS",
        )
        start_review(application["id"])
        closed = get_success_data(api.close_posting(posting["id"], chair_headers))
        assert closed["posting_status"] == "CLOSED"

        blocked = api.archive_posting(posting["id"], chair_headers)
        validate_error(blocked, ApiErrorId.ERR_REFERENCE_IN_USE)

        after = get_success_data(api.get_posting(posting["id"], chair_headers))
        assert after["posting_status"] == "CLOSED", "failed archive must not move the posting"

    def test_posting_close_expires_submitted_applications_cascade(
        self, api, chair_headers, hr_reviewer_1_headers
    ):
        """PRD Section 3.3: "Either way, closing cascades: every application still
        sitting in `SUBMITTED` against that posting transitions to `EXPIRED`."

        Design: Corner/state_machines/posting_close_expires_submitted_applications_cascade
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = _dept_and_term("CASC")
        posting = create_open_posting(dept["id"], term_code="2026FA",
                                      min_education_tier="BACHELORS")
        app1 = create_application(posting["id"], applicant_name="A One",
                                  applicant_email="a1@x.edu",
                                  claimed_education_tier="BACHELORS")
        app2 = create_application(posting["id"], applicant_name="A Two",
                                  applicant_email="a2@x.edu",
                                  claimed_education_tier="BACHELORS")
        start_review(app2["id"])

        get_success_data(api.close_posting(posting["id"], chair_headers))

        st1 = get_success_data(api.get_application(app1["id"], hr_reviewer_1_headers))
        st2 = get_success_data(api.get_application(app2["id"], hr_reviewer_1_headers))
        assert st1["application_status"] == "EXPIRED", (
            "SUBMITTED application must expire on posting close"
        )
        assert st2["application_status"] == "UNDER_REVIEW", (
            "conditional cascade spares applications past SUBMITTED"
        )


class TestLogicalClock:
    def test_clock_default_reading_is_2026_08_01(self, api, chair_headers):
        """PRD Section 2.4: "At startup the clock reads exactly
        `2026-08-01T00:00:00Z`; before any explicit set call it continues to read
        that default and never falls back to wall-clock time."
        PRD Section 3.3: "Publishing moves the posting from `DRAFT` to `OPEN` and is
        allowed only when three conditions hold: the posting's department is active,
        the named `term_code` matches an existing term whose `rollover_status` is not
        `ROLLED_OVER`, and the current logical date is on or before `close_date`. A
        publish attempted from any other state, or with one of those conditions
        broken, is refused with `ERR_INVALID_STATE`."

        The publish date-gate observes the default clock: close_date 2026-07-31
        (before the default) must refuse, close_date 2026-08-01 (on it) must pass.

        Design: Corner/cross_cutting_layers/clock_default_and_deterministic_expiry
        """
        # No set_clock call anywhere in this test: the default reading is observed.
        dept = create_department(code="CLKX", contact_hour_value=1.00)
        create_fall_term()

        expired_window = create_posting(
            dept["id"], term_code="2026FA", title="Early Pool",
            min_education_tier="BACHELORS",
            open_date="2026-07-01", close_date="2026-07-31",
        )
        refused = api.publish_posting(expired_window["id"], chair_headers)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE)

        boundary_window = create_posting(
            dept["id"], term_code="2026FA", title="Boundary Pool",
            min_education_tier="BACHELORS",
            open_date="2026-07-01", close_date="2026-08-01",
        )
        published = api.publish_posting(boundary_window["id"], chair_headers)
        data = validate_success(published, 200)
        assert data["posting_status"] == "OPEN", (
            "close_date equal to the default clock reading 2026-08-01 must publish"
        )

    def test_clock_advance_auto_closes_posting_and_expires_applications(
        self, api, hr_admin_headers, hr_reviewer_1_headers
    ):
        """PRD Section 2.4: "Moving it past the final millisecond of a posting's
        close date automatically closes that posting and expires its untouched
        applications."

        Design: Corner/cross_cutting_layers/clock_default_and_deterministic_expiry
        """
        dept = create_department(code="CLK2", contact_hour_value=1.00)
        create_fall_term()
        set_clock("2026-07-01T00:00:00Z")
        posting = create_open_posting(
            dept["id"], term_code="2026FA", title="Clock Pool",
            min_education_tier="BACHELORS",
            open_date="2026-07-01", close_date="2026-07-15",
        )
        application = create_application(
            posting["id"], applicant_name="Lua Adjunct",
            applicant_email="lua@x.edu", claimed_education_tier="BACHELORS",
        )

        set_clock("2026-07-16T00:00:00Z")

        posting_after = get_success_data(api.get_posting(posting["id"], hr_admin_headers))
        assert posting_after["posting_status"] == "CLOSED", (
            "advancing past close_date must auto-close the posting"
        )
        app_after = get_success_data(api.get_application(application["id"], hr_admin_headers))
        assert app_after["application_status"] == "EXPIRED", (
            "untouched SUBMITTED application must expire with the auto-close"
        )
