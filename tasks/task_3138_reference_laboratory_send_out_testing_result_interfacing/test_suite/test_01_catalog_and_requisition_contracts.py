"""Catalog entries, specimen intake contracts, requisition shape and role gating.

These are the breadth claims that ride directly on the endpoint surface: what a
create returns, what an out-of-enum or missing input does, what a synthetic
identifier resolves to, and which roles may act.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_catalog_entry,
    assert_specimen,
    make_lab_client_admin_headers,
    setup_active_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCESSIONING = "accessioning_technologist_headers"
OPS = "reference_lab_operations_headers"


# =============================================================================
# Catalogue entry creation
# =============================================================================

class TestCatalogEntryCreation:

    def test_catalog_entry_create_returns_full_requirement_block_and_starts_draft(self, api, ops_headers):
        """PRD 3.4: "A `LabClientAdmin` or a `ReferenceLabOperations` operator
        creates an entry in `DRAFT`, supplying its published `test_code` and
        long-form `test_name`, its `test_category` from `ROUTINE`, `ESOTERIC`
        and `GENETIC`, its analytical `method`, and the full specimen
        requirement block - `required_specimen_type`, `container_type`,
        `min_volume_ml`, `transport_temperature`, and the three stability
        windows".
        PRD 3.4: "`reflex_test_code` names the test to chain to and may be null
        when no reflex applies."

        Design: Corner/entities/catalog_entry_create_returns_every_declared_field_and_starts_draft
        """
        client = validate_success(api.create_client_laboratory({
            "name": "Cache Valley Reference Lab",
            "clia_number": "45D-3001",
            "client_type": "REFERENCE_LAB",
            "state_code": "UT",
            "billing_arrangement": "CLIENT",
            "credit_limit_cents": 5000000,
        }, ops_headers), 201)

        res = api.create_catalog_entry({
            "test_code": "LACTATE_PLASMA",
            "test_name": "Lactate, Plasma",
            "test_category": "ROUTINE",
            "method": "PHOTOMETRY",
            "required_specimen_type": "PLASMA_LITHIUM_HEPARIN",
            "container_type": "GREEN_TOP",
            "min_volume_ml": 1.0,
            "transport_temperature": "REFRIGERATED",
            "stability_hours_ambient": 0.5,
            "stability_hours_refrigerated": 24,
            "stability_hours_frozen": 720,
            "base_tat_hours": 6,
            "list_price_cents": 1400,
            "client_price_cents": 1237,
            "floor_price_cents": 0,
            "critical_value_low": None,
            "critical_value_high": None,
            "reflex_test_code": None,
            "reflex_condition": "NONE",
            "reflex_within_hours": 24,
            "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, make_lab_client_admin_headers(client["id"]))

        assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
        body = res.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        entry = body["data"]
        assert_catalog_entry(entry)
        assert entry["test_code"] == "LACTATE_PLASMA"
        assert entry["test_category"] == "ROUTINE"
        assert entry["status"] == "DRAFT"
        assert entry["version"] == 1
        assert entry["reflex_test_code"] is None
        assert entry["critical_value_low"] is None
        assert entry["min_volume_ml"] == 1.0
        assert entry["transport_temperature"] == "REFRIGERATED"

    def test_catalog_entry_create_with_out_of_enum_transport_temperature_is_invalid_request(
            self, api, ops_headers, client_admin_headers):
        """PRD 2.11: "A required body field that is absent, a field carrying a
        value outside its enumerated set, or an unparseable payload is a
        request-shape failure reported as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD 2.5: "the specimen's observed `transport_temperature` is drawn from
        the same three values and must equal the declared value for every
        ordered test".

        Design: Corner/entities/test_catalog_entry_create_with_out_of_enum_transport_temperature_returns_invalid_request
        """
        res = api.create_catalog_entry({
            "test_code": "BAD_TEMP",
            "test_name": "Bad Temperature Test",
            "test_category": "ROUTINE",
            "method": "PHOTOMETRY",
            "required_specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "min_volume_ml": 1.0,
            "transport_temperature": "CHILLED",
            "stability_hours_ambient": 24,
            "stability_hours_refrigerated": 24,
            "stability_hours_frozen": 24,
            "base_tat_hours": 6,
            "list_price_cents": 1000,
            "client_price_cents": None,
            "floor_price_cents": 0,
            "critical_value_low": None,
            "critical_value_high": None,
            "reflex_test_code": None,
            "reflex_condition": "NONE",
            "reflex_within_hours": 24,
            "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, client_admin_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

        data, meta = validate_paginated(api.list_catalog_entries(
            ops_headers, params={"status": "DRAFT"}))
        assert meta["total_count"] == 0, "a rejected entry must leave no row behind"


# =============================================================================
# Specimen intake contracts
# =============================================================================

class TestSpecimenIntakeContract:

    def test_specimen_get_returns_condition_and_zero_aliquot_total(self, api, accessioning_headers):
        """PRD 3.2: "A primary tube is created with `aliquot_parent_id` and
        `aliquot_volume_ml` both left null, and its arrival refreshes the parent
        leg's `specimen_count`."
        PRD 2.5: "A specimen presented for accessioning whose condition is
        anything other than `ACCEPTABLE` must carry a `condition_reason_code`".

        Design: Corner/entities/specimen_get_returns_condition_and_zero_aliquot_total_unchanged
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3101",
            "patient_mrn": "MRN-3101",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "aliquot_parent_id": None,
            "aliquot_volume_ml": None,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)

        fetched = validate_success(api.get_specimen(specimen["id"], accessioning_headers), 200)
        assert_specimen(fetched)
        assert fetched["status"] == "RECEIVED"
        assert fetched["condition"] == "ACCEPTABLE"
        assert fetched["condition_reason_code"] is None
        assert fetched["rejection_reason_code"] is None
        assert fetched["total_aliquot_volume_ml"] == 0.00
        assert fetched["volume_ml"] == 2.5
        assert fetched["accession_number"] == "ACC-3101"

    def test_specimen_create_ignores_supplied_status_computed_and_version(self, api, accessioning_headers):
        """PRD 2.4: "The `version` field is an integer that begins at its
        initial value and increments by one on every mutation of the resource".
        PRD 2.5: "Remaining stability is the binding window minus that elapsed
        time. Because it is derived on every read rather than stored".

        Design: Corner/entities/specimen_create_extra_status_and_version_fields_are_ignored_input
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        res = api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3201",
            "patient_mrn": "MRN-3201",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
            "status": "RELEASED",
            "remaining_stability_hours": 999,
            "version": 42,
        }, accessioning_headers)
        assert res.status_code == 201
        specimen = res.json()["data"]
        assert specimen["status"] == "RECEIVED", "server-managed status must not come from input"
        assert specimen["version"] == 1, "server-managed version must not come from input"
        assert specimen["remaining_stability_hours"] != 999.0

        data, meta = validate_paginated(api.list_specimens(
            accessioning_headers, params={"status": "RECEIVED"}))
        assert meta["total_count"] == 1


# =============================================================================
# Requisition shape
# =============================================================================

class TestRequisitionShape:

    def test_empty_test_lines_is_a_shape_failure_that_stores_nothing(self, api, accessioning_headers):
        """PRD 3.3: "A requisition that carries no test lines at all is a shape
        failure, not a business failure. It is checked before catalogue
        integrity and before interface integrity, raises `ERR_EMPTY_REQUISITION`
        (HTTP 400), and leaves no order row behind".
        PRD 2.11: "A required body field that is absent, a field carrying a
        value outside its enumerated set, or an unparseable payload is a
        request-shape failure reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/send_out_order_create_without_any_test_lines_returns_empty_requisition
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3101",
            "patient_mrn": "MRN-3101",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)

        res = api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3102",
            "patient_mrn": "MRN-3101",
            "client_requested_at": "2026-08-31T20:46:00Z",
            "priority": "ROUTINE",
            "test_lines": [],
            "override_utilization_guard": False,
        }, accessioning_headers)
        err = validate_error(res, "ERR_EMPTY_REQUISITION", expected_status=400)
        assert err["error_id"] != "ERR_CATALOG_ENTRY_NOT_PUBLISHED"

        data, meta = validate_paginated(api.list_send_out_orders(
            accessioning_headers, params={"client_laboratory_id": scenario["client"]["id"]}))
        assert meta["total_count"] == 0, "no phantom empty order may be left behind"

    def test_body_foreign_keys_resolve_left_to_right_in_declared_order(self, api, accessioning_headers):
        """PRD 2.11: "Body foreign keys are resolved in the exact order the
        endpoint's input list declares, and an unresolvable one raises the
        corresponding entity-specific not-found identifier as well."
        PRD 2.11: "For the client-scoped order listing, the client segment is
        examined first, so a missing client yields
        `ERR_CLIENT_LABORATORY_NOT_FOUND` even when the request's other inputs
        are also invalid."

        Design: Corner/entities/send_out_order_create_body_foreign_keys_are_checked_in_declared_input_order
        """
        fake_specimen = "00000000-0000-4000-8000-000000000002"
        fake_entry = "00000000-0000-4000-8000-000000000003"

        both_unknown = api.create_send_out_order({
            "client_laboratory_id": "00000000-0000-4000-8000-000000000001",
            "specimen_id": fake_specimen,
            "order_number": "REQ-3301",
            "patient_mrn": "MRN-3301",
            "client_requested_at": "2026-09-01T06:01:00Z",
            "priority": "ROUTINE",
            "test_lines": [{"test_catalog_entry_id": fake_entry, "line_sequence": 1}],
            "override_utilization_guard": False,
        }, accessioning_headers)
        err = validate_error(both_unknown, "ERR_CLIENT_LABORATORY_NOT_FOUND", expected_status=404)
        assert err["error_id"] != "ERR_SPECIMEN_NOT_FOUND"

        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        specimen_unknown = api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": fake_specimen,
            "order_number": "REQ-3302",
            "patient_mrn": "MRN-3301",
            "client_requested_at": "2026-09-01T06:02:00Z",
            "priority": "ROUTINE",
            "test_lines": [{"test_catalog_entry_id": fake_entry, "line_sequence": 1}],
            "override_utilization_guard": False,
        }, accessioning_headers)
        validate_error(specimen_unknown, "ERR_SPECIMEN_NOT_FOUND", expected_status=404)

        data, meta = validate_paginated(api.list_send_out_orders(accessioning_headers))
        assert meta["total_count"] == 0


# =============================================================================
# Retrieval and listing
# =============================================================================

class TestRetrieval:

    def test_unknown_order_id_returns_the_entity_specific_not_found(self, api, ops_headers):
        """PRD 2.11: "Where a path carries more than one resource identifier,
        the service resolves them from left to right and rejects the request at
        the first one that does not exist, returning the entity-specific
        not-found identifier for whichever identifier failed".
        PRD 2.11: "In every case the status is 404."

        Design: Corner/entities/send_out_order_get_with_an_unknown_id_returns_order_not_found
        """
        res = api.get_send_out_order(NON_EXISTENT_UUID, ops_headers)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_SEND_OUT_ORDER_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()

    def test_order_test_line_listing_paginates_and_filters_within_one_order(
            self, api, ops_headers, accessioning_headers, medtech_headers):
        """PRD 2.3: "`limit` caps how many items a single page returns: it
        defaults to 10, its smallest permitted value is 1 and its largest is
        100. `offset` states how many items to skip before the page begins and
        defaults to 0."
        PRD 2.3: "the `meta` object carries four pagination fields beyond the
        request identifiers: `limit`, `offset`, `total_count` - the total number
        of resources matching the query, ignoring the window - and `has_more`".

        Design: Corner/entities/order_test_lines_list_paginates_and_filters_within_one_order
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        entry = scenario["entry"]
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3101",
            "patient_mrn": "MRN-3101",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3101",
            "patient_mrn": "MRN-3101",
            "client_requested_at": "2026-08-31T20:45:00Z",
            "priority": "ROUTINE",
            "test_lines": [
                {"test_catalog_entry_id": entry["id"], "line_sequence": 1},
                {"test_catalog_entry_id": entry["id"], "line_sequence": 2},
                {"test_catalog_entry_id": entry["id"], "line_sequence": 3},
            ],
            "override_utilization_guard": True,
        }, accessioning_headers), 201)

        page1, meta1 = validate_paginated(api.list_order_test_lines(
            medtech_headers, params={"send_out_order_id": order["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_order_test_lines(
            medtech_headers, params={"send_out_order_id": order["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_order_test_lines(
            medtech_headers, params={"send_out_order_id": order["id"], "line_status": "PENDING"}))
        assert len(filtered) == 3
        assert meta3["total_count"] == 3

        defaulted, meta4 = validate_paginated(api.list_order_test_lines(
            medtech_headers, params={"send_out_order_id": order["id"]}))
        assert len(defaulted) == 3
        assert meta4["limit"] == 10
        assert meta4["offset"] == 0


# =============================================================================
# Billing ledger opening state
# =============================================================================

class TestBillingLedgerOpening:

    def test_fresh_ledger_starts_all_accumulators_at_zero(
            self, api, ops_headers, billing_headers):
        """PRD 3.10: "A client's ledger tracks three running totals and one
        counter: `billed_cents` is the running sum of posted charge amounts,
        `voided_cents` is the running sum of voided amounts, `net_billed_cents`
        is the first minus the second, and `charge_entry_count` is the number of
        posted-charge events applied".
        PRD 3.10: "The ledger's `status` is one of `OPEN`, `HELD` or `CLOSED`,
        and a fresh ledger opens with all four of those quantities at zero."

        Design: Corner/entities/billing_ledger_create_omitting_opening_fields_starts_all_zero
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        res = api.create_billing_ledger(
            {"client_laboratory_id": scenario["client"]["id"]}, billing_headers)
        assert res.status_code == 201
        ledger = res.json()["data"]
        assert ledger["billed_cents"] == 0.00
        assert ledger["voided_cents"] == 0.00
        assert ledger["net_billed_cents"] == 0.00
        assert ledger["charge_entry_count"] == 0
        assert ledger["status"] == "OPEN"
        assert ledger["version"] == 1


# =============================================================================
# Authentication and role gating
# =============================================================================

class TestUserContextAndRoleGating:

    def test_request_without_user_context_headers_returns_missing_user_context(self, api):
        """PRD 2.1: "Every request must carry two headers. `X-User-ID` identifies
        the acting party and `X-User-Role` names their operational capacity. Both
        are mandatory; a request that omits either one, or that presents an
        `X-User-Role` value that is not one of the recognised role names, is
        rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400)."
        PRD 2.1: "This header check runs before every other rule in the system,
        so a request that is malformed in several ways at once still reports the
        header failure."

        Design: Corner/errors/request_without_user_context_headers_returns_missing_user_context
        """
        res = api.get_send_out_order(NON_EXISTENT_UUID, {})
        assert res.status_code == 400
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_MISSING_USER_CONTEXT"
        assert body["data"]["error_id"] != "ERR_SEND_OUT_ORDER_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()

    def test_only_reference_lab_operations_may_withdraw_a_catalogue_entry(
            self, api, ops_headers, client_admin_headers, accessioning_headers):
        """PRD 2.1: "Performing an operation that is not permitted for one's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD 3.4: "Withdrawal is the heavier act and belongs to a
        `ReferenceLabOperations` operator, available from either `PUBLISHED` or
        `DEPRECATED`".

        Design: Corner/rbac/accessioning_technologist_cannot_withdraw_a_catalogue_entry
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        entry_id = scenario["entry"]["id"]

        refused = api.withdraw_catalog_entry(entry_id, accessioning_headers)
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
        assert api.get_catalog_entry(entry_id, ops_headers).json()["data"]["status"] == "PUBLISHED"

        allowed = validate_success(api.withdraw_catalog_entry(entry_id, ops_headers), 200)
        assert allowed["status"] == "WITHDRAWN"
        data, meta = validate_paginated(api.list_catalog_entries(
            ops_headers, params={"status": "PUBLISHED"}))
        assert meta["total_count"] == 0

    def test_only_interface_analyst_may_certify_a_build(
            self, api, ops_headers, interface_headers, courier_headers):
        """PRD 2.1: "Performing an operation that is not permitted for one's role
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD 3.12: "Certification is the gate to live traffic. It requires the
        build to be `IN_BUILD` and to have completed at least one round-trip
        order and one round-trip result against the client's test endpoint".

        Design: Corner/rbac/interface_analyst_certifies_a_build_while_other_roles_cannot
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        client = scenario["client"]
        build = validate_success(api.create_interface_build({
            "client_laboratory_id": client["id"],
            "build_version_label": "v2-in-build",
            "format": "HL7_V2_5_1",
            "order_interface_enabled": True,
            "result_interface_enabled": True,
        }, interface_headers), 201)
        started = validate_success(api.start_interface_build(build["id"], interface_headers), 200)
        # PRD 3.12: starting construction moves the build to IN_BUILD; the client's
        # derived interface_status is not asserted mid-flight because PRD 3.1
        # names only the NOT_BUILT/IN_BUILD/CERTIFIED reading of a client's most
        # advanced *build*, and the scenario already holds a certified one.
        assert started["status"] == "IN_BUILD"

        refused = api.certify_interface_build(build["id"], courier_headers)
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

        certified = validate_success(api.certify_interface_build(build["id"], interface_headers), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] is not None
        assert api.get_client_laboratory(client["id"], ops_headers).json()["data"]["interface_status"] == "CERTIFIED"

    def test_peer_role_without_the_operation_cannot_book_a_courier_run(
            self, api, ops_headers, courier_headers):
        """PRD 2.1: "Ten roles are recognised, and their names must be spelled
        exactly as follows: `ReferenceLabOperations`, `LabClientAdmin`,
        `CourierCoordinator`, ..."
        PRD 2.1: "Performing an operation that is not permitted for one's role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/peer_role_without_the_operation_cannot_book_a_courier_run
        """
        client = validate_success(api.create_client_laboratory({
            "name": "Uintah Basin Clinic",
            "clia_number": "45D-3002",
            "client_type": "PHYSICIAN_OFFICE",
            "state_code": "UT",
            "billing_arrangement": "PATIENT",
            "credit_limit_cents": 400000,
        }, ops_headers), 201)
        version = api.get_client_laboratory(client["id"], ops_headers).json()["data"]["version"]
        body = {
            "client_laboratory_id": client["id"],
            "route_code": "VER-Y",
            "origin_city": "Vernal",
            "destination_city": "Salt Lake City",
            "vehicle_id": "SUV-32",
            "scheduled_departure_at": "2026-09-01T22:00:00Z",
            "scheduled_arrival_at": "2026-09-02T03:30:00Z",
            "scheduled_pickup_at": "2026-09-01T22:00:00Z",
            "scheduled_delivery_at": "2026-09-02T03:30:00Z",
            "temperature_control_mode": "AMBIENT",
            "expected_client_laboratory_version": version,
        }

        refused = api.create_courier_run(body, ops_headers)
        validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

        accepted = api.create_courier_run(dict(body, route_code="VER-X", vehicle_id="SUV-31"),
                                         courier_headers)
        assert accepted.status_code == 201
        assert accepted.json()["data"]["status"] == "PLANNED"
        data, meta = validate_paginated(api.list_courier_runs(
            ops_headers, params={"client_laboratory_id": client["id"]}))
        assert meta["total_count"] == 1

    def test_client_administrator_cannot_act_on_another_clients_order(
            self, api, ops_headers, accessioning_headers):
        """PRD 2.1: "When `X-User-Role` is `LabClientAdmin`, `X-User-ID` is the
        `id` of the acting `ClientLaboratory`; ownership checks on any resource
        that references a `ClientLaboratory` compare the resource's
        `client_laboratory_id` field to `X-User-ID`, and a mismatch yields
        `ERR_CLIENT_SCOPE_VIOLATION`."

        Design: Corner/rbac/client_administrator_cannot_act_on_another_clients_order
        """
        scenario = setup_active_client(clock="2026-09-01T00:00:00Z")
        foreign = validate_success(api.create_client_laboratory({
            "name": "Emery County Clinic",
            "clia_number": "45D-4001",
            "client_type": "PHYSICIAN_OFFICE",
            "state_code": "UT",
            "billing_arrangement": "CLIENT",
            "credit_limit_cents": 400000,
        }, ops_headers), 201)
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3901",
            "patient_mrn": "MRN-3901",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 3.0,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T03:30:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, accessioning_headers), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3901",
            "patient_mrn": "MRN-3901",
            "client_requested_at": "2026-08-31T20:45:00Z",
            "priority": "ROUTINE",
            "test_lines": [{"test_catalog_entry_id": scenario["entry"]["id"], "line_sequence": 1}],
            "override_utilization_guard": False,
        }, accessioning_headers), 201)

        refused = api.cancel_order(order["id"], make_lab_client_admin_headers(foreign["id"]))
        err = validate_error(refused, "ERR_CLIENT_SCOPE_VIOLATION", expected_status=403)
        assert err["error_id"] != "ERR_INSUFFICIENT_PERMISSIONS"

        owned = validate_success(api.cancel_order(
            order["id"], make_lab_client_admin_headers(scenario["client"]["id"])), 200)
        assert owned["order_status"] == "CANCELLED"
        assert owned["client_laboratory_id"] == scenario["client"]["id"]