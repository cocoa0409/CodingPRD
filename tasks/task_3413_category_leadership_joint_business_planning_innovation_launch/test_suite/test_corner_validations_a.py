"""Corner queue — validation pipeline probes: authentication, pipeline
priority, the data-governance boundary, and the numeric caps on plan targets,
event discount depth, and activation fund parameters.

Each test translates one non-stub corner-design `validations` instance and
cites the PRD sentence that pins the asserted rule.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_category_analysis,
    create_activate_payload,
    create_analysis_payload,
    create_category,
    create_event_payload,
    create_plan,
    create_plan_payload,
    create_retailer,
    create_retailer_payload,
    get_plan,
    make_headers,
    setup_accepted_plan,
    setup_proposed_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plan_create_without_auth_headers_rejected(api):
    """PRD §2.1: "All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names their operational capacity."
    PRD §2.1: "A request missing either header, or carrying a role name outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A plan-create sent with neither header fails authentication (401) before
    any other check can run — the body identifiers are never even resolved.

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    payload = create_plan_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID)
    validate_error(api.create_plan(payload, None), ApiErrorId.ERR_UNAUTHENTICATED)


def test_unrecognized_role_name_rejected_as_unauthenticated(api):
    """PRD §2.1: "The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `ManufacturerPlanner`, `RetailerBuyer`, `CategoryAdvisor`, `SupplyChainPlanner`, and `FinanceAnalyst`."
    PRD §2.1: "A request missing either header, or carrying a role name outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    `X-User-Role: SuperUser` is an authentication failure (401
    ERR_UNAUTHENTICATED), not an authorization failure (403).

    Design: Corner/validations/unknown_role_returns_401
    """
    validate_error(
        api.create_retailer(
            create_retailer_payload(), make_headers("test-superuser-1", "SuperUser")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )


def test_negotiate_shape_violation_masks_missing_plan(api, manufacturer_planner_headers):
    """PRD §2.9: "The server evaluates checks in a fixed priority order and reports the first failure it encounters; a lower-priority problem is masked until every higher-priority problem is resolved."
    PRD §2.9: "Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored — including the pagination `limit` range, the promotional discount-depth cap, the shelf space-change cap, the store-count range, the rule that `sku_adds` and `sku_drops` must not overlap, positive committed volumes, a positive sales target, review and event windows whose end is strictly after their start, the `YYYY-MM` accrual period format, and the requirement that a price-pack's `channel` belongs to the plan retailer's channel set. Any breach is `ERR_VALIDATION` (HTTP 400)."
    PRD §2.9: "Existence: path and body identifiers resolve left to right per §2.6, else the matching not-found error."
    PRD §3.1: "While the plan is `PROPOSED`, the `RetailerBuyer` of the plan's own retailer may counter: the call carries a new `growth_target_pct`, and on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."

    A negotiate with an empty body (missing the required `growth_target_pct`)
    against a plan id that does not exist reports the shape breach (priority
    4), not the missing plan (priority 6).

    Design: Corner/validations/negotiate_missing_field_beats_not_found
    """
    validate_error(
        api.negotiate_plan(NON_EXISTENT_UUID, {}, manufacturer_planner_headers),
        ApiErrorId.ERR_VALIDATION,
    )


def test_competitor_data_rejected_under_manufacturer_only_scope(
    api, category_advisor_headers
):
    """PRD §3.3: "The system's data-governance boundary sits exactly here: an analysis that incorporates competitor data is only lawful when the plan's category carries an `advisory_scope` of `FULL_CATEGORY`; submitting one with `includes_competitor_data` set to true against a `MANUFACTURER_ONLY` category is rejected with `ERR_GOVERNANCE_BOUNDARY` (HTTP 422)."

    The same analysis body is rejected under a MANUFACTURER_ONLY category and
    accepted (201) under a FULL_CATEGORY category.

    Design: Corner/validations/governance_boundary_competitor_data_rejected
    """
    retailer = create_retailer()
    restricted = create_category(name="Laundry Care", advisory_scope="MANUFACTURER_ONLY")
    full = create_category(name="Paper Care", advisory_scope="FULL_CATEGORY")
    plan_restricted = create_plan(retailer["id"], restricted["id"])
    plan_full = create_plan(retailer["id"], full["id"])

    validate_error(
        api.create_category_analysis(
            plan_restricted["id"],
            create_analysis_payload(includes_competitor_data=True),
            category_advisor_headers,
        ),
        ApiErrorId.ERR_GOVERNANCE_BOUNDARY,
    )

    created = validate_success(
        api.create_category_analysis(
            plan_full["id"],
            create_analysis_payload(includes_competitor_data=True),
            category_advisor_headers,
        ),
        201,
    )
    assert_category_analysis(created)
    assert created["includes_competitor_data"] is True, (
        "the accepted analysis must record includes_competitor_data as true"
    )


def test_growth_target_above_inclusive_max_rejected(api, manufacturer_planner_headers):
    """PRD §3.1: "The growth target may range from -20 percent to 50 percent, both bounds inclusive, and the same bound is re-checked on every later negotiation move, with `ERR_GROWTH_TARGET_OUT_OF_RANGE` greeting any breach."

    51 is one past the inclusive 50 ceiling, so plan creation fails with the
    named range error (400).

    Design: Corner/validations/growth_target_above_range_returns_400
    """
    retailer = create_retailer()
    category = create_category()
    validate_error(
        api.create_plan(
            create_plan_payload(
                retailer["id"], category["id"], growth_target_pct=51
            ),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_GROWTH_TARGET_OUT_OF_RANGE,
    )


def test_discount_depth_above_cap_rejected(api, manufacturer_planner_headers):
    """PRD §3.2: "Each **PromotionalEvent** is created under its plan with a `name`, an `event_type` drawn from `FEATURE`, `DISPLAY`, `PRICE_REDUCTION`, and `IN_STORE_DEMO`, a `start_date` taken at midnight UTC, an `end_date` that must be strictly after the start, and a `discount_depth_pct` greater than 0 and at most 40 — the ceiling on how deep any event may discount."
    PRD §2.9: "Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored — including the pagination `limit` range, the promotional discount-depth cap, the shelf space-change cap, the store-count range, the rule that `sku_adds` and `sku_drops` must not overlap, positive committed volumes, a positive sales target, review and event windows whose end is strictly after their start, the `YYYY-MM` accrual period format, and the requirement that a price-pack's `channel` belongs to the plan retailer's channel set. Any breach is `ERR_VALIDATION` (HTTP 400)."

    A `discount_depth_pct` of 41 breaches the 40-percent cap — a body-shape
    violation (400) even though the plan is alive and pencilable.

    Design: Corner/validations/discount_depth_above_max_returns_400
    """
    scenario = setup_proposed_plan()
    validate_error(
        api.create_event(
            scenario["plan"]["id"],
            create_event_payload(discount_depth_pct=41),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_VALIDATION,
    )


def test_accrual_rate_above_max_rejected_at_activation(api, manufacturer_planner_headers):
    """PRD §3.1: "A `ManufacturerPlanner` activates an `ACCEPTED` plan by supplying the fund parameters `accrual_rate_pct` — the percent of invoiced sales that will accrue into the fund, which must be greater than 0 and at most 5 — and `edlp_split_pct`, the percent of each period credit routed to everyday-price support, an integer from 0 to 80 inclusive."
    PRD §2.9: "Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored — including the pagination `limit` range, the promotional discount-depth cap, the shelf space-change cap, the store-count range, the rule that `sku_adds` and `sku_drops` must not overlap, positive committed volumes, a positive sales target, review and event windows whose end is strictly after their start, the `YYYY-MM` accrual period format, and the requirement that a price-pack's `channel` belongs to the plan retailer's channel set. Any breach is `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "On success the server creates the plan's one and only **TradeFund** — stamped with the plan's id, the locked `accrual_rate_pct` and `edlp_split_pct`, and every computed balance at zero — snapshots the negotiated target into the plan's `committed_growth_pct`, stamps `activated_at` from the logical clock (both fields null until this moment), moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`."

    `accrual_rate_pct` 6 exceeds the at-most-5 bound: the activation is a
    body-shape breach (400) and the plan stays ACCEPTED.

    Design: Corner/validations/accrual_rate_above_max_returns_400
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.activate_plan(
            plan_id,
            create_activate_payload(accrual_rate_pct=6),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_VALIDATION,
    )

    reloaded = get_plan(plan_id)
    assert reloaded["status"] == "ACCEPTED", (
        f"a rejected activation must not move the plan, got {reloaded['status']}"
    )


def test_edlp_split_above_max_starves_event_bucket(api, manufacturer_planner_headers):
    """PRD §3.1: "The split floor protects the event program: because the event bucket must receive at least 20 percent of every period credit, an `edlp_split_pct` above 80 is rejected with `ERR_EVENT_SPLIT_TOO_LOW` (HTTP 422)."
    PRD §3.1: "On success the server creates the plan's one and only **TradeFund** — stamped with the plan's id, the locked `accrual_rate_pct` and `edlp_split_pct`, and every computed balance at zero — snapshots the negotiated target into the plan's `committed_growth_pct`, stamps `activated_at` from the logical clock (both fields null until this moment), moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`."

    `edlp_split_pct` 85 would leave the event bucket 15 percent of every period
    credit — below the 20-percent floor — so activation fails (422) and no fund
    is created.

    Design: Corner/validations/event_split_below_min_returns_422
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.activate_plan(
            plan_id,
            create_activate_payload(edlp_split_pct=85),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_EVENT_SPLIT_TOO_LOW,
    )

    funds, meta = validate_paginated(
        api.list_funds(manufacturer_planner_headers, params={"plan_id": plan_id})
    )
    assert funds == [], f"a rejected activation must create no fund, got {funds!r}"
    assert meta["total_count"] == 0
