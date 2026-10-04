"""Depth tests: validation priority pairs and boundary precision."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_error_is_one_of, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_customer_headers,
    make_sales_associate_headers, make_finance_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_vehicle_retail_listed,
    create_vehicle_with_active_appraisal, create_vehicle_appraised,
    create_appraisal_for, create_sale_for, create_sale_payload,
    create_transfer_request_payload, create_transfer_for,
    create_return_payload,
    open_inspection_for, add_line_item_for, approve_line_item_for,
    complete_inspection_for,
    get_vehicle_version,
    assert_transfer_request,
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


class TestSaleStateVsTemporalConflict:
    def _recon_vehicle_and_pending_appraisal(self):
        """V_A driven to RECON (never listed); V_B appraised for CUST1 with an
        open-but-never-completed inspection (appraisal PENDING_INSPECTION);
        clock advanced to 2026-09-10."""
        store, staff, cust = _phx_full_staff()
        # V_A -> RECON.
        veh_a, appr_a = create_vehicle_appraised(store, staff, cust,
                                                 vin="VAAAAAAAAAAAAAAAA")
        insp_a = open_inspection_for(veh_a["id"], staff["inspector"]["id"])
        for cat, cost in (("MECHANICAL", 100000), ("BODY", 50000)):
            item = add_line_item_for(insp_a["id"], staff["inspector"]["id"],
                                     category=cat, cost_cents=cost)
            approve_line_item_for(insp_a["id"], item["id"],
                                  staff["inspector"]["id"])
        complete_inspection_for(insp_a["id"], staff["inspector"]["id"])
        veh_a = get_success_data(api_client.get_vehicle(
            veh_a["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_a["lifecycle_status"] == "RECON"

        # V_B appraised, inspection opened but never completed.
        veh_b = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VBBBBBBBBBBBBBBBB",
                               make="Toyota", model="Corolla", model_year=2020,
                               odometer_miles=95000, book_value_cents=800000)
        appr_b = create_appraisal_for(veh_b["id"], cust["id"],
                                      staff["appraiser"]["id"])
        open_inspection_for(veh_b["id"], staff["inspector"]["id"])

        set_clock("2026-09-10T00:00:00Z")
        return store, staff, cust, veh_a, appr_b

    def test_state_error_beats_temporal_error(self):
        """PRD §2.8: "When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order, and the first failing rule determines the error returned:"
        PRD §2.8: "5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`."
        PRD §2.8: "8. Temporal windows (`ERR_WINDOW_CLOSED` family, with state-aware sub-codes: an expired appraisal surfaces as `ERR_APPRAISAL_EXPIRED`, a closed return window as `ERR_RETURN_WINDOW_CLOSED`, and a transfer fulfilment past hold expiry as `ERR_WINDOW_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/sale_state_vs_temporal_conflict
        """
        store, staff, cust, veh_a, appr_b = (
            self._recon_vehicle_and_pending_appraisal())
        resp = api_client.create_sale(
            create_sale_payload(veh_a["id"], cust["id"],
                                staff["sales"]["id"],
                                trade_in_appraisal_id=appr_b["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        # PRD §3.5 names ERR_CROSS_ENTITY_STATE for a sale against a vehicle
        # that is not RETAIL_LISTED; §2.8 level-5 prose names ERR_INVALID_STATE
        # for "any other from-state violation". PRD does not pin which wording
        # wins for sale creation, so accept either member of the 409 pair.
        validate_error_is_one_of(resp, [ApiErrorId.ERR_CROSS_ENTITY_STATE,
                                        ApiErrorId.ERR_INVALID_STATE])

        sales, meta = validate_paginated(api_client.list_sales(
            make_sales_associate_headers(staff["sales"]["id"]),
            params={"vehicle_id": veh_a["id"]}))
        assert sales == []

    def test_state_error_prevents_any_sale_row_from_persisting(self):
        """PRD §2.8: "When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order, and the first failing rule determines the error returned:"
        PRD §3.5: "A `SalesAssociate` opens a sale by supplying the `vehicle_id`, the buyer's `customer_id`, their own `associate_id` (an associate whose `role_kind` is `SALES`), and optionally a `trade_in_appraisal_id`. The vehicle must be `RETAIL_LISTED` at its current store and unheld — a sale against a vehicle not `RETAIL_LISTED`, or one held for someone else's transfer, is rejected with `ERR_CROSS_ENTITY_STATE` (with the transfer-hold exception described below)."

        Design: Difficulty/priority_pair_validation_conflict/sale_state_vs_temporal_conflict
        """
        store, staff, cust, veh_a, appr_b = (
            self._recon_vehicle_and_pending_appraisal())
        resp = api_client.create_sale(
            create_sale_payload(veh_a["id"], cust["id"],
                                staff["sales"]["id"],
                                trade_in_appraisal_id=appr_b["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        assert resp.status_code == 409
        body = resp.json()
        # See note in test_state_error_beats_temporal_error: PRD §3.5 and
        # §2.8 level-5 each name a different 409 for this rejection.
        assert body["data"]["error_id"] in ("ERR_CROSS_ENTITY_STATE",
                                            "ERR_INVALID_STATE")
        # The rejected call must not leave a Sale behind.
        sales, meta = validate_paginated(api_client.list_sales(
            make_sales_associate_headers(staff["sales"]["id"]),
            params={"vehicle_id": veh_a["id"]}))
        assert sales == []
        assert meta["total_count"] == 0


class TestTransferReferentialVsFiscalOccConflict:
    def _vehicle_under_hold_with_stale_version(self):
        """V_A RETAIL_LISTED at PHX; CUST2's transfer holds the vehicle; the
        returned pre-hold version is stale by the time CUST1 attempts."""
        store, staff, cust1 = _phx_full_staff()
        dal = create_store(store_code="DAL-01", display_name="Dallas",
                           region="CENTRAL")
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        pre_hold_version = get_vehicle_version(
            veh_a["id"], make_customer_headers(cust1["id"]))
        tr1 = get_success_data(api_client.create_transfer_request(
            create_transfer_request_payload(veh_a["id"], cust2["id"],
                                            dal["id"], pre_hold_version),
            make_customer_headers(cust2["id"])))
        return store, dal, staff, cust1, cust2, veh_a, tr1, pre_hold_version

    def test_hold_rejection_takes_precedence_over_stale_version(self):
        """PRD §2.8: "9. Cross-entity referential rules (`ERR_CROSS_ENTITY_STATE` family, again with state-aware sub-codes such as `ERR_APPRAISAL_NOT_ACTIVE`, `ERR_APPRAISAL_CUSTOMER_MISMATCH`, `ERR_OFFER_NOT_PRESENTED`, and `ERR_FINANCING_DECLINED`)."
        PRD §2.8: "12. Stale optimistic-concurrency version (`ERR_STALE_VERSION`)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_referential_vs_fiscal_occ_conflict
        """
        (store, dal, staff, cust1, cust2, veh_a, tr1, pre_hold_version) = (
            self._vehicle_under_hold_with_stale_version())
        resp = api_client.create_transfer_request(
            create_transfer_request_payload(veh_a["id"], cust1["id"],
                                            dal["id"], pre_hold_version),
            make_customer_headers(cust1["id"]))
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] in (
            "ERR_VEHICLE_ALREADY_HELD", "ERR_CROSS_ENTITY_STATE")

    def test_rejected_request_leaves_a_single_transfer_for_vehicle(self):
        """PRD §2.8: "9. Cross-entity referential rules (`ERR_CROSS_ENTITY_STATE` family, again with state-aware sub-codes such as `ERR_APPRAISAL_NOT_ACTIVE`, `ERR_APPRAISAL_CUSTOMER_MISMATCH`, `ERR_OFFER_NOT_PRESENTED`, and `ERR_FINANCING_DECLINED`)."
        PRD §3.4: "The vehicle must be `RETAIL_LISTED` — a request against a vehicle in any other lifecycle state is rejected with `ERR_VEHICLE_NOT_LISTED` — and its `hold_status` must be `NONE`; a request against an already-held vehicle is rejected with `ERR_VEHICLE_ALREADY_HELD`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_referential_vs_fiscal_occ_conflict
        """
        (store, dal, staff, cust1, cust2, veh_a, tr1, pre_hold_version) = (
            self._vehicle_under_hold_with_stale_version())
        resp = api_client.create_transfer_request(
            create_transfer_request_payload(veh_a["id"], cust1["id"],
                                            dal["id"], pre_hold_version),
            make_customer_headers(cust1["id"]))
        assert resp.status_code == 409
        requests, meta = validate_paginated(
            api_client.list_vehicle_transfer_requests(
                veh_a["id"],
                make_store_manager_headers(staff["manager"]["id"])))
        assert len(requests) == 1
        assert requests[0]["id"] == tr1["id"]


class TestDispositionThresholdStrictlyGreater:
    def _appraised_vehicles_ef(self):
        """Two identical vehicles (book 500,000, year 2024, odo 20,000) at PHX;
        provisional basis 340,000 -> threshold 68,000."""
        store, staff, cust = _phx_full_staff()
        veh_e = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VEEEEEEEEEEEEEEEE",
                               make="Mazda", model="3", model_year=2024,
                               odometer_miles=20000, book_value_cents=500000)
        veh_f = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VFFFFFFFFFFFFFFFF",
                               make="Mazda", model="3", model_year=2024,
                               odometer_miles=20000, book_value_cents=500000)
        create_appraisal_for(veh_e["id"], cust["id"], staff["appraiser"]["id"])
        create_appraisal_for(veh_f["id"], cust["id"], staff["appraiser"]["id"])
        return store, staff, cust, veh_e, veh_f

    def _inspect_with_single_line(self, vehicle_id, inspector_id, cost):
        insp = open_inspection_for(vehicle_id, inspector_id)
        item = add_line_item_for(insp["id"], inspector_id,
                                 category="MECHANICAL", cost_cents=cost)
        approve_line_item_for(insp["id"], item["id"], inspector_id)
        return insp

    def test_threshold_exact_equality_stays_retail(self):
        """PRD §3.2: "If the inspection's `estimated_repair_total_cents` is **strictly greater** than that threshold, the disposition is `WHOLESALE`; otherwise (including exact equality with the threshold) it is `RETAIL`."
        PRD §3.2: "A `RETAIL` disposition also assigns the vehicle's `condition_grade`: `A` when the estimated repair total is exactly zero, `B` when it is positive but no more than half the threshold (rounded down), and `C` otherwise. The vehicle's `recon_cost_total_cents` is set to the inspection's `estimated_repair_total_cents`, the vehicle moves to `RECON`, and the sourcing appraisal is activated"

        Design: Difficulty/boundary_precision_check/disposition_threshold_strictly_greater
        """
        store, staff, cust, veh_e, veh_f = self._appraised_vehicles_ef()
        insp_e = self._inspect_with_single_line(
            veh_e["id"], staff["inspector"]["id"], 68000)
        insp_e = complete_inspection_for(insp_e["id"],
                                         staff["inspector"]["id"])
        assert insp_e["disposition"] == "RETAIL"

        veh_e = get_success_data(api_client.get_vehicle(
            veh_e["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_e["lifecycle_status"] == "RECON"
        # 68,000 > floor(68,000 / 2) = 34,000 -> grade C.
        assert veh_e["condition_grade"] == "C"

    def test_one_cent_over_threshold_forces_wholesale(self):
        """PRD §3.2: "If the inspection's `estimated_repair_total_cents` is **strictly greater** than that threshold, the disposition is `WHOLESALE`; otherwise (including exact equality with the threshold) it is `RETAIL`."
        PRD §3.2: "A `WHOLESALE` disposition instead sets `condition_grade` to `WHOLESALE_ONLY` and moves the vehicle to `WHOLESALE_PENDING`"

        Design: Difficulty/boundary_precision_check/disposition_threshold_strictly_greater
        """
        store, staff, cust, veh_e, veh_f = self._appraised_vehicles_ef()
        insp_f = self._inspect_with_single_line(
            veh_f["id"], staff["inspector"]["id"], 68001)
        insp_f = complete_inspection_for(insp_f["id"],
                                         staff["inspector"]["id"])
        assert insp_f["disposition"] == "WHOLESALE"

        veh_f = get_success_data(api_client.get_vehicle(
            veh_f["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh_f["lifecycle_status"] == "WHOLESALE_PENDING"
        assert veh_f["condition_grade"] == "WHOLESALE_ONLY"


class TestReturnWindowDaySevenExactly:
    def _completed_sale_and_open_return(self):
        store, staff, cust = _phx_full_staff()
        staff["finance"] = create_associate(store["id"], "FINANCE",
                                            "Finance One")
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh_a, cust, staff["sales"])
        sale = get_success_data(api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        ret = get_success_data(api_client.create_return(
            create_return_payload(sale["id"], odometer_at_return=30100),
            make_customer_headers(cust["id"])))
        return store, staff, cust, veh_a, sale, ret

    def test_approve_at_exactly_seven_days_succeeds(self):
        """PRD §3.7: "Approval requires that `opened_at` fall within seven days (`RETURN_WINDOW_DAYS`) of the sale's `completed_at`; a return opened later is rejected with `ERR_RETURN_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/return_window_day_seven_exactly
        """
        store, staff, cust, veh_a, sale, ret = (
            self._completed_sale_and_open_return())
        set_clock("2026-09-08T00:00:00Z")
        ret = get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert ret["status"] == "APPROVED"

    def test_settle_after_window_still_succeeds_and_refunds_in_full(self):
        """PRD §3.7: "Approval requires that `opened_at` fall within seven days (`RETURN_WINDOW_DAYS`) of the sale's `completed_at`; a return opened later is rejected with `ERR_RETURN_WINDOW_CLOSED`."
        PRD §3.7: "Settlement, also by a `StoreManager`, is restricted to the store whose books carried the sale — the acting manager's store must equal the sale's `store_id`."

        Design: Difficulty/boundary_precision_check/return_window_day_seven_exactly
        """
        store, staff, cust, veh_a, sale, ret = (
            self._completed_sale_and_open_return())
        set_clock("2026-09-08T00:00:00Z")
        ret = get_success_data(api_client.approve_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        set_clock("2026-09-08T00:00:01Z")
        ret = get_success_data(api_client.settle_return(
            ret["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert ret["status"] == "SETTLED"
        # 100 extra miles are within the 400-mile cap -> no deduction.
        assert ret["refund_total_cents"] == 1797600
