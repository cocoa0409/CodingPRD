"""Reservation activation: state preconditions, RBAC, line-capacity accounting,
and the compensating bucket invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_line_capacity_buckets,
    create_active_reservation,
    create_customer,
    create_deposit_held_reservation,
    create_module_series,
    create_promoted_line,
    create_production_line,
    create_ramping_line,
    create_reservation,
    get_line,
    get_reservation,
    make_customer_admin_headers,
    post_production_run,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["contracts_officer_headers"]


def test_activate_from_pending_rejected(api):
    """PRD §3.4: "Activation is the commercial desk's step: a `ContractsOfficer`
    moves the reservation `DEPOSIT_HELD → ACTIVE`."
    PRD §2.5: "A request whose target resource is not in a state from which the
    requested transition is defined is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/activate_from_pending_rejected
    """
    customer = create_customer()
    bundle = create_ramping_line()
    reservation = create_reservation(
        customer, bundle["line"], bundle["series"], deposit_usd=125000.0
    )

    resp = api.activate_reservation(reservation["id"], CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_reservation(reservation["id"])["status"] == "PENDING"


def test_customer_admin_cannot_activate_reservation(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.4: "Activation is the commercial desk's step: a `ContractsOfficer`
    moves the reservation `DEPOSIT_HELD → ACTIVE`."

    Design: Corner/rbac/customer_admin_cannot_activate_reservation
    """
    customer = create_customer()
    bundle = create_ramping_line()
    reservation = create_deposit_held_reservation(
        customer, bundle["line"], bundle["series"]
    )

    resp = api.activate_reservation(
        reservation["id"], make_customer_admin_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_reservation(reservation["id"])["status"] == "DEPOSIT_HELD"


def test_fk_reverse_reservations_by_line(api):
    """PRD §4: "Reservations booked on this line"
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/fk_reverse_reservations_by_line
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(
        customer, line, series, deposit_usd=125000.0
    )

    resp = api.list_line_capacity_reservations(line["id"], PM)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 reservation on the line, got {len(data)}"
    assert data[0]["id"] == reservation["id"]


class TestActivationRequiresRampingOrCapacityLine:
    """Activation is defined only while the line is RAMPING or AT_CAPACITY."""

    def test_activate_on_commissioning_line_rejected_then_succeeds(self, api):
        """PRD §3.4: "Activation requires the line to be in `RAMPING` or
        `AT_CAPACITY`, requires the line's `available_capacity_mw` to be at
        least the reservation's `contracted_mw` (else `ERR_CAPACITY_UNAVAILABLE`,
        HTTP 422), and requires the booked series to still be `ACTIVE` (else
        `ERR_SERIES_DISCONTINUED`)."
        PRD §2.5: "A request whose target resource is not in a state from which
        the requested transition is defined is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_line_ramping_or_capacity
        """
        customer = create_customer()
        series = create_module_series()
        line = create_production_line()  # stays COMMISSIONING (no runs yet)
        reservation = create_deposit_held_reservation(customer, line, series)

        resp = api.activate_reservation(reservation["id"], CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_reservation(reservation["id"])["status"] == "DEPOSIT_HELD"

        # Commission the line, then the identical activation succeeds.
        post_production_run(line["id"], series["id"], quarter=0)
        validate_success(api.commission_line(line["id"], PM), 200)
        resp = api.activate_reservation(reservation["id"], CO)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_activate_on_at_capacity_line_succeeds(self, api):
        """PRD §3.4: "Activation requires the line to be in `RAMPING` or
        `AT_CAPACITY`, requires the line's `available_capacity_mw` to be at
        least the reservation's `contracted_mw` (else `ERR_CAPACITY_UNAVAILABLE`,
        HTTP 422), and requires the booked series to still be `ACTIVE` (else
        `ERR_SERIES_DISCONTINUED`)."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_line_ramping_or_capacity
        """
        customer = create_customer()
        bundle = create_promoted_line()
        line = bundle["line"]
        assert line["status"] == "AT_CAPACITY"

        reservation = create_deposit_held_reservation(
            customer, line, bundle["series"]
        )
        resp = api.activate_reservation(reservation["id"], CO)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"


class TestLineCapacityAggregateBooking:
    """Capacity is an aggregate resource: available must cover the activated
    volume, with the boundary inclusive."""

    def test_activate_beyond_available_rejected(self, api):
        """PRD §3.4: "Activation requires the line to be in `RAMPING` or
        `AT_CAPACITY`, requires the line's `available_capacity_mw` to be at
        least the reservation's `contracted_mw` (else `ERR_CAPACITY_UNAVAILABLE`,
        HTTP 422), and requires the booked series to still be `ACTIVE` (else
        `ERR_SERIES_DISCONTINUED`)."
        PRD §2.7: "`committed_capacity_mw` is the sum of `contracted_mw` over
        reservations on the line in `ACTIVE` or `CONSTRAINED` status, and never
        exceeds `annual_capacity_mw`. `reserved_capacity_mw` is the sum over
        reservations in `PENDING` or `DEPOSIT_HELD` status."

        Design: Difficulty/resource_temporal_overlap/line_capacity_aggregate_booking
        """
        customer = create_customer()
        bundle = create_ramping_line()
        line, series = bundle["line"], bundle["series"]

        r1 = create_active_reservation(
            customer, line, series, contracted_mw=40.0, deposit_usd=500000.0
        )
        assert r1["status"] == "ACTIVE"
        r2 = create_deposit_held_reservation(
            customer, line, series, contracted_mw=50.0, deposit_usd=625000.0
        )

        # available == 100.0 - 40.0 (committed) - 50.0 (reserved) == 10.0 < 50.0
        resp = api.activate_reservation(r2["id"], CO)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_UNAVAILABLE)
        assert get_reservation(r2["id"])["status"] == "DEPOSIT_HELD"

        line_after = get_line(line["id"])
        assert line_after["committed_capacity_mw"] == pytest.approx(40.0, abs=1e-6)
        assert line_after["reserved_capacity_mw"] == pytest.approx(50.0, abs=1e-6)

    def test_activate_exactly_at_available_passes(self, api):
        """PRD §3.4: "Activation requires the line to be in `RAMPING` or
        `AT_CAPACITY`, requires the line's `available_capacity_mw` to be at
        least the reservation's `contracted_mw` (else `ERR_CAPACITY_UNAVAILABLE`,
        HTTP 422), and requires the booked series to still be `ACTIVE` (else
        `ERR_SERIES_DISCONTINUED`)."
        PRD §2.7: "`available_capacity_mw` is what remains: the nameplate minus
        committed minus reserved."

        Design: Difficulty/resource_temporal_overlap/line_capacity_aggregate_booking
        """
        customer = create_customer()
        bundle = create_ramping_line()
        line, series = bundle["line"], bundle["series"]

        create_active_reservation(
            customer, line, series, contracted_mw=40.0, deposit_usd=500000.0
        )
        create_deposit_held_reservation(
            customer, line, series, contracted_mw=40.0, deposit_usd=500000.0
        )
        r3 = create_deposit_held_reservation(
            customer, line, series, contracted_mw=10.0, deposit_usd=125000.0
        )

        # available == 100.0 - 40.0 (committed) - 50.0 (reserved, r3's own
        # 10.0 included per §2.7) == 10.0, exactly the activated volume.
        resp = api.activate_reservation(r3["id"], CO)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

        # The reserved->committed move leaves available invariant; the 10.0
        # MW of headroom r3 just consumed is offset by its own 10.0 leaving
        # the reserved bucket.
        line_after = get_line(line["id"])
        assert line_after["committed_capacity_mw"] == pytest.approx(50.0, abs=1e-6)
        assert line_after["reserved_capacity_mw"] == pytest.approx(40.0, abs=1e-6)
        assert line_after["available_capacity_mw"] == pytest.approx(10.0, abs=1e-6)
        assert_line_capacity_buckets(line_after)


class TestLineCapacityBucketsConserved:
    """committed + reserved + available == annual_capacity_mw across paired
    forward/compensating actions."""

    def test_create_then_cancel_from_pending_restores_buckets(self, api):
        """PRD §2.7: "`committed_capacity_mw` is the sum of `contracted_mw` over
        reservations on the line in `ACTIVE` or `CONSTRAINED` status, and never
        exceeds `annual_capacity_mw`. `reserved_capacity_mw` is the sum over
        reservations in `PENDING` or `DEPOSIT_HELD` status.
        `available_capacity_mw` is what remains: the nameplate minus committed
        minus reserved."
        PRD §3.4: "a reservation leaving `PENDING` or `DEPOSIT_HELD` subtracts
        its `contracted_mw` from the line's `reserved_capacity_mw`; one leaving
        `ACTIVE` or `CONSTRAINED` subtracts it from `committed_capacity_mw`;
        `available_capacity_mw` is recomputed and the line's `version`
        increments in either case."

        Design: Difficulty/compensating_invariant/line_capacity_buckets_conserved
        """
        customer = create_customer()
        bundle = create_ramping_line()
        line, series = bundle["line"], bundle["series"]

        reservation = create_reservation(
            customer, line, series, contracted_mw=25.0, deposit_usd=312500.0
        )
        line_mid = get_line(line["id"])
        assert line_mid["reserved_capacity_mw"] == pytest.approx(25.0, abs=1e-6)
        assert line_mid["available_capacity_mw"] == pytest.approx(75.0, abs=1e-6)
        assert_line_capacity_buckets(line_mid)

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

        line_after = get_line(line["id"])
        assert line_after["reserved_capacity_mw"] == pytest.approx(0.0, abs=1e-6)
        assert line_after["committed_capacity_mw"] == pytest.approx(0.0, abs=1e-6)
        assert line_after["available_capacity_mw"] == pytest.approx(
            line_after["annual_capacity_mw"], abs=1e-6
        )

    def test_activate_then_cancel_restores_committed_bucket(self, api):
        """PRD §3.4: "a reservation leaving `PENDING` or `DEPOSIT_HELD`
        subtracts its `contracted_mw` from the line's `reserved_capacity_mw`;
        one leaving `ACTIVE` or `CONSTRAINED` subtracts it from
        `committed_capacity_mw`; `available_capacity_mw` is recomputed and the
        line's `version` increments in either case."
        PRD §3.4: "On activation the line's `reserved_capacity_mw` decreases by
        `contracted_mw`, `committed_capacity_mw` increases by the same amount,
        `available_capacity_mw` and `warranty_reserved_mw` are recomputed, and
        the line's `version` increments."

        Design: Difficulty/compensating_invariant/line_capacity_buckets_conserved
        """
        customer = create_customer()
        bundle = create_ramping_line()
        line, series = bundle["line"], bundle["series"]

        reservation = create_active_reservation(
            customer, line, series, contracted_mw=25.0, deposit_usd=312500.0
        )
        line_mid = get_line(line["id"])
        assert line_mid["committed_capacity_mw"] == pytest.approx(25.0, abs=1e-6)
        assert line_mid["reserved_capacity_mw"] == pytest.approx(0.0, abs=1e-6)
        assert line_mid["available_capacity_mw"] == pytest.approx(75.0, abs=1e-6)

        resp = api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

        line_after = get_line(line["id"])
        assert line_after["committed_capacity_mw"] == pytest.approx(0.0, abs=1e-6)
        assert line_after["reserved_capacity_mw"] == pytest.approx(0.0, abs=1e-6)
        assert line_after["available_capacity_mw"] == pytest.approx(100.0, abs=1e-6)
        assert_line_capacity_buckets(line_after)
