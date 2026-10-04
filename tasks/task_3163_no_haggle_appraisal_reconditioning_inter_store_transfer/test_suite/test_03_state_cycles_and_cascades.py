"""Depth tests: non-linear state machines (Vehicle return/re-inspection cycle
and the AuctionLot relist cycle) and transitive cascades."""
import pytest

from test_helpers import (
    api_client, validate_paginated, get_success_data,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_customer_headers,
    make_sales_associate_headers, auction_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle_retail_listed, create_vehicle_with_active_appraisal,
    create_vehicle_wholesale_pending, create_sale_for,
    create_return_payload, create_auction_lot_payload,
    close_auction_lot_payload, create_transfer_for,
    open_inspection_for, complete_inspection_for, list_vehicle_for,
    store_ledger_entries, get_vehicle_version,
    assert_vehicle, assert_auction_lot, assert_transfer_request,
    assert_ledger_entries_for,
)


def _phx_full_staff():
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    staff = {
        "manager": create_associate(store["id"], "MANAGER", "Manager One"),
        "appraiser": create_associate(store["id"], "APPRAISER", "Appraiser One"),
        "inspector": create_associate(store["id"], "INSPECTOR", "Inspector One"),
        "sales": create_associate(store["id"], "SALES", "Sales One"),
    }
    cust = create_customer(email="c1@x.com")
    return store, staff, cust


class TestVehicleRetailReturnReinspectionCycle:
    def _settled_return(self):
        store, staff, cust = _phx_full_staff()
        veh_a, appr_a, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh_a, cust, staff["sales"])
        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], odometer_at_return=30100),
            make_customer_headers(cust["id"])))
        get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        return store, staff, cust, veh_a, sale, ret

    def test_returned_vehicle_reenters_pipeline_with_hold_cleared(self):
        """PRD §3.7: "A returned vehicle re-enters the reconditioning pipeline: a `ReconditioningInspector` opens a fresh inspection on the `RETURNED` vehicle (whose `hold_status` must be `RETURN_REVIEW_HOLD`), which clears the hold to `NONE`, resets `recon_cost_total_cents` to zero, resets `inventory_acquired_at` to the current logical time (so `days_in_inventory` restarts), and moves the vehicle back to `IN_INSPECTION`."

        Design: Difficulty/non_linear_state_machine/vehicle_retail_return_reinspection_cycle
        """
        store, staff, cust, veh_a, sale, ret = self._settled_return()

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_a["lifecycle_status"] == "RETURNED"
        assert veh_a["hold_status"] == "RETURN_REVIEW_HOLD"

        insp2 = open_inspection_for(veh_a["id"], staff["inspector"]["id"])
        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert_vehicle(veh_a)
        assert veh_a["lifecycle_status"] == "IN_INSPECTION"
        assert veh_a["hold_status"] == "NONE"
        assert veh_a["recon_cost_total_cents"] == 0
        return insp2, veh_a

    def test_cycle_regrades_relists_and_reprices_from_scratch(self):
        """PRD §3.7: "From there the inspection-completion machinery of §3.2 applies unchanged — the vehicle may be graded, relisted, repriced (its `days_in_inventory` now measuring the re-acquisition), and sold again."
        PRD §3.2: "A `RETAIL` disposition also assigns the vehicle's `condition_grade`: `A` when the estimated repair total is exactly zero, `B` when it is positive but no more than half the threshold (rounded down), and `C` otherwise."
        PRD §3.7: "First, the gross refund is the sale's `amount_due_cents` — what the buyer actually paid out of pocket. Second, a mileage deduction is computed: the excess of `odometer_at_return` over the vehicle's recorded `odometer_miles` beyond a 400-mile cap (`RETURN_MILEAGE_CAP`), never less than zero, multiplied by fifty cents per mile (`PER_MILE_CENTS`). Third, `refund_total_cents` is the gross refund minus the mileage deduction, never less than zero."

        Design: Difficulty/non_linear_state_machine/vehicle_retail_return_reinspection_cycle
        """
        store, staff, cust, veh_a, sale, ret = self._settled_return()
        # 100 extra miles are within the 400-mile cap -> no deduction.
        assert ret["refund_total_cents"] == 1797600

        insp2 = open_inspection_for(veh_a["id"], staff["inspector"]["id"])
        insp2 = complete_inspection_for(insp2["id"],
                                        staff["inspector"]["id"])
        assert insp2["disposition"] == "RETAIL"

        list_vehicle_for(veh_a["id"], staff["manager"]["id"])
        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert_vehicle(veh_a)
        assert veh_a["lifecycle_status"] == "RETAIL_LISTED"
        assert veh_a["condition_grade"] == "A"
        # Recomputed from the final offer 1,605,000 x 1.12 after the cycle.
        assert veh_a["current_list_price_cents"] == 1797600


class TestAuctionLotUnsoldRelistCycle:
    def _wholesale_vc(self):
        store, staff, cust = _phx_full_staff()
        veh_c, appr_c, insp_c = create_vehicle_wholesale_pending(
            store, staff, cust, vin="VCCCCCCCCCCCCCCCC",
            make="Ford", model="F-150", model_year=2018,
            odometer_miles=140000, book_value_cents=1000000)
        return store, veh_c

    def test_three_rounds_of_reserve_decay(self):
        """PRD §3.8: "Relisting creates a new lot for the same vehicle with `auction_round` incremented, provided the previous lot is `UNSOLD` and its `auction_round` was below 3; once three rounds are exhausted, a relist attempt is rejected with `ERR_AUCTION_ROUNDS_EXHAUSTED` — though a below-reserve close itself still completes, leaving the lot `UNSOLD`."
        PRD §3.8: "On a relist, book value is ignored entirely: the reserve is the prior lot's `reserve_price_cents` decayed by ten percent — multiplied by 90 and divided by 100, rounded half-up — and in either case the reserve is floored at one thousand dollars (`100000` cents)."

        Design: Difficulty/non_linear_state_machine/auction_lot_unsold_relist_cycle
        """
        _store, veh_c = self._wholesale_vc()
        lot1 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]), auction_manager_headers()))
        lot1 = get_success_data(api_client.close_auction_lot(
            lot1["id"], close_auction_lot_payload(800000),
            auction_manager_headers()))
        assert lot1["status"] == "UNSOLD"

        veh_c = get_success_data(api_client.get_vehicle(
            veh_c["id"], auction_manager_headers()))
        assert veh_c["lifecycle_status"] == "WHOLESALE_PENDING"

        lot2 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]), auction_manager_headers()))
        assert_auction_lot(lot2)
        assert lot2["reserve_price_cents"] == 810000
        assert lot2["auction_round"] == 2

        lot2 = get_success_data(api_client.close_auction_lot(
            lot2["id"], close_auction_lot_payload(700000),
            auction_manager_headers()))
        assert lot2["status"] == "UNSOLD"

        lot3 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]), auction_manager_headers()))
        assert_auction_lot(lot3)
        assert lot3["reserve_price_cents"] == 729000
        assert lot3["auction_round"] == 3

    def test_round_three_close_at_reserve_disposes_vehicle(self):
        """PRD §3.8: "When the hammer price is at least the reserve, the lot becomes `SOLD`, an `AUCTION_PROCEEDS` entry of `hammer_price_cents` posts at the vehicle's current store, and the vehicle reaches its terminal state `DISPOSED`."

        Design: Difficulty/non_linear_state_machine/auction_lot_unsold_relist_cycle
        """
        store, veh_c = self._wholesale_vc()
        lot_id = None
        for hammer in (800000, 700000, 729000):
            lot = get_success_data(api_client.create_auction_lot(
                create_auction_lot_payload(veh_c["id"]),
                auction_manager_headers()))
            lot_id = lot["id"]
            lot = get_success_data(api_client.close_auction_lot(
                lot_id, close_auction_lot_payload(hammer),
                auction_manager_headers()))
        assert lot["status"] == "SOLD"

        veh_c = get_success_data(api_client.get_vehicle(
            veh_c["id"], auction_manager_headers()))
        assert veh_c["lifecycle_status"] == "DISPOSED"

        staff_mgr = create_associate(store["id"], "MANAGER", "Manager One")
        entries = store_ledger_entries(store["id"], staff_mgr["id"])
        proceeds = assert_ledger_entries_for(entries, lot_id,
                                             "AUCTION_PROCEEDS")
        assert len(proceeds) == 1
        assert proceeds[0]["amount_cents"] == 729000


class TestReturnSettlementFourHopCascade:
    def _settled_sale_with_trade_in(self, odometer_at_return=30050,
                                    reason_code="MECHANICAL_DEFECT"):
        store, staff, cust = _phx_full_staff()
        veh_a, _appr_a, _insp_a = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        veh_b, appr_b = create_vehicle_with_active_appraisal(
            store, staff, cust, vin="VBBBBBBBBBBBBBBBB",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000)
        sale = create_sale_for(veh_a, cust, staff["sales"],
                               trade_in_appraisal_id=appr_b["id"])
        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], reason_code=reason_code,
                                  odometer_at_return=odometer_at_return),
            make_customer_headers(cust["id"])))
        get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        return store, staff, cust, veh_a, veh_b, appr_b, sale, ret

    def test_settle_cascades_sale_vehicle_appraisal_trade_in(self):
        """PRD §3.7: "Settlement cascades outward. The return becomes `SETTLED` (terminal), the sale becomes `RETURNED`, and the vehicle moves from `SOLD` to `RETURNED` with `hold_status` set to `RETURN_REVIEW_HOLD`. The redeemed trade-in appraisal on the sale reactivates if the logical clock is still before its `valid_until`: it returns from `REDEEMED` to `ACTIVE` for the remainder of its original validity window, and the trade-in vehicle's re-acquisition is unwound — the vehicle returns to the customer and leaves inventory, recorded as `DISPOSED` with a zero-value ledger treatment."

        Design: Difficulty/transitive_cascade/return_settlement_four_hop_cascade
        """
        (store, staff, cust, veh_a, veh_b, appr_b, sale, ret) = (
            self._settled_sale_with_trade_in())

        sale = get_success_data(api_client.get_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "RETURNED"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_a["lifecycle_status"] == "RETURNED"
        assert veh_a["hold_status"] == "RETURN_REVIEW_HOLD"

        appr_b = get_success_data(api_client.get_appraisal(
            appr_b["id"], make_appraiser_headers(staff["appraiser"]["id"])))
        assert appr_b["status"] == "ACTIVE"

        veh_b = get_success_data(api_client.get_vehicle(
            veh_b["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_b["lifecycle_status"] == "DISPOSED"

    def test_settle_posts_waterfall_ledger_entries(self):
        """PRD §3.7: "bucket B, a `REFUND_PAYABLE` entry, pays the remainder to the customer in cash as a negative entry; bucket C, a `COMMISSION_CLAWBACK` entry of negative `flat_commission_cents`, posts unconditionally and independently of the refund remainder."
        PRD §3.7: "First, the gross refund is the sale's `amount_due_cents` — what the buyer actually paid out of pocket. Second, a mileage deduction is computed: the excess of `odometer_at_return` over the vehicle's recorded `odometer_miles` beyond a 400-mile cap (`RETURN_MILEAGE_CAP`), never less than zero, multiplied by fifty cents per mile (`PER_MILE_CENTS`). Third, `refund_total_cents` is the gross refund minus the mileage deduction, never less than zero."

        Design: Difficulty/transitive_cascade/return_settlement_four_hop_cascade
        """
        (store, staff, cust, veh_a, veh_b, appr_b, sale, ret) = (
            self._settled_sale_with_trade_in())
        # amount_due = 1,797,600 - 285,500 = 1,512,100; odometer excess 50
        # miles is within the 400-mile cap -> no deduction.
        assert ret["refund_total_cents"] == 1512100

        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        # §3.7 pins entry kind and amount, not the polymorphic ref target —
        # filter by kind only (Sale vs ReturnRequest refs both satisfy §1.2).
        payables = [e for e in entries if e["entry_kind"] == "REFUND_PAYABLE"]
        assert len(payables) == 1
        assert payables[0]["amount_cents"] == -1512100
        clawbacks = [e for e in entries
                     if e["entry_kind"] == "COMMISSION_CLAWBACK"]
        assert len(clawbacks) == 1
        assert clawbacks[0]["amount_cents"] == -25000


class TestTransferDeliveryStoreMoveCascade:
    def _delivered_transfer(self):
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()  # PHX WEST
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
        sa2 = create_associate(dal["id"], "SALES", "Sales Two")
        cust1 = create_customer(email="c1@x.com")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        tr = create_transfer_for(veh_a, cust2, dal["id"])
        get_success_data(api_client.pay_transfer_request(
            tr["id"], make_customer_headers(cust2["id"])))
        get_success_data(api_client.ship_transfer_request(
            tr["id"], make_store_manager_headers(staff["manager"]["id"])))
        tr = get_success_data(api_client.deliver_transfer_request(
            tr["id"], make_store_manager_headers(mgr2["id"])))
        return store, dal, staff, mgr2, sa2, cust1, cust2, veh_a, tr

    def test_deliver_moves_vehicle_and_starts_hold(self):
        """PRD §3.4: "a `StoreManager` at the destination store confirms delivery (`IN_TRANSIT` → `DELIVERED`), which moves the vehicle's `current_store_id` to the destination store, sets `hold_expires_at` to the delivery instant plus the destination store's `transfer_hold_days`, and increments the vehicle's `version`."

        Design: Difficulty/transitive_cascade/transfer_delivery_store_move_cascade
        """
        (store, dal, staff, mgr2, sa2, cust1, cust2, veh_a, tr) = (
            self._delivered_transfer())
        assert_transfer_request(tr)
        assert tr["status"] == "DELIVERED"
        assert tr["hold_expires_at"] == "2026-09-08T00:00:00Z"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(mgr2["id"])))
        assert veh_a["current_store_id"] == dal["id"]

    def test_fulfilment_cascade_sells_vehicle_and_clears_hold(self):
        """PRD §3.5: "In the latter case, completing before `hold_expires_at` clears the hold, moves the transfer request to `FULFILLED`, and then sells the vehicle; if the hold has already lapsed, the request must first have transitioned to `HOLD_EXPIRED`, and completing against it is rejected with `ERR_WINDOW_CLOSED`."
        PRD §3.5: "A `SALE_REVENUE` ledger entry of `sale_price_cents` posts at the sale store."
        PRD §3.4: "The customer — and only that customer, matched by `customer_id` — pays the fee, moving the request to `FEE_PAID` and posting a `TRANSFER_FEE` ledger entry for `shipping_fee_cents` at the destination store's books"

        Design: Difficulty/transitive_cascade/transfer_delivery_store_move_cascade
        """
        (store, dal, staff, mgr2, sa2, cust1, cust2, veh_a, tr) = (
            self._delivered_transfer())
        veh_at_dal = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(mgr2["id"])))
        sale = create_sale_for(veh_at_dal, cust2, sa2)
        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(sa2["id"])))
        assert sale["status"] == "COMPLETED"
        assert sale["store_id"] == dal["id"]
        assert sale["sale_price_cents"] == 1797600

        tr = get_success_data(api_client.get_transfer_request(
            tr["id"], make_customer_headers(cust2["id"])))
        assert tr["status"] == "FULFILLED"

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(mgr2["id"])))
        assert_vehicle(veh_a)
        assert veh_a["lifecycle_status"] == "SOLD"
        assert veh_a["hold_status"] == "NONE"

        entries = store_ledger_entries(dal["id"], mgr2["id"])
        fees = assert_ledger_entries_for(entries, tr["id"], "TRANSFER_FEE")
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 45000
        revenues = assert_ledger_entries_for(entries, sale["id"],
                                             "SALE_REVENUE")
        assert len(revenues) == 1
        assert revenues[0]["amount_cents"] == 1797600
