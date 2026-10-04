"""One trigger, several observable state changes (PRD 3.7 / 3.3).

Terminating a hire voids its booked voucher and frees the bed it occupied,
admitting a hire the pool had rejected; cancelling a confirmed reservation
releases its per-night inventory and promotes the longest-waiting fitting
waitlist entry, which in turn blocks a later one.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_error,
)
from test_helpers.api_errors import ERR_HOUSING_FULL
from test_helpers.fixtures import (
    book_reservation,
    bookable_inventory,
    contract_version,
    hire_employee,
    housing_scenario,
    read_hire,
    set_clock,
    vouchers_for_hire,
)
from test_helpers.test_users import FRONT_DESK, HR_MANAGER


class TestHireTerminationCascade:
    """terminate -> voucher VOID -> bed released -> blocked hire admitted."""

    def _setup(self, client):
        scenario = housing_scenario(client, bed_count=1)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        first = hire_employee(
            client, contract_id, season_id, lodging_id, unit_id,
            needs_transport=True, transport_origin="Bozeman",
        )
        probe = client.create_hire(
            contract_id,
            {
                "season_id": season_id,
                "service_line_id": lodging_id,
                "employee_ref": "emp-002",
                "housing_unit_id": unit_id,
                "arrival_date": "2027-06-01T00:00:00Z",
                "departure_date": "2027-08-31T00:00:00Z",
                "needs_transport": False,
            },
            headers=HR_MANAGER,
        )
        validate_error(probe, ERR_HOUSING_FULL)
        return scenario, first

    def test_termination_voids_the_linked_voucher(self, client):
        """PRD 3.7: "Termination by the HR manager — which requires a
        `reason` — moves a `HIRED` or `ARRIVED` hire to `TERMINATED`,
        releases the bed, and voids the linked booked voucher if one exists."

        Design: Difficulty/transitive_cascade/hire_termination_cascades_voucher_void_and_bed_release_then_rehire
        """
        scenario, first = self._setup(client)
        contract_id = scenario["contract"]["id"]
        terminated = get_success_data(client.terminate_hire(
            contract_id, first["id"], {"reason": "early resignation"},
            headers=HR_MANAGER,
        ))
        assert terminated["status"] == C.HIRE_TERMINATED
        vouchers = vouchers_for_hire(client, contract_id, first["id"])
        assert len(vouchers) == 1, "exactly one voucher must exist for the hire"
        assert vouchers[0]["status"] == C.VOUCHER_VOID

    def test_the_freed_bed_admits_the_previously_blocked_hire(self, client):
        """PRD 3.7: "If no available unit has a free bed, the creation is
        rejected with `ERR_HOUSING_FULL`." and "the bed is released when the
        hire becomes `DEPARTED`, `NO_SHOW`, or `TERMINATED`."

        Design: Difficulty/transitive_cascade/hire_termination_cascades_voucher_void_and_bed_release_then_rehire
        """
        scenario, first = self._setup(client)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        client.terminate_hire(
            contract_id, first["id"], {"reason": "early resignation"},
            headers=HR_MANAGER,
        )
        third = hire_employee(
            client, contract_id, season_id, lodging_id, unit_id,
            arrival_date="2027-06-15T00:00:00Z",
        )
        assert third["status"] == C.HIRE_HIRED


class TestCancellationPromotionChain:
    """cancel -> nights released -> oldest fitting waitlist entry promoted."""

    def _setup(self, client):
        """One-room room class; three overlapping window-period requests."""
        scenario = bookable_inventory(
            client,
            room_class_overrides={"code": "LODGE_STD", "total_rooms": 1,
                                  "peak_season_months": [7]},
        )
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        room_class_id = scenario["room_class"]["id"]
        version = scenario["version"]
        r1 = book_reservation(
            client, contract_id, season_id, room_class_id, version,
            guest_ref="g-1",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        r2 = book_reservation(
            client, contract_id, season_id, room_class_id,
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="g-2",
            check_in_date="2027-07-11T00:00:00Z",
            check_out_date="2027-07-13T00:00:00Z",
        )
        r3 = book_reservation(
            client, contract_id, season_id, room_class_id,
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="g-3",
            check_in_date="2027-07-11T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        # Close the 72-hour lottery window: 2026-12-01 + 72h -> advance.
        set_clock(client, "2027-01-01T00:00:00Z")
        return contract_id, r1, r2, r3

    def test_cancellation_promotes_the_longest_waiting_fitting_entry(self, client):
        """PRD 3.3: "Cancelling a confirmed reservation also releases its
        per-night inventory, and the release triggers waitlist promotion: the
        longest-waiting `REQUESTED` reservation — again ordered by
        `created_at` ascending with `guest_ref` ascending as tie-break — that
        now fits on every night of its stay is promoted to `CONFIRMED`."

        Design: Difficulty/transitive_cascade/reservation_cancellation_promotes_waitlist_then_stale_statement_marks
        """
        contract_id, r1, r2, r3 = self._setup(client)
        after_run = get_success_data(client.get_reservation(
            contract_id, r1["id"], headers=FRONT_DESK
        ))
        assert after_run["status"] == C.RESERVATION_CONFIRMED
        client.cancel_reservation(contract_id, r1["id"], headers=FRONT_DESK)
        promoted = get_success_data(client.get_reservation(
            contract_id, r2["id"], headers=FRONT_DESK
        ))
        assert promoted["status"] == C.RESERVATION_CONFIRMED, (
            "r2 was created before r3 and fits once r1 leaves"
        )

    def test_the_promotion_consumes_the_night_the_later_entry_needs(self, client):
        """PRD 3.3: "a candidate that does not fit remains `REQUESTED` as a
        waitlist entry."

        Design: Difficulty/transitive_cascade/reservation_cancellation_promotes_waitlist_then_stale_statement_marks
        """
        contract_id, r1, _r2, r3 = self._setup(client)
        cancelled = get_success_data(client.cancel_reservation(
            contract_id, r1["id"], headers=FRONT_DESK
        ))
        assert cancelled["status"] == C.RESERVATION_CANCELLED
        assert_cents(
            cancelled["cancellation_fee_cents"], 0,
            "cancellation_fee_cents (cancel more than 30 days before check-in)",
        )
        blocked = get_success_data(client.get_reservation(
            contract_id, r3["id"], headers=FRONT_DESK
        ))
        assert blocked["status"] == C.RESERVATION_REQUESTED, (
            "night 2027-07-11 is taken by the promoted r2, so r3 still waits"
        )
