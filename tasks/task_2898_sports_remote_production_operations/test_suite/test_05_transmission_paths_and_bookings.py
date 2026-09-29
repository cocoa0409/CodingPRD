"""Transmission: satellite guard-band geometry, shared fiber capacity, the
proving-test loop, the bandwidth ledger and the booking's OCC token."""

from test_helpers import (
    assert_data_feed,
    assert_instant_equals,
    assert_labor_ledger,
    assert_labor_ledger_conserved,
    assert_path_booking,
    assert_path_ledger,
    assert_readiness,
    assert_status,
    assert_system_prep,
    assert_transmission_path,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    BOOKING_WINDOW_END,
    BOOKING_WINDOW_START,
    CANONICAL_PROVISIONAL_TOTAL_CENTS,
)
from test_helpers.factories import (
    create_path_booking_payload,
    schedule_path_test_payload,
)
from test_helpers.fixtures import (
    assign_truck,
    book_path,
    create_prep,
    file_test_result,
    new_crew_member,
    new_data_feed,
    new_fiber_path,
    new_production,
    new_satellite_path,
    new_truck,
    offer_call,
    production_version,
    read_booking,
    read_feed,
    read_path,
    read_prep,
    read_production,
    schedule_test,
    set_clock,
)


# ---------------------------------------------------------------------------
# Satellite: exclusive occupation with a symmetric guard band
# ---------------------------------------------------------------------------
def test_satellite_trailing_occupation_refused_at_nine_minutes_accepted_at_ten(api, td_headers):
    """A transponder occupation that begins nine minutes after the incumbent's end
    lands inside the trailing guard band; one minute later it clears.

    PRD: "A **satellite transponder is exclusive**: it cannot be shared at any bandwidth, and each occupation is inflated by the path's `guard_band_minutes` on *both* ends before the overlap is tested, so that the carrier has time to bring one occupation down and the next up."
    PRD: "The request is refused with `ERR_PATH_WINDOW_CONFLICT` when there exists an active booking on the same transponder such that the new window's start falls strictly before that booking's end pushed later by the guard band, and that booking's start pulled earlier by the guard band falls strictly before the new window's end."
    PRD: "A gap of exactly the guard band between two occupations is therefore accepted."
    Design: Difficulty/resource_temporal_overlap/satellite_transponder_exclusive_window_with_symmetric_guard_band
    """
    path = new_satellite_path(api, capacity_mbps=300, guard_band_minutes=10)
    assert_transmission_path(path)
    assert path["guard_band_minutes"] == 10

    incumbent = new_production(
        api,
        scheduled_start_utc="2026-08-15T20:00:00Z",
        scheduled_end_utc="2026-08-15T22:00:00Z",
    )
    # The incumbent occupies 20:00Z..22:00Z, so with a 10-minute guard band the
    # transponder is unavailable until 22:10Z.
    book_path(
        api, incumbent["id"], path["id"],
        window_start_utc="2026-08-15T20:00:00Z",
        window_end_utc="2026-08-15T22:00:00Z",
        requested_mbps=100,
    )

    follower = new_production(
        api,
        venue_name="Harbour Dome",
        venue_roof_type="DOMED",
        scheduled_start_utc="2026-08-15T22:30:00Z",
        scheduled_end_utc="2026-08-15T23:00:00Z",
    )
    follower_version = production_version(api, follower["id"])

    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                follower["id"], path["id"], follower_version,
                window_start_utc="2026-08-15T22:09:00Z",
                window_end_utc="2026-08-15T23:00:00Z",
                requested_mbps=100,
            ),
            td_headers,
        ),
        "ERR_PATH_WINDOW_CONFLICT",
    )
    assert_path_ledger(read_path(api, path["id"]), 100, 1)

    accepted = validate_success(
        api.create_path_booking(
            create_path_booking_payload(
                follower["id"], path["id"], follower_version,
                window_start_utc="2026-08-15T22:10:00Z",
                window_end_utc="2026-08-15T23:00:00Z",
                requested_mbps=100,
            ),
            td_headers,
        ),
        201,
    )
    assert_path_booking(accepted)
    assert_status(accepted, "RESERVED")
    assert_instant_equals(
        accepted["window_start_utc"], "2026-08-15T22:10:00Z", "window_start_utc"
    )
    assert_path_ledger(read_path(api, path["id"]), 200, 2)


def test_satellite_leading_occupation_refused_at_nine_minutes_accepted_at_ten(api, td_headers):
    """The guard band is symmetric, so an occupation that ends nine minutes before
    the incumbent's start is refused and one ending exactly ten minutes before is
    accepted.

    PRD: "The guard band is applied on both ends of every satellite occupation and is ignored entirely for fiber circuits."
    PRD: "The request is refused with `ERR_PATH_WINDOW_CONFLICT` when there exists an active booking on the same transponder such that the new window's start falls strictly before that booking's end pushed later by the guard band, and that booking's start pulled earlier by the guard band falls strictly before the new window's end."
    PRD: "Bandwidth plays no part in this decision at all: `requested_mbps` is recorded and committed, but a satellite conflict is decided purely on window geometry."
    Design: Difficulty/resource_temporal_overlap/satellite_transponder_exclusive_window_with_symmetric_guard_band
    """
    path = new_satellite_path(api, capacity_mbps=300, guard_band_minutes=10)
    incumbent = new_production(
        api,
        scheduled_start_utc="2026-08-15T20:00:00Z",
        scheduled_end_utc="2026-08-15T22:00:00Z",
    )
    # Pulled earlier by the guard band, the incumbent's occupation opens at 19:50Z.
    book_path(
        api, incumbent["id"], path["id"],
        window_start_utc="2026-08-15T20:00:00Z",
        window_end_utc="2026-08-15T22:00:00Z",
        requested_mbps=100,
    )

    earlier = new_production(
        api,
        venue_name="Northgate Field",
        venue_roof_type="RETRACTABLE",
        scheduled_start_utc="2026-08-15T18:30:00Z",
        scheduled_end_utc="2026-08-15T19:30:00Z",
    )
    earlier_version = production_version(api, earlier["id"])

    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                earlier["id"], path["id"], earlier_version,
                window_start_utc="2026-08-15T18:00:00Z",
                window_end_utc="2026-08-15T19:51:00Z",
                requested_mbps=100,
            ),
            td_headers,
        ),
        "ERR_PATH_WINDOW_CONFLICT",
    )
    assert read_production(api, earlier["id"])["version"] == earlier_version, (
        "a refused booking must not advance the production version"
    )

    accepted = validate_success(
        api.create_path_booking(
            create_path_booking_payload(
                earlier["id"], path["id"], earlier_version,
                window_start_utc="2026-08-15T18:00:00Z",
                window_end_utc="2026-08-15T19:50:00Z",
                requested_mbps=100,
            ),
            td_headers,
        ),
        201,
    )
    assert_status(accepted, "RESERVED")
    assert_path_ledger(read_path(api, path["id"]), 200, 2)

    rows, meta = validate_paginated(
        api.list_path_bookings(td_headers, {"path_id": path["id"]})
    )
    assert meta["total_count"] == 2, "the refused attempt left no booking row behind"
    assert all(row["path_id"] == path["id"] for row in rows)


# ---------------------------------------------------------------------------
# The conserved bandwidth ledger
# ---------------------------------------------------------------------------
def test_releasing_one_of_two_fiber_bookings_returns_exactly_its_bandwidth(api, pm_headers):
    """Releasing the 120 Mbps booking off a circuit carrying 200 Mbps leaves
    exactly the other 80 Mbps committed - neither zero nor the original 200.

    PRD: "For each transmission path, `committed_mbps_total` always equals the sum of `requested_mbps` over that path's bookings in the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` and `PROMOTED`, and `active_booking_count` is the count of that same row set."
    PRD: "Creating a booking adds exactly `requested_mbps`; releasing it or failing it over subtracts exactly `requested_mbps`, so a create-then-release pair leaves the path's committed total identical to its pre-create value."
    PRD: "The release drives the booking to `RELEASED`, subtracts exactly its `requested_mbps` from the path's `committed_mbps_total` and decrements `active_booking_count` by 1, and then runs the derivation — so releasing the only `CONFIRMED` `PRIMARY` booking of a production demotes it from `PROVISIONED` or `REHEARSED` back to `SURVEYED`, with the rehearsal-abort and readiness-hold cascade that entails."
    Design: Difficulty/compensating_invariant/path_booking_release_restores_committed_bandwidth_exactly
    """
    path = new_fiber_path(api, path_code="FIB-A", carrier_code="CARR1", capacity_mbps=300)
    assert_path_ledger(path, 0, 0)

    production_a = new_production(api)
    production_b = new_production(api, venue_name="Harbour Dome", venue_roof_type="DOMED")
    window = {
        "window_start_utc": "2026-08-15T16:00:00Z",
        "window_end_utc": "2026-08-15T23:00:00Z",
    }
    booking_a = book_path(
        api, production_a["id"], path["id"], requested_mbps=120, **window
    )
    booking_b = book_path(
        api, production_b["id"], path["id"], requested_mbps=80, **window
    )
    assert_path_ledger(read_path(api, path["id"]), 200, 2)

    released = validate_success(
        api.release_path_booking(booking_a["id"], pm_headers), 200
    )
    assert_path_booking(released)
    assert_status(released, "RELEASED")

    after_one = read_path(api, path["id"])
    assert_path_ledger(after_one, 80, 1)
    assert after_one["capacity_mbps"] == 300, (
        "contracted capacity is never mutated by a booking"
    )
    assert_status(read_booking(api, booking_b["id"]), "RESERVED")


def test_releasing_every_booking_frees_the_circuit_for_a_full_capacity_booking(api, pm_headers):
    """Once both bookings are handed back the circuit reads zero on both
    aggregates, and the freed capacity is immediately re-bookable in full.

    PRD: "`RELEASED` and `FAILED_OVER` bookings contribute nothing to either aggregate and are invisible to every capacity and overlap test."
    PRD: "Creating a booking adds exactly `requested_mbps`; releasing it or failing it over subtracts exactly `requested_mbps`, so a create-then-release pair leaves the path's committed total identical to its pre-create value."
    PRD: "The request is refused with `ERR_PATH_CAPACITY_EXCEEDED` when the sum of `requested_mbps` over that concurrent set, plus the new booking's own `requested_mbps`, is strictly greater than the path's `capacity_mbps`; a sum exactly equal to capacity is accepted."
    Design: Difficulty/compensating_invariant/path_booking_release_restores_committed_bandwidth_exactly
    """
    path = new_fiber_path(api, path_code="FIB-A", carrier_code="CARR1", capacity_mbps=300)
    production_a = new_production(api)
    production_b = new_production(api, venue_name="Harbour Dome", venue_roof_type="DOMED")
    window = {
        "window_start_utc": "2026-08-15T16:00:00Z",
        "window_end_utc": "2026-08-15T23:00:00Z",
    }
    booking_a = book_path(
        api, production_a["id"], path["id"], requested_mbps=120, **window
    )
    booking_b = book_path(
        api, production_b["id"], path["id"], requested_mbps=80, **window
    )

    validate_success(api.release_path_booking(booking_a["id"], pm_headers), 200)
    validate_success(api.release_path_booking(booking_b["id"], pm_headers), 200)

    emptied = read_path(api, path["id"])
    assert_path_ledger(emptied, 0, 0)
    assert emptied["capacity_mbps"] == 300

    production_c = new_production(api, venue_name="Lakeside Field", venue_roof_type="DOMED")
    rebooked = book_path(
        api, production_c["id"], path["id"], requested_mbps=300, **window
    )
    assert_status(rebooked, "RESERVED")
    assert rebooked["requested_mbps"] == 300
    assert_path_ledger(read_path(api, path["id"]), 300, 1)


# ---------------------------------------------------------------------------
# The bounded retest loop
# ---------------------------------------------------------------------------
def test_three_failed_proving_tests_exhaust_the_retest_budget(api, td_headers):
    """The `TEST_SCHEDULED` / `TEST_FAILED` cycle may be walked exactly three
    times; the fourth scheduling attempt is refused and the booking stays failed.

    PRD: "Scheduling the proving test writes a `test_window_start_utc` and `test_window_end_utc` onto the booking and moves it `RESERVED → TEST_SCHEDULED`; the same action is also the retest edge `TEST_FAILED → TEST_SCHEDULED`, and a booking in any other status is refused with `ERR_BOOKING_STATE_INVALID`."
    PRD: "The retest loop is bounded: once the booking's `test_attempt_count` has reached 3, scheduling another test is refused with `ERR_TEST_ATTEMPT_LIMIT`, so a path gets at most three chances to prove itself."
    PRD: "Either outcome increments `test_attempt_count` by 1."
    PRD: "For each transmission path, `committed_mbps_total` always equals the sum of `requested_mbps` over that path's bookings in the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` and `PROMOTED`, and `active_booking_count` is the count of that same row set."
    Design: Corner/state_machines/path_booking_retest_loop_bounded_by_max_test_attempts
    """
    production = new_production(api)
    path = new_fiber_path(api)
    booking = book_path(
        api, production["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    assert_status(booking, "RESERVED")
    assert booking["test_attempt_count"] == 0

    attempts = [
        ("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z", "2026-08-15T12:30:00Z"),
        ("2026-08-15T13:00:00Z", "2026-08-15T14:00:00Z", "2026-08-15T13:30:00Z"),
        ("2026-08-15T14:00:00Z", "2026-08-15T15:00:00Z", "2026-08-15T14:30:00Z"),
    ]
    for attempt_number, (start, end, filing) in enumerate(attempts, start=1):
        scheduled = schedule_test(
            api, booking["id"],
            test_window_start_utc=start, test_window_end_utc=end,
        )
        assert_status(scheduled, "TEST_SCHEDULED")
        set_clock(api, filing)
        failed = file_test_result(api, booking["id"], "FAIL")
        assert_status(failed, "TEST_FAILED")
        assert failed["test_attempt_count"] == attempt_number, (
            "each filed result advances the counter by exactly one"
        )

    validate_error(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-15T15:00:00Z",
                test_window_end_utc="2026-08-15T16:00:00Z",
            ),
            td_headers,
        ),
        "ERR_TEST_ATTEMPT_LIMIT",
    )

    exhausted = read_booking(api, booking["id"])
    assert_status(exhausted, "TEST_FAILED")
    assert exhausted["test_attempt_count"] == 3
    assert_instant_equals(
        exhausted["test_window_start_utc"],
        "2026-08-15T14:00:00Z",
        "test_window_start_utc",
    )
    assert_path_ledger(read_path(api, path["id"]), 200, 1)


# ---------------------------------------------------------------------------
# Declared initial states
# ---------------------------------------------------------------------------
def test_booking_prep_and_call_open_in_their_declared_initial_states(api):
    """A booking, a preparation and a crew call created in one flow each land on
    their declared initial state with their derived counters already coherent.

    PRD: "A surviving booking is created at `RESERVED`; the path's `committed_mbps_total` rises by exactly the new `requested_mbps` and its `active_booking_count` by exactly 1."
    PRD: "Either outcome increments `test_attempt_count` by 1."
    PRD: "A new preparation opens at `PENDING` with `feed_validated_at` null."
    PRD: "A new feed opens at `ACTIVE` with `active_consumer_count` at 0; its only other status is `SUSPENDED`."
    PRD: "On success the call is created at `OFFERED`, its `provisional_total_cents` is added to the production's `labor_committed_cents`, and the derivation runs."
    PRD: "When the candidate set is empty no turnaround rule applies at all and `turnaround_minutes_before_call` is written as null."
    Design: Corner/state_machines/booking_prep_and_call_start_in_their_declared_initial_states
    """
    production = new_production(api)
    path = new_fiber_path(api)
    feed = new_data_feed(api)
    crew_member = new_crew_member(api)

    booking = book_path(
        api, production["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    assert_path_booking(booking)
    assert_status(booking, "RESERVED")
    assert booking["test_attempt_count"] == 0, "no proving test has been scheduled yet"
    assert booking["test_window_start_utc"] is None
    assert booking["test_window_end_utc"] is None
    assert_path_ledger(read_path(api, path["id"]), 200, 1)

    prep = create_prep(api, production["id"], feed["id"])
    assert_system_prep(prep)
    assert_status(prep, "PENDING")
    assert prep["feed_validated_at"] is None
    assert_status(read_prep(api, prep["id"]), "PENDING")

    opened_feed = read_feed(api, feed["id"])
    assert_data_feed(opened_feed)
    assert_status(opened_feed, "ACTIVE")
    assert opened_feed["active_consumer_count"] == 0, (
        "a PENDING preparation is not yet a consumer"
    )

    call = offer_call(api, production["id"], crew_member["id"])
    assert_status(call, "OFFERED")
    assert call["turnaround_minutes_before_call"] is None
    assert call["provisional_total_cents"] > 0, (
        "an offered call already carries its provisional reserve"
    )


def test_reserved_primary_booking_and_pending_prep_score_only_the_forward_view(api):
    """The same freshly opened arrangement scores 52.50 on the forward-looking
    projection and 0.00 on the airtime-certified figure.

    PRD: "`required_crew_positions` — the count of *accepted* crew calls a certified crew component demands — is 12 for a `TIER_1` event, 4 for a `TIER_2` event and 2 for a `TIER_3` event."
    PRD: "The **crew component** is worth up to 15 points and is proportional: take the variant's crew numerator divided by `required_crew_positions`, cap that ratio at 1 so surplus crew never earns extra credit, multiply by 15, and round half up to two decimal places."
    PRD: "Its transmission predicate holds when the production has a booking whose `booking_role` is `PRIMARY` and whose status is any of `RESERVED`, `TEST_SCHEDULED`, `CONFIRMED` or `PROMOTED`."
    PRD: "The **airtime-certified figure**, always computed and exposed as `readiness_score_certified`, counts only work that has already succeeded, and it is the only variant that gates the show onto air."
    PRD: "The production's `labor_committed_cents` is always the sum of `provisional_total_cents` over its calls in `OFFERED` or `ACCEPTED` plus the sum of `settled_total_cents` over its calls in `RELEASED`, summed in `created_at` ascending order, with `DECLINED` and `CANCELLED` calls contributing nothing; `labor_available_cents` is always `labor_budget_total_cents` less that committed figure."
    Design: Corner/state_machines/booking_prep_and_call_start_in_their_declared_initial_states
    """
    production = new_production(api)
    assert production["required_crew_positions"] == 2, "TIER_3 demands two positions"
    assert production["required_validated_preps"] == 1

    path = new_fiber_path(api)
    feed = new_data_feed(api)
    crew_member = new_crew_member(api)
    book_path(
        api, production["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    create_prep(api, production["id"], feed["id"])
    call = offer_call(api, production["id"], crew_member["id"])
    assert call["provisional_total_cents"] == CANONICAL_PROVISIONAL_TOTAL_CENTS

    scored = read_production(api, production["id"])
    # 0 survey + 25 reserved primary + 20 pending prep + 15 x 1/2 crew.
    assert_readiness(scored, preflight=52.50, certified=0.00)
    assert_labor_ledger(
        scored,
        call["provisional_total_cents"],
        scored["labor_budget_total_cents"] - call["provisional_total_cents"],
    )
    assert_labor_ledger_conserved(scored)


# ---------------------------------------------------------------------------
# Redundancy class against booking role
# ---------------------------------------------------------------------------
def test_primary_booking_on_a_backup_only_circuit_is_refused(api, td_headers):
    """A standby-only circuit cannot carry the show's transport of record, and the
    refusal leaves the circuit's ledger completely untouched.

    PRD: "Redundancy is then checked: a booking whose role is `PRIMARY` requires the path's `redundancy_class` to be `PRIMARY_ELIGIBLE`, so a `BACKUP_ONLY` circuit may only ever carry standby bookings and a primary booking on one is refused with `ERR_PATH_REDUNDANCY_INVALID`."
    PRD: "Both aggregates start at zero: `committed_mbps_total` and `active_booking_count`."
    Design: Corner/validations/primary_booking_requires_a_primary_eligible_path
    """
    path = new_fiber_path(api, path_code="FIB-B", redundancy_class="BACKUP_ONLY")
    assert path["redundancy_class"] == "BACKUP_ONLY"
    assert_path_ledger(path, 0, 0)

    production = new_production(api)
    version_before = production_version(api, production["id"])

    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                production["id"], path["id"], version_before,
                booking_role="PRIMARY",
                window_start_utc=BOOKING_WINDOW_START,
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=100,
            ),
            td_headers,
        ),
        "ERR_PATH_REDUNDANCY_INVALID",
    )
    assert_path_ledger(read_path(api, path["id"]), 0, 0)
    assert read_production(api, production["id"])["version"] == version_before


def test_backup_booking_on_a_backup_only_circuit_is_accepted(api, td_headers):
    """The rule is about the role-and-class pair rather than the circuit being
    busy: the very same window is accepted as a standby route, and it earns no
    transmission credit.

    PRD: "Redundancy is then checked: a booking whose role is `PRIMARY` requires the path's `redundancy_class` to be `PRIMARY_ELIGIBLE`, so a `BACKUP_ONLY` circuit may only ever carry standby bookings and a primary booking on one is refused with `ERR_PATH_REDUNDANCY_INVALID`."
    PRD: "Its transmission predicate holds when the production has a booking whose `booking_role` is `PRIMARY` and whose status is any of `RESERVED`, `TEST_SCHEDULED`, `CONFIRMED` or `PROMOTED`."
    Design: Corner/validations/primary_booking_requires_a_primary_eligible_path
    """
    path = new_fiber_path(api, path_code="FIB-B", redundancy_class="BACKUP_ONLY")
    production = new_production(api)
    version_before = production_version(api, production["id"])

    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                production["id"], path["id"], version_before,
                booking_role="PRIMARY",
                window_start_utc=BOOKING_WINDOW_START,
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=100,
            ),
            td_headers,
        ),
        "ERR_PATH_REDUNDANCY_INVALID",
    )

    standby = validate_success(
        api.create_path_booking(
            create_path_booking_payload(
                production["id"], path["id"], version_before,
                booking_role="BACKUP",
                window_start_utc=BOOKING_WINDOW_START,
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=100,
            ),
            td_headers,
        ),
        201,
    )
    assert_path_booking(standby)
    assert_status(standby, "RESERVED")
    assert standby["booking_role"] == "BACKUP"
    assert_path_ledger(read_path(api, path["id"]), 100, 1)
    assert_readiness(read_production(api, production["id"]), preflight=0.00)


# ---------------------------------------------------------------------------
# Proving-window geometry
# ---------------------------------------------------------------------------
def test_test_window_escaping_the_booking_window_is_refused(api, td_headers):
    """A proving window that starts before the occupation opens, or ends after it
    closes, escapes the booking and is refused; a contained window is scheduled.

    PRD: "The test window must be non-empty — an end at or before the start is `ERR_INVALID_TIME_WINDOW` — and it must lie **fully inside** the booking's own occupation window, meaning the test start is at or after `window_start_utc` and the test end is at or before `window_end_utc`; a window that escapes the booking is refused with `ERR_TEST_WINDOW_INVALID`."
    PRD: "Scheduling the proving test writes a `test_window_start_utc` and `test_window_end_utc` onto the booking and moves it `RESERVED → TEST_SCHEDULED`; the same action is also the retest edge `TEST_FAILED → TEST_SCHEDULED`, and a booking in any other status is refused with `ERR_BOOKING_STATE_INVALID`."
    Design: Corner/validations/test_window_must_lie_inside_the_booking_window
    """
    production = new_production(api)
    path = new_fiber_path(api)
    booking = book_path(
        api, production["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )

    validate_error(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-15T11:00:00Z",
                test_window_end_utc="2026-08-15T13:00:00Z",
            ),
            td_headers,
        ),
        "ERR_TEST_WINDOW_INVALID",
    )
    validate_error(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-16T01:00:00Z",
                test_window_end_utc="2026-08-16T03:00:00Z",
            ),
            td_headers,
        ),
        "ERR_TEST_WINDOW_INVALID",
    )
    assert_status(read_booking(api, booking["id"]), "RESERVED")

    scheduled = validate_success(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-15T12:30:00Z",
                test_window_end_utc="2026-08-15T13:00:00Z",
            ),
            td_headers,
        ),
        200,
    )
    assert_status(scheduled, "TEST_SCHEDULED")
    assert_instant_equals(
        scheduled["test_window_start_utc"],
        "2026-08-15T12:30:00Z",
        "test_window_start_utc",
    )
    assert_instant_equals(
        scheduled["test_window_end_utc"],
        "2026-08-15T13:00:00Z",
        "test_window_end_utc",
    )


def test_reversed_test_window_is_refused_as_an_empty_interval(api, td_headers):
    """A proving window whose end is at or before its start is empty, and the
    emptiness clause is reported before containment is ever considered.

    PRD: "The test window must be non-empty — an end at or before the start is `ERR_INVALID_TIME_WINDOW` — and it must lie **fully inside** the booking's own occupation window, meaning the test start is at or after `window_start_utc` and the test end is at or before `window_end_utc`; a window that escapes the booking is refused with `ERR_TEST_WINDOW_INVALID`."
    Design: Corner/validations/test_window_must_lie_inside_the_booking_window
    """
    production = new_production(api)
    path = new_fiber_path(api)
    booking = book_path(
        api, production["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )

    validate_error(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-15T13:00:00Z",
                test_window_end_utc="2026-08-15T12:00:00Z",
            ),
            td_headers,
        ),
        "ERR_INVALID_TIME_WINDOW",
    )
    validate_error(
        api.schedule_path_test(
            booking["id"],
            schedule_path_test_payload(
                test_window_start_utc="2026-08-15T13:00:00Z",
                test_window_end_utc="2026-08-15T13:00:00Z",
            ),
            td_headers,
        ),
        "ERR_INVALID_TIME_WINDOW",
    )

    untouched = read_booking(api, booking["id"])
    assert_status(untouched, "RESERVED")
    assert untouched["test_window_start_utc"] is None


# ---------------------------------------------------------------------------
# Shared fiber capacity: window-scoped gate, path-wide ledger
# ---------------------------------------------------------------------------
def test_fiber_capacity_gate_is_window_scoped_while_the_ledger_is_not(api, td_headers):
    """200 + 100 fills a 300 Mbps circuit exactly, one more megabit on an
    overlapping window is refused, and a full 300 on an adjacent window is
    accepted - yet the path-wide ledger sums all three.

    PRD: "A **fiber circuit is shared**: concurrent bookings coexist on the circuit and only the aggregate bandwidth is constrained."
    PRD: "The set of concurrent bookings is those active bookings whose window overlaps the new one under half-open comparison — an existing booking starts strictly before the new window ends and the new window starts strictly before that existing booking ends — which means a booking that starts exactly when another ends is not concurrent with it."
    PRD: "The request is refused with `ERR_PATH_CAPACITY_EXCEEDED` when the sum of `requested_mbps` over that concurrent set, plus the new booking's own `requested_mbps`, is strictly greater than the path's `capacity_mbps`; a sum exactly equal to capacity is accepted."
    PRD: "For each transmission path, `committed_mbps_total` always equals the sum of `requested_mbps` over that path's bookings in the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` and `PROMOTED`, and `active_booking_count` is the count of that same row set."
    Design: Corner/validations/fiber_capacity_counts_only_overlapping_active_bookings
    """
    path = new_fiber_path(api, capacity_mbps=300)
    production_a = new_production(api)
    production_b = new_production(api, venue_name="Harbour Dome", venue_roof_type="DOMED")
    production_c = new_production(
        api, venue_name="Northgate Field", venue_roof_type="RETRACTABLE"
    )

    book_path(
        api, production_a["id"], path["id"], requested_mbps=200,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    book_path(
        api, production_b["id"], path["id"], requested_mbps=100,
        window_start_utc=BOOKING_WINDOW_START, window_end_utc=BOOKING_WINDOW_END,
    )
    assert_path_ledger(read_path(api, path["id"]), 300, 2)

    version_c = production_version(api, production_c["id"])
    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                production_c["id"], path["id"], version_c,
                window_start_utc="2026-08-15T20:00:00Z",
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=1,
            ),
            td_headers,
        ),
        "ERR_PATH_CAPACITY_EXCEEDED",
    )
    assert_path_ledger(read_path(api, path["id"]), 300, 2)

    # A window that starts exactly when the other two end is not concurrent with
    # them, so the full contracted capacity is available on it again.
    adjacent = validate_success(
        api.create_path_booking(
            create_path_booking_payload(
                production_c["id"], path["id"], version_c,
                window_start_utc=BOOKING_WINDOW_END,
                window_end_utc="2026-08-16T06:00:00Z",
                requested_mbps=300,
            ),
            td_headers,
        ),
        201,
    )
    assert_status(adjacent, "RESERVED")
    assert_instant_equals(
        adjacent["window_start_utc"], BOOKING_WINDOW_END, "window_start_utc"
    )
    assert_path_ledger(read_path(api, path["id"]), 600, 3)

    rows, meta = validate_paginated(
        api.list_path_bookings(
            td_headers, {"path_id": path["id"], "status": "RESERVED"}
        )
    )
    assert meta["total_count"] == 3
    assert all(row["status"] == "RESERVED" for row in rows)


# ---------------------------------------------------------------------------
# The booking's optimistic-concurrency token
# ---------------------------------------------------------------------------
def test_path_booking_replaying_the_pre_assignment_version_is_refused(api, td_headers):
    """A truck assignment advances the production version, so a booking presenting
    the pre-assignment token is refused before the bandwidth ledger is ever
    touched; the fresh token books normally.

    PRD: "If that value does not equal the referenced production's current `version`, the request is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412) and nothing is written."
    PRD: "A new `PRIMARY` path booking legitimately supersedes the production's existing `PRIMARY` booking, releasing it and returning its bandwidth, so a stale writer would tear down a transport arrangement it never observed."
    PRD: "A surviving booking is created at `RESERVED`; the path's `committed_mbps_total` rises by exactly the new `requested_mbps` and its `active_booking_count` by exactly 1."
    PRD: "Its transmission predicate holds when the production has a booking whose `booking_role` is `PRIMARY` and whose status is any of `RESERVED`, `TEST_SCHEDULED`, `CONFIRMED` or `PROMOTED`."
    Design: Corner/cross_cutting_complexity_layers/path_booking_occ_token_must_match_the_current_production_version
    """
    production = new_production(api)
    path = new_fiber_path(api)
    truck = new_truck(api)

    version_one = production_version(api, production["id"])
    assigned = assign_truck(api, production["id"], truck["id"])
    version_two = assigned["version"]
    assert version_two == version_one + 1

    validate_error(
        api.create_path_booking(
            create_path_booking_payload(
                production["id"], path["id"], version_one,
                window_start_utc=BOOKING_WINDOW_START,
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=200,
            ),
            td_headers,
        ),
        "ERR_STALE_PRODUCTION_VERSION",
    )
    assert_path_ledger(read_path(api, path["id"]), 0, 0)
    _rows, meta = validate_paginated(
        api.list_path_bookings(td_headers, {"production_id": production["id"]})
    )
    assert meta["total_count"] == 0, "the refused booking wrote no row at all"

    booked = validate_success(
        api.create_path_booking(
            create_path_booking_payload(
                production["id"], path["id"], version_two,
                window_start_utc=BOOKING_WINDOW_START,
                window_end_utc=BOOKING_WINDOW_END,
                requested_mbps=200,
            ),
            td_headers,
        ),
        201,
    )
    assert_path_booking(booked)
    assert_status(booked, "RESERVED")
    assert_path_ledger(read_path(api, path["id"]), 200, 1)

    scored = read_production(api, production["id"])
    assert_status(scored, "PLANNED", "production stage")
    assert_readiness(scored, preflight=25.00, certified=0.00)
