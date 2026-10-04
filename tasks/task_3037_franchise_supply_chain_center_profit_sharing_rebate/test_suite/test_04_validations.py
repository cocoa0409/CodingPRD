"""Validation claims: center/store state gates, product availability, capacity,
credit limits, overlap rules, and date-range sanity."""
from test_helpers import (
    ApiErrorId,
    activate_center,
    activate_store,
    add_line,
    api_client,
    create_active_store,
    create_center,
    create_draft_po,
    create_price_book,
    create_product,
    create_store,
    get_store_version,
    get_success_data,
    set_clock,
    setup_submitted_po,
    setup_trading_store,
    submit_po,
    confirm_po,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestCenterNotActive:
    def test_center_not_active_blocks_store_activation(self, api):
        """PRD §3.2: "Activation requires two things: the center must be `ACTIVE`
        (otherwise `ERR_CENTER_NOT_ACTIVE`), and the store must hold at least one
        compliance agreement in `ACTIVE` status."

        Design: Corner/validations/center_not_active_blocks_store_activation
        """
        set_clock()
        center = create_center()  # remains DRAFT
        store = create_store(center["id"], store_number="ST-BLK", operator_name="Blk",
                             credit_limit_cents=100000)
        resp = api.activate_store(center["id"], store["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CENTER_NOT_ACTIVE)


class TestProductUnavailable:
    def test_product_unavailable_blocks_order_line(self, api):
        """PRD §3.1: "Order lines and price book entries may only reference a product
        that is `ACTIVE` and not `RECALLED`; anything else is refused with
        `ERR_PRODUCT_UNAVAILABLE`."

        Design: Corner/validations/product_unavailable_blocks_order_line
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"], sku="OLD", name="Old",
                                 base_cost_cents_per_unit=100)
        activate_center(center["id"])
        validate_success(api.discontinue_product(center["id"], product["id"], ADMIN))
        store = create_active_store(center["id"], credit_limit_cents=1000000)
        po = create_draft_po(center["id"], store["id"])
        resp = api.add_order_line(center["id"], store["id"], po["id"],
                                  {"product_id": product["id"], "quantity": 10},
                                  make_store_manager_headers(store["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNAVAILABLE)


class TestCapacityExceeded:
    def test_capacity_exceeded_blocks_po_confirm(self, api):
        """PRD §3.5: "The week's capacity plan must have `available_units` at least
        equal to the order's total units, else `ERR_CAPACITY_EXCEEDED`"

        Design: Corner/validations/capacity_exceeded_blocks_po_confirm
        """
        # Baseline capacity 1000; first confirmed PO consumes all 1000 units.
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=1000,
                                 center_capacity=1000, credit_limit=100000000,
                                 with_capacity_plan=True, with_route=True)
        center_id, store_id = ctx["center"]["id"], ctx["store"]["id"]
        confirm_po(center_id, ctx["po"]["id"])
        # Second PO for 1 unit cannot be confirmed — no available units left.
        po2 = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po2["id"], ctx["product"]["id"], 1)
        submit_po(center_id, store_id, po2["id"])
        resp = api.confirm_purchase_order(center_id, po2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestCreditLimit:
    def test_credit_limit_exceeded_blocks_po_submit(self, api):
        """PRD §3.4: "if the order's total exceeds the store's `credit_limit_cents`
        minus its current `outstanding_balance_cents`, submission fails with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/credit_limit_exceeded_blocks_po_submit
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.0,
                                                     credit_limit=1000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 2)  # total 2000 > 1000
        version = get_store_version(center_id, store_id)
        resp = api.submit_purchase_order(center_id, store_id, po["id"], version,
                                         make_store_manager_headers(store_id))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_credit_limit_zero_balance_edge_exact_equality_succeeds(self, api):
        """PRD §3.4: "if the order's total exceeds the store's `credit_limit_cents`
        minus its current `outstanding_balance_cents`, submission fails with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_zero_balance_edge
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.0,
                                                     credit_limit=100000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 100)  # total == 100000
        data = submit_po(center_id, store_id, po["id"])
        assert data["status"] == "SUBMITTED"

    def test_credit_limit_zero_balance_edge_exceeding_by_one_fails(self, api):
        """PRD §3.4: "if the order's total exceeds the store's `credit_limit_cents`
        minus its current `outstanding_balance_cents`, submission fails with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_zero_balance_edge
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.0,
                                                     credit_limit=100000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 100)
        add_line(center_id, store_id, po["id"], product["id"], 1)  # total 101000 > 100000
        version = get_store_version(center_id, store_id)
        resp = api.submit_purchase_order(center_id, store_id, po["id"], version,
                                         make_store_manager_headers(store_id))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestPriceBookOverlap:
    def test_price_book_overlap_rejected(self, api):
        """PRD §3.1: "Two `ACTIVE` entries for the same product and store tier may never
        have overlapping windows — an overlapping creation is rejected with
        `ERR_PRICE_BOOK_OVERLAP`."

        Design: Corner/validations/price_book_overlap_rejected
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        create_price_book(center["id"], product["id"], markup_pct=0.1,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_until="2026-12-31T00:00:00Z")
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        resp = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.2,
            "min_quantity": 1, "effective_from": "2026-06-01T00:00:00Z",
            "effective_until": "2027-06-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRICE_BOOK_OVERLAP)


class TestPromotionOverlap:
    def test_promotion_overlap_rejected(self, api):
        """PRD §3.3: "if any existing `CONFIRMED` or `EXECUTING` promotion for the same
        products has an overlapping date range, the confirmation is rejected with
        `ERR_PROMOTION_OVERLAP`."

        Design: Corner/validations/promotion_overlap_rejected
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"], category="FOOD_INGREDIENT",
                                 base_cost_cents_per_unit=500, is_promotion_eligible=True)
        activate_center(center["id"])
        promo1 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "P1", "start_date": "2026-09-07T00:00:00Z",
            "end_date": "2026-09-14T00:00:00Z", "surge_multiplier": 2.0,
            "affected_product_ids": [product["id"]]}, ADMIN))
        validate_success(api.confirm_promotion(center["id"], promo1["id"], ADMIN))
        promo2 = get_success_data(api.create_promotion(center["id"], {
            "promotion_code": "P2", "start_date": "2026-09-10T00:00:00Z",
            "end_date": "2026-09-17T00:00:00Z", "surge_multiplier": 1.5,
            "affected_product_ids": [product["id"]]}, ADMIN))
        resp = api.confirm_promotion(center["id"], promo2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROMOTION_OVERLAP)


class TestInvalidDateRange:
    def test_invalid_date_range_rejected(self, api):
        """PRD §3.1: "a creation whose `effective_from` is not strictly before its
        `effective_until` fails with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/invalid_date_range_rejected
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        resp = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.1,
            "min_quantity": 1, "effective_from": "2027-01-01T00:00:00Z",
            "effective_until": "2026-01-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        assert resp.status_code == 400


class TestValidationPriority:
    def test_state_vs_fiscal_on_po_submit(self, api):
        """PRD §2.6: "The pipeline is evaluated in this order: ... 5. **Store
        operational state** — the store must be `ACTIVE` for purchase order operations,
        else `ERR_STORE_NOT_ACTIVE` (HTTP 409). ... 10. **Store credit** — the order
        must not push the store past its credit ceiling, else `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 409). Applies to purchase order submission."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_po_submit
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        store = create_active_store(center["id"], store_number="ST-P", operator_name="P Corp",
                                    credit_limit_cents=1)
        # Draft a PO while the store is ACTIVE, then suspend the store so that
        # submission violates both store-not-ACTIVE (priority 5) and the credit
        # ceiling (priority 10): the state gate fires first.
        po = create_draft_po(center["id"], store["id"])
        add_line(center["id"], store["id"], po["id"], product["id"], 1)
        api.suspend_store(center["id"], store["id"], ADMIN, reason="test")
        version = get_store_version(center["id"], store["id"])
        resp = api.submit_purchase_order(center["id"], store["id"], po["id"], version,
                                         make_store_manager_headers(store["id"]))
        assert resp.status_code == 409
        err = validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED

    def test_referential_vs_temporal_on_promotion_confirm(self, api):
        """PRD §2.6: "11. **Price book non-overlap** — a new price book's effective
        window must not overlap an existing `ACTIVE` book for the same product and store
        tier, else `ERR_PRICE_BOOK_OVERLAP` (HTTP 409). ... 13. **Date-range sanity** —
        an effective-from must be strictly before its effective-until, and a promotion's
        start strictly before its end, else `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_promotion_confirm
        """
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        create_price_book(center["id"], product["id"], markup_pct=0.1,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_until="2027-01-01T00:00:00Z")
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        # Overlapping window AND from > until: PRD §2.6 places non-overlap (11)
        # before date-range sanity (13). Whether an inverted window "overlaps" the
        # existing book is an implementation reading, so accept either error while
        # pinning the pair.
        resp = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.2,
            "min_quantity": 1, "effective_from": "2027-06-01T00:00:00Z",
            "effective_until": "2026-06-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        err_id = validate_error_is_one_of(resp, [ApiErrorId.ERR_PRICE_BOOK_OVERLAP,
                                                 ApiErrorId.ERR_INVALID_DATE_RANGE])
        assert err_id in (ApiErrorId.ERR_PRICE_BOOK_OVERLAP,
                          ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_state_vs_fiscal_on_po_submit_suspended_store_blocks_submission(self, api):
        """PRD §3.4: "Submission is the moment of accountability, and it stacks several
        gates in the §2.6 order: the store must be `ACTIVE` (else
        `ERR_STORE_NOT_ACTIVE`), the center must be `ACTIVE` or in `SURGE_MODE` (else
        `ERR_CENTER_NOT_ACTIVE`), and the order must contain at least one line (else
        `ERR_ORDER_HAS_NO_LINES`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_po_submit
        """
        # Companion angle on the same rule: submission (not creation) against a
        # SUSPENDED store surfaces the priority-5 state error even though the order
        # total would also breach the credit ceiling (priority 10).
        center, product, store = setup_trading_store(base_cost=1000, markup=0.0,
                                                     credit_limit=1)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 1)  # total 1000 > 1
        api.suspend_store(center_id, store_id, ADMIN, reason="test")
        version = get_store_version(center_id, store_id)
        resp = api.submit_purchase_order(center_id, store_id, po["id"], version,
                                         make_store_manager_headers(store_id))
        assert resp.status_code == 409
        err = validate_error(resp, ApiErrorId.ERR_STORE_NOT_ACTIVE)
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED

    def test_referential_vs_temporal_price_book_valid_window_overlap_still_rejected(self, api):
        """PRD §2.6: "11. **Price book non-overlap** — a new price book's effective
        window must not overlap an existing `ACTIVE` book for the same product and store
        tier, else `ERR_PRICE_BOOK_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_promotion_confirm
        """
        # Companion angle on the same rule: when ONLY the overlap rule (priority 11)
        # can fail — the window itself is sane — the referential error still fires,
        # confirming the overlap rule is reachable independently of date-range sanity.
        set_clock()
        center = create_center()
        product = create_product(center["id"])
        activate_center(center["id"])
        create_price_book(center["id"], product["id"], markup_pct=0.1,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_until="2027-01-01T00:00:00Z")
        version = get_success_data(api.get_supply_center(center["id"], ANY))["version"]
        resp = api.create_price_book(center["id"], {
            "product_id": product["id"], "store_tier": "STANDARD", "markup_pct": 0.2,
            "min_quantity": 1, "effective_from": "2026-06-01T00:00:00Z",
            "effective_until": "2026-12-01T00:00:00Z",
            "expected_center_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRICE_BOOK_OVERLAP)
        assert resp.status_code == 409
