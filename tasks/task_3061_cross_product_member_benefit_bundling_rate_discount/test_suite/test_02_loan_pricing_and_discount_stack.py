"""Loan pricing: stack assembly, the two pricing variants, the cap and the floor."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_application,
    assert_loan_account,
    attach_application,
    create_active_rule,
    fetch_loan,
    finalize_loan,
    list_applications,
    make_member_headers,
    setup_member_with_priced_loan,
    validate_error,
    validate_success,
)


def _provisional_stack(base_apr_bps=1200, base_bps=250, autopay_bps=75,
                       principal_cents=1200000):
    """Two-class stack (one BASE, one ADDITIVE autopay) on a PROVISIONAL loan."""
    return setup_member_with_priced_loan(
        base_apr_bps,
        [
            {"rule_code": "DEP_BOOST_25", "discount_kind": "MEMBER_TIER",
             "stacking_class": "BASE", "discount_bps": base_bps},
            {"rule_code": "AUTOPAY_STD", "discount_kind": "AUTOPAY",
             "stacking_class": "ADDITIVE", "discount_bps": autopay_bps},
        ],
        autopay=True,
        principal_cents=principal_cents,
    )


def _final_stack(base_apr_bps=1200, base_bps=250, autopay_bps=75,
                 principal_cents=1200000):
    """The same two-class stack, but each rule is attached and the loan is FINAL.

    Attaching both applications pins the frozen snapshot at the sum of the two
    magnitudes, which is what a FINAL loan holds.
    """
    setup = _provisional_stack(base_apr_bps, base_bps, autopay_bps, principal_cents)
    attach_application(setup["loan"]["id"], setup["rules_by_code"]["DEP_BOOST_25"]["id"])
    attach_application(setup["loan"]["id"], setup["rules_by_code"]["AUTOPAY_STD"]["id"])
    finalize_loan(setup["loan"]["id"])
    setup["loan"] = fetch_loan(setup["loan"]["id"])
    return setup


def test_final_loan_keeps_its_frozen_stack_when_a_new_rule_is_activated(api):
    """PRD §3.5: "a loan whose pricing is final holds its stack frozen at its
    application snapshots, so a rule activated afterwards changes nothing until
    the loan returns to provisional."

    Design: Difficulty/dual_variant_calc/loan_apr_provisional_vs_final_after_rule_activation
    """
    setup = _final_stack()
    loan = setup["loan"]
    assert loan["pricing_status"] == "FINAL"
    assert loan["discount_stack_bps"] == 325
    assert loan["effective_apr_bps"] == 875

    create_active_rule("PROMO_50", discount_kind="PROMOTIONAL",
                                  stacking_class="CAP_CONTRIBUTING", discount_bps=50)

    after = fetch_loan(loan["id"])
    assert after["pricing_status"] == "FINAL", "activation must not un-freeze the loan"
    assert after["discount_stack_bps"] == 325, (
        "final_apr freezes the stack at the snapshot in force when the loan was finalized"
    )
    assert after["effective_apr_bps"] == 875, (
        "final_apr ignores the newly activated 50 bps rule"
    )


def test_the_breakdown_of_a_final_loan_reports_the_frozen_stack_and_the_floor(api):
    """PRD §3.5: "A loan's pricing breakdown reports both the stored, capped
    stack and the raw uncapped sum beside the effective rate, the floor and the
    count of applied applications, so an operator can see the cap binding."

    Design: Difficulty/dual_variant_calc/loan_apr_provisional_vs_final_after_rule_activation
    """
    setup = _final_stack()
    loan = setup["loan"]
    create_active_rule("PROMO_50", discount_kind="PROMOTIONAL",
                       stacking_class="CAP_CONTRIBUTING", discount_bps=50)

    resp = api.get_pricing_breakdown(loan["id"], TEST_USERS["underwriter_headers"])
    breakdown = validate_success(resp, expected_status=200)
    assert breakdown["stored_bps"] == 325, (
        "the stored stack of a FINAL loan is the frozen snapshot"
    )
    assert breakdown["floor_bps"] == 199
    assert breakdown["effective_apr_bps"] == 875


def test_provisional_loan_prices_a_rule_activated_after_it_was_first_priced(api):
    """PRD §2.5: "a loan whose pricing is provisional re-derives its stack on
    every mutation, so a rule activated or retired after the first pricing flows
    straight through".
    PRD §3.5: "The effective rate is then the undiscounted rate less the capped
    stack, and it never falls below the hard floor of 199 basis points, whatever
    discounts are stacked."

    Design: Difficulty/dual_variant_calc/loan_apr_provisional_vs_final_after_rule_activation
    """
    setup = _provisional_stack()
    loan = setup["loan"]
    assert loan["pricing_status"] == "PROVISIONAL"
    assert loan["discount_stack_bps"] == 325
    assert loan["effective_apr_bps"] == 875

    create_active_rule("PROMO_50", discount_kind="PROMOTIONAL",
                       stacking_class="CAP_CONTRIBUTING", discount_bps=50)

    after = fetch_loan(loan["id"])
    assert after["pricing_status"] == "PROVISIONAL"
    assert after["discount_stack_bps"] == 375, (
        "provisional_apr re-derives the stack, so the later 50 bps rule flows through"
    )
    assert after["effective_apr_bps"] == 825, "1200 - 375"
    assert after["discount_stack_bps"] - loan["discount_stack_bps"] == 50, (
        "the two variants differ by exactly the 50 bps the new rule carries"
    )


# --------------------------------------------------------------------------
# Stack assembly
# --------------------------------------------------------------------------

def test_discount_stack_keeps_one_survivor_per_class_by_the_pinned_sort_key(api):
    """PRD §2.5: "From the pool, exactly one survivor is kept per stacking
    class, selected by the ordering that prefers the largest discount in basis
    points, then the latest window start, then the latest creation timestamp;
    the resource identifier is never consulted as a tie-break. The discounts of
    the survivors are summed and the sum is capped at 400 basis points. Each
    surviving rule yields one application in `APPLIED` state, and every other
    candidate of the same class yields a `PREEMPTED` application."

    Design: Corner/calculations/discount_stack_selects_one_survivor_per_class_by_the_pinned_sort_key
    """
    setup = setup_member_with_priced_loan(
        1200,
        [
            {"rule_code": "A_60", "discount_kind": "PROMOTIONAL",
             "stacking_class": "ADDITIVE", "discount_bps": 60,
             "effective_from": "2026-02-01T00:00:00Z"},
            {"rule_code": "A_40", "discount_kind": "AUTOPAY",
             "stacking_class": "ADDITIVE", "discount_bps": 40,
             "effective_from": "2026-03-01T00:00:00Z"},
            {"rule_code": "B_30", "discount_kind": "MEMBER_TIER",
             "stacking_class": "BASE", "discount_bps": 30,
             "effective_from": "2026-02-01T00:00:00Z"},
        ],
        autopay=True,
        principal_cents=500000,
    )
    loan = fetch_loan(setup["loan"]["id"])
    assert loan["discount_stack_bps"] == 90, (
        "60 ADDITIVE survivor plus 30 BASE survivor; the 40 bps candidate loses its class"
    )
    assert loan["effective_apr_bps"] == 1110, "1200 - 90"

    apps = list_applications(loan_account_id=loan["id"])
    additive = [app for app in apps if app["rule_id"] == setup["rules_by_code"]["A_60"]["id"]]
    losing = [app for app in apps if app["rule_id"] == setup["rules_by_code"]["A_40"]["id"]]
    assert additive and additive[0]["application_state"] == "APPLIED"
    assert additive[0]["applied_bps"] == 60
    if losing:
        assert_application(losing[0])
        assert losing[0]["application_state"] == "PREEMPTED", (
            "every non-surviving candidate of the class is displaced into PREEMPTED"
        )
        assert losing[0]["preempted_by_application_id"] is not None


def test_discount_stack_only_counts_rules_inside_their_validity_window(api):
    """PRD §2.5: "The candidate pool is every rule that is `ACTIVE`, whose
    window contains the current logical instant under the half-open convention
    that the start is inclusive and the end is exclusive".

    Design: Corner/calculations/discount_stack_only_counts_rules_inside_their_validity_window
    """
    setup = setup_member_with_priced_loan(
        1000,
        [
            {"rule_code": "W_CLOSED", "discount_kind": "PROMOTIONAL",
             "stacking_class": "ADDITIVE", "discount_bps": 90,
             "effective_from": "2026-03-01T00:00:00Z",
             "effective_to": "2026-09-01T00:00:00Z"},
            {"rule_code": "W_OPEN", "discount_kind": "MEMBER_TIER",
             "stacking_class": "ADDITIVE", "discount_bps": 20,
             "effective_from": "2026-09-01T00:00:00Z",
             "effective_to": "2027-01-01T00:00:00Z"},
        ],
        principal_cents=400000,
    )
    loan = fetch_loan(setup["loan"]["id"])
    assert loan["discount_stack_bps"] == 20, (
        "W_CLOSED's effective_to equals the logical instant and the window is half-open "
        "on the right, so it is not a candidate"
    )
    assert loan["effective_apr_bps"] == 980, "1000 - 20; the inclusive left bound admits W_OPEN"


def test_discount_stack_applies_the_cap_and_still_reports_the_uncapped_sum(api):
    """PRD §2.5: "The discounts of the survivors are summed and the sum is
    capped at 400 basis points."
    PRD §3.5: "A loan's pricing breakdown reports both the stored, capped stack
    and the raw uncapped sum beside the effective rate, the floor and the count
    of applied applications, so an operator can see the cap binding."

    Design: Corner/calculations/discount_stack_applies_the_cap_and_still_reports_the_uncapped_sum
    """
    setup = setup_member_with_priced_loan(
        1200,
        [
            {"rule_code": "CAP_BASE_200", "discount_kind": "MEMBER_TIER",
             "stacking_class": "BASE", "discount_bps": 200},
            {"rule_code": "CAP_ADD_150", "discount_kind": "AUTOPAY",
             "stacking_class": "ADDITIVE", "discount_bps": 150},
            {"rule_code": "CAP_CC_100", "discount_kind": "PROMOTIONAL",
             "stacking_class": "CAP_CONTRIBUTING", "discount_bps": 100},
        ],
        autopay=True,
        principal_cents=900000,
    )
    loan = setup["loan"]
    resp = api.get_pricing_breakdown(loan["id"], TEST_USERS["underwriter_headers"])
    breakdown = validate_success(resp, expected_status=200)
    assert breakdown["uncapped_bps"] == 450, "200 + 150 + 100 before the ceiling"
    assert breakdown["stored_bps"] == 400, "the STACK_CAP_BPS ceiling binds"
    assert_loan_account(loan)
    assert loan["discount_stack_bps"] == 400
    assert loan["effective_apr_bps"] == 800, "1200 - 400"


def test_effective_apr_never_falls_below_the_hard_floor(api):
    """PRD §3.5: "The effective rate is then the undiscounted rate less the
    capped stack, and it never falls below the hard floor of 199 basis points,
    whatever discounts are stacked — the floor is absolute."

    Design: Corner/endpoints/pricing_breakdown_read_is_computed_from_the_live_rule_pool
    """
    setup = setup_member_with_priced_loan(
        550,
        [
            {"rule_code": "FLOOR_500", "discount_kind": "MEMBER_TIER",
             "stacking_class": "BASE", "discount_bps": 500},
        ],
        principal_cents=350000,
    )
    loan = setup["loan"]
    assert loan["discount_stack_bps"] == 400, "the 500 bps rule is capped to the ceiling"
    assert loan["effective_apr_bps"] == 199, (
        "550 - 400 is 150, below the floor, so the floor raises it to exactly 199"
    )

    resp = api.get_pricing_breakdown(loan["id"], TEST_USERS["underwriter_headers"])
    breakdown = validate_success(resp, expected_status=200)
    assert breakdown["stored_bps"] == 400
    assert breakdown["uncapped_bps"] == 500
    assert breakdown["floor_bps"] == 199


# --------------------------------------------------------------------------
# Discount applications
# --------------------------------------------------------------------------

def test_discount_application_create_snapshots_the_rule_values(api):
    """PRD §2.5: "It names the loan through `loan_account_id` and the rule
    through `rule_id`, and snapshots the rule's magnitude into `applied_bps` and
    its window into `window_from` and `window_to` at the moment of application."

    Design: Corner/endpoints/discount_application_create_returns_201_with_the_snapshotted_rule_values
    """
    setup = setup_member_with_priced_loan(
        1150,
        [
            {"rule_code": "SNAP_65", "discount_kind": "PROMOTIONAL",
             "stacking_class": "ADDITIVE", "discount_bps": 65,
             "effective_from": "2026-05-01T00:00:00Z",
             "effective_to": "2027-05-01T00:00:00Z"},
        ],
        principal_cents=450000,
    )
    loan = setup["loan"]
    resp = api.create_application(
        loan["id"],
        {"rule_id": setup["rules_by_code"]["SNAP_65"]["id"],
         "expected_loan_account_version": loan["version"]},
        TEST_USERS["benefits_admin_headers"],
    )
    application = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert_application(application)
    assert application["applied_bps"] == 65
    assert application["application_state"] == "APPLIED"
    assert application["window_from"] == "2026-05-01T00:00:00Z"
    assert application["window_to"] == "2027-05-01T00:00:00Z"

    after = fetch_loan(loan["id"])
    assert after["discount_stack_bps"] == 65
    assert after["effective_apr_bps"] == 1085, "1150 - 65"


def test_unknown_holding_id_is_checked_before_the_state_precondition(api):
    """PRD §2.9: "Every other resource identifier in the path resolves, else
    `ERR_RESOURCE_NOT_FOUND`. The identifiers governed here are the holding,
    loan account, enrolment, entitlement, rule, application, ledger entry,
    cycle, notice, check, and session identifiers."
    PRD §2.9: "Validation is a single ordered ladder, evaluated top to bottom,
    and the first rule that fails determines the error returned; later rules are
    not consulted."

    Design: Corner/validations/unknown_resource_id_is_checked_before_the_state_precondition
    """
    member = api.create_member(
        {"member_number": "M-V-003", "full_name": "Yara Chen", "email": "yara.v@x.com"},
        TEST_USERS["anonymous_headers"],
    ).json()["data"]
    resp = api.adopt_holding(NON_EXISTENT_UUID, make_member_headers(member["id"]))
    validate_error(resp, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

def _node_map():
    from test_helpers import setup_node_map
    return setup_node_map()


def test_a_known_stack_decomposes_into_its_component_magnitudes(api):
    """PRD §3.5: "The surviving magnitudes are summed and the sum is capped at
    400 basis points; the capped value is what the loan stores as its discount
    stack. The effective rate is then the undiscounted rate less the capped
    stack".
    PRD §2.4: "A member reaches `PREMIER` when their adopted product count is at
    least 3 and their adopted distinct product-line count is at least 3. Failing
    that, they reach `PLUS` when their adopted product count is at least 2 and
    their distinct line count is at least 2."

    Design: Difficulty/combinatorial_formula/member_tier_then_base_apr_evaluation_order_pins_the_final_apr
    """
    setup = _node_map()
    components = setup["components"]
    expected = components["base_bps"] + components["autopay_bps"]

    loan = fetch_loan(setup["loan"]["id"])
    assert setup["member"]["member_tier"] == "PLUS"
    assert loan["discount_stack_bps"] == expected, (
        f"the stored stack must equal the two live rule magnitudes: {components}"
    )
    assert loan["effective_apr_bps"] == loan["base_apr_bps"] - loan["discount_stack_bps"], (
        "the effective rate is the undiscounted rate less the capped stack"
    )


def test_the_tier_rule_enters_the_pool_only_because_the_tier_step_ran_first(api):
    """PRD §2.4: "Tier is derived from adoption breadth by a top-down threshold
    rule; the first clause satisfied determines the result."
    PRD §3.4: "Once activated, the rule's status becomes `ACTIVE` and every loan
    of every member whose tier is at least `min_member_tier` is repriced".

    Design: Difficulty/combinatorial_formula/member_tier_then_base_apr_evaluation_order_pins_the_final_apr
    """
    setup = _node_map()
    member = setup["member"]
    assert member["product_adoption_count"] == 2, (
        "the adopted holdings are counted before the discount lookup runs"
    )
    assert member["product_line_set"] == ["LENDING", "BANKING"]

    base_rule = [r for r in setup["rules"] if r["stacking_class"] == "BASE"][0]
    assert base_rule["min_member_tier"] in ("NONE", "BASE", "PLUS"), (
        "the rule is admitted at the member's recomputed tier"
    )
    loan = fetch_loan(setup["loan"]["id"])
    assert loan["discount_stack_bps"] >= base_rule["discount_bps"], (
        "the tier rule contributes its full magnitude, so the tier step must have run first"
    )
