"""Endpoint corners: catalog-search filtering and the cutoff action's response type."""

from test_helpers import (
    ADMIN,
    CURATOR,
    DCM,
    create_attribute_payload,
    create_distribution_center_payload,
    create_item_payload,
    setup_account,
    setup_clock,
    setup_order_scenario,
    validate_paginated,
    validate_success,
)


def _create_item(api, sku, price, material_spec, long_tail=False):
    item = validate_success(api.create_item(
        create_item_payload(
            sku=sku, description=f"Search item {material_spec}", material_spec=material_spec,
            long_tail=long_tail, unit_price_cents=price, unit_weight_kg=0.10,
            curation_bundle_size=4,
            curated_dimension_json={"nominal_length_mm": 10, "nominal_width_mm": 10,
                                    "nominal_height_mm": 10, "drawing_revision": 1}),
        CURATOR), 201)
    # PRD 3.1: every item submitted to a curation batch must already carry at least
    # one standardized attribute row, or the whole submission is blocked with
    # ERR_CURATION_ATTRIBUTES_MISSING.
    validate_success(api.create_item_attribute(
        item["id"], create_attribute_payload(
            attribute_name="Grade", attribute_value="8.8", unit_of_measure="n/a"),
        CURATOR), 201)
    return item


class TestCatalogSearchFiltersAllDeclaredQueryParameters:
    """Each declared search filter narrows the same collection independently."""

    def _catalog(self, api):
        setup_clock(api)
        dc = validate_success(api.create_distribution_center(
            create_distribution_center_payload(), ADMIN), 201)
        acct = setup_account(api)
        brass = _create_item(api, "SE-1001", 1000, "brass")
        steel = _create_item(api, "SE-1002", 1100, "steel")
        bronze = _create_item(api, "SE-1003", 1200, "bronze", long_tail=True)
        validate_success(api.create_item_attribute(
            bronze["id"], create_attribute_payload(
                attribute_name="Alloy", attribute_value="C93200", unit_of_measure="n/a"),
            CURATOR), 201)
        validate_success(api.create_curation_review(
            {"item_ids": [brass["id"], steel["id"]]}, CURATOR), 201)
        validate_success(api.create_stock(
            {"item_id": brass["id"], "dc_id": dc["id"], "account_id": acct["id"],
             "on_hand_units": 4, "daily_demand_units": 1, "inbound_daily_units": 1}, DCM),
            201)
        return {"dc": dc, "brass": brass, "steel": steel, "bronze": bronze}

    def test_the_material_spec_and_long_tail_filters_each_select_one_row(self, api):
        """PRD §3.11: "Searching the catalog accepts a free-text `q` term and narrower
        filters — `material_spec` for the material, `region` for the delivery region,
        `long_tail` for whether the item is long-tail sourced".

        Design: Corner/endpoints/catalog_search_filters_all_declared_query_parameters
        """
        context = self._catalog(api)

        by_material, _meta = validate_paginated(api.list_items(
            CURATOR, {"material_spec": "brass", "limit": 100, "offset": 0}))
        assert len(by_material) == 1
        assert by_material[0]["id"] == context["brass"]["id"]

        by_long_tail, _meta = validate_paginated(api.list_items(
            CURATOR, {"long_tail": True, "limit": 100, "offset": 0}))
        assert len(by_long_tail) == 1
        assert by_long_tail[0]["id"] == context["bronze"]["id"]

    def test_the_free_text_and_centre_filters_narrow_to_the_matching_row(self, api):
        """PRD §3.11: "Searching the catalog accepts a free-text `q` term and narrower
        filters — ... `dc_id` to scope to one center and `supplier_id` to scope to one
        supplier — and every result carries its live availability at the relevant center
        together with its `unit_price_cents`."

        Design: Corner/endpoints/catalog_search_filters_all_declared_query_parameters
        """
        context = self._catalog(api)

        by_text, _meta = validate_paginated(api.list_items(
            CURATOR, {"q": "bronze", "limit": 100, "offset": 0}))
        assert len(by_text) == 1
        assert by_text[0]["id"] == context["bronze"]["id"]

        by_center, _meta = validate_paginated(api.list_items(
            CURATOR, {"dc_id": context["dc"]["id"], "limit": 100, "offset": 0}))
        assert len(by_center) == 1
        assert by_center[0]["id"] == context["brass"]["id"]


class TestConfirmCutoffResponseIsTheShipmentNotTheOrder:
    """Certifying the cutoff returns the Shipment, and only from a picked order."""

    def test_certifying_a_picked_order_returns_the_shipment(self, api):
        """PRD §3.7: "A successful certification moves the shipment to
        `CUTOFF_CONFIRMED`, stamps the shipment's `cutoff_sequence_index` with the center's
        current `cutoff_sequence_index`, moves the order's `fulfillment_status` from
        `PICKED` to `SHIPPED` while `order_status` stays `RELEASED`, and increments the
        order's `version` by 1."
        PRD §4: "an operation that modifies an existing resource or performs a state
        transition responds with 200 and returns the modified resource".

        Design: Corner/endpoints/confirm_cutoff_response_is_the_shipment_not_the_order
        """
        scenario = setup_order_scenario(
            api,
            lines_spec=[{"price": 2000, "qty": 2, "bundle": 4, "on_hand": 6, "sku": "CA-1001"}],
            target="PICKED",
            utc="2026-09-14T10:05:00Z",
        )
        current = validate_success(api.get_order(scenario["order"]["id"],
                                                 scenario["acct_headers"]))

        response = validate_success(api.confirm_cutoff(
            scenario["order"]["id"],
            {"expected_order_version": current["version"], "service_level": "TWO_DAY"}, DCM))

        assert response["shipment_status"] == "CUTOFF_CONFIRMED"
        assert response["service_level"] == "TWO_DAY"
        assert response["dc_id"] == scenario["dc"]["id"]
        assert "freight_charge_cents" in response, "the response body is the Shipment"

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "SHIPPED"

        shipments, _meta = validate_paginated(api.list_shipments(
            DCM, {"order_id": scenario["order"]["id"], "limit": 10, "offset": 0}))
        assert len(shipments) == 1
        assert shipments[0]["id"] == response["id"]