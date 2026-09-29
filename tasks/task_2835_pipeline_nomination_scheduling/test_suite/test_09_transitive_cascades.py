"""Cascades that travel several hops from the call that triggered them.

One notice on a maintenance event walks from the event to the segment, from the
segment to the cycle, from the cycle to every nomination and from every nomination
to its batch ticket. One withdrawal walks from a nomination to the cycle's totals
and back down into a sibling nomination's allocation.
"""

from test_helpers import (
    SCHEDULER,
    api_client,
    assert_capacity_conservation,
    assert_millisecond_timestamp,
    make_shipper_headers,
    nomination_key,
    prorate_cycle,
    refresh_cycle,
    refresh_nomination,
    refresh_segment,
    refresh_tickets,
    set_clock,
    setup_multi_shipper_cycle,
    ticket_at,
    validate_success,
)

PAIRED_HISTORY = [
    ("ALPHA", 30000, "2026-06-30T00:00:00Z"),
    ("ALPHA", 42000, "2026-07-31T00:00:00Z"),
    ("BRAVO", 20000, "2026-06-30T00:00:00Z"),
    ("BRAVO", 16000, "2026-07-31T00:00:00Z"),
]

ALPHA_KEY = nomination_key("ALPHA", "ULSD")
BRAVO_KEY = nomination_key("BRAVO", "CBOB")


def _barrels(value) -> int:
    return int(round(float(value)))


def _ratio(value) -> float:
    return round(float(value), 6)


def _published_pair():
    """ALPHA 70000 ULSD and BRAVO 50000 CBOB prorated to 60000 / 40000 on a
    published schedule, with the clock standing well clear of the planned work."""
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 70000), ("BRAVO", "CBOB", 50000)],
        grades=("ULSD", "CBOB"),
        history=PAIRED_HISTORY,
        publish=True,
    )
    set_clock("2026-08-25T00:00:00Z", SCHEDULER)
    return ctx


def _plan_and_notify_a_thirty_percent_outage(ctx):
    event = validate_success(
        api_client.create_maintenance_event(
            {
                "segment_id": ctx["segment"]["id"],
                "kind": "PIGGING",
                "window_start": "2026-09-10T00:00:00Z",
                "window_end": "2026-09-12T00:00:00Z",
                "capacity_derate_pct": 0.30,
                "notes": "scraper run through the September batches",
            },
            SCHEDULER,
        ),
        expected_status=201,
    )
    notified = validate_success(
        api_client.notify_maintenance_event(event["id"], SCHEDULER)
    )
    return notified


def test_one_maintenance_notice_derates_the_line_and_resizes_the_published_cycle(api):
    """The notice reaches both shippers, recomputes the segment's derate to 0.30 and
    marks it DERATED, and then re-sizes the September cycle from 100000 bbl to
    69700 bbl of effective capacity — less than it had already promised, so the
    published plan is torn up and the cycle enters RESEQUENCING.

    PRD 3.8: "Hop two derates the line. The segment's `derate_pct` is recomputed as
    the largest `capacity_derate_pct` among the maintenance events on that segment
    whose `status` is `NOTIFIED` or `ACTIVE`, and the segment's `operational_status`
    follows from it: `OPERATIONAL` when no such event applies and the governing
    derate is therefore 0, `DERATED` when the governing derate is strictly between 0
    and 1, and `SHUT` when it is exactly 1."

    PRD 3.8: "Where the recomputed `effective_capacity_bbl` is strictly less than
    `allocated_total_bbl`, the cycle transitions `PUBLISHED → RESEQUENCING`, because
    the carrier can no longer move what it promised."

    Design: Difficulty/transitive_cascade/maintenance_notification_cascades_five_hops_into_resequencing
    """
    ctx = _published_pair()
    assert _barrels(ctx["cycle"]["effective_capacity_bbl"]) == 100000
    assert _barrels(ctx["cycle"]["allocated_total_bbl"]) == 100000

    notified = _plan_and_notify_a_thirty_percent_outage(ctx)

    assert notified["status"] == "NOTIFIED"
    assert_millisecond_timestamp(notified["notified_at"], "notified_at")
    assert notified["notified_at"].startswith("2026-08-25T00:00:00")
    assert int(notified["notified_shipper_count"]) == 2

    segment = refresh_segment(ctx)
    assert round(float(segment["derate_pct"]), 2) == 0.30
    assert segment["operational_status"] == "DERATED"

    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "RESEQUENCING"
    assert _barrels(cycle["effective_capacity_bbl"]) == 69700
    assert _barrels(cycle["allocated_total_bbl"]) == 69700
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 0
    assert _ratio(cycle["proration_factor"]) == 0.580833
    assert _barrels(cycle["total_transmix_bbl"]) == 0
    assert_capacity_conservation(cycle)


def test_the_resequencing_cascade_recuts_both_nominations_and_voids_their_batches(api):
    """Hops four and five reach the leaves: both nominations are re-cut to 41820 and
    27880 bbl and pushed back for revision with their loop counters at 1, both
    batch tickets are voided as RESEQUENCING, and a fresh proration run then returns
    the pair to PRORATED at exactly those derated allocations.

    PRD 3.8: "Hop five clears the physical plan. Every batch ticket of that cycle
    whose `movement_status` is `PLANNED` and whose nomination just moved to
    `REVISION_REQUESTED` transitions `PLANNED → CANCELLED` with `cancel_reason`
    recorded as `RESEQUENCING`."

    PRD 3.5: "Surviving nominations settle into `PRORATED` by one of three hops —
    `ACCEPTED → PRORATED` in the ordinary run, and `SUBMITTED → PRORATED` or
    `REVISION_REQUESTED → PRORATED` when the cycle was `RESEQUENCING` — and the cycle
    itself moves to `PRORATED`."

    Design: Difficulty/transitive_cascade/maintenance_notification_cascades_five_hops_into_resequencing
    """
    ctx = _published_pair()
    _plan_and_notify_a_thirty_percent_outage(ctx)

    alpha = refresh_nomination(ctx, ALPHA_KEY)
    bravo = refresh_nomination(ctx, BRAVO_KEY)
    assert alpha["status"] == "REVISION_REQUESTED"
    assert _barrels(alpha["allocated_bbl"]) == 41820
    assert int(alpha["revision_count"]) == 1
    assert bravo["status"] == "REVISION_REQUESTED"
    assert _barrels(bravo["allocated_bbl"]) == 27880
    assert int(bravo["revision_count"]) == 1

    refresh_tickets(ctx)
    for position in (1, 2):
        ticket = ticket_at(ctx, position)
        assert ticket["movement_status"] == "CANCELLED"
        assert ticket["cancel_reason"] == "RESEQUENCING"

    prorate_cycle(ctx)
    alpha = refresh_nomination(ctx, ALPHA_KEY)
    bravo = refresh_nomination(ctx, BRAVO_KEY)
    cycle = refresh_cycle(ctx)
    assert alpha["status"] == "PRORATED"
    assert _barrels(alpha["allocated_bbl"]) == 41820
    assert bravo["status"] == "PRORATED"
    assert _barrels(bravo["allocated_bbl"]) == 27880
    assert cycle["status"] == "PRORATED"
    assert _barrels(cycle["allocated_total_bbl"]) == 69700
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 0
    assert _ratio(cycle["proration_factor"]) == 0.580833
    assert_capacity_conservation(cycle)


def _prorated_pair():
    """The same pair, stopped at PRORATED so the withdrawal is still permitted."""
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 70000), ("BRAVO", "CBOB", 50000)],
        grades=("ULSD", "CBOB"),
        history=PAIRED_HISTORY,
        prorate=True,
    )


def _withdraw(ctx, key):
    nomination = ctx["nominations"][key]
    return api_client.withdraw_nomination(
        nomination["id"], make_shipper_headers(nomination["shipper_id"])
    )


def test_a_withdrawal_zeroes_its_own_row_and_re_derives_the_cycle_totals(api):
    """BRAVO's withdrawal drops it out of every aggregate: its own allocation goes to
    zero, the cycle's nominated total falls from 120000 to ALPHA's 70000 bbl, and the
    proration factor rises to exactly 1.000000 because nothing is being cut any more.

    PRD 3.3: "Hop one moves the nomination to `WITHDRAWN` and zeroes its
    `allocated_bbl`. Hop two recomputes the cycle's `nominated_total_bbl` and
    `proration_factor` over the surviving nominations."

    Design: Difficulty/transitive_cascade/nomination_withdrawal_cascades_three_hops_into_sibling_allocations
    """
    ctx = _prorated_pair()
    assert _barrels(ctx["cycle"]["nominated_total_bbl"]) == 120000
    assert _ratio(ctx["cycle"]["proration_factor"]) == 0.833333

    validate_success(_withdraw(ctx, BRAVO_KEY))

    bravo = refresh_nomination(ctx, BRAVO_KEY)
    cycle = refresh_cycle(ctx)
    assert bravo["status"] == "WITHDRAWN"
    assert _barrels(bravo["allocated_bbl"]) == 0
    assert _barrels(cycle["nominated_total_bbl"]) == 70000
    assert _ratio(cycle["proration_factor"]) == 1.000000


def test_a_withdrawal_re_runs_the_proration_and_lifts_the_surviving_sibling(api):
    """The third hop is the one that matters commercially: the 40000 bbl BRAVO gave
    back are re-prorated, so ALPHA — which had been cut to 60000 bbl — is rewritten
    to the full 70000 bbl it asked for, while the line's effective capacity is
    untouched and the remaining 30000 bbl stay unallocated.

    PRD 3.3: "Hop three fires only because the cycle is in `PRORATED`: the whole
    proration is re-run and every remaining `PRORATED` nomination's `allocated_bbl`
    is rewritten, because the barrels the withdrawing shipper released are now
    available to shippers whose nominations were cut."

    Design: Difficulty/transitive_cascade/nomination_withdrawal_cascades_three_hops_into_sibling_allocations
    """
    ctx = _prorated_pair()
    assert _barrels(ctx["nominations"][ALPHA_KEY]["allocated_bbl"]) == 60000

    validate_success(_withdraw(ctx, BRAVO_KEY))

    alpha = refresh_nomination(ctx, ALPHA_KEY)
    cycle = refresh_cycle(ctx)
    assert _barrels(alpha["allocated_bbl"]) == 70000
    assert _barrels(cycle["allocated_total_bbl"]) == 70000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 30000
    assert _barrels(cycle["effective_capacity_bbl"]) == 100000
    assert cycle["status"] == "PRORATED"
    assert_capacity_conservation(cycle)
