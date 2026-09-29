"""Listing: the destination channel's own state, the assortment gate and pricing."""

from test_helpers import (
    ADMIN,
    CHANNEL_RESALE_MP,
    MERCH,
    api_client,
    assert_instant,
    assert_null,
    assert_unit_dimensions,
    create_channel,
    fetch_unit,
    list_unit,
    list_unit_payload,
    pause_channel,
    refurbish_unit,
    setup_accepted_trade_in,
    setup_estate,
    setup_refurbished_unit,
    validate_error,
    validate_success,
)


def _reactivate_channel(channel_id):
    """Put a paused channel back on air, which only a ProgramAdmin may do."""
    return validate_success(
        api_client.patch_channel(channel_id, {"status": "ACTIVE"}, ADMIN)
    )


def _ready_outerwear_unit(estate):
    """An OWNED_INVENTORY OUTERWEAR grade B unit that has passed a zero-cost refurb."""
    return setup_refurbished_unit(estate, loyalty_tier="PLUS")


def test_a_paused_channel_refuses_a_listable_unit_and_reactivation_admits_it():
    """Nothing about the unit changes across the refusal and the success.

    PRD §3.6: "The destination channel must be `ACTIVE`, otherwise
    `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §3.1: "A channel's `status` begins `ACTIVE` and may be paused; a `PAUSED`
    channel accepts neither new listings nor new resale orders, and both refusals
    carry `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §3.6: "A successful listing writes `listed_channel_id` to the chosen
    channel, freezes `list_price_minor` and `current_price_minor` as just computed,
    resets `markdown_step_count` to 0, stamps `listed_at` from the logical clock,
    moves `lifecycle_state` to `LISTED`, and increments the unit's version."
    PRD §3.6: "`accounting_state` is not touched by listing at all."

    Design: Difficulty/cross_entity_state_dependency/listing_blocked_by_paused_channel_state
    """
    estate = setup_estate()
    channel = estate["channel"]
    assert channel["status"] == "ACTIVE"

    scenario = _ready_outerwear_unit(estate)
    unit = scenario["unit"]
    assert scenario["refurb_order"]["status"] == "COMPLETED"
    assert_unit_dimensions(unit, "READY", "CAPITALIZED")
    version_when_ready = unit["version"]

    paused = pause_channel(channel["id"])
    assert paused["status"] == "PAUSED"

    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(channel["id"]), MERCH
        ),
        "ERR_CHANNEL_NOT_ACTIVE",
        409,
    )

    # The refused listing wrote nothing at all onto the unit.
    untouched = fetch_unit(unit["id"])
    assert untouched["lifecycle_state"] == "READY"
    assert untouched["version"] == version_when_ready
    assert_null(untouched["listed_channel_id"], "listed_channel_id")
    assert_null(untouched["list_price_minor"], "list_price_minor")
    assert_null(untouched["listed_at"], "listed_at")

    revived = _reactivate_channel(channel["id"])
    assert revived["status"] == "ACTIVE"

    listed = list_unit(unit["id"], channel["id"])
    assert listed["lifecycle_state"] == "LISTED"
    assert listed["listed_channel_id"] == channel["id"]
    # Baseline 19500 beats the 12075 margin floor and clears the 35000 ceiling.
    assert listed["list_price_minor"] == 19500
    assert listed["current_price_minor"] == 19500
    assert listed["markdown_step_count"] == 0
    assert_instant(listed["listed_at"], "2026-08-01T00:00:00Z", "listed_at")
    assert listed["version"] > version_when_ready
    # Listing moved only the commercial dimension.
    assert listed["accounting_state"] == "CAPITALIZED"


def test_the_destination_channels_state_is_the_only_thing_that_differs():
    """The same unit, the same instant, two channels, two outcomes.

    PRD §3.6: "The destination channel must be `ACTIVE`, otherwise
    `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §3.6: "The request names the destination through `channel_id`."
    PRD §3.6: "Otherwise `list_price_minor` is the greater of the baseline resale
    value and the margin floor, then clamped down to the channel ceiling — that is,
    the lesser of the channel ceiling and that greater-of pair."

    Design: Difficulty/cross_entity_state_dependency/listing_blocked_by_paused_channel_state
    """
    estate = setup_estate()
    paused_destination = estate["channel"]
    live_destination = create_channel(CHANNEL_RESALE_MP, code="RESALE-2")

    unit = _ready_outerwear_unit(estate)["unit"]

    pause_channel(paused_destination["id"])
    # Both channels are identically configured; only one of them is on air.
    assert live_destination["status"] == "ACTIVE"
    assert live_destination["allowed_assortment"] == "RESALE_ONLY"
    assert live_destination["max_resale_price_ratio_bp"] == 7000

    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(paused_destination["id"]), MERCH
        ),
        "ERR_CHANNEL_NOT_ACTIVE",
        409,
    )
    assert fetch_unit(unit["id"])["lifecycle_state"] == "READY"

    listed = list_unit(unit["id"], live_destination["id"])
    assert listed["lifecycle_state"] == "LISTED"
    assert listed["listed_channel_id"] == live_destination["id"]
    assert listed["list_price_minor"] == 19500


def test_the_channel_ceiling_clamps_the_price_of_a_consigned_unit():
    """A consigned unit has no floor to speak of, so the ceiling is the only rule.

    PRD §3.6: "The **baseline resale value** is the unit's `reference_msrp_minor`
    multiplied by the tier's `resale_price_pct_bp`, divided by ten thousand and
    rounded down."
    PRD §3.6: "The **channel ceiling** is the unit's `reference_msrp_minor`
    multiplied by that channel's `max_resale_price_ratio_bp`, divided by ten
    thousand and rounded down."
    PRD §3.6: "Otherwise `list_price_minor` is the greater of the baseline resale
    value and the margin floor, then clamped down to the channel ceiling — that is,
    the lesser of the channel ceiling and that greater-of pair."
    PRD §3.6: "A `CONSIGNED` unit has a `capitalized_cost_minor` of 0, which makes
    its margin floor 0 and leaves the channel ceiling as the only binding
    constraint."
    PRD §3.6: "`accounting_state` is not touched by listing at all."

    Design: Corner/calculations/resale_list_price_is_clamped_by_the_channel_ceiling
    """
    estate = setup_estate()
    outlet = create_channel(
        code="OUTLET-1",
        channel_type="OUTLET",
        allowed_assortment="BOTH",
        max_resale_price_ratio_bp=3000,
        region_code="US-CA",
    )

    unit = setup_refurbished_unit(
        estate, loyalty_tier="PLUS", ownership_treatment="CONSIGNED"
    )["unit"]
    # A consigned unit capitalizes nothing, so its margin floor is ceil(0) = 0.
    assert_unit_dimensions(unit, "READY", "UNCAPITALIZED")
    assert unit["capitalized_cost_minor"] == 0

    listed = list_unit(unit["id"], outlet["id"])
    # Baseline floor(50000 * 3900 / 10000) = 19500 against a ceiling of
    # floor(50000 * 3000 / 10000) = 15000, so the ceiling binds.
    assert listed["list_price_minor"] == 15000
    assert listed["current_price_minor"] == 15000
    assert listed["markdown_step_count"] == 0
    assert listed["lifecycle_state"] == "LISTED"
    assert_instant(listed["listed_at"], "2026-08-01T00:00:00Z", "listed_at")
    # The accounting dimension is exactly where it was before the listing.
    assert listed["accounting_state"] == "UNCAPITALIZED"


def test_the_three_listing_gates_each_refuse_the_same_unit_in_turn():
    """Not ready, wrong assortment, unreachable floor — then a clean listing.

    PRD §3.6: "The unit must be in `lifecycle_state` `READY` — its first listing
    after refurbishment — or `RETURNED`, which is the re-listing of a unit that came
    back on a refund; a unit in any other lifecycle state is refused with
    `ERR_UNIT_NOT_READY_FOR_LISTING`."
    PRD §3.6: "The channel's `allowed_assortment` must read `RESALE_ONLY` or
    `BOTH`; a channel restricted to `NEW_ONLY` refuses the listing with
    `ERR_ASSORTMENT_NOT_PERMITTED`, which is the assortment-separation gate that
    keeps refurbished stock out of the full-price shop window."
    PRD §3.6: "The **margin floor** is the unit's `capitalized_cost_minor`
    multiplied by eleven thousand five hundred basis points — a hundred and fifteen
    percent, meaning the brand insists on at least a fifteen percent margin over
    carrying cost — divided by ten thousand and rounded **up**, so the floor is never
    undershot by a fractional cent."
    PRD §3.6: "If the margin floor comes out strictly above the channel ceiling,
    no compliant price exists on that channel at all and the listing is refused with
    `ERR_MARGIN_FLOOR_ABOVE_CHANNEL_CEILING`."

    Design: Corner/errors/listing_gate_errors_are_triggerable_on_three_channels
    """
    estate = setup_estate()
    resale_channel = estate["channel"]
    full_price_channel = create_channel(
        code="DTC-NEW",
        channel_type="FULL_PRICE_DTC",
        allowed_assortment="NEW_ONLY",
        max_resale_price_ratio_bp=9000,
        region_code="US-CA",
    )
    tight_channel = create_channel(
        code="TIGHT",
        channel_type="OUTLET",
        allowed_assortment="BOTH",
        max_resale_price_ratio_bp=1000,
        region_code="US-CA",
    )

    scenario = setup_accepted_trade_in(estate, loyalty_tier="PLUS")
    unit = scenario["unit"]
    assert scenario["grant"]["issued_amount_minor"] == 10500
    assert unit["lifecycle_state"] == "INTAKE"

    # An un-refurbished unit is not in a listable lifecycle state at all.
    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(resale_channel["id"]), MERCH
        ),
        "ERR_UNIT_NOT_READY_FOR_LISTING",
        409,
    )

    passed = refurbish_unit(unit, estate["bay"])
    assert passed["status"] == "COMPLETED"
    unit = fetch_unit(unit["id"])
    assert_unit_dimensions(unit, "READY", "CAPITALIZED")
    assert unit["capitalized_cost_minor"] == 10500

    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(full_price_channel["id"]), MERCH
        ),
        "ERR_ASSORTMENT_NOT_PERMITTED",
        409,
    )

    # Margin floor ceil(10500 * 11500 / 10000) = 12075 against a ceiling of
    # floor(50000 * 1000 / 10000) = 5000: no compliant price exists.
    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(tight_channel["id"]), MERCH
        ),
        "ERR_MARGIN_FLOOR_ABOVE_CHANNEL_CEILING",
        409,
    )

    listed = list_unit(unit["id"], resale_channel["id"])
    assert listed["list_price_minor"] == 19500
    assert listed["listed_channel_id"] == resale_channel["id"]
    assert listed["lifecycle_state"] == "LISTED"

    # And a unit already LISTED is no longer in a listable lifecycle state.
    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(resale_channel["id"]), MERCH
        ),
        "ERR_UNIT_NOT_READY_FOR_LISTING",
        409,
    )
