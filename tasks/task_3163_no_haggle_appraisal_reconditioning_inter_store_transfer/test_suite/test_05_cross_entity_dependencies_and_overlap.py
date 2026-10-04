"""Depth tests: cross-entity state dependencies and resource temporal overlap."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_customer_headers, make_sales_associate_headers,
    make_finance_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle_retail_listed, create_vehicle_with_active_appraisal,
    create_vehicle_appraised, create_appraisal_for, create_sale_for,
    create_sale_payload, create_transfer_request_payload,
    create_transfer_for, accept_financing_payload,
    get_vehicle_version,
    assert_appraisal, assert_transfer_request, assert_financing_application,
)


def _phx_full_staff(include_finance=False):
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    staff = {
        "manager": create_associate(store["id"], "MANAGER", "Manager One"),
        "appraiser": create_associate(store["id"], "APPRAISER", "Appraiser One"),
        "inspector": create_associate(store["id"], "INSPECTOR", "Inspector One"),
        "sales": create_associate(store["id"], "SALES", "Sales One"),
    }
    if include_finance:
        staff["finance"] = create_associate(store["id"], "FINANCE",
                                            "Finance One")
    cust = create_customer(email="c1@x.com")
    return store, staff, cust


class TestSaleRequiresAppraisalActivePair:
    def _expired_trade_in_setup(self):
        """V_A RETAIL_LISTED; V_B's appraisal ACTIVE then expired by clock."""
        store, staff, cust = _phx_full_staff()
        veh_a, _appr_a, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        veh_b, appr_b = create_vehicle_with_active_appraisal(
            store, staff, cust, vin="VBBBBBBBBBBBBBBBB",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000)
        assert appr_b["status"] == "ACTIVE"
        set_clock("2026-09-08T00:00:00Z")
        return store, staff, cust, veh_a, appr_b

    def test_expired_appraisal_blocks_sale_creation(self):
        """PRD §3.5: "When a trade-in appraisal is attached, it must be `ACTIVE`; a trade-in appraisal in `PENDING_INSPECTION`, `REDEEMED`, or `VOIDED` status is rejected with `ERR_APPRAISAL_NOT_ACTIVE`, while one already `EXPIRED` (or past `valid_until`) is rejected with `ERR_APPRAISAL_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/sale_requires_appraisal_active_pair
        """
        store, staff, cust, veh_a, appr_b = self._expired_trade_in_setup()
        resp = api_client.create_sale(
            create_sale_payload(veh_a["id"], cust["id"],
                                staff["sales"]["id"],
                                trade_in_appraisal_id=appr_b["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_EXPIRED)

    def test_clock_reaching_valid_until_marks_appraisal_expired(self):
        """PRD §3.2: "Once an appraisal is `ACTIVE`, the clock governs its end. When the logical clock reaches or passes `valid_until`, the appraisal becomes `EXPIRED`; the same `EXPIRED` outcome is applied lazily whenever the appraisal is read or a redemption is attempted at or after `valid_until`."

        Design: Difficulty/cross_entity_state_dependency/sale_requires_appraisal_active_pair
        """
        store, staff, cust, veh_a, appr_b = self._expired_trade_in_setup()
        api_client.create_sale(
            create_sale_payload(veh_a["id"], cust["id"],
                                staff["sales"]["id"],
                                trade_in_appraisal_id=appr_b["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        appr_b = get_success_data(api_client.get_appraisal(
            appr_b["id"], make_appraiser_headers(staff["appraiser"]["id"])))
        assert_appraisal(appr_b)
        assert appr_b["status"] == "EXPIRED"
        assert appr_b["valid_until"] == "2026-09-08T00:00:00Z"

        sales, meta = validate_paginated(api_client.list_sales(
            make_sales_associate_headers(staff["sales"]["id"]),
            params={"vehicle_id": veh_a["id"]}))
        assert sales == []


class TestSaleCompletionRequiresFinancingAcceptedPair:
    def _pending_financed_sale(self):
        store, staff, cust = _phx_full_staff(include_finance=True)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh_a, cust, staff["sales"])
        fin = get_success_data(api_client.submit_financing_application(
            sale["id"], make_finance_manager_headers(staff["finance"]["id"])))
        return store, staff, cust, veh_a, sale, fin

    def test_completion_blocked_until_offer_accepted(self):
        """PRD §3.5: "A `SalesAssociate` completes a `PENDING_FINANCE` sale only when its financing posture is settled: either no financing application exists for the sale (a cash deal), or the application is `ACCEPTED`; completing with an application in any other state is rejected with `ERR_FINANCING_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/sale_completion_requires_financing_accepted_pair
        """
        store, staff, cust, veh_a, sale, fin = self._pending_financed_sale()
        resp = api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_ACCEPTED)

        sale = get_success_data(api_client.get_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "PENDING_FINANCE"

    def test_accepted_offer_unblocks_completion_and_supersedes_rest(self):
        """PRD §3.6: "Acceptance moves the chosen offer to `ACCEPTED` and every other offer on the application to `SUPERSEDED`, and the application itself to `ACCEPTED`."
        PRD §3.6: "The rate per lender and tier is: `LENDER_A` offers 490, 690, or 990 for tiers one through three; `LENDER_B` offers 515, 740, or 1040; `LENDER_C` offers 540, 780, or 1090."
        PRD §3.6: "For a non-declined tier the system immediately creates the full lender panel — three `LenderOffer` rows, one each for `LENDER_A`, `LENDER_B`, and `LENDER_C`, all in `PRESENTED` status, in the same submission response; the application moves from `SUBMITTED` to `OFFERS_PRESENTED`."

        Design: Difficulty/cross_entity_state_dependency/sale_completion_requires_financing_accepted_pair
        """
        store, staff, cust, veh_a, sale, fin = self._pending_financed_sale()
        fin = get_success_data(api_client.get_financing_application(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        assert_financing_application(fin)
        assert fin["approval_tier"] == "TIER_2"
        assert fin["status"] == "OFFERS_PRESENTED"

        offers, meta = validate_paginated(api_client.list_financing_offers(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        assert len(offers) == 3
        apr_by_lender = {o["lender_code"]: o["apr_bps"] for o in offers}
        assert apr_by_lender == {"LENDER_A": 690, "LENDER_B": 740,
                                 "LENDER_C": 780}

        fin = get_success_data(api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_B"),
            make_customer_headers(cust["id"])))
        assert fin["status"] == "ACCEPTED"

        offers, meta = validate_paginated(api_client.list_financing_offers(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        status_by_lender = {o["lender_code"]: o["offer_status"]
                            for o in offers}
        assert status_by_lender == {"LENDER_A": "SUPERSEDED",
                                    "LENDER_B": "ACCEPTED",
                                    "LENDER_C": "SUPERSEDED"}

        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "COMPLETED"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_a["lifecycle_status"] == "SOLD"


class TestTransferHoldHalfOpenExclusion:
    def _delivered_hold_setup(self):
        """CUST2's transfer PHX->DAL paid, shipped, delivered; hold until
        2026-09-08T00:00:00Z."""
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        dal = create_store(store_code="DAL-01", display_name="Dallas",
                           region="CENTRAL")
        staff = {
            "manager": create_associate(store["id"], "MANAGER", "Manager One"),
            "appraiser": create_associate(store["id"], "APPRAISER",
                                          "Appraiser One"),
            "inspector": create_associate(store["id"], "INSPECTOR",
                                          "Inspector One"),
        }
        mgr2 = create_associate(dal["id"], "MANAGER", "Manager Two")
        cust1 = create_customer(email="c1@x.com")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        tr1 = create_transfer_for(veh_a, cust2, dal["id"])
        get_success_data(api_client.pay_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))
        get_success_data(api_client.ship_transfer_request(
            tr1["id"], make_store_manager_headers(staff["manager"]["id"])))
        tr1 = get_success_data(api_client.deliver_transfer_request(
            tr1["id"], make_store_manager_headers(mgr2["id"])))
        return store, dal, staff, mgr2, cust1, cust2, veh_a, tr1

    def test_overlapping_request_during_hold_rejected(self):
        """PRD §3.4: "The vehicle must be `RETAIL_LISTED` — a request against a vehicle in any other lifecycle state is rejected with `ERR_VEHICLE_NOT_LISTED` — and its `hold_status` must be `NONE`; a request against an already-held vehicle is rejected with `ERR_VEHICLE_ALREADY_HELD`."

        Design: Difficulty/resource_temporal_overlap/transfer_hold_half_open_exclusion
        """
        (store, dal, staff, mgr2, cust1, cust2, veh_a, tr1) = (
            self._delivered_hold_setup())
        version = get_vehicle_version(veh_a["id"],
                                      make_customer_headers(cust1["id"]))
        resp = api_client.create_transfer_request(
            create_transfer_request_payload(veh_a["id"], cust1["id"],
                                            store["id"], version),
            make_customer_headers(cust1["id"]))
        validate_error(resp, ApiErrorId.ERR_VEHICLE_ALREADY_HELD)

    def test_request_at_expiry_instant_succeeds_after_auto_expiry(self):
        """PRD §2.5: "Advancing the clock re-evaluates every pending automatic transition: an `ACTIVE` appraisal whose `valid_until` has passed becomes `EXPIRED`; a `DELIVERED` transfer request whose `hold_expires_at` has passed becomes `HOLD_EXPIRED`; and a financing application whose offers have outlived their validity window becomes `EXPIRED`."
        PRD §3.4: "If the clock reaches `hold_expires_at` first, the request becomes `HOLD_EXPIRED`: the hold is cleared, the vehicle's `version` increments, the vehicle — still `RETAIL_LISTED` — returns to the open market at the destination store, and the shipping fee is **not** refunded."
        PRD §3.4: "Creation snapshots the vehicle's `current_store_id` into `from_store_id`, computes `shipping_fee_cents` (immutable thereafter), sets the vehicle's `hold_status` to `TRANSFER_HOLD` — removing it from open-market sale eligibility — and increments the vehicle's `version`."

        Design: Difficulty/resource_temporal_overlap/transfer_hold_half_open_exclusion
        """
        (store, dal, staff, mgr2, cust1, cust2, veh_a, tr1) = (
            self._delivered_hold_setup())
        set_clock("2026-09-08T00:00:00Z")

        tr1 = get_success_data(api_client.get_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))
        assert tr1["status"] == "HOLD_EXPIRED"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_customer_headers(cust1["id"])))
        assert veh_a["hold_status"] == "NONE"

        tr2 = create_transfer_for(veh_a, cust1, store["id"])
        assert_transfer_request(tr2)
        assert tr2["from_store_id"] == dal["id"]
        assert tr2["status"] == "REQUESTED"

        entries, meta = validate_paginated(api_client.list_ledger_entries(
            dal["id"], make_store_manager_headers(mgr2["id"]),
            params={"limit": 100}))
        refunds = [e for e in entries
                   if e["ref_id"] == tr1["id"]
                   and e["entry_kind"] == "TRANSFER_FEE_REFUND"]
        assert refunds == []


class TestAppraisalValiditySingleActivePerVehicle:
    def _vehicle_with_pending_appraisal(self):
        store, staff, cust1 = _phx_full_staff()
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, appr1 = create_vehicle_appraised(store, staff, cust1,
                                                vin="VAAAAAAAAAAAAAAAA")
        return store, staff, cust1, cust2, veh_a, appr1

    def test_second_appraisal_during_validity_window_rejected(self):
        """PRD §3.1: "A vehicle already in `APPRAISED` whose prior appraisal has reached a terminal state and which never entered inspection may be re-appraised; but if any non-terminal appraisal (one in `PENDING_INSPECTION` or `ACTIVE`) still exists for the vehicle, a second appraisal is rejected with `ERR_CROSS_ENTITY_STATE`."

        Design: Difficulty/resource_temporal_overlap/appraisal_validity_single_active_per_vehicle
        """
        store, staff, cust1, cust2, veh_a, appr1 = (
            self._vehicle_with_pending_appraisal())
        resp = api_client.create_appraisal(
            {"vehicle_id": veh_a["id"], "customer_id": cust2["id"],
             "appraiser_id": staff["appraiser"]["id"]},
            make_appraiser_headers(staff["appraiser"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)

        appraisals, meta = validate_paginated(
            api_client.list_vehicle_appraisals(
                veh_a["id"],
                make_appraiser_headers(staff["appraiser"]["id"])))
        assert len(appraisals) == 1
        assert appraisals[0]["id"] == appr1["id"]

    def test_lone_appraisal_keeps_its_provisional_offer(self):
        """PRD §3.1: "The provisional offer starts from the vehicle's `book_value_cents`, subtracts eight hundred dollars (`80000` cents) for each full model-year of age (the age in years being the current logical year minus `model_year`, never less than zero), and subtracts fifteen dollars (`1500` cents) for each whole block of one thousand miles by which the odometer exceeds an allowance of twelve thousand miles per year of age (the excess itself never less than zero)."
        PRD §3.1: "A vehicle already in `APPRAISED` whose prior appraisal has reached a terminal state and which never entered inspection may be re-appraised; but if any non-terminal appraisal (one in `PENDING_INSPECTION` or `ACTIVE`) still exists for the vehicle, a second appraisal is rejected with `ERR_CROSS_ENTITY_STATE`."

        Design: Difficulty/resource_temporal_overlap/appraisal_validity_single_active_per_vehicle
        """
        store, staff, cust1, cust2, veh_a, appr1 = (
            self._vehicle_with_pending_appraisal())
        api_client.create_appraisal(
            {"vehicle_id": veh_a["id"], "customer_id": cust2["id"],
             "appraiser_id": staff["appraiser"]["id"]},
            make_appraiser_headers(staff["appraiser"]["id"]))
        appr1 = get_success_data(api_client.get_appraisal(
            appr1["id"], make_appraiser_headers(staff["appraiser"]["id"])))
        assert_appraisal(appr1)
        assert appr1["status"] == "PENDING_INSPECTION"
        assert appr1["provisional_offer_cents"] == 1680000
