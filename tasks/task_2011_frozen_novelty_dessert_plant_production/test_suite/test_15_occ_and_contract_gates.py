"""Optimistic concurrency, contract gates, enum validation, append-only
readings, and common-field version semantics (PRD §2.4, §2.6, §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    allocate,
    assert_temp_reading,
    create_contract,
    create_customer,
    create_product,
    create_shipment,
    get_success_data,
    make_customer_rep_headers,
    setup_active_contract,
    setup_completed_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_customer_payload, create_product_payload
from test_helpers.fixtures import PM, WH


class TestOccReformulation:
    def test_occ_reformulation_stale_version_rejected(self, api):
        """PRD §2.6: "Creating a reformulation of a Product requires the
        request to carry expected_product_version equal to the parent
        product's current version. ... a mismatch is rejected with
        ERR_STALE_VERSION (HTTP 412)"."

        Design: Corner/cross_cutting_layers/occ_reformulation_stale_version_rejected
        """
        product = create_product(sku_code="P-OCC", product_name="Occ Bar")
        observed_version = product["version"]
        validate_success(api.patch_product(
            product["id"], {"product_name": "Occ Bar v1.1"}, PM))
        payload = create_product_payload(
            sku_code="P-OCC-2", product_name="Occ Bar Reformulated",
            fill_volume_ml_per_unit=72, target_overrun_pct=42)
        payload["expected_product_version"] = observed_version
        resp = api.create_reformulation(product["id"], payload, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_reformulation_success_path(self, api):
        """PRD §3.1: "On success the new product's predecessor_product_id
        points at the parent, the parent's successor_product_id points at
        the new product, and the parent's version increments."

        Design: Corner/cross_cutting_layers/occ_reformulation_success_path
        """
        product = create_product(sku_code="P-OC2", product_name="Occ2 Bar")
        payload = create_product_payload(
            sku_code="P-OC2-R", product_name="Occ2 Bar R",
            fill_volume_ml_per_unit=72, target_overrun_pct=42)
        payload["expected_product_version"] = product["version"]
        child = validate_success(api.create_reformulation(
            product["id"], payload, PM), 201)
        assert child["predecessor_product_id"] == product["id"]
        parent = get_success_data(api.get_product(product["id"], PM))
        assert parent["successor_product_id"] == child["id"]
        assert parent["version"] == product["version"] + 1


class TestOccAmend:
    def test_occ_amend_stale_version_rejected(self, api):
        """PRD §2.6: "Amending a CoPackContract requires the request to
        carry expected_contract_version equal to the contract's current
        version. In either case, a mismatch is rejected with
        ERR_STALE_VERSION (HTTP 412)"."

        Design: Corner/cross_cutting_layers/occ_amend_stale_version_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(**create_customer_payload(
            customer_code="PL-1", display_name="Big Retailer",
            kind="PRIVATE_LABEL"))
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-OCC")
        submitted = validate_success(api.submit_contract(
            contract["id"], make_customer_rep_headers(customer["id"])))
        validate_success(api.approve_contract(contract["id"], PM))
        resp = api.amend_contract(
            contract["id"],
            {"expected_contract_version": submitted["version"],
             "committed_units": 2000}, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_amend_success_path(self, api):
        """PRD §3.2: "Amending a contract's committed_units,
        unit_price_cents, or end_date is permitted while APPROVED or
        ACTIVE, but requires expected_contract_version matching the
        contract's current version". PRD §2.4: version is "incremented by
        exactly 1 on every mutation"."

        Design: Corner/cross_cutting_layers/occ_amend_success_path
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(**create_customer_payload(
            customer_code="PL-1", display_name="Big Retailer",
            kind="PRIVATE_LABEL"))
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-OC3")
        validate_success(api.submit_contract(
            contract["id"], make_customer_rep_headers(customer["id"])))
        approved = validate_success(api.approve_contract(contract["id"], PM))
        amended = validate_success(api.amend_contract(
            contract["id"],
            {"expected_contract_version": approved["version"],
             "committed_units": 2000}, PM))
        assert amended["committed_units"] == 2000
        assert amended["version"] == approved["version"] + 1


class TestVersionIncrement:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "version (an integer starting at 1, incremented by
        exactly 1 on every mutation — including state transitions,
        side-effect cascades, and explicit edits)"."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        product = create_product(sku_code="P-V", product_name="Version Bar")
        assert product["version"] == 1
        patched = validate_success(api.patch_product(
            product["id"], {"product_name": "Version Bar B"}, PM))
        assert patched["version"] == 2
        discontinued = validate_success(
            api.discontinue_product(product["id"], PM))
        assert discontinued["version"] == 3
        assert discontinued["status"] == "DISCONTINUED"


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §1 ("the plant runs on a logical clock ... consistency is
        immediate" theme) — a GET issued after a PATCH reflects the mutation
        in the same logical instant. The §2.4 updated_at is "refreshed on
        every mutation" and §3.1 PATCH edits the spec.

        Design: Corner/consistency_model/immediate_read_after_write
        """
        product = create_product(sku_code="P-IC", product_name="IC Bar")
        validate_success(api.patch_product(
            product["id"], {"target_overrun_pct": 55}, PM))
        fetched = get_success_data(api.get_product(product["id"], PM))
        assert fetched["target_overrun_pct"] == 55


class TestContractGates:
    def test_contract_not_active_rejected(self, api):
        """PRD §3.8: "When contract_id is supplied, the contract must be
        ACTIVE and its customer_id must equal the shipment's customer_id,
        else ERR_CONTRACT_NOT_ACTIVE (HTTP 422)." A DRAFT contract (never
        submitted) is not ACTIVE.

        Design: Corner/validations/contract_not_active_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(**create_customer_payload(
            customer_code="PL-1", display_name="Big Retailer",
            kind="PRIVATE_LABEL"))
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-NA")
        resp = api.create_shipment(
            {"shipment_code": "SH-NA", "customer_id": customer["id"],
             "contract_id": contract["id"]}, WH)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_contract_product_mismatch_rejected(self, api):
        """PRD §3.8: "On a contract-linked shipment, the lot's product_id
        must equal the contract's product_id, else
        ERR_CONTRACT_PRODUCT_MISMATCH (HTTP 422)."

        Design: Corner/validations/contract_product_mismatch_rejected
        """
        ctx = setup_active_contract(contract_code="CT-PM",
                                    activate_at="2026-08-05T08:00:00Z")
        # Produce a DIFFERENT (non-copack) product's lot.
        run_ctx = setup_completed_run(
            product_overrides={"sku_code": "BAR-VAN-70"},
            run_code="R-PM", scheduled_start="2026-08-05T10:00:00Z",
            booking_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            clock="2026-08-05T08:00:00Z")
        shipment = create_shipment(ctx["customer"]["id"],
                                   shipment_code="SH-PM",
                                   contract_id=ctx["contract"]["id"])
        resp = api.create_allocation(
            shipment["id"], {"lot_id": run_ctx["lot"]["id"], "units": 100}, WH)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_PRODUCT_MISMATCH)

    def test_contract_submit_twice_rejected(self, api):
        """PRD §3.2: "The CustomerRep owning the contract then submits it,
        moving DRAFT → SUBMITTED." A second submit on the SUBMITTED contract
        fails the state gate (§5 ERR_INVALID_STATE: "Target resource's state
        does not allow the requested transition")."

        Design: Corner/state_machines/contract_submit_twice_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(**create_customer_payload(
            customer_code="PL-1", display_name="Big Retailer",
            kind="PRIVATE_LABEL"))
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-S")
        rep = make_customer_rep_headers(customer["id"])
        validate_success(api.submit_contract(contract["id"], rep))
        resp = api.submit_contract(contract["id"], rep)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInvalidEnum:
    def test_invalid_enum_format_returns_invalid_request(self, api):
        """PRD §3.1: "format is either NOVELTY (bars, sandwiches) or BULK
        (pints, tubs)". PRD §5: ERR_INVALID_REQUEST covers "enum outside
        declared set". 'CONE' is outside the declared set.

        Design: Corner/validations/invalid_enum_format_returns_invalid_request
        """
        payload = create_product_payload(sku_code="X-2", product_name="X",
                                         format="CONE")
        resp = api.create_product(payload, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTempReadings:
    def test_temp_readings_append_and_retrieve(self, api):
        """PRD §3.8: "Temperature readings are append-only logger events.
        While a shipment is IN_TRANSIT, the lead appends a batch of
        readings, each with recorded_at and temp_c. Readings are stored
        against the shipment and listed in created_at ascending order."
        PRD §2.4: "TempReading is the sole exception: it is append-only and
        carries only id and created_at. Both updated_at and version are
        absent from TempReading."

        Design: Corner/entities/temp_readings_append_and_retrieve
        """
        ctx = setup_completed_run(run_code="R-T")
        customer = create_customer()
        shipment = create_shipment(customer["id"], shipment_code="SH-T")
        allocate(shipment["id"], ctx["lot"]["id"], 500)
        get_success_data(api.load_shipment(shipment["id"], WH))
        get_success_data(api.dispatch_shipment(shipment["id"], WH))
        created = validate_success(api.append_temperature_readings(
            shipment["id"],
            {"readings": [
                {"recorded_at": "2026-08-10T09:00:00Z", "temp_c": -19.5},
                {"recorded_at": "2026-08-10T10:00:00Z", "temp_c": -19.2},
            ]}, WH), 201)
        assert len(created) == 2
        for reading in created:
            assert_temp_reading(reading)
        listed = get_success_data(
            api.list_temperature_readings(shipment["id"], PM))
        assert len(listed) == 2
        assert listed[0]["temp_c"] == -19.5
        assert_temp_reading(listed[0])
        assert_temp_reading(listed[1])


class TestLotDiscovery:
    def test_cascade_created_lot_discoverable_via_reverse_get(self, api):
        """PRD §3.7: "Lots are listed with optional filters on product_id,
        run_id, zone_id, and status." The lot created by run completion is
        discovered via GET /inventory-lots?run_id=<id>.

        Design: Corner/endpoints/cascade_created_lot_discoverable_via_reverse_get
        """
        ctx = setup_completed_run(run_code="R-DV")
        data, meta = validate_paginated(api.list_inventory_lots(
            PM, params={"run_id": ctx["run"]["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["run_id"] == ctx["run"]["id"]
        assert data[0]["product_id"] == ctx["product"]["id"]
