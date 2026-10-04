"""Reservation booking: schema gates, OCC guard, ownership, deposit minimums,
and immediate read-after-write visibility."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_quarter,
    create_customer,
    create_module_series,
    create_production_line,
    create_ramping_line,
    create_reservation,
    create_reservation_payload,
    get_line,
    get_reservation,
    make_customer_admin_headers,
    required_deposit_usd,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

CO = TEST_USERS["contracts_officer_headers"]
PM = TEST_USERS["plant_manager_headers"]


def test_reservation_create_past_delivery_year_rejected(api):
    """PRD §3.4: "The booking must satisfy several constraints: `delivery_year`
    must be at least the logical clock's current year, `contracted_mw` and
    `price_usd_per_w` must be greater than zero, `term_years` must be between 1
    and 5 inclusive, and the booked series must be `ACTIVE` — violations are
    rejected with `ERR_INVALID_REQUEST` (HTTP 400), except that a discontinued
    series surfaces as `ERR_SERIES_DISCONTINUED` (HTTP 422)."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and before any set call it must continue to read
    this default — it must never fall back to wall-clock time."

    Design: Corner/validations/reservation_create_past_delivery_year_rejected
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    version = get_line(line["id"])["version"]

    payload = create_reservation_payload(
        customer_id=customer["id"],
        line_id=line["id"],
        series_id=series["id"],
        delivery_year=2025,  # logical clock default year is 2026
        deposit_usd=125000.0,
        expected_line_version=version,
    )
    resp = api.create_reservation(payload, make_customer_admin_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_cross_customer_post_deposit_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id`
    of the acting `Customer`; ownership checks on any resource that references a
    `Customer` — reservations, deliveries, warranty claims, recycling
    obligations — compare the resource's customer foreign key to `X-User-ID`,
    and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/cross_customer_post_deposit_forbidden
    """
    customer_a = create_customer(legal_name="Acme Solar Dev", credit_tier="TIER_A")
    customer_b = create_customer(legal_name="Beta Power Co", credit_tier="TIER_B")
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer_a, line, series, deposit_usd=125000.0)

    # Customer B attempts to post the deposit on customer A's reservation.
    resp = api.post_deposit(
        reservation["id"], make_customer_admin_headers(customer_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_reservation(reservation["id"])["status"] == "PENDING"


def test_immediate_visibility_after_reservation_create(api):
    """PRD §3.4: "On success the reservation enters `PENDING`, the line's
    `reserved_capacity_mw` grows by `contracted_mw`, `available_capacity_mw` is
    recomputed, and the line's `version` increments by 1."
    PRD §2.4: "Every persisted resource carries `id` (a server-minted UUID with
    no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with
    three fractional digits), and `version` (an integer that increments by 1 on
    every mutation of the resource)."

    Design: Corner/consistency_model/immediate_visibility_after_reservation_create
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer, line, series, deposit_usd=125000.0)

    resp = api.get_reservation(reservation["id"], CO)
    data = validate_success(resp, 200)
    assert data["status"] == "PENDING"
    assert data["contracted_mw"] == pytest.approx(10.0, abs=1e-9)
    assert data["delivered_mw"] == pytest.approx(0.0, abs=1e-9)
    assert data["deposit_forfeited_usd"] == pytest.approx(0.0, abs=1e-9)


def test_reservation_create_stale_line_version_rejected(api):
    """PRD §2.6: "The creation request must carry `expected_line_version`, the
    client's last observed `version` of the target production line. If the
    line's current `version` has advanced since that observation — because
    another reservation on the line was created, activated, cancelled, or
    because a lifecycle action on the line itself bumped its version — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    client from booking against a stale view of `available_capacity_mw`."

    Design: Corner/cross_cutting_complexity_layers/reservation_create_stale_line_version_rejected
    """
    customer = create_customer()
    bundle = create_ramping_line()
    line = bundle["line"]
    series = bundle["series"]
    observed_version = get_line(line["id"])["version"]

    headers = make_customer_admin_headers(customer["id"])
    payload = create_reservation_payload(
        customer_id=customer["id"],
        line_id=line["id"],
        series_id=series["id"],
        contracted_mw=5.0,
        deposit_usd=62500.0,
        expected_line_version=observed_version,
    )
    first = api.create_reservation(payload, headers)
    first_data = validate_success(first, 201)
    assert first_data["status"] == "PENDING"

    version_after = get_line(line["id"])["version"]
    assert version_after == observed_version + 1, (
        "reservation create must increment the line version by 1"
    )

    # Replay the same create with the now-stale observed version.
    replay = api.create_reservation(payload, headers)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    assert get_line(line["id"])["version"] == version_after, (
        "a rejected create must not move the line version"
    )


class TestDepositMinimumBoundary:
    """Deposit minimum = contracted_mw * 1e6 * price * tier fraction; the
    >= boundary is inclusive."""

    def test_post_deposit_exact_minimum_passes(self, api):
        """PRD §3.4: "The required deposit is `contracted_mw` converted to watts
        (multiplied by one million), multiplied by `price_usd_per_w`, multiplied
        by the tier fraction — five percent for `TIER_A`, ten percent for
        `TIER_B`, twenty percent for `TIER_C` — with the result at 2 decimal
        places rounded half up."
        PRD §3.4: "The posted `deposit_usd` must be at least the required
        minimum for the customer's tier; a deposit exactly equal to the minimum
        passes, and anything below it is rejected with `ERR_DEPOSIT_INSUFFICIENT`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/deposit_exact_minimum_boundary
        """
        customer = create_customer(legal_name="Beta Power Co", credit_tier="TIER_B")
        bundle = create_ramping_line()
        # TIER_B minimum: 10.0 * 1e6 * 0.30 * 0.10 == 300000.00 exactly.
        reservation = create_reservation(
            customer, bundle["line"], bundle["series"],
            price_usd_per_w=0.30, deposit_usd=300000.0,
        )
        assert required_deposit_usd(10.0, 0.30, "TIER_B") == pytest.approx(300000.0)

        resp = api.post_deposit(
            reservation["id"], make_customer_admin_headers(customer["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "DEPOSIT_HELD", (
            "a deposit exactly equal to the minimum passes"
        )

    def test_booking_below_minimum_deposit_rejected(self, api):
        """PRD §3.4: "The minimum deposit is tier-based. The required deposit is
        `contracted_mw` converted to watts (multiplied by one million),
        multiplied by `price_usd_per_w`, multiplied by the tier fraction — five
        percent for `TIER_A`, ten percent for `TIER_B`, twenty percent for
        `TIER_C` — with the result at 2 decimal places rounded half up. The same
        minimum is enforced at booking and again when the deposit is posted."

        Design: Difficulty/boundary_precision_check/deposit_exact_minimum_boundary
        """
        customer = create_customer(legal_name="Beta Power Co", credit_tier="TIER_B")
        bundle = create_ramping_line()
        version = get_line(bundle["line"]["id"])["version"]

        # One cent below the TIER_B minimum of 300000.00: rejected at booking.
        payload = create_reservation_payload(
            customer_id=customer["id"],
            line_id=bundle["line"]["id"],
            series_id=bundle["series"]["id"],
            price_usd_per_w=0.30,
            deposit_usd=299999.99,
            expected_line_version=version,
        )
        resp = api.create_reservation(payload, make_customer_admin_headers(customer["id"]))
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_DEPOSIT_INSUFFICIENT, ApiErrorId.ERR_INVALID_REQUEST],
        )
