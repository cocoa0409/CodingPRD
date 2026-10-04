"""Corner tests: no-haggle price enforcement, repricing-aware
completion, FK reverse reachability, optimistic concurrency on transfer
creation, clock-driven aging, derived field reconciliation, and immediate
cascade visibility."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_customer_headers,
    make_sales_associate_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_vehicle_retail_listed,
    create_vehicle_appraised, create_appraisal_for, create_sale_for,
    create_transfer_request_payload, create_transfer_for,
    open_inspection_for, add_line_item_for, reject_line_item_for,
    get_vehicle_version, store_ledger_entries,
    assert_sale, assert_transfer_request,
)


def _phx_staff(with_sales=False):
    set_clock("2026-09-01T00:00:00Z")
    store = create_store()
    staff = {
        "manager": create_associate(store["id"], "MANAGER", "Manager One"),
        "appraiser": create_associate(store["id"], "APPRAISER", "Appraiser One"),
        "inspector": create_associate(store["id"], "INSPECTOR", "Inspector One"),
    }
    if with_sales:
        staff["sales"] = create_associate(store["id"], "SALES", "Sales One")
    cust = create_customer(email="c1@x.com")
    return store, staff, cust


class TestSaleCreationSnapshotsNoHagglePriceAndIgnoresClientPrice:
    def test_client_supplied_price_rejected_and_snapshot_taken(self):
        """PRD §3.5: "The sale begins `PENDING_FINANCE` with `sale_price_cents` taken from the vehicle's `current_list_price_cents` — never client-supplied — and `amount_due_cents` equal to `sale_price_cents` minus `trade_in_credit_cents`, floored at zero."
        PRD §3.3: "This is the no-haggle price: it is system-computed, never negotiable, and never supplied by a client."

        Design: Corner/endpoints/sale_creation_snapshots_no_haggle_price_and_ignores_client_price
        """
        store, staff, cust = _phx_staff(with_sales=True)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        assert veh["current_list_price_cents"] == 1797600

        resp = api_client.create_sale(
            {"vehicle_id": veh["id"], "customer_id": cust["id"],
             "associate_id": staff["sales"]["id"], "sale_price_cents": 1},
            make_sales_associate_headers(staff["sales"]["id"]))
        # PRD §3.5 pins "never client-supplied" (the server must not use the
        # value) but does not say the request is rejected — a faithful
        # implementation may ignore the field. Accept either outcome; if the
        # sale was created it stands in for the one below.
        sale = None
        if resp.status_code < 300:
            sale = resp.json()["data"]
            assert sale["sale_price_cents"] == 1797600
        else:
            validate_error(resp, ApiErrorId.ERR_VALIDATION)

        if sale is None:
            sale = create_sale_for(veh, cust, staff["sales"])
        assert_sale(sale)
        assert sale["sale_price_cents"] == 1797600
        assert sale["trade_in_credit_cents"] == 0
        assert sale["amount_due_cents"] == 1797600
        assert sale["status"] == "PENDING_FINANCE"


class TestSaleCompletionUsesCurrentPriceNotSnapshot:
    def test_completion_recomputes_after_markdown(self):
        """PRD §3.5: "The `sale_price_cents` is recomputed from the vehicle's `current_list_price_cents` at completion time."
        PRD §3.5: "A `SALE_REVENUE` ledger entry of `sale_price_cents` posts at the sale store."

        Design: Corner/endpoints/sale_completion_uses_current_price_not_snapshot
        """
        store, staff, cust = _phx_staff(with_sales=True)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh, cust, staff["sales"])
        assert sale["sale_price_cents"] == 1797600

        set_clock("2026-10-01T00:00:00Z")
        mgr_headers = make_store_manager_headers(staff["manager"]["id"])
        version = get_vehicle_version(veh["id"], mgr_headers)
        pe = get_success_data(api_client.create_pricing_event(
            veh["id"], {"expected_vehicle_version": version}, mgr_headers))
        assert pe["new_price_cents"] == 1743672

        sale = get_success_data(api_client.complete_sale(
            sale["id"],
            make_sales_associate_headers(staff["sales"]["id"])))
        assert_sale(sale)
        assert sale["sale_price_cents"] == 1743672
        assert sale["amount_due_cents"] == 1743672

        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        revenues = [e for e in entries
                    if e["ref_id"] == sale["id"]
                    and e["entry_kind"] == "SALE_REVENUE"]
        assert len(revenues) == 1
        assert revenues[0]["amount_cents"] == 1743672


class TestReverseReachabilityFilteredLists:
    def test_fk_reverse_lookups_filter_correctly(self):
        """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
        PRD §4: "| GET | `/v1/vehicles` | List vehicles with filters | PlatformAdmin, StoreManager, Appraiser, ReconditioningInspector, SalesAssociate, FinanceManager, AuctionManager, Customer |"
        PRD §4: "| GET | `/v1/appraisals` | List appraisals | PlatformAdmin, StoreManager, Appraiser, SalesAssociate |"
        PRD §4: "| GET | `/v1/transfer-requests` | List transfer requests | PlatformAdmin, StoreManager, SalesAssociate, Customer |"

        Design: Corner/endpoints/reverse_reachability_filtered_lists
        """
        store, staff, cust = _phx_staff()
        veh_a = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VAAAAAAAAAAAAAAAA")
        veh_b = create_vehicle(store["id"], staff["manager"]["id"],
                               vin="VBBBBBBBBBBBBBBBB", make="Toyota",
                               model="Corolla", model_year=2020,
                               odometer_miles=95000, book_value_cents=800000)
        appr = create_appraisal_for(veh_a["id"], cust["id"],
                                    staff["appraiser"]["id"])
        mgr_headers = make_store_manager_headers(staff["manager"]["id"])
        ap_headers = make_appraiser_headers(staff["appraiser"]["id"])

        vehicles, meta = validate_paginated(api_client.list_vehicles(
            mgr_headers, params={"current_store_id": store["id"]}))
        assert len(vehicles) == 2
        assert meta["total_count"] == 2

        appraisals, meta = validate_paginated(api_client.list_appraisals(
            ap_headers, params={"customer_id": cust["id"]}))
        assert len(appraisals) == 1
        assert appraisals[0]["id"] == appr["id"]

        appraisals, meta = validate_paginated(api_client.list_appraisals(
            ap_headers, params={"appraiser_id": staff["appraiser"]["id"]}))
        assert len(appraisals) == 1
        assert appraisals[0]["id"] == appr["id"]

        transfers, meta = validate_paginated(api_client.list_transfer_requests(
            mgr_headers, params={"from_store_id": store["id"]}))
        assert transfers == []
        assert meta["total_count"] == 0


class TestOccStaleVersionOnTransferCreate:
    def test_recreate_with_stale_version_rejected_then_fresh_succeeds(self):
        """PRD §2.7: "Creating a customer transfer request requires the request body to carry `expected_vehicle_version` holding the `version` of the target `Vehicle` as the client last observed it. If the vehicle's current `version` no longer matches — because another writer has since mutated the vehicle (a repricing run, a hold placement, a store move from a delivered transfer) — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the vehicle's availability and price."
        PRD §3.4: "an optional `supersedes_request_id` chaining a re-booking after a previously cancelled request on the same vehicle"

        Design: Corner/cross_cutting_layers/occ_stale_version_on_transfer_create
        """
        store, staff, cust = _phx_staff()
        dal = create_store(store_code="DAL-01", display_name="Dallas",
                           region="CENTRAL")
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        cust_headers = make_customer_headers(cust["id"])

        v0 = get_vehicle_version(veh["id"], cust_headers)
        tr1 = get_success_data(api_client.create_transfer_request(
            create_transfer_request_payload(veh["id"], cust["id"],
                                            dal["id"], v0),
            cust_headers))
        get_success_data(api_client.cancel_transfer_request(
            tr1["id"], cust_headers))

        resp = api_client.create_transfer_request(
            create_transfer_request_payload(
                veh["id"], cust["id"], dal["id"], v0,
                supersedes_request_id=tr1["id"]),
            cust_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        v1 = get_vehicle_version(veh["id"], cust_headers)
        tr2 = get_success_data(api_client.create_transfer_request(
            create_transfer_request_payload(
                veh["id"], cust["id"], dal["id"], v1,
                supersedes_request_id=tr1["id"]),
            cust_headers))
        assert_transfer_request(tr2)
        assert tr2["supersedes_request_id"] == tr1["id"]
        assert tr2["status"] == "REQUESTED"

        veh = get_success_data(api_client.get_vehicle(veh["id"],
                                                      cust_headers))
        assert veh["hold_status"] == "TRANSFER_HOLD"


class TestScheduledClockDrivesDaysInInventory:
    def test_days_in_inventory_derived_from_logical_clock(self):
        """PRD §2.5: "Before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time."
        PRD §3.1: "Its `days_in_inventory` is derived, never stored as input: it is the whole number of days elapsed since `inventory_acquired_at`, recomputed on every read and on every repricing run."

        Design: Corner/cross_cutting_layers/scheduled_clock_drives_days_in_inventory
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        mgr_headers = make_store_manager_headers(mgr["id"])
        veh = create_vehicle(store["id"], mgr["id"],
                             vin="VAAAAAAAAAAAAAAAA")

        veh = get_success_data(api_client.get_vehicle(veh["id"], mgr_headers))
        assert veh["days_in_inventory"] == 0
        assert veh["inventory_acquired_at"] == "2026-09-01T00:00:00Z"

        set_clock("2026-09-30T00:00:00Z")
        veh = get_success_data(api_client.get_vehicle(veh["id"], mgr_headers))
        assert veh["days_in_inventory"] == 29
        assert veh["inventory_acquired_at"] == "2026-09-01T00:00:00Z"

        set_clock("2026-10-01T00:00:00Z")
        veh = get_success_data(api_client.get_vehicle(veh["id"], mgr_headers))
        assert veh["days_in_inventory"] == 30
        assert veh["inventory_acquired_at"] == "2026-09-01T00:00:00Z"


class TestDerivedFieldReconciliationEstimatedRepairTotal:
    def test_estimated_total_tracks_line_item_mutations(self):
        """PRD §3.2: "Each line begins `PROPOSED` and is individually approved or rejected; both actions recompute the inspection's `estimated_repair_total_cents`, which is always the sum of `cost_cents` over line items whose `line_status` is not `REJECTED`."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_estimated_repair_total
        """
        store, staff, cust = _phx_staff()
        veh, appr = create_vehicle_appraised(store, staff, cust,
                                             vin="VAAAAAAAAAAAAAAAA")
        insp = open_inspection_for(veh["id"], staff["inspector"]["id"])
        ins_headers = make_inspector_headers(staff["inspector"]["id"])

        li1 = add_line_item_for(insp["id"], staff["inspector"]["id"],
                                category="COSMETIC", cost_cents=12000)
        li2 = add_line_item_for(insp["id"], staff["inspector"]["id"],
                                category="BODY", cost_cents=9000)
        insp = get_success_data(api_client.get_inspection(insp["id"],
                                                          ins_headers))
        assert insp["estimated_repair_total_cents"] == 21000

        reject_line_item_for(insp["id"], li2["id"], staff["inspector"]["id"])
        insp = get_success_data(api_client.get_inspection(insp["id"],
                                                          ins_headers))
        assert insp["estimated_repair_total_cents"] == 12000


class TestImmediateConsistencyCascadeVisibleInSameRead:
    def test_complete_response_and_immediate_reads_agree(self):
        """PRD §3.5: "Completion stamps `completed_at`, moves the sale to `COMPLETED`, and fires a multi-hop cascade:"
        PRD §3.5: "The vehicle moves from `RETAIL_LISTED` to `SOLD`."
        PRD §2.4: "`version`: an integer incremented by exactly one on every mutation, serving as the basis for optimistic concurrency control."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_read
        """
        store, staff, cust = _phx_staff(with_sales=True)
        veh, _appr, _insp = create_vehicle_retail_listed(
            store, staff, cust, vin="VAAAAAAAAAAAAAAAA")
        sale = create_sale_for(veh, cust, staff["sales"])
        mgr_headers = make_store_manager_headers(staff["manager"]["id"])
        veh_pre = get_success_data(api_client.get_vehicle(veh["id"],
                                                          mgr_headers))

        sale = get_success_data(api_client.complete_sale(
            sale["id"],
            make_sales_associate_headers(staff["sales"]["id"])))
        assert sale["status"] == "COMPLETED"

        veh = get_success_data(api_client.get_vehicle(veh["id"],
                                                      mgr_headers))
        assert veh["lifecycle_status"] == "SOLD"
        assert veh["version"] == veh_pre["version"] + 1

        entries = store_ledger_entries(store["id"], staff["manager"]["id"])
        revenue = [e for e in entries
                   if e["ref_id"] == sale["id"]
                   and e["entry_kind"] == "SALE_REVENUE"]
        assert len(revenue) == 1
        assert revenue[0]["amount_cents"] == 1797600
        commission = [e for e in entries
                      if e["ref_id"] == sale["id"]
                      and e["entry_kind"] == "COMMISSION_ACCRUAL"]
        assert len(commission) == 1
        assert commission[0]["amount_cents"] == 25000
