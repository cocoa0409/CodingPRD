"""Core arithmetic of the pipeline nomination service.

Effective capacity, the shipping history base, interface transmix cuts, tariff
pinning and settlement money are all specified as exact, deterministic figures.
Every test here builds its own network from scratch, drives the cycle to the
lifecycle stage the arithmetic is observable at, and pins the computed values to
the literals the PRD's formulas produce.
"""

from test_helpers import (
    ADMIN,
    SCHEDULER,
    add_tariff,
    assert_batch_ticket,
    assert_capacity_conservation,
    assert_cycle,
    assert_money_precision,
    assert_nomination,
    assert_ratio_precision,
    assert_settlement,
    assert_whole_barrels,
    create_nomination_payload,
    make_shipper_headers,
    nominate,
    nomination_key,
    settle_payload,
    setup_cycle_with_nomination,
    setup_delivered_cycle,
    setup_multi_shipper_cycle,
    setup_open_cycle,
    setup_prorated_cycle,
    validate_paginated,
    validate_success,
)


def _tickets_in_sequence(api, cycle_id):
    """The cycle's batch tickets in sequence-position order, with the listing's
    total_count, read straight back from the collection endpoint."""
    tickets, meta = validate_paginated(
        api.list_batch_tickets(SCHEDULER, params={"cycle_id": cycle_id, "limit": 100})
    )
    return tickets, meta


def test_effective_capacity_carves_out_linefill_makeup_and_transmix_reserve(api):
    """A line standing at 5000 bbl of linefill against a 20000 bbl requirement cannot offer
    that 15000 bbl shortfall to shippers, and the 1000 bbl slop reserve comes off as well, so
    the 101000 bbl nameplate sizes down to exactly 85000 nominatable barrels.

    PRD 3.4: "First, the **linefill make-up** is the amount by which the segment's
    `linefill_requirement_bbl` exceeds its current `linefill_bbl`, or zero when linefill is
    already at or above requirement — never a negative number."
    PRD 3.4: "Third, the linefill make-up is subtracted from that truncated figure, and then the
    segment's `transmix_reserve_bbl` is subtracted as well."
    PRD 3.4: "The outcome is written to the cycle's `effective_capacity_bbl`, and the value of
    `derate_pct` used is snapshotted into the cycle's `derate_pct_applied`."

    Design: Corner/calculations/effective_capacity_subtracts_linefill_makeup_and_transmix_reserve
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000, linefill_bbl=5000)
    cycle_id = ctx["cycle"]["id"]

    validate_success(api.close_cycle(cycle_id, SCHEDULER))
    cycle = validate_success(api.prorate_cycle(cycle_id, SCHEDULER))

    assert_cycle(cycle)
    assert_whole_barrels(cycle["effective_capacity_bbl"], "effective_capacity_bbl")
    assert float(cycle["effective_capacity_bbl"]) == 85000, (
        "101000 nameplate less a 15000 linefill make-up less a 1000 transmix reserve is "
        f"85000 nominatable barrels, got {cycle['effective_capacity_bbl']}"
    )
    assert float(cycle["derate_pct_applied"]) == 0, (
        "no maintenance is planned, so the snapshotted derate is 0, got "
        f"{cycle['derate_pct_applied']}"
    )
    assert float(cycle["allocated_total_bbl"]) == 30000, (
        f"the sole 30000 bbl nomination is awarded in full, got {cycle['allocated_total_bbl']}"
    )
    assert float(cycle["unallocated_capacity_bbl"]) == 55000, (
        f"85000 less 30000 awarded leaves 55000, got {cycle['unallocated_capacity_bbl']}"
    )
    assert_capacity_conservation(cycle)
    assert_ratio_precision(cycle["proration_factor"], "proration_factor")
    assert float(cycle["proration_factor"]) == 1.000000, (
        f"30000 allocated over 30000 nominated is 1.000000, got {cycle['proration_factor']}"
    )

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["linefill_bbl"]) == 5000, (
        "sizing the line reads linefill but never tops it up, got "
        f"{segment['linefill_bbl']}"
    )


def test_history_base_divides_by_qualifying_record_count_only(api):
    """ALPHA holds four movement records on this segment but only two qualify: the PROVISIONAL
    90000 bbl row is excluded by its record status and the FINAL 88000 bbl row ending
    2025-01-15 falls outside the one-year lookback that opens at 2025-08-01. The divisor is the
    qualifying count of two, so the history base is (30000 + 42000) / 2.

    PRD 3.5: "A historical movement record qualifies for a nomination when its `shipper_id`
    matches the nomination's shipper, its `segment_id` matches the cycle's segment, its
    `record_status` is `FINAL`, and its `cycle_end_at` falls at or after the instant exactly 365
    days — one full year — before the cycle's `window_open_at` and strictly before
    `window_open_at` itself."
    PRD 3.5: "Otherwise `history_base_bbl` is the sum of `actual_shipped_bbl` across the
    qualifying records divided by the *number of qualifying records* — never by a fixed number of
    cycles — rounded half up to two decimal places."
    PRD 3.5: "The count of qualifying records also fixes `allocation_class`: a shipper with at
    least two qualifying records on the segment is `HISTORICAL`, and a shipper with fewer than two
    is `NEW_SHIPPER`."

    Design: Corner/calculations/shipper_history_base_excludes_provisional_and_out_of_window_rows
    """
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000)],
        history=[
            ("ALPHA", 30000, "2026-06-30T00:00:00Z", "FINAL", "2026-07"),
            ("ALPHA", 42000, "2026-07-31T00:00:00Z", "FINAL", "2026-08"),
            ("ALPHA", 90000, "2026-07-15T00:00:00Z", "PROVISIONAL", "2026-08B"),
            ("ALPHA", 88000, "2025-01-15T00:00:00Z", "FINAL", "2025-01"),
        ],
        close=True,
    )
    cycle_id = ctx["cycle"]["id"]
    nomination_id = ctx["nominations"][nomination_key("ALPHA")]["id"]

    cycle = validate_success(api.prorate_cycle(cycle_id, SCHEDULER))
    nomination = validate_success(api.get_nomination(nomination_id, SCHEDULER))

    assert_nomination(nomination)
    assert float(nomination["history_base_bbl"]) == 36000.00, (
        "72000 barrels over the two qualifying records is a 36000.00 bbl history base, got "
        f"{nomination['history_base_bbl']}"
    )
    assert nomination["allocation_class"] == "HISTORICAL", (
        "two qualifying records make the shipper HISTORICAL, got "
        f"{nomination['allocation_class']}"
    )
    assert float(nomination["allocated_bbl"]) == 30000, (
        f"the sole nomination clears the historical pool in full, got {nomination['allocated_bbl']}"
    )
    assert nomination["status"] == "PRORATED", (
        f"a surviving nomination settles into PRORATED, got {nomination['status']}"
    )
    assert float(cycle["effective_capacity_bbl"]) == 100000, (
        "linefill sits at requirement, so only the 1000 bbl reserve comes off the 101000 bbl "
        f"nameplate, got {cycle['effective_capacity_bbl']}"
    )
    assert float(cycle["unallocated_capacity_bbl"]) == 70000, (
        f"100000 less 30000 awarded leaves 70000, got {cycle['unallocated_capacity_bbl']}"
    )
    assert_capacity_conservation(cycle)


def test_interface_transmix_is_zero_when_the_batch_matches_the_linefill_grade(api):
    """The linefill grade stands upstream of sequence position 1, so a lone ULSD batch on a
    ULSD-filled line meets no grade change at all: the rank gap is zero, no slop cut is
    generated, and the cycle's transmix total stays at zero.

    PRD 3.6: "For the ticket at `sequence_position` 1 the upstream rank is the `sequence_rank` of
    the segment's linefill grade, named by the segment's `linefill_grade_id`; for every later
    ticket it is the `sequence_rank` of the grade on the predecessor ticket's nomination."
    PRD 3.6: "Where the gap is zero — same grade behind same grade — the ticket's `transmix_bbl`
    is 0 and its `requires_flush` is false."
    PRD 3.6: "Walking that order assigns `sequence_position` starting at 1, each ticket's
    `predecessor_batch_id` names the ticket at the position immediately before it, and the ticket
    at position 1 has a null `predecessor_batch_id`."

    Design: Corner/calculations/interface_transmix_zero_when_batch_matches_linefill_grade
    """
    ctx = setup_prorated_cycle(nominated_bbl=30000)
    cycle_id = ctx["cycle"]["id"]

    cycle = validate_success(api.build_schedule(cycle_id, SCHEDULER))
    tickets, meta = _tickets_in_sequence(api, cycle_id)

    assert meta["total_count"] == 1, (
        f"one prorated nomination lifts exactly one batch ticket, got {meta['total_count']}"
    )
    ticket = tickets[0]
    assert_batch_ticket(ticket)
    assert int(ticket["sequence_position"]) == 1, (
        f"the only ticket sequences first, got {ticket['sequence_position']}"
    )
    assert ticket["predecessor_batch_id"] is None, (
        "the ticket at position 1 has no predecessor batch, got "
        f"{ticket['predecessor_batch_id']}"
    )
    assert float(ticket["transmix_bbl"]) == 0, (
        f"ULSD behind ULSD linefill is a zero rank gap, got {ticket['transmix_bbl']}"
    )
    assert ticket["requires_flush"] is False, (
        f"a zero rank gap never requires a flush, got {ticket['requires_flush']}"
    )
    assert float(cycle["total_transmix_bbl"]) == 0, (
        f"the cycle generates no interface cut at all, got {cycle['total_transmix_bbl']}"
    )

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["transmix_inventory_bbl"]) == 0, (
        "building a schedule moves no slop into the line, got "
        f"{segment['transmix_inventory_bbl']}"
    )


def test_interface_transmix_doubles_on_an_upgrade_and_flags_the_flush(api):
    """One sequence exercises all three interface branches against a 250 bbl cut: JET rank 1
    behind the ULSD rank 3 linefill is an upgrade of gap 2 costing 250 * 2 * 2 = 1000 bbl and
    demanding a flush, ULSD behind JET is a downgrade of gap 2 costing 500 bbl with no flush, and
    CBOB rank 4 behind ULSD is a downgrade of gap 1 costing 250 bbl. The cycle carries 1750 bbl.

    PRD 3.6: "Those nominations are ordered by the `sequence_rank` of their product grade
    ascending — cleanest product first — then by `allocated_bbl` descending, then by the
    nomination's `created_at` ascending."
    PRD 3.6: "Where the ticket's own rank is *higher* than the upstream rank, meaning a dirtier
    product following a cleaner one, the cut is a **downgrade**: `transmix_bbl` is the segment's
    `transmix_cut_bbl` multiplied by the rank gap, and `requires_flush` stays false."
    PRD 3.6: "Where the ticket's own rank is *lower* than the upstream rank, meaning a cleaner
    product following a dirtier one, the cut is an **upgrade** and costs twice as much:
    `transmix_bbl` is the segment's `transmix_cut_bbl` multiplied by the rank gap and then
    multiplied by two, and `requires_flush` is true when and only when the rank gap is two or more
    steps."
    PRD 3.6: "The cycle's `total_transmix_bbl` is the sum of `transmix_bbl` across the cycle's
    tickets whose `movement_status` is anything other than `CANCELLED`."

    Design: Corner/calculations/interface_transmix_upgrade_multiplier_and_flush_flag
    """
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "JET", 20000), ("BRAVO", "ULSD", 20000), ("CHARLIE", "CBOB", 20000)],
        grades=("JET", "ULSD", "CBOB"),
        segment_overrides={"transmix_reserve_bbl": 2000},
        prorate=True,
    )
    cycle_id = ctx["cycle"]["id"]

    assert float(ctx["cycle"]["effective_capacity_bbl"]) == 99000, (
        "the 2000 bbl reserve comes off the 101000 bbl nameplate, got "
        f"{ctx['cycle']['effective_capacity_bbl']}"
    )
    assert float(ctx["cycle"]["unallocated_capacity_bbl"]) == 39000, (
        "99000 less the 60000 barrels awarded leaves 39000, got "
        f"{ctx['cycle']['unallocated_capacity_bbl']}"
    )
    for key in ("ALPHA:JET", "BRAVO:ULSD", "CHARLIE:CBOB"):
        assert float(ctx["nominations"][key]["allocated_bbl"]) == 20000, (
            f"{key} is awarded its full 20000 bbl nomination, got "
            f"{ctx['nominations'][key]['allocated_bbl']}"
        )

    cycle = validate_success(api.build_schedule(cycle_id, SCHEDULER))
    tickets, meta = _tickets_in_sequence(api, cycle_id)

    assert meta["total_count"] == 3, (
        f"three prorated nominations lift three tickets, got {meta['total_count']}"
    )
    assert [int(t["sequence_position"]) for t in tickets] == [1, 2, 3], (
        "tickets sequence cleanest product first, got "
        f"{[t['sequence_position'] for t in tickets]}"
    )
    jet_ticket, ulsd_ticket, cbob_ticket = tickets
    for ticket in tickets:
        assert_batch_ticket(ticket)

    assert jet_ticket["nomination_id"] == ctx["nominations"]["ALPHA:JET"]["id"], (
        "JET at rank 1 is the cleanest product and sequences first"
    )
    assert jet_ticket["predecessor_batch_id"] is None
    assert float(jet_ticket["transmix_bbl"]) == 1000, (
        "an upgrade of rank gap 2 cuts 250 * 2 * 2 barrels, got "
        f"{jet_ticket['transmix_bbl']}"
    )
    assert jet_ticket["requires_flush"] is True, (
        f"a two-step upgrade requires a flush, got {jet_ticket['requires_flush']}"
    )

    assert ulsd_ticket["nomination_id"] == ctx["nominations"]["BRAVO:ULSD"]["id"]
    assert ulsd_ticket["predecessor_batch_id"] == jet_ticket["id"], (
        "position 2 names the ticket immediately before it, got "
        f"{ulsd_ticket['predecessor_batch_id']}"
    )
    assert float(ulsd_ticket["transmix_bbl"]) == 500, (
        f"a downgrade of rank gap 2 cuts 250 * 2 barrels, got {ulsd_ticket['transmix_bbl']}"
    )
    assert ulsd_ticket["requires_flush"] is False, (
        f"a downgrade never requires a flush, got {ulsd_ticket['requires_flush']}"
    )

    assert cbob_ticket["nomination_id"] == ctx["nominations"]["CHARLIE:CBOB"]["id"]
    assert cbob_ticket["predecessor_batch_id"] == ulsd_ticket["id"]
    assert float(cbob_ticket["transmix_bbl"]) == 250, (
        f"a downgrade of rank gap 1 cuts 250 barrels, got {cbob_ticket['transmix_bbl']}"
    )
    assert cbob_ticket["requires_flush"] is False

    assert float(cycle["total_transmix_bbl"]) == 1750, (
        f"1000 plus 500 plus 250 is 1750 barrels of slop, got {cycle['total_transmix_bbl']}"
    )


def test_tariff_pinning_ignores_draft_and_superseded_candidates(api):
    """Three ULSD rates price this segment and the winner is neither the newest filing nor the
    oldest: the DRAFT rate effective from 2026-08-15 is not a candidate at all, the 2026-07-01
    rate was pushed to SUPERSEDED when the 2026-08-05 rate was activated, so closing on
    2026-08-20 pins the single EFFECTIVE row.

    PRD 3.2: "The candidate set is every tariff whose `segment_id` equals the cycle's segment,
    whose `grade_id` equals the nomination's grade, whose `status` is `EFFECTIVE`, whose
    `effective_from` is at or before the cycle's `window_close_at`, and whose `effective_to` is
    either null or strictly later than the cycle's `window_close_at`."
    PRD 3.2: "`DRAFT` and `SUPERSEDED` rows are never candidates."
    PRD 3.2: "Activation also has a cascade: every *other* tariff for the same `segment_id` and
    `grade_id` that is currently `EFFECTIVE` and whose effectivity interval overlaps the newly
    activated one moves `EFFECTIVE → SUPERSEDED`."
    PRD 3.4: "A nomination whose `nominated_bbl` is at least its pinned `tender_minimum_bbl` moves
    `SUBMITTED → ACCEPTED` with `pinned_tariff_id` frozen."

    Design: Corner/calculations/tariff_pinning_ignores_draft_and_superseded_candidates
    """
    ctx = setup_open_cycle()
    older_tariff = ctx["tariffs"]["ULSD"]
    effective_tariff = add_tariff(
        ctx,
        "ULSD",
        base_rate_usd_per_bbl=2.100,
        tier1_rate_usd_per_bbl=1.950,
        tier2_rate_usd_per_bbl=1.800,
        imbalance_penalty_rate_usd_per_bbl=0.50,
        effective_from="2026-08-05T00:00:00Z",
    )
    draft_tariff = add_tariff(
        ctx,
        "ULSD",
        activate=False,
        base_rate_usd_per_bbl=9.999,
        tier1_rate_usd_per_bbl=9.999,
        tier2_rate_usd_per_bbl=9.999,
        imbalance_penalty_rate_usd_per_bbl=0.99,
        effective_from="2026-08-15T00:00:00Z",
    )
    nominate(ctx, "ALPHA", nominated_bbl=30000)
    cycle_id = ctx["cycle"]["id"]
    nomination_id = ctx["nominations"][nomination_key("ALPHA")]["id"]

    cycle = validate_success(api.close_cycle(cycle_id, SCHEDULER))
    nomination = validate_success(api.get_nomination(nomination_id, SCHEDULER))

    assert_nomination(nomination)
    assert nomination["pinned_tariff_id"] == effective_tariff["id"], (
        "the most recently filed EFFECTIVE rate covering the closing instant bills, got "
        f"{nomination['pinned_tariff_id']}"
    )
    assert nomination["status"] == "ACCEPTED", (
        "30000 barrels clears the pinned 6000 bbl tender minimum, got "
        f"{nomination['status']}"
    )

    superseded = validate_success(api.get_tariff(older_tariff["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED", (
        "activating the overlapping 2026-08-05 rate supersedes the 2026-07-01 rate, got "
        f"{superseded['status']}"
    )
    still_draft = validate_success(api.get_tariff(draft_tariff["id"], ADMIN))
    assert still_draft["status"] == "DRAFT", (
        f"an unactivated filing stays DRAFT and never pins, got {still_draft['status']}"
    )
    assert cycle["status"] == "CLOSED", (
        f"closing drives the cycle OPEN to CLOSED, got {cycle['status']}"
    )


def test_settlement_money_rounds_each_ticket_line_on_the_delivered_basis(api):
    """A single batch that injects 30000 bbl and delivers 29900 bbl makes every money field
    checkable at once: the 100.00 bbl of shrinkage is allocated back to the sole shipper, so the
    imbalance is 29900 - 30000 + 100 = 0.00 and the tier is TOLERANCE with a zero penalty, while
    the DELIVERED basis bills 29900 * 1.705 against a SCHEDULED counterfactual of 30000 * 1.705.

    PRD 3.9: "The cycle's system loss is the total injected less the total delivered, rounded half
    up to two decimal places — and interface transmix is deliberately **not** part of it, since
    transmix was already accounted into the segment's slop inventory at injection."
    PRD 3.9: "Otherwise each billed shipper, taken in ascending order of the shipper's
    `created_at`, receives a share equal to the system loss multiplied by that shipper's own
    delivered volume divided by the cycle's total delivered volume, rounded half up to two decimal
    places."
    PRD 3.9: "For a given ticket, the billable volume under the `DELIVERED` basis is the larger of
    the ticket's `delivered_bbl` — treated as zero when it is null — and the pinned tariff's
    `tender_minimum_bbl`; under the `SCHEDULED` basis it is the larger of the ticket's
    `volume_bbl` and that same `tender_minimum_bbl`."
    PRD 3.9: "The rate that applies to that billable volume is the pinned tariff's
    `tier2_rate_usd_per_bbl` when the billable volume is at or above `tier2_min_bbl`, otherwise its
    `tier1_rate_usd_per_bbl` when the billable volume is at or above `tier1_min_bbl`, and otherwise
    its `base_rate_usd_per_bbl`."
    PRD 3.9: "The ticket's line amount is the billable volume multiplied by that rate, rounded half
    up to two decimal places — **rounded per ticket, before any summation** — and the shipper's
    charge on a given basis is the exact sum of those rounded lines."
    PRD 3.9: "Step four: `imbalance_bbl` is the `delivered_bbl` less the `scheduled_bbl` plus the
    `loss_allocation_bbl`, rounded half up to two decimal places — note that it may legitimately be
    negative."
    PRD 3.9: "Step eight computes `total_billed_usd` as `tariff_charge_usd` plus
    `imbalance_charge_usd`, rounded half up to two decimal places."

    Design: Corner/calculations/settlement_money_rounds_each_ticket_line_on_the_delivered_basis
    """
    ctx = setup_delivered_cycle(nominated_bbl=30000, injected_bbl=30000, delivered_bbl=29900)
    cycle_id = ctx["cycle"]["id"]

    validate_success(api.settle_cycle(cycle_id, settle_payload("DELIVERED"), SCHEDULER))
    settlements, meta = validate_paginated(
        api.list_settlements(SCHEDULER, params={"cycle_id": cycle_id, "limit": 10})
    )

    assert meta["total_count"] == 1, (
        f"one billed shipper raises one settlement row, got {meta['total_count']}"
    )
    settlement = settlements[0]
    assert_settlement(settlement)

    assert float(settlement["scheduled_bbl"]) == 30000, (
        f"the ticket's scheduled volume is 30000 barrels, got {settlement['scheduled_bbl']}"
    )
    assert float(settlement["delivered_bbl"]) == 29900, (
        f"the ticket delivered 29900 barrels, got {settlement['delivered_bbl']}"
    )
    assert float(settlement["loss_allocation_bbl"]) == 100.00, (
        "the sole shipper absorbs the whole 100.00 bbl system loss, got "
        f"{settlement['loss_allocation_bbl']}"
    )
    assert float(settlement["imbalance_bbl"]) == 0.00, (
        "29900 delivered less 30000 scheduled plus 100 allocated loss is 0.00, got "
        f"{settlement['imbalance_bbl']}"
    )
    assert_ratio_precision(settlement["imbalance_pct"], "imbalance_pct")
    assert float(settlement["imbalance_pct"]) == 0.000000, (
        f"a zero imbalance over 30000 scheduled is 0.000000, got {settlement['imbalance_pct']}"
    )
    assert settlement["imbalance_tier"] == "TOLERANCE", (
        "an imbalance at or below half of one percent is TOLERANCE, got "
        f"{settlement['imbalance_tier']}"
    )
    assert float(settlement["imbalance_charge_usd"]) == 0.00, (
        f"the TOLERANCE multiplier of 0 zeroes the penalty, got {settlement['imbalance_charge_usd']}"
    )
    assert float(settlement["tariff_charge_usd"]) == 50979.50, (
        "29900 barrels at the 1.705 tier-one rate is 50979.50, got "
        f"{settlement['tariff_charge_usd']}"
    )
    assert float(settlement["alt_basis_charge_usd"]) == 51150.00, (
        "the SCHEDULED counterfactual bills 30000 barrels at 1.705 for 51150.00, got "
        f"{settlement['alt_basis_charge_usd']}"
    )
    assert float(settlement["basis_delta_usd"]) == 170.50, (
        f"51150.00 less 50979.50 is a 170.50 basis delta, got {settlement['basis_delta_usd']}"
    )
    assert float(settlement["total_billed_usd"]) == 50979.50, (
        "transportation plus a zero penalty is 50979.50, got "
        f"{settlement['total_billed_usd']}"
    )
    for money in ("tariff_charge_usd", "alt_basis_charge_usd", "basis_delta_usd", "total_billed_usd"):
        assert_money_precision(settlement[money], money)
    assert settlement["status"] == "DRAFT", (
        f"settlement raises the row as DRAFT, got {settlement['status']}"
    )

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["system_loss_bbl"]) == 100.00, (
        f"line shrinkage is booked to system loss, got {segment['system_loss_bbl']}"
    )


def test_cycle_totals_are_visible_immediately_after_the_nomination_is_accepted(api):
    """There is no settling period anywhere in this service: the very next read after the 201
    already shows the cycle's nominated total at 30000 barrels and its version at 2, and the
    nomination is already present in its listing. That is exactly why the token the next
    submission carries is the one this read returns.

    PRD 2.11: "Cascades are applied immediately and synchronously within the request that triggers
    them; there is no deferred or eventual settling of derived fields, and a read issued
    immediately after a mutating call sees every consequence of it."
    PRD 3.3: "The cycle's `version` increments by one — which is exactly why the next submission
    must re-read it — and the cycle's `nominated_total_bbl`, `allocated_total_bbl` and
    `unallocated_capacity_bbl` are recomputed."
    PRD 3.4: "`nominated_total_bbl` is the sum of `nominated_bbl` over the cycle's nominations
    whose `status` is one of `SUBMITTED`, `ACCEPTED`, `PRORATED`, `REVISION_REQUESTED`, `SCHEDULED`
    or `COMPLETED`; `allocated_total_bbl` is the sum of `allocated_bbl` over that same status set;
    `unallocated_capacity_bbl` is `effective_capacity_bbl` less `allocated_total_bbl`; and
    `proration_factor` is refreshed as described in §3.5."

    Design: Corner/consistency_model/cycle_totals_are_visible_immediately_after_the_nomination_is_accepted
    """
    ctx = setup_open_cycle()
    cycle_id = ctx["cycle"]["id"]
    shipper = ctx["shippers"]["ALPHA"]
    shipper_view = make_shipper_headers(shipper["id"])

    assert int(ctx["cycle"]["version"]) == 1, (
        f"a freshly opened cycle carries version 1, got {ctx['cycle']['version']}"
    )

    nomination = validate_success(
        api.create_nomination(
            create_nomination_payload(
                cycle_id,
                shipper["id"],
                ctx["grades"]["ULSD"]["id"],
                ctx["origin"]["id"],
                ctx["destination"]["id"],
                int(ctx["cycle"]["version"]),
                nominated_bbl=30000,
            ),
            shipper_view,
        ),
        201,
    )

    immediate_read = validate_success(api.get_cycle(cycle_id, shipper_view))
    assert float(immediate_read["nominated_total_bbl"]) == 30000, (
        "the read that immediately follows the submission already carries the 30000 bbl total, "
        f"got {immediate_read['nominated_total_bbl']}"
    )
    assert int(immediate_read["version"]) == 2, (
        "the accepted submission has already incremented the cycle's version, got "
        f"{immediate_read['version']}"
    )
    assert immediate_read["status"] == "OPEN", (
        f"collecting nominations leaves the cycle OPEN, got {immediate_read['status']}"
    )
    assert float(immediate_read["allocated_total_bbl"]) == 0, (
        "no capacity is awarded until the cycle is prorated, got "
        f"{immediate_read['allocated_total_bbl']}"
    )

    listed, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle_id, "limit": 10})
    )
    assert meta["total_count"] == 1, (
        f"the immediate listing already sees the one nomination, got {meta['total_count']}"
    )
    assert listed[0]["id"] == nomination["id"], (
        f"the listed row is the nomination just submitted, got {listed[0]['id']}"
    )
