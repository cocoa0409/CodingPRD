"""Wholesale open credit: the submit-time credit gate boundary and the exposure
input set (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_retail_account,
    create_retail_order,
    deliver_freight_order,
    get_retail_account,
    run_cycle,
    setup_open_cycle,
    submit_order,
    validate_error,
)


class TestCreditExactlyAtLimit:
    """Difficulty instance: credit_exactly_at_limit_passes_one_cent_over_fails.
    Account limit 943950; W1 qty 10 totals 854050 (unit 85405 at the 5% tier),
    leaving exactly 89900 of headroom — one qty-1 order at full price 89900."""

    def _setup(self):
        ctx = setup_open_cycle()
        account = create_retail_account(
            business_name="Exact Credit Co", credit_limit_cents=943_950
        )
        w1 = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=10)
        submit_order(w1)
        w2 = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=1)
        w3 = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=1)
        return ctx, account, w1, w2, w3

    def test_submit_landing_exactly_at_limit_passes(self, api, platform_admin_headers):
        """PRD §3.3: "the account's current `credit_used_cents` plus the submitting
        order's `provisional_total_cents` must not strictly exceed `credit_limit_cents`.
        Equality passes — an order that lands the account exactly at its limit is
        accepted."

        Design: Difficulty/boundary_precision_check/credit_exactly_at_limit_passes_one_cent_over_fails
        """
        _, account, _w1, w2, _w3 = self._setup()
        # 854050 + 89900 == 943950 == limit: equality passes.
        submitted = submit_order(w2)
        assert submitted["allocation_state"] == "RESERVED", (
            f"equality-at-limit submit must be RESERVED, got {submitted['allocation_state']}"
        )
        acct = get_retail_account(account["id"])
        assert acct["credit_used_cents"] == 943950, (
            f"exposure must sit exactly at the limit, got {acct['credit_used_cents']}"
        )

    def test_one_cent_over_limit_is_rejected(self, api, platform_admin_headers):
        """PRD §3.3: "A strictly-over-the-limit submit is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422), and per §2.8 this gate is the last check
        in the pipeline, evaluated only after every other guard has passed."

        Design: Difficulty/boundary_precision_check/credit_exactly_at_limit_passes_one_cent_over_fails
        """
        from test_helpers import make_wholesale_buyer_headers

        _, account, _w1, w2, w3 = self._setup()
        submit_order(w2)  # exposure now exactly 943950
        # 943950 + 89900 == 1033850 > 943950: strictly over.
        resp = api.transition_order(
            w3["id"], {"action": "SUBMIT"}, make_wholesale_buyer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


class TestCreditExposureInputSet:
    def test_credit_exposure_excludes_delivered_orders(self, api, platform_admin_headers):
        """PRD §3.3: "`credit_used_cents` is the sum, across the account's orders whose
        allocation state is `RESERVED` or `ALLOCATED` and whose fulfillment state is
        `PENDING`, `PICKED`, or `SHIPPED`, of each order's `final_total_cents` when the
        order is `ALLOCATED` and its `provisional_total_cents` when it is `RESERVED`.
        Orders that are `UNALLOCATED`, `WAITLISTED`, `DROPPED`, `DELIVERED`, or
        `CANCELLED` contribute nothing."

        Design: Corner/calculations/credit_exposure_excludes_delivered_orders
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=1_000_000)
        order = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=1)
        submit_order(order)
        run_cycle(ctx["cycle"]["id"])
        # ALLOCATED, not yet delivered: counts at final_total_cents (89900, tier 0).
        assert get_retail_account(account["id"])["credit_used_cents"] == 89900
        deliver_freight_order(order["id"])
        # DELIVERED leaves the exposure set.
        assert get_retail_account(account["id"])["credit_used_cents"] == 0, (
            "a DELIVERED order must release its exposure"
        )


class TestAccountCloseGate:
    def test_account_close_with_open_exposure_returns_422(self, api, platform_admin_headers):
        """PRD §3.3: "closure is only accepted when `credit_used_cents` is exactly zero,
        otherwise `ERR_ACCOUNT_HAS_OPEN_EXPOSURE`, and any other transition is
        `ERR_INVALID_TRANSITION`."

        Design: Corner/errors/account_close_with_open_exposure_returns_422
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=1_000_000)
        order = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=1)
        submit_order(order)  # exposure 89900 > 0
        resp = api.transition_retail_account(
            account["id"], {"to_state": "CLOSED"}, platform_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_EXPOSURE.value)
        assert get_retail_account(account["id"])["status"] == "ACTIVE"
