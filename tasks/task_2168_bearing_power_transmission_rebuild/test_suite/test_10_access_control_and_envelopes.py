# -*- coding: utf-8 -*-
"""Authentication, role and action authorisation, envelopes and the 404 catalogue."""
import pytest

from test_helpers import (
    ADMIN_1, ENG_1, INSP_1, ONE_BAND, PLANNER_1, ApiErrorId, add_measurement,
    api_client as api, build_user_headers, create_asset, create_bench, create_core,
    create_customer, create_order, create_reading, create_standard,
    customer_version, is_iso8601_timestamp, open_inspection, order_version,
    read_customer, read_inspection, reserve_bench, setup_shop, validate_error,
    validate_paginated, validate_success,
)

UNKNOWN_ID = "44444444-4444-4444-8444-444444444444"


class TestAuthenticationAndRoles:

    def test_an_unknown_role_short_circuits_the_whole_ladder(self):
        """PRD 2.1: "Every request, without exception, must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in which they are
        acting. If either header is missing or empty, or if `X-User-Role` is not one of the five
        role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This
        check runs before anything else — before the path is resolved, before the body is
        parsed."

        Design: Corner/validations/request_with_missing_auth_headers_returns_unauthenticated
        """
        customer = create_customer(name="Auth Mill", account_code="AUT-001")
        resp = api.cancel_rebuild_order(
            "22222222-2222-4222-8222-222222222222",
            {"cancel_reason": "no credentials"},
            build_user_headers("nobody", "UnknownRole"))
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        assert error["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value

        validate_success(api.get_customer(customer["id"], ADMIN_1))

    def test_endpoint_level_role_lists_are_enforced_on_shop_admin_only_writes(self):
        """PRD 2.1: "Once the caller is authenticated, the role is checked against the
        endpoint's authorised-role list from the table in §4. A caller whose role is absent from
        that list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.1: "A `ShopAdmin` is the service-centre manager. Reference data, core receipt, the
        credit ledger, installations and warranty adjudication all belong to this role."

        Design: Corner/rbac/planner_cannot_receive_cores_or_post_credit_notes
        """
        world = setup_shop(account_code="ROL-001", customer_name="Role Mill",
                           asset_tag="ROL-01-GBX", serial_no="SN-ROL-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        cust_id, order_id = world["customer"]["id"], world["order"]["id"]
        cv = customer_version(cust_id)

        validate_error(api.create_core_unit({
            "customer_id": cust_id, "clearance_standard_id": world["standard"]["id"],
            "serial_no": "SN-ROL-2", "rebuild_count": 0,
            "declared_condition_grade": "GRADE_B"}, PLANNER_1),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        validate_error(api.create_manual_credit_note(cust_id, {
            "amount_cents": 1000, "memo": "not my job",
            "expected_customer_version": cv}, PLANNER_1),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        validate_error(api.cancel_rebuild_order(
            order_id, {"cancel_reason": "not my job either"}, INSP_1),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        _, meta = validate_paginated(api.list_core_units(
            ADMIN_1, params={"customer_id": cust_id}))
        assert meta["total_count"] == 1
        assert read_customer(cust_id)["total_credit_balance_cents"] == 67500
        from test_helpers import read_order
        assert read_order(order_id)["work_status"] == "DRAFT"

    def test_the_action_level_permission_map_is_finer_than_the_endpoint_role_list(self):
        """PRD 2.1: "Several endpoints take an `action` or `decision` discriminator in the body,
        and the role check goes one level deeper on those: a role may be permitted to reach the
        endpoint yet not permitted to invoke that particular action, in which case the rejection
        is `ERR_ACTION_NOT_PERMITTED_FOR_ROLE` (HTTP 403)."
        PRD 2.1: "On the inspection advance endpoint, `SUBMIT` is open only to `Inspector`;
        `ACCEPT` to `Inspector` and `ShopAdmin`; `RETURN` to `ReliabilityEngineer` and
        `ShopAdmin`; `REOPEN` only to `Inspector`."

        Design: Corner/rbac/planner_cannot_use_the_inspector_only_submit_action
        """
        world = setup_shop(account_code="ACT-001", customer_name="Action Mill",
                           asset_tag="ACT-01-GBX", serial_no="SN-ACT-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        reading = create_reading(world["asset"]["id"])
        insp = open_inspection(world["order"]["id"],
                               linked_vibration_reading_id=reading["id"])
        add_measurement(insp["id"], "BORE", 85)

        error = validate_error(
            api.advance_inspection(insp["id"], {"action": "SUBMIT"}, ADMIN_1),
            ApiErrorId.ERR_ACTION_NOT_PERMITTED_FOR_ROLE.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        submitted = validate_success(
            api.advance_inspection(insp["id"], {"action": "SUBMIT"}, INSP_1))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "insp-1"

        validate_error(api.advance_inspection(
            insp["id"], {"action": "RETURN", "return_reason": "not my call"}, INSP_1),
            ApiErrorId.ERR_ACTION_NOT_PERMITTED_FOR_ROLE.value, 403)

        returned = validate_success(api.advance_inspection(
            insp["id"], {"action": "RETURN", "return_reason": "re-shoot it"}, ENG_1))
        assert returned["status"] == "RETURNED"


class TestEnvelopesAndPagination:

    def test_success_and_error_envelopes_carry_their_declared_shape(self):
        """PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for
        a list of resources."
        PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/endpoints/success_and_error_envelopes_carry_the_declared_shape
        """
        bench = create_bench(bench_code="B-ENV", parallel_slots=2, cleanroom=True)

        single = api.get_bench(bench["id"], ADMIN_1)
        body = single.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["cleanroom"] is True
        assert body["data"]["parallel_slots"] == 2

        listing = api.list_bench_reservations(bench["id"], ADMIN_1)
        list_body = listing.json()
        assert list_body["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"list meta must carry {field}"

        missing = api.get_bench("33333333-3333-4333-8333-333333333333", ADMIN_1)
        error_body = missing.json()
        assert missing.status_code == 404
        assert error_body["response_type"] == "error"
        assert error_body["data"]["error_id"] == ApiErrorId.ERR_BENCH_NOT_FOUND.value
        assert error_body["data"]["message"].strip()

    def test_pagination_parameters_outside_their_bounds_are_rejected(self):
        """PRD 2.3: "A `limit` outside the 1-to-100 range, or a negative `offset`, is a
        malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than
        being silently clamped."

        Design: Corner/endpoints/pagination_parameters_outside_their_bounds_are_rejected
        """
        customer = create_customer(name="Bound Mill", account_code="BND-001")
        standard = create_standard(feature_bands=ONE_BAND)
        create_core(customer["id"], standard["id"], serial_no="SN-BND-1",
                    declared_condition_grade="GRADE_B")

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(api.list_core_units(ADMIN_1, params=params),
                           ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        rows, meta = validate_paginated(
            api.list_core_units(ADMIN_1, params={"limit": 100, "offset": 0}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_every_declared_foreign_key_is_reachable_backwards(self):
        """PRD 2.5: "Many resources are addressed through a nested path — an account's assets, a
        bench's reservations, an order's part lines, an inspection's measurements, an
        installation's claims."
        PRD 2.3: "`total_count` reports the number of rows matching the filter before paging is
        applied, and `has_more` is true exactly when rows remain beyond the current page."

        Design: Corner/endpoints/sub_resource_lookups_resolve_children_from_each_parent
        """
        world = setup_shop(account_code="LNK-001", customer_name="Link Mill",
                           asset_tag="LNK-01-GBX", serial_no="SN-LNK-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0,
                           bench_code="B-LNK")
        bare = create_customer(name="Bare Mill", account_code="LNK-002")
        cust_id, asset_id = world["customer"]["id"], world["asset"]["id"]
        order_id, bench_id = world["order"]["id"], world["bench"]["id"]

        from test_helpers import add_part_line
        part_line = add_part_line(order_id, part_no="BRG-22324", qty=1,
                                  unit_cost_cents=40000)
        reservation = reserve_bench(order_id, bench_id,
                                    "2026-09-12T08:00:00Z", "2026-09-12T12:00:00Z")
        reading = create_reading(asset_id)
        insp = open_inspection(order_id, linked_vibration_reading_id=reading["id"])
        add_measurement(insp["id"], "BORE", 85)

        rows, meta = validate_paginated(api.list_customer_assets(cust_id, ADMIN_1))
        assert meta["total_count"] == 1 and rows[0]["id"] == asset_id

        rows, meta = validate_paginated(api.list_asset_vibration_readings(asset_id, ADMIN_1))
        assert meta["total_count"] == 1 and rows[0]["id"] == reading["id"]

        rows, meta = validate_paginated(api.list_part_lines(order_id, ADMIN_1))
        assert meta["total_count"] == 1 and rows[0]["id"] == part_line["id"]

        rows, meta = validate_paginated(api.list_order_bench_reservations(order_id, ADMIN_1))
        assert meta["total_count"] == 1 and rows[0]["id"] == reservation["id"]

        _, meta = validate_paginated(api.list_measurements(insp["id"], ADMIN_1))
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(api.list_bench_reservations(bench_id, ADMIN_1))
        assert meta["total_count"] == 1 and rows[0]["id"] == reservation["id"]

        rows, meta = validate_paginated(api.list_inspections(
            ADMIN_1, params={"linked_vibration_reading_id": reading["id"]}))
        assert meta["total_count"] == 1 and rows[0]["id"] == insp["id"]

        rows, meta = validate_paginated(api.list_customer_assets(bare["id"], ADMIN_1))
        assert meta["total_count"] == 0 and rows == []


class TestErrorCatalogue:

    def test_each_unresolvable_id_answers_with_its_own_not_found_code(self):
        """PRD 2.5: "Each entity type has its own not-found code: `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_ASSET_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`, `ERR_BENCH_NOT_FOUND`,
        `ERR_CORE_UNIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
        `ERR_READING_NOT_FOUND`, `ERR_PART_LINE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_INSTALLATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_CREDIT_NOTE_NOT_FOUND`, all
        HTTP 404."
        PRD 2.5: "The same codes are reused for foreign keys supplied in a request body, but
        body foreign keys are resolved later in the ladder (see §2.8) and in the order the
        endpoint declares its input fields."

        Design: Corner/errors/unknown_ids_in_paths_and_bodies_return_entity_specific_not_found
        """
        world = setup_shop(account_code="NF-001", customer_name="NotFound Mill",
                           asset_tag="NF-01-GBX", serial_no="SN-NF-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0,
                           bench_code="B-NF")

        validate_error(api.get_asset(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_ASSET_NOT_FOUND.value, 404)
        validate_error(api.get_clearance_standard(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_STANDARD_NOT_FOUND.value, 404)
        validate_error(api.get_bench(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_BENCH_NOT_FOUND.value, 404)
        validate_error(api.get_core_unit(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_CORE_UNIT_NOT_FOUND.value, 404)
        validate_error(api.get_rebuild_order(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
        validate_error(api.get_inspection(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_INSPECTION_NOT_FOUND.value, 404)
        validate_error(api.get_installation(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_INSTALLATION_NOT_FOUND.value, 404)
        validate_error(api.get_warranty_claim(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404)
        validate_error(api.get_credit_note(UNKNOWN_ID, ADMIN_1),
                       ApiErrorId.ERR_CREDIT_NOTE_NOT_FOUND.value, 404)
        validate_error(api.advance_part_line(UNKNOWN_ID, {"action": "SUBMIT"}, PLANNER_1),
                       ApiErrorId.ERR_PART_LINE_NOT_FOUND.value, 404)
        validate_error(api.advance_bench_reservation(
            UNKNOWN_ID, {"action": "CONFIRM"}, PLANNER_1),
            ApiErrorId.ERR_RESERVATION_NOT_FOUND.value, 404)

        validate_error(api.create_inspection({
            "rebuild_order_id": world["order"]["id"],
            "linked_vibration_reading_id": UNKNOWN_ID}, INSP_1),
            ApiErrorId.ERR_READING_NOT_FOUND.value, 404)
        validate_error(api.create_rebuild_order({
            "customer_id": world["customer"]["id"], "core_unit_id": UNKNOWN_ID,
            "customer_asset_id": world["asset"]["id"], "labor_hours": 4.0}, PLANNER_1),
            ApiErrorId.ERR_CORE_UNIT_NOT_FOUND.value, 404)

    def test_reused_unique_keys_are_rejected_with_the_right_duplicate_code(self):
        """PRD 3.1: "An account is opened with a legal `name` for the plant being billed and a
        short `account_code` of between 1 and 32 characters that must be unique across all
        accounts; a reliability `contact_email` may be supplied and defaults to null when it is
        not."
        PRD 3.1: "Re-using an `account_code` that already exists is rejected with
        `ERR_DUPLICATE_KEY`."
        PRD 3.1: "A repeated `asset_tag` inside the same account is `ERR_DUPLICATE_KEY`."
        PRD 3.2: "The `serial_no` must be unique within that account; a repeat is
        `ERR_DUPLICATE_SERIAL`."

        Design: Corner/errors/duplicate_account_code_model_code_bench_code_and_serial_are_rejected
        """
        cust_a = create_customer(name="Dup Mill", account_code="DUP-001")
        cust_b = create_customer(name="Other Mill", account_code="DUP-002")
        create_asset(cust_a["id"], asset_tag="DUP-01-GBX", criticality="STANDARD",
                     duty_class="CONTINUOUS")
        standard = create_standard(feature_bands=ONE_BAND)
        create_bench(bench_code="B-DUP", parallel_slots=1)
        create_core(cust_a["id"], standard["id"], serial_no="SN-DUP-1",
                    declared_condition_grade="GRADE_B")

        validate_error(api.create_customer(
            {"name": "Clone Mill", "account_code": "DUP-001"}, ADMIN_1),
            ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

        validate_error(api.create_clearance_standard({
            "model_code": "SKF-22324-CCK", "base_core_value_cents": 5000,
            "max_rebuild_count": 1, "warranty_hours": 100, "warranty_months": 1,
            "cleanroom_required": False, "required_feature_codes": ["BORE"],
            "feature_bands": ONE_BAND}, ADMIN_1),
            ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

        validate_error(api.create_bench(
            {"bench_code": "B-DUP", "parallel_slots": 3, "cleanroom": False}, ADMIN_1),
            ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

        validate_error(api.create_asset(cust_a["id"], {
            "asset_tag": "DUP-01-GBX", "criticality": "CRITICAL",
            "duty_class": "STANDBY"}, ADMIN_1),
            ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

        validate_error(api.create_core_unit({
            "customer_id": cust_a["id"], "clearance_standard_id": standard["id"],
            "serial_no": "SN-DUP-1", "rebuild_count": 0,
            "declared_condition_grade": "GRADE_B"}, ADMIN_1),
            ApiErrorId.ERR_DUPLICATE_SERIAL.value, 409)

        validate_success(api.create_core_unit({
            "customer_id": cust_b["id"], "clearance_standard_id": standard["id"],
            "serial_no": "SN-DUP-1", "rebuild_count": 0,
            "declared_condition_grade": "GRADE_B"}, ADMIN_1), 201)

        _, meta = validate_paginated(api.list_core_units(
            ADMIN_1, params={"customer_id": cust_a["id"]}))
        assert meta["total_count"] == 1
