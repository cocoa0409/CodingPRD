"""Membership lifecycle and the billing close: pinned evaluation order,
tenure discount arming, OCC, wallet flooring, and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_membership,
    get_success_data,
    make_customer_headers,
    read_customer,
    read_membership,
    set_clock,
    validate_error,
    validate_success,
    wallet_adjust,
)

ENROLL_CLOCK = "2026-09-01T00:00:00Z"
# Twelve 30-day billing closes starting at 2026-09-01T00:00:00Z.
CLOSE_INSTANTS = [
    "2026-10-01T00:00:00Z",
    "2026-10-31T00:00:00Z",
    "2026-11-30T00:00:00Z",
    "2026-12-30T00:00:00Z",
    "2027-01-29T00:00:00Z",
    "2027-02-28T00:00:00Z",
    "2027-03-30T00:00:00Z",
    "2027-04-29T00:00:00Z",
    "2027-05-29T00:00:00Z",
    "2027-06-28T00:00:00Z",
    "2027-07-28T00:00:00Z",
    "2027-08-27T00:00:00Z",
]


def _close_paid_period(api, site_ops_headers, membership_id, instant):
    set_clock(instant)
    resp = api.close_membership_period(membership_id, {"period_fee_paid": True}, site_ops_headers)
    return validate_success(resp)


class TestBillingCloseEvaluationOrder:
    def test_membership_billing_close_evaluation_order(self, api, site_ops_headers):
        """PRD §3.4: "Third, tenure_discount_bps is recomputed for the next
        period: it becomes 500 basis points (a 5% discount) once periods_paid
        has reached 12, and remains 0 below that tenure threshold."
        PRD §3.4: "Fifth, period_orders_count and period_credit_earned_cents
        reset to 0."

        Design: Difficulty/combinatorial_formula/membership_billing_close_evaluation_order
        """
        set_clock(ENROLL_CLOCK)
        customer = create_customer(email="tenure@example.com", full_name="Tess Tenure",
                                   date_of_birth="1988-05-05T00:00:00Z")
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        for instant in CLOSE_INSTANTS:
            _close_paid_period(api, site_ops_headers, membership["id"], instant)
        after = read_membership(membership["id"])
        assert after["periods_paid"] == 12
        # armed only AFTER the 12th increment
        assert after["tenure_discount_bps"] == 500
        assert after["status"] == "ACTIVE"
        assert after["period_orders_count"] == 0 and after["period_credit_earned_cents"] == 0

    def test_tenure_discount_zero_below_threshold(self, api, site_ops_headers):
        """PRD §3.4: "it becomes 500 basis points (a 5% discount) once
        periods_paid has reached 12, and remains 0 below that tenure
        threshold."

        Design: Difficulty/combinatorial_formula/membership_billing_close_evaluation_order
        """
        set_clock(ENROLL_CLOCK)
        customer = create_customer()
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        for instant in CLOSE_INSTANTS[:11]:
            _close_paid_period(api, site_ops_headers, membership["id"], instant)
        after = read_membership(membership["id"])
        assert after["periods_paid"] == 11
        assert after["tenure_discount_bps"] == 0, "below the tenure threshold the discount stays 0"
        assert after["status"] == "ACTIVE"

    def test_unpaid_close_lapses_and_renew_revives(self, api, site_ops_headers):
        """PRD §3.4: "Finally, if the period fee went unpaid, the membership
        transitions ACTIVE → LAPSED."
        PRD §3.4: "A LAPSED membership can be revived: the owning customer
        renews it, which requires the membership to currently be LAPSED,
        operates under the customer-version OCC rule of §2.8, and on success
        returns the membership to ACTIVE with a fresh 30-day period starting
        at the logical clock."

        Design: Difficulty/combinatorial_formula/membership_billing_close_evaluation_order
        """
        set_clock(ENROLL_CLOCK)
        customer = create_customer()
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        set_clock("2026-10-01T00:00:00Z")
        resp = api.close_membership_period(
            membership["id"], {"period_fee_paid": False}, site_ops_headers
        )
        closed = validate_success(resp)
        assert closed["status"] == "LAPSED"
        customer_now = read_customer(customer["id"])
        renewed = validate_success(
            api.renew_membership(
                membership["id"],
                {"expected_customer_version": customer_now["version"]},
                make_customer_headers(customer["id"]),
            )
        )
        assert renewed["status"] == "ACTIVE"
        # fresh 30-day period starting at the logical clock
        assert renewed["current_period_start"].startswith("2026-10-01"), renewed
        assert renewed["current_period_end"].startswith("2026-10-31"), renewed


class TestMembershipOCC:
    def test_occ_stale_customer_version_on_membership_cancel(self, api, site_ops_headers):
        """PRD §2.8: "Renewing or cancelling a Membership requires the client
        to supply expected_customer_version matching the owning Customer's
        current version. Because a loyalty accrual on a delivered order bumps
        Customer.version, a membership write carrying a version observed before
        that accrual is rejected with ERR_STALE_VERSION (HTTP 412), keeping
        membership lifecycle writes serialized against wallet-mutating
        cascades."

        Design: Corner/cross_cutting_layers/occ_stale_customer_version_on_membership_cancel
        """
        customer = create_customer(email="occ@example.com", full_name="Oskar Occ",
                                   date_of_birth="1991-01-01T00:00:00Z")
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        observed_version = read_customer(customer["id"])["version"]
        # an interleaving wallet adjustment bumps Customer.version
        wallet_adjust(customer["id"], 25, reason="interleaving bump")
        resp = api.cancel_membership(
            membership["id"],
            {"expected_customer_version": observed_version},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert read_membership(membership["id"])["status"] == "ACTIVE"

    def test_membership_cancel_with_fresh_version_succeeds(self, api, site_ops_headers):
        """PRD §3.4: "A customer may also cancel an ACTIVE membership outright;
        cancellation is one-way to CANCELLED, requires the customer to own the
        membership, and carries the same expected_customer_version OCC guard"
        PRD §2.8: "Renewing or cancelling a Membership requires the client to
        supply expected_customer_version matching the owning Customer's current
        version."

        Design: Corner/cross_cutting_layers/occ_stale_customer_version_on_membership_cancel
        """
        customer = create_customer()
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        fresh_version = read_customer(customer["id"])["version"]
        resp = api.cancel_membership(
            membership["id"],
            {"expected_customer_version": fresh_version},
            make_customer_headers(customer["id"]),
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"


class TestMembershipLockdown:
    def test_membership_terminal_lockdown_cancelled_stays_cancelled(self, api, site_ops_headers):
        """PRD §3.4: "cancellation is one-way to CANCELLED"
        PRD §3.4: "A LAPSED membership can be revived: the owning customer
        renews it, which requires the membership to currently be LAPSED"

        Design: Corner/state_machines/membership_terminal_lockdown_cancelled_stays_cancelled
        """
        customer = create_customer(email="lock@example.com", full_name="Lena Lock",
                                   date_of_birth="1992-02-02T00:00:00Z")
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        version_after_enroll = read_customer(customer["id"])["version"]
        get_success_data(
            api.cancel_membership(
                membership["id"],
                {"expected_customer_version": version_after_enroll},
                make_customer_headers(customer["id"]),
            )
        )
        version_after_cancel = read_customer(customer["id"])["version"]
        renew = api.renew_membership(
            membership["id"],
            {"expected_customer_version": version_after_cancel},
            make_customer_headers(customer["id"]),
        )
        validate_error(renew, ApiErrorId.ERR_INVALID_STATE)
        assert read_membership(membership["id"])["status"] == "CANCELLED"

    def test_membership_re_cancel_rejected(self, api, site_ops_headers):
        """PRD §3.4: "A customer may also cancel an ACTIVE membership outright;
        cancellation is one-way to CANCELLED"

        Design: Corner/state_machines/membership_terminal_lockdown_cancelled_stays_cancelled
        """
        customer = create_customer()
        membership = create_membership(customer["id"], monthly_fee_cents=1000)
        get_success_data(
            api.cancel_membership(
                membership["id"],
                {"expected_customer_version": read_customer(customer["id"])["version"]},
                make_customer_headers(customer["id"]),
            )
        )
        again = api.cancel_membership(
            membership["id"],
            {"expected_customer_version": read_customer(customer["id"])["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)
        assert read_membership(membership["id"])["status"] == "CANCELLED"


class TestWalletFlooring:
    def test_wallet_adjustment_negative_amount_floors_at_zero(self, api):
        """PRD §3.4: "operator adjustments floor the resulting balance at 0 and
        increment the customer's version."

        Design: Corner/endpoints/wallet_adjustment_negative_amount_floors_at_zero
        """
        customer = create_customer(email="floor@example.com", full_name="Flo Floor",
                                   date_of_birth="1991-01-01T00:00:00Z")
        wallet_adjust(customer["id"], 50, reason="seed")
        adjusted = wallet_adjust(customer["id"], -120, reason="clawback")
        assert adjusted["wallet_credit_cents"] == 0, "floored, not -70"
        assert adjusted["version"] == 3, "create, +50, -120 each increment version"

    def test_wallet_adjustment_positive_credit(self, api):
        """PRD §3.4: "can be adjusted directly by SiteOps through an operator
        credit or debit carrying an amount_cents (positive or negative) and a
        reason; operator adjustments floor the resulting balance at 0 and
        increment the customer's version."

        Design: Corner/endpoints/wallet_adjustment_negative_amount_floors_at_zero
        """
        customer = create_customer()
        adjusted = wallet_adjust(customer["id"], 75, reason="promo")
        assert adjusted["wallet_credit_cents"] == 75
        assert adjusted["version"] == 2
