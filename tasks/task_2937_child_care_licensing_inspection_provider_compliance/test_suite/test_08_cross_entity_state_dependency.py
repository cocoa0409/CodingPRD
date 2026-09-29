"""Gates that read a *sibling* entity's state (PRD §3.4, §3.6, §3.7, §3.9).

In every class the refused request and the accepted one carry the identical body;
what changes between them is the state of a different row.
"""

from test_helpers import (
    CODE_FACILITY,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_point_ledger,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _half_cleared_provider_in_pending_review(api):
    """Fernbank Center: the director's FBI check is CLEARED but the child abuse
    registry check is still SUBMITTED, and the INITIAL visit already sits in
    PENDING_REVIEW with a passing outcome."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Fernbank Center",
        site_address="81 Fernbank Way",
        program_type="CENTER",
        requested_capacity=20,
    )
    provider_id = provider["id"]
    director = fx.attach_staff(
        api,
        provider_id,
        full_name="Dana Director",
        member_type="DIRECTOR",
        qualified_age_groups=["PRESCHOOL"],
        role_title="Center Director",
    )
    fbi = fx.open_check(api, director["id"], "FBI_FINGERPRINT")
    fx.record_result(api, fbi["id"], "CLEARED")
    registry = fx.open_check(api, director["id"], "CHILD_ABUSE_REGISTRY")
    # §3.2 guards submission on at least one room whose requested group sizes sum
    # to the requested capacity exactly, so the PRESCHOOL room asks for all 20.
    fx.add_roster(
        api, provider_id, age_group="PRESCHOOL", requested_group_size=20
    )

    validate_success(
        api.submit_application(provider_id, headers=make_applicant_headers(provider_id))
    )
    inspection = fx.schedule_visit(
        api,
        provider_id,
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="INITIAL",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
    )
    fx.start_visit(api, inspection["id"], ada["id"])
    pending = fx.submit_findings(api, inspection["id"], ada["id"], "PASS", ["PRESCHOOL"])
    return {
        "provider_id": provider_id,
        "director": director,
        "registry": registry,
        "inspection": pending,
    }


class TestInspectionFinalizeRequiresProviderClearance:
    """§3.3: "the finalization of an `INITIAL` inspection, which is the
    cross-entity dependency between an inspection and the registry results behind
    it"."""

    def test_one_missing_registry_check_blocks_both_the_advance_and_the_finalize(
        self, api
    ):
        """A director covering one of the two required check types leaves the
        provider uncleared, and that alone refuses the supervisor's advance and the
        finalize.

        PRD §3.3: "It is true when the provider has at least one `DIRECTOR` and,
        for every attached person, that person's own `clearance_status` is `CLEARED`
        **and** their unexpired cleared-or-waived check types cover both
        `FBI_FINGERPRINT` and `CHILD_ABUSE_REGISTRY`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_inspection_finalize_requires_provider_clearance
        """
        ctx = _half_cleared_provider_in_pending_review(api)
        before = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert before["clearance_complete"] is False
        assert before["application_status"] == "SUBMITTED"

        validate_error(
            api.clear_checks(ctx["provider_id"], headers=supervisor_headers()),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )
        validate_error(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            ),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["application_status"] == "SUBMITTED"
        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert inspection["status"] == "PENDING_REVIEW"
        assert inspection["finalized_at"] is None
        assert inspection["version"] == ctx["inspection"]["version"], (
            "a refused finalize must not advance the inspection revision"
        )

    def test_clearing_the_second_check_lets_the_identical_finalize_through(self, api):
        """Nothing about the inspection changes; clearing the sibling check flips
        the provider flag and the same call now finalizes and passes the
        application forward.

        PRD §3.4: "when the type is `INITIAL` and the outcome is `PASS` or
        `CONDITIONAL_PASS`, the provider's `application_status` moves from
        `CHECKS_CLEARED` to `INITIAL_INSPECTION_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_inspection_finalize_requires_provider_clearance
        """
        ctx = _half_cleared_provider_in_pending_review(api)
        validate_error(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            ),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        fx.record_result(api, ctx["registry"]["id"], "CLEARED")
        person = validate_success(
            api.get_staff_member(ctx["director"]["id"], headers=supervisor_headers())
        )
        assert person["clearance_status"] == "CLEARED"
        cleared = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert cleared["clearance_complete"] is True
        assert (
            validate_success(
                api.get_inspection(
                    ctx["inspection"]["id"], headers=supervisor_headers()
                )
            )["status"]
            == "PENDING_REVIEW"
        ), "clearing a background check must not touch the inspection"

        advanced = validate_success(
            api.clear_checks(ctx["provider_id"], headers=supervisor_headers())
        )
        assert advanced["application_status"] == "CHECKS_CLEARED"

        finalized = validate_success(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            )
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["violation_count"] == 0
        assert finalized["cap_required"] is False
        assert_score(
            finalized["preliminary_compliance_score"],
            100.00,
            "preliminary_compliance_score",
        )
        assert_score(
            finalized["final_compliance_score"], 100.00, "final_compliance_score"
        )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["application_status"] == "INITIAL_INSPECTION_PASSED"


def _posting_pending_redaction(api, catalog):
    """Glenmoor Center with complaint A under investigation, its finalized
    COMPLAINT visit scoring 96.00, and a posting prepared with redaction still
    incomplete.

    The investigator is assigned before the visit finalizes, because §3.7 bars an
    investigator who has finalized a visit of the same provider.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    ben = fx.register_inspector(
        api,
        full_name="Ben Investigator",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Glenmoor Center",
        site_address="91 Glenmoor Ave",
        program_type="CENTER",
        requested_capacity=20,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="PHONE",
        allegation_category="FACILITY",
        affected_age_group="PRESCHOOL",
        narrative="Caller reports a broken gate on the playground.",
        anonymous=False,
        complainant_name="R. Calloway",
    )
    fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint["id"],
    )
    fx.assign_investigator(api, complaint["id"], ada["id"])
    fx.start_visit(api, inspection["id"], ada["id"])
    fx.cite(
        api,
        inspection["id"],
        ada["id"],
        catalog[CODE_FACILITY],
        primary_age_group="PRESCHOOL",
        narrative="Playground gate latch broken.",
    )
    fx.submit_findings(
        api, inspection["id"], ada["id"], "CONDITIONAL_PASS", ["PRESCHOOL"]
    )
    finalized = fx.finalize_visit(api, inspection["id"])
    posting = fx.prepare_posting(
        api,
        inspection["id"],
        consumer_summary="One moderate facility finding was corrected during the visit.",
        redaction_complete=False,
    )
    fx.set_clock(api, "2026-08-05T13:00:00Z")
    return {
        "provider_id": provider["id"],
        "complaint_id": complaint["id"],
        "inspection": finalized,
        "posting": posting,
        "ada": ada,
        "ben": ben,
    }


class TestPostingPublishBlockedByOpenInvestigation:
    """§3.9: "**no complaint of that posting's provider may be in
    `UNDER_INVESTIGATION` at that moment**"."""

    def test_the_open_investigation_outranks_the_posting_s_own_redaction_gap(
        self, api, catalog
    ):
        """The posting is unredacted *and* the provider has an open investigation,
        and the cross-entity gate is the one reported.

        PRD §3.9: "Making a posting public requires `PENDING_REDACTION`;
        `redaction_complete` must be true, or the call is `ERR_REDACTION_INCOMPLETE`
        (HTTP 409); the referenced inspection must still be `FINALIZED`; and **no
        complaint of that posting's provider may be in `UNDER_INVESTIGATION` at that
        moment**, or the call is `ERR_POSTING_BLOCKED_OPEN_INVESTIGATION` (HTTP
        409)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_posting_publish_blocked_by_open_investigation
        """
        ctx = _posting_pending_redaction(api, catalog)
        assert_score(
            ctx["inspection"]["final_compliance_score"], 96.00, "final_compliance_score"
        )
        assert ctx["inspection"]["violation_count"] == 1
        posting = ctx["posting"]
        assert posting["posting_status"] == "PENDING_REDACTION"
        assert posting["correction_count"] == 0
        assert posting["display_score"] is None
        assert posting["redaction_complete"] is False
        assert (
            validate_success(
                api.get_complaint(ctx["complaint_id"], headers=supervisor_headers())
            )["status"]
            == "UNDER_INVESTIGATION"
        )

        validate_error(
            api.post_posting(posting["id"], headers=admin_headers()),
            "ERR_POSTING_BLOCKED_OPEN_INVESTIGATION",
            409,
        )

    def test_determining_the_complaint_changes_which_error_is_reported(
        self, api, catalog
    ):
        """Once the sibling complaint is DETERMINED the same call reports the
        posting's own redaction gap, which only the cross-entity gate firing first
        can explain.

        PRD §3.9: "That last condition is evaluated live against every complaint of
        the provider, not merely those connected to the inspection being posted,
        which is why closing an unrelated investigation can unblock a posting."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_posting_publish_blocked_by_open_investigation
        """
        ctx = _posting_pending_redaction(api, catalog)
        validate_error(
            api.post_posting(ctx["posting"]["id"], headers=admin_headers()),
            "ERR_POSTING_BLOCKED_OPEN_INVESTIGATION",
            409,
        )

        determined = fx.record_determination(
            api, ctx["complaint_id"], ctx["ada"]["id"], "INCONCLUSIVE"
        )
        assert determined["status"] == "DETERMINED"
        assert determined["timeliness_flag"] == "ON_TIME"

        validate_error(
            api.post_posting(ctx["posting"]["id"], headers=admin_headers()),
            "ERR_REDACTION_INCOMPLETE",
            409,
        )

        posting = validate_success(
            api.get_posting(ctx["posting"]["id"], headers=admin_headers())
        )
        assert posting["posting_status"] == "PENDING_REDACTION"
        assert posting["posted_at"] is None
        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert inspection["violation_count"] == 1, (
            "an INCONCLUSIVE determination cites nothing"
        )
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 4, 0, 4)
        assert provider["current_ladder_step"] == 0

    def test_a_redacted_posting_publishes_once_every_investigation_is_closed(
        self, api, catalog
    ):
        """A second visit, posted with redaction complete, is still blocked while
        its own complaint is under investigation and publishes the moment that
        complaint is determined.

        PRD §3.9: "On success `posting_status` becomes `POSTED`, `posted_at` is
        stamped, and `expires_at` is set to 36 months after that instant."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_posting_publish_blocked_by_open_investigation
        """
        ctx = _posting_pending_redaction(api, catalog)
        fx.record_determination(api, ctx["complaint_id"], ctx["ada"]["id"], "INCONCLUSIVE")

        second = fx.intake_complaint(
            api,
            ctx["provider_id"],
            intake_channel="PHONE",
            allegation_category="RATIO",
            affected_age_group="PRESCHOOL",
            narrative="Second caller reports thin staffing in the preschool room.",
            anonymous=True,
        )
        fx.screen_complaint(api, second["id"], "SCREEN_IN")
        visit = fx.schedule_visit(
            api,
            ctx["provider_id"],
            ctx["ada"]["id"],
            "2026-08-12T09:00:00Z",
            inspection_type="COMPLAINT",
            target_age_groups=["PRESCHOOL"],
            duration_minutes=120,
            complaint_id=second["id"],
        )
        fx.assign_investigator(api, second["id"], ctx["ben"]["id"])
        fx.start_visit(api, visit["id"], ctx["ada"]["id"])
        fx.submit_findings(api, visit["id"], ctx["ada"]["id"], "PASS", ["PRESCHOOL"])
        clean = fx.finalize_visit(api, visit["id"])
        assert_score(
            clean["final_compliance_score"], 100.00, "final_compliance_score"
        )

        posting = fx.prepare_posting(
            api,
            visit["id"],
            consumer_summary="No findings were recorded at this visit.",
            redaction_complete=True,
        )
        validate_error(
            api.post_posting(posting["id"], headers=admin_headers()),
            "ERR_POSTING_BLOCKED_OPEN_INVESTIGATION",
            409,
        )

        fx.record_determination(api, second["id"], ctx["ben"]["id"], "INCONCLUSIVE")
        published = fx.publish_posting(api, posting["id"])

        assert published["posting_status"] == "POSTED"
        assert_instant(published["posted_at"], "2026-08-05T13:00:00Z", "posted_at")
        assert_instant(published["expires_at"], "2029-08-05T13:00:00Z", "expires_at")
        assert published["enforcement_banner"] == "NONE"
        assert_score(published["display_score"], 100.00, "display_score")


def _pending_review_visit_with_two_findings(api, catalog):
    """Harrowgate Center with a COMPLAINT visit in PENDING_REVIEW carrying
    SU-101/PRESCHOOL (15 points) and FA-401/PRESCHOOL (4 points)."""
    fx.set_clock(api, "2026-08-05T13:00:00Z")
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Harrowgate Center",
        site_address="101 Harrowgate St",
        program_type="CENTER",
        requested_capacity=20,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="MANDATED_REPORTER",
        allegation_category="SUPERVISION",
        affected_age_group="PRESCHOOL",
        narrative="Teacher reports a classroom left unattended.",
        anonymous=False,
        complainant_name="M. Ortiz",
    )
    fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-06T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint["id"],
    )
    fx.start_visit(api, inspection["id"], ada["id"])
    critical = fx.cite(
        api,
        inspection["id"],
        ada["id"],
        catalog[CODE_SUPERVISION],
        primary_age_group="PRESCHOOL",
        narrative="Preschool room left unattended for several minutes.",
    )
    moderate = fx.cite(
        api,
        inspection["id"],
        ada["id"],
        catalog[CODE_FACILITY],
        primary_age_group="PRESCHOOL",
        narrative="Playground gate latch broken.",
    )
    pending = fx.submit_findings(
        api, inspection["id"], ada["id"], "FAIL", ["PRESCHOOL"]
    )
    return {
        "provider_id": provider["id"],
        "inspection_id": inspection["id"],
        "ver_pending": pending["version"],
        "violation_ids": [critical["id"], moderate["id"]],
        "ada": ada,
    }


class TestCapSubmissionRequiresFinalizedInspection:
    """§3.6: "The inspection must be `FINALIZED`." """

    def test_a_plan_against_a_pending_review_visit_is_refused_on_state_not_version(
        self, api, catalog
    ):
        """The submission carries the live version, so the OCC gate at priority 21
        is satisfied and the state gate at priority 42 is the one observed, and no
        plan row survives the refusal.

        PRD §2.2: "Then come the two optimistic-concurrency comparisons — the
        provider revision on amendment creation, and the inspection revision on plan
        submission — which precede every state check. State preconditions follow, in
        this internal order: the provider's application dimension, then the
        provider's licence dimension, then the inspection, the violation, ..."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_cap_submission_requires_finalized_inspection
        """
        ctx = _pending_review_visit_with_two_findings(api, catalog)
        body = f.cap_payload(
            ctx["inspection_id"],
            ctx["violation_ids"],
            ctx["ver_pending"],
            narrative="Retrain staff on supervision and replace the gate latch.",
            proposed_completion_date="2026-08-08",
        )

        validate_error(
            api.create_cap(
                body, headers=make_applicant_headers(ctx["provider_id"])
            ),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )

        rows, meta = validate_paginated(
            api.list_caps(
                inspection_id=ctx["inspection_id"], headers=supervisor_headers()
            )
        )
        assert rows == [], (
            f"the refused submission must leave no plan row; got {rows!r}"
        )
        assert meta["total_count"] == 0

    def test_finalizing_bumps_the_version_the_plan_must_now_carry(self, api, catalog):
        """The finalize that opens the state gate closes the version gate: the
        version the client just used is stale by one and is refused at priority 21.

        PRD §3.4: "Both the inspection's and the provider's `version` counters
        advance."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_cap_submission_requires_finalized_inspection
        """
        ctx = _pending_review_visit_with_two_findings(api, catalog)
        finalized = fx.finalize_visit(api, ctx["inspection_id"])

        assert finalized["status"] == "FINALIZED"
        assert finalized["version"] == ctx["ver_pending"] + 1

        validate_error(
            api.create_cap(
                f.cap_payload(
                    ctx["inspection_id"],
                    ctx["violation_ids"],
                    ctx["ver_pending"],
                    narrative="Retrain staff on supervision and replace the gate latch.",
                    proposed_completion_date="2026-08-08",
                ),
                headers=make_applicant_headers(ctx["provider_id"]),
            ),
            "ERR_STALE_INSPECTION_VERSION",
            412,
        )

    def test_the_post_finalize_version_carries_the_identical_body_to_201(
        self, api, catalog
    ):
        """With the post-finalize version the same body is accepted, and the plan's
        deadline is set by its critical member rather than its moderate one.

        PRD §3.6: "The plan's own deadline, `due_at`, is the current instant plus
        the **minimum** correction allowance across the violations the plan covers
        — that is, the tightest of the 3, 10, 30 and 45 day allowances implied by
        those violations' effective severities."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_cap_submission_requires_finalized_inspection
        """
        ctx = _pending_review_visit_with_two_findings(api, catalog)
        finalized = fx.finalize_visit(api, ctx["inspection_id"])

        cap = validate_success(
            api.create_cap(
                f.cap_payload(
                    ctx["inspection_id"],
                    ctx["violation_ids"],
                    finalized["version"],
                    narrative="Retrain staff on supervision and replace the gate latch.",
                    proposed_completion_date="2026-08-08",
                ),
                headers=make_applicant_headers(ctx["provider_id"]),
            ),
            201,
        )

        assert cap["status"] == "SUBMITTED"
        assert cap["review_cycle_count"] == 1
        assert cap["provider_id"] == ctx["provider_id"], (
            "provider_id is not supplied but copied from the inspection"
        )
        assert_instant(cap["due_at"], "2026-08-08T13:00:00Z", "due_at")
        assert cap["reviewed_at"] is None
        assert cap["approved_at"] is None
        assert cap["completed_at"] is None
        assert cap["reviewed_by_user_id"] is None

        after = validate_success(
            api.get_inspection(ctx["inspection_id"], headers=supervisor_headers())
        )
        assert after["version"] == finalized["version"] + 1, (
            "a successful creation also increments the inspection's version"
        )

    def test_finalization_already_moved_both_findings_out_of_cited(
        self, api, catalog
    ):
        """Both violations sit in CORRECTION_PENDING before the plan is reviewed, so
        the approval finds nothing left in CITED to move.

        PRD §3.4: "every violation of the inspection still in `CITED` moves to
        `CORRECTION_PENDING` and receives its `correction_due_date`"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_cap_submission_requires_finalized_inspection
        """
        ctx = _pending_review_visit_with_two_findings(api, catalog)
        fx.finalize_visit(api, ctx["inspection_id"])

        for violation_id in ctx["violation_ids"]:
            row = validate_success(
                api.get_violation(violation_id, headers=supervisor_headers())
            )
            assert row["status"] == "CORRECTION_PENDING", (
                f"violation {violation_id} should have left CITED at finalization"
            )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 19, 0, 19)
        assert provider["critical_open_count"] == 1

    def test_the_review_of_the_accepted_plan_approves_it(self, api, catalog):
        """The supervisor's APPROVE stamps both instants and records the reviewing
        identity, its own FINALIZED precondition being satisfied.

        PRD §3.6: "An approval sets `status` to `APPROVED`, stamps both
        `reviewed_at` and `approved_at`, records the reviewing identity in
        `reviewed_by_user_id`, stores the note"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_cap_submission_requires_finalized_inspection
        """
        ctx = _pending_review_visit_with_two_findings(api, catalog)
        finalized = fx.finalize_visit(api, ctx["inspection_id"])
        cap = fx.submit_cap(
            api,
            ctx["provider_id"],
            ctx["inspection_id"],
            ctx["violation_ids"],
            finalized["version"],
            narrative="Retrain staff on supervision and replace the gate latch.",
            proposed_completion_date="2026-08-08",
        )

        reviewed = fx.review_cap(api, cap["id"], "APPROVE", "Plan accepted.")

        assert reviewed["status"] == "APPROVED"
        assert_instant(reviewed["approved_at"], "2026-08-05T13:00:00Z", "approved_at")
        assert_instant(reviewed["reviewed_at"], "2026-08-05T13:00:00Z", "reviewed_at")
        assert reviewed["reviewed_by_user_id"] is not None
        assert reviewed["review_note"] == "Plan accepted."


def _two_incident_reports(api):
    """Ivybridge Center, never inspected, with a FATALITY report filed two hours
    after the event and a MEDICATION_ERROR report filed three hours after.

    The provider has no inspections at all, so the segregation-of-duties lookback
    for the investigator is empty and the late-filing cascade has no candidate.
    """
    fx.set_clock(api, "2026-08-05T12:00:00Z")
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["INFANT", "PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Ivybridge Center",
        site_address="111 Ivybridge Rd",
        program_type="CENTER",
        requested_capacity=20,
    )
    fatality = fx.file_incident_report(
        api,
        provider["id"],
        incident_type="FATALITY",
        occurred_at="2026-08-05T10:00:00Z",
        affected_child_age_group="INFANT",
        narrative="An infant was found unresponsive during nap time and did not survive.",
    )
    medication = fx.file_incident_report(
        api,
        provider["id"],
        incident_type="MEDICATION_ERROR",
        occurred_at="2026-08-05T09:00:00Z",
        affected_child_age_group="PRESCHOOL",
        narrative=(
            "A preschooler received a second dose of an inhaler in error; no "
            "symptoms followed."
        ),
    )
    return {
        "provider_id": provider["id"],
        "fatality": fatality,
        "medication": medication,
        "ada": ada,
    }


class TestIncidentCloseRequiresGeneratedComplaintResolved:
    """§3.7: "when `generated_complaint_id` is not null, that complaint's status
    must be `CLOSED` or `SCREENED_OUT`"."""

    def test_a_fatality_report_may_not_be_merely_monitored(self, api):
        """Both reports arrive inside their windows, and the MONITOR disposition is
        refused for the fatality while leaving it in REPORTED.

        PRD §3.7: "but a `FATALITY` or `MISSING_CHILD` report may **never** be
        merely monitored, and the attempt is refused with
        `ERR_INCIDENT_REQUIRES_INVESTIGATION` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_incident_close_requires_generated_complaint_resolved
        """
        ctx = _two_incident_reports(api)
        for report in (ctx["fatality"], ctx["medication"]):
            assert report["status"] == "REPORTED"
            assert report["reporting_timeliness"] == "TIMELY"
            assert report["late_report_violation_created"] is False

        validate_error(
            api.review_incident_report(
                ctx["fatality"]["id"],
                "MONITOR",
                agency_note="Monitoring only.",
                headers=supervisor_headers(),
            ),
            "ERR_INCIDENT_REQUIRES_INVESTIGATION",
            409,
        )

        still_reported = validate_success(
            api.get_incident_report(ctx["fatality"]["id"], headers=supervisor_headers())
        )
        assert still_reported["status"] == "REPORTED"
        assert still_reported["generated_complaint_id"] is None

    def test_opening_an_investigation_generates_a_p1_agency_complaint(self, api):
        """The OPEN_INVESTIGATION disposition manufactures the sibling row this
        instance turns on, already screened in and priority P1.

        PRD §3.7: "auto-creates one complaint for the report's provider directly in
        `SCREENED_IN` — intake screening is implicit for agency-initiated
        investigations — with `intake_channel` `AGENCY_INCIDENT`,
        `allegation_category` `ABUSE` when the incident type is a fatality, a
        serious injury or a missing child and `RECORDS` otherwise,
        `affected_age_group` copied from the report's `affected_child_age_group`"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_incident_close_requires_generated_complaint_resolved
        """
        ctx = _two_incident_reports(api)
        opened = validate_success(
            api.review_incident_report(
                ctx["fatality"]["id"],
                "OPEN_INVESTIGATION",
                agency_note="Fatality: investigation opened.",
                headers=supervisor_headers(),
            )
        )

        assert opened["status"] == "INVESTIGATION_OPENED"
        assert_instant(opened["reviewed_at"], "2026-08-05T12:00:00Z", "reviewed_at")
        assert opened["generated_complaint_id"] is not None

        complaint = validate_success(
            api.get_complaint(
                opened["generated_complaint_id"], headers=supervisor_headers()
            )
        )
        assert complaint["status"] == "SCREENED_IN"
        assert complaint["intake_channel"] == "AGENCY_INCIDENT"
        assert complaint["allegation_category"] == "ABUSE"
        assert complaint["affected_age_group"] == "INFANT"
        assert complaint["priority"] == "P1"
        assert complaint["alleged_serious_harm"] is True
        assert complaint["anonymous"] is False
        assert complaint["complainant_name"] is None
        assert_instant(
            complaint["investigation_due_at"],
            "2026-09-04T12:00:00Z",
            "investigation_due_at",
        )

    def test_the_close_is_refused_while_the_generated_complaint_runs(self, api):
        """A SCREENED_IN sibling blocks the close, and a DETERMINED sibling still
        blocks it, so the gate reads the exact state rather than merely whether a
        determination exists.

        PRD §3.7: "A report that opened an investigation therefore cannot be closed
        while the investigation it started is still running."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_incident_close_requires_generated_complaint_resolved
        """
        ctx = _two_incident_reports(api)
        opened = validate_success(
            api.review_incident_report(
                ctx["fatality"]["id"],
                "OPEN_INVESTIGATION",
                agency_note="Fatality: investigation opened.",
                headers=supervisor_headers(),
            )
        )
        complaint_id = opened["generated_complaint_id"]

        validate_error(
            api.close_incident_report(
                ctx["fatality"]["id"],
                agency_note="Attempting closure.",
                headers=supervisor_headers(),
            ),
            "ERR_INVALID_COMPLAINT_STATE",
            409,
        )
        blocked = validate_success(
            api.get_incident_report(ctx["fatality"]["id"], headers=supervisor_headers())
        )
        assert blocked["status"] == "INVESTIGATION_OPENED"
        assert blocked["closed_at"] is None

        fx.assign_investigator(api, complaint_id, ctx["ada"]["id"])
        determined = fx.record_determination(
            api, complaint_id, ctx["ada"]["id"], "INCONCLUSIVE"
        )
        assert determined["status"] == "DETERMINED"

        validate_error(
            api.close_incident_report(
                ctx["fatality"]["id"],
                agency_note="Second attempt, complaint still open.",
                headers=supervisor_headers(),
            ),
            "ERR_INVALID_COMPLAINT_STATE",
            409,
        )
        assert (
            validate_success(
                api.get_incident_report(
                    ctx["fatality"]["id"], headers=supervisor_headers()
                )
            )["status"]
            == "INVESTIGATION_OPENED"
        )

    def test_closing_the_complaint_releases_the_report(self, api):
        """The identical close that failed twice returns 200 once the sibling
        complaint reaches CLOSED.

        PRD §3.7: "A supervisor **closes** a report from `UNDER_REVIEW` or
        `INVESTIGATION_OPENED`, optionally supplying a final `agency_note`, which
        sets `status` to `CLOSED` and stamps `closed_at`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_incident_close_requires_generated_complaint_resolved
        """
        ctx = _two_incident_reports(api)
        opened = validate_success(
            api.review_incident_report(
                ctx["fatality"]["id"],
                "OPEN_INVESTIGATION",
                headers=supervisor_headers(),
            )
        )
        complaint_id = opened["generated_complaint_id"]
        fx.assign_investigator(api, complaint_id, ctx["ada"]["id"])
        fx.record_determination(api, complaint_id, ctx["ada"]["id"], "INCONCLUSIVE")

        closed_complaint = validate_success(
            api.close_complaint(
                complaint_id,
                "Investigation concluded; no licensing violation established.",
                headers=supervisor_headers(),
            )
        )
        assert closed_complaint["status"] == "CLOSED"

        closed_report = validate_success(
            api.close_incident_report(
                ctx["fatality"]["id"],
                agency_note="Closed after the complaint was closed.",
                headers=supervisor_headers(),
            )
        )
        assert closed_report["status"] == "CLOSED"
        assert_instant(closed_report["closed_at"], "2026-08-05T12:00:00Z", "closed_at")

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 0, 0, 0)

    def test_a_monitored_report_has_no_sibling_and_closes_ungated(self, api):
        """The MEDICATION_ERROR report keeps generated_complaint_id null, so the same
        close endpoint applies no cross-entity precondition at all.

        PRD §3.7: "Monitoring moves the report to `UNDER_REVIEW`, stamps
        `reviewed_at`, stores the note and leaves `generated_complaint_id` null"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_incident_close_requires_generated_complaint_resolved
        """
        ctx = _two_incident_reports(api)
        monitored = validate_success(
            api.review_incident_report(
                ctx["medication"]["id"],
                "MONITOR",
                agency_note="Medication error: monitoring.",
                headers=supervisor_headers(),
            )
        )
        assert monitored["status"] == "UNDER_REVIEW"
        assert monitored["generated_complaint_id"] is None

        closed = validate_success(
            api.close_incident_report(
                ctx["medication"]["id"],
                agency_note="No further action.",
                headers=supervisor_headers(),
            )
        )
        assert closed["status"] == "CLOSED"
        assert_instant(closed["closed_at"], "2026-08-05T12:00:00Z", "closed_at")

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 0, 0, 0)
