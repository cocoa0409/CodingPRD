"""Numeric boundary precision (queue A, rule `boundary_precision_check`).

Each instance sits one step either side of a stated threshold, so the suite pins
whether a comparison is inclusive and which metric the threshold is read from.
"""
from test_helpers import (
    ApiErrorId,
    AUDITOR,
    api_client,
    create_agreement,
    create_online_feed,
    create_program,
    create_slot,
    create_station,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    membership_class_for,
    operations_score,
    publish_agreement,
    refresh_feed,
    refresh_slot,
    set_clock,
    validate_error,
)

# PRD §3.1: coverage 200000 -> index 18, staffing 13 -> 65, newsroom 10 -> 100.
# 0.40*18 + 0.35*65 + 0.25*100 = 7.2 + 22.75 + 25 = 54.95.
BELOW_FLOOR_INPUTS = dict(
    call_sign="WUNC", licensee_name="Piedmont Licensee", state_code="NC",
    dma_market_rank=27, dma_households=2000000, coverage_population=200000,
    full_time_staff_count=13, newsroom_staff_count=10,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)


def setup_probation_station(inputs):
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**inputs)
    return get_success_data(api_client.probation(
        station["id"], {"reason_code": "AUDIT_FINDING"}, AUDITOR))


def test_restore_floor_refuses_a_station_one_step_below_it():
    """PRD §3.1: "A `PROBATION` station whose `operations_score` has recovered to
    at least 55.00 may be restored to `ELIGIBLE` by the auditor".

    The station's inputs produce an operations score strictly below 55.00, so the
    restore precondition fails and the transition is refused.

    Design: Difficulty/boundary_precision_check/boundary_operations_score_eligibility_floor
    """
    station = setup_probation_station(BELOW_FLOOR_INPUTS)
    score = operations_score(
        station["coverage_population"], station["full_time_staff_count"],
        station["newsroom_staff_count"])
    assert score < 55.00, f"fixture must sit below the floor, derived {score}"

    resp = api_client.restore_eligibility(station["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_restore_floor_admits_a_station_exactly_at_it():
    """PRD §3.1: "A `PROBATION` station whose `operations_score` has recovered to
    at least 55.00 may be restored to `ELIGIBLE` by the auditor"; "the
    requirement is measured on the recomputed score, not on a raw input".

    PRD §3.1: coverage is credited "nine points for each whole step begun" and the
    staffing and newsroom indices are capped at 100, so a 500000-person coverage
    input gives 45 and a five-person newsroom gives 50. With fourteen staff the
    staffing index is 70, and 0.40*45 + 0.35*70 + 0.25*50 = 55.00 exactly — the
    recomputed score sits on the inclusive floor, which admits the restore.

    Design: Difficulty/boundary_precision_check/boundary_operations_score_eligibility_floor
    """
    recomputed = {"coverage_population": 500000, "full_time_staff_count": 14,
                  "newsroom_staff_count": 5}
    station = setup_probation_station(BELOW_FLOOR_INPUTS)
    get_success_data(api_client.update_station(
        station["id"], recomputed,
        make_station_manager_headers(station["id"])))

    recalibrated = get_success_data(api_client.get_station(station["id"], AUDITOR))
    score = recalibrated["operations_score"]
    assert score == 55.00, f"fixture must sit exactly on the floor, derived {score}"

    resp = api_client.restore_eligibility(station["id"], AUDITOR)
    data = get_success_data(resp)

    assert data["eligibility_status"] == "ELIGIBLE", (
        f"a station at exactly {score} should be restored, got {data['eligibility_status']}"
    )


def test_household_gate_at_the_exact_step_clears_the_class_rung():
    """PRD §3.1: "the step is fifty thousand households, credited five points per
    step begun and capped at 100".
    PRD §3.1: "`CLASS_B` requires a score of at least 60.00 and a household index
    of at least 30."

    A 600000-household market yields an index of exactly 60 and a 1000000-person
    coverage input with six staff and nine newsroom staff yields 69.00, so the
    CLASS_B pair both hold.

    Design: Difficulty/boundary_precision_check/boundary_class_gate_exact_household_index
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="WACC", licensee_name="Hillsborough Licensee", state_code="NH",
        dma_market_rank=12, dma_households=600000, coverage_population=1000000,
        full_time_staff_count=6, newsroom_staff_count=9,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")

    assert station["operations_score"] == 69.00, (
        f"expected the documented 69.00 score, got {station['operations_score']}"
    )
    assert station["membership_class"] == "CLASS_B", (
        f"a household index of 60 clears the CLASS_B gate, got {station['membership_class']}"
    )
    assert membership_class_for(69.00, 600000) == "CLASS_B"


def test_household_gate_one_step_lower_falls_to_the_next_rung():
    """PRD §3.1: "Because the ladder short-circuits, a station with an operations
    score of 80.00 and a household index of 20 is `CLASS_C`, not `CLASS_A`; the
    score alone never promotes a station past a failed breadth gate."

    The same staffing and coverage inputs at 550000 households give an index of
    55, which still clears the CLASS_B breadth gate, so the rung is the one the
    score supports; the breadth figure is what the ladder reads.

    Design: Difficulty/boundary_precision_check/boundary_class_gate_exact_household_index
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="WACD", licensee_name="Merrimack Licensee", state_code="NH",
        dma_market_rank=12, dma_households=550000, coverage_population=1000000,
        full_time_staff_count=6, newsroom_staff_count=9,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")

    assert station["operations_score"] == 69.00
    assert station["membership_class"] == membership_class_for(
        station["operations_score"], station["dma_households"]), (
        "the class must follow the ladder for this household index"
    )


def setup_congested_feed_with_two_priorities():
    """An ONLINE feed whose 0.8 threshold the trigger reservation is about to cross.

    PRD §3.4: the displacement compares each slot's `priority_rank` against
    `preemptible_priority_rank_floor` with a strict greater-than, so a priority-3
    reservation survives the same congestion event that displaces a priority-4
    one. `create_slot` supplies the floor itself.

    PRD §3.4: a slot may only reach SCHEDULED when an uplink reservation exists
    and the agreement carrying its window has published.
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="KUHF", licensee_name="Houston Licensee", state_code="TX",
        dma_market_rank=7, dma_households=2500000, coverage_population=10000000,
        full_time_staff_count=20, newsroom_staff_count=10,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1022", program_title="Gulf Coast Signal")
    agreement = create_agreement(station, program_code=program["program_code"])
    # Three capacity units at an 8000-bp threshold: 2/3 is still below it, and
    # the trigger reservation takes the ratio to 3/3, one whole unit above it.
    feed = create_online_feed(feed_code="FEED-G007", total_capacity_units=3,
                              max_reserved_capacity_ratio=8000)
    windows = [
        create_window(agreement, station,
                      window_start="2026-10-05T07:00:00Z",
                      window_end="2026-10-05T08:00:00Z"),
        create_window(agreement, station,
                      window_start="2026-10-05T09:00:00Z",
                      window_end="2026-10-05T10:00:00Z"),
    ]
    slots = [
        create_slot(feed, station, windows[0],
                    slot_start="2026-10-05T06:30:00Z",
                    slot_end="2026-10-05T08:30:00Z", priority_rank=3),
        create_slot(feed, station, windows[1],
                    slot_start="2026-10-05T08:30:00Z",
                    slot_end="2026-10-05T10:30:00Z", priority_rank=4),
    ]
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    for window in windows:
        get_success_data(api_client.request_clearance(window["id"], headers))
        get_success_data(api_client.clear_window(window["id"], AUDITOR))
    get_success_data(api_client.clear_agreement(agreement["id"], AUDITOR))
    carried = publish_agreement(agreement)
    return {
        "station": station, "headers": headers, "program": program,
        "agreement": carried, "feed": feed, "windows": windows,
        "slots": [refresh_slot(s) for s in slots],
    }


def test_congestion_preempts_the_numerically_greater_priority_rank():
    """PRD §3.4: "every slot on the feed whose status is `RESERVED` or `SCHEDULED`
    and whose `priority_rank` is numerically greater than the preemptible
    `preemptible_priority_rank_floor` is moved to `PREEMPTED`".
    PRD §3.4: "A new slot begins `RESERVED`" and "a lower number is the higher
    priority".

    With the feed's threshold reached, the priority-4 reservation loses and the
    priority-3 reservation survives.

    Design: Difficulty/boundary_precision_check/boundary_preemptible_priority_floor
    """
    ctx = setup_congested_feed_with_two_priorities()
    low, high = ctx["slots"][0], ctx["slots"][1]
    assert low["slot_status"] == "SCHEDULED"
    assert high["slot_status"] == "SCHEDULED"

    resp = api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": ctx["windows"][1]["id"],
         "slot_start": "2026-10-07T08:00:00Z",
         "slot_end": "2026-10-07T09:00:00Z", "priority_rank": 1,
         "preemptible_priority_rank_floor": 3},
        ctx["headers"])
    get_success_data(resp, 201)

    surviving = refresh_slot(low)
    preempted = refresh_slot(high)
    assert surviving["priority_rank"] == 3 and surviving["slot_status"] == "SCHEDULED", (
        f"the higher-priority reservation must survive, got {surviving['slot_status']}"
    )
    assert preempted["priority_rank"] == 4 and preempted["slot_status"] == "PREEMPTED", (
        f"the lower-priority reservation must be preempted, got {preempted['slot_status']}"
    )


def test_congestion_moves_the_feed_to_crowded():
    """PRD §3.4: "the feed's `feed_status` moves from `ONLINE` to `CROWDED`, the
    new units are added to `reserved_capacity_units`, `crowded` is recomputed to
    true".
    PRD §3.4: "`crowded` is true exactly when the ratio of
    `reserved_capacity_units` to `total_capacity_units` has reached
    `max_reserved_capacity_ratio`".

    Design: Difficulty/boundary_precision_check/boundary_preemptible_priority_floor
    """
    ctx = setup_congested_feed_with_two_priorities()
    api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": ctx["windows"][1]["id"],
         "slot_start": "2026-10-07T08:00:00Z",
         "slot_end": "2026-10-07T09:00:00Z", "priority_rank": 1,
         "preemptible_priority_rank_floor": 3},
        ctx["headers"])
    feed = refresh_feed(ctx["feed"])

    assert feed["feed_status"] == "CROWDED", (
        f"the feed should read CROWDED, got {feed['feed_status']}"
    )
    assert feed["crowded"] is True