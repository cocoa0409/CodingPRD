"""The refusal catalogue: one triggering recipe per declared error id.

Each test drives the error, proves the refused call moved nothing, and then
sends the neighbouring request the same row *does* accept — so an
implementation that refuses too widely fails just as loudly as one that
refuses too narrowly.
"""

from test_helpers import (
    CODE_RATIO,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    NON_EXISTENT_ID,
    admin_headers,
    assert_capacity_slots,
    assert_cents,
    assert_instant,
    assert_point_ledger,
    assert_points,
    bgu_headers,
    factories as f,
    fixtures as fx,
    headers_with_blank_user_id,
    headers_with_unknown_role,
    headers_without_user_id,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    make_investigator_headers,
    supervisor_headers,
    types as t,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


def _in_progress_annual(api, catalog):
    """An IN_PROGRESS ANNUAL visit at VISIT_INSTANT on a DRAFT provider."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    provider = fx.create_provider(api, requested_capacity=10)
    inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        inspector["id"],
        VISIT_INSTANT,
        inspection_type="ANNUAL",
        target_age_groups=PRESCHOOL_ONLY,
    )
    fx.set_clock(api, VISIT_INSTANT)
    fx.start_visit(api, inspection["id"], inspector["id"])
    return provider, inspector, inspection


class TestStatePreconditionsGuardEveryRow:
    """§2.7: "State preconditions follow" — one wrong origin state per entity."""

    def test_a_freshly_cited_violation_cannot_be_marked_uncorrected(self, api, catalog):
        """UNCORRECTED is reachable only from CORRECTION_PENDING, which finalize
        creates; the very same CITED row is nonetheless vacatable.

        PRD §3.6: "a non-correction may be recorded only from
        `CORRECTION_PENDING`, and a vacation may be recorded from `CITED`,
        `CORRECTION_PENDING` or `UNCORRECTED`. Anything else is
        `ERR_INVALID_VIOLATION_STATE` (HTTP 409)."

        Design: Corner/errors/err_invalid_violation_state_uncorrected_before_finalize
        """
        provider, inspector, inspection = _in_progress_annual(api, catalog)
        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Nap room left unattended.",
        )
        assert violation["status"] == "CITED"
        assert_points(violation["assessed_points"], 15, "assessed_points")
        before = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        # §3.6: the counters read only finalized inspections, so nothing has
        # landed on the provider yet.
        assert_point_ledger(before, 0, 0, 0)

        validate_error(
            api.disposition_violation(
                violation["id"], "UNCORRECTED", headers=supervisor_headers()
            ),
            "ERR_INVALID_VIOLATION_STATE",
            409,
        )
        refused = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert refused["status"] == "CITED"
        assert refused["corrected_at"] is None

        vacated = validate_success(
            api.disposition_violation(
                violation["id"],
                "VACATED",
                vacated_reason="Cited against the wrong room.",
                headers=supervisor_headers(),
            )
        )
        assert vacated["status"] == "VACATED", (
            "only the requested target state was wrong, not the origin state"
        )
        assert vacated["vacated_reason"] == "Cited against the wrong room."
        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(after, 0, 0, 0)

    def test_a_waiver_cannot_be_sought_while_the_registry_is_still_silent(self, api):
        """The waiver path opens only for a DISQUALIFIED check, so a SUBMITTED one
        is refused and neither the check nor the person's clearance moves.

        PRD §3.3: "A check that is not `DISQUALIFIED` is `ERR_INVALID_CHECK_STATE`"

        Design: Corner/errors/err_invalid_check_state_waiver_requested_on_a_submitted_check
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
        assert check["status"] == "SUBMITTED"
        assert check["waiver_requested_at"] is None

        validate_error(
            api.request_waiver(
                check["id"],
                "The record is thirty years old and unrelated to child care.",
                headers=make_applicant_headers(provider["id"]),
            ),
            "ERR_INVALID_CHECK_STATE",
            409,
        )

        after = validate_success(
            api.get_background_check(check["id"], headers=bgu_headers())
        )
        assert after["status"] == "SUBMITTED"
        assert after["waiver_requested_at"] is None
        assert after["waiver_rationale"] is None
        person = validate_success(
            api.get_staff_member(director["id"], headers=admin_headers())
        )
        assert person["clearance_status"] == "PENDING", "the refusal has no cascade"

    def test_an_incident_cannot_be_closed_before_it_has_been_reviewed(self, api):
        """Closing accepts UNDER_REVIEW or INVESTIGATION_OPENED only; the MONITOR
        disposition that unlocks it is itself legal for a SERIOUS_INJURY.

        PRD §3.7: "The two operations on a report demand specific origin states,
        and a wrong one is refused with `ERR_INVALID_INCIDENT_STATE` (HTTP 409):
        dispositioning requires `REPORTED`, and closing accepts `UNDER_REVIEW` or
        `INVESTIGATION_OPENED`."

        Design: Corner/errors/err_invalid_incident_state_close_before_review
        """
        filed_at = "2026-08-05T12:00:00Z"
        fx.set_clock(api, filed_at)
        provider = fx.create_provider(api, requested_capacity=10)
        report = fx.file_incident_report(
            api,
            provider["id"],
            incident_type="SERIOUS_INJURY",
            occurred_at="2026-08-05T10:00:00Z",
            affected_child_age_group="PRESCHOOL",
            narrative="Child fell from a climber and needed stitches.",
        )
        assert report["status"] == "REPORTED"
        assert report["reporting_timeliness"] == "TIMELY"
        assert report["late_report_violation_created"] is False
        assert_instant(
            report["reporting_deadline_at"],
            "2026-08-06T10:00:00Z",
            "reporting_deadline_at",
        )

        validate_error(
            api.close_incident_report(report["id"], headers=supervisor_headers()),
            "ERR_INVALID_INCIDENT_STATE",
            409,
        )
        refused = validate_success(
            api.get_incident_report(report["id"], headers=admin_headers())
        )
        assert refused["status"] == "REPORTED"
        assert refused["closed_at"] is None

        reviewed = validate_success(
            api.review_incident_report(
                report["id"],
                "MONITOR",
                agency_note="Injury log reviewed; no pattern.",
                headers=supervisor_headers(),
            )
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["generated_complaint_id"] is None, "MONITOR opens no complaint"
        assert_instant(reviewed["reviewed_at"], filed_at, "reviewed_at")

        closed = validate_success(
            api.close_incident_report(
                report["id"],
                agency_note="No further action.",
                headers=supervisor_headers(),
            )
        )
        assert closed["status"] == "CLOSED"
        assert_instant(closed["closed_at"], filed_at, "closed_at")

    def test_an_amendment_awaiting_its_pre_move_visit_cannot_be_decided(self, api):
        """decide accepts only SUBMITTED, while withdraw also accepts
        PRE_INSPECTION_REQUIRED — so the same row refuses one and takes the other.

        PRD §3.9: "attaching the pre-move inspection requires
        `PRE_INSPECTION_REQUIRED`, deciding requires `SUBMITTED`, and withdrawing
        accepts either `SUBMITTED` or `PRE_INSPECTION_REQUIRED`."

        Design: Corner/errors/err_invalid_amendment_state_decide_before_the_pre_move_inspection
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        amendment = validate_success(
            api.create_amendment(
                f.amendment_payload(
                    provider["id"],
                    "SITE_MOVE",
                    provider["version"],
                    new_site_address="88 Oak Ave",
                ),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert amendment["requires_inspection"] is True
        assert amendment["status"] == "PRE_INSPECTION_REQUIRED"
        assert amendment["decided_at"] is None

        validate_error(
            api.decide_amendment(amendment["id"], "APPROVE", headers=admin_headers()),
            "ERR_INVALID_AMENDMENT_STATE",
            409,
        )
        refused = validate_success(
            api.get_amendment(amendment["id"], headers=admin_headers())
        )
        assert refused["status"] == "PRE_INSPECTION_REQUIRED"
        assert refused["decided_at"] is None
        unmoved = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert unmoved["site_address"] == provider["site_address"], (
            "a refused decision applies no effect"
        )

        withdrawn = validate_success(
            api.withdraw_amendment(
                amendment["id"], headers=make_applicant_headers(provider["id"])
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_instant(withdrawn["decided_at"], DEFAULT_LOGICAL_CLOCK, "decided_at")

    def test_an_appeal_presupposes_an_effective_action(self, api, catalog):
        """Filing an appeal requires EFFECTIVE; a PROPOSED action has no deadline
        yet, so the window gate cannot even be evaluated.

        PRD §3.8: "issuance requires `PROPOSED`, effectuation requires `ISSUED`,
        filing an appeal requires `EFFECTIVE`, and deciding an appeal requires
        `APPEALED`."

        Design: Corner/errors/err_invalid_enforcement_state_appeal_before_effectuation
        """
        provider, inspector, inspection = _in_progress_annual(api, catalog)
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Nap room left unattended.",
        )
        fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
        fx.finalize_visit(api, inspection["id"])
        landed = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(landed, 15, 0, 15)

        action = fx.propose_action(
            api,
            provider["id"],
            "WARNING",
            source_inspection_id=inspection["id"],
            rationale="First supervision failure.",
        )
        assert action["status"] == "PROPOSED"
        assert action["action_type"] == "WARNING"
        assert action["ladder_step"] == 1
        assert_points(action["basis_points"], 15, "basis_points")
        assert_cents(action["fine_amount_cents"], 37500)
        assert action["issued_at"] is None
        assert action["appeal_deadline_at"] is None

        validate_error(
            api.appeal_action(
                action["id"],
                "The room was covered by a floating aide.",
                headers=make_applicant_headers(provider["id"]),
            ),
            "ERR_INVALID_ENFORCEMENT_STATE",
            409,
        )
        refused = validate_success(
            api.get_enforcement_action(action["id"], headers=admin_headers())
        )
        assert refused["status"] == "PROPOSED"
        assert refused["appealed_at"] is None
        assert refused["appeal_note"] is None
        assert refused["appeal_deadline_at"] is None
        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert after["current_ladder_step"] == 0, "nothing was effectuated"


class TestUniquenessAndReferenceAgreement:
    """§2.7: "non-temporal constraint rules and referential-agreement rules"."""

    def test_only_one_live_check_per_person_per_type_may_exist(self, api):
        """A second FBI_FINGERPRINT is refused while the first is live, but the
        sibling registry type is accepted — the key is the pair, not the person.

        PRD §3.3: "Only one *live* check per person per type may exist: if any
        other check of the same person and the same type is already in
        `SUBMITTED`, `CLEARED`, `WAIVER_PENDING` or `WAIVED`, the request is
        refused with `ERR_DUPLICATE_CHECK_TYPE` (HTTP 409)."

        Design: Corner/errors/err_duplicate_check_type_second_live_fingerprint_check
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
        first = fx.open_check(api, director["id"], "FBI_FINGERPRINT")
        assert first["status"] == "SUBMITTED"

        validate_error(
            api.create_background_check(
                f.background_check_payload(director["id"], "FBI_FINGERPRINT"),
                headers=bgu_headers(),
            ),
            "ERR_DUPLICATE_CHECK_TYPE",
            409,
        )
        unchanged = validate_success(
            api.get_background_check(first["id"], headers=bgu_headers())
        )
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["version"] == first["version"]

        second = validate_success(
            api.create_background_check(
                f.background_check_payload(director["id"], "CHILD_ABUSE_REGISTRY"),
                headers=bgu_headers(),
            ),
            201,
        )
        assert second["status"] == "SUBMITTED"
        assert second["check_type"] == "CHILD_ABUSE_REGISTRY"
        assert second["id"] != first["id"]

        rows, meta = validate_paginated(
            api.list_background_checks(
                headers=bgu_headers(), staff_member_id=director["id"]
            )
        )
        assert meta["total_count"] == 2, "no second fingerprint row was created"
        assert {row["check_type"] for row in rows} == {
            "FBI_FINGERPRINT",
            "CHILD_ABUSE_REGISTRY",
        }

    def test_a_repeat_must_name_a_prior_citation_of_the_same_checklist_item(
        self, api, catalog
    ):
        """Pointing the repeat reference at another rule's violation is refused, so
        the repeat multiplier can never be earned by chaining unrelated findings.

        PRD §3.6: "The row named by `repeat_of_violation_id` must belong to the
        **same provider**, must name the **same `checklist_item_id`**, must have
        been created within 24 months of the new citation instant with the lower
        edge exclusive, and must not itself be `VACATED`. Any failure is
        `ERR_REPEAT_REFERENCE_INVALID` (HTTP 422)."

        Design: Corner/errors/err_repeat_reference_invalid_points_at_another_checklist_item
        """
        provider, inspector, inspection = _in_progress_annual(api, catalog)
        supervision = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Nap room left unattended.",
        )

        validate_error(
            api.create_violation(
                f.violation_payload(
                    inspection["id"],
                    catalog[CODE_RATIO],
                    primary_age_group="PRESCHOOL",
                    narrative="One staff member for fourteen preschoolers.",
                    repeat_of_violation_id=supervision["id"],
                ),
                headers=make_inspector_headers(inspector["id"]),
            ),
            "ERR_REPEAT_REFERENCE_INVALID",
            422,
        )
        _rows, meta = validate_paginated(
            api.list_violations(headers=admin_headers(), inspection_id=inspection["id"])
        )
        assert meta["total_count"] == 1, "the refused call created no Violation row"

        ratio = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_RATIO],
            primary_age_group="PRESCHOOL",
            narrative="One staff member for fourteen preschoolers.",
        )
        assert ratio["repeat_chain_depth"] == 0
        assert ratio["repeat_of_violation_id"] is None
        assert_points(ratio["assessed_points"], 8, "first-offence SERIOUS points")

        fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
        fx.finalize_visit(api, inspection["id"])
        landed = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_point_ledger(landed, 23, 0, 23)


class TestSafetyAndRegulatoryRulesAnswerFirst:
    """§2.7: "Business rules are evaluated after all state checks, in three
    groups: safety and regulatory rules first"."""

    def test_the_highest_priority_allegation_cannot_be_screened_out(self, api):
        """An ABUSE allegation computes P1 for every age band, so the screen-out is
        refused while SCREEN_IN on the identical row is accepted.

        PRD §3.7: "a complaint whose computed priority is `P1` may never be
        screened out**, and the attempt is refused with
        `ERR_P1_CANNOT_BE_SCREENED_OUT` (HTTP 409)"

        Design: Corner/errors/err_p1_cannot_be_screened_out_abuse_allegation
        """
        received_at = "2026-08-10T00:00:00Z"
        fx.set_clock(api, received_at)
        provider = fx.create_provider(api, requested_capacity=10)
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="PHONE",
            allegation_category="ABUSE",
            affected_age_group="PRESCHOOL",
            narrative="Caller reports a child was struck.",
        )
        assert complaint["priority"] == "P1"
        assert_instant(
            complaint["investigation_due_at"],
            "2026-09-09T00:00:00Z",
            "investigation_due_at",
        )

        validate_error(
            api.screen_complaint(complaint["id"], "SCREEN_OUT", headers=intake_headers()),
            "ERR_P1_CANNOT_BE_SCREENED_OUT",
            409,
        )
        refused = validate_success(
            api.get_complaint(complaint["id"], headers=admin_headers())
        )
        assert refused["status"] == "RECEIVED"
        assert refused["screened_at"] is None

        screened = validate_success(
            api.screen_complaint(complaint["id"], "SCREEN_IN", headers=intake_headers())
        )
        assert screened["status"] == "SCREENED_IN"
        assert_instant(screened["screened_at"], received_at, "screened_at")

    def test_a_substantiated_finding_needs_a_visit_to_hang_its_citation_on(self, api):
        """With no FINALIZED complaint inspection the substantiated branch is
        refused, while the unsubstantiated branch — which cites nothing — is taken.

        PRD §3.7: "a `FINALIZED` inspection whose `complaint_id` is this complaint
        must exist to carry the automatic citation, or the call is
        `ERR_COMPLAINT_INSPECTION_REQUIRED` (HTTP 409)"

        Design: Corner/errors/err_complaint_inspection_required_substantiated_without_a_visit
        """
        received_at = "2026-08-10T00:00:00Z"
        fx.set_clock(api, received_at)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="WEB",
            allegation_category="SUPERVISION",
            affected_age_group="PRESCHOOL",
            narrative="Children left alone in the yard.",
        )
        assert complaint["priority"] == "P2"
        fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
        assigned = fx.assign_investigator(api, complaint["id"], inspector["id"])
        assert assigned["status"] == "UNDER_INVESTIGATION"
        assert assigned["assigned_investigator_id"] == inspector["id"]

        validate_error(
            api.record_determination(
                complaint["id"],
                "SUBSTANTIATED",
                headers=make_investigator_headers(inspector["id"]),
            ),
            "ERR_COMPLAINT_INSPECTION_REQUIRED",
            409,
        )
        refused = validate_success(
            api.get_complaint(complaint["id"], headers=admin_headers())
        )
        assert refused["status"] == "UNDER_INVESTIGATION"
        assert refused["determination"] is None
        _rows, meta = validate_paginated(
            api.list_violations(headers=admin_headers())
        )
        assert meta["total_count"] == 0, "the refused cascade cited nothing"

        determined = validate_success(
            api.record_determination(
                complaint["id"],
                "UNSUBSTANTIATED",
                headers=make_investigator_headers(inspector["id"]),
            )
        )
        assert determined["status"] == "DETERMINED"
        assert determined["determination"] == "UNSUBSTANTIATED"
        assert determined["timeliness_flag"] == "ON_TIME"
        assert_instant(
            determined["investigation_due_at"],
            "2026-09-24T00:00:00Z",
            "investigation_due_at",
        )
        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert after["substantiated_complaint_count_24mo"] == 0
        assert_point_ledger(after, 0, 0, 0)

    def test_an_unresolved_critical_answers_before_the_point_balance(self, api, catalog):
        """Two promotion gates fail on the same call — one open CRITICAL and a
        non-zero point balance — and the safety gate is the one that answers.

        PRD §2.7: "Business rules are evaluated after all state checks, in three
        groups: safety and regulatory rules first, then temporal rules, then
        non-temporal constraint rules and referential-agreement rules, and last of
        all the capacity and fiscal rules."

        Design: Corner/errors/err_unresolved_critical_violation_blocks_promotion_before_the_points_gate
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        base = fx.setup_licensed_provider(
            api,
            catalog=catalog,
            requested_capacity=10,
            inspector_certified_age_groups=PRESCHOOL_ONLY,
            initial_scheduled_for=VISIT_INSTANT,
        )
        ctx, inspector = base["ctx"], base["inspector"]
        assert ctx.provider["license_status"] == "PROVISIONAL"
        assert_instant(
            ctx.provider["provisional_started_at"],
            DEFAULT_LOGICAL_CLOCK,
            "provisional_started_at",
        )

        # A passing ANNUAL finalized after the provisional start satisfies the
        # licence-dimension state check of §3.8, so only the two business gates
        # are left to fail.
        fx.run_visit(
            api,
            ctx.id,
            inspector["id"],
            "2026-08-10T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
            age_groups_observed=PRESCHOOL_ONLY,
            outcome="PASS",
        )
        failing = fx.run_visit(
            api,
            ctx.id,
            inspector["id"],
            "2026-08-11T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
            age_groups_observed=PRESCHOOL_ONLY,
            catalog=catalog,
            citations=[
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "PRESCHOOL",
                    "narrative": "Preschool room left unattended during nap.",
                }
            ],
            outcome="FAIL",
        )
        violation = failing["violations"][0]
        ctx.reload()
        assert ctx.provider["critical_open_count"] == 1
        assert_point_ledger(ctx.provider, 15, 0, 15)
        version_before = ctx.provider["version"]

        fx.set_clock(api, "2027-02-06T09:00:00Z")
        validate_error(
            api.promote_to_full(ctx.id, headers=supervisor_headers()),
            "ERR_UNRESOLVED_CRITICAL_VIOLATION",
            409,
        )
        refused = ctx.reload()
        assert refused["license_status"] == "PROVISIONAL", (
            "a refused promotion mutates nothing"
        )
        assert refused["version"] == version_before

        corrected = validate_success(
            api.disposition_violation(
                violation["id"], "VERIFIED_CORRECTED", headers=supervisor_headers()
            )
        )
        assert corrected["status"] == "VERIFIED_CORRECTED"
        cleared = ctx.reload()
        assert cleared["critical_open_count"] == 0
        assert_point_ledger(cleared, 0, 15, 15)

        promoted = validate_success(
            api.promote_to_full(ctx.id, headers=supervisor_headers())
        )
        assert promoted["license_status"] == "FULL", (
            "both business gates were all that stood in the way"
        )
        assert promoted["application_status"] == "LICENSED"


class TestTemporalAndEnforcementBlocks:
    """§3.8: the appeal window is frozen at issue, and an effective suspension
    freezes the licence itself."""

    def test_an_appeal_one_second_past_the_frozen_deadline_is_refused(self, api, catalog):
        """The deadline is 15 days after `issued_at` and is not moved by the later
        effectuation; the upper edge is inclusive, so one second later fails.

        PRD §3.8: "the current instant must be at or before `appeal_deadline_at`.
        **The upper edge is inclusive**: filing at exactly the deadline instant is
        accepted, and one second later is `ERR_APPEAL_DEADLINE_PASSED` (HTTP 409)."

        Design: Corner/errors/err_appeal_deadline_passed_one_second_after_the_window
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        base = fx.setup_licensed_provider(
            api,
            catalog=catalog,
            requested_capacity=10,
            inspector_certified_age_groups=PRESCHOOL_ONLY,
            initial_scheduled_for=VISIT_INSTANT,
        )
        ctx, inspector = base["ctx"], base["inspector"]
        issued_at = "2026-08-10T09:00:00Z"
        annual = fx.schedule_visit(
            api,
            ctx.id,
            inspector["id"],
            issued_at,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, issued_at)
        fx.start_visit(api, annual["id"], inspector["id"])
        for narrative in (
            "Preschool room unattended during nap.",
            "Second room unattended at pickup.",
        ):
            fx.cite(
                api,
                annual["id"],
                inspector["id"],
                catalog[CODE_SUPERVISION],
                primary_age_group="PRESCHOOL",
                narrative=narrative,
            )
        fx.submit_findings(api, annual["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
        fx.finalize_visit(api, annual["id"])
        ctx.reload()
        assert_point_ledger(ctx.provider, 30, 0, 30)

        action = fx.propose_action(
            api,
            ctx.id,
            "PROBATION",
            source_inspection_id=annual["id"],
            rationale="Two critical supervision failures.",
        )
        assert action["action_type"] == "PROBATION"
        assert action["ladder_step"] == 2
        assert_points(action["basis_points"], 30, "basis_points")
        # 50000 + 30 * 2500 = 125000 gross, second tier: +12500 surcharge, then a
        # 5 percent credit of 6875 off the 137500 net.
        assert_cents(action["fine_amount_cents"], 130625)

        issued = fx.issue_action(api, action["id"])
        assert issued["status"] == "ISSUED"
        assert_instant(issued["issued_at"], issued_at, "issued_at")
        assert_instant(
            issued["appeal_deadline_at"], "2026-08-25T09:00:00Z", "appeal_deadline_at"
        )

        fx.set_clock(api, "2026-08-12T09:00:00Z")
        effective = fx.effectuate_action(api, action["id"])
        assert effective["status"] == "EFFECTIVE"
        assert_instant(effective["effective_at"], "2026-08-12T09:00:00Z", "effective_at")
        assert_instant(
            effective["appeal_deadline_at"],
            "2026-08-25T09:00:00Z",
            "appeal_deadline_at is frozen at issue, not at effectuation",
        )
        on_probation = ctx.reload()
        assert on_probation["license_status"] == "PROBATION"
        assert on_probation["probation_cycle_count"] == 1
        assert on_probation["current_ladder_step"] == 2

        fx.set_clock(api, "2026-08-25T09:00:01Z")
        validate_error(
            api.appeal_action(
                action["id"],
                "A floating aide covered both rooms.",
                headers=ctx.headers,
            ),
            "ERR_APPEAL_DEADLINE_PASSED",
            409,
        )
        refused = validate_success(
            api.get_enforcement_action(action["id"], headers=admin_headers())
        )
        assert refused["status"] == "EFFECTIVE"
        assert refused["appealed_at"] is None
        assert refused["appeal_note"] is None

    def test_an_effective_suspension_blocks_the_decision_but_not_the_filing(
        self, api, catalog
    ):
        """A CAPACITY_DECREASE never reaches the critical-violation gate, so the
        refusal is attributable to the enforcement state alone — and a fresh
        amendment can still be filed while the licence is suspended.

        PRD §3.9: "No enforcement action of that provider may be `EFFECTIVE` with
        `action_type` `SUSPENSION` or `REVOCATION`, or the approval is
        `ERR_ACTIVE_ENFORCEMENT_BLOCKS_AMENDMENT` (HTTP 409)"

        Design: Corner/errors/err_active_enforcement_blocks_amendment_while_suspended
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        base = fx.setup_licensed_provider(
            api,
            catalog=catalog,
            requested_capacity=10,
            inspector_certified_age_groups=PRESCHOOL_ONLY,
            initial_scheduled_for=VISIT_INSTANT,
        )
        ctx, inspector = base["ctx"], base["inspector"]
        assert_capacity_slots(ctx.provider, 10, 0)

        first = fx.run_visit(
            api,
            ctx.id,
            inspector["id"],
            "2026-08-10T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
            age_groups_observed=PRESCHOOL_ONLY,
            catalog=catalog,
            citations=[
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "PRESCHOOL",
                    "narrative": "Preschool room unattended during nap.",
                },
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "PRESCHOOL",
                    "narrative": "Second room unattended at pickup.",
                },
            ],
            outcome="FAIL",
        )
        ctx.reload()
        assert_point_ledger(ctx.provider, 30, 0, 30)
        probation = fx.run_enforcement(
            api, ctx.id, "PROBATION", source_inspection_id=first["inspection"]["id"]
        )
        assert probation["status"] == "EFFECTIVE"
        on_probation = ctx.reload()
        assert on_probation["license_status"] == "PROBATION"

        # Filed while the licence still carries its ten slots, so the delta is
        # negative and no pre-move visit is required.
        amendment = validate_success(
            api.create_amendment(
                f.amendment_payload(
                    ctx.id,
                    "CAPACITY_DECREASE",
                    on_probation["version"],
                    requested_capacity=5,
                ),
                headers=ctx.headers,
            ),
            201,
        )
        assert amendment["requires_inspection"] is False
        assert amendment["status"] == "SUBMITTED"
        assert amendment["effective_capacity_delta"] == -5

        second = fx.run_visit(
            api,
            ctx.id,
            inspector["id"],
            "2026-08-11T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
            age_groups_observed=PRESCHOOL_ONLY,
            catalog=catalog,
            citations=[
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "PRESCHOOL",
                    "narrative": "Third room unattended the following morning.",
                }
            ],
            outcome="FAIL",
        )
        ctx.reload()
        assert_point_ledger(ctx.provider, 45, 0, 45)
        suspension = fx.run_enforcement(
            api, ctx.id, "SUSPENSION", source_inspection_id=second["inspection"]["id"]
        )
        assert suspension["status"] == "EFFECTIVE"
        assert suspension["ladder_step"] == 3
        assert_points(suspension["basis_points"], 45, "basis_points")
        # 150000 + 45 * 2500 = 262500 gross, second tier: +26250, less a 5 percent
        # credit of 14438 off the 288750 net.
        assert_cents(suspension["fine_amount_cents"], 274312)
        assert suspension["capacity_held_slots"] == 10
        suspended = ctx.reload()
        assert suspended["license_status"] == "SUSPENDED"
        assert_capacity_slots(suspended, 0, 10)

        filed_while_suspended = validate_success(
            api.create_amendment(
                f.amendment_payload(
                    ctx.id,
                    "SITE_MOVE",
                    suspended["version"],
                    new_site_address="88 Oak Ave",
                ),
                headers=ctx.headers,
            ),
            201,
        )
        assert filed_while_suspended["status"] == "PRE_INSPECTION_REQUIRED", (
            "filing during a suspension is permitted; only deciding is blocked"
        )

        validate_error(
            api.decide_amendment(amendment["id"], "APPROVE", headers=admin_headers()),
            "ERR_ACTIVE_ENFORCEMENT_BLOCKS_AMENDMENT",
            409,
        )
        refused = validate_success(
            api.get_amendment(amendment["id"], headers=admin_headers())
        )
        assert refused["status"] == "SUBMITTED"
        assert refused["decided_at"] is None
        after = ctx.reload()
        assert_capacity_slots(after, 0, 10)


class TestTheIdentityEnvelopeAndTheOwnershipChain:
    """§2.7: authentication comes first, and ownership only after existence."""

    def test_four_ways_to_fail_the_identity_envelope_all_answer_401(self, api):
        """A missing id, a blank id, an undeclared role and a ghost entity-backed
        id are indistinguishable to the caller: all four are 401, never 403.

        PRD §2.7: "Authentication comes first: the presence and non-blankness of
        `X-User-ID`, then the presence and validity of `X-User-Role`, then whether
        that role is admitted by the target endpoint, then whether an entity-backed
        role's identifier resolves to a row of its backing entity."

        Design: Corner/errors/err_unauthenticated_four_ways_to_fail_the_identity_envelope
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        # Provider creation is the one endpoint that sends no X-User-ID at all.
        provider = fx.create_provider(api, requested_capacity=10)

        envelopes = (
            ("X-User-ID absent entirely", headers_without_user_id(t.ROLE_APPLICANT)),
            ("an empty-string X-User-ID", headers_with_blank_user_id(t.ROLE_APPLICANT)),
            ("a role outside the eight declared", headers_with_unknown_role(provider["id"])),
            (
                "an entity-backed id that resolves to no Provider row",
                make_applicant_headers(NON_EXISTENT_ID),
            ),
        )
        for label, headers in envelopes:
            validate_error(
                api.submit_application(provider["id"], headers=headers),
                "ERR_UNAUTHENTICATED",
                401,
            )
            unchanged = validate_success(
                api.get_provider(
                    provider["id"], headers=make_applicant_headers(provider["id"])
                )
            )
            assert unchanged["application_status"] == "DRAFT", label
            assert unchanged["version"] == provider["version"], label

    def test_a_valid_identity_still_cannot_reach_another_holders_row(self, api):
        """Two chains, one rule: a roster reached through another provider's
        provider_id and an inspection reached by the wrong inspector are both 403,
        and the owner's identical request succeeds.

        PRD §2.7: "Ownership is checked after existence, since a resource must
        exist before it can be owned"

        Design: Corner/errors/err_ownership_violation_applicant_reaches_another_providers_roster
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider_a = fx.create_provider(
            api,
            legal_name="Bright Start Center",
            site_address="12 Elm St",
            program_type="CENTER",
            requested_capacity=10,
        )
        provider_b = fx.create_provider(
            api,
            legal_name="Little Acorns Home",
            site_address="40 Pine Rd",
            program_type="FAMILY_HOME",
            requested_capacity=6,
        )
        roster = fx.add_roster(
            api, provider_a["id"], age_group="PRESCHOOL", requested_group_size=10
        )
        assigned = fx.register_inspector(
            api, full_name="Ivy Cole", certified_age_groups=PRESCHOOL_ONLY
        )
        stranger = fx.register_inspector(
            api, full_name="Omar Vance", certified_age_groups=PRESCHOOL_ONLY
        )
        inspection = fx.schedule_visit(
            api,
            provider_a["id"],
            assigned["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )

        validate_error(
            api.patch_roster(
                roster["id"],
                staff_assigned_count=1,
                headers=make_applicant_headers(provider_b["id"]),
            ),
            "ERR_OWNERSHIP_VIOLATION",
            403,
        )
        untouched = validate_success(
            api.get_roster(roster["id"], headers=make_applicant_headers(provider_a["id"]))
        )
        assert untouched["staff_assigned_count"] == 0
        assert untouched["enrolled_count"] == 0
        assert untouched["version"] == roster["version"]

        validate_error(
            api.start_inspection(
                inspection["id"], headers=make_inspector_headers(stranger["id"])
            ),
            "ERR_OWNERSHIP_VIOLATION",
            403,
        )
        still_scheduled = validate_success(
            api.get_inspection(inspection["id"], headers=admin_headers())
        )
        assert still_scheduled["status"] == "SCHEDULED"
        assert still_scheduled["started_at"] is None

        accepted = validate_success(
            api.patch_roster(
                roster["id"],
                staff_assigned_count=1,
                headers=make_applicant_headers(provider_a["id"]),
            )
        )
        assert accepted["staff_assigned_count"] == 1
        assert accepted["version"] == roster["version"] + 1, (
            "the refusals were about identity, not about the payload"
        )
