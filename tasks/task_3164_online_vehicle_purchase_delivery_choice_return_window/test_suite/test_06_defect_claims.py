"""Tests for defect claims and warranty authorizations (PRD §3.8)."""
from test_helpers import (
    api_client,
    TEST_USERS,
    make_customer_headers,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_customer,
    create_listed_vehicle,
    create_completed_order,
    create_returned_order_with_transit,
)


class TestDefectClaimReauthorization:
    """Claim survives voided authorization and can be re-authorized (PRD §3.8)."""

    def test_void_then_reauthorize(self, api):
        """PRD §3.8: "An authorization in ISSUED may also be voided — the void request
        carries a reason such as the shop closing or the customer declining the repair —
        moving it to VOIDED while the claim remains AUTHORIZED and may be re-authorized
        with a fresh estimate."

        Design: Difficulty/non_linear_state_machine/defect_claim_review_cycle_and_reauthorization_loop
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=25100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "transmission slip", "defect_area": "transmission", "current_mileage": 25200},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        auth1_resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 120000}, TEST_USERS["warranty_admin_headers"]
        )
        auth1 = get_success_data(auth1_resp)
        api.void_repair_authorization(
            auth1["id"], {"reason": "shop closed"}, TEST_USERS["warranty_admin_headers"]
        )
        auth1_after = get_success_data(
            api.get_repair_authorization(auth1["id"], TEST_USERS["warranty_admin_headers"])
        )
        assert auth1_after["status"] == "VOIDED"
        auth2_resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 150000}, TEST_USERS["warranty_admin_headers"]
        )
        auth2 = validate_success(auth2_resp, 200)
        claim_after = get_success_data(api.get_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"]))
        assert claim_after["status"] == "AUTHORIZED"
        assert auth2["status"] == "ISSUED"
        assert auth2["covered_amount_cents"] == 150000
        assert auth2["deductible_cents"] == 0

    def test_reauthorization_creates_new_authorization(self, api):
        """PRD §3.8: "the claim remains AUTHORIZED and may be re-authorized with a fresh
        estimate." A second authorize call creates a new RepairAuthorization in ISSUED.

        Design: Difficulty/non_linear_state_machine/defect_claim_review_cycle_and_reauthorization_loop
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=25100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "transmission slip", "defect_area": "transmission", "current_mileage": 25200},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        auth1 = get_success_data(
            api.authorize_defect_claim(claim["id"], {"estimate_cents": 120000}, TEST_USERS["warranty_admin_headers"])
        )
        api.void_repair_authorization(auth1["id"], {"reason": "shop closed"}, TEST_USERS["warranty_admin_headers"])
        auth2 = get_success_data(
            api.authorize_defect_claim(claim["id"], {"estimate_cents": 150000}, TEST_USERS["warranty_admin_headers"])
        )
        assert auth2["id"] != auth1["id"]
        assert auth2["status"] == "ISSUED"
        assert auth2["covered_amount_cents"] == 150000
        assert auth2["deductible_cents"] == 0


class TestWarrantyCoverageCap:
    """Warranty cap split (PRD §3.8)."""

    def test_estimate_above_cap_splits_correctly(self, api):
        """PRD §3.8: "its covered_amount_cents is the smaller of estimate_cents and the
        warranty claim cap of 400000 cents; and its deductible_cents is the remainder of
        the estimate above the covered amount — so covered amount plus deductible always
        equals the estimate."

        Design: Corner/calculations/warranty_coverage_cap_split
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=5100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "engine knock", "defect_area": "engine", "current_mileage": 5200},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 550000}, TEST_USERS["warranty_admin_headers"]
        )
        auth = validate_success(resp, 200)
        assert auth["covered_amount_cents"] == 400000
        assert auth["deductible_cents"] == 150000
        assert auth["covered_amount_cents"] + auth["deductible_cents"] == 550000
        claim_after = get_success_data(api.get_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"]))
        assert claim_after["status"] == "AUTHORIZED"
        assert claim_after["authorized_estimate_cents"] == 550000


class TestClaimOnReturnedOrderRejected:
    """Filing a claim on a RETURN_COMPLETED order is rejected (PRD §3.8)."""

    def test_claim_on_returned_order_rejected(self, api):
        """PRD §3.8: "After delivery, the customer may file a defect claim against a
        completed order — claims exist only post-sale and before any return, so filing
        against an order not in COMPLETED is rejected with ERR_INVALID_STATE."

        Design: Difficulty/cross_entity_state_dependency/claim_authorize_requires_order_completed
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=9100)
        api.return_order(order["id"], {"return_mileage": 9200, "reason_code": "X"}, cust_headers)
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-02T13:00:00Z", "end_at": "2026-09-02T14:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        api.create_center(
            {"name": "ATL RC 2", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        api.return_intake(order["id"], {"inspection_result": "ACCEPT", "excess_wear": False}, advocate)
        resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "late claim", "defect_area": "door", "current_mileage": 9200},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        claims = get_success_data(api.get_order_defect_claims(order["id"], cust_headers))
        assert claims == []

    def test_authorize_on_returned_order_claim_rejected(self, api):
        """PRD §3.8: "The order must still be COMPLETED — claims on returned or cancelled
        orders cannot be authorized." PRD §3.7: "Any defect claims on the order still in
        FILED or UNDER_REVIEW are auto-denied with review_note set to 'order returned'."

        Design: Difficulty/cross_entity_state_dependency/claim_authorize_requires_order_completed
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=9100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "rattle", "defect_area": "dashboard", "current_mileage": 9150},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        api.return_order(order["id"], {"return_mileage": 9200, "reason_code": "X"}, cust_headers)
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-02T13:00:00Z", "end_at": "2026-09-02T14:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        api.create_center(
            {"name": "ATL RC 3", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        api.return_intake(order["id"], {"inspection_result": "ACCEPT", "excess_wear": False}, advocate)
        resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 100000}, TEST_USERS["warranty_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestDisclosedDefectSafety:
    """Disclosed defects are never covered (PRD §3.8)."""

    def test_disclosed_defect_authorize_rejected_even_past_window(self, api):
        """PRD §3.8: "The claim's disclosure_flag must be UNDISCLOSED; a defect whose area
        was disclosed at sale is never covered, and authorization is rejected with
        ERR_DEFECT_DISCLOSED."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_beats_warranty_window_temporal
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        api.create_annotation(
            vehicle["id"],
            {"area": "hood", "severity": "MODERATE", "deduction_cents": 80000, "image_count": 3},
            TEST_USERS["recon_operator_headers"],
        )
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=40100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "hood dent worsened", "defect_area": "hood", "current_mileage": 40200},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        api.set_clock("2026-12-30T00:00:00Z", TEST_USERS["platform_admin_headers"])
        resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 90000}, TEST_USERS["warranty_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_DISCLOSED, 422)
        claim_after = get_success_data(api.get_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"]))
        assert claim_after["status"] == "UNDER_REVIEW"
        assert claim_after["disclosure_flag"] == "DISCLOSED"

    def test_disclosed_defect_authorize_rejected_within_window(self, api):
        """PRD §3.8: "The claim's disclosure_flag must be UNDISCLOSED; a defect whose area
        was disclosed at sale is never covered, and authorization is rejected with
        ERR_DEFECT_DISCLOSED."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_beats_warranty_window_temporal
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        api.create_annotation(
            vehicle["id"],
            {"area": "hood", "severity": "MODERATE", "deduction_cents": 80000, "image_count": 3},
            TEST_USERS["recon_operator_headers"],
        )
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=40100)
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "hood dent worsened", "defect_area": "hood", "current_mileage": 40200},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        resp = api.authorize_defect_claim(
            claim["id"], {"estimate_cents": 90000}, TEST_USERS["warranty_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_DISCLOSED, 422)
        claim_after = get_success_data(api.get_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"]))
        assert claim_after["status"] == "UNDER_REVIEW"
        assert claim_after["disclosure_flag"] == "DISCLOSED"
