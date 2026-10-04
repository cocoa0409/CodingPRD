"""Subscription creation rules, cadence arithmetic, and request validation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_customer,
    create_stocked_product,
    create_subscription,
    create_subscription_payload,
    get_subscription_by_id,
    make_customer_headers,
    make_platform_admin_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestSubscriptionInitialState:
    def test_subscription_created_in_active_with_start_date_as_next_delivery(self, api):
        """PRD §3.3: "On creation the subscription is `ACTIVE`, its
        `next_delivery_date` equals its `start_date`, and the system captures
        the product's `current_price_cents` into `subscribe_price_cents` — the
        baseline against which price-increase notices are later judged."
        PRD §3.3: "a null cap means uncapped."

        Design: Corner/state_machines/subscription_created_in_active_with_start_date_as_next_delivery
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(price_cents=1000)
        resp = api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"],
                cadence_months=2, quantity=3, start_date="2026-09-20",
            ),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["next_delivery_date"] == "2026-09-20"
        assert data["subscribe_price_cents"] == 1000
        assert data["price_cap_cents"] is None

    def test_cadence_advance_month_end_clamps_oct31_to_nov30(self, api):
        """PRD §3.3: "the day-of-month is the lesser of the source day and the
        number of days in the target month — so a January 31 anchor advanced by
        one month lands on the last day of February, not March 3. This same
        clamping governs plan-generation advancement, resume fix-up, and cadence
        changes alike."
        PRD §3.5: "a DeliveryPlan is created in `OPEN` status with its
        `delivery_date` set to the customer's `preferred_delivery_day` within
        the target month".

        Design: Corner/entities/cadence_advance_month_end_clamps_oct31_to_nov30
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(
            customer, product, cadence_months=1, start_date="2026-10-31",
        )
        get_success = validate_success(
            api.generate_plans({"delivery_month": "2026-10"}, ADMIN), 201,
        )
        assert get_success, "expected a plan to be generated"
        plan = get_success[0]
        assert plan["delivery_date"] == "2026-10-10"
        updated = get_subscription_by_id(sub["id"], customer)
        assert updated["next_delivery_date"] == "2026-11-30"


class TestSubscriptionValidation:
    def test_subscription_create_missing_required_product_id(self, api):
        """PRD §2.5: "The server checks, in this sequence: (1) request
        well-formedness — all required fields present, no unknown fields, field
        types correct — rejected as `ERR_INVALID_REQUEST`".

        Design: Corner/validations/subscription_create_missing_required_product_id
        """
        set_clock()
        customer = create_customer()
        payload = create_subscription_payload(customer["id"], "placeholder")
        payload.pop("product_id")
        resp = api.create_subscription(
            payload, make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_coupon_create_with_invalid_discount_type_enum(self, api):
        """PRD §3.7: "a `discount_type` of `PERCENT` or `FLAT`".
        PRD §2.5: "(1) request well-formedness — all required fields present, no
        unknown fields, field types correct — rejected as `ERR_INVALID_REQUEST`".

        Design: Corner/validations/coupon_create_with_invalid_discount_type_enum
        """
        set_clock()
        resp = api.create_coupon(
            {
                "code": "BOGO",
                "discount_type": "BOGO",
                "valid_from": "2026-09-01",
                "valid_to": "2026-09-30",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_subscription_create_with_cadence_seven_returns_invalid_cadence(self, api):
        """PRD §3.3: "a `cadence_months` between 1 and 6 inclusive"
        PRD §3.3: "An out-of-range cadence is rejected with
        `ERR_INVALID_CADENCE`".

        Design: Corner/validations/subscription_create_with_cadence_seven_returns_invalid_cadence
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        resp = api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], cadence_months=7,
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CADENCE.value, 422)

    def test_customer_patch_with_delivery_day_29_returns_invalid_delivery_day(self, api):
        """PRD §3.2: "the day of month on which consolidated deliveries are
        scheduled, between 1 and 28 inclusive"
        PRD §3.2: "An out-of-range `preferred_delivery_day`, whether at creation
        or on a later patch, is rejected with `ERR_INVALID_DELIVERY_DAY`".

        Design: Corner/validations/customer_patch_with_delivery_day_29_returns_invalid_delivery_day
        """
        set_clock()
        customer = create_customer()
        resp = api.patch_customer(
            customer["id"], {"preferred_delivery_day": 29},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DELIVERY_DAY.value, 422)
        unchanged = validate_success(api.get_customer(customer["id"], ADMIN))
        assert unchanged["preferred_delivery_day"] == 10

    def test_subscription_create_with_quantity_zero_returns_quantity_out_of_range(self, api):
        """PRD §3.3: "a `quantity` between 1 and 30 units per delivery"
        PRD §3.3: "An out-of-range cadence is rejected with
        `ERR_INVALID_CADENCE`, an out-of-range quantity with
        `ERR_QUANTITY_OUT_OF_RANGE`."

        Design: Corner/validations/subscription_create_with_quantity_zero_returns_quantity_out_of_range
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        resp = api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], quantity=0),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUANTITY_OUT_OF_RANGE.value, 422)

    def test_subscription_create_with_start_date_one_day_out_returns_too_soon(self, api):
        """PRD §3.3: "The `start_date` must be at least two days after the
        logical today — anything earlier is rejected with
        `ERR_START_DATE_TOO_SOON`."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-09-01T00:00:00Z`."

        Design: Corner/validations/subscription_create_with_start_date_one_day_out_returns_too_soon
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        resp = api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], start_date="2026-09-02",
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_START_DATE_TOO_SOON.value, 422)

    def test_subscription_on_discontinued_product_returns_not_subscribable(self, api):
        """PRD §3.3: "The product must be usable for subscription: a
        discontinued product or one with `subscription_eligible` set false is
        rejected with `ERR_PRODUCT_NOT_SUBSCRIBABLE`".

        Design: Corner/validations/subscription_on_discontinued_product_returns_not_subscribable
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(units=0, discontinued=True)
        resp = api.create_subscription(
            create_subscription_payload(customer["id"], product["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SUBSCRIBABLE.value, 422)

    def test_subscription_on_priceless_product_returns_product_without_price(self, api):
        """PRD §3.3: "a product with no effective price at the logical present
        is rejected with `ERR_PRODUCT_WITHOUT_PRICE`".

        Design: Corner/validations/subscription_on_priceless_product_returns_product_without_price
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(price_cents=None, units=0)
        resp = api.create_subscription(
            create_subscription_payload(customer["id"], product["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_WITHOUT_PRICE.value, 422)

    def test_subscription_with_unknown_product_id_returns_product_not_found(self, api):
        """PRD §2.5: "existence of path- and body-referenced resources,
        validated left-to-right so an outer identifier is checked before an
        inner one, each with its own not-found error".
        PRD §5: "`ERR_PRODUCT_NOT_FOUND` | 404 Not Found".

        Design: Corner/validations/subscription_with_unknown_product_id_returns_product_not_found
        """
        set_clock()
        customer = create_customer()
        resp = api.create_subscription(
            create_subscription_payload(customer["id"], NON_EXISTENT_UUID),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value, 404)

    def test_suspended_customer_cannot_create_subscription(self, api):
        """PRD §3.2: "While an account is `SUSPENDED`, two customer-initiated
        operations are blocked with `ERR_CUSTOMER_SUSPENDED` (HTTP 409):
        creating a new subscription, and resuming a paused one."

        Design: Corner/validations/suspended_customer_cannot_create_subscription
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        validate_success(api.suspend_customer(customer["id"], ADMIN))
        resp = api.create_subscription(
            create_subscription_payload(customer["id"], product["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value, 409)


class TestPriceEventMonotonicity:
    def test_price_event_equal_effective_from_rejected_then_later_accepted(self, api):
        """PRD §2.9: "Price events for a product must be strictly increasing in
        `effective_from`: appending an event whose `effective_from` is not
        strictly greater than every existing event for that product is rejected
        with `ERR_PRICE_EVENT_NOT_MONOTONIC` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/price_event_equal_effective_from_collides_closed_point_semantics
        """
        set_clock()
        product, _ = create_stocked_product(price_cents=1000, units=0)
        resp = api.create_price_event(
            product["id"],
            {"price_cents": 1100, "effective_from": "2026-09-01T00:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_EVENT_NOT_MONOTONIC.value, 409)

    def test_price_event_one_second_later_accepted(self, api):
        """PRD §2.9: "Price events for a product must be strictly increasing in
        `effective_from`: appending an event whose `effective_from` is not
        strictly greater than every existing event for that product is rejected
        with `ERR_PRICE_EVENT_NOT_MONOTONIC` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/price_event_equal_effective_from_collides_closed_point_semantics
        """
        set_clock()
        product, _ = create_stocked_product(price_cents=1000, units=0)
        resp = api.create_price_event(
            product["id"],
            {"price_cents": 1100, "effective_from": "2026-09-01T00:00:01Z"},
            ADMIN,
        )
        validate_success(resp, expected_status=201)
        events = api.list_price_events(product["id"], ADMIN).json()["data"]
        assert len(events) == 2
