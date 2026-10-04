"""Order lifecycle: confirm gates, amendments under OCC, terminal lockdown."""
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
    create_retail_quote,
    create_member_quote,
    add_line,
    confirm_order,
    read_order,
    set_clock,
    run_daily_cycle,
    extend_quote_via_consultation,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]


class TestOrderCreation:

    def test_order_create_computed_fields_initialized(self, api):
        """PRD §3.4: "The new order enters in `QUOTE` with `quote_expires_at` set to 14 days after its creation time and `consultation_extensions_used` at zero."
        PRD §3.4: "all of its computed money fields — `quote_total_cents`, `subtotal_cents`, `white_glove_fee_cents`, `total_cents`, `deposit_due_cents`, `deposit_paid_cents`, `cancel_refund_cents` — start at zero"
        PRD §2.7: "Every other order (a retail guest order with neither customer reference, or a member order whose member has dropped to `LAPSED` or a cancelled state) is priced `RETAIL`."

        Design: Corner/entities/order_create_computed_fields_initialized
        """
        gallery = setup_gallery(name="Gallery CE")
        order = validate_success(
            api.create_order({"gallery_id": gallery["id"]}, ASSOCIATE), expected_status=201
        )
        assert order["status"] == "QUOTE"
        assert order["quote_expires_at"] == "2026-09-15T00:00:00.000Z"
        assert order["total_cents"] == 0
        assert order["subtotal_cents"] == 0
        assert order["deposit_due_cents"] == 0
        assert order["pricing_tier"] == "RETAIL"
        assert order["consultation_extensions_used"] == 0

    def test_order_get_missing_returns_not_found(self, api):
        """PRD §2.9: "a line operation against a non-existent order fails with `ERR_ORDER_NOT_FOUND` before the line id is examined at all"
        PRD §5: "`ERR_ORDER_NOT_FOUND` | 404 Not Found"

        Design: Corner/entities/order_get_missing_returns_not_found
        """
        resp = api.get_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


class TestConfirmGates:

    def test_confirm_zero_custom_goes_ready_for_delivery(self, api):
        """PRD §3.4: "an order with no custom lines at all skips that state and lands directly in `READY_FOR_DELIVERY`, since nothing stands between it and delivery scheduling."

        Design: Corner/state_machines/confirm_zero_custom_goes_ready_for_delivery
        """
        gallery = setup_gallery(name="Gallery T5")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert confirmed["status"] == "READY_FOR_DELIVERY"

    def test_confirm_gated_by_member_standing_grace_passes(self, api):
        """PRD §3.4: "a member order's member must be in `ACTIVE` or `GRACE` standing (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`, HTTP 409)"
        PRD §3.1: "While in `GRACE`, a member retains full member pricing — their computed `pricing_tier` is still `MEMBER`"

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_member_standing
        """
        gallery = setup_gallery(name="Gallery L")
        member = setup_member(email="m8@x.com", full_name="M Eight", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)
        # Extend the quote past the lapse instant so expiry does not mask the
        # standing check (PRD §3.6: completion extends expiry by 14 days).
        extend_quote_via_consultation(order["id"], member_id=member["id"], days=406)
        set_clock("2027-09-02T00:00:00Z")
        run_daily_cycle()

        member_at_confirm = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_at_confirm["status"] == "GRACE"

        confirmed = validate_success(api.confirm_order(order["id"], {}, headers))
        assert confirmed["status"] == "READY_FOR_DELIVERY"

    def test_confirm_rejected_when_member_lapsed(self, api):
        """PRD §3.4: "a member order's member must be in `ACTIVE` or `GRACE` standing (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_member_standing
        """
        gallery = setup_gallery(name="Gallery L2")
        member = setup_member(email="m8b@x.com", full_name="M Eight B", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)
        # Extend the quote past the lapse instant so expiry does not mask the
        # standing check (PRD §3.6: completion extends expiry by 14 days).
        extend_quote_via_consultation(order["id"], member_id=member["id"], days=448)
        set_clock("2027-10-02T00:00:00Z")
        run_daily_cycle()

        member_at_confirm = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_at_confirm["status"] == "LAPSED"

        resp = api.confirm_order(order["id"], {}, headers)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)
        assert read_order(order["id"])["status"] == "QUOTE"

    def test_confirm_empty_order_rejected(self, api):
        """PRD §3.4: "it must contain at least one line (otherwise `ERR_ORDER_EMPTY`, HTTP 422)"

        Design: Corner/validations/confirm_empty_order_rejected
        """
        gallery = setup_gallery(name="Gallery V9")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        line = add_line(order["id"], product["id"], qty=1)
        get_success_data(api.remove_order_line(order["id"], line["id"], {}, ASSOCIATE))

        resp = api.confirm_order(order["id"], {}, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY.value)

    def test_confirm_missing_deposit_rejected(self, api):
        """PRD §3.4: "If `deposit_due_cents` is greater than zero, the request must include `deposit_payment_cents` (its absence is rejected with `ERR_DEPOSIT_REQUIRED`, HTTP 422)"

        Design: Corner/validations/confirm_missing_deposit_rejected
        """
        gallery = setup_gallery(name="Gallery V7")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        resp = api.confirm_order(order["id"], {}, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED.value)

    def test_confirm_deposit_amount_mismatch_rejected(self, api):
        """PRD §3.4: "the supplied amount must equal `deposit_due_cents` exactly (a mismatch is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`, HTTP 422)"

        Design: Corner/validations/confirm_deposit_amount_mismatch_rejected
        """
        gallery = setup_gallery(name="Gallery V8")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        resp = api.confirm_order(order["id"], {"deposit_payment_cents": 40000}, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH.value)


class TestTerminalLockdown:

    def test_cancelled_order_rejects_further_line_adds(self, api):
        """PRD §3.4: "`DELIVERED` and `CANCELLED` are terminal; an order in either state cannot be cancelled, amended, or confirmed."

        Design: Corner/state_machines/cancelled_order_rejects_further_line_adds
        """
        gallery = setup_gallery(name="Gallery T1")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        get_success_data(api.cancel_order(order["id"], ASSOCIATE))

        resp = api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_rejected_trade_account_is_terminal(self, api):
        """PRD §3.2: "Rejection requires no tier and transitions `APPLIED → REJECTED`, also stamping `decided_at`; `REJECTED` is terminal."

        Design: Corner/state_machines/rejected_trade_account_is_terminal
        """
        account = validate_success(
            api.create_trade_account(
                {
                    "email": "tt@x.com",
                    "business_name": "TT",
                    "credential_document_id": "d1",
                    "license_number": "L1",
                },
                TEST_USERS["anonymous_headers"],
            ),
            expected_status=201,
        )
        get_success_data(
            api.verify_trade_account(
                account["id"], {"decision": "REJECT"}, TEST_USERS["trade_reviewer_headers"]
            )
        )
        resp = api.verify_trade_account(
            account["id"],
            {"decision": "APPROVE", "tier": "TIER_1"},
            TEST_USERS["trade_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestOccOnConfirmedOrders:

    def test_stale_version_rejected_on_confirmed_amendment(self, api):
        """PRD §2.8: "Both line-mutation operations on a `CONFIRMED` order — adding a line and removing a line — require the request to carry `expected_order_version`, a non-optional input field encoding the client's last-observed `version` of the order. If the supplied value does not match the order's current `version` — meaning another amendment has landed since the client last read the order — the mutation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied."
        PRD §3.4: "Every successful amendment re-runs the pricing engine, recomputes `deposit_due_cents`, refreshes the order's `updated_at`, and increments the order's `version` by exactly 1 — which is precisely what arms the OCC check for the next writer."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_on_confirmed_amendment
        """
        gallery = setup_gallery(name="Gallery X1")
        custom = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        stock = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], custom["id"], qty=1)
        confirmed = confirm_order(order["id"], {"deposit_payment_cents": 60000})
        observed_version = confirmed["version"]

        first = validate_success(
            api.add_order_line(
                order["id"],
                {"product_id": stock["id"], "qty": 1,
                 "expected_order_version": observed_version},
                ASSOCIATE,
            ),
            expected_status=201,
        )
        assert first["id"]

        resp = api.add_order_line(
            order["id"],
            {"product_id": stock["id"], "qty": 1,
             "expected_order_version": observed_version},
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_occ_ignored_for_quote_orders(self, api):
        """PRD §2.8: "While the order is still in `QUOTE`, the `expected_order_version` field is optional and, when present, ignored."

        Design: Corner/cross_cutting_layers/occ_ignored_for_quote_orders
        """
        gallery = setup_gallery(name="Gallery X2")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        second = validate_success(
            api.add_order_line(order["id"], {"product_id": product["id"], "qty": 2}, ASSOCIATE),
            expected_status=201,
        )
        assert second["qty"] == 2
        priced = read_order(order["id"])
        assert priced["subtotal_cents"] == 30000


class TestValidationPriorityPairs:

    def test_confirm_state_error_beats_fiscal_error(self, api):
        """PRD §2.10: "4. **State preconditions** — the transition's required from-state and standing checks (`ERR_INVALID_STATE` and its specialized forms `ERR_MEMBERSHIP_NOT_ACTIVE`, `ERR_TRADE_NOT_VERIFIED`, `ERR_LINE_NON_CANCELABLE`, `ERR_SLOT_NOT_OPEN`, `ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID`; the empty-order confirm check `ERR_ORDER_EMPTY` also belongs to this tier)."
        PRD §2.10: "8. **Fiscal business rules** — deposit presence and exact-amount checks at confirm (`ERR_DEPOSIT_REQUIRED`, `ERR_DEPOSIT_AMOUNT_MISMATCH`)."
        PRD §2.10: "A request failing multiple tiers reports the error from the earliest tier only."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_fiscal_error
        """
        gallery = setup_gallery(name="Gallery I")
        member = setup_member(email="m7@x.com", full_name="M Seven", auto_renew=False)
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)
        # Extend the quote past the lapse instant so expiry (tier 6) does not
        # mask the standing check (tier 4) — PRD §3.6 completion extends by 14d.
        extend_quote_via_consultation(order["id"], member_id=member["id"], days=448)
        set_clock("2027-10-02T00:00:00Z")
        run_daily_cycle()

        member_after = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_after["status"] == "LAPSED"

        resp = api.confirm_order(order["id"], {}, headers)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)
        assert read_order(order["id"])["status"] == "QUOTE"

    def test_referential_error_beats_temporal_error_on_line_add(self, api):
        """PRD §2.10: "5. **Referential business rules** — the referenced product exists and is orderable, fabric options match the product kind, and customer-reference exclusivity on order creation (`ERR_PRODUCT_UNAVAILABLE`, `ERR_PRODUCT_KIND_MISMATCH`)."
        PRD §2.10: "6. **Temporal business rules** — quote expiry, slot overlap, daily route capacity, and the return window (`ERR_QUOTE_EXPIRED`, `ERR_SLOT_OVERLAP`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_RETURN_WINDOW_CLOSED`)."
        PRD §2.10: "A request failing multiple tiers reports the error from the earliest tier only."

        Design: Difficulty/priority_pair_validation_conflict/add_line_referential_error_beats_temporal_error
        """
        gallery = setup_gallery(name="Gallery J")
        product = setup_product(list_price_cents=5000, line_kind="STOCK",
                                status="DISCONTINUED")
        order = create_retail_quote(gallery["id"])
        set_clock("2026-09-16T00:00:00Z")

        resp = api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNAVAILABLE.value)
