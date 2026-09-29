"""Writes refused for the state of a neighbour rather than for their own payload.

A contract draft is impeccable in itself and is still refused because a screening
result on a different endpoint suspended the presenter.  A reading log entry
names a perfectly valid participant and is still refused because the challenge
that owns that participant was never opened.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import (
    ERR_CHALLENGE_STATE_INVALID,
    ERR_PRESENTER_SUSPENDED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import assert_lot_state, assert_program_status
from test_helpers.factories import contract_payload, log_entry_payload
from test_helpers.fixtures import LibraryWorld


# ==========================================================================
# A contract blocked by the presenter it names
# ==========================================================================
def _suspended_presenter_and_adult_program(world: LibraryWorld) -> Dict[str, Any]:
    """An adult program needing no screening, and a presenter flagged out of play.

    Nothing about the intended draft is wrong: both references resolve, the
    program is in draft and the mileage is non-negative.
    """
    branch = world.branch()
    program = world.program(
        branch["id"],
        title="Local History Lecture",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-12T18:00:00.000Z",
        end_utc="2026-08-12T19:00:00.000Z",
        attendance_target=30,
        attendance_cap=30,
        supply_sku="KIT-HIST",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=80000,
    )
    presenter = world.presenter(
        legal_name="Ivo Marek",
        presenter_type="INDIVIDUAL",
        insurance_certificate_expires_on="2027-06-30",
        quoted_fee_cents=70000,
    )
    world.flag_screening(presenter["id"], "NAME_CHECK", "2026-08-01")
    return {"branch": branch, "program": program, "presenter": presenter}


class TestContractDependsOnPresenterEngagementState:
    """The draft has no state of its own; the presenter's decides it."""

    def test_a_draft_against_a_suspended_presenter_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The refusal is about the presenter, not about the request.

        "A suspended presenter cannot be contracted at all, so a draft against a
        presenter whose `engagement_status` is `SUSPENDED` is rejected with
        `ERR_PRESENTER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/contract_creation_depends_on_presenter_engagement_state_not_its_own
        """
        scenario = _suspended_presenter_and_adult_program(world)

        response = world.api.create_contract(
            contract_payload(
                scenario["presenter"]["id"], scenario["program"]["id"], 12
            ),
            world.coordinator,
        )
        validate_error(
            response,
            ERR_PRESENTER_SUSPENDED,
            ERROR_HTTP_STATUS[ERR_PRESENTER_SUSPENDED],
        )

    def test_no_contract_row_is_created_at_all(self, world: LibraryWorld) -> None:
        """The presenter's contract collection stays empty.

        "The new contract reports `status` of `DRAFT`, `negotiation_round` of 0,
        `offered_fee_cents`, `countered_fee_cents` and `agreed_fee_cents` all
        null".

        Design: Difficulty/cross_entity_state_dependency/contract_creation_depends_on_presenter_engagement_state_not_its_own
        """
        scenario = _suspended_presenter_and_adult_program(world)
        world.api.create_contract(
            contract_payload(
                scenario["presenter"]["id"], scenario["program"]["id"], 12
            ),
            world.coordinator,
        )

        rows, meta = validate_paginated(
            world.api.list_contracts(
                world.manager, presenter_id=scenario["presenter"]["id"]
            )
        )
        assert meta["total_count"] == 0, "no contract row may have been created"
        assert rows == []

    def test_neither_the_presenter_nor_the_program_moved(
        self, world: LibraryWorld
    ) -> None:
        """The rejected create never touched the compliance dimension.

        "A freshly drafted program reports `operational_status` of `DRAFT` and
        `compliance_status` of `UNVERIFIED`".

        Design: Difficulty/cross_entity_state_dependency/contract_creation_depends_on_presenter_engagement_state_not_its_own
        """
        scenario = _suspended_presenter_and_adult_program(world)
        world.api.create_contract(
            contract_payload(
                scenario["presenter"]["id"], scenario["program"]["id"], 12
            ),
            world.coordinator,
        )

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["engagement_status"] == "SUSPENDED"
        assert presenter["screening_decision"] == "FLAGGED"
        assert presenter["screening_status"] == "PENDING_ADJUDICATION"
        assert presenter["executed_contract_count"] == 0

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(
            program, operational_status="DRAFT", compliance_status="UNVERIFIED"
        )


# ==========================================================================
# A log entry blocked by the challenge that owns the participant
# ==========================================================================
def _participant_enrolled_before_the_challenge_opened(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """A valid reader on a ladder that was deliberately never opened."""
    branch = world.branch()
    lot = world.prize_lot(
        branch["id"],
        sku="PRIZE-P1",
        unit_cost_cents=100,
        quantity_procured=10,
        reuse_pool=False,
    )
    challenge = world.challenge(
        name="Not Yet Open",
        logging_method="MINUTES",
        unit_label="minute",
        start_on="2026-06-01",
        end_on="2026-08-31",
        correction_policy="LEDGER_TRUTH",
        prize_budget_cents=50000,
    )
    tier = world.tier(
        challenge["id"],
        tier_index=1,
        threshold_units=60,
        prize_sku="PRIZE-P1",
        prize_units_per_participant=1,
    )
    participant = world.participant(
        challenge["id"],
        branch["id"],
        display_name="Eager Reader",
        age_band="AGE_5_11",
    )
    return {
        "branch": branch,
        "lot": lot,
        "challenge": challenge,
        "tier": tier,
        "participant": participant,
    }


class TestLogEntryDependsOnTheOwningChallengeState:
    """Enrolment is legal in planning; logging is not."""

    def test_the_participant_exists_yet_the_entry_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The failure names the challenge's state, not the reader or the payload.

        "Enrolment is permitted while the challenge is in `PLANNING` or `OPEN` —
        readers may be signed up before the window opens". "The challenge must be
        `OPEN` — logging against a `PLANNING` or `RECONCILED` challenge is
        `ERR_CHALLENGE_STATE_INVALID`".

        Design: Difficulty/cross_entity_state_dependency/log_entry_depends_on_owning_challenge_being_open_not_on_the_participant
        """
        scenario = _participant_enrolled_before_the_challenge_opened(world)

        response = world.api.create_log_entry(
            scenario["participant"]["id"],
            log_entry_payload(60, "2026-07-15", "STAFF_DESK"),
            world.coordinator,
        )
        validate_error(
            response,
            ERR_CHALLENGE_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_CHALLENGE_STATE_INVALID],
        )

    def test_the_append_only_ledger_stays_completely_empty(
        self, world: LibraryWorld
    ) -> None:
        """No entry was appended, so every derived counter is still its default.

        "A new participant reports `cumulative_units`, `awarded_tier_index`,
        `eligible_tier_index` and `entry_count` all 0 and `last_entry_on` null".

        Design: Difficulty/cross_entity_state_dependency/log_entry_depends_on_owning_challenge_being_open_not_on_the_participant
        """
        scenario = _participant_enrolled_before_the_challenge_opened(world)
        world.api.create_log_entry(
            scenario["participant"]["id"],
            log_entry_payload(60, "2026-07-15", "STAFF_DESK"),
            world.coordinator,
        )

        _, meta = validate_paginated(
            world.api.list_log_entries(
                world.coordinator, participant_id=scenario["participant"]["id"]
            )
        )
        assert meta["total_count"] == 0

        participant = world.read_participant(scenario["participant"]["id"])
        assert participant["cumulative_units"] == 0
        assert participant["entry_count"] == 0
        assert participant["eligible_tier_index"] == 0
        assert participant["awarded_tier_index"] == 0
        assert participant["last_entry_on"] is None

    def test_no_prize_money_and_no_prize_unit_moved(
        self, world: LibraryWorld
    ) -> None:
        """The unopened challenge, its tier and its stock are all untouched.

        "The accepted transition sets `status` to `OPEN`, locks the ladder,
        increments the challenge's `version` by 1 and answers 200 OK."

        Design: Difficulty/cross_entity_state_dependency/log_entry_depends_on_owning_challenge_being_open_not_on_the_participant
        """
        scenario = _participant_enrolled_before_the_challenge_opened(world)
        world.api.create_log_entry(
            scenario["participant"]["id"],
            log_entry_payload(60, "2026-07-15", "STAFF_DESK"),
            world.coordinator,
        )

        challenge = world.read_challenge(scenario["challenge"]["id"])
        assert challenge["status"] == "PLANNING"
        assert challenge["prize_committed_cents"] == 0

        tier = world.read_tier(scenario["tier"]["id"])
        assert tier["award_count"] == 0
        assert tier["deferred_count"] == 0

        assert_lot_state(
            world.read_lot(scenario["lot"]["id"]),
            available=10,
            reserved=0,
            issued=0,
        )
