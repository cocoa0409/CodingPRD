"""Depth tests: compensating invariants — sale-return ledger netting and
stage-dependent transfer cancellation fee conservation."""
import pytest

from test_helpers import (
    api_client, validate_paginated, get_success_data,
    make_store_manager_headers, make_customer_headers,
    make_sales_associate_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle_retail_listed, create_sale_for, create_return_payload,
    create_transfer_for,
    store_ledger_entries, assert_ledger_entries_for,
    assert_vehicle, assert_transfer_request,
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


class TestSaleReturnRestoresInventoryAndLedger:
    def _settled_cash_return(self):
        store, staff, cust = _phx_full_staff()
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh_a, cust, staff["sales"])
        sale = get_success_data(api_client.complete_sale(
            sale["id"],
            make_sales_associate_headers(staff["sales"]["id"])))
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], odometer_at_return=30100),
            make_customer_headers(cust["id"])))
        get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        return store, staff, cust, veh_a, sale, ret

    def test_sale_ledger_entries_net_to_zero(self):
        """PRD §3.5: "A `SALE_REVENUE` ledger entry of `sale_price_cents` posts at the sale store."
        PRD §3.5: "A `COMMISSION_ACCRUAL` entry posts the selling associate's `flat_commission_cents`."
        PRD §3.7: "bucket B, a `REFUND_PAYABLE` entry, pays the remainder to the customer in cash as a negative entry; bucket C, a `COMMISSION_CLAWBACK` entry of negative `flat_commission_cents`, posts unconditionally and independently of the refund remainder."
        PRD §2.10: "Ledger entries are append-only; corrections are expressed as new, opposite-signed entries, never as edits."

        Design: Difficulty/compensating_invariant/sale_return_restores_inventory_and_ledger
        """
        store, staff, cust, veh_a, sale, ret = self._settled_cash_return()
        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        # Sale-side entries reference the Sale; settlement waterfall entries
        # (REFUND_PAYABLE, COMMISSION_CLAWBACK) may reference the ReturnRequest
        # per §1.2's polymorphic ref — PRD §3.7 pins kind+amount, not ref.
        sale_entries = [e for e in entries
                        if e["ref_id"] in (sale["id"], ret["id"])]
        amounts = {(e["entry_kind"], e["amount_cents"]) for e in sale_entries}
        assert ("SALE_REVENUE", 1797600) in amounts
        assert ("COMMISSION_ACCRUAL", 25000) in amounts
        assert ("REFUND_PAYABLE", -1797600) in amounts
        assert ("COMMISSION_CLAWBACK", -25000) in amounts
        assert sum(e["amount_cents"] for e in sale_entries) == 0

    def test_vehicle_returns_to_store_inventory(self):
        """PRD §3.7: "Settlement cascades outward. The return becomes `SETTLED` (terminal), the sale becomes `RETURNED`, and the vehicle moves from `SOLD` to `RETURNED` with `hold_status` set to `RETURN_REVIEW_HOLD`."
        PRD §3.7: "Third, `refund_total_cents` is the gross refund minus the mileage deduction, never less than zero."

        Design: Difficulty/compensating_invariant/sale_return_restores_inventory_and_ledger
        """
        store, staff, cust, veh_a, sale, ret = self._settled_cash_return()
        assert ret["refund_total_cents"] == 1797600

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert_vehicle(veh_a)
        assert veh_a["lifecycle_status"] == "RETURNED"
        assert veh_a["current_store_id"] == store["id"]

        sale = get_success_data(api_client.get_sale(
            sale["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert sale["status"] == "RETURNED"


class TestTransferCancelStagesConserveFeeLedger:
    def _listed_vehicle_two_stores(self):
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
        cust1 = create_customer(email="c1@x.com")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        return store, dal, staff, cust1, cust2, veh_a

    def test_cancel_before_shipping_refunds_full_fee(self):
        """PRD §3.4: "Cancelling from `FEE_PAID` additionally refunds the full fee via a `TRANSFER_FEE_REFUND` ledger entry of `shipping_fee_cents` at the destination store."

        Design: Difficulty/compensating_invariant/transfer_cancel_stages_conserve_fee_ledger
        """
        store, dal, staff, cust1, cust2, veh_a = (
            self._listed_vehicle_two_stores())
        tr1 = create_transfer_for(veh_a, cust2, dal["id"])
        get_success_data(api_client.pay_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))
        tr1 = get_success_data(api_client.cancel_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))
        assert_transfer_request(tr1)
        assert tr1["status"] == "CANCELLED"

        entries = store_ledger_entries(dal["id"], staff["manager"]["id"])
        tr1_entries = [e for e in entries if e["ref_id"] == tr1["id"]]
        amounts = {(e["entry_kind"], e["amount_cents"])
                   for e in tr1_entries}
        assert ("TRANSFER_FEE", 45000) in amounts
        assert ("TRANSFER_FEE_REFUND", -45000) in amounts
        assert sum(e["amount_cents"] for e in tr1_entries) == 0

    def test_cancel_in_transit_retains_half_fee_and_returns_vehicle(self):
        """PRD §3.4: "Cancelling from `IN_TRANSIT` refunds half the fee — half of `shipping_fee_cents`, rounded half-up — as a `TRANSFER_FEE_REFUND` entry, retaining the other half as restocking; the vehicle remains at the origin store and its hold is cleared."

        Design: Difficulty/compensating_invariant/transfer_cancel_stages_conserve_fee_ledger
        """
        store, dal, staff, cust1, cust2, veh_a = (
            self._listed_vehicle_two_stores())
        tr1 = create_transfer_for(veh_a, cust2, dal["id"])
        get_success_data(api_client.pay_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))
        get_success_data(api_client.cancel_transfer_request(
            tr1["id"], make_customer_headers(cust2["id"])))

        tr2 = create_transfer_for(veh_a, cust1, dal["id"],
                                  supersedes_request_id=tr1["id"])
        get_success_data(api_client.pay_transfer_request(
            tr2["id"], make_customer_headers(cust1["id"])))
        get_success_data(api_client.ship_transfer_request(
            tr2["id"], make_store_manager_headers(staff["manager"]["id"])))
        tr2 = get_success_data(api_client.cancel_transfer_request(
            tr2["id"], make_customer_headers(cust1["id"])))
        assert tr2["status"] == "CANCELLED"

        entries = store_ledger_entries(dal["id"], staff["manager"]["id"])
        tr2_entries = [e for e in entries if e["ref_id"] == tr2["id"]]
        amounts = {(e["entry_kind"], e["amount_cents"])
                   for e in tr2_entries}
        assert ("TRANSFER_FEE", 45000) in amounts
        assert ("TRANSFER_FEE_REFUND", -22500) in amounts
        # Net +22,500 retained at the destination store.
        assert sum(e["amount_cents"] for e in tr2_entries) == 22500

        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert_vehicle(veh_a)
        assert veh_a["hold_status"] == "NONE"
        assert veh_a["current_store_id"] == store["id"]
        assert veh_a["lifecycle_status"] == "RETAIL_LISTED"
