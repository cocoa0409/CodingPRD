"""Service order creation and the pricing waterfall: the pinned per-line rounding
site, the volume and fee bands and their keying, deadline tiering at the exact
boundary instant, line-collection shape rules and the fiscal gate."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    TIER_MULTIPLIERS,
    assert_posture,
    assert_service_order,
    assert_service_order_line,
    assert_service_order_waterfall,
    booth_version,
    create_service_order_payload,
    get_booth,
    get_exhibitor,
    get_order,
    list_order_lines,
    make_exhibitor_headers,
    place_order,
    service_order_line,
    set_clock,
    setup_show_ground,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["show_operations_headers"]

# Three cleaning lines whose gross is 100005 cents each, so the 1.30 STANDARD
# multiplier lands every one of them on exactly half a cent.
HALF_CENT_LINES = [
    service_order_line(1, "CLN-VAC", 3, 33335, 0),
    service_order_line(2, "CLN-PORT", 5, 20001, 0),
    service_order_line(3, "CLN-SHAMP", 1, 100005, 0),
]

STANDARD_BAND_CLOCK = "2026-09-05T12:00:00Z"
DISCOUNT_DEADLINE = "2026-09-01T00:00:00Z"
ONE_SECOND_PAST_DEADLINE = "2026-09-01T00:00:01Z"


def _order_priced_at(clock, lines, service_type, **ground_kwargs):
    """Show ground with one booth, the clock parked at `clock` when one is given,
    and one service order placed by the booth's own exhibitor. Returns the
    re-read order."""
    ground = setup_show_ground(**ground_kwargs)
    if clock is not None:
        set_clock(clock)
    created = place_order(ground["booth"]["id"], ground["exhibitor"]["id"],
                          lines=lines, service_type=service_type)
    return get_order(created["id"])


# ---------------------------------------------------------------------------
# The rounding site on a service order line
# ---------------------------------------------------------------------------

def test_each_line_is_rounded_half_up_before_the_subtotal_is_summed():
    """PRD §3.5: "For each line, `unit_qty` is multiplied by `unit_rate_cents` to give an exact integer cent gross; that gross is multiplied by one minus the line's `discount_pct`; the result is multiplied by the order's `tier_multiplier`; and **that** product is rounded half up to a whole cent and stored as `line_total_cents`."
    PRD §3.5: "`subtotal_cents` is the exact integer sum of the per-line rounded values."
    PRD §2.6: "Service order lines are each rounded to whole cents and the rounded values are added."

    Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_round_per_line_then_sum
    """
    order = _order_priced_at(STANDARD_BAND_CLOCK, HALF_CENT_LINES, "CLEANING")

    assert_service_order(order)
    assert order["deadline_tier"] == "STANDARD", (
        f"an order stamped {STANDARD_BAND_CLOCK} sits past the discount deadline and "
        f"on or before move_in_start, so the tier is STANDARD, got {order['deadline_tier']}"
    )
    assert order["tier_multiplier"] == pytest.approx(TIER_MULTIPLIERS["STANDARD"], abs=0.01), (
        f"the STANDARD multiplier is exactly 1.30, got {order['tier_multiplier']}"
    )

    lines = list_order_lines(order["id"])
    assert len(lines) == 3, f"the order carries 3 lines, got {len(lines)}"
    by_seq = {line["line_seq"]: line for line in lines}
    assert set(by_seq) == {1, 2, 3}, f"line_seq values must be 1, 2 and 3, got {sorted(by_seq)}"
    for seq in (1, 2, 3):
        assert by_seq[seq]["line_total_cents"] == 130007, (
            f"line {seq} grosses 100005 cents, which the 1.30 multiplier takes to 130006.5 "
            f"and half-up rounding takes to 130007, got {by_seq[seq]['line_total_cents']}"
        )

    assert order["subtotal_cents"] == 390021, (
        f"three lines rounded to 130007 each sum to 390021, got {order['subtotal_cents']}"
    )
    assert order["subtotal_cents"] != 390020, (
        "390020 is the forbidden reading that sums the unrounded products and rounds once"
    )


def test_per_line_rounding_carries_its_extra_cents_through_the_discount_and_fee_steps():
    """PRD §3.5: "The rounding site is pinned: each line is rounded to whole cents first and the rounded figures are then added."
    PRD §3.5: "Step three computes `volume_discount_cents` as `subtotal_cents` multiplied by that rate, rounded half up."
    PRD §3.5: "Step six computes `service_fee_cents` as `discounted_base_cents` multiplied by that rate, rounded half up."
    PRD §3.5: "Step seven computes `total_cents` as `discounted_base_cents` plus `service_fee_cents`, again exact integer arithmetic."

    Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_round_per_line_then_sum
    """
    order = _order_priced_at(STANDARD_BAND_CLOCK, HALF_CENT_LINES, "CLEANING")

    assert order["subtotal_cents"] == 390021, (
        f"the per-line rounded subtotal is 390021, got {order['subtotal_cents']}"
    )
    assert order["volume_discount_cents"] == 15601, (
        f"390021 sits in the four percent volume band and 15600.84 rounds half up to 15601, "
        f"got {order['volume_discount_cents']}"
    )
    assert order["discounted_base_cents"] == 374420, (
        f"390021 minus 15601 is 374420, got {order['discounted_base_cents']}"
    )
    assert order["service_fee_cents"] == 18721, (
        f"374420 sits at or above 200000 so the fee is five percent, 18721, "
        f"got {order['service_fee_cents']}"
    )
    assert order["total_cents"] == 393141, (
        f"374420 plus 18721 is 393141, got {order['total_cents']}"
    )
    assert order["total_cents"] != 393140, (
        "393140 is the total the forbidden sum-then-round-once reading produces"
    )
    assert_service_order_waterfall(order)


# ---------------------------------------------------------------------------
# Which figure each band is keyed on
# ---------------------------------------------------------------------------

def test_volume_band_is_keyed_on_the_subtotal_and_lowers_the_discounted_base():
    """PRD §3.5: "Step two selects a volume-discount rate keyed on `subtotal_cents`: below 100000 cents the rate is zero; from 100000 up to but not including 500000 it is four percent; from 500000 up to but not including 1500000 it is seven percent; at 1500000 and above it is ten percent."
    PRD §3.5: "Step four computes `discounted_base_cents` as `subtotal_cents` minus `volume_discount_cents`, exact integer arithmetic."

    Design: Difficulty/combinatorial_formula/fee_tier_keyed_on_discounted_base_not_subtotal
    """
    order = _order_priced_at(None, [service_order_line(1, "MH-FORK", 2, 100000, 0)],
                             "MATERIAL_HANDLING", booth_number="2210",
                             booth_sqft=200, booth_type="PENINSULA")

    assert_service_order(order)
    assert order["deadline_tier"] == "ADVANCE", (
        f"the clock sits before the discount deadline, so the tier is ADVANCE, "
        f"got {order['deadline_tier']}"
    )
    assert order["subtotal_cents"] == 200000, (
        f"two units at 100000 cents under a 1.00 multiplier subtotal to 200000, "
        f"got {order['subtotal_cents']}"
    )
    assert order["volume_discount_cents"] == 8000, (
        f"200000 sits in the four percent volume band, so the discount is 8000, "
        f"got {order['volume_discount_cents']}"
    )
    assert order["discounted_base_cents"] == 192000, (
        f"200000 minus 8000 is 192000, got {order['discounted_base_cents']}"
    )


def test_service_fee_band_is_keyed_on_the_discounted_base_not_on_the_subtotal():
    """PRD §3.5: "Step five selects a service-fee rate keyed on `discounted_base_cents` — not on the subtotal and not on the total: below 50000 cents the rate is nine percent; from 50000 up to but not including 200000 it is seven percent; at 200000 and above it is five percent."
    PRD §3.5: "The keying matters: a subtotal of 200000 cents earns the four percent volume band, leaving a discounted base of 192000, which falls into the **seven** percent fee band — not the five percent band that keying the fee off the subtotal would have selected."

    Design: Difficulty/combinatorial_formula/fee_tier_keyed_on_discounted_base_not_subtotal
    """
    order = _order_priced_at(None, [service_order_line(1, "MH-FORK", 2, 100000, 0)],
                             "MATERIAL_HANDLING", booth_number="2210",
                             booth_sqft=200, booth_type="PENINSULA")

    assert order["discounted_base_cents"] == 192000, (
        f"the fee band is keyed on a discounted base of 192000, "
        f"got {order['discounted_base_cents']}"
    )
    assert order["service_fee_cents"] == 13440, (
        f"192000 sits below 200000 so the fee is seven percent, 13440, "
        f"got {order['service_fee_cents']}"
    )
    assert order["total_cents"] == 205440, (
        f"192000 plus 13440 is 205440, got {order['total_cents']}"
    )
    assert order["total_cents"] != 201600, (
        "201600 is the total that keying the fee band off the 200000 subtotal would give"
    )
    assert_service_order_waterfall(order)


# ---------------------------------------------------------------------------
# The deadline tier boundary
# ---------------------------------------------------------------------------

def test_order_stamped_at_exactly_the_discount_deadline_is_priced_at_advance_tier():
    """PRD §3.5: "If `ordered_at` is at or before the show's `discount_deadline`, the order's `deadline_tier` is `ADVANCE` and its `tier_multiplier` is 1.00."
    PRD §3.5: "Both comparisons include their boundary instant, so an order placed at exactly `discount_deadline` is `ADVANCE` and one placed at exactly `move_in_start` is `STANDARD`; one microsecond later flips the tier."

    Design: Difficulty/boundary_precision_check/deadline_tier_inclusive_at_exact_discount_deadline
    """
    order = _order_priced_at(DISCOUNT_DEADLINE,
                             [service_order_line(1, "CLN-VAC", 2, 75000, 0)],
                             "CLEANING")

    assert_service_order(order)
    assert order["deadline_tier"] == "ADVANCE", (
        f"an order stamped at exactly the discount deadline {DISCOUNT_DEADLINE} is ADVANCE, "
        f"got {order['deadline_tier']}"
    )
    assert order["tier_multiplier"] == pytest.approx(TIER_MULTIPLIERS["ADVANCE"], abs=0.01), (
        f"the ADVANCE multiplier is exactly 1.00, got {order['tier_multiplier']}"
    )
    assert order["subtotal_cents"] == 150000, (
        f"two units at 75000 cents under a 1.00 multiplier subtotal to 150000, "
        f"got {order['subtotal_cents']}"
    )
    assert order["total_cents"] == 154080, (
        f"150000 less a 6000 volume discount is 144000, plus a seven percent fee of 10080 "
        f"is 154080, got {order['total_cents']}"
    )
    assert_service_order_waterfall(order)


def test_order_stamped_one_second_past_the_discount_deadline_is_priced_at_standard_tier():
    """PRD §3.5: "Otherwise, if `ordered_at` is at or before the show's `move_in_start`, the tier is `STANDARD` and the multiplier is 1.30."
    PRD §3.5: "Both comparisons include their boundary instant, so an order placed at exactly `discount_deadline` is `ADVANCE` and one placed at exactly `move_in_start` is `STANDARD`; one microsecond later flips the tier."

    Design: Difficulty/boundary_precision_check/deadline_tier_inclusive_at_exact_discount_deadline
    """
    order = _order_priced_at(ONE_SECOND_PAST_DEADLINE,
                             [service_order_line(1, "CLN-VAC", 2, 75000, 0)],
                             "CLEANING")

    assert_service_order(order)
    assert order["deadline_tier"] == "STANDARD", (
        f"one second past the discount deadline the identical order is STANDARD, "
        f"got {order['deadline_tier']}"
    )
    assert order["tier_multiplier"] == pytest.approx(TIER_MULTIPLIERS["STANDARD"], abs=0.01), (
        f"the STANDARD multiplier is exactly 1.30, got {order['tier_multiplier']}"
    )
    assert order["subtotal_cents"] == 195000, (
        f"a 150000 cent gross under the 1.30 multiplier subtotals to 195000, "
        f"got {order['subtotal_cents']}"
    )
    assert order["total_cents"] == 200304, (
        f"195000 less a 7800 volume discount is 187200, plus a seven percent fee of 13104 "
        f"is 200304, got {order['total_cents']}"
    )
    assert_service_order_waterfall(order)


# ---------------------------------------------------------------------------
# The shape of the lines collection
# ---------------------------------------------------------------------------

def test_create_service_order_omitting_the_lines_field_is_an_invalid_request(api):
    """PRD §3.5: "Either the `Exhibitor` itself or `ShowOperations` on its behalf raises one against a `booth_id`, naming a `service_type` of `ELECTRICAL`, `RIGGING`, `MATERIAL_HANDLING`, `CLEANING` or `INSTALL_DISMANTLE`, supplying the order's `lines`, and pinning the booth it read with `expected_booth_version`."
    PRD §2.9: "Request shape: every required body field is present, every enum value is a declared member of its enumeration, every integer field is a non-negative integer, and every datetime parses as ISO 8601 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."
    PRD §3.5: "The `lines` collection must be non-empty, or the order is refused with `ERR_EMPTY_COLLECTION`."

    Design: Corner/entities/create_service_order_missing_required_lines_returns_invalid_request
    """
    ground = setup_show_ground()
    booth_id = ground["booth"]["id"]
    payload = create_service_order_payload(booth_id, booth_version(booth_id))
    payload.pop("lines")

    response = api.create_service_order(
        payload, make_exhibitor_headers(ground["exhibitor"]["id"]))

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert error["error_id"] != ApiErrorId.ERR_EMPTY_COLLECTION.value, (
        "an absent lines field is a request-shape failure, not an empty collection"
    )

    orders, meta = validate_paginated(
        api.list_service_orders(OPS, params={"booth_id": booth_id}))
    assert meta["total_count"] == 0, (
        f"a refused creation writes no order, got {meta['total_count']} on the booth"
    )
    assert orders == [], f"a refused creation writes no order, got {orders}"


def test_priced_order_lines_are_immutable_and_carry_neither_version_nor_updated_at(api):
    """PRD §2.5: "A `ServiceOrderLine` is immutable once written and is never soft-deleted, so it carries only `id` and `created_at`: it has neither an `updated_at` field nor a `version` field, and neither should appear in its representation."
    PRD §3.5: "Line rows are immutable once written, are never soft-deleted, and each stores its own computed `line_total_cents`."
    PRD §3.5: "For each line, `unit_qty` is multiplied by `unit_rate_cents` to give an exact integer cent gross; that gross is multiplied by one minus the line's `discount_pct`; the result is multiplied by the order's `tier_multiplier`; and **that** product is rounded half up to a whole cent and stored as `line_total_cents`."

    Design: Corner/entities/service_order_line_is_immutable_and_carries_no_version
    """
    ground = setup_show_ground()
    order = place_order(ground["booth"]["id"], ground["exhibitor"]["id"],
                        lines=[service_order_line(1, "ELEC-20A", 4, 32500, 0),
                               service_order_line(2, "ELEC-LBR", 3, 21750, 0.10)])

    response = api.list_service_order_lines(order["id"], OPS)
    lines, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", (
        "a line listing is a collection read and carries response_type array"
    )
    assert meta["total_count"] == 2, (
        f"the order was written with 2 lines, got {meta['total_count']}"
    )
    by_seq = {line["line_seq"]: line for line in lines}
    assert set(by_seq) == {1, 2}, f"line_seq values must be 1 and 2, got {sorted(by_seq)}"

    for seq, line in by_seq.items():
        assert_service_order_line(line)
        assert "version" not in line, (
            f"line {seq} must not carry a version field, got {line.get('version')}"
        )
        assert "updated_at" not in line, (
            f"line {seq} must not carry an updated_at field, got {line.get('updated_at')}"
        )

    assert by_seq[1]["line_total_cents"] == 130000, (
        f"4 units at 32500 cents undiscounted under a 1.00 multiplier is 130000, "
        f"got {by_seq[1]['line_total_cents']}"
    )
    assert by_seq[2]["line_total_cents"] == 58725, (
        f"3 units at 21750 cents less ten percent under a 1.00 multiplier is 58725, "
        f"got {by_seq[2]['line_total_cents']}"
    )


def test_line_sequence_with_a_gap_is_refused_and_prices_nothing(api):
    """PRD §3.5: "The `line_seq` values must be unique within the order and must form a contiguous run starting at 1; a gap or a duplicate is refused with `ERR_INVALID_LINE_SEQUENCE`."
    PRD §2.9: "Line sequence numbers are unique and contiguous from 1 — otherwise `ERR_INVALID_LINE_SEQUENCE` (422). Applies to `POST /service-orders`."

    Design: Corner/validations/non_contiguous_line_sequence_rejected
    """
    ground = setup_show_ground()
    booth_id = ground["booth"]["id"]
    payload = create_service_order_payload(
        booth_id, booth_version(booth_id),
        lines=[service_order_line(1, "ELEC-20A", 1, 32500, 0),
               service_order_line(3, "ELEC-LBR", 1, 21750, 0)])

    response = api.create_service_order(
        payload, make_exhibitor_headers(ground["exhibitor"]["id"]))

    validate_error(response, ApiErrorId.ERR_INVALID_LINE_SEQUENCE.value, 422)

    orders, meta = validate_paginated(
        api.list_service_orders(OPS, params={"booth_id": booth_id}))
    assert meta["total_count"] == 0, (
        f"a refused line sequence prices nothing, got {meta['total_count']} orders"
    )
    assert orders == [], f"a refused line sequence prices nothing, got {orders}"


# ---------------------------------------------------------------------------
# The fiscal gate
# ---------------------------------------------------------------------------

def test_projected_exposure_exactly_equal_to_the_credit_limit_is_admitted(api):
    """PRD §3.5: "The exhibitor's projected exposure is its current `account_balance_cents` plus the sum of `total_cents` across all of its service orders whose `billing_status` is `UNBILLED`, counting the order now being created."
    PRD §3.5: "That figure must not exceed the exhibitor's `credit_limit_cents`; equality is permitted, and only a strictly greater figure is refused, with `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402."
    PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of `settled_cents` over those same invoices, minus the sum of `settlement_cents` over that exhibitor's damage claims whose `status` is `SETTLED`."
    PRD §2.10: "A balance exactly equal to the limit is not a breach."

    Design: Corner/calculations/credit_limit_equality_is_admitted_not_refused
    """
    ground = setup_show_ground(credit_limit_cents=154080)
    booth_id = ground["booth"]["id"]
    exhibitor_id = ground["exhibitor"]["id"]
    payload = create_service_order_payload(
        booth_id, booth_version(booth_id), service_type="CLEANING",
        lines=[service_order_line(1, "CLN-VAC", 2, 75000, 0)])

    response = api.create_service_order(payload, make_exhibitor_headers(exhibitor_id))

    order = validate_success(response, 201)
    assert_service_order(order)
    assert order["total_cents"] == 154080, (
        f"the order totals 154080, exactly the credit limit, got {order['total_cents']}"
    )
    assert order["billing_status"] == "UNBILLED", (
        f"a freshly written order begins UNBILLED, got {order['billing_status']}"
    )
    assert_service_order_waterfall(order)

    exhibitor = get_exhibitor(exhibitor_id)
    assert exhibitor["account_balance_cents"] == 0, (
        f"nothing has been invoiced, so the balance stays 0, "
        f"got {exhibitor['account_balance_cents']}"
    )
    assert_posture(get_booth(booth_id), "OPEN")
