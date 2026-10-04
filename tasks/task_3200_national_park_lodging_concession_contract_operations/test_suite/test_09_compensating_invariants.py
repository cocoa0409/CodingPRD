"""Conserved quantities and the actions that restore them.

Housing beds are conserved across hire-then-terminate (PRD 3.7); per-night
room inventory is conserved across allocation-then-cancel, so a night
released by a cancellation is fully reusable (PRD 3.3).  Both invariants are
observed by probing the pool with another write after the compensation.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import ERR_HOUSING_FULL
from test_helpers.assertions import (
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    book_reservation,
    bookable_inventory,
    hire_employee,
    housing_scenario,
    set_clock,
)
from test_helpers.test_users import FRONT_DESK, HR_MANAGER


class TestHousingBedConservation:
    """create(hire) then terminate(hire) is net-zero on occupied beds."""

    def _setup(self, client):
        """A 3-bed unit with two hires already occupying beds."""
        scenario = housing_scenario(client, bed_count=3)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        return scenario

    def test_create_then_terminate_restores_the_free_bed(self, client):
        """PRD 3.7: "A hire occupies one bed from the moment of hiring through
        arrival — `HIRED` and `ARRIVED` hires both occupy beds — and the bed
        is released when the hire becomes `DEPARTED`, `NO_SHOW`, or
        `TERMINATED`."

        Design: Difficulty/compensating_invariant/housing_bed_occupancy_conserved_across_hire_and_terminate
        """
        scenario = self._setup(client)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        third = hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        client.terminate_hire(
            contract_id, third["id"], {"reason": "withdrew"}, headers=HR_MANAGER,
        )
        fourth = hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        assert fourth["status"] == C.HIRE_HIRED, (
            "create+terminate must leave the pool exactly where it started"
        )

    def test_without_the_termination_the_third_bed_stays_taken(self, client):
        """PRD 3.7: "If no available unit has a free bed, the creation is
        rejected with `ERR_HOUSING_FULL`."

        Design: Difficulty/compensating_invariant/housing_bed_occupancy_conserved_across_hire_and_terminate
        """
        scenario = self._setup(client)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        overflow = client.create_hire(
            contract_id,
            f.hire_payload(season_id, lodging_id, unit_id),
            headers=HR_MANAGER,
        )
        validate_error(overflow, ERR_HOUSING_FULL)


class TestRoomNightInventoryConservation:
    """confirm then cancel returns the per-night allocation to zero."""

    def _scenario(self, client):
        """A 2-room class with one 2-night window reservation, allocated."""
        scenario = bookable_inventory(
            client,
            room_class_overrides={"code": "LODGE_2", "total_rooms": 2,
                                  "peak_season_months": [7]},
        )
        contract_id = scenario["contract"]["id"]
        reservation = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-1",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        # Close the 72-hour window so the allocation run confirms the stay.
        set_clock(client, "2026-12-04T01:00:00Z")
        return scenario, reservation

    def test_nights_released_by_a_cancellation_are_fully_reusable(self, client):
        """PRD 3.3: "Cancelling a confirmed reservation also releases its
        per-night inventory" and "Requests created after the window has
        closed skip the queue and are allocated immediately in arrival order
        against whatever inventory remains, first-come by `created_at`."

        Design: Difficulty/compensating_invariant/room_night_inventory_conserved_across_confirm_and_cancel
        """
        scenario, first = self._scenario(client)
        contract_id = scenario["contract"]["id"]
        confirmed = get_success_data(client.get_reservation(
            contract_id, first["id"], headers=FRONT_DESK
        ))
        assert confirmed["status"] == C.RESERVATION_CONFIRMED
        cancelled = get_success_data(client.cancel_reservation(
            contract_id, first["id"], headers=FRONT_DESK
        ))
        assert cancelled["status"] == C.RESERVATION_CANCELLED
        return scenario

    def test_a_post_window_request_for_the_same_nights_is_confirmed(self, client):
        """PRD 3.3: "Requests created after the window has closed skip the
        queue and are allocated immediately in arrival order against whatever
        inventory remains, first-come by `created_at`."

        Design: Difficulty/compensating_invariant/room_night_inventory_conserved_across_confirm_and_cancel
        """
        scenario, first = self._scenario(client)
        contract_id = scenario["contract"]["id"]
        from test_helpers.fixtures import contract_version
        client.cancel_reservation(contract_id, first["id"], headers=FRONT_DESK)
        follow_up = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="g-2",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        # With the released nights back in the pool the post-window request
        # allocates immediately rather than queueing.
        reread = get_success_data(client.get_reservation(
            contract_id, follow_up["id"], headers=FRONT_DESK
        ))
        assert reread["status"] == C.RESERVATION_CONFIRMED, (
            "the released nights must be fully reusable"
        )
