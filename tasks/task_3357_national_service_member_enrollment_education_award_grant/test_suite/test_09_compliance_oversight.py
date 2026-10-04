"""Compliance oversight: visit spacing, conduct, findings with segregation of
duties, the corrective-action loop, the overdue sweep's three-hop cascade, and
award reinstatement (PRD §2.1, §3.3, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    conduct_visit,
    decide_finding,
    decide_finding_payload,
    get_enrollment,
    make_compliance_officer_headers,
    make_grantee_staff_headers,
    record_finding,
    schedule_visit,
    setup_active_enrollment,
    setup_award_suspended_by_overdue_sweep,
    setup_awarded_program,
    setup_finding_evidence_submitted,
    submit_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOverdueSweepCascade:
    def test_sweep_escalates_finding_suspends_award_and_enrollments(self, api, officer_headers):
        """One trigger, three hops: the overdue finding ESCALATED, its award
        SUSPENDED with reason ESCALATED_FINDING_OVERDUE, and its ACTIVE
        enrollment SUSPENDED with origin AWARD_CASCADE — all reported in the
        sweep response.

        PRD §3.8: "Escalation is a three-hop cascade: the finding escalates; its award, if `ACTIVE`, is suspended with `suspension_reason` recorded as `ESCALATED_FINDING_OVERDUE`; and that suspension cascades in turn to every `ACTIVE` enrollment of the award, each dropped to `SUSPENDED` with `suspension_origin` `AWARD_CASCADE`"
        PRD §3.8: "The sweep reports what it did: the identifiers of the findings it escalated (`escalated_finding_ids`), the awards it suspended (`suspended_award_ids`), and the enrollments it suspended (`suspended_enrollment_ids`)."

        Design: Difficulty/transitive_cascade/overdue_corrective_action_suspends_award_and_enrollments
        """
        scenario = setup_award_suspended_by_overdue_sweep()
        sweep = scenario["sweep"]
        assert scenario["finding_id"] in sweep["escalated_finding_ids"]
        assert scenario["award_id"] in sweep["suspended_award_ids"]
        assert scenario["enrollment_id"] in sweep["suspended_enrollment_ids"]
        finding = validate_success(api.get_finding(scenario["finding_id"], officer_headers))
        assert finding["status"] == "ESCALATED"
        award = validate_success(api.get_award(scenario["award_id"], officer_headers))
        assert award["status"] == "SUSPENDED"
        assert award["suspension_reason"] == "ESCALATED_FINDING_OVERDUE"
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["status"] == "SUSPENDED"
        assert enrollment["suspension_origin"] == "AWARD_CASCADE"

    def test_cascade_suspended_enrollment_rejects_allowance_payment(self, api):
        """Depth-4 observable: a payment against the cascade-suspended
        enrollment fails the ACTIVE-state check.

        PRD §3.6: "the enrollment must be `ACTIVE`, a state check that precedes every fiscal check (`ERR_ENROLLMENT_NOT_ACTIVE`)"
        PRD §2.9: "When an award is suspended — manually or through the overdue-finding escalation cascade — every one of its `ACTIVE` enrollments is suspended with it, stamped with `suspension_origin` `AWARD_CASCADE`"

        Design: Difficulty/transitive_cascade/overdue_corrective_action_suspends_award_and_enrollments
        """
        scenario = setup_award_suspended_by_overdue_sweep()
        resp = api.create_allowance_payment(
            scenario["enrollment_id"], {"amount_cents": 1000},
            make_grantee_staff_headers(scenario["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
        assert resp.status_code == 409


class TestVisitSpacing:
    def test_visit_exactly_thirty_days_away_allowed(self, api, officer_headers):
        """A second visit exactly 30 days after the first is accepted.

        PRD §3.8: "the new date must sit at least 30 days away, in either direction, from every other visit of that award that is `SCHEDULED` or `CONDUCTED`; exactly 30 days of separation is allowed, anything tighter is `ERR_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/visit_thirty_day_buffer_gap
        """
        program = setup_awarded_program()
        visit_1 = schedule_visit(program["award_id"], "co-one", scheduled_date="2026-11-02")
        assert visit_1["status"] == "SCHEDULED"
        visit_2 = schedule_visit(
            program["award_id"], "co-one", visit_type="FILE_REVIEW",
            scheduled_date="2026-12-02",
        )
        assert visit_2["status"] == "SCHEDULED", "exactly 30 days of separation is allowed"

    def test_visit_fifteen_days_away_rejected(self, api, officer_headers):
        """A third visit 15 days after the second is rejected even though it
        sits 45 days after the first — the buffer applies against every visit.

        PRD §3.8: "the new date must sit at least 30 days away, in either direction, from every other visit of that award that is `SCHEDULED` or `CONDUCTED`; exactly 30 days of separation is allowed, anything tighter is `ERR_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/visit_thirty_day_buffer_gap
        """
        program = setup_awarded_program()
        schedule_visit(program["award_id"], "co-one", scheduled_date="2026-11-02")
        schedule_visit(program["award_id"], "co-one", visit_type="FILE_REVIEW",
                       scheduled_date="2026-12-02")
        resp = api.create_visit(
            program["award_id"],
            {"visit_type": "SITE_VISIT", "scheduled_date": "2026-12-17"},
            make_compliance_officer_headers("co-one"),
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_TOO_SOON)
        assert resp.status_code == 409
        rows, meta = validate_paginated(
            api.list_award_visits(program["award_id"], officer_headers)
        )
        assert meta["total_count"] == 2


class TestVisitAndFindingLifecycle:
    def test_conduct_twice_is_invalid_state(self, api, officer_headers):
        """Conducting an already-CONDUCTED visit hits the transition guard and
        the original conducted_at stamp is not overwritten.

        PRD §3.8: "Conducting the visit stamps `conducted_at` and moves it `SCHEDULED` → `CONDUCTED`."
        PRD §2.10: "state guards (`ERR_INVALID_STATE` and its state-specific siblings)"

        Design: Corner/state_machines/conduct_conducted_visit_returns_invalid_state
        """
        program = setup_awarded_program()
        visit = schedule_visit(program["award_id"], "co-one")
        conducted = conduct_visit(visit["id"], "co-one")
        assert conducted["status"] == "CONDUCTED"
        assert conducted["conducted_at"].startswith("2026-10-02")
        resp = api.conduct_visit(visit["id"], make_compliance_officer_headers("co-one"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _ = validate_paginated(api.list_award_visits(program["award_id"], officer_headers))
        assert rows[0]["status"] == "CONDUCTED"
        assert rows[0]["conducted_at"].startswith("2026-10-02"), "conducted_at unchanged"

    def test_visit_closes_when_all_findings_resolved(self, api, officer_headers):
        """A decision by a different officer resolves the finding and bubbles
        the visit to CLOSED once every finding is RESOLVED.

        PRD §3.8: "An approval resolves the finding (`RESOLVED`), and when every finding of the visit is `RESOLVED` — with at least one finding in existence — the visit bubbles itself up to `CLOSED`."
        PRD §3.8: "The decider is recorded as `decided_by_officer_id`."

        Design: Corner/state_machines/visit_closes_when_all_findings_resolved
        """
        scenario = setup_finding_evidence_submitted()
        decided = decide_finding(scenario["finding_id"], "co-two", "APPROVE")
        assert decided["status"] == "RESOLVED"
        assert decided["decided_by_officer_id"] == "co-two"
        rows, _ = validate_paginated(
            api.list_award_visits(scenario["award_id"], officer_headers)
        )
        assert rows[0]["status"] == "CLOSED", "bubble-up on last finding resolved"

    def test_same_officer_cannot_decide_own_visit_finding(self, api, officer_headers):
        """Segregation of duties: the visit creator's decide is rejected; a
        different officer decides successfully.

        PRD §3.8: "the deciding officer's `X-User-ID` must differ from the visit's `created_by_officer_id`, with a self-decision rejected as `ERR_SOD_VIOLATION`."

        Design: Corner/validations/same_officer_cannot_decide_own_visit_finding
        """
        scenario = setup_finding_evidence_submitted()
        own = api.decide_finding(
            scenario["finding_id"], decide_finding_payload("APPROVE"),
            make_compliance_officer_headers("co-one"),
        )
        validate_error(own, ApiErrorId.ERR_SOD_VIOLATION)
        assert own.status_code == 403
        finding = validate_success(api.get_finding(scenario["finding_id"], officer_headers))
        assert finding["status"] == "EVIDENCE_SUBMITTED"
        other = api.decide_finding(
            scenario["finding_id"], decide_finding_payload("APPROVE", note="Verified"),
            make_compliance_officer_headers("co-two"),
        )
        assert validate_success(other)["status"] == "RESOLVED"

    def test_program_officer_cannot_decide_finding(self, api, officer_headers):
        """Finding decide admits only ComplianceOfficer; the program officer
        role is rejected outright.

        PRD §2.1: "Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/program_officer_cannot_decide_finding_returns_unauthorized
        """
        scenario = setup_finding_evidence_submitted()
        resp = api.decide_finding(
            scenario["finding_id"], decide_finding_payload("APPROVE"), officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        finding = validate_success(api.get_finding(scenario["finding_id"], officer_headers))
        assert finding["status"] == "EVIDENCE_SUBMITTED"

    def test_trust_administrator_cannot_schedule_visit(self, api):
        """The trust administrator has no compliance surface.

        PRD §2.1: "Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/trust_administrator_cannot_schedule_visit
        """
        program = setup_awarded_program()
        resp = api.create_visit(
            program["award_id"],
            {"visit_type": "SITE_VISIT", "scheduled_date": "2026-11-02"},
            TEST_USERS["trust_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestReinstateAndSweep:
    def test_reinstate_blocked_while_finding_escalated(self, api, officer_headers):
        """Reinstate over an ESCALATED finding is rejected; after the grantee
        submits evidence (accepted even from ESCALATED) and a second officer
        resolves it, reinstate succeeds and the cascade-suspended enrollment
        returns to ACTIVE with origin NONE.

        PRD §3.3: "Reinstating a `SUSPENDED` award is blocked while any finding of the award stands `ESCALATED` (`ERR_FINDINGS_ESCALATED`); a successful reinstate clears `suspension_reason` back to null and returns exactly the cascade-suspended enrollments — those whose `suspension_origin` is `AWARD_CASCADE` — to `ACTIVE` with origin `NONE`."
        PRD §3.8: "evidence is accepted from `ACTION_ASSIGNED` and, notably, from `ESCALATED` as well, so an escalated finding remains correctable."

        Design: Corner/validations/reinstate_blocked_while_finding_escalated
        """
        scenario = setup_award_suspended_by_overdue_sweep()
        blocked = api.reinstate_award(scenario["award_id"], officer_headers)
        validate_error(blocked, ApiErrorId.ERR_FINDINGS_ESCALATED)
        submitted = submit_evidence(scenario["finding_id"], scenario["org_id"],
                                    evidence_note="Files completed 10/17")
        assert submitted["status"] == "EVIDENCE_SUBMITTED", "remediation stays open"
        decide_finding(scenario["finding_id"], "co-two", "APPROVE")
        reinstated = validate_success(api.reinstate_award(scenario["award_id"], officer_headers))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["status"] == "ACTIVE"
        assert enrollment["suspension_origin"] == "NONE"

    def test_sweep_with_nothing_overdue_is_a_noop(self, api, officer_headers):
        """A sweep with no overdue corrective actions reports three empty lists
        and leaves every resource untouched — an OPEN finding has no due_at and
        is never swept.

        PRD §3.8: "A `ComplianceOfficer` can run the overdue sweep, which finds every finding in `ACTION_ASSIGNED` or `EVIDENCE_SUBMITTED` whose `due_at` is earlier than the current logical time and moves it to `ESCALATED`."
        PRD §3.8: "The sweep reports what it did: the identifiers of the findings it escalated (`escalated_finding_ids`), the awards it suspended (`suspended_award_ids`), and the enrollments it suspended (`suspended_enrollment_ids`)."

        Design: Corner/endpoints/sweep_with_nothing_overdue_is_a_noop
        """
        scenario = setup_active_enrollment()
        visit = schedule_visit(scenario["award_id"], "co-one")
        conduct_visit(visit["id"], "co-one")
        finding = record_finding(visit["id"], "co-one")
        resp = api.sweep_overdue(make_compliance_officer_headers("co-one"))
        sweep = validate_success(resp, 200)
        assert sweep["escalated_finding_ids"] == []
        assert sweep["suspended_award_ids"] == []
        assert sweep["suspended_enrollment_ids"] == []
        finding_now = validate_success(api.get_finding(finding["id"], officer_headers))
        assert finding_now["status"] == "OPEN"
        award = validate_success(api.get_award(scenario["award_id"], officer_headers))
        assert award["status"] == "ACTIVE"
        assert get_enrollment(scenario["enrollment_id"])["status"] == "ACTIVE"
