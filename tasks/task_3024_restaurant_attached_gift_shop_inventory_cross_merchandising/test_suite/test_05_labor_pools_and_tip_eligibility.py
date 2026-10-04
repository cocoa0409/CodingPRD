"""Labor pools, shift lifecycles and the tip-eligibility derivation."""
import pytest

from test_helpers import api_client, validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, CASHIER, server_for, cashier_for,
    create_item, setup_store, setup_open_day, open_store_day, create_shift, start_shift,
    create_check, get_store_day, get_location, post_guest_counts, store_day_with_disputed_receipt,
    shift_iso, create_receipt, reconcile_receipt,
)

BOAT = "ITM-BOAT-6400"


def _boat():
    return create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)


def _boot(**brand_overrides):
    base = {"tip_minimum_minutes": 240, "food_storage_corridor_units": 310}
    base.update(brand_overrides)
    return setup_open_day(brand_overrides=base)


# ==========================================================================
# Difficulty queue A — cross_entity_state_dependency (shift start gate)
# ==========================================================================

def test_starting_a_shift_is_refused_while_the_store_day_gate_is_suspended(api):
    """PRD §3.6: "Starting a shift is a `BoutiqueManager` action that requires the shift to
    be `SCHEDULED`, requires the logical clock's current instant to be at or after the
    shift's `start_utc`, and requires the referenced store day's `conversion_gate` to be
    anything other than `SUSPENDED`"
    PRD §2.10: "A `SUSPENDED` gate refuses every retail-side write it guards, and such a
    refusal is reported with `ERR_STORE_DAY_GATE_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/shift_start_depends_on_the_store_day_conversion_gate
    """
    brand = api.create_brand(f.create_brand_payload(tip_minimum_minutes=240,
                                                    food_storage_corridor_units=310), ADMIN).json()["data"]
    loc = api.create_location(f.create_location_payload(brand["id"]), ADMIN).json()["data"]
    item = _boat()
    day, _ = store_day_with_disputed_receipt(loc["id"], "2026-09-13T00:00:00Z", item["id"],
                                             receipt_number="R-1042-0013")
    assert day["conversion_gate"] == "SUSPENDED"
    validate_success(api.set_clock("2026-09-13T09:05:00Z", ADMIN))
    shift = create_shift(loc["id"], employee_id="E-903", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-13T09:00:00Z", end_utc="2026-09-13T12:59:00Z")

    validate_error(api.start_staff_shift(shift["id"], MANAGER),
                   ApiErrorId.ERR_STORE_DAY_GATE_SUSPENDED.value)


def test_the_suspended_gate_blocks_the_shift_without_rewriting_it(api):
    """PRD §3.6: "A new shift starts with `status` of `SCHEDULED`, `tip_eligible` false and
    `tip_eligible_minutes` of zero."
    PRD §2.10: "An `OPEN` gate admits every retail-side write in this document. A
    `SUSPENDED` gate refuses every retail-side write it guards"

    Design: Difficulty/cross_entity_state_dependency/shift_start_depends_on_the_store_day_conversion_gate
    """
    brand = api.create_brand(f.create_brand_payload(tip_minimum_minutes=240,
                                                    food_storage_corridor_units=310), ADMIN).json()["data"]
    loc = api.create_location(f.create_location_payload(brand["id"]), ADMIN).json()["data"]
    item = _boat()
    day, receipt = store_day_with_disputed_receipt(loc["id"], "2026-09-13T00:00:00Z", item["id"],
                                                   receipt_number="R-1042-0013")
    validate_success(api.set_clock("2026-09-13T09:05:00Z", ADMIN))
    shift = create_shift(loc["id"], employee_id="E-903", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-13T09:00:00Z", end_utc="2026-09-13T12:59:00Z")
    validate_error(api.start_staff_shift(shift["id"], MANAGER),
                   ApiErrorId.ERR_STORE_DAY_GATE_SUSPENDED.value)

    unchanged = api.get_staff_shift(shift["id"], MANAGER).json()["data"]
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["tip_eligible"] is False


# ==========================================================================
# Difficulty queue A — transitive_cascade (shift completion)
# ==========================================================================

def test_completing_a_shift_reweights_the_checks_it_presented(api):
    """PRD §3.6: "Every `GuestCheck` that this employee presented - recorded on the check
    as `presented_shift_id` - has its `tip_eligible` recomputed as the conjunction over all
    shifts that reference it"
    PRD §2.11: "the check's own `tip_eligible` is true only when **every** shift that
    presented it is tip-eligible and the check is `FINALIZED`"

    Design: Difficulty/transitive_cascade/shift_completion_cascades_three_hops_to_the_conversion_index
    """
    brand = api.create_brand(f.create_brand_payload(tip_minimum_minutes=240,
                                                    waiting_area_retail_weight_bps=6000,
                                                    food_storage_corridor_units=310), ADMIN).json()["data"]
    loc = api.create_location(f.create_location_payload(brand["id"]), ADMIN).json()["data"]
    day = open_store_day(loc["id"], "2026-09-07T00:00:00Z")
    # PRD 3.1 derives traffic_state RUSH and conversion_gate GATED_RESTRICTED at
    # or above 120 guests, and PRD 3.6 requires the gate to be exactly OPEN for a
    # shift to be tip-eligible, so the day is kept below the 120-guest edge.
    day = post_guest_counts(day["id"], day["version"], 90, 900000, 35, 18)
    # PRD 3.6: starting a shift requires the logical clock's current instant to be
    # at or after the shift's start_utc, so the clock is placed inside the shift.
    validate_success(api.set_clock("2026-09-07T09:00:00Z", ADMIN))
    shift = create_shift(loc["id"], employee_id="E-901", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-07T09:00:00Z", end_utc="2026-09-07T13:00:00Z")
    start_shift(shift["id"])
    for table, subtotal, tip in (("7", 11200, 2000), ("8", 8000, 2000)):
        check = create_check(loc["id"], day["id"], shift["id"], table_number=table,
                             restaurant_guest_count=4, restaurant_subtotal_cents=subtotal)
        validate_success(api.post_tip(check["id"], {"tip_cents": tip}, cashier_for(shift["id"])))
        validate_success(api.finalize_guest_check(check["id"], cashier_for(shift["id"])))

    completed = validate_success(api.complete_staff_shift(shift["id"], MANAGER))

    assert completed["status"] == "COMPLETED"
    assert completed["tip_eligible"] is True, "09:00 to 13:00 is exactly 240 minutes"
    rows, _ = validate_paginated(
        api.list_guest_checks(MANAGER, {"store_day_id": day["id"], "tip_eligible": True})
    )
    assert len(rows) == 2


def test_completing_a_shift_moves_the_store_day_conversion_index(api):
    """PRD §3.5: "Earned tips are the sum of `tip_cents` across the checks of that store
    day whose `tip_eligible` is true and whose `check_status` is `FINALIZED`"
    PRD §3.5: "The second signal is the tip share. If the day's `retail_sales_cents` is
    zero the tip share is pinned to 0; otherwise it is the day's earned tips multiplied by
    ten thousand and divided by the day's `retail_sales_cents`"

    Design: Difficulty/transitive_cascade/shift_completion_cascades_three_hops_to_the_conversion_index
    """
    brand = api.create_brand(f.create_brand_payload(tip_minimum_minutes=240,
                                                    waiting_area_retail_weight_bps=6000,
                                                    food_storage_corridor_units=310), ADMIN).json()["data"]
    loc = api.create_location(f.create_location_payload(brand["id"]), ADMIN).json()["data"]
    day = open_store_day(loc["id"], "2026-09-07T00:00:00Z")
    # PRD 3.1 derives traffic_state RUSH and conversion_gate GATED_RESTRICTED at
    # or above 120 guests, and PRD 3.6 requires the gate to be exactly OPEN for a
    # shift to be tip-eligible, so the day is kept below the 120-guest edge.
    day = post_guest_counts(day["id"], day["version"], 90, 900000, 35, 18)
    # PRD 3.6: starting a shift requires the logical clock's current instant to be
    # at or after the shift's start_utc, so the clock is placed inside the shift.
    validate_success(api.set_clock("2026-09-07T09:00:00Z", ADMIN))
    before = get_store_day(day["id"])["waiting_area_conversion_index_bps"]

    shift = create_shift(loc["id"], employee_id="E-901", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-07T09:00:00Z", end_utc="2026-09-07T13:00:00Z")
    start_shift(shift["id"])
    boat = _boat()
    # PRD 3.5: "If the day's `retail_sales_cents` is zero the tip share is pinned
    # to 0", and the tip share is the signal a completing shift moves — so the
    # day needs a reconciled retail receipt for the tip leg to carry any weight.
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                             "R-1042-0101")
    reconcile_receipt(receipt["id"])
    check = create_check(loc["id"], day["id"], shift["id"], table_number="7",
                         restaurant_guest_count=4, restaurant_subtotal_cents=11200)
    validate_success(api.post_tip(check["id"], {"tip_cents": 2000}, cashier_for(shift["id"])))
    validate_success(api.finalize_guest_check(check["id"], cashier_for(shift["id"])))

    validate_success(api.complete_staff_shift(shift["id"], MANAGER))
    after = get_store_day(day["id"])["waiting_area_conversion_index_bps"]

    assert after != before, "the tip-eligible finalized check must move the index"


# ==========================================================================
# Difficulty queue A — resource_temporal_overlap (half-open shift interval)
# ==========================================================================

def test_a_shift_overlapping_by_one_second_is_refused(api):
    """PRD §3.6: "Within one location and for one `employee_id`, no second shift's interval
    may overlap the first by a minute or more"
    PRD §3.6: "An overlap is refused with `ERR_SHIFT_OVERLAP` (HTTP 409) at priority 19."

    Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_admits_back_to_back_shifts
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    create_shift(loc["id"], employee_id="E-701", workcode="CASHIER", tip_eligible_claim=True,
                 start_utc="2026-09-15T09:00:00Z", end_utc="2026-09-15T13:00:00Z")
    payload = f.create_staff_shift_payload(loc["id"], employee_id="E-701", workcode="CASHIER",
                                           tip_eligible_claim=True,
                                           start_utc="2026-09-15T12:59:59Z",
                                           end_utc="2026-09-15T16:00:00Z")
    validate_error(api.create_staff_shift(payload, MANAGER), ApiErrorId.ERR_SHIFT_OVERLAP.value)


def test_back_to_back_shifts_touching_at_a_single_instant_are_admitted(api):
    """PRD §3.6: "a back-to-back pair that touches at a single instant is permitted,
    because the intervals are half-open and the earlier shift's `end_utc` does not include
    the later shift's `start_utc`."
    PRD §3.6: "A new shift starts with `status` of `SCHEDULED`, `tip_eligible` false and
    `tip_eligible_minutes` of zero."

    Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_admits_back_to_back_shifts
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    create_shift(loc["id"], employee_id="E-702", workcode="CASHIER", tip_eligible_claim=True,
                 start_utc="2026-09-15T09:00:00Z", end_utc="2026-09-15T13:00:00Z")

    second = validate_success(api.create_staff_shift(
        f.create_staff_shift_payload(loc["id"], employee_id="E-702", workcode="SERVER",
                                     tip_eligible_claim=False,
                                     start_utc="2026-09-15T13:00:00Z",
                                     end_utc="2026-09-15T16:00:00Z"), MANAGER), 201)

    assert second["status"] == "SCHEDULED"
    assert second["tip_eligible_minutes"] == 0


# ==========================================================================
# Corner queue B — calculations
# ==========================================================================

def test_shift_length_rounds_up_to_whole_hours_before_the_threshold(api):
    """PRD §3.6: "the shift's length in hours is rounded **up** to a whole number of hours
    and then multiplied by sixty to yield minutes."
    PRD §3.6: "At the default minimum of 240 minutes, a four-hour shift meets the bar
    exactly and a three-hour-fifty-nine-minute shift that rounds up to four hours also
    meets it."

    Design: Corner/calculations/tip_eligibility_rounds_shift_length_up_before_comparing
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    # PRD §3.6: "a claim that cannot reach the bar is refused with
    # ERR_TIP_SHIFT_TOO_SHORT (HTTP 422) at priority 26", so the sub-minimum
    # shift is never scheduled with a claim; it is scheduled without one and the
    # rounding rule is read off the derived eligibility instead.
    long = create_shift(loc["id"], employee_id="E-401", workcode="CASHIER",
                        tip_eligible_claim=True,
                        start_utc="2026-09-21T09:00:00Z", end_utc="2026-09-21T12:59:00Z")
    short = create_shift(loc["id"], employee_id="E-402", workcode="SERVER",
                         tip_eligible_claim=False,
                         start_utc="2026-09-21T09:00:00Z", end_utc="2026-09-21T11:59:00Z")
    validate_success(api.set_clock("2026-09-21T09:00:00Z", ADMIN))

    long_started = start_shift(long["id"])
    short_started = start_shift(short["id"])

    assert long_started["tip_eligible_minutes"] == 240, "ceil(3h59m) * 60"
    assert long_started["tip_eligible"] is True
    assert short_started["tip_eligible_minutes"] == 180
    assert short_started["tip_eligible"] is False


def test_shift_shorter_than_one_hour_has_zero_tip_minutes(api):
    """PRD §3.6: "A shift whose rounded-up length is zero hours - one shorter than an hour
    - has a minute count of zero and is ineligible regardless of its workcode."
    PRD §2.11: "the workcode must be tip-eligible, the shift must have worked at least the
    brand's minimum tip-eligible minutes, and the store day's `conversion_gate` must be
    exactly `OPEN`"

    Design: Corner/calculations/tip_eligibility_rounds_shift_length_up_before_comparing
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    tiny = create_shift(loc["id"], employee_id="E-403", workcode="CASHIER",
                        start_utc="2026-09-21T09:00:00Z", end_utc="2026-09-21T09:30:00Z")
    validate_success(api.set_clock("2026-09-21T09:00:00Z", ADMIN))

    started = start_shift(tiny["id"])

    assert started["tip_eligible_minutes"] == 0
    assert started["tip_eligible"] is False


# ==========================================================================
# Corner queue B — state_machines
# ==========================================================================

def test_completing_a_scheduled_shift_is_refused(api):
    """PRD §3.6: "A `BoutiqueManager` completes a shift that is currently `IN_PROGRESS` and
    whose `start_utc` the logical clock has reached"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/staff_shift_complete_requires_an_in_progress_shift
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    shift = create_shift(loc["id"], employee_id="E-201", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-21T09:00:00Z", end_utc="2026-09-21T13:00:00Z")
    validate_success(api.set_clock("2026-09-21T09:00:00Z", ADMIN))

    validate_error(api.complete_staff_shift(shift["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = api.get_staff_shift(shift["id"], MANAGER).json()["data"]
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["tip_eligible"] is False


def test_starting_then_completing_a_shift_succeeds(api):
    """PRD §3.6: "completion stamps `completed_at`, recomputes `tip_eligible_minutes` over
    the worked interval and recomputes `tip_eligible` through the same three-condition
    derivation"
    PRD §3.6: "`COMPLETED` is one of the shift's two terminal states"

    Design: Corner/state_machines/staff_shift_complete_requires_an_in_progress_shift
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    shift = create_shift(loc["id"], employee_id="E-202", workcode="CASHIER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-21T09:00:00Z", end_utc="2026-09-21T13:00:00Z")
    validate_success(api.set_clock("2026-09-21T09:00:00Z", ADMIN))
    started = start_shift(shift["id"])
    assert started["status"] == "IN_PROGRESS"

    completed = validate_success(api.complete_staff_shift(shift["id"], MANAGER))

    assert completed["status"] == "COMPLETED"
    assert completed["tip_eligible"] is True, "09:00 to 13:00 is exactly 240 minutes"


# ==========================================================================
# Corner queue B — endpoints
# ==========================================================================

def test_the_tip_eligible_check_query_separates_the_two_shifts(api):
    """PRD §2.11: "the check's own `tip_eligible` is true only when **every** shift that
    presented it is tip-eligible and the check is `FINALIZED`."
    PRD §3.6: "A shift whose rounded-up length is zero hours - one shorter than an hour - has a
    minute count of zero and is ineligible regardless of its workcode."

    Design: Corner/endpoints/tip_recompute_helper_makes_the_tip_eligible_query_observable
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    validate_success(api.set_clock("2026-09-21T12:00:00Z", ADMIN))
    long_shift = create_shift(loc["id"], employee_id="E-501", workcode="CASHIER",
                              tip_eligible_claim=True,
                              start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T12:00:00Z")
    # A 3-hour shift cannot reach the 240-minute bar, so PRD 3.6 refuses any
    # tip-eligibility claim for it; the audience here is the derived eligibility.
    short_shift = create_shift(loc["id"], employee_id="E-502", workcode="SERVER",
                               tip_eligible_claim=False,
                               start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T11:00:00Z")
    start_shift(long_shift["id"])
    start_shift(short_shift["id"])
    check_long = create_check(loc["id"], day["id"], long_shift["id"], table_number="11",
                              restaurant_guest_count=2, restaurant_subtotal_cents=5000)
    check_short = create_check(loc["id"], day["id"], short_shift["id"], table_number="12",
                               restaurant_guest_count=2, restaurant_subtotal_cents=5000)
    for cid, sid in ((check_long["id"], long_shift["id"]), (check_short["id"], short_shift["id"])):
        api.post_tip(cid, {"tip_cents": 900}, cashier_for(sid))
        validate_success(api.finalize_guest_check(cid, cashier_for(sid)))

    eligible, meta = validate_paginated(
        api.list_guest_checks(MANAGER, {"store_day_id": day["id"], "tip_eligible": True})
    )

    assert meta["total_count"] == 1
    assert eligible[0]["id"] == check_long["id"]
    assert eligible[0]["tip_cents"] == 900


def test_the_shift_side_query_agrees_with_the_check_side_derivation(api):
    """PRD §3.6: "The shift is then tip-eligible only when all three conditions hold
    together: the workcode is tip-eligible, the rounded-up minute count is at least the
    brand's `tip_minimum_minutes`, and the referenced store day's `conversion_gate` is
    exactly `OPEN`."
    PRD §2.11: "The workcodes `SERVER` and `CASHIER` are therefore the only tip-eligible
    positions in the chain."

    Design: Corner/endpoints/tip_recompute_helper_makes_the_tip_eligible_query_observable
    """
    brand, loc = setup_store(brand_overrides={"tip_minimum_minutes": 240,
                                              "food_storage_corridor_units": 310})
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    validate_success(api.set_clock("2026-09-21T12:00:00Z", ADMIN))
    long_shift = create_shift(loc["id"], employee_id="E-503", workcode="CASHIER",
                              tip_eligible_claim=True,
                              start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T12:00:00Z")
    short_shift = create_shift(loc["id"], employee_id="E-504", workcode="SERVER",
                               tip_eligible_claim=False,
                               start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T11:00:00Z")
    start_shift(long_shift["id"])
    start_shift(short_shift["id"])

    rows, meta = validate_paginated(
        api.list_staff_shifts(MANAGER, {"location_id": loc["id"], "tip_eligible": True})
    )

    assert meta["total_count"] == 1
    assert rows[0]["id"] == long_shift["id"]