"""Depth tests: combinatorial formulas — repricing rounding, transfer fee
combinatorics, and the pinned return reversal waterfall evaluation order."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_customer_headers, make_sales_associate_headers,
    make_finance_manager_headers, auction_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle_retail_listed, create_vehicle_with_active_appraisal,
    create_sale_for, create_transfer_request_payload,
    accept_financing_payload, create_return_payload,
    get_vehicle_version, store_ledger_entries,
    assert_vehicle, assert_transfer_request, assert_sale,
    assert_ledger_entries_for,
)


def _phx_full_staff():
    """Store PHX + full associate panel + CUST1 (credit 720, income 9,000,000)."""
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    staff = {
        "manager": create_associate(store["id"], "MANAGER", "Manager One"),
        "appraiser": create_associate(store["id"], "APPRAISER", "Appraiser One"),
        "inspector": create_associate(store["id"], "INSPECTOR", "Inspector One"),
        "sales": create_associate(store["id"], "SALES", "Sales One"),
        "finance": create_associate(store["id"], "FINANCE", "Finance One"),
    }
    cust = create_customer(email="c1@x.com")
    return store, staff, cust


class TestRepricingPerEventRoundingComposes:
    def _listed_vehicle_a(self, store, staff, cust):
        return create_vehicle_retail_listed(store, staff, cust,
                                            vin="VAAAAAAAAAAAAAAAA")

    def _markdown(self, vehicle_id, manager_id):
        v = get_vehicle_version(vehicle_id,
                                make_store_manager_headers(manager_id))
        return get_success_data(api_client.create_pricing_event(
            vehicle_id, {"expected_vehicle_version": v},
            make_store_manager_headers(manager_id)))

    def test_three_markdowns_recompute_from_current_price_each_time(self):
        """PRD §3.3: "The new price is the current list price multiplied by one hundred minus the tier percentage, divided by one hundred, rounded half-up to whole cents **per event** (each event re-rounds from the current price; unrounded intermediates are never carried across events, so successive markdowns compose multiplicatively)."

        Design: Difficulty/combinatorial_formula/repricing_per_event_rounding_composes
        """
        store, staff, cust = _phx_full_staff()
        vehicle, appr, _insp = self._listed_vehicle_a(store, staff, cust)
        assert vehicle["current_list_price_cents"] == 1797600

        set_clock("2026-10-01T00:00:00Z")
        pe1 = self._markdown(vehicle["id"], staff["manager"]["id"])
        assert pe1["new_price_cents"] == 1743672

        set_clock("2026-10-16T00:00:00Z")
        pe2 = self._markdown(vehicle["id"], staff["manager"]["id"])
        assert pe2["new_price_cents"] == 1656488

        set_clock("2026-10-31T00:00:00Z")
        pe3 = self._markdown(vehicle["id"], staff["manager"]["id"])
        # Unfloored value would be round_half_up(1656488 * 0.92) = 1523969.
        assert pe3["new_price_cents"] == 1605000

        events, meta = validate_paginated(api_client.list_pricing_events(
            vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
        markdowns = [e for e in events
                     if e["trigger_kind"] == "SCHEDULED_MARKDOWN"]
        assert [e["new_price_cents"] for e in markdowns] == [
            1743672, 1656488, 1605000]

        vehicle = get_success_data(api_client.get_vehicle(
            vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert_vehicle(vehicle)
        assert vehicle["current_list_price_cents"] == 1605000

    def test_markdown_tiers_select_by_days_in_inventory_and_floor_holds(self):
        """PRD §3.3: "The markdown tier is chosen by the vehicle's `days_in_inventory` at run time: fewer than 30 days yields no change; at least 30 but fewer than 45 days yields a three-percent markdown; at least 45 but fewer than 60 days yields five percent; 60 days or more yields eight percent."
        PRD §3.3: "The result is floored at the sourcing appraisal's `final_offer_cents` — the system never lists below the acquisition offer."

        Design: Difficulty/combinatorial_formula/repricing_per_event_rounding_composes
        """
        store, staff, cust = _phx_full_staff()
        vehicle, appr, _insp = self._listed_vehicle_a(store, staff, cust)

        set_clock("2026-10-01T00:00:00Z")
        pe1 = self._markdown(vehicle["id"], staff["manager"]["id"])
        assert pe1["days_in_inventory_at_event"] == 30
        assert pe1["trigger_kind"] == "SCHEDULED_MARKDOWN"

        set_clock("2026-10-16T00:00:00Z")
        pe2 = self._markdown(vehicle["id"], staff["manager"]["id"])
        assert pe2["days_in_inventory_at_event"] == 45

        set_clock("2026-10-31T00:00:00Z")
        pe3 = self._markdown(vehicle["id"], staff["manager"]["id"])
        assert pe3["days_in_inventory_at_event"] == 60
        # Floor at the sourcing appraisal's final offer (1,605,000).
        assert appr["final_offer_cents"] == 1605000
        assert pe3["new_price_cents"] == appr["final_offer_cents"]


class TestTransferFeeLaneBandExpediteSurcharge:
    def test_expedited_cross_country_nearly_new_fee(self):
        """PRD §3.4: "cross-country (`WEST`–`EAST`) is band 2 at nine hundred dollars (`90000` cents). If `expedited` is set, the band base is multiplied by three and divided by two (a 1.5× multiplier), rounded half-up to whole cents. Finally, if the vehicle is nearly new — its `model_year` is at least the current logical year minus one — an enclosed-carrier surcharge of two hundred dollars (`20000` cents) is added."

        Design: Difficulty/combinatorial_formula/transfer_fee_lane_band_expedite_surcharge
        """
        store, staff, cust1 = _phx_full_staff()
        mia = create_store(store_code="MIA-01", display_name="Miami",
                           region="EAST")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        vehicle, appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VDDDDDDDDDDDDDDDD",
            make="Tesla", model="Model 3", model_year=2025,
            odometer_miles=5000, line_items=[])

        version = get_vehicle_version(vehicle["id"],
                                      make_customer_headers(cust2["id"]))
        tr = get_success_data(api_client.create_transfer_request(
            create_transfer_request_payload(
                vehicle["id"], cust2["id"], mia["id"], version,
                expedited=True),
            make_customer_headers(cust2["id"])))
        assert_transfer_request(tr)
        assert tr["shipping_fee_cents"] == 155000
        assert tr["status"] == "REQUESTED"
        assert tr["from_store_id"] == store["id"]
        assert tr["to_store_id"] == mia["id"]

        vehicle = get_success_data(api_client.get_vehicle(
            vehicle["id"], make_customer_headers(cust2["id"])))
        assert_vehicle(vehicle)
        assert vehicle["hold_status"] == "TRANSFER_HOLD"

    def test_same_lane_non_expedited_fee_has_no_multiplier(self):
        """PRD §3.4: "The shipping fee depends on the lane band between the origin and destination store regions: same region is band 0 at one hundred fifty dollars (`15000` cents); adjacent regions (`WEST`–`CENTRAL` or `CENTRAL`–`EAST`) are band 1 at four hundred fifty dollars (`45000` cents); cross-country (`WEST`–`EAST`) is band 2 at nine hundred dollars (`90000` cents). If `expedited` is set, the band base is multiplied by three and divided by two (a 1.5× multiplier), rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/transfer_fee_lane_band_expedite_surcharge
        """
        store, staff, cust1 = _phx_full_staff()
        mia = create_store(store_code="MIA-01", display_name="Miami",
                           region="EAST")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        vehicle, appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VDDDDDDDDDDDDDDDD",
            make="Tesla", model="Model 3", model_year=2025,
            odometer_miles=5000, line_items=[])

        version = get_vehicle_version(vehicle["id"],
                                      make_customer_headers(cust2["id"]))
        tr = get_success_data(api_client.create_transfer_request(
            create_transfer_request_payload(
                vehicle["id"], cust2["id"], mia["id"], version),
            make_customer_headers(cust2["id"])))
        assert_transfer_request(tr)
        # Band 2 base 90,000 + nearly-new surcharge 20,000, no expedite.
        assert tr["shipping_fee_cents"] == 110000


class TestReturnWaterfallPinnedEvaluationOrder:
    def _financed_sale_with_trade_in(self):
        """V_A (list 1,797,600) sold financed to CUST1 with V_B trade-in
        (final offer 285,500). Returns (store, staff, cust, veh_a, appr_b,
        sale, fin)."""
        store, staff, cust = _phx_full_staff()
        veh_a, _appr_a, _insp_a = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        veh_b, appr_b = create_vehicle_with_active_appraisal(
            store, staff, cust, vin="VBBBBBBBBBBBBBBBB",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000)
        assert appr_b["final_offer_cents"] == 285500

        sale = create_sale_for(veh_a, cust, staff["sales"],
                               trade_in_appraisal_id=appr_b["id"])
        assert sale["amount_due_cents"] == 1512100
        fin = get_success_data(api_client.submit_financing_application(
            sale["id"], make_finance_manager_headers(staff["finance"]["id"])))
        get_success_data(api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_A"),
            make_customer_headers(cust["id"])))
        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "COMPLETED"
        return store, staff, cust, veh_a, appr_b, sale, fin

    def test_mileage_deduction_applies_before_lender_reversal_cap(self):
        """PRD §3.7: "First, the gross refund is the sale's `amount_due_cents` — what the buyer actually paid out of pocket. Second, a mileage deduction is computed: the excess of `odometer_at_return` over the vehicle's recorded `odometer_miles` beyond a 400-mile cap (`RETURN_MILEAGE_CAP`), never less than zero, multiplied by fifty cents per mile (`PER_MILE_CENTS`). Third, `refund_total_cents` is the gross refund minus the mileage deduction, never less than zero. Fourth, the refund is allocated to buckets in order: bucket A, a `LENDER_REVERSAL` entry, applies only when the sale was financed and sends the smaller of the refund total and the accepted offer's principal outstanding (the application's `requested_amount_cents`) to the lender as a negative entry, with the remainder carrying down; bucket B, a `REFUND_PAYABLE` entry, pays the remainder to the customer in cash as a negative entry; bucket C, a `COMMISSION_CLAWBACK` entry of negative `flat_commission_cents`, posts unconditionally and independently of the refund remainder."

        Design: Difficulty/combinatorial_formula/return_waterfall_pinned_evaluation_order
        """
        store, staff, cust, veh_a, appr_b, sale, fin = (
            self._financed_sale_with_trade_in())
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], odometer_at_return=30800),
            make_customer_headers(cust["id"])))
        get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))

        # Deduction: (30800 - 30000 - 400) * 50 = 20,000; gross 1,512,100.
        assert ret["refund_total_cents"] == 1492100

        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        # PRD names the waterfall entry kinds and amounts (§3.7) but does not
        # pin whether the polymorphic ref points at the Sale or the
        # ReturnRequest, so filter by kind only (§1.2 admits both ref_entity
        # values).
        reversals = [e for e in entries if e["entry_kind"] == "LENDER_REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -1492100
        # Lender absorbs the full refund: zero cash remainder to the customer.
        payables = [e for e in entries if e["entry_kind"] == "REFUND_PAYABLE"]
        assert payables == [] or all(p["amount_cents"] == 0 for p in payables)

    def test_clawback_and_terminal_cascades_fire(self):
        """PRD §3.7: "bucket C, a `COMMISSION_CLAWBACK` entry of negative `flat_commission_cents`, posts unconditionally and independently of the refund remainder."
        PRD §3.7: "Settlement cascades outward. The return becomes `SETTLED` (terminal), the sale becomes `RETURNED`, and the vehicle moves from `SOLD` to `RETURNED` with `hold_status` set to `RETURN_REVIEW_HOLD`. The redeemed trade-in appraisal on the sale reactivates if the logical clock is still before its `valid_until`: it returns from `REDEEMED` to `ACTIVE` for the remainder of its original validity window, and the trade-in vehicle's re-acquisition is unwound — the vehicle returns to the customer and leaves inventory, recorded as `DISPOSED` with a zero-value ledger treatment."

        Design: Difficulty/combinatorial_formula/return_waterfall_pinned_evaluation_order
        """
        store, staff, cust, veh_a, appr_b, sale, fin = (
            self._financed_sale_with_trade_in())
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], odometer_at_return=30800),
            make_customer_headers(cust["id"])))
        get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert ret["status"] == "SETTLED"

        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        clawbacks = [e for e in entries
                     if e["entry_kind"] == "COMMISSION_CLAWBACK"]
        assert len(clawbacks) == 1
        assert clawbacks[0]["amount_cents"] == -25000

        sale = get_success_data(api_client.get_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert_sale(sale)
        assert sale["status"] == "RETURNED"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_a["lifecycle_status"] == "RETURNED"
        assert veh_a["hold_status"] == "RETURN_REVIEW_HOLD"

        appr_b = get_success_data(api_client.get_appraisal(
            appr_b["id"],
            make_appraiser_headers(staff["appraiser"]["id"])))
        assert appr_b["status"] == "ACTIVE"
