"""Regulatory approval, rate-base admission, and remand/refile tests."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_regulatory_application,
    setup_target_in_municipal_review, setup_target_in_regulatory_review,
    setup_hearing_held, pass_council_vote, schedule_event, record_outcome,
    set_clock, file_application, decide_application,
    current_target_version,
    make_headers,
    create_capital_item_payload,
    create_target, create_assessment_with_items, submit_assessment,
    accept_assessment, open_valuation_case, submit_entry, finalize_case,
)


def _setup_regulatory_with_estimates(entry_value_cents=100000000):
    """Regulatory review with the two pinned items so filing estimate is 172502."""
    items = [
        create_capital_item_payload(category="DISTRIBUTION", description="d",
                                    cost_low_cents=100000, cost_high_cents=100001),
        create_capital_item_payload(category="TREATMENT", horizon="SHORT_TERM",
                                    description="d",
                                    cost_low_cents=50000, cost_high_cents=50002),
    ]
    target = create_target(customer_count=100)
    assessment, _ = create_assessment_with_items(target["id"], items)
    submit_assessment(assessment["id"])
    accept_assessment(assessment["id"])
    case = open_valuation_case(target["id"])
    entry = submit_entry(case["id"], value_cents=entry_value_cents)
    finalize_case(case["id"], entry["id"])
    setup_hearing_held(target["id"])
    pass_council_vote(target["id"])
    return {"target": target, "assessment": assessment, "case": case, "entry": entry}


def test_rate_base_as_paid_vs_depreciated_diverge(api):
    """PRD §3.5: "Under the `AS_PAID` method, the commission admits up to fair
    value plus that acquisition premium: the as-paid admission is the purchase
    price or the selected value plus the premium cap, whichever is smaller.
    Under the `DEPRECIATED_ORIGINAL_COST` method, the cap is instead the
    seller's net book cost: the base admission is the purchase price or
    `original_cost_less_depreciation_cents`, whichever is smaller."

    Design: Difficulty/dual_variant_calc/rate_base_as_paid_vs_depreciated_diverge
    """
    ctx1 = _setup_regulatory_with_estimates()
    app1 = file_application(ctx1["target"]["id"], purchase_price_cents=105000000,
                            rate_base_method="AS_PAID")
    decided1 = decide_application(app1["id"], "APPROVED")
    assert decided1["status"] == "APPROVED"
    assert decided1["admitted_rate_base_cents"] == 105000000
    assert decided1["disallowed_premium_cents"] == 0

    ctx2 = _setup_regulatory_with_estimates()
    app2 = file_application(ctx2["target"]["id"], purchase_price_cents=105000000,
                            rate_base_method="DEPRECIATED_ORIGINAL_COST",
                            ocld_cents=90000000)
    decided2 = decide_application(app2["id"], "APPROVED")
    assert decided2["status"] == "APPROVED"
    assert decided2["admitted_rate_base_cents"] == 90000000
    assert decided2["disallowed_premium_cents"] == 15000000


def test_rate_base_as_paid_vs_depreciated_diverge_ocld_above_price(api):
    """PRD §3.5: "Under the `DEPRECIATED_ORIGINAL_COST` method, the cap is
    instead the seller's net book cost: the base admission is the purchase price
    or `original_cost_less_depreciation_cents`, whichever is smaller."

    Design: Difficulty/dual_variant_calc/rate_base_as_paid_vs_depreciated_diverge
    """
    ctx = _setup_regulatory_with_estimates()
    # OCLD (110M) above price (105M): price binds; disallowed is zero.
    app = file_application(ctx["target"]["id"], purchase_price_cents=105000000,
                           rate_base_method="DEPRECIATED_ORIGINAL_COST",
                           ocld_cents=110000000)
    decided = decide_application(app["id"], "APPROVED")
    assert decided["admitted_rate_base_cents"] == 105000000
    assert decided["disallowed_premium_cents"] == 0


def test_rate_base_nested_min_branch_selection(api):
    """PRD §3.5: "The premium cap is ten percent of the target's
    `selected_value_cents`, rounded half-up to a whole cent." and "The admitted
    rate base is then the base admission capped once more against the
    capital-need ceiling: the target's `filing_estimate_cents` plus the
    `selected_value_cents` plus the premium cap, with the admitted amount the
    smaller of the two."

    Design: Difficulty/combinatorial_formula/rate_base_nested_min_branch_selection
    """
    ctx = _setup_regulatory_with_estimates()
    app = file_application(ctx["target"]["id"], purchase_price_cents=115000000,
                           rate_base_method="AS_PAID")
    decided = decide_application(app["id"], "APPROVED")
    assert decided["status"] == "APPROVED"
    assert decided["admitted_rate_base_cents"] == 110000000
    assert decided["disallowed_premium_cents"] == 5000000
    fresh = get_success_data(api.get_target(ctx["target"]["id"],
                                            TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "CLOSING"
    assert fresh["admitted_rate_base_cents"] == 110000000
    assert fresh["disallowed_premium_cents"] == 5000000


def test_rate_base_nested_min_branch_selection_ceiling_binds(api):
    """PRD §3.5: "The result is recorded as the application's
    `admitted_rate_base_cents`, and the excess of price over admission — the
    purchase price minus the admitted rate base — is recorded as
    `disallowed_premium_cents`."

    Design: Difficulty/combinatorial_formula/rate_base_nested_min_branch_selection
    """
    # selected_value = 5000000 -> premium cap 500000; ceiling = filing + 5.5M.
    ctx = setup_target_in_regulatory_review(purchase_price_cents=8000000,
                                            rate_base_method="AS_PAID",
                                            entry_value_cents=5000000)
    decided = decide_application(ctx["application"]["id"], "APPROVED")
    assert decided["admitted_rate_base_cents"] == 5500000
    assert decided["disallowed_premium_cents"] == 2500000


def test_regulatory_application_remand_refile_cycle(api):
    """PRD §3.5: "The `RegulatoryOfficer` may refile a `REMANDED` application,
    which returns it to `FILED`, bumps `filing_round` by one, and may replace
    the `purchase_price_cents` and `rate_base_method`".

    Design: Difficulty/non_linear_state_machine/regulatory_application_remand_refile_cycle
    """
    ctx = setup_target_in_regulatory_review(purchase_price_cents=105000000,
                                            entry_value_cents=100000000,
                                            customer_count=100)
    decide_application(ctx["application"]["id"], "REMANDED")
    version = current_target_version(ctx["target"]["id"])
    resp = api.refile_regulatory_application(
        ctx["application"]["id"],
        {"expected_target_version": version, "purchase_price_cents": 100000000,
         "rate_base_method": "AS_PAID"},
        TEST_USERS["reg_officer_headers"])
    refiled = validate_success(resp, 200)
    assert refiled["status"] == "FILED"
    assert refiled["filing_round"] == 2
    assert refiled["purchase_price_cents"] == 100000000
    fresh = get_success_data(api.get_target(ctx["target"]["id"],
                                            TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REGULATORY_REVIEW"


def test_regulatory_application_remand_refile_cycle_then_approve(api):
    """PRD §3.5: "**`REMANDED`.** The application returns to the utility for
    rework, keeping the target in `REGULATORY_REVIEW`."

    Design: Difficulty/non_linear_state_machine/regulatory_application_remand_refile_cycle
    """
    ctx = setup_target_in_regulatory_review(purchase_price_cents=4000000,
                                            entry_value_cents=5000000,
                                            customer_count=100)
    remanded = decide_application(ctx["application"]["id"], "REMANDED")
    assert remanded["status"] == "REMANDED"
    fresh = get_success_data(api.get_target(ctx["target"]["id"],
                                            TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REGULATORY_REVIEW"

    version = current_target_version(ctx["target"]["id"])
    refiled = get_success_data(api.refile_regulatory_application(
        ctx["application"]["id"],
        {"expected_target_version": version, "purchase_price_cents": 4000000,
         "rate_base_method": "AS_PAID"},
        TEST_USERS["reg_officer_headers"]))
    assert refiled["filing_round"] == 2
    decided = decide_application(ctx["application"]["id"], "APPROVED")
    assert decided["status"] == "APPROVED"


def test_occ_refile_stale_version(api):
    """PRD §2.7: "**Refiling a remanded regulatory application.** The request
    likewise must carry `expected_target_version` matching the target's current
    `version`. ... a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_refile_stale_version
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    stale_version = current_target_version(ctx["target"]["id"])
    decide_application(ctx["application"]["id"], "REMANDED")
    resp = api.refile_regulatory_application(
        ctx["application"]["id"],
        {"expected_target_version": stale_version - 1,
         "purchase_price_cents": 5000000, "rate_base_method": "AS_PAID"},
        TEST_USERS["reg_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    app_now = get_success_data(api.get_regulatory_application(
        ctx["application"]["id"], TEST_USERS["reg_officer_headers"]))
    assert app_now["status"] == "REMANDED"


def test_regulatory_filing_requires_council_approval(api):
    """PRD §3.5: "Filing before council approval is rejected with
    `ERR_APPROVAL_PREREQ` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/regulatory_filing_requires_council_approval
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    resp = api.create_regulatory_application(
        ctx["target"]["id"],
        {"purchase_price_cents": 5000000, "rate_base_method": "AS_PAID"},
        TEST_USERS["reg_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_PREREQ)
    fresh = get_success_data(api.get_target(ctx["target"]["id"],
                                            TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "MUNICIPAL_REVIEW"


def test_regulatory_filing_requires_council_approval_after_band_failure(api):
    """PRD §3.5: "Filing before council approval is rejected with
    `ERR_APPROVAL_PREREQ` (HTTP 409)."
    PRD §3.4: "When `yes_share_pct` is at least 50.00 but below 60.00 ... the
    target stays in `MUNICIPAL_REVIEW`".

    Design: Difficulty/cross_entity_state_dependency/regulatory_filing_requires_council_approval
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    get_success_data(record_outcome(vote["id"], {"yes_votes": 11, "no_votes": 9}))
    resp = api.create_regulatory_application(
        target_id, {"purchase_price_cents": 5000000, "rate_base_method": "AS_PAID"},
        TEST_USERS["reg_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_PREREQ)


def test_transition_manager_cannot_decide_application(api):
    """PRD §2.1: "A `Commissioner` is the state utility commissioner who decides
    filed applications." and "A request whose role is not permitted for the
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/transition_manager_cannot_decide_application
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    resp = api.decide_regulatory_application(
        ctx["application"]["id"], {"outcome": "APPROVED"},
        TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    app_now = get_success_data(api.get_regulatory_application(
        ctx["application"]["id"], TEST_USERS["reg_officer_headers"]))
    assert app_now["status"] == "FILED"
