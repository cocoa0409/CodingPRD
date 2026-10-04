"""Agent lifecycle: appointment windows, suspend/reinstate cycles, termination
terminality and the four-hop termination cascade, and portfolio reviews with
segregation of duties."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    bind_agent_policy_via_referral,
    create_agent,
    create_agent_quote,
    create_appointment,
    create_appointed_agent,
    create_schedule,
    create_consumer,
    get_success_data,
    set_clock,
    setup_product_with_feed,
    submit_agent_quote,
    validate_error,
    validate_paginated,
    validate_success,
)

UR = TEST_USERS["underwriting_reviewer_headers"]


class TestAppointmentWindows:
    def test_appointment_half_open_windows_allow_adjacency_reject_intersection(
        self, api, underwriting_reviewer_headers
    ):
        """PRD §3.6: "a new appointment whose window intersects an existing
        `ACTIVE` appointment for the same agent, state, and line is rejected with
        `ERR_APPOINTMENT_WINDOW_OVERLAP`, while adjacency — one window's end
        equaling the other's start — is allowed."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_windows_allow_adjacency_reject_intersection
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()

        appt1 = validate_success(api.create_appointment(
            agent["id"],
            {"state_code": "TX", "line_of_business": "AUTO",
             "effective_start": "2026-01-01T00:00:00Z",
             "effective_end": "2026-06-01T00:00:00Z"},
            underwriting_reviewer_headers,
        ), 201)
        assert appt1["status"] == "ACTIVE"

        # Adjacent: end == start is allowed
        appt2 = validate_success(api.create_appointment(
            agent["id"],
            {"state_code": "TX", "line_of_business": "AUTO",
             "effective_start": "2026-06-01T00:00:00Z",
             "effective_end": "2026-12-01T00:00:00Z"},
            underwriting_reviewer_headers,
        ), 201)
        assert appt2["status"] == "ACTIVE"

        # Strictly intersecting: rejected
        resp = api.create_appointment(
            agent["id"],
            {"state_code": "TX", "line_of_business": "AUTO",
             "effective_start": "2026-03-01T00:00:00Z",
             "effective_end": "2026-04-01T00:00:00Z"},
            underwriting_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_OVERLAP, 409)

        # Same window in a different state: overlap is scoped to (agent, state, line)
        appt3 = validate_success(api.create_appointment(
            agent["id"],
            {"state_code": "OK", "line_of_business": "AUTO",
             "effective_start": "2026-03-01T00:00:00Z",
             "effective_end": "2026-04-01T00:00:00Z"},
            underwriting_reviewer_headers,
        ), 201)
        assert appt3["status"] == "ACTIVE"

    def test_appointment_overlap_scoped_to_agent_state_line_triple(
        self, api, underwriting_reviewer_headers
    ):
        """PRD §3.6: "a new appointment whose window intersects an existing
        `ACTIVE` appointment for the same agent, state, and line is rejected with
        `ERR_APPOINTMENT_WINDOW_OVERLAP`, while adjacency — one window's end
        equaling the other's start — is allowed."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_windows_allow_adjacency_reject_intersection
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()
        create_appointment(
            agent["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-06-01T00:00:00Z",
        )

        # Same agent and window but a different line of business: allowed
        home_appt = validate_success(api.create_appointment(
            agent["id"],
            {"state_code": "TX", "line_of_business": "HOME",
             "effective_start": "2026-01-01T00:00:00Z",
             "effective_end": "2026-06-01T00:00:00Z"},
            underwriting_reviewer_headers,
        ), 201)
        assert home_appt["status"] == "ACTIVE"

        # Same agent, state, and line with a genuinely intersecting window:
        # rejected, and the existing appointment is untouched
        resp = api.create_appointment(
            agent["id"],
            {"state_code": "TX", "line_of_business": "AUTO",
             "effective_start": "2026-05-31T00:00:00Z",
             "effective_end": "2026-07-01T00:00:00Z"},
            underwriting_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_OVERLAP, 409)

        rows, meta = validate_paginated(
            api.list_agent_appointments(agent["id"], underwriting_reviewer_headers)
        )
        assert len(rows) == 2

    def test_appointment_reads_expired_after_clock_passes_end(
        self, api, carrier_admin_headers, underwriting_reviewer_headers
    ):
        """PRD §2.9: "An appointment whose `effective_end` is not null and is at or
        before the current logical time reads as `EXPIRED`, even though nothing was
        ever written to it."
        PRD §3.6: "Appointment to the carrier's agency force — moving
        `APPLICANT → APPOINTED` — is performed by an `UnderwritingReviewer` and
        requires the agent to already hold at least one `ACTIVE` appointment record
        (`ERR_AGENT_NOT_APPOINTED_IN_STATE` otherwise)."

        Design: Corner/state_machines/appointment_reads_expired_after_clock_passes_end
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()
        appt = create_appointment(
            agent["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-02-01T00:00:00Z",
        )
        set_clock("2026-02-01T00:00:00Z")
        fetched = validate_success(api.get_appointment(appt["id"], carrier_admin_headers))
        assert fetched["status"] == "EXPIRED"

        resp = api.appoint_agent(agent["id"], underwriting_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_APPOINTED_IN_STATE, 409)


class TestAgentSuspendReinstateCycle:
    def test_agent_suspend_reinstate_cycle_valid_pass(self, api):
        """PRD §3.6: "Suspension (`APPOINTED → SUSPENDED`) and reinstatement
        (`SUSPENDED → APPOINTED`) are reviewer actions; reinstatement, like initial
        appointment, requires at least one `ACTIVE` appointment record
        (`ERR_AGENT_NOT_APPOINTED_IN_STATE`)."

        Design: Difficulty/non_linear_state_machine/agent_suspend_reinstate_cycle_on_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()
        create_appointment(agent["id"])
        appointed = validate_success(api.appoint_agent(agent["id"], UR))
        assert appointed["status"] == "APPOINTED"

        suspended = validate_success(api.suspend_agent(agent["id"], UR))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_agent(agent["id"], UR))
        assert reinstated["status"] == "APPOINTED"

    def test_second_suspend_from_suspended_rejected(self, api):
        """PRD §3.6: "Suspension (`APPOINTED → SUSPENDED`) and reinstatement
        (`SUSPENDED → APPOINTED`) are reviewer actions; reinstatement, like
        initial appointment, requires at least one `ACTIVE` appointment record
        (`ERR_AGENT_NOT_APPOINTED_IN_STATE`)."

        Design: Difficulty/non_linear_state_machine/agent_suspend_reinstate_cycle_on_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()
        initial_version = agent["version"]
        create_appointment(agent["id"])
        validate_success(api.appoint_agent(agent["id"], UR))
        validate_success(api.suspend_agent(agent["id"], UR))
        validate_success(api.reinstate_agent(agent["id"], UR))
        validate_success(api.suspend_agent(agent["id"], UR))

        resp = api.suspend_agent(agent["id"], UR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        reinstated = validate_success(api.reinstate_agent(agent["id"], UR))
        assert reinstated["status"] == "APPOINTED"
        # appoint + suspend + reinstate + suspend + reinstate = +5 over create
        assert reinstated["version"] == initial_version + 5


class TestAgentTermination:
    def test_terminated_agent_is_terminal(self, api, underwriting_reviewer_headers):
        """PRD §3.6: "Termination — direct, or via a portfolio review — carries
        the platform's deepest cascade, three hops."

        Design: Corner/state_machines/terminated_agent_is_terminal
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_appointed_agent()
        validate_success(
            api.terminate_agent(agent["id"], underwriting_reviewer_headers,
                                payload={"reason": "non-performance"})
        )

        resp_suspend = api.suspend_agent(agent["id"], underwriting_reviewer_headers)
        validate_error(resp_suspend, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        resp_terminate = api.terminate_agent(agent["id"], underwriting_reviewer_headers)
        validate_error(resp_terminate, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_agent(agent["id"], underwriting_reviewer_headers))
        assert after["status"] == "TERMINATED"

    def test_portfolio_review_termination_cascade_agent_to_appointments_to_schedules_to_statements(
        self, api, carrier_admin_headers, underwriting_reviewer_headers,
        underwriting_reviewer_2_headers,
    ):
        """PRD §3.8: "`TERMINATE` runs the full agent-termination cascade of §3.6 —
        including its precondition that no `PLACED` bundle placements name the
        agent (`ERR_AGENT_HAS_ACTIVE_PLACEMENTS`)."
        PRD §3.6: "Hop one: every `ACTIVE` appointment of the agent moves to
        `TERMINATED` with `terminated_reason` recorded as `AGENT_TERMINATED`. Hop
        two: every `ACTIVE` commission schedule of the agent whose
        `line_of_business` is no longer covered by any remaining `ACTIVE`
        appointment moves to `VOIDED`. Hop three: every `DRAFT` commission
        statement of the agent moves to `STALE` — it must be regenerated against
        the surviving schedules."

        Design: Difficulty/transitive_cascade/portfolio_review_termination_cascade_agent_to_appointments_to_schedules_to_statements
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            }
        )
        agent = create_appointed_agent()
        appt_list, _ = validate_paginated(
            api.list_agent_appointments(agent["id"], carrier_admin_headers)
        )
        appt_id = appt_list[0]["id"]
        schedule = create_schedule(agent["id"])
        consumer = create_consumer()
        bind_agent_policy_via_referral(
            consumer, agent, ctx["product"]["id"],
            coverages=[{"coverage_code": "FLAT", "tier": "TIER_C"}],
        )
        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            carrier_admin_headers,
        ))
        assert stmt["status"] == "DRAFT"

        review = get_success_data(api.create_portfolio_review(
            agent["id"], {"reason": "loss ratio spike"}, underwriting_reviewer_headers
        ))
        get_success_data(api.issue_findings(
            review["id"], {"findings": "trailing loss ratio above appetite"},
            underwriting_reviewer_headers,
        ))
        acted = validate_success(api.take_review_action(
            review["id"], {"action": "TERMINATE"}, underwriting_reviewer_2_headers
        ))
        assert acted["status"] == "ACTION_TAKEN"
        assert acted["actioned_by_user_id"] == "test-underwriting-reviewer-2"

        agent_after = get_success_data(api.get_agent(agent["id"], carrier_admin_headers))
        assert agent_after["status"] == "TERMINATED"

        appt_after = get_success_data(api.get_appointment(appt_id, carrier_admin_headers))
        assert appt_after["status"] == "TERMINATED"
        assert appt_after["terminated_reason"] == "AGENT_TERMINATED"

        sched_after = get_success_data(
            api.get_commission_schedule(schedule["id"], carrier_admin_headers)
        )
        assert sched_after["status"] == "VOIDED"

        stmt_after = get_success_data(
            api.get_commission_statement(stmt["id"], carrier_admin_headers)
        )
        assert stmt_after["status"] == "STALE"

    def test_portfolio_review_termination_cascade_via_direct_terminate_replicates_hops(
        self, api, carrier_admin_headers, underwriting_reviewer_headers
    ):
        """PRD §3.6: "Hop one: every `ACTIVE` appointment of the agent moves to
        `TERMINATED` with `terminated_reason` recorded as `AGENT_TERMINATED`. Hop
        two: every `ACTIVE` commission schedule of the agent whose
        `line_of_business` is no longer covered by any remaining `ACTIVE`
        appointment moves to `VOIDED`. Hop three: every `DRAFT` commission
        statement of the agent moves to `STALE` — it must be regenerated against
        the surviving schedules."

        Design: Difficulty/transitive_cascade/portfolio_review_termination_cascade_agent_to_appointments_to_schedules_to_statements
        """
        set_clock("2026-01-01T00:00:00Z")
        setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"FLAT": {"TIER_C": 99995}},
                "min_premium_cents": 0,
            }
        )
        agent = create_appointed_agent()
        appt_list, _ = validate_paginated(
            api.list_agent_appointments(agent["id"], carrier_admin_headers)
        )
        appt_id = appt_list[0]["id"]
        schedule = create_schedule(agent["id"])
        # statement windows must end at or before the logical clock
        set_clock("2026-02-01T00:00:00Z")
        stmt = get_success_data(api.create_commission_statement(
            agent["id"],
            {"period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-02-01T00:00:00Z"},
            carrier_admin_headers,
        ))

        terminated = validate_success(api.terminate_agent(
            agent["id"], underwriting_reviewer_headers, payload={"reason": "exit"}
        ))
        assert terminated["status"] == "TERMINATED"

        appt_after = get_success_data(api.get_appointment(appt_id, carrier_admin_headers))
        assert appt_after["status"] == "TERMINATED"
        assert appt_after["terminated_reason"] == "AGENT_TERMINATED"

        sched_after = get_success_data(
            api.get_commission_schedule(schedule["id"], carrier_admin_headers)
        )
        assert sched_after["status"] == "VOIDED"

        stmt_after = get_success_data(
            api.get_commission_statement(stmt["id"], carrier_admin_headers)
        )
        assert stmt_after["status"] == "STALE"


class TestPortfolioReviewSegregation:
    def test_review_action_by_opening_reviewer_rejected_segregation_of_duties(
        self, api, underwriting_reviewer_headers, underwriting_reviewer_2_headers
    ):
        """PRD §3.8: "Taking action moves it `FINDINGS_ISSUED → ACTION_TAKEN`
        under a hard segregation-of-duties rule: the actioning reviewer's
        `X-User-ID` must differ from `opened_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`), and the platform records it as
        `actioned_by_user_id`."
        PRD §3.8: "`CONTINUE` leaves the agent untouched."

        Design: Corner/rbac/review_action_by_opening_reviewer_rejected_segregation_of_duties
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_appointed_agent()
        review = get_success_data(api.create_portfolio_review(
            agent["id"], {"reason": "loss ratio"}, underwriting_reviewer_headers
        ))
        get_success_data(api.issue_findings(
            review["id"], {"findings": "above appetite"}, underwriting_reviewer_headers
        ))

        resp = api.take_review_action(
            review["id"], {"action": "CONTINUE"}, underwriting_reviewer_headers
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        acted = validate_success(api.take_review_action(
            review["id"], {"action": "CONTINUE"}, underwriting_reviewer_2_headers
        ))
        assert acted["status"] == "ACTION_TAKEN"
        assert acted["action"] == "CONTINUE"
        assert acted["actioned_by_user_id"] == "test-underwriting-reviewer-2"

        agent_after = get_success_data(api.get_agent(agent["id"], underwriting_reviewer_headers))
        assert agent_after["status"] == "APPOINTED"
