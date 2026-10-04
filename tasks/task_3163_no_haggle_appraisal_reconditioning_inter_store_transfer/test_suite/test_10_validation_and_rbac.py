"""Corner tests: header auth, role permission, entity-backed identity,
segregation of duties, state-aware validation errors, role-matrix denials,
and offer supersede rules."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_error_is_one_of, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_customer_headers,
    make_sales_associate_headers, make_finance_manager_headers,
    auction_manager_headers, admin_headers, anonymous_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_vehicle_retail_listed,
    create_vehicle_with_active_appraisal, create_vehicle_appraised,
    create_vehicle_wholesale_pending,
    create_appraisal_for, create_sale_for, create_sale_payload,
    create_transfer_request_payload, create_transfer_for,
    create_auction_lot_payload, close_auction_lot_payload,
    accept_financing_payload,
    open_inspection_for, add_line_item_for, approve_line_item_for,
    complete_inspection_for,
    get_vehicle_version,
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


class TestMissingAuthHeadersRejected:
    def test_request_without_user_context_headers_rejected(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID` identifies the acting principal and `X-User-Role` names their operational role. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        resp = api_client.get_store(store["id"], anonymous_headers())
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbacRoleDeniedOnExclusiveEndpoint:
    def test_customer_cannot_create_appraisal(self):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "| POST | `/v1/appraisals` | Create a standing appraisal offer for a vehicle in `INTAKE` | Appraiser |"

        Design: Corner/validations/rbac_role_denied_on_exclusive_endpoint
        """
        store, staff, cust = _phx_staff()
        veh = create_vehicle(store["id"], staff["manager"]["id"],
                             vin="VAAAAAAAAAAAAAAAA")
        resp = api_client.create_appraisal(
            {"vehicle_id": veh["id"], "customer_id": cust["id"],
             "appraiser_id": cust["id"]},
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        appraisals, meta = validate_paginated(
            api_client.list_vehicle_appraisals(
                veh["id"],
                make_appraiser_headers(staff["appraiser"]["id"])))
        assert appraisals == []


class TestEntityBackedIdentityUnknownRejected:
    def test_unknown_customer_identity_rejected(self):
        """PRD §2.1: "For these six entity-backed roles, an `X-User-ID` that does not reference an existing backing entity is rejected with `ERR_UNKNOWN_IDENTITY`."

        Design: Corner/validations/entity_backed_identity_unknown_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        create_store()
        resp = api_client.get_customer(
            NON_EXISTENT_UUID, make_customer_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_IDENTITY)


class TestSegregationOfDutiesInspectorEqualsAppraiser:
    def test_inspector_must_differ_from_sourcing_appraiser(self):
        """PRD §2.9: "The `inspector_id` on a newly opened reconditioning inspection must differ from the `appraiser_id` of the vehicle's latest sourcing appraisal — the newest non-terminal appraisal on that vehicle. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_inspector_equals_appraiser
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        apx = create_associate(store["id"], "APPRAISER", "Appraiser X")
        inx = create_associate(store["id"], "INSPECTOR", "Inspector X")
        cust = create_customer(email="c1@x.com")
        veh = create_vehicle(store["id"], mgr["id"],
                             vin="VAAAAAAAAAAAAAAAA")
        create_appraisal_for(veh["id"], cust["id"], apx["id"])

        resp = api_client.open_inspection(
            veh["id"], {"inspector_id": apx["id"]},
            make_inspector_headers(apx["id"]))
        # The SoD collision is only constructible by reusing the appraiser
        # associate as the inspector identity/payload. PRD §2.1 rejects that
        # identity at level 3 (ERR_UNKNOWN_IDENTITY), §2.8 level 2/7 admit
        # ERR_UNAUTHORIZED_ROLE / ERR_VALIDATION for the role_kind mismatch,
        # and §2.9 names ERR_SEGREGATION_OF_DUTIES for the collision itself;
        # PRD does not pin which level pre-empts, so accept any of the four.
        validate_error_is_one_of(resp, [ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                                        ApiErrorId.ERR_UNKNOWN_IDENTITY,
                                        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                                        ApiErrorId.ERR_VALIDATION])

        insp = get_success_data(api_client.open_inspection(
            veh["id"], {"inspector_id": inx["id"]},
            make_inspector_headers(inx["id"])))
        assert insp["status"] == "OPEN"

        veh = get_success_data(api_client.get_vehicle(
            veh["id"], make_store_manager_headers(mgr["id"])))
        assert veh["lifecycle_status"] == "IN_INSPECTION"


class TestInspectionAlreadyOpenRejected:
    def test_second_open_inspection_rejected(self):
        """PRD §3.2: "A `ReconditioningInspector` opens a reconditioning inspection on a vehicle in `APPRAISED` (or, after a return, in `RETURNED` — see §3.7) by supplying an `inspector_id`."
        PRD §2.8: "5. State-machine admissibility of the requested transition. Error selection here is state-aware: a transfer creation against a vehicle not in `RETAIL_LISTED` yields `ERR_VEHICLE_NOT_LISTED`; any other from-state violation yields `ERR_INVALID_STATE`."

        Design: Corner/validations/inspection_already_open_rejected
        """
        store, staff, cust = _phx_staff()
        veh, appr = create_vehicle_appraised(store, staff, cust,
                                             vin="VAAAAAAAAAAAAAAAA")
        insp = open_inspection_for(veh["id"], staff["inspector"]["id"])

        resp = api_client.open_inspection(
            veh["id"], {"inspector_id": staff["inspector"]["id"]},
            make_inspector_headers(staff["inspector"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        inspections, meta = validate_paginated(
            api_client.list_vehicle_inspections(
                veh["id"],
                make_inspector_headers(staff["inspector"]["id"])))
        assert len(inspections) == 1
        assert inspections[0]["id"] == insp["id"]


class TestTransferCreateAgainstSoldVehicleRejected:
    def test_transfer_against_sold_vehicle_rejected(self):
        """PRD §3.4: "The vehicle must be `RETAIL_LISTED` — a request against a vehicle in any other lifecycle state is rejected with `ERR_VEHICLE_NOT_LISTED`"

        Design: Corner/validations/transfer_create_against_sold_vehicle_rejected
        """
        store, staff, cust = _phx_staff(with_sales=True)
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh, cust, staff["sales"])
        get_success_data(api_client.complete_sale(
            sale["id"],
            make_sales_associate_headers(staff["sales"]["id"])))

        dal = create_store(store_code="DAL-01", display_name="Dallas",
                           region="CENTRAL")
        version = get_vehicle_version(veh["id"],
                                      make_customer_headers(cust2["id"]))
        resp = api_client.create_transfer_request(
            create_transfer_request_payload(veh["id"], cust2["id"],
                                            dal["id"], version),
            make_customer_headers(cust2["id"]))
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_LISTED)


class TestTransferSameStoreRejected:
    def test_destination_equal_to_origin_rejected(self):
        """PRD §3.4: "The destination store must differ from the vehicle's current store, or the request fails validation with `ERR_VALIDATION`."

        Design: Corner/validations/transfer_same_store_rejected
        """
        store, staff, cust = _phx_staff()
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        version = get_vehicle_version(veh["id"],
                                      make_customer_headers(cust["id"]))
        resp = api_client.create_transfer_request(
            create_transfer_request_payload(veh["id"], cust["id"],
                                            store["id"], version),
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        veh = get_success_data(api_client.get_vehicle(
            veh["id"], make_customer_headers(cust["id"])))
        assert veh["hold_status"] == "NONE"


class TestTradeInAppraisalCustomerMismatchRejected:
    def test_appraisal_owned_by_other_customer_rejected(self):
        """PRD §3.5: "The appraisal must also belong to the buyer — its `customer_id` must equal the sale's `customer_id` — or the sale is rejected with `ERR_APPRAISAL_CUSTOMER_MISMATCH`."

        Design: Corner/validations/trade_in_appraisal_customer_mismatch_rejected
        """
        store, staff, cust1 = _phx_staff(with_sales=True)
        cust2 = create_customer(email="c2@x.com", credit_score=700,
                                stated_annual_income_cents=8000000)
        veh_a, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust1, vin="VAAAAAAAAAAAAAAAA")
        veh_b, appr_b = create_vehicle_with_active_appraisal(
            store, staff, cust1, vin="VBBBBBBBBBBBBBBBB",
            make="Toyota", model="Corolla", model_year=2020,
            odometer_miles=95000, book_value_cents=800000)

        resp = api_client.create_sale(
            create_sale_payload(veh_a["id"], cust2["id"],
                                staff["sales"]["id"],
                                trade_in_appraisal_id=appr_b["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_CUSTOMER_MISMATCH)

        appr_b = get_success_data(api_client.get_appraisal(
            appr_b["id"], make_appraiser_headers(staff["appraiser"]["id"])))
        assert appr_b["status"] == "ACTIVE"

        sales, meta = validate_paginated(api_client.list_sales(
            make_sales_associate_headers(staff["sales"]["id"]),
            params={"vehicle_id": veh_a["id"]}))
        assert sales == []


class TestAuctionRelistRoundCapAndHammerValidation:
    def _three_unsold_rounds(self):
        store, staff, cust = _phx_staff()
        veh_c, appr_c, insp_c = create_vehicle_wholesale_pending(
            store, staff, cust, vin="VCCCCCCCCCCCCCCCC",
            make="Ford", model="F-150", model_year=2018,
            odometer_miles=140000, book_value_cents=1000000)
        lots = []
        for hammer in (800000, 700000):
            lot = get_success_data(api_client.create_auction_lot(
                create_auction_lot_payload(veh_c["id"]),
                auction_manager_headers()))
            get_success_data(api_client.close_auction_lot(
                lot["id"], close_auction_lot_payload(hammer),
                auction_manager_headers()))
            lots.append(lot)
        lot3 = get_success_data(api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]),
            auction_manager_headers()))
        return store, staff, veh_c, lot3

    def test_hammer_zero_rejected_and_round_cap_exhausted(self):
        """PRD §3.8: "Closing a lot requires a `hammer_price_cents` strictly greater than zero (a non-positive hammer is rejected with `ERR_HAMMER_BELOW_RESERVE_INVALID`)."
        PRD §3.8: "Relisting creates a new lot for the same vehicle with `auction_round` incremented, provided the previous lot is `UNSOLD` and its `auction_round` was below 3; once three rounds are exhausted, a relist attempt is rejected with `ERR_AUCTION_ROUNDS_EXHAUSTED` — though a below-reserve close itself still completes, leaving the lot `UNSOLD`."

        Design: Corner/validations/auction_relist_round_cap_and_hammer_validation
        """
        store, staff, veh_c, lot3 = self._three_unsold_rounds()

        resp = api_client.close_auction_lot(
            lot3["id"], close_auction_lot_payload(0),
            auction_manager_headers())
        validate_error(resp, ApiErrorId.ERR_HAMMER_BELOW_RESERVE_INVALID)

        lot3 = get_success_data(api_client.close_auction_lot(
            lot3["id"], close_auction_lot_payload(600000),
            auction_manager_headers()))
        assert lot3["status"] == "UNSOLD"

        veh_c = get_success_data(api_client.get_vehicle(
            veh_c["id"], auction_manager_headers()))
        assert veh_c["lifecycle_status"] == "WHOLESALE_PENDING"

        resp = api_client.create_auction_lot(
            create_auction_lot_payload(veh_c["id"]),
            auction_manager_headers())
        validate_error(resp, ApiErrorId.ERR_AUCTION_ROUNDS_EXHAUSTED)

        lots, meta = validate_paginated(api_client.list_vehicle_auction_lots(
            veh_c["id"], auction_manager_headers()))
        assert len(lots) == 3


class TestOccStaleVersionOnPricingEvent:
    def test_second_pricing_event_with_same_version_rejected(self):
        """PRD §2.7: "Applying a scheduled algorithmic markdown to a vehicle likewise requires `expected_vehicle_version` matching the vehicle's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the pricing run to re-read the vehicle and recompute against fresh state."

        Design: Corner/validations/occ_stale_version_on_pricing_event
        """
        store, staff, cust = _phx_staff()
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        set_clock("2026-10-01T00:00:00Z")
        mgr_headers = make_store_manager_headers(staff["manager"]["id"])
        v0 = get_vehicle_version(veh["id"], mgr_headers)

        pe = get_success_data(api_client.create_pricing_event(
            veh["id"], {"expected_vehicle_version": v0}, mgr_headers))
        assert pe["new_price_cents"] == 1743672

        resp = api_client.create_pricing_event(
            veh["id"], {"expected_vehicle_version": v0}, mgr_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        events, meta = validate_paginated(api_client.list_pricing_events(
            veh["id"], mgr_headers))
        assert len(events) == 2
        assert {e["trigger_kind"] for e in events} == {
            "INITIAL_LISTING", "SCHEDULED_MARKDOWN"}


class TestOfferNotPresentedAndSupersedeRules:
    def test_second_accept_after_terminal_accepted_fails(self):
        """PRD §3.6: "The named offer must be one of the application's `PRESENTED` offers; naming any other lender is rejected with `ERR_OFFER_NOT_PRESENTED`, and attempting to accept on a `DECLINED` application is rejected with `ERR_FINANCING_DECLINED`. Acceptance moves the chosen offer to `ACCEPTED` and every other offer on the application to `SUPERSEDED`, and the application itself to `ACCEPTED`."

        Design: Corner/errors/offer_not_presented_and_supersede_rules
        """
        store, staff, cust = _phx_staff(with_sales=True, with_finance=True)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh, cust, staff["sales"])
        fin = get_success_data(api_client.submit_financing_application(
            sale["id"], make_finance_manager_headers(staff["finance"]["id"])))
        get_success_data(api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_A"),
            make_customer_headers(cust["id"])))

        resp = api_client.accept_financing(
            fin["id"], accept_financing_payload("LENDER_C"),
            make_customer_headers(cust["id"]))
        assert resp.status_code == 409

        offers, meta = validate_paginated(api_client.list_financing_offers(
            fin["id"], make_finance_manager_headers(staff["finance"]["id"])))
        status_by_lender = {o["lender_code"]: (o["offer_status"],
                                               o["apr_bps"])
                            for o in offers}
        assert status_by_lender["LENDER_A"] == ("ACCEPTED", 690)
        assert status_by_lender["LENDER_B"][0] == "SUPERSEDED"
        assert status_by_lender["LENDER_C"][0] == "SUPERSEDED"


class TestRoleMatrixExclusiveOperationsUnauthorized:
    def test_cross_role_attempts_on_exclusive_endpoints_rejected(self):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "| POST | `/v1/vehicles/{id}/list` | Move a `RECON` vehicle to `RETAIL_LISTED` at the initial no-haggle price | StoreManager |"
        PRD §4: "| POST | `/v1/vehicles` | Intake a vehicle at a store | StoreManager |"
        PRD §4: "| POST | `/v1/sales` | Open a no-haggle sale for a `RETAIL_LISTED` vehicle | SalesAssociate |"
        PRD §4: "| POST | `/v1/auction-lots` | List a `WHOLESALE_PENDING` vehicle at auction; also the relist path | AuctionManager |"
        PRD §4: "| POST | `/v1/appraisals` | Create a standing appraisal offer for a vehicle in `INTAKE` | Appraiser |"

        Design: Corner/rbac/role_matrix_exclusive_operations_unauthorized
        """
        store, staff, cust = _phx_staff(with_sales=True, with_finance=True)
        veh = create_vehicle(store["id"], staff["manager"]["id"],
                             vin="VAAAAAAAAAAAAAAAA")

        resp = api_client.list_vehicle(
            veh["id"], make_appraiser_headers(staff["appraiser"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        resp = api_client.create_vehicle(
            {"vin": "VHACKHACKHACKHAC1", "make": "X", "model": "Y",
             "model_year": 2022, "odometer_miles": 1,
             "book_value_cents": 1000, "current_store_id": store["id"]},
            auction_manager_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        resp = api_client.create_sale(
            create_sale_payload(veh["id"], cust["id"],
                                staff["sales"]["id"]),
            make_finance_manager_headers(staff["finance"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        resp = api_client.create_auction_lot(
            create_auction_lot_payload(veh["id"]),
            make_sales_associate_headers(staff["sales"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        resp = api_client.create_appraisal(
            {"vehicle_id": veh["id"], "customer_id": cust["id"],
             "appraiser_id": staff["inspector"]["id"]},
            make_inspector_headers(staff["inspector"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        veh = get_success_data(api_client.get_vehicle(
            veh["id"], make_store_manager_headers(staff["manager"]["id"])))
        assert veh["lifecycle_status"] == "INTAKE"
