"""Corner-queue tests: RBAC peer-role isolation and the shared read surface."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_plan,
    create_crew_pool,
    create_locomotive,
    create_train_plan,
    create_yard,
    get_success_data,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

NP = TEST_USERS["network_planner_headers"]
CD = TEST_USERS["crew_dispatcher_headers"]
PP = TEST_USERS["power_planner_headers"]
TS = TEST_USERS["terminal_superintendent_headers"]
SM = TEST_USERS["service_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestRoleExclusiveDenial:
    def test_service_manager_cannot_write_plans(self, api, any_headers):
        """PRD §2.1: "A `NetworkPlanner` owns the logical clock, yard
        registration, train plan design/activation/retirement, and trip-plan
        assignment and replanning." and "A request whose role is recognized
        but not authorized for the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/service_manager_cannot_write_plans
        """
        yA = create_yard(yard_code="RB-A")
        yB = create_yard(yard_code="RB-B")
        plan = create_train_plan(
            yA["id"], yB["id"], train_symbol="RB-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        resp = api.activate_train_plan(
            plan["id"], {"expected_train_plan_version": plan["version"]}, SM
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        reread = get_success_data(api.get_train_plan(plan["id"], any_headers))
        assert reread["status"] == "DRAFT"

    def test_network_planner_cannot_operate_departures(self, api, any_headers):
        """PRD §2.1: "A `TerminalSuperintendent` owns scheduling, finalizing,
        and cancelling departures, and records every car movement event." and
        "A request whose role is recognized but not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/network_planner_cannot_operate_departures
        """
        yA = create_yard(yard_code="RB3-A")
        yB = create_yard(yard_code="RB3-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="RB3-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        pool = create_crew_pool(yA["id"])
        loco = create_locomotive(yA["id"], unit_number="RB3-UP1")
        resp = api.create_train_departure(
            {
                "train_plan_id": plan["id"], "service_date": "2026-09-01",
                "crew_pool_id": pool["id"], "locomotive_id": loco["id"],
                "car_count_planned": 5, "crew_hours_estimated": 6,
            },
            NP,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        loco_now = get_success_data(api.get_locomotive(loco["id"], any_headers))
        assert loco_now["status"] == "AVAILABLE"
        _data, meta = validate_paginated(api.list_train_departures(any_headers))
        assert meta["total_count"] == 0


class TestSharedReadSurface:
    def test_terminal_superintendent_cannot_triage_but_reads_everything(self, api, any_headers):
        """PRD §2.1: "A `ServiceManager` owns customer registration,
        service-credit adjustment, shipment creation and cancellation, and
        exception triage and resolution." and "Every GET endpoint is declared
        with authorized role `Any`, and the authorization layer maps every
        authenticated role — the five business roles plus `Any` itself — onto
        read access."

        Design: Corner/rbac/terminal_superintendent_cannot_triage_but_reads_everything
        """
        yA = create_yard(yard_code="RB2-A")
        create_yard(yard_code="RB2-B")
        resp = api.triage_service_exception(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {"triage_notes": "x", "root_cause_code": "OTHER"},
            TS,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        yard = get_success_data(api.get_yard(yA["id"], TS))
        assert yard["yard_code"] == "RB2-A", (
            "the shared GET surface works for the same role"
        )
