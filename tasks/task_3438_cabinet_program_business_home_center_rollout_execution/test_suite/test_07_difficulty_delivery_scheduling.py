"""Promised-vs-scheduled delivery weeks and aggregate slot capacity (PRD §3.3, §3.4)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    PLANT_SCHEDULER_HEADERS,
    WEEK_CURRENT,
    WEEK_NEXT,
    WEEK_PLUS_2,
    family_spec,
    order_line,
)
from test_helpers import fixtures


def test_promise_and_capacity_aware_delivery_diverge(api):
    """The capacity-blind promise and the slot-constrained schedule answer the
    same question differently once the primary-window bucket fills.

    PRD §3.3: "At submit, the order's `promised_delivery_week` is the submit week advanced by the effective lead time: the largest `base_lead_weeks` among the order's families, plus 2 extra weeks when the account's `lead_time_class` is `EXTENDED`."
    PRD §3.4: "When the primary window offers no eligible slot, a slip window of up to 4 further weeks beyond the primary window's end is searched."
    PRD §3.4: "The capacity-aware answer to \"when will this arrive\" — which can slip past the sales promise when buckets are full — is the order's `scheduled_delivery_week`: its `scheduled_week` plus the largest `base_lead_weeks` among the order's families."
    Design: Difficulty/dual_variant_calc/promised_week_table_vs_capacity_aware_scheduled_week_diverge
    """
    world = fixtures.setup_active_program(api)
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=10)
    fixtures.create_production_slot(api, week=WEEK_PLUS_2, capacity_units=10)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=10)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=5)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    fixtures.acknowledge_order(api, o2["id"])

    s1 = fixtures.schedule_order(api, o1["id"])
    s2 = fixtures.schedule_order(api, o2["id"])

    # Submit week W36 + lead 3 -> promised W39 for both.
    # o1 fills the W37 bucket: W37 + 3 = W40, inside the promise.
    assert s1["promised_delivery_week"] == "2026-W39"
    assert s1["scheduled_week"] == "2026-W37"
    assert s1["scheduled_delivery_week"] == "2026-W40"
    # o2 (10 + 5 > 10) slips to the W38 bucket: W38 + 3 = W41, past the promise.
    assert s2["promised_delivery_week"] == "2026-W39"
    assert s2["scheduled_week"] == "2026-W38"
    assert s2["scheduled_delivery_week"] == "2026-W41"
    assert s2["promised_delivery_week"] != s2["scheduled_delivery_week"]


def test_capacity_matches_promise_when_earliest_slot_is_current_week(api):
    """With a slot open in the submit week itself, both variants agree.

    PRD §3.3: "At submit, the order's `promised_delivery_week` is the submit week advanced by the effective lead time: the largest `base_lead_weeks` among the order's families, plus 2 extra weeks when the account's `lead_time_class` is `EXTENDED`."
    PRD §3.4: "Among eligible slots the picker ranks by week ascending, then `plant_code` ascending, then `created_at` ascending — never by `id` — and takes the first."
    PRD §3.4: "A slot starts `OPEN` with `committed_units` at zero, locks automatically when commitments reach exactly its capacity, and re-opens automatically whenever a release drops commitments back below capacity."
    Design: Difficulty/dual_variant_calc/promised_week_table_vs_capacity_aware_scheduled_week_diverge
    """
    world = fixtures.setup_active_program(api)
    # A slot opened for the current week is lawful (not before the current one).
    fixtures.create_production_slot(api, week=WEEK_CURRENT, capacity_units=10)
    order = fixtures.place_order(api, world["account"], world["program"])
    fixtures.acknowledge_order(api, order["id"])

    scheduled = fixtures.schedule_order(api, order["id"])
    assert scheduled["scheduled_week"] == "2026-W36"
    assert scheduled["scheduled_delivery_week"] == "2026-W39"
    assert scheduled["promised_delivery_week"] == "2026-W39"
    assert scheduled["scheduled_delivery_week"] == scheduled["promised_delivery_week"]


def test_slot_fills_inclusively_then_next_unit_refused(api):
    """Commitments may reach capacity exactly (auto-lock); one unit beyond has
    no eligible slot anywhere in the primary or slip windows.

    PRD §3.4: "A slot starts `OPEN` with `committed_units` at zero, locks automatically when commitments reach exactly its capacity, and re-opens automatically whenever a release drops commitments back below capacity."
    PRD §3.4: "A slot is eligible for a family when it produces that family, its `week` is not before the current week, it is `OPEN`, its week falls inside the window from the current week through the `requested_delivery_week` set back by that family's `base_lead_weeks`, and its `committed_units` plus the demand does not exceed `capacity_units` — overbooking is never allowed in this variant."
    PRD §3.4: "Every family's pick must succeed: if any family finds no slot, the entire transition fails with `ERR_NO_CAPACITY` and nothing is committed."
    Design: Difficulty/resource_temporal_overlap/slot_weekly_aggregate_capacity_inclusive_fill_then_exhaustion
    """
    world = fixtures.setup_active_program(
        api,
        families=[family_spec(standard_price_cents=1000, base_lead_weeks=3, complexity_units_per_cabinet=2)],
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=50)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=15)]
    )  # 30 units
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=10)],
    )  # 20 units
    o3 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="3 Job Ln", lines=[order_line(quantity=1)],
    )  # 2 units
    for order in (o1, o2, o3):
        fixtures.acknowledge_order(api, order["id"])

    fixtures.schedule_order(api, o1["id"])
    slots, _ = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert slots[0]["committed_units"] == 30
    assert slots[0]["status"] == "OPEN"

    fixtures.schedule_order(api, o2["id"])
    slots, _ = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert slots[0]["committed_units"] == 50
    assert slots[0]["status"] == "LOCKED"

    blocked = api.transition_order(
        o3["id"], {"to_status": "SCHEDULED"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_NO_CAPACITY")
    after = fixtures.get_order(api, o3["id"])
    assert after["status"] == "ACKNOWLEDGED"


def test_multi_family_schedule_commits_all_or_nothing(api):
    """A family without any slot sinks the whole transition; the family that
    could have been scheduled commits nothing.

    PRD §3.4: "Every family's pick must succeed: if any family finds no slot, the entire transition fails with `ERR_NO_CAPACITY` and nothing is committed."
    PRD §3.4: "Scheduling runs the strict variant of capacity selection once per distinct `family_code` in the order."
    Design: Difficulty/resource_temporal_overlap/slot_weekly_aggregate_capacity_inclusive_fill_then_exhaustion
    """
    world = fixtures.setup_active_program(
        api,
        families=[
            family_spec("F1", standard_price_cents=1000, base_lead_weeks=3, complexity_units_per_cabinet=1),
            family_spec("F2", standard_price_cents=2000, base_lead_weeks=3, complexity_units_per_cabinet=1),
        ],
    )
    fixtures.create_production_slot(api, family_code="F1", week=WEEK_NEXT, capacity_units=100)
    order = fixtures.place_order(
        api, world["account"], world["program"],
        lines=[order_line("F1", quantity=2), order_line("F2", quantity=1)],
    )
    fixtures.acknowledge_order(api, order["id"])

    blocked = api.transition_order(
        order["id"], {"to_status": "SCHEDULED"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_NO_CAPACITY")

    after = fixtures.get_order(api, order["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["scheduled_week"] is None
    slots, _ = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert slots[0]["committed_units"] == 0
    assert slots[0]["status"] == "OPEN"
