"""Corner queue — entity creation defaults, computed fields, and parent wiring.

Each test translates one corner-design `entities` instance and cites the PRD
sentence that pins the asserted rule. Creation responses are validated with
``validate_success(resp, 201)``; reads/actions with ``validate_success(resp,
200)``; rejections with ``validate_error`` against the registered status map.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_category,
    assert_category_analysis,
    assert_deduction,
    assert_innovation_launch,
    assert_launch_phase,
    assert_plan,
    assert_price_pack_decision,
    assert_retailer,
    create_analysis_payload,
    create_category,
    create_category_payload,
    create_deduction_payload,
    create_launch_payload,
    create_plan_payload,
    create_ppd_payload,
    create_retailer,
    create_retailer_payload,
    make_retailer_buyer_headers,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_retailer_create_omitting_status_defaults_active(api, platform_admin_headers):
    """PRD §3.1: "A retailer also carries a lifecycle `status` from `ACTIVE` and `SUSPENDED`, settable only at creation and defaulting to `ACTIVE`; it matters exactly once, at plan activation, where a suspended retailer blocks the transition."

    A create body without `status` persists the default `ACTIVE`.

    Design: Corner/entities/retailer_create_defaults_active
    """
    resp = api.create_retailer(
        create_retailer_payload(name="Retailer Alpha", country_code="US", channels=["MASS"]),
        platform_admin_headers,
    )
    retailer = validate_success(resp, 201)
    assert_retailer(retailer)
    assert retailer["status"] == "ACTIVE", (
        f"omitted status must default to ACTIVE, got {retailer['status']}"
    )


def test_retailer_create_explicit_suspended_persisted(api, platform_admin_headers):
    """PRD §3.1: "A retailer also carries a lifecycle `status` from `ACTIVE` and `SUSPENDED`, settable only at creation and defaulting to `ACTIVE`; it matters exactly once, at plan activation, where a suspended retailer blocks the transition."

    `status` is settable at creation: `SUSPENDED` is accepted and persisted.

    Design: Corner/entities/retailer_create_explicit_suspended_accepted
    """
    resp = api.create_retailer(
        create_retailer_payload(
            name="Retailer Beta", country_code="US", channels=["GROCERY"], status="SUSPENDED"
        ),
        platform_admin_headers,
    )
    retailer = validate_success(resp, 201)
    assert_retailer(retailer)
    assert retailer["status"] == "SUSPENDED", (
        f"creation-time SUSPENDED must persist, got {retailer['status']}"
    )


def test_category_create_omitting_scope_defaults_full_category(api, platform_admin_headers):
    """PRD §3.1: "A **Category** is created with a `name` such as "Laundry Care" and an `advisory_scope` of either `FULL_CATEGORY` or `MANUFACTURER_ONLY`, defaulting to `FULL_CATEGORY` when omitted — the data-governance switch that decides whether competitor data may enter advisory analyses (see §3.3)."

    A create body without `advisory_scope` persists `FULL_CATEGORY`.

    Design: Corner/entities/category_create_defaults_full_category_scope
    """
    resp = api.create_category(create_category_payload(name="Laundry Care"), platform_admin_headers)
    category = validate_success(resp, 201)
    assert_category(category)
    assert category["advisory_scope"] == "FULL_CATEGORY", (
        f"omitted advisory_scope must default to FULL_CATEGORY, got {category['advisory_scope']}"
    )


def test_plan_create_lands_proposed_round_one(api, manufacturer_planner_headers):
    """PRD §3.1: "A plan is born directly into `PROPOSED` with its `negotiation_round` at 1."
    PRD §3.1: "On success the server creates the plan's one and only **TradeFund** — stamped with the plan's id, the locked `accrual_rate_pct` and `edlp_split_pct`, and every computed balance at zero — snapshots the negotiated target into the plan's `committed_growth_pct`, stamps `activated_at` from the logical clock (both fields null until this moment), moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`."

    A freshly created plan is `PROPOSED` with `negotiation_round` 1, and both
    activation-owned fields are still null.

    Design: Corner/entities/plan_create_initial_computed_fields
    """
    retailer = create_retailer()
    category = create_category()
    resp = api.create_plan(
        create_plan_payload(retailer["id"], category["id"]), manufacturer_planner_headers
    )
    plan = validate_success(resp, 201)
    assert_plan(plan)
    assert plan["status"] == "PROPOSED", f"plan must be born PROPOSED, got {plan['status']}"
    assert plan["negotiation_round"] == 1, (
        f"plan must be born with negotiation_round 1, got {plan['negotiation_round']}"
    )
    assert plan["committed_growth_pct"] is None, "committed_growth_pct must be null until activation"
    assert plan["activated_at"] is None, "activated_at must be null until activation"


def test_plan_create_with_undeclared_status_field_rejected(api, manufacturer_planner_headers):
    """PRD §2.9: "Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored"
    PRD §2.9: "Any breach is `ERR_VALIDATION` (HTTP 400)."

    A client-supplied `status` in the plan create body is an undeclared field —
    rejected, not silently ignored.

    Design: Corner/entities/plan_create_extra_computed_field_rejected
    """
    retailer = create_retailer()
    category = create_category()
    payload = create_plan_payload(retailer["id"], category["id"], status="ACTIVATED")
    validate_error(
        api.create_plan(payload, manufacturer_planner_headers),
        ApiErrorId.ERR_VALIDATION,
    )


def test_plan_create_with_dangling_retailer_returns_404(api, manufacturer_planner_headers):
    """PRD §3.1: "A body naming a retailer or category that does not exist is rejected with `ERR_RETAILER_NOT_FOUND` or `ERR_CATEGORY_NOT_FOUND` respectively."
    PRD §2.6: "A `retailer_id` in a plan-creation body that does not resolve yields `ERR_RETAILER_NOT_FOUND` (HTTP 404)"

    A dangling `retailer_id` is a 404 `ERR_RETAILER_NOT_FOUND`, not a 400.

    Design: Corner/entities/plan_create_with_missing_retailer_returns_404
    """
    category = create_category()
    validate_error(
        api.create_plan(
            create_plan_payload(NON_EXISTENT_UUID, category["id"]),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_RETAILER_NOT_FOUND,
    )


def test_launch_create_autocreates_four_ordered_pending_phases(api, manufacturer_planner_headers):
    """PRD §3.5: "Creation builds the launch's execution skeleton automatically: exactly four **LaunchPhase** children appear, each stamped with the owning launch's id as its `launch_id`, carrying `phase_index` 1 through 4 and, by index, the `phase_type` values `CAPACITY_BUILD`, `DISTRIBUTION_BUILD`, `TRADE_SPEND`, and `SUSTAIN`."
    PRD §3.5: "All four are born `PENDING` with `distribution_target_pct`, `capacity_cases`, and `trade_spend_cents` all at 0."
    PRD §3.5: "The launch itself is born `PLANNING`, its `budget_remaining_cents` initialized to the full `total_trade_budget_cents`, both distribution projections at 0, and `launched_at` null."
    PRD §3.5: "The phase list always reads in `phase_index` ascending order."

    Design: Corner/entities/launch_create_autocreates_four_phases
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    resp = api.create_launch(
        plan_id,
        create_launch_payload(
            launch_date="2027-03-01T00:00:00Z", total_trade_budget_cents=500000
        ),
        manufacturer_planner_headers,
    )
    launch = validate_success(resp, 201)
    assert_innovation_launch(launch)
    assert launch["status"] == "PLANNING", f"launch must be born PLANNING, got {launch['status']}"
    assert launch["budget_remaining_cents"] == 500000, (
        f"budget_remaining_cents must start at the full total, got {launch['budget_remaining_cents']}"
    )

    phases, meta = validate_paginated(
        api.list_launch_phases(launch["id"], manufacturer_planner_headers)
    )
    assert len(phases) == 4, f"exactly four phases must appear, got {len(phases)}"
    assert meta["total_count"] == 4
    assert [p["phase_index"] for p in phases] == [1, 2, 3, 4], (
        "the phase list must read in phase_index ascending order"
    )
    assert [p["phase_type"] for p in phases] == [
        "CAPACITY_BUILD",
        "DISTRIBUTION_BUILD",
        "TRADE_SPEND",
        "SUSTAIN",
    ], "phase_type must follow phase_index 1..4"
    for phase in phases:
        assert_launch_phase(phase)
        assert phase["launch_id"] == launch["id"]
        assert phase["status"] == "PENDING", f"phase must be born PENDING, got {phase['status']}"
        assert phase["distribution_target_pct"] == 0
        assert phase["capacity_cases"] == 0
        assert phase["trade_spend_cents"] == 0


def test_price_per_unit_rounds_up_to_next_cent(api, manufacturer_planner_headers):
    """PRD §3.8: "Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures."

    601/6 rounds UP to 101; an exact 600/6 stays 100 — no spurious bump.

    Design: Corner/entities/ppd_price_per_unit_ceil_rounding
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    resp_a = api.create_price_pack_decision(
        plan_id,
        create_ppd_payload(
            channel="MASS", pack_code="TB-A", unit_count=6, list_price_cents=601
        ),
        manufacturer_planner_headers,
    )
    ppd_a = validate_success(resp_a, 201)
    assert_price_pack_decision(ppd_a)
    assert ppd_a["price_per_unit_cents"] == 101, (
        f"ceil(601/6) must be 101, got {ppd_a['price_per_unit_cents']}"
    )

    resp_b = api.create_price_pack_decision(
        plan_id,
        create_ppd_payload(
            channel="GROCERY", pack_code="TB-B", unit_count=6, list_price_cents=600
        ),
        manufacturer_planner_headers,
    )
    ppd_b = validate_success(resp_b, 201)
    assert_price_pack_decision(ppd_b)
    assert ppd_b["price_per_unit_cents"] == 100, (
        f"exact 600/6 must stay 100, got {ppd_b['price_per_unit_cents']}"
    )


def test_deduction_create_born_received_with_zeroed_flags(api, finance_analyst_headers):
    """PRD §3.6: "A claim is born `RECEIVED` with `settled_amount_cents` null, `short_paid` false, and `absorbed_by_manufacturer` false, and the fund's deduction list can be browsed filtered by `status` or `bucket`."

    Design: Corner/entities/deduction_create_defaults
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]
    resp = api.create_deduction(
        fund_id,
        create_deduction_payload("CL-1", bucket="EDLP", amount_cents=2500),
        make_retailer_buyer_headers(scenario["retailer"]["id"]),
    )
    deduction = validate_success(resp, 201)
    assert_deduction(deduction)
    assert deduction["status"] == "RECEIVED", (
        f"claim must be born RECEIVED, got {deduction['status']}"
    )
    assert deduction["short_paid"] is False
    assert deduction["absorbed_by_manufacturer"] is False
    assert deduction["settled_amount_cents"] is None


def test_analysis_competitor_share_derived_on_create(api, category_advisor_headers):
    """PRD §3.3: "Every analysis carries a computed `competitor_share_pct`, derived as 100 minus the `manufacturer_share_pct`, so the manufacturer's view of the category always accounts for the full hundred points."
    PRD §3.3: "An analysis is born `SUBMITTED` and waits on the retailer."

    `manufacturer_share_pct` 62.5 derives `competitor_share_pct` 37.5 at
    creation, and the record lands `SUBMITTED`.

    Design: Corner/entities/analysis_competitor_share_computed
    """
    scenario = setup_proposed_plan()
    resp = api.create_category_analysis(
        scenario["plan"]["id"],
        create_analysis_payload(manufacturer_share_pct=62.5, includes_competitor_data=True),
        category_advisor_headers,
    )
    analysis = validate_success(resp, 201)
    assert_category_analysis(analysis)
    assert analysis["competitor_share_pct"] == pytest.approx(37.5, abs=1e-6), (
        f"100 - 62.5 must derive 37.5, got {analysis['competitor_share_pct']}"
    )
    assert analysis["status"] == "SUBMITTED", (
        f"analysis must be born SUBMITTED, got {analysis['status']}"
    )
