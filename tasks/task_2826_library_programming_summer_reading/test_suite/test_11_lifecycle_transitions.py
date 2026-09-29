"""Declared edges of every published state machine, taken one edge at a time.

Each entity in this service carries its own machine, and the interesting claims
are the edges that are legal, the edges that are refused, the initial state each
machine starts in and the terminal states that admit nothing further.  A refusal
here is always a state refusal: the payload of every rejected request is
impeccable and only the state of the entity it addresses is wrong.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_CHALLENGE_HAS_NO_TIERS,
    ERR_CHALLENGE_STATE_INVALID,
    ERR_CONTRACT_STATE_INVALID,
    ERR_PROGRAM_STATE_INVALID,
    ERR_RESERVATION_STATE_INVALID,
    ERR_SCREENING_STATE_INVALID,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_award_pricing,
    assert_date_equals,
    assert_deferred_award,
    assert_lot_state,
    assert_materials_conservation,
    assert_one_decimal_pct,
    assert_prize_conservation,
    assert_program_status,
)
from test_helpers.factories import (
    counter_payload,
    reservation_payload,
    screening_result_payload,
    tier_payload,
)
from test_helpers.fixtures import LibraryWorld


class TestProgramOperationalTransitions:
    """The publish edge, two refused edges and one terminal state."""

    def test_publishing_on_a_merely_held_reservation_leaves_that_hold_untouched(
        self, world: LibraryWorld
    ) -> None:
        """A HELD booking already satisfies the space gate, and stays HELD.

        "an `IN_BRANCH` program must already hold a room reservation in either
        `HELD` or `CONFIRMED` status, or the publication is rejected with
        `ERR_NO_CONFIRMED_ROOM`". "Every accepted publication increments the
        program's `version` by 1, and the operation answers 200 OK with the
        updated program."

        Design: Corner/state_machines/program_schedule_transition_draft_to_scheduled_with_a_held_reservation
        """
        branch = world.branch()
        room = world.room(branch["id"])
        program = world.program(
            branch["id"], attendance_target=40, attendance_cap=50
        )
        created_version = program["version"]
        reservation = world.hold(program["id"], room["id"])

        published = get_success_data(
            world.api.schedule_program(program["id"], world.coordinator, {}), 200
        )

        assert_program_status(
            published,
            operational_status="SCHEDULED",
            compliance_status="UNVERIFIED",
        )
        assert published["version"] > created_version
        assert world.read_reservation(reservation["id"])["status"] == "HELD"

    def test_close_out_from_scheduled_reports_the_state_gate_and_not_the_clock(
        self, world: LibraryWorld
    ) -> None:
        """Both gates are unmet, and the state gate is the one that answers.

        "It requires `operational_status` of `CONFIRMED` — a program that was
        never confirmed has nothing to settle and reports
        `ERR_PROGRAM_STATE_INVALID`".

        Design: Corner/state_machines/program_close_out_from_scheduled_rejected
        """
        branch = world.branch()
        room = world.room(branch["id"])
        program = world.program(
            branch["id"], attendance_target=40, attendance_cap=50
        )
        world.hold(program["id"], room["id"])
        world.schedule(program["id"])
        world.set_clock("2026-08-12T16:00:00.000Z")

        response = world.api.close_out_program(
            program["id"],
            {
                "verified_registrant_attendance": 0,
                "drop_in_headcount": 0,
                "surveys_collected": 0,
            },
            world.manager,
        )
        body = validate_error(
            response,
            ERR_PROGRAM_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_PROGRAM_STATE_INVALID],
        )
        assert body["error_id"] != "ERR_PROGRAM_NOT_YET_ENDED"

        stale = world.read_program(program["id"])
        assert_program_status(stale, operational_status="SCHEDULED")
        assert stale["gross_attendance"] == 0
        assert_one_decimal_pct(
            stale["survey_response_rate_pct"], 0.0, "survey_response_rate_pct"
        )

    def test_a_replayed_cancel_is_refused_and_the_first_reason_stands(
        self, world: LibraryWorld
    ) -> None:
        """Cancellation is not idempotent by replay; the stored reason is not rewritten.

        "Attempting to publish a program whose `operational_status` is anything
        other than `DRAFT` or `SCHEDULED` is rejected with
        `ERR_PROGRAM_STATE_INVALID`." "`operational_status` becomes `CANCELLED`,
        `closure_reason` is stored, the `version` increments by 1, and the answer
        is 200 OK."

        Design: Corner/state_machines/cancel_on_an_already_cancelled_program_rejected_rather_than_repeated
        """
        branch = world.branch()
        program = world.program(
            branch["id"], attendance_target=40, attendance_cap=50
        )
        world.cancel(program["id"], "Presenter unavailable")

        response = world.api.cancel_program(
            program["id"], {"closure_reason": "Duplicate request"}, world.manager
        )
        validate_error(
            response,
            ERR_PROGRAM_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_PROGRAM_STATE_INVALID],
        )

        after = world.read_program(program["id"])
        assert_program_status(after, operational_status="CANCELLED")
        assert after["closure_reason"] == "Presenter unavailable"

    def test_a_closed_out_program_refuses_a_weather_close_and_keeps_its_settlement(
        self, world: LibraryWorld
    ) -> None:
        """The terminal state answers before the timing rule is ever consulted.

        "It requires `operational_status` of either `SCHEDULED` or `CONFIRMED`".
        "Each entry in `supply_draw_lines` moves its `units` from its lot's
        `quantity_reserved` to that lot's `quantity_issued` — the stock was
        consumed, so `quantity_available` does not change and the lot's `status`
        does not change either".

        Design: Corner/state_machines/closed_out_program_rejects_a_later_weather_close
        """
        branch = world.branch()
        room = world.room(branch["id"])
        lot = world.supply_lot(branch["id"])
        program = world.program(branch["id"])
        reservation = world.hold(program["id"], room["id"])
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])
        world.confirm_program(program["id"])
        world.set_clock("2026-08-12T16:00:00.000Z")
        world.close_out(program["id"], 0, 0, 0)

        response = world.api.weather_close_program(
            program["id"], {"closure_reason": "Thunderstorm"}, world.manager
        )
        body = validate_error(
            response,
            ERR_PROGRAM_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_PROGRAM_STATE_INVALID],
        )
        assert body["error_id"] != "ERR_WEATHER_WINDOW_PASSED"

        settled = world.read_program(program["id"])
        assert_program_status(settled, operational_status="CLOSED_OUT")
        assert settled["closure_reason"] is None
        assert settled["materials_spent_cents"] == 2750
        assert settled["materials_committed_cents"] == 0
        assert_materials_conservation(settled)
        assert_one_decimal_pct(
            settled["attendance_attainment_funder_pct"],
            0.0,
            "attendance_attainment_funder_pct",
        )
        assert_lot_state(
            world.read_lot(lot["id"]), available=90, reserved=0, issued=10
        )

    def test_every_freshly_created_entity_sits_in_its_declared_initial_state(
        self, world: LibraryWorld
    ) -> None:
        """Five machines, five starting states, none of them one step further on.

        "A freshly drafted program reports `operational_status` of `DRAFT` and
        `compliance_status` of `UNVERIFIED`". "An accepted hold answers 201
        Created with the new reservation in `HELD` status". "A new challenge
        reports `status` of `PLANNING`". "A new presenter reports
        `engagement_status` of `PROSPECT`, `screening_decision`,
        `screening_status` and `screening_tier` all `NONE`".

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
        """
        branch = world.branch()
        room = world.room(branch["id"])

        program = world.program(
            branch["id"], attendance_target=40, attendance_cap=50
        )
        assert_program_status(
            program, operational_status="DRAFT", compliance_status="UNVERIFIED"
        )

        reservation = world.hold(program["id"], room["id"])
        assert reservation["status"] == "HELD"

        challenge = world.challenge()
        assert challenge["status"] == "PLANNING"
        assert challenge["prize_inventory_posture"] == "AMPLE"

        lot = world.supply_lot(branch["id"])
        assert lot["status"] == "ACTIVE"

        presenter = world.presenter()
        assert presenter["screening_status"] == "NONE"
        assert presenter["engagement_status"] == "PROSPECT"


def _program_whose_first_hold_was_superseded(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """One draft program, two rooms, and a second hold taken on the second room."""
    branch = world.branch()
    room_a = world.room(branch["id"], room_name="Story Room", capacity_seats=60)
    room_b = world.room(branch["id"], room_name="Meeting Room", capacity_seats=40)
    program = world.program(branch["id"], attendance_target=40, attendance_cap=50)
    first = world.hold(program["id"], room_a["id"])
    second_response = world.api.create_reservation(
        program["id"],
        reservation_payload(room_b["id"], world.program_version(program["id"])),
        world.coordinator,
    )
    return {
        "branch": branch,
        "room_a": room_a,
        "room_b": room_b,
        "program": program,
        "first": first,
        "second_response": second_response,
    }


class TestReservationTransitions:
    """Superseding, the refusal to confirm a superseded hold, and the draw cascade."""

    def test_a_second_hold_supersedes_the_first_rather_than_releasing_it(
        self, world: LibraryWorld
    ) -> None:
        """One live reservation per program, and the displaced one is SUPERSEDED.

        "Only one live reservation per program is meaningful, so a hold that lands
        while the program already carries a `HELD` reservation moves that earlier
        one to `SUPERSEDED` and installs the newcomer as the program's `HELD`
        reservation."

        Design: Corner/state_machines/second_reservation_create_supersedes_the_first_held_reservation
        """
        scenario = _program_whose_first_hold_was_superseded(world)

        second = get_success_data(scenario["second_response"], 201)
        assert second["status"] == "HELD"
        assert second["room_id"] == scenario["room_b"]["id"]

        assert world.read_reservation(scenario["first"]["id"])["status"] == "SUPERSEDED"

        rows, meta = validate_paginated(
            world.api.list_reservations(
                world.coordinator,
                program_id=scenario["program"]["id"],
                status="HELD",
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [second["id"]]

    def test_the_superseded_predecessor_can_no_longer_be_confirmed(
        self, world: LibraryWorld
    ) -> None:
        """Only a HELD reservation may be confirmed, and this one no longer is.

        "it requires the reservation to be `HELD` (a reservation in any other
        status yields `ERR_RESERVATION_STATE_INVALID`)".

        Design: Corner/state_machines/confirming_a_superseded_reservation_rejected
        """
        scenario = _program_whose_first_hold_was_superseded(world)
        get_success_data(scenario["second_response"], 201)

        response = world.api.confirm_reservation(
            scenario["first"]["id"], world.coordinator
        )
        validate_error(
            response,
            ERR_RESERVATION_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_RESERVATION_STATE_INVALID],
        )

        assert world.read_reservation(scenario["first"]["id"])["status"] == "SUPERSEDED"
        assert world.read_program(scenario["program"]["id"])[
            "confirmed_room_capacity"
        ] == 0

    def test_a_draw_that_takes_the_last_unit_flips_the_lot_to_depleted(
        self, world: LibraryWorld
    ) -> None:
        """Forty units required against a forty-unit lot, reserved and not issued.

        "An accepted confirmation stores `supply_draw_lines`, moves each drawn
        lot's units from `quantity_available` to `quantity_reserved` (re-deriving
        `quantity_available` and setting the lot's `status` to `DEPLETED` when it
        reaches 0)".

        Design: Corner/state_machines/supply_draw_that_zeroes_a_lot_flips_it_to_depleted
        """
        branch = world.branch()
        room = world.room(branch["id"])
        lot = world.supply_lot(branch["id"], quantity_procured=40)
        program = world.program(
            branch["id"], attendance_target=40, attendance_cap=50
        )
        reservation = world.hold(program["id"], room["id"])
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])

        confirmed = get_success_data(
            world.api.confirm_program(program["id"], world.manager), 200
        )

        assert_program_status(confirmed, operational_status="CONFIRMED")
        assert confirmed["materials_committed_cents"] == 11000
        assert confirmed["materials_available_cents"] == 39000
        assert confirmed["confirmed_room_capacity"] == 60
        assert_materials_conservation(confirmed)

        assert_lot_state(
            world.read_lot(lot["id"]),
            available=0,
            reserved=40,
            issued=0,
            status="DEPLETED",
        )


def _two_readers_and_one_medal(world: LibraryWorld) -> Dict[str, Any]:
    """A single-unit prize lot exhausted by the first reader, deferring the second.

    Both readers are enrolled at the lot's own branch, so neither award can
    attract a cross-branch surcharge and the only variable left is the unit cost
    of whichever lot ends up serving them.
    """
    branch = world.branch()
    first_lot = world.prize_lot(
        branch["id"], sku="MEDAL", unit_cost_cents=500, quantity_procured=1
    )
    opened = world.opened_challenge(
        tiers=[
            {
                "tier_index": 1,
                "threshold_units": 5,
                "prize_sku": "MEDAL",
                "prize_units_per_participant": 1,
            }
        ],
        logging_method="BOOKS",
        unit_label="books",
    )
    challenge_id = opened["challenge"]["id"]
    first_reader = world.participant(
        challenge_id, branch["id"], display_name="Ada L.", age_band="AGE_5_11"
    )
    second_reader = world.participant(
        challenge_id, branch["id"], display_name="Ben O.", age_band="AGE_5_11"
    )
    world.log_entry(first_reader["id"], 5, "2026-08-01")
    world.log_entry(second_reader["id"], 5, "2026-08-01")
    deferred = world.awards_for_participant(second_reader["id"])
    return {
        "branch": branch,
        "first_lot_id": first_lot["id"],
        "challenge_id": challenge_id,
        "tier_id": opened["tiers"][0]["id"],
        "second_reader_id": second_reader["id"],
        "deferred_award_id": deferred[0]["id"],
    }


class TestChallengeAndAwardTransitions:
    """The open gate, the terminal reconcile and the promotion of a deferral."""

    def test_opening_a_challenge_with_an_empty_ladder_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The refusal leaves the ladder unlocked, so a tier can still be appended.

        "it requires the ladder to exist: a challenge with no tiers at all is
        refused with `ERR_CHALLENGE_HAS_NO_TIERS`". "The **incentive ladder** is a
        sequence of tiers appended one at a time, and it may only be extended
        while the challenge is in `PLANNING`".

        Design: Corner/state_machines/challenge_open_requires_at_least_one_incentive_tier
        """
        challenge = world.challenge()

        response = world.api.open_challenge(challenge["id"], world.manager)
        validate_error(
            response,
            ERR_CHALLENGE_HAS_NO_TIERS,
            ERROR_HTTP_STATUS[ERR_CHALLENGE_HAS_NO_TIERS],
        )

        assert world.read_challenge(challenge["id"])["status"] == "PLANNING"

        appended = get_success_data(
            world.api.create_incentive_tier(
                challenge["id"],
                tier_payload(tier_index=1, threshold_units=5000),
                world.manager,
            ),
            201,
        )
        assert appended["tier_index"] == 1

    def test_a_reconciled_challenge_refuses_a_replayed_reconcile(
        self, world: LibraryWorld
    ) -> None:
        """RECONCILED admits nothing further, so no money can move a second time.

        "`RECONCILED` is terminal: no further tier may be appended, no reader may
        be enrolled, and no entry or correction may be logged against the
        challenge afterwards." "A `ProgramManager` reconciles a challenge whose
        `status` is `OPEN` — anything else is `ERR_CHALLENGE_STATE_INVALID`".

        Design: Corner/state_machines/reconciled_challenge_rejects_a_second_reconcile
        """
        opened = world.opened_challenge(
            tiers=[
                {
                    "tier_index": 1,
                    "threshold_units": 5,
                    "prize_sku": "MEDAL",
                    "prize_units_per_participant": 1,
                }
            ],
            logging_method="BOOKS",
            unit_label="books",
        )
        challenge_id = opened["challenge"]["id"]
        world.set_clock("2026-09-01T00:00:00.000Z")
        world.reconcile(challenge_id)

        response = world.api.reconcile_challenge(challenge_id, world.manager)
        validate_error(
            response,
            ERR_CHALLENGE_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_CHALLENGE_STATE_INVALID],
        )

        challenge = world.read_challenge(challenge_id)
        assert challenge["status"] == "RECONCILED"
        assert challenge["prize_committed_cents"] == 0
        assert challenge["prize_spent_cents"] == 0
        assert challenge["prize_available_cents"] == 10000
        assert_prize_conservation(challenge)

    def test_the_second_reader_waits_with_a_deferral_that_books_no_money(
        self, world: LibraryWorld
    ) -> None:
        """The exhausted ladder still grants the award, only as a deferral.

        "The posture is a warning surface, never a gate: a `CONSTRAINED` challenge
        still accepts logging and still grants awards, it simply grants some of
        them as deferrals."

        Design: Corner/state_machines/procuring_a_new_prize_lot_promotes_a_deferred_award_to_reserved
        """
        scenario = _two_readers_and_one_medal(world)

        award = get_success_data(
            world.api.get_tier_award(scenario["deferred_award_id"], world.manager),
            200,
        )
        assert_deferred_award(award)

        challenge = world.read_challenge(scenario["challenge_id"])
        assert challenge["prize_inventory_posture"] == "CONSTRAINED"
        assert challenge["prize_committed_cents"] == 500
        assert challenge["deferred_award_count"] == 1

    def test_procuring_a_dearer_lot_promotes_the_deferral_at_the_new_price(
        self, world: LibraryWorld
    ) -> None:
        """Promotion is a fresh pricing against the new lot, not a replay of the old.

        "Promotion is a fresh pricing, not a replay of the original: the promoted
        award's `lot_id` becomes the lot it drew from, `unit_cost_cents` captures
        *that* lot's cost, and `line_cost_cents`, `transfer_surcharge_cents` and
        `award_total_cents` are recomputed by exactly the rule above against the
        participant's `home_branch_id`".

        Design: Corner/state_machines/procuring_a_new_prize_lot_promotes_a_deferred_award_to_reserved
        """
        scenario = _two_readers_and_one_medal(world)

        second_lot = get_success_data(
            world.api.create_inventory_lot(
                {
                    "branch_id": scenario["branch"]["id"],
                    "category": "PRIZE",
                    "sku": "MEDAL",
                    "unit_cost_cents": 600,
                    "quantity_procured": 2,
                    "reuse_pool": False,
                },
                world.manager,
            ),
            201,
        )

        promoted = get_success_data(
            world.api.get_tier_award(scenario["deferred_award_id"], world.manager),
            200,
        )
        assert_award_pricing(
            promoted,
            units=1,
            unit_cost_cents=600,
            transfer_surcharge_cents=0,
            status="RESERVED",
            lot_id=second_lot["id"],
        )

        assert_lot_state(
            world.read_lot(second_lot["id"]), available=1, reserved=1, issued=0
        )
        assert_lot_state(
            world.read_lot(scenario["first_lot_id"]),
            available=0,
            reserved=1,
            issued=0,
            status="DEPLETED",
        )

        challenge = world.read_challenge(scenario["challenge_id"])
        assert challenge["prize_committed_cents"] == 1100
        assert challenge["prize_available_cents"] == 8900
        assert challenge["deferred_award_count"] == 0
        assert challenge["prize_inventory_posture"] == "AMPLE"
        assert_prize_conservation(challenge)


def _flagged_presenter_whose_confirmed_program_was_unwound(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """An adult program taken all the way to CONFIRMED, then undone by a flag.

    The program is adult-only, so nothing about the execution ever depended on
    screening; the flag arrives afterwards and unwinds a commitment that was
    entirely legitimate when it was made.
    """
    branch = world.branch()
    room = world.room(branch["id"])
    lot = world.supply_lot(branch["id"])
    program = world.program(
        branch["id"],
        title="Adult Book Club",
        age_group="ADULT",
        start_utc="2026-08-12T18:00:00.000Z",
        end_utc="2026-08-12T19:00:00.000Z",
        attendance_target=10,
        attendance_cap=20,
    )
    reservation = world.hold(
        program["id"],
        room["id"],
        start_utc="2026-08-12T18:00:00.000Z",
        end_utc="2026-08-12T19:00:00.000Z",
    )
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    presenter = world.presenter()
    contract = world.contract(presenter["id"], program["id"], 20)
    world.offer(contract["id"], 50000, world.manager)
    world.execute(contract["id"], world.second_manager)
    world.confirm_program(program["id"])
    world.request_screening(presenter["id"], "NAME_CHECK")
    world.screening_result(presenter["id"], "FLAGGED", "2026-08-01")
    return {
        "branch": branch,
        "lot_id": lot["id"],
        "program_id": program["id"],
        "reservation_id": reservation["id"],
        "presenter_id": presenter["id"],
        "contract_id": contract["id"],
    }


class TestPresenterAndContractTransitions:
    """Two parallel screening dimensions, one refused counter and one compensation."""

    def test_a_clearance_advances_screening_while_engagement_stays_prospect(
        self, world: LibraryWorld
    ) -> None:
        """Two dimensions on one record, and only one of them moves.

        "The request sets `screening_decision` to `PENDING`, stores the supplied
        tier, clears `screening_decided_on` and `screening_valid_until` back to
        null, leaves `screening_status` at `PENDING`". "A name check decided on
        2026-06-01 is therefore valid until 2027-06-01".

        Design: Corner/state_machines/presenter_screening_dimension_advances_while_engagement_stays_prospect
        """
        presenter = world.presenter()

        pending = world.request_screening(presenter["id"], "NAME_CHECK")
        assert pending["screening_decision"] == "PENDING"
        assert pending["screening_status"] == "PENDING"
        assert pending["engagement_status"] == "PROSPECT"

        cleared = world.screening_result(presenter["id"], "CLEAR", "2026-07-01")
        assert cleared["screening_decision"] == "CLEAR"
        assert_date_equals(
            cleared["screening_valid_until"], "2027-07-01", "screening_valid_until"
        )
        assert cleared["screening_status"] == "ACTIVE"
        assert cleared["engagement_status"] == "PROSPECT"
        assert cleared["executed_contract_count"] == 0

    def test_a_result_filed_before_any_request_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The result step requires a PENDING decision, and this one has none.

        "Recording a result requires `screening_decision` to be exactly
        `PENDING`". "It is `NONE` when `screening_decision` is `NONE`".

        Design: Corner/state_machines/screening_result_before_any_screening_request_rejected
        """
        presenter = world.presenter()

        response = world.api.record_screening_result(
            presenter["id"],
            screening_result_payload("CLEAR", "2026-07-01"),
            world.officer,
        )
        validate_error(
            response,
            ERR_SCREENING_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_SCREENING_STATE_INVALID],
        )

        after = world.read_presenter(presenter["id"])
        assert after["screening_decision"] == "NONE"
        assert after["screening_valid_until"] is None
        assert after["screening_status"] == "NONE"

    def test_a_counter_on_a_draft_contract_never_opens_the_negotiation(
        self, world: LibraryWorld
    ) -> None:
        """The presenter's reply presupposes a standing offer, and there is none.

        "A presenter's reply is recorded as a counter, which requires the contract
        to be `OFFERED`". "The new contract reports `status` of `DRAFT`,
        `negotiation_round` of 0, `offered_fee_cents`, `countered_fee_cents` and
        `agreed_fee_cents` all null".

        Design: Corner/state_machines/countering_a_draft_contract_rejected
        """
        branch = world.branch()
        program = world.program(
            branch["id"],
            title="Adult Book Club",
            age_group="ADULT",
            start_utc="2026-08-12T18:00:00.000Z",
            end_utc="2026-08-12T19:00:00.000Z",
            attendance_target=20,
            attendance_cap=25,
        )
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program["id"], 20)

        response = world.api.counter_contract(
            contract["id"], counter_payload(60000), world.coordinator
        )
        validate_error(
            response,
            ERR_CONTRACT_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_CONTRACT_STATE_INVALID],
        )

        after = world.read_contract(contract["id"])
        assert after["status"] == "DRAFT"
        assert after["negotiation_round"] == 0
        assert after["countered_fee_cents"] is None
        assert after["total_fee_cents"] == 0

    def test_the_flag_left_the_contract_blocked_and_the_program_unwound(
        self, world: LibraryWorld
    ) -> None:
        """The position the adjudication has to compensate, stated in full.

        "The second link, caused by the first, moves every contract of this
        presenter whose `status` is `OFFERED`, `COUNTERED` or `EXECUTED` to
        `BLOCKED`; where such a contract was `EXECUTED`, its `total_fee_cents` is
        subtracted from the owning program's `presenter_fee_committed_cents`".

        Design: Corner/state_machines/cleared_with_conditions_adjudication_restores_a_blocked_contract_to_offered
        """
        scenario = _flagged_presenter_whose_confirmed_program_was_unwound(world)

        assert world.read_contract(scenario["contract_id"])["status"] == "BLOCKED"

        program = world.read_program(scenario["program_id"])
        assert_program_status(
            program, operational_status="SCHEDULED", compliance_status="BLOCKED"
        )
        assert program["presenter_fee_committed_cents"] == 0

        assert_lot_state(
            world.read_lot(scenario["lot_id"]), available=100, reserved=0, issued=0
        )
        assert world.read_reservation(scenario["reservation_id"])["status"] == "HELD"

    def test_a_conditional_clearance_restores_the_offer_but_re_commits_nothing(
        self, world: LibraryWorld
    ) -> None:
        """The contract comes back to OFFERED carrying no money at all.

        "Every contract of this presenter still in `BLOCKED` status is restored to
        `OFFERED`, with `negotiation_round` and `offered_by_user_id` both
        preserved exactly as they were and `total_fee_cents` left at 0". "Each
        such contract's program moves its `compliance_status` to
        `PENDING_SCREENING` — never straight back to `CLEARED`".

        Design: Corner/state_machines/cleared_with_conditions_adjudication_restores_a_blocked_contract_to_offered
        """
        scenario = _flagged_presenter_whose_confirmed_program_was_unwound(world)

        adjudicated = world.adjudicate(
            scenario["presenter_id"], "CLEARED_WITH_CONDITIONS", "2026-08-03"
        )
        assert adjudicated["screening_decision"] == "CLEARED_WITH_CONDITIONS"
        assert_date_equals(
            adjudicated["screening_valid_until"],
            "2027-08-03",
            "screening_valid_until",
        )
        assert adjudicated["screening_status"] == "ACTIVE"
        assert adjudicated["engagement_status"] == "ACTIVE"
        assert adjudicated["executed_contract_count"] == 1

        contract = world.read_contract(scenario["contract_id"])
        assert contract["status"] == "OFFERED"
        assert contract["negotiation_round"] == 1
        assert contract["offered_by_user_id"] == "mgr-001"
        assert contract["total_fee_cents"] == 0

        program = world.read_program(scenario["program_id"])
        assert_program_status(
            program,
            operational_status="SCHEDULED",
            compliance_status="PENDING_SCREENING",
        )
        assert program["confirmed_room_capacity"] == 0
        assert program["presenter_fee_committed_cents"] == 0
        assert program["materials_committed_cents"] == 0

        assert_lot_state(
            world.read_lot(scenario["lot_id"]),
            available=100,
            reserved=0,
            issued=0,
            status="ACTIVE",
        )
