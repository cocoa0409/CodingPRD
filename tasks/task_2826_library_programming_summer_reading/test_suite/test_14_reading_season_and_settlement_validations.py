"""Refusals in the reading season, the negotiation and the settlement calls.

The reading ladder guards provenance, dates and a per-day allowance; the
correction endpoint guards its target and its floor; and the money endpoints
guard the fee cap, the materials budget and the two ending windows.  Each case
also reads the neighbouring admissible call where one exists, so a gate is never
proved by a single refusal alone.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS,
    ERR_CHALLENGE_WINDOW_STILL_OPEN,
    ERR_CORRECTION_TARGET_INVALID,
    ERR_CORRECTION_WOULD_GO_NEGATIVE,
    ERR_DAILY_LOG_CAP_EXCEEDED,
    ERR_FEE_CAP_EXCEEDED,
    ERR_LOG_DATE_IN_FUTURE,
    ERR_LOG_DATE_OUTSIDE_WINDOW,
    ERR_LOG_SOURCE_NOT_PERMITTED,
    ERR_MATERIALS_BUDGET_EXCEEDED,
    ERR_PRESENTER_INSURANCE_LAPSED,
    ERR_PRESENTER_SUSPENDED,
    ERR_PROGRAM_NOT_YET_ENDED,
    ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE,
    ERR_TIER_SEQUENCE_INVALID,
    ERR_WEATHER_WINDOW_PASSED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_lot_state,
    assert_materials_conservation,
    assert_one_decimal_pct,
    assert_program_status,
    assert_supply_draw_lines,
)
from test_helpers.factories import (
    close_out_payload,
    closure_payload,
    log_correction_payload,
    log_entry_payload,
    offer_payload,
    tier_payload,
)
from test_helpers.fixtures import LibraryWorld
from test_helpers.test_users import make_reader_headers

HIGH_TIER = [
    {
        "tier_index": 1,
        "threshold_units": 5000,
        "prize_sku": "MEDAL",
        "prize_units_per_participant": 1,
    }
]


def _one_reader_in_an_open_challenge(
    world: LibraryWorld, **challenge_kwargs: Any
) -> Dict[str, Any]:
    """An OPEN challenge with a single enrolled reader and an unreachable tier."""
    branch = world.branch()
    opened = world.opened_challenge(tiers=HIGH_TIER, **challenge_kwargs)
    participant = world.participant(
        opened["challenge"]["id"],
        branch["id"],
        display_name="Ada L.",
        age_band="AGE_5_11",
    )
    return {
        "branch": branch,
        "challenge": opened["challenge"],
        "tier": opened["tiers"][0],
        "participant": participant,
    }


class TestReadingLogEntryRefusals:
    """Provenance, the inclusive window, the clock and the per-day allowance."""

    def test_a_reader_may_only_claim_self_service_provenance(
        self, world: LibraryWorld
    ) -> None:
        """The identical payload succeeds once the source is the reader's own.

        "A `Reader` may only claim `SELF_SERVICE` provenance; a reader posting
        `STAFF_DESK` or `OUTREACH_SITE` is refused with
        `ERR_LOG_SOURCE_NOT_PERMITTED`, because those two sources assert that a
        staff member witnessed the entry."

        Design: Corner/validations/reader_may_not_log_a_staff_desk_entry
        """
        scenario = _one_reader_in_an_open_challenge(world)
        participant_id = scenario["participant"]["id"]

        validate_error(
            world.api.create_log_entry(
                participant_id,
                log_entry_payload(30, "2026-07-20", "STAFF_DESK"),
                make_reader_headers(participant_id),
            ),
            ERR_LOG_SOURCE_NOT_PERMITTED,
            ERROR_HTTP_STATUS[ERR_LOG_SOURCE_NOT_PERMITTED],
        )

        accepted = world.reader_log_entry(participant_id, 30, "2026-07-20")
        assert accepted["source"] == "SELF_SERVICE"

        after = world.read_participant(participant_id)
        assert after["cumulative_units"] == 30
        assert after["entry_count"] == 1

    def test_the_challenge_window_is_inclusive_of_its_first_day(
        self, world: LibraryWorld
    ) -> None:
        """The thirtieth of June is outside; the first of July is inside.

        "Next, `logged_on` must lie inside the challenge's inclusive window from
        `start_on` to `end_on`; a date outside it is `ERR_LOG_DATE_OUTSIDE_WINDOW`,
        and both endpoints are admissible."

        Design: Corner/validations/log_entry_dated_before_the_challenge_window_rejected
        """
        scenario = _one_reader_in_an_open_challenge(world)
        participant_id = scenario["participant"]["id"]

        validate_error(
            world.api.create_log_entry(
                participant_id,
                log_entry_payload(30, "2026-06-30"),
                world.coordinator,
            ),
            ERR_LOG_DATE_OUTSIDE_WINDOW,
            ERROR_HTTP_STATUS[ERR_LOG_DATE_OUTSIDE_WINDOW],
        )

        accepted = world.log_entry(participant_id, 30, "2026-07-01")
        assert accepted["units"] == 30

        after = world.read_participant(participant_id)
        assert after["cumulative_units"] == 30
        assert after["entry_count"] == 1

    def test_a_date_inside_the_window_but_ahead_of_the_clock_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The window rule passes and the clock rule fires instead.

        "Next, `logged_on` must not be after the logical clock's date; a
        future-dated entry is `ERR_LOG_DATE_IN_FUTURE`, while an entry dated exactly
        today is fine."

        Design: Corner/validations/log_entry_dated_after_the_logical_clock_rejected
        """
        scenario = _one_reader_in_an_open_challenge(world)
        participant_id = scenario["participant"]["id"]

        error = validate_error(
            world.api.create_log_entry(
                participant_id,
                log_entry_payload(30, "2026-08-05"),
                world.coordinator,
            ),
            ERR_LOG_DATE_IN_FUTURE,
            ERROR_HTTP_STATUS[ERR_LOG_DATE_IN_FUTURE],
        )
        assert error["error_id"] != ERR_LOG_DATE_OUTSIDE_WINDOW

        refused = world.read_participant(participant_id)
        assert refused["cumulative_units"] == 0
        assert refused["entry_count"] == 0

        world.set_clock("2026-08-05T00:00:00.000Z")
        accepted = world.log_entry(participant_id, 30, "2026-08-05")
        assert accepted["units"] == 30
        assert world.read_participant(participant_id)["entry_count"] == 1

    def test_the_books_allowance_is_spent_per_date_not_per_entry(
        self, world: LibraryWorld
    ) -> None:
        """Six books then five breaches ten; the same five on the next day does not.

        "The cap is per date, not per entry and not per challenge: three separate
        100-minute entries on one date are fine, a fourth is not, and the same three
        entries spread across three dates are never in tension."

        Design: Corner/validations/minutes_log_that_crosses_the_daily_cap_rejected
        """
        scenario = _one_reader_in_an_open_challenge(
            world,
            logging_method="BOOKS",
            unit_label="books",
        )
        participant_id = scenario["participant"]["id"]
        world.log_entry(participant_id, 6, "2026-07-20")

        validate_error(
            world.api.create_log_entry(
                participant_id, log_entry_payload(5, "2026-07-20"), world.coordinator
            ),
            ERR_DAILY_LOG_CAP_EXCEEDED,
            ERROR_HTTP_STATUS[ERR_DAILY_LOG_CAP_EXCEEDED],
        )

        accepted = world.log_entry(participant_id, 5, "2026-07-21")
        assert accepted["units"] == 5

        after = world.read_participant(participant_id)
        assert after["cumulative_units"] == 11
        assert after["entry_count"] == 2
        assert after["last_entry_on"] == "2026-07-21"


class TestCorrectionAndLadderRefusals:
    """The correction target, the per-entry floor, the ladder and the window."""

    def test_an_entry_that_has_already_been_corrected_cannot_be_corrected_again(
        self, world: LibraryWorld
    ) -> None:
        """A current version does not rescue a superseded target.

        "If the echo is current, `corrected_entry_id` must name an entry whose
        `entry_type` is `LOG`, which belongs to this same participant, and which no
        earlier `CORRECTION` has already superseded; naming a correction entry,
        another participant's entry, or an already-corrected entry is
        `ERR_CORRECTION_TARGET_INVALID`."

        Design: Corner/validations/correcting_an_already_corrected_entry_rejected
        """
        scenario = _one_reader_in_an_open_challenge(world)
        participant_id = scenario["participant"]["id"]
        entry = world.log_entry(participant_id, 30, "2026-07-20")
        world.correction(participant_id, entry["id"], -10)
        version_before = world.participant_version(participant_id)

        validate_error(
            world.api.create_log_correction(
                participant_id,
                log_correction_payload(entry["id"], -5, version_before),
                world.coordinator,
            ),
            ERR_CORRECTION_TARGET_INVALID,
            ERROR_HTTP_STATUS[ERR_CORRECTION_TARGET_INVALID],
        )

        after = world.read_participant(participant_id)
        assert after["cumulative_units"] == 20
        assert after["entry_count"] == 2
        assert after["version"] == version_before

        _, meta = validate_paginated(
            world.api.list_log_entries(
                world.coordinator, corrected_entry_id=entry["id"]
            )
        )
        assert meta["total_count"] == 1

    def test_the_negative_floor_is_measured_on_the_target_entry_alone(
        self, world: LibraryWorld
    ) -> None:
        """Eighty cumulative units cannot absorb a forty-unit cut to a thirty.

        "Then `units_delta` must be non-zero and must leave the target entry's own
        post-correction units at or above 0 — a correction may reduce an entry to
        nothing but may not drive a single entry negative — failing which the answer
        is `ERR_CORRECTION_WOULD_GO_NEGATIVE`."

        Design: Corner/validations/correction_that_would_drive_one_entry_negative_rejected
        """
        scenario = _one_reader_in_an_open_challenge(world)
        participant_id = scenario["participant"]["id"]
        small_entry = world.log_entry(participant_id, 30, "2026-07-20")
        world.log_entry(participant_id, 50, "2026-07-21")
        version_before = world.participant_version(participant_id)

        validate_error(
            world.api.create_log_correction(
                participant_id,
                log_correction_payload(small_entry["id"], -40, version_before),
                world.coordinator,
            ),
            ERR_CORRECTION_WOULD_GO_NEGATIVE,
            ERROR_HTTP_STATUS[ERR_CORRECTION_WOULD_GO_NEGATIVE],
        )

        refused = world.read_participant(participant_id)
        assert refused["cumulative_units"] == 80
        assert refused["entry_count"] == 2
        assert refused["version"] == version_before

        world.correction(participant_id, small_entry["id"], -30)
        assert world.read_participant(participant_id)["cumulative_units"] == 50

    def test_the_ladder_admits_neither_a_flat_threshold_nor_a_skipped_index(
        self, world: LibraryWorld
    ) -> None:
        """Both ordering constraints hold jointly, and either breach reads the same.

        "Two ordering constraints hold jointly: `tier_index` must be exactly one
        greater than the challenge's current highest tier index — so the first tier
        must be 1, the second 2, and no gap or repeat is ever admitted — and
        `threshold_units` must be strictly greater than the previous tier's
        `threshold_units`. Either violation is reported as
        `ERR_TIER_SEQUENCE_INVALID`."

        Design: Corner/validations/incentive_tier_whose_threshold_does_not_rise_rejected
        """
        challenge = world.challenge()
        world.tier(challenge["id"], tier_index=1, threshold_units=60)

        validate_error(
            world.api.create_incentive_tier(
                challenge["id"],
                tier_payload(tier_index=2, threshold_units=60),
                world.manager,
            ),
            ERR_TIER_SEQUENCE_INVALID,
            ERROR_HTTP_STATUS[ERR_TIER_SEQUENCE_INVALID],
        )
        validate_error(
            world.api.create_incentive_tier(
                challenge["id"],
                tier_payload(tier_index=3, threshold_units=120),
                world.manager,
            ),
            ERR_TIER_SEQUENCE_INVALID,
            ERROR_HTTP_STATUS[ERR_TIER_SEQUENCE_INVALID],
        )

        _, meta = validate_paginated(
            world.api.list_incentive_tiers(
                world.manager, challenge_id=challenge["id"]
            )
        )
        assert meta["total_count"] == 1

    def test_the_final_logging_day_is_still_too_early_to_reconcile(
        self, world: LibraryWorld
    ) -> None:
        """Strictly after end_on means the thirty-first of August will not do.

        "only after the logging window has actually shut: the logical clock's date
        must be strictly after the challenge's `end_on`, and a reconciliation
        attempted on or before that date is refused with
        `ERR_CHALLENGE_WINDOW_STILL_OPEN`."

        Design: Corner/validations/reconciling_on_the_final_day_of_the_challenge_rejected
        """
        opened = world.opened_challenge(tiers=HIGH_TIER)
        challenge_id = opened["challenge"]["id"]
        world.set_clock("2026-08-31T23:00:00.000Z")

        validate_error(
            world.api.reconcile_challenge(challenge_id, world.manager),
            ERR_CHALLENGE_WINDOW_STILL_OPEN,
            ERROR_HTTP_STATUS[ERR_CHALLENGE_WINDOW_STILL_OPEN],
        )
        assert world.read_challenge(challenge_id)["status"] == "OPEN"

        world.set_clock("2026-09-01T00:00:00.000Z")
        reconciled = get_success_data(
            world.api.reconcile_challenge(challenge_id, world.manager), 200
        )
        assert reconciled["status"] == "RECONCILED"


def _offered_contract_on_an_adult_program(
    world: LibraryWorld,
    *,
    offered_fee_cents: int = 50000,
    round_trip_miles: int = 20,
    **presenter_kwargs: Any,
) -> Dict[str, Any]:
    """A DRAFT adult program with a live offer standing against it."""
    branch = world.branch()
    program = world.adult_program(branch["id"])
    presenter = world.presenter(**presenter_kwargs)
    contract = world.contract(
        presenter["id"], program["id"], round_trip_miles=round_trip_miles
    )
    world.offer(contract["id"], offered_fee_cents, world.manager)
    return {
        "branch": branch,
        "program": program,
        "presenter": presenter,
        "contract": contract,
    }


class TestContractExecutionRefusals:
    """The certificate date, the fee ceiling and the suspension gate."""

    def test_a_certificate_lapsing_a_day_early_stops_the_execution(
        self, world: LibraryWorld
    ) -> None:
        """The comparison is against the calendar date of the program's end.

        "Second, the presenter's `insurance_certificate_expires_on` must fall on
        or after the calendar date of the program's `end_utc`, failing which the
        answer is `ERR_PRESENTER_INSURANCE_LAPSED`."

        Design: Corner/validations/contract_execution_with_a_certificate_expiring_before_the_program_rejected
        """
        scenario = _offered_contract_on_an_adult_program(
            world, insurance_certificate_expires_on="2026-08-11"
        )

        validate_error(
            world.api.execute_contract(
                scenario["contract"]["id"], world.second_manager
            ),
            ERR_PRESENTER_INSURANCE_LAPSED,
            ERROR_HTTP_STATUS[ERR_PRESENTER_INSURANCE_LAPSED],
        )

        contract = world.read_contract(scenario["contract"]["id"])
        assert contract["status"] == "OFFERED"
        assert contract["total_fee_cents"] == 0
        assert contract["agreed_fee_cents"] is None

        program = world.read_program(scenario["program"]["id"])
        assert program["presenter_fee_committed_cents"] == 0
        assert_program_status(program, compliance_status="UNVERIFIED")

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["engagement_status"] == "PROSPECT"
        assert presenter["executed_contract_count"] == 0

    def test_the_fee_ceiling_is_tested_against_the_computed_total(
        self, world: LibraryWorld
    ) -> None:
        """Twenty-one miles adds sixty-five cents and that is the whole breach.

        "`total_fee_cents` is compared against a ceiling that is the smaller of a
        system-wide cap of 250000 cents and the owning branch's
        `per_program_fee_cap_cents`, and a total above that ceiling is rejected
        outright with `ERR_FEE_CAP_EXCEEDED` — the contract stays `OFFERED` and
        nothing is stored."

        Design: Corner/validations/contract_whose_total_exceeds_the_branch_cap_rejected
        """
        scenario = _offered_contract_on_an_adult_program(
            world, offered_fee_cents=150000, round_trip_miles=21
        )
        assert scenario["branch"]["per_program_fee_cap_cents"] == 150000

        validate_error(
            world.api.execute_contract(
                scenario["contract"]["id"], world.second_manager
            ),
            ERR_FEE_CAP_EXCEEDED,
            ERROR_HTTP_STATUS[ERR_FEE_CAP_EXCEEDED],
        )

        contract = world.read_contract(scenario["contract"]["id"])
        assert contract["status"] == "OFFERED"
        assert contract["total_fee_cents"] == 0
        assert contract["travel_fee_cents"] == 0
        assert contract["agreed_fee_cents"] is None

        program = world.read_program(scenario["program"]["id"])
        assert program["presenter_fee_committed_cents"] == 0
        assert_budget_variance_and_posture(program, 250000, "WITHIN_BUDGET")

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["executed_contract_count"] == 0
        assert presenter["engagement_status"] == "PROSPECT"

    def test_a_suspended_presenter_cannot_be_offered_even_a_draft_contract(
        self, world: LibraryWorld
    ) -> None:
        """The draft survives the flag and the offer is what fails.

        "A suspended presenter cannot be contracted at all, so a draft against a
        presenter whose `engagement_status` is `SUSPENDED` is rejected with
        `ERR_PRESENTER_SUSPENDED`."

        Design: Corner/validations/offering_a_draft_contract_for_a_suspended_presenter_rejected
        """
        branch = world.branch()
        program = world.adult_program(branch["id"])
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program["id"])
        world.request_screening(presenter["id"])
        world.screening_result(presenter["id"], "FLAGGED", "2026-08-01")

        validate_error(
            world.api.offer_contract(
                contract["id"], offer_payload(50000), world.manager
            ),
            ERR_PRESENTER_SUSPENDED,
            ERROR_HTTP_STATUS[ERR_PRESENTER_SUSPENDED],
        )

        after = world.read_contract(contract["id"])
        assert after["status"] == "DRAFT"
        assert after["negotiation_round"] == 0
        assert after["offered_fee_cents"] is None

        suspended = world.read_presenter(presenter["id"])
        assert suspended["engagement_status"] == "SUSPENDED"
        assert suspended["screening_status"] == "PENDING_ADJUDICATION"

        assert_program_status(
            world.read_program(program["id"]), compliance_status="UNVERIFIED"
        )


def _scheduled_craft_program(world: LibraryWorld, **program_kwargs: Any) -> Dict[str, Any]:
    """A published in-branch program with a CONFIRMED room and stock to draw on."""
    branch = world.branch()
    room = world.room(branch["id"])
    lot = world.supply_lot(
        branch["id"],
        sku="CRAFT-KIT",
        unit_cost_cents=250,
        quantity_procured=100,
        reuse_pool=False,
    )
    program = world.program(branch["id"], **program_kwargs)
    reservation = world.hold(program["id"], room["id"])
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    return {
        "branch": branch,
        "room": room,
        "lot": lot,
        "program": program,
        "reservation": reservation,
    }


class TestConfirmationAndSettlementGates:
    """The materials budget, the two ending windows and the satisfaction case."""

    def test_only_the_contingency_breaches_the_materials_budget(
        self, world: LibraryWorld
    ) -> None:
        """A ten-thousand subtotal fits ten thousand five hundred; eleven does not.

        "If `materials_committed_cents` would exceed the program's
        `materials_budget_cents`, the confirmation is refused with
        `ERR_MATERIALS_BUDGET_EXCEEDED` and, once again, nothing is allocated — the
        lots are left exactly as they were."

        Design: Corner/validations/confirm_whose_draw_plus_contingency_exceeds_the_budget_rejected
        """
        scenario = _scheduled_craft_program(
            world,
            attendance_target=40,
            attendance_cap=50,
            materials_budget_cents=10500,
        )

        validate_error(
            world.api.confirm_program(scenario["program"]["id"], world.manager),
            ERR_MATERIALS_BUDGET_EXCEEDED,
            ERROR_HTTP_STATUS[ERR_MATERIALS_BUDGET_EXCEEDED],
        )

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(program, operational_status="SCHEDULED")
        assert_supply_draw_lines(program, [])
        assert program["materials_committed_cents"] == 0
        assert program["materials_available_cents"] == 10500
        assert_materials_conservation(program)

        assert_lot_state(
            world.read_lot(scenario["lot"]["id"]),
            available=100,
            reserved=0,
            issued=0,
            status="ACTIVE",
        )

    def test_a_program_still_running_cannot_be_closed_out(
        self, world: LibraryWorld
    ) -> None:
        """The counts supplied at half past two are discarded entirely.

        "it requires the logical clock to be at or after the program's `end_utc`; a
        clock still inside the program's window reports `ERR_PROGRAM_NOT_YET_ENDED`".

        Design: Corner/validations/close_out_before_the_program_ends_rejected
        """
        scenario = _scheduled_craft_program(world)
        confirmed = world.confirm_program(scenario["program"]["id"])
        assert confirmed["materials_committed_cents"] == 2750
        world.set_clock("2026-08-12T14:30:00.000Z")

        validate_error(
            world.api.close_out_program(
                scenario["program"]["id"], close_out_payload(5, 2, 3), world.manager
            ),
            ERR_PROGRAM_NOT_YET_ENDED,
            ERROR_HTTP_STATUS[ERR_PROGRAM_NOT_YET_ENDED],
        )

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(program, operational_status="CONFIRMED")
        assert program["gross_attendance"] == 0
        assert program["materials_spent_cents"] == 0
        assert program["materials_committed_cents"] == 2750

    def test_the_registration_check_answers_before_the_survey_check(
        self, world: LibraryWorld
    ) -> None:
        """One payload breaches both coherence rules and the earlier one replies.

        "`verified_registrant_attendance` may not exceed the program's
        `registered_count`, failing which the answer is
        `ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS` — you cannot verify more registrants
        than registered."

        Design: Corner/validations/close_out_count_ladder_prefers_the_registration_check_over_the_survey_check
        """
        scenario = _scheduled_craft_program(world)
        program_id = scenario["program"]["id"]
        world.register(program_id, registrant_reference="card-0001", seats=1)
        world.confirm_program(program_id)
        world.set_clock("2026-08-12T16:00:00.000Z")

        first = validate_error(
            world.api.close_out_program(
                program_id, close_out_payload(2, 0, 5), world.manager
            ),
            ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS,
            ERROR_HTTP_STATUS[ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS],
        )
        assert first["error_id"] != ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE

        validate_error(
            world.api.close_out_program(
                program_id, close_out_payload(1, 0, 2), world.manager
            ),
            ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE,
            ERROR_HTTP_STATUS[ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE],
        )

        closed = world.close_out(program_id, 1, 0, 1)
        assert_program_status(closed, operational_status="CLOSED_OUT")
        assert closed["gross_attendance"] == 1
        assert closed["no_show_count"] == 0
        assert_one_decimal_pct(
            closed["survey_response_rate_pct"], 100.0, "survey_response_rate_pct"
        )
        assert closed["materials_spent_cents"] == 2750
        assert closed["materials_committed_cents"] == 0

    def test_a_weather_closure_declared_after_the_end_instant_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The state gate passes and the temporal gate is what stops the call.

        "it requires the logical clock to be strictly before the program's
        `end_utc`: a closure declared after the program has already ended is refused
        with `ERR_WEATHER_WINDOW_PASSED`, because by then the event either happened
        or did not."

        Design: Corner/validations/weather_closure_declared_after_the_program_ended_rejected
        """
        scenario = _scheduled_craft_program(world)
        world.confirm_program(scenario["program"]["id"])
        world.set_clock("2026-08-12T16:00:00.000Z")

        validate_error(
            world.api.weather_close_program(
                scenario["program"]["id"],
                closure_payload("Regional flood warning"),
                world.manager,
            ),
            ERR_WEATHER_WINDOW_PASSED,
            ERROR_HTTP_STATUS[ERR_WEATHER_WINDOW_PASSED],
        )

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(program, operational_status="CONFIRMED")
        assert program["closure_reason"] is None
        assert_lot_state(
            world.read_lot(scenario["lot"]["id"]),
            available=90,
            reserved=10,
            issued=0,
            status="ACTIVE",
        )

    def test_a_confirmation_that_satisfies_every_gate_commits_in_full(
        self, world: LibraryWorld
    ) -> None:
        """An available room, a confirmed booking, room in the staffing ceiling and stock.

        "An accepted confirmation stores `supply_draw_lines`, moves each drawn
        lot's units from `quantity_available` to `quantity_reserved` (re-deriving
        `quantity_available` and setting the lot's `status` to `DEPLETED` when it
        reaches 0), stores `materials_committed_cents` and
        `materials_available_cents`".

        Design: Corner/validations/confirm_passes_when_every_gate_from_eighteen_to_forty_seven_is_satisfied
        """
        scenario = _scheduled_craft_program(world)
        assert scenario["branch"]["overlapping_program_capacity"] == 2
        assert scenario["room"]["capacity_seats"] == 60

        confirmed = get_success_data(
            world.api.confirm_program(scenario["program"]["id"], world.manager), 200
        )
        assert_program_status(confirmed, operational_status="CONFIRMED")
        assert confirmed["materials_committed_cents"] == 2750
        assert confirmed["materials_available_cents"] == 47250
        assert_materials_conservation(confirmed)
        assert_supply_draw_lines(
            confirmed,
            [
                {
                    "lot_id": scenario["lot"]["id"],
                    "units": 10,
                    "unit_cost_cents": 250,
                    "surcharge_cents": 0,
                    "line_total_cents": 2500,
                }
            ],
        )
        assert_budget_variance_and_posture(confirmed, 247250, "WITHIN_BUDGET")

        assert_lot_state(
            world.read_lot(scenario["lot"]["id"]),
            available=90,
            reserved=10,
            issued=0,
            status="ACTIVE",
        )
        assert world.read_branch(scenario["branch"]["id"])[
            "programs_over_budget_count"
        ] == 0
