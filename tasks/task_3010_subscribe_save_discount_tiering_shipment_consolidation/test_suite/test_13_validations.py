"""Validation claims: required fields, enum domains, scalar ranges, temporal
rules, and fiscal gates (PRD §2.5, §3.2, §3.3, §3.7, §3.11)."""
from test_helpers import (
    ADMIN,
    SUPPORT,
    ApiErrorId,
    api_client,
    attach_coupon,
    create_coupon,
    create_customer,
    create_coupon_payload,
    create_product,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_customer_by_id,
    get_placement,
    get_plan,
    get_success_data,
    list_plan_lines,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    setup_delivered_plan,
    setup_reported_claim,
    validate_error,
    validate_success,
)

GHOST_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestRequiredFields:
    def test_subscription_create_missing_required_product_id(self):
        """PRD §3.3: "A `Customer` subscribes by supplying a payload
        containing their own `customer_id`, the `product_id`, a
        `cadence_months` between 1 and 6 inclusive, a `quantity` between 1 and
        30 units per delivery, a `start_date` for the first delivery, and an
        optional `price_cap_cents`."
        PRD §2.5: "(1) request well-formedness — all required fields present,
        no unknown fields, field types correct — rejected as
        `ERR_INVALID_REQUEST`".

        Design: Corner/validations/subscription_create_missing_required_product_id
        """
        set_clock()
        customer = create_customer()
        payload = {"customer_id": customer["id"], "cadence_months": 1,
                   "quantity": 1, "start_date": "2026-09-10"}
        resp = api_client.create_subscription(
            payload, make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTypeConstraints:
    def test_coupon_create_with_invalid_discount_type_enum(self):
        """PRD §3.7: "A `PlatformAdmin` creates coupons with a unique `code`,
        a `discount_type` of `PERCENT` or `FLAT`, a validity window
        `valid_from`/`valid_to`, and the matching value field".

        Design: Corner/validations/coupon_create_with_invalid_discount_type_enum
        """
        set_clock()
        payload = create_coupon_payload("BOGO")
        payload["discount_type"] = "BOGO"
        resp = api_client.create_coupon(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestScalarRanges:
    def test_subscription_create_with_cadence_seven_returns_invalid_cadence(self):
        """PRD §3.3: "An out-of-range cadence is rejected with
        `ERR_INVALID_CADENCE`".

        Design: Corner/validations/subscription_create_with_cadence_seven_returns_invalid_cadence
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 7, "quantity": 1, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CADENCE)

    def test_customer_patch_with_delivery_day_29_returns_invalid_delivery_day(self):
        """PRD §3.2: "An out-of-range `preferred_delivery_day`, whether at
        creation or on a later patch, is rejected with
        `ERR_INVALID_DELIVERY_DAY`; both the administrator and the customer
        themselves may patch that field on their own record."

        Design: Corner/validations/customer_patch_with_delivery_day_29_returns_invalid_delivery_day
        """
        set_clock()
        customer = create_customer()
        resp = api_client.patch_customer(
            customer["id"], {"preferred_delivery_day": 29},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_DELIVERY_DAY)
        assert get_customer_by_id(customer["id"])["preferred_delivery_day"] == 10

    def test_subscription_create_with_quantity_zero_returns_out_of_range(self):
        """PRD §3.3: "an out-of-range quantity with
        `ERR_QUANTITY_OUT_OF_RANGE`."

        Design: Corner/validations/subscription_create_with_quantity_zero_returns_quantity_out_of_range
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 1, "quantity": 0, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUANTITY_OUT_OF_RANGE)


class TestTemporalRules:
    def test_start_date_one_day_out_returns_too_soon(self):
        """PRD §3.3: "The `start_date` must be at least two days after the
        logical today — anything earlier is rejected with
        `ERR_START_DATE_TOO_SOON`."

        Design: Corner/validations/subscription_create_with_start_date_one_day_out_returns_too_soon
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 1, "quantity": 1, "start_date": "2026-09-02"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_START_DATE_TOO_SOON)

    def test_coupon_attach_before_valid_from_returns_not_yet_valid(self):
        """PRD §3.7: "a plan whose `delivery_date` falls before the coupon's
        `valid_from` is rejected with `ERR_COUPON_NOT_YET_VALID`".

        Design: Corner/validations/coupon_attach_before_valid_from_returns_not_yet_valid
        """
        customer, product, placement, subs, plan = setup_customer_with_plan()
        create_coupon("FUTURE", discount_type="FLAT", flat_off_cents=100,
                      stackable=False, valid_from="2026-09-15",
                      valid_to="2026-09-30")
        resp = attach_coupon(plan, customer, "FUTURE")
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_YET_VALID)
        assert get_plan(plan["id"])["applied_coupon_codes"] == []


class TestCatalogUsability:
    def test_subscription_on_discontinued_product_returns_not_subscribable(self):
        """PRD §3.3: "a discontinued product or one with
        `subscription_eligible` set false is rejected with
        `ERR_PRODUCT_NOT_SUBSCRIBABLE`".

        Design: Corner/validations/subscription_on_discontinued_product_returns_not_subscribable
        """
        from test_helpers import add_price
        set_clock()
        customer = create_customer()
        product = create_product(discontinued=True)
        add_price(product["id"])
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 1, "quantity": 1, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SUBSCRIBABLE)

    def test_subscription_on_priceless_product_returns_without_price(self):
        """PRD §3.3: "a product with no effective price at the logical present
        is rejected with `ERR_PRODUCT_WITHOUT_PRICE`."

        Design: Corner/validations/subscription_on_priceless_product_returns_product_without_price
        """
        set_clock()
        customer = create_customer()
        product = create_product()
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 1, "quantity": 1, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_WITHOUT_PRICE)

    def test_subscription_with_unknown_product_id_returns_not_found(self):
        """PRD §2.5: "(5) existence of path- and body-referenced resources,
        validated left-to-right so an outer identifier is checked before an
        inner one, each with its own not-found error".
        PRD §5: `ERR_PRODUCT_NOT_FOUND` maps to 404 Not Found.

        Design: Corner/validations/subscription_with_unknown_product_id_returns_product_not_found
        """
        set_clock()
        customer = create_customer()
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": GHOST_ID,
             "cadence_months": 1, "quantity": 1, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


class TestCouponStackingLimits:
    def _setup_plan_with_coupons(self):
        customer, product, placement, subs, plan = setup_customer_with_plan()
        return customer, plan

    def test_third_coupon_attach_returns_stack_limit(self):
        """PRD §3.7: "a plan carries at most 2 coupons, so attaching a third
        is rejected with `ERR_COUPON_STACK_LIMIT`".

        Design: Corner/validations/third_coupon_attach_returns_stack_limit
        """
        customer, plan = self._setup_plan_with_coupons()
        for code in ("A1", "A2", "A3"):
            create_coupon(code, discount_type="FLAT", flat_off_cents=10,
                          stackable=True)
        validate_success(attach_coupon(plan, customer, "A1"))
        validate_success(attach_coupon(plan, customer, "A2"))
        resp = attach_coupon(plan, customer, "A3")
        validate_error(resp, ApiErrorId.ERR_COUPON_STACK_LIMIT)
        assert get_plan(plan["id"])["applied_coupon_codes"] == ["A1", "A2"]

    def test_second_coupon_after_non_stackable_returns_not_stackable(self):
        """PRD §3.7: "a non-stackable coupon may never be combined with any
        other coupon in either direction, so attaching a non-stackable coupon
        to a plan that already holds one, or attaching any coupon to a plan
        already holding a non-stackable one, is rejected with
        `ERR_COUPON_NOT_STACKABLE`."

        Design: Corner/validations/second_coupon_after_non_stackable_returns_not_stackable
        """
        customer, plan = self._setup_plan_with_coupons()
        create_coupon("SOLO", discount_type="FLAT", flat_off_cents=10,
                      stackable=False)
        create_coupon("OTHER", discount_type="FLAT", flat_off_cents=10,
                      stackable=True)
        validate_success(attach_coupon(plan, customer, "SOLO"))
        resp = attach_coupon(plan, customer, "OTHER")
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_STACKABLE)
        assert get_plan(plan["id"])["applied_coupon_codes"] == ["SOLO"]


class TestClaimShape:
    def test_claim_with_empty_damaged_lines_returns_claim_lines_invalid(self):
        """PRD §3.11: "An empty array, an id that is not on the plan, or a
        line not in `SHIPPED` status is rejected with
        `ERR_CLAIM_LINES_INVALID`."

        Design: Corner/validations/claim_with_empty_damaged_lines_returns_claim_lines_invalid
        """
        customer, product, placement, subs, plan = setup_delivered_plan()
        resp = api_client.create_damage_claim(
            plan["id"], {"damaged_line_ids": []},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_LINES_INVALID)


class TestReshipStockGate:
    def test_reship_review_without_stock_returns_insufficient_inventory(self):
        """PRD §3.11: "A reship approval is gated on stock: for every damaged
        line, the line's product must have a placement in the plan customer's
        region with `on_hand_units` at least the line's `quantity`, or the
        review is rejected with `ERR_INSUFFICIENT_INVENTORY`."

        Design: Corner/validations/reship_review_without_stock_returns_insufficient_inventory
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(quantity=4, units=4))
        resp = api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
        claim_after = get_success_data(
            api_client.get_damage_claim(claim["id"], SUPPORT))
        assert claim_after["claim_status"] == "REPORTED"
        placement_after = get_placement(placement["id"])
        assert placement_after["on_hand_units"] == 0
        assert placement_after["shipped_units"] == 4


class TestSuspendedAccountGate:
    def test_suspended_customer_cannot_create_subscription(self):
        """PRD §3.2: "While an account is `SUSPENDED`, two customer-initiated
        operations are blocked with `ERR_CUSTOMER_SUSPENDED` (HTTP 409):
        creating a new subscription, and resuming a paused one."

        Design: Corner/validations/suspended_customer_cannot_create_subscription
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        get_success_data(api_client.suspend_customer(customer["id"], ADMIN))
        resp = api_client.create_subscription(
            {"customer_id": customer["id"], "product_id": product["id"],
             "cadence_months": 1, "quantity": 1, "start_date": "2026-09-10"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
