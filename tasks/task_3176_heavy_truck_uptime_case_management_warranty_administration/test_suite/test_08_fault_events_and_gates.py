"""Fault events: append-only shape, critical-fault response window, and the
truck decommission gate."""
from test_helpers import (
    ApiErrorId,
    assert_fault_event,
    create_case_payload,
    create_fault_event_payload,
    make_uptime_coordinator_headers,
    setup_clock,
    setup_fleet_with_truck,
    setup_full_environment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFaultEventImmutability:
    def test_fault_event_is_immutable_no_update_endpoint(self, api):
        """PRD §2.4: "`FaultEvent` rows are append-only telematics events: they
        carry `id` and `created_at` only; `updated_at` and `version` are absent
        because the row is never mutated after creation"
        PRD §3.2: "New fault events are born `UNLINKED`."

        Design: Corner/entities/fault_event_is_immutable_no_update_endpoint
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Imm Fleet")
        resp = api.create_fault_event(
            env["fleet"]["id"],
            env["truck"]["id"],
            create_fault_event_payload(
                severity="CRITICAL",
                recommended_action="STOP_IMMEDIATELY",
                occurred_at="2026-09-01T00:00:00Z",
            ),
            env["uc"],
        )
        fe = validate_success(resp, expected_status=201)
        assert_fault_event(fe)
        assert fe["event_status"] == "UNLINKED"
        assert "version" not in fe, "append-only rows must not carry version"
        assert "updated_at" not in fe, "append-only rows must not carry updated_at"

    def test_fault_event_dismiss_transitions_unlinked_to_dismissed(self, api):
        """PRD §3.2: "An `UNLINKED` event may be dismissed by a
        `UptimeCoordinator`, moving it to `DISMISSED`; both `LINKED` and
        `DISMISSED` are terminal."

        Design: Corner/entities/fault_event_is_immutable_no_update_endpoint
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Imm2 Fleet")
        fe = validate_success(
            api.create_fault_event(
                env["fleet"]["id"], env["truck"]["id"],
                create_fault_event_payload(
                    severity="INFO", recommended_action="MONITOR",
                    occurred_at="2026-09-01T00:00:00Z",
                ),
                env["uc"],
            ),
            expected_status=201,
        )
        dismissed = validate_success(
            api.dismiss_fault_event(
                env["fleet"]["id"], env["truck"]["id"], fe["id"], env["uc"]
            )
        )
        assert dismissed["event_status"] == "DISMISSED"


class TestCriticalFaultWindow:
    def test_err_critical_fault_window_lapsed(self, api):
        """PRD §3.2: "When `fault_event_id` is present and the referenced event
        had `severity` of `CRITICAL` together with `recommended_action` of
        `STOP_IMMEDIATELY`, the case must be opened within 30 minutes of the
        event's `occurred_at` — that is, `occurred_at` must be no earlier than
        the current clock minus 30 minutes; otherwise the create is rejected
        with `ERR_CRITICAL_FAULT_WINDOW_LAPSED` (HTTP 422)."

        Design: Corner/errors/err_critical_fault_window_lapsed
        """
        setup_clock("2026-09-01T11:00:00Z")
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Crit Fleet")
        uc = make_uptime_coordinator_headers()
        fe = validate_success(
            api.create_fault_event(
                fleet["id"], truck["id"],
                create_fault_event_payload(
                    fault_code="SPN3216_FMI4",
                    severity="CRITICAL",
                    recommended_action="STOP_IMMEDIATELY",
                    occurred_at="2026-09-01T11:00:00Z",
                ),
                uc,
            ),
            expected_status=201,
        )
        setup_clock("2026-09-01T12:00:00Z")  # 60 minutes later
        resp = api.create_case(
            fleet["id"], truck["id"],
            create_case_payload(fault_code="SPN3216_FMI4", fault_event_id=fe["id"]),
            uc,
        )
        validate_error(
            resp, ApiErrorId.ERR_CRITICAL_FAULT_WINDOW_LAPSED.value, expected_status=422
        )
        events = validate_paginated(
            api.list_fault_events(fleet["id"], truck["id"], uc)
        )[0]
        assert events[0]["event_status"] == "UNLINKED", (
            "rejected case create must leave the fault event UNLINKED"
        )

    def test_critical_fault_within_window_links_event(self, api):
        """PRD §3.2: "When `fault_event_id` is present and the referenced event
        had `severity` of `CRITICAL` together with `recommended_action` of
        `STOP_IMMEDIATELY`, the case must be opened within 30 minutes of the
        event's `occurred_at` — that is, `occurred_at` must be no earlier than
        the current clock minus 30 minutes; otherwise the create is rejected
        with `ERR_CRITICAL_FAULT_WINDOW_LAPSED` (HTTP 422)."
        PRD §3.2: "When the case was opened from a fault event, the event
        transitions `UNLINKED` → `LINKED`, and the case's `severity_at_open`
        snapshots the event's `severity`."

        Design: Corner/errors/err_critical_fault_window_lapsed
        """
        setup_clock("2026-09-01T11:00:00Z")
        fleet, truck, fm = setup_fleet_with_truck(fleet_name="Crit2 Fleet")
        uc = make_uptime_coordinator_headers()
        fe = validate_success(
            api.create_fault_event(
                fleet["id"], truck["id"],
                create_fault_event_payload(
                    fault_code="SPN3216_FMI4",
                    severity="CRITICAL",
                    recommended_action="STOP_IMMEDIATELY",
                    occurred_at="2026-09-01T11:00:00Z",
                ),
                uc,
            ),
            expected_status=201,
        )
        setup_clock("2026-09-01T11:29:00Z")  # within the 30-minute window
        case = validate_success(
            api.create_case(
                fleet["id"], truck["id"],
                create_case_payload(fault_code="SPN3216_FMI4", fault_event_id=fe["id"]),
                uc,
            ),
            expected_status=201,
        )
        assert case["case_status"] == "OPEN"
        assert case["severity_at_open"] == "CRITICAL"
        events = validate_paginated(
            api.list_fault_events(fleet["id"], truck["id"], uc)
        )[0]
        assert events[0]["event_status"] == "LINKED"


class TestDecommissionGate:
    def test_truck_decommission_conditional_action_requires_zero_open_cases(self, api):
        """PRD §3.1: "When a truck reaches end of life, a `FleetManager`
        decommissions it — but only when the truck's `open_case_count` is zero;
        otherwise the transition is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/endpoints/truck_decommission_conditional_action_requires_zero_open_cases
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cond Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        validate_success(
            api.create_case(fid, tid, create_case_payload(), env["uc"]),
            expected_status=201,
        )
        resp = api.decommission_truck(fid, tid, env["fm"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck["truck_status"] == "IN_SERVICE"

    def test_decommission_allowed_when_no_open_cases(self, api):
        """PRD §3.1: "When a truck reaches end of life, a `FleetManager`
        decommissions it — but only when the truck's `open_case_count` is zero;
        otherwise the transition is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/endpoints/truck_decommission_conditional_action_requires_zero_open_cases
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cond2 Fleet")
        resp = api.decommission_truck(env["fleet"]["id"], env["truck"]["id"], env["fm"])
        truck = validate_success(resp)
        assert truck["truck_status"] == "DECOMMISSIONED"
