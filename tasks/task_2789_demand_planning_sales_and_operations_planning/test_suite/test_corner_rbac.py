"""Breadth over role membership: the judgement calls each role is denied even on rows
it created, the verbs shared by several roles and refused to their neighbours, and the
customer-backed identity that turns one read endpoint into two different answers.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    adjustment_review_payload,
    capacity_block_payload,
    consensus_adjustment_payload,
    demand_forecast_payload,
    forecast_transition_payload,
    scenario_select_payload,
    supply_plan_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    EXEC,
    LEAD,
    PLANNER,
    SUPPLY,
    advance_cycle_to,
    build_supply_plan,
    create_adjustment,
    create_capacity_block,
    create_capacity_scenario,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    evaluate_scenario,
    post_accuracy_record,
    read_adjustment,
    read_cycle,
    read_forecast,
    read_promotion,
    transition_cycle,
    transition_forecast,
)
from test_helpers.test_users import make_demand_planner_headers, make_customer_rep_headers


def test_no_demand_planner_may_review_an_adjustment_not_even_a_colleagues():
    """The denial is drawn on the role rather than on the identity, so the proposer and
    an uninvolved second planner are refused with the same code, and only the review
    lead moves the row and the line's consensus.

    PRD: "A `DemandPlanner` may never review or endorse an adjustment, including one it
    proposed itself."

    Design: Corner/rbac/demand_planner_cannot_review_its_own_adjustment
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-RBAC-REVIEW", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    adjustment = create_adjustment(
        forecast["id"], forecast["version"], "SALES_INTELLIGENCE", 100
    )
    assert adjustment["status"] == "PROPOSED"

    own = validate_error(
        api_client.review_consensus_adjustment(
            adjustment["id"], adjustment_review_payload("ENDORSE"), PLANNER
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert own["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    colleague = validate_error(
        api_client.review_consensus_adjustment(
            adjustment["id"],
            adjustment_review_payload("ENDORSE"),
            make_demand_planner_headers("planner-9"),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert colleague["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    still_open = read_adjustment(adjustment["id"])
    assert still_open["status"] == "PROPOSED"
    assert still_open["reviewed_by_user_id"] is None

    endorsed = validate_success(
        api_client.review_consensus_adjustment(
            adjustment["id"], adjustment_review_payload("ENDORSE"), LEAD
        ),
        200,
    )
    assert endorsed["status"] == "ENDORSED"
    assert endorsed["reviewed_by_user_id"] == "lead-1"

    moved = read_forecast(forecast["id"])
    assert moved["consensus_units"] == 1100
    assert moved["endorsed_adjustment_count"] == 1


def test_the_supply_planner_that_drafted_and_evaluated_may_not_select():
    """The author is turned away by the membership list long before any duties check,
    and the executive's selection with the very same version token proves the token was
    current and the refusal purely about the role.

    PRD: "A `SupplyPlanner` may neither select a scenario nor publish a cycle."

    Design: Corner/rbac/supply_planner_cannot_select_a_scenario_it_authored
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-RBAC-SELECT", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")

    scenario = create_capacity_scenario(cycle["id"], item["id"], 5, name="Buy 5 hours")
    assert scenario["created_by_user_id"] == "supply-1"
    evaluated = evaluate_scenario(scenario["id"])
    assert evaluated["net_gap_closure_cents"] == 287800

    at_executive = transition_cycle(cycle["id"], "EXECUTIVE_REVIEW")
    token = at_executive["version"]

    refused = validate_error(
        api_client.select_scenario(
            scenario["id"], scenario_select_payload(token), SUPPLY
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    assert refused["error_id"] != ApiErrorId.ERR_STALE_CYCLE_VERSION.value

    before = read_cycle(cycle["id"], EXEC)
    assert before["selected_closure_cents"] == 0

    selected = validate_success(
        api_client.select_scenario(scenario["id"], scenario_select_payload(token), EXEC),
        200,
    )
    assert selected["status"] == "SELECTED"
    assert selected["selected_by_user_id"] == "exec-1"

    after = read_cycle(cycle["id"], EXEC)
    assert after["selected_closure_cents"] == 287800
    assert after["residual_gap_cents"] == 812200


def test_the_executive_cannot_build_a_plan_in_the_phase_that_exists_for_plans():
    """Everything about the request is right except the role — the cycle is squarely in
    supply review — so the refusal is the plain role denial and it leaves nothing behind
    for the planner's later create to collide with.

    PRD: "If the named role is present and valid but is not authorised for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/executive_sponsor_cannot_create_a_supply_plan_in_the_right_phase
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=14)
    cycle = create_cycle(cycle_code="CY-RBAC-PLAN", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    moved = transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    assert moved["status"] == "SUPPLY_REVIEW"
    assert read_forecast(forecast["id"])["status"] == "CONSENSUS_LOCKED"

    refused = validate_error(
        api_client.create_supply_plan(supply_plan_payload(cycle["id"], item["id"]), EXEC),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value
    assert refused["error_id"] != ApiErrorId.ERR_FORECAST_NOT_LOCKED.value

    plan = validate_success(
        api_client.create_supply_plan(
            supply_plan_payload(cycle["id"], item["id"]), SUPPLY
        ),
        201,
    )
    assert plan["constrained_units"] == 1330
    assert plan["constraint_type"] == "NONE"

    rows, meta = validate_paginated(
        api_client.list_supply_plans(SUPPLY, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == plan["id"]


def test_the_widest_role_is_shut_out_of_both_demand_review_judgements():
    """The process owner may create the promotion and open the cycle yet is refused on
    both review-room verbs, and the lead is admitted to the identical rows a moment
    later, so neither refusal was about the rows' state.

    PRD: "`DemandReviewLead` — chairs the demand review. The sole approver of trade
    promotions and the sole reviewer of consensus adjustments, able to endorse, reject,
    or request a revision."

    Design: Corner/rbac/sop_admin_cannot_approve_a_promotion_or_review_an_adjustment
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    promotion = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=10,
        cannibalization_pct=2,
    )
    cycle = create_cycle(cycle_code="CY-RBAC-ADMIN", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    adjustment = create_adjustment(
        forecast["id"], forecast["version"], "SALES_INTELLIGENCE", 100
    )

    promo_refusal = validate_error(
        api_client.approve_promotion(promotion["id"], ADMIN, {}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert promo_refusal["error_id"] != ApiErrorId.ERR_PROMOTION_NOT_APPROVABLE.value
    assert promo_refusal["error_id"] != ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value

    review_refusal = validate_error(
        api_client.review_consensus_adjustment(
            adjustment["id"], adjustment_review_payload("ENDORSE"), ADMIN
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert review_refusal["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    assert review_refusal["error_id"] != ApiErrorId.ERR_ADJUSTMENT_NOT_REVIEWABLE.value

    assert read_promotion(promotion["id"])["status"] == "DRAFT"
    assert read_forecast(forecast["id"])["consensus_units"] == 1000

    approved = validate_success(
        api_client.approve_promotion(promotion["id"], LEAD, {}), 200
    )
    assert approved["status"] == "APPROVED"

    endorsed = validate_success(
        api_client.review_consensus_adjustment(
            adjustment["id"], adjustment_review_payload("ENDORSE"), LEAD
        ),
        200,
    )
    assert endorsed["status"] == "ENDORSED"
    assert read_forecast(forecast["id"])["consensus_units"] == 1100


def test_a_customer_rep_cannot_write_even_on_its_own_customers_line():
    """Two writes about the rep's own customer are refused on the verb alone — neither
    the duplicate key nor the scope rule is ever reached — while the same identity reads
    that very line without trouble.

    PRD: "`CustomerRep` — the external representative of exactly one trade customer.
    Read-only."

    Design: Corner/rbac/customer_rep_cannot_write_forecasts_or_adjustments
    """
    family = create_family()
    item = create_item(family["id"])
    own = create_customer(customer_code="CUST-SELF", name="Self Grocery")
    cycle = create_cycle(cycle_code="CY-RBAC-REP", financial_commitment_cents=0)
    forecast = create_forecast(cycle["id"], item["id"], own["id"], level_units=1000)
    rep = make_customer_rep_headers(own["id"])

    duplicate_write = validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(
                cycle["id"], item["id"], own["id"], level_units=2000
            ),
            rep,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert duplicate_write["error_id"] != ApiErrorId.ERR_DUPLICATE_FORECAST.value

    adjustment_write = validate_error(
        api_client.create_consensus_adjustment(
            consensus_adjustment_payload(
                forecast["id"],
                forecast["version"],
                "SALES_INTELLIGENCE",
                100,
                rationale="our own read of the market",
            ),
            rep,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert adjustment_write["error_id"] != ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value
    assert adjustment_write["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_PHASE_ACTOR.value

    own_read = validate_success(api_client.get_demand_forecast(forecast["id"], rep), 200)
    assert own_read["baseline_units"] == 1000
    assert own_read["customer_id"] == own["id"]

    lines, line_meta = validate_paginated(
        api_client.list_demand_forecasts(
            ADMIN, params={"cycle_id": cycle["id"], "limit": 100}
        )
    )
    assert line_meta["total_count"] == 1
    assert len(lines) == 1

    adjustments, adjustment_meta = validate_paginated(
        api_client.list_consensus_adjustments(ADMIN, params={"limit": 100})
    )
    assert adjustment_meta["total_count"] == 0
    assert adjustments == []


def test_one_rep_identity_reads_its_own_scored_record_and_is_refused_the_neighbours():
    """The same endpoint answers twice for the same caller — a full record for the row
    that names its customer, a scope refusal for the row that names another — and the
    refusal is the scope code rather than a pretence that the row is absent.

    PRD: "On the corresponding single-resource reads, the targeted row's `customer_id`
    must be the caller's own customer, and the same error is returned otherwise."

    Design: Corner/rbac/customer_rep_reads_its_own_accuracy_record_and_is_rejected_on_a_foreign_one
    """
    family = create_family()
    item = create_item(family["id"])
    own = create_customer(customer_code="CUST-SELF", name="Self Grocery")
    other = create_customer(
        customer_code="CUST-OTHER", name="Other Club", channel="CLUB", priority_rank=4
    )
    cycle = create_cycle(cycle_code="CY-RBAC-SCOPE", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], own["id"], level_units=1000)
    create_forecast(cycle["id"], item["id"], other["id"], level_units=500)
    advance_cycle_to(cycle["id"], "PUBLISHED")

    mine = post_accuracy_record(cycle["id"], item["id"], own["id"], 900)
    assert mine["abs_error_units"] == 100
    assert float(mine["ape_pct"]) == 11.11
    assert mine["accountable_planner_user_id"] == "planner-1"

    theirs = post_accuracy_record(cycle["id"], item["id"], other["id"], 500)
    assert theirs["abs_error_units"] == 0
    assert float(theirs["ape_pct"]) == 0.00

    rep = make_customer_rep_headers(own["id"])
    readable = validate_success(api_client.get_accuracy_record(mine["id"], rep), 200)
    assert readable["id"] == mine["id"]
    assert readable["customer_id"] == own["id"]
    assert readable["forecast_units_snapshot"] == 1000
    assert readable["signed_error_units"] == 100

    refused = validate_error(
        api_client.get_accuracy_record(theirs["id"], rep),
        ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value,
        403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_ACCURACY_RECORD_NOT_FOUND.value

    lead_view = validate_success(api_client.get_accuracy_record(theirs["id"], LEAD), 200)
    assert lead_view["customer_id"] == other["id"]

    scoped, scoped_meta = validate_paginated(
        api_client.list_accuracy_records(rep, params={"customer_id": own["id"], "limit": 100})
    )
    assert scoped_meta["total_count"] == 1
    assert len(scoped) == 1
    assert scoped[0]["id"] == mine["id"]

    everything, everything_meta = validate_paginated(
        api_client.list_accuracy_records(ADMIN, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert everything_meta["total_count"] == 2
    assert len(everything) == 2


def test_three_roles_may_lock_a_forecast_line_and_the_supply_planner_may_not():
    """Four sibling lines differing only in who is asked to lock them: the three named
    drivers each carry their line to the locked status and move its counter, while the
    fourth line stays exactly where it started.

    PRD: "An `SopAdmin`, `DemandPlanner` or `DemandReviewLead` may drive a line by
    naming a `target_status`, and each such transition increments the line's `version`
    by 1."

    Design: Corner/rbac/forecast_transitions_shared_by_three_roles_and_rejected_for_supply_planner
    """
    family = create_family()
    item = create_item(family["id"])
    cycle = create_cycle(cycle_code="CY-RBAC-SHARE", financial_commitment_cents=0)

    lines = []
    for index, rank in enumerate((3, 4, 5, 6), start=1):
        customer = create_customer(
            customer_code="CUST-%d" % index,
            name="Grocer %d" % index,
            priority_rank=rank,
        )
        line = create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
        assert line["status"] == "BASELINE"
        lines.append(line)

    for line, driver in zip(lines[:3], (ADMIN, PLANNER, LEAD)):
        locked = transition_forecast(line["id"], "CONSENSUS_LOCKED", driver)
        assert locked["status"] == "CONSENSUS_LOCKED"
        assert locked["consensus_units"] == 1000
        assert locked["version"] == line["version"] + 1

    refused = validate_error(
        api_client.transition_demand_forecast(
            lines[3]["id"], forecast_transition_payload("CONSENSUS_LOCKED"), SUPPLY
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_FORECAST_TRANSITION_INVALID.value

    untouched = read_forecast(lines[3]["id"])
    assert untouched["status"] == "BASELINE"
    assert untouched["version"] == lines[3]["version"]

    rows, meta = validate_paginated(
        api_client.list_demand_forecasts(
            ADMIN,
            params={
                "cycle_id": cycle["id"],
                "status": "CONSENSUS_LOCKED",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3


def test_two_roles_may_declare_run_hours_and_the_demand_planner_may_not():
    """Both named declarers post a block and each family ends up with exactly one, while
    the third role's attempt on a window that overlaps nothing and respects the
    changeover gap is still turned away on the role alone.

    PRD: "Before a supply review can bind anything, a `SopAdmin` or `SupplyPlanner`
    declares the run hours available on a family's asset group."

    Design: Corner/rbac/capacity_block_creation_shared_by_two_roles_and_rejected_for_a_third
    """
    family_a = create_family(
        family_code="FAM-A", name="Family A", accountable_planner_user_id="planner-a"
    )
    family_b = create_family(
        family_code="FAM-B", name="Family B", accountable_planner_user_id="planner-b"
    )

    by_admin = validate_success(
        api_client.create_capacity_block(
            capacity_block_payload(
                family_a["id"],
                start_date="2026-09-01",
                end_date="2026-09-30",
                available_hours=14,
            ),
            ADMIN,
        ),
        201,
    )
    assert by_admin["family_id"] == family_a["id"]
    assert by_admin["available_hours"] == 14

    by_supply = validate_success(
        api_client.create_capacity_block(
            capacity_block_payload(
                family_b["id"],
                start_date="2026-09-01",
                end_date="2026-09-30",
                available_hours=9,
            ),
            SUPPLY,
        ),
        201,
    )
    assert by_supply["family_id"] == family_b["id"]
    assert by_supply["available_hours"] == 9

    refused = validate_error(
        api_client.create_capacity_block(
            capacity_block_payload(
                family_a["id"],
                start_date="2026-10-05",
                end_date="2026-10-20",
                available_hours=5,
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_CAPACITY_BLOCK_OVERLAP.value
    assert refused["error_id"] != ApiErrorId.ERR_FAMILY_NOT_FOUND.value

    for family, expected in ((family_a, by_admin), (family_b, by_supply)):
        rows, meta = validate_paginated(
            api_client.list_capacity_blocks(
                SUPPLY, params={"family_id": family["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == expected["id"]
