"""Response envelope, authentication context, and typed 404 behaviour (PRD §2.1–§2.3, §2.7)."""
import re

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_customer,
    create_line,
    create_order,
    get_success_data,
    open_exposure_interval,
    order_line_spec,
    receive_lot,
    setup_catalog,
    validate_error,
    validate_paginated,
)

TEST_WAREHOUSE = build_user_headers("wh-01", "WarehouseOps")
SALES_USER = build_user_headers("sales-01", "SalesRep")


class TestListPaginationAndEnvelope:
    def test_list_pagination_and_envelope_shape(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of 1
        and maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/list_pagination_and_envelope_shape
        """
        create_line(line_code="LIN-P1", name="Page Line 1")
        create_line(line_code="LIN-P2", name="Page Line 2")
        create_line(line_code="LIN-P3", name="Page Line 3",
                    sourcing_channel="OPEN_MARKET")

        resp1 = api.list_manufacturer_lines(ADMIN, params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert meta1["api_request_id"].startswith("req_")
        assert re.search(r"\.\d{3}Z$", meta1["api_request_timestamp"]), (
            "api_request_timestamp must carry three fractional digits"
        )

        resp2 = api.list_manufacturer_lines(ADMIN, params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Default pagination (no query params): limit defaults to 10.
        resp3 = api.list_manufacturer_lines(ADMIN)
        page3, meta3 = validate_paginated(resp3)
        assert meta3["limit"] == 10
        assert meta3["offset"] == 0
        assert len(page3) == 3
        assert meta3["has_more"] is False

    def test_error_envelope_shape_on_failure(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "response_type": "error" and a data
        object where "The `error_id` is a unique, machine-readable string that
        identifies the specific error" and "The `message` provides a
        human-readable explanation of what went wrong."
        PRD §3.1: "A manufacturer line is created with a `line_code` that must
        be unique across all lines — a duplicate is rejected with
        `ERR_DUPLICATE_LINE_CODE`".

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        create_line(line_code="LIN-ENV", name="Envelope Line")
        resp = api.create_manufacturer_line(
            {"line_code": "LIN-ENV", "name": "Envelope Line 2",
             "sourcing_channel": "FRANCHISED"},
            ADMIN,
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["response_type"] == "error"
        error_data = validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_CODE)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestAuthContext:
    def test_request_without_role_header_returns_400(self, api):
        """PRD §2.1: "Failure to provide valid headers — either header missing,
        or a role value not among the six declared roles — results in an
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/validations/request_without_role_header_returns_400
        """
        headers = {"X-User-ID": "sales-01", "Content-Type": "application/json"}
        resp = api.list_manufacturer_lines(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFound:
    def test_order_get_nonexistent_returns_not_found(self, api):
        """PRD §2.7: "The request is rejected immediately with the 404 error
        corresponding to the first identifier that does not resolve to an
        existing resource".

        Design: Corner/entities/order_get_nonexistent_returns_not_found
        """
        resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_lot_create_with_unknown_part_fk_rejected(self, api):
        """PRD §2.7: "The same left-to-right discipline applies to foreign keys
        carried in request bodies: a `manufacturer_line_id`, `customer_id`,
        `part_id`, `order_line_id`, `primary_part_id`, or `alternate_part_id`
        that names no existing resource surfaces its own specific 404".

        Design: Corner/entities/lot_create_with_unknown_part_fk_rejected
        """
        resp = api.create_lot(
            {"part_id": NON_EXISTENT_UUID, "date_code": "202601",
             "qty_received": 10, "source_type": "FRANCHISED"},
            TEST_WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND)

    def test_acknowledge_nonexistent_order_returns_not_found(self, api):
        """PRD §2.11: "Request shape is validated next — a missing required
        field, a wrong type, an invalid enum member, a non-positive quantity,
        or an empty `lines` array is `ERR_INVALID_REQUEST` — and only then are
        path identifiers and body foreign keys resolved to their 404s."
        PRD §2.7: "The request is rejected immediately with the 404 error
        corresponding to the first identifier that does not resolve to an
        existing resource: `ERR_ORDER_NOT_FOUND` before
        `ERR_ORDER_LINE_NOT_FOUND`, and `ERR_LOT_NOT_FOUND` before
        `ERR_EXPOSURE_NOT_FOUND`."

        Design: Corner/validations/acknowledge_nonexistent_order_returns_not_found
        """
        resp = api.acknowledge_order(NON_EXISTENT_UUID, SALES_USER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_unknown_ids_across_resources_return_404(self, api):
        """PRD §2.7: "a `manufacturer_line_id`, `customer_id`, `part_id`,
        `order_line_id`, `primary_part_id`, or `alternate_part_id` that names
        no existing resource surfaces its own specific 404
        (`ERR_MANUFACTURER_LINE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, and so on through
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_BUYBACK_NOT_FOUND`, `ERR_ALLOCATION_RUN_NOT_FOUND`, and
        `ERR_ALTERNATE_APPROVAL_NOT_FOUND`)"
        PRD §2.7: "An exposure identifier must additionally belong to the lot
        named in the path; an exposure that exists under a different lot is
        reported as `ERR_EXPOSURE_NOT_FOUND` for the path under inspection."

        Design: Corner/errors/unknown_ids_across_resources_return_404
        """
        line, part = setup_catalog(line_code="LIN-404")
        lot = receive_lot(part["id"], qty_received=10)

        cases = [
            (api.get_manufacturer_line(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_MANUFACTURER_LINE_NOT_FOUND),
            (api.get_part(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_PART_NOT_FOUND),
            (api.get_customer(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api.get_order_line(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
            (api.get_lot(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_LOT_NOT_FOUND),
            (api.seal_exposure(lot["id"], NON_EXISTENT_UUID, TEST_WAREHOUSE),
             ApiErrorId.ERR_EXPOSURE_NOT_FOUND),
            (api.get_design_registration(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
            (api.get_claim(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api.get_buyback(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_BUYBACK_NOT_FOUND),
            (api.get_allocation_run(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_ALLOCATION_RUN_NOT_FOUND),
            (api.get_alternate_approval(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_ALTERNATE_APPROVAL_NOT_FOUND),
        ]
        for resp, expected_error in cases:
            validate_error(resp, expected_error)


class TestFkReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §4: "List design registrations, filterable by `customer_id`,
        `part_id`, `status`" — and likewise the list endpoints for lots
        ("List lots, filterable by `part_id`, `status`, `authenticity`"),
        order lines ("List order lines, filterable by `order_id`, `part_id`,
        `status`"), and a lot's exposure intervals ("List the exposure
        intervals of a lot").

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        line, part = setup_catalog(line_code="LIN-FK")
        lot = receive_lot(part["id"], qty_received=50)
        exposure = open_exposure_interval(lot["id"], note="fk check")
        customer = create_customer(name="Cust FK")
        order = create_order(customer["id"],
                             [order_line_spec(part["id"], 5, "2026-10-01")])

        lots, lots_meta = validate_paginated(
            api.list_lots(ADMIN, params={"part_id": part["id"]}))
        assert lots_meta["total_count"] == 1
        assert lots[0]["id"] == lot["id"]

        lines, lines_meta = validate_paginated(
            api.list_order_lines(ADMIN, params={"order_id": order["id"]}))
        assert lines_meta["total_count"] == 1
        assert lines[0]["order_id"] == order["id"]

        exposures, exp_meta = validate_paginated(api.list_exposures(lot["id"], ADMIN))
        assert exp_meta["total_count"] == 1
        assert exposures[0]["id"] == exposure["id"]

        registrations, reg_meta = validate_paginated(
            api.list_design_registrations(ADMIN, params={"customer_id": customer["id"]}))
        assert reg_meta["total_count"] == 0
        assert registrations == []

        # keep linters honest about the successful creates
        assert get_success_data(api.get_order(order["id"], ADMIN))["status"] == "SUBMITTED"
