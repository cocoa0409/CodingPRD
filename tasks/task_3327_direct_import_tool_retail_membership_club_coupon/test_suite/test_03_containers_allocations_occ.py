"""Container flow, allocation pool, and optimistic concurrency tests
(PRD §2.8, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_active_item,
    create_container_payload,
    get_success_data,
    make_container,
    make_issued_po,
    make_planned_allocation,
    make_store,
    validate_error,
    validate_success,
)


def _container_on_issued_po(api, item, quantity=10, unit_cost=500):
    po = make_issued_po(item["id"], quantity, unit_cost)
    cont = get_success_data(api.create_container(
        create_container_payload(po["id"], item["id"], quantity), _LC))
    return po, cont


# Role header shorthands resolved lazily from test_helpers at import.
from test_helpers import TEST_USERS  # noqa: E402

_LC = TEST_USERS["logistics_coordinator_headers"]
_CO = TEST_USERS["compliance_officer_headers"]
_IP = TEST_USERS["inventory_planner_headers"]


class TestCustomsHoldReleaseCycle:

    def test_customs_hold_release_cycle_reaches_cleared(
            self, api, compliance_officer_headers, logistics_coordinator_headers):
        """PRD §3.2: "a container at `AT_PORT` may be placed on `CUSTOMS_HOLD`
        and later released back to `AT_PORT` — that hold/release cycle may
        repeat, each pair counting as a full cycle."

        Design: Difficulty/non_linear_state_machine/container_customs_hold_release_cycle
        """
        item = create_active_item(sku="CYC1", unit_retail_cents=50000,
                                  member_price_cents=47000,
                                  floor_margin_pct=0.10, lead_time_days=60,
                                  unit_weight_kg=50.0)
        po = make_issued_po(item["id"], 2, 20000,
                            estimated_duty_cents=1000,
                            estimated_freight_cents=2000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 2,
                                     container_number="C-CYC"),
            logistics_coordinator_headers))
        get_success_data(api.depart_container(cont["id"], logistics_coordinator_headers))
        get_success_data(api.arrive_port_container(cont["id"], logistics_coordinator_headers))

        # Two full hold/release cycles.
        for _ in range(2):
            held = validate_success(api.hold_customs_container(
                cont["id"], compliance_officer_headers))
            assert held["status"] == "CUSTOMS_HOLD"
            released = validate_success(api.release_customs_container(
                cont["id"], compliance_officer_headers))
            assert released["status"] == "AT_PORT"

        cleared = validate_success(api.clear_customs_container(
            cont["id"], compliance_officer_headers))
        assert cleared["status"] == "CLEARED"
        # version: 1 (create) + depart + arrive + 2*(hold+release) + clear = 8
        assert cleared["version"] == 8, (
            f"Expected version 8 after 7 transition mutations, got {cleared['version']}")

    def test_customs_hold_release_cycle_state_not_consumed(
            self, api, compliance_officer_headers, logistics_coordinator_headers):
        """PRD §3.2: "that hold/release cycle may repeat, each pair counting as
        a full cycle." A single cycle still leaves the container able to
        progress to CLEARED.

        Design: Difficulty/non_linear_state_machine/container_customs_hold_release_cycle
        """
        item = create_active_item(sku="CYC1B")
        po = make_issued_po(item["id"], 1, 1000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1),
            logistics_coordinator_headers))
        get_success_data(api.depart_container(cont["id"], logistics_coordinator_headers))
        get_success_data(api.arrive_port_container(cont["id"], logistics_coordinator_headers))
        validate_success(api.hold_customs_container(cont["id"], compliance_officer_headers))
        validate_success(api.release_customs_container(cont["id"], compliance_officer_headers))
        cleared = validate_success(api.clear_customs_container(
            cont["id"], compliance_officer_headers))
        assert cleared["status"] == "CLEARED"


class TestAllocationCommitContainerState:

    def test_allocation_commit_depends_on_container_state(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §3.3: "the container must be `BOOKED` or `DEPARTED`, otherwise
        `ERR_CONTAINER_NOT_ALLOCATABLE`"

        Design: Difficulty/cross_entity_state_dependency/allocation_commit_depends_on_container_state
        """
        item = create_active_item(sku="XD1")
        po = make_issued_po(item["id"], 5, 12000,
                            estimated_duty_cents=500,
                            estimated_freight_cents=500)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 5,
                                     container_number="C-XD1"),
            logistics_coordinator_headers))
        cont_v = cont["version"]
        store = make_store([item["id"]], store_code="ST10")
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 2)
        get_success_data(api.depart_container(cont["id"], logistics_coordinator_headers))
        get_success_data(api.arrive_port_container(cont["id"], logistics_coordinator_headers))

        resp = api.commit_allocation(alloc["id"], cont_v, inventory_planner_headers)
        validate_error(resp, ApiErrorId.ERR_CONTAINER_NOT_ALLOCATABLE)

        alloc_after = validate_success(
            api.get_allocation(alloc["id"], inventory_planner_headers))
        assert alloc_after["status"] == "PLANNED"
        cont_after = validate_success(
            api.get_container(cont["id"], inventory_planner_headers))
        assert cont_after["unallocated_quantities"][item["id"]] == 5

    def test_allocation_commit_from_booked_succeeds(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §3.3: "the container must be `BOOKED` or `DEPARTED`, otherwise
        `ERR_CONTAINER_NOT_ALLOCATABLE`" — from BOOKED the same commit succeeds.

        Design: Difficulty/cross_entity_state_dependency/allocation_commit_depends_on_container_state
        """
        item = create_active_item(sku="XD1B")
        po = make_issued_po(item["id"], 5, 12000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 5),
            logistics_coordinator_headers))
        store = make_store([item["id"]])
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 2)
        committed = validate_success(api.commit_allocation(
            alloc["id"], cont["version"], inventory_planner_headers))
        assert committed["status"] == "COMMITTED"
        cont_after = validate_success(
            api.get_container(cont["id"], inventory_planner_headers))
        assert cont_after["unallocated_quantities"][item["id"]] == 3


class TestOptimisticConcurrency:

    def test_err_stale_version_occ_conflict(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §2.8: "If the container's current `version` differs from
        `expected_container_version` — for example because another commit or
        decommit on the same container legitimately moved the shared
        unallocated pool forward — the commit is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        container before retrying."

        Design: Corner/errors/err_stale_version_occ_conflict
        """
        item = create_active_item(sku="ER2")
        po = make_issued_po(item["id"], 6, 1000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 6,
                                     container_number="C-ER2"),
            logistics_coordinator_headers))
        v0 = cont["version"]
        store = make_store([item["id"]], store_code="ST-ER2")
        a1 = make_planned_allocation(store["id"], cont["id"], item["id"], 3)
        a2 = make_planned_allocation(store["id"], cont["id"], item["id"], 3)
        validate_success(api.commit_allocation(a1["id"], v0, inventory_planner_headers))

        resp = api.commit_allocation(a2["id"], v0, inventory_planner_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_container(cont["id"], inventory_planner_headers))
        committed = validate_success(api.commit_allocation(
            a2["id"], fresh["version"], inventory_planner_headers))
        assert committed["status"] == "COMMITTED"
        cont_after = validate_success(
            api.get_container(cont["id"], inventory_planner_headers))
        assert cont_after["unallocated_quantities"][item["id"]] == 0

    def test_occ_commit_happy_path_version_bump(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §3.3: "A successful commit moves the allocation to `COMMITTED`,
        decrements the container's `unallocated_quantities` entry by the
        committed quantity, and increments the container's `version`" and
        "Decommitting moves an allocation from `COMMITTED` back to `PLANNED`,
        returns its quantity to the pool, and increments the container's
        `version`"

        Design: Corner/cross_cutting_layers/occ_commit_happy_path_version_bump
        """
        item = create_active_item(sku="CC1")
        po = make_issued_po(item["id"], 4, 500)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 4,
                                     container_number="C-CC1"),
            logistics_coordinator_headers))
        v0 = cont["version"]
        store = make_store([item["id"]], store_code="ST-CC1")
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 1)
        validate_success(api.commit_allocation(alloc["id"], v0, inventory_planner_headers))
        v1 = validate_success(api.get_container(cont["id"], inventory_planner_headers))["version"]
        assert v1 == v0 + 1
        validate_success(api.decommit_allocation(alloc["id"], inventory_planner_headers))
        v2 = validate_success(api.get_container(cont["id"], inventory_planner_headers))["version"]
        assert v2 == v0 + 2


class TestContainerPoolConservation:

    def test_container_pool_conserved_under_commit_decommit(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §3.3: "Decommitting moves an allocation from `COMMITTED` back to
        `PLANNED`, returns its quantity to the pool, and increments the
        container's `version`; the `PLANNED` ↔ `COMMITTED` cycle may repeat."

        Design: Difficulty/compensating_invariant/container_pool_conserved_under_commit_decommit
        """
        item = create_active_item(sku="CI1", unit_retail_cents=45000,
                                  member_price_cents=43000,
                                  floor_margin_pct=0.10)
        po = make_issued_po(item["id"], 5, 20000,
                            estimated_duty_cents=500,
                            estimated_freight_cents=500)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 5,
                                     container_number="C-CI1"),
            logistics_coordinator_headers))
        store = make_store([item["id"]], store_code="ST13")
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 2)
        validate_success(api.commit_allocation(
            alloc["id"], cont["version"], inventory_planner_headers))
        mid = validate_success(api.get_container(cont["id"], inventory_planner_headers))
        assert mid["unallocated_quantities"][item["id"]] == 3

        validate_success(api.decommit_allocation(alloc["id"], inventory_planner_headers))
        after = validate_success(api.get_container(cont["id"], inventory_planner_headers))
        assert after["unallocated_quantities"][item["id"]] == 5, (
            "commit took pool to 3; decommit must restore it to 5 — no drift")
        alloc_after = validate_success(
            api.get_allocation(alloc["id"], inventory_planner_headers))
        assert alloc_after["status"] == "PLANNED"

    def test_pool_invariant_commit_decommit_repeatable(
            self, api, inventory_planner_headers, logistics_coordinator_headers):
        """PRD §3.3: "the `PLANNED` ↔ `COMMITTED` cycle may repeat." A second
        commit/decommit round also conserves the pool exactly.

        Design: Difficulty/compensating_invariant/container_pool_conserved_under_commit_decommit
        """
        item = create_active_item(sku="CI1C")
        po = make_issued_po(item["id"], 5, 20000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 5),
            logistics_coordinator_headers))
        store = make_store([item["id"]])
        alloc = make_planned_allocation(store["id"], cont["id"], item["id"], 2)
        for _ in range(2):
            cur = validate_success(api.get_container(cont["id"], inventory_planner_headers))
            validate_success(api.commit_allocation(
                alloc["id"], cur["version"], inventory_planner_headers))
            validate_success(api.decommit_allocation(alloc["id"], inventory_planner_headers))
        final = validate_success(api.get_container(cont["id"], inventory_planner_headers))
        assert final["unallocated_quantities"][item["id"]] == 5


class TestFirstReceiptActualCosts:

    def test_first_receipt_requires_actual_costs(
            self, api, logistics_coordinator_headers,
            compliance_officer_headers, purchasing_manager_headers):
        """PRD §3.2: "first, if this is the PO's first receipt, the payload
        must supply `actual_duty_cents` and `actual_freight_cents` (both at
        least zero), otherwise `ERR_PO_ACTUAL_COSTS_REQUIRED`"

        Design: Corner/endpoints/first_receipt_requires_actual_costs
        """
        item = create_active_item(sku="EP4", unit_retail_cents=3000,
                                  member_price_cents=3000)
        po = make_issued_po(item["id"], 2, 1000,
                            estimated_duty_cents=10, estimated_freight_cents=10)
        c1 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1,
                                     container_number="C-EP4-1"),
            logistics_coordinator_headers))
        c2 = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1,
                                     container_number="C-EP4-2"),
            logistics_coordinator_headers))
        for c in (c1, c2):
            get_success_data(api.depart_container(c["id"], logistics_coordinator_headers))
            get_success_data(api.arrive_port_container(c["id"], logistics_coordinator_headers))
            get_success_data(api.clear_customs_container(c["id"], compliance_officer_headers))

        resp = api.receive_container(c1["id"], {}, logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PO_ACTUAL_COSTS_REQUIRED)

        received = validate_success(api.receive_container(
            c1["id"], {"actual_duty_cents": 50, "actual_freight_cents": 50},
            logistics_coordinator_headers))
        assert received["status"] == "RECEIVED"

        # Second receipt may omit actuals (already recorded).
        received2 = validate_success(api.receive_container(
            c2["id"], {}, logistics_coordinator_headers))
        assert received2["status"] == "RECEIVED"
        po_after = validate_success(
            api.get_purchase_order(po["id"], purchasing_manager_headers))
        assert po_after["status"] == "RECEIVED"
