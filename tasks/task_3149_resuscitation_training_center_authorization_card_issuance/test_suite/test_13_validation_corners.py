"""Corner coverage: validation pipeline — auth context, authorization before
existence, OCC stale versions, quota-last session-full, renewal shortfall."""
from test_helpers import (
    ADMIN,
    COORD,
    QA,
    TC,
    ApiErrorId,
    NON_EXISTENT_UUID,
    center_version,
    create_center_with_faculty,
    create_quality_audit_payload,
    create_scheduled_session,
    create_site_payload,
    create_training_center_payload,
    enroll_student,
    get_success_data,
    set_clock_start,
    setup_renewal_ready_instructor,
    setup_teaching_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    create_active_center,
)


class TestAuthContext:
    def test_create_center_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.5: "1. **Authentication context (highest priority).** Both
        `X-User-ID` and `X-User-Role` headers must be present and non-empty,
        otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/create_center_missing_auth_header_returns_unauthenticated
        """
        set_clock_start()
        resp = api.create_training_center(
            create_training_center_payload(
                legal_name="No Auth Center", region="WEST",
                contact_email="x@x.example"),
            headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestAuthorizationBeatsExistence:
    def test_authorization_beats_existence_for_denied_role(self, api):
        """PRD §2.5: "Every mutating request passes through a validation
        pipeline whose checks run in a fixed order. A request that fails an
        earlier check is rejected immediately and never reaches a later check;
        the `error_id` returned is always the first failing rule."
        PRD §2.5: "2. **Role authorization.** The caller's role must be
        permitted for the endpoint per the authorization matrix in §4."
        PRD §2.5: "3. **Existence of path resources.**"

        Design: Corner/validations/authorization_beats_existence_for_denied_role
        """
        set_clock_start()
        # TCCoordinator may not create sites (§4); the center does not exist,
        # but authorization fires first.
        resp = api.create_site(
            NON_EXISTENT_UUID,
            create_site_payload(name="Ghost Lab",
                                street_address="1 Nowhere Rd",
                                capacity_students=10),
            COORD)
        err = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert err["error_id"] != ApiErrorId.ERR_TRAINING_CENTER_NOT_FOUND


class TestOccSiteAlign:
    def test_occ_stale_version_blocks_second_site_align(self, api):
        """PRD §2.10: "Aligning a site — moving it from `PENDING_ALIGNMENT` to
        `ALIGNED` — requires the request to carry
        `expected_training_center_version` matching the current `version` of
        the center that owns the site. If another writer has advanced the
        center's version since the client last read it (for example by aligning
        a different site, or by opening an audit), the align request is
        rejected with `ERR_STALE_VERSION` (HTTP 412) so the client refreshes
        its view of the center before retrying."

        Design: Corner/validations/occ_stale_version_blocks_second_site_align
        """
        center, faculty = create_center_with_faculty()
        v0 = center_version(center["id"])
        site1 = get_success_data(api.create_site(
            center["id"], create_site_payload(
                name="Site One", capacity_students=24), TC))
        site2 = get_success_data(api.create_site(
            center["id"], create_site_payload(
                name="Site Two", street_address="200 Airway Blvd",
                capacity_students=12), TC))

        first = validate_success(api.align_site(
            site1["id"], {"expected_training_center_version": v0}, TC))
        assert first["status"] == "ALIGNED"

        # The first alignment advanced the center version; the stale version
        # is rejected even though every business precondition holds.
        resp = api.align_site(
            site2["id"], {"expected_training_center_version": v0}, TC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        site2_now = validate_success(api.get_site(site2["id"], TC))
        assert site2_now["status"] == "PENDING_ALIGNMENT"


class TestOccAuditOpen:
    def test_occ_stale_version_blocks_audit_open(self, api):
        """PRD §2.10: "Opening a quality audit against a center likewise
        requires the request to carry `expected_training_center_version`
        matching the center's current `version`. The audit's baseline must
        reflect the center's current governance state — its status and the set
        of aligned sites — so a stale version means the baseline has moved and
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "A successful open increments the center's `version` by 1."

        Design: Corner/validations/occ_stale_version_blocks_audit_open
        """
        center, faculty, site = create_active_center()
        v0 = center_version(center["id"], QA)

        audit1 = validate_success(
            api.create_quality_audit(
                create_quality_audit_payload(center["id"], v0), QA),
            expected_status=201)
        assert audit1["status"] == "OPEN"

        # The first audit bumped the center version; the stale version fails.
        resp = api.create_quality_audit(
            create_quality_audit_payload(center["id"], v0), QA)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        _, meta = validate_paginated(
            api.list_center_audits(center["id"], QA))
        assert meta["total_count"] == 1


class TestSessionFullQuota:
    def test_roster_add_on_full_session_returns_session_full(self, api):
        """PRD §3.6: "The session must be `SCHEDULED` (otherwise
        `ERR_SESSION_NOT_SCHEDULED`) and must have at least one seat available
        — `seats_available` greater than zero — otherwise the enrollment is
        rejected with `ERR_SESSION_FULL`."
        PRD §3.6: "A `TCCoordinator` may cancel an `ENROLLED` roster entry
        (otherwise `ERR_ROSTER_ENTRY_NOT_ENROLLED`); the entry moves to
        `CANCELLED` and the session's `seats_available` increments by 1."

        Design: Corner/validations/roster_add_on_full_session_returns_session_full
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entries = []
        for i in range(6):
            entries.append(enroll_student(
                session["id"], f"Stu {i + 1}", f"s{i + 1}@x.example"))

        resp = api.add_roster_entry(
            session["id"],
            {"student_name": "Stu Seven", "student_email": "s7@x.example"},
            COORD)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)

        # A cancel frees exactly one seat; the identical add now succeeds.
        validate_success(api.cancel_roster_entry(entries[0]["id"], COORD))
        added = validate_success(
            api.add_roster_entry(
                session["id"],
                {"student_name": "Stu Seven", "student_email": "s7@x.example"},
                COORD),
            expected_status=201)
        assert added["status"] == "ENROLLED"
        s_now = validate_success(api.get_course_session(session["id"], COORD))
        assert s_now["seats_available"] == 0


class TestRenewalSessionShortfall:
    def test_renewal_with_fewer_than_two_sessions_returns_shortfall(self, api):
        """PRD §3.3: "Within the trailing twenty-four-month window (sessions
        whose `start_at` is on or after the instant twenty-four months before
        the current clock, and on or before the current clock — again inclusive
        on both ends), the instructor must have been the `primary_instructor_id`
        of at least two `CourseSession` rows whose `status` is `COMPLETED`.
        Sessions in `SCHEDULED`, `IN_PROGRESS`, or `CANCELLED` do not count.
        Falling short of two completed sessions rejects the renewal with
        `ERR_RENEWAL_SESSION_SHORTFALL`."

        Design: Corner/validations/renewal_with_fewer_than_two_sessions_returns_shortfall
        """
        ctx = setup_renewal_ready_instructor(num_completed_sessions=1)
        lead_id = ctx["lead"]["id"]
        # Inside the renewal window (2028-08-01 is within 90 days of due).
        get_success_data(api.set_clock("2028-08-01T00:00:00Z", ADMIN))
        resp = api.renew_instructor(lead_id, TC)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_SESSION_SHORTFALL)
        still = validate_success(api.get_instructor(lead_id, TC))
        assert still["renewal_count"] == 0
        assert still["renewal_due_at"] == "2028-09-01T00:00:00Z"
