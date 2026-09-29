"""Declared initial states, walked edges, refused edges and the cascades.

Every test here translates one §1.2 state-machine claim: where a row is born,
which triggers the machine accepts from a given state, which it refuses with the
entity's own state error, and which side effects an accepted edge must perform in
the same request (PRD §2.10: "This service has no deferred jobs and no eventual
consistency").
"""

from test_helpers import (
    CODE_FACILITY,
    CODE_RECORDS,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_point_ledger,
    assert_points,
    assert_risk,
    assert_score,
    bgu_headers,
    factories as f,
    fixtures as fx,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL_ROOM = [{"age_group": "PRESCHOOL", "requested_group_size": 10}]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


class TestInitialStatesAndTheHappyPath:
    """§3.2: "The new record starts with `application_status` at `DRAFT`"."""

    def test_five_machines_are_born_in_their_declared_initial_states(self, api):
        """One chain births a provider, a person, a registry check, a visit, a
        complaint and an incident report, and no client ever names a state.

        PRD §3.2: "The new record starts with `application_status` at `DRAFT` and
        `license_status` at `NONE`"; "A newly attached person starts with
        `clearance_status` at `PENDING`"; §3.3: "is created in status `SUBMITTED`";
        §3.4: "creates the record in `SCHEDULED`"; §3.7: "The record is created in
        `RECEIVED` with `received_at` at the logical clock"; "The record is created
        in `REPORTED` with `late_report_violation_created` false"

        Design: Corner/state_machines/sm_initial_state_new_rows_start_in_declared_initial_states
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        assert provider["application_status"] == "DRAFT"
        assert provider["license_status"] == "NONE"

        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        director = fx.attach_staff(
            api, provider["id"], qualified_age_groups=["PRESCHOOL"], role_title="Director"
        )
        assert director["clearance_status"] == "PENDING"

        check = validate_success(
            api.create_background_check(
                f.background_check_payload(director["id"]), headers=bgu_headers()
            ),
            201,
        )
        assert check["status"] == "SUBMITTED"
        assert check["decided_at"] is None
        assert check["expires_at"] is None

        inspection = validate_success(
            api.create_inspection(
                f.inspection_payload(
                    provider["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for=VISIT_INSTANT,
                    target_age_groups=["PRESCHOOL"],
                ),
                headers=supervisor_headers(),
            ),
            201,
        )
        assert inspection["status"] == "SCHEDULED"

        complaint = validate_success(
            api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    intake_channel="WEB",
                    allegation_category="RECORDS",
                    affected_age_group="SCHOOL_AGE",
                    narrative="Attendance sheets not kept.",
                ),
                headers=intake_headers(),
            ),
            201,
        )
        assert complaint["status"] == "RECEIVED"
        assert_instant(complaint["received_at"], DEFAULT_LOGICAL_CLOCK, "received_at")

        report = validate_success(
            api.create_incident_report(
                f.incident_report_payload(
                    provider["id"],
                    incident_type="SERIOUS_INJURY",
                    occurred_at=DEFAULT_LOGICAL_CLOCK,
                    affected_child_age_group="PRESCHOOL",
                    narrative="Fall from climber, stitches.",
                ),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert report["status"] == "REPORTED"
        assert report["late_report_violation_created"] is False

    def test_the_application_walks_draft_to_licensed_and_mints_a_number(
        self, api, catalog
    ):
        """Four accepted edges in a row end with LIC-01-0001, 10 licensed slots and
        the room's approved size lifted from 0 to 10.

        PRD §3.8: "On success it moves `application_status` to `LICENSED` and
        `license_status` from `NONE` to `PROVISIONAL`; stamps both `licensed_at`
        and `provisional_started_at` with the current instant, so the two are equal
        at issuance; sets `approved_group_size` equal to `requested_group_size` on
        every one of the provider's rooms ... and mints the `license_number`. The
        number is the literal `LIC-`, then the two digits of the provider's
        `county_code` after its `CTY-` prefix, then a hyphen, then a sequence
        number padded with leading zeros to four digits."

        Design: Corner/state_machines/sm_valid_transition_application_walks_draft_to_licensed
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        ctx = fx.setup_provider_dossier(
            api,
            requested_capacity=10,
            rooms=PRESCHOOL_ROOM,
            director_qualified_age_groups=["PRESCHOOL"],
            catalog=catalog,
            seed_checklist=False,
        )

        submitted = fx.submit_application(ctx)
        assert submitted["application_status"] == "SUBMITTED"
        cleared = fx.clear_checks(ctx)
        assert cleared["application_status"] == "CHECKS_CLEARED"

        inspection = fx.schedule_visit(
            api,
            ctx.id,
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="INITIAL",
            target_age_groups=["PRESCHOOL"],
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        fx.submit_findings(api, inspection["id"], inspector["id"], "PASS", ["PRESCHOOL"])
        finalized = fx.finalize_visit(api, inspection["id"])
        assert finalized["status"] == "FINALIZED"
        assert ctx.reload()["application_status"] == "INITIAL_INSPECTION_PASSED"
        assert ctx.reload_roster("PRESCHOOL")["approved_group_size"] == 0

        licensed = validate_success(
            api.license_decision(ctx.id, "ISSUE", headers=supervisor_headers())
        )
        assert licensed["application_status"] == "LICENSED"
        assert licensed["license_status"] == "PROVISIONAL"
        assert licensed["license_number"] == "LIC-01-0001"
        assert licensed["licensed_capacity"] == 10
        assert licensed["suspended_capacity"] == 0
        assert_instant(licensed["licensed_at"], VISIT_INSTANT, "licensed_at")
        assert_instant(
            licensed["provisional_started_at"], VISIT_INSTANT, "provisional_started_at"
        )
        assert ctx.reload_roster("PRESCHOOL")["approved_group_size"] == 10

        assert_score(finalized["preliminary_compliance_score"], 100.00, "preliminary")
        assert_score(finalized["final_compliance_score"], 100.00, "final")
        assert finalized["violation_count"] == 0
        assert finalized["cap_required"] is False


class TestRefusedEdgesLeaveTheRowAlone:
    """§2.7: "the **first** rule violated determines the response — no later rule
    is evaluated"."""

    def test_clear_checks_is_refused_while_the_director_has_no_registry_results(
        self, api, catalog
    ):
        """A SUBMITTED application whose only director has never been checked cannot
        take the clearance edge, and the refusal writes nothing.

        PRD §3.3: "The flag is read as a precondition in three places: the
        supervisor's clearance advance, which moves `application_status` from
        `SUBMITTED` to `CHECKS_CLEARED` and recomputes the flag before requiring it
        to be true ... In all three, a false flag is `ERR_CLEARANCE_INCOMPLETE`
        (HTTP 409)."

        Design: Corner/state_machines/sm_precondition_enforcement_clear_checks_needs_complete_clearance
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        ctx = fx.setup_provider_dossier(
            api,
            requested_capacity=10,
            rooms=PRESCHOOL_ROOM,
            director_qualified_age_groups=["PRESCHOOL"],
            clear_director=False,
            catalog=catalog,
            seed_checklist=False,
        )
        submitted = fx.submit_application(ctx)
        version_at_submission = submitted["version"]

        validate_error(
            api.clear_checks(ctx.id, headers=supervisor_headers()),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        after = ctx.reload()
        assert after["clearance_complete"] is False
        assert after["application_status"] == "SUBMITTED"
        assert after["version"] == version_at_submission, (
            "the refused transition performed no write"
        )
        director = validate_success(
            api.get_staff_member(ctx.director["id"], headers=ctx.headers)
        )
        assert director["clearance_status"] == "PENDING"

    def test_voiding_vacates_the_citation_and_releases_the_window(self, api, catalog):
        """One void performs all three side effects: the open citation is VACATED,
        the provider's ledger stays empty and the inspector's count returns to 0.

        PRD §3.4: "Voiding sets `status` to `VOIDED`, vacates every violation of
        the inspection whose status is `CITED` or `CORRECTION_PENDING` — recording
        `vacated_reason` as an inspection-voided note — recomputes the inspector's
        `scheduled_visit_count`, releasing both the inspector's and the provider's
        occupied windows, recomputes the provider's violation-point counters, and
        increments the inspection's `version`."

        Design: Corner/state_machines/sm_side_effect_execution_void_vacates_citations_and_frees_the_slot
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=["PRESCHOOL"],
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Broken gate latch on the play yard.",
        )
        assert_points(violation["assessed_points"], 4, "assessed_points")

        voided = validate_success(
            api.void_inspection(inspection["id"], headers=supervisor_headers())
        )
        assert voided["status"] == "VOIDED"

        after_violation = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert after_violation["status"] == "VACATED"
        assert after_violation["vacated_reason"] is not None

        after_provider = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(after_provider, 0, 0, 0)
        assert_risk(after_provider, 0.00, "LOW")

        after_inspector = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert after_inspector["scheduled_visit_count"] == 0, (
            "the released window no longer blocks new scheduling"
        )

    def test_triggers_absent_from_the_scheduled_state_are_all_state_errors(
        self, api, catalog
    ):
        """Finalize, submit-for-review and reopen are all refused from SCHEDULED,
        the single legal trigger succeeds, and a replayed start is refused too.

        PRD §3.4: "The **assigned inspector**, and nobody else, starts it: the
        visit must be `SCHEDULED` (otherwise `ERR_INVALID_INSPECTION_STATE`, HTTP
        409)"

        Design: Corner/state_machines/sm_invalid_transitions_out_of_state_triggers_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=["PRESCHOOL"],
        )
        scheduled_version = inspection["version"]
        fx.set_clock(api, VISIT_INSTANT)
        inspector_hdrs = make_inspector_headers(inspector["id"])

        validate_error(
            api.finalize_inspection(inspection["id"], headers=supervisor_headers()),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )
        validate_error(
            api.submit_for_review(
                inspection["id"], "PASS", ["PRESCHOOL"], headers=inspector_hdrs
            ),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )
        validate_error(
            api.reopen_inspection(inspection["id"], headers=supervisor_headers()),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )

        started = validate_success(
            api.start_inspection(inspection["id"], headers=inspector_hdrs)
        )
        assert started["status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], VISIT_INSTANT, "started_at")
        assert started["version"] == scheduled_version + 1, (
            "exactly one successful write followed the scheduling"
        )

        validate_error(
            api.start_inspection(inspection["id"], headers=inspector_hdrs),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )

    def test_a_screened_out_complaint_is_frozen_for_ever(self, api):
        """SCREENED_OUT accepts no further trigger: re-screening, assignment and
        closing are all ERR_INVALID_COMPLAINT_STATE.

        PRD §3.7: "Screening out moves it to the terminal `SCREENED_OUT` and also
        stamps `screened_at`, leaving `timeliness_flag` null for ever."

        Design: Corner/state_machines/sm_terminal_state_screened_out_complaint_rejects_further_transitions
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        complaint = validate_success(
            api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    intake_channel="MAIL",
                    allegation_category="RECORDS",
                    affected_age_group="SCHOOL_AGE",
                    narrative="Sign-in sheets missing for two weeks.",
                ),
                headers=intake_headers(),
            ),
            201,
        )
        assert complaint["priority"] == "P3", (
            "§3.7: 'Records is `P3` in both' bands, and a provider whose "
            "license_status is NONE triggers no escalation"
        )
        screened_out = validate_success(
            api.screen_complaint(complaint["id"], "SCREEN_OUT", headers=intake_headers())
        )
        assert screened_out["status"] == "SCREENED_OUT"
        assert screened_out["timeliness_flag"] is None

        validate_error(
            api.screen_complaint(complaint["id"], "SCREEN_IN", headers=intake_headers()),
            "ERR_INVALID_COMPLAINT_STATE",
            409,
        )
        validate_error(
            api.assign_investigator(
                complaint["id"], inspector["id"], headers=supervisor_headers()
            ),
            "ERR_INVALID_COMPLAINT_STATE",
            409,
        )
        validate_error(
            api.close_complaint(
                complaint["id"],
                "Trying to close a screened-out complaint.",
                headers=supervisor_headers(),
            ),
            "ERR_INVALID_COMPLAINT_STATE",
            409,
        )

        after = validate_success(api.get_complaint(complaint["id"], headers=admin_headers()))
        assert after["status"] == "SCREENED_OUT"
        assert after["assigned_investigator_id"] is None


class TestReplaysCyclesAndCascades:
    """§2.10: "Whenever one operation changes a second entity, that change is
    visible immediately in the same request"."""

    def test_replaying_submit_application_is_a_state_error_not_a_second_success(
        self, api, catalog
    ):
        """The DRAFT-to-SUBMITTED edge is not idempotent: the replay is refused and
        the version stays where the first call left it.

        PRD §3.2: "**Submitting the application** moves `application_status` from
        `DRAFT` to `SUBMITTED`. Only the owning applicant may submit, and the
        request is refused with `ERR_INVALID_APPLICATION_STATE` (HTTP 409) unless
        the application is still in `DRAFT`."

        Design: Corner/state_machines/sm_idempotency_second_submit_application_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        ctx = fx.setup_provider_dossier(
            api,
            requested_capacity=10,
            rooms=PRESCHOOL_ROOM,
            director_qualified_age_groups=["PRESCHOOL"],
            clear_director=False,
            catalog=catalog,
            seed_checklist=False,
        )
        first = fx.submit_application(ctx)
        assert first["application_status"] == "SUBMITTED"

        validate_error(
            api.submit_application(ctx.id, headers=ctx.headers),
            "ERR_INVALID_APPLICATION_STATE",
            409,
        )

        after = ctx.reload()
        assert after["version"] == first["version"], "the replay wrote nothing"
        assert after["application_status"] == "SUBMITTED"

    def test_the_reopen_cycle_is_walked_twice_and_then_closed(self, api, catalog):
        """`reopen_count` reaches 1 then 2, each reopen clearing the submission
        fields, and the third reopen is refused so the cycle terminates.

        PRD §3.4: "Reopening requires `PENDING_REVIEW` and requires `reopen_count`
        to be strictly below 2; a third reopen is refused with
        `ERR_INVALID_INSPECTION_STATE`, the same error as a wrong-state reopen.
        Reopening returns `status` to `IN_PROGRESS` — the revert edge — increments
        `reopen_count`, and clears `outcome`, `age_groups_observed` and
        `submitted_at` back to null"

        Design: Corner/state_machines/sm_cyclic_inspection_reopen_bounded_at_two
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=["PRESCHOOL"],
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        fx.submit_findings(api, inspection["id"], inspector["id"], "PASS", ["PRESCHOOL"])

        first = validate_success(
            api.reopen_inspection(inspection["id"], headers=supervisor_headers())
        )
        assert first["reopen_count"] == 1
        assert first["status"] == "IN_PROGRESS"
        assert first["outcome"] is None
        assert first["age_groups_observed"] is None
        assert first["submitted_at"] is None

        fx.submit_findings(api, inspection["id"], inspector["id"], "PASS", ["PRESCHOOL"])
        second = validate_success(
            api.reopen_inspection(inspection["id"], headers=supervisor_headers())
        )
        assert second["reopen_count"] == 2

        fx.submit_findings(api, inspection["id"], inspector["id"], "PASS", ["PRESCHOOL"])
        validate_error(
            api.reopen_inspection(inspection["id"], headers=supervisor_headers()),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )
        after = validate_success(
            api.get_inspection(inspection["id"], headers=admin_headers())
        )
        assert after["status"] == "PENDING_REVIEW"
        assert after["reopen_count"] == 2

    def test_a_denied_application_voids_its_scheduled_visit(self, api, catalog):
        """DENY reaches down to the provider's children: the SCHEDULED INITIAL visit
        is VOIDED and the inspector's count returns to 0, while no licence is minted.

        PRD §3.8: "A `DENY` requires `application_status` to be `SUBMITTED` or
        `CHECKS_CLEARED`. It moves the status to the terminal `DENIED`, stores
        `decision_reason`, and voids every inspection of that provider whose status
        is `SCHEDULED`, `IN_PROGRESS` or `PENDING_REVIEW`"

        Design: Corner/state_machines/sm_cascade_down_application_denial_voids_scheduled_inspections
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        ctx = fx.setup_provider_dossier(
            api,
            requested_capacity=10,
            rooms=PRESCHOOL_ROOM,
            director_qualified_age_groups=["PRESCHOOL"],
            clear_director=False,
            catalog=catalog,
            seed_checklist=False,
        )
        fx.submit_application(ctx)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        inspection = fx.schedule_visit(
            api,
            ctx.id,
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="INITIAL",
            target_age_groups=["PRESCHOOL"],
        )

        denied = validate_success(
            api.license_decision(
                ctx.id,
                "DENY",
                decision_reason="Site fails minimum square footage.",
                headers=supervisor_headers(),
            )
        )
        assert denied["application_status"] == "DENIED"
        assert denied["license_status"] == "NONE"
        assert denied["decision_reason"] == "Site fails minimum square footage."
        assert denied["license_number"] is None

        after_inspection = validate_success(
            api.get_inspection(inspection["id"], headers=admin_headers())
        )
        assert after_inspection["status"] == "VOIDED"
        after_inspector = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert after_inspector["scheduled_visit_count"] == 0
        _rows, meta = validate_paginated(
            api.list_inspections(
                headers=admin_headers(), provider_id=ctx.id, status="SCHEDULED"
            )
        )
        assert meta["total_count"] == 0

    def test_a_failed_initial_visit_finalizes_without_advancing_the_application(
        self, api, catalog
    ):
        """The bubble-up edge is conditional on the outcome: a FAIL leaves the
        application at CHECKS_CLEARED while every other finalize effect still runs.

        PRD §3.4: "when the type is `INITIAL` and the outcome is `PASS` or
        `CONDITIONAL_PASS`, the provider's `application_status` moves from
        `CHECKS_CLEARED` to `INITIAL_INSPECTION_PASSED` ... When an `INITIAL`
        inspection finalizes with outcome `FAIL` the application status stays at
        `CHECKS_CLEARED` and the inspection still finalizes normally."

        Design: Corner/state_machines/sm_bubble_up_failed_initial_inspection_does_not_advance_application
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        inspector = fx.register_inspector(api, certified_age_groups=["PRESCHOOL"])
        ctx = fx.setup_provider_dossier(
            api,
            requested_capacity=10,
            rooms=PRESCHOOL_ROOM,
            director_qualified_age_groups=["PRESCHOOL"],
            catalog=catalog,
            seed_checklist=False,
        )
        fx.advance_to_checks_cleared(ctx)
        inspection = fx.schedule_visit(
            api,
            ctx.id,
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="INITIAL",
            target_age_groups=["PRESCHOOL"],
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Two preschoolers left unsupervised in the hallway.",
        )
        assert_points(violation["assessed_points"], 15, "assessed_points")
        fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", ["PRESCHOOL"])

        finalized = fx.finalize_visit(api, inspection["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["cap_required"] is True
        assert finalized["violation_count"] == 1
        assert_score(finalized["preliminary_compliance_score"], 85.00, "preliminary")
        assert_score(finalized["final_compliance_score"], 85.00, "final")

        provider = ctx.reload()
        assert provider["application_status"] == "CHECKS_CLEARED", (
            "the FAIL outcome blocks the bubble-up edge"
        )
        assert_point_ledger(provider, 15, 0, 15)
        assert provider["critical_open_count"] == 1

        after_violation = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert after_violation["status"] == "CORRECTION_PENDING"
        assert_instant(
            after_violation["correction_due_date"],
            "2026-08-08T09:00:00Z",
            "correction_due_date",
        )

    def test_a_late_report_with_no_finalized_visit_cites_nothing(self, api, catalog):
        """The late-report cascade is conditional on a citable inspection: with none,
        the report is still LATE_REPORT but no RE-601 violation appears.

        PRD §3.7: "If the set is **empty** — a brand-new provider that has never
        been inspected — nothing is cited, `late_report_violation_created` stays
        false, and the report itself is still created successfully. The late filing
        is recorded either way; only the citation is conditional."

        Design: Corner/state_machines/sm_conditional_cascade_late_incident_without_finalized_inspection
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        fx.set_clock(api, "2026-08-02T00:00:01Z")

        report = validate_success(
            api.create_incident_report(
                f.incident_report_payload(
                    provider["id"],
                    incident_type="SERIOUS_INJURY",
                    occurred_at=DEFAULT_LOGICAL_CLOCK,
                    affected_child_age_group="PRESCHOOL",
                    narrative="Reported a day late.",
                ),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert report["reporting_timeliness"] == "LATE_REPORT"
        assert_instant(
            report["reporting_deadline_at"],
            "2026-08-02T00:00:00Z",
            "reporting_deadline_at",
        )
        assert report["late_report_violation_created"] is False
        assert report["status"] == "REPORTED"

        _rows, meta = validate_paginated(
            api.list_violations(
                headers=admin_headers(), checklist_item_id=catalog[CODE_RECORDS]
            )
        )
        assert meta["total_count"] == 0

        after = validate_success(api.get_provider(provider["id"], headers=admin_headers()))
        assert_point_ledger(after, 0, 0, 0)
        assert after["critical_open_count"] == 0
