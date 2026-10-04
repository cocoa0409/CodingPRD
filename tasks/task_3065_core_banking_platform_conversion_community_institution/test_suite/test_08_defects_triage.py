"""Post-live defect triage: priority scoring, segregation of duties, cycles."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_ops_headers, make_vtl_headers,
    setup_live_project, setup_live_project_with_defect,
    setup_mock_conversion_project, set_clock,
)

PM = TEST_USERS["pm_headers"]
OPS = TEST_USERS["ops_headers"]
VTL = TEST_USERS["vtl_headers"]
FC = TEST_USERS["fc_headers"]


class TestTriagePriority:
    def test_severity_plus_capped_age_score_bands(self, api):
        """PRD §3.11: "The severity contributes a weight: 100 for `SEV1`, 50
        for `SEV2`, 20 for `SEV3`. Age contributes in steps: the whole hours
        since `opened_at`, divided into complete twenty-four-hour steps, capped
        at three steps, times 10 points per step. The score is the sum; the
        priority band is 1 when the score is at least 110, 2 when at least 90,
        3 when at least 60, 4 when at least 30, and 5 otherwise — every
        boundary inclusive, so a score of exactly 110 yields priority 1 while
        109 yields priority 2."

        Design: Difficulty/combinatorial_formula/defect_triage_priority_multifactor_threshold
        """
        ctx = setup_live_project()
        pid = ctx["project"]["id"]
        set_clock("2026-09-25T00:00:00Z")
        d1 = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "D1 statement misalign",
                 "severity": "SEV1"}, OPS,
            ),
            201,
        )
        set_clock("2026-09-27T00:00:00Z")
        d2 = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "D2 card auth drop",
                 "severity": "SEV1"}, OPS,
            ),
            201,
        )
        set_clock("2026-09-28T00:00:00Z")
        d3 = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "D3 fresh sev1", "severity": "SEV1"},
                OPS,
            ),
            201,
        )
        t1 = get_success_data(api.triage_defect(d1["id"], VTL))
        t2 = get_success_data(api.triage_defect(d2["id"], VTL))
        t3 = get_success_data(api.triage_defect(d3["id"], VTL))
        # 72h -> age steps capped at 3 -> 100 + 30 = 130 -> priority 1.
        assert t1["triage_priority"] == 1
        # 24h -> 100 + 10 = 110 -> priority 1 (inclusive boundary).
        assert t2["triage_priority"] == 1
        # 0h -> 100 -> 90 <= 100 < 110 -> priority 2.
        assert t3["triage_priority"] == 2

    def test_age_cap_and_inclusive_boundary_interact(self, api):
        """PRD §3.11: "Age contributes in steps: the whole hours since
        `opened_at`, divided into complete twenty-four-hour steps, capped at
        three steps, times 10 points per step."
        PRD §3.11: "every boundary inclusive, so a score of exactly 110 yields
        priority 1 while 109 yields priority 2."

        Design: Difficulty/combinatorial_formula/defect_triage_priority_multifactor_threshold
        """
        ctx = setup_live_project()
        pid = ctx["project"]["id"]
        set_clock("2026-09-21T00:00:00Z")
        sev2 = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "sev2 aged", "severity": "SEV2"}, OPS,
            ),
            201,
        )
        sev3 = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "sev3 aged", "severity": "SEV3"}, OPS,
            ),
            201,
        )
        # Age 96h (4 days): the cap pins the age weight at 3 steps = 30.
        set_clock("2026-09-25T00:00:00Z")
        t_sev2 = get_success_data(api.triage_defect(sev2["id"], VTL))
        t_sev3 = get_success_data(api.triage_defect(sev3["id"], VTL))
        # SEV2: 50 + 30 = 80 -> 60 <= 80 < 90 -> priority 3.
        assert t_sev2["triage_priority"] == 3
        # SEV3: 20 + 30 = 50 -> 30 <= 50 < 60 -> priority 4.
        assert t_sev3["triage_priority"] == 4


class TestSegregationOfDuties:
    def test_reporter_cannot_triage_own_defect(self, api):
        """PRD §2.1: "Two segregation pairs are enforced against these recorded
        identifiers: the operator who reported a defect may not be the one who
        triages it, and the operator who approved a service credit claim may
        not be the one who pays it — either attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/errors/err_segregation_of_duties_reporter_cannot_triage
        """
        ctx = setup_live_project_with_defect(
            severity="SEV2", reporter_headers=make_ops_headers("ops-bob")
        )
        defect = ctx["defect"]
        resp = api.triage_defect(defect["id"], make_vtl_headers("ops-bob"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        ok = get_success_data(api.triage_defect(defect["id"], make_vtl_headers("vtl-nina")))
        assert ok["status"] == "TRIAGED"

    def test_finance_controller_cannot_triage_defects(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/finance_controller_cannot_triage_defects
        """
        ctx = setup_live_project_with_defect(severity="SEV3")
        resp = api.triage_defect(ctx["defect"]["id"], FC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestDefectCycle:
    def test_reject_fix_retains_priority_and_reopen_reresolve(self, api):
        """PRD §3.11: "from `IN_FIX`, the vendor may reject the fix, returning
        the defect to `OPEN` with its `triage_priority` retained."
        PRD §3.11: "A `ProjectManager` may reopen a resolved defect (`RESOLVED
        → REOPENED`), which increments `reopened_count`, clears `resolved_at`
        to null, forces `credit_eligible` false"
        PRD §3.11: "The SLA deadline never moves: resolving a `REOPENED` defect
        recomputes `credit_eligible` against the original deadline."

        Design: Difficulty/non_linear_state_machine/defect_machine_cycle_reopen_reresolve_retain_priority
        """
        ctx = setup_live_project_with_defect(
            severity="SEV2", defect_clock="2026-09-21T00:00:00Z"
        )
        defect = ctx["defect"]
        assert defect["sla_deadline"] == "2026-09-24T00:00:00.000Z"
        triaged = get_success_data(api.triage_defect(defect["id"], VTL))
        # SEV2 fresh: 50 + 0 = 50 -> priority 4.
        assert triaged["triage_priority"] == 4
        get_success_data(api.start_fix_defect(defect["id"], VTL))
        rejected = get_success_data(api.reject_fix_defect(defect["id"], VTL))
        assert rejected["status"] == "OPEN"
        assert rejected["triage_priority"] == 4
        set_clock("2026-09-22T00:00:00Z")
        resolved = get_success_data(api.resolve_defect(defect["id"], VTL))
        assert resolved["credit_eligible"] is False
        set_clock("2026-09-23T00:00:00Z")
        reopened = get_success_data(api.reopen_defect(defect["id"], PM))
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_count"] == 1
        assert reopened["credit_eligible"] is False
        set_clock("2026-09-25T12:00:00Z")
        resolved2 = get_success_data(api.resolve_defect(defect["id"], VTL))
        assert resolved2["status"] == "RESOLVED"
        assert resolved2["credit_eligible"] is True
        assert resolved2["resolved_at"] == "2026-09-25T12:00:00.000Z"

    def test_cycle_returns_to_open_and_priority_survives(self, api):
        """PRD §3.11: "from `IN_FIX`, the vendor may reject the fix, returning
        the defect to `OPEN` with its `triage_priority` retained."

        Design: Difficulty/non_linear_state_machine/defect_machine_cycle_reopen_reresolve_retain_priority
        """
        ctx = setup_live_project_with_defect(
            severity="SEV1", defect_clock="2026-09-21T00:00:00Z"
        )
        defect = ctx["defect"]
        triaged = get_success_data(api.triage_defect(defect["id"], VTL))
        assert triaged["triage_priority"] == 2  # 100 + 0
        get_success_data(api.start_fix_defect(defect["id"], VTL))
        rejected = get_success_data(api.reject_fix_defect(defect["id"], VTL))
        assert rejected["status"] == "OPEN"
        assert rejected["triage_priority"] == 2
        # From OPEN the defect may be triaged or resolved again.
        again = get_success_data(api.triage_defect(defect["id"], VTL))
        assert again["status"] == "TRIAGED"


class TestAncillaryCascade:
    def test_resolve_demotes_verified_system_and_reverify_closes_cycle(self, api):
        """PRD §3.11: "Resolution is possible from `OPEN`, `TRIAGED`, `IN_FIX`,
        and `REOPENED`, and always does the same three things: stamps
        `resolved_at` from the clock; sets `credit_eligible` true exactly when
        `resolved_at` falls after the `sla_deadline`; and, when
        `linked_system_id` is set, knocks the linked ancillary system back —
        `VERIFIED` to `INTEGRATING`, `RETEST_PASSED` to `FAILED`."

        Design: Difficulty/non_linear_state_machine/ancillary_system_machine_cycle_via_defect_cascade
        """
        ctx = setup_live_project()
        sys_id = ctx["system"]["id"]
        defect = get_success_data(
            api.create_defect(
                {"project_id": ctx["project"]["id"],
                 "title": "online banking SSO broken", "severity": "SEV3",
                 "linked_system_id": sys_id},
                OPS,
            ),
            201,
        )
        get_success_data(api.resolve_defect(defect["id"], VTL))
        sys_after = get_success_data(api.get_ancillary_system(sys_id, OPS))
        # The defect-resolve cascade knocks VERIFIED back to INTEGRATING —
        # cycle link 1 (VERIFIED -> INTEGRATING) is the observable assertion.
        assert sys_after["status"] == "INTEGRATING"

    def test_failed_integration_retest_cycle(self, api):
        """PRD §3.8: "A failed system can be retested to `RETEST_PASSED`, which
        is also terminal and equally satisfies the go-live requirement."

        Design: Corner/endpoints/ancillary_failed_retest_cycle
        """
        ctx = setup_mock_conversion_project()
        pid = ctx["project"]["id"]
        sys_row = get_success_data(
            api.create_ancillary_system(
                {"project_id": pid, "name": "ITEMS-1",
                 "category": "ITEM_PROCESSING", "interface_version": "v1"},
                OPS,
            ),
            201,
        )
        get_success_data(api.start_integration(sys_row["id"], OPS))
        get_success_data(api.fail_integration(sys_row["id"], OPS))
        retested = get_success_data(api.retest_integration(sys_row["id"], OPS))
        assert retested["status"] == "RETEST_PASSED"
        resp = api.verify_integration(sys_row["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_resolve_demotes_retest_passed_back_to_failed(self, api):
        """PRD §3.8: "resolving a defect linked to a system knocks a `VERIFIED`
        system back to `INTEGRATING` and a `RETEST_PASSED` system back to
        `FAILED`, forcing re-verification before any later go-live gate
        evaluation."

        Design: Difficulty/non_linear_state_machine/ancillary_system_machine_cycle_via_defect_cascade
        """
        ctx = setup_mock_conversion_project()
        pid = ctx["project"]["id"]
        sys_row = get_success_data(
            api.create_ancillary_system(
                {"project_id": pid, "name": "RPT-1", "category": "REPORTING",
                 "interface_version": "v4"},
                OPS,
            ),
            201,
        )
        get_success_data(api.start_integration(sys_row["id"], OPS))
        get_success_data(api.fail_integration(sys_row["id"], OPS))
        get_success_data(api.retest_integration(sys_row["id"], OPS))
        defect = get_success_data(
            api.create_defect(
                {"project_id": pid, "title": "report feed stale",
                 "severity": "SEV3", "linked_system_id": sys_row["id"]},
                OPS,
            ),
            201,
        )
        get_success_data(api.resolve_defect(defect["id"], VTL))
        sys_after = get_success_data(api.get_ancillary_system(sys_row["id"], OPS))
        assert sys_after["status"] == "FAILED"


class TestDefectTerminalState:
    def test_closing_closed_defect_rejected(self, api):
        """PRD §3.11: "Closing a defect (`RESOLVED → CLOSED`, terminal) is
        permitted only while no `OPEN` service credit claim references it."

        Design: Corner/errors/err_invalid_state_on_terminal_defect_close_twice
        """
        ctx = setup_live_project_with_defect(severity="SEV3")
        defect = ctx["defect"]
        get_success_data(api.resolve_defect(defect["id"], VTL))
        closed = get_success_data(api.close_defect(defect["id"], PM))
        assert closed["status"] == "CLOSED"
        resp = api.close_defect(defect["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
