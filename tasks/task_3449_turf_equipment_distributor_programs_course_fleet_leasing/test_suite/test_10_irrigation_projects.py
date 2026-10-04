"""Irrigation dealer channel: the pinned design-spec evaluation order, per-turf
water budgets, half-open install-window overlap with adjacency, and the stale
controller reference at approval (PRD §3.9).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_irrigation_project_payload,
    make_course_manager_headers,
    make_irrigation_dealer_headers,
    run_rollover,
    setup_irrigation_project,
    submit_design,
    validate_error,
    validate_success,
)


def test_design_submit_computes_controllers_and_fee(api):
    """PRD §3.9: "First, `controllers_required` is the `zone_count` divided by
    8 zones per controller, rounded up. Second, `design_fee_cents` is a base
    design fee of 250,000 cents, plus 45,000 cents per required controller,
    plus 12,000 cents per irrigated acre."
    PRD §3.9: "On submission the design specification is computed in a pinned
    order — the controller count feeds the fee, and the fee never feeds the
    controller count, so there is no iteration."

    Design: Difficulty/combinatorial_formula/irrigation_controller_fee_order_of_evaluation
    """
    ctx = setup_irrigation_project()  # 120 acres, 22 zones, BENTGRASS course
    submitted = submit_design(ctx["project"], ctx["controller"])
    # ceil(22 / 8) = 3 controllers, and the controller count feeds the fee.
    assert submitted["controllers_required"] == 3
    # 250,000 + 3 x 45,000 + 120 x 12,000 = 1,825,000.
    assert submitted["design_fee_cents"] == 1825000, (
        f"got {submitted['design_fee_cents']}"
    )


def test_design_submit_computes_water_budget_and_pins_model(api):
    """PRD §3.9: "Third, `water_budget_gpd` is the `acreage` multiplied by the
    daily gallons per acre for the course's `turf_profile`: 22,000 for
    `BENTGRASS`, 16,000 for `BERMUDA`, 20,000 for `POA_ANNUA`, and 18,000 for
    `MIXED`. The `controller_model_id` and both window fields are pinned on the
    project at this point."

    Design: Difficulty/combinatorial_formula/irrigation_controller_fee_order_of_evaluation
    """
    ctx = setup_irrigation_project()  # 120 acres, 22 zones, BENTGRASS course
    submitted = submit_design(ctx["project"], ctx["controller"])
    # 120 acres x 22,000 gpd (BENTGRASS) = 2,640,000.
    assert submitted["water_budget_gpd"] == 2640000
    assert submitted["controller_model_id"] == ctx["controller"]["id"]
    assert submitted["install_window_start"] == "2027-04-01"
    assert submitted["install_window_end"] == "2027-05-01"


def test_irrigation_bermuda_design_values(api):
    """PRD §3.9: "First, `controllers_required` is the `zone_count` divided by
    8 zones per controller, rounded up. Second, `design_fee_cents` is a base
    design fee of 250,000 cents, plus 45,000 cents per required controller,
    plus 12,000 cents per irrigated acre. Third, `water_budget_gpd` is the
    `acreage` multiplied by the daily gallons per acre for the course's
    `turf_profile`: 22,000 for `BENTGRASS`, 16,000 for `BERMUDA`, 20,000 for
    `POA_ANNUA`, and 18,000 for `MIXED`."

    Design: Corner/calculations/irrigation_bermuda_design_values
    """
    ctx = setup_irrigation_project(
        course_overrides={
            "name": "Sagebrush GC",
            "turf_profile": "BERMUDA",
            "cut_quality_standard": "MAINTENANCE",
            "credit_limit_cents": 5000000,
        },
        project_overrides={"acreage": 50, "zone_count": 17},
    )
    submitted = submit_design(ctx["project"], ctx["controller"])
    assert submitted["controllers_required"] == 3  # ceil(17 / 8)
    # 250,000 + 3 x 45,000 + 50 x 12,000 = 985,000.
    assert submitted["design_fee_cents"] == 985000
    # 50 acres x 16,000 gpd (BERMUDA) = 800,000.
    assert submitted["water_budget_gpd"] == 800000


def test_interior_overlap_rejected(api):
    """PRD §3.9: "And the window must not collide with another live project of
    the same course: no sibling project in `DESIGN_SUBMITTED`, `APPROVED`, or
    `INSTALLED` may have a half-open window — start inclusive, end exclusive —
    intersecting this one; adjacency, where one window's end equals another's
    start, is allowed, and a genuine overlap is rejected with
    `ERR_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/irrigation_halfopen_adjacency_allowed_overlap_rejected
    """
    ctx = setup_irrigation_project(
        project_overrides={"acreage": 60, "zone_count": 12}
    )
    submit_design(ctx["project"], ctx["controller"])  # [2027-04-01, 2027-05-01)
    dealer_headers = make_irrigation_dealer_headers(ctx["dealer"]["id"])
    second = validate_success(
        api.create_irrigation_project(
            create_irrigation_project_payload(ctx["course"]["id"], acreage=20, zone_count=6),
            dealer_headers,
        ),
        201,
    )
    resp = api.transition_irrigation_project(
        second["id"], "DESIGN_SUBMITTED", dealer_headers,
        controller_model_id=ctx["controller"]["id"],
        install_window_start="2027-04-15", install_window_end="2027-05-15",
    )
    # [2027-04-15, 2027-05-15) intersects [2027-04-01, 2027-05-01) interior.
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_adjacent_window_allowed(api):
    """PRD §3.9: "adjacency, where one window's end equals another's start, is
    allowed, and a genuine overlap is rejected with `ERR_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/irrigation_halfopen_adjacency_allowed_overlap_rejected
    """
    ctx = setup_irrigation_project(
        project_overrides={"acreage": 60, "zone_count": 12}
    )
    submit_design(ctx["project"], ctx["controller"])  # [2027-04-01, 2027-05-01)
    dealer_headers = make_irrigation_dealer_headers(ctx["dealer"]["id"])
    third = validate_success(
        api.create_irrigation_project(
            create_irrigation_project_payload(ctx["course"]["id"], acreage=40, zone_count=9),
            dealer_headers,
        ),
        201,
    )
    submitted = validate_success(
        api.transition_irrigation_project(
            third["id"], "DESIGN_SUBMITTED", dealer_headers,
            controller_model_id=ctx["controller"]["id"],
            install_window_start="2027-05-01", install_window_end="2027-06-01",
        )
    )
    assert submitted["status"] == "DESIGN_SUBMITTED", (
        "half-open adjacency at 2027-05-01 is allowed"
    )


def test_irrigation_approve_stale_controller_reference_rejected(api, corporate_admin_headers):
    """PRD §3.9: "The course then decides: the `CourseManager` of the project
    course approves the design, moving the project to `APPROVED`, provided the
    pinned controller model is still `CATALOG_ACTIVE` — if catalog aging has
    discontinued it since submission, approval is rejected with
    `ERR_STALE_REFERENCE` (HTTP 409)."
    PRD §3.2: "Catalog aging is enforced by the season rollover: a model whose
    age strictly exceeds 240 months — a twenty-year sales window — is moved to
    `DISCONTINUED`, its terminal state."

    Design: Corner/validations/irrigation_approve_stale_controller_reference_rejected
    """
    ctx = setup_irrigation_project()
    submitted = submit_design(ctx["project"], ctx["controller"])
    assert submitted["status"] == "DESIGN_SUBMITTED"
    # Controller model was published at the 2026-09-01 startup clock; at
    # 2046-10-01 its age is 241 months, strictly beyond the 240-month window.
    advance_clock("2046-10-01T00:00:00Z")
    run_rollover()
    resp = api.transition_irrigation_project(
        ctx["project"]["id"], "APPROVED",
        make_course_manager_headers(ctx["course"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REFERENCE.value)
    after = validate_success(
        api.get_irrigation_project(ctx["project"]["id"], corporate_admin_headers)
    )
    assert after["status"] == "DESIGN_SUBMITTED", (
        "the rejected approval leaves the project in DESIGN_SUBMITTED"
    )
