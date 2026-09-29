"""Declaring markdown campaigns: half-open windows, the per-category rule and
the channel-wide capacity cap.

Every campaign here is declared against a channel that carries no listed stock,
so the arithmetic of a cadence run stays out of the way and the declaration
rules are the only thing under test.
"""

from test_helpers import (
    ADMIN,
    MERCH,
    api_client,
    assert_channel,
    assert_instant,
    assert_markdown_campaign,
    assert_null,
    assert_pagination_meta,
    create_campaign,
    create_channel,
    create_markdown_campaign_payload,
    fetch_campaign,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _attempt(channel_id, product_category, window_start_at, window_end_at):
    """A declaration request whose refusal is the thing being observed."""
    return api_client.create_markdown_campaign(
        create_markdown_campaign_payload(
            channel_id,
            product_category=product_category,
            window_start_at=window_start_at,
            window_end_at=window_end_at,
            cadence_days=7,
            step_bp=1000,
            floor_pct_bp=7000,
        ),
        MERCH,
    )


def _declare(channel_id, product_category, window_start_at, window_end_at):
    """The same request as ``_attempt``, taken through the success path."""
    return create_campaign(
        channel_id,
        product_category=product_category,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        cadence_days=7,
        step_bp=1000,
        floor_pct_bp=7000,
    )


def _campaigns_of(channel_id, params=None):
    return validate_paginated(
        api_client.list_channel_markdown_campaigns(channel_id, MERCH, params)
    )


def _two_scheduled_campaigns():
    """One channel already carrying a FOOTWEAR and an OUTERWEAR campaign.

    Their windows are chosen so that [2026-08-15, 2026-08-25) overlaps both of
    them, which puts the channel at its aggregate capacity for that span while
    only the FOOTWEAR campaign is a per-category peer.
    """
    channel = create_channel()
    footwear = _declare(
        channel["id"], "FOOTWEAR", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    outerwear = _declare(
        channel["id"], "OUTERWEAR", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z"
    )
    return channel, footwear, outerwear


def test_the_category_overlap_answers_before_the_channel_capacity_cap():
    """One request violates both rules and must name only the temporal one.

    PRD §3.6: "The window must not overlap, on the half-open interval, another
    `SCHEDULED` or `ACTIVE` campaign covering the same (`channel_id`,
    `product_category`) pair — that collision is `ERR_CAMPAIGN_CATEGORY_OVERLAP`."
    PRD §3.6: "Separately and more broadly, at most two non-terminal campaigns
    may overlap the requested window on the same channel counting across *all*
    product categories; a third is refused with `ERR_CAMPAIGN_CAPACITY_EXCEEDED`."
    PRD §2.11: "**Temporal conflicts** — bay window conflict, reported as
    `ERR_BAY_WINDOW_CONFLICT` (409), on refurbishment order creation; campaign
    overlap on the same channel and category, reported as
    `ERR_CAMPAIGN_CATEGORY_OVERLAP` (409), and then channel-wide campaign
    capacity, reported as `ERR_CAMPAIGN_CAPACITY_EXCEEDED` (409), both on
    markdown campaign creation; then the intake window, reported as
    `ERR_INTAKE_WINDOW_EXPIRED` (409), on trade-in receipt; then the after-sale
    windows, reported as `ERR_RETURN_WINDOW_CLOSED` and `ERR_WARRANTY_EXPIRED`
    (409), on a return request."

    Design: Difficulty/priority_pair_validation_conflict/campaign_category_overlap_outranks_channel_capacity_exhaustion
    """
    channel, footwear, outerwear = _two_scheduled_campaigns()
    # A SCHEDULED campaign already counts for both rules.
    assert footwear["status"] == "SCHEDULED"
    assert outerwear["status"] == "SCHEDULED"

    # FOOTWEAR over [08-15, 08-20) overlaps its own category peer *and* would be
    # the third campaign overlapping that span on this channel.
    validate_error(
        _attempt(
            channel["id"], "FOOTWEAR", "2026-08-15T00:00:00Z", "2026-08-20T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CATEGORY_OVERLAP",
        409,
    )

    # BAG has no category peer on this channel, so the same overlapping span
    # leaves only the aggregate rule able to fire — the lower-priority rule is
    # genuinely live rather than shadowed dead code.
    validate_error(
        _attempt(
            channel["id"], "BAG", "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CAPACITY_EXCEEDED",
        409,
    )


def test_a_refused_declaration_leaves_no_row_and_the_legal_one_is_scheduled():
    """Two refusals, one acceptance, and a listing that counts only the survivors.

    PRD §3.6: "A campaign is created in `SCHEDULED` with `run_count` at 0 and
    `last_run_at` null."
    PRD §3.6: "Campaigns on a channel are listable by `ProgramAdmin` and
    `MerchandisingManager` with optional filters on `product_category` and
    `status`, plus `limit` and `offset`."
    PRD §2.4: "A **markdown campaign window** and a **diversion report period**,
    delimited by `window_start_at`/`window_end_at` and
    `period_start_at`/`period_end_at` respectively, are *half-open*: the start
    instant is inside the window and the end instant is outside it."
    PRD §2.6: "Most resources — customers, condition-tier policies,
    brand-currency policies, store locations, refurbishment bays, channels,
    trade-ins, brand-currency grants, resale units, refurbishment orders,
    markdown campaigns, resale orders and diversion reports — additionally carry
    `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the
    row, and `version`, an integer that is initialized to 1 when the row is
    created and incremented by exactly one on every mutation."

    Design: Difficulty/priority_pair_validation_conflict/campaign_category_overlap_outranks_channel_capacity_exhaustion
    """
    channel, footwear, outerwear = _two_scheduled_campaigns()

    validate_error(
        _attempt(
            channel["id"], "FOOTWEAR", "2026-08-15T00:00:00Z", "2026-08-20T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CATEGORY_OVERLAP",
        409,
    )
    validate_error(
        _attempt(
            channel["id"], "BAG", "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CAPACITY_EXCEEDED",
        409,
    )

    # FOOTWEAR over [09-01, 10-01) begins exactly where the incumbent FOOTWEAR
    # window ends, which is outside that window, so neither rule is touched:
    # only the OUTERWEAR campaign overlaps and one is below the cap of two.
    third = _declare(
        channel["id"], "FOOTWEAR", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    assert_markdown_campaign(third)
    assert third["status"] == "SCHEDULED"
    assert third["run_count"] == 0
    assert_null(third["last_run_at"], "last_run_at")
    assert third["version"] == 1
    assert third["channel_id"] == channel["id"]
    assert third["product_category"] == "FOOTWEAR"
    assert_instant(third["window_start_at"], "2026-09-01T00:00:00Z", "window_start_at")
    assert_instant(third["window_end_at"], "2026-10-01T00:00:00Z", "window_end_at")

    # Exactly the three accepted rows exist; neither refusal left a trace.
    rows, meta = _campaigns_of(channel["id"])
    assert_pagination_meta(meta, 3)
    assert {row["id"] for row in rows} == {
        footwear["id"],
        outerwear["id"],
        third["id"],
    }

    footwear_rows, footwear_meta = _campaigns_of(
        channel["id"], {"product_category": "FOOTWEAR"}
    )
    assert_pagination_meta(footwear_meta, 2)
    assert {row["id"] for row in footwear_rows} == {footwear["id"], third["id"]}

    bag_rows, bag_meta = _campaigns_of(channel["id"], {"product_category": "BAG"})
    assert_pagination_meta(bag_meta, 0)
    assert bag_rows == []

    scheduled_rows, scheduled_meta = _campaigns_of(
        channel["id"], {"status": "SCHEDULED"}
    )
    assert_pagination_meta(scheduled_meta, 3)
    assert len(scheduled_rows) == 3


def _abutting_footwear_series():
    """Three back-to-back FOOTWEAR campaigns on one channel.

    [08-01, 09-01), [09-01, 10-01) and [10-01, 11-01) each begin on the instant
    the previous one ends, which the half-open convention places outside that
    previous window.
    """
    channel = create_channel()
    first = _declare(
        channel["id"], "FOOTWEAR", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    second = _declare(
        channel["id"], "FOOTWEAR", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    third = _declare(
        channel["id"], "FOOTWEAR", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
    )
    return channel, [first, second, third]


def test_campaigns_may_abut_at_an_instant_but_not_overlap_by_a_day():
    """Sharing the exclusive end instant is legal; one day of genuine overlap is not.

    PRD §2.4: "A **markdown campaign window** and a **diversion report period**,
    delimited by `window_start_at`/`window_end_at` and
    `period_start_at`/`period_end_at` respectively, are *half-open*: the start
    instant is inside the window and the end instant is outside it."
    PRD §3.6: "The window must not overlap, on the half-open interval, another
    `SCHEDULED` or `ACTIVE` campaign covering the same (`channel_id`,
    `product_category`) pair — that collision is `ERR_CAMPAIGN_CATEGORY_OVERLAP`."
    PRD §3.6: "A campaign is created in `SCHEDULED` with `run_count` at 0 and
    `last_run_at` null."

    Design: Difficulty/resource_temporal_overlap/markdown_campaign_window_uses_half_open_interval_with_channel_capacity_cap
    """
    channel = create_channel()
    incumbent = _declare(
        channel["id"], "FOOTWEAR", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert incumbent["status"] == "SCHEDULED"

    # [08-31, 10-01) shares the whole of 2026-08-31 with the incumbent, which is
    # a real intersection of the two half-open windows.
    validate_error(
        _attempt(
            channel["id"], "FOOTWEAR", "2026-08-31T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CATEGORY_OVERLAP",
        409,
    )

    # Starting exactly on the incumbent's excluded end instant intersects nothing.
    successor = _declare(
        channel["id"], "FOOTWEAR", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    assert_markdown_campaign(successor)
    assert successor["status"] == "SCHEDULED"
    assert successor["run_count"] == 0
    assert_null(successor["last_run_at"], "last_run_at")
    assert_instant(
        successor["window_start_at"], "2026-09-01T00:00:00Z", "window_start_at"
    )
    assert successor["id"] != incumbent["id"]

    # And the same abutment works again one window further along.
    trailer = _declare(
        channel["id"], "FOOTWEAR", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
    )
    assert trailer["status"] == "SCHEDULED"
    assert_instant(trailer["window_start_at"], "2026-10-01T00:00:00Z", "window_start_at")
    assert trailer["id"] not in (incumbent["id"], successor["id"])

    rows, meta = _campaigns_of(channel["id"])
    assert_pagination_meta(meta, 3)
    assert len(rows) == 3


def test_the_channel_wide_cap_counts_two_overlaps_across_all_categories():
    """A span that overlaps two incumbents is refused; one that overlaps one is not.

    PRD §3.6: "Separately and more broadly, at most two non-terminal campaigns
    may overlap the requested window on the same channel counting across *all*
    product categories; a third is refused with `ERR_CAMPAIGN_CAPACITY_EXCEEDED`."
    PRD §3.6: "The window must not overlap, on the half-open interval, another
    `SCHEDULED` or `ACTIVE` campaign covering the same (`channel_id`,
    `product_category`) pair — that collision is `ERR_CAMPAIGN_CATEGORY_OVERLAP`."
    PRD §3.6: "Campaigns on a channel are listable by `ProgramAdmin` and
    `MerchandisingManager` with optional filters on `product_category` and
    `status`, plus `limit` and `offset`."

    Design: Difficulty/resource_temporal_overlap/markdown_campaign_window_uses_half_open_interval_with_channel_capacity_cap
    """
    channel, footwear_series = _abutting_footwear_series()
    assert [row["status"] for row in footwear_series] == ["SCHEDULED"] * 3

    # OUTERWEAR over [08-15, 09-15) has no category peer at all, yet it straddles
    # the first two FOOTWEAR windows and would be the third overlapping campaign.
    validate_error(
        _attempt(
            channel["id"], "OUTERWEAR", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z"
        ),
        "ERR_CAMPAIGN_CAPACITY_EXCEEDED",
        409,
    )

    # Pulled back inside the first window it overlaps exactly one incumbent, so
    # the channel holds two overlapping campaigns, which is the cap and not past it.
    admitted = _declare(
        channel["id"], "OUTERWEAR", "2026-08-15T00:00:00Z", "2026-08-25T00:00:00Z"
    )
    assert_markdown_campaign(admitted)
    assert admitted["status"] == "SCHEDULED"
    assert admitted["product_category"] == "OUTERWEAR"

    rows, meta = _campaigns_of(channel["id"])
    assert_pagination_meta(meta, 4)
    assert admitted["id"] in {row["id"] for row in rows}

    outerwear_rows, outerwear_meta = _campaigns_of(
        channel["id"], {"product_category": "OUTERWEAR"}
    )
    assert_pagination_meta(outerwear_meta, 1)
    assert outerwear_rows[0]["id"] == admitted["id"]


def test_a_channel_round_trips_and_its_campaign_listing_is_path_scoped():
    """Create, read, PATCH — and a sub-resource that answers for one channel only.

    PRD §3.1: "A channel is registered with a `code` unique across channels, a
    `channel_type` of `FULL_PRICE_DTC`, `RESALE_MARKETPLACE` or `OUTLET`, an
    `allowed_assortment` of `NEW_ONLY`, `RESALE_ONLY` or `BOTH`, a
    `max_resale_price_ratio_bp` between 1 and 10000 inclusive, and a non-empty
    `region_code`."
    PRD §3.1: "A channel's `status` begins `ACTIVE` and may be paused; a `PAUSED`
    channel accepts neither new listings nor new resale orders, and both refusals
    carry `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §2.6: "Most resources — customers, condition-tier policies,
    brand-currency policies, store locations, refurbishment bays, channels,
    trade-ins, brand-currency grants, resale units, refurbishment orders,
    markdown campaigns, resale orders and diversion reports — additionally carry
    `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the
    row, and `version`, an integer that is initialized to 1 when the row is
    created and incremented by exactly one on every mutation."
    PRD §3.6: "Campaigns on a channel are listable by `ProgramAdmin` and
    `MerchandisingManager` with optional filters on `product_category` and
    `status`, plus `limit` and `offset`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, alongside the request
    identifier and timestamp."

    Design: Corner/endpoints/channel_crud_and_campaign_subresource_routing
    """
    marketplace = create_channel()
    outlet = create_channel(
        code="OUTLET-1",
        channel_type="OUTLET",
        allowed_assortment="BOTH",
        max_resale_price_ratio_bp=5000,
    )
    assert marketplace["status"] == "ACTIVE"
    assert marketplace["version"] == 1

    read_back = validate_success(api_client.get_channel(marketplace["id"], MERCH))
    assert_channel(read_back)
    assert read_back["id"] == marketplace["id"]
    assert read_back["code"] == "RESALE-MP"
    assert read_back["channel_type"] == "RESALE_MARKETPLACE"
    assert read_back["allowed_assortment"] == "RESALE_ONLY"
    assert read_back["max_resale_price_ratio_bp"] == 7000
    assert read_back["region_code"] == "US-CA"
    assert read_back["status"] == "ACTIVE"
    # A read is not a mutation, so the counter has not moved.
    assert read_back["version"] == marketplace["version"]

    before_rows, before_meta = _campaigns_of(marketplace["id"])
    assert before_rows == []
    assert_pagination_meta(before_meta, 0, has_more=False)

    campaign = create_campaign(marketplace["id"])
    assert campaign["product_category"] == "OUTERWEAR"

    after_rows, after_meta = _campaigns_of(marketplace["id"])
    assert_pagination_meta(after_meta, 1)
    assert after_rows[0]["id"] == campaign["id"]
    assert after_rows[0]["product_category"] == "OUTERWEAR"
    assert after_rows[0]["channel_id"] == marketplace["id"]

    # The sub-resource is scoped by the channel in the path, not global.
    other_rows, other_meta = _campaigns_of(outlet["id"])
    assert other_rows == []
    assert_pagination_meta(other_meta, 0, has_more=False)

    paused = validate_success(
        api_client.patch_channel(marketplace["id"], {"status": "PAUSED"}, ADMIN)
    )
    assert_channel(paused)
    assert paused["status"] == "PAUSED"
    assert paused["version"] == marketplace["version"] + 1
    # The PATCH named only the status, so the commercial terms are untouched.
    assert paused["code"] == "RESALE-MP"
    assert paused["channel_type"] == "RESALE_MARKETPLACE"
    assert paused["allowed_assortment"] == "RESALE_ONLY"
    assert paused["max_resale_price_ratio_bp"] == 7000


def test_a_half_day_window_is_refused_and_only_the_boundary_run_is_legal():
    """A 14.5-day span, a run before the window, the closing run, then the refusal.

    PRD §2.4: "In every one of those four cases the end must fall strictly after
    the start, and for markdown campaigns and diversion reports the span must
    additionally be expressible as a whole number of days; a window that violates
    either shape is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 422)."
    PRD §3.6: "A run requested on a campaign that is already `CLOSED`, or at a
    logical clock strictly before `window_start_at`, is refused with
    `ERR_CAMPAIGN_NOT_RUNNABLE`."
    PRD §3.6: "A run at or after `window_end_at` is a closing run: from `ACTIVE`
    or from `SCHEDULED` — the latter being a campaign that expired without ever
    having been run — it moves the campaign to the terminal `CLOSED` and **steps
    no price whatsoever**."
    PRD §3.6: "Every run that is not refused performs its bookkeeping
    unconditionally: `run_count` is incremented by one, `last_run_at` is stamped
    from the logical clock, and the campaign's version is incremented — that
    holds even when the eligible set turns out to be empty and even for a closing
    run."
    PRD §3.6: "A closing run and a working run with no eligible units both report
    zeros across all five counters while still reporting their
    `run_sequence_no`."

    Design: Corner/errors/campaign_window_and_runnability_errors_are_triggerable
    """
    channel = create_channel()

    # [2026-09-01T00:00:00Z, 2026-09-15T12:00:00Z) ends strictly after it starts
    # but spans fourteen and a half days.
    validate_error(
        _attempt(
            channel["id"], "OUTERWEAR", "2026-09-01T00:00:00Z", "2026-09-15T12:00:00Z"
        ),
        "ERR_INVALID_TIME_WINDOW",
        422,
    )

    campaign = _declare(
        channel["id"], "OUTERWEAR", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"
    )
    assert campaign["status"] == "SCHEDULED"
    assert campaign["run_count"] == 0
    assert_null(campaign["last_run_at"], "last_run_at")

    # The clock still reads the 2026-08-01 default, strictly before the window.
    validate_error(
        api_client.run_markdown_cadence(campaign["id"], MERCH),
        "ERR_CAMPAIGN_NOT_RUNNABLE",
        409,
    )
    unrun = fetch_campaign(campaign["id"])
    assert unrun["status"] == "SCHEDULED"
    assert unrun["run_count"] == 0
    assert_null(unrun["last_run_at"], "last_run_at")
    assert unrun["version"] == campaign["version"]

    set_clock("2026-09-15T00:00:00Z")
    closing = validate_success(
        api_client.run_markdown_cadence(campaign["id"], MERCH)
    )
    assert closing["run_sequence_no"] == 1
    assert closing["evaluated_unit_count"] == 0
    assert closing["marked_down_unit_count"] == 0
    assert closing["skipped_at_floor_count"] == 0
    assert closing["written_down_unit_count"] == 0
    assert closing["total_markdown_minor"] == 0

    closed = fetch_campaign(campaign["id"])
    assert closed["status"] == "CLOSED"
    assert closed["run_count"] == 1
    assert_instant(closed["last_run_at"], "2026-09-15T00:00:00Z", "last_run_at")
    assert closed["version"] == campaign["version"] + 1

    # The same instant that closed the campaign now makes it unrunnable.
    validate_error(
        api_client.run_markdown_cadence(campaign["id"], MERCH),
        "ERR_CAMPAIGN_NOT_RUNNABLE",
        409,
    )
    final = fetch_campaign(campaign["id"])
    assert final["run_count"] == 1
    assert_instant(final["last_run_at"], "2026-09-15T00:00:00Z", "last_run_at")
    assert final["version"] == closed["version"]
