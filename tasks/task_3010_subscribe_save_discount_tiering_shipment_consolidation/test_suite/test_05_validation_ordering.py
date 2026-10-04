"""Validation-ordering probes: one error wins when two checks could fire
(PRD §2.5)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    attach_coupon,
    cancel_subscription_and_get_offer,
    create_coupon,
    create_customer,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_success,
)


class TestStateBeatsConstraint:
    def test_cancelled_subscription_patch_reports_state_error(self):
        """PRD §2.5: "(6) state preconditions, including the
        optimistic-concurrency version match on refresh — the state errors and
        `ERR_STALE_PLAN_VERSION`; (7) scalar domain ranges — cadence, delivery
        day, quantity, price cap, claim line shape".

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_constraint_error_on_cancelled_subscription_patch
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api_client.decline_retention_offer(offer["id"], headers))
        assert get_error(api_client.patch_subscription(
            sub["id"], {"cadence_months": 9}, headers)) == "ERR_SUBSCRIPTION_NOT_ACTIVE"

    def test_state_error_carries_409_not_422(self):
        """PRD §5: `ERR_SUBSCRIPTION_NOT_ACTIVE` maps to 409 Conflict;
        `ERR_INVALID_CADENCE` maps to 422 Unprocessable Entity.
        PRD §2.5: "A later check is only reached when every earlier check
        passes."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_constraint_error_on_cancelled_subscription_patch
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api_client.decline_retention_offer(offer["id"], headers))
        resp = api_client.patch_subscription(
            sub["id"], {"cadence_months": 9}, headers)
        assert resp.status_code == 409, (
            f"expected 409 for the state error, got {resp.status_code}")
        assert resp.json()["data"]["error_id"] == "ERR_SUBSCRIPTION_NOT_ACTIVE"


class TestTemporalBeatsFiscal:
    def _setup(self):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1, price_cents=1000,
        )
        create_coupon("OLD", discount_type="FLAT", flat_off_cents=100,
                      stackable=False, min_subtotal_cents=999999,
                      valid_from="2026-08-01", valid_to="2026-08-31")
        return customer, plan

    def test_expired_coupon_wins_over_min_subtotal(self):
        """PRD §2.5: "(9) temporal rules — start-date lead time, coupon
        windows, price-event monotonicity, promotion window overlap, offer
        expiry; and finally (10) money and stock gates — coupon minimum
        subtotal, stacking limits, and reshipment stock sufficiency."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_fiscal_error_on_coupon_attach
        """
        customer, plan = self._setup()
        resp = attach_coupon(plan, customer, "OLD")
        error = validate_error(resp, ApiErrorId.ERR_COUPON_EXPIRED)
        assert error["error_id"] == "ERR_COUPON_EXPIRED"

    def test_expired_coupon_error_carries_422(self):
        """PRD §5: `ERR_COUPON_EXPIRED` maps to 422 Unprocessable Entity.
        PRD §2.5: "A later check is only reached when every earlier check
        passes."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_fiscal_error_on_coupon_attach
        """
        customer, plan = self._setup()
        resp = attach_coupon(plan, customer, "OLD")
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] == "ERR_COUPON_EXPIRED"


def get_error(response):
    return response.json()["data"]["error_id"]
