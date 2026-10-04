"""Second passes for depth instances: isolated single-violation error paths."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_delivered_stock_order,
    create_retail_quote,
    create_member_quote,
    add_line,
    confirm_order,
    read_order,
    set_clock,
    run_daily_cycle,
    create_return_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]


class TestConfirmFiscalTierAlone:

    def test_confirm_deposit_required_fires_alone_when_standing_ok(self, api):
        """PRD §3.4: "If `deposit_due_cents` is greater than zero, the request must include `deposit_payment_cents` (its absence is rejected with `ERR_DEPOSIT_REQUIRED`, HTTP 422)"
        PRD §2.10: "A request failing multiple tiers reports the error from the earliest tier only."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_fiscal_error
        """
        gallery = setup_gallery(name="Gallery I2")
        member = setup_member(email="m7b@x.com", full_name="M Seven B")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)

        # Member is ACTIVE and the quote is fresh: only the fiscal tier can fail.
        resp = api.confirm_order(order["id"], {}, headers)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED.value)
        assert read_order(order["id"])["status"] == "QUOTE"


class TestQuoteExpiryAlone:

    def test_expired_quote_rejects_line_add_with_active_product(self, api):
        """PRD §2.10: "6. **Temporal business rules** — quote expiry, slot overlap, daily route capacity, and the return window (`ERR_QUOTE_EXPIRED`, `ERR_SLOT_OVERLAP`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_RETURN_WINDOW_CLOSED`)."
        PRD §3.4: "the clock must be at or before `quote_expires_at` (otherwise `ERR_QUOTE_EXPIRED`, HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/add_line_referential_error_beats_temporal_error
        """
        gallery = setup_gallery(name="Gallery J2")
        product = setup_product(list_price_cents=5000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        set_clock("2026-09-16T00:00:00Z")

        # The product is ACTIVE: only the temporal tier can fail.
        resp = api.add_order_line(
            order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED.value)


class TestReturnDeliveryGate:

    def test_return_accepted_once_order_delivered(self, api):
        """PRD §3.8: "The request is valid only when the order is `DELIVERED` (otherwise `ERR_INVALID_STATE`)"
        PRD §3.7: "The first appointment of an order to reach `COMPLETED` delivers the order: the order moves from `READY_FOR_DELIVERY` to its terminal `DELIVERED` state"

        Design: Difficulty/cross_entity_state_dependency/return_gated_by_completed_delivery
        """
        setup = setup_delivered_stock_order(list_price_cents=50000,
                                            delivery_date="2026-09-05")
        order = setup["order"]
        line = setup["line"]
        assert order["status"] == "DELIVERED"

        ret = validate_success(
            api.create_return(create_return_payload(order["id"], [line["id"]]), ASSOCIATE),
            expected_status=201,
        )
        assert ret["status"] == "REQUESTED"
        assert ret["order_id"] == order["id"]
