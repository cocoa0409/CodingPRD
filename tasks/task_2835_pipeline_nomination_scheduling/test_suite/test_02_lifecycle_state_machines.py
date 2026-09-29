"""Lifecycle state machines: cycles, nominations, tariffs, batch tickets,
maintenance events and settlements.

Each test drives one declared transition — or one refused transition — and then
re-reads every row the PRD says the call touches, so that a cascade stopping at
its first hop is visible. Every test builds its own network, shippers, tariffs
and cycle from scratch.
"""

import pytest

from test_helpers import (
    ADMIN,
    CERTIFIER,
    CERTIFIER_USER_ID,
    INVOICER,
    OPERATOR,
    SCHEDULER,
    SECOND_CERTIFIER,
    ApiErrorId,
    add_tariff,
    assert_batch_ticket,
    assert_capacity_conservation,
    assert_cycle,
    assert_maintenance_event,
    assert_millisecond_timestamp,
    assert_nomination,
    assert_settlement,
    assert_tariff,
    create_nomination_payload,
    create_tariff_payload,
    deliver_payload,
    get_success_data,
    invoice_payload,
    make_shipper_headers,
    nomination_key,
    plan_maintenance,
    refresh_cycle,
    setup_closed_cycle,
    setup_cycle_with_nomination,
    setup_draft_settlement,
    setup_network,
    setup_published_cycle,
    setup_scheduled_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


# ------------------------------------------- the nomination cycle's own ladder


def test_closing_the_nomination_window_pins_the_rate_and_sizes_the_line(api):
    """PRD 3.4: "A `PipelineScheduler` closing a cycle drives it `OPEN → CLOSED`,
    and the action is refused with `ERR_CYCLE_INVALID_STATE` from any other
    status."
    PRD 3.4: "A nomination whose `nominated_bbl` is at least its pinned
    `tender_minimum_bbl` moves `SUBMITTED → ACCEPTED` with `pinned_tariff_id`
    frozen."
    PRD 3.4: "Third, the linefill make-up is subtracted from that truncated
    figure, and then the segment's `transmix_reserve_bbl` is subtracted as well."
    PRD 3.5: "Every proration run closes by recomputing the cycle's
    `nominated_total_bbl` first, then `allocated_total_bbl` as the sum of the
    allocations, then `unallocated_capacity_bbl` as `effective_capacity_bbl` less
    `allocated_total_bbl`, and finally `proration_factor` as
    `allocated_total_bbl` divided by `nominated_total_bbl` rounded half up to six
    decimal places — or exactly 1.000000 when `nominated_total_bbl` is zero."

    Design: Corner/state_machines/cycle_close_moves_open_to_closed_and_pins_the_effective_tariff
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000)
    nomination = ctx["nominations"][nomination_key("ALPHA")]
    ulsd_tariff = ctx["tariffs"]["ULSD"]

    closed = validate_success(api.close_cycle(ctx["cycle"]["id"], SCHEDULER))

    assert_cycle(closed)
    assert closed["status"] == "CLOSED", f"close must reach CLOSED, got {closed['status']}"
    # 101000 bbl of nameplate at a zero derate, linefill already at requirement,
    # less the segment's 1000 bbl transmix reserve.
    assert int(closed["effective_capacity_bbl"]) == 100000
    assert float(closed["derate_pct_applied"]) == 0
    assert float(closed["nominated_total_bbl"]) == 30000
    assert int(closed["allocated_total_bbl"]) == 0
    assert int(closed["unallocated_capacity_bbl"]) == 100000
    assert float(closed["proration_factor"]) == pytest.approx(0.0, abs=0.0000005)
    assert_capacity_conservation(closed)

    accepted = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert_nomination(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["pinned_tariff_id"] == ulsd_tariff["id"], (
        "the close pins the only EFFECTIVE tariff covering the closing instant"
    )
    assert accepted["rejection_reason"] is None
    assert int(accepted["allocated_bbl"]) == 0


def test_closing_an_already_closed_cycle_is_refused(api):
    """PRD 3.4: "A `PipelineScheduler` closing a cycle drives it `OPEN → CLOSED`,
    and the action is refused with `ERR_CYCLE_INVALID_STATE` from any other
    status."
    PRD 3.2: "The winner's identifier is written to the nomination's
    `pinned_tariff_id` and is never rewritten afterwards."

    Design: Corner/state_machines/cycle_close_from_closed_state_rejected
    """
    ctx = setup_closed_cycle(nominated_bbl=30000)
    nomination = ctx["nominations"][nomination_key("ALPHA")]
    pinned_before = nomination["pinned_tariff_id"]

    validate_error(
        api.close_cycle(ctx["cycle"]["id"], SCHEDULER),
        ApiErrorId.ERR_CYCLE_INVALID_STATE.value,
    )

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "CLOSED", "the refused second close leaves the cycle CLOSED"
    assert int(cycle["effective_capacity_bbl"]) == 100000
    assert_capacity_conservation(cycle)

    unchanged = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["pinned_tariff_id"] == pinned_before, (
        "a rate once pinned is not re-pinned by a refused close"
    )


def test_prorating_before_the_window_closes_is_refused(api):
    """PRD 3.5: "A `PipelineScheduler` may prorate a cycle from exactly two
    states — `CLOSED → PRORATED` in the ordinary case, and
    `RESEQUENCING → PRORATED` after a maintenance derate has torn a published
    schedule apart — and any other from-state is refused with
    `ERR_CYCLE_INVALID_STATE`."
    PRD 3.3: "The new nomination itself starts with `status` of `SUBMITTED`,
    `revision_count` of 0, `allocated_bbl` of 0, `history_base_bbl` of 0,
    `allocation_class` of `NEW_SHIPPER`, `pinned_tariff_id` of null and
    `rejection_reason` of null."

    Design: Corner/state_machines/cycle_prorate_from_open_state_rejected
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000)
    nomination = ctx["nominations"][nomination_key("ALPHA")]

    validate_error(
        api.prorate_cycle(ctx["cycle"]["id"], SCHEDULER),
        ApiErrorId.ERR_CYCLE_INVALID_STATE.value,
    )

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "OPEN", "the window must close before proration runs"
    assert int(cycle["effective_capacity_bbl"]) == 0, (
        "the line is only sized at close, so an OPEN cycle still reads 0"
    )

    untouched = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert untouched["status"] == "SUBMITTED"
    assert int(untouched["allocated_bbl"]) == 0
    assert float(untouched["history_base_bbl"]) == 0
    assert untouched["pinned_tariff_id"] is None


# ------------------------------------- the twin key and the nomination's escape


def test_second_nomination_on_the_twin_key_supersedes_the_first(api):
    """PRD 3.3: "Where the submission is accepted, the newest surviving twin that
    is in `SUBMITTED` or in `ACCEPTED` transitions `SUBMITTED → SUPERSEDED` or
    `ACCEPTED → SUPERSEDED` and has its `allocated_bbl` set to 0, and the new
    row's `supersedes_nomination_id` points at it."
    PRD 3.3: "Either way a `SUPERSEDED` nomination is terminal and is excluded
    from the cycle's `nominated_total_bbl`."
    PRD 3.3: "The cycle's `version` increments by one — which is exactly why the
    next submission must re-read it — and the cycle's `nominated_total_bbl`,
    `allocated_total_bbl` and `unallocated_capacity_bbl` are recomputed."

    Design: Corner/state_machines/nomination_twin_key_supersedes_the_prior_submitted_row
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000)
    retired_row = ctx["nominations"][nomination_key("ALPHA")]
    alpha = ctx["shippers"]["ALPHA"]

    # Re-read the cycle so the replacement carries a fresh view of its version.
    cycle_before = refresh_cycle(ctx)

    replacement = validate_success(
        api.create_nomination(
            create_nomination_payload(
                cycle_before["id"],
                alpha["id"],
                ctx["grades"]["ULSD"]["id"],
                ctx["origin"]["id"],
                ctx["destination"]["id"],
                cycle_before["version"],
                nominated_bbl=25000,
            ),
            make_shipper_headers(alpha["id"]),
        ),
        201,
    )

    assert_nomination(replacement)
    assert replacement["status"] == "SUBMITTED"
    assert float(replacement["nominated_bbl"]) == 25000
    assert replacement["supersedes_nomination_id"] == retired_row["id"], (
        "the replacement points at the row it retires"
    )

    retired = validate_success(api.get_nomination(retired_row["id"], SCHEDULER))
    assert retired["status"] == "SUPERSEDED"
    assert int(retired["allocated_bbl"]) == 0

    cycle = validate_success(api.get_cycle(cycle_before["id"], SCHEDULER))
    assert float(cycle["nominated_total_bbl"]) == 25000, (
        "the superseded row drops out rather than adding its barrels"
    )
    # Version 1 at open, then one increment per accepted submission.
    assert int(cycle["version"]) == 3


def test_withdrawing_after_the_schedule_is_built_is_refused(api):
    """PRD 3.3: "A `PRORATED` nomination may be withdrawn only while its cycle is
    exactly `PRORATED`."
    PRD 3.3: "A withdrawal attempted with the cycle outside the state allowed for
    that from-state is refused with `ERR_NOMINATION_LOCKED`, and a withdrawal
    attempted from any other nomination status is refused with
    `ERR_NOMINATION_INVALID_STATE`."

    Design: Corner/state_machines/nomination_withdraw_after_schedule_build_rejected
    """
    ctx = setup_scheduled_cycle(nominated_bbl=30000)
    nomination = ctx["nominations"][nomination_key("ALPHA")]
    alpha = ctx["shippers"]["ALPHA"]

    validate_error(
        api.withdraw_nomination(nomination["id"], make_shipper_headers(alpha["id"])),
        ApiErrorId.ERR_NOMINATION_LOCKED.value,
    )

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "SCHEDULED", (
        "the carrier has already committed volume, so the cycle is past PRORATED"
    )
    assert int(cycle["allocated_total_bbl"]) == 30000
    assert int(cycle["unallocated_capacity_bbl"]) == 70000
    assert_capacity_conservation(cycle)

    held = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert held["status"] == "PRORATED", "the refused withdrawal changes no state"
    assert int(held["allocated_bbl"]) == 30000, "the allocation is left untouched"


# ---------------------------------------------------- the tariff catalogue


def test_activating_a_newer_tariff_supersedes_the_overlapping_effective_rate(api):
    """PRD 3.2: "Activation also has a cascade: every *other* tariff for the same
    `segment_id` and `grade_id` that is currently `EFFECTIVE` and whose
    effectivity interval overlaps the newly activated one moves
    `EFFECTIVE → SUPERSEDED`."
    PRD 3.2: "That is the only way a tariff reaches `SUPERSEDED`, and it is a
    terminal state."

    Design: Corner/state_machines/tariff_activation_supersedes_the_overlapping_effective_tariff
    """
    ctx = setup_network(grades=("ULSD",))
    incumbent = add_tariff(ctx, "ULSD")

    challenger = get_success_data(
        api.create_tariff(
            create_tariff_payload(
                ctx["segment"]["id"],
                ctx["grades"]["ULSD"]["id"],
                base_rate_usd_per_bbl=1.955,
                tier1_rate_usd_per_bbl=1.805,
                tier2_rate_usd_per_bbl=1.655,
                imbalance_penalty_rate_usd_per_bbl=0.50,
                effective_from="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        )
    )
    assert challenger["status"] == "DRAFT", "a newly drafted tariff begins as DRAFT"

    activated = validate_success(api.activate_tariff(challenger["id"], ADMIN))
    assert_tariff(activated)
    assert activated["status"] == "EFFECTIVE"

    retired = validate_success(api.get_tariff(incumbent["id"], ADMIN))
    assert retired["status"] == "SUPERSEDED", (
        "the open-ended incumbent overlaps the newly activated interval"
    )

    rows, meta = validate_paginated(
        api.list_tariffs(
            ADMIN,
            params={
                "segment_id": ctx["segment"]["id"],
                "grade_id": ctx["grades"]["ULSD"]["id"],
                "status": "EFFECTIVE",
                "limit": 10,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one rate should survive as a pinning candidate, got {meta['total_count']}"
    )
    assert rows[0]["id"] == challenger["id"]


def test_activating_an_effective_tariff_a_second_time_is_refused(api):
    """PRD 3.2: "Activation by a `TariffAdministrator` moves `DRAFT → EFFECTIVE`;
    activation from any other status is refused with `ERR_TARIFF_INVALID_STATE`."
    PRD 3.2: "Activation also has a cascade: every *other* tariff for the same
    `segment_id` and `grade_id` that is currently `EFFECTIVE` and whose
    effectivity interval overlaps the newly activated one moves
    `EFFECTIVE → SUPERSEDED`."

    Design: Corner/state_machines/tariff_activate_twice_rejected
    """
    ctx = setup_network(grades=("ULSD",))
    tariff = add_tariff(ctx, "ULSD")
    assert tariff["status"] == "EFFECTIVE", "the first activation must have landed"

    validate_error(
        api.activate_tariff(tariff["id"], ADMIN),
        ApiErrorId.ERR_TARIFF_INVALID_STATE.value,
    )

    still_effective = validate_success(api.get_tariff(tariff["id"], ADMIN))
    assert still_effective["status"] == "EFFECTIVE", (
        "the cascade names every *other* tariff, so a rate never supersedes itself"
    )


# ------------------------------------ the batch ticket's two status dimensions


def test_delivering_a_planned_batch_before_injection_is_refused(api):
    """PRD 3.7: "The ticket's `movement_status` must be `INJECTED`, or the attempt
    is refused with `ERR_TICKET_INVALID_STATE`."
    PRD 3.6: "A new ticket's `measured_sulfur_ppm`, `measured_rvp_psi`,
    `injected_bbl`, `delivered_bbl` and `cancel_reason` are all null, and its
    `retest_count` is 0."
    PRD 3.1: "A newly registered terminal starts with `inventory_bbl` of 0 and
    `version` of 1."

    Design: Corner/state_machines/batch_ticket_deliver_from_planned_rejected
    """
    ctx = setup_published_cycle(nominated_bbl=30000)
    ticket = ctx["tickets"][0]

    validate_error(
        api.deliver_batch(ticket["id"], deliver_payload(29900), OPERATOR),
        ApiErrorId.ERR_TICKET_INVALID_STATE.value,
    )

    unmoved = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert_batch_ticket(unmoved)
    assert unmoved["movement_status"] == "PLANNED", "delivery cannot precede injection"
    assert unmoved["quality_status"] == "PENDING", (
        "the quality dimension is untouched by a refused delivery"
    )
    assert unmoved["injected_bbl"] is None
    assert unmoved["delivered_bbl"] is None

    destination = validate_success(api.get_terminal(ctx["destination"]["id"], SCHEDULER))
    assert float(destination["inventory_bbl"]) == 0, "no barrels reached the delivery tank"

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["in_transit_bbl"]) == 0
    assert float(segment["system_loss_bbl"]) == 0, "no shrinkage is booked by a refusal"


# ------------------------------------------- integrity work and the line derate


def test_completing_maintenance_returns_the_segment_to_operational(api):
    """PRD 3.8: "`notified_at` takes the logical clock, and
    `notified_shipper_count` takes the size of the **notification scope**: the
    number of distinct shippers the notice reaches."
    PRD 3.8: "The segment's `derate_pct` is recomputed as the largest
    `capacity_derate_pct` among the maintenance events on that segment whose
    `status` is `NOTIFIED` or `ACTIVE`, and the segment's `operational_status`
    follows from it: `OPERATIONAL` when no such event applies and the governing
    derate is therefore 0, `DERATED` when the governing derate is strictly between
    0 and 1, and `SHUT` when it is exactly 1."
    PRD 3.8: "Completing the work moves the event `ACTIVE → COMPLETED`, again
    requiring the declared from-state, and restores capacity: the segment's
    `derate_pct` is recomputed over whatever `NOTIFIED` or `ACTIVE` events remain,
    and its `operational_status` returns to `OPERATIONAL` when none do."

    Design: Corner/state_machines/maintenance_complete_returns_segment_to_operational
    """
    ctx = setup_network(grades=("ULSD",))
    event = plan_maintenance(
        ctx,
        kind="PIGGING",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-12T00:00:00Z",
        capacity_derate_pct=0.30,
        notes="scheduled cleaning pig run",
    )

    notified = validate_success(api.notify_maintenance_event(event["id"], SCHEDULER))
    assert_maintenance_event(notified)
    assert notified["status"] == "NOTIFIED"
    assert_millisecond_timestamp(notified["notified_at"], "notified_at")
    assert notified["notified_at"] == "2026-08-01T00:00:00.000Z", (
        "the notice is stamped from the logical clock"
    )
    assert int(notified["notified_shipper_count"]) == 0, (
        "no cycle exists on the segment, so the notice reaches no shipper"
    )

    derated = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(derated["derate_pct"]) == pytest.approx(0.30, abs=0.005)
    assert derated["operational_status"] == "DERATED"

    started = validate_success(api.start_maintenance_event(event["id"], SCHEDULER))
    assert started["status"] == "ACTIVE"
    during = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(during["derate_pct"]) == pytest.approx(0.30, abs=0.005), (
        "the derate stays in force across NOTIFIED → ACTIVE"
    )
    assert during["operational_status"] == "DERATED", "0.30 is not 1, so never SHUT"

    completed = validate_success(api.complete_maintenance_event(event["id"], SCHEDULER))
    assert completed["status"] == "COMPLETED"
    restored = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(restored["derate_pct"]) == 0, "no NOTIFIED or ACTIVE event remains"
    assert restored["operational_status"] == "OPERATIONAL"


def test_starting_maintenance_before_the_notice_is_refused(api):
    """PRD 3.8: "Starting the work moves the event `NOTIFIED → ACTIVE` and
    requires the `NOTIFIED` status, otherwise `ERR_MAINTENANCE_INVALID_STATE`."
    PRD 3.8: "A new event's `status` is `PLANNED`, its `notified_at` is null and
    its `notified_shipper_count` is 0."
    PRD 3.8: "A `PLANNED` event derates nothing yet — planning work is not the
    same as telling shippers about it."

    Design: Corner/state_machines/maintenance_start_from_planned_rejected
    """
    ctx = setup_network(grades=("ULSD",))
    event = plan_maintenance(
        ctx,
        kind="HYDROTEST",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-12T00:00:00Z",
        capacity_derate_pct=1.00,
    )
    assert event["status"] == "PLANNED"

    validate_error(
        api.start_maintenance_event(event["id"], SCHEDULER),
        ApiErrorId.ERR_MAINTENANCE_INVALID_STATE.value,
    )

    unnotified = validate_success(api.get_maintenance_event(event["id"], SCHEDULER))
    assert unnotified["status"] == "PLANNED", "the common carrier notice is a prerequisite"
    assert unnotified["notified_at"] is None

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["derate_pct"]) == 0, "a PLANNED event derates nothing"
    assert segment["operational_status"] == "OPERATIONAL", (
        "a 1.00 derate only shuts the line once the notice has been issued"
    )


# ------------------------------------------- the settlement chain's terminal end


def test_certifying_an_invoiced_settlement_is_refused(api):
    """PRD 3.9: "A `PipelineScheduler` certifies a settlement, driving it
    `DRAFT → CERTIFIED`; certification from any other status is refused with
    `ERR_SETTLEMENT_INVALID_STATE`, and certification by the very operator whose
    `X-User-ID` was recorded in the cycle's `schedule_published_by_user_id` is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "A successful certification records the certifier's `X-User-ID` in
    `certified_by_user_id`."
    PRD 3.9: "Invoicing stores the `invoice_number` and recomputes the billed
    shipper's `exposure_usd` one last time."
    PRD 3.9: "Settlement stamps the cycle's `settled_at` with the logical clock,
    reconciles the segment's `system_loss_bbl`, moves every nomination of the cycle
    still in `SCHEDULED` whose tickets have all reached `DELIVERED` along the
    `SCHEDULED → COMPLETED` hop, and recomputes `exposure_usd` for every billed
    shipper — which, since the cycle is now `SETTLED`, drops its tickets out of
    exposure entirely."

    Design: Corner/state_machines/settlement_certify_after_invoice_rejected
    """
    ctx = setup_draft_settlement(basis_mode="DELIVERED")
    settlement = ctx["settlements"][0]
    nomination = ctx["nominations"][nomination_key("ALPHA")]

    # The publishing operator is a different scheduler, so duty separation holds.
    certified = get_success_data(api.certify_settlement(settlement["id"], CERTIFIER))
    assert certified["status"] == "CERTIFIED"
    invoiced = get_success_data(
        api.invoice_settlement(
            settlement["id"], invoice_payload("INV-2026-09-001"), INVOICER
        )
    )
    assert invoiced["status"] == "INVOICED"

    validate_error(
        api.certify_settlement(settlement["id"], SECOND_CERTIFIER),
        ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value,
    )

    final = validate_success(api.get_settlement(settlement["id"], SCHEDULER))
    assert_settlement(final)
    assert final["status"] == "INVOICED", "INVOICED is terminal"
    assert final["certified_by_user_id"] == CERTIFIER_USER_ID, (
        "the refused re-certification does not overwrite the original certifier"
    )
    assert final["invoice_number"] == "INV-2026-09-001", (
        "the stored invoice number survives the refusal"
    )

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "SETTLED"
    billed = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert billed["status"] == "COMPLETED", (
        "the nomination whose ticket was delivered completed at settlement"
    )
