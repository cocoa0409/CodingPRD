"""Breadth over the rejection ladder: pairs of simultaneously violated rules where
only the earlier check may surface, from the header pair at the very top down to the
segregation, freeze and scope gates in the middle.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    capacity_investment_scenario_payload,
    consensus_adjustment_payload,
    cycle_transition_payload,
    demand_forecast_payload,
    scenario_select_payload,
    supply_plan_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    PLANNER,
    SUPPLY,
    advance_cycle_to,
    build_supply_plan,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    evaluate_scenario,
    ration_plan,
    read_cycle,
    read_forecast,
    transition_cycle,
)
from test_helpers.test_users import make_customer_rep_headers, make_executive_sponsor_headers

UNKNOWN_CYCLE_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_ITEM_ID = "00000000-0000-4000-8000-0000000000fe"
UNKNOWN_PROMOTION_ID = "00000000-0000-4000-8000-0000000000aa"


def test_a_missing_user_id_header_outranks_the_role_check_which_outranks_existence():
    """Three checks are broken at once — no identifier, a role with no business at
    this endpoint, and a body naming rows that do not exist — and the ladder reports
    them strictly top down, never reaching the 404.

    PRD: "`X-User-Role` and `X-User-ID` are both present, non-empty, and the role is
    one of the six declared in §2.1 — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/supply_plan_create_missing_x_user_id_header_unauthenticated_beats_unauthorized
    """
    customer = create_customer()
    payload = supply_plan_payload(UNKNOWN_CYCLE_ID, UNKNOWN_ITEM_ID)

    headerless = validate_error(
        api_client.create_supply_plan(payload, {"X-User-Role": "CustomerRep"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    assert headerless["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
    assert headerless["error_id"] != ApiErrorId.ERR_CYCLE_NOT_FOUND.value

    identified = validate_error(
        api_client.create_supply_plan(payload, make_customer_rep_headers(customer["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert identified["error_id"] != ApiErrorId.ERR_CYCLE_NOT_FOUND.value
    assert identified["error_id"] != ApiErrorId.ERR_ITEM_NOT_FOUND.value

    listing = api_client.list_supply_plans(SUPPLY, params={"limit": 100})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []


def test_a_malformed_target_status_outranks_the_unknown_cycle_in_the_path():
    """The body's enum is validated before the path identifier is resolved, so the
    same unknown cycle yields a 400 with a bad status and a 404 with a good one, and
    neither attempt is ever reported as a transition conflict.

    PRD: "Checks are evaluated in the following order, and the first violation
    encountered ends the request"

    Design: Corner/validations/transition_invalid_enum_beats_unknown_cycle_returns_invalid_request
    """
    bad_enum = validate_error(
        api_client.transition_planning_cycle(
            UNKNOWN_CYCLE_ID, cycle_transition_payload("NOT_A_STATUS"), ADMIN
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    assert bad_enum["error_id"] != ApiErrorId.ERR_CYCLE_NOT_FOUND.value
    assert bad_enum["error_id"] != ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value

    good_enum = validate_error(
        api_client.transition_planning_cycle(
            UNKNOWN_CYCLE_ID, cycle_transition_payload("SUPPLY_REVIEW"), ADMIN
        ),
        ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        404,
    )
    assert good_enum["error_id"] != ApiErrorId.ERR_CYCLE_TRANSITION_INVALID.value

    listing = api_client.list_planning_cycles(ADMIN, params={"limit": 100})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []


def test_an_unresolvable_promotion_reference_outranks_its_approval_state():
    """Resolving the body's foreign keys comes before judging what the referenced row
    is for, so an identifier that matches nothing is a 404 while a real but unapproved
    promotion is the eligibility 422 — and neither writes an adjustment.

    PRD: "**Body reference existence.** Every foreign-key identifier in the body
    resolves, per §2.4. This applies to item creation, item lifecycle transitions,
    capacity-block creation, promotion creation, forecast creation, adjustment
    creation, supply-plan creation, scenario creation and accuracy-record creation."

    Design: Corner/validations/unknown_promotion_id_returns_promotion_not_found_before_not_approved
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-FK", financial_commitment_cents=0)
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=1000
    )
    draft = create_promotion(item["id"], customer["id"], lift_pct=10, cannibalization_pct=2)
    assert draft["status"] == "DRAFT"

    missing = validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                forecast["id"],
                forecast["version"],
                "PROMOTION",
                0,
                promotion_id=UNKNOWN_PROMOTION_ID,
                rationale="citing a promotion that does not exist",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_PROMOTION_NOT_FOUND.value,
        404,
    )
    assert missing["error_id"] != ApiErrorId.ERR_PROMOTION_NOT_APPROVED.value

    validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                forecast["id"],
                forecast["version"],
                "PROMOTION",
                0,
                promotion_id=draft["id"],
                rationale="citing a promotion that exists but is unapproved",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_PROMOTION_NOT_APPROVED.value,
        422,
    )

    listing = api_client.list_consensus_adjustments(
        PLANNER, params={"demand_forecast_id": forecast["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []

    untouched = read_forecast(forecast["id"])
    assert untouched["status"] == "BASELINE"
    assert untouched["version"] == forecast["version"]


def test_the_authors_own_stale_token_is_reported_as_segregation_not_as_staleness():
    """The author and a colleague send byte-identical stale selections and receive
    different errors, because the duties check sits above the version check; only the
    colleague with a fresh token closes the gap.

    PRD: "the acting `X-User-ID` must differ from the scenario's
    `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; a
    capacity-investment scenario's target supply plan must not have gone `STALE`
    since the scenario was evaluated, otherwise `ERR_STALE_SUPPLY_PLAN`; and the
    supplied `expected_cycle_version` must equal the cycle's current `version`,
    otherwise `ERR_STALE_CYCLE_VERSION`."

    Design: Corner/validations/segregation_of_duties_beats_stale_cycle_version
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-SOD", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    assert plan["shortfall_units"] == 430
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")

    scenario = validate_success(
        api_client.create_scenario(
            capacity_investment_scenario_payload(
                cycle["id"], item["id"], 5, name="Five extra run hours"
            ),
            EXEC,
        ),
        201,
    )
    assert scenario["created_by_user_id"] == "exec-1"
    stale_token = read_cycle(cycle["id"])["version"]

    evaluated = evaluate_scenario(scenario["id"])
    assert evaluated["incremental_units"] == 430
    assert evaluated["gross_uplift_cents"] == 430000
    assert evaluated["investment_cost_cents"] == 125000
    assert evaluated["pre_trade_closure_cents"] == 305000
    assert float(evaluated["trade_rate_pct"]) == 4.0
    assert evaluated["trade_spend_cents"] == 17200
    assert evaluated["net_gap_closure_cents"] == 287800

    transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")
    author_attempt = validate_error(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(stale_token), EXEC
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert author_attempt["error_id"] != ApiErrorId.ERR_STALE_CYCLE_VERSION.value

    colleague = make_executive_sponsor_headers("exec-2")
    validate_error(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(stale_token), colleague
        ),
        ApiErrorId.ERR_STALE_CYCLE_VERSION.value,
        412,
    )

    current_token = read_cycle(cycle["id"])["version"]
    assert current_token != stale_token
    selected = validate_success(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(current_token), colleague
        ),
        200,
    )
    assert selected["status"] == "SELECTED"
    assert selected["selected_by_user_id"] == "exec-2"

    closed = read_cycle(cycle["id"])
    assert closed["selected_closure_cents"] == 287800
    assert closed["residual_gap_cents"] == 812200
    assert closed["posture"] == "AT_RISK"


def test_the_phase_actor_check_claims_the_write_the_freeze_would_also_have_blocked():
    """A published cycle is both frozen and past every working phase, and the two
    writes split: the one the phase-actor check covers is a 403 while the one it does
    not cover falls through to the freeze.

    PRD: "Because the phase-actor check sits earlier in the rejection ladder of §2.9,
    it wins wherever both could apply."

    Design: Corner/validations/phase_actor_beats_cycle_frozen_on_supply_plan_create
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-SPLIT", financial_commitment_cents=0)
    published = advance_cycle_to(cycle["id"], "PUBLISHED")
    assert published["status"] == "PUBLISHED"
    assert published["posture"] == "FROZEN"

    plan_attempt = validate_error(
        api_client.create_supply_plan(
            supply_plan_payload(cycle["id"], item["id"]), SUPPLY
        ),
        ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value,
        403,
    )
    assert plan_attempt["error_id"] != ApiErrorId.ERR_CYCLE_FROZEN.value
    assert plan_attempt["error_id"] != ApiErrorId.ERR_FORECAST_NOT_LOCKED.value

    forecast_attempt = validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(cycle["id"], item["id"], customer["id"]), PLANNER
        ),
        ApiErrorId.ERR_CYCLE_FROZEN.value,
        409,
    )
    assert forecast_attempt["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value

    plans, plan_meta = validate_paginated(
        api_client.list_supply_plans(SUPPLY, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert plan_meta["total_count"] == 0
    assert plans == []

    lines, line_meta = validate_paginated(
        api_client.list_demand_forecasts(
            PLANNER, params={"cycle_id": cycle["id"], "limit": 100}
        )
    )
    assert line_meta["total_count"] == 0
    assert lines == []


def test_the_phase_closed_rejection_only_covers_the_write_the_actor_check_omits():
    """One phase forward, the same planner meets two different conflicts: forecast
    creation is outside the phase-actor family so it reports the closed phase, which
    also outranks the duplicate key, while adjustment creation is inside it.

    PRD: "The second rejection, `ERR_CYCLE_PHASE_CLOSED` (HTTP 409), covers the same
    family of writes plus forecast-line creation and forecast-line transitions, and
    it fires when the cycle has moved past the phase that admits the class of write
    and the acting role is nonetheless the role that owns that phase."

    Design: Corner/validations/phase_closed_fires_only_where_phase_actor_is_silent
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-CLOSED", financial_commitment_cents=0)
    forecast = create_forecast(
        cycle["id"], item["id"], customer["id"], level_units=1000
    )
    moved = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    assert moved["posture"] == "GREEN"

    locked = read_forecast(forecast["id"])
    assert locked["status"] == "CONSENSUS_LOCKED"

    duplicate = validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(cycle["id"], item["id"], customer["id"]), PLANNER
        ),
        ApiErrorId.ERR_CYCLE_PHASE_CLOSED.value,
        409,
    )
    assert duplicate["error_id"] != ApiErrorId.ERR_DUPLICATE_FORECAST.value
    assert duplicate["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value

    adjustment = validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                forecast["id"],
                locked["version"],
                "SALES_INTELLIGENCE",
                100,
                rationale="late intelligence after the phase moved on",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value,
        403,
    )
    assert adjustment["error_id"] != ApiErrorId.ERR_CYCLE_PHASE_CLOSED.value
    assert adjustment["error_id"] != ApiErrorId.ERR_STALE_FORECAST_VERSION.value

    still_locked = read_forecast(forecast["id"])
    assert still_locked["status"] == "CONSENSUS_LOCKED"
    assert still_locked["consensus_units"] == 1000

    rows, meta = validate_paginated(
        api_client.list_consensus_adjustments(
            PLANNER, params={"demand_forecast_id": forecast["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_customer_rep_must_name_its_own_customer_on_the_allocation_listing():
    """Both the omitted filter and a filter naming someone else are the same scope
    violation, and the one legal listing narrows a two-row plan to the rep's own row
    while the planner sees both.

    PRD: "On the list reads of demand forecast lines, allocations and accuracy records
    it must supply a `customer_id` filter equal to its own customer's `id`; omitting
    the filter, or supplying any other customer's `id`, is rejected with
    `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/customer_rep_listing_allocations_without_customer_id_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    own = create_customer(customer_code="CUST-SELF", name="Self Grocery", priority_rank=3)
    other = create_customer(
        customer_code="CUST-OTHER", name="Other Club", channel="CLUB", priority_rank=4
    )
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-SCOPE", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], own["id"], level_units=500)
    create_forecast(cycle["id"], item["id"], other["id"], level_units=500)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    assert plan["constraint_type"] == "CAPACITY"
    rationed = ration_plan(plan["id"])
    assert rationed["status"] == "RATIONED"

    rep = make_customer_rep_headers(own["id"])
    validate_error(
        api_client.list_allocations(rep, params={"supply_plan_id": plan["id"], "limit": 100}),
        ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api_client.list_allocations(
            rep, params={"customer_id": other["id"], "limit": 100}
        ),
        ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value,
        403,
    )

    scoped, scoped_meta = validate_paginated(
        api_client.list_allocations(rep, params={"customer_id": own["id"], "limit": 100})
    )
    assert scoped_meta["total_count"] == 1
    assert len(scoped) == 1
    assert scoped[0]["customer_id"] == own["id"]
    assert scoped[0]["requested_units"] == 500
    assert scoped[0]["allocated_units"] == 450

    everything, everything_meta = validate_paginated(
        api_client.list_allocations(SUPPLY, params={"limit": 100})
    )
    assert everything_meta["total_count"] == 2
    assert len(everything) == 2
