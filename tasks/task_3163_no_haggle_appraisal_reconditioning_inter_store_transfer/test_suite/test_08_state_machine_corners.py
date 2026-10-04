"""Corner tests: invalid state transitions, terminal lockdown,
precondition enforcement, idempotency, guarded transfer transitions, and
financing offer expiry."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_error_is_one_of, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_customer_headers,
    make_sales_associate_headers, make_finance_manager_headers,
    auction_manager_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_vehicle_retail_listed,
    create_vehicle_wholesale_pending, create_vehicle_with_active_appraisal,
    create_vehicle_appraised, create_appraisal_for, create_sale_for,
    create_transfer_request_payload, create_transfer_for,
    create_auction_lot_payload, close_auction_lot_payload,
    accept_financing_payload,
    open_inspection_for, add_line_item_for, approve_line_item_for,
    reject_line_item_for, complete_inspection_for, list_vehicle_for,
    get_vehicle_version,
    assert_vehicle, assert_appraisal,
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
    cust = create_customer(email="c1@x.com")
    return store, staff, cust


class TestVehicleInitialStateAndInvalidTransitionRejected:
    def test_list_and_pricing_event_from_intake_rejected(self):
        """PRD §3.3: "A `StoreManager` lists a vehicle that is in `RECON` with `hold_status` `NONE`."
        PRD §3.3: "A `StoreManager` applies a pricing event to a `RETAIL_LISTED` vehicle with `hold_status` `NONE`; the request must carry `expected_vehicle_version` per §2.7."
        PRD §2.8: "5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/vehicle_initial_state_and_invalid_transition_rejected
        """
        store, staff, cust = _phx_staff()
        veh = create_vehicle(store["id"], staff["manager"]["id"],
                             vin="VAAAAAAAAAAAAAAAA")
        mgr_headers = make_store_manager_headers(staff["manager"]["id"])

        resp = api_client.list_vehicle(veh["id"], mgr_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        version = get_vehicle_version(veh["id"], mgr_headers)
        resp = api_client.create_pricing_event(
            veh["id"], {"expected_vehicle_version": version}, mgr_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        veh = get_success_data(api_client.get_vehicle(veh["id"], mgr_headers))
        assert_vehicle(veh)
        assert veh["lifecycle_status"] == "INTAKE"
        assert veh["current_list_price_cents"] is None

        events, meta = validate_paginated(api_client.list_pricing_events(
            veh["id"], mgr_headers))
        assert events == []


class TestTerminalStateLockdownDisposedAndSettled:
    def _disposed_vehicle_c(self):
        store, staff, cust = _phx_staff()
        veh_c, appr_c, insp_c = create_vehicle_wholesale_pending(
            store, staff, cust, vin="VCCCCCCCCCCCCCCCC",
            make="Ford", model="F-150", model_year=2018,
            odometer_miles=140000, book_value_cents=1000000)
        lot = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]),
            auction_manager_headers()))
        lot = get_success_data(api_client.close_auction_lot(
            lot["id"], close_auction_lot_payload(900000),
            auction_manager_headers()))
        assert lot["status"] == "SOLD"
        veh_c = get_success_data(api_client.get_vehicle(
            veh_c["id"], auction_manager_headers()))
        assert veh_c["lifecycle_status"] == "DISPOSED"
        return store, staff, cust, veh_c, lot

    def test_disposed_vehicle_rejects_inspections_appraisals_lots(self):
        """PRD §3.8: "When the hammer price is at least the reserve, the lot becomes `SOLD`, an `AUCTION_PROCEEDS` entry of `hammer_price_cents` posts at the vehicle's current store, and the vehicle reaches its terminal state `DISPOSED`."
        PRD §3.2: "A `ReconditioningInspector` opens a reconditioning inspection on a vehicle in `APPRAISED` (or, after a return, in `RETURNED` — see §3.7) by supplying an `inspector_id`."
        PRD §2.8: "5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_disposed_and_settled
        """
        store, staff, cust, veh_c, lot = self._disposed_vehicle_c()

        resp = api_client.open_inspection(
            veh_c["id"], {"inspector_id": staff["inspector"]["id"]},
            make_inspector_headers(staff["inspector"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.create_appraisal(
            {"vehicle_id": veh_c["id"], "customer_id": cust["id"],
             "appraiser_id": staff["appraiser"]["id"]},
            make_appraiser_headers(staff["appraiser"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]),
            auction_manager_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.close_auction_lot(
            lot["id"], close_auction_lot_payload(950000),
            auction_manager_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        veh_c = get_success_data(api_client.get_vehicle(
            veh_c["id"], auction_manager_headers()))
        assert veh_c["lifecycle_status"] == "DISPOSED"


class TestInspectionCompleteWithProposedItemsRejected:
    def test_completion_blocked_until_all_lines_resolved(self):
        """PRD §3.2: "Completion is allowed only when no line item remains `PROPOSED`; otherwise the attempt is rejected with `ERR_LINE_ITEMS_UNRESOLVED`."
        PRD §3.2: "Each line begins `PROPOSED` and is individually approved or rejected; both actions recompute the inspection's `estimated_repair_total_cents`, which is always the sum of `cost_cents` over line items whose `line_status` is not `REJECTED`."
        PRD §3.2: "A `RETAIL` disposition also assigns the vehicle's `condition_grade`: `A` when the estimated repair total is exactly zero, `B` when it is positive but no more than half the threshold (rounded down), and `C` otherwise. The vehicle's `recon_cost_total_cents` is set to the inspection's `estimated_repair_total_cents`, the vehicle moves to `RECON`, and the sourcing appraisal is activated"
        PRD §3.2: "The final offer equals the provisional offer minus one half of the vehicle's `recon_cost_total_cents` (that is, fifty percent of the just-completed inspection's estimated repair total), again floored at five hundred dollars and rounded half-up to whole cents at the final step; `valid_until` is exactly seven days after `valid_from`."

        Design: Corner/state_machines/inspection_complete_with_proposed_items_rejected
        """
        store, staff, cust = _phx_staff()
        veh, appr = create_vehicle_appraised(store, staff, cust,
                                             vin="VAAAAAAAAAAAAAAAA")
        insp = open_inspection_for(veh["id"], staff["inspector"]["id"])
        li1 = add_line_item_for(insp["id"], staff["inspector"]["id"],
                                category="MECHANICAL", cost_cents=100000)
        li2 = add_line_item_for(insp["id"], staff["inspector"]["id"],
                                category="BODY", cost_cents=50000)
        approve_line_item_for(insp["id"], li1["id"],
                              staff["inspector"]["id"])

        resp = api_client.complete_inspection(
            insp["id"], make_inspector_headers(staff["inspector"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LINE_ITEMS_UNRESOLVED)

        insp = get_success_data(api_client.get_inspection(
            insp["id"], make_inspector_headers(staff["inspector"]["id"])))
        assert insp["status"] == "OPEN"

        reject_line_item_for(insp["id"], li2["id"], staff["inspector"]["id"])
        insp = complete_inspection_for(insp["id"], staff["inspector"]["id"])
        assert insp["disposition"] == "RETAIL"

        veh = get_success_data(api_client.get_vehicle(
            veh["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh["condition_grade"] == "B"
        assert veh["recon_cost_total_cents"] == 100000

        appr = get_success_data(api_client.get_appraisal(
            appr["id"], make_appraiser_headers(staff["appraiser"]["id"])))
        assert_appraisal(appr)
        assert appr["final_offer_cents"] == 1630000


class TestAppraisalVoidAndIdempotentSecondVoidRejected:
    def test_void_active_appraisal_once_then_replay_fails(self):
        """PRD §3.1: "An `Appraiser` may void an `ACTIVE` offer; a `StoreManager` may do the same. When the acting role is `Appraiser`, voiding is restricted to the appraiser who issued the offer — the acting `appraiser_id` must equal the appraisal's `appraiser_id` — whereas a `StoreManager` may void any active offer. Voiding sets the appraisal's `status` to `VOIDED`."
        PRD §2.8: "5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/appraisal_void_and_idempotent_second_void_rejected
        """
        store, staff, cust = _phx_staff()
        veh_b, appr_b = create_vehicle_with_active_appraisal(
            store, staff, cust, vin="VBBBBBBBBBBBBBBBB",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000)
        ap_headers = make_appraiser_headers(staff["appraiser"]["id"])

        appr_b = get_success_data(api_client.void_appraisal(
            appr_b["id"], ap_headers))
        assert appr_b["status"] == "VOIDED"

        resp = api_client.void_appraisal(appr_b["id"], ap_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        appr_b = get_success_data(api_client.get_appraisal(
            appr_b["id"], ap_headers))
        assert appr_b["final_offer_cents"] == 285500
        assert appr_b["valid_until"] == "2026-09-08T00:00:00Z"


class TestTransferShipRoleAndStoreScopingEnforced:
    def _paid_transfer_phx_to_dal(self):
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
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        tr = create_transfer_for(veh, cust2, dal["id"])
        get_success_data(api_client.pay_transfer_request(
            tr["id"], make_customer_headers(cust2["id"])))
        return store, dal, staff, mgr2, cust2, veh, tr

    def test_only_origin_manager_ships_and_only_destination_delivers(self):
        """PRD §3.4: "A `StoreManager` at the origin store ships the vehicle (`FEE_PAID` → `IN_TRANSIT`); a `StoreManager` at the destination store confirms delivery (`IN_TRANSIT` → `DELIVERED`), which moves the vehicle's `current_store_id` to the destination store, sets `hold_expires_at` to the delivery instant plus the destination store's `transfer_hold_days`, and increments the vehicle's `version`."

        Design: Corner/state_machines/transfer_ship_role_and_store_scoping_enforced
        """
        store, dal, staff, mgr2, cust2, veh, tr = (
            self._paid_transfer_phx_to_dal())
        mgr1_headers = make_store_manager_headers(staff["manager"]["id"])
        mgr2_headers = make_store_manager_headers(mgr2["id"])

        resp = api_client.ship_transfer_request(tr["id"], mgr2_headers)
        # PRD §3.4 names the origin/destination scoping rule without pinning
        # an error_id; §2.8 admits either the role-permission level
        # (ERR_UNAUTHORIZED_ROLE) or the state-check level (ERR_INVALID_STATE).
        validate_error_is_one_of(resp, [ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                                        ApiErrorId.ERR_INVALID_STATE])

        tr = get_success_data(api_client.ship_transfer_request(
            tr["id"], mgr1_headers))
        assert tr["status"] == "IN_TRANSIT"

        resp = api_client.deliver_transfer_request(tr["id"], mgr1_headers)
        validate_error_is_one_of(resp, [ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                                        ApiErrorId.ERR_INVALID_STATE])

        tr = get_success_data(api_client.get_transfer_request(
            tr["id"], make_customer_headers(cust2["id"])))
        assert tr["status"] == "IN_TRANSIT"


class TestFinancingOfferExpiryAutoTransition:
    def _presented_application(self):
        store, staff, cust = _phx_staff(with_sales=True, with_finance=True)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh, cust, staff["sales"])
        fin = get_success_data(api_client.submit_financing_application(
            sale["id"], make_finance_manager_headers(staff["finance"]["id"])))
        return store, staff, cust, veh, sale, fin

    def test_clock_past_three_days_expires_application_and_offers(self):
        """PRD §3.6: "Offers also age out: when the logical clock passes the application's `created_at` by more than three days, the application becomes `EXPIRED` and all its presented offers are superseded — after which an accept attempt fails the state check with `ERR_INVALID_STATE` (see §2.8)."

        Design: Corner/state_machines/financing_offer_expiry_auto_transition
        """
        store, staff, cust, veh, sale, fin = self._presented_application()
        set_clock("2026-09-04T00:00:01Z")

        fin = get_success_data(api_client.get_financing_application(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        assert fin["status"] == "EXPIRED"

        resp = api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_A"),
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        offers, meta = validate_paginated(api_client.list_financing_offers(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        assert len(offers) == 3
        assert all(o["offer_status"] == "SUPERSEDED" for o in offers)

    def test_expired_application_still_blocks_sale_completion(self):
        """PRD §3.6: "Offers also age out: when the logical clock passes the application's `created_at` by more than three days, the application becomes `EXPIRED` and all its presented offers are superseded — after which an accept attempt fails the state check with `ERR_INVALID_STATE` (see §2.8)."
        PRD §3.5: "A `SalesAssociate` completes a `PENDING_FINANCE` sale only when its financing posture is settled: either no financing application exists for the sale (a cash deal), or the application is `ACCEPTED`; completing with an application in any other state is rejected with `ERR_FINANCING_NOT_ACCEPTED`."

        Design: Corner/state_machines/financing_offer_expiry_auto_transition
        """
        store, staff, cust, veh, sale, fin = self._presented_application()
        set_clock("2026-09-04T00:00:01Z")

        resp = api_client.complete_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_ACCEPTED)

        sale = get_success_data(api_client.get_sale(
            sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "PENDING_FINANCE"
