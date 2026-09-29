"""Two conserved identities, each broken on purpose and then restored.

The volumetric identity spans five accumulators across three rows and is restored by
an operator cancelling a batch that is already in the line. The capacity identity
lives inside one cycle and is restored by the service itself, when a second off-spec
measurement ends a batch and hands its barrels back.
"""

from test_helpers import (
    OPERATOR,
    SCHEDULER,
    api_client,
    assert_capacity_conservation,
    assert_volumetric_conservation,
    cancel_payload,
    inject_payload,
    inject_ticket,
    nomination_key,
    refresh_cycle,
    refresh_destination,
    refresh_nomination,
    refresh_origin,
    refresh_segment,
    refresh_shipper,
    refresh_tickets,
    set_clock,
    setup_multi_shipper_cycle,
    ticket_at,
    validate_error,
    validate_success,
)

RELEASE_REASON = "shipper released the barrels back to the origin tank"


def _barrels(value) -> int:
    return int(round(float(value)))


def _volume(value) -> float:
    return round(float(value), 2)


def _money(value) -> float:
    return round(float(value), 2)


def _published_pair(origin_stock_bbl=100000):
    """ALPHA's 30000 bbl of ULSD at position 1 and 26100 bbl of CBOB at position 2, on
    a published schedule over a tank holding 100000 bbl."""
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000), ("ALPHA", "CBOB", 26100)],
        grades=("ULSD", "CBOB"),
        origin_stock_bbl=origin_stock_bbl,
        publish=True,
    )


def _both_batches_in_the_line():
    """Both batches injected on specification, which puts 56100 bbl in transit and
    250 bbl of interface slop in the segment's slop tank."""
    ctx = _published_pair()
    set_clock("2026-09-01T00:00:00Z", SCHEDULER)
    inject_ticket(ctx, ticket_at(ctx, 1)["id"], 30000, measured_sulfur_ppm=9, measured_rvp_psi=10)
    inject_ticket(
        ctx, ticket_at(ctx, 2)["id"], 26100, measured_sulfur_ppm=40, measured_rvp_psi=13
    )
    refresh_origin(ctx)
    refresh_destination(ctx)
    refresh_segment(ctx)
    return ctx


def test_cancelling_an_injected_batch_returns_the_barrels_and_the_interface_cut(api):
    """The compensation is exact and it is bigger than the batch: 26100 bbl of product
    *and* the 250 bbl the interface cut both go back into the origin tank, taking it
    from 43650.00 to 70000.00 bbl, while in transit falls to the surviving batch's
    30000 bbl and the slop tank empties.

    PRD 3.7: "Cancelling a ticket whose `movement_status` is `INJECTED` moves it
    `INJECTED → CANCELLED` and is a full compensation: the origin terminal's
    `inventory_bbl` is increased by the sum of `injected_bbl` and `transmix_bbl`, the
    segment's `in_transit_bbl` is decreased by `injected_bbl`, and the segment's
    `transmix_inventory_bbl` is decreased by `transmix_bbl` — each by exactly the
    amount the injection moved, so the five-accumulator total of §2.7 is left unchanged
    and nothing is booked to `system_loss_bbl`."

    Design: Difficulty/compensating_invariant/inject_then_cancel_restores_volumetric_conservation
    """
    ctx = _both_batches_in_the_line()
    assert _volume(ctx["origin"]["inventory_bbl"]) == 43650.00
    assert _volume(ctx["segment"]["in_transit_bbl"]) == 56100.00
    assert _volume(ctx["segment"]["transmix_inventory_bbl"]) == 250.00
    gasoline_batch = ticket_at(ctx, 2)
    assert _volume(gasoline_batch["transmix_bbl"]) == 250.00

    cancelled = validate_success(
        api_client.cancel_batch(
            gasoline_batch["id"], cancel_payload(cancel_reason=RELEASE_REASON), OPERATOR
        )
    )

    assert cancelled["movement_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == RELEASE_REASON
    assert _volume(cancelled["transmix_bbl"]) == 250.00

    assert _volume(refresh_origin(ctx)["inventory_bbl"]) == 70000.00
    segment = refresh_segment(ctx)
    assert _volume(segment["in_transit_bbl"]) == 30000.00
    assert _volume(segment["transmix_inventory_bbl"]) == 0.00
    assert _volume(segment["system_loss_bbl"]) == 0.00


def test_the_five_accumulator_total_is_the_same_after_the_compensation(api):
    """Nothing leaked and nothing was invented: the book still totals 100000.00 bbl
    across the five accumulators, the destination tank is still empty, the cycle's
    transmix figure drops to zero because a cancelled ticket leaves that sum, exposure
    falls back to the 55650.00 USD of the one surviving batch, and the untouched ULSD
    ticket is still INJECTED.

    PRD 2.7: "An injection followed by a cancellation of the same batch ticket must
    leave the five-accumulator total bit-identical to its value before the injection:
    the cancellation returns the injected barrels *plus* the interface transmix cut to
    the origin terminal's `inventory_bbl`, and unwinds `in_transit_bbl` and
    `transmix_inventory_bbl` by exactly the amounts the injection added."

    PRD 3.7: "The `cancel_reason` is stored, and both the cycle's `total_transmix_bbl`
    and the shipper's `exposure_usd` are recomputed."

    Design: Difficulty/compensating_invariant/inject_then_cancel_restores_volumetric_conservation
    """
    ctx = _both_batches_in_the_line()
    assert_volumetric_conservation(
        ctx["origin"], ctx["destination"], ctx["segment"], 100000.00
    )

    validate_success(
        api_client.cancel_batch(
            ticket_at(ctx, 2)["id"], cancel_payload(cancel_reason=RELEASE_REASON), OPERATOR
        )
    )

    refresh_origin(ctx)
    refresh_destination(ctx)
    refresh_segment(ctx)
    assert _volume(ctx["destination"]["inventory_bbl"]) == 0.00
    assert_volumetric_conservation(
        ctx["origin"], ctx["destination"], ctx["segment"], 100000.00
    )

    assert _volume(refresh_cycle(ctx)["total_transmix_bbl"]) == 0.00
    assert _money(refresh_shipper(ctx, "ALPHA")["exposure_usd"]) == 55650.00

    refresh_tickets(ctx)
    assert ticket_at(ctx, 1)["movement_status"] == "INJECTED"


def _pair_awaiting_injection():
    """The same published pair with neither batch presented yet, so the cycle holds
    56100 bbl allocated against 43900 bbl spare and 250 bbl of planned interface cut."""
    ctx = _published_pair()
    set_clock("2026-09-02T00:00:00Z", SCHEDULER)
    return ctx


def _present_off_spec_gasoline(ctx):
    """Present the CBOB batch at 120 ppm against its 80 ppm ceiling."""
    return api_client.inject_batch(
        ticket_at(ctx, 2)["id"], inject_payload(26100, 120, 14), OPERATOR
    )


def test_the_second_off_spec_measurement_ends_the_batch_and_the_first_does_not(api):
    """Both presentations are refused with the same code, and the difference between
    them is what they do to the ticket: the first only rejects the product and leaves
    the batch planned, while the second exhausts the two retests allowed and cancels
    the batch outright, recording why.

    PRD 3.7: "A second refusal, however, ends the batch."

    PRD 3.7: "Hop two cancels the ticket: `movement_status` moves `PLANNED →
    CANCELLED` with `cancel_reason` recorded as `QUALITY_RETEST_LIMIT`."

    Design: Difficulty/compensating_invariant/quality_retest_limit_releases_allocation_preserving_capacity_conservation
    """
    ctx = _pair_awaiting_injection()

    validate_error(
        _present_off_spec_gasoline(ctx), "ERR_QUALITY_SPEC_VIOLATION", expected_status=422
    )
    refresh_tickets(ctx)
    once_refused = ticket_at(ctx, 2)
    assert once_refused["quality_status"] == "REJECTED"
    assert int(once_refused["retest_count"]) == 1
    assert once_refused["movement_status"] == "PLANNED"

    validate_error(
        _present_off_spec_gasoline(ctx), "ERR_QUALITY_SPEC_VIOLATION", expected_status=422
    )
    refresh_tickets(ctx)
    ended = ticket_at(ctx, 2)
    assert int(ended["retest_count"]) == 2
    assert ended["movement_status"] == "CANCELLED"
    assert ended["cancel_reason"] == "QUALITY_RETEST_LIMIT"


def test_the_released_barrels_land_in_unallocated_capacity_and_the_identity_holds(api):
    """The refused 26100 bbl are not lost to the cycle: the parent nomination is pushed
    back for revision with its allocation zeroed, and allocated plus unallocated moves
    from 56100 + 43900 to 30000 + 70000 — still exactly the 100000 bbl of effective
    capacity. Meanwhile no barrel ever left the tank, nothing was booked to loss, and
    the surviving ULSD nomination is still SCHEDULED for its full volume.

    PRD 3.7: "Hop three pushes the parent nomination `SCHEDULED → REVISION_REQUESTED`,
    increments its `revision_count` by one and sets its `allocated_bbl` to 0, releasing
    the refused barrels back into the cycle's `unallocated_capacity_bbl` so that
    allocated plus unallocated still equals effective capacity."

    PRD 2.8: "A parallel identity governs allocation rather than volume: for every
    nomination cycle, `allocated_total_bbl` plus `unallocated_capacity_bbl` must equal
    `effective_capacity_bbl` exactly, in whole barrels, with zero drift."

    Design: Difficulty/compensating_invariant/quality_retest_limit_releases_allocation_preserving_capacity_conservation
    """
    ctx = _pair_awaiting_injection()
    assert _barrels(ctx["cycle"]["allocated_total_bbl"]) == 56100
    assert _barrels(ctx["cycle"]["unallocated_capacity_bbl"]) == 43900
    assert _volume(ctx["cycle"]["total_transmix_bbl"]) == 250.00

    for _ in range(2):
        validate_error(
            _present_off_spec_gasoline(ctx),
            "ERR_QUALITY_SPEC_VIOLATION",
            expected_status=422,
        )

    gasoline = refresh_nomination(ctx, nomination_key("ALPHA", "CBOB"))
    assert gasoline["status"] == "REVISION_REQUESTED"
    assert _barrels(gasoline["allocated_bbl"]) == 0
    assert int(gasoline["revision_count"]) == 1

    cycle = refresh_cycle(ctx)
    assert _barrels(cycle["allocated_total_bbl"]) == 30000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 70000
    assert _barrels(cycle["effective_capacity_bbl"]) == 100000
    assert_capacity_conservation(cycle)
    assert _volume(cycle["total_transmix_bbl"]) == 0.00

    origin = refresh_origin(ctx)
    segment = refresh_segment(ctx)
    assert _volume(origin["inventory_bbl"]) == 100000.00
    assert _volume(segment["in_transit_bbl"]) == 0.00
    assert _volume(segment["transmix_inventory_bbl"]) == 0.00
    assert _volume(segment["system_loss_bbl"]) == 0.00
    assert _money(refresh_shipper(ctx, "ALPHA")["exposure_usd"]) == 0.00

    diesel = refresh_nomination(ctx, nomination_key("ALPHA", "ULSD"))
    assert diesel["status"] == "SCHEDULED"
    assert _barrels(diesel["allocated_bbl"]) == 30000
    assert ticket_at(ctx, 1)["movement_status"] == "PLANNED"
    assert ticket_at(ctx, 1)["quality_status"] == "PENDING"
