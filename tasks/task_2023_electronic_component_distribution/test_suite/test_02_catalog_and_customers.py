"""Catalog management: manufacturer lines, parts, customers (PRD §3.1, §2.5)."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    ApiErrorId,
    assert_manufacturer_line,
    assert_part,
    create_customer,
    create_line,
    create_part,
    get_success_data,
    order_line_spec,
    setup_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
SALES = TEST_USERS["sales_rep_headers"]


class TestManufacturerLineDefaults:
    def test_manufacturer_line_create_defaults_applied(self, api):
        """PRD §3.1: "`ncnr`, a boolean defaulting to false, marking all of the
        line's parts as non-cancellable/non-returnable; `cancel_window_days`,
        defaulting to 30, the number of days before a line's ship date by which
        cancellation must occur; and `reschedule_window_days`, defaulting to 20,
        the analogous cutoff for moving a ship date. The line also declares an
        `allocation_policy` — `BACKLOG_BASIS` by default, or `USAGE_BASIS`".
        PRD §3.1: "Each line maintains a running `open_debit_balance_cents`,
        initialized to zero at creation and reconciled later by ship-and-debit
        settlement (§3.7)."

        Design: Corner/entities/manufacturer_line_create_defaults_applied
        """
        resp = api.create_manufacturer_line(
            {"line_code": "LIN-DEF", "name": "Default Line",
             "sourcing_channel": "FRANCHISED"},
            ADMIN,
        )
        created = validate_success(resp, 201)
        assert_manufacturer_line(created)
        assert created["ncnr"] is False
        assert created["cancel_window_days"] == 30
        assert created["reschedule_window_days"] == 20
        assert created["allocation_policy"] == "BACKLOG_BASIS"
        assert created["open_debit_balance_cents"] == 0
        assert isinstance(created["version"], int)

        fetched = get_success_data(api.get_manufacturer_line(created["id"], ADMIN))
        assert fetched["ncnr"] is False
        assert fetched["cancel_window_days"] == 30
        assert fetched["reschedule_window_days"] == 20
        assert fetched["allocation_policy"] == "BACKLOG_BASIS"
        assert fetched["open_debit_balance_cents"] == 0


class TestUniqueness:
    def test_duplicate_line_code_rejected(self, api):
        """PRD §3.1: "A manufacturer line is created with a `line_code` that
        must be unique across all lines — a duplicate is rejected with
        `ERR_DUPLICATE_LINE_CODE`".

        Design: Corner/validations/duplicate_line_code_rejected
        """
        create_line(line_code="LIN-DUP", name="Dup Line")
        resp = api.create_manufacturer_line(
            {"line_code": "LIN-DUP", "name": "Dup Line 2",
             "sourcing_channel": "OPEN_MARKET"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_CODE)
        lines, meta = validate_paginated(api.list_manufacturer_lines(ADMIN))
        assert meta["total_count"] == 1

    def test_duplicate_part_number_scoped_to_line(self, api):
        """PRD §3.1: "Parts are created under a line by reference to
        `manufacturer_line_id`, with a `part_number` unique within that line —
        duplicates are rejected with `ERR_DUPLICATE_PART_NUMBER`."

        Design: Corner/validations/duplicate_part_number_scoped_to_line
        """
        line1 = create_line(line_code="LIN-S1", name="Scope Line 1")
        line2 = create_line(line_code="LIN-S2", name="Scope Line 2")
        create_part(line1["id"], part_number="PN-SCOPE")

        resp_dup = api.create_part(
            {"manufacturer_line_id": line1["id"], "part_number": "PN-SCOPE",
             "msl_level": 2, "floor_life_hours": 100, "date_code_limit_months": 24,
             "standard_cost_cents": 1000, "book_price_cents": 1500},
            ADMIN,
        )
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_PART_NUMBER)

        resp_ok = api.create_part(
            {"manufacturer_line_id": line2["id"], "part_number": "PN-SCOPE",
             "msl_level": 2, "floor_life_hours": 100, "date_code_limit_months": 24,
             "standard_cost_cents": 1000, "book_price_cents": 1500},
            ADMIN,
        )
        created = validate_success(resp_ok, 201)
        assert_part(created)
        assert created["manufacturer_line_id"] == line2["id"]


class TestPartCreation:
    def test_part_create_missing_required_msl_level(self, api):
        """PRD §2.11: "Request shape is validated next — a missing required
        field, a wrong type, an invalid enum member, a non-positive quantity,
        or an empty `lines` array is `ERR_INVALID_REQUEST`".
        PRD §2.6: "Parts carry a JEDEC moisture sensitivity level `msl_level`
        in the range 1 through 6, together with a `floor_life_hours` budget".

        Design: Corner/entities/part_create_missing_required_msl_level
        """
        line = create_line(line_code="LIN-RQ", name="Required Line")
        resp = api.create_part(
            {"manufacturer_line_id": line["id"], "part_number": "PRQ-1",
             "floor_life_hours": 100, "date_code_limit_months": 24,
             "standard_cost_cents": 1000, "book_price_cents": 1500},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        parts, meta = validate_paginated(
            api.list_parts(ADMIN, params={"manufacturer_line_id": line["id"]}))
        assert meta["total_count"] == 0
        assert parts == []

    def test_part_computed_qty_on_hand_input_ignored(self, api):
        """PRD §3.1: "Three computed quantities summarize a part's position at
        all times: `qty_on_hand`, the sum of unreserved units over the part's
        `AVAILABLE` lots; `qty_reserved`, the sum of reserved units over those
        same lots; and `open_demand_qty`, the sum of `quantity` over the part's
        order lines that are `OPEN` under an `ACKNOWLEDGED` order."

        Design: Corner/entities/part_computed_qty_on_hand_input_ignored
        """
        line = create_line(line_code="LIN-CI", name="Computed Line")
        resp = api.create_part(
            {"manufacturer_line_id": line["id"], "part_number": "PCI-1",
             "msl_level": 3, "floor_life_hours": 100, "date_code_limit_months": 24,
             "standard_cost_cents": 1000, "book_price_cents": 1500,
             "qty_on_hand": 999},
            ADMIN,
        )
        created = validate_success(resp, 201)
        assert created["qty_on_hand"] == 0, (
            "qty_on_hand is computed from AVAILABLE lots; with none it is 0 "
            "regardless of the client-supplied value"
        )
        assert created["qty_reserved"] == 0
        assert created["open_demand_qty"] == 0


class TestLotChannelAndShape:
    def test_channel_mismatch_franchised_lot_rejected(self, api):
        """PRD §2.5: "A `FRANCHISED` lot is only lawful when the part's
        manufacturer line is itself a franchised line — that is, the line's
        `sourcing_channel` is `FRANCHISED`."
        PRD §2.5: "Receiving a `FRANCHISED` lot for a part whose line is not
        franchised is rejected with `ERR_CHANNEL_MISMATCH`."

        Design: Corner/validations/channel_mismatch_franchised_lot_rejected
        """
        line = create_line(line_code="LIN-OM", name="Open Market Line",
                           sourcing_channel="OPEN_MARKET")
        part = create_part(line["id"], part_number="POM-1")
        resp = api.create_lot(
            {"part_id": part["id"], "date_code": "202601", "qty_received": 10,
             "source_type": "FRANCHISED"},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_CHANNEL_MISMATCH)

    def test_invalid_enum_source_type_rejected(self, api):
        """PRD §2.11: "Request shape is validated next — a missing required
        field, a wrong type, an invalid enum member, a non-positive quantity,
        or an empty `lines` array is `ERR_INVALID_REQUEST`".
        PRD §2.5: "Every inventory lot is received with a declared
        `source_type` of either `FRANCHISED` or `OPEN_MARKET`."

        Design: Corner/validations/invalid_enum_source_type_rejected
        """
        line, part = setup_catalog(line_code="LIN-EN")
        resp = api.create_lot(
            {"part_id": part["id"], "date_code": "202601", "qty_received": 10,
             "source_type": "GRAY_MARKET"},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        lots, meta = validate_paginated(
            api.list_lots(ADMIN, params={"part_id": part["id"]}))
        assert meta["total_count"] == 0


class TestOrderCreationGates:
    def test_credit_hold_customer_blocked_at_order_create(self, api):
        """PRD §3.1: "A customer's `status` begins `GOOD_STANDING`; a customer
        moved to `CREDIT_HOLD` may not place new orders and may not have orders
        acknowledged — both attempts are rejected with
        `ERR_CUSTOMER_CREDIT_HOLD`."

        Design: Corner/validations/credit_hold_customer_blocked_at_order_create
        """
        line, part = setup_catalog(line_code="LIN-CH")
        customer = create_customer(name="Cust CH", status="CREDIT_HOLD")
        resp = api.create_order(
            {"customer_id": customer["id"],
             "lines": [order_line_spec(part["id"], 5, "2026-10-01")]},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)
        orders, meta = validate_paginated(
            api.list_orders(ADMIN, params={"customer_id": customer["id"]}))
        assert meta["total_count"] == 0

    def test_order_with_empty_lines_rejected(self, api):
        """PRD §3.3: "An order is booked by a `SalesRep`, or by a
        `CustomerBuyer` acting for their own account, with a `customer_id`, an
        optional `note`, and a non-empty `lines` array — an order without lines
        is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/order_with_empty_lines_rejected
        """
        customer = create_customer(name="Cust EL")
        resp = api.create_order(
            {"customer_id": customer["id"], "lines": []},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
