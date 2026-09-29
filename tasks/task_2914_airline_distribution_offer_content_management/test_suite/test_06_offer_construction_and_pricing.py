"""Offer construction: per-line rounding, the pinned summation order and surcharges."""

from test_helpers import (
    ITEM_TYPE_ANCILLARY,
    ITEM_TYPE_BUNDLE_ANCILLARY,
    ITEM_TYPE_FARE,
    ITEM_TYPE_SURCHARGE,
    assert_line,
    assert_offer_money,
    fixtures as fx,
    line_by_code,
)


def _priced_world(api):
    channel = fx.create_ndc_channel(api)
    partner = fx.create_alpha_agency(api)
    catalogue = fx.create_ndc_catalogue(api)
    filing = fx.create_ndc_filing(api)
    return channel, partner, catalogue, filing


def test_a_la_carte_offer_sums_already_rounded_line_amounts(api):
    """PRD §3.5: "Third, the channel markup is applied and the line is rounded: the
    line's `net_amount_cents` is the discounted value multiplied by one plus the
    channel's `content_markup_pct`, rounded half up to whole cents."
    PRD §3.5: "Each line is rounded to whole cents at the third step, and the offer's
    `subtotal_cents` is then the sum of those **already rounded** `net_amount_cents`
    values across the fare line, the bundled ancillary lines and the à la carte
    ancillary lines."
    PRD §3.5: "Summing the unrounded line values and rounding once at the end is
    explicitly not the rule, and the two approaches can differ by as much as one cent
    per line beyond the first."

    Design: Difficulty/combinatorial_formula/offer_subtotal_rounds_per_line_before_summing
    """
    channel, partner, _catalogue, filing = _priced_world(api)

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        ancillary_codes=[fx.ANCILLARY_BAG, fx.ANCILLARY_SEAT, fx.ANCILLARY_WIFI],
    )
    lines = fx.read_offer_items(api, offer["id"])

    # 45010 * 1.035 = 46585.35 -> 46585; 7010 -> 7255; 3010 -> 3115; 1010 -> 1045.
    assert line_by_code(lines, fx.NDC_FARE_BASIS)["net_amount_cents"] == 46585
    assert line_by_code(lines, fx.ANCILLARY_BAG)["net_amount_cents"] == 7255
    assert line_by_code(lines, fx.ANCILLARY_SEAT)["net_amount_cents"] == 3115
    assert line_by_code(lines, fx.ANCILLARY_WIFI)["net_amount_cents"] == 1045

    # Sum of the rounded lines is 58000; rounding once at the end would give 58001
    # because 56040 * 1.035 = 58001.4.
    assert offer["subtotal_cents"] == 58000
    assert offer["subtotal_cents"] != 58001

    # ANCILLARY base 11415 -> raw 570.75 -> 571, clamped down to the rule's max 400.
    # ALL base 58000 -> raw 1160, inside [500, 1200].
    assert_offer_money(offer, subtotal_cents=58000, surcharge_cents=1560, item_count=6)


def test_bundled_lines_discount_at_full_precision_then_round_once(api):
    """PRD §3.5: "Second, the bundle discount is applied — and *only* to bundled
    ancillary lines: the discounted value is the line's list amount multiplied by one
    minus the bundle's `bundle_discount_pct`, carried at full precision with no
    rounding."
    PRD §3.5: "Surcharge lines are produced afterwards and never enter `subtotal_cents`."

    Design: Difficulty/combinatorial_formula/offer_subtotal_rounds_per_line_before_summing
    """
    channel, partner, catalogue, filing = _priced_world(api)

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        bundle_id=catalogue["bundle"]["id"],
    )
    lines = fx.read_offer_items(api, offer["id"])

    bag = line_by_code(lines, fx.ANCILLARY_BAG)
    seat = line_by_code(lines, fx.ANCILLARY_SEAT)
    assert bag["item_type"] == ITEM_TYPE_BUNDLE_ANCILLARY
    assert seat["item_type"] == ITEM_TYPE_BUNDLE_ANCILLARY
    # 7010 * 0.9 = 6309 exactly, * 1.035 = 6529.815 -> 6530.
    assert bag["list_amount_cents"] == 7010
    assert bag["net_amount_cents"] == 6530
    # 3010 * 0.9 = 2709 exactly, * 1.035 = 2803.815 -> 2804.
    assert seat["list_amount_cents"] == 3010
    assert seat["net_amount_cents"] == 2804

    # 46585 + 6530 + 2804; the ANCILLARY base is 9334, below its 10000 threshold, so
    # only the ALL rule fires: 55919 * 0.02 = 1118.38 -> 1118.
    assert_offer_money(offer, subtotal_cents=55919, surcharge_cents=1118, item_count=4)
    assert offer["subtotal_cents"] == 55919


def test_surcharge_raw_amount_is_rounded_before_the_clamps(api):
    """PRD §3.5: "The raw amount is the scope base multiplied by the rule's `rate_pct`,
    rounded half up to whole cents; that rounding happens **before** the clamps, not
    after."
    PRD §3.5: "The emitted line records the raw amount in its `list_amount_cents` and
    the clamped amount in its `net_amount_cents`, so a clamped surcharge remains
    auditable against what the rate alone would have produced."

    Design: Difficulty/combinatorial_formula/offer_subtotal_rounds_per_line_before_summing
    """
    channel, partner, _catalogue, filing = _priced_world(api)

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        ancillary_codes=[fx.ANCILLARY_BAG, fx.ANCILLARY_SEAT, fx.ANCILLARY_WIFI],
    )
    lines = fx.read_offer_items(api, offer["id"])

    ancillary_surcharge = line_by_code(lines, fx.SURCHARGE_ANCILLARY_CODE)
    assert ancillary_surcharge["item_type"] == ITEM_TYPE_SURCHARGE
    # Scope base 7255 + 3115 + 1045 = 11415; 11415 * 0.05 = 570.75 -> 571 -> clamp 400.
    assert ancillary_surcharge["list_amount_cents"] == 571
    assert ancillary_surcharge["net_amount_cents"] == 400
    assert ancillary_surcharge["refundable"] is False

    all_surcharge = line_by_code(lines, fx.SURCHARGE_ALL_CODE)
    assert all_surcharge["list_amount_cents"] == 1160
    assert all_surcharge["net_amount_cents"] == 1160

    # Presentation order: fare, a la carte ancillaries by code, then surcharges in
    # ascending threshold order.
    assert_line(lines[0], 1, ITEM_TYPE_FARE, fx.NDC_FARE_BASIS, 45010, 46585, True)
    assert_line(lines[1], 2, ITEM_TYPE_ANCILLARY, fx.ANCILLARY_BAG, 7010, 7255, True)
    assert_line(lines[2], 3, ITEM_TYPE_ANCILLARY, fx.ANCILLARY_SEAT, 3010, 3115, False)
    assert_line(lines[3], 4, ITEM_TYPE_ANCILLARY, fx.ANCILLARY_WIFI, 1010, 1045, False)
    assert lines[4]["item_code"] == fx.SURCHARGE_ANCILLARY_CODE
    assert lines[5]["item_code"] == fx.SURCHARGE_ALL_CODE
    assert offer["total_cents"] == 59560
