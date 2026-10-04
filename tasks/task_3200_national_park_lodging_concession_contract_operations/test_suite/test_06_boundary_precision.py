"""Boundary precision: exact thresholds decide pass/fail (PRD 3.2, 3.3, 3.7).

The rate cap admits equality and rejects one cent above; the deposit cap
clamps the twenty-percent figure at exactly 50000 cents; the housing pool
rejects at zero free beds and admits the moment one frees up; the thirty-day
refund horizon is strict on the short side.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_HOUSING_FULL,
    ERR_RATE_EXCEEDS_COMPARABILITY,
)
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    active_contract,
    add_room_class,
    add_study,
    approve_filing,
    book_reservation,
    bookable_inventory,
    contract_version,
    hire_employee,
    housing_scenario,
    set_clock,
    submit_filing,
)
from test_helpers.test_users import FRONT_DESK, HR_MANAGER, RATE_ANALYST


class TestRateCapBoundary:
    """cap = round(mean * 1.05); equality passes, one cent over fails."""

    def _scenario(self, client):
        reset = bookable_inventory(
            client,
            study_overrides={
                "title": "S2",
                "comparables": [
                    dict(c) for c in C.STUDY_MEAN_20500_COMPARABLES
                ],
            },
            filing_overrides={
                "submitted_rates": f.band_rates_payload(
                    solo=18000, double=20000, family=21000
                ),
            },
            clock=None,
        )
        return reset

    def _filing(self, client, scenario, family_rate):
        return submit_filing(
            client,
            scenario["contract"]["id"],
            scenario["season"]["id"],
            scenario["room_class"]["id"],
            scenario["study"]["id"],
            submitted_rates=f.band_rates_payload(
                solo=18000, double=20000, family=family_rate
            ),
        )

    def test_a_rate_exactly_at_the_cap_is_approved(self, client):
        """PRD 3.2: "every band's submitted nightly rate must be at most that
        cap — a rate exactly equal to the cap passes, a rate one cent above
        it fails with `ERR_RATE_EXCEEDS_COMPARABILITY`."

        Design: Difficulty/boundary_precision_check/rate_cap_equality_passes_and_one_cent_over_fails
        """
        scenario = self._scenario(client)
        assert scenario["study"]["weighted_mean_cents"] == 20500
        # cap = round_half_up(20500 * 1.05) = 21525.
        filing = self._filing(client, scenario, 21525)
        approved = approve_filing(client, scenario["contract"]["id"], filing["id"])
        assert approved["status"] == C.FILING_APPROVED

    def test_a_rate_one_cent_over_the_cap_is_rejected(self, client):
        """PRD 3.2: "a rate exactly equal to the cap passes, a rate one cent
        above it fails with `ERR_RATE_EXCEEDS_COMPARABILITY`."

        Design: Difficulty/boundary_precision_check/rate_cap_equality_passes_and_one_cent_over_fails
        """
        scenario = self._scenario(client)
        filing = self._filing(client, scenario, 21526)
        contract_id = scenario["contract"]["id"]
        response = client.start_review_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        )
        assert get_success_data(response)["status"] == C.FILING_UNDER_REVIEW
        response = client.approve_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        )
        validate_error(response, ERR_RATE_EXCEEDS_COMPARABILITY)


class TestDepositCap:
    """The deposit is the smaller of 20% and 50000 cents."""

    def test_a_long_stay_clamps_the_deposit_at_the_cap(self, client):
        """PRD 3.3: "The `deposit_cents` is the total charge multiplied by
        0.2, rounded half-up to whole cents, but capped at 50000 cents — the
        deposit is the smaller of the rounded twenty-percent figure and the
        cap."

        Design: Corner/calculations/deposit_caps_at_50000_cents
        """
        scenario = bookable_inventory(client)
        reservation = book_reservation(
            client,
            scenario["contract"]["id"],
            scenario["season"]["id"],
            scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-long",
            check_in_date="2027-07-01T00:00:00Z",
            check_out_date="2027-07-11T00:00:00Z",
            occupancy_band=C.BAND_FAMILY,
        )
        assert reservation["nights"] == 10
        assert_cents(reservation["total_charge_cents"], 260000, "total_charge_cents")
        # 20% of 260000 is 52000; the cap clamps it to 50000.
        assert_cents(reservation["deposit_cents"], 50000, "deposit_cents")

    def test_an_uncapped_stay_pays_exactly_twenty_percent(self, client):
        """PRD 3.3: "The `deposit_cents` is the total charge multiplied by
        0.2, rounded half-up to whole cents, but capped at 50000 cents — the
        deposit is the smaller of the rounded twenty-percent figure and the
        cap."

        Design: Corner/calculations/deposit_caps_at_50000_cents
        """
        scenario = bookable_inventory(client)
        reservation = book_reservation(
            client,
            scenario["contract"]["id"],
            scenario["season"]["id"],
            scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-short",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-13T00:00:00Z",
            occupancy_band=C.BAND_FAMILY,
        )
        # 3 nights at 26000 -> 78000 total; 20% = 15600 < cap.
        assert_cents(reservation["total_charge_cents"], 78000, "total_charge_cents")
        assert_cents(reservation["deposit_cents"], 15600, "deposit_cents")


class TestCancellationFeeBoundary:
    """Thirty days before check-in: full refund; inside: deposit forfeit."""

    def _confirmed_reservation(self, client, guest_ref, check_in, check_out,
                               clock_now):
        """A CONFIRMED reservation, with the logical clock at ``clock_now``."""
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        reservation = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["version"],
            guest_ref=guest_ref,
            check_in_date=check_in,
            check_out_date=check_out,
        )
        # Run the allocation, then land the clock at the requested instant
        # (before check-in, so no no-show sweep has fired).
        set_clock(client, "2027-01-01T00:00:00Z")
        set_clock(client, clock_now)
        confirmed = get_success_data(client.get_reservation(
            contract_id, reservation["id"], headers=FRONT_DESK
        ))
        assert confirmed["status"] == C.RESERVATION_CONFIRMED
        return contract_id, reservation

    def test_cancel_31_days_out_refunds_in_full(self, client):
        """PRD 3.3: "if the cancellation occurs fewer than 30 days before the
        `check_in_date`, the full deposit is forfeit and
        `cancellation_fee_cents` equals `deposit_cents`; otherwise the
        cancellation is free and the fee is zero."

        Design: Corner/calculations/cancellation_fee_depends_on_thirty_day_boundary
        """
        # 2027-07-01 is 31 days before check-in 2027-08-01.
        contract_id, far = self._confirmed_reservation(
            client, "g-far",
            "2027-08-01T00:00:00Z", "2027-08-03T00:00:00Z",
            "2027-07-01T00:00:00Z",
        )
        cancelled = get_success_data(client.cancel_reservation(
            contract_id, far["id"], headers=FRONT_DESK
        ))
        assert cancelled["status"] == C.RESERVATION_CANCELLED
        assert_cents(cancelled["cancellation_fee_cents"], 0,
                     "cancellation_fee_cents (31 days before check-in)")

    def test_cancel_14_days_out_forfeits_the_deposit(self, client):
        """PRD 3.3: "if the cancellation occurs fewer than 30 days before the
        `check_in_date`, the full deposit is forfeit and
        `cancellation_fee_cents` equals `deposit_cents`; otherwise the
        cancellation is free and the fee is zero."

        Design: Corner/calculations/cancellation_fee_depends_on_thirty_day_boundary
        """
        # 2027-06-01 is 14 days before check-in 2027-06-15; the stay is 2
        # SOLO nights at 19000 -> 38000 total, deposit 7600.
        contract_id, near = self._confirmed_reservation(
            client, "g-near",
            "2027-06-15T00:00:00Z", "2027-06-17T00:00:00Z",
            "2027-06-01T00:00:00Z",
        )
        cancelled = get_success_data(client.cancel_reservation(
            contract_id, near["id"], headers=FRONT_DESK
        ))
        assert cancelled["status"] == C.RESERVATION_CANCELLED
        assert_cents(cancelled["cancellation_fee_cents"], 7600,
                     "cancellation_fee_cents (14 days before check-in)")


class TestHousingPoolBoundary:
    """Zero free beds rejects; one freed bed admits exactly one hire."""

    def _setup(self, client):
        scenario = housing_scenario(client, bed_count=2)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        h1 = hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        h2 = hire_employee(client, contract_id, season_id, lodging_id, unit_id)
        arrived = get_success_data(client.mark_arrived(
            contract_id, h2["id"], headers=HR_MANAGER
        ))
        assert arrived["status"] == C.HIRE_ARRIVED
        return scenario, h1, h2

    def test_the_third_hire_at_zero_free_beds_is_rejected(self, client):
        """PRD 3.7: "If no available unit has a free bed, the creation is
        rejected with `ERR_HOUSING_FULL`."

        Design: Difficulty/boundary_precision_check/housing_pool_zero_free_beds_rejected_and_one_freed_admits
        """
        scenario, _h1, _h2 = self._setup(client)
        contract_id = scenario["contract"]["id"]
        response = client.create_hire(
            contract_id,
            f.hire_payload(
                scenario["season"]["id"],
                scenario["lines"][C.LINE_LODGING]["id"],
                scenario["unit"]["id"],
            ),
            headers=HR_MANAGER,
        )
        validate_error(response, ERR_HOUSING_FULL)

    def test_one_freed_bed_admits_exactly_one_more_hire(self, client):
        """PRD 3.7: "A hire occupies one bed from the moment of hiring through
        arrival — `HIRED` and `ARRIVED` hires both occupy beds — and the bed
        is released when the hire becomes `DEPARTED`, `NO_SHOW`, or
        `TERMINATED`."

        Design: Difficulty/boundary_precision_check/housing_pool_zero_free_beds_rejected_and_one_freed_admits
        """
        scenario, _h1, h2 = self._setup(client)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        lodging_id = scenario["lines"][C.LINE_LODGING]["id"]
        unit_id = scenario["unit"]["id"]
        departed = get_success_data(client.mark_departed(
            contract_id, h2["id"], headers=HR_MANAGER
        ))
        assert departed["status"] == C.HIRE_DEPARTED
        hire_four = hire_employee(
            client, contract_id, season_id, lodging_id, unit_id,
            arrival_date="2027-06-05T00:00:00Z",
        )
        assert hire_four["status"] == C.HIRE_HIRED
        # ...and the pool is full again.
        overflow = client.create_hire(
            contract_id,
            f.hire_payload(season_id, lodging_id, unit_id),
            headers=HR_MANAGER,
        )
        validate_error(overflow, ERR_HOUSING_FULL)
