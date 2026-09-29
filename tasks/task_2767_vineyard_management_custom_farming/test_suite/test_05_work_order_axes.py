"""Crew registration and the two independent axes of a scheduled task."""
from test_helpers import (
    ApiErrorId,
    assert_crew,
    assert_instant,
    assert_money,
    assert_plan_ledger,
    assert_version,
    make_crew_supervisor_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestCrewRegistration:
    """PRD §3.4 — `crew_status` carries a declared default."""

    def test_crew_registered_without_a_status_is_active_and_bookable(self, api):
        """`crew_status` is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE` when the field is omitted; only an `ACTIVE` crew may be scheduled or dispatched, and referencing an `INACTIVE` one is refused with `ERR_CREW_INACTIVE`.

        Design: Corner/entities/crew_create_omitting_crew_status_defaults_to_active
        """
        payload = f.crew_payload(crew_status=f.OMIT)
        assert "crew_status" not in payload

        data = validate_success(api.create_crew(payload, fx.VM), 201)

        assert_crew(data)
        assert data["crew_status"] == "ACTIVE"
        assert data["scheduled_work_order_count"] == 0
        assert data["pest_certified"] is False
        assert_version(data, 1, "crew")


class TestExecutionAxisGuards:
    """PRD §3.4 — the execution dimension and its terminal states."""

    def test_completing_a_scheduled_order_is_refused(self, api):
        """The same supervisor reports the finished work, supplying `actual_vines` and `actual_hours`; this requires the order to be `IN_PROGRESS`, otherwise `ERR_WORK_ORDER_NOT_IN_PROGRESS`.

        Design: Corner/state_machines/work_order_complete_from_scheduled_rejected
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"],
            planned_vines=6000, planned_hours=10.0,
        )
        assert_money(order["estimated_labor_cost"], 5011.50, "estimated_labor_cost")

        validate_error(
            api.complete_work_order(
                order["id"], f.complete_work_order_payload(5200, 12.0),
                make_crew_supervisor_headers(s.crew["id"]),
            ),
            ApiErrorId.ERR_WORK_ORDER_NOT_IN_PROGRESS,
        )

        order = fx.read_work_order(api, order["id"])
        assert order["execution_status"] == "SCHEDULED"
        assert order["payroll_status"] == "NOT_PAYABLE"
        assert order["actual_labor_cost"] is None
        assert_money(order["estimated_labor_cost"], 5011.50, "estimated_labor_cost")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 5011.50,
                     "committed_cost")

    def test_completion_writes_the_actual_cost_and_advances_payroll(self, api):
        """Completion moves execution `IN_PROGRESS → COMPLETED`, stamps `completed_at`, writes `actual_labor_cost` from the reported-work variant of the labor formula, advances payroll `NOT_PAYABLE → PENDING`.

        Design: Corner/state_machines/work_order_complete_sets_actual_cost_and_advances_payroll_axis
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"],
            planned_vines=6000, planned_hours=10.0,
        )
        fx.start_work_order(api, order["id"], s.crew["id"])

        completed = fx.complete_work_order(api, order["id"], s.crew["id"], 5200, 12.0)

        assert completed["execution_status"] == "COMPLETED"
        assert completed["payroll_status"] == "PENDING"
        assert completed["actual_vines"] == 5200
        assert completed["actual_hours"] == 12.0
        assert_money(completed["actual_labor_cost"], 4343.30, "actual_labor_cost")
        assert_money(completed["estimated_labor_cost"], 5011.50,
                     "estimated_labor_cost")
        assert_instant(completed["completed_at"], "2026-08-01T00:00:00Z",
                       "completed_at")
        assert_version(completed, 3, "work order")

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 4343.30, 10344.20,
                           "WITHIN_BUDGET")

    def test_starting_a_cancelled_order_is_refused(self, api):
        """Starting requires that the order actually be `SCHEDULED`, otherwise `ERR_WORK_ORDER_NOT_SCHEDULED`, and that the crew be `ACTIVE`.

        Design: Corner/state_machines/work_order_start_from_cancelled_rejected
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"],
            planned_vines=6000, planned_hours=10.0,
        )
        fx.cancel_work_order(api, order["id"], "WEATHER")

        validate_error(
            api.start_work_order(order["id"],
                                 make_crew_supervisor_headers(s.crew["id"])),
            ApiErrorId.ERR_WORK_ORDER_NOT_SCHEDULED,
        )

        order = fx.read_work_order(api, order["id"])
        assert order["execution_status"] == "CANCELLED"
        assert order["cancel_reason"] == "WEATHER"
        assert order["started_at"] is None
        assert order["payroll_status"] == "NOT_PAYABLE"
        assert_version(order, 2, "work order")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 0.00,
                     "committed_cost")

    def test_cancelling_a_completed_order_is_refused(self, api):
        """It requires a `cancel_reason` and is refused with `ERR_WORK_ORDER_TERMINAL` on an order that is already `COMPLETED` or `CANCELLED`.

        Design: Corner/state_machines/work_order_cancel_from_completed_rejected
        """
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"],
            planned_vines=6000, planned_hours=10.0,
        )
        fx.start_work_order(api, order["id"], s.crew["id"])
        fx.complete_work_order(api, order["id"], s.crew["id"], 5200, 12.0)

        validate_error(
            api.cancel_work_order(order["id"],
                                  f.cancel_work_order_payload("CLIENT_REQUEST"),
                                  fx.VM),
            ApiErrorId.ERR_WORK_ORDER_TERMINAL,
        )

        order = fx.read_work_order(api, order["id"])
        assert order["execution_status"] == "COMPLETED"
        assert_money(order["actual_labor_cost"], 4343.30, "actual_labor_cost")
        assert order["cancel_reason"] is None
        assert order["payroll_status"] == "PENDING"
        assert_version(order, 3, "work order")


class TestPayrollAxis:
    """PRD §3.4 — the payroll dimension is moved only by a `Controller`."""

    def _completed_order(self, api, planned_vines=6000, planned_hours=10.0,
                         actual_vines=5200, actual_hours=12.0):
        s = fx.setup_operational_block(api)
        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"],
            planned_vines=planned_vines, planned_hours=planned_hours,
        )
        fx.start_work_order(api, order["id"], s.crew["id"])
        order = fx.complete_work_order(api, order["id"], s.crew["id"],
                                       actual_vines, actual_hours)
        return s, order

    def test_paying_before_approving_is_refused_then_the_pair_succeeds(self, api):
        """Attempting `APPROVE` on an order whose `payroll_status` is not `PENDING`, or `PAY` on one whose `payroll_status` is not `APPROVED` — including the tempting shortcut of paying a `PENDING` order without approving it first — is refused with `ERR_PAYROLL_STATE_INVALID`.

        Design: Corner/state_machines/payroll_pay_before_approve_rejected_then_approve_pay_succeeds
        """
        s, order = self._completed_order(api)
        assert order["payroll_status"] == "PENDING"
        assert_version(order, 3, "work order")

        validate_error(
            api.advance_payroll(order["id"],
                                f.payroll_payload("PAY",
                                                  payroll_note="Skipping approval"),
                                fx.CTL),
            ApiErrorId.ERR_PAYROLL_STATE_INVALID,
        )
        refused = fx.read_work_order(api, order["id"])
        assert refused["payroll_status"] == "PENDING"
        assert_version(refused, 3, "work order")

        approved = fx.advance_payroll(api, order["id"], "APPROVE")
        assert approved["payroll_status"] == "APPROVED"
        assert_version(approved, 4, "work order")

        paid = fx.advance_payroll(api, order["id"], "PAY")
        assert paid["payroll_status"] == "PAID"
        assert paid["execution_status"] == "COMPLETED"
        assert_version(paid, 5, "work order")
        assert_money(paid["actual_labor_cost"], 4343.30, "actual_labor_cost")

    def test_the_payroll_axis_moves_while_execution_stays_terminal(self, api):
        """Neither dimension is derivable from the other, and each is driven by a distinct set of operations.

        Design: Difficulty/non_linear_state_machine/work_order_payroll_axis_advances_independently_of_execution_axis
        """
        s, order = self._completed_order(api)

        validate_error(
            api.advance_payroll(
                order["id"],
                f.payroll_payload("PAY", payroll_note="Premature pay attempt"),
                fx.CTL,
            ),
            ApiErrorId.ERR_PAYROLL_STATE_INVALID,
        )
        refused = fx.read_work_order(api, order["id"])
        assert refused["execution_status"] == "COMPLETED"
        assert refused["payroll_status"] == "PENDING"
        assert_version(refused, 3, "work order")
        assert_money(refused["actual_labor_cost"], 4343.30, "actual_labor_cost")

    def test_payroll_transitions_bump_the_version_without_touching_execution(self, api):
        """`APPROVE` moves `PENDING → APPROVED` and `PAY` moves `APPROVED → PAID`; each increments the order's `version` by 1 and neither touches `execution_status` in any way.

        Design: Difficulty/non_linear_state_machine/work_order_payroll_axis_advances_independently_of_execution_axis
        """
        s, order = self._completed_order(api)

        approved = fx.advance_payroll(api, order["id"], "APPROVE")
        assert approved["payroll_status"] == "APPROVED"
        assert approved["execution_status"] == "COMPLETED"
        assert_version(approved, 4, "work order")

        paid = fx.advance_payroll(api, order["id"], "PAY")
        assert paid["payroll_status"] == "PAID"
        assert paid["execution_status"] == "COMPLETED"
        assert_version(paid, 5, "work order")
        assert_money(paid["actual_labor_cost"], 4343.30, "actual_labor_cost")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 4343.30,
                     "committed_cost")

    def test_the_crew_supervisor_may_not_release_payroll(self, api):
        """The payroll axis is moved only by a `Controller`, and only through the payroll operation, which takes a `payroll_action` of `APPROVE` or `PAY` and an optional `payroll_note`.

        Design: Corner/rbac/crew_supervisor_cannot_release_payroll
        """
        s, order = self._completed_order(api, planned_vines=3000, planned_hours=8.0,
                                         actual_vines=3000, actual_hours=8.0)
        assert_money(order["actual_labor_cost"], 2505.75, "actual_labor_cost")
        assert order["payroll_status"] == "PENDING"
        version_before = order["version"]

        validate_error(
            api.advance_payroll(
                order["id"],
                f.payroll_payload("APPROVE", payroll_note="Supervisor attempt"),
                make_crew_supervisor_headers(s.crew["id"]),
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        )
        refused = fx.read_work_order(api, order["id"])
        assert refused["payroll_status"] == "PENDING"
        assert_version(refused, version_before, "work order")

        released = fx.advance_payroll(api, order["id"], "APPROVE")
        assert released["payroll_status"] == "APPROVED"
        assert_version(released, version_before + 1, "work order")
        assert released["execution_status"] == "COMPLETED"


class TestCrewOwnershipAndAvailability:
    """PRD §2.1 and §3.4 — the acting crew and the referenced crew must agree."""

    def test_a_foreign_crew_supervisor_may_not_start_the_order(self, api):
        """Concretely, starting or completing a work order, and dispatching a harvest load, require that `X-User-ID` equal the `crew_id` recorded on that work order or load; a mismatch is `ERR_CREW_OWNERSHIP_REQUIRED` (HTTP 403).

        Design: Corner/rbac/crew_supervisor_of_another_crew_cannot_start_work_order
        """
        s = fx.setup_operational_block(api)
        other_crew = fx.create_hourly_crew(api)
        order = fx.create_work_order(api, s.block["id"], s.plan["id"], s.crew["id"])

        validate_error(
            api.start_work_order(order["id"],
                                 make_crew_supervisor_headers(other_crew["id"])),
            ApiErrorId.ERR_CREW_OWNERSHIP_REQUIRED,
        )
        refused = fx.read_work_order(api, order["id"])
        assert refused["execution_status"] == "SCHEDULED"
        assert refused["started_at"] is None

        started = fx.start_work_order(api, order["id"], s.crew["id"])
        assert started["execution_status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], "2026-08-01T00:00:00Z", "started_at")
        assert fx.read_crew(api, other_crew["id"])["scheduled_work_order_count"] == 0

    def test_scheduling_against_an_inactive_crew_is_refused(self, api):
        """Only an `ACTIVE` crew may be scheduled or dispatched, and referencing an `INACTIVE` one is refused with `ERR_CREW_INACTIVE`.

        Design: Difficulty/cross_entity_state_dependency/work_order_create_refused_when_crew_inactive
        """
        s = fx.setup_operational_block(api)
        idle_crew = fx.create_hourly_crew(api, crew_status="INACTIVE")

        validate_error(
            api.create_work_order(
                f.work_order_payload(
                    s.block["id"], s.plan["id"], idle_crew["id"],
                    task_type="SUCKERING",
                    scheduled_start="2026-08-06T06:00:00Z",
                    scheduled_end="2026-08-06T14:00:00Z",
                    planned_vines=3000, planned_hours=8.0,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_CREW_INACTIVE,
        )

        idle_crew = fx.read_crew(api, idle_crew["id"])
        assert idle_crew["crew_status"] == "INACTIVE"
        assert idle_crew["scheduled_work_order_count"] == 0
        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")

    def test_the_identical_slot_is_accepted_against_an_active_crew(self, api):
        """A successful create freezes the order's cost estimate, sets `execution_status` to `SCHEDULED` and `payroll_status` to `NOT_PAYABLE`, leaves `actual_vines`, `actual_hours`, `actual_labor_cost`, `cancel_reason`, `started_at` and `completed_at` null, then recomputes the plan's `committed_cost`, `remaining_budget` and `budget_posture` and the crew's `scheduled_work_order_count`.

        Design: Difficulty/cross_entity_state_dependency/work_order_create_refused_when_crew_inactive
        """
        s = fx.setup_operational_block(api)
        idle_crew = fx.create_hourly_crew(api, crew_status="INACTIVE")
        validate_error(
            api.create_work_order(
                f.work_order_payload(
                    s.block["id"], s.plan["id"], idle_crew["id"],
                    task_type="SUCKERING",
                    scheduled_start="2026-08-06T06:00:00Z",
                    scheduled_end="2026-08-06T14:00:00Z",
                    planned_vines=3000, planned_hours=8.0,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_CREW_INACTIVE,
        )

        accepted = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="SUCKERING",
            scheduled_start="2026-08-06T06:00:00Z",
            scheduled_end="2026-08-06T14:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        assert accepted["execution_status"] == "SCHEDULED"
        assert accepted["payroll_status"] == "NOT_PAYABLE"
        assert accepted["actual_vines"] is None
        assert accepted["actual_hours"] is None
        assert accepted["actual_labor_cost"] is None
        assert accepted["started_at"] is None
        assert accepted["completed_at"] is None
        assert_money(accepted["estimated_labor_cost"], 2505.75,
                     "estimated_labor_cost")

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 2505.75, 12181.75,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 1


class TestImmediateConsistency:
    """PRD §2.10 — the recomputation is visible in the response that caused it."""

    def test_derived_figures_are_visible_without_a_second_read(self, api):
        """Almost every derived figure in this system is a state-filtered roll-up over child rows, and the recomputation is immediate: by the time a request returns, every aggregate it disturbed already reflects the change.

        Design: Corner/consistency model/derived_fields_are_visible_in_the_same_response_that_changes_them
        """
        s = fx.setup_operational_block(api)

        order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-03T06:00:00Z",
            scheduled_end="2026-08-03T18:00:00Z",
            planned_vines=5200, planned_hours=12.0,
        )
        assert_money(order["estimated_labor_cost"], 4343.30, "estimated_labor_cost")
        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 4343.30, 10344.20,
                           "WITHIN_BUDGET")

        fx.start_work_order(api, order["id"], s.crew["id"])
        completed = fx.complete_work_order(api, order["id"], s.crew["id"], 6000, 10.0)
        assert_money(completed["actual_labor_cost"], 5011.50, "actual_labor_cost")
        assert_money(completed["estimated_labor_cost"], 4343.30,
                     "estimated_labor_cost")
        assert completed["payroll_status"] == "PENDING"

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 5011.50, 9676.00,
                           "WITHIN_BUDGET")
