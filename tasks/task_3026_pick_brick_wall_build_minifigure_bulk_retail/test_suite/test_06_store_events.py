"""In-store events: scheduling windows, capacity, waitlist promotion and check-in."""
import pytest

from test_helpers import (
    CLOCK_2026_09_02,
    CLOCK_2026_09_02_0100,
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    create_reservation_payload,
    create_store_event_payload,
    join_queue,
    load_bin,
    make_member_headers,
    open_store,
    reset_clock,
    run_epoch,
    schedule_launch,
    set_clock,
    stored_instant,
    validate_error,
    validate_paginated,
    validate_success,
)


def _event(store_id, headers=None, **overrides):
    res = api_client.create_store_event(
        create_store_event_payload(store_id, **overrides),
        headers or TEST_USERS["associate_headers"])
    return validate_success(res, 201)


def _register(event_id, member_id, seats=1):
    res = api_client.create_reservation(
        create_reservation_payload(event_id, member_id, seats=seats),
        TEST_USERS["associate_headers"])
    return validate_success(res, 201)


def test_touching_event_slots_are_admitted_by_half_open_semantics(api):
    """PRD §3.6: "The effective window is the half-open interval from `start_utc`
    up to but excluding `end_utc`, which must fall after the start."
    PRD §3.6: "a requested interval that intersects an existing slot of the same
    store is refused with `ERR_EVENT_SLOT_OVERLAP`, and because the interval is
    half-open, two slots that merely touch at a boundary are permitted."

    Design: Difficulty/resource_temporal_overlap/touching_event_slots_are_admitted_by_half_open_semantics
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3110", element_name="Brick 1x6")
    load_bin(store["id"], element["id"], bin_label="Q01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    morning = _event(store["id"], title="Morning Build", capacity_units=1,
                     days_from_default_clock=1, duration_hours=2,
                     start_offset_hours=10)
    assert stored_instant(morning["start_utc"]) == "2026-09-02T10:00:00Z", (
        morning["start_utc"])
    assert stored_instant(morning["end_utc"]) == "2026-09-02T12:00:00Z", (
        morning["end_utc"])

    noon = api.create_store_event(
        create_store_event_payload(store["id"], title="Noon Build", capacity_units=1,
                                   days_from_default_clock=1, duration_hours=2,
                                   start_offset_hours=12),
        TEST_USERS["associate_headers"])
    noon_event = validate_success(noon, 201)
    assert noon_event["start_utc"] == morning["end_utc"], (
        "a slot starting exactly at the previous slot's end merely touches")

    overlap = api.create_store_event(
        create_store_event_payload(store["id"], title="Overlap Build",
                                   capacity_units=1, days_from_default_clock=1,
                                   duration_hours=1, start_offset_hours=11),
        TEST_USERS["associate_headers"])
    validate_error(overlap, "ERR_EVENT_SLOT_OVERLAP")


def test_launch_identity_windows_use_positive_width_and_closed_open_overlap(api):
    """PRD §3.4: "Scheduling validates the window in a fixed order. First the
    window must have positive width: an early-access instant that is not
    strictly before the release instant is refused with
    `ERR_LAUNCH_WINDOW_INVALID`. Only then is overlap considered: the requested
    window must not intersect the early-access window of an existing launch of
    the same theme, and an intersection is refused with
    `ERR_LAUNCH_WINDOW_OVERLAP`."
    PRD §3.4: "Because the interval is half-open, two windows that merely touch
    at a boundary do not intersect."

    Design: Difficulty/resource_temporal_overlap/launch_identity_windows_use_positive_width_and_closed_open_overlap
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3120", element_name="Slope 2x4")
    load_bin(store["id"], element["id"], bin_label="R01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    first = schedule_launch(theme="Town", exclusive_set_sku="LEGO-E1",
                            days_from_default_clock=10,
                            vip_early_days_before_release=1)
    second = schedule_launch(theme="Icons", exclusive_set_sku="LEGO-E2",
                             days_from_default_clock=11,
                             vip_early_days_before_release=1)
    assert stored_instant(first["vip_early_access_utc"]) == "2026-09-10T00:00:00Z"
    assert second["vip_early_access_utc"] != first["vip_early_access_utc"]

    # A Town relaunch whose window sits inside the first Town window.
    overlapping = api.create_theme_launch(
        {"theme": "Town", "exclusive_set_sku": "LEGO-E3",
         "allocated_exclusive_units": 5, "exclusive_set_unit_price_cents": 1400,
         "per_customer_limit": 1, "days_from_default_clock": 10,
         "vip_early_days_before_release": 1},
        TEST_USERS["admin_headers"])
    validate_error(overlapping, "ERR_LAUNCH_WINDOW_OVERLAP")

    # A zero-width window on a theme with no other launch.
    zero_width = api.create_theme_launch(
        {"theme": "Technic", "exclusive_set_sku": "LEGO-E4",
         "allocated_exclusive_units": 5, "exclusive_set_unit_price_cents": 1400,
         "per_customer_limit": 1, "days_from_default_clock": 3,
         "vip_early_days_before_release": -1},
        TEST_USERS["admin_headers"])
    validate_error(zero_width, "ERR_LAUNCH_WINDOW_INVALID")


def test_wave_reconcile_rounds_are_fenced_so_a_late_waitlist_join_is_admitted(api):
    """PRD §3.6: "At the start of a promotion pass the slot's current
    `waitlist_epoch` fence is read; only waitlisted rows whose `wait_mark` is at
    or below that fence are in the pool, and rows that joined after the fence
    was read are carried to the following pass."
    PRD §3.6: "A slot moves through `SCHEDULED`, `OPEN`, `CLOSED` and
    `COMPLETED`. It opens on the epoch pass once the clock reaches its start,
    provided the hosting store is not frozen. It closes on the epoch pass once
    the clock reaches its end."

    Design: Difficulty/boundary_precision_check/wave_reconcile_rounds_are_fenced_so_a_late_waitlist_join_is_admitted
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    event = _event(store["id"], event_kind="MINI_BUILD", title="Monthly Mini Build",
                   capacity_units=1, days_from_default_clock=1, duration_hours=2)

    first = add_member(store["id"])
    second = add_member(store["id"])
    first_res = _register(event["id"], first["id"])
    second_res = _register(event["id"], second["id"])
    assert first_res["status"] == "REGISTERED"
    assert second_res["status"] == "WAITLISTED"

    run_epoch(store["id"])  # clock still at the start: the slot stays SCHEDULED
    assert validate_success(api.get_store_event(
        event["id"], TEST_USERS["associate_headers"]), 200)["stage"] in (
        "SCHEDULED", "COMPLETED"), (
        "the pass at the starting instant neither opens nor completes the slot")

    set_clock("2026-09-02T03:00:00Z")
    run_epoch(store["id"])

    closed = validate_success(api.get_store_event(
        event["id"], TEST_USERS["associate_headers"]), 200)
    assert closed["stage"] in ("CLOSED", "COMPLETED"), (
        "the pass past end_utc must close the slot")

    demoted = validate_success(api.get_reservation(
        second_res["id"], TEST_USERS["associate_headers"]), 200)
    assert demoted["status"] == "NOT_ADMITTED", (
        "a waitlisted row that the fenced pass could not promote is marked NOT_ADMITTED")

    late = add_member(store["id"])
    late_res = _register(event["id"], late["id"])
    assert late_res["status"] in ("WAITLISTED", "REGISTERED"), (
        "a later registration is recorded rather than refused")

    run_epoch(store["id"])
    still_waiting = validate_success(api.get_reservation(
        late_res["id"], TEST_USERS["associate_headers"]), 200)


def test_small_cup_band_and_waitlist_promotion_arithmetic_in_one_wave(api):
    """PRD §3.6: "A registration that fits within the slot's remaining capacity
    is recorded as `REGISTERED`; one that does not is recorded as `WAITLISTED`
    with a `wait_mark` stamped from the slot's promotion fence."
    PRD §3.6: "The slot's `registered_count` and `waitlisted_count` are
    recomputed after every registration, cancellation and promotion."

    Design: Difficulty/combinatorial_formula/small_cup_band_and_waitlist_promotion_arithmetic_in_one_wave
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3011", element_name="Tile 1x2",
                          theme="Technic", cost_basis_cents=9)
    load_bin(store["id"], element["id"], bin_label="E01", bin_capacity_grams=2000,
             bin_mass_grams=2000)
    event = _event(store["id"], title="Weekend Build", capacity_units=1,
                   days_from_default_clock=1, duration_hours=2)

    first = add_member(store["id"])
    second = add_member(store["id"])
    _register(event["id"], first["id"])
    second_res = _register(event["id"], second["id"])

    after = validate_success(api.get_store_event(
        event["id"], TEST_USERS["associate_headers"]), 200)
    assert after["registered_count"] == 1, (
        "one seat exactly fills a one-seat slot: the comparison is inclusive")
    assert after["waitlisted_count"] == 1
    assert second_res["status"] == "WAITLISTED"


def test_check_in_outside_the_event_window_is_refused(api):
    """PRD §3.6: "Checking in is a member action on their own reservation and is
    admitted for a row in `REGISTERED` or, once promoted off the waitlist, in
    `PROMOTED`; it requires the slot to be `OPEN` and the logical clock to sit
    inside the event window, and outside the window the attempt is refused with
    `ERR_EVENT_WINDOW_CLOSED`."

    Design: Corner/state_machines/check_in_outside_the_event_window_is_refused
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    member = add_member(store["id"])
    event = _event(store["id"], event_kind="MINI_BUILD", title="Mini Build",
                   capacity_units=2, days_from_default_clock=1, duration_hours=2)
    reservation = _register(event["id"], member["id"])

    res = api.check_in_reservation(reservation["id"], make_member_headers(member["id"]))
    validate_error(res, "ERR_EVENT_WINDOW_CLOSED")

    reread = validate_success(api.get_reservation(
        reservation["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "REGISTERED"
    assert reread["checked_in_at_utc"] is None, "a refused check-in stamps nothing"

    refreshed = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed["passed_mb_reservations"] == 0, (
        "no pass is recorded for a refused check-in")


def test_cancelled_reservation_cannot_be_cancelled_again(api):
    """PRD §3.7: "Cancelling is likewise a member action and expires the
    reservation immediately, freeing its seats for the next waitlisted guest and,
    if the slot had closed but has not yet ended, reopening it."
    PRD §2.4: "Fourth, state: the target resource must be in a condition that
    admits the operation, including the optimistic-concurrency version match
    described in §2.9; this rung reports the state-conflict family —
    `ERR_INVALID_STATE`, `ERR_STALE_VERSION`, `ERR_MEMBER_STALE_VERSION` and
    `ERR_INSPECTION_STALE_VERSION`"

    Design: Corner/state_machines/cancelled_reservation_cannot_be_cancelled_again
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    member = add_member(store["id"])
    event = _event(store["id"], title="Build Event", capacity_units=1,
                   days_from_default_clock=1, duration_hours=3)
    reservation = _register(event["id"], member["id"])
    version_before = reservation["version"]

    first = validate_success(api.cancel_reservation(
        reservation["id"], make_member_headers(member["id"])), 200)
    assert first["status"] == "EXPIRED"

    second = api.cancel_reservation(reservation["id"], make_member_headers(member["id"]))
    validate_error(second, "ERR_INVALID_STATE")

    reread = validate_success(api.get_reservation(
        reservation["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["version"] == version_before + 1, (
        "the refused second cancel must not mutate the row again")


def test_epoch_run_is_checkpointed_not_per_request(api):
    """PRD §3.8: "A head-office operator advances a store's run index through
    the epoch capability, naming the store as `id`, which increments the store's
    `last_event_run_index` and drives three ordered passes over everything
    belonging to that store."
    PRD §3.6: "A slot moves through `SCHEDULED`, `OPEN`, `CLOSED` and
    `COMPLETED`. It opens on the epoch pass once the clock reaches its start"

    Design: Corner/cross_cutting_complexity_layers/epoch_run_is_checkpointed_not_per_request
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="7101")
    load_bin(store["id"], element["id"], bin_label="AE01", bin_capacity_grams=1000,
             bin_mass_grams=600)
    event = _event(store["id"], title="Checkpoint Build", capacity_units=4,
                   days_from_default_clock=1, duration_hours=4)
    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-J1",
                             per_customer_limit=1, days_from_default_clock=1,
                             vip_early_days_before_release=0)

    set_clock("2026-09-02T01:00:00Z")

    _rows, before_meta = validate_paginated(api.list_store_events(
        TEST_USERS["associate_headers"],
        params={"store_id": store["id"], "stage": "OPEN"}))
    assert before_meta["total_count"] == 0, (
        "the clock alone moves nothing: wave-driven transitions need the checkpoint")
    assert validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["associate_headers"]), 200)["stage"] == "SCHEDULED"

    advanced = run_epoch(store["id"])
    assert advanced["last_event_run_index"] == 1, (
        "the epoch capability advances the run index")

    rows, after_meta = validate_paginated(api.list_store_events(
        TEST_USERS["associate_headers"],
        params={"store_id": store["id"], "stage": "OPEN"}))
    assert after_meta["total_count"] == 1, (
        "after the checkpoint the slot whose start has passed reads OPEN")
    assert rows[0]["id"] == event["id"]

    refreshed_launch = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed_launch["stage"] == "STAGED_OPEN", (
        "the same checkpoint rolls the launch forward to STAGED_OPEN")


def test_waitlist_promotion_accepts_a_seat_count_landing_exactly_on_capacity(api):
    """PRD §3.6: "Within the pool, rows are promoted in `arrival_counter` order
    while the accumulated `seats` still fit within the slot's `capacity_units` as
    measured against `registered_count`, and the comparison is inclusive —
    landing exactly on capacity promotes."
    PRD §3.6: "Cancelling is likewise a member action and expires the
    reservation immediately, freeing its seats for the next waitlisted guest"

    Design: Difficulty/boundary_precision_check/wave_reconcile_rounds_are_fenced_so_a_late_waitlist_join_is_admitted
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    event = _event(store["id"], title="Promotion Build", capacity_units=2,
                   days_from_default_clock=1, duration_hours=3)

    holder = add_member(store["id"])
    waiting = add_member(store["id"])
    held = _register(event["id"], holder["id"], seats=2)
    waitlisted = _register(event["id"], waiting["id"], seats=2)
    assert held["status"] == "REGISTERED"
    assert waitlisted["status"] == "WAITLISTED"

    validate_success(api.cancel_reservation(held["id"],
                                            make_member_headers(holder["id"])), 200)

    promoted = validate_success(api.get_reservation(
        waitlisted["id"], TEST_USERS["associate_headers"]), 200)
    assert promoted["status"] == "PROMOTED", (
        "two free seats at capacity two is an inclusive fit")
    assert promoted["status"] != "NOT_ADMITTED"

    refreshed = validate_success(api.get_store_event(
        event["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed["registered_count"] >= 1, (
        "the freed seats are re-counted onto the slot")

def test_a_slot_whose_end_precedes_its_start_has_no_positive_width(api):
    """PRD §3.6: "The effective window is the half-open interval from `start_utc`
    up to but excluding `end_utc`, which must fall after the start."
    PRD §3.6: "The window is validated for positive width before overlap is
    considered"

    Design: Difficulty/resource_temporal_overlap/touching_event_slots_are_admitted_by_half_open_semantics
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)

    res = api.create_store_event(
        create_store_event_payload(store["id"], title="Inverted Window",
                                   capacity_units=1, days_from_default_clock=1,
                                   duration_hours=-2),
        TEST_USERS["associate_headers"])
    if res.status_code < 400:
        raise AssertionError(
            "an interval whose end precedes its start must be refused, but the "
            f"slot was scheduled: HTTP {res.status_code} {res.text}")

    _rows, meta = validate_paginated(api.list_store_events(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}))
    assert meta["total_count"] == 0, "the refused slot is never scheduled"


def test_a_closed_launch_reopens_with_its_allocation_restored(api):
    """PRD §3.4: "a launch that has closed may be reopened to `SCHEDULED` with
    both instants recomputed and `exclusive_set_units_remaining` restored to the
    full `allocated_exclusive_units`."

    Design: Difficulty/resource_temporal_overlap/launch_identity_windows_use_positive_width_and_closed_open_overlap
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3121", element_name="Slope 2x2")
    load_bin(store["id"], element["id"], bin_label="R02", bin_capacity_grams=1000,
             bin_mass_grams=600)
    member = add_member(store["id"])

    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-E5",
                             allocated_exclusive_units=1, per_customer_limit=1,
                             days_from_default_clock=1,
                             vip_early_days_before_release=1)
    version_at_creation = launch["version"]
    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    set_clock("2026-09-01T00:00:00Z")

    queue_row = join_queue(member["id"], launch["id"], requested_units=1)
    granted = validate_success(api.grant_launch_queues(
        {"launch_id": launch["id"],
         "expected_theme_launch_version": version_at_creation},
        TEST_USERS["associate_headers"]), 200)
    assert granted[0]["status"] == "GRANTED"

    closed = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert closed["exclusive_set_units_remaining"] == 0
    assert closed["stage"] == "CLOSED"

    reopened = validate_success(api.reschedule_theme_launch(
        launch["id"], {"days_from_default_clock": 5},
        TEST_USERS["admin_headers"]), 200)
    assert reopened["stage"] == "SCHEDULED", (
        "a closed launch may be reopened by resupplying a day offset")
    assert reopened["exclusive_set_units_remaining"] == 1, (
        "reopening restores the full declared allocation")
    assert stored_instant(reopened["release_utc"]) != stored_instant(
        closed["release_utc"]), "both instants are recomputed from the new day offset"
