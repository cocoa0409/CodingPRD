"""Layers that cut across the whole service: version echoes, cascades, flags.

Optimistic concurrency is exercised on both echoed versions, the close-out
cascade is checked as one atomic fan-out rather than as separate reads, the
participant's four derived fields are reconciled after each write, and the
challenge's `logging_method` is shown to be the only input deciding the daily
cap.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_DAILY_LOG_CAP_EXCEEDED,
    ERR_STALE_PARTICIPANT_VERSION,
    ERR_STALE_PROGRAM_VERSION,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_date_equals,
    assert_lot_state,
    assert_one_decimal_pct,
    assert_program_status,
)
from test_helpers.factories import (
    log_correction_payload,
    log_entry_payload,
    reservation_payload,
)
from test_helpers.fixtures import LibraryWorld


class TestOptimisticConcurrencyOnBothEchoedVersions:
    """A stale echo is refused at 412 and leaves the version it echoed untouched."""

    def test_a_replayed_program_version_is_refused_and_the_refreshed_one_supersedes(
        self, world: LibraryWorld
    ) -> None:
        """Only the two accepted creates moved the program's version.

        "Creating a *second* reservation for the same program while echoing the
        current `version` is entirely legitimate and is the intended re-booking path:
        the program's prior `HELD` reservation moves to `SUPERSEDED` and the new one
        becomes the program's `HELD` reservation." and "When the echoed value does not
        match the program's current `version`, the reservation is rejected with
        `ERR_STALE_PROGRAM_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_a_second_reservation_returns_412
        """
        branch = world.branch()
        room = world.room(branch["id"])
        program = world.program(branch["id"])
        drafted_version = program["version"]

        first_hold = world.hold(
            program["id"],
            room["id"],
            expected_program_version=drafted_version,
            setup_minutes=15,
        )
        assert world.read_program(program["id"])["version"] == drafted_version + 1

        replayed = world.api.create_reservation(
            program["id"],
            reservation_payload(room["id"], drafted_version, setup_minutes=20),
            world.coordinator,
        )
        validate_error(
            replayed,
            ERR_STALE_PROGRAM_VERSION,
            ERROR_HTTP_STATUS[ERR_STALE_PROGRAM_VERSION],
        )
        assert world.read_program(program["id"])["version"] == drafted_version + 1

        second_hold = world.hold(
            program["id"],
            room["id"],
            expected_program_version=drafted_version + 1,
            setup_minutes=20,
        )
        assert world.read_program(program["id"])["version"] == drafted_version + 2

        superseded = world.read_reservation(first_hold["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["setup_minutes"] == 15
        standing = world.read_reservation(second_hold["id"])
        assert standing["status"] == "HELD"
        assert standing["setup_minutes"] == 20

        _, meta = validate_paginated(
            world.api.list_reservations(world.coordinator, program_id=program["id"])
        )
        assert meta["total_count"] == 2

    def test_an_intervening_log_entry_invalidates_an_in_flight_correction(
        self, world: LibraryWorld
    ) -> None:
        """The refreshed echo then lands the identical correction.

        "if a log entry was accepted for that participant after the caller's read,
        the echoed value is behind and the correction is rejected with
        `ERR_STALE_PARTICIPANT_VERSION` and HTTP 412 — before the target entry is
        validated at all." and "A participant's `version` increments by 1 on every
        accepted log entry and on every accepted correction alike".

        Design: Corner/cross_cutting_complexity_layers/stale_expected_participant_version_on_a_log_correction_returns_412
        """
        branch = world.branch()
        opened = world.opened_challenge()
        participant = world.participant(
            opened["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        first_entry = world.log_entry(participant["id"], 30, "2026-07-20")
        observed_version = world.participant_version(participant["id"])
        world.log_entry(participant["id"], 20, "2026-07-21")

        stale = world.api.create_log_correction(
            participant["id"],
            log_correction_payload(first_entry["id"], -10, observed_version),
            world.coordinator,
        )
        validate_error(
            stale,
            ERR_STALE_PARTICIPANT_VERSION,
            ERROR_HTTP_STATUS[ERR_STALE_PARTICIPANT_VERSION],
        )

        refreshed_version = world.participant_version(participant["id"])
        assert refreshed_version == observed_version + 1

        correction = get_success_data(
            world.api.create_log_correction(
                participant["id"],
                log_correction_payload(first_entry["id"], -10, refreshed_version),
                world.coordinator,
            ),
            201,
        )
        assert correction["entry_type"] == "CORRECTION"
        assert correction["units_delta"] == -10
        assert correction["corrected_entry_id"] == first_entry["id"]

        settled = world.read_participant(participant["id"])
        assert settled["cumulative_units"] == 40
        assert settled["entry_count"] == 3
        assert_date_equals(settled["last_entry_on"], "2026-07-21", "last_entry_on")
        assert settled["version"] == refreshed_version + 1


class TestCloseOutFiresEveryLinkInOneResponse:
    """Four links move together: the program, its money, its lot and its contract."""

    def test_one_close_out_call_settles_program_money_stock_and_contract(
        self, world: LibraryWorld
    ) -> None:
        """The committed encumbrance becomes spent without changing the variance.

        "`materials_committed_cents` moves wholesale into `materials_spent_cents`
        and drops to 0" and "Each entry in `supply_draw_lines` moves its `units` from
        its lot's `quantity_reserved` to that lot's `quantity_issued`" and "Every
        contract of this program whose `status` is `EXECUTED` becomes `COMPLETED`,
        `presenter_fee_committed_cents` moves wholesale into
        `presenter_fee_spent_cents` and drops to 0".

        Design: Corner/cross_cutting_complexity_layers/close_out_cascade_moves_committed_money_to_spent_and_completes_the_contract
        """
        branch = world.branch()
        room = world.room(branch["id"], capacity_seats=60)
        lot = world.supply_lot(
            branch["id"],
            sku="CRAFT-KIT",
            unit_cost_cents=250,
            quantity_procured=100,
            reuse_pool=False,
        )
        program = world.adult_program(
            branch["id"],
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
        )
        reservation = world.hold(program["id"], room["id"])
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])
        world.register(program["id"], registrant_reference="card-0001", seats=1)
        presenter = world.presenter()
        contract = world.executed_contract(presenter["id"], program["id"])
        assert contract["total_fee_cents"] == 50000
        confirmed = world.confirm_program(program["id"])
        assert confirmed["materials_committed_cents"] == 2750
        assert confirmed["confirmed_room_capacity"] == 60

        world.set_clock("2026-08-12T16:00:00.000Z")
        closed = world.close_out(program["id"], 1, 3, 2)

        assert_program_status(closed, operational_status="CLOSED_OUT")
        assert closed["gross_attendance"] == 4
        assert closed["no_show_count"] == 0
        assert_one_decimal_pct(
            closed["survey_response_rate_pct"], 50.0, "survey_response_rate_pct"
        )
        assert_one_decimal_pct(
            closed["attendance_attainment_funder_pct"],
            40.0,
            "attendance_attainment_funder_pct",
        )
        assert_one_decimal_pct(
            closed["attendance_attainment_internal_pct"],
            6.7,
            "attendance_attainment_internal_pct",
        )

        assert closed["materials_spent_cents"] == 2750
        assert closed["materials_committed_cents"] == 0
        assert closed["presenter_fee_spent_cents"] == 50000
        assert closed["presenter_fee_committed_cents"] == 0
        assert_budget_variance_and_posture(closed, 197250, "WITHIN_BUDGET")

        settled_lot = world.read_lot(lot["id"])
        assert_lot_state(settled_lot, available=90, reserved=0, issued=10)
        assert settled_lot["status"] == "ACTIVE"

        completed = world.read_contract(contract["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["total_fee_cents"] == 50000
        assert completed["kill_fee_cents"] == 0


class TestParticipantDerivedFieldReconciliation:
    """Four derived fields, recomputed from the ledger after every single write."""

    def test_each_write_re_derives_the_sum_the_count_and_the_last_log_date(
        self, world: LibraryWorld
    ) -> None:
        """The correction moves the sum and the count but never the last log date.

        "A new participant reports `cumulative_units`, `awarded_tier_index`,
        `eligible_tier_index` and `entry_count` all 0 and `last_entry_on` null" and
        "An accepted log entry re-derives the participant's `cumulative_units`,
        `eligible_tier_index`, `entry_count` (which counts entries of both types) and
        `last_entry_on` (the greatest `logged_on` across the participant's `LOG`
        entries only)".

        Design: Corner/cross_cutting_complexity_layers/participant_derived_fields_reconcile_after_each_entry_and_correction
        """
        branch = world.branch()
        opened = world.opened_challenge()
        participant = world.participant(
            opened["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        assert participant["cumulative_units"] == 0
        assert participant["entry_count"] == 0
        assert participant["last_entry_on"] is None
        assert participant["eligible_tier_index"] == 0
        assert participant["awarded_tier_index"] == 0

        first_entry = world.log_entry(participant["id"], 50, "2026-07-20")
        world.log_entry(participant["id"], 25, "2026-07-25")

        after_entries = world.read_participant(participant["id"])
        assert after_entries["cumulative_units"] == 75
        assert after_entries["entry_count"] == 2
        assert_date_equals(
            after_entries["last_entry_on"], "2026-07-25", "last_entry_on"
        )

        world.correction(participant["id"], first_entry["id"], -15)

        after_correction = world.read_participant(participant["id"])
        assert after_correction["cumulative_units"] == 60
        assert after_correction["entry_count"] == 3
        assert_date_equals(
            after_correction["last_entry_on"], "2026-07-25", "last_entry_on"
        )
        assert after_correction["eligible_tier_index"] == 0

        rows, meta = validate_paginated(
            world.api.list_log_entries(
                world.manager, participant_id=participant["id"], limit=100
            )
        )
        assert meta["total_count"] == 3
        assert len([row for row in rows if row["entry_type"] == "CORRECTION"]) == 1


class TestLoggingMethodDecidesTheDailyCap:
    """One field on the challenge, and nothing else, sets the per-date ceiling."""

    def test_the_same_six_units_are_refused_on_activities_and_accepted_on_books(
        self, world: LibraryWorld
    ) -> None:
        """Exactly the activities cap is admissible while one unit past it is not.

        "the participant's net `LOG` units for that single `logged_on` date,
        including the entry being posted and after accounting for any corrections
        already recorded against that date, may not exceed the cap implied by the
        challenge's `logging_method` — 300 for `MINUTES`, 10 for `BOOKS` and 5 for
        `ACTIVITIES`. Exceeding it is `ERR_DAILY_LOG_CAP_EXCEEDED`."

        Design: Corner/cross_cutting_complexity_layers/logging_method_flag_sets_the_daily_cap
        """
        branch = world.branch()
        activities = world.opened_challenge(
            name="Activities Summer 2026",
            logging_method="ACTIVITIES",
            unit_label="activities",
        )
        books = world.opened_challenge(
            name="Books Summer 2026", logging_method="BOOKS", unit_label="books"
        )
        activities_reader = world.participant(
            activities["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        books_reader = world.participant(
            books["challenge"]["id"],
            branch["id"],
            display_name="Bo N.",
            age_band="AGE_12_17",
        )

        refused = world.api.create_log_entry(
            activities_reader["id"],
            log_entry_payload(6, "2026-07-20", "STAFF_DESK"),
            world.coordinator,
        )
        validate_error(
            refused,
            ERR_DAILY_LOG_CAP_EXCEEDED,
            ERROR_HTTP_STATUS[ERR_DAILY_LOG_CAP_EXCEEDED],
        )

        at_the_cap = get_success_data(
            world.api.create_log_entry(
                activities_reader["id"],
                log_entry_payload(5, "2026-07-20", "STAFF_DESK"),
                world.coordinator,
            ),
            201,
        )
        assert at_the_cap["units"] == 5

        under_the_books_cap = get_success_data(
            world.api.create_log_entry(
                books_reader["id"],
                log_entry_payload(6, "2026-07-20", "STAFF_DESK"),
                world.coordinator,
            ),
            201,
        )
        assert under_the_books_cap["units"] == 6

        assert world.read_participant(activities_reader["id"])["cumulative_units"] == 5
        assert world.read_participant(books_reader["id"])["cumulative_units"] == 6
