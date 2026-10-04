"""Two resource models with different overlap semantics.

Room-night inventory is a per-night half-open interval resource: adjacent
stays that share only a checkout/check-in day never collide (PRD 3.3).
Employee-housing beds are an aggregate count per season: two hires with
disjoint date ranges still each consume a bed for the whole season (PRD 3.7).
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
    contract_version,
    hire_employee,
    housing_scenario,
    set_clock,
)
from test_helpers.test_users import FRONT_DESK, HR_MANAGER


class TestPerNightHalfOpenIntervals:
    """One-room class; adjacent stays fit, a shared night does not."""

    def _setup(self, client):
        """One room; three window-period requests: A 7/10-7/12, B 7/12-7/14
        (adjacent to A), C 7/11-7/12 (shares night 7/11 with A)."""
        scenario = bookable_inventory(
            client,
            room_class_overrides={"code": "LODGE_1", "total_rooms": 1,
                                  "peak_season_months": [7]},
        )
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        room_class_id = scenario["room_class"]["id"]
        reservations = {}
        for guest, check_in, check_out in (
            ("g-a", "2027-07-10T00:00:00Z", "2027-07-12T00:00:00Z"),
            ("g-b", "2027-07-12T00:00:00Z", "2027-07-14T00:00:00Z"),
            ("g-c", "2027-07-11T00:00:00Z", "2027-07-12T00:00:00Z"),
        ):
            reservations[guest] = book_reservation(
                client, contract_id, season_id, room_class_id,
                contract_version(client, contract_id, headers=FRONT_DESK),
                guest_ref=guest,
                check_in_date=check_in,
                check_out_date=check_out,
            )
        set_clock(client, "2027-01-01T00:00:00Z")  # close the lottery window
        return contract_id, reservations

    def test_adjacent_stays_sharing_only_a_turnover_day_both_confirm(
        self, client
    ):
        """PRD 3.3: "Nights are treated as half-open intervals from check-in
        to check-out, so adjacent stays — one guest checking out on the day
        another checks in — do not conflict."

        Design: Difficulty/resource_temporal_overlap/reservation_per_night_half_open_interval_capacity
        """
        contract_id, reservations = self._setup(client)
        for guest in ("g-a", "g-b"):
            reread = get_success_data(client.get_reservation(
                contract_id, reservations[guest]["id"], headers=FRONT_DESK
            ))
            assert reread["status"] == C.RESERVATION_CONFIRMED, (
                "{0} should fit: the stays share no night".format(guest)
            )

    def test_a_stay_sharing_a_night_stays_on_the_waitlist(self, client):
        """PRD 3.3: "For each candidate, the system checks every night of the
        stay: the number of rooms already allocated in that room class for
        that night must be below the class's `total_rooms`." and "a candidate
        that does not fit remains `REQUESTED` as a waitlist entry."

        Design: Difficulty/resource_temporal_overlap/reservation_per_night_half_open_interval_capacity
        """
        contract_id, reservations = self._setup(client)
        reread = get_success_data(client.get_reservation(
            contract_id, reservations["g-c"]["id"], headers=FRONT_DESK
        ))
        assert reread["status"] == C.RESERVATION_REQUESTED, (
            "g-c collides with g-a on night 2027-07-11"
        )


class TestHousingPoolAggregateCount:
    """Beds are a season-level count pool, not a per-night interval."""

    def _setup(self, client):
        """One unit with one bed; HA occupies June."""
        scenario = housing_scenario(client, bed_count=1)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        hire_a = hire_employee(
            client, contract_id, season_id, lodging_id, unit_id,
            employee_ref="emp-june",
            arrival_date="2027-06-01T00:00:00Z",
            departure_date="2027-06-30T00:00:00Z",
        )
        return scenario, hire_a

    def test_a_disjoint_date_hire_is_rejected_while_the_bed_is_held(self, client):
        """PRD 3.7: "the unit must have a free bed for the season: the number
        of beds already assigned to hires in `HIRED` or `ARRIVED` status for
        the same season must leave at least one free."

        Design: Difficulty/resource_temporal_overlap/housing_unit_bed_pool_aggregate_capacity_not_interval
        """
        scenario, _hire_a = self._setup(client)
        response = client.create_hire(
            scenario["contract"]["id"],
            f.hire_payload(
                scenario["season"]["id"],
                scenario["lines"][C.LINE_LODGING]["id"],
                scenario["unit"]["id"],
                employee_ref="emp-aug",
                arrival_date="2027-08-01T00:00:00Z",
                departure_date="2027-08-31T00:00:00Z",
            ),
            headers=HR_MANAGER,
        )
        validate_error(response, ERR_HOUSING_FULL)

    def test_the_same_hire_is_admitted_once_the_bed_is_released(self, client):
        """PRD 3.7: "Termination by the HR manager — which requires a
        `reason` — moves a `HIRED` or `ARRIVED` hire to `TERMINATED`,
        releases the bed, and voids the linked booked voucher if one exists."

        Design: Difficulty/resource_temporal_overlap/housing_unit_bed_pool_aggregate_capacity_not_interval
        """
        scenario, hire_a = self._setup(client)
        client.terminate_hire(
            scenario["contract"]["id"], hire_a["id"],
            {"reason": "season over early"}, headers=HR_MANAGER,
        )
        hire_b = hire_employee(
            client,
            scenario["contract"]["id"],
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            employee_ref="emp-aug",
            arrival_date="2027-08-01T00:00:00Z",
            departure_date="2027-08-31T00:00:00Z",
        )
        assert hire_b["status"] == C.HIRE_HIRED
