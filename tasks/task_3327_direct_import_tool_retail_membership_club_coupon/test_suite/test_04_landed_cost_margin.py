"""Landed-cost dual-variant calculations and margin-floor tests
(PRD §2.7, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_active_item,
    create_container_payload,
    create_item_payload,
    create_purchase_order_payload,
    get_success_data,
    make_issued_po,
    validate_error,
    validate_success,
    TEST_USERS,
)

PM = TEST_USERS["purchasing_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestLandedCostDualVariant:

    def test_landed_cost_provisional_vs_final(self, api):
        """PRD §3.2: "For each line, in the order the lines appear in the PO,
        the provisional landed unit cost is the line's `unit_cost_cents` plus
        the pool multiplied by that line's goods value, divided by the goods
        total, then divided by the line's quantity — each division truncating
        to whole cents with no remainder redistribution." and "The provisional
        and final variants must produce different results whenever the
        estimated and actual pools differ"

        Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final
        """
        item_a = create_active_item(sku="A1", unit_retail_cents=5000,
                                    member_price_cents=4500)
        item_b = create_active_item(sku="B1", unit_retail_cents=9000,
                                    member_price_cents=8500)
        po = get_success_data(api.create_purchase_order(
            create_purchase_order_payload(
                item_a["id"], 10, 1000,
                po_number="PO-1",
                lines=[{"item_id": item_a["id"], "quantity": 10,
                        "unit_cost_cents": 1000},
                       {"item_id": item_b["id"], "quantity": 5,
                        "unit_cost_cents": 2000}],
                estimated_duty_cents=500, estimated_freight_cents=500),
            PM))
        issued = get_success_data(api.issue_purchase_order(po["id"], PM))

        # Provisional (pool 1000): goods A=10000, B=10000, total=20000
        #   A: 1000 + floor(1000*10000/20000/10) = 1000 + 50 = 1050
        #   B: 2000 + floor(1000*10000/20000/5)  = 2000 + 100 = 2100
        assert issued["provisional_landed_costs"][item_a["id"]] == 1050
        assert issued["provisional_landed_costs"][item_b["id"]] == 2100

        cont = get_success_data(api.create_container(
            create_container_payload(
                po["id"], item_a["id"], 10,
                container_number="C-1",
                lines=[{"item_id": item_a["id"], "quantity": 10},
                       {"item_id": item_b["id"], "quantity": 5}]),
            LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        received = validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 700, "actual_freight_cents": 900}, LC))
        assert received["status"] == "RECEIVED"

        po_after = validate_success(api.get_purchase_order(po["id"], PM))
        # Final (actual pool 1600): A share 800 -> 1000 + 80 = 1080;
        # B share 800 -> 2000 + 160 = 2160.
        assert po_after["final_landed_costs"][item_a["id"]] == 1080
        assert po_after["final_landed_costs"][item_b["id"]] == 2160
        assert po_after["status"] == "RECEIVED"

        item_a_after = validate_success(api.get_item(item_a["id"], PM))
        item_b_after = validate_success(api.get_item(item_b["id"], PM))
        assert item_a_after["current_landed_unit_cost_cents"] == 1080
        assert item_b_after["current_landed_unit_cost_cents"] == 2160

    def test_landed_cost_provisional_uses_estimates_not_actuals(self, api):
        """PRD §3.2: provisional landed-cost allocation forms "the cost pool as
        `estimated_duty_cents` plus `estimated_freight_cents`" at issue time —
        computed before any actuals exist.

        Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final
        """
        item = create_active_item(sku="A2", unit_retail_cents=5000,
                                  member_price_cents=4500)
        po = get_success_data(api.create_purchase_order(
            create_purchase_order_payload(
                item["id"], 4, 1000,
                estimated_duty_cents=400, estimated_freight_cents=400),
            PM))
        issued = get_success_data(api.issue_purchase_order(po["id"], PM))
        # pool 800; goods 4000; share = floor(800*4000/4000) = 800;
        # per unit = floor(800/4) = 200 -> 1000 + 200 = 1200
        assert issued["provisional_landed_costs"][item["id"]] == 1200
        assert issued["status"] == "ISSUED"


class TestFinalLandedCostRemainderCarry:

    def test_final_landed_cost_remainder_carry_rounding(self, api):
        """PRD §3.2: "maintain a running remainder starting at zero; for each
        line, compute its exact share in millicents as the pool multiplied by
        the line's goods value multiplied by one thousand, divided by the goods
        total; take the whole-cent share as that millicent figure floored to
        cents; add the leftover millicents into the running remainder; whenever
        the running remainder reaches at least one thousand millicents, add one
        cent to the line's share and subtract one thousand from the remainder"
        and "Earlier lines absorb the rounding pennies first."

        Design: Difficulty/combinatorial_formula/final_landed_cost_remainder_carry_rounding
        """
        r1 = create_active_item(sku="R1", unit_retail_cents=2000,
                                member_price_cents=1900)
        r2 = create_active_item(sku="R2", unit_retail_cents=100,
                                member_price_cents=100, floor_margin_pct=0.01,
                                unit_weight_kg=0.01)
        po = get_success_data(api.create_purchase_order(
            create_purchase_order_payload(
                r1["id"], 3, 333,
                po_number="PO-R",
                lines=[{"item_id": r1["id"], "quantity": 3,
                        "unit_cost_cents": 333},
                       {"item_id": r2["id"], "quantity": 1,
                        "unit_cost_cents": 1}],
                estimated_duty_cents=0, estimated_freight_cents=0),
            PM))
        get_success_data(api.issue_purchase_order(po["id"], PM))
        cont = get_success_data(api.create_container(
            create_container_payload(
                po["id"], r1["id"], 3,
                container_number="C-R",
                lines=[{"item_id": r1["id"], "quantity": 3},
                       {"item_id": r2["id"], "quantity": 1}]),
            LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 1, "actual_freight_cents": 0}, LC))

        po_after = validate_success(api.get_purchase_order(po["id"], PM))
        # pool 1 cent, goods_total 1000.
        # R1: exact share 999 millicents -> 0 cents, carry 999.
        # R2: exact share 1 millicent -> 0 cents, carry 1000 -> +1 cent to R2.
        assert po_after["final_landed_costs"][r1["id"]] == 333
        assert po_after["final_landed_costs"][r2["id"]] == 2

    def test_final_landed_cost_carry_order_matters(self, api):
        """PRD §3.2: "The provisional and final variants must produce different
        results whenever the estimated and actual pools differ, and may differ
        per line even with equal pools because of the remainder carry."

        Design: Difficulty/combinatorial_formula/final_landed_cost_remainder_carry_rounding
        """
        r1 = create_active_item(sku="R1C", unit_retail_cents=2000,
                                member_price_cents=1900)
        r2 = create_active_item(sku="R2C", unit_retail_cents=100,
                                member_price_cents=100, floor_margin_pct=0.01,
                                unit_weight_kg=0.01)
        # Same lines, but estimated pool 1 equals actual pool 1: provisional
        # (no redistribution) vs final (carry) may differ per line.
        po = get_success_data(api.create_purchase_order(
            create_purchase_order_payload(
                r1["id"], 3, 333,
                lines=[{"item_id": r1["id"], "quantity": 3,
                        "unit_cost_cents": 333},
                       {"item_id": r2["id"], "quantity": 1,
                        "unit_cost_cents": 1}],
                estimated_duty_cents=1, estimated_freight_cents=0),
            PM))
        issued = get_success_data(api.issue_purchase_order(po["id"], PM))
        # Provisional: R1 gets floor(1*999/1000/3)=0 -> 333;
        # R2 gets floor(1*1/1000/1)=0 -> 1 (no redistribution).
        assert issued["provisional_landed_costs"][r1["id"]] == 333
        assert issued["provisional_landed_costs"][r2["id"]] == 1

        cont = get_success_data(api.create_container(
            create_container_payload(
                po["id"], r1["id"], 3,
                lines=[{"item_id": r1["id"], "quantity": 3},
                       {"item_id": r2["id"], "quantity": 1}]),
            LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 1, "actual_freight_cents": 0}, LC))
        po_after = validate_success(api.get_purchase_order(po["id"], PM))
        # Final carry gives R2 the cent even though the pools were equal.
        assert po_after["final_landed_costs"][r2["id"]] == 2
        assert po_after["final_landed_costs"][r1["id"]] == 333


class TestMarginFloor:

    def test_margin_floor_equality_allowed(self, api):
        """PRD §3.1: "A candidate price violates the floor only when the price
        scaled by one hundred thousand is strictly smaller than the floor value
        scaled by one hundred thousand and truncated to a whole number — an
        exact rational comparison, so a price landing precisely on the floor is
        allowed." and "A violating reprice is rejected with
        `ERR_MARGIN_FLOOR_VIOLATION`"

        Design: Corner/validations/margin_floor_equality_allowed
        """
        item = create_active_item(sku="V3", unit_retail_cents=5000,
                                  member_price_cents=4800,
                                  floor_margin_pct=0.20)
        po = make_issued_po(item["id"], 1, 1000)
        cont = get_success_data(api.create_container(
            create_container_payload(po["id"], item["id"], 1,
                                     container_number="C-V3"), LC))
        get_success_data(api.depart_container(cont["id"], LC))
        get_success_data(api.arrive_port_container(cont["id"], LC))
        get_success_data(api.clear_customs_container(cont["id"], CO))
        validate_success(api.receive_container(
            cont["id"], {"actual_duty_cents": 0, "actual_freight_cents": 0}, LC))
        # landed cost 1000, floor = 1000 * 1.20 = 1200
        resp = api.reprice_item(item["id"], {"unit_retail_cents": 1199}, PM)
        validate_error(resp, ApiErrorId.ERR_MARGIN_FLOOR_VIOLATION)
        ok = validate_success(api.reprice_item(
            item["id"], {"unit_retail_cents": 1200}, PM))
        assert ok["unit_retail_cents"] == 1200

    def test_margin_floor_vacuous_without_landed_cost(self, api):
        """PRD §3.1: "When `current_landed_unit_cost_cents` is still null the
        check passes vacuously."

        Design: Corner/validations/margin_floor_equality_allowed
        """
        item = create_active_item(sku="V3B", unit_retail_cents=5000,
                                  member_price_cents=4800,
                                  floor_margin_pct=0.50)
        ok = validate_success(api.reprice_item(
            item["id"], {"unit_retail_cents": 10}, PM))
        assert ok["unit_retail_cents"] == 10
