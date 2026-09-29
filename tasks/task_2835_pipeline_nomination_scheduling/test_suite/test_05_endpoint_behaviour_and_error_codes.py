"""Endpoint behaviour and error codes for the pipeline nomination service.

Covers the observable behaviour of the collection filters, the proration-policy
filing, schedule publication, the linefill adjustment, and the refusals a caller
hears when it names a resource that does not exist or acts on a nomination from
the wrong state.
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN,
    OPERATOR,
    PUBLISHER_USER_ID,
    SCHEDULER,
    TEST_DEFAULTS,
    UNKNOWN_BATCH_TICKET_ID,
    UNKNOWN_MAINTENANCE_EVENT_ID,
    UNKNOWN_NOMINATION_ID,
    UNKNOWN_SETTLEMENT_ID,
    ApiErrorId,
    assert_millisecond_timestamp,
    create_inventory_adjustment_payload,
    inject_payload,
    linefill_adjustment_payload,
    make_scheduler_headers,
    make_shipper_headers,
    nomination_key,
    proration_policy_payload,
    refresh_cycle,
    resubmit_nomination_payload,
    set_clock,
    setup_cycle_with_nomination,
    setup_multi_shipper_cycle,
    setup_network,
    setup_prorated_cycle,
    setup_scheduled_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant the service rendered or the PRD names."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _instant_equals(actual: str, expected: str) -> bool:
    """True when two rendered instants denote the same moment in UTC."""
    return _instant(actual) == _instant(expected)


# --------------------------------------------------------------------------
# Collection filters over the nomination book
# --------------------------------------------------------------------------


def test_nomination_listing_narrows_to_one_shipper(api):
    """PRD 2.3: "Each collection also accepts a set of equality filters, which
    narrow the result set before sorting and paging."
    PRD 2.3: "Nominations may be filtered by `cycle_id`, `shipper_id`, `grade_id`,
    `origin_terminal_id`, `destination_terminal_id`, `supersedes_nomination_id`,
    `pinned_tariff_id` or `status`."
    PRD 2.3: "`total_count` (the number of rows matching the filters before the
    page window is applied)"
    PRD 2.3: "nominations sort by `created_at` ascending"
    PRD 2.6: "A successful submission increments the cycle's `version` by one, so
    a client that submits twice must re-read the cycle between attempts."

    Design: Corner/endpoints/nomination_listing_filters_by_shipper_id
    """
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000), ("BRAVO", "ULSD", 20000)]
    )
    cycle = ctx["cycle"]
    alpha = ctx["shippers"]["ALPHA"]
    nomination_alpha = ctx["nominations"][nomination_key("ALPHA")]
    nomination_bravo = ctx["nominations"][nomination_key("BRAVO")]

    filtered, filtered_meta = validate_paginated(
        api.list_nominations(
            SCHEDULER,
            params={"cycle_id": cycle["id"], "shipper_id": alpha["id"], "limit": 10},
        )
    )
    assert filtered_meta["total_count"] == 1, (
        "the shipper_id filter narrows the cycle to ALPHA's single nomination, got "
        f"total_count {filtered_meta['total_count']}"
    )
    assert len(filtered) == 1, f"expected one nomination row, got {len(filtered)}"
    assert filtered[0]["id"] == nomination_alpha["id"], (
        "the filtered listing must return ALPHA's nomination"
    )

    unfiltered, unfiltered_meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"], "limit": 10})
    )
    assert unfiltered_meta["total_count"] == 2, (
        "the unfiltered cycle listing must count both nominations, got "
        f"{unfiltered_meta['total_count']}"
    )
    assert [row["id"] for row in unfiltered] == [
        nomination_alpha["id"],
        nomination_bravo["id"],
    ], "nominations are returned sorted by created_at ascending"

    cycle = refresh_cycle(ctx)
    assert cycle["nominated_total_bbl"] == 50000, (
        "filtering a listing changes no aggregate: the cycle still carries the two "
        f"nominated volumes, got {cycle['nominated_total_bbl']}"
    )
    assert cycle["version"] == 3, (
        "each of the two accepted submissions increments the cycle's version by one "
        f"from 1, so the cycle must be at version 3, got {cycle['version']}"
    )


# --------------------------------------------------------------------------
# Filing a new proration methodology
# --------------------------------------------------------------------------


def test_proration_policy_filing_leaves_an_already_prorated_cycle_alone(api):
    """PRD 3.1: "A `TariffAdministrator` may replace a segment's `proration_policy`
    at any time; the new value governs every subsequent proration run and never
    rewrites the allocations of a cycle that has already been prorated."
    PRD 3.5: "Every proration run closes by recomputing the cycle's
    `nominated_total_bbl` first, then `allocated_total_bbl` as the sum of the
    allocations, then `unallocated_capacity_bbl` as `effective_capacity_bbl` less
    `allocated_total_bbl`, and finally `proration_factor` as `allocated_total_bbl`
    divided by `nominated_total_bbl` rounded half up to six decimal places — or
    exactly 1.000000 when `nominated_total_bbl` is zero."

    Design: Corner/endpoints/proration_policy_change_does_not_retroactively_reallocate
    """
    ctx = setup_prorated_cycle(nominated_bbl=30000)
    segment = ctx["segment"]
    nomination = ctx["nominations"][nomination_key("ALPHA")]

    segment_after = validate_success(
        api.change_proration_policy(
            segment["id"], proration_policy_payload("VOLUME_WEIGHTED"), ADMIN
        )
    )
    assert segment_after["proration_policy"] == "VOLUME_WEIGHTED", (
        "the filing must replace the segment's methodology, got "
        f"{segment_after['proration_policy']}"
    )

    nomination_after = validate_success(
        api.get_nomination(nomination["id"], SCHEDULER)
    )
    assert nomination_after["status"] == "PRORATED", (
        f"the already-prorated nomination stays PRORATED, got {nomination_after['status']}"
    )
    assert nomination_after["allocated_bbl"] == 30000, (
        "the filing never rewrites an allocation already awarded, expected 30000 bbl, "
        f"got {nomination_after['allocated_bbl']}"
    )

    cycle_after = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle_after["status"] == "PRORATED", (
        f"the cycle keeps its PRORATED status, got {cycle_after['status']}"
    )
    assert cycle_after["allocated_total_bbl"] == 30000, (
        f"allocated_total_bbl stays at 30000, got {cycle_after['allocated_total_bbl']}"
    )
    assert cycle_after["unallocated_capacity_bbl"] == 70000, (
        "the 100000 bbl of effective capacity less the 30000 bbl awarded stays "
        f"unallocated, got {cycle_after['unallocated_capacity_bbl']}"
    )
    assert float(cycle_after["proration_factor"]) == 1.0, (
        "the whole nominated volume was awarded, so the factor stays 1.000000, got "
        f"{cycle_after['proration_factor']}"
    )


# --------------------------------------------------------------------------
# Publishing the schedule
# --------------------------------------------------------------------------


def test_publish_schedule_stamps_the_logical_clock_and_the_publishing_operator(api):
    """PRD 3.6: "Publication drives the cycle `SCHEDULED → PUBLISHED`, increments
    the cycle's `schedule_version` by one, stamps `schedule_published_at` with the
    logical clock and records the publishing operator's `X-User-ID` in
    `schedule_published_by_user_id`, and moves every nomination of the cycle still
    in `PRORATED` to `SCHEDULED`."
    PRD 3.6: "Building a schedule does not itself advance `schedule_version`; only
    publication does."
    PRD 2.4: "Every instant the service stores or returns uses that same rendering,
    and every instant a client supplies must parse as ISO 8601 UTC or the request
    is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/publish_schedule_stamps_logical_clock_and_publisher_identity
    """
    ctx = setup_scheduled_cycle(nominated_bbl=30000)
    cycle_before = refresh_cycle(ctx)
    assert cycle_before["schedule_version"] == 0, (
        "building the schedule does not advance schedule_version, got "
        f"{cycle_before['schedule_version']}"
    )

    set_clock("2026-08-15T00:00:00Z", SCHEDULER)

    published = validate_success(
        api.publish_schedule(
            ctx["cycle"]["id"], make_scheduler_headers(PUBLISHER_USER_ID)
        )
    )
    assert published["status"] == "PUBLISHED", (
        f"publication drives the cycle to PUBLISHED, got {published['status']}"
    )
    assert published["schedule_version"] == 1, (
        "publication increments schedule_version from 0 to 1, got "
        f"{published['schedule_version']}"
    )
    assert_millisecond_timestamp(
        published["schedule_published_at"], "schedule_published_at"
    )
    assert _instant_equals(
        published["schedule_published_at"], "2026-08-15T00:00:00.000Z"
    ), (
        "schedule_published_at is stamped from the logical clock, expected "
        f"2026-08-15T00:00:00.000Z, got {published['schedule_published_at']}"
    )
    assert published["schedule_published_by_user_id"] == PUBLISHER_USER_ID, (
        "the publishing operator's identifier is recorded on the cycle, expected "
        f"{PUBLISHER_USER_ID}, got {published['schedule_published_by_user_id']}"
    )

    nomination = validate_success(
        api.get_nomination(ctx["nominations"][nomination_key("ALPHA")]["id"], SCHEDULER)
    )
    assert nomination["status"] == "SCHEDULED", (
        "every nomination still PRORATED is carried to SCHEDULED by the same call, got "
        f"{nomination['status']}"
    )
    assert nomination["allocated_bbl"] == 30000, (
        f"publication does not touch the allocation, got {nomination['allocated_bbl']}"
    )


# --------------------------------------------------------------------------
# Walking the batch sequence through the predecessor filter
# --------------------------------------------------------------------------


def test_batch_ticket_predecessor_filter_returns_the_next_batch_in_sequence(api):
    """PRD 2.3: "Batch tickets may be filtered by `cycle_id`, `nomination_id`,
    `predecessor_batch_id`, `movement_status` or `quality_status`."
    PRD 3.6: "Walking that order assigns `sequence_position` starting at 1, each
    ticket's `predecessor_batch_id` names the ticket at the position immediately
    before it, and the ticket at position 1 has a null `predecessor_batch_id`."
    PRD 3.6: "Each ticket's `injection_window_start` is the cycle's `ship_start_at`
    advanced by one 24-hour slot for every position ahead of it — that is, by
    `sequence_position` minus one whole days — and its `injection_window_end` is 24
    hours after its own start."

    Design: Corner/endpoints/batch_ticket_predecessor_filter_returns_the_next_batch_in_sequence
    """
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "JET", 20000), ("BRAVO", "ULSD", 20000), ("CHARLIE", "CBOB", 20000)],
        grades=("JET", "ULSD", "CBOB"),
        build=True,
        segment_overrides={"transmix_reserve_bbl": 2000},
    )
    tickets = ctx["tickets"]
    assert len(tickets) == 3, (
        f"the build must lift one ticket per prorated nomination, got {len(tickets)}"
    )
    first, second, third = tickets[0], tickets[1], tickets[2]

    rows, meta = validate_paginated(
        api.list_batch_tickets(
            SCHEDULER, params={"predecessor_batch_id": first["id"], "limit": 10}
        )
    )
    assert meta["total_count"] == 1, (
        "exactly one ticket names the position-1 ticket as its predecessor, got "
        f"total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == second["id"], (
        "the predecessor filter walks one hop to the position-2 ticket"
    )
    assert rows[0]["sequence_position"] == 2, (
        f"the ticket behind position 1 sits at position 2, got {rows[0]['sequence_position']}"
    )

    assert _instant_equals(
        second["injection_window_start"], "2026-09-02T00:00:00.000Z"
    ), (
        "position 2 opens one 24-hour slot after the cycle's ship_start_at, got "
        f"{second['injection_window_start']}"
    )
    assert _instant_equals(second["injection_window_end"], "2026-09-03T00:00:00.000Z"), (
        "the injection window closes 24 hours after its own start, got "
        f"{second['injection_window_end']}"
    )
    assert _instant_equals(
        first["injection_window_start"], TEST_DEFAULTS["SHIP_START_AT"]
    ), (
        "position 1 opens exactly at the cycle's ship_start_at, got "
        f"{first['injection_window_start']}"
    )
    assert first["predecessor_batch_id"] is None, (
        "the ticket at position 1 has no predecessor, got "
        f"{first['predecessor_batch_id']}"
    )
    assert third["sequence_position"] == 3, (
        f"the third ticket sits at position 3, got {third['sequence_position']}"
    )
    assert _instant_equals(third["injection_window_start"], "2026-09-03T00:00:00.000Z"), (
        "position 3 opens two 24-hour slots after ship_start_at, got "
        f"{third['injection_window_start']}"
    )


# --------------------------------------------------------------------------
# Linefill funding versus tank inventory
# --------------------------------------------------------------------------


def test_linefill_adjustment_credits_the_segment_not_the_tank(api):
    """PRD 3.1: "An `adjustment_kind` of `LINEFILL` behaves differently: it requires
    an accompanying `segment_id`, it adds `adjustment_bbl` to that segment's
    `linefill_bbl`, and it leaves the terminal's `inventory_bbl` untouched."
    PRD 3.1: "An `adjustment_kind` of `INVENTORY` adds `adjustment_bbl` to the
    terminal's `inventory_bbl`, and a negative `adjustment_bbl` therefore withdraws
    volume."
    PRD 3.1: "Either way the terminal's `version` increments by one, and the
    response is the updated terminal."
    PRD 3.1: "A newly registered terminal starts with `inventory_bbl` of 0 and
    `version` of 1."

    Design: Corner/endpoints/linefill_adjustment_credits_the_segment_not_terminal_inventory
    """
    ctx = setup_network(linefill_bbl=0)
    origin = ctx["origin"]
    segment = ctx["segment"]
    assert origin["inventory_bbl"] == 0, (
        f"a newly registered terminal opens with an empty tank, got {origin['inventory_bbl']}"
    )
    assert origin["version"] == 1, (
        f"a newly registered terminal opens at version 1, got {origin['version']}"
    )

    after_linefill = validate_success(
        api.create_inventory_adjustment(
            origin["id"],
            linefill_adjustment_payload(
                origin["version"],
                segment["id"],
                adjustment_bbl=20000,
                reason="initial linefill of the mainline",
            ),
            OPERATOR,
        )
    )
    assert after_linefill["inventory_bbl"] == 0, (
        "a LINEFILL adjustment leaves the terminal's own tank untouched, got "
        f"{after_linefill['inventory_bbl']}"
    )
    assert after_linefill["version"] == 2, (
        f"the terminal's version increments to 2 either way, got {after_linefill['version']}"
    )

    segment_after = validate_success(api.get_segment(segment["id"], SCHEDULER))
    assert segment_after["linefill_bbl"] == 20000, (
        "the 20000 barrels are booked to the named segment's linefill, got "
        f"{segment_after['linefill_bbl']}"
    )

    after_inventory = validate_success(
        api.create_inventory_adjustment(
            origin["id"],
            create_inventory_adjustment_payload(
                after_linefill["version"],
                adjustment_kind="INVENTORY",
                adjustment_bbl=100000,
                reason="refinery receipt",
                segment_id=segment["id"],
            ),
            OPERATOR,
        )
    )
    assert after_inventory["inventory_bbl"] == 100000, (
        "an INVENTORY adjustment adds to the terminal's own tank, got "
        f"{after_inventory['inventory_bbl']}"
    )
    assert after_inventory["version"] == 3, (
        f"the second adjustment carries the terminal to version 3, got {after_inventory['version']}"
    )

    segment_final = validate_success(api.get_segment(segment["id"], SCHEDULER))
    assert segment_final["linefill_bbl"] == 20000, (
        "the INVENTORY adjustment leaves the segment's linefill alone, got "
        f"{segment_final['linefill_bbl']}"
    )
    assert segment_final["operational_status"] == "OPERATIONAL", (
        "no maintenance has been notified, so the segment is still OPERATIONAL, got "
        f"{segment_final['operational_status']}"
    )


# --------------------------------------------------------------------------
# A built schedule is not yet authority to move product
# --------------------------------------------------------------------------


def test_injection_against_an_unpublished_cycle_is_refused(api):
    """PRD 3.7: "The ticket's cycle must be in `PUBLISHED` — an unpublished plan is
    not authority to move product — and an attempt made against a cycle in any other
    status is refused with `ERR_CYCLE_INVALID_STATE`, never with
    `ERR_TICKET_INVALID_STATE`."
    PRD 3.6: "Every ticket is born with two independent status dimensions on the
    same row: `movement_status` of `PLANNED`, tracking the physical movement and
    taking only the values `PLANNED`, `INJECTED`, `DELIVERED` or `CANCELLED` (of
    which `DELIVERED` and `CANCELLED` are terminal), and `quality_status` of
    `PENDING`, tracking the specification dimension and taking only `PENDING`,
    `PASSED` or `REJECTED`."
    PRD 3.1: "A new shipper's `status` is `ACTIVE`, its `suspended_reason` is null
    and its `exposure_usd` is 0.00."

    Design: Corner/endpoints/inject_before_publication_rejected
    """
    ctx = setup_scheduled_cycle(
        nominated_bbl=30000, origin_stock_bbl=TEST_DEFAULTS["ORIGIN_STOCK_BBL"]
    )
    ticket = ctx["tickets"][0]

    response = api.inject_batch(
        ticket["id"], inject_payload(30000, 9, 8), OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_INVALID_STATE.value)

    cycle_after = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle_after["status"] == "SCHEDULED", (
        f"the refused injection leaves the cycle SCHEDULED, got {cycle_after['status']}"
    )
    assert cycle_after["schedule_published_at"] is None, (
        "the cycle was never published, so its stamp stays null, got "
        f"{cycle_after['schedule_published_at']}"
    )

    ticket_after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert ticket_after["movement_status"] == "PLANNED", (
        f"no volume moved, so the ticket stays PLANNED, got {ticket_after['movement_status']}"
    )
    assert ticket_after["quality_status"] == "PENDING", (
        "the cycle-status refusal precedes the quality dimension, which stays PENDING, "
        f"got {ticket_after['quality_status']}"
    )

    origin_after = validate_success(api.get_terminal(ctx["origin"]["id"], SCHEDULER))
    assert origin_after["inventory_bbl"] == TEST_DEFAULTS["ORIGIN_STOCK_BBL"], (
        "the origin tank is untouched by the refused injection, expected "
        f"{TEST_DEFAULTS['ORIGIN_STOCK_BBL']}, got {origin_after['inventory_bbl']}"
    )

    shipper_after = validate_success(
        api.get_shipper(ctx["shippers"]["ALPHA"]["id"], SCHEDULER)
    )
    assert float(shipper_after["exposure_usd"]) == 0.00, (
        "no ticket reached INJECTED, so the shipper's exposure stays 0.00, got "
        f"{shipper_after['exposure_usd']}"
    )


# --------------------------------------------------------------------------
# Path identifiers that resolve to nothing
# --------------------------------------------------------------------------


def test_unknown_nomination_id_is_not_found(api):
    """PRD 2.5: "A missing nomination cycle yields `ERR_CYCLE_NOT_FOUND` (404) on
    the single-cycle read and on every cycle action; a missing nomination yields
    `ERR_NOMINATION_NOT_FOUND` (404) on the single-nomination read and every
    nomination action; a missing batch ticket yields `ERR_BATCH_TICKET_NOT_FOUND`
    (404) on the single-ticket read and every ticket action; a missing maintenance
    event yields `ERR_MAINTENANCE_EVENT_NOT_FOUND` (404) on the single-event read
    and every event action; a missing settlement yields `ERR_SETTLEMENT_NOT_FOUND`
    (404) on the single-settlement read and every settlement action."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/unknown_nomination_id_returns_nomination_not_found
    """
    set_clock(TEST_DEFAULTS["WINDOW_OPEN_AT"], ADMIN)

    response = api.get_nomination(UNKNOWN_NOMINATION_ID, SCHEDULER)
    error_data = validate_error(response, ApiErrorId.ERR_NOMINATION_NOT_FOUND.value)
    assert isinstance(error_data.get("message"), str) and error_data["message"], (
        "the refusal carries a human-readable message and no nomination payload"
    )
    assert "id" not in error_data, (
        f"the error payload must not carry a nomination, got keys {sorted(error_data)}"
    )


def test_unknown_batch_ticket_id_is_not_found_on_read_and_on_injection(api):
    """PRD 2.5: "A missing nomination cycle yields `ERR_CYCLE_NOT_FOUND` (404) on
    the single-cycle read and on every cycle action; a missing nomination yields
    `ERR_NOMINATION_NOT_FOUND` (404) on the single-nomination read and every
    nomination action; a missing batch ticket yields `ERR_BATCH_TICKET_NOT_FOUND`
    (404) on the single-ticket read and every ticket action; a missing maintenance
    event yields `ERR_MAINTENANCE_EVENT_NOT_FOUND` (404) on the single-event read
    and every event action; a missing settlement yields `ERR_SETTLEMENT_NOT_FOUND`
    (404) on the single-settlement read and every settlement action."
    PRD 2.5: "Every identifier embedded in the URL path is resolved left to right,
    before any identifier in the request body is looked at."

    Design: Corner/errors/unknown_batch_ticket_id_returns_batch_ticket_not_found
    """
    set_clock(TEST_DEFAULTS["WINDOW_OPEN_AT"], ADMIN)

    validate_error(
        api.get_batch_ticket(UNKNOWN_BATCH_TICKET_ID, SCHEDULER),
        ApiErrorId.ERR_BATCH_TICKET_NOT_FOUND.value,
    )
    validate_error(
        api.inject_batch(
            UNKNOWN_BATCH_TICKET_ID, inject_payload(1000, 9, 8), OPERATOR
        ),
        ApiErrorId.ERR_BATCH_TICKET_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(
        api.list_batch_tickets(SCHEDULER, params={"limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"the failed injection creates no batch ticket, got total_count {meta['total_count']}"
    )


def test_unknown_maintenance_event_id_is_not_found_on_notify(api):
    """PRD 2.5: "A missing nomination cycle yields `ERR_CYCLE_NOT_FOUND` (404) on
    the single-cycle read and on every cycle action; a missing nomination yields
    `ERR_NOMINATION_NOT_FOUND` (404) on the single-nomination read and every
    nomination action; a missing batch ticket yields `ERR_BATCH_TICKET_NOT_FOUND`
    (404) on the single-ticket read and every ticket action; a missing maintenance
    event yields `ERR_MAINTENANCE_EVENT_NOT_FOUND` (404) on the single-event read
    and every event action; a missing settlement yields `ERR_SETTLEMENT_NOT_FOUND`
    (404) on the single-settlement read and every settlement action."
    PRD 2.5: "The ladder below is exhaustive and is evaluated from top to bottom;
    the first rank whose condition fails determines both the `error_id` and the HTTP
    status, and no later rank is consulted."

    Design: Corner/errors/unknown_maintenance_event_id_returns_maintenance_event_not_found
    """
    set_clock(TEST_DEFAULTS["WINDOW_OPEN_AT"], SCHEDULER)

    validate_error(
        api.notify_maintenance_event(UNKNOWN_MAINTENANCE_EVENT_ID, SCHEDULER),
        ApiErrorId.ERR_MAINTENANCE_EVENT_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(
        api.list_maintenance_events(SCHEDULER, params={"limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"no maintenance event exists to notify, got total_count {meta['total_count']}"
    )


def test_unknown_settlement_id_is_not_found_on_certify(api):
    """PRD 2.5: "A missing nomination cycle yields `ERR_CYCLE_NOT_FOUND` (404) on
    the single-cycle read and on every cycle action; a missing nomination yields
    `ERR_NOMINATION_NOT_FOUND` (404) on the single-nomination read and every
    nomination action; a missing batch ticket yields `ERR_BATCH_TICKET_NOT_FOUND`
    (404) on the single-ticket read and every ticket action; a missing maintenance
    event yields `ERR_MAINTENANCE_EVENT_NOT_FOUND` (404) on the single-event read
    and every event action; a missing settlement yields `ERR_SETTLEMENT_NOT_FOUND`
    (404) on the single-settlement read and every settlement action."
    PRD 2.5: "The ladder below is exhaustive and is evaluated from top to bottom;
    the first rank whose condition fails determines both the `error_id` and the HTTP
    status, and no later rank is consulted."

    Design: Corner/errors/unknown_settlement_id_returns_settlement_not_found
    """
    set_clock(TEST_DEFAULTS["WINDOW_OPEN_AT"], SCHEDULER)

    validate_error(
        api.certify_settlement(
            UNKNOWN_SETTLEMENT_ID, make_scheduler_headers("sched-certifier-1")
        ),
        ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(
        api.list_settlements(SCHEDULER, params={"limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"no settlement has been raised, got total_count {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Resubmission belongs to the revision loop
# --------------------------------------------------------------------------


def test_resubmitting_a_submitted_nomination_is_refused(api):
    """PRD 3.8: "Only the owning shipper may resubmit — otherwise
    `ERR_NOT_RESOURCE_OWNER` — the shipper's `status` must be `ACTIVE`, or
    `ERR_SHIPPER_NOT_ACTIVE`, and the nomination must be in `REVISION_REQUESTED`, or
    `ERR_NOMINATION_INVALID_STATE`."
    PRD 3.3: "The new nomination itself starts with `status` of `SUBMITTED`,
    `revision_count` of 0, `allocated_bbl` of 0, `history_base_bbl` of 0,
    `allocation_class` of `NEW_SHIPPER`, `pinned_tariff_id` of null and
    `rejection_reason` of null."

    Design: Corner/errors/resubmit_a_submitted_nomination_returns_nomination_invalid_state
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000)
    nomination = ctx["nominations"][nomination_key("ALPHA")]
    alpha = ctx["shippers"]["ALPHA"]
    assert nomination["status"] == "SUBMITTED", (
        f"the nomination is merely SUBMITTED, got {nomination['status']}"
    )

    response = api.resubmit_nomination(
        nomination["id"],
        resubmit_nomination_payload(25000),
        make_shipper_headers(alpha["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOMINATION_INVALID_STATE.value)

    nomination_after = validate_success(
        api.get_nomination(nomination["id"], SCHEDULER)
    )
    assert nomination_after["status"] == "SUBMITTED", (
        f"the refused resubmission changes no status, got {nomination_after['status']}"
    )
    assert nomination_after["nominated_bbl"] == 30000, (
        "the shipper cannot edit its nominated volume through resubmit, expected "
        f"30000, got {nomination_after['nominated_bbl']}"
    )
    assert nomination_after["revision_count"] == 0, (
        "no revision was ever requested, so the counter stays 0, got "
        f"{nomination_after['revision_count']}"
    )

    cycle_after = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle_after["nominated_total_bbl"] == 30000, (
        "the cycle's nominated total is untouched by the refusal, got "
        f"{cycle_after['nominated_total_bbl']}"
    )
