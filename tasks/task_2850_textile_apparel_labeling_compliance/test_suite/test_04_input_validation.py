"""Input-validation and rejection-ordering behaviour of the labeling API.

Every test in this module drives one request that is defective in a way the PRD
names explicitly, and asserts both the error identifier the PRD attaches to that
defect and the fact that the refused request left no trace behind.
"""
import pytest

from test_helpers import *  # noqa: F401,F403

# A syntactically valid UUID that names no persisted row.
_ABSENT_STYLE_ID = "2f1a9b7c-0000-4000-8000-000000000000"


def _brand_and_market(market_code="US", **market_overrides):
    """Register one market regime and one self-of-record brand owner, and return
    (brand, brand_admin_headers). The BrandAdmin headers carry the brand row's own
    id, which is what every brand-scope-gated write compares against."""
    register_market(market_code, **market_overrides)
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    return brand, make_brand_admin_headers(brand["id"])


def test_fiber_declaration_summing_to_one_hundred_point_one_is_rejected(api):
    """PRD 3.2: "A non-empty array that misses 100.0, or one that declares the same
    fiber name twice, is rejected with `ERR_FIBER_PERCENT_SUM`."

    60.0 + 37.1 + 3.0 sums to 100.1 after one-decimal rounding, so the style is
    refused even though it lands within a tenth of the target, and nothing is
    persisted for the brand.

    Design: Corner/validations/fiber_declaration_summing_to_one_hundred_point_one_is_rejected
    """
    brand, brand_headers = _brand_and_market()

    payload = style_payload(
        brand["id"],
        style_code="NL-SUM-1",
        product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"],
        net_weight_grams=320.0,
        declared_fibers=[
            fiber_line("COTTON", 60.0),
            fiber_line("POLYESTER", 37.1),
            fiber_line("ELASTANE", 3.0),
        ],
    )
    resp = api.create_style(payload, brand_headers)
    validate_error(resp, ApiErrorId.ERR_FIBER_PERCENT_SUM, 422)

    listing = api.list_brand_styles(brand["id"], ADMIN)
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        "A declaration summing to 100.1 must persist no Style row, got "
        f"total_count={meta['total_count']}"
    )
    assert rows == [], f"Expected an empty style list for the brand, got {rows}"


def test_fiber_declaration_replacement_on_an_untested_style_is_accepted(api):
    """PRD 3.2: "From `FIBER_DECLARED` the replacement is an edit of a declaration
    that was never benched: the array is replaced, the printable string recomputed,
    the style stays at `FIBER_DECLARED`, `label_readiness` is recomputed and the
    style's `version` is incremented by 1." PRD 3.2: "This is also the path taken by
    the first declaration written onto a style that was created without one."

    The style is created with no declaration at all, so its printable string starts
    empty at version 1; the first replacement fires the FIBER_DECLARED self edge
    rather than a move, and touches no laboratory row.

    Design: Corner/validations/fiber_declaration_replacement_on_an_untested_style_is_accepted
    """
    brand, brand_headers = _brand_and_market()

    payload = style_payload(
        brand["id"],
        style_code="NL-BARE-1",
        product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"],
        net_weight_grams=300.0,
    )
    payload.pop("declared_fibers")
    style = validate_success(api.create_style(payload, brand_headers), 201)
    assert_style(style)
    assert style["version"] == 1, (
        f"A freshly created style starts at version 1, got {style['version']}"
    )
    assert style["declared_fibers"] == [], (
        "An omitted declaration array defaults to an empty array, got "
        f"{style['declared_fibers']}"
    )
    assert style["effective_fiber_content_text"] == "", (
        "An empty declaration renders the empty string, got "
        f"{style['effective_fiber_content_text']!r}"
    )
    assert style["substantiation_state"] == "FIBER_DECLARED", (
        f"A new style starts at FIBER_DECLARED, got {style['substantiation_state']}"
    )

    replacement = {
        "declared_fibers": [
            fiber_line("COTTON", 60.0),
            fiber_line("POLYESTER", 37.0),
            fiber_line("ELASTANE", 3.0),
        ],
        "expected_style_version": style["version"],
    }
    updated = validate_success(
        api.replace_fiber_declaration(style["id"], replacement, brand_headers), 200)
    assert_style(updated)
    assert updated["substantiation_state"] == "FIBER_DECLARED", (
        "The FIBER_DECLARED self edge must fire on a replacement that was never "
        f"benched, got {updated['substantiation_state']}"
    )
    assert updated["version"] == 2, (
        f"The replacement increments the style version 1 -> 2, got {updated['version']}"
    )
    assert updated["effective_fiber_content_text"] == (
        "60.0% COTTON, 37.0% POLYESTER, 3.0% OTHER FIBER"), (
        "ELASTANE at 3.0 sits below the 5.0 listing threshold and buckets into "
        f"OTHER FIBER, got {updated['effective_fiber_content_text']!r}"
    )
    assert updated["label_readiness"] == "BLOCKED", (
        "A declaration alone substantiates nothing, so label_readiness stays "
        f"BLOCKED, got {updated['label_readiness']}"
    )

    tests_listing = api.list_style_lab_tests(style["id"], ADMIN)
    _, meta = validate_paginated(tests_listing)
    assert meta["total_count"] == 0, (
        "No laboratory row is touched or created by a FIBER_DECLARED replacement, "
        f"got total_count={meta['total_count']}"
    )


def test_origin_determination_on_a_trim_only_graph_is_rejected(api):
    """PRD 3.3: "It is refused with `ERR_ORIGIN_GRAPH_INSUFFICIENT` unless the
    style's graph has at least one non-ornamentation node at stage `YARN`, `FABRIC`
    or `CUT_AND_SEW` — the pool the first legal method needs — and at least one
    non-ornamentation node at stage `YARN` or `FIBER`, which is the pool the second
    method needs." PRD 3.3: "Trim nodes never enter either pool."

    A single non-ornamentation TRIM node satisfies neither pool, so the draft is
    refused and the style's origin dimension must stay at ORIGIN_UNDETERMINED with
    its version untouched.

    Design: Corner/validations/origin_determination_on_a_trim_only_graph_is_rejected
    """
    brand, brand_headers = _brand_and_market()
    style = validate_success(api.create_style(style_payload(
        brand["id"],
        style_code="NL-TRIM-1",
        product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"],
        net_weight_grams=300.0,
        declared_fibers=[fiber_line("COTTON", 100.0)],
    ), brand_headers), 201)

    add_material_input(style["id"], stage="TRIM", country_code="FR",
                       value_added_usd=4.00, weight_grams=30.0,
                       is_ornamentation=False)
    before = read_style(style["id"])
    assert before["origin_state"] == "ORIGIN_UNDETERMINED", (
        f"A style with only a TRIM node stays undetermined, got {before['origin_state']}"
    )

    resp = api.create_origin_determination(
        {"style_id": style["id"], "expected_style_version": before["version"]},
        SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_ORIGIN_GRAPH_INSUFFICIENT, 422)

    after = read_style(style["id"])
    assert after["origin_state"] == "ORIGIN_UNDETERMINED", (
        "A refused draft must not advance the origin dimension, got "
        f"{after['origin_state']}"
    )
    assert after["version"] == before["version"], (
        f"A refused draft bumps no version, expected {before['version']} but got "
        f"{after['version']}"
    )

    listing = api.list_style_origin_determinations(style["id"], ADMIN)
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        "A refused draft persists no OriginDetermination row, got "
        f"total_count={meta['total_count']}"
    )


def test_fiber_results_summing_below_the_coherence_band_are_rejected(api):
    """PRD 3.4: "For a fiber-content run, `measured_fibers` must be non-empty — each
    entry pairing a `fiber_generic_name` with a `measured_pct` at one decimal place —
    and the measured percentages must sum to a value within 99.0 through 101.0
    inclusive; a sum outside that band is rejected with `ERR_LAB_RESULT_INCOHERENT`."

    57.0 + 40.0 + 1.5 sums to 98.5 and falls below the closed band, so the post is
    refused before any tolerance comparison runs; the bench stays BENCH_RESERVED and
    the same row accepts a corrected post whose 3.0 pp deviation exactly equals the
    governing market tolerance.

    Design: Corner/validations/fiber_results_summing_below_the_coherence_band_are_rejected
    """
    brand, brand_headers = _brand_and_market(fiber_tolerance_pp=3.0)
    style = validate_success(api.create_style(style_payload(
        brand["id"],
        style_code="NL-4410",
        product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"],
        net_weight_grams=320.0,
        declared_fibers=[
            fiber_line("COTTON", 60.0),
            fiber_line("POLYESTER", 37.0),
            fiber_line("ELASTANE", 3.0),
        ],
    ), brand_headers), 201)

    lab_test = reserve_fiber_test(
        style["id"], lab_code="LAB-ATL-1", method="AATCC_20A",
        specimen_received_at="2026-08-03T09:00:00Z",
        results_due_at="2026-08-05T09:00:00Z")
    assert lab_test["state"] == "BENCH_RESERVED", (
        f"A fresh reservation lands in BENCH_RESERVED, got {lab_test['state']}"
    )

    incoherent = {"measured_fibers": [
        {"fiber_generic_name": "COTTON", "measured_pct": 57.0},
        {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
        {"fiber_generic_name": "ELASTANE", "measured_pct": 1.5},
    ]}
    resp = api.post_lab_test_results(lab_test["id"], incoherent, LAB)
    validate_error(resp, ApiErrorId.ERR_LAB_RESULT_INCOHERENT, 422)

    after = validate_success(api.get_lab_test(lab_test["id"], LAB), 200)
    assert_lab_test(after)
    assert after["state"] == "BENCH_RESERVED", (
        f"A refused post leaves the bench reserved, got {after['state']}"
    )
    assert after["result_delta_pp_max"] is None, (
        "result_delta_pp_max stays null until results are posted, got "
        f"{after['result_delta_pp_max']}"
    )
    assert not after.get("measured_fibers"), (
        f"The refused post writes no measurements, got {after.get('measured_fibers')}"
    )
    style_after = read_style(style["id"])
    assert style_after["substantiation_state"] == "FIBER_TEST_PENDING", (
        "The refusal leaves the style at FIBER_TEST_PENDING so the lab can post a "
        f"corrected result, got {style_after['substantiation_state']}"
    )

    corrected = {"measured_fibers": [
        {"fiber_generic_name": "COTTON", "measured_pct": 57.0},
        {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
        {"fiber_generic_name": "ELASTANE", "measured_pct": 3.0},
    ]}
    passed = validate_success(
        api.post_lab_test_results(lab_test["id"], corrected, LAB), 200)
    assert passed["state"] == "PASSED", (
        "A measured sum of exactly 100.0 whose largest deviation equals the 3.0 pp "
        f"market tolerance passes, got {passed['state']}"
    )
    assert passed["result_delta_pp_max"] == pytest.approx(3.0, abs=0.01), (
        "The largest deviation over the union of declared and measured names is "
        f"3.0 pp, got {passed['result_delta_pp_max']}"
    )


def test_unknown_style_in_the_path_answers_before_a_malformed_body(api):
    """PRD 2.7: "The service therefore evaluates checks in one fixed order and
    returns the error of the **earliest** applicable check — never the most obvious
    defect, and never the last one discovered." PRD 2.6: "Identifiers embedded in a
    URL path are resolved strictly left to right, and the first one that does not
    resolve to a live row decides the 404."

    The request is defective twice over: the style in the path does not exist, and
    the body names a `stage` of GARMENT which is not a declared enum member. Path
    existence is rung 3 of the ladder and request shape is rung 6, so the answer must
    be ERR_STYLE_NOT_FOUND rather than ERR_INVALID_REQUEST.

    Design: Corner/validations/unknown_style_in_the_path_answers_before_a_malformed_body
    """
    register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")

    doubly_defective = {
        "stage": "GARMENT",
        "country_code": "IN",
        "value_added_usd": 2.00,
        "weight_grams": 500.0,
        "is_ornamentation": False,
    }
    resp = api.create_material_input(_ABSENT_STYLE_ID, doubly_defective, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STYLE_NOT_FOUND, 404)


def test_audit_window_that_ends_before_it_starts_is_rejected(api):
    """PRD 3.9: "It names the audited `brand_id`, a `scope` of `STYLE_DOSSIER`,
    `MARKET_LABELING` or `IMPORT_MARKING`, and a bounded audited period given by
    `audit_window_from` inclusive and `audit_window_to` exclusive, where the upper
    bound must be strictly after the lower bound — otherwise
    `ERR_INVALID_EFFECTIVE_WINDOW`."

    A reversed window is refused and no ComplianceAudit row is created.

    Design: Corner/validations/audit_window_that_ends_before_it_starts_is_rejected
    """
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")

    payload = compliance_audit_payload(
        brand["id"],
        scope="STYLE_DOSSIER",
        audit_window_from="2026-06-30T00:00:00Z",
        audit_window_to="2026-01-01T00:00:00Z",
    )
    resp = api.create_compliance_audit(payload, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_EFFECTIVE_WINDOW, 422)

    listing = api.list_compliance_audits(AUDITOR, params={"brand_id": brand["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        "A reversed audit window must persist no ComplianceAudit row, got "
        f"total_count={meta['total_count']}"
    )
    assert rows == [], f"Expected an empty audit list for the brand, got {rows}"


def test_style_code_is_unique_per_brand_and_reusable_across_brands(api):
    """PRD 3.2: "It names its owning party through a `brand_id` in the creation
    payload, carries a brand-facing `style_code` of 1 to 32 characters that must be
    unique within that party — a repeat is rejected with `ERR_DUPLICATE_STYLE_CODE` —
    and declares a `product_class` from `WOVEN_OUTERWEAR`, `KNIT_TOP`, `HOSIERY` and
    `HOME_TEXTILE`."

    Uniqueness is scoped to the pair of brand and style code: the second NL-4410
    under the same brand is refused, while the identical code under a different brand
    is accepted.

    Design: Corner/validations/style_code_is_unique_per_brand_and_reusable_across_brands
    """
    register_market("US")
    brand_a = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    brand_b = register_brand(legal_name="Harborline Brands Inc", rn_number="RN67890")
    headers_a = make_brand_admin_headers(brand_a["id"])
    headers_b = make_brand_admin_headers(brand_b["id"])

    def _payload(brand_id, product_class, net_weight_grams):
        return style_payload(
            brand_id,
            style_code="NL-4410",
            product_class=product_class,
            target_market_codes=["US"],
            net_weight_grams=net_weight_grams,
            declared_fibers=[fiber_line("COTTON", 100.0)],
        )

    style_a = validate_success(api.create_style(
        _payload(brand_a["id"], "WOVEN_OUTERWEAR", 320.0), headers_a), 201)

    duplicate = api.create_style(
        _payload(brand_a["id"], "KNIT_TOP", 200.0), headers_a)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_STYLE_CODE, 409)

    style_b = validate_success(api.create_style(
        _payload(brand_b["id"], "KNIT_TOP", 200.0), headers_b), 201)
    assert_style(style_b)
    assert style_b["id"] != style_a["id"], (
        "The same style code under a different brand must yield a distinct row"
    )
    assert style_b["brand_id"] == brand_b["id"], (
        f"The second style belongs to brand B, got brand_id={style_b['brand_id']}"
    )

    listing = api.list_brand_styles(brand_a["id"], ADMIN)
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, (
        "The refused duplicate must leave brand A owning exactly one style, got "
        f"total_count={meta['total_count']}"
    )


def test_trim_node_carrying_a_parent_is_rejected(api):
    """PRD 3.3: "A supplied `parent_input_id` must reference a node of the *same*
    style whose stage rank is strictly less than the new node's stage rank, so yarn
    can be made from fiber but never from fabric; and a `TRIM` node must always be a
    root, meaning its `parent_input_id` must be null." PRD 3.3: "Violations of either
    rule — a cross-style parent, a parent at an equal or higher rank, or a parented
    trim node — are rejected with `ERR_MATERIAL_STAGE_ORDER`."

    The parent named here is a live FIBER node of the very same style, yet the TRIM
    node is still refused: TRIM must be a root, and TRIM's rank of 0 sits below
    FIBER's rank of 1 so the strictly-increasing clause is breached too.

    Design: Corner/validations/trim_node_carrying_a_parent_is_rejected
    """
    brand, brand_headers = _brand_and_market()
    style = validate_success(api.create_style(style_payload(
        brand["id"],
        style_code="NL-4410",
        product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"],
        net_weight_grams=320.0,
        declared_fibers=[fiber_line("COTTON", 100.0)],
    ), brand_headers), 201)

    root = add_material_input(style["id"], stage="FIBER", country_code="IN",
                              value_added_usd=2.00, weight_grams=500.0,
                              is_ornamentation=False)
    assert_material_input(root)
    assert root["depth"] == 0, f"A root node has depth 0, got {root['depth']}"

    parented_trim = material_input_payload(
        stage="TRIM", country_code="FR", value_added_usd=4.00,
        weight_grams=30.0, is_ornamentation=False, parent_input_id=root["id"])
    resp = api.create_material_input(style["id"], parented_trim, brand_headers)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_STAGE_ORDER, 422)

    listing = api.list_material_inputs(ADMIN, params={"style_id": style["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, (
        "The refused TRIM node must not join the graph, so only the FIBER root "
        f"remains, got total_count={meta['total_count']}"
    )
    assert [row["stage"] for row in rows] == ["FIBER"], (
        f"Expected the graph to hold only the FIBER root, got {rows}"
    )
