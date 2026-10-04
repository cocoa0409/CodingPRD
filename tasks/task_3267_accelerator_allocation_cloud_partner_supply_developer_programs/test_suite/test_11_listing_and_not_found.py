"""Corner coverage: listing, pagination and not-found semantics on read surfaces."""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_partner_ops_headers,
    startup_clock, create_certified_blueprint, create_validated_partner,
    create_product, create_supply_node, create_allocation_hold,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]


class TestAllocationHoldListing:
    """List responses carry limit, offset, total_count and has_more."""

    def _three_requested_holds(self):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        for qty in (100, 150, 200):
            create_allocation_hold(product["id"], node["id"], qty, partner["id"])
        return partner, product, node

    def test_first_page_reports_total_count_and_has_more(self):
        """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/allocation_holds_list_paginates_with_total_count_and_has_more
        """
        partner, product, node = self._three_requested_holds()
        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]),
            params={"partner_id": partner["id"], "limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3, (
            f"total_count counts the filtered set, got {meta['total_count']}"
        )
        assert meta["has_more"] is True

    def test_second_page_reports_has_more_false(self):
        """PRD §2.3: "Every list endpoint returns its items sorted by creation timestamp
        in ascending order unless the endpoint's own description states otherwise."

        Design: Corner/entities/allocation_holds_list_paginates_with_total_count_and_has_more
        """
        partner, product, node = self._three_requested_holds()
        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]),
            params={"partner_id": partner["id"], "limit": 2, "offset": 2}))
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_defaults_apply_when_no_paging_parameters_are_supplied(self):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned,
        defaults to 10 ... The `offset` parameter sets the number of leading items to
        skip and defaults to 0."

        Design: Corner/entities/allocation_holds_list_paginates_with_total_count_and_has_more
        """
        partner, product, node = self._three_requested_holds()
        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]), params={"partner_id": partner["id"]}))
        assert meta["limit"] == 10, f"default limit is 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset is 0, got {meta['offset']}"


class TestUnknownPartnerRead:
    """A read against a well-formed but unknown partner id reports the partner error."""

    def test_unknown_partner_reports_partner_not_found(self):
        """PRD §2.10: "Paths under the partner collection report `ERR_PARTNER_NOT_FOUND`
        with HTTP 404 when the named partner does not exist".

        Design: Corner/entities/unknown_partner_get_returns_partner_not_found
        """
        startup_clock()
        response = api.get_partner(NON_EXISTENT_UUID, make_partner_ops_headers(NON_EXISTENT_UUID))
        validate_error(response, ApiErrorId.ERR_PARTNER_NOT_FOUND, 404)


class TestSupplyNodeFilteredList:
    """The SKU-filtered pool list returns only the pools bound to that SKU."""

    def test_filter_returns_only_the_matching_sku_pools(self):
        """PRD §3.3: "A `SupplyNode` is a supplier pool that serves exactly one SKU."
        PRD §2.3: "Every list endpoint returns its items sorted by creation timestamp in
        ascending order unless the endpoint's own description states otherwise."

        Design: Corner/entities/supply_node_filtered_list_returns_only_matching_sku_pools
        """
        startup_clock()
        product_a = create_product(sku_code="AC-100-PCIE")
        product_b = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                                   tdp_watts=900, supply_ceiling_units=4000,
                                   long_term_availability_through="2032-01-01T00:00:00Z")
        create_supply_node(product_a["id"], node_code="POOL-A1")
        create_supply_node(product_a["id"], node_code="POOL-A2", node_region="EMEA",
                           capacity_units=500)
        create_supply_node(product_b["id"], node_code="POOL-B1", node_region="APAC",
                           capacity_units=300)

        data, meta = validate_paginated(api.list_supply_nodes(
            PLANNER, params={"product_sku_id": product_a["id"]}))
        assert len(data) == 2, f"two pools serve SKU A, got {len(data)}"
        assert all(row["product_sku_id"] == product_a["id"] for row in data), (
            "no returned pool belongs to the sibling SKU"
        )
        assert meta["total_count"] == 2