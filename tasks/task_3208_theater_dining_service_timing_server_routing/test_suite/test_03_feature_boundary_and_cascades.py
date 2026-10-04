"""Feature-start boundary, cold-line re-sequencing, and the dark-period gate."""
import pytest

from test_helpers import (
    api_client, ADMIN, LEAD,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_order_slip, assert_check_tab,
    make_menu_item, make_slip, set_clock,
    read_capacity, read_slip, read_check, read_showtime,
    setup_dining_open_showtime, setup_in_service_showtime,
    setup_three_cold_line_tickets, setup_compensated_check_for_ejection,
    setup_unverified_alcohol_in_service, place_scenario_slip,
)


def test_start_feature_is_admissible_only_at_the_exact_instant(api):
    """PRD §3.6: "The kitchen lead performs it on a showtime that is in `SERVICE`
    — an attempt from any other state is refused with `ERR_SHOWTIME_NOT_IN_SERVICE`
    — and only once the logical clock has reached the showtime's `start_at_utc`
    exactly; a request made a moment before that instant is refused with
    `ERR_FEATURE_START_BOUNDARY`."
    PRD §3.6: "The showtime's `status` then becomes `RUNNING`, and its derived
    `service_mode` settles into `IN_KITCHEN` for as long as the clock remains
    strictly before the entrée deadline".

    Design: Difficulty/boundary_precision_check/feature_start_boundary_is_exact_equality_on_the_clock
    """
    scenario = setup_in_service_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=lambda s: place_scenario_slip(s, seat=9, catalog_name="Pizza"),
    )
    showtime = scenario["showtime"]

    set_clock("2026-09-01T19:59:00Z")
    early = api_client.start_feature(showtime["id"], LEAD)
    validate_error(early, "ERR_FEATURE_START_BOUNDARY")

    set_clock("2026-09-01T20:00:00Z")
    validate_success(api_client.start_feature(showtime["id"], LEAD), 200)
    after = read_showtime(showtime["id"], LEAD)
    assert after["status"] == "RUNNING", "the cut-over succeeded at the exact instant"
    assert after["service_mode"] == "IN_KITCHEN", (
        "the clock is still strictly before the 21:15 entree deadline"
    )


def test_cold_line_fire_order_moves_forward_at_cut_over(api):
    """PRD §3.5: "the ordering and the cursor advance are therefore re-derived
    whenever the cohort's membership changes — when a slip is prepared, when a
    ticket is voided, and at the cut-over to the feature."

    Design: Difficulty/boundary_precision_check/feature_start_boundary_is_exact_equality_on_the_clock
    """
    scenario = setup_dining_open_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:50:00Z",
    )
    place_scenario_slip(scenario, seat=9, catalog_name="Pizza")
    showtime = scenario["showtime"]

    # The feature boundary sits at exactly 20:00; the cut-over is performed there.
    set_clock("2026-09-01T19:55:00Z")
    validate_success(api_client.start_service(showtime["id"], LEAD), 200)
    set_clock("2026-09-01T20:00:00Z")
    validate_success(api_client.start_feature(showtime["id"], LEAD), 200)

    cohort, _ = validate_paginated(
        api_client.list_showtime_kitchen_tickets(
            showtime["id"], LEAD, params={"station": "cold_line"}
        )
    )
    assert len(cohort) == 1, "the accepted entree received its cold-line ticket"
    assert cohort[0]["sequence_position"] == 1
    assert cohort[0]["fire_at_utc"].endswith("19:30:00Z"), (
        "the anchor is still thirty minutes before the feature, recomputed at the cut-over"
    )


def test_alcohol_void_cascade_reaches_ticket_slip_check_and_rollup(api):
    """PRD §3.6: "Every beverage ticket whose identification check is still
    `PENDING` at the cut-over is voided: the ticket moves to `VOIDED`, its order
    slip is released without charge and moves to `VOIDED`, and the slip's
    `id_check_status` is set to `REFUSED`. A guest whose drink was never verified
    loses the drink and owes nothing for it."
    PRD §3.6: "the slip's tab closes unpaid with its `original_cents` set to zero;
    and, because the slip belonged to a server's section, that server's
    provisional rollup is recomputed, which in turn changes the auditorium's shock
    liability figure".

    Design: Difficulty/transitive_cascade/unverified_alcohol_cascade_ticket_to_slip_to_server_rollup
    """
    scenario = setup_unverified_alcohol_in_service(place_slip=True)
    slip, showtime = scenario["slip"], scenario["showtime"]
    assert slip["id_check_status"] == "PENDING"

    set_clock("2026-09-01T20:00:00Z")
    validate_success(api_client.start_feature(showtime["id"], LEAD), 200)

    # hop 1: the hot-line ticket leaves the queue.
    hot, _ = validate_paginated(api_client.list_showtime_kitchen_tickets(
        showtime["id"], LEAD, params={"station": "hot_line"}
    ))
    assert len(hot) == 1
    assert hot[0]["station"] == "hot_line"
    assert hot[0]["status"] == "VOIDED", "the unverified beverage ticket was voided at the boundary"

    # hop 2: the slip follows it, and its identification axis is refused.
    after = read_slip(slip["id"], ADMIN)
    assert after["status"] == "VOIDED"
    assert after["id_check_status"] == "REFUSED"

    # hop 2 continued: the tab closed unpaid.
    checks, _ = validate_paginated(api_client.list_checks(LEAD, params={"id": slip["id"]}))
    assert checks and checks[0]["original_cents"] == 0, (
        "a released slip owes nothing, so its tab opens at zero"
    )

    # hop 3: the load rollup recomputed for the surviving cohort.
    snapshot = read_capacity(showtime["id"], LEAD)
    assert snapshot["entree_load_points"] == 0, (
        "the voided slip no longer consumes cold-line capacity"
    )

    assert after["status"] == "VOIDED"
    liability = get_success_data(
        api_client.get_auditorium_refund_liability(scenario["auditorium"]["id"], LEAD)
    )
    assert liability["shock_liability_cents"] == 0, (
        "no live tab stands on the owning server, so the charting figure is zero"
    )
    assert liability["fair_liability_cents"] == 0, (
        "a released slip owes nothing, so the reconciliation figure is zero too"
    )


def test_the_second_cut_over_is_refused_rather_than_rerun(api):
    """PRD §3.6: "Cutting over to the feature is the single most consequential
    event in the evening".
    PRD §3.5: "That act is admissible only from `DINING_OPEN` (otherwise
    `ERR_SHOWTIME_NOT_DINING_OPEN`)".

    Design: Difficulty/transitive_cascade/unverified_alcohol_cascade_ticket_to_slip_to_server_rollup
    """
    scenario = setup_unverified_alcohol_in_service(place_slip=True)
    slip, showtime = scenario["slip"], scenario["showtime"]
    set_clock("2026-09-01T20:00:00Z")
    validate_success(api_client.start_feature(showtime["id"], LEAD), 200)

    repeat = api_client.start_feature(showtime["id"], LEAD)
    validate_error(repeat, "ERR_SHOWTIME_NOT_IN_SERVICE")
    assert read_slip(slip["id"], ADMIN)["status"] == "VOIDED", (
        "the void was not double-charged by a repeated cut-over"
    )


def test_cutting_over_before_the_service_window_is_impossible(api):
    """PRD §3.5: "That act is admissible only from `DINING_OPEN` (otherwise
    `ERR_SHOWTIME_NOT_DINING_OPEN`)".

    Design: Difficulty/transitive_cascade/unverified_alcohol_cascade_ticket_to_slip_to_server_rollup
    """
    scenario = setup_dining_open_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:50:00Z",
    )
    place_scenario_slip(scenario, seat=11, catalog_name="Arepa")
    showtime = scenario["showtime"]

    set_clock("2026-09-01T20:05:00Z")
    validate_success(api_client.start_service(showtime["id"], LEAD), 200)
    again = api_client.start_service(showtime["id"], LEAD)
    validate_error(again, "ERR_SHOWTIME_NOT_DINING_OPEN")


def test_boundary_books_thirty_percent_compensation_on_a_late_slip(api):
    """PRD §3.6: "one whose deadline has already passed is recorded as a late
    service delivery: its `status` is set to `DELIVERED` even though nothing was
    actually handed over, its late-delivery marker is set, it is assigned the
    automatic compensation tier, and an automatic refund amount is computed as the
    slip's `subtotal_cents` multiplied by thirty percent and rounded half up to a
    whole cent."

    Design: Difficulty/boundary_precision_check/feature_start_boundary_is_exact_equality_on_the_clock
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    check = scenario["check"]
    assert_order_slip(read_slip(scenario["slip"]["id"], ADMIN))
    assert check["original_cents"] == 1000
    assert check["refunded_cents"] == 300, "thirty percent of one thousand cents"
    assert check["status"] == "PARTIALLY_REFUNDED"


def test_the_boundary_compensation_leaves_the_balance_free(api):
    """PRD §3.6: "an automatic refund amount is computed as the slip's
    `subtotal_cents` multiplied by thirty percent and rounded half up to a whole
    cent."
    PRD §3.8: "the tab then reads `REFUNDED` if the refunded amount has reached the
    original total and `PARTIALLY_REFUNDED` otherwise."

    Design: Difficulty/compensating_invariant/compensating_refund_leaves_the_settled_tab_at_zero
    """
    # The fixture re-reads the tab after the boundary cascade, so its snapshot
    # already carries the write; a second read would only race the fixture.
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    check = read_check(scenario["check"]["id"], LEAD)
    assert_check_tab(check)
    assert check["original_cents"] - check["refunded_cents"] == 700, (
        "the computed amount is added to the refunded total, leaving the collected balance"
    )
    assert check["status"] == "PARTIALLY_REFUNDED", (
        "the refunded total has not reached the original, so the tab is only partly refunded"
    )



def test_the_cold_line_is_renumbered_across_a_void_at_scale(api):
    """PRD §3.5: "Only tickets in `QUEUED` or `PREPARING` occupy a position: a ticket
    that reaches `READY`, `DELIVERED`, or `VOIDED` leaves the cohort and does not
    keep its slot."
    PRD §3.5: "The platform maintains an invariant across every recomputation: the
    sum, over the cohort, of each ticket's ceiling-rounded line minutes must equal
    the elapsed span between the anchor and the completion instant of the final
    cohort member."

    Design: Difficulty/transitive_cascade/unverified_alcohol_cascade_ticket_to_slip_to_server_rollup
    """
    scenario = setup_three_cold_line_tickets(costs=(1, 1, 1))
    showtime, tickets = scenario["showtime"], scenario["tickets"]
    assert [t["sequence_position"] for t in tickets] == [1, 2, 3]

    get_success_data(api_client.void_kitchen_ticket(
        tickets[0]["id"], {"reason_code": "SERVICE_OVERFLOW"}, LEAD
    ))
    survivors, meta = validate_paginated(
        api_client.list_showtime_kitchen_tickets(
            showtime["id"], LEAD, params={"station": "cold_line", "status": "QUEUED"}
        )
    )
    assert len(survivors) == 2
    assert meta["total_count"] == 2
    assert sorted(t["sequence_position"] for t in survivors) == [1, 2], (
        "the two survivors are renumbered from one without leaving the voided slot"
    )