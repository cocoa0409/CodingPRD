"""Calculation rules: channel multipliers, lead-time table, slot selection, expedite overbook (PRD §3.3-§3.5)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    PLANT_SCHEDULER_HEADERS,
    WEEK_NEXT,
    WEEK_PLUS_2,
    WEEK_PLUS_5,
    family_spec,
    order_line,
)
from test_helpers import fixtures


def test_pricing_national_channel_multiplier_applied(api):
    """A NATIONAL account prices at the 0.90 multiplier.

    PRD §3.3: "For each line, the family's `standard_price_cents` is multiplied by the account's channel multiplier — 1.00 for `STANDARD`, 0.95 for `VOLUME`, 0.90 for `NATIONAL` — and the result is rounded half-up to whole cents, giving the line's channel unit price."
    Design: Corner/calculations/pricing_national_channel_multiplier_applied
    """
    world = fixtures.setup_active_program(
        api,
        account_overrides={"pricing_class": "NATIONAL"},
        families=[family_spec(base_lead_weeks=2)],
    )
    order = fixtures.place_order(api, world["account"], world["program"])

    # 10000 x 0.90 = 9000, no tier (gross far below 500000), no program discount.
    assert order["quoted_total_cents"] == 9000
    assert order["lines"][0]["unit_quoted_cents"] == 9000


def test_promised_week_extended_lead_class_adds_two_weeks(api):
    """An EXTENDED account's promise adds two weeks on top of the base lead.

    PRD §3.3: "At submit, the order's `promised_delivery_week` is the submit week advanced by the effective lead time: the largest `base_lead_weeks` among the order's families, plus 2 extra weeks when the account's `lead_time_class` is `EXTENDED`."
    Design: Corner/calculations/promised_week_extended_lead_class_adds_two_weeks
    """
    world = fixtures.setup_active_program(
        api,
        account_overrides={"channel": "BUILDER", "lead_time_class": "EXTENDED"},
    )
    order = fixtures.place_order(
        api, world["account"], world["program"],
        requested_delivery_week=WEEK_PLUS_5,
    )

    # Submit week W36 + base lead 3 + EXTENDED 2 = W41.
    assert order["promised_delivery_week"] == "2026-W41"


def test_slot_selector_earliest_eligible_week_wins(api):
    """Between two eligible buckets the picker ranks by week ascending, not by
    creation order.

    PRD §3.4: "Among eligible slots the picker ranks by week ascending, then `plant_code` ascending, then `created_at` ascending — never by `id` — and takes the first."
    Design: Corner/calculations/slot_selector_earliest_eligible_week_wins
    """
    world = fixtures.setup_active_program(api)
    # Create the LATER week first to prove ranking is not creation order.
    fixtures.create_production_slot(api, plant_code="PLANT_WEST", week=WEEK_PLUS_2, capacity_units=5)
    fixtures.create_production_slot(api, plant_code="PLANT_EAST", week=WEEK_NEXT, capacity_units=5)
    order = fixtures.place_order(
        api, world["account"], world["program"], requested_delivery_week=WEEK_PLUS_5
    )
    fixtures.acknowledge_order(api, order["id"])

    scheduled = fixtures.schedule_order(api, order["id"])
    assert scheduled["scheduled_week"] == "2026-W37"

    slots, meta = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert meta["total_count"] == 1
    assert slots[0]["committed_units"] == 1


def test_expedite_overbook_allows_ten_percent_then_refuses(api):
    """Replacement scheduling may overbook a LOCKED slot by floor(capacity x
    0.10); the next unit beyond the allowance finds no capacity.

    PRD §3.5: "Capacity then follows the expedite variant of slot selection: the window is only the current week and the next, slots in `OPEN` or `LOCKED` are both eligible, and a slot stays eligible while its `committed_units` plus the replacement's demand fit within its `capacity_units` plus the floor of one-tenth of `capacity_units` — an overbook allowance of up to 10 percent."
    PRD §3.5: "Ranking is the same week-plant-creation order as the strict variant, and finding no eligible slot rejects the transition with `ERR_NO_CAPACITY`."
    Design: Corner/calculations/expedite_overbook_allows_ten_percent_then_refuses
    """
    world = fixtures.setup_delivered_order(
        api,
        order_overrides={"lines": [order_line(quantity=50)]},
        slot_overrides={"week": WEEK_NEXT, "capacity_units": 50},
    )
    slot = world["slot"]
    assert slot["capacity_units"] == 50
    # The original order's 50 units fill the slot exactly.
    assert fixtures.list_production_slots(api, {"family_code": "F1", "week": "2026-W37"})[0][
        "committed_units"
    ] == 50

    claim5 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=5)
    fixtures.approve_claim(api, claim5["id"], "REPLACEMENT")
    r5 = fixtures.get_replacement_for_claim(api, claim5["id"])

    claim1 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    fixtures.approve_claim(api, claim1["id"], "REPLACEMENT")
    r1 = fixtures.get_replacement_for_claim(api, claim1["id"])

    # 50 + 5 <= 50 + floor(50 x 0.10) = 55: the five-unit replacement schedules.
    scheduled = fixtures.transition_replacement(api, r5["id"], "SCHEDULED")
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_week"] == "2026-W37"
    assert fixtures.list_production_slots(api, {"family_code": "F1", "week": "2026-W37"})[0][
        "committed_units"
    ] == 55

    # 55 + 1 > 55: refused, and the replacement stays put.
    blocked = api.transition_replacement_order(
        r1["id"], {"to_status": "SCHEDULED"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_NO_CAPACITY")
    assert fixtures.get_replacement_order(api, r1["id"])["status"] == "CREATED"
