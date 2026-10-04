"""Recall cascades, allocation ETA projections, and store dock capacity
(PRD §3.2, §3.3, §3.10)."""
from test_helpers import (
    ApiErrorId,
    create_active_item,
    create_container_payload,
    create_recall_payload,
    get_success_data,
    make_active_recall,
    make_issued_po,
    make_planned_allocation,
    make_store,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

PM = TEST_USERS["purchasing_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
IP = TEST_USERS["inventory_planner_headers"]


class TestRecallCascade:

    def test_recall_activation_quarantine_block_chain(self, api):
        """PRD §3.10: "First, the item's `lifecycle_status` moves from `ACTIVE`
        to `QUARANTINED`, its `open_recall_count` increments by one, and its
        `version` increments. Second — for `STOP_SALE` or `HAZARD` severities
        only — every non-terminal StoreAllocation for the item moves to
        `BLOCKED`, committed quantities return to their containers'
        `unallocated_quantities`"

        Design: Difficulty/transitive_cascade/recall_activation_quarantine_block_chain
        """
        item = create_active_item(sku="RC1", unit_retail_cents=4000,
                                  member_price_cents=3600,
                                  floor_margin_pct=0.10)
        po = make_issued_po(item["id"], 10, 1500,
                            estimated_duty_cents=200,
                            estimated_freight_cents=300)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 10,
                                     container_number="C-RC"), LC))
        store = make_store([item["id"]], store_code="ST5",
                           market_tier="SECONDARY")
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 4)
        validate_success(api.commit_allocation(alloc["id"], cont["version"], IP))
        recall = get_success_data(api.create_recall(
            create_recall_payload(item["id"], "STOP_SALE",
                                  reason="cord fire risk"), CO))

        validate_success(api.activate_recall(recall["id"], CO))
        item_after = validate_success(api.get_item(item["id"], PM))
        assert item_after["lifecycle_status"] == "QUARANTINED"
        assert item_after["open_recall_count"] == 1
        alloc_after = validate_success(api.get_allocation(alloc["id"], IP))
        assert alloc_after["status"] == "BLOCKED"
        cont_after = validate_success(api.get_container(cont["id"], IP))
        assert cont_after["unallocated_quantities"][item["id"]] == 10

    def test_recall_notice_severity_does_not_block_allocations(self, api):
        """PRD §3.10: "Second — for `STOP_SALE` or `HAZARD` severities only —
        every non-terminal StoreAllocation for the item moves to `BLOCKED`"

        Design: Difficulty/transitive_cascade/recall_activation_quarantine_block_chain
        """
        item = create_active_item(sku="RC1N")
        po = make_issued_po(item["id"], 10, 1500)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 10), LC))
        store = make_store([item["id"]])
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 4)
        validate_success(api.commit_allocation(alloc["id"], cont["version"], IP))
        make_active_recall(item["id"], "NOTICE")
        item_after = validate_success(api.get_item(item["id"], PM))
        assert item_after["lifecycle_status"] == "QUARANTINED"
        alloc_after = validate_success(api.get_allocation(alloc["id"], IP))
        assert alloc_after["status"] == "COMMITTED"
        cont_after = validate_success(api.get_container(cont["id"], IP))
        assert cont_after["unallocated_quantities"][item["id"]] == 6


class TestContainerReceiveCascade:

    def test_container_receive_landed_cost_margin_chain(self, api):
        """PRD §3.2: "Second, every line item's
        `current_landed_unit_cost_cents` updates to the new final landed cost
        and each touched item's `version` increments." and PRD §3.1: "A
        violating reprice is rejected with `ERR_MARGIN_FLOOR_VIOLATION`"

        Design: Difficulty/transitive_cascade/container_receive_landed_cost_margin_chain
        """
        item = get_success_data(api.create_item(
            dict(sku="MG1", name="Vise", brand_tier="MID",
                 origin_country="IN", unit_retail_cents=3000,
                 member_price_cents=2800, floor_margin_pct=0.20,
                 lead_time_days=50, unit_weight_kg=6.0), PM))
        v0 = item["version"]
        get_success_data(api.activate_item(item["id"], PM))
        po = make_issued_po(item["id"], 4, 1000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 4,
                                     container_number="C-MG"), LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 2000, "actual_freight_cents": 0}, LC))

        item_after = validate_success(api.get_item(item["id"], PM))
        # final landed = 1000 + floor(2000/4) = 1500
        assert item_after["current_landed_unit_cost_cents"] == 1500
        assert item_after["version"] > v0
        po_after = validate_success(api.get_purchase_order(po["id"], PM))
        assert po_after["status"] == "RECEIVED"

        # hop-3: floor = 1500 * 1.20 = 1800; reprice to 1700 violates.
        resp = api.reprice_item(
            item["id"], {"unit_retail_cents": 1700,
                         "member_price_cents": 1700}, PM)
        validate_error(resp, ApiErrorId.ERR_MARGIN_FLOOR_VIOLATION)

    def test_container_receive_updates_landed_cost_from_null(self, api):
        """PRD §3.1: "`current_landed_unit_cost_cents` null until the first
        receipt of a container carrying the item establishes a landed cost" and
        PRD §3.2: "every line item's `current_landed_unit_cost_cents` updates
        to the new final landed cost"

        Design: Difficulty/transitive_cascade/container_receive_landed_cost_margin_chain
        """
        item = create_active_item(sku="MG2", unit_retail_cents=3000,
                                  member_price_cents=2800,
                                  floor_margin_pct=0.20)
        before = validate_success(api.get_item(item["id"], PM))
        assert before["current_landed_unit_cost_cents"] is None

        po = make_issued_po(item["id"], 2, 1000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 2), LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 100, "actual_freight_cents": 0}, LC))
        after = validate_success(api.get_item(item["id"], PM))
        # 1000 + floor(100/2) = 1050
        assert after["current_landed_unit_cost_cents"] == 1050


class TestCustomsQuarantineBlock:

    def test_customs_clearance_depends_on_recall_state(self, api):
        """PRD §3.2: "Clearance moves a container from `AT_PORT` to `CLEARED`,
        but clearance is blocked with `ERR_CONTAINER_QUARANTINE_BLOCK` while
        the container holds any line item whose `lifecycle_status` is
        `QUARANTINED` under an `ACTIVE` recall of severity `HAZARD`." and PRD
        §3.10: "when the count reaches zero and the item is `QUARANTINED`, the
        item returns to `ACTIVE` automatically."

        Design: Difficulty/cross_entity_state_dependency/customs_clearance_depends_on_recall_state
        """
        item = create_active_item(sku="XD2", unit_retail_cents=20000,
                                  member_price_cents=19000,
                                  floor_margin_pct=0.10)
        po = make_issued_po(item["id"], 3, 8000,
                            estimated_duty_cents=300,
                            estimated_freight_cents=300)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 3,
                                     container_number="C-XD2"), LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        recall = get_success_data(api.create_recall(
            create_recall_payload(item["id"], "HAZARD",
                                  reason="tank weld rupture"), CO))
        get_success_data(api.activate_recall(recall["id"], CO))

        resp = api.clear_customs_container(cont["id"], CO)
        validate_error(resp, ApiErrorId.ERR_CONTAINER_QUARANTINE_BLOCK)

        validate_success(api.close_recall(recall["id"], CO))
        item_after = validate_success(api.get_item(item["id"], PM))
        assert item_after["lifecycle_status"] == "ACTIVE"
        cleared = validate_success(api.clear_customs_container(cont["id"], CO))
        assert cleared["status"] == "CLEARED"

    def test_customs_hold_containers_also_blocked_by_hazard(self, api):
        """PRD §3.10: "containers sitting at `AT_PORT` or `CUSTOMS_HOLD` that
        hold the item cannot clear customs until the recall closes"

        Design: Difficulty/cross_entity_state_dependency/customs_clearance_depends_on_recall_state
        """
        item = create_active_item(sku="XD2H")
        po = make_issued_po(item["id"], 1, 8000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1), LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.hold_customs_container(cont["id"], CO))
        make_active_recall(item["id"], "HAZARD")
        resp = api.clear_customs_container(cont["id"], CO)
        validate_error(resp, ApiErrorId.ERR_CONTAINER_QUARANTINE_BLOCK)


class TestRecallCloseRestoration:

    def test_cascade_side_effects_recall_close_restores_item(self, api):
        """PRD §3.10: "Closing an `ACTIVE` recall decrements the item's
        `open_recall_count`; when the count reaches zero and the item is
        `QUARANTINED`, the item returns to `ACTIVE` automatically."

        Design: Corner/cross_cutting_layers/cascade_side_effects_recall_close_restores_item
        """
        item = create_active_item(sku="CC2")
        r1 = make_active_recall(item["id"], "NOTICE")
        r2 = make_active_recall(item["id"], "STOP_SALE")
        mid = validate_success(api.get_item(item["id"], PM))
        assert mid["open_recall_count"] == 2

        validate_success(api.close_recall(r1["id"], CO))
        after1 = validate_success(api.get_item(item["id"], PM))
        assert after1["open_recall_count"] == 1
        assert after1["lifecycle_status"] == "QUARANTINED"

        validate_success(api.close_recall(r2["id"], CO))
        after2 = validate_success(api.get_item(item["id"], PM))
        assert after2["open_recall_count"] == 0
        assert after2["lifecycle_status"] == "ACTIVE"


class TestAllocationEta:

    def test_allocation_eta_lead_time_vs_transfer(self, api):
        """PRD §3.3: "At creation the system stamps `eta_date`: while the
        container is `BOOKED` or `DEPARTED`, the expected store-delivery date
        is the current logical-clock date plus the item's `lead_time_days`;
        once the container has reached `AT_PORT`, `CUSTOMS_HOLD`, or `CLEARED`,
        the ETA is the current logical-clock date plus 7 days of inland
        transfer"

        Design: Corner/calculations/allocation_eta_lead_time_vs_transfer
        """
        item = create_active_item(sku="CALC4", unit_retail_cents=9000,
                                  member_price_cents=8500,
                                  lead_time_days=40)
        po = make_issued_po(item["id"], 4, 4000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 4,
                                     container_number="C-C4"), LC))
        store = make_store([item["id"]], store_code="ST-C4")
        set_clock("2026-09-10T00:00:00Z")
        a1 = make_planned_allocation(store["id"], cont["id"], item["id"], 1)
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        a2 = make_planned_allocation(store["id"], cont["id"], item["id"], 1)

        a1_after = validate_success(api.get_allocation(a1["id"], IP))
        a2_after = validate_success(api.get_allocation(a2["id"], IP))
        assert a1_after["eta_date"] == "2026-10-20"  # 09-10 + 40 lead days
        assert a2_after["eta_date"] == "2026-09-17"  # 09-10 + 7 transfer days


class TestStoreDockCapacity:

    def test_store_dock_capacity_equality_allowed(self, api):
        """PRD §3.3: "if that delivered-today total plus this container's
        committed quantity to the store exceeds the store's
        `receiving_capacity_units`, the entire receive is rejected with
        `ERR_STORE_DOCK_CAPACITY_EXCEEDED`. The comparison is strict — a total
        landing exactly on capacity is allowed."

        Design: Difficulty/boundary_precision_check/store_dock_capacity_equality_allowed
        """
        item = create_active_item(sku="BD2", unit_retail_cents=7000,
                                  member_price_cents=6500,
                                  floor_margin_pct=0.10)
        po = make_issued_po(item["id"], 5, 3000,
                            estimated_duty_cents=100,
                            estimated_freight_cents=100)
        c1 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 3,
                                     container_number="C-BD2-1"), LC))
        c2 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 2,
                                     container_number="C-BD2-2"), LC))
        store = make_store([item["id"]], store_code="ST9",
                           format="SMALL_FORMAT", market_tier="SECONDARY",
                           receiving_capacity_units=5)
        a1 = make_planned_allocation(store["id"], c1["id"], item["id"], 3)
        validate_success(api.commit_allocation(a1["id"], c1["version"], IP))
        a2 = make_planned_allocation(store["id"], c2["id"], item["id"], 2)
        validate_success(api.commit_allocation(a2["id"], c2["version"], IP))
        for c in (c1, c2):
            get_success_data(api.depart_container(c["id"], LC))
            get_success_data(api.arrive_port_container(c["id"], LC))
            get_success_data(api.clear_customs_container(c["id"], CO))
        validate_success(api.receive_container(
            c1["id"], {"actual_duty_cents": 100, "actual_freight_cents": 100}, LC))
        # 3 + 2 == capacity 5 -> allowed
        received = validate_success(api.receive_container(c2["id"], {}, LC))
        assert received["status"] == "RECEIVED"
        po_after = validate_success(api.get_purchase_order(po["id"], PM))
        assert po_after["status"] == "RECEIVED"

    def test_store_dock_capacity_over_capacity_rejected(self, api):
        """PRD §3.3: "if that delivered-today total plus this container's
        committed quantity to the store exceeds the store's
        `receiving_capacity_units`, the entire receive is rejected with
        `ERR_STORE_DOCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/store_dock_capacity_equality_allowed
        """
        item = create_active_item(sku="BD2X", unit_retail_cents=7000,
                                  member_price_cents=6500)
        po = make_issued_po(item["id"], 4, 3000)
        c1 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 2,
                                     container_number="C-BD2X-1"), LC))
        c2 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 2,
                                     container_number="C-BD2X-2"), LC))
        store = make_store([item["id"]], receiving_capacity_units=3)
        a1 = make_planned_allocation(store["id"], c1["id"], item["id"], 2)
        validate_success(api.commit_allocation(a1["id"], c1["version"], IP))
        a2 = make_planned_allocation(store["id"], c2["id"], item["id"], 2)
        validate_success(api.commit_allocation(a2["id"], c2["version"], IP))
        for c in (c1, c2):
            get_success_data(api.depart_container(c["id"], LC))
            get_success_data(api.arrive_port_container(c["id"], LC))
            get_success_data(api.clear_customs_container(c["id"], CO))
        validate_success(api.receive_container(
            c1["id"], {"actual_duty_cents": 0, "actual_freight_cents": 0}, LC))
        # 2 + 2 > 3 -> one unit past capacity -> rejected
        resp = api.receive_container(c2["id"], {}, LC)
        validate_error(resp, ApiErrorId.ERR_STORE_DOCK_CAPACITY_EXCEEDED)
        c2_after = validate_success(api.get_container(c2["id"], LC))
        assert c2_after["status"] == "CLEARED"

    def test_store_dock_daily_bucket_capacity(self, api):
        """PRD §3.3: "the system sums the quantities already delivered to that
        store on the same logical-clock date by containers received earlier
        that day; if that delivered-today total plus this container's committed
        quantity to the store exceeds the store's `receiving_capacity_units`,
        the entire receive is rejected with
        `ERR_STORE_DOCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/store_dock_daily_bucket_capacity
        """
        item = create_active_item(sku="TO2", unit_retail_cents=9000,
                                  member_price_cents=8500,
                                  floor_margin_pct=0.10)
        po = make_issued_po(item["id"], 9, 4000,
                            estimated_duty_cents=200,
                            estimated_freight_cents=200)
        c1 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 5,
                                     container_number="C-TO2-1"), LC))
        c2 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 4,
                                     container_number="C-TO2-2"), LC))
        store = make_store([item["id"]], store_code="ST12",
                           receiving_capacity_units=6)
        a1 = make_planned_allocation(store["id"], c1["id"], item["id"], 5)
        validate_success(api.commit_allocation(a1["id"], c1["version"], IP))
        a2 = make_planned_allocation(store["id"], c2["id"], item["id"], 4)
        validate_success(api.commit_allocation(a2["id"], c2["version"], IP))
        for c in (c1, c2):
            get_success_data(api.depart_container(c["id"], LC))
            get_success_data(api.arrive_port_container(c["id"], LC))
            get_success_data(api.clear_customs_container(c["id"], CO))
        set_clock("2026-11-03T08:00:00Z")
        validate_success(api.receive_container(
            c1["id"], {"actual_duty_cents": 200, "actual_freight_cents": 200}, LC))
        # 5 + 4 > 6 same day -> rejected
        resp = api.receive_container(c2["id"], {}, LC)
        validate_error(resp, ApiErrorId.ERR_STORE_DOCK_CAPACITY_EXCEEDED)
        # next day: bucket resets
        set_clock("2026-11-04T00:00:00Z")
        received = validate_success(api.receive_container(c2["id"], {}, LC))
        assert received["status"] == "RECEIVED"

    def test_store_dock_bucket_isolated_per_store(self, api):
        """PRD §3.3: "For each store with `COMMITTED` allocations on the
        receiving container, the system sums the quantities already delivered
        to that store on the same logical-clock date by containers received
        earlier that day" — the bucket is per store, so another store's
        deliveries do not consume this store's capacity.

        Design: Difficulty/resource_temporal_overlap/store_dock_daily_bucket_capacity
        """
        item = create_active_item(sku="TO2B", unit_retail_cents=9000,
                                  member_price_cents=8500)
        po = make_issued_po(item["id"], 6, 4000)
        c1 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 3,
                                     container_number="C-TO2B-1"), LC))
        c2 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 3,
                                     container_number="C-TO2B-2"), LC))
        s1 = make_store([item["id"]], store_code="ST12A",
                        receiving_capacity_units=3)
        s2 = make_store([item["id"]], store_code="ST12B",
                        receiving_capacity_units=3)
        a1 = make_planned_allocation(s1["id"], c1["id"], item["id"], 3)
        validate_success(api.commit_allocation(a1["id"], c1["version"], IP))
        a2 = make_planned_allocation(s2["id"], c2["id"], item["id"], 3)
        validate_success(api.commit_allocation(a2["id"], c2["version"], IP))
        for c in (c1, c2):
            get_success_data(api.depart_container(c["id"], LC))
            get_success_data(api.arrive_port_container(c["id"], LC))
            get_success_data(api.clear_customs_container(c["id"], CO))
        set_clock("2026-11-05T08:00:00Z")
        # Each store receives exactly at its own capacity: both succeed.
        r1 = validate_success(api.receive_container(
            c1["id"], {"actual_duty_cents": 0, "actual_freight_cents": 0}, LC))
        assert r1["status"] == "RECEIVED"
        r2 = validate_success(api.receive_container(c2["id"], {}, LC))
        assert r2["status"] == "RECEIVED"
