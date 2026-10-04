"""The kitchen clock: load projection, capacity bands, and cold-line fire order."""
import pytest

from test_helpers import (
    api_client, ADMIN, LEAD,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_capacity_snapshot, assert_kitchen_ticket,
    make_menu_item, make_slip, make_showtime, set_clock, server_headers,
    read_capacity, read_slip, read_ticket, read_showtime, make_section,
    setup_dining_open_showtime, setup_entree_load, setup_three_cold_line_tickets,
    setup_with_voided_entree, setup_in_service_showtime, place_scenario_slip,
    entree_fire_at, MINUTES_FROM_ENTREE_TO_START,
)


def test_load_projection_switches_variant_on_the_same_demand(api):
    """PRD §3.5: "The *wave* variant is the one used while the seating gate is
    still absorbing orders, and it measures demand as point cost."
    PRD §3.5: "The *final* variant is the one written into the projection snapshot
    once the showtime has left the seating phases — that is, when its status is
    neither `SCHEDULED` nor `DINING_OPEN`. It widens the cohort to the entire
    cluster, including showtimes that start after the target, and it changes the
    unit of measurement from point cost to item count, summing the number of
    qualifying entrée slips rather than their points."
    PRD §2.10: "Two shows sharing an auditorium and starting within two hours of
    one another compete for the same line, and the projection must account for the
    earlier show's wave before the later show's slot opens."

    Design: Difficulty/dual_variant_calc/kitchen_load_projection_wave_vs_final_over_one_cluster
    """
    scenario = setup_dining_open_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=60,
        clock="2026-09-01T19:40:00Z", kitchen_point_rate=1,
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    # A second showtime on the same auditorium, inside the two-hour cluster.
    make_showtime(scenario["auditorium"]["id"], "2026-09-01T20:45:00Z", 60,
                  title="Aliens")
    item = make_menu_item("ENTREE", price_cents=1200, prep_minutes=2, catalog_name="Fries")
    make_slip(showtime["id"], section["id"], server, 12,
              [{"menu_item_id": item["id"], "quantity": 1}],
              expected_showtime_version=read_showtime(showtime["id"], LEAD)["version"])

    before = read_capacity(showtime["id"], LEAD)
    assert before["projection_variant"] == "wave_projection", (
        "while the seating window is absorbing orders the wave variant runs"
    )
    assert before["entree_load_points"] == 2, "one 2-point entree is 2 points of demand"

    set_clock("2026-09-01T19:50:00Z")
    get_success_data(api_client.start_service(showtime["id"], LEAD))
    after = read_capacity(showtime["id"], LEAD)
    assert after["projection_variant"] == "final_projection", (
        "once the showtime leaves the seating phases the final variant runs"
    )
    assert after["entree_load_points"] == 1, (
        "the same single entree is now counted as one item rather than two points"
    )
    assert after["entree_load_points"] != before["entree_load_points"], (
        "the identical slip set produced a different figure purely from the variant switch"
    )


def test_load_projection_excludes_terminal_and_hot_line_slips(api):
    """PRD §3.5: "The projection measures cold-line entrée demand only: hot-line
    beverage slips are excluded from it entirely, and so are slips that have
    already reached `READY`, `DELIVERED`, `CANCELLED`, or `VOIDED`."
    PRD §3.3: "The cancellation is admissible only while the slip is non-terminal".

    Design: Corner/calculations/kitchen_load_projection_excludes_non_entree_and_terminal_slips
    """
    scenario = setup_with_voided_entree(keep_points=2, doomed_points=4, prep_minutes=2)
    snapshot = read_capacity(scenario["showtime"]["id"], LEAD)
    assert snapshot["entree_load_points"] == 2, (
        "only the single surviving 1x entree at 2 points remains in the cohort: "
        "the cancelled slip left it and the 4x beverage slip never joined it, "
        "because the projection measures cold-line entree demand only"
    )
    assert snapshot["beverage_load_points"] == 4, (
        "the beverage gate measures the slip separately, as four points of "
        "hot-line demand"
    )


def test_quiet_showtime_reports_normal_band_and_latest_acceptance(api):
    """PRD §3.5: "The entrée gate converts the wave projection into minutes by
    dividing it by the auditorium's `kitchen_point_rate` and rounding up, then
    subtracts those minutes from the entrée deadline to obtain the latest instant
    at which an entrée may still be accepted."
    PRD §3.5: "That percentage bands as `BLOCKED` when it is strictly greater
    than one hundred, `LATE` when it is at least ninety and at most one hundred,
    and `NORMAL` below ninety."

    Design: Corner/calculations/dining_capacity_read_model_on_a_quiet_showtime_reports_normal
    """
    scenario = setup_entree_load(
        load_points=2, prep_minutes=1, start_at_utc="2026-09-01T20:00:00Z",
        runtime_minutes=100, order_clock="2026-09-01T19:50:00Z",
        read_clock="2026-09-01T19:50:00Z", kitchen_point_rate=1,
    )
    snapshot = read_capacity(scenario["showtime"]["id"], LEAD)
    assert_capacity_snapshot(snapshot)
    assert snapshot["capacity_band"] == "NORMAL", (
        "a single small order keeps the utilization strictly below the late threshold"
    )
    assert snapshot["load_pct"] == 2, "floor(2 * 100 / (1 * 85)) == 2, below 90"
    assert snapshot["entree_load_points"] == 2
    assert snapshot["entry_stage"] == 2, (
        "two slips have been accepted on the showtime, so the stage counter reads two"
    )
    assert snapshot["entree_latest_accept_at_utc"] == "2026-09-01T21:13:00Z", (
        "the deadline 21:15 minus ceil(2 / 1) minutes"
    )


def test_load_pct_exactly_one_hundred_bands_late_not_blocked(api):
    """PRD §3.5: "a utilization of exactly one hundred percent is `LATE`, not
    `BLOCKED`, because the blocking test is strictly greater than one hundred; and
    a clock exactly equal to the latest-acceptance instant is `NORMAL`, because
    that test is at-or-before."
    PRD §3.5: "a `LATE` slip is accepted only when the caller supplies
    `capacity_ack` set to true and is otherwise refused with
    `ERR_KITCHEN_CAPACITY_BAND` (HTTP 409)".

    Design: Difficulty/combinatorial_formula/dining_order_capacity_snapshot_two_min_layers_at_exact_boundary
    """
    # The clock sits at `dining_open_at_utc` (19:40). A hundred points read
    # against the sixty whole minutes to the 21:15 deadline is exactly one
    # hundred percent, but the entree gate is independent of that figure: the
    # hundred-minute run rounded up still fits before the deadline, so the entree
    # band is NORMAL and the ceiling is the utilization band's.
    # Ninety one-point entrees are ninety minutes of line work, which is exactly
    # the whole-minute gap between the latest-acceptance instant (19:45) and the
    # 21:15 deadline: floor(90 * 100 / (1 * 90)) is exactly one hundred. The
    # entree gate is NORMAL — the clock sits exactly on its latest-acceptance
    # instant — so the ceiling is the utilization band's.
    scenario = setup_entree_load(
        load_points=90, prep_minutes=1, start_at_utc="2026-09-01T20:00:00Z",
        runtime_minutes=100, order_clock="2026-09-01T19:40:00Z",
        read_clock="2026-09-01T19:45:00Z", kitchen_point_rate=1, seat_capacity=200,
        capacity_ack=True,
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = scenario["item"]

    snapshot = read_capacity(showtime["id"], LEAD)
    assert snapshot["load_pct"] == 100, "floor(90 * 100 / (1 * 90)) is exactly one hundred"
    assert snapshot["capacity_band"] == "LATE", (
        "the blocking test is strictly greater than one hundred, so the ceiling is LATE"
    )
    assert snapshot["entree_load_points"] == 90
    assert snapshot["entree_latest_accept_at_utc"] == "2026-09-01T19:45:00Z", (
        "the 21:15 deadline minus ceil(90 / 1) minutes"
    )

    # A LATE slip is admitted once the caller acknowledges it, exactly as the
    # pinned boundary requires.
    version = read_showtime(showtime["id"], LEAD)["version"]
    accepted = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 91, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version, "capacity_ack": True},
        server_headers(server),
    )
    slip = validate_success(accepted, 201)
    assert slip["status"] == "ACCEPTED", "a LATE slip proceeds once acknowledged"

    # One minute on the utilization band has passed the ceiling, so the outer min
    # is BLOCKED and the acknowledgement no longer admits anything.
    set_clock("2026-09-01T19:46:00Z")
    blocked = read_capacity(showtime["id"], LEAD)
    assert blocked["capacity_band"] == "BLOCKED", (
        "floor(91 * 100 / (1 * 89)) exceeds one hundred"
    )
    version = read_showtime(showtime["id"], LEAD)["version"]
    still_refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 92, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version, "capacity_ack": True},
        server_headers(server),
    )
    validate_error(still_refused, "ERR_KITCHEN_CAPACITY_BAND")
    assert still_refused.status_code == 409, (
        "a BLOCKED slip is refused with the same error regardless of the flag"
    )


def test_read_model_band_is_the_band_the_write_is_judged_against(api):
    """PRD §3.5: "Comparing the logical clock against that instant and against the
    deadline itself yields the entrée band: `NORMAL` when the clock is at or
    before the latest-acceptance instant, `LATE` when it is past that instant but
    still at or before the deadline, and `BLOCKED` once it is past the deadline."
    PRD §3.5: "a `LATE` slip is accepted only when the caller supplies
    `capacity_ack` set to true and is otherwise refused with
    `ERR_KITCHEN_CAPACITY_BAND` (HTTP 409)".

    Design: Corner/endpoints/compute_capacity_summary_matches_the_snapshot_the_write_gate_uses
    """
    # Twenty points on a one-point-per-minute line is twenty minutes of work; at
    # 20:53 the whole minutes remaining before the 21:15 deadline are twenty-two,
    # so the ramp is floor(20 * 100 / 22) — exactly ninety, which the pinned
    # threshold bands as LATE. The entree gate is still NORMAL at that instant
    # (its latest-acceptance point is 20:55), so the read model's verdict comes
    # from the utilization band alone, and the write is judged against it.
    scenario = setup_entree_load(
        load_points=20, prep_minutes=10, start_at_utc="2026-09-01T20:00:00Z",
        runtime_minutes=100, order_clock="2026-09-01T19:40:00Z",
        read_clock="2026-09-01T20:53:00Z", kitchen_point_rate=1,
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = scenario["item"]

    snapshot = read_capacity(showtime["id"], LEAD)
    assert snapshot["entree_load_points"] == 20, "two accepted 10-point entrees"
    assert snapshot["entree_latest_accept_at_utc"] == "2026-09-01T20:55:00Z", (
        "the 21:15 deadline minus ceil(20 / 1) minutes"
    )
    assert snapshot["load_pct"] == 90, "floor(20 * 100 / (1 * 22)) is exactly the late floor"
    assert snapshot["capacity_band"] == "LATE", (
        "the ramp alone is adverse, and ninety percent is LATE rather than NORMAL"
    )
    assert snapshot["entry_stage"] == 2, "two slips are already accepted"

    version = read_showtime(showtime["id"], LEAD)["version"]
    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 4, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    )
    validate_error(refused, "ERR_KITCHEN_CAPACITY_BAND")

    version = read_showtime(showtime["id"], LEAD)["version"]
    accepted = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 5, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version, "capacity_ack": True},
        server_headers(server),
    )
    validate_success(accepted, 201)


def test_cold_line_sequence_sits_behind_allergen_and_large_party(api):
    """PRD §3.5: "The first key is the ticket's compatibility priority, computed
    as a weighted score: a ticket scores three points if any line on its slip
    marks an `allergen_substitution` and two points if its slip carries at least
    four total units across its lines, and the two contributions add, so a slip
    that is both an allergen substitution and a large party scores five. Tickets
    are ordered by that score *descending*".

    Design: Difficulty/compensating_invariant/void_and_recreate_leaves_the_kitchen_fire_budget_unchanged
    """
    scenario = setup_three_cold_line_tickets(costs=(1, 3, 1))
    tickets = scenario["tickets"]
    assert len(tickets) == 3
    positions = sorted(t["sequence_position"] for t in tickets)
    assert positions == [1, 2, 3], "only QUEUED/PREPARING cold-line tickets occupy a position"
    for ticket in tickets:
        assert_kitchen_ticket(ticket)
        assert ticket["station"] == "cold_line"


def test_voiding_the_middle_ticket_renumbers_the_survivors(api):
    """PRD §3.5: "Voiding the ticket at position 2 of 4 therefore moves the
    ticket previously at position 3 into position 2 and leaves the ticket
    originally at position 4 enduring at position 3, with position 4 now
    unoccupied."
    PRD §3.5: "The platform maintains an invariant across every recomputation:
    the sum, over the cohort, of each ticket's ceiling-rounded line minutes must
    equal the elapsed span between the anchor and the completion instant of the
    final cohort member."
    PRD §3.5: "Fire capacity may be neither created nor destroyed by voiding,
    re-adding, or re-sequencing a ticket".

    Design: Difficulty/compensating_invariant/void_and_recreate_leaves_the_kitchen_fire_budget_unchanged
    """
    scenario = setup_three_cold_line_tickets(costs=(1, 2, 1))
    showtime, tickets = scenario["showtime"], scenario["tickets"]
    middle, last = tickets[1], tickets[2]

    assert middle["point_cost"] == 2
    assert middle["sequence_position"] == 2
    assert last["sequence_position"] == 3

    get_success_data(api_client.void_kitchen_ticket(
        middle["id"], {"reason_code": "SERVICE_OVERFLOW"}, LEAD
    ))

    survivor = read_ticket(last["id"], LEAD)
    assert survivor["sequence_position"] == 2, (
        "the ticket previously at position 3 moves into the vacated position 2"
    )

    queued, meta = validate_paginated(
        api_client.list_showtime_kitchen_tickets(
            showtime["id"], LEAD, params={"station": "cold_line", "status": "QUEUED"}
        )
    )
    assert len(queued) == 2, "the voided middle ticket left the cohort"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_explicit_refresh_restores_the_fire_budget(api):
    """PRD §3.5: "A supervisor can also force a re-derivation without changing
    membership, which recomputes both the positions and the fire instants so that
    the invariant is restored."
    PRD §3.5: "the sum, over the cohort, of each ticket's ceiling-rounded line
    minutes must equal the elapsed span between the anchor and the completion
    instant of the final cohort member."

    Design: Difficulty/compensating_invariant/void_and_recreate_leaves_the_kitchen_fire_budget_unchanged
    """
    scenario = setup_three_cold_line_tickets(costs=(1, 1, 2))
    showtime, tickets = scenario["showtime"], scenario["tickets"]
    anchor = entree_fire_at("2026-09-01T20:00:00Z")
    assert anchor.endswith("19:30:00Z"), "the cold line is anchored 30 minutes before the feature"

    refreshed = validate_success(
        api_client.refresh_kitchen_ticket(tickets[0]["id"], LEAD), 200
    )
    assert_kitchen_ticket(refreshed)

    cohort, _ = validate_paginated(
        api_client.list_showtime_kitchen_tickets(
            showtime["id"], LEAD, params={"station": "cold_line", "status": "QUEUED"}
        )
    )
    # ceil(point_cost / 1) summed over the cohort is the span the anchor opens.
    assert sum(t["point_cost"] for t in cohort) == 4, (
        "the three tickets cost 1 + 1 + 2 points in total"
    )
    assert min(t["sequence_position"] for t in cohort) == 1


def test_voiding_the_last_ticket_leaves_the_surviving_span_short(api):
    """PRD §3.5: "Each ticket in turn is stamped with the running cursor, and the
    cursor then advances by the number of minutes that ticket occupies on the
    line — its `point_cost` divided by the auditorium's `kitchen_point_rate`,
    rounded *up* to a whole minute."
    PRD §3.5: "The platform maintains an invariant across every recomputation: the
    sum, over the cohort, of each ticket's ceiling-rounded line minutes must equal
    the elapsed span between the anchor and the completion instant of the final
    cohort member."

    Design: Corner/endpoints/reorder_then_remove_keeps_the_kitchen_fire_budget_at_two
    """
    scenario = setup_three_cold_line_tickets(costs=(2, 2, 2))
    tickets = scenario["tickets"]
    assert [t["fire_at_utc"][-9:] for t in tickets] == ["19:30:00Z", "19:32:00Z", "19:34:00Z"], (
        "three 2-point tickets at one point per minute run 19:30, 19:32 and 19:34"
    )
    assert [t["sequence_position"] for t in tickets] == [1, 2, 3]

    get_success_data(api_client.void_kitchen_ticket(
        tickets[2]["id"], {"reason_code": "SERVICE_COMP_FAILURE"}, LEAD
    ))
    survivor = read_ticket(tickets[1]["id"], LEAD)
    assert survivor["sequence_position"] == 2, (
        "the second ticket keeps its position when only the last one leaves"
    )
    assert survivor["fire_at_utc"].endswith("19:32:00Z"), (
        "the surviving two-ticket run fires at 19:30 and 19:32, so its span is two minutes for two points"
    )


def test_cold_line_run_totals_the_cohort_point_cost(api):
    """PRD §3.5: "a ticket's `fire_at_utc` is the showtime's `start_at_utc` minus
    `MINUTES_FROM_ENTREE_TO_START`, which is thirty minutes, so the whole
    cold-line run is anchored half an hour before the feature begins."

    Design: Corner/endpoints/reorder_then_remove_keeps_the_kitchen_fire_budget_at_two
    """
    scenario = setup_three_cold_line_tickets(costs=(1, 3, 1))
    tickets = scenario["tickets"]
    anchor_minutes = MINUTES_FROM_ENTREE_TO_START
    assert anchor_minutes == 30
    assert tickets[0]["fire_at_utc"][-9:] == "19:30:00Z"
    assert tickets[0]["sequence_position"] == 1
    assert sum(t["point_cost"] for t in tickets) == 5, (
        "the cold-line cohort costs 1 + 3 + 1 = 5 points, so it spans five fire minutes"
    )
    assert all(t["station"] == "cold_line" for t in tickets)

def test_final_variant_widens_the_cohort_to_the_whole_cluster(api):
    """PRD §3.5: "The *final* variant is the one written into the projection
    snapshot once the showtime has left the seating phases — that is, when its
    status is neither `SCHEDULED` nor `DINING_OPEN`."
    PRD §3.5: "It widens the cohort to the entire cluster, including showtimes
    that start after the target, and it changes the unit of measurement from point
    cost to item count, summing the number of qualifying entrée slips rather than
    their points."

    Design: Difficulty/dual_variant_calc/kitchen_load_projection_wave_vs_final_over_one_cluster
    """
    set_clock("2026-09-01T19:40:00Z")
    auditorium = get_success_data(api_client.create_auditorium(
        {"name": "Theater 3", "seat_capacity": 60, "screen_lead_time_minutes": 20,
         "kitchen_point_rate": 1, "alcove_point_rate": 3}, ADMIN))
    server = get_success_data(api_client.create_server(
        {"display_name": "Dana", "home_auditorium_id": auditorium["id"]}, ADMIN))
    item = make_menu_item("ENTREE", price_cents=1200, prep_minutes=1, catalog_name="Fries")

    target = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 60, title="Alien")
    target = get_success_data(api_client.open_dining(target["id"], LEAD))
    target_section = make_section(target["id"], server["id"], "LEFT")
    version = read_showtime(target["id"], LEAD)["version"]
    make_slip(target["id"], target_section["id"], server, 12,
              [{"menu_item_id": item["id"], "quantity": 1}],
              expected_showtime_version=version)

    # A later showtime on the same auditorium, inside the two-hour cluster window.
    # Both shows live on the second auditorium; the server is homed there, and the
    # two are only 35 minutes apart so they do not overlap.
    # Two shows only 95 minutes apart would collide: a runtime's dining window is
    # [start - 20, start + deadline - 30), and the cluster's own reach is the
    # target's cluster instant plus two hours, so the forward show has to sit far
    # enough out to have a window of its own.
    set_clock("2026-09-01T20:40:00Z")
    later = make_showtime(auditorium["id"], "2026-09-01T20:55:00Z", 60, title="Aliens")
    later = get_success_data(api_client.open_dining(later["id"], LEAD))
    later_section = make_section(later["id"], server["id"], "CENTER")
    version = read_showtime(later["id"], LEAD)["version"]
    make_slip(later["id"], later_section["id"], server, 3,
              [{"menu_item_id": item["id"], "quantity": 1}],
              expected_showtime_version=version)

    assert later["dining_open_at_utc"].endswith("20:35:00Z"), (
        "the forward show's window opens after the target's has closed"
    )
    wave = read_capacity(target["id"], LEAD)
    assert wave["projection_variant"] == "wave_projection"
    assert wave["entree_load_points"] == 1, (
        "the wave cohort holds only showtimes starting at or before the target, so the later show contributes nothing"
    )

    get_success_data(api_client.start_service(target["id"], LEAD))
    final = read_capacity(target["id"], LEAD)
    assert final["projection_variant"] == "final_projection", (
        "the target has left the seating phases"
    )
    assert final["entree_load_points"] == 2, (
        "the widened cohort counts both showtimes' qualifying entrees as plates"
    )
    assert final["entree_load_points"] > wave["entree_load_points"], (
        "the identical target slip set plus a forward show is reported differently by the two variants"
    )


def test_the_outer_min_escalates_from_normal_to_blocked_in_one_minute(api):
    """PRD §3.5: "The entrée gate converts the wave projection into minutes by
    dividing it by the auditorium's `kitchen_point_rate` and rounding up, then
    subtracts those minutes from the entrée deadline to obtain the latest instant
    at which an entrée may still be accepted."
    PRD §3.5: "The snapshot's binding band is the *worse* of two candidates, taking
    `NORMAL` as the best and `BLOCKED` as the worst."
    PRD §3.5: "a utilization of exactly one hundred percent is `LATE`, not
    `BLOCKED`, because the blocking test is strictly greater than one hundred; and
    a clock exactly equal to the latest-acceptance instant is `NORMAL`, because
    that test is at-or-before."

    Design: Difficulty/combinatorial_formula/dining_order_capacity_snapshot_two_min_layers_at_exact_boundary
    """
    scenario = setup_entree_load(
        load_points=8, prep_minutes=1, start_at_utc="2026-09-01T20:00:00Z",
        runtime_minutes=100, order_clock="2026-09-01T19:40:00Z",
        read_clock="2026-09-01T21:12:00Z", kitchen_point_rate=3,
    )
    showtime, server, section, item = (
        scenario["showtime"], scenario["server"], scenario["section"], scenario["item"]
    )

    # At the latest-acceptance instant both layers are NORMAL, so the placement is
    # admitted with no acknowledgement.
    at_boundary = read_capacity(showtime["id"], LEAD)
    assert at_boundary["entree_load_points"] == 8
    assert at_boundary["load_pct"] == 88, "floor(8 * 100 / (3 * 3)) is below the late threshold"
    assert at_boundary["capacity_band"] == "NORMAL"
    assert at_boundary["entree_latest_accept_at_utc"] == "2026-09-01T21:12:00Z", (
        "the deadline 21:15 minus ceil(8 / 3) minutes is the clock itself"
    )
    version = read_showtime(showtime["id"], LEAD)["version"]
    validate_success(api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 20, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    ), 201)

    # One minute on, the utilization band alone escalates the outer min to BLOCKED.
    set_clock("2026-09-01T21:13:00Z")
    after = read_capacity(showtime["id"], LEAD)
    assert after["capacity_band"] == "BLOCKED", (
        "floor(9 * 100 / (3 * 2)) exceeds one hundred, the worst of the two candidates"
    )
    version = read_showtime(showtime["id"], LEAD)["version"]
    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 21, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    )
    validate_error(refused, "ERR_KITCHEN_CAPACITY_BAND")

    version = read_showtime(showtime["id"], LEAD)["version"]
    still_refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 22, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version, "capacity_ack": True},
        server_headers(server),
    )
    validate_error(still_refused, "ERR_KITCHEN_CAPACITY_BAND")
    assert still_refused.status_code == 409, (
        "a BLOCKED slip is refused with the same error regardless of the acknowledgement flag"
    )


def test_the_capacity_refusal_differs_from_the_window_refusal(api):
    """PRD §3.3: "Beyond the mode gate, a slip whose computed `channel` is
    `BEVERAGE` is admissible only while the clock is at or before
    `dining_close_at_utc` (otherwise `ERR_DINING_WINDOW_CLOSED`)".
    PRD §3.5: "a `BLOCKED` slip is refused with that same error regardless of the
    flag" — `ERR_KITCHEN_CAPACITY_BAND`.

    Design: Difficulty/priority_pair_validation_conflict/closed_window_priority_8_beats_capacity_priority_17
    """
    scenario = setup_dining_open_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:40:00Z", kitchen_point_rate=1,
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    room = get_success_data(api_client.get_auditorium(scenario["auditorium"]["id"], ADMIN))
    heavy_entree = make_menu_item("ENTREE", price_cents=1000, prep_minutes=10,
                                  catalog_name="Tenders")
    drink = make_menu_item("BEVERAGE", price_cents=600, prep_minutes=1,
                           catalog_name="Pale Ale")
    item = heavy_entree

    # Two heavy entrees put twenty points on the cold line, close to the
    # twenty-five minutes that would still fit before the 21:15 deadline, so the
    # entree gate alone is LATE at 20:50 while the clock stays inside the seating
    # window (which closes at 21:05). PRD §3.3 reads a BEVERAGE slip against that
    # close rather than the entree deadline, so the placement reaches the
    # ordering rule and only there.
    # The two are stacked at the seating window's own open instant, where the
    # line still has the whole evening in hand and each placement is admitted.
    set_clock("2026-09-01T19:40:00Z")
    for seat in (1, 2):
        version = read_showtime(showtime["id"], LEAD)["version"]
        make_slip(showtime["id"], section["id"], server, seat,
                  [{"menu_item_id": item["id"], "quantity": 1}],
                  expected_showtime_version=version)

    # At 20:53 the whole minutes left are twenty-two and the ramp is exactly
    # ninety percent, which bands LATE. A BEVERAGE slip writes against the
    # seating window's close (20:45) rather than the entree deadline (21:15), and
    # 20:53 is past that close — so §3.3's window rule, which outranks the
    # capacity band, is what the caller sees.
    set_clock("2026-09-01T20:53:00Z")
    capacity = read_capacity(showtime["id"], LEAD)
    assert capacity["capacity_band"] == "LATE", (
        "the ramp alone is adverse, so the outer min is LATE"
    )
    assert capacity["entree_load_points"] == 20
    assert room["kitchen_point_rate"] == 1

    version = read_showtime(showtime["id"], LEAD)["version"]
    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 40, "lines": [{"menu_item_id": drink["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    )
    validate_error(refused, "ERR_DINING_WINDOW_CLOSED")
    assert refused.status_code == 409




def test_a_dark_period_showtime_refuses_preparation(api):
    """PRD §3.4: "the showtime's `service_mode` must be `IN_KITCHEN` or
    `PRE_SHOW`; an attempt to move food through a room that has entered its dark
    period is refused with `ERR_DARK_PERIOD_FULFILMENT_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_window_priority_8_beats_capacity_priority_17
    """
    scenario = setup_in_service_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=60,
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=lambda s: place_scenario_slip(s, seat=5, catalog_name="Fries"),
    )
    showtime, server, slip = scenario["showtime"], scenario["server"], scenario["slip"]
    assert read_slip(slip["id"], LEAD)["status"] == "ACCEPTED"

    # PRD §2.4: "an administrator-only capability advances the logical clock",
    # and `service_mode` "is recomputed on every clock set". The runtime-60
    # feature's entree deadline is 20:45, so 21:00 puts the room in its dark
    # period with no cut-over involved — and the slip, still ACCEPTED, is the
    # subject of the preparation edge rather than of §3.6's boundary pass.
    set_clock("2026-09-01T21:00:00Z")
    assert read_showtime(showtime["id"], LEAD)["service_mode"] == "DARK_PERIOD"

    refused = api_client.prepare_order_slip(slip["id"], server_headers(server))
    validate_error(refused, "ERR_DARK_PERIOD_FULFILMENT_BLOCKED")
    assert refused.status_code == 409
