"""Corner tests: appraisal offer floor, financing tier scoring
boundaries, DECLINED filtering, flat compensation plus volume bonus, and
the auction reserve minimum floor."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_customer_headers, make_sales_associate_headers,
    make_finance_manager_headers, auction_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_vehicle_retail_listed,
    create_vehicle_with_active_appraisal, create_vehicle_wholesale_pending,
    create_vehicle_appraised, create_appraisal_for, create_sale_for,
    accept_financing_payload, create_auction_lot_payload,
    open_inspection_for, add_line_item_for, approve_line_item_for,
    complete_inspection_for, store_ledger_entries,
    assert_appraisal, assert_financing_application, assert_auction_lot,
)


def _phx_staff(with_sales=False, with_finance=False):
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    staff = {
        "manager": create_associate(store["id"], "MANAGER", "Manager One"),
        "appraiser": create_associate(store["id"], "APPRAISER", "Appraiser One"),
        "inspector": create_associate(store["id"], "INSPECTOR", "Inspector One"),
    }
    if with_sales:
        staff["sales"] = create_associate(store["id"], "SALES", "Sales One")
    if with_finance:
        staff["finance"] = create_associate(store["id"], "FINANCE",
                                            "Finance One")
    return store, staff


class TestAppraisalFormulaConstantsAndFloor:
    def test_raw_offer_below_zero_floored_at_five_hundred_dollars(self):
        """PRD §3.1: "The provisional offer starts from the vehicle's `book_value_cents`, subtracts eight hundred dollars (`80000` cents) for each full model-year of age (the age in years being the current logical year minus `model_year`, never less than zero), and subtracts fifteen dollars (`1500` cents) for each whole block of one thousand miles by which the odometer exceeds an allowance of twelve thousand miles per year of age (the excess itself never less than zero). The result is floored at five hundred dollars (`50000` cents) and rounded half-up to whole cents only at the final step."
        PRD §3.1: "Creation moves the vehicle from `INTAKE` to `APPRAISED` and computes a `provisional_offer_cents`."

        Design: Corner/calculations/appraisal_formula_constants_and_floor
        """
        store, staff = _phx_staff()
        cust = create_customer(email="c1@x.com")
        veh = create_vehicle(store["id"], staff["manager"]["id"],
                             vin="VGGGGGGGGGGGGGGGG", make="Kia",
                             model="Rio", model_year=2024,
                             odometer_miles=30000, book_value_cents=100000)
        appr = create_appraisal_for(veh["id"], cust["id"],
                                    staff["appraiser"]["id"])
        assert_appraisal(appr)
        # Raw: 100,000 - 2*80,000 - 0 = -60,000 -> floored at 50,000.
        assert appr["provisional_offer_cents"] == 50000
        assert appr["status"] == "PENDING_INSPECTION"


class TestFinancingTierScoringBoundariesAndDeclined:
    def _listed_corolla(self, store, staff, vin, customer):
        return create_vehicle_retail_listed(
            store, staff, customer, vin=vin, make="Toyota", model="Corolla",
            model_year=2020, odometer_miles=95000, book_value_cents=800000,
            line_items=[])

    def test_credit_535_tier_3_and_credit_536_tier_2(self):
        """PRD §3.6: "The customer's `credit_score` (between 300 and 850 inclusive) is normalized by subtracting 300 and dividing by 550. A debt-to-income ratio is formed by dividing the sale's `amount_due_cents` by the customer's `stated_annual_income_cents` (with a denominator of at least 1); the normalized DTI is one minus the ratio divided by a cap of 0.5, clamped to never fall below zero. The final score is seven-tenths of the normalized credit plus three-tenths of the normalized DTI, computed to four decimal places with round-half-up before any comparison. A score of at least 0.8000 earns `TIER_1`; at least 0.6000 earns `TIER_2`; at least 0.4000 earns `TIER_3`; anything lower is `DECLINED`."
        PRD §3.6: "The rate per lender and tier is: `LENDER_A` offers 490, 690, or 990 for tiers one through three; `LENDER_B` offers 515, 740, or 1040; `LENDER_C` offers 540, 780, or 1090."
        PRD §3.6: "Each offer references its application via `application_id`, carries an `apr_bps` annual percentage rate in basis points, and sets its `max_amount_cents` equal to `requested_amount_cents` — every lender funds the full request at its own tier rate."

        Design: Corner/calculations/financing_tier_scoring_boundaries_and_declined
        """
        store, staff = _phx_staff(with_sales=True, with_finance=True)
        c535 = create_customer(email="low535@x.com", credit_score=535,
                               stated_annual_income_cents=100000000000)
        c536 = create_customer(email="mid536@x.com", credit_score=536,
                               stated_annual_income_cents=100000000000)

        veh1, _a1, _i1 = self._listed_corolla(store, staff,
                                              "VB1B1B1B1B1B1B1B1", c535)
        veh2, _a2, _i2 = self._listed_corolla(store, staff,
                                              "VB2B2B2B2B2B2B2B2", c536)
        fm_headers = make_finance_manager_headers(staff["finance"]["id"])

        sale1 = create_sale_for(veh1, c535, staff["sales"])
        fin1 = get_success_data(api_client.submit_financing_application(
            sale1["id"], fm_headers))
        sale2 = create_sale_for(veh2, c536, staff["sales"])
        fin2 = get_success_data(api_client.submit_financing_application(
            sale2["id"], fm_headers))

        assert_financing_application(fin1)
        assert fin1["approval_tier"] == "TIER_3"
        assert fin1["requested_amount_cents"] == 319760
        assert_financing_application(fin2)
        assert fin2["approval_tier"] == "TIER_2"

        offers1, _ = validate_paginated(api_client.list_financing_offers(
            fin1["id"], fm_headers))
        apr1 = {o["lender_code"]: o["apr_bps"] for o in offers1}
        assert apr1 == {"LENDER_A": 990, "LENDER_B": 1040, "LENDER_C": 1090}
        assert all(o["max_amount_cents"] == 319760 for o in offers1)

        offers2, _ = validate_paginated(api_client.list_financing_offers(
            fin2["id"], fm_headers))
        apr2 = {o["lender_code"]: o["apr_bps"] for o in offers2}
        assert apr2 == {"LENDER_A": 690, "LENDER_B": 740, "LENDER_C": 780}


class TestFinancingDeclinedCreatesNoOffers:
    def test_declined_application_presents_empty_panel(self):
        """PRD §3.6: "A `DECLINED` application creates zero offers and remains `SUBMITTED` until withdrawn."
        PRD §3.6: "attempting to accept on a `DECLINED` application is rejected with `ERR_FINANCING_DECLINED`."
        PRD §3.5: "A `SalesAssociate` completes a `PENDING_FINANCE` sale only when its financing posture is settled: either no financing application exists for the sale (a cash deal), or the application is `ACCEPTED`; completing with an application in any other state is rejected with `ERR_FINANCING_NOT_ACCEPTED`."

        Design: Corner/calculations/financing_declined_creates_no_offers
        """
        store, staff = _phx_staff(with_sales=True, with_finance=True)
        poor = create_customer(email="poor@x.com", credit_score=300,
                               stated_annual_income_cents=1)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, poor, vin="VB3B3B3B3B3B3B3B3",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000, line_items=[])
        sale = create_sale_for(veh, poor, staff["sales"])
        fm_headers = make_finance_manager_headers(staff["finance"]["id"])

        fin = get_success_data(api_client.submit_financing_application(
            sale["id"], fm_headers))
        assert_financing_application(fin)
        assert fin["approval_tier"] == "DECLINED"
        assert fin["status"] == "SUBMITTED"

        offers, meta = validate_paginated(api_client.list_financing_offers(
            fin["id"], fm_headers))
        assert offers == []
        assert meta["total_count"] == 0

        resp = api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_A"),
            make_customer_headers(poor["id"]))
        validate_error(resp, ApiErrorId.ERR_FINANCING_DECLINED)

        resp = api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_ACCEPTED)


class TestAssociateCompFlatAcrossPricePointsAndVolumeBonus:
    def test_five_sales_accrue_flat_commissions_plus_tier_one_bonus(self):
        """PRD §3.9: "On every completed sale the system accrues the selling associate's `flat_commission_cents` (default `25000` cents, two hundred fifty dollars) as a `COMMISSION_ACCRUAL` entry — identical for every vehicle regardless of `sale_price_cents`, so commission is never a function of price."
        PRD §3.9: "A monthly volume bonus layers on top, measured against the logical-clock calendar month of each sale's `completed_at` at the associate's home store. When an associate's count of completed sales in a month reaches at least 5, a bonus of five hundred dollars (`50000` cents) accrues; at least 10 earns fifteen hundred dollars (`150000` cents); at least 20 earns four thousand dollars (`400000` cents). Each tier bonus accrues as a single ledger entry at the sale that first crosses that tier's boundary (the boundary is inclusive — reaching the tier count exactly triggers the bonus)."

        Design: Corner/calculations/associate_comp_flat_across_price_points_and_volume_bonus
        """
        store, staff = _phx_staff(with_sales=True)
        customers = [
            create_customer(email=f"c{i}@x.com", credit_score=700,
                            stated_annual_income_cents=8000000)
            for i in range(1, 6)
        ]
        # V_A: expensive retail listing (1,797,600).
        veh_a, _aa, _ia = create_vehicle_retail_listed(
            store, staff, customers[0], vin="VAAAAAAAAAAAAAAAA")
        # Four cheap Corollas (list 319,760).
        cheap_vehicles = []
        for i, cust in enumerate(customers[1:], start=1):
            veh, _a, _i = create_vehicle_retail_listed(
                store, staff, cust, vin=f"VINB{i}X" + "B" * 11,
                make="Toyota", model="Corolla", model_year=2020,
                odometer_miles=95000, book_value_cents=800000,
                line_items=[])
            cheap_vehicles.append((veh, cust))

        for veh, cust in cheap_vehicles:
            sale = create_sale_for(veh, cust, staff["sales"])
            get_success_data(api_client.complete_sale(
                sale["id"],
                make_sales_associate_headers(staff["sales"]["id"])))
        sale_a = create_sale_for(veh_a, customers[0], staff["sales"])
        get_success_data(api_client.complete_sale(
            sale_a["id"],
            make_sales_associate_headers(staff["sales"]["id"])))

        entries = store_ledger_entries(store["id"], staff["manager"]["id"],
                                       entry_kind="COMMISSION_ACCRUAL")
        assert len(entries) == 6
        amounts = sorted(e["amount_cents"] for e in entries)
        assert amounts.count(25000) == 5
        assert amounts.count(50000) == 1
        assert sum(amounts) == 175000


class TestAuctionReserveMinimumFloor:
    def test_raw_reserve_below_floor_uses_minimum(self):
        """PRD §3.8: "On a first listing, the reserve is eighty-five percent of the vehicle's `book_value_cents` — book value multiplied by 85 and divided by 100, rounded half-up — plus fifty percent of `recon_cost_total_cents` as reconditioning-cost recovery. On a relist, book value is ignored entirely: the reserve is the prior lot's `reserve_price_cents` decayed by ten percent — multiplied by 90 and divided by 100, rounded half-up — and in either case the reserve is floored at one thousand dollars (`100000` cents)."
        PRD §3.2: "If the inspection's `estimated_repair_total_cents` is **strictly greater** than that threshold, the disposition is `WHOLESALE`; otherwise (including exact equality with the threshold) it is `RETAIL`."

        Design: Corner/calculations/auction_reserve_minimum_floor
        """
        store, staff = _phx_staff()
        cust = create_customer(email="c1@x.com")
        veh_g = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VGGGGGGGGGGGGGGGG", make="Kia",
                               model="Rio", model_year=2024,
                               odometer_miles=30000, book_value_cents=100000)
        create_appraisal_for(veh_g["id"], cust["id"],
                             staff["appraiser"]["id"])
        insp = open_inspection_for(veh_g["id"], staff["inspector"]["id"])
        li = add_line_item_for(insp["id"], staff["inspector"]["id"],
                               category="BODY", cost_cents=20000)
        approve_line_item_for(insp["id"], li["id"], staff["inspector"]["id"])
        insp = complete_inspection_for(insp["id"], staff["inspector"]["id"])
        # Provisional basis floored at 50,000 -> threshold 10,000; 20,000 >.
        assert insp["disposition"] == "WHOLESALE"

        lot = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_g["id"]),
            auction_manager_headers()))
        assert_auction_lot(lot)
        # Raw 85,000 + 10,000 = 95,000 floored to 100,000.
        assert lot["reserve_price_cents"] == 100000
