"""Supplier replenishment, unit intake, release, wastage shape, and listing."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_blood_unit,
    assert_same_instant,
    assert_wastage_record,
    create_draft_order,
    create_supplier_order_payload,
    find_unit_by_number,
    get_success_data,
    make_stock,
    make_supplier,
    receive_order_units,
    receive_payload,
    receive_unit_descriptor,
    release_unit,
    set_clock,
    submit_order,
    acknowledge_order,
    supplier_order_line,
    validate_error,
    validate_paginated,
    validate_success,
    SUPERVISOR,
    COORDINATOR,
    TECH_A,
    QO_1,
)


class TestUnitIntakeAndRelease:
    def test_unit_received_in_quarantine_with_computed_expiry(self, api):
        """PRD §3.2: "Receiving against an order in `ACKNOWLEDGED` or `RECEIVING` —
        otherwise `ERR_SO_NOT_RECEIVABLE` — accepts a `units` payload of unit
        descriptors and creates one **BloodUnit** per descriptor, opening each in
        `QUARANTINED`."
        PRD §3.2: "The fixed clock adds a class shelf life to `collected_at`: 1,008
        hours (forty-two days) for `RBC`, 840 hours (thirty-five days) for
        `WHOLE_BLOOD`, 120 hours (five days) for either platelet product, and 8,760
        hours (one year) for `FFP` or `CRYO`."
        PRD §3.2: "the booleans `irradiated`, `cmv_negative`, and `washed` (each
        defaulting to false)"

        Design: Corner/entities/unit_received_in_quarantine_with_computed_expiry
        """
        stock = make_stock([receive_unit_descriptor("U-100")], release=False)
        unit = stock["units"]["U-100"]
        assert_blood_unit(unit)
        assert unit["status"] == "QUARANTINED", "received units open in QUARANTINED"
        assert_same_instant(unit["expires_at"], "2026-09-12T00:00:00Z",
                            "RBC collected 2026-08-01 + 1008h")
        assert unit["irradiated"] is False
        assert unit["cmv_negative"] is False
        assert unit["washed"] is False

    def test_unit_release_from_quarantine_valid(self, api):
        """PRD §3.2: "Releasing a `QUARANTINED` unit to `AVAILABLE` — a
        `BloodBankTechnologist` action requiring the supplier to be `ACTIVE`
        (`ERR_SUPPLIER_SUSPENDED` when suspended) and the unit to be in
        `QUARANTINED` (`ERR_UNIT_NOT_RELEASABLE` otherwise) — recomputes the bucket
        posture."
        PRD §2.5: "**`version` (integer):** a system-managed integer that increments
        by one on every mutation, available for optimistic concurrency control where
        §2.8 declares it."

        Design: Corner/state_machines/unit_release_from_quarantine_valid
        """
        stock = make_stock([receive_unit_descriptor("U-100")], release=False)
        unit = stock["units"]["U-100"]
        released = validate_success(
            api.release_unit_from_quarantine(unit["id"], TECH_A))
        assert released["status"] == "AVAILABLE"
        assert released["version"] == unit["version"] + 1, (
            "the release is one mutation on the unit"
        )

    def test_unit_release_from_available_rejected(self, api):
        """PRD §3.2: "the unit to be in `QUARANTINED` (`ERR_UNIT_NOT_RELEASABLE`
        otherwise)"

        Design: Corner/state_machines/unit_release_from_available_rejected
        """
        stock = make_stock([receive_unit_descriptor("U-100")], release=True)
        unit = stock["units"]["U-100"]

        resp = api.release_unit_from_quarantine(unit["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_RELEASABLE)

        after = get_success_data(api.get_blood_unit(unit["id"], TECH_A))
        assert after["status"] == "AVAILABLE", "the failed release changes nothing"
        assert after["version"] == unit["version"], "no mutation, no version bump"

    def test_supplier_order_receive_before_ack_rejected(self, api):
        """PRD §3.2: "Receiving against an order in `ACKNOWLEDGED` or `RECEIVING` —
        otherwise `ERR_SO_NOT_RECEIVABLE`"

        Design: Corner/state_machines/supplier_order_receive_before_ack_rejected
        """
        supplier = make_supplier()
        order = create_draft_order(
            supplier["id"], [supplier_order_line(quantity=1)])
        submit_order(order["id"])

        resp = api.receive_supplier_order(
            order["id"], receive_payload([receive_unit_descriptor("U-100")]),
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SO_NOT_RECEIVABLE)

        data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"supplier_order_id": order["id"]}))
        assert meta["total_count"] == 0, "a rejected receipt creates no units"


class TestSupplierOrderCloseOut:
    def test_supplier_order_auto_close_and_backorder_branch(self, api):
        """PRD §3.2: "the first receipt moves the order to `RECEIVING`, and when
        every line stands fully received the order auto-closes to `CLOSED` within
        the same call."
        PRD §3.2: "A supervisor or coordinator may also close a `RECEIVING` order
        manually (any other state: `ERR_SO_NOT_CLOSABLE`); closure sets
        `backordered` true when any line closed short of its ordered quantity."

        Design: Corner/state_machines/supplier_order_auto_close_and_backorder_branch
        """
        supplier = make_supplier()
        so1 = create_draft_order(supplier["id"], [supplier_order_line(quantity=1)])
        submit_order(so1["id"])
        acknowledge_order(so1["id"])
        so2 = create_draft_order(
            supplier["id"],
            [supplier_order_line(product_type="FFP", abo_type="A", quantity=2)])
        submit_order(so2["id"])
        acknowledge_order(so2["id"])

        so1 = validate_success(api.receive_supplier_order(
            so1["id"], receive_payload([receive_unit_descriptor("U-100")]),
            COORDINATOR))
        assert so1["status"] == "CLOSED", "full receipt auto-closes in the same call"
        assert so1["backordered"] is False, "no line closed short"

        so2 = validate_success(api.receive_supplier_order(
            so2["id"],
            receive_payload([receive_unit_descriptor(
                "U-200", product_type="FFP", abo_type="A", volume_ml=250,
                donor_id="D-501", lot_number="LOT-2")]),
            COORDINATOR))
        assert so2["status"] == "RECEIVING", "one line short stays open"
        so2 = validate_success(api.close_supplier_order(so2["id"], COORDINATOR))
        assert so2["status"] == "CLOSED"
        assert so2["backordered"] is True, "manual close one unit short is backordered"


class TestReceiptGuards:
    def test_over_receipt_returns_422(self, api):
        """PRD §3.2: "each descriptor's `product_type`, `abo_type`, and `rh_type`
        must match a line on the order and the cumulative received quantity per
        line must never exceed the ordered quantity, else `ERR_OVER_RECEIPT`
        (HTTP 422)"

        Design: Corner/validations/over_receipt_returns_422
        """
        supplier = make_supplier()
        order = create_draft_order(supplier["id"], [supplier_order_line(quantity=1)])
        submit_order(order["id"])
        acknowledge_order(order["id"])

        resp = api.receive_supplier_order(
            order["id"],
            receive_payload([
                receive_unit_descriptor("U-100", donor_id="D-500"),
                receive_unit_descriptor("U-101", donor_id="D-501"),
            ]),
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_OVER_RECEIPT)

    def test_error_duplicate_unit_number(self, api):
        """PRD §3.2: "each `unit_number` (the supplier-assigned ISBT identifier)
        must be globally unique across every unit ever received, else
        `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409)"

        Design: Corner/errors/error_duplicate_unit_number
        """
        # Advance the logical clock so the second manifest's collected_at
        # (2026-08-02) is not in the future — otherwise §2.9's pipeline answers
        # the earlier-priority ERR_SPECIMEN_TIME_INVALID before the
        # unit-number uniqueness rule is reached.
        set_clock()
        supplier = make_supplier()
        _order1, _units = receive_order_units(
            supplier["id"], [supplier_order_line(quantity=1)],
            [receive_unit_descriptor("U-100")])
        order2 = create_draft_order(supplier["id"], [supplier_order_line(quantity=1)])
        submit_order(order2["id"])
        acknowledge_order(order2["id"])

        resp = api.receive_supplier_order(
            order2["id"],
            receive_payload([receive_unit_descriptor(
                "U-100", collected_at="2026-08-02T00:00:00Z", donor_id="D-501",
                lot_number="LOT-2")]),
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER)

        _data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"supplier_order_id": order2["id"]}))
        assert meta["total_count"] == 0, "the duplicate descriptor created no unit"


class TestSubmitGates:
    def test_supplier_suspended_blocks_submit(self, api):
        """PRD §3.2: "Submission moves a `DRAFT` order to `SUBMITTED` (any other
        from-state: `ERR_SO_NOT_SUBMITTABLE`) and requires the supplier to be
        `ACTIVE` (`ERR_SUPPLIER_SUSPENDED` otherwise)."

        Design: Corner/validations/supplier_suspended_blocks_submit
        """
        supplier = make_supplier()
        order = create_draft_order(supplier["id"], [supplier_order_line(quantity=1)])
        get_success_data(api.suspend_supplier(
            supplier["id"], {"reason": "documentation lapse"}, SUPERVISOR))

        resp = api.submit_supplier_order(order["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_SUSPENDED)

        order = get_success_data(api.get_supplier_order(order["id"], TECH_A))
        assert order["status"] == "DRAFT", "the rejected submit leaves the order DRAFT"

    def test_wastage_review_gate_blocks_coordinator_submit(self, api):
        """PRD §3.2: "when a `SupplierCoordinator` — but not a `BloodBankSupervisor`,
        who is exempt — submits a non-emergency order and any bucket named in its
        lines currently carries a rolling wastage rate of 0.05 or more (see §3.8),
        the submission is rejected with `ERR_WASTAGE_REVIEW_REQUIRED` (HTTP 409),
        forcing a supervisor's eyes onto a bleeding bucket before more stock is
        ordered into it."

        Design: Corner/validations/wastage_review_gate_blocks_coordinator_submit
        """
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        _order1, units = receive_order_units(
            supplier["id"], [supplier_order_line(quantity=3)],
            [receive_unit_descriptor("U-100", donor_id="D-500"),
             receive_unit_descriptor("U-101", donor_id="D-501"),
             receive_unit_descriptor("U-102", donor_id="D-502")])
        # One of three in-window receipts is wasted: rate 0.3333 >= 0.05.
        get_success_data(api.discard_unit(units["U-100"]["id"],
                                          {"note": "qc failure"}, SUPERVISOR))
        order2 = create_draft_order(supplier["id"], [supplier_order_line(quantity=2)])

        resp = api.submit_supplier_order(order2["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WASTAGE_REVIEW_REQUIRED)

        submitted = validate_success(
            api.submit_supplier_order(order2["id"], SUPERVISOR))
        assert submitted["status"] == "SUBMITTED", "the supervisor is exempt"


class TestWastageRecordShape:
    def test_wastage_record_immutable_event_shape(self, api):
        """PRD §2.5: "The exception is the **WastageRecord**, an append-only event
        log entry that carries only `id` and `created_at`; both `updated_at` and
        `version` are absent from it by design, since a wastage record is written
        once and never modified."
        PRD §3.8: "a `quantity_units` that is always 1 in this benchmark (one record
        per wasted unit), the `recorded_by_user_id` of the actor whose action
        created it — or the literal string `system` for sweep- and closure-created
        records — and an optional `note` (used by manual discards)."

        Design: Corner/entities/wastage_record_immutable_event_shape
        """
        stock = make_stock([receive_unit_descriptor("U-100")], release=False)
        unit = stock["units"]["U-100"]
        get_success_data(api.discard_unit(unit["id"], {"note": "damaged"},
                                          SUPERVISOR))

        data, _meta = validate_paginated(api.list_wastage_records(
            QO_1, params={"unit_id": unit["id"]}))
        assert len(data) == 1
        record = validate_success(api.get_wastage_record(data[0]["id"], QO_1))
        assert_wastage_record(record)
        assert record["reason"] == "MANUAL"
        assert record["quantity_units"] == 1
        assert record["recorded_by_user_id"] == "sup-1"


class TestListingAndNotFound:
    def test_pagination_defaults_and_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, accepts a minimum of 1, and is bounded above at 100. The
        `offset` parameter skips a number of items from the front of the result set
        and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_and_limit_offset
        """
        descriptors = [receive_unit_descriptor("U-%03d" % (i + 1),
                                               donor_id="D-%03d" % (i + 1))
                       for i in range(12)]
        stock = make_stock(descriptors, release=False)
        order_id = stock["supply_order"]["id"]

        data, meta = validate_paginated(
            api.list_blood_units(TECH_A, params={"supplier_order_id": order_id}))
        assert len(data) == 10, "the default page caps at 10 items"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10 and meta["offset"] == 0

        data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"supplier_order_id": order_id, "limit": 5, "offset": 10}))
        assert len(data) == 2, "the last page holds the remainder"
        assert meta["total_count"] == 12
        assert meta["has_more"] is False

    def test_list_filter_by_status(self, api):
        """PRD §3.2: "The blood-unit list endpoint filters by `status`,
        `product_type`, `abo_type`, `rh_type`, `supplier_id`, `supplier_order_id`,
        `donor_id`, `lot_number`, `derived_from_unit_id`, `unit_number`, and
        `expires_before`."

        Design: Corner/endpoints/list_filter_by_status
        """
        stock = make_stock([receive_unit_descriptor("U-100", donor_id="D-500"),
                            receive_unit_descriptor("U-101", donor_id="D-501")],
                           release=False)
        release_unit(stock["units"]["U-100"]["id"])
        order_id = stock["supply_order"]["id"]

        data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"supplier_order_id": order_id, "status": "AVAILABLE"}))
        assert meta["total_count"] == 1
        assert data[0]["unit_number"] == "U-100"

        data, meta = validate_paginated(api.list_blood_units(
            TECH_A, params={"supplier_order_id": order_id, "status": "QUARANTINED"}))
        assert meta["total_count"] == 1
        assert data[0]["unit_number"] == "U-101"

    def test_get_nonexistent_unit_returns_404(self, api):
        """PRD §2.9: "third, path-identifier existence, validated left to right —
        an unmatched route or an unknown path id yields a resource-specific 404"
        which names "`ERR_UNIT_NOT_FOUND` for a blood unit".

        Design: Corner/endpoints/get_nonexistent_unit_returns_404
        """
        resp = api.get_blood_unit(NON_EXISTENT_UUID, TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)
