"""Warranty and performance-guarantee claims: filing field rules, review loop,
pinned liquidation rounding, and the line-level warranty capacity cap."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_customer,
    create_module_series,
    create_production_line,
    create_reservation,
    file_claim,
    file_under_review_claim,
    get_reservation,
    guaranteed_energy_kwh,
    make_customer_admin_headers,
    setup_active_reservation,
    validate_error,
    validate_paginated,
    validate_success,
)

WA = TEST_USERS["warranty_administrator_headers"]


def test_defect_claim_measured_energy_forbidden(api):
    """PRD §3.8: "`measured_energy_kwh` — measured first-year energy — is
    required when the claim is a `PERFORMANCE_SHORTFALL` and forbidden
    otherwise."

    Design: Corner/entities/defect_claim_measured_energy_forbidden
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer, line, series, deposit_usd=125000.0)

    resp = api.create_warranty_claim(
        {
            "reservation_id": reservation["id"],
            "claim_type": "PRODUCT_DEFECT",
            "claimed_mw": 1.0,
            "measured_energy_kwh": 100.0,
        },
        make_customer_admin_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_performance_claim_measured_energy_required(api):
    """PRD §3.8: "`measured_energy_kwh` — measured first-year energy — is
    required when the claim is a `PERFORMANCE_SHORTFALL` and forbidden
    otherwise."

    Design: Corner/entities/performance_claim_measured_energy_required
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer, line, series, deposit_usd=125000.0)

    resp = api.create_warranty_claim(
        {
            "reservation_id": reservation["id"],
            "claim_type": "PERFORMANCE_SHORTFALL",
            "claimed_mw": 1.0,
        },
        make_customer_admin_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_fk_reverse_claims_by_reservation(api):
    """PRD §4: "Warranty claims filed against this reservation"
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/fk_reverse_claims_by_reservation
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer, line, series, deposit_usd=125000.0)
    claim = file_claim(reservation, customer, claimed_mw=1.0)

    resp = api.list_reservation_warranty_claims(reservation["id"], WA)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 claim, got {len(data)}"
    assert data[0]["id"] == claim["id"]


def test_warranty_review_loop_request_info(api):
    """PRD §3.8: "A `WarrantyAdministrator` opens review, moving the claim
    `FILED → UNDER_REVIEW`."
    PRD §3.8: "If information is needed, the administrator can return the claim
    `UNDER_REVIEW → FILED` pending customer data, and the review loop may
    repeat."

    Design: Corner/state_machines/warranty_review_loop_request_info
    """
    scenario = setup_active_reservation()
    claim = file_under_review_claim(
        scenario["reservation"], scenario["customer"], claimed_mw=1.0
    )
    assert claim["status"] == "UNDER_REVIEW"

    resp = api.request_info_claim(claim["id"], WA)
    data = validate_success(resp, 200)
    assert data["status"] == "FILED", "request-info loops the claim back to FILED"


def test_withdraw_then_review_rejected(api):
    """PRD §3.8: "Payment moves an `APPROVED` claim to `PAID`; denial is
    terminal; and the owning `CustomerAdmin` may withdraw a claim from `FILED`
    or `UNDER_REVIEW`, moving it to `WITHDRAWN`."
    PRD §2.5: "A request whose target resource is not in a state from which the
    requested transition is defined is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/withdraw_then_review_rejected
    """
    scenario = setup_active_reservation()
    customer = scenario["customer"]
    claim = file_claim(scenario["reservation"], customer, claimed_mw=1.0)

    resp = api.withdraw_claim(claim["id"], make_customer_admin_headers(customer["id"]))
    assert validate_success(resp, 200)["status"] == "WITHDRAWN"

    resp = api.review_claim(claim["id"], WA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_review_claim_on_cancelled_reservation_rejected(api):
    """PRD §3.8: "Review is only possible while the underlying reservation is
    `ACTIVE`, `CONSTRAINED`, or `COMPLETED`; a claim against a `CANCELLED`
    reservation is rejected with `ERR_CLAIM_ON_CANCELLED` (HTTP 409)."

    Design: Corner/state_machines/review_claim_on_cancelled_reservation_rejected
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    reservation = create_reservation(customer, line, series, deposit_usd=125000.0)
    validate_success(
        api.cancel_reservation(
            reservation["id"], make_customer_admin_headers(customer["id"])
        ),
        200,
    )
    claim = file_claim(reservation, customer, claimed_mw=1.0)
    assert claim["status"] == "FILED"

    resp = api.review_claim(claim["id"], WA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_ON_CANCELLED)


class TestPerformanceLiquidationPinnedRounding:
    """guaranteed_energy rounded per claim first; shortfall multiplied by the
    liquidated rate and rounded once — never summed from unrounded parts."""

    def test_liquidation_amount_pinned_rounding(self, api):
        """PRD §3.8: "For a `PERFORMANCE_SHORTFALL` claim, the guaranteed
        first-year energy is computed as `claimed_mw` multiplied by one thousand
        (kilowatts per megawatt) multiplied by a guarantee factor of 1,700.0
        kilowatt-hours per kilowatt, rounded once to 2 decimal places half up;
        if `measured_energy_kwh` is at least that guaranteed energy the claim is
        not payable and must be denied. Otherwise the shortfall is the
        guaranteed energy minus the measured energy, and the liquidated amount
        is the shortfall multiplied by a liquidated rate of 0.05 USD per
        kilowatt-hour, rounded once to 2 decimal places half up after the
        multiplication — never summed from unrounded components."
        PRD §3.8: "In both cases the computed `claim_amount_usd` is frozen at
        approval."

        Design: Difficulty/combinatorial_formula/performance_liquidation_pinned_rounding
        """
        scenario = setup_active_reservation()
        claim = file_under_review_claim(
            scenario["reservation"], scenario["customer"],
            claim_type="PERFORMANCE_SHORTFALL",
            claimed_mw=2.0, measured_energy_kwh=3000000.0,
        )

        resp = api.adjudicate_claim(claim["id"], {"outcome": "APPROVE"}, WA)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        # guaranteed == round(2.0 * 1000 * 1700.0, 2) == 3400000.00;
        # shortfall 400000.00; amount == round(400000.00 * 0.05, 2) == 20000.00
        assert guaranteed_energy_kwh(2.0) == pytest.approx(3400000.00, abs=0.01)
        assert data["claim_amount_usd"] == pytest.approx(20000.00, abs=0.01)

    def test_liquidation_amount_second_factor_set(self, api):
        """PRD §3.8: "Otherwise the shortfall is the guaranteed energy minus the
        measured energy, and the liquidated amount is the shortfall multiplied
        by a liquidated rate of 0.05 USD per kilowatt-hour, rounded once to 2
        decimal places half up after the multiplication — never summed from
        unrounded components."

        Design: Difficulty/combinatorial_formula/performance_liquidation_pinned_rounding
        """
        scenario = setup_active_reservation()
        claim = file_under_review_claim(
            scenario["reservation"], scenario["customer"],
            claim_type="PERFORMANCE_SHORTFALL",
            claimed_mw=1.5, measured_energy_kwh=2500000.0,
        )

        resp = api.adjudicate_claim(claim["id"], {"outcome": "APPROVE"}, WA)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        # guaranteed == 2550000.00; shortfall 50000.00; amount == 2500.00
        assert data["claim_amount_usd"] == pytest.approx(2500.00, abs=0.01)


class TestWarrantyCapExactBoundary:
    """Line-level warranty cap: approved + paid claimed_mw must not exceed
    0.10 * annual_capacity_mw; exactly at the cap passes."""

    def test_approve_at_cap_passes_beyond_cap_rejected(self, api):
        """PRD §3.8: "Across all claims in `APPROVED` or `PAID` status on
        reservations of the claim's line, the sum of `claimed_mw` plus this
        claim's `claimed_mw` must not exceed ten percent of the line's
        `annual_capacity_mw`; an approval exactly at the cap passes, and one
        beyond it is rejected with `ERR_WARRANTY_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_cap_exact_boundary
        """
        scenario = setup_active_reservation()  # line cap: 0.10 * 100.0 == 10.0
        reservation, customer = scenario["reservation"], scenario["customer"]

        claim1 = file_under_review_claim(reservation, customer, claimed_mw=10.0)
        claim2 = file_under_review_claim(reservation, customer, claimed_mw=0.5)

        resp = api.adjudicate_claim(claim1["id"], {"outcome": "APPROVE"}, WA)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED", "0.0 + 10.0 <= 10.0: at cap passes"

        resp = api.adjudicate_claim(claim2["id"], {"outcome": "APPROVE"}, WA)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_CAP_EXCEEDED)

    def test_paid_claims_still_count_toward_cap(self, api):
        """PRD §3.8: "Across all claims in `APPROVED` or `PAID` status on
        reservations of the claim's line, the sum of `claimed_mw` plus this
        claim's `claimed_mw` must not exceed ten percent of the line's
        `annual_capacity_mw`; an approval exactly at the cap passes, and one
        beyond it is rejected with `ERR_WARRANTY_CAP_EXCEEDED` (HTTP 422)."
        PRD §3.8: "Payment moves an `APPROVED` claim to `PAID`; denial is
        terminal; and the owning `CustomerAdmin` may withdraw a claim from
        `FILED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`."

        Design: Difficulty/boundary_precision_check/warranty_cap_exact_boundary
        """
        scenario = setup_active_reservation()
        reservation, customer = scenario["reservation"], scenario["customer"]

        claim1 = file_under_review_claim(reservation, customer, claimed_mw=10.0)
        validate_success(api.adjudicate_claim(claim1["id"], {"outcome": "APPROVE"}, WA), 200)
        paid = validate_success(api.pay_claim(claim1["id"], WA), 200)
        assert paid["status"] == "PAID"

        # The PAID claim still occupies the full 10.0 MW cap.
        claim2 = file_under_review_claim(reservation, customer, claimed_mw=0.5)
        resp = api.adjudicate_claim(claim2["id"], {"outcome": "APPROVE"}, WA)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_CAP_EXCEEDED)
