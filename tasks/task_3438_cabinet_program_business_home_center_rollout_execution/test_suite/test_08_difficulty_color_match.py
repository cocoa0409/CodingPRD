"""Replacement color-match boundary: deltaE 2.0 inclusive pass, 3.0 rejected (PRD §3.5)."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import PLANT_SCHEDULER_HEADERS, WEEK_NEXT, factories, order_line
from test_helpers import fixtures


def _delivered_world_with_pinned_batch(api, order_quantity=2):
    """Order delivered with batch B1 (lab 50/20/30) pinned on its line at
    production start."""
    world = fixtures.setup_delivered_order(
        api,
        order_overrides={"lines": [order_line(quantity=order_quantity)]},
        slot_overrides={"week": WEEK_NEXT, "capacity_units": 100},
    )
    return world


def test_delta_e_two_passes_three_rejected(api):
    """The 2.0 boundary passes inclusively; a distance of 3.0 is refused.

    PRD §3.5: "Scheduling a replacement — `CREATED` → `SCHEDULED` under a `PlantScheduler` — first checks color: the deltaE between the replacement batch and the original pinned batch, computed as the square root of the sum of the squared differences of their `lab_l`, `lab_a`, and `lab_b` coordinates and compared in full floating point, must be no greater than 2.0; the boundary value 2.0 exactly passes, an identical batch passes trivially, and anything larger is rejected with `ERR_COLOR_MISMATCH`."
    PRD §3.5: "A `REPLACEMENT` approval settles goods: `settlement_cents` is 0, a `CURRENT` finish batch must exist for the claimed line's `finish_code` (`ERR_NO_CURRENT_BATCH`), and a replacement order is created in `CREATED` carrying the `damage_claim_id`, the original `order_id` and `line_index`, a `quantity` equal to the claim's `claimed_qty`, `finish_batch_id` set to that current batch, and `original_finish_batch_id` set to the batch pinned on the original order line at production start."
    Design: Difficulty/boundary_precision_check/color_match_delta_e_inclusive_boundary
    """
    world = _delivered_world_with_pinned_batch(api)

    # B2 at deltaE == 2.0 from the pinned B1 becomes CURRENT before claim 1.
    b2 = fixtures.create_finish_batch(
        api, batch_code="B2", lab_l=52, lab_a=20, lab_b=30,
        effective_from="2026-09-01T00:00:00Z",
    )
    claim1 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    claim1 = fixtures.approve_claim(api, claim1["id"], "REPLACEMENT")
    assert claim1["settlement_cents"] == 0
    r1 = fixtures.get_replacement_for_claim(api, claim1["id"])
    assert r1["finish_batch_id"] == b2["id"]
    assert r1["original_finish_batch_id"] == world["order"]["lines"][0]["finish_batch_id"]

    # B3 at deltaE == 3.0 becomes CURRENT before claim 2.
    fixtures.create_finish_batch(
        api, batch_code="B3", lab_l=53, lab_a=20, lab_b=30,
        effective_from="2026-09-01T01:00:00Z",
    )
    claim2 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    fixtures.approve_claim(api, claim2["id"], "REPLACEMENT")
    r2 = fixtures.get_replacement_for_claim(api, claim2["id"])

    scheduled = fixtures.transition_replacement(api, r1["id"], "SCHEDULED")
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_week"] == "2026-W37"

    blocked = api.transition_replacement_order(
        r2["id"], factories.replacement_transition_payload("SCHEDULED"), PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_COLOR_MISMATCH")
    r2_after = fixtures.get_replacement_order(api, r2["id"])
    assert r2_after["status"] == "CREATED"


def test_identical_batch_passes_trivially(api):
    """When the CURRENT batch at approval is the pinned batch itself, the color
    check passes trivially and scheduling proceeds.

    PRD §3.5: "Scheduling a replacement — `CREATED` → `SCHEDULED` under a `PlantScheduler` — first checks color: the deltaE between the replacement batch and the original pinned batch, computed as the square root of the sum of the squared differences of their `lab_l`, `lab_a`, and `lab_b` coordinates and compared in full floating point, must be no greater than 2.0; the boundary value 2.0 exactly passes, an identical batch passes trivially, and anything larger is rejected with `ERR_COLOR_MISMATCH`."
    Design: Difficulty/boundary_precision_check/color_match_delta_e_inclusive_boundary
    """
    world = _delivered_world_with_pinned_batch(api, order_quantity=1)

    claim = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    fixtures.approve_claim(api, claim["id"], "REPLACEMENT")
    replacement = fixtures.get_replacement_for_claim(api, claim["id"])

    # No new batch was registered: the replacement targets the very batch that
    # was pinned on the order line at IN_PRODUCTION.
    assert replacement["finish_batch_id"] == replacement["original_finish_batch_id"]

    scheduled = fixtures.transition_replacement(api, replacement["id"], "SCHEDULED")
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_week"] == "2026-W37"
