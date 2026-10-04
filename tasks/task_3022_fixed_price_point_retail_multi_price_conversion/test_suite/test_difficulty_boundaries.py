"""Boundary precision on three scalar metrics and on two empty-collection edges."""

from test_helpers import (
    ANALYST_HEADERS,
    api_client,
    factories,
    E,
    get_success_data,
    PLANNER_HEADERS,
    SOM_HEADERS,
    validate_error,
    validate_success,
    fixtures,
)



def test_the_pack_ceiling_is_inclusive_at_its_exact_value_and_rejects_the_next_cent(api):
    """123 cents passes the landing gate; 124 is the first rejecting value.

    PRD §3.5: "the shelf price is first multiplied by the target landed cost ratio as an exact
    rational, that product is then multiplied by one minus the buffer, and the result is floored
    at the cent, with the cent rounding performed half down."
    PRD §3.5: "The comparison against the vendor's quote is inclusive on the passing side: a
    quoted cost at or below the ceiling passes, and only a quoted cost strictly above the ceiling
    fails."
    PRD §3.5: "Once the program is advancing from `PENDING_ACTIVATION` to `ACTIVE`, the same
    ceiling becomes fatal: a `quoted_landed_cost_cents` strictly above it raises
    `ERR_PACK_COST_TARGET_MISSED` and HTTP 422 and the transition does not occur."

    Design: Difficulty/boundary_precision_check/three_scalar_threshold_boundaries_first_true_at_k
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(400, 0.35, label="FOUR_DOLLAR")
    vendor = fixtures.create_vendor()

    # floor(400 * 0.35 * 0.88) == floor(123.2) == 123.
    at_ceiling = fixtures.create_pack_program(
        vendor["id"], price_point["id"], quoted_landed_cost_cents=123)
    assert at_ceiling["target_landed_cost_cents"] == 123
    landed = validate_success(
        fixtures.advance_pack_program(at_ceiling["id"], status="ACTIVE"), 200)
    assert landed["status"] == "ACTIVE", "a quote at exactly the ceiling passes the gate"

    above_ceiling = fixtures.create_pack_program(
        vendor["id"], price_point["id"], quoted_landed_cost_cents=124)
    validate_error(
        fixtures.advance_pack_program(above_ceiling["id"], status="ACTIVE"),
        E.ERR_PACK_COST_TARGET_MISSED.value,
    )
    still_draft = validate_success(api.get_pack_program(above_ceiling["id"], ANALYST_HEADERS), 200)
    assert still_draft["status"] == "DRAFT", "the failed advance left the program where it was"


def test_the_mismatch_tolerance_is_inclusive_on_the_rounded_ratio(api):
    """Five mismatches over 96 facings round to the tolerance; over 80 they exceed it.

    PRD §3.11: "Otherwise the ratio is the mismatched count divided by the observed count,
    rounded half up to three decimal places, and the result is `VIOLATION` when that rounded
    ratio is strictly greater than the tolerance of 0.052, and `WITHIN_TOLERANCE` otherwise."
    PRD §3.11: "Because the comparison runs on the rounded value rather than the raw quotient,
    ratios that differ in their raw form can land on the same rounded figure and take the same
    branch"
    PRD §2.6: "Coverage ratios and mismatch ratios are the two ratio-valued outputs in this
    system, and each is rounded half up to exactly 3 decimal places, with the tolerance
    comparisons evaluated against the rounded value rather than the raw quotient."

    Design: Difficulty/boundary_precision_check/three_scalar_threshold_boundaries_first_true_at_k
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()

    exact = validate_success(
        api_client.create_audit(
            factories.create_audit_payload(
                store["id"], price_point["id"], observed_item_count=96, mismatched_item_count=5),
            SOM_HEADERS),
        201,
    )
    # 5 / 96 == 0.052083... which rounds to 0.052: equality stays WITHIN_TOLERANCE.
    assert exact["mismatch_ratio"] == 0.052
    assert exact["result"] == "WITHIN_TOLERANCE", "the tolerance is inclusive on the passing side"

    over = validate_success(
        api_client.create_audit(
            factories.create_audit_payload(
                store["id"], price_point["id"], observed_item_count=80, mismatched_item_count=5),
            SOM_HEADERS),
        201,
    )
    # 5 / 80 == 0.0625, which rounds half up to 0.063 and exceeds the tolerance.
    assert over["mismatch_ratio"] == 0.063
    assert over["result"] == "VIOLATION"


def test_the_coverage_floor_is_read_on_the_rounded_ratio_for_three_unfinished_resets(api):
    """Zero of three executed resets measures -1.000 against a baseline of three.

    PRD §3.8: "`coverage_delta_pct` is the completed count minus that baseline, divided by that
    baseline, rounded half up to three decimal places."
    PRD §3.8: "`completed_aisle_count` counts the store's aisle resets in `EXECUTED`;
    `projected_convertible_aisle_count` counts those in `PLANNED` or `EXECUTING`; abandoned
    resets are excluded from both counts."
    PRD §3.8: "An `adjusted_baseline` is then taken as the larger of the projected convertible
    count and a floor of one aisle, so a store with no projected resets is measured against a
    baseline of one rather than dividing by zero."

    Design: Difficulty/boundary_precision_check/three_scalar_threshold_boundaries_first_true_at_k
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(400, 0.35, label="FOUR_DOLLAR")
    store = fixtures.create_store(shelf_facing_capacity_sqft=400.0)
    window = fixtures.create_open_season_window()
    # The begin runs first, so the store's conversion price point is the target;
    # while the store is CONVERTING every reset must carry that same price point.
    begin = validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    assert begin["status"] == "CONVERTING"
    for index, aisle in enumerate(("A11", "A12", "A13"), start=1):
        fixtures.plan_reset_ok(
            store["id"], target["id"], window["id"], aisle_code=aisle,
            starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
            allocated_shelf_sqft=50.0)

    project = get_success_data(fixtures.open_conversion_project(
        store["id"], origin["id"], target["id"], expected_store_version=begin["version"]), 201)
    started = validate_success(api.start_conversion_project(project["id"], SOM_HEADERS), 200)
    assert started["status"] == "IN_PROGRESS"
    state = {"conversion_id": project["id"]}
    coverage = validate_success(
        api.get_project_coverage(state["conversion_id"], SOM_HEADERS), 200)
    assert coverage["completed_aisle_count"] == 0
    assert coverage["projected_convertible_aisle_count"] == 3
    assert coverage["adjusted_baseline"] == 3
    assert coverage["coverage_delta_pct"] == -1.000
    assert coverage["shortfall"] is True, "zero of three is below the negative one half floor"


def test_a_visit_with_no_facings_is_defined_rather_than_a_division_error(api):
    """A zero-facings audit reads ratio zero and a clean result.

    PRD §3.11: "When `observed_item_count` is zero the ratio is zero and the result is
    `WITHIN_TOLERANCE`."
    PRD §3.11: "A newly filed audit begins `OPEN`, its store's `price_integrity_audit_count` is
    incremented, and the store's `open_violation_count` is recomputed."
    PRD §3.11: "Both counts must be non-negative, and the mismatched count must not exceed the
    observed count; a negative count or a mismatch count above the observed count is refused as
    malformed."

    Design: Difficulty/boundary_precision_check/empty_and_zero_collection_edges_on_second_endpoints
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()

    visit = validate_success(
        api_client.create_audit(
            factories.create_audit_payload(
                store["id"], price_point["id"], observed_item_count=0, mismatched_item_count=0),
            SOM_HEADERS),
        201,
    )
    assert visit["observed_item_count"] == 0
    assert visit["mismatched_item_count"] == 0
    assert visit["mismatch_ratio"] == 0
    assert visit["result"] == "WITHIN_TOLERANCE"
    assert visit["status"] == "OPEN"

    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["price_integrity_audit_count"] == 1, "the visit is still recorded"
    assert store_after["open_violation_count"] == 0, "a clean visit is not an open violation"


def test_a_project_with_no_resets_reads_the_baseline_substitute(api):
    """A project on a store with zero AisleReset rows reads a baseline of one, not a divide by zero.

    PRD §3.8: "An `adjusted_baseline` is then taken as the larger of the projected convertible
    count and a floor of one aisle, so a store with no projected resets is measured against a
    baseline of one rather than dividing by zero."
    PRD §3.8: "`coverage_delta_pct` is the completed count minus that baseline, divided by that
    baseline, rounded half up to three decimal places."
    PRD §2.8: "a `to_price_point_id` equal to its `from_price_point_id`"

    Design: Difficulty/boundary_precision_check/empty_and_zero_collection_edges_on_second_endpoints
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(400, 0.35, label="FOUR_DOLLAR")
    store = fixtures.create_store()

    begin = validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    same_pair = fixtures.open_conversion_project(
        store["id"], origin["id"], origin["id"], expected_store_version=begin["version"])
    validate_error(same_pair, E.ERR_INVALID_REQUEST.value)

    # The store is already CONVERTING from the begin above, so the project is opened
    # against that same observation rather than re-beginning the conversion.
    project = get_success_data(fixtures.open_conversion_project(
        store["id"], origin["id"], target["id"], expected_store_version=begin["version"]), 201)
    validate_success(api.start_conversion_project(project["id"], SOM_HEADERS), 200)
    coverage = validate_success(api.get_project_coverage(project["id"], SOM_HEADERS), 200)
    assert coverage["completed_aisle_count"] == 0
    assert coverage["projected_convertible_aisle_count"] == 0
    assert coverage["adjusted_baseline"] == 1, (
        "the floor of one aisle stands in for the empty projected set"
    )
    assert coverage["coverage_delta_pct"] == -1.000
    assert coverage["shortfall"] is True

    resets = validate_success(api.list_store_aisle_resets(store["id"], PLANNER_HEADERS), 200)
    assert resets == []