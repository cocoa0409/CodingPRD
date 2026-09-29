"""Entity round-trips: envelope shape, defaults, derived reads and foreign-key filters."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_common_fields,
    assert_inventory_lot,
    assert_material,
    assert_response_meta,
)
from test_helpers.factories import (
    create_delivery_order_payload,
    create_order_line_payload,
    create_will_call_order_payload,
)
from test_helpers.fixtures import read_order, seed_account
from test_helpers.test_users import (
    make_contractor_headers,
    make_headers_for_role,
    make_yard_admin_headers,
)

MISSING_MATERIAL_ID = "00000000-0000-4000-8000-0000000000e4"
DANGLING_MATERIAL_ID = "00000000-0000-4000-8000-0000000000ea"


class TestMaterialCreation:
    """What a registration stores, what it defaults, and what the envelope carries."""

    def test_a_fully_specified_registration_returns_the_standard_object_envelope(self, api):
        """Every declared input is echoed and the two derived figures start at rest.

        PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        PRD 3.1: "Registration leaves the material's `status` at `ACTIVE`, its
        `available_net_cubic_yards` at 0.0, and its `effective_density_lb_per_cubic_yard`
        computed from the moisture profile as described in section 3.5."

        Design: Corner/entities/material_create_returns_201_with_full_envelope
        """
        response = api.create_material(
            {
                "sku": "MULCH-E1",
                "name": "Corner Test Mulch",
                "offered_forms": ["BULK", "BAGGED"],
                "seasonal_category": "MULCH",
                "density_lb_per_cubic_yard": 1000,
                "shrinkage_factor": 0.10,
                "moisture_pct": 15.0,
                "unit_bag_cubic_yards": 0.037,
                "prebuy_eligible": False,
            },
            headers=make_yard_admin_headers(),
        )
        assert response.status_code == 201

        body = response.json()
        assert body["response_type"] == "object"
        assert_response_meta(body)

        material = validate_success(response, 201)
        assert_material(material)
        assert is_valid_uuid(material["id"])
        assert material["sku"] == "MULCH-E1"
        assert material["name"] == "Corner Test Mulch"
        assert material["offered_forms"] == ["BULK", "BAGGED"]
        assert material["seasonal_category"] == "MULCH"
        assert material["density_lb_per_cubic_yard"] == 1000
        assert material["shrinkage_factor"] == pytest.approx(0.10, abs=CENTS)
        assert material["status"] == "ACTIVE"
        assert material["version"] == 1
        # 15.0 is the yard's reference moisture, so the uplift term is zero
        assert material["effective_density_lb_per_cubic_yard"] == pytest.approx(1000.00, abs=CENTS)
        assert material["available_net_cubic_yards"] == pytest.approx(0.0, abs=CENTS)

    def test_omitting_the_three_optional_inputs_applies_the_declared_defaults(self, api):
        """A registration naming only the mandatory profile still lands on a complete row.

        PRD 3.1: "`moisture_pct` is the yard-wide moisture reading for the material, between
        0 and 60 inclusive, defaulting to 15.0 when the registration omits it."

        PRD 3.1: "`unit_bag_cubic_yards` is the loose volume a single bag occupies, strictly
        positive, defaulting to 0.037, and it exists so that a bagged quantity can be
        converted into cubic yards for the purpose of reserving stockpile."

        PRD 3.1: "`prebuy_eligible` is a boolean defaulting to false that decides whether
        season contracts may be written against the material at all."

        Design: Corner/entities/material_create_omitting_optional_fields_applies_declared_defaults
        """
        material = validate_success(
            api.create_material(
                {
                    "sku": "SOIL-E6",
                    "name": "Default Soil",
                    "offered_forms": ["BULK"],
                    "seasonal_category": "SOIL",
                    "density_lb_per_cubic_yard": 1200,
                    "shrinkage_factor": 0.10,
                },
                headers=make_yard_admin_headers(),
            ),
            201,
        )
        assert material["moisture_pct"] == pytest.approx(15.0, abs=CENTS)
        assert material["unit_bag_cubic_yards"] == pytest.approx(0.037, abs=0.0001)
        assert material["prebuy_eligible"] is False
        # the defaulted moisture is the reference point, so density passes through unchanged
        assert material["effective_density_lb_per_cubic_yard"] == pytest.approx(1200.00, abs=CENTS)
        assert material["status"] == "ACTIVE"
        assert material["version"] == 1

    def test_the_system_fields_are_server_minted_and_a_patch_advances_the_version(self, api):
        """A moisture edit moves version and updated_at while id and created_at stay put.

        PRD 2.4: "`version` is an integer that starts at 1 when the record is created and
        increases by exactly 1 on every mutation of that record, including mutations the
        caller did not directly request -- a cascade that only recomputes a derived money or
        volume field still advances the touched record's `version` and refreshes its
        `updated_at`."

        PRD 3.1: "Either change recomputes `effective_density_lb_per_cubic_yard` and advances
        the material's `version`."

        Design: Corner/entities/material_system_fields_are_server_minted_and_version_advances
        """
        created = validate_success(
            api.create_material(
                {
                    "sku": "AGG-E8",
                    "name": "System Field Stone",
                    "offered_forms": ["BULK"],
                    "seasonal_category": "AGGREGATE",
                    "density_lb_per_cubic_yard": 1000,
                    "shrinkage_factor": 0.10,
                    "moisture_pct": 15.0,
                    "unit_bag_cubic_yards": 0.037,
                    "prebuy_eligible": False,
                },
                headers=make_yard_admin_headers(),
            ),
            201,
        )
        assert_common_fields(created)
        assert created["version"] == 1

        patched = validate_success(
            api.patch_material(
                created["id"], {"moisture_pct": 20.0}, headers=make_yard_admin_headers()
            ),
            200,
        )
        assert patched["id"] == created["id"]
        assert patched["created_at"] == created["created_at"]
        assert patched["version"] == 2
        assert patched["updated_at"] >= created["updated_at"]
        # ROUND_HALF_UP(1000 * (1 + (20.0 - 15.0) / 100), 2)
        assert patched["effective_density_lb_per_cubic_yard"] == pytest.approx(1050.00, abs=CENTS)


class TestMaterialReads:
    """Reads of the catalogue, one row at a time and by the page."""

    def test_a_read_returns_the_stored_row_with_its_derived_density(self, api):
        """The uplift for 22.5 percent moisture is seven and a half percent of the density.

        PRD 3.5: "The material's `effective_density_lb_per_cubic_yard` is its
        `density_lb_per_cubic_yard` multiplied by one plus the quantity obtained by
        subtracting the yard's reference moisture of 15.0 percent from the material's
        `moisture_pct` and dividing by one hundred, with the result rounded half up to two
        decimal places -- wetter material is heavier per cubic yard, and this is the figure
        the scale house actually cares about."

        PRD 3.1: "Reads of the catalogue may be narrowed by `status`, by `seasonal_category`
        and by `prebuy_eligible`, and are available to every role in the yard."

        Design: Corner/entities/material_get_by_id_returns_stored_row
        """
        created = validate_success(
            api.create_material(
                {
                    "sku": "MULCH-E2",
                    "name": "Retrieval Mulch",
                    "offered_forms": ["BULK"],
                    "seasonal_category": "MULCH",
                    "density_lb_per_cubic_yard": 800,
                    "shrinkage_factor": 0.10,
                    "moisture_pct": 22.5,
                    "unit_bag_cubic_yards": 0.037,
                    "prebuy_eligible": False,
                },
                headers=make_yard_admin_headers(),
            ),
            201,
        )

        fetched = validate_success(
            api.get_material(created["id"], headers=make_headers_for_role("Contractor", "reader-1")),
            200,
        )
        assert fetched["id"] == created["id"]
        assert fetched["sku"] == "MULCH-E2"
        # ROUND_HALF_UP(800 * (1 + (22.5 - 15.0) / 100), 2)
        assert fetched["effective_density_lb_per_cubic_yard"] == pytest.approx(860.00, abs=CENTS)
        # a read is not a mutation, so neither counter moved
        assert fetched["version"] == 1
        assert fetched["updated_at"] == created["updated_at"]

    def test_the_list_page_reports_the_filtered_total_and_the_has_more_flag(self, api):
        """total_count counts the matching set while data carries only the page.

        PRD 2.3: "The `meta` object of a list response carries `limit` and `offset` echoing
        the effective values used, `total_count` giving the number of rows matching the
        filters before pagination was applied, and `has_more` set to true exactly when rows
        remain beyond the current page."

        PRD 2.3: "`limit` controls the page size: it defaults to 10 when omitted, accepts a
        minimum of 1 and a maximum of 100, and a value outside that inclusive range is a
        malformed request."

        Design: Corner/entities/material_list_paginates_with_total_count_and_has_more
        """
        admin = make_yard_admin_headers()
        for sku, name, category, prebuy in (
            ("MULCH-E3A", "Page Mulch A", "MULCH", False),
            ("MULCH-E3B", "Page Mulch B", "MULCH", False),
            ("SALT-E3C", "Page Salt C", "SALT", True),
        ):
            validate_success(
                api.create_material(
                    {
                        "sku": sku,
                        "name": name,
                        "offered_forms": ["BULK"],
                        "seasonal_category": category,
                        "density_lb_per_cubic_yard": 1000,
                        "shrinkage_factor": 0.10,
                        "moisture_pct": 15.0,
                        "unit_bag_cubic_yards": 0.037,
                        "prebuy_eligible": prebuy,
                    },
                    headers=admin,
                ),
                201,
            )

        first_page, first_meta = validate_paginated(
            api.list_materials(headers=admin, params={"limit": 2, "offset": 0})
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(first_page) == 2

        last_page, last_meta = validate_paginated(
            api.list_materials(headers=admin, params={"limit": 2, "offset": 2})
        )
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False
        assert last_meta["offset"] == 2
        assert len(last_page) == 1
        # offset skips rather than filters, so the two pages are disjoint and cover the set
        assert len({row["id"] for row in first_page} & {row["id"] for row in last_page}) == 0
        assert len({row["id"] for row in first_page + last_page}) == 3

        mulch_only, mulch_meta = validate_paginated(
            api.list_materials(headers=admin, params={"seasonal_category": "MULCH"})
        )
        # the filter narrows total_count itself, not just the page
        assert mulch_meta["total_count"] == 2
        assert {row["seasonal_category"] for row in mulch_only} == {"MULCH"}
        # limit and offset were omitted, so their declared defaults apply
        assert mulch_meta["limit"] == 10
        assert mulch_meta["offset"] == 0

    def test_a_well_formed_uuid_matching_no_material_is_a_typed_404(self, api):
        """The error envelope names the resource type rather than returning an empty body.

        PRD 2.4: "A path naming a resource that does not exist yields the 404 error specific
        to that resource type: `ERR_MATERIAL_NOT_FOUND`, `ERR_PRICE_SCHEDULE_NOT_FOUND`,
        `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PO_NOT_FOUND`,
        `ERR_PREBUY_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` or `ERR_CONTAINER_RETURN_NOT_FOUND`."

        PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/material_get_unknown_id_returns_not_found
        """
        response = api.get_material(MISSING_MATERIAL_ID, headers=make_yard_admin_headers())
        validate_error(response, ApiErrorId.MATERIAL_NOT_FOUND.value, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert_response_meta(body)
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""


AGGREGATE_PROFILE = {
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


def _register(api, sku, name, **profile):
    payload = dict(AGGREGATE_PROFILE, sku=sku, name=name)
    payload.update(profile)
    return validate_success(api.create_material(payload, headers=make_yard_admin_headers()), 201)


class TestInventoryLotIntake:
    """Intake computes the sellable figure and refuses to be handed one.

    The lot's parent is a body foreign key rather than a path segment, so it has to be
    dereferenced on the way in.
    """

    def test_omitting_the_intake_moisture_reading_is_a_shape_violation(self, api):
        """The reading carries no default, so it cannot be silently filled in.

        PRD 3.2: "Scaling one in creates an `InventoryLot` naming its `material_id`, the
        `gross_cubic_yards` that came off the scale -- strictly positive -- and the
        `moisture_pct_at_intake` measured on the truck scale, between 0 and 60 inclusive."

        PRD 2.8: "**Request shape** -- on every endpoint: required fields present, every enum
        value inside its declared set, numeric fields positive where the field declares
        positivity, a `BAGGED` `quantity` integral, `limit` inside 1 through 100 and `offset`
        at least 0, and a claim decision naming either `APPROVE` or `DENY` accompanied by its
        matching companion field; else `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/inventory_lot_create_without_moisture_returns_400
        """
        material = _register(api, "AGG-E5", "Required Field Stone")

        rejected = api.create_inventory_lot(
            {"material_id": material["id"], "gross_cubic_yards": 50.0},
            headers=make_yard_admin_headers(),
        )
        validate_error(rejected, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_inventory_lots(
                headers=make_yard_admin_headers(), params={"material_id": material["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert validate_success(
            api.get_material(material["id"], headers=make_yard_admin_headers()), 200
        )["available_net_cubic_yards"] == pytest.approx(0.0, abs=CENTS)

    def test_the_sellable_volume_is_derived_on_the_intake_basis(self, api):
        """A wet pile loses the full shrinkage and the clamped moisture multiplier at once.

        PRD 3.2: "While `basis` is `INTAKE` -- meaning no moisture reading has been filed
        since the lot was scaled in -- `net_sellable_cubic_yards` is the `gross_cubic_yards`
        multiplied by one minus the full `shrinkage_factor` of the material, multiplied by the
        moisture multiplier taken from `moisture_pct_at_intake`, with the product rounded half
        up to two decimal places."

        PRD 3.2: "Intake sets `current_moisture_pct` equal to `moisture_pct_at_intake`, sets
        `basis` to `INTAKE`, sets `status` to `AVAILABLE`, leaves `withdrawn_gross_cubic_yards`
        and `reserved_cubic_yards` at 0.0, computes `net_sellable_cubic_yards`, and refreshes
        the parent material's `available_net_cubic_yards`."

        Design: Corner/entities/inventory_lot_net_sellable_is_computed_not_accepted
        """
        material = _register(
            api, "SOIL-E7", "Computed Soil", seasonal_category="SOIL"
        )

        lot = validate_success(
            api.create_inventory_lot(
                {
                    "material_id": material["id"],
                    "gross_cubic_yards": 40.0,
                    "moisture_pct_at_intake": 25.0,
                },
                headers=make_yard_admin_headers(),
            ),
            201,
        )
        assert_inventory_lot(lot)
        # ROUND_HALF_UP(40.00 * (1 - 0.10) * (1 - (25.0 - 15.0) / 100), 2)
        assert lot["net_sellable_cubic_yards"] == pytest.approx(32.40, abs=CENTS)
        assert lot["basis"] == "INTAKE"
        assert lot["current_moisture_pct"] == pytest.approx(25.0, abs=CENTS)
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert lot["reserved_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
        assert lot["status"] == "AVAILABLE"

        assert validate_success(
            api.get_material(material["id"], headers=make_yard_admin_headers()), 200
        )["available_net_cubic_yards"] == pytest.approx(32.40, abs=CENTS)

    def test_a_body_foreign_key_naming_no_material_is_a_typed_404(self, api):
        """A dangling parent reference is dereferenced rather than stored.

        PRD 2.4: "The same catalogue of 404 codes covers foreign keys arriving in a request
        body -- `material_id`, `contractor_account_id`, `job_purchase_order_id`,
        `material_order_id`, `delivery_truck_id`, `delivery_load_id`, `will_call_ticket_id` --
        and those body references are resolved in the order the endpoint declares its input
        fields, so the first unresolvable reference in declaration order is the one reported."

        Design: Corner/entities/inventory_lot_create_with_unknown_material_returns_not_found
        """
        rejected = api.create_inventory_lot(
            {
                "material_id": DANGLING_MATERIAL_ID,
                "gross_cubic_yards": 50.0,
                "moisture_pct_at_intake": 15.0,
            },
            headers=make_yard_admin_headers(),
        )
        validate_error(rejected, ApiErrorId.MATERIAL_NOT_FOUND.value, 404)

        _, meta = validate_paginated(api.list_inventory_lots(headers=make_yard_admin_headers()))
        assert meta["total_count"] == 0


class TestOrderLineWrites:
    """A line's enum, and the parent reference the reverse read has to travel back along."""

    def test_a_form_outside_the_declared_pair_is_a_shape_violation(self, api):
        """PALLET is not one of the two forms a line may name, so nothing is stored.

        PRD 3.4: "Each `OrderLine` names its `material_order_id`, its `material_id`, its
        `form` (`BULK` or `BAGGED`, and it must appear in the material's `offered_forms`),
        and its `quantity`, which is a strictly positive number interpreted as cubic yards
        for a bulk line and as a whole count of bags for a bagged line -- a non-integral
        bagged quantity is a malformed request."

        PRD 2.8: "**Request shape** -- on every endpoint: required fields present, every enum
        value inside its declared set, numeric fields positive where the field declares
        positivity, a `BAGGED` `quantity` integral, `limit` inside 1 through 100 and `offset`
        at least 0, and a claim decision naming either `APPROVE` or `DENY` accompanied by its
        matching companion field; else `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/order_line_invalid_form_enum_returns_400
        """
        material = _register(api, "AGG-E9", "Enum Stone")
        account = seed_account(
            api, business_name="Enum Landscapes", credit_limit_cents=5000000
        )
        headers = make_contractor_headers(account["id"])
        order = validate_success(
            api.create_material_order(
                create_delivery_order_payload(
                    account["id"], delivery_address="1 Enum St"
                ),
                headers=headers,
            ),
            201,
        )

        # the shape rung sits above the offered-forms business rung, so the enum is what
        # decides the outcome
        rejected = api.create_order_line(
            create_order_line_payload(order["id"], material["id"], "PALLET", 5.0),
            headers=headers,
        )
        validate_error(rejected, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_order_lines(headers=headers, params={"material_order_id": order["id"]})
        )
        assert meta["total_count"] == 0
        assert read_order(api, order["id"])["fulfillment_status"] == "DRAFT"

    def test_the_line_list_narrowed_by_parent_order_sees_only_that_orders_lines(self, api):
        """Two orders on one account, and the filter keeps their lines apart.

        PRD 3.4: "Lines may be listed filtered by `material_order_id`, by `material_id`, by
        `prebuy_contract_id`, by `inventory_lot_id` and by `form`."

        PRD 2.3: "Unless a subsection states a different ordering for a specific collection,
        list results are returned sorted by `created_at` ascending -- oldest record first."

        PRD 3.4: "Everything monetary stays empty at this stage: `unit_price_cents`,
        `line_price_cents`, `final_line_price_cents` and `inventory_lot_id` are all null on a
        draft line, and `delivered_volume_cubic_yards` sits at 0.0."

        Design: Corner/entities/order_line_list_filters_by_parent_order_foreign_key
        """
        material = _register(api, "AGG-E11", "Filter Stone")
        account = seed_account(
            api, business_name="Filter Grounds", credit_limit_cents=5000000
        )
        headers = make_contractor_headers(account["id"])

        order_a = validate_success(
            api.create_material_order(
                create_delivery_order_payload(
                    account["id"], delivery_address="2 Filter Way"
                ),
                headers=headers,
            ),
            201,
        )
        line_a1 = validate_success(
            api.create_order_line(
                create_order_line_payload(order_a["id"], material["id"], "BULK", 3.0),
                headers=headers,
            ),
            201,
        )
        line_a2 = validate_success(
            api.create_order_line(
                create_order_line_payload(order_a["id"], material["id"], "BULK", 4.0),
                headers=headers,
            ),
            201,
        )

        order_b = validate_success(
            api.create_material_order(
                create_will_call_order_payload(account["id"]), headers=headers
            ),
            201,
        )
        line_b1 = validate_success(
            api.create_order_line(
                create_order_line_payload(order_b["id"], material["id"], "BULK", 5.0),
                headers=headers,
            ),
            201,
        )

        admin = make_yard_admin_headers()
        filtered, filtered_meta = validate_paginated(
            api.list_order_lines(headers=admin, params={"material_order_id": order_a["id"]})
        )
        assert filtered_meta["total_count"] == 2
        # oldest first, so the 3.00-cubic-yard line precedes the 4.00-cubic-yard one
        assert [row["id"] for row in filtered] == [line_a1["id"], line_a2["id"]]
        assert line_b1["id"] not in {row["id"] for row in filtered}

        unfiltered, unfiltered_meta = validate_paginated(api.list_order_lines(headers=admin))
        assert unfiltered_meta["total_count"] == 3
        assert {row["id"] for row in unfiltered} == {
            line_a1["id"],
            line_a2["id"],
            line_b1["id"],
        }
        for row in unfiltered:
            # neither order has been confirmed, so no line has been priced or pinned
            assert row["unit_price_cents"] is None
            assert row["line_price_cents"] is None
            assert row["final_line_price_cents"] is None
            assert row["inventory_lot_id"] is None
            assert row["delivered_volume_cubic_yards"] == pytest.approx(0.0, abs=CENTS)
