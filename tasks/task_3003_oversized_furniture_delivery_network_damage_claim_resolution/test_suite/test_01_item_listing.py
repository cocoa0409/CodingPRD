"""Item listing: cubing, freight-class thresholds, and the parcel gate."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_item,
    create_supplier,
    create_item,
    set_clock,
    api_client,
    TEST_USERS,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestCubeScoreWeightedThresholdClassification:
    def test_cube_score_boundary_values_classify_correctly(self, api):
        """PRD §3.1: "First, the item's `cube_score` is computed as a weighted
        blend of its shape: 0.45 times the longest of the three packaged
        dimensions, plus 0.30 times the cube root of the product of the three
        dimensions, plus 0.25 times the sum of the three dimensions — with the
        result rounded half-up to 2 decimal places."
        PRD §3.1: "a score of at most 40.00 yields `PARCEL_ELIGIBLE`; above
        40.00 and at most 70.00 yields `LTL_250`; above 70.00 and at most
        100.00 yields `LTL_150`; above 100.00 and at most 150.00 yields
        `LTL_125`; anything above 150.00 yields `LTL_92_5`."

        Design: Difficulty/combinatorial_formula/cube_score_weighted_threshold_classification
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        bound = create_item(
            supplier["id"], sku="SKU-CB-BOUND",
            dim_length_in=30.9, dim_width_in=24, dim_height_in=20,
            weight_lb=10, declared_value_cents=10000, white_glove_eligible=False,
        )
        over = create_item(
            supplier["id"], sku="SKU-CB-OVER",
            dim_length_in=31, dim_width_in=24, dim_height_in=20,
            weight_lb=10, declared_value_cents=10000, white_glove_eligible=False,
        )
        big = create_item(
            supplier["id"], sku="SKU-CB-125",
            dim_length_in=100, dim_width_in=40, dim_height_in=40,
            weight_lb=60, declared_value_cents=50000, white_glove_eligible=False,
        )
        assert bound["cube_score"] == pytest.approx(40.00, abs=0.001)
        assert bound["freight_class"] == "PARCEL_ELIGIBLE"
        assert over["cube_score"] == pytest.approx(40.08, abs=0.001)
        assert over["freight_class"] == "LTL_250"
        assert big["cube_score"] == pytest.approx(106.29, abs=0.001)
        assert big["freight_class"] == "LTL_125"

    def test_cube_score_weights_and_rounding(self, api):
        """PRD §3.1: "0.45 times the longest of the three packaged dimensions,
        plus 0.30 times the cube root of the product of the three dimensions,
        plus 0.25 times the sum of the three dimensions — with the result
        rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/cube_score_weighted_threshold_classification
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(
            supplier["id"], sku="SKU-CB-W",
            dim_length_in=40, dim_width_in=40, dim_height_in=20,
            weight_lb=30, declared_value_cents=80000, white_glove_eligible=True,
        )
        # 0.45*40 + 0.30*cbrt(32000) + 0.25*100 = 18 + 9.5096... + 25 = 52.52
        assert item["cube_score"] == pytest.approx(52.52, abs=0.001)
        assert item["freight_class"] == "LTL_250"


class TestFreightClassBoundaryScoreExactly40:
    def test_score_exactly_40_is_parcel_eligible(self, api):
        """PRD §3.1: "a score of at most 40.00 yields `PARCEL_ELIGIBLE`"
        PRD §3.1: "A score of exactly 40.00 is therefore `PARCEL_ELIGIBLE`."

        Design: Difficulty/boundary_precision_check/freight_class_boundary_score_exactly_40
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(
            supplier["id"], sku="SKU-B40",
            dim_length_in=30.9, dim_width_in=24, dim_height_in=20,
            weight_lb=10, declared_value_cents=10000, white_glove_eligible=False,
        )
        assert item["cube_score"] == pytest.approx(40.00, abs=0.001)
        assert item["freight_class"] == "PARCEL_ELIGIBLE"

    def test_score_just_above_40_flips_to_ltl_250(self, api):
        """PRD §3.1: "a score of at most 40.00 yields `PARCEL_ELIGIBLE`; above
        40.00 and at most 70.00 yields `LTL_250`".

        Design: Difficulty/boundary_precision_check/freight_class_boundary_score_exactly_40
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(
            supplier["id"], sku="SKU-B40P",
            dim_length_in=31, dim_width_in=24, dim_height_in=20,
            weight_lb=10, declared_value_cents=10000, white_glove_eligible=False,
        )
        assert item["cube_score"] == pytest.approx(40.08, abs=0.001)
        assert item["freight_class"] == "LTL_250"


class TestDeclaredGirthPerLineThenSumRounding:
    def test_fractional_dimensions_ceil_per_line(self, api):
        """PRD §3.1: "Third, the parcel gate: the `declared_girth_in` is
        computed by rounding each dimension up to a whole inch individually
        first and only then combining them — the ceiled length plus twice the
        sum of the ceiled width and the ceiled height."

        Design: Difficulty/combinatorial_formula/declared_girth_per_line_then_sum_rounding
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(
            supplier["id"], sku="SKU-FRAC-1",
            dim_length_in=20.2, dim_width_in=30.4, dim_height_in=10.1,
            weight_lb=12, declared_value_cents=9000, white_glove_eligible=False,
        )
        # ceil(20.2) + 2*(ceil(30.4) + ceil(10.1)) = 21 + 2*(31 + 11) = 105
        assert item["declared_girth_in"] == 105

    def test_parcel_gate_on_per_line_girth(self, api):
        """PRD §3.1: "The item's `parcel_ok` flag is true when the resulting
        `declared_girth_in` is at most 165 inches."

        Design: Difficulty/combinatorial_formula/declared_girth_per_line_then_sum_rounding
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(
            supplier["id"], sku="SKU-FRAC-2",
            dim_length_in=20.2, dim_width_in=30.4, dim_height_in=10.1,
            weight_lb=12, declared_value_cents=9000, white_glove_eligible=False,
        )
        assert item["declared_girth_in"] == 105
        assert item["parcel_ok"] is True


class TestItemCreateReturnsComputedFields:
    def test_item_create_returns_computed_fields_and_ignores_client_state(self, api):
        """PRD §3.1: "At the moment of listing, three computations run and are
        stored on the item."
        PRD §3.1: "A newly listed item starts in `LISTED` status."
        PRD §2.4: "All resources in the system — Suppliers, Items, Hubs,
        Customers, Orders, FreightLanes, Shipments, Linehauls,
        DeliveryAppointments, DamageClaims, Chargebacks, and
        ReturnAuthorizations — carry a standard set of system-managed
        fields:"

        Design: Corner/entities/item_create_returns_computed_fields_and_ignores_client_state
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        resp = api.create_item(
            {
                "supplier_id": supplier["id"], "sku": "SKU-LG-1",
                "dim_length_in": 40, "dim_width_in": 40, "dim_height_in": 20,
                "weight_lb": 30, "declared_value_cents": 80000,
                "white_glove_eligible": True,
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert resp.json()["response_type"] == "object"
        assert_item(data)
        assert data["cube_score"] == pytest.approx(52.52, abs=0.001)
        assert data["freight_class"] == "LTL_250"
        # ceil(40) + 2*(ceil(40) + ceil(20)) = 40 + 2*60 = 160 (positional
        # per PRD §3.1: ceiled length + twice the ceiled width + ceiled height)
        assert data["declared_girth_in"] == 160
        assert data["parcel_ok"] is True
        assert data["status"] == "LISTED"
        assert data["version"] == 1


class TestItemCreateIgnoresSmuggledComputedFields:
    def test_smuggled_cube_score_and_version_are_ignored(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, and which serves
        as the basis for optimistic concurrency control where a rule requires
        it."
        PRD §3.1: "At the moment of listing, three computations run and are
        stored on the item."

        Design: Corner/entities/item_create_with_extra_computed_field_input_ignored
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        resp = api.create_item(
            {
                "supplier_id": supplier["id"], "sku": "SKU-SMUG",
                "dim_length_in": 40, "dim_width_in": 40, "dim_height_in": 20,
                "weight_lb": 30, "declared_value_cents": 80000,
                "white_glove_eligible": True,
                "cube_score": 999.99, "version": 77,
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["cube_score"] == pytest.approx(52.52, abs=0.001), (
            "client-supplied cube_score must be ignored in favor of the computed value"
        )
        assert data["version"] == 1, "client-supplied version must be ignored"


class TestItemGetNotFound:
    def test_item_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.7: "third, whether every path and body identifier resolves
        to an existing resource, validated left-to-right with path segments
        first and body fields in their declared input order
        (`ERR_NOT_FOUND`)"

        Design: Corner/entities/item_get_with_unknown_id_returns_not_found
        """
        set_clock(SETUP_CLOCK)
        resp = api.get_item(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSupplierCreateDefaults:
    def test_supplier_create_omitting_lead_time_defaults_to_3(self, api):
        """PRD §3.1: "an optional `lead_time_days` representing promised
        drop-ship handling days, which defaults to 3 when omitted."
        PRD §3.1: "A newly registered supplier starts with its `status` field
        at `ACTIVE`, a `compliance_score` of 100.00, an `on_time_ship_rate` of
        100.00, and a `chargeback_rate` of 0.00"

        Design: Corner/entities/supplier_create_omitting_lead_time_defaults_to_3
        """
        set_clock(SETUP_CLOCK)
        resp = api.create_supplier(
            {"supplier_code": "SUP-DFT", "legal_name": "Defaults Inc",
             "drop_ship_enabled": True},
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["lead_time_days"] == 3
        assert data["compliance_score"] == pytest.approx(100.00, abs=0.001)
        assert data["on_time_ship_rate"] == pytest.approx(100.00, abs=0.001)
        assert data["chargeback_rate"] == pytest.approx(0.00, abs=0.001)
        assert data["status"] == "ACTIVE"


class TestItemsListPagination:
    def test_items_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; if not provided, it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."

        Design: Corner/entities/items_list_paginates_with_total_count_and_has_more
        """
        from test_helpers import validate_paginated

        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        create_item(supplier["id"], sku="SKU-P1")  # 40x40x20 -> LTL_250
        create_item(
            supplier["id"], sku="SKU-P2",
            dim_length_in=20, dim_width_in=16, dim_height_in=12,
            weight_lb=12, declared_value_cents=9000, white_glove_eligible=False,
        )
        create_item(
            supplier["id"], sku="SKU-P3",
            dim_length_in=100, dim_width_in=40, dim_height_in=40,
            weight_lb=60, declared_value_cents=50000, white_glove_eligible=False,
        )

        page1 = api.list_items(ADMIN, params={"supplier_id": supplier["id"], "limit": 2, "offset": 0})
        rows, meta = validate_paginated(page1)
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        page2 = api.list_items(ADMIN, params={"supplier_id": supplier["id"], "limit": 2, "offset": 2})
        rows2, meta2 = validate_paginated(page2)
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered = api.list_items(ADMIN, params={"freight_class": "LTL_250"})
        rows3, meta3 = validate_paginated(filtered)
        assert len(rows3) == 1
        assert meta3["total_count"] == 1

        default_page = api.list_items(ADMIN)
        rows4, meta4 = validate_paginated(default_page)
        assert len(rows4) == 3
        assert meta4["limit"] == 10
        assert meta4["offset"] == 0
