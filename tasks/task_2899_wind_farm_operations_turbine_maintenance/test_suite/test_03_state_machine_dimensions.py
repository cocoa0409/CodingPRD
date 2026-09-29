"""Turbine dual dimensions, the bounded revision cycle and the replacement fork/join."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_crane_costs,
    assert_farm_buckets,
    assert_stock_line,
    assert_turbine_dimensions,
)
from test_helpers.constants import (
    AVAILABILITY_DOWN_MAJOR,
    AVAILABILITY_FAULTED,
    AVAILABILITY_ONLINE,
    CURTAILMENT_CURTAILED,
    CURTAILMENT_REASON_NOISE,
    CURTAILMENT_UNCONSTRAINED,
    DISPOSITION_REMOTE_RESET,
    PATH_CRANE_LIFT,
    PATH_UPTOWER_REPAIR,
    REPLACEMENT_EXECUTED,
    RESET_OUTCOME_SUCCEEDED,
    STOCK_OUT_OF_STOCK,
    TRIAGE_CLEARED,
    WO_REVISION_REQUESTED,
    WO_SUBMITTED,
)
from test_helpers.fixtures import (
    active_curtailment,
    raise_fault,
    read_fault_event,
    read_farm,
    read_replacement,
    read_spare_part,
    read_turbine,
    read_work_order,
    remote_reset,
    setup_dual_dimension_turbine,
    setup_fork_join_replacements,
    setup_revision_cycle_order,
    triage,
    turbine_version,
)
from test_helpers.test_users import (
    make_crew_lead_headers,
    make_engineer_headers,
    make_planner_headers,
)


def test_fault_then_activation_each_write_only_their_own_dimension(api):
    """A fault moves availability alone; an activation then moves curtailment alone.

    The contract states: "Raising a fault moves the availability dimension and
    leaves the curtailment dimension exactly as it was; activating a curtailment
    order moves the curtailment dimension and leaves the availability dimension
    exactly as it was."  It also states of activation: "Activation increments the
    turbine's `active_curtailment_count` by 1 and sets its
    `effective_power_limit_kw` to the smallest `power_limit_kw` across all of that
    turbine's active orders — the most restrictive instruction wins."

    Design: Difficulty/non_linear_state_machine/turbine_availability_and_curtailment_dimensions_advance_independently
    """
    site = setup_dual_dimension_turbine(api)
    turbine_id = site["t1"]["id"]

    raise_fault(api, turbine_id, "FC-1000", "2026-06-01T00:00:00Z")

    faulted = read_turbine(api, turbine_id)
    assert_turbine_dimensions(faulted, AVAILABILITY_FAULTED, CURTAILMENT_UNCONSTRAINED)
    assert faulted["active_curtailment_count"] == 0
    assert faulted["effective_power_limit_kw"] == 4200
    assert faulted["active_fault_code"] == "FC-1000"

    active_curtailment(
        api,
        turbine_id,
        turbine_version(api, turbine_id),
        reason=CURTAILMENT_REASON_NOISE,
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-02T00:00:00Z",
        power_limit_kw=1000,
        deemed_kwh_per_hour=0,
    )

    curtailed = read_turbine(api, turbine_id)
    assert_turbine_dimensions(curtailed, AVAILABILITY_FAULTED, CURTAILMENT_CURTAILED)
    assert curtailed["active_curtailment_count"] == 1
    assert curtailed["effective_power_limit_kw"] == 1000
    assert curtailed["active_fault_code"] == "FC-1000"


def test_a_successful_remote_reset_returns_only_the_availability_dimension(api):
    """The reset clears the fault yet leaves the turbine capped and CURTAILED.

    The contract states: "A `reset_outcome` of `SUCCEEDED` moves the event
    `RESET_PENDING → CLEARED`, stamps `cleared_at` with the current logical clock,
    clears the turbine's `active_fault_code` to null, and drives the availability
    dimension `FAULTED → ONLINE`."  It adds: "Crucially, a successful reset
    accrues nothing yet — `downtime_hours`, `lost_energy_kwh` and every downstream
    availability effect are deferred to the closure step, so a cleared event that
    is never closed contributes nothing to availability or to lost energy."

    Design: Difficulty/non_linear_state_machine/turbine_availability_and_curtailment_dimensions_advance_independently
    """
    site = setup_dual_dimension_turbine(api)
    turbine_id = site["t1"]["id"]

    event = raise_fault(api, turbine_id, "FC-1000", "2026-06-01T00:00:00Z")
    active_curtailment(
        api,
        turbine_id,
        turbine_version(api, turbine_id),
        reason=CURTAILMENT_REASON_NOISE,
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-02T00:00:00Z",
        power_limit_kw=1000,
        deemed_kwh_per_hour=0,
    )
    triage(api, event["id"], DISPOSITION_REMOTE_RESET)
    remote_reset(api, event["id"], RESET_OUTCOME_SUCCEEDED)

    reset = read_turbine(api, turbine_id)
    assert_turbine_dimensions(reset, AVAILABILITY_ONLINE, CURTAILMENT_CURTAILED)
    assert reset["active_fault_code"] is None
    assert reset["effective_power_limit_kw"] == 1000
    assert reset["active_curtailment_count"] == 1
    assert reset["counted_downtime_hours_period"] == 0

    cleared = read_fault_event(api, event["id"])
    assert cleared["triage_state"] == TRIAGE_CLEARED
    assert cleared["cleared_at"] is not None
    assert cleared["downtime_hours"] is None
    assert cleared["lost_energy_kwh"] is None


def test_the_third_revision_lands_at_round_three_and_a_fourth_is_refused(api):
    """The revision back-edge is bounded by the counter, not by the state pair.

    The contract states: "In both cases the order's `revision_round` must be
    **strictly** below 3 before the request is accepted, and a fourth attempt on an
    order already at 3 is refused with `ERR_REVISION_LIMIT_EXCEEDED`."  It adds:
    "An accepted request increments `revision_round` by 1."

    Design: Difficulty/non_linear_state_machine/work_order_revision_cycle_terminates_at_three_rounds
    """
    site = setup_revision_cycle_order(api)
    order_id = site["order"]["id"]

    for round_number in (1, 2, 3):
        validate_success(api.submit_work_order(order_id, make_planner_headers()))
        sent_back = validate_success(
            api.request_revision(
                order_id, f"round {round_number}", make_engineer_headers()
            )
        )
        assert sent_back["state"] == WO_REVISION_REQUESTED
        assert sent_back["revision_round"] == round_number

    resubmitted = validate_success(api.submit_work_order(order_id, make_planner_headers()))
    assert resubmitted["state"] == WO_SUBMITTED
    assert resubmitted["revision_round"] == 3

    refused = api.request_revision(
        order_id, "round 4 must be refused", make_engineer_headers()
    )
    validate_error(refused, "ERR_REVISION_LIMIT_EXCEEDED", 422)

    after = read_work_order(api, order_id)
    assert after["state"] == WO_SUBMITTED
    assert after["revision_round"] == 3


def test_an_order_that_exhausted_its_revisions_is_still_resubmittable(api):
    """Only the revision edge is bounded; the submission edge of the cycle stays open.

    The contract states: "Re-submission is **never** gated by `revision_round`:
    only the revision back-edge is bounded, so an order that has exhausted its
    revisions is still re-submittable and still schedulable."

    Design: Difficulty/non_linear_state_machine/work_order_revision_cycle_terminates_at_three_rounds
    """
    site = setup_revision_cycle_order(api)
    order_id = site["order"]["id"]

    for round_number in (1, 2, 3):
        validate_success(api.submit_work_order(order_id, make_planner_headers()))
        validate_success(
            api.request_revision(
                order_id, f"round {round_number}", make_engineer_headers()
            )
        )

    exhausted = read_work_order(api, order_id)
    assert exhausted["state"] == WO_REVISION_REQUESTED
    assert exhausted["revision_round"] == 3

    reopened = validate_success(api.submit_work_order(order_id, make_planner_headers()))
    assert reopened["state"] == WO_SUBMITTED
    assert reopened["revision_round"] == 3
    assert reopened["submitted_by_user_id"] == make_planner_headers()["X-User-ID"]


def test_the_two_execution_branches_rejoin_at_executed_with_divergent_ledger_postings(api):
    """One EXECUTED state, two different ledger effects.

    The contract states: "On the **crane-lift branch**, the replacement's
    `allocated_crane_cost_cents` is added to the farm's `maintenance_spend_cents`
    and the same amount to its `opex_accrued_cents`."  Of the other branch it
    states: "On the **up-tower branch** no crane cost is posted at all and
    `allocated_crane_cost_cents` stays 0; instead the farm's
    `maintenance_spend_cents` and `opex_accrued_cents` each rise by the
    replacement's `uptower_labor_hours` multiplied by an up-tower labour rate of
    950,000 cents per hour, rounded half up to a whole cent."

    Design: Difficulty/non_linear_state_machine/component_replacement_fork_join_executes_with_divergent_ledger_postings
    """
    site = setup_fork_join_replacements(api)
    crew_headers = make_crew_lead_headers(site["crew"]["id"])

    lifted = validate_success(api.execute_replacement(site["ra"]["id"], crew_headers))
    assert lifted["state"] == REPLACEMENT_EXECUTED
    assert lifted["execution_path"] == PATH_CRANE_LIFT

    crane = validate_success(api.get_crane_mobilization(site["crane"]["id"], make_planner_headers()))
    assert_crane_costs(
        crane,
        lift_days=2,
        standby_days=0,
        billable_days=2,
        subtotal_cents=8480000,
        volume_credit_cents=254400,
        total_crane_cost_cents=8225600,
    )
    assert_cents(lifted["allocated_crane_cost_cents"], 8225600, "R_a allocated crane cost")
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=8225600,
        opex_accrued_cents=8225600,
    )

    uptower = validate_success(api.execute_replacement(site["rb"]["id"], crew_headers))
    assert uptower["state"] == REPLACEMENT_EXECUTED
    assert uptower["execution_path"] == PATH_UPTOWER_REPAIR
    assert_cents(uptower["allocated_crane_cost_cents"], 0, "R_b allocated crane cost")
    assert uptower["crane_mobilization_id"] is None

    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=36725600,
        opex_accrued_cents=36725600,
    )
    assert_stock_line(
        read_spare_part(api, site["sp_gb"]["id"]), 0, 0, 1, 1, status=STOCK_OUT_OF_STOCK
    )
    assert_stock_line(
        read_spare_part(api, site["sp_gen"]["id"]), 0, 0, 1, 1, status=STOCK_OUT_OF_STOCK
    )
    assert read_turbine(api, site["t1"]["id"])["availability_state"] == AVAILABILITY_DOWN_MAJOR


def test_planning_uptower_zeroes_the_lift_and_books_its_hours_on_the_parent_order(api):
    """The up-tower fork rewrites the replacement and lifts the parent order's hours.

    The contract states: "Taking it sets `execution_path` to `UPTOWER_REPAIR`,
    leaves `crane_mobilization_id` null, sets `estimated_lift_hours` to 0 and
    `allocated_crane_cost_cents` to 0, and adds the stored `uptower_labor_hours` to
    the parent work order's `estimated_hours`."

    Design: Difficulty/non_linear_state_machine/component_replacement_fork_join_executes_with_divergent_ledger_postings
    """
    site = setup_fork_join_replacements(api)

    uptower = read_replacement(api, site["rb"]["id"])
    assert uptower["execution_path"] == PATH_UPTOWER_REPAIR
    assert uptower["crane_mobilization_id"] is None
    assert uptower["estimated_lift_hours"] == 0
    assert_cents(uptower["allocated_crane_cost_cents"], 0, "R_b allocated crane cost")
    assert uptower["uptower_labor_hours"] == 30

    parent = read_work_order(api, site["order"]["id"])
    assert parent["estimated_hours"] == 40

    validate_success(
        api.execute_replacement(site["rb"]["id"], make_engineer_headers())
    )
    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=28500000,
        opex_accrued_cents=28500000,
    )
