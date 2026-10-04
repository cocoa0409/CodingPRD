"""Application lifecycle basics: pagination, submit gate, state guards,
RBAC exclusivity, and applicant ownership."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    create_applicant,
    create_application,
    get_application,
    make_applicant_headers,
    run_applicant_to_accepted,
    create_program_with_opening,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]
MEDIC = TEST_USERS["medical_officer_headers"]


class TestApplicationListing:
    def test_list_applications_paginates_with_envelope(self):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        sets the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_applications_paginates_with_envelope
        """
        set_clock(DEFAULT_CLOCK_START)
        created = []
        for _ in range(3):
            applicant = create_applicant()
            created.append(create_application(applicant["id"])["id"])

        page1, meta1 = validate_paginated(
            api_client.list_applications(PLACER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_applications(PLACER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        page_ids = [a["id"] for a in page1] + [a["id"] for a in page2]
        assert len(set(page_ids)) == 3, "pages must not overlap"
        assert set(page_ids) == set(created), "pages together cover all 3 applications"


class TestSubmissionGate:
    def test_submit_requires_at_least_one_sector_preference(self):
        """PRD §3.2: "Submission is the applicant's own act and requires at
        least one sector preference — submitting a draft whose
        `sector_preferences` list is empty fails with `ERR_VALIDATION`."
        PRD §3.2: "an optional `sector_preferences` list drawn from the sector
        enum, and an optional free-text `statement`, the latter two defaulting
        to empty."

        Design: Corner/state_machines/submit_requires_at_least_one_sector_preference
        """
        set_clock(DEFAULT_CLOCK_START)
        ana = create_applicant()
        resp = api_client.create_application(
            {"applicant_id": ana["id"]}, make_applicant_headers(ana["id"]))
        app = validate_success(resp, 201)
        assert app["sector_preferences"] == [], \
            "a draft created without sector_preferences defaults to empty"
        assert app["status"] == "DRAFT"

        validate_error(
            api_client.submit_application(
                app["id"], make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_VALIDATION, 400)
        assert get_application(app["id"])["status"] == "DRAFT"

    def test_application_double_submit_rejected(self):
        """PRD §3.2: "State guards reject transitions from the wrong source
        state: submitting an already-`SUBMITTED` application, or beginning
        review of a `DRAFT`, fails with `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/application_double_submit_rejected
        """
        set_clock(DEFAULT_CLOCK_START)
        ana = create_applicant()
        app = create_application(ana["id"])
        submit_application(app["id"], ana["id"])

        validate_error(
            api_client.submit_application(
                app["id"], make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        assert get_application(app["id"])["status"] == "SUBMITTED"

    def test_withdrawn_application_terminal_lockdown(self):
        """PRD §3.2: "Withdrawal is always the applicant's prerogative, but
        its blast radius grows with the pipeline stage, and only non-terminal
        states offer it."
        PRD §2.9: "State-machine guards run sixth, each with its dedicated
        error where one exists — `ERR_INVALID_APPLICATION_STATE` for
        application transitions attempted from a state that does not offer
        them, `ERR_OPENING_NOT_OPEN` for issuance against a non-`OPEN`
        opening or cancellation of a `CLOSED` or `CANCELLED` one,
        `ERR_INVITATION_NOT_ACTIONABLE` for answering an invitation no longer
        `ISSUED`, `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` for determining a
        clearance no longer `SUBMITTED`, `ERR_ENROLLMENT_NOT_ASSESSABLE` for
        assessment, remediation, or swearing-in attempted from the wrong
        enrollment state, and `ERR_SERVICE_NOT_ACTIVE` for service-scoped
        actions against a service that is not `ACTIVE`."

        Design: Corner/state_machines/withdrawn_application_terminal_lockdown
        """
        set_clock(DEFAULT_CLOCK_START)
        ana = create_applicant()
        app = create_application(ana["id"])
        withdrawn = validate_success(
            api_client.withdraw_application(
                app["id"], make_applicant_headers(ana["id"])), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        validate_error(
            api_client.submit_application(
                app["id"], make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        validate_error(
            api_client.begin_review_application(app["id"], PLACER),
            ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        assert get_application(app["id"])["status"] == "WITHDRAWN"


class TestRoleAndOwnership:
    def test_roles_cannot_cross_exclusive_operations(self):
        """PRD §2.1: "Each operation is restricted to a named subset of these
        roles, and an authenticated caller whose role is outside the
        operation's allowed set is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/roles_cannot_cross_exclusive_operations
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        app_id = bundle["application"]["id"]
        clearance = validate_success(
            api_client.create_medical_clearance(
                {"application_id": app_id, "conditions": [], "dental_status": "CLEAR"},
                make_applicant_headers(ana["id"])),
            201)

        # An Applicant cannot create assignment openings (SystemAdmin-only).
        validate_error(
            api_client.create_assignment_opening(
                {
                    "country_program_id": program["id"],
                    "sector": "HEALTH",
                    "title": "Nope",
                    "required_skills": [],
                    "seats_total": 1,
                    "departure_date": "2027-01-15T00:00:00Z",
                    "invitation_issue_deadline": "2026-12-01T00:00:00Z",
                },
                make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_FORBIDDEN, 403)
        # A PlacementOfficer cannot determine medical clearances.
        validate_error(
            api_client.determine_medical_clearance(
                clearance["id"], {"determination": "CLEARED"}, PLACER),
            ApiErrorId.ERR_FORBIDDEN, 403)
        # A MedicalOfficer cannot file applications (Applicant-only).
        validate_error(
            api_client.create_application(
                {"applicant_id": ana["id"], "sector_preferences": ["EDUCATION"]},
                MEDIC),
            ApiErrorId.ERR_FORBIDDEN, 403)
        # No side effects: the clearance is still SUBMITTED.
        clearances = validate_success(
            api_client.list_medical_clearances(app_id, MEDIC), 200)
        assert len(clearances) == 1
        assert clearances[0]["status"] == "SUBMITTED"

    def test_applicant_cannot_act_on_others_application(self):
        """PRD §2.1: "Seven applicant-scoped operations enforce this
        ownership check and reject a mismatched caller with `ERR_NOT_OWNER`
        (HTTP 403): submitting an application, withdrawing an application,
        accepting an invitation, declining an invitation, creating a medical
        clearance, resubmitting a medical clearance, and reading the match
        list of an application."

        Design: Corner/rbac/applicant_cannot_act_on_others_application
        """
        set_clock(DEFAULT_CLOCK_START)
        ana = create_applicant()
        bob = create_applicant()
        app = create_application(ana["id"])
        submit_application(app["id"], ana["id"])

        validate_error(
            api_client.submit_application(
                app["id"], make_applicant_headers(bob["id"])),
            ApiErrorId.ERR_NOT_OWNER, 403)
        validate_error(
            api_client.withdraw_application(
                app["id"], make_applicant_headers(bob["id"])),
            ApiErrorId.ERR_NOT_OWNER, 403)
        validate_error(
            api_client.get_application_matches(
                app["id"], make_applicant_headers(bob["id"])),
            ApiErrorId.ERR_NOT_OWNER, 403)
        assert get_application(app["id"])["status"] == "SUBMITTED", \
            "rejected calls must leave the application untouched"
