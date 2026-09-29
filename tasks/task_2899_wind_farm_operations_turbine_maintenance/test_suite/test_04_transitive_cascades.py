"""Multi-hop cascades that land on rows the triggering request never names."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_crane_costs,
    assert_farm_buckets,
    assert_four_dp,
    assert_instant_equals,
    assert_stock_line,
    assert_two_dp,
)
from test_helpers.constants import (
    AVAILABILITY_ONLINE,
    CRANE_CANCELLED,
    CRANE_MOBILIZED,
    CREW_AVAILABLE,
    CURTAILMENT_UNCONSTRAINED,
    REPLACEMENT_CANCELLED,
    STOCK_BELOW_REORDER_POINT,
    STOCK_IN_STOCK,
    TRIAGE_CLOSED,
    WINDOW_CONFIRMED,
    WINDOW_EXPIRED,
    WO_COMPLETED,
    WO_REVISION_REQUESTED,
)
from test_helpers.fixtures import (
    read_agreement,
    read_crane,
    read_crew,
    read_farm,
    read_fault_event,
    read_replacement,
    read_spare_part,
    read_turbine,
    read_window,
    read_work_order,
    setup_replacement_cancellation_cascade,
    setup_six_hop_completion_cascade,
)
from test_helpers.test_users import make_engineer_headers, make_planner_headers


def test_completing_a_fault_dispatch_order_closes_the_event_and_admits_its_downtime(api):
    """The first four hops of a completion, ending on the turbine's period counters.

    The contract states: "The order moves `IN_PROGRESS → COMPLETED` and its
    `labor_cost_cents` is set to `actual_hours` multiplied by the assigned crew's
    `hourly_rate_cents`, rounded half up to a whole cent."  It continues: "On a
    `FAULT_DISPATCH` order the linked fault event is carried from `DISPATCHED`
    through `CLEARED` to `CLOSED` inside this same request, with `cleared_at`
    stamped from the logical clock and `downtime_hours` and `lost_energy_kwh`
    computed exactly as §3.2 describes."  And: "That closure admits the downtime:
    the turbine's `counted_downtime_hours_period` rises by `downtime_hours` when
    the event's `contractual_exclusion_pinned` is false and by nothing when it is
    true, while `cumulative_lost_energy_kwh` rises by `lost_energy_kwh`
    regardless."

    Design: Difficulty/transitive_cascade/work_order_completion_cascades_six_hops_into_an_unnamed_work_orders_priority_score
    """
    site = setup_six_hop_completion_cascade(api)

    completed = validate_success(
        api.complete_work_order(site["wo1"]["id"], 6, make_engineer_headers())
    )
    assert completed["state"] == WO_COMPLETED
    assert_cents(completed["labor_cost_cents"], 108000, "wo1.labor_cost_cents")

    turbine = read_turbine(api, site["t1"]["id"])
    assert turbine["availability_state"] == AVAILABILITY_ONLINE
    assert turbine["curtailment_state"] == CURTAILMENT_UNCONSTRAINED
    assert turbine["counted_downtime_hours_period"] == 24
    assert_two_dp(turbine["cumulative_lost_energy_kwh"], 48000.00, "t1.cumulative_lost_energy_kwh")

    event = read_fault_event(api, site["fault_event"]["id"])
    assert event["triage_state"] == TRIAGE_CLOSED
    assert_instant_equals(event["cleared_at"], "2026-07-03T00:00:00Z", "event.cleared_at")
    assert_two_dp(event["downtime_hours"], 24.00, "event.downtime_hours")
    assert_two_dp(event["lost_energy_kwh"], 48000.00, "event.lost_energy_kwh")

    untouched = read_turbine(api, site["t2"]["id"])
    assert untouched["counted_downtime_hours_period"] == 0

    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=108000,
        opex_accrued_cents=108000,
    )
    assert read_crew(api, site["crew"]["id"])["status"] == CREW_AVAILABLE
    assert read_window(api, site["window"]["id"])["state"] == WINDOW_EXPIRED


def test_the_completion_reprices_a_submitted_order_on_a_different_turbine(api):
    """Hops five and six: the projection flips at risk and re-scores an unnamed order.

    The contract states: "`at_risk_flag` is true exactly when
    `projected_shortfall_pct` is greater than 0, and while it is true it adds the
    liquidated-damages term to the priority score of every open work order on the
    farm, as §3.3 describes."  It also states: "The projection writes
    `projected_shortfall_pct` and `at_risk_flag` and **never** writes
    `assessed_lda_cents`."  And of the score: "The **liquidated-damages term** is
    1.0 when at least one service agreement exists on the turbine's farm that is in
    `ACTIVE` with its `at_risk_flag` true, and 0.0 otherwise — agreements in
    `IN_SETTLEMENT` or `SETTLED` never contribute this term."

    Design: Difficulty/transitive_cascade/work_order_completion_cascades_six_hops_into_an_unnamed_work_orders_priority_score
    """
    site = setup_six_hop_completion_cascade(api)

    before = read_work_order(api, site["wo2"]["id"])
    assert_two_dp(before["priority_score"], 70.00, "wo2.priority_score before")

    validate_success(api.complete_work_order(site["wo1"]["id"], 6, make_engineer_headers()))

    agreement = read_agreement(api, site["agreement"]["id"])
    assert_four_dp(agreement["projected_shortfall_pct"], 0.6667, "agreement.projected_shortfall_pct")
    assert agreement["at_risk_flag"] is True
    assert_cents(agreement["assessed_lda_cents"], 0, "agreement.assessed_lda_cents")

    after = read_work_order(api, site["wo2"]["id"])
    assert_two_dp(after["priority_score"], 90.67, "wo2.priority_score after")
    assert after["turbine_id"] == site["t2"]["id"]


def test_cancelling_one_reservation_reprices_the_survivor_and_unwinds_the_schedule(api):
    """Four hops from one cancel, including a rewrite of the row nobody named.

    The contract states: "One unit returns from the part's `quantity_reserved` to
    its `quantity_on_hand`, leaving `total_units_accounted` unchanged, and the
    part's `status` and `procurement_flag` are re-derived from the restored
    balance."  Of the mobilization it states: "When survivors remain, the
    mobilization is simply repriced and the waterfall re-run over them."  And of
    the parent: "Whenever the parent work order is in `SCHEDULED`, it returns
    `SCHEDULED → REVISION_REQUESTED` with `revision_round` incremented by 1,
    `crew_id` and `weather_window_id` set to null, its window's
    `active_work_order_count` decremented by 1 with the window's own `state`
    unchanged, and its crew returned to `AVAILABLE` when it holds no other
    `SCHEDULED` or `IN_PROGRESS` order."

    Design: Difficulty/transitive_cascade/replacement_cancellation_cascades_four_hops_and_reprices_the_surviving_reservation
    """
    site = setup_replacement_cancellation_cascade(api)

    cancelled = validate_success(
        api.cancel_replacement(
            site["r2"]["id"], "second gearbox deferred to next campaign", make_planner_headers()
        )
    )
    assert cancelled["state"] == REPLACEMENT_CANCELLED
    assert_cents(cancelled["allocated_crane_cost_cents"], 0, "r2.allocated_crane_cost_cents")
    assert cancelled["execution_path"] is None

    assert_stock_line(
        read_spare_part(api, site["part"]["id"]),
        1,
        1,
        0,
        2,
        status=STOCK_BELOW_REORDER_POINT,
        procurement_flag=True,
    )

    crane = read_crane(api, site["crane"]["id"])
    assert crane["state"] == CRANE_MOBILIZED
    assert crane["reserved_replacement_count"] == 1
    assert_crane_costs(
        crane,
        lift_days=2,
        standby_days=2,
        billable_days=4,
        subtotal_cents=12960000,
        volume_credit_cents=388800,
        total_crane_cost_cents=12571200,
    )
    survivor = read_replacement(api, site["r1"]["id"])
    assert_cents(survivor["allocated_crane_cost_cents"], 12571200, "r1.allocated_crane_cost_cents")

    parent = read_work_order(api, site["order"]["id"])
    assert parent["state"] == WO_REVISION_REQUESTED
    assert parent["revision_round"] == 1
    assert parent["crew_id"] is None
    assert parent["weather_window_id"] is None

    window = read_window(api, site["window"]["id"])
    assert window["state"] == WINDOW_CONFIRMED
    assert window["active_work_order_count"] == 0
    assert read_crew(api, site["crew"]["id"])["status"] == CREW_AVAILABLE

    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=0,
        opex_accrued_cents=0,
    )


def test_cancelling_the_last_reservation_cancels_the_crane_at_a_forty_percent_fee(api):
    """The mobilization only collapses once its reservation count reaches zero.

    The contract states: "The mobilization's `reserved_replacement_count` is
    decremented. When it reaches 0 the mobilization moves `MOBILIZED → CANCELLED`,
    its `billable_days` is set to 0, and its `total_crane_cost_cents` is rewritten
    to 40 percent of `mobilization_fee_cents`, rounded half up to a whole cent — a
    cancellation fee that is itself charged to the farm's `maintenance_spend_cents`
    and `opex_accrued_cents`."  Of the parent hop it states: "When the parent is in
    any other state this hop does nothing."

    Design: Difficulty/transitive_cascade/replacement_cancellation_cascades_four_hops_and_reprices_the_surviving_reservation
    """
    site = setup_replacement_cancellation_cascade(api)

    validate_success(
        api.cancel_replacement(
            site["r2"]["id"], "second gearbox deferred to next campaign", make_planner_headers()
        )
    )
    validate_success(
        api.cancel_replacement(site["r1"]["id"], "campaign abandoned", make_planner_headers())
    )

    crane = read_crane(api, site["crane"]["id"])
    assert crane["state"] == CRANE_CANCELLED
    assert crane["reserved_replacement_count"] == 0
    assert crane["billable_days"] == 0
    assert_cents(crane["total_crane_cost_cents"], 1600000, "crane.total_crane_cost_cents")

    assert_farm_buckets(
        read_farm(api, site["farm"]["id"]),
        maintenance_spend_cents=1600000,
        opex_accrued_cents=1600000,
    )
    assert_stock_line(
        read_spare_part(api, site["part"]["id"]), 2, 0, 0, 2, status=STOCK_IN_STOCK
    )

    parent = read_work_order(api, site["order"]["id"])
    assert parent["state"] == WO_REVISION_REQUESTED
    assert parent["revision_round"] == 1
