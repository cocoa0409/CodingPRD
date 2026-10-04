"""Catalog foundations: item pallet design, region validation, envelope shape,
and role-based access control."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_item,
    build_user_headers,
    create_club_payload,
    create_item_payload,
    create_member_payload,
    create_region,
    create_region_payload,
    create_vendor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestItemPalletDesign:
    def test_item_create_computes_pallet_quantity_standard_footprint(self, api, category_manager_headers):
        """PRD §3.1: "pallet_qty_units` is the product of `case_pack_qty`, `cases_per_layer`, and
        `max_layers`. `pallets_per_slot` is 1 when the pallet footprint — the product of
        `pallet_length_in` and `pallet_width_in` — is at most the standard floor-slot
        area of 48 inches by 40 inches, and 2 when the footprint exceeds it."
        PRD §3.1: "A new item begins life in `DRAFT`."

        Design: Corner/entities/item_create_computes_pallet_quantity_and_ignores_client_override
        """
        region = create_region()
        vendor = create_vendor()
        payload = create_item_payload(
            vendor["id"], sku="2100021", case_pack_qty=24, pallet_length_in=40,
            pallet_width_in=40, cases_per_layer=5, max_layers=4, item_type="REGULAR",
        )
        resp = api.create_item(payload, category_manager_headers)
        item = validate_success(resp, 201)
        assert_item(item)
        assert item["pallet_qty_units"] == 480, f"expected 480 (24*5*4), got {item['pallet_qty_units']}"
        assert item["pallets_per_slot"] == 1, f"footprint 1600 <= 1920 must give 1, got {item['pallets_per_slot']}"
        assert item["status"] == "DRAFT"
        assert item["version"] == 1

    def test_item_create_computes_pallet_quantity_oversized_boundary(self, api, category_manager_headers):
        """PRD §3.1: "pallets_per_slot` is 1 when the pallet footprint — the product of `pallet_length_in` and
        `pallet_width_in` — is at most the standard floor-slot area of 48 inches by 40
        inches, and 2 when the footprint exceeds it."

        Design: Corner/entities/item_create_computes_pallet_quantity_and_ignores_client_override
        """
        region = create_region()
        vendor = create_vendor()
        payload = create_item_payload(
            vendor["id"], sku="2100022", case_pack_qty=10, pallet_length_in=48,
            pallet_width_in=41, cases_per_layer=2, max_layers=2, item_type="REGULAR",
        )
        resp = api.create_item(payload, category_manager_headers)
        item = validate_success(resp, 201)
        assert item["pallet_qty_units"] == 40, f"expected 40 (10*2*2), got {item['pallet_qty_units']}"
        assert item["pallets_per_slot"] == 2, f"footprint 1968 > 1920 must give 2, got {item['pallets_per_slot']}"

    def test_footprint_exactly_48x40_consumes_one_slot(self, api, category_manager_headers):
        """PRD §3.1: "pallets_per_slot` is 1 when the pallet footprint — the product of `pallet_length_in` and
        `pallet_width_in` — is at most the standard floor-slot area of 48 inches by 40
        inches, and 2 when the footprint exceeds it."

        Design: Corner/entities/oversized_item_footprint_consumes_two_slots
        """
        region = create_region()
        vendor = create_vendor()
        exact = create_item_payload(
            vendor["id"], sku="2200022", case_pack_qty=10, pallet_length_in=48,
            pallet_width_in=40, cases_per_layer=2, max_layers=2, item_type="REGULAR",
        )
        over = create_item_payload(
            vendor["id"], sku="2200023", case_pack_qty=10, pallet_length_in=48,
            pallet_width_in=41, cases_per_layer=2, max_layers=2, item_type="REGULAR",
        )
        item_exact = validate_success(api.create_item(exact, category_manager_headers), 201)
        item_over = validate_success(api.create_item(over, category_manager_headers), 201)
        assert item_exact["pallets_per_slot"] == 1, "1920 <= 1920: inclusive boundary stays at 1 slot"
        assert item_over["pallets_per_slot"] == 2, "1968 > 1920: oversized footprint takes 2 slots"

    def test_footprint_one_inch_over_consumes_two_slots(self, api, category_manager_headers):
        """PRD §3.1: "pallets_per_slot` is 1 when the pallet footprint — the product of `pallet_length_in` and
        `pallet_width_in` — is at most the standard floor-slot area of 48 inches by 40
        inches, and 2 when the footprint exceeds it."

        Design: Corner/entities/oversized_item_footprint_consumes_two_slots
        """
        region = create_region()
        vendor = create_vendor()
        payload = create_item_payload(
            vendor["id"], sku="2200024", case_pack_qty=10, pallet_length_in=49,
            pallet_width_in=40, cases_per_layer=2, max_layers=2, item_type="REGULAR",
        )
        item = validate_success(api.create_item(payload, category_manager_headers), 201)
        assert item["pallets_per_slot"] == 2, "1960 > 1920 must consume two floor slots"


class TestMemberDefaults:
    def test_member_defaults_household_size_and_status(self, api, membership_desk_headers):
        """PRD §3.5: "a `tier` of either `GOLD_STAR` or `EXECUTIVE`, and a `household_size` of at least 1
        (default 1) that later feeds complaint weighting. Members begin `ACTIVE`; the
        desk may suspend a member, moving them to `SUSPENDED`."

        Design: Corner/entities/member_default_household_size_and_status
        """
        region = create_region()
        from test_helpers import create_club, create_member
        club = create_club(region["id"], club_number=2101)
        member = create_member(club["id"], membership_number="M000000601")
        assert member["household_size"] == 1, f"default household_size must be 1, got {member['household_size']}"
        assert member["status"] == "ACTIVE", f"members begin ACTIVE, got {member['status']}"


class TestReferenceAndEnvelope:
    def test_get_missing_region_returns_not_found(self, api, regional_ops_headers):
        """PRD §2.8: "a dangling reference — path or body — is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/region_not_found_returns_404
        """
        resp = api.get_region(NON_EXISTENT_UUID, regional_ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_envelope_and_created_at_ascending_order(self, api, regional_ops_headers):
        """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and
        `has_more` inside `meta`. The default sort order for every list endpoint is
        `created_at` ascending; no tie-break on `id` is ever applied for business
        purposes."

        Design: Corner/entities/list_pagination_envelope_defaults
        """
        create_region(code="RD", name="R4")
        create_region(code="RE", name="R5")
        resp = api.list_regions(regional_ops_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected 2 regions, got {len(data)}"
        assert data[0]["code"] == "RD", "default sort is created_at ascending"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_list_envelope_pagination_fields_present(self, api, regional_ops_headers):
        """PRD §2.3: "All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to
        10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0."

        Design: Corner/entities/list_pagination_envelope_defaults
        """
        create_region(code="RH", name="R10")
        resp = api.list_regions(regional_ops_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1


class TestRegionValidation:
    def test_duplicate_region_code_rejected(self, api, regional_ops_headers):
        """PRD §3.1: "A region carries a human-readable `name`, a `code` of two to four uppercase letters that
        must be unique across regions, and `avg_member_income_cents`, the average member
        household income in cents that later feeds allocation weighting; the income
        figure must be at least zero."

        Design: Corner/entities/duplicate_region_code_rejected
        """
        create_region(code="DUP", name="R6")
        resp = api.create_region(
            create_region_payload(code="DUP", name="R7"), regional_ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)

    def test_lowercase_region_code_rejected(self, api, regional_ops_headers):
        """PRD §2.8: "requests whose field values violate format, range, or enum rules — a `sku` that is not
        exactly seven digits, a region `code` that is not two to four uppercase letters,
        a time not in HH:MM form — are rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/invalid_region_code_format_rejected
        """
        resp = api.create_region(
            create_region_payload(code="abc", name="R8"), regional_ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_create_region_missing_required_field_rejected(self, api, regional_ops_headers):
        """PRD §2.8: "Requests with a malformed body or a missing required field are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400), and requests whose field values violate
        format, range, or enum rules — a `sku` that is not exactly seven digits, a
        region `code` that is not two to four uppercase letters, a time not in HH:MM
        form — are rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_region_missing_required_field_returns_invalid_request
        """
        resp = api.create_region({"name": "R9", "code": "RF"}, regional_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failure(self, api, regional_ops_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope
        format" with "response_type": "error" and "data": {"error_id": ...,
        "message": "A human-readable explanation of the error."}

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api.get_club(NON_EXISTENT_UUID, regional_ops_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND
        assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0


class TestRoleAccess:
    def test_exclusive_operations_denied_to_other_roles(
        self, api, membership_desk_headers, depot_manager_headers
    ):
        """PRD §2.1: "A request whose role is not permitted for the endpoint — or whose entity-backed identity
        does not match the resource being acted upon — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /wcd/items is authorized for CategoryManager; POST /wcd/regions for
        RegionalOps; POST /wcd/cross-dock-runs for DepotPlanner.

        Design: Corner/roles/rbac_exclusive_operations_denied_to_other_roles
        """
        region = create_region(code="RAH")
        vendor = create_vendor()
        from test_helpers import create_depot
        depot = create_depot(region["id"])
        # MembershipDesk cannot create items (CategoryManager-only)
        item_payload = create_item_payload(vendor["id"], sku="4800048")
        validate_error(api.create_item(item_payload, membership_desk_headers), ApiErrorId.ERR_FORBIDDEN)
        # VendorRep cannot create regions (RegionalOps-only)
        from test_helpers import make_vendor_rep_headers
        validate_error(
            api.create_region(create_region_payload(code="RAI", name="RAH2"),
                              make_vendor_rep_headers(vendor["id"])),
            ApiErrorId.ERR_FORBIDDEN,
        )
        # DepotManager cannot create cross-dock runs (DepotPlanner-only)
        validate_error(
            api.create_cross_dock_run(
                {"depot_id": depot["id"], "run_date": "2026-09-02", "cutoff_time": "16:00"},
                depot_manager_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )

    def test_request_without_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside the declared set, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/roles/missing_auth_headers_rejected
        """
        resp = api.list_regions(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_request_with_undeclared_role_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside the declared set, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/roles/missing_auth_headers_rejected
        """
        resp = api.list_regions(headers=build_user_headers("test-x", "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
