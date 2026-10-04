"""Case lifecycle: initial state, invalid transitions, terminal lockdown,
the PENDING_CLOSE cycle, pagination, downtime computation, and fleet gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_case,
    make_uptime_coordinator_headers,
    setup_case_in_state,
    setup_clock,
    setup_full_environment,
    setup_fleet_with_truck,
    validate_error,
    validate_paginated,
    validate_success,
    create_case_payload,
)


class TestCaseInitialState:
    def test_case_initial_state_is_open(self, api):
        """PRD §3.2: "On success, the case is created in `OPEN` status with
        `opened_at` set to the server's clock, `closed_at` null,
        `downtime_hours` at 0.00, `diagnostic_minutes_authorized` at 0,
        `expedite_count` at 0, and `opened_from_fault_event_id` recorded when
        applicable."

        Design: Corner/state_machines/case_initial_state_is_open
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Init Fleet")
        case = validate_success(
            api.create_case(
                env["fleet"]["id"],
                env["truck"]["id"],
                create_case_payload(fault_code="SPN3216_FMI4"),
                env["uc"],
            ),
            expected_status=201,
        )
        assert_case(case)
        assert case["case_status"] == "OPEN"
        assert case["downtime_hours"] == 0.00
        assert case["expedite_count"] == 0
        assert case["closed_at"] is None

    def test_case_create_increments_truck_and_fleet_open_case_count(self, api):
        """PRD §3.2: "The truck's `open_case_count` and the fleet's
        `open_case_count` are each incremented."

        Design: Corner/state_machines/case_initial_state_is_open
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Init2 Fleet")
        validate_success(
            api.create_case(
                env["fleet"]["id"],
                env["truck"]["id"],
                create_case_payload(fault_code="SPN3216_FMI4"),
                env["uc"],
            ),
            expected_status=201,
        )
        truck = validate_success(
            api.get_truck(env["fleet"]["id"], env["truck"]["id"], env["fm"])
        )
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert truck["open_case_count"] == 1
        assert fleet["open_case_count"] == 1


class TestCaseInvalidTransitions:
    def test_case_close_from_open_returns_invalid_state_transition(self, api):
        """PRD §4: "POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/close` |
        Close a PENDING_CLOSE case" and PRD §5: "`ERR_INVALID_STATE_TRANSITION` |
        409 Conflict".

        Design: Corner/state_machines/case_close_from_open_returns_invalid_state_transition
        """
        setup_clock()
        env = setup_full_environment(fleet_name="IT Fleet")
        case = validate_success(
            api.create_case(
                env["fleet"]["id"],
                env["truck"]["id"],
                create_case_payload(),
                env["uc"],
            ),
            expected_status=201,
        )
        resp = api.close_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
        after = validate_success(
            api.get_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert after["case_status"] == "OPEN"

    def test_work_order_complete_from_draft_returns_invalid_state(self, api):
        """PRD §3.4: "When the repair finishes, the `DealerAdvisor` completes
        the work order by supplying `labor_minutes_actual` (zero or more) and a
        `repair_outcome` of `FIXED`, `NOT_FIXED`, or `PARTIAL`. Completion moves
        the work order `IN_PROGRESS` → `COMPLETED`."

        Design: Corner/state_machines/work_order_complete_from_draft_returns_invalid_state
        """
        setup_clock()
        env = setup_full_environment(fleet_name="WOIT Fleet")
        ctx = setup_case_in_state(env, "SCHEDULED")
        case = ctx["case"]
        wo = ctx["work_order"]
        assert wo["work_order_status"] == "DRAFT"
        resp = api.complete_work_order(
            env["fleet"]["id"],
            env["truck"]["id"],
            case["id"],
            wo["id"],
            {"labor_minutes_actual": 60, "repair_outcome": "FIXED"},
            env["da"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
        wos = validate_paginated(
            api.list_work_orders(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )[0]
        assert wos[0]["work_order_status"] == "DRAFT"


class TestCaseTerminalLockdown:
    def test_case_terminal_states_reject_further_transitions(self, api):
        """PRD §4: "POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/cancel` |
        Cancel an OPEN, TRIAGE, or SCHEDULED case" and PRD §5:
        "`ERR_INVALID_STATE_TRANSITION` | 409 Conflict".

        Design: Corner/state_machines/case_terminal_states_reject_further_transitions
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Term Fleet")
        ctx = setup_case_in_state(env, "CLOSED")
        case = ctx["case"]
        assert case["case_status"] == "CLOSED"
        resp = api.cancel_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
        after = validate_success(
            api.get_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert after["case_status"] == "CLOSED"

    def test_closed_case_rejects_triage_as_well(self, api):
        """PRD §3.3: "An `OPEN` case is triaged by a `UptimeCoordinator`,
        advancing it to `TRIAGE`" and PRD §5: "`ERR_INVALID_STATE_TRANSITION` |
        409 Conflict".

        Design: Corner/state_machines/case_terminal_states_reject_further_transitions
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Term2 Fleet")
        ctx = setup_case_in_state(env, "CLOSED")
        case = ctx["case"]
        resp = api.triage_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
        after = validate_success(
            api.get_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert after["case_status"] == "CLOSED"


class TestCasePagination:
    def test_cases_list_paginates_and_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "List endpoints paginate through `limit` and `offset`
        query parameters. `limit` defaults to 10 when omitted, with a minimum
        of 1 and a maximum of 100; `offset` defaults to 0."

        Design: Corner/entities/cases_list_paginates_and_reports_total_count_and_has_more
        """
        setup_clock()
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Page Fleet")
        uc = make_uptime_coordinator_headers()
        for fault_code in ["SPN3216_FMI4", "SPN3226_FMI4", "SPN168_FMI4"]:
            resp = api.create_case(
                fleet["id"], truck["id"], create_case_payload(fault_code=fault_code), uc
            )
            assert resp.status_code == 201, f"setup case create failed: {resp.text}"

        page1, meta1 = validate_paginated(
            api.list_cases(fleet["id"], truck["id"], fm, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_cases(fleet["id"], truck["id"], fm, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_cases_list_default_limit_covers_all_rows(self, api):
        """PRD §2.3: "List endpoints paginate through `limit` and `offset`
        query parameters. `limit` defaults to 10 when omitted, with a minimum
        of 1 and a maximum of 100; `offset` defaults to 0."

        Design: Corner/entities/cases_list_paginates_and_reports_total_count_and_has_more
        """
        setup_clock()
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Page2 Fleet")
        uc = make_uptime_coordinator_headers()
        for fault_code in ["SPN3216_FMI4", "SPN3226_FMI4", "SPN168_FMI4"]:
            api.create_case(
                fleet["id"], truck["id"], create_case_payload(fault_code=fault_code), uc
            )
        page, meta = validate_paginated(api.list_cases(fleet["id"], truck["id"], fm))
        assert len(page) == 3, "default limit=10 must cover all 3 rows"
        assert meta["limit"] == 10
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestCaseDowntimeComputedAtClose:
    def test_case_downtime_hours_computed_at_close(self, api):
        """PRD §3.8: "`closed_at` is stamped with the server clock;
        `downtime_hours` is computed as the elapsed time from `opened_at` to
        `closed_at`, converted to hours and rounded half-up to two decimal
        places (a 30-minute closure records 0.50; a 1-minute closure records
        0.02; the value is never negative)"

        Design: Corner/entities/case_downtime_hours_computed_at_close
        """
        setup_clock("2026-09-01T13:00:00Z")
        env = setup_full_environment(fleet_name="CF Fleet")
        ctx = setup_case_in_state(env, "OPEN")
        case = ctx["case"]
        open_case = validate_success(
            api.get_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert open_case["downtime_hours"] == 0.00, "an open case reports 0.00 downtime"
        # walk the same case to PENDING_CLOSE, then move the clock forward 2.5h
        case_id = case["id"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        validate_success(api.triage_case(fid, tid, case_id, env["uc"]))
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        validate_success(
            api.schedule_case(
                fid,
                tid,
                case_id,
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T14:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case_id, env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case_id, wos[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case_id, env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case_id, wos[0]["id"],
                {"labor_minutes_actual": 60, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case_id, env["da"]))
        setup_clock("2026-09-01T15:30:00Z")
        closed = validate_success(api.close_case(fid, tid, case_id, env["uc"]))
        assert closed["case_status"] == "CLOSED"
        assert closed["downtime_hours"] == pytest.approx(2.50, abs=0.001), (
            f"13:00 -> 15:30 is 2.50 hours, got {closed['downtime_hours']}"
        )


class TestFleetSuspendGate:
    def test_fleet_suspend_blocks_mutating_child_operations(self, api):
        """PRD §2.9: "A fleet whose `fleet_status` is not `ACTIVE` refuses
        every mutating operation under its hierarchy with `ERR_FLEET_NOT_ACTIVE`
        (HTTP 409)."

        Design: Corner/entities/fleet_suspend_blocks_mutating_child_operations
        """
        setup_clock()
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Susp Fleet")
        validate_success(api.suspend_fleet(fleet["id"], fm))
        resp = api.create_case(
            fleet["id"],
            truck["id"],
            create_case_payload(),
            make_uptime_coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_NOT_ACTIVE.value, expected_status=409)

    def test_suspended_fleet_recovers_via_reactivate(self, api):
        """PRD §3.1: "Fleets can later be suspended and reactivated; suspending
        flips `fleet_status` to `SUSPENDED` and bumps the fleet's `version`,
        and reactivation returns it to `ACTIVE`."

        Design: Corner/entities/fleet_suspend_blocks_mutating_child_operations
        """
        setup_clock()
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Susp2 Fleet")
        validate_success(api.suspend_fleet(fleet["id"], fm))
        reactivated = validate_success(api.reactivate_fleet(fleet["id"], fm))
        assert reactivated["fleet_status"] == "ACTIVE"
        resp = api.create_case(
            fleet["id"],
            truck["id"],
            create_case_payload(),
            make_uptime_coordinator_headers(),
        )
        assert resp.status_code == 201, (
            f"case create must succeed after reactivation: {resp.text}"
        )
