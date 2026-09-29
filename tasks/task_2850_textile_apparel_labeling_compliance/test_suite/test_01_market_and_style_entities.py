"""Market regime registry, brand registry, style entity and supply-graph node
entity behaviour: creation echoes, computed defaults, list envelope counters and
the per-kind rejections that guard the entity surface.
"""
import pytest

from test_helpers import *  # noqa: F401,F403


# A syntactically valid UUID that matches no persisted row.
_UNKNOWN_UUID = "2f1a9b7c-0000-4000-8000-000000000000"

_BRAND_NAME = "Northline Apparel Co"


def _brand_and_market():
    """One registered US regime plus one SELF_OF_RECORD brand owner."""
    market = register_market("US", required_languages=["en"], fiber_tolerance_pp=3.0,
                             absolute_claim_tolerance_pp=0.0,
                             min_durability_cycles=20, marking_duty_rate=0.100,
                             requires_identity_disclosure=True,
                             requires_origin_statement=True)
    brand = register_brand(legal_name=_BRAND_NAME, party_type="BRAND_OWNER",
                           rn_number="RN12345",
                           responsibility_mode="SELF_OF_RECORD")
    return market, brand


def _style_with_three_node_graph():
    """A style carrying a FIBER root, a YARN child of it and a FABRIC
    grandchild, so the graph spans depths 0, 1 and 2."""
    _market, brand = _brand_and_market()
    style = create_style(brand["id"], style_code="NL-4410", net_weight_grams=320.0,
                         declared_fibers=[fiber_line("COTTON", 100.0)])
    nodes = build_supply_graph(style["id"], [
        {"stage": "FIBER", "country_code": "IN", "value_added_usd": 2.00,
         "weight_grams": 500.0, "is_ornamentation": False},
        {"stage": "YARN", "country_code": "IN", "value_added_usd": 3.00,
         "weight_grams": 480.0, "is_ornamentation": False, "_parent": 0},
        {"stage": "FABRIC", "country_code": "CN", "value_added_usd": 6.00,
         "weight_grams": 950.0, "is_ornamentation": False, "_parent": 1},
    ])
    return style, nodes


def test_market_requirement_create_echoes_all_eight_declared_inputs(
        api, compliance_admin_headers):
    """PRD 4: "Endpoints that bring a new resource into existence answer with HTTP 201 and return the created resource in `data`."

    PRD 2.4: "Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp."

    PRD 2.10: "`fiber_tolerance_pp` is the allowed absolute deviation, in percentage points, between a declared fiber percentage and the laboratory-measured percentage; it ranges from 0.0 to 5.0 inclusive at one decimal place."

    Design: Corner/entities/market_requirement_create_returns_every_declared_field
    """
    payload = market_requirement_payload(
        market_code="CA",
        required_languages=["en", "fr"],
        fiber_tolerance_pp=3.0,
        absolute_claim_tolerance_pp=0.3,
        min_durability_cycles=25,
        marking_duty_rate=0.100,
        requires_identity_disclosure=True,
        requires_origin_statement=True,
    )
    resp = api.create_market_requirement(payload, compliance_admin_headers)
    data = validate_success(resp, 201)

    body = resp.json()
    assert body["response_type"] == "object", (
        "a single created regime must answer response_type 'object', got "
        f"{body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert_millisecond_instant(body["meta"]["api_request_timestamp"],
                              "meta.api_request_timestamp")

    assert_market_requirement(data)
    assert is_valid_uuid(data["id"]), (
        f"the regime id must be a server-minted UUID with no type prefix, got {data['id']!r}"
    )
    assert_millisecond_instant(data["created_at"], "created_at")

    assert data["market_code"] == "CA", "market_code must be echoed verbatim"
    assert sorted(data["required_languages"]) == ["en", "fr"], (
        f"required_languages must hold exactly the two submitted codes, got "
        f"{data['required_languages']!r}"
    )
    assert data["fiber_tolerance_pp"] == pytest.approx(3.0, abs=0.01), (
        f"fiber_tolerance_pp must be echoed as 3.0, got {data['fiber_tolerance_pp']!r}"
    )
    assert data["absolute_claim_tolerance_pp"] == pytest.approx(0.3, abs=0.01), (
        "absolute_claim_tolerance_pp must be echoed as 0.3, got "
        f"{data['absolute_claim_tolerance_pp']!r}"
    )
    assert data["min_durability_cycles"] == 25, (
        f"min_durability_cycles must be echoed as 25, got {data['min_durability_cycles']!r}"
    )
    assert data["marking_duty_rate"] == pytest.approx(0.100, abs=0.0005), (
        f"marking_duty_rate must be echoed as 0.100, got {data['marking_duty_rate']!r}"
    )
    assert data["requires_identity_disclosure"] is True, (
        "requires_identity_disclosure must be echoed as true"
    )
    assert data["requires_origin_statement"] is True, (
        "requires_origin_statement must be echoed as true"
    )


def test_brand_read_back_carries_its_computed_defaults(api, compliance_admin_headers):
    """PRD 3.1: "From those two inputs the service computes `responsible_brand_id`, the **brand of record**: it equals `licensor_brand_id` when `responsibility_mode` is `LICENSOR_OF_RECORD`, and it equals the row's own `id` when the mode is `SELF_OF_RECORD`."

    PRD 3.1: "`outstanding_penalty_usd` is the party's marking-penalty ledger of record, carried at 2 decimal places and never negative, and it starts at 0.00 because a freshly registered party owns no shipments."

    PRD 3.1: "And `posture` is the gate that both of the others feed, taking the value `OPEN`, `RESTRICTED` or `SUSPENDED` and starting at `OPEN`."

    Design: Corner/entities/brand_get_by_id_returns_the_stored_row
    """
    created = validate_success(api.create_brand(brand_payload(
        legal_name=_BRAND_NAME, party_type="BRAND_OWNER", rn_number="RN12345",
        licensor_brand_id=None, responsibility_mode="SELF_OF_RECORD",
    ), compliance_admin_headers), 201)

    data = validate_success(api.get_brand(created["id"], compliance_admin_headers), 200)
    assert_brand(data)

    assert data["id"] == created["id"], "the read must return the registered row"
    assert data["responsible_brand_id"] == created["id"], (
        "SELF_OF_RECORD resolves the responsibility chain to the row itself, expected "
        f"{created['id']!r}, got {data['responsible_brand_id']!r}"
    )
    assert data["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
        "a freshly registered party owns no shipments so its ledger reads 0.00, got "
        f"{data['outstanding_penalty_usd']!r}"
    )
    assert data["critical_audit_finding_count"] == 0, (
        "critical_audit_finding_count starts at 0, got "
        f"{data['critical_audit_finding_count']!r}"
    )
    assert data["posture"] == "OPEN", (
        f"posture starts at OPEN, got {data['posture']!r}"
    )
    assert data["version"] == 1, (
        f"version starts at 1 on creation, got {data['version']!r}"
    )
    assert data["licensor_brand_id"] is None, (
        "licensor_brand_id must be null for a party that is not a licensee, got "
        f"{data['licensor_brand_id']!r}"
    )
    assert data["legal_name"] == _BRAND_NAME
    assert data["rn_number"] == "RN12345"


def test_material_input_list_counters_describe_the_whole_filtered_set(
        api, compliance_admin_headers):
    """PRD 2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."

    PRD 3.3: "Filtering by `style_id` returns every node of a style; filtering by `parent_input_id` returns the direct children of one node through the self-referential reverse lookup; `stage` and `country_code` filters are also available."

    Design: Corner/entities/material_inputs_listing_paginates_with_total_count_and_has_more
    """
    style, _nodes = _style_with_three_node_graph()

    first_resp = api.list_material_inputs(
        compliance_admin_headers,
        params={"style_id": style["id"], "limit": 2, "offset": 0})
    first, first_meta = validate_paginated(first_resp)
    assert first_resp.json()["response_type"] == "array", (
        "a list endpoint must answer response_type 'array'"
    )
    assert len(first) == 2, (
        f"limit 2 must return exactly 2 of the 3 nodes, got {len(first)}"
    )
    assert first_meta["total_count"] == 3, (
        "total_count counts the rows matching the style_id filter before the page "
        f"window, expected 3, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "one row remains beyond the first window, so has_more must be true"
    )
    assert first_meta["limit"] == 2, f"meta.limit must echo 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"meta.offset must echo 0, got {first_meta['offset']}"

    second, second_meta = validate_paginated(api.list_material_inputs(
        compliance_admin_headers,
        params={"style_id": style["id"], "limit": 2, "offset": 2}))
    assert len(second) == 1, (
        f"offset 2 must return the single remaining node, got {len(second)}"
    )
    assert second_meta["total_count"] == 3, (
        "total_count is invariant under the page window, expected 3, got "
        f"{second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "no row remains beyond the second window, so has_more must be false"
    )
    assert second_meta["offset"] == 2, (
        f"meta.offset must echo 2, got {second_meta['offset']}"
    )

    paged_ids = [row["id"] for row in first] + [row["id"] for row in second]
    assert len(set(paged_ids)) == 3, (
        f"the two windows must together cover all three distinct nodes, got {paged_ids}"
    )


def test_material_input_depth_counts_the_hops_from_the_graph_root(
        api, compliance_admin_headers):
    """PRD 3.3: "On success the node's `depth` is computed as 0 for a root and as its parent's depth plus 1 otherwise."

    PRD 2.3: "Two list endpoints override that default: the market-requirement list is ordered by `market_code` ascending, and the supply-graph node list is ordered by `depth` ascending and then by `created_at` ascending within a depth."

    Design: Corner/entities/material_inputs_listing_paginates_with_total_count_and_has_more
    """
    style, _nodes = _style_with_three_node_graph()

    rows, meta = validate_paginated(api.list_material_inputs(
        compliance_admin_headers, params={"style_id": style["id"], "limit": 100}))
    assert meta["total_count"] == 3, (
        f"the style carries exactly three nodes, got total_count {meta['total_count']}"
    )
    for row in rows:
        assert_material_input(row)

    by_stage = {row["stage"]: row for row in rows}
    assert by_stage["FIBER"]["depth"] == 0, (
        f"the FIBER root has depth 0, got {by_stage['FIBER']['depth']}"
    )
    assert by_stage["YARN"]["depth"] == 1, (
        f"the YARN child of the root has depth 1, got {by_stage['YARN']['depth']}"
    )
    assert by_stage["FABRIC"]["depth"] == 2, (
        f"the FABRIC child of the YARN node has depth 2, got {by_stage['FABRIC']['depth']}"
    )
    assert [row["depth"] for row in rows] == [0, 1, 2], (
        "the supply-graph node list is ordered by depth ascending, got "
        f"{[row['depth'] for row in rows]}"
    )


def test_style_read_with_unknown_id_answers_style_not_found(
        api, compliance_admin_headers):
    """PRD 2.6: "Identifiers embedded in a URL path are resolved strictly left to right, and the first one that does not resolve to a live row decides the 404."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/style_get_with_unknown_id_not_found
    """
    resp = api.get_style(_UNKNOWN_UUID, compliance_admin_headers)
    error = validate_error(resp, ApiErrorId.ERR_STYLE_NOT_FOUND, 404)

    assert resp.json()["response_type"] == "error", (
        "an unresolved path identifier must answer the error envelope, not an empty "
        "200 object"
    )
    assert error["message"].strip(), "the error envelope must carry a non-blank message"


def test_style_create_without_product_class_is_a_shape_violation(
        api, compliance_admin_headers):
    """PRD 3.2: "It names its owning party through a `brand_id` in the creation payload, carries a brand-facing `style_code` of 1 to 32 characters that must be unique within that party — a repeat is rejected with `ERR_DUPLICATE_STYLE_CODE` — and declares a `product_class` from `WOVEN_OUTERWEAR`, `KNIT_TOP`, `HOSIERY` and `HOME_TEXTILE`."

    PRD 2.7: "This covers a missing required field, an enum value that is not a declared member, a number outside its declared range, an array that is required to be non-empty but is empty, a `limit` outside 1 through 100 or a negative `offset`, a `method` that does not match the `test_type` it is reserved for, a `wash_temp_c` present on a fiber-content reservation or absent on a care-performance one, and a `results_due_at` that is not strictly after `specimen_received_at`."

    Design: Corner/entities/style_create_missing_product_class_returns_invalid_request
    """
    _market, brand = _brand_and_market()
    payload = style_payload(brand["id"], style_code="NL-4410",
                            target_market_codes=["US"], net_weight_grams=320.0,
                            declared_fibers=[fiber_line("COTTON", 100.0)])
    del payload["product_class"]

    validate_error(api.create_style(payload, make_brand_admin_headers(brand["id"])),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_brand_styles(brand["id"], compliance_admin_headers))
    assert meta["total_count"] == 0, (
        "a create rejected for shape must persist no Style row, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"no style may be listed for the brand, got {rows!r}"


def test_style_create_with_unknown_product_class_is_a_shape_violation(
        api, compliance_admin_headers):
    """PRD 3.2: "It names its owning party through a `brand_id` in the creation payload, carries a brand-facing `style_code` of 1 to 32 characters that must be unique within that party — a repeat is rejected with `ERR_DUPLICATE_STYLE_CODE` — and declares a `product_class` from `WOVEN_OUTERWEAR`, `KNIT_TOP`, `HOSIERY` and `HOME_TEXTILE`."

    PRD 2.7: "This covers a missing required field, an enum value that is not a declared member, a number outside its declared range, an array that is required to be non-empty but is empty, a `limit` outside 1 through 100 or a negative `offset`, a `method` that does not match the `test_type` it is reserved for, a `wash_temp_c` present on a fiber-content reservation or absent on a care-performance one, and a `results_due_at` that is not strictly after `specimen_received_at`."

    Design: Corner/entities/style_create_with_unknown_product_class_returns_invalid_enum
    """
    _market, brand = _brand_and_market()
    payload = style_payload(brand["id"], style_code="NL-4410",
                            product_class="SWIMWEAR",
                            target_market_codes=["US"], net_weight_grams=320.0,
                            declared_fibers=[fiber_line("COTTON", 100.0)])

    validate_error(api.create_style(payload, make_brand_admin_headers(brand["id"])),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_brand_styles(brand["id"], compliance_admin_headers))
    assert meta["total_count"] == 0, (
        "a product_class outside the four declared members persists no Style row, got "
        f"total_count {meta['total_count']}"
    )


def test_style_create_without_declared_fibers_stands_undeclared(
        api, compliance_admin_headers):
    """PRD 3.2: "The array may be omitted or supplied empty at style creation, in which case it defaults to an empty array and the style simply stands undeclared; but whenever it is non-empty, the declared percentages must sum to exactly 100.0 after each line is rounded to one decimal place."

    PRD 3.2: "The other computed field on a style is `effective_fiber_content_text`, the canonical printable fiber string, which defaults to the empty string and is recomputed at style creation and on every replacement of the declaration."

    PRD 3.2: "It defaults to `BLOCKED` on a new style and is recomputed by every operation that touches either dimension."

    Design: Corner/entities/style_create_without_declared_fibers_defaults_to_an_empty_declaration
    """
    _market, brand = _brand_and_market()
    payload = style_payload(brand["id"], style_code="NL-BARE-1",
                            product_class="WOVEN_OUTERWEAR",
                            target_market_codes=["US"], net_weight_grams=300.0)
    del payload["declared_fibers"]

    data = validate_success(
        api.create_style(payload, make_brand_admin_headers(brand["id"])), 201)
    assert_style(data)

    assert data["declared_fibers"] == [], (
        f"an omitted declaration defaults to the empty array, got {data['declared_fibers']!r}"
    )
    assert data["effective_fiber_content_text"] == "", (
        "an empty declaration renders the empty string, got "
        f"{data['effective_fiber_content_text']!r}"
    )
    assert data["substantiation_state"] == "FIBER_DECLARED", (
        "the fiber dimension starts at FIBER_DECLARED, got "
        f"{data['substantiation_state']!r}"
    )
    assert data["origin_state"] == "ORIGIN_UNDETERMINED", (
        f"the origin dimension starts at ORIGIN_UNDETERMINED, got {data['origin_state']!r}"
    )
    assert data["label_readiness"] == "BLOCKED", (
        f"label_readiness defaults to BLOCKED on a new style, got {data['label_readiness']!r}"
    )


def test_style_fiber_text_buckets_the_sub_five_percent_line_as_other_fiber(
        api, compliance_admin_headers):
    """PRD 3.2: "Otherwise the lines are split into two groups: a line belongs to the **listed** group when its `ornamentation_exempt` flag is false and its `declared_pct` is at least 5.0 percent; every other line — one that is ornamentation-exempt, or one below 5.0 percent — belongs to the **bucketed** group."

    PRD 3.2: "The listed lines are sorted by `declared_pct` descending, and lines with equal percentages are then ordered by `fiber_generic_name` ascending; insertion order and row identifiers never participate."

    PRD 3.2: "If the bucketed group is non-empty, one final segment is appended: the sum of the bucketed lines' declared percentages, rounded half-up to one decimal place, rendered at one decimal place, followed by a percent sign, a space, and the words `OTHER FIBER`."

    Design: Corner/entities/style_effective_fiber_content_text_buckets_sub_five_percent_lines_into_other_fiber
    """
    _market, brand = _brand_and_market()
    payload = style_payload(
        brand["id"], style_code="NL-4410", product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"], net_weight_grams=320.0,
        declared_fibers=[
            fiber_line("ELASTANE", 3.0),
            fiber_line("COTTON", 60.0),
            fiber_line("POLYESTER", 37.0),
        ])

    data = validate_success(
        api.create_style(payload, make_brand_admin_headers(brand["id"])), 201)
    assert_style(data)

    assert data["effective_fiber_content_text"] == (
        "60.0% COTTON, 37.0% POLYESTER, 3.0% OTHER FIBER"), (
        "the 3.0 ELASTANE line sits below the 5.0 listing threshold so it must render "
        "as the trailing OTHER FIBER bucket behind the two listed lines ordered by "
        f"declared_pct descending, got {data['effective_fiber_content_text']!r}"
    )
    assert {line["fiber_generic_name"]: line["declared_pct"]
            for line in data["declared_fibers"]} == pytest.approx(
        {"ELASTANE": 3.0, "COTTON": 60.0, "POLYESTER": 37.0}, abs=0.01), (
        "the stored declaration must still hold the three submitted lines - only the "
        f"rendered string is reordered, got {data['declared_fibers']!r}"
    )


def test_market_regime_row_exposes_no_updated_at_and_no_version(
        api, compliance_admin_headers):
    """PRD 2.4: "The one exception is the market-requirement resource: a market regime is immutable once registered, so those rows carry only `id` and `created_at`, and neither `updated_at` nor `version` is ever emitted for them."

    PRD 2.4: "There is no update endpoint for a market regime."

    PRD 2.10: "The registry list is readable by all seven roles and accepts an optional `market_code` filter alongside the usual page window; registration is a `ComplianceAdmin` privilege."

    Design: Corner/entities/market_requirement_row_carries_no_version_and_has_no_update_endpoint
    """
    created = register_market("US")

    rows, meta = validate_paginated(api.list_market_requirements(
        compliance_admin_headers, params={"market_code": "US"}))
    assert meta["total_count"] == 1, (
        f"exactly one regime is registered for US, got total_count {meta['total_count']}"
    )
    assert len(rows) == 1, f"the filtered page must hold one row, got {len(rows)}"
    assert rows[0]["id"] == created["id"], (
        f"the listed row must be the registered one, got {rows[0]['id']!r}"
    )

    for row in (created, rows[0]):
        assert_market_requirement(row)
        assert "id" in row and "created_at" in row, (
            "a market regime row carries id and created_at"
        )
        assert "updated_at" not in row, (
            f"a market regime never emits updated_at, got {row!r}"
        )
        assert "version" not in row, (
            f"a market regime never emits version, got {row!r}"
        )


def test_material_input_append_under_unknown_style_answers_style_not_found(
        api, compliance_admin_headers):
    """PRD 2.7: "Existence of every path identifier, left to right — the per-kind 404 codes, on every endpoint with a path parameter."

    PRD 2.6: "The per-kind codes are `ERR_BRAND_NOT_FOUND`, `ERR_STYLE_NOT_FOUND`, `ERR_MATERIAL_INPUT_NOT_FOUND`, `ERR_LAB_TEST_NOT_FOUND`, `ERR_ORIGIN_DETERMINATION_NOT_FOUND`, `ERR_LABEL_SPEC_NOT_FOUND`, `ERR_IMPORT_SHIPMENT_NOT_FOUND`, `ERR_COMPLIANCE_AUDIT_NOT_FOUND` and `ERR_AUDIT_FINDING_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/material_input_create_under_unknown_style_not_found
    """
    register_brand(legal_name=_BRAND_NAME, party_type="BRAND_OWNER",
                   rn_number="RN12345", responsibility_mode="SELF_OF_RECORD")

    payload = material_input_payload(stage="FIBER", country_code="IN",
                                     value_added_usd=2.00, weight_grams=500.0,
                                     is_ornamentation=False)
    resp = api.create_material_input(_UNKNOWN_UUID, payload, compliance_admin_headers)
    validate_error(resp, ApiErrorId.ERR_STYLE_NOT_FOUND, 404)


def test_material_input_parent_from_another_style_is_a_stage_order_violation(
        api, compliance_admin_headers):
    """PRD 3.3: "A supplied `parent_input_id` must reference a node of the *same* style whose stage rank is strictly less than the new node's stage rank, so yarn can be made from fiber but never from fabric; and a `TRIM` node must always be a root, meaning its `parent_input_id` must be null."

    PRD 3.3: "Violations of either rule — a cross-style parent, a parent at an equal or higher rank, or a parented trim node — are rejected with `ERR_MATERIAL_STAGE_ORDER`."

    Design: Corner/entities/material_input_parent_belonging_to_another_style_is_rejected
    """
    _market, brand = _brand_and_market()
    style_one = create_style(brand["id"], style_code="NL-S1",
                            product_class="WOVEN_OUTERWEAR",
                            target_market_codes=["US"], net_weight_grams=320.0,
                            declared_fibers=[fiber_line("COTTON", 100.0)])
    style_two = create_style(brand["id"], style_code="NL-S2",
                            product_class="WOVEN_OUTERWEAR",
                            target_market_codes=["US"], net_weight_grams=310.0,
                            declared_fibers=[fiber_line("COTTON", 100.0)])
    foreign_node = add_material_input(style_two["id"], stage="FIBER",
                                      country_code="IN", value_added_usd=2.00,
                                      weight_grams=500.0, is_ornamentation=False)

    payload = material_input_payload(stage="YARN", country_code="IN",
                                     value_added_usd=3.00, weight_grams=480.0,
                                     is_ornamentation=False,
                                     parent_input_id=foreign_node["id"])
    validate_error(
        api.create_material_input(style_one["id"], payload,
                                  make_brand_admin_headers(brand["id"])),
        ApiErrorId.ERR_MATERIAL_STAGE_ORDER, 422)

    rows, meta = validate_paginated(api.list_material_inputs(
        compliance_admin_headers, params={"style_id": style_one["id"]}))
    assert meta["total_count"] == 0, (
        "the rejected append must persist no node in the first style's graph, got "
        f"total_count {meta['total_count']}"
    )
    assert rows == [], f"the first style's graph must stay empty, got {rows!r}"

    _kept, kept_meta = validate_paginated(api.list_material_inputs(
        compliance_admin_headers, params={"style_id": style_two["id"]}))
    assert kept_meta["total_count"] == 1, (
        "the other style keeps its own root node, got total_count "
        f"{kept_meta['total_count']}"
    )
