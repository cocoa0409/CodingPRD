"""Requests that breach several rungs at once and must report the earliest one."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import assert_cents, assert_crane_costs, assert_version_unchanged
from test_helpers.constants import (
    CRANE_MOBILIZED,
    CRANE_REQUESTED,
    REPLACEMENT_CRANE_RESERVED,
    SETTLEMENT_DRAFT,
    WINDOW_CONFIRMED,
    WO_SCHEDULED,
)
from test_helpers.factories import landowner_settlement_payload, schedule_payload
from test_helpers.fixtures import (
    confirmed_window,
    create_crew,
    read_crane,
    read_farm,
    read_replacement,
    read_window,
    setup_reserve_crane_ladder,
    setup_schedule_ladder,
    setup_settlement_ladder,
)
from test_helpers.test_users import make_commercial_headers, make_planner_headers


def test_scheduling_reports_the_unconfirmed_window_ahead_of_both_safety_and_capacity(api):
    """Rung 13 wins over rungs 14 and 18 on a request that breaches all three.

    The contract states: "When a single request violates more than one rule, the
    response must carry the error belonging to the earliest rung of the ladder
    below."  Rung 13 reads: "**Weather-window confirmation**, yielding
    `ERR_WEATHER_WINDOW_NOT_CONFIRMED`, on work-order scheduling only."  Rung 14
    reads: "**Safety gates.** In order: the crane workable-day gate
    (`ERR_LIFT_WIND_LIMIT_EXCEEDED`, on crane reservation), the crew wind limit
    (`ERR_CREW_WIND_LIMIT_EXCEEDED`, on scheduling), the crew certification
    requirement (`ERR_CREW_CERTIFICATION_MISSING`, on scheduling), and the
    force-stop interlock (`ERR_TURBINE_FORCE_STOPPED`, which applies to two
    operations: attempting a remote reset and starting a work order)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_peels_a_three_rung_ladder_state_44_then_safety_52_then_fiscal_72
    """
    site = setup_schedule_ladder(api)
    body = schedule_payload(
        site["crew_a"]["id"],
        site["window_a"]["id"],
        "2026-06-20T06:00:00Z",
        "2026-06-20T14:00:00Z",
    )

    unconfirmed = api.schedule_work_order(site["order"]["id"], body, make_planner_headers())
    validate_error(unconfirmed, "ERR_WEATHER_WINDOW_NOT_CONFIRMED", 409)

    validate_success(api.confirm_weather_window(site["window_a"]["id"], make_planner_headers()))

    windy = api.schedule_work_order(site["order"]["id"], body, make_planner_headers())
    validate_error(windy, "ERR_CREW_WIND_LIMIT_EXCEEDED", 422)


def test_capacity_surfaces_last_and_no_rejected_rung_touched_a_window(api):
    """Rung 18 is the only surviving breach once the window and the wind are fixed.

    The contract states: "**Quota, capacity and fiscal gates.** In order: reset
    eligibility (`ERR_RESET_NOT_PERMITTED`, which applies both to a triage
    disposition of `REMOTE_RESET` and to a remote-reset attempt), reset quota
    (`ERR_RESET_QUOTA_EXHAUSTED`, on a remote-reset attempt), crew daily capacity
    (`ERR_CREW_CAPACITY_EXCEEDED`, on scheduling), spare-part availability
    (`ERR_SPARE_PART_UNAVAILABLE`, on replacement planning), landowner budget
    headroom (`ERR_MINIMUM_PAYMENT_ABOVE_CAP`, on settlement drafting),
    service-due eligibility (`ERR_SERVICE_NOT_DUE`, on raising a scheduled-service
    work order), the revision bound (`ERR_REVISION_LIMIT_EXCEEDED`, on requesting a
    revision), and finally the non-empty availability denominator
    (`ERR_NO_TURBINES_IN_SERVICE`, on settling a service agreement)."  It also
    states: "A rejected request writes nothing at all — no counter moves, no
    `version` advances, no partial cascade survives."

    Design: Difficulty/priority_pair_validation_conflict/schedule_peels_a_three_rung_ladder_state_44_then_safety_52_then_fiscal_72
    """
    site = setup_schedule_ladder(api)
    validate_success(api.confirm_weather_window(site["window_a"]["id"], make_planner_headers()))
    calm_window = confirmed_window(
        api,
        site["farm"]["id"],
        start_utc="2026-06-22T00:00:00Z",
        end_utc="2026-06-23T00:00:00Z",
        forecast_wind_speed_ms=8,
        forecast_gust_ms=12,
        icing_risk=False,
    )

    over_capacity = api.schedule_work_order(
        site["order"]["id"],
        schedule_payload(
            site["crew_a"]["id"],
            calm_window["id"],
            "2026-06-22T06:00:00Z",
            "2026-06-22T14:00:00Z",
        ),
        make_planner_headers(),
    )
    validate_error(over_capacity, "ERR_CREW_CAPACITY_EXCEEDED", 422)

    crew_b = create_crew(
        api,
        site["farm"]["id"],
        crew_code="CRW-B",
        technician_count=4,
        certifications=["GWO_BASIC"],
        max_work_wind_speed_ms=20,
        daily_hours_capacity=12,
        hourly_rate_cents=21000,
    )
    scheduled = validate_success(
        api.schedule_work_order(
            site["order"]["id"],
            schedule_payload(
                crew_b["id"],
                calm_window["id"],
                "2026-06-22T06:00:00Z",
                "2026-06-22T14:00:00Z",
            ),
            make_planner_headers(),
        )
    )
    assert scheduled["state"] == WO_SCHEDULED
    assert scheduled["crew_id"] == crew_b["id"]
    assert scheduled["weather_window_id"] == calm_window["id"]

    used = read_window(api, calm_window["id"])
    assert used["state"] == WINDOW_CONFIRMED
    assert used["active_work_order_count"] == 1
    spared = read_window(api, site["window_a"]["id"])
    assert spared["state"] == WINDOW_CONFIRMED
    assert spared["active_work_order_count"] == 0


def test_a_foreign_crane_with_too_few_workable_dates_reports_the_safety_gate(api):
    """The workable-day gate on rung 14 pre-empts the farm mismatch on rung 17.

    The contract states: "Because the crane workable-day gate sits on rung 14 and
    the crane-to-farm match sits on rung 17, a crane reservation that both names a
    crane on the wrong farm and fails the workable-day gate is reported as
    `ERR_LIFT_WIND_LIMIT_EXCEEDED`, not as `ERR_CRANE_FARM_MISMATCH`."  It also
    states: "A rejected request writes nothing at all — no counter moves, no
    `version` advances, no partial cascade survives."

    Design: Difficulty/priority_pair_validation_conflict/reserve_crane_prefers_safety_50_over_referential_67_on_a_foreign_farm_crane
    """
    site = setup_reserve_crane_ladder(api)

    both_broken = api.reserve_crane(
        site["replacement"]["id"], site["c_short"]["id"], make_planner_headers()
    )
    validate_error(both_broken, "ERR_LIFT_WIND_LIMIT_EXCEEDED", 422)

    untouched = read_crane(api, site["c_short"]["id"])
    assert untouched["state"] == CRANE_REQUESTED
    assert untouched["reserved_replacement_count"] == 0
    assert_version_unchanged(site["c_short"], untouched)


def test_the_farm_mismatch_surfaces_once_the_slot_is_long_enough(api):
    """Rung 17 is next in line, and the home crane finally reserves and reprices.

    The contract states: "**Referential consistency.** In order: crew-to-farm match
    (`ERR_CREW_FARM_MISMATCH`, on scheduling), crane-to-farm match
    (`ERR_CRANE_FARM_MISMATCH`, on crane reservation), spare-part component-type
    match (`ERR_SPARE_PART_TYPE_MISMATCH`, on replacement planning), and up-tower
    eligibility (`ERR_UPTOWER_NOT_PERMITTED`, on taking the up-tower branch)."  Of
    a successful reservation it states: "A successful reservation sets
    `execution_path` to `CRANE_LIFT`, stores the `crane_mobilization_id`, moves the
    mobilization `REQUESTED → MOBILIZED` if it was still `REQUESTED`, increments its
    `reserved_replacement_count` by 1, and reprices the whole mobilization."

    Design: Difficulty/priority_pair_validation_conflict/reserve_crane_prefers_safety_50_over_referential_67_on_a_foreign_farm_crane
    """
    site = setup_reserve_crane_ladder(api)

    foreign = api.reserve_crane(
        site["replacement"]["id"], site["c_long"]["id"], make_planner_headers()
    )
    validate_error(foreign, "ERR_CRANE_FARM_MISMATCH", 422)
    assert read_crane(api, site["c_long"]["id"])["state"] == CRANE_REQUESTED
    assert read_crane(api, site["c_long"]["id"])["reserved_replacement_count"] == 0

    reserved = validate_success(
        api.reserve_crane(
            site["replacement"]["id"], site["c_home"]["id"], make_planner_headers()
        )
    )
    assert reserved["state"] == REPLACEMENT_CRANE_RESERVED
    assert reserved["crane_mobilization_id"] == site["c_home"]["id"]

    home = read_crane(api, site["c_home"]["id"])
    assert home["state"] == CRANE_MOBILIZED
    assert home["reserved_replacement_count"] == 1
    assert_crane_costs(
        home,
        lift_days=2,
        standby_days=0,
        billable_days=2,
        subtotal_cents=8480000,
        volume_credit_cents=254400,
        total_crane_cost_cents=8225600,
    )
    assert_cents(
        read_replacement(api, site["replacement"]["id"])["allocated_crane_cost_cents"],
        8225600,
        "replacement.allocated_crane_cost_cents",
    )


def test_the_settlement_freeze_is_reported_ahead_of_the_period_overlap(api):
    """Rung 12 wins while an agreement is settling; rung 15 is next once it finalizes.

    The contract states: "When a single request violates more than one rule, the
    response must carry the error belonging to the earliest rung of the ladder
    below."  Of settlement drafting it states: "Three further gates apply: the
    settlement's half-open period must not overlap any non-void settlement for the
    same farm and the same `parcel_code`, failing which it is refused with
    `ERR_SETTLEMENT_PERIOD_OVERLAP`; no agreement on the farm may be in
    `IN_SETTLEMENT`, failing which it is refused with `ERR_AGREEMENT_IN_SETTLEMENT`;
    and `minimum_payment_cents` must not exceed the farm's remaining headroom, which
    is `landowner_budget_cap_cents` minus the farm's current
    `landowner_payable_cents`, failing which it is refused with
    `ERR_MINIMUM_PAYMENT_ABOVE_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/settlement_creation_peels_state_43_then_temporal_60_then_fiscal_74
    """
    site = setup_settlement_ladder(api)
    overlapping = landowner_settlement_payload(
        site["farm_version"],
        parcel_code="P-1",
        royalty_basis="METERED_ONLY",
        period_start_utc="2026-06-15T00:00:00Z",
        period_end_utc="2026-07-15T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=99900000,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )

    frozen = api.create_landowner_settlement(
        site["farm"]["id"], overlapping, make_commercial_headers()
    )
    validate_error(frozen, "ERR_AGREEMENT_IN_SETTLEMENT", 409)

    validate_success(api.finalize_agreement(site["agreement"]["id"], make_commercial_headers()))

    clashing = api.create_landowner_settlement(
        site["farm"]["id"], overlapping, make_commercial_headers()
    )
    validate_error(clashing, "ERR_SETTLEMENT_PERIOD_OVERLAP", 409)


def test_the_headroom_is_measured_net_of_what_is_already_posted(api):
    """Rung 18 measures the cap less `landowner_payable_cents`, and adjacency is no overlap.

    The contract states: "Three further gates apply: the settlement's half-open
    period must not overlap any non-void settlement for the same farm and the same
    `parcel_code`, failing which it is refused with `ERR_SETTLEMENT_PERIOD_OVERLAP`;
    no agreement on the farm may be in `IN_SETTLEMENT`, failing which it is refused
    with `ERR_AGREEMENT_IN_SETTLEMENT`; and `minimum_payment_cents` must not exceed
    the farm's remaining headroom, which is `landowner_budget_cap_cents` minus the
    farm's current `landowner_payable_cents`, failing which it is refused with
    `ERR_MINIMUM_PAYMENT_ABOVE_CAP`."  It also states: "A rejected request writes
    nothing at all — no counter moves, no `version` advances, no partial cascade
    survives."

    Design: Difficulty/priority_pair_validation_conflict/settlement_creation_peels_state_43_then_temporal_60_then_fiscal_74
    """
    site = setup_settlement_ladder(api)
    validate_success(api.finalize_agreement(site["agreement"]["id"], make_commercial_headers()))

    before = read_farm(api, site["farm"]["id"])
    assert_cents(before["landowner_payable_cents"], 240000, "farm.landowner_payable_cents")
    assert_cents(before["landowner_budget_cap_cents"], 100000000, "farm.landowner_budget_cap_cents")

    over_cap = api.create_landowner_settlement(
        site["farm"]["id"],
        landowner_settlement_payload(
            before["version"],
            parcel_code="P-1",
            royalty_basis="METERED_ONLY",
            period_start_utc="2026-07-01T00:00:00Z",
            period_end_utc="2026-08-01T00:00:00Z",
            royalty_pct=4.0,
            minimum_payment_cents=99900000,
            energy_price_cents_per_kwh=6,
            road_damage_assessment_cents=0,
        ),
        make_commercial_headers(),
    )
    validate_error(over_cap, "ERR_MINIMUM_PAYMENT_ABOVE_CAP", 422)
    assert_version_unchanged(before, read_farm(api, site["farm"]["id"]))

    drafted = validate_success(
        api.create_landowner_settlement(
            site["farm"]["id"],
            landowner_settlement_payload(
                before["version"],
                parcel_code="P-1",
                royalty_basis="METERED_ONLY",
                period_start_utc="2026-07-01T00:00:00Z",
                period_end_utc="2026-08-01T00:00:00Z",
                royalty_pct=4.0,
                minimum_payment_cents=1000,
                energy_price_cents_per_kwh=6,
                road_damage_assessment_cents=0,
            ),
            make_commercial_headers(),
        ),
        201,
    )
    assert drafted["state"] == SETTLEMENT_DRAFT
    assert_cents(drafted["payment_cents"], 240000, "settlement.payment_cents")
    assert read_farm(api, site["farm"]["id"])["version"] == before["version"] + 1
