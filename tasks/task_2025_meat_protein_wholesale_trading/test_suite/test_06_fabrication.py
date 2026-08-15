"""Fabrication: mass-balance posting, output-lot genealogy, void unwind, and
the conserved-mass invariant across post and void."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_sheet_line,
    api_client,
    book_po,
    create_carcass_product,
    create_customer,
    create_fabrication_batch_payload,
    create_product,
    create_sheet,
    create_supplier,
    create_warehouse,
    create_yield_spec,
    get_lot,
    get_warehouse,
    inspect_lot,
    load_out_shipment,
    publish_sheet,
    receive_po,
    request_allocation,
    run_sheet,
    set_clock,
    validate_error,
    validate_success,
)


def _list_batch_outputs(batch_id):
    resp = api_client.list_inventory_lots(
        TEST_USERS["desk_admin_headers"],
        params={"fabrication_batch_id": batch_id},
    )
    return validate_success(resp)


def _setup_carcase_lot(weight=1000):
    """CARC-E-style setup: carcass product with 20%/75% yield specs and one
    AVAILABLE input lot. Returns (carc, rib, chk, warehouse, lot)."""
    carc = create_carcass_product(product_code="CARC-E")
    rib = create_product(product_code="RIBEYE-E", max_fat_pct=12.0)
    chk = create_product(product_code="CHUCK-E", max_fat_pct=18.0)
    create_yield_spec(carc["id"], rib["id"], 20.0, 15.0, 25.0)
    create_yield_spec(carc["id"], chk["id"], 75.0, 70.0, 80.0)
    supplier = create_supplier(establishment_number="EST-13")
    warehouse = create_warehouse(name="WH-F")
    set_clock("2026-08-03T00:00:00Z")
    po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=weight,
                 contract_price_per_cwt_cents=25_000,
                 required_delivery_date="2026-08-03")
    _, lot = receive_po(po["id"], warehouse["id"], weight,
                        production_date="2026-08-02")
    inspect_lot(lot["id"], 30.0)  # carcasses are always spec-compliant
    return carc, rib, chk, warehouse, get_lot(lot["id"])


class TestFabricationMassConservation:
    def test_post_consumes_input_and_creates_outputs(self,
                                                     warehouse_operator_headers):
        """PRD §3.5: "On a successful post, the input lot's
        `current_weight_lbs` falls to zero and the lot transitions to
        `DEPLETED`; one output lot is created per `outputs` entry with
        `received_weight_lbs` equal to the entry's `weight_lbs`, a
        system-minted `lot_code`, `parent_lot_id` pointing at the input lot,
        `fabrication_batch_id` pointing at the batch, `production_date` copied
        from the input lot, and `warehouse_id` copied from the input lot; the
        batch's totals are computed; and the warehouse's occupancy is
        recomputed."
        PRD §2.11: "A warehouse's `occupied_lbs` is a live aggregate: the sum
        of `current_weight_lbs` over all lots stored at that warehouse whose
        status is `IN_INSPECTION`, `AVAILABLE`, or `QUARANTINED`."

        Design: Difficulty/compensating_invariant/fabrication_post_void_mass_conservation
        """
        _, rib, chk, warehouse, lot = _setup_carcase_lot(1000)
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 1000

        resp = api_client.create_fabrication_batch(
            create_fabrication_batch_payload(
                lot["id"], loss_lbs=50,
                outputs=[{"product_id": rib["id"], "weight_lbs": 200},
                         {"product_id": chk["id"], "weight_lbs": 750}]),
            warehouse_operator_headers,
        )
        batch = validate_success(resp, expected_status=201)
        assert batch["total_output_weight_lbs"] == 950
        assert batch["yield_efficiency_pct"] == 95.0

        posted = validate_success(
            api_client.post_fabrication_batch(batch["id"],
                                              warehouse_operator_headers))
        assert posted["status"] == "POSTED"

        input_after = get_lot(lot["id"])
        assert input_after["status"] == "DEPLETED"
        assert input_after["current_weight_lbs"] == 0
        # 1000 consumed, 950 output, 50 loss: occupancy drops by the loss.
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 950

        outputs = _list_batch_outputs(batch["id"])
        assert len(outputs) == 2
        for out in outputs:
            assert out["parent_lot_id"] == lot["id"]
            assert out["fabrication_batch_id"] == batch["id"]
            assert out["production_date"] == "2026-08-02"
            assert out["warehouse_id"] == warehouse["id"]
            assert out["status"] == "IN_INSPECTION", \
                "both outputs sit inside their yield bands"
        weights = sorted(o["received_weight_lbs"] for o in outputs)
        assert weights == [200, 750]

    def test_void_restores_mass_exactly(self, warehouse_operator_headers,
                                        desk_admin_headers):
        """PRD §3.5: "The unwind fires a two-link cascade: first, every output
        lot moves to `DEPLETED` with its `current_weight_lbs` driven to zero;
        second, once the outputs are depleted, the input lot's
        `current_weight_lbs` is restored to its pre-post weight and the input
        lot returns to `AVAILABLE`; the warehouse's occupancy is then
        recomputed."

        Design: Difficulty/compensating_invariant/fabrication_post_void_mass_conservation
        """
        _, rib, chk, warehouse, lot = _setup_carcase_lot(1000)
        occ_pre = get_warehouse(warehouse["id"])["occupied_lbs"]
        assert occ_pre == 1000

        batch = validate_success(api_client.create_fabrication_batch(
            create_fabrication_batch_payload(
                lot["id"], loss_lbs=50,
                outputs=[{"product_id": rib["id"], "weight_lbs": 200},
                         {"product_id": chk["id"], "weight_lbs": 750}]),
            warehouse_operator_headers,
        ), expected_status=201)
        api_client.post_fabrication_batch(batch["id"],
                                          warehouse_operator_headers)
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 950

        voided = validate_success(
            api_client.void_fabrication_batch(batch["id"], desk_admin_headers))
        assert voided["status"] == "VOIDED"

        occ_post = get_warehouse(warehouse["id"])["occupied_lbs"]
        assert occ_post == occ_pre == 1000, \
            f"mass must be restored exactly: pre {occ_pre}, post-void {occ_post}"
        input_after = get_lot(lot["id"])
        assert input_after["status"] == "AVAILABLE"
        assert input_after["current_weight_lbs"] == 1000
        for out in _list_batch_outputs(batch["id"]):
            assert out["status"] == "DEPLETED"
            assert out["current_weight_lbs"] == 0


class TestFabricationGates:
    def test_mass_balance_violation(self, warehouse_operator_headers):
        """PRD §3.5: "And mass must balance exactly: the batch's
        `total_output_weight_lbs` plus its `loss_lbs` must equal the input
        lot's `current_weight_lbs` with no tolerance; any discrepancy is
        rejected with `ERR_MASS_BALANCE_VIOLATION` (HTTP 422)."

        Design: Corner/validations/fabrication_mass_balance_violation
        """
        carc = create_carcass_product(product_code="CARC-MB")
        rib = create_product(product_code="RIBEYE-MB", max_fat_pct=12.0)
        create_yield_spec(carc["id"], rib["id"], 20.0, 15.0, 25.0)
        supplier = create_supplier(establishment_number="EST-MB")
        warehouse = create_warehouse()
        set_clock("2026-08-03T00:00:00Z")
        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=1000,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-03", po_number="PO-MB")
        _, lot = receive_po(po["id"], warehouse["id"], 1000, lot_code="LOT-MB",
                            production_date="2026-08-01")
        inspect_lot(lot["id"], 30.0)

        batch = validate_success(api_client.create_fabrication_batch(
            create_fabrication_batch_payload(
                lot["id"], loss_lbs=50,
                outputs=[{"product_id": rib["id"], "weight_lbs": 900}]),
            warehouse_operator_headers,
        ), expected_status=201)

        resp = api_client.post_fabrication_batch(batch["id"],
                                                 warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MASS_BALANCE_VIOLATION)
        batch_after = validate_success(
            api_client.get_fabrication_batch(batch["id"],
                                             warehouse_operator_headers))
        assert batch_after["status"] == "DRAFT"
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "AVAILABLE"
        assert lot_after["current_weight_lbs"] == 1000

    def test_posted_batch_not_voidable_after_draw(self,
                                                  warehouse_operator_headers,
                                                  desk_admin_headers):
        """PRD §3.5: "Voiding a `POSTED` batch is an unwind, permitted only
        when every output lot is untouched — each output's `current_weight_lbs`
        still equals its `received_weight_lbs`; if any output has been drawn
        down, the void is rejected with `ERR_BATCH_NOT_VOIDABLE`."

        Design: Corner/validations/posted_batch_not_voidable_after_draw
        """
        carc = create_carcass_product(product_code="CARC-NV")
        rib = create_product(product_code="RIBEYE-NV", max_fat_pct=12.0,
                             shelf_life_days=30)
        chk = create_product(product_code="CHUCK-NV", max_fat_pct=18.0,
                             shelf_life_days=30)
        create_yield_spec(carc["id"], rib["id"], 20.0, 15.0, 25.0)
        create_yield_spec(carc["id"], chk["id"], 75.0, 70.0, 80.0)
        supplier = create_supplier(establishment_number="EST-NV")
        warehouse = create_warehouse()
        customer = create_customer(customer_code="CUST-NV")
        set_clock("2026-08-03T00:00:00Z")
        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=1000,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-03", po_number="PO-NV")
        _, lot = receive_po(po["id"], warehouse["id"], 1000, lot_code="LOT-NV",
                            production_date="2026-08-01")
        inspect_lot(lot["id"], 30.0)
        sheet = create_sheet()
        line = add_sheet_line(sheet["id"], rib["id"], 700, 100_000)
        publish_sheet(sheet["id"])

        batch = validate_success(api_client.create_fabrication_batch(
            create_fabrication_batch_payload(
                lot["id"], loss_lbs=50,
                outputs=[{"product_id": rib["id"], "weight_lbs": 200},
                         {"product_id": chk["id"], "weight_lbs": 750}]),
            warehouse_operator_headers,
        ), expected_status=201)
        api_client.post_fabrication_batch(batch["id"], warehouse_operator_headers)

        outputs = _list_batch_outputs(batch["id"])
        out_lot = next(o for o in outputs if o["product_id"] == rib["id"])
        inspect_lot(out_lot["id"], 10.0)

        alloc = request_allocation(customer, line["id"], 100)
        run_sheet(sheet["id"])
        load_out_shipment(alloc["id"], 100, lot_ids=[out_lot["id"]])
        assert get_lot(out_lot["id"])["current_weight_lbs"] == 100

        resp = api_client.void_fabrication_batch(batch["id"],
                                                 desk_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_VOIDABLE)
        batch_after = validate_success(
            api_client.get_fabrication_batch(batch["id"], desk_admin_headers))
        assert batch_after["status"] == "POSTED"

    def test_void_voided_batch_returns_batch_not_draft(self,
                                                       warehouse_operator_headers,
                                                       desk_admin_headers):
        """PRD §3.5: "Voiding is a `DeskAdmin` act with two distinct paths.
        Voiding a `DRAFT` batch simply moves it to `VOIDED` with no further
        effect."
        PRD §3.5: "Both paths report a batch in the wrong from-state as
        `ERR_BATCH_NOT_DRAFT`."

        Design: Corner/validations/void_voided_batch_returns_batch_not_draft
        """
        carc = create_carcass_product(product_code="CARC-BD")
        rib = create_product(product_code="RIBEYE-BD", max_fat_pct=12.0)
        create_yield_spec(carc["id"], rib["id"], 100.0, 90.0, 100.0)
        supplier = create_supplier(establishment_number="EST-BD")
        warehouse = create_warehouse()
        set_clock("2026-08-03T00:00:00Z")
        po = book_po(supplier["id"], carc["id"], ordered_weight_lbs=100,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-03", po_number="PO-BD")
        _, lot = receive_po(po["id"], warehouse["id"], 100, lot_code="LOT-BD",
                            production_date="2026-08-01")
        inspect_lot(lot["id"], 30.0)  # carcass: always compliant -> AVAILABLE

        batch = validate_success(api_client.create_fabrication_batch(
            create_fabrication_batch_payload(
                lot["id"], loss_lbs=0,
                outputs=[{"product_id": rib["id"], "weight_lbs": 100}]),
            warehouse_operator_headers,
        ), expected_status=201)
        first = api_client.void_fabrication_batch(batch["id"],
                                                  desk_admin_headers)
        assert validate_success(first)["status"] == "VOIDED"

        second = api_client.void_fabrication_batch(batch["id"],
                                                   desk_admin_headers)
        validate_error(second, ApiErrorId.ERR_BATCH_NOT_DRAFT)
        batch_after = validate_success(
            api_client.get_fabrication_batch(batch["id"], desk_admin_headers))
        assert batch_after["status"] == "VOIDED"


class TestYieldSpecKindRules:
    def test_yield_spec_carcass_kind_enforced(self, desk_admin_headers):
        """PRD §3.1: "A yield spec's `carcass_product_id` must reference a
        product of kind `CARCASS`, and its `output_product_id` must reference
        a product of kind `PRIMAL` or `SUBPRIMAL`; a mismatch on either side is
        rejected with `ERR_PRODUCT_KIND_MISMATCH` (HTTP 422)."

        Design: Corner/validations/yield_spec_carcass_kind_enforced
        """
        rib = create_product(product_code="RIBEYE-YS", max_fat_pct=12.0)
        resp = api_client.create_yield_spec(
            {"carcass_product_id": rib["id"], "output_product_id": rib["id"],
             "expected_yield_pct": 50.0, "min_yield_pct": 45.0,
             "max_yield_pct": 55.0},
            desk_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_KIND_MISMATCH)
