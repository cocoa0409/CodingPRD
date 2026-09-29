"""Precondition builders and pytest fixtures.

The harness restarts the API server before every individual test, so each test
begins against an empty database with the logical clock at its startup default.
Every fixture here therefore builds its whole precondition chain from scratch:
branch, room, lot, program, reservation, presenter, screening, contract,
challenge, tier and participant, in that dependency order.

The fixtures are layered:

* Tier 1 - the client and the pinned logical clock.
* Tier 2 - single entities created in isolation.
* Tier 3 - short composites: a held reservation, a scheduled program, an open
  challenge, an enrolled participant, a screened presenter.
* Tier 4 - full lifecycle composites: a confirmed program with a supply draw, an
  executed contract with its priced fee ladder.
* Tier 5 - the ``LibraryWorld`` driver, which exposes the same steps as ordinary
  methods so a test that needs an unusual chain can assemble one inline.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import LibraryApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    SCREENING_OFFICER_HEADERS,
    SECOND_MANAGER_HEADERS,
    SECOND_MANAGER_USER_ID,
    make_reader_headers,
)


class LibraryWorld:
    """A thin driver that turns each API call into one named setup step."""

    def __init__(self, api: LibraryApiClient):
        self.api = api
        self.manager = MANAGER_HEADERS
        self.second_manager = SECOND_MANAGER_HEADERS
        self.coordinator = COORDINATOR_HEADERS
        self.officer = SCREENING_OFFICER_HEADERS

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, self.manager))

    def pin_clock(self) -> Dict[str, Any]:
        """Pin the logical clock to the startup default."""
        return self.set_clock(DEFAULT_CLOCK_UTC)

    # ------------------------------------------------------------------
    # Branches, rooms and lots
    # ------------------------------------------------------------------
    def branch(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_branch(f.branch_payload(**kwargs), self.manager)
        )

    def room(self, branch_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_room(branch_id, f.room_payload(**kwargs), self.manager)
        )

    def supply_lot(self, branch_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_inventory_lot(
                f.inventory_lot_payload(branch_id, **kwargs), self.manager
            )
        )

    def prize_lot(self, branch_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_inventory_lot(
                f.prize_lot_payload(branch_id, **kwargs), self.manager
            )
        )

    def read_branch(self, branch_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_branch(branch_id, self.manager))

    def read_room(self, room_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_room(room_id, self.manager))

    def read_lot(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_inventory_lot(lot_id, self.manager))

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def program(self, branch_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_program(
                f.program_payload(branch_id, **kwargs), self.coordinator
            )
        )

    def adult_program(self, branch_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_program(
                f.adult_program_payload(branch_id, **kwargs), self.coordinator
            )
        )

    def read_program(self, program_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_program(program_id, self.coordinator))

    def program_version(self, program_id: str) -> int:
        return self.read_program(program_id)["version"]

    def schedule(self, program_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.schedule_program(
                program_id, self.coordinator, f.schedule_payload(**kwargs)
            )
        )

    def confirm_program(self, program_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.confirm_program(program_id, self.manager)
        )

    def register(self, program_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.register(
                program_id, f.registration_payload(**kwargs), self.coordinator
            )
        )

    def close_out(
        self,
        program_id: str,
        verified_registrant_attendance: int,
        drop_in_headcount: int,
        surveys_collected: int,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.close_out_program(
                program_id,
                f.close_out_payload(
                    verified_registrant_attendance,
                    drop_in_headcount,
                    surveys_collected,
                ),
                self.manager,
            )
        )

    def weather_close(self, program_id: str, closure_reason: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.weather_close_program(
                program_id, f.closure_payload(closure_reason), self.manager
            )
        )

    def cancel(self, program_id: str, closure_reason: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.cancel_program(
                program_id, f.closure_payload(closure_reason), self.manager
            )
        )

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------
    def hold(self, program_id: str, room_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Hold a room, echoing the program's current version."""
        version = kwargs.pop(
            "expected_program_version", self.program_version(program_id)
        )
        return get_success_data(
            self.api.create_reservation(
                program_id,
                f.reservation_payload(room_id, version, **kwargs),
                self.coordinator,
            )
        )

    def confirm_reservation(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.confirm_reservation(reservation_id, self.coordinator)
        )

    def read_reservation(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_reservation(reservation_id, self.coordinator)
        )

    # ------------------------------------------------------------------
    # Presenters and screening
    # ------------------------------------------------------------------
    def presenter(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_presenter(f.presenter_payload(**kwargs), self.coordinator)
        )

    def read_presenter(self, presenter_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_presenter(presenter_id, self.manager))

    def request_screening(
        self, presenter_id: str, screening_tier: str = "NAME_CHECK"
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.request_screening(
                presenter_id, f.screening_request_payload(screening_tier), self.officer
            )
        )

    def screening_result(
        self, presenter_id: str, result: str, decided_on: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_screening_result(
                presenter_id, f.screening_result_payload(result, decided_on), self.officer
            )
        )

    def adjudicate(
        self, presenter_id: str, decision: str, decided_on: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.adjudicate_screening(
                presenter_id, f.adjudication_payload(decision, decided_on), self.officer
            )
        )

    def clear_screening(
        self,
        presenter_id: str,
        screening_tier: str = "NAME_CHECK",
        decided_on: str = "2026-07-01",
    ) -> Dict[str, Any]:
        """Take a presenter from unscreened to an active clearance in two steps."""
        self.request_screening(presenter_id, screening_tier)
        return self.screening_result(presenter_id, "CLEAR", decided_on)

    def flag_screening(
        self,
        presenter_id: str,
        screening_tier: str = "NAME_CHECK",
        decided_on: str = "2026-08-01",
    ) -> Dict[str, Any]:
        """Take a presenter from unscreened to a flagged suspension."""
        self.request_screening(presenter_id, screening_tier)
        return self.screening_result(presenter_id, "FLAGGED", decided_on)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def contract(
        self, presenter_id: str, program_id: str, round_trip_miles: int = 20
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_contract(
                f.contract_payload(presenter_id, program_id, round_trip_miles),
                self.coordinator,
            )
        )

    def offer(
        self,
        contract_id: str,
        offered_fee_cents: int = 50000,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.offer_contract(
                contract_id,
                f.offer_payload(offered_fee_cents),
                headers or self.manager,
            )
        )

    def counter(self, contract_id: str, countered_fee_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.counter_contract(
                contract_id, f.counter_payload(countered_fee_cents), self.coordinator
            )
        )

    def execute(
        self, contract_id: str, headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute the standing offer under an identity that did not make it."""
        return get_success_data(
            self.api.execute_contract(contract_id, headers or self.second_manager)
        )

    def read_contract(self, contract_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_contract(contract_id, self.manager))

    def executed_contract(
        self,
        presenter_id: str,
        program_id: str,
        round_trip_miles: int = 20,
        offered_fee_cents: int = 50000,
    ) -> Dict[str, Any]:
        """Draft, offer and execute one contract, honouring segregation of duties."""
        contract = self.contract(presenter_id, program_id, round_trip_miles)
        self.offer(contract["id"], offered_fee_cents, self.manager)
        return self.execute(contract["id"], self.second_manager)

    # ------------------------------------------------------------------
    # Challenges, tiers, participants and the ledger
    # ------------------------------------------------------------------
    def challenge(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_challenge(f.challenge_payload(**kwargs), self.manager)
        )

    def read_challenge(self, challenge_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_challenge(challenge_id, self.manager))

    def tier(self, challenge_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_incentive_tier(
                challenge_id, f.tier_payload(**kwargs), self.manager
            )
        )

    def read_tier(self, tier_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_incentive_tier(tier_id, self.manager))

    def open_challenge(self, challenge_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.open_challenge(challenge_id, self.manager))

    def reconcile(self, challenge_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.reconcile_challenge(challenge_id, self.manager)
        )

    def opened_challenge(
        self, tiers: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Create a challenge, append its tier ladder and open it for logging.

        Returns ``{"challenge": ..., "tiers": [...]}`` with the challenge read
        back after the open so its status is the published ``OPEN``.
        """
        challenge = self.challenge(**kwargs)
        tier_specs = tiers if tiers is not None else [{}]
        created = [self.tier(challenge["id"], **spec) for spec in tier_specs]
        opened = self.open_challenge(challenge["id"])
        return {"challenge": opened, "tiers": created}

    def participant(
        self, challenge_id: str, home_branch_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_participant(
                f.participant_payload(challenge_id, home_branch_id, **kwargs),
                self.coordinator,
            )
        )

    def read_participant(self, participant_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_participant(participant_id, self.coordinator)
        )

    def participant_version(self, participant_id: str) -> int:
        return self.read_participant(participant_id)["version"]

    def log_entry(
        self,
        participant_id: str,
        units: int,
        logged_on: str,
        source: str = "STAFF_DESK",
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_log_entry(
                participant_id,
                f.log_entry_payload(units, logged_on, source),
                headers or self.coordinator,
            )
        )

    def reader_log_entry(
        self, participant_id: str, units: int, logged_on: str
    ) -> Dict[str, Any]:
        """Post a self-service entry as the reader who owns the record."""
        return get_success_data(
            self.api.create_log_entry(
                participant_id,
                f.log_entry_payload(units, logged_on, "SELF_SERVICE"),
                make_reader_headers(participant_id),
            )
        )

    def correction(
        self,
        participant_id: str,
        corrected_entry_id: str,
        units_delta: int,
        note: Optional[str] = None,
        expected_participant_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        version = (
            expected_participant_version
            if expected_participant_version is not None
            else self.participant_version(participant_id)
        )
        return get_success_data(
            self.api.create_log_correction(
                participant_id,
                f.log_correction_payload(
                    corrected_entry_id, units_delta, version, note
                ),
                self.coordinator,
            )
        )

    def awards_for_participant(self, participant_id: str) -> List[Dict[str, Any]]:
        rows, _ = validate_paginated(
            self.api.list_tier_awards(
                self.manager, participant_id=participant_id, limit=100
            )
        )
        return rows

    def awards_for_tier(self, tier_id: str) -> List[Dict[str, Any]]:
        rows, _ = validate_paginated(
            self.api.list_tier_awards(self.manager, tier_id=tier_id, limit=100)
        )
        return rows

    def log_entries_for_participant(self, participant_id: str) -> List[Dict[str, Any]]:
        rows, _ = validate_paginated(
            self.api.list_log_entries(
                self.manager, participant_id=participant_id, limit=100
            )
        )
        return rows


# ==========================================================================
# Tier 1 - client and clock
# ==========================================================================
@pytest.fixture
def api() -> LibraryApiClient:
    """The endpoint client, pointed at the server the harness has just started."""
    return LibraryApiClient()


@pytest.fixture
def world(api: LibraryApiClient) -> LibraryWorld:
    """A driver whose logical clock is pinned to the startup default instant.

    "At server startup it reads exactly `2026-08-01T00:00:00.000Z`, and it reports
    that instant until a caller moves it." Pinning it explicitly keeps every
    date-granularity rule reproducible.
    """
    driver = LibraryWorld(api)
    driver.pin_clock()
    return driver


# ==========================================================================
# Tier 2 - single entities
# ==========================================================================
@pytest.fixture
def branch(world: LibraryWorld) -> Dict[str, Any]:
    """One branch with a staffing overlap ceiling of two and a 150000-cent cap."""
    return world.branch()


@pytest.fixture
def east_branch(world: LibraryWorld) -> Dict[str, Any]:
    """A second branch, so cross-branch sourcing has somewhere to reach."""
    return world.branch(name="East Branch", branch_code="EAST")


@pytest.fixture
def room(world: LibraryWorld, branch: Dict[str, Any]) -> Dict[str, Any]:
    """A 60-seat room with fifteen-minute setup and teardown minimums."""
    return world.room(branch["id"])


@pytest.fixture
def supply_lot(world: LibraryWorld, branch: Dict[str, Any]) -> Dict[str, Any]:
    """A 100-unit CRAFT-KIT supply lot at 250 cents, held at the branch itself."""
    return world.supply_lot(branch["id"])


@pytest.fixture
def presenter(world: LibraryWorld) -> Dict[str, Any]:
    """An unscreened presenter whose certificate runs to 2027-01-01."""
    return world.presenter()


@pytest.fixture
def craft_program(world: LibraryWorld, branch: Dict[str, Any]) -> Dict[str, Any]:
    """A drafted school-age in-branch registration program on 2026-08-12."""
    return world.program(branch["id"])


@pytest.fixture
def adult_program(world: LibraryWorld, branch: Dict[str, Any]) -> Dict[str, Any]:
    """A drafted adult program, so ``serves_minors`` derives false."""
    return world.adult_program(branch["id"])


# ==========================================================================
# Tier 3 - short composites
# ==========================================================================
@pytest.fixture
def held_reservation(
    world: LibraryWorld, craft_program: Dict[str, Any], room: Dict[str, Any]
) -> Dict[str, Any]:
    """A program with one held room reservation covering its public window."""
    reservation = world.hold(craft_program["id"], room["id"])
    return {
        "program": world.read_program(craft_program["id"]),
        "room": room,
        "reservation": reservation,
    }


@pytest.fixture
def scheduled_program(
    world: LibraryWorld, held_reservation: Dict[str, Any]
) -> Dict[str, Any]:
    """A published program whose room reservation is confirmed."""
    world.confirm_reservation(held_reservation["reservation"]["id"])
    program = world.schedule(held_reservation["program"]["id"])
    return {
        "program": program,
        "room": held_reservation["room"],
        "reservation": world.read_reservation(held_reservation["reservation"]["id"]),
    }


@pytest.fixture
def open_minutes_challenge(world: LibraryWorld) -> Dict[str, Any]:
    """An open minutes challenge with a single 5000-unit tier."""
    return world.opened_challenge()


@pytest.fixture
def enrolled_participant(
    world: LibraryWorld, branch: Dict[str, Any], open_minutes_challenge: Dict[str, Any]
) -> Dict[str, Any]:
    """A freshly enrolled participant on an open challenge."""
    participant = world.participant(
        open_minutes_challenge["challenge"]["id"], branch["id"]
    )
    return {
        "participant": participant,
        "challenge": open_minutes_challenge["challenge"],
        "tier": open_minutes_challenge["tiers"][0],
    }


@pytest.fixture
def cleared_presenter(world: LibraryWorld) -> Dict[str, Any]:
    """A presenter carrying an active name-check clearance decided 2026-07-01."""
    created = world.presenter()
    world.clear_screening(created["id"])
    return world.read_presenter(created["id"])


# ==========================================================================
# Tier 4 - full lifecycle composites
# ==========================================================================
@pytest.fixture
def confirmed_program_with_draw(
    world: LibraryWorld, branch: Dict[str, Any], room: Dict[str, Any]
) -> Dict[str, Any]:
    """A confirmed ten-attendee program whose supply draw took ten units.

    Ten units at 250 cents is a 2500-cent subtotal, which sits below the
    20000-cent contingency threshold, so the contingency is ten per cent and the
    materials commitment is 2750 cents.
    """
    lot = world.supply_lot(branch["id"])
    program = world.program(branch["id"], attendance_target=10)
    reservation = world.hold(program["id"], room["id"])
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    confirmed = world.confirm_program(program["id"])
    return {
        "program": confirmed,
        "branch": branch,
        "room": room,
        "lot": lot,
        "reservation": world.read_reservation(reservation["id"]),
    }


@pytest.fixture
def confirmed_program_with_executed_contract(
    world: LibraryWorld, confirmed_program_with_draw: Dict[str, Any]
) -> Dict[str, Any]:
    """A confirmed program carrying one executed 50000-cent adult contract.

    The program is adult, so no escort fee applies; the mileage is twenty, so no
    travel is reimbursed; the certificate runs well past the program, so no rider
    applies; and 2026-08-12 is a Wednesday, so no weekend premium applies.
    """
    scenario = dict(confirmed_program_with_draw)
    presenter_row = world.presenter(legal_name="Adult Speaker")
    contract = world.executed_contract(
        presenter_row["id"], scenario["program"]["id"], 20, 50000
    )
    scenario["presenter"] = world.read_presenter(presenter_row["id"])
    scenario["contract"] = contract
    scenario["program"] = world.read_program(scenario["program"]["id"])
    return scenario


# ==========================================================================
# Tier 5 - convenience re-exports
# ==========================================================================
OFFERING_USER_ID = MANAGER_USER_ID
EXECUTING_USER_ID = SECOND_MANAGER_USER_ID
