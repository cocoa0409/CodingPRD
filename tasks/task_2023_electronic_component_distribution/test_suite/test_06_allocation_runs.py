"""Fair-share allocation runs: basis variants, waterfall rounding, OCC, and
publication rules (PRD §3.4, §2.10)."""
from test_helpers import (
    ADMIN,
    SALES,
    api_client,
    ApiErrorId,
    advance_clock,
    assert_allocation_run,
    create_allocation_run_for_part,
    create_allocation_run_payload,
    create_customer,
    create_line,
    create_order,
    create_part,
    get_order_lines,
    get_part,
    get_success_data,
    make_quality_inspector_headers,
    open_exposure_interval,
    order_line_spec,
    receive_lot,
    setup_acknowledged_order,
    setup_allocated_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def api_ack(order_id):
    """Acknowledge a SUBMITTED order as SalesRep (setup step)."""
    return api_client.acknowledge_order(order_id, SALES)


def _two_customer_demand(part_id, usage_a=300, usage_b=100, qty=1000,
                         ship_date="2026-10-01"):
    """Two customers and two acknowledged single-line orders of equal quantity
    on the given part (customer A first, customer B second)."""
    cust_a = create_customer(name="Cust A",
                             trailing_12mo_component_usage_units=usage_a)
    cust_b = create_customer(name="Cust B",
                             trailing_12mo_component_usage_units=usage_b)
    order_a = create_order(cust_a["id"], [order_line_spec(part_id, qty, ship_date)])
    get_success_data(api_ack(order_a["id"]))
    order_b = create_order(cust_b["id"], [order_line_spec(part_id, qty, ship_date)])
    get_success_data(api_ack(order_b["id"]))
    line_a = get_order_lines(order_a["id"])[0]
    line_b = get_order_lines(order_b["id"])[0]
    return {"cust_a": cust_a, "cust_b": cust_b, "order_a": order_a,
            "order_b": order_b, "line_a": line_a, "line_b": line_b}


class TestAllocationBasisVariants:
    def test_allocation_backlog_basis_split(self, api):
        """PRD §3.4: "In shortage, the waterfall runs: each line's weight is its
        booked `quantity` under `BACKLOG_BASIS`, or its ordering customer's
        `trailing_12mo_component_usage_units` under `USAGE_BASIS` — so identical
        booked quantities split equally under backlog basis but can diverge
        sharply under usage basis."
        PRD §3.4: "`total_supply_qty` is the sum of `qty_on_hand` across the
        part's `AVAILABLE` lots, and `total_demand_qty` is the sum of `quantity`
        across eligible lines — those that are `OPEN`, belong to an
        `ACKNOWLEDGED` order, and reference the run's part."

        Design: Difficulty/dual_variant_calc/allocation_basis_backlog_vs_usage
        """
        line = create_line(line_code="LIN-B", allocation_policy="BACKLOG_BASIS")
        part = create_part(line["id"], part_number="PB-1")
        receive_lot(part["id"], qty_received=90)
        demand = _two_customer_demand(part["id"])

        run = create_allocation_run_for_part(part["id"])
        assert_allocation_run(run)
        assert run["basis"] == "BACKLOG_BASIS"
        assert run["total_supply_qty"] == 90
        assert run["total_demand_qty"] == 2000
        assert run["lines"] == [
            {"order_line_id": demand["line_a"]["id"], "allocated_qty": 45},
            {"order_line_id": demand["line_b"]["id"], "allocated_qty": 45},
        ], "Identical booked quantities split equally under backlog basis"

    def test_allocation_usage_basis_split(self, api):
        """PRD §3.4: "In shortage, the waterfall runs: each line's weight is its
        booked `quantity` under `BACKLOG_BASIS`, or its ordering customer's
        `trailing_12mo_component_usage_units` under `USAGE_BASIS` — so identical
        booked quantities split equally under backlog basis but can diverge
        sharply under usage basis."
        PRD §3.4: "Each line's raw share is the floor of the total supply
        multiplied by its weight and divided by the sum of all weights; each
        line is tentatively allocated the lesser of its raw share and its booked
        quantity. The units left over after this flooring are then distributed
        one unit per pass, iterating the lines that remain below their booked
        quantity ordered by line creation time, then by ship date, then by
        descending quantity, granting one unit each and repeating passes until
        the remainder is exhausted."

        Design: Difficulty/dual_variant_calc/allocation_basis_backlog_vs_usage
        """
        backlog_line = create_line(line_code="LIN-B",
                                   allocation_policy="BACKLOG_BASIS")
        part_b = create_part(backlog_line["id"], part_number="PB-1")
        receive_lot(part_b["id"], qty_received=90)
        demand_b = _two_customer_demand(part_b["id"])
        run_b = create_allocation_run_for_part(part_b["id"])

        usage_line = create_line(line_code="LIN-U", allocation_policy="USAGE_BASIS")
        part_u = create_part(usage_line["id"], part_number="PU-1")
        receive_lot(part_u["id"], qty_received=90)
        demand_u = _two_customer_demand(part_u["id"])
        run_u = create_allocation_run_for_part(part_u["id"])

        assert run_u["basis"] == "USAGE_BASIS"
        assert run_u["total_supply_qty"] == 90
        assert run_u["total_demand_qty"] == 2000
        # Weights 300 vs 100: raw 67.5 -> 67, raw 22.5 -> 22; the single
        # remainder unit goes to the earliest-created line (67 -> 68).
        assert run_u["lines"] == [
            {"order_line_id": demand_u["line_a"]["id"], "allocated_qty": 68},
            {"order_line_id": demand_u["line_b"]["id"], "allocated_qty": 22},
        ]
        assert run_b["lines"] == [
            {"order_line_id": demand_b["line_a"]["id"], "allocated_qty": 45},
            {"order_line_id": demand_b["line_b"]["id"], "allocated_qty": 45},
        ]
        assert run_u["lines"][0]["allocated_qty"] != run_b["lines"][0]["allocated_qty"], (
            "Identical booked quantities diverge across basis variants (45 vs 68)"
        )


class TestFloorThenRemainder:
    def _setup_three_way_shortage(self):
        line = create_line(line_code="LIN-R", allocation_policy="BACKLOG_BASIS")
        part = create_part(line["id"], part_number="PR-1")
        receive_lot(part["id"], qty_received=101)
        lines = []
        for idx, qty in enumerate((60, 80, 60)):
            customer = create_customer(name=f"Cust R{idx + 1}")
            order = create_order(customer["id"],
                                 [order_line_spec(part["id"], qty, "2026-10-01")])
            get_success_data(api_ack(order["id"]))
            lines.append(get_order_lines(order["id"])[0])
        return part, lines

    def test_allocation_floor_shares_and_totals(self, api):
        """PRD §3.4: "Each line's raw share is the floor of the total supply
        multiplied by its weight and divided by the sum of all weights; each
        line is tentatively allocated the lesser of its raw share and its booked
        quantity."
        PRD §3.4: "The computed `lines` array of `{ order_line_id,
        allocated_qty }` pairs is stored on the run sorted by order line
        creation time ascending."

        Design: Difficulty/combinatorial_formula/allocation_floor_then_remainder_waterfall
        """
        part, lines = self._setup_three_way_shortage()
        run = create_allocation_run_for_part(part["id"])
        assert run["total_supply_qty"] == 101
        assert run["total_demand_qty"] == 200
        assert run["lines"] == [
            {"order_line_id": lines[0]["id"], "allocated_qty": 31},
            {"order_line_id": lines[1]["id"], "allocated_qty": 40},
            {"order_line_id": lines[2]["id"], "allocated_qty": 30},
        ]

    def test_allocation_remainder_goes_to_earliest_line(self, api):
        """PRD §3.4: "The units left over after this flooring are then
        distributed one unit per pass, iterating the lines that remain below
        their booked quantity ordered by line creation time, then by ship date,
        then by descending quantity, granting one unit each and repeating passes
        until the remainder is exhausted."
        PRD §2.9: "Allocation arithmetic works in whole units: raw fair shares
        are floored per line before remainder units are distributed one at a
        time, and no exact-split rounding is ever applied."

        Design: Difficulty/combinatorial_formula/allocation_floor_then_remainder_waterfall
        """
        part, lines = self._setup_three_way_shortage()
        run = create_allocation_run_for_part(part["id"])
        by_line = {entry["order_line_id"]: entry["allocated_qty"]
                   for entry in run["lines"]}
        # Raw shares floor to 30 / 40 / 30 (from 30.3 / 40.4 / 30.3); the single
        # leftover unit goes to the earliest-created line, not the largest.
        assert by_line[lines[0]["id"]] == 31, (
            "Earliest-created line receives the remainder unit"
        )
        assert by_line[lines[1]["id"]] == 40, "The largest line keeps its floor share"
        assert by_line[lines[2]["id"]] == 30, (
            "The third line, equally sized to the first but created later, "
            "receives no remainder unit"
        )
        assert sum(by_line.values()) == 101, "Every unit of supply is allocated"


class TestPublicationRules:
    def test_publish_twice_rejected(self, api):
        """PRD §3.4: "Publishing requires the run still be `PROVISIONAL` —
        otherwise `ERR_ALLOCATION_RUN_NOT_PROVISIONAL`".

        Design: Corner/state_machines/publish_twice_rejected
        """
        sc = setup_allocated_order(quantity=10, lot_qty=100, line_code="LIN-PP")
        resp = api.publish_allocation_run(sc["run"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_RUN_NOT_PROVISIONAL)

        order_line = get_success_data(api.get_order_line(sc["order_line"]["id"], ADMIN))
        assert order_line["allocated_qty"] == 10, "Allocations are not applied twice"
        part = get_part(sc["part"]["id"])
        assert part["qty_reserved"] == 10
        assert part["qty_on_hand"] == 90

    def test_run_without_open_demand_rejected(self, api):
        """PRD §3.4: "An empty supply is rejected with
        `ERR_NO_ALLOCATABLE_SUPPLY`; empty eligible demand with
        `ERR_NO_OPEN_DEMAND`."

        Design: Corner/errors/run_without_open_demand_rejected
        """
        line = create_line(line_code="LIN-ND")
        part = create_part(line["id"], part_number="PND-1")
        receive_lot(part["id"], qty_received=50)
        part_fresh = get_part(part["id"])

        resp = api.create_allocation_run(
            create_allocation_run_payload(part["id"], part_fresh["version"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_DEMAND)
        runs, meta = validate_paginated(
            api.list_allocation_runs(ADMIN, params={"part_id": part["id"]}))
        assert meta["total_count"] == 0

    def test_publish_after_supply_drop_rejected(self, api):
        """PRD §3.4: "Publishing requires the run still be `PROVISIONAL` —
        otherwise `ERR_ALLOCATION_RUN_NOT_PROVISIONAL` — and re-verifies that
        the current available supply still covers the sum of the run's allocated
        quantities; if intervening events have eroded supply below that total,
        publication fails with `ERR_QUANTITY_EXCEEDS_AVAILABLE`."

        Design: Corner/errors/publish_after_supply_drop_rejected
        """
        sc = setup_acknowledged_order(quantity=60, line_code="LIN-SD",
                                      part_kw={"floor_life_hours": 100})
        lot = receive_lot(sc["part"]["id"], qty_received=100)
        run = create_allocation_run_for_part(sc["part"]["id"])
        assert run["status"] == "PROVISIONAL"
        assert run["total_supply_qty"] == 100

        open_exposure_interval(lot["id"], note="drop supply")
        advance_clock("2026-08-05T04:00:00Z")  # 100 hours >= floor life 100
        assert get_success_data(api.get_lot(lot["id"], ADMIN))["status"] == "QUARANTINED"

        resp = api.publish_allocation_run(run["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_AVAILABLE)
        run_after = get_success_data(api.get_allocation_run(run["id"], ADMIN))
        assert run_after["status"] == "PROVISIONAL", (
            "A failed publish does not consume the run"
        )


class TestSupplyGate:
    def _setup_open_market_supply(self):
        """One franchised line/part whose only stock is an open-market lot
        still IN_INSPECTION, plus one acknowledged line of demand."""
        sc = setup_acknowledged_order(quantity=10, line_code="LIN-A")
        lot = receive_lot(sc["part"]["id"], qty_received=50,
                          source_type="OPEN_MARKET", receiver_id="wh-01")
        return sc, lot

    def test_allocation_run_rejected_without_available_supply(self, api):
        """PRD §3.4: "An empty supply is rejected with
        `ERR_NO_ALLOCATABLE_SUPPLY`".
        PRD §2.5: "An `OPEN_MARKET` lot begins `IN_INSPECTION` with
        `authenticity` set to `PENDING_INSPECTION`, and it contributes nothing
        to available supply until a `QualityInspector` authenticates it."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_available_lot
        """
        sc, lot = self._setup_open_market_supply()
        assert lot["status"] == "IN_INSPECTION"
        part_fresh = get_part(sc["part"]["id"])

        resp = api.create_allocation_run(
            create_allocation_run_payload(sc["part"]["id"], part_fresh["version"]),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ALLOCATABLE_SUPPLY)

    def test_allocation_run_succeeds_after_lot_authenticated(self, api):
        """PRD §2.5: "A disposition of `AUTHENTICATE` moves the lot to
        `AVAILABLE` and stamps `authenticity` as `AUTHENTICATED`".
        PRD §3.4: "When supply meets or exceeds demand, every eligible line is
        allocated its full `quantity`."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_available_lot
        """
        sc, lot = self._setup_open_market_supply()
        inspected = validate_success(
            api.inspect_lot(lot["id"], {"disposition": "AUTHENTICATE"},
                            make_quality_inspector_headers("qi-01")),
            200)
        assert inspected["status"] == "AVAILABLE"
        assert inspected["authenticity"] == "AUTHENTICATED"

        run = create_allocation_run_for_part(sc["part"]["id"])
        assert run["total_supply_qty"] == 50
        assert run["total_demand_qty"] == 10
        assert run["lines"] == [
            {"order_line_id": sc["order_line"]["id"], "allocated_qty": 10}
        ]


class TestRunSupersedeAndOcc:
    def test_allocation_run_create_stale_part_version_rejected(self, api):
        """PRD §2.10: "A request to create an allocation run must carry
        `expected_part_version` equal to the target part's current `version`;
        if another writer has advanced the part's version since the client last
        read it — for example by publishing an earlier run — the creation is
        rejected with `ERR_STALE_PART_VERSION` (HTTP 412)".
        PRD §3.4: "creation also increments the part's `version`."

        Design: Corner/complexity_layers/allocation_run_create_stale_part_version_rejected
        """
        line = create_line(line_code="LIN-OC1")
        part = create_part(line["id"], part_number="POC-1")
        receive_lot(part["id"], qty_received=100)
        customer = create_customer(name="Cust OC1")
        order = create_order(customer["id"],
                             [order_line_spec(part["id"], 10, "2026-10-01")])
        get_success_data(api_ack(order["id"]))
        observed_version = get_part(part["id"])["version"]

        run = validate_success(
            api.create_allocation_run(
                create_allocation_run_payload(part["id"], observed_version), ADMIN),
            201)
        assert run["status"] == "PROVISIONAL"

        resp = api.create_allocation_run(
            create_allocation_run_payload(part["id"], observed_version), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_PART_VERSION)

        run_after = get_success_data(api.get_allocation_run(run["id"], ADMIN))
        assert run_after["status"] == "PROVISIONAL", (
            "The rejected create did not supersede the live PROVISIONAL run"
        )
        runs, meta = validate_paginated(
            api.list_allocation_runs(ADMIN, params={"part_id": part["id"]}))
        assert meta["total_count"] == 1

    def test_allocation_run_supersede_and_publish(self, api):
        """PRD §3.4: "At most one `PROVISIONAL` run exists per part at a time,
        so creating a new run automatically moves any prior `PROVISIONAL` run
        for the same part to `SUPERSEDED`".
        PRD §3.4: "Publishing requires the run still be `PROVISIONAL` —
        otherwise `ERR_ALLOCATION_RUN_NOT_PROVISIONAL`".

        Design: Corner/complexity_layers/allocation_run_supersede_and_publish
        """
        line = create_line(line_code="LIN-SP")
        part = create_part(line["id"], part_number="PSP-1")
        receive_lot(part["id"], qty_received=100)
        customer = create_customer(name="Cust SP")
        order = create_order(customer["id"],
                             [order_line_spec(part["id"], 10, "2026-10-01")])
        get_success_data(api_ack(order["id"]))
        order_line = get_order_lines(order["id"])[0]

        run1 = create_allocation_run_for_part(part["id"])
        run2 = create_allocation_run_for_part(part["id"])

        run1_after = get_success_data(api.get_allocation_run(run1["id"], ADMIN))
        assert run1_after["status"] == "SUPERSEDED", (
            "The second create supersedes the prior PROVISIONAL run"
        )

        resp = api.publish_allocation_run(run1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_RUN_NOT_PROVISIONAL)

        published = validate_success(api.publish_allocation_run(run2["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"
        updated_line = get_success_data(api.get_order_line(order_line["id"], ADMIN))
        assert updated_line["status"] == "ALLOCATED"
        assert updated_line["allocated_qty"] == 10
