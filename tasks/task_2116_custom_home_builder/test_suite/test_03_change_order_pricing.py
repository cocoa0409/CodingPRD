"""Change-order pricing: markup tiers, the pinned contingency tier and the revision cycle."""

from test_helpers import (
    ApiErrorId,
    assert_change_order,
    assert_money_equals,
    assert_money_not_equals,
    create_change_order,
    price_change_order,
    read_change_order,
    read_project,
    run_revision_round,
    setup_job,
    setup_priced_change_order,
    setup_submitted_change_order,
    submit_change_order,
    validate_error,
    validate_success,
)


def test_change_order_prices_at_the_pinned_contingency_tier(api):
    """PRD §3.3: "First, a markup tier is selected from the raw `direct_cost` alone: a direct
    cost below 5,000.00 dollars earns a markup rate of 0.20; a direct cost from 5,000.00
    dollars up to but not including 25,000.00 dollars earns 0.15; and a direct cost of
    25,000.00 dollars or more earns 0.10."
    PRD §3.3: "Fourth — and this is the step implementations most often get wrong — a
    contingency tier is selected **from that pre-contingency subtotal and never from the final
    price**: a subtotal of 10,000.00 dollars or less earns a contingency rate of 0.00; a
    subtotal above 10,000.00 dollars and up to and including 50,000.00 dollars earns 0.03; and
    a subtotal strictly above 50,000.00 dollars earns 0.05."
    PRD §3.3: "There is no fixed point to solve here: the tier must not be re-derived from the
    priced result, so a change order whose subtotal lands at 48,850.00 dollars takes the 0.03
    tier even though its final price crosses 50,000.00 dollars."

    Design: Difficulty/combinatorial_formula/change_order_contingency_tier_keyed_on_presubtotal
    """
    ctx = setup_job()
    change_order = create_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    priced = validate_success(
        api.price_change_order(change_order["id"], {}, ctx["estimator_headers"]), 200
    )

    assert_change_order(priced)
    assert priced["markup_rate_applied"] == 0.10
    assert priced["contingency_rate_applied"] == 0.03
    assert_money_equals(priced["priced_amount"], 50315.50, "priced_amount")
    assert_money_not_equals(
        priced["priced_amount"],
        51292.50,
        "priced_amount (fixed-point contingency solution)",
    )


def test_pricing_stamps_the_estimator_and_moves_the_change_order_to_priced(api):
    """PRD §3.3: "Pricing is the estimator's craft, and both an `Estimator` and a
    `ProjectManager` may perform it. Pricing advances a change order `DRAFT → PRICED`, and the
    same operation also closes the negotiation loop by advancing `REVISION_REQUESTED →
    PRICED`; both edges require the parent project to be `UNDER_CONSTRUCTION`."
    PRD §3.3: "Every pricing pass stamps `priced_by_staff_id` with the acting employee's
    identifier and `priced_at` with the logical clock now."

    Design: Difficulty/combinatorial_formula/change_order_contingency_tier_keyed_on_presubtotal
    """
    ctx = setup_job()
    change_order = create_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )
    assert change_order["status"] == "DRAFT"

    priced = validate_success(
        api.price_change_order(change_order["id"], {}, ctx["estimator_headers"]), 200
    )

    assert priced["status"] == "PRICED"
    assert priced["priced_by_staff_id"] == ctx["estimator"]["id"]
    assert priced["priced_at"] is not None


def test_markup_tier_ceiling_is_inclusive_on_the_upper_tier(api):
    """PRD §3.3: "First, a markup tier is selected from the raw `direct_cost` alone: a direct
    cost below 5,000.00 dollars earns a markup rate of 0.20; a direct cost from 5,000.00
    dollars up to but not including 25,000.00 dollars earns 0.15; and a direct cost of
    25,000.00 dollars or more earns 0.10."
    PRD §3.3: "Fifth, `priced_amount` is the subtotal plus the contingency, rounded half up to
    two decimals, and the two rates that were used are recorded in `markup_rate_applied` and
    `contingency_rate_applied`."

    Design: Corner/calculations/change_order_markup_tier_boundary_at_exactly_five_thousand
    """
    ctx = setup_job()
    at_ceiling = create_change_order(
        ctx,
        origin="FIELD_CONDITION",
        scope_description="At the tier ceiling",
        direct_cost=5000.00,
        schedule_impact_days=0,
    )
    below_ceiling = create_change_order(
        ctx,
        origin="FIELD_CONDITION",
        scope_description="One cent below the tier ceiling",
        direct_cost=4999.99,
        schedule_impact_days=0,
    )

    priced_at = validate_success(
        api.price_change_order(at_ceiling["id"], {}, ctx["estimator_headers"]), 200
    )
    priced_below = validate_success(
        api.price_change_order(below_ceiling["id"], {}, ctx["estimator_headers"]), 200
    )

    assert priced_at["markup_rate_applied"] == 0.15
    assert priced_at["contingency_rate_applied"] == 0.00
    assert_money_equals(priced_at["priced_amount"], 5750.00, "priced_amount at 5000.00")

    assert priced_below["markup_rate_applied"] == 0.20
    assert_money_equals(
        priced_below["priced_amount"], 5999.99, "priced_amount at 4999.99"
    )


def test_revision_cycle_reprices_the_change_order_and_counts_the_round(api):
    """PRD §3.3: "**Requesting a revision** advances `SUBMITTED → REVISION_REQUESTED`,
    requires that `revision_count` still be strictly below 3, stores the homeowner's
    `revision_note`, and deliberately leaves `priced_amount` at its last value until the
    estimator reprices; a revision requested once the count has reached the ceiling earns
    `ERR_REVISION_LIMIT_EXCEEDED`."
    PRD §3.3: "When the pass is a repricing off the back of a client revision request, it
    additionally increments `revision_count` by one before the recomputation is filed, using
    whatever `direct_cost` and `schedule_impact_days` now stand on the record."

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_returns_to_priced
    """
    ctx = setup_job()
    submitted = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )
    assert_money_equals(submitted["priced_amount"], 50315.50, "priced_amount before revision")

    validate_success(
        api.decide_change_order(
            submitted["id"],
            {"decision": "REQUEST_REVISION", "revision_note": "Shrink the porch to 12 feet"},
            ctx["client_headers"],
        ),
        200,
    )

    repriced = validate_success(
        api.price_change_order(
            submitted["id"],
            {"direct_cost": 12000.00, "schedule_impact_days": 2},
            ctx["estimator_headers"],
        ),
        200,
    )

    assert repriced["revision_count"] == 1
    assert_money_equals(repriced["direct_cost"], 12000.00, "direct_cost")
    assert repriced["markup_rate_applied"] == 0.15
    assert repriced["contingency_rate_applied"] == 0.03
    assert_money_equals(repriced["priced_amount"], 15213.10, "priced_amount after revision")


def test_repriced_change_order_returns_to_submitted_without_touching_the_ledger(api):
    """PRD §3.3: "Submission is a `ProjectManager` action that advances a change order `PRICED
    → SUBMITTED`."
    PRD §2.6: "`approved_change_order_total` is the sum of `priced_amount` across the
    project's change orders whose status is `APPROVED`. Change orders in `DRAFT`, `PRICED`,
    `SUBMITTED`, `REVISION_REQUESTED`, `REJECTED`, or `VOIDED` contribute nothing."

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_returns_to_priced
    """
    ctx = setup_job()
    submitted = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    validate_success(
        api.decide_change_order(
            submitted["id"],
            {"decision": "REQUEST_REVISION", "revision_note": "Shrink the porch to 12 feet"},
            ctx["client_headers"],
        ),
        200,
    )
    price_change_order(ctx, submitted["id"], direct_cost=12000.00, schedule_impact_days=2)
    resubmitted = validate_success(
        api.submit_change_order(submitted["id"], ctx["pm_headers"]), 200
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["approved_change_order_total"], 0.00, "approved_change_order_total"
    )


def test_fourth_revision_request_breaches_the_revision_budget(api):
    """PRD §3.3: "**Requesting a revision** advances `SUBMITTED → REVISION_REQUESTED`,
    requires that `revision_count` still be strictly below 3, stores the homeowner's
    `revision_note`, and deliberately leaves `priced_amount` at its last value until the
    estimator reprices; a revision requested once the count has reached the ceiling earns
    `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Corner/validations/change_order_fourth_revision_request_exceeds_limit
    """
    ctx = setup_job()
    change_order = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )
    run_revision_round(ctx, change_order["id"], "Round 1", 3100.00)
    run_revision_round(ctx, change_order["id"], "Round 2", 3200.00)
    run_revision_round(ctx, change_order["id"], "Round 3", 3300.00)

    response = api.decide_change_order(
        change_order["id"],
        {"decision": "REQUEST_REVISION", "revision_note": "Round 4"},
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED, 409)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["revision_count"] == 3
    assert_money_equals(stored["direct_cost"], 3300.00, "direct_cost")
    assert_money_equals(stored["priced_amount"], 3960.00, "priced_amount")


def test_new_change_order_opens_in_draft_with_no_pricing(api):
    """PRD §3.3: "A `ProjectManager` opens a change order in `DRAFT` by naming the
    `project_id`, the `origin` — `CLIENT_REQUEST`, `FIELD_CONDITION`, or `ALLOWANCE_OVERAGE` —
    a narrative `scope_description`, the `direct_cost` of the changed scope before any markup
    (at least zero, at most two decimals), and optionally the `schedule_impact_days` count of
    whole calendar days the change pushes the schedule, which defaults to zero and may not be
    negative."
    PRD §3.3: "A fresh change order carries `revision_count` of zero and null
    `markup_rate_applied`, `contingency_rate_applied`, `priced_amount`, `priced_by_staff_id`,
    `submitted_by_staff_id`, `revision_note`, `void_reason`, `priced_at`, `submitted_at`,
    `client_response_due_at`, and `decided_at`."

    Design: Corner/state_machines/new_change_order_starts_in_draft_initial_state
    """
    ctx = setup_job()

    response = api.create_change_order(
        {
            "project_id": ctx["project"]["id"],
            "origin": "FIELD_CONDITION",
            "scope_description": "Rock encountered at footing",
            "direct_cost": 3000.00,
        },
        ctx["pm_headers"],
    )
    change_order = validate_success(response, 201)

    assert_change_order(change_order)
    assert change_order["status"] == "DRAFT"
    assert change_order["priced_amount"] is None
    assert change_order["revision_count"] == 0
    assert change_order["priced_by_staff_id"] is None
    assert change_order["schedule_impact_days"] == 0

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["approved_change_order_total"], 0.00, "approved_change_order_total"
    )


def test_submitting_an_unpriced_change_order_is_refused(api):
    """PRD §3.3: "Submission is a `ProjectManager` action that advances a change order `PRICED
    → SUBMITTED`."
    PRD §2.10: "**Target state admits the transition.** The target row must be in a state from
    which the requested transition is declared, or the family-specific conflict code —
    `ERR_PROJECT_INVALID_STATE`, `ERR_ALLOWANCE_INVALID_STATE`, `ERR_SELECTION_NOT_PENDING`,
    `ERR_CHANGE_ORDER_INVALID_STATE`, `ERR_TASK_INVALID_STATE`, `ERR_COST_ENTRY_INVALID_STATE`,
    `ERR_DRAW_NOT_IN_DRAFT`, `ERR_DRAW_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`,
    `ERR_DEFECT_INVALID_STATE`, or `ERR_PHOTO_ALREADY_PUBLISHED` — each with HTTP 409."

    Design: Corner/state_machines/submit_change_order_still_in_draft_is_rejected
    """
    ctx = setup_job()
    change_order = create_change_order(
        ctx,
        origin="FIELD_CONDITION",
        scope_description="Rock encountered at footing",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )

    response = api.submit_change_order(change_order["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE, 409)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "DRAFT"
    assert stored["submitted_by_staff_id"] is None


def test_second_client_decision_on_a_rejected_change_order_is_refused(api):
    """PRD §3.3: "The homeowner then rules on the document with a `decision` that can go three
    ways, and only from `SUBMITTED`; a decision aimed at a change order in any other status
    earns `ERR_CHANGE_ORDER_INVALID_STATE`."
    PRD §3.3: "**Rejection** advances `SUBMITTED → REJECTED`, stamps `decided_at`, and leaves
    `approved_change_order_total` and `contract_sum_current` exactly where they were;
    `REJECTED` is terminal."

    Design: Corner/state_machines/client_decision_on_already_rejected_change_order_is_rejected
    """
    ctx = setup_job()
    change_order = setup_priced_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a wine room",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )
    submit_change_order(ctx, change_order["id"])
    validate_success(
        api.decide_change_order(
            change_order["id"], {"decision": "REJECT"}, ctx["client_headers"]
        ),
        200,
    )

    response = api.decide_change_order(
        change_order["id"], {"decision": "APPROVE"}, ctx["client_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE, 409)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "REJECTED"
    assert_money_equals(stored["priced_amount"], 3600.00, "priced_amount")

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["approved_change_order_total"], 0.00, "approved_change_order_total"
    )
    assert_money_equals(project["contract_sum_current"], 900000.00, "contract_sum_current")
