"""Reservation close-out sweep and the pinned deposit-forfeiture waterfall."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_quarter,
    create_customer,
    create_ramping_line,
    create_active_reservation,
    get_line,
    get_reservation,
    make_customer_admin_headers,
    set_clock,
    setup_active_reservation,
    setup_delivered_reservation,
    validate_success,
)

CO = TEST_USERS["contracts_officer_headers"]


def test_closeout_sweep_completes_reservation_full_forfeit(api):
    """PRD §3.4: "The reservation close-out sweep, run as part of the
    quarter-close operation, completes a reservation — `ACTIVE → COMPLETED` —
    once its booking term has fully elapsed, meaning the logical clock's current
    year is strictly greater than `delivery_year` plus `term_years` minus 1."
    PRD §3.2: "The operation returns the `closed_quarter` index plus counts of
    `lines_promoted` and `reservations_completed` (the close-out sweep of §3.4
    runs in the same operation)."
    PRD §3.4: "Otherwise the forfeiture is the smaller of the posted
    `deposit_usd` and fifteen percent of the shortfall between contract value
    and delivered value."

    Design: Corner/state_machines/closeout_sweep_completes_reservation_full_forfeit
    """
    scenario = setup_active_reservation(
        reservation_overrides={
            "contracted_mw": 10.0, "price_usd_per_w": 0.25,
            "deposit_usd": 200000.0, "delivery_year": 2027, "term_years": 1,
        }
    )
    reservation = scenario["reservation"]
    line_id = scenario["line"]["id"]

    # Clock year 2028 > 2027 + 1 - 1: the booking term has fully elapsed.
    set_clock("2028-06-01T00:00:00Z")
    close = close_quarter()
    assert close["reservations_completed"] == 1, (
        f"exactly one reservation term elapsed, got {close['reservations_completed']}"
    )

    after = get_reservation(reservation["id"])
    assert after["status"] == "COMPLETED"
    # delivered_mw == 0: forfeit = MIN(200000.00, 0.15 * 2500000.00) = 200000.00
    assert after["deposit_forfeited_usd"] == pytest.approx(200000.00, abs=0.01)
    line_after = get_line(line_id)
    assert line_after["committed_capacity_mw"] == pytest.approx(0.0, abs=1e-6)


def test_forfeiture_zero_at_performance_floor(api):
    """PRD §3.4: "The evaluation order is pinned. First compute the delivered
    value: `delivered_mw` converted to watts times `price_usd_per_w`. Then
    compute the contract value the same way from `contracted_mw`. If the
    delivered value is at least eighty percent of the contract value, nothing is
    forfeited."

    Design: Corner/calculations/forfeiture_zero_at_performance_floor
    """
    scenario = setup_delivered_reservation(volume_mw=8.0)
    reservation = scenario["reservation"]
    customer = scenario["customer"]
    assert reservation["delivered_mw"] == pytest.approx(8.0, abs=1e-9)

    # delivered_value == 8.0 * 1e6 * 0.25 == 2000000.00 == 0.80 * 2500000.00
    resp = api.cancel_reservation(
        reservation["id"], make_customer_admin_headers(customer["id"])
    )
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"
    assert data["delivered_mw"] == pytest.approx(8.0, abs=1e-9)
    assert data["deposit_forfeited_usd"] == pytest.approx(0.0, abs=0.01), (
        "floor met exactly (>= eighty percent): nothing is forfeited"
    )


class TestForfeiturePinnedEvaluationOrder:
    """The waterfall order resolves delivered value first, then compares
    against the performance floor, then caps the forfeiture at the deposit."""

    def test_partial_delivery_below_floor_forfeits_shortfall_share(self, api):
        """PRD §3.4: "The evaluation order is pinned. First compute the
        delivered value: `delivered_mw` converted to watts times
        `price_usd_per_w`. Then compute the contract value the same way from
        `contracted_mw`. If the delivered value is at least eighty percent of
        the contract value, nothing is forfeited. Otherwise the forfeiture is
        the smaller of the posted `deposit_usd` and fifteen percent of the
        shortfall between contract value and delivered value. The refund is the
        deposit minus the forfeiture."

        Design: Difficulty/combinatorial_formula/forfeiture_pinned_evaluation_order
        """
        scenario = setup_delivered_reservation(volume_mw=5.0)
        reservation = scenario["reservation"]
        customer = scenario["customer"]

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        assert data["delivered_mw"] == pytest.approx(5.0, abs=1e-9)
        # delivered 1250000.00 < 0.80 * 2500000.00 == 2000000.00;
        # forfeit = MIN(200000.00, 0.15 * 1250000.00) == 187500.00
        assert data["deposit_forfeited_usd"] == pytest.approx(187500.00, abs=0.01)
        assert data["deposit_usd"] == pytest.approx(200000.00, abs=0.01)

    def test_min_cap_binds_when_shortfall_share_exceeds_deposit(self, api):
        """PRD §3.4: "Otherwise the forfeiture is the smaller of the posted
        `deposit_usd` and fifteen percent of the shortfall between contract
        value and delivered value. The refund is the deposit minus the
        forfeiture."

        Design: Difficulty/combinatorial_formula/forfeiture_pinned_evaluation_order
        """
        scenario = setup_delivered_reservation(volume_mw=3.0)
        reservation = scenario["reservation"]
        customer = scenario["customer"]

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        # delivered 750000.00 < 2000000.00 floor;
        # 0.15 * (2500000.00 - 750000.00) == 262500.00 > deposit 200000.00
        assert data["deposit_forfeited_usd"] == pytest.approx(200000.00, abs=0.01)


class TestDepositSplitConservedOnCancel:
    """deposit_usd == deposit_forfeited_usd + refundable remainder, exactly."""

    def test_zero_delivery_forfeits_entire_deposit(self, api):
        """PRD §3.4: "When a reservation leaves `ACTIVE` or `CONSTRAINED` —
        whether by the close-out sweep or by immediate cancellation — the
        deposit-forfeiture waterfall runs against its `delivered_mw` to date,
        and the forfeited amount is recorded in `deposit_forfeited_usd` (leaving
        any refundable balance as the remainder of the deposit)."
        PRD §3.4: "Otherwise the forfeiture is the smaller of the posted
        `deposit_usd` and fifteen percent of the shortfall between contract
        value and delivered value. The refund is the deposit minus the
        forfeiture."

        Design: Difficulty/compensating_invariant/deposit_split_conserved_on_cancel
        """
        scenario = setup_active_reservation()  # no deliveries at all
        reservation = scenario["reservation"]
        customer = scenario["customer"]

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        # delivered_value 0.00 < floor; 0.15 * 2500000.00 == 375000.00 > deposit
        assert data["deposit_forfeited_usd"] == pytest.approx(200000.00, abs=0.01)
        assert data["deposit_usd"] == pytest.approx(200000.00, abs=0.01)
        refundable = data["deposit_usd"] - data["deposit_forfeited_usd"]
        assert refundable == pytest.approx(0.00, abs=0.01), (
            "forfeit + refundable must conserve the deposit exactly"
        )

    def test_partial_delivery_conserves_deposit_split(self, api):
        """PRD §3.4: "the forfeited amount is recorded in
        `deposit_forfeited_usd` (leaving any refundable balance as the remainder
        of the deposit)."
        PRD §3.4: "Otherwise the forfeiture is the smaller of the posted
        `deposit_usd` and fifteen percent of the shortfall between contract
        value and delivered value. The refund is the deposit minus the
        forfeiture."

        Design: Difficulty/compensating_invariant/deposit_split_conserved_on_cancel
        """
        scenario = setup_delivered_reservation(volume_mw=5.0)
        reservation = scenario["reservation"]
        customer = scenario["customer"]

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["deposit_forfeited_usd"] == pytest.approx(187500.00, abs=0.01)
        refundable = data["deposit_usd"] - data["deposit_forfeited_usd"]
        assert refundable == pytest.approx(12500.00, abs=0.01), (
            "refund = deposit - forfeiture = 200000.00 - 187500.00"
        )
