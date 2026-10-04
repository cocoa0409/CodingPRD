"""Depth tests: dual-variant calculations on Appraisal and AuctionLot."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, auction_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_appraisal_for, open_inspection_for,
    add_line_item_for, approve_line_item_for, complete_inspection_for,
    create_auction_lot_payload, close_auction_lot_payload,
    assert_vehicle, assert_appraisal, assert_auction_lot,
)


def _phx_staff():
    """Store PHX (WEST, threshold 0.20) + manager/appraiser/inspector + CUST1."""
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    mgr = create_associate(store["id"], "MANAGER", "Manager One")
    ap = create_associate(store["id"], "APPRAISER", "Appraiser One")
    ins = create_associate(store["id"], "INSPECTOR", "Inspector One")
    cust = create_customer(email="c1@x.com")
    return store, mgr, ap, ins, cust


def _drive_inspection(vehicle_id, ins, line_items):
    insp = open_inspection_for(vehicle_id, ins["id"])
    for category, cost in line_items:
        item = add_line_item_for(insp["id"], ins["id"], category=category,
                                 cost_cents=cost)
        approve_line_item_for(insp["id"], item["id"], ins["id"])
    complete_inspection_for(insp["id"], ins["id"])
    return insp


class TestAppraisalProvisionalVsFinalDiverge:
    def test_provisional_and_final_offer_values(self):
        """PRD §3.1: "The provisional offer starts from the vehicle's `book_value_cents`, subtracts eight hundred dollars (`80000` cents) for each full model-year of age (the age in years being the current logical year minus `model_year`, never less than zero), and subtracts fifteen dollars (`1500` cents) for each whole block of one thousand miles by which the odometer exceeds an allowance of twelve thousand miles per year of age (the excess itself never less than zero)."
        PRD §3.2: "The final offer equals the provisional offer minus one half of the vehicle's `recon_cost_total_cents` (that is, fifty percent of the just-completed inspection's estimated repair total), again floored at five hundred dollars and rounded half-up to whole cents at the final step; `valid_until` is exactly seven days after `valid_from`."

        Design: Difficulty/dual_variant_calc/appraisal_provisional_vs_final_offer_diverge
        """
        store, mgr, ap, ins, cust = _phx_staff()
        vehicle = create_vehicle(store["id"], mgr["id"],
                                 vin="VAAAAAAAAAAAAAAAA")
        appr = create_appraisal_for(vehicle["id"], cust["id"], ap["id"])
        assert appr["provisional_offer_cents"] == 1680000

        _drive_inspection(vehicle["id"], ins,
                          [("MECHANICAL", 100000), ("BODY", 50000)])

        appr = get_success_data(api_client.get_appraisal(
            appr["id"], make_appraiser_headers(ap["id"])))
        assert_appraisal(appr)
        assert appr["provisional_offer_cents"] == 1680000
        assert appr["final_offer_cents"] == 1605000
        assert appr["final_offer_cents"] == appr["provisional_offer_cents"] - 75000

    def test_activation_status_and_validity_window(self):
        """PRD §3.2: "the sourcing appraisal is activated — its `status` moves from `PENDING_INSPECTION` to `ACTIVE`, its `final_offer_cents` is computed, and `valid_from` / `valid_until` are stamped."
        PRD §3.2: "`valid_until` is exactly seven days after `valid_from`."

        Design: Difficulty/dual_variant_calc/appraisal_provisional_vs_final_offer_diverge
        """
        store, mgr, ap, ins, cust = _phx_staff()
        vehicle = create_vehicle(store["id"], mgr["id"],
                                 vin="VAAAAAAAAAAAAAAAA")
        appr = create_appraisal_for(vehicle["id"], cust["id"], ap["id"])

        _drive_inspection(vehicle["id"], ins,
                          [("MECHANICAL", 100000), ("BODY", 50000)])

        appr = get_success_data(api_client.get_appraisal(
            appr["id"], make_appraiser_headers(ap["id"])))
        assert appr["status"] == "ACTIVE"
        assert appr["valid_from"] == "2026-09-01T00:00:00Z"
        assert appr["valid_until"] == "2026-09-08T00:00:00Z"


class TestAuctionReserveStandardVsRelistDiverge:
    def _wholesale_pending_vc(self):
        """V_C at PHX driven to WHOLESALE_PENDING (est 100,000 > 58,800)."""
        store, mgr, ap, ins, cust = _phx_staff()
        vehicle = create_vehicle(
            store["id"], mgr["id"], vin="VCCCCCCCCCCCCCCCC",
            make="Ford", model="F-150", model_year=2018,
            odometer_miles=140000, book_value_cents=1000000)
        create_appraisal_for(vehicle["id"], cust["id"], ap["id"])
        _drive_inspection(vehicle["id"], ins, [("SAFETY", 100000)])
        vehicle = get_success_data(api_client.get_vehicle(
            vehicle["id"], make_store_manager_headers(mgr["id"])))
        assert vehicle["lifecycle_status"] == "WHOLESALE_PENDING"
        return store, vehicle

    def test_standard_reserve_first_listing(self):
        """PRD §3.8: "On a first listing, the reserve is eighty-five percent of the vehicle's `book_value_cents` — book value multiplied by 85 and divided by 100, rounded half-up — plus fifty percent of `recon_cost_total_cents` as reconditioning-cost recovery."

        Design: Difficulty/dual_variant_calc/auction_reserve_standard_vs_relist_diverge
        """
        _store, vehicle = self._wholesale_pending_vc()
        lot1 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(vehicle["id"]),
            auction_manager_headers()))
        assert_auction_lot(lot1)
        assert lot1["reserve_price_cents"] == 900000
        assert lot1["auction_round"] == 1
        assert lot1["status"] == "LISTED"

    def test_relist_reserve_decays_ten_percent(self):
        """PRD §3.8: "On a relist, book value is ignored entirely: the reserve is the prior lot's `reserve_price_cents` decayed by ten percent — multiplied by 90 and divided by 100, rounded half-up — and in either case the reserve is floored at one thousand dollars (`100000` cents)."
        PRD §3.8: "When the hammer price falls below the reserve, the lot becomes `UNSOLD` and the vehicle returns to `WHOLESALE_PENDING` to await relist."

        Design: Difficulty/dual_variant_calc/auction_reserve_standard_vs_relist_diverge
        """
        _store, vehicle = self._wholesale_pending_vc()
        lot1 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(vehicle["id"]),
            auction_manager_headers()))
        lot1 = get_success_data(api_client.close_auction_lot(
            lot1["id"], close_auction_lot_payload(800000),
            auction_manager_headers()))
        assert lot1["status"] == "UNSOLD"
        assert lot1["reserve_price_cents"] == 900000

        lot2 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(vehicle["id"]),
            auction_manager_headers()))
        assert_auction_lot(lot2)
        assert lot2["reserve_price_cents"] == 810000
        assert lot2["auction_round"] == 2
        assert lot1["reserve_price_cents"] - lot2["reserve_price_cents"] == 90000

        vehicle = get_success_data(api_client.get_vehicle(
            vehicle["id"], auction_manager_headers()))
        assert_vehicle(vehicle)
        assert vehicle["lifecycle_status"] == "AT_AUCTION"
