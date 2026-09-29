"""The role matrix: exclusive verbs, shared verbs and the read-only reader.

Each case pairs every refusal with the request that is admitted, because a role
check that is merely absent and one that is too wide fail the same way here.
"""

from test_helpers import (
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_point_ledger,
    assert_points,
    bgu_headers,
    factories as f,
    fixtures as fx,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    public_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


class TestExclusiveOperationsAreExclusiveInBothDirections:
    """§4: "The `Authorized Role(s)` column is exhaustive"."""

    def test_seven_cross_role_attempts_are_all_unauthorized(self, api):
        """Seven endpoints, seven roles that are not on their lists: every attempt
        is ERR_UNAUTHORIZED and every target row is exactly where it started,
        including the clock the supervisor tried to move.

        PRD §4: "The `Authorized Role(s)` column is exhaustive: a request whose
        `X-User-Role` is not listed for the endpoint it addresses is refused with
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_exclusive_operations_seven_cross_role_attempts_are_unauthorized
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        check = fx.open_check(api, director["id"], "FBI_FINGERPRINT")
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        # the clock stays at the default so ``scheduled_for`` is strictly future
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="PHONE",
            allegation_category="RECORDS",
            affected_age_group="SCHOOL_AGE",
            narrative="Attendance records incomplete.",
        )

        # the baseline revision is read after the dossier is assembled, because
        # §3.2 already advanced it when the director was attached
        before_provider = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        applicant = make_applicant_headers(provider["id"])
        inspector_hdrs = make_inspector_headers(inspector["id"])
        attempts = (
            (
                "clear-checks is the supervisor's",
                lambda: api.clear_checks(provider["id"], headers=applicant),
            ),
            (
                "the logical clock is the administrator's",
                lambda: api.set_clock("2027-01-01T00:00:00Z", headers=supervisor_headers()),
            ),
            (
                "the checklist catalogue is the administrator's",
                lambda: api.create_checklist_item(
                    {
                        "code": "FA-401",
                        "title": "Playground surfacing intact",
                        "category": "FACILITY",
                        "default_severity": "MODERATE",
                        "age_groups_applicable": PRESCHOOL_ONLY,
                    },
                    headers=inspector_hdrs,
                ),
            ),
            (
                "screening is the intake specialist's",
                lambda: api.screen_complaint(
                    complaint["id"], "SCREEN_IN", headers=supervisor_headers()
                ),
            ),
            (
                "the inspector conducts but never finalizes",
                lambda: api.finalize_inspection(inspection["id"], headers=inspector_hdrs),
            ),
            (
                "registry results are the clearance unit's",
                lambda: api.record_check_result(
                    check["id"], "CLEARED", headers=supervisor_headers()
                ),
            ),
            (
                "submit-application is the applicant's, even for the administrator",
                lambda: api.submit_application(provider["id"], headers=admin_headers()),
            ),
        )
        for _label, attempt in attempts:
            # each ``_label`` names the exclusive bullet the attempt crosses
            validate_error(attempt(), "ERR_UNAUTHORIZED", 403)

        after_provider = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert after_provider["application_status"] == "DRAFT", (
            "neither the refused clear-checks nor the refused submit moved the edge"
        )
        assert after_provider["version"] == before_provider["version"]

        _items, item_meta = validate_paginated(
            api.list_checklist_items(headers=admin_headers(), code="FA-401")
        )
        assert item_meta["total_count"] == 0, "the refused registration created nothing"

        after_complaint = validate_success(
            api.get_complaint(complaint["id"], headers=admin_headers())
        )
        assert after_complaint["status"] == "RECEIVED"
        assert after_complaint["screened_at"] is None

        after_inspection = validate_success(
            api.get_inspection(inspection["id"], headers=admin_headers())
        )
        assert after_inspection["status"] == "SCHEDULED"
        assert after_inspection["finalized_at"] is None

        after_check = validate_success(
            api.get_background_check(check["id"], headers=bgu_headers())
        )
        assert after_check["status"] == "SUBMITTED"
        assert after_check["decided_at"] is None

        # the clock is only observable through what it stamps: a fresh P3 intake
        # still receives at the default instant, so the refused write moved nothing
        later = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="WEB",
            allegation_category="RECORDS",
            affected_age_group="SCHOOL_AGE",
            narrative="Second records allegation.",
        )
        assert_instant(later["received_at"], DEFAULT_LOGICAL_CLOCK, "received_at")
        assert later["priority"] == "P3"


class TestSharedOperationsAreSharedForTheWholeVerb:
    """§3.6: "vacating is supervisor-only", though the verb itself is shared."""

    def test_both_writers_schedule_but_only_the_supervisor_vacates(self, api, catalog):
        """The supervisor and the administrator create one visit each on the same
        inspector, and the disposition endpoint admits both the inspector and the
        supervisor — yet only the supervisor's vacating body is accepted.

        PRD §3.6: "An inspector may verify a correction or record a non-correction,
        but **vacating is supervisor-only**: an inspector who sends a vacating
        disposition is refused with `ERR_UNAUTHORIZED` (HTTP 403), even though the
        same inspector may use the same capability for the other two dispositions."

        Design: Corner/rbac/rbac_shared_operations_two_roles_write_the_same_rows
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        # POST /licensing/providers is shared with the AgencyAdmin, so the row the
        # rest of this case writes to is itself created under a shared bullet
        provider = validate_success(
            api.create_provider(
                f.provider_payload(requested_capacity=10), headers=admin_headers()
            ),
            201,
        )
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)

        by_supervisor = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        by_admin = validate_success(
            api.create_inspection(
                f.inspection_payload(
                    provider["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for="2026-08-07T09:00:00Z",
                    target_age_groups=PRESCHOOL_ONLY,
                ),
                headers=admin_headers(),
            ),
            201,
        )
        assert by_supervisor["status"] == "SCHEDULED"
        assert by_admin["status"] == "SCHEDULED"
        assert_instant(
            by_supervisor["visit_window_end"], "2026-08-05T11:00:00Z", "first window end"
        )
        assert_instant(
            by_admin["visit_window_end"], "2026-08-07T11:00:00Z", "second window end"
        )
        roll = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert roll["scheduled_visit_count"] == 2, "both shared writers counted"

        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, by_supervisor["id"], inspector["id"])
        violation = fx.cite(
            api,
            by_supervisor["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Nap room left unattended.",
        )
        assert_points(violation["assessed_points"], 15, "assessed_points")
        # §3.5: only a finalized visit's citations reach the provider's counters,
        # so the visit is carried to FINALIZED before the ledger is read
        fx.submit_findings(
            api, by_supervisor["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY
        )
        finalized = fx.finalize_visit(api, by_supervisor["id"])
        assert finalized["status"] == "FINALIZED"
        before = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(before, 15, 0, 15)

        vacating_reason = "Recorded against the wrong room."
        validate_error(
            api.disposition_violation(
                violation["id"],
                "VACATED",
                vacated_reason=vacating_reason,
                headers=make_inspector_headers(inspector["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        refused = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert refused["status"] == "CORRECTION_PENDING"
        assert refused["vacated_reason"] is None
        still = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(still, 15, 0, 15)

        vacated = validate_success(
            api.disposition_violation(
                violation["id"],
                "VACATED",
                vacated_reason=vacating_reason,
                headers=supervisor_headers(),
            )
        )
        assert vacated["status"] == "VACATED", "the identical body from the supervisor"
        assert vacated["vacated_reason"] == vacating_reason
        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(after, 0, 0, 0)
        assert after["critical_open_count"] == 0
        final_roll = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert final_roll["scheduled_visit_count"] == 1, "the finalized visit dropped out"


class TestSegregationOfDutiesIsPerInspectorNotPerRole:
    """§3.7: the recent inspector of this provider may not investigate it."""

    def test_the_inspector_who_finalized_four_days_ago_cannot_take_the_case(self, api):
        """The assignment is refused for the inspector who finalized this provider's
        visit inside the lookback and accepted for an untainted colleague of the
        same role and county, with the refused attempt leaving no trace.

        PRD §3.7: "the proposed investigator must not have finalized **any**
        inspection of that complaint's provider whose `finalized_at` is strictly
        later than 12 months before the current instant."

        Design: Corner/rbac/rbac_segregation_of_duties_recent_inspector_cannot_investigate
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        fx.clear_person(api, director["id"])
        conductor = fx.register_inspector(
            api, full_name="Ivy Cole", certified_age_groups=PRESCHOOL_ONLY
        )
        colleague = fx.register_inspector(
            api, full_name="Omar Vance", certified_age_groups=PRESCHOOL_ONLY
        )
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            conductor["id"],
            "2026-08-06T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, "2026-08-06T09:00:00Z")
        fx.start_visit(api, inspection["id"], conductor["id"])
        fx.submit_findings(
            api, inspection["id"], conductor["id"], "PASS", PRESCHOOL_ONLY
        )
        finalized = fx.finalize_visit(api, inspection["id"])
        assert finalized["status"] == "FINALIZED"
        assert_instant(finalized["finalized_at"], "2026-08-06T09:00:00Z", "finalized_at")

        fx.set_clock(api, "2026-08-10T00:00:00Z")
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="MANDATED_REPORTER",
            allegation_category="SUPERVISION",
            affected_age_group="PRESCHOOL",
            narrative="Reporter observed an unattended classroom.",
        )
        assert complaint["priority"] == "P2"
        assert_instant(
            complaint["investigation_due_at"],
            "2026-09-24T00:00:00Z",
            "investigation_due_at",
        )
        screened = fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
        assert screened["status"] == "SCREENED_IN"
        roll_before = validate_success(
            api.get_inspector(conductor["id"], headers=admin_headers())
        )

        validate_error(
            api.assign_investigator(
                complaint["id"], conductor["id"], headers=supervisor_headers()
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        refused = validate_success(
            api.get_complaint(complaint["id"], headers=admin_headers())
        )
        assert refused["status"] == "SCREENED_IN"
        assert refused["assigned_investigator_id"] is None
        roll_after = validate_success(
            api.get_inspector(conductor["id"], headers=admin_headers())
        )
        assert roll_after == roll_before, "no field of the inspector records the attempt"

        assigned = validate_success(
            api.assign_investigator(
                complaint["id"], colleague["id"], headers=supervisor_headers()
            )
        )
        assert assigned["status"] == "UNDER_INVESTIGATION"
        assert assigned["assigned_investigator_id"] == colleague["id"]
        assert assigned["determination"] is None


class TestThePublicReaderReadsAndNeverWrites:
    """§2.1: the consumer-education role has "no mutating capability whatsoever"."""

    def test_the_register_is_readable_while_every_write_is_refused(self, api):
        """The reader pages the provider directory and the posting register without
        any identity beyond its role, and its two write attempts — one of them the
        header-exempt provider create — are ERR_UNAUTHORIZED.

        PRD §2.1: "A `PublicPortalReader` is an unprivileged consumer-education
        reader with read-only access and no mutating capability whatsoever."

        Design: Corner/rbac/rbac_shared_operations_public_reader_may_read_but_never_write
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)

        rows, meta = validate_paginated(api.list_providers(headers=public_headers()))
        assert [row["id"] for row in rows] == [provider["id"]]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        one = validate_success(
            api.get_provider(provider["id"], headers=public_headers())
        )
        assert one["id"] == provider["id"]
        assert one["application_status"] == "DRAFT"

        postings, posting_meta = validate_paginated(
            api.list_postings(headers=public_headers())
        )
        assert postings == [], "an empty register still carries the envelope"
        assert posting_meta["total_count"] == 0
        assert posting_meta["has_more"] is False

        validate_error(
            api.create_provider(
                f.provider_payload(
                    legal_name="Ghost Center",
                    site_address="1 Nowhere",
                    requested_capacity=5,
                ),
                headers=public_headers(),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    intake_channel="WEB",
                    allegation_category="RECORDS",
                    affected_age_group="SCHOOL_AGE",
                    narrative="Records look wrong.",
                ),
                headers=public_headers(),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _again, meta_again = validate_paginated(
            api.list_providers(headers=admin_headers())
        )
        assert meta_again["total_count"] == 1, "neither refused write created a row"
        _complaints, complaint_meta = validate_paginated(
            api.list_complaints(headers=intake_headers(), provider_id=provider["id"])
        )
        assert complaint_meta["total_count"] == 0
