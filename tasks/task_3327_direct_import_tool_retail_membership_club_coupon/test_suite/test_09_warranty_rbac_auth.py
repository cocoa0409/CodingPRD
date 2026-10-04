"""Warranty claim adjudication, appeal cycle, claim rate, RBAC and auth
(PRD §2.1, §2.6, §2.9, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_active_item,
    create_coupon_payload,
    get_success_data,
    make_completed_warranty_sale,
    make_customer,
    make_customer_headers,
    make_denied_claim,
    make_open_sale,
    make_store,
    make_claim,
    add_line,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

SC = TEST_USERS["store_clerk_headers"]
WA = TEST_USERS["warranty_adjuster_headers"]
MM = TEST_USERS["marketing_manager_headers"]
PM = TEST_USERS["purchasing_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


class TestWarrantyClaimAppealCycle:

    def test_warranty_claim_deny_appeal_cycle(self, api):
        """PRD §3.9: "A denied claim may be appealed by the customer back to
        `UNDER_REVIEW`, but only within two limits: `appeal_count` must still
        be below 1 — appealing a claim that has already been appealed once is
        rejected with `ERR_CLAIM_APPEAL_EXHAUSTED`" and "the `UNDER_REVIEW` →
        `DENIED` → `UNDER_REVIEW` cycle is allowed exactly once."

        Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_cycle
        """
        item = create_active_item(sku="W1", unit_retail_cents=6000,
                                  member_price_cents=5500,
                                  floor_margin_pct=0.10)
        store = make_store([item["id"]], store_code="ST4")
        cust = make_customer(email="c4@x.com")
        sale, _merch, wline = make_completed_warranty_sale(
            store["id"], cust["id"], item["id"], warranty_price_cents=1500)
        claim = make_claim(wline["id"], 800, reason="motor failure")
        get_success_data(api.start_review_claim(claim["id"], WA))
        get_success_data(api.deny_claim(claim["id"], WA))

        appealed = validate_success(api.appeal_claim(
            claim["id"], make_customer_headers(cust["id"])))
        assert appealed["status"] == "UNDER_REVIEW"
        assert appealed["appeal_count"] == 1

        get_success_data(api.deny_claim(claim["id"], WA))
        resp = api.appeal_claim(claim["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_APPEAL_EXHAUSTED)
        claim_after = validate_success(api.get_warranty_claim(claim["id"], WA))
        assert claim_after["status"] == "DENIED"

    def test_warranty_claim_appeal_reopens_exactly_once(self, api):
        """PRD §3.9: "A successful appeal increments `appeal_count`; the
        `UNDER_REVIEW` → `DENIED` → `UNDER_REVIEW` cycle is allowed exactly
        once."

        Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_cycle
        """
        item = create_active_item(sku="W1B")
        store = make_store([item["id"]])
        cust = make_customer()
        _sale, _m, wline = make_completed_warranty_sale(
            store["id"], cust["id"], item["id"], warranty_price_cents=800)
        claim = make_denied_claim(wline["id"], 500)
        appealed = validate_success(api.appeal_claim(
            claim["id"], make_customer_headers(cust["id"])))
        assert appealed["appeal_count"] == 1
        # After the single appeal the claim can still be approved/settled.
        get_success_data(api.approve_claim(claim["id"], WA))
        settled = validate_success(api.settle_claim(claim["id"], 500, WA))
        assert settled["status"] == "SETTLED"


class TestClaimAppealFinality:

    def test_err_claim_final_above_threshold(self, api):
        """PRD §3.9: "`claim_amount_cents` must be at most 100000 cents,
        because claims above 1000 dollars are final on first denial, rejected
        with `ERR_CLAIM_FINAL`."

        Design: Corner/errors/err_claim_final_above_threshold
        """
        item = create_active_item(sku="ER3", unit_retail_cents=200000,
                                  member_price_cents=190000,
                                  floor_margin_pct=0.10)
        store = make_store([item["id"]], store_code="ST-ER3")
        cust = make_customer(email="er3@x.com")
        _sale, _m, wline = make_completed_warranty_sale(
            store["id"], cust["id"], item["id"], warranty_price_cents=5000,
            warranty_qty=2)
        big = make_denied_claim(wline["id"], 100001)
        edge = make_denied_claim(wline["id"], 100000)

        resp = api.appeal_claim(big["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_FINAL)
        appealed = validate_success(api.appeal_claim(
            edge["id"], make_customer_headers(cust["id"])))
        assert appealed["status"] == "UNDER_REVIEW"
        assert appealed["appeal_count"] == 1


class TestWarrantyClaimRate:

    def test_warranty_claim_rate_input_set(self, api):
        """PRD §3.9: "the numerator counts WarrantyClaim rows whose sale line's
        covered item is this item and whose status is `FILED`, `UNDER_REVIEW`,
        `APPROVED`, or `SETTLED`; the denominator counts SaleLine rows of this
        item on sales in `COMPLETED` or `RETURNED_PARTIAL`."

        Design: Corner/calculations/warranty_claim_rate_input_set
        """
        item = create_active_item(sku="CALC5", unit_retail_cents=6000,
                                  member_price_cents=5500)
        store = make_store([item["id"]], store_code="ST-C5")
        cust = make_customer(email="calc6@x.com")
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        from test_helpers import add_warranty_line
        wline = add_warranty_line(sale["id"], item["id"], item["id"], 1000, 2)
        validate_success(api.complete_sale(sale["id"], {}, SC))

        claim1 = make_claim(wline["id"], 500, reason="r1")
        get_success_data(api.start_review_claim(claim1["id"], WA))
        get_success_data(api.deny_claim(claim1["id"], WA))
        # DENIED is terminal (PRD §3.9), so a distinct claim supplies the
        # counted status; the warranty line is excluded from the denominator,
        # which is the 1 merchandise line.
        make_claim(wline["id"], 700, reason="r2")  # FILED

        item_after = validate_success(api.get_item(item["id"], PM))
        # 1 non-denied claim / 1 merchandise line = 1.0
        assert float(item_after["warranty_claim_rate"]) == 1.0

    def test_warranty_claim_rate_zero_before_claims(self, api):
        """PRD §3.1: "a `warranty_claim_rate` of zero" and PRD §3.9: "The rate
        is the numerator divided by the denominator, or zero when the
        denominator is zero"

        Design: Corner/calculations/warranty_claim_rate_input_set
        """
        item = create_active_item(sku="CALC5B")
        fetched = validate_success(api.get_item(item["id"], PM))
        assert float(fetched["warranty_claim_rate"]) == 0.0


class TestRbacAndAuth:

    def test_store_clerk_cannot_manage_coupons(self, api, store_clerk_headers):
        """PRD §2.1: "an authenticated caller whose role is not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD §4:
        POST /coupons is authorized for `MarketingManager` only.

        Design: Corner/roles/store_clerk_cannot_manage_coupons
        """
        resp = api.create_coupon(
            create_coupon_payload(code="RBAC1", per_customer_limit=1,
                                  budget_cents=1000),
            store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_logistics_cannot_clear_customs(
            self, api, logistics_coordinator_headers):
        """PRD §2.1: "an authenticated caller whose role is not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD §4:
        POST /containers/{containerId}/clear-customs is authorized for
        `ComplianceOfficer` only.

        Design: Corner/roles/logistics_cannot_clear_customs
        """
        from test_helpers import (create_container_payload, make_issued_po)
        item = create_active_item(sku="RB2")
        po = make_issued_po(item["id"], 1, 500)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1,
                                     container_number="C-RB2"),
            logistics_coordinator_headers))
        get_success_data(api.depart_container(cont["id"], logistics_coordinator_headers))
        get_success_data(api.arrive_port_container(cont["id"], logistics_coordinator_headers))
        resp = api.clear_customs_container(cont["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        cont_after = validate_success(
            api.get_container(cont["id"], logistics_coordinator_headers))
        assert cont_after["status"] == "AT_PORT"

    def test_customer_appeal_is_customer_exclusive(
            self, api, warranty_adjuster_headers):
        """PRD §2.1: "an authenticated caller whose role is not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD §4:
        POST /warranty-claims/{claimId}/appeal is authorized for `Customer`
        only.

        Design: Corner/roles/customer_appeal_is_customer_exclusive
        """
        item = create_active_item(sku="RB3", unit_retail_cents=5000,
                                  member_price_cents=5000)
        store = make_store([item["id"]], store_code="ST-RB3")
        cust = make_customer(email="rb3@x.com")
        _sale, _m, wline = make_completed_warranty_sale(
            store["id"], cust["id"], item["id"], warranty_price_cents=800)
        claim = make_denied_claim(wline["id"], 500)
        resp = api.appeal_claim(claim["id"], warranty_adjuster_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAuthAndExistence:

    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.list_items({"X-User-ID": "someone"})  # no role header
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_existence_before_state_left_to_right(self, api, store_clerk_headers):
        """PRD §2.6: "Path identifiers are validated in strict left-to-right
        order: the first identifier in the URL hierarchy that does not
        correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/validations/existence_before_state_left_to_right
        """
        resp = api.complete_sale(NON_EXISTENT_UUID, {}, store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSaleCompletionBasics:

    def test_sale_complete_empty_rejected(self, api, store_clerk_headers):
        """PRD §3.7: "Completing an `OPEN` sale requires: at least one line,
        otherwise `ERR_EMPTY_SALE`"

        Design: Corner/endpoints/sale_complete_empty_rejected
        """
        store = make_store([], store_code="ST-EP2", receiving_capacity_units=100)
        cust = make_customer(email="ep2@x.com")
        sale = make_open_sale(store["id"], cust["id"])
        resp = api.complete_sale(sale["id"], {}, store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_SALE)
