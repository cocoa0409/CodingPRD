"""Cadence runs: the stepping ladder, the price floor, the eligibility predicate
and the per-campaign run checkpoint.

Every unit here starts from the same listing — an OUTERWEAR grade B unit whose
baseline resale value is floor(50000 * 3900 / 10000) = 19500, listed at the
2026-08-01T00:00:00Z default clock — so its markdown floor is always
ceil(19500 * 6000 / 10000) = 11700 and the ladder is 19500 → 16575 → 14088 →
11974 → 11700.
"""

from test_helpers import (
    ADMIN,
    MERCH,
    api_client,
    assert_instant,
    assert_markdown_campaign,
    assert_pagination_meta,
    assert_unit_dimensions,
    create_campaign,
    create_channel,
    fetch_campaign,
    fetch_unit,
    place_order,
    run_campaign,
    set_clock,
    setup_estate,
    setup_listed_unit,
    validate_paginated,
)

# The first three working runs of the ladder: (clock, price the run leaves).
LADDER = (
    ("2026-08-08T00:00:00Z", 16575),
    ("2026-08-15T00:00:00Z", 14088),
    ("2026-08-22T00:00:00Z", 11974),
)
FLOOR_RUN_AT = "2026-08-29T00:00:00Z"
FLOOR_PRICE = 11700


def _run_at(campaign_id, instant):
    """Move the logical clock to ``instant`` and take one cadence run there."""
    set_clock(instant)
    return run_campaign(campaign_id)


def _listed_unit_with_campaign(window_end_at="2026-09-01T00:00:00Z"):
    """A LISTED unit priced at 19500 plus an OUTERWEAR campaign over its channel."""
    estate = setup_estate()
    scenario = setup_listed_unit(estate, loyalty_tier="PLUS")
    assert scenario["unit"]["list_price_minor"] == 19500
    assert scenario["unit"]["current_price_minor"] == 19500
    assert scenario["unit"]["markdown_step_count"] == 0
    assert_unit_dimensions(scenario["unit"], "LISTED", "CAPITALIZED")
    campaign = create_campaign(
        scenario["channel"]["id"], window_end_at=window_end_at
    )
    assert_markdown_campaign(campaign)
    assert campaign["status"] == "SCHEDULED"
    assert campaign["floor_pct_bp"] == 6000
    return scenario, campaign


def _walk_the_ladder(scenario, campaign):
    """Take the three intermediate runs, checking the unit after each one."""
    unit_id = scenario["unit"]["id"]
    for instant, expected_price in LADDER:
        report = _run_at(campaign["id"], instant)
        assert report["marked_down_unit_count"] == 1
        assert report["written_down_unit_count"] == 0
        unit = fetch_unit(unit_id)
        assert unit["current_price_minor"] == expected_price
        # Every intermediate step lands strictly above the 11700 floor, so the
        # accounting dimension has no reason to move yet.
        assert_unit_dimensions(unit, "LISTED", "CAPITALIZED")
    return fetch_unit(unit_id)


def test_the_floor_contact_writes_the_unit_down_without_moving_its_lifecycle():
    """Four runs later the accounting dimension moves and the commercial one does not.

    PRD §3.6: "The **floor price** is the unit's `list_price_minor` multiplied by
    the campaign's `floor_pct_bp`, divided by ten thousand and rounded **up**."
    PRD §3.6: "The **stepped price** is the unit's `current_price_minor`
    multiplied by ten thousand minus the campaign's `step_bp`, divided by ten
    thousand and rounded **down**."
    PRD §3.6: "The new price is the greater of those two, so the step never cuts
    below the floor."
    PRD §3.6: "Otherwise `current_price_minor` becomes the new price,
    `markdown_step_count` is incremented by one, and the unit's version is
    incremented."
    PRD §3.6: "And when that new price lands *exactly* on the floor price and the
    unit's `accounting_state` is `CAPITALIZED`, the accounting dimension moves to
    `WRITTEN_DOWN` in the same step."

    Design: Difficulty/non_linear_state_machine/resale_unit_lifecycle_and_accounting_dimensions_move_independently
    """
    scenario, campaign = _listed_unit_with_campaign()
    unit = scenario["unit"]
    version_when_listed = unit["version"]

    before_floor = _walk_the_ladder(scenario, campaign)
    assert before_floor["current_price_minor"] == 11974
    assert before_floor["markdown_step_count"] == 3

    # Stepped floor(11974 * 8500 / 10000) = 10177 would undercut the floor, so
    # the run lands exactly on 11700, a drop of 274.
    floor_run = _run_at(campaign["id"], FLOOR_RUN_AT)
    assert floor_run["evaluated_unit_count"] == 1
    assert floor_run["marked_down_unit_count"] == 1
    assert floor_run["skipped_at_floor_count"] == 0
    assert floor_run["written_down_unit_count"] == 1
    assert floor_run["total_markdown_minor"] == 274

    at_floor = fetch_unit(unit["id"])
    assert at_floor["current_price_minor"] == FLOOR_PRICE
    assert at_floor["markdown_step_count"] == 4
    # The commercial dimension is exactly where the listing left it.
    assert at_floor["lifecycle_state"] == "LISTED"
    # The accounting dimension moved on its own.
    assert at_floor["accounting_state"] == "WRITTEN_DOWN"
    assert at_floor["list_price_minor"] == 19500
    assert at_floor["version"] > version_when_listed


def test_the_purchase_moves_the_lifecycle_and_leaves_the_write_down_standing():
    """A written-down unit is bought: the commercial dimension advances alone.

    PRD §3.7: "First, `gross_price_minor` is snapshotted from the unit's
    `current_price_minor` — whatever the markdown cadence had brought it down to
    at that moment."
    PRD §3.7: "The bands are upper-inclusive and are tried in declared order: a
    gross price of at most twenty thousand minor units is charged nine hundred
    basis points; a gross price of at most sixty thousand minor units is charged
    six hundred and fifty basis points; anything above sixty thousand is charged
    four hundred and fifty basis points."
    PRD §3.7: "`channel_fee_minor` is the gross price multiplied by the selected
    rate in basis points, divided by ten thousand, rounded **half up**."
    PRD §3.7: "Third, `order_total_minor` is `gross_price_minor` plus
    `channel_fee_minor`."
    PRD §3.7: "As the last cross-entity effect, the purchased unit moves from
    `LISTED` to `RESERVED` and its version is incremented; its
    `current_price_minor` is now frozen inside the order's `gross_price_minor` and
    the unit is no longer eligible for any markdown step."
    PRD §3.6: "`RESERVED` and `SOLD` units are frozen at their sale price and
    never eligible; `RETURNED` units are not listed and never eligible; and a unit
    one day short of its next step boundary is excluded until the next run."

    Design: Difficulty/non_linear_state_machine/resale_unit_lifecycle_and_accounting_dimensions_move_independently
    """
    scenario, campaign = _listed_unit_with_campaign(
        window_end_at="2026-10-01T00:00:00Z"
    )
    _walk_the_ladder(scenario, campaign)
    _run_at(campaign["id"], FLOOR_RUN_AT)

    written_down = fetch_unit(scenario["unit"]["id"])
    assert written_down["current_price_minor"] == FLOOR_PRICE
    assert_unit_dimensions(written_down, "LISTED", "WRITTEN_DOWN")
    version_at_the_floor = written_down["version"]

    order = place_order(
        scenario["customer"], scenario["channel"], written_down, 0
    )
    assert order["status"] == "PLACED"
    # Gross 11700 sits in the first band, so 900bp of it, half up, is 1053.
    assert order["gross_price_minor"] == FLOOR_PRICE
    assert order["channel_fee_minor"] == 1053
    assert order["order_total_minor"] == 12753
    assert order["credit_applied_minor"] == 0
    assert order["cash_due_minor"] == 12753

    sold = fetch_unit(scenario["unit"]["id"])
    # The commercial dimension moved on the purchase.
    assert sold["lifecycle_state"] == "RESERVED"
    # The accounting dimension did not move back.
    assert sold["accounting_state"] == "WRITTEN_DOWN"
    assert sold["current_price_minor"] == FLOOR_PRICE
    assert sold["markdown_step_count"] == 4
    assert sold["version"] > version_at_the_floor

    # A reserved unit has left the eligible set altogether.
    after_sale = _run_at(campaign["id"], "2026-09-05T00:00:00Z")
    assert after_sale["evaluated_unit_count"] == 0
    assert after_sale["marked_down_unit_count"] == 0
    assert after_sale["skipped_at_floor_count"] == 0
    assert after_sale["total_markdown_minor"] == 0
    assert fetch_unit(scenario["unit"]["id"])["current_price_minor"] == FLOOR_PRICE


def test_a_unit_one_day_short_of_its_step_is_excluded_but_the_run_still_counts():
    """Six days of age is not seven, yet the campaign still opens and checkpoints.

    PRD §3.6: "A unit's `aged_days` is the whole number of complete days between
    `listed_at` and the logical clock — the elapsed seconds divided by eighty-six
    thousand four hundred, rounded down — and is 0 whenever `listed_at` is null."
    PRD §3.6: "On a working run the campaign selects its eligible units, and every
    one of the following must hold for a unit to qualify: its `lifecycle_state` is
    `LISTED`; its `listed_channel_id` equals the campaign's `channel_id`; its
    `product_category` equals the campaign's `product_category`; and its
    `aged_days` is at least the campaign's `cadence_days` multiplied by one more
    than its current `markdown_step_count`."
    PRD §3.6: "`RESERVED` and `SOLD` units are frozen at their sale price and
    never eligible; `RETURNED` units are not listed and never eligible; and a unit
    one day short of its next step boundary is excluded until the next run."
    PRD §3.6: "A run while the clock is at or after `window_start_at` and strictly
    before `window_end_at` is a working run: from `SCHEDULED` it moves the campaign
    to `ACTIVE`, and from `ACTIVE` it leaves it `ACTIVE`."
    PRD §3.6: "Every run that is not refused performs its bookkeeping
    unconditionally: `run_count` is incremented by one, `last_run_at` is stamped
    from the logical clock, and the campaign's version is incremented — that holds
    even when the eligible set turns out to be empty and even for a closing run."
    PRD §3.6: "A closing run and a working run with no eligible units both report
    zeros across all five counters while still reporting their `run_sequence_no`."

    Design: Corner/calculations/markdown_eligibility_excludes_a_unit_one_day_short_of_the_step
    """
    scenario, campaign = _listed_unit_with_campaign()
    unit = scenario["unit"]
    assert_instant(unit["listed_at"], "2026-08-01T00:00:00Z", "listed_at")
    assert unit["aged_days"] == 0
    version_when_listed = unit["version"]

    # 2026-08-07 is six complete days after the listing, and the unit needs
    # cadence_days * (0 + 1) = 7, so the eligible set is empty.
    short = _run_at(campaign["id"], "2026-08-07T00:00:00Z")
    assert short["run_sequence_no"] == 1
    assert short["evaluated_unit_count"] == 0
    assert short["marked_down_unit_count"] == 0
    assert short["skipped_at_floor_count"] == 0
    assert short["written_down_unit_count"] == 0
    assert short["total_markdown_minor"] == 0

    untouched = fetch_unit(unit["id"])
    assert untouched["aged_days"] == 6
    assert untouched["current_price_minor"] == 19500
    assert untouched["markdown_step_count"] == 0
    # An excluded unit is not a mutation, so it is not versioned either.
    assert untouched["version"] == version_when_listed

    opened = fetch_campaign(campaign["id"])
    assert opened["status"] == "ACTIVE"
    assert opened["run_count"] == 1
    assert_instant(opened["last_run_at"], "2026-08-07T00:00:00Z", "last_run_at")
    assert opened["version"] == campaign["version"] + 1

    # One day later the same unit clears the predicate exactly.
    stepped = _run_at(campaign["id"], "2026-08-08T00:00:00Z")
    assert stepped["run_sequence_no"] == 2
    assert stepped["evaluated_unit_count"] == 1
    assert stepped["marked_down_unit_count"] == 1
    # 19500 - floor(19500 * 8500 / 10000) = 19500 - 16575.
    assert stepped["total_markdown_minor"] == 2925

    marked = fetch_unit(unit["id"])
    assert marked["aged_days"] == 7
    assert marked["current_price_minor"] == 16575
    assert marked["markdown_step_count"] == 1
    # 16575 is still well above the 11700 floor.
    assert_unit_dimensions(marked, "LISTED", "CAPITALIZED")
    assert marked["version"] > version_when_listed


def test_a_run_that_recomputes_the_same_floor_price_skips_the_unit():
    """The fifth run changes nothing on the unit and everything on the campaign.

    PRD §3.6: "If that new price equals the unit's existing `current_price_minor`,
    the unit is skipped entirely: its `markdown_step_count`, its
    `current_price_minor` and its version are all left untouched, and it is
    counted as having been skipped at the floor."
    PRD §3.6: "Its response carries `run_sequence_no`, the campaign's `run_count`
    after this run's increment, so the first run reports 1; `evaluated_unit_count`,
    the number of eligible units the run examined; `marked_down_unit_count`, how
    many of those actually had their price changed; `skipped_at_floor_count`, how
    many were skipped because the computed new price equalled the price they
    already had; `written_down_unit_count`, how many were flipped from
    `CAPITALIZED` to `WRITTEN_DOWN` by landing on the floor; and
    `total_markdown_minor`, the summed reduction in minor units across every unit
    whose price actually moved."
    PRD §3.6: "Every run that is not refused performs its bookkeeping
    unconditionally: `run_count` is incremented by one, `last_run_at` is stamped
    from the logical clock, and the campaign's version is incremented — that holds
    even when the eligible set turns out to be empty and even for a closing run."
    PRD §3.6: "A run while the clock is at or after `window_start_at` and strictly
    before `window_end_at` is a working run: from `SCHEDULED` it moves the campaign
    to `ACTIVE`, and from `ACTIVE` it leaves it `ACTIVE`."

    Design: Corner/calculations/markdown_run_at_the_floor_skips_the_unit_but_still_advances_the_run
    """
    scenario, campaign = _listed_unit_with_campaign(
        window_end_at="2026-10-01T00:00:00Z"
    )
    _walk_the_ladder(scenario, campaign)

    fourth = _run_at(campaign["id"], FLOOR_RUN_AT)
    assert fourth["run_sequence_no"] == 4
    assert fourth["marked_down_unit_count"] == 1
    assert fourth["skipped_at_floor_count"] == 0
    assert fourth["written_down_unit_count"] == 1
    assert fourth["total_markdown_minor"] == 274

    at_floor = fetch_unit(scenario["unit"]["id"])
    assert at_floor["current_price_minor"] == FLOOR_PRICE
    assert at_floor["markdown_step_count"] == 4
    assert at_floor["accounting_state"] == "WRITTEN_DOWN"
    version_at_the_floor = at_floor["version"]

    # Age 35 clears cadence_days * (4 + 1), so the unit is eligible and examined,
    # but max(floor(11700 * 8500 / 10000), 11700) is the price it already carries.
    fifth = _run_at(campaign["id"], "2026-09-05T00:00:00Z")
    assert fifth["run_sequence_no"] == 5
    assert fifth["evaluated_unit_count"] == 1
    assert fifth["marked_down_unit_count"] == 0
    assert fifth["skipped_at_floor_count"] == 1
    assert fifth["written_down_unit_count"] == 0
    assert fifth["total_markdown_minor"] == 0

    skipped = fetch_unit(scenario["unit"]["id"])
    assert skipped["current_price_minor"] == FLOOR_PRICE
    assert skipped["markdown_step_count"] == 4
    assert skipped["accounting_state"] == "WRITTEN_DOWN"
    assert skipped["version"] == version_at_the_floor

    still_running = fetch_campaign(campaign["id"])
    assert still_running["run_count"] == 5
    assert still_running["status"] == "ACTIVE"
    assert_instant(
        still_running["last_run_at"], "2026-09-05T00:00:00Z", "last_run_at"
    )


def test_each_campaign_keeps_its_own_run_checkpoint_across_empty_runs():
    """Two campaigns, three runs, and no shared counter anywhere.

    PRD §3.6: "Every run that is not refused performs its bookkeeping
    unconditionally: `run_count` is incremented by one, `last_run_at` is stamped
    from the logical clock, and the campaign's version is incremented — that holds
    even when the eligible set turns out to be empty and even for a closing run."
    PRD §3.6: "Its response carries `run_sequence_no`, the campaign's `run_count`
    after this run's increment, so the first run reports 1; `evaluated_unit_count`,
    the number of eligible units the run examined; `marked_down_unit_count`, how
    many of those actually had their price changed; `skipped_at_floor_count`, how
    many were skipped because the computed new price equalled the price they
    already had; `written_down_unit_count`, how many were flipped from
    `CAPITALIZED` to `WRITTEN_DOWN` by landing on the floor; and
    `total_markdown_minor`, the summed reduction in minor units across every unit
    whose price actually moved."
    PRD §3.6: "A closing run and a working run with no eligible units both report
    zeros across all five counters while still reporting their `run_sequence_no`."
    PRD §3.6: "A **cadence run** is executed against a campaign at the current
    logical clock by a `MerchandisingManager` or a `ProgramAdmin`, and its
    behaviour depends entirely on where the clock sits relative to the campaign
    window."
    PRD §3.6: "Campaigns on a channel are listable by `ProgramAdmin` and
    `MerchandisingManager` with optional filters on `product_category` and
    `status`, plus `limit` and `offset`."

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_counters_are_per_campaign_and_survive_empty_runs
    """
    channel_a = create_channel(code="RESALE-A")
    channel_b = create_channel(
        code="RESALE-B",
        channel_type="OUTLET",
        allowed_assortment="BOTH",
        region_code="US-NY",
    )
    campaign_a = create_campaign(channel_a["id"])
    campaign_b = create_campaign(channel_b["id"])
    assert campaign_a["status"] == "SCHEDULED"
    assert campaign_a["run_count"] == 0
    assert campaign_b["run_count"] == 0

    # The clock reads the 2026-08-01 default, which is the window's own start
    # instant, so both campaigns are runnable and nothing is listed anywhere.
    first_a = run_campaign(campaign_a["id"])
    assert first_a["run_sequence_no"] == 1
    assert first_a["evaluated_unit_count"] == 0
    assert first_a["marked_down_unit_count"] == 0
    assert first_a["skipped_at_floor_count"] == 0
    assert first_a["written_down_unit_count"] == 0
    assert first_a["total_markdown_minor"] == 0

    # A different permitted role takes the second run; the checkpoint belongs to
    # the campaign, not to the caller.
    second_a = run_campaign(campaign_a["id"], ADMIN)
    assert second_a["run_sequence_no"] == 2
    assert second_a["evaluated_unit_count"] == 0

    # Campaign B has never been run, so it is still on its own first checkpoint.
    first_b = run_campaign(campaign_b["id"])
    assert first_b["run_sequence_no"] == 1
    assert first_b["evaluated_unit_count"] == 0

    after_a = fetch_campaign(campaign_a["id"])
    assert after_a["status"] == "ACTIVE"
    assert after_a["run_count"] == 2
    assert_instant(after_a["last_run_at"], "2026-08-01T00:00:00Z", "last_run_at")
    assert after_a["version"] == campaign_a["version"] + 2

    after_b = fetch_campaign(campaign_b["id"])
    assert after_b["status"] == "ACTIVE"
    assert after_b["run_count"] == 1
    assert_instant(after_b["last_run_at"], "2026-08-01T00:00:00Z", "last_run_at")
    assert after_b["version"] == campaign_b["version"] + 1

    rows, meta = validate_paginated(
        api_client.list_channel_markdown_campaigns(
            channel_b["id"], MERCH, {"product_category": "OUTERWEAR"}
        )
    )
    assert_pagination_meta(meta, 1)
    assert rows[0]["id"] == campaign_b["id"]
    assert rows[0]["channel_id"] == channel_b["id"]
