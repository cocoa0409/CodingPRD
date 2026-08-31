"""Pricing the permit: four separately rounded fee components."""
from test_helpers import (
    validate_success, validate_paginated,
    assert_permit_submittal, assert_permit_fee_components_sum,
    permit_submittal_payload,
    setup_intake_project, setup_feasibility_cleared_project,
    add_utility_connection, decide_utility_connection, open_project,
    prepare_submittal, file_submittal, approve_plan_check, read_project,
    DESIGN_LEAD,
)


def test_each_fee_component_is_rounded_before_the_components_are_summed(api):
    """PRD §2.8: "Where a total is described as the sum of several rate-driven components,
    each component is rounded to whole cents **first** and the already-rounded components are
    then added. Computing the exact real-valued components, summing them, and rounding once
    at the end produces a different answer and is incorrect."
    PRD §3.4: "`plan_check_component_cents` is the jurisdiction's `plan_check_base_fee_cents`
    plus its `plan_check_rate_per_sqft_cents` multiplied by the project's `proposed_sqft`,
    with a 7.5 percent technology surcharge applied to that subtotal — that is, the subtotal
    multiplied by 1.075 — and the result rounded half away from zero to whole cents."

    Design: Difficulty/combinatorial_formula/permit_fee_component_rounding_order
    """
    ctx = setup_feasibility_cleared_project(api)
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")
    decide_utility_connection(api, connection["id"])

    submittal = validate_success(api.create_permit_submittal(
        ctx["project"]["id"], permit_submittal_payload(), DESIGN_LEAD), 201)

    assert_permit_submittal(submittal)
    assert submittal["plan_check_component_cents"] == 203_207
    assert submittal["impact_component_cents"] == 324_573
    assert submittal["school_component_cents"] == 372_685
    assert submittal["total_permit_fee_cents"] == 1_120_465
    assert submittal["total_permit_fee_cents"] != 1_120_466, (
        "summing the unrounded reals and rounding once at the end is the wrong order")


def test_priced_permit_includes_the_decided_utility_component(api):
    """PRD §3.4: "`utility_component_cents` is the sum of `separation_cost_cents` across every
    utility record of the project whose status is `SEPARATE_APPROVED`, `SHARED_APPROVED`, or
    `ENERGIZED`, enumerated in `created_at` ascending order; records still in
    `PENDING_DECISION` contribute nothing."
    PRD §3.4: "The new `PermitSubmittal` is created in `PREPARED` status with `cycle_number`
    0, `design_revision` 1, and `submitted_on_date`, `correction_deadline_date`, and
    `approved_on_date` all null — and with its fee already priced."

    Design: Difficulty/combinatorial_formula/permit_fee_component_rounding_order
    """
    ctx = setup_feasibility_cleared_project(api)
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")
    decided = decide_utility_connection(api, connection["id"])
    assert decided["decision"] == "SHARED"

    submittal = validate_success(api.create_permit_submittal(
        ctx["project"]["id"], permit_submittal_payload(), DESIGN_LEAD), 201)

    assert submittal["utility_component_cents"] == 220_000
    assert submittal["status"] == "PREPARED"
    assert submittal["cycle_number"] == 0
    assert submittal["design_revision"] == 1
    assert submittal["submitted_on_date"] is None
    assert submittal["approved_on_date"] is None
    assert_permit_fee_components_sum(submittal)


def test_impact_component_is_zero_strictly_below_750_sqft(api):
    """PRD §3.4: "`impact_component_cents` is zero for any unit strictly smaller than 750
    square feet; at 750 square feet and above it is the jurisdiction's
    `impact_fee_per_sqft_cents` multiplied by `proposed_sqft`, multiplied again by a
    proportionality factor that is the lesser of 1.0 and the ratio of `proposed_sqft` to the
    parcel's `existing_dwelling_sqft`, rounded half away from zero to whole cents."

    Design: Difficulty/boundary_precision_check/impact_fee_threshold_at_750_sqft
    """
    ctx = setup_intake_project(api, project_overrides={"proposed_sqft": 749})

    submittal = validate_success(api.create_permit_submittal(
        ctx["project"]["id"], permit_submittal_payload(design_sheet_count=12), DESIGN_LEAD), 201)

    assert submittal["impact_component_cents"] == 0
    assert submittal["plan_check_component_cents"] == 201_466
    assert submittal["school_component_cents"] == 363_939
    assert submittal["total_permit_fee_cents"] == 565_405


def test_impact_component_applies_at_exactly_750_sqft(api):
    """PRD §3.4: "`impact_component_cents` is zero for any unit strictly smaller than 750
    square feet; at 750 square feet and above it is the jurisdiction's
    `impact_fee_per_sqft_cents` multiplied by `proposed_sqft`, multiplied again by a
    proportionality factor that is the lesser of 1.0 and the ratio of `proposed_sqft` to the
    parcel's `existing_dwelling_sqft`, rounded half away from zero to whole cents."
    PRD §2.8: "The first, applied to every fee and every builder markup, rounds half away
    from zero to whole cents — so a computed fee of 1250.5 cents becomes 1251, and a computed
    credit of negative 1250.5 cents becomes negative 1251."

    Design: Difficulty/boundary_precision_check/impact_fee_threshold_at_750_sqft
    """
    ctx = setup_intake_project(api, project_overrides={"proposed_sqft": 749})
    at_threshold = open_project(api, ctx["property"]["id"], proposed_sqft=750)

    submittal = validate_success(api.create_permit_submittal(
        at_threshold["id"], permit_submittal_payload(design_sheet_count=12), DESIGN_LEAD), 201)

    assert submittal["impact_component_cents"] == 310_345
    assert submittal["plan_check_component_cents"] == 201_563, (
        "187500 * 1.075 = 201562.5 rounds half away from zero to 201563")
    assert submittal["school_component_cents"] == 364_425
    assert submittal["total_permit_fee_cents"] == 876_333


def test_school_component_is_zero_strictly_below_500_sqft(api):
    """PRD §3.4: "`school_component_cents` is zero for any unit strictly smaller than 500
    square feet; at 500 square feet and above it is a statewide rate of 452 cents per square
    foot multiplied by `proposed_sqft`, carrying the same 7.5 percent technology surcharge,
    rounded half away from zero to whole cents."

    Design: Corner/calculations/school_fee_exempt_strictly_below_500_sqft
    """
    small = {"unit_type": "CONVERSION", "proposed_sqft": 499, "proposed_height_ft": 12.0,
             "rear_setback_ft": 4.0, "side_setback_ft": 4.0, "bedrooms": 1,
             "contract_base_price_cents": 15_000_000}
    ctx = setup_intake_project(api, project_overrides=small)
    at_threshold = open_project(api, ctx["property"]["id"], **dict(small, proposed_sqft=500))

    below = validate_success(api.create_permit_submittal(
        ctx["project"]["id"], permit_submittal_payload(design_sheet_count=9), DESIGN_LEAD), 201)
    at = validate_success(api.create_permit_submittal(
        at_threshold["id"], permit_submittal_payload(design_sheet_count=9), DESIGN_LEAD), 201)

    assert below["school_component_cents"] == 0
    assert below["impact_component_cents"] == 0
    assert below["plan_check_component_cents"] == 177_278
    assert below["total_permit_fee_cents"] == 177_278

    assert at["school_component_cents"] == 242_950
    assert at["plan_check_component_cents"] == 177_375
    assert at["total_permit_fee_cents"] == 420_325


def test_submittal_listing_separates_the_revision_package_from_the_original(api):
    """PRD §3.4: "Submittal listings for a project may be narrowed by `status`."
    PRD §3.4: "An `APPROVED` outcome closes the permit: the submittal moves
    `UNDER_PLAN_CHECK → APPROVED`, `approved_on_date` is stamped from the logical clock, the
    project moves `PERMITTING → PERMITTED`, and the submittal's `total_permit_fee_cents` is
    copied onto the project's own `total_permit_fee_cents` field."

    Design: Corner/endpoints/list_permit_submittals_for_project_returns_both_revisions
    """
    ctx = setup_feasibility_cleared_project(api)
    first = prepare_submittal(api, ctx["project"]["id"])
    file_submittal(api, first["id"])
    approve_plan_check(api, first["id"])
    revision = prepare_submittal(api, ctx["project"]["id"], design_sheet_count=3)
    file_submittal(api, revision["id"])

    rows, meta = validate_paginated(api.list_permit_submittals(
        ctx["project"]["id"], DESIGN_LEAD, {"status": "UNDER_PLAN_CHECK"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == revision["id"]

    everything, all_meta = validate_paginated(
        api.list_permit_submittals(ctx["project"]["id"], DESIGN_LEAD))
    assert all_meta["total_count"] == 2
    assert everything[0]["id"] == first["id"], "submittals come back oldest first"

    project = read_project(api, ctx["project"]["id"])
    assert project["total_permit_fee_cents"] == 900_465, (
        "no utility record was ever created, so utility_component_cents is 0")
