"""Pricing arithmetic: payoff-quote variants, trade-in credit, schedules and fees.

Every assertion in this module is an exact integer count of cents. The two
payoff-quote flavours are priced against byte-identical loan state so their
divergence is attributable to the rebate method and the administration charge
alone; the declared trade-in estimate is compared against the graded final
credit on the same physical handset; the installment ladder is checked for the
residual the last installment must absorb; and the successor loan's tiered
origination fee is pinned to the pre-fee base rather than to the principal it
produces.
"""
from test_helpers import (
    CANCELLATION_ADMIN_FEE_CENTS,
    CONDITION_MULTIPLIERS_BPS,
    DIAGNOSTIC_FAIL_CREDIT_BPS,
    MODEL_B_BASE_PRINCIPAL_COMPONENT_CENTS,
    MODEL_B_LAST_INSTALLMENT_AMOUNT_CENTS,
    MODEL_B_LAST_PRINCIPAL_COMPONENT_CENTS,
    MODEL_B_LOAN_PRINCIPAL_CENTS,
    MODEL_B_MONTHLY_INSTALLMENT_CENTS,
    MODEL_B_OBLIGATION_BALANCE_CENTS,
    MODEL_B_PREMIUM_TOTAL_CENTS,
    PRORATA_REBATE_BPS,
    SCREEN_DEDUCTION_CENTS,
    TRADE_IN_CREDIT_FLOOR_CENTS,
    apply_bps,
    assert_diagnostic_report,
    assert_installment,
    assert_iso_equals,
    assert_loan,
    assert_loan_ledger_invariants,
    assert_payoff_quote,
    assert_schedule_sums_to_principal,
    assert_trade_in,
    complete_upgrade,
    diagnostic_report_payload,
    due_date_for,
    expected_battery_deduction_cents,
    expected_condition_multiplier_bps,
    expected_origination_fee_cents,
    expected_schedule_components,
    grade_trade_in,
    make_associate_headers,
    make_technician_headers,
    payoff_quote_payload,
    read_customer,
    read_device_model,
    read_device_unit,
    read_installments,
    read_loan,
    read_trade_in,
    read_upgrade_request,
    receive_trade_in,
    round_half_up,
    setup_active_loan,
    setup_completion_ready,
    setup_trade_in_declared,
    setup_trade_in_received,
    setup_upgrade_request,
    trade_in_declaration_payload,
    unearned_premium_pro_rata,
    unearned_premium_rule_of_78,
    validate_paginated,
    validate_success,
)

# The reference financed model: retail 89900, premium 999, trade-in base 45000,
# financed over 24 months with no down payment.
REFERENCE_TERM_MONTHS = 24
TRADE_IN_BASE_CREDIT_CENTS = 45_000


def test_payoff_quote_variants_diverge_on_identical_loan_state(api):
    """Both quote flavours priced against one loan with 12 of 24 installments PAID:
    the rollover quote rebates 6234 cents by rule-of-78 and charges no admin fee for a
    total of 38714, while the cancellation quote rebates 10789 cents pro rata and adds
    2500 for a total of 36659 — a divergence of exactly 2055 cents.

    PRD §3.7: "For an `UPGRADE_ROLLOVER` quote the rebate uses the **rule-of-78** method. `unearned_premium_cents` is the total premium multiplied by the unexpired term times one more than the unexpired term, divided by the full term times one more than the full term, rounded half up to whole cents; and `premium_rebate_cents` equals `unearned_premium_cents` in full, with no retention factor applied."
    PRD §3.7: "For an `EARLY_CANCELLATION` quote the rebate uses the **pro-rata** method. `unearned_premium_cents` is the total premium less the loan's `paid_premium_cents` — a straight-line unexpired figure. `premium_rebate_cents` is then 9,000 basis points of that, or 90 percent, rounded half up to whole cents; the withheld 10 percent is the program's cancellation retention haircut."
    PRD §3.7: "`admin_fee_cents` is 2,500 cents on an `EARLY_CANCELLATION` quote and zero on an `UPGRADE_ROLLOVER` quote — leaving the program costs an administration charge, upgrading within it does not."
    PRD §3.7: "`total_payoff_cents` is then `remaining_principal_cents` plus `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."

    Design: Difficulty/dual_variant_calc/payoff_quote_variant_divergence_cancellation_vs_rollover
    """
    ctx = setup_upgrade_request(paid_count=12)
    loan = ctx["loan"]
    assert loan["term_months"] == REFERENCE_TERM_MONTHS
    assert loan["principal_cents"] == MODEL_B_LOAN_PRINCIPAL_CENTS == 89_900
    assert loan["paid_installment_count"] == 12
    assert loan["paid_principal_cents"] == 44_952
    assert loan["paid_premium_cents"] == 11_988
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["delinquency_state"] == "CURRENT"

    rollover = validate_success(api.create_payoff_quote(
        ctx["loan_id"], payoff_quote_payload("UPGRADE_ROLLOVER"),
        ctx["customer_headers"]), 201)
    cancellation = validate_success(api.create_payoff_quote(
        ctx["loan_id"], payoff_quote_payload("EARLY_CANCELLATION"),
        ctx["customer_headers"]), 201)
    assert_payoff_quote(rollover)
    assert_payoff_quote(cancellation)

    # remaining_principal_cents is identical on both: 89900 - 44952.
    for quote in (rollover, cancellation):
        assert quote["remaining_principal_cents"] == 44_948
        assert quote["outstanding_late_fee_cents"] == 0
        assert quote["paid_installment_count_at_quote"] == 12
        assert quote["past_due_amount_cents"] == 0
        assert quote["status"] == "ISSUED"

    # Rule-of-78: 23976 * 12*13 / (24*25) = 6233.76 -> 6234, rebated in full.
    assert MODEL_B_PREMIUM_TOTAL_CENTS == 23_976
    assert unearned_premium_rule_of_78(MODEL_B_PREMIUM_TOTAL_CENTS, 24, 12) == 6_234
    assert rollover["quote_type"] == "UPGRADE_ROLLOVER"
    assert rollover["unearned_premium_cents"] == 6_234
    assert rollover["premium_rebate_cents"] == 6_234
    assert rollover["admin_fee_cents"] == 0
    assert rollover["total_payoff_cents"] == 38_714, (
        f"rollover total expected 44948 + 0 + 0 - 6234 = 38714, "
        f"got {rollover['total_payoff_cents']}")

    # Pro rata: 23976 - 11988 = 11988 unexpired, 9000bps of which is 10789.2 -> 10789.
    assert unearned_premium_pro_rata(MODEL_B_PREMIUM_TOTAL_CENTS, 11_988) == 11_988
    assert apply_bps(11_988, PRORATA_REBATE_BPS) == 10_789
    assert cancellation["quote_type"] == "EARLY_CANCELLATION"
    assert cancellation["unearned_premium_cents"] == 11_988
    assert cancellation["premium_rebate_cents"] == 10_789
    assert cancellation["admin_fee_cents"] == CANCELLATION_ADMIN_FEE_CENTS == 2_500
    assert cancellation["total_payoff_cents"] == 36_659, (
        f"cancellation total expected 44948 + 0 + 2500 - 10789 = 36659, "
        f"got {cancellation['total_payoff_cents']}")

    assert rollover["total_payoff_cents"] - cancellation["total_payoff_cents"] == 2_055
    assert cancellation["premium_rebate_cents"] > rollover["premium_rebate_cents"]

    # 7-day half-open validity, stamped from the logical clock at 2027-06-27.
    assert_iso_equals(rollover["issued_at"], "2027-06-27T00:00:00.000Z", "issued_at")
    assert_iso_equals(rollover["expires_at"], "2027-07-04T00:00:00.000Z", "expires_at")
    assert_iso_equals(cancellation["expires_at"], "2027-07-04T00:00:00.000Z", "expires_at")


def test_payoff_quote_variants_diverge_on_twelve_month_term_at_midpoint(api):
    """On a 12-month loan halfway through its ladder the pro-rata rebate (5395) still
    beats the rule-of-78 rebate (3228), but the 2500-cent administration charge more
    than closes the gap, so the cancellation total 42053 lands 333 cents ABOVE the
    rollover total 41720 — the divergence is not a fixed offset.

    PRD §3.7: "For an `UPGRADE_ROLLOVER` quote the rebate uses the **rule-of-78** method. `unearned_premium_cents` is the total premium multiplied by the unexpired term times one more than the unexpired term, divided by the full term times one more than the full term, rounded half up to whole cents; and `premium_rebate_cents` equals `unearned_premium_cents` in full, with no retention factor applied."
    PRD §3.7: "On identical loan data at the midpoint of a term, this method returns a strictly larger rebate than the rule-of-78 method does."
    PRD §3.7: "`total_payoff_cents` is then `remaining_principal_cents` plus `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."

    Design: Difficulty/dual_variant_calc/payoff_quote_variant_divergence_cancellation_vs_rollover
    """
    ctx = setup_upgrade_request(paid_count=6, term_months=12)
    loan = ctx["loan"]
    assert loan["term_months"] == 12
    assert loan["principal_cents"] == 89_900
    assert loan["premium_total_cents"] == 11_988
    assert loan["paid_installment_count"] == 6
    assert loan["paid_principal_cents"] == 44_952
    assert loan["paid_premium_cents"] == 5_994

    rollover = validate_success(api.create_payoff_quote(
        ctx["loan_id"], payoff_quote_payload("UPGRADE_ROLLOVER"),
        ctx["customer_headers"]), 201)
    cancellation = validate_success(api.create_payoff_quote(
        ctx["loan_id"], payoff_quote_payload("EARLY_CANCELLATION"),
        ctx["customer_headers"]), 201)

    # 11988 * 6*7 / (12*13) = 3227.54 -> 3228.
    assert unearned_premium_rule_of_78(11_988, 12, 6) == 3_228
    assert rollover["remaining_principal_cents"] == 44_948
    assert rollover["unearned_premium_cents"] == 3_228
    assert rollover["premium_rebate_cents"] == 3_228
    assert rollover["admin_fee_cents"] == 0
    assert rollover["total_payoff_cents"] == 41_720

    # 11988 - 5994 = 5994 unexpired; 9000bps of it is 5394.6 -> 5395.
    assert apply_bps(5_994, PRORATA_REBATE_BPS) == 5_395
    assert cancellation["remaining_principal_cents"] == 44_948
    assert cancellation["unearned_premium_cents"] == 5_994
    assert cancellation["premium_rebate_cents"] == 5_395
    assert cancellation["admin_fee_cents"] == 2_500
    assert cancellation["total_payoff_cents"] == 42_053

    assert cancellation["premium_rebate_cents"] > rollover["premium_rebate_cents"]
    assert cancellation["total_payoff_cents"] - rollover["total_payoff_cents"] == 333


def test_trade_in_declared_estimate_ignores_deductions_graded_final_applies_them(api):
    """One physical handset, two credit figures: the GOOD declaration is estimated at
    the multiplier alone (45000 * 8500bps = 38250) while the bench grading applies the
    same multiplier and then subtracts the flat screen and battery deductions
    (38250 - 2500 - 4000 = 31750), leaving credit_variance_cents at exactly -6500.

    PRD §3.9: "The estimate is the traded handset's model `trade_in_base_credit_cents` multiplied by the condition multiplier for the declared condition and divided by 10,000, rounded half up to whole cents."
    PRD §3.9: "No screen deduction, no battery deduction, no diagnostic outcome and no floor clamp enter the estimate: the multiplier alone determines it."
    PRD §3.9: "Then, and only then, `screen_deduction_cents` and `battery_deduction_cents` are subtracted from the rounded product; the deductions are flat cash amounts and are never scaled by the multiplier."
    PRD §3.9: "`credit_variance_cents` is then `credit_final_cents` less `credit_estimate_cents`, and it goes negative whenever grading came in below the customer's own declaration — which is the whole point of grading, since the declared condition is ignored entirely and an `EXCELLENT` declaration cannot lift a cracked-screen handset above `FAIR`."

    Design: Difficulty/dual_variant_calc/trade_in_credit_declared_estimate_vs_final_graded
    """
    ctx = setup_upgrade_request(paid_count=12)
    assert ctx["model"]["trade_in_base_credit_cents"] == TRADE_IN_BASE_CREDIT_CENTS

    declared = validate_success(api.declare_trade_in(
        ctx["upgrade_request_id"],
        trade_in_declaration_payload(ctx["device_id"], "GOOD"),
        ctx["customer_headers"]), 201)
    assert_trade_in(declared)

    # Variant one — the declared estimate: 45000 * 8500 / 10000 = 38250, multiplier only.
    assert CONDITION_MULTIPLIERS_BPS["GOOD"] == 8_500
    assert apply_bps(TRADE_IN_BASE_CREDIT_CENTS, 8_500) == 38_250
    assert declared["declared_condition"] == "GOOD"
    assert declared["credit_estimate_cents"] == 38_250
    assert declared["status"] == "DECLARED"
    assert declared["credit_final_cents"] is None
    assert declared["graded_condition"] is None
    assert declared["diagnostic_result"] is None
    assert declared["credit_variance_cents"] == 0
    assert read_upgrade_request(ctx["upgrade_request_id"])[
        "trade_in_credit_projection_cents"] == 38_250

    receive_trade_in(declared["id"])
    report = validate_success(api.create_diagnostic_report(
        declared["id"],
        diagnostic_report_payload(screen_grade="SCRATCHED", battery_health_pct=78,
                                  water_damage_flag=False, functional_pass=True),
        make_technician_headers()), 201)
    assert_diagnostic_report(report)

    # Variant two — the graded final credit: the same 8500bps multiplier, then the
    # flat 2500 screen deduction and 4000 battery deduction come off the rounded product.
    assert report["diagnostic_result"] == "PASS"
    assert report["derived_condition"] == "GOOD"
    assert report["condition_multiplier_bps"] == expected_condition_multiplier_bps("GOOD") == 8_500
    assert report["screen_deduction_cents"] == SCREEN_DEDUCTION_CENTS["SCRATCHED"] == 2_500
    assert report["battery_deduction_cents"] == expected_battery_deduction_cents(78) == 4_000
    assert report["computed_credit_cents"] == 31_750, (
        f"computed_credit_cents expected 38250 - 2500 - 4000 = 31750, "
        f"got {report['computed_credit_cents']}")
    assert report["sequence_no"] == 1
    assert report["report_type"] == "INITIAL"

    graded = read_trade_in(declared["id"])
    assert graded["status"] == "GRADED"
    assert graded["graded_condition"] == "GOOD"
    assert graded["credit_estimate_cents"] == 38_250
    assert graded["credit_final_cents"] == 31_750
    assert graded["credit_variance_cents"] == -6_500
    assert graded["latest_report_sequence_no"] == 1

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "TRADE_IN_GRADED"
    assert request["trade_in_credit_projection_cents"] == 31_750


def test_trade_in_graded_credit_overrides_a_pessimistic_poor_declaration(api):
    """The divergence runs upward too: a POOR self-declaration is estimated at
    3000bps (13500) while a PRISTINE screen and a 90 percent battery grade the same
    handset EXCELLENT at 10000bps with no deductions (45000), so
    credit_variance_cents is +31500 and the declared condition never binds the grade.

    PRD §3.9: "The four condition multipliers, in basis points, are 10,000 for `EXCELLENT`, 8,500 for `GOOD`, 6,000 for `FAIR` and 3,000 for `POOR` — so a self-declared pristine handset is estimated at its full base credit, a good one at 85 percent of it, a fair one at 60 percent, and a poor one at 30 percent."
    PRD §3.9: "Whichever way the diagnostic lands, the trade-in advances `RECEIVED → GRADED` and takes its grading fields from the report: `graded_condition` from the report's `derived_condition`, `diagnostic_result` from the report's `diagnostic_result`, `credit_final_cents` from the report's `computed_credit_cents`, `latest_report_sequence_no` from the report's `sequence_no`, and `graded_at` stamped from the logical clock."
    PRD §3.9: "`credit_variance_cents` is then `credit_final_cents` less `credit_estimate_cents`, and it goes negative whenever grading came in below the customer's own declaration — which is the whole point of grading, since the declared condition is ignored entirely and an `EXCELLENT` declaration cannot lift a cracked-screen handset above `FAIR`."

    Design: Difficulty/dual_variant_calc/trade_in_credit_declared_estimate_vs_final_graded
    """
    ctx = setup_trade_in_declared(declared_condition="POOR")
    assert apply_bps(TRADE_IN_BASE_CREDIT_CENTS, CONDITION_MULTIPLIERS_BPS["POOR"]) == 13_500
    assert ctx["trade_in"]["declared_condition"] == "POOR"
    assert ctx["trade_in"]["credit_estimate_cents"] == 13_500

    receive_trade_in(ctx["trade_in_id"])
    report = grade_trade_in(ctx["trade_in_id"], screen_grade="PRISTINE",
                            battery_health_pct=90, water_damage_flag=False,
                            functional_pass=True)
    assert report["derived_condition"] == "EXCELLENT"
    assert report["condition_multiplier_bps"] == 10_000
    assert report["screen_deduction_cents"] == 0
    assert report["battery_deduction_cents"] == 0
    assert report["computed_credit_cents"] == 45_000

    graded = read_trade_in(ctx["trade_in_id"])
    assert graded["graded_condition"] == "EXCELLENT"
    assert graded["credit_estimate_cents"] == 13_500
    assert graded["credit_final_cents"] == 45_000
    assert graded["credit_variance_cents"] == 31_500, (
        "credit_variance_cents is credit_final_cents less credit_estimate_cents: "
        f"45000 - 13500 = 31500, got {graded['credit_variance_cents']}")
    assert read_upgrade_request(ctx["upgrade_request_id"])[
        "trade_in_credit_projection_cents"] == 45_000


def test_installment_schedule_residual_lands_on_last_installment_only(api):
    """A 89900-cent principal over 24 months puts the half-up base component 3746 on
    installments 1 through 23 and the whole residual 89900 - 3746*23 = 3742 on
    installment 24 alone, so the principal components sum to 89900 exactly.

    PRD §3.3: "First a base principal component is derived: the loan's `principal_cents` divided by its `term_months`, rounded half up to whole cents."
    PRD §3.3: "For the last installment — and only the last — `principal_component_cents` is instead the loan's `principal_cents` less the base figure multiplied by one fewer than `term_months`; this residual guarantees that the principal components sum to `principal_cents` exactly, and it means the final installment's principal share may come out either smaller or larger than the base figure."
    PRD §3.3: "The residual is never spread across several installments and never lands on installment 1."
    PRD §3.3: "`premium_component_cents` is the loan's snapshotted `monthly_protection_premium_cents` on every installment without exception and is never rounded, being a flat per-month constant."
    PRD §3.3: "`amount_due_cents` on each installment is its `principal_component_cents` plus its `premium_component_cents`."

    Design: Difficulty/combinatorial_formula/installment_component_rounding_residual_on_last
    """
    ctx = setup_active_loan(term_months=24)
    loan = ctx["loan"]
    assert_loan(loan)
    assert_loan_ledger_invariants(loan)

    base, last = expected_schedule_components(MODEL_B_LOAN_PRINCIPAL_CENTS, 24)
    assert (base, last) == (3_746, 3_742)
    assert round_half_up(89_900, 24) == MODEL_B_BASE_PRINCIPAL_COMPONENT_CENTS == 3_746
    assert 89_900 - 3_746 * 23 == MODEL_B_LAST_PRINCIPAL_COMPONENT_CENTS == 3_742

    assert loan["principal_cents"] == 89_900
    assert loan["term_months"] == 24
    assert loan["monthly_protection_premium_cents"] == 999
    assert loan["premium_total_cents"] == MODEL_B_PREMIUM_TOTAL_CENTS == 23_976
    assert loan["monthly_installment_cents"] == MODEL_B_MONTHLY_INSTALLMENT_CENTS == 4_745
    assert loan["obligation_balance_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS == 113_876
    assert loan["origination_fee_cents"] == 0
    assert loan["rolled_over_balance_cents"] == 0
    assert loan["predecessor_loan_id"] is None

    rows, meta = validate_paginated(api.list_installments(
        ctx["loan_id"], make_associate_headers(), params={"limit": 100}))
    assert meta["total_count"] == 24, f"expected 24 installments, meta says {meta['total_count']}"
    schedule = sorted(rows, key=lambda row: row["installment_number"])
    assert [row["installment_number"] for row in schedule] == list(range(1, 25))
    for row in schedule:
        assert_installment(row)
        assert row["premium_component_cents"] == 999
        assert row["status"] == "SCHEDULED"
        assert row["late_fee_assessed"] is False
        assert row["late_fee_cents"] == 0
        assert row["paid_amount_cents"] == 0

    for row in schedule[:23]:
        assert row["principal_component_cents"] == 3_746, (
            f"installment {row['installment_number']} must carry the base component 3746, "
            f"got {row['principal_component_cents']}")
        assert row["amount_due_cents"] == 4_745

    assert schedule[0]["principal_component_cents"] == 3_746
    assert schedule[23]["principal_component_cents"] == 3_742
    assert schedule[23]["amount_due_cents"] == MODEL_B_LAST_INSTALLMENT_AMOUNT_CENTS == 4_741
    assert sum(row["principal_component_cents"] for row in schedule) == 89_900
    assert sum(row["premium_component_cents"] for row in schedule) == 23_976
    assert_schedule_sums_to_principal(schedule, loan)

    assert_iso_equals(schedule[0]["due_date"], "2026-09-01T00:00:00.000Z", "installment 1 due_date")
    assert_iso_equals(schedule[0]["due_date"], due_date_for(loan["origination_date"], 1))
    assert_iso_equals(schedule[23]["due_date"], "2028-08-01T00:00:00.000Z", "installment 24 due_date")


def test_installment_schedule_residual_exceeds_base_component_on_twelve_month_term(api):
    """When the half-up base component rounds DOWN the residual is larger than the base:
    89905 over 12 months gives a base of 7492 on installments 1 through 11 and a final
    principal component of 89905 - 7492*11 = 7493, still summing to 89905 exactly.

    PRD §3.3: "First a base principal component is derived: the loan's `principal_cents` divided by its `term_months`, rounded half up to whole cents."
    PRD §3.3: "For the last installment — and only the last — `principal_component_cents` is instead the loan's `principal_cents` less the base figure multiplied by one fewer than `term_months`; this residual guarantees that the principal components sum to `principal_cents` exactly, and it means the final installment's principal share may come out either smaller or larger than the base figure."
    PRD §3.3: "`monthly_installment_cents` is the base monthly principal component (derived just below) plus the monthly premium, which is what the customer is told they will pay each month — with the caveat that the final installment may differ from it by the principal residual."

    Design: Difficulty/combinatorial_formula/installment_component_rounding_residual_on_last
    """
    ctx = setup_active_loan(term_months=12, model_overrides={"retail_price_cents": 89_905})
    loan = ctx["loan"]
    assert loan["principal_cents"] == 89_905
    assert loan["term_months"] == 12

    base, last = expected_schedule_components(89_905, 12)
    assert (base, last) == (7_492, 7_493)
    assert last > base, "this fixture exists to exercise a residual larger than the base"

    assert loan["premium_total_cents"] == 11_988
    assert loan["monthly_installment_cents"] == 8_491
    assert loan["obligation_balance_cents"] == 101_893
    assert_loan_ledger_invariants(loan)

    schedule = read_installments(ctx["loan_id"])
    assert len(schedule) == 12
    for row in schedule[:11]:
        assert row["principal_component_cents"] == 7_492
        assert row["amount_due_cents"] == 8_491
    assert schedule[11]["principal_component_cents"] == 7_493
    assert schedule[11]["amount_due_cents"] == 8_492
    assert sum(row["principal_component_cents"] for row in schedule) == 89_905
    assert_schedule_sums_to_principal(schedule, loan)
    assert_iso_equals(schedule[11]["due_date"], "2027-08-01T00:00:00.000Z",
                      "installment 12 due_date")


def test_trade_in_pass_credit_floors_at_zero_after_unscaled_deductions(api):
    """On a PASS the credit chain is round-then-deduct-then-floor: a 15000-cent base at
    the FAIR multiplier rounds to 9000, the flat 9500 screen and 8000 battery deductions
    take it to -8500, and the floor clamps the recorded credit to exactly 0.

    PRD §3.9: "`computed_credit_cents` on a `PASS` report is then built in a fixed order that must not be rearranged."
    PRD §3.9: "Then, and only then, `screen_deduction_cents` and `battery_deduction_cents` are subtracted from the rounded product; the deductions are flat cash amounts and are never scaled by the multiplier."
    PRD §3.9: "Finally the result is floored at zero, so a heavily deducted low-base handset yields a credit of 0 cents rather than a negative one."
    PRD §3.9: "Rounding before the deductions and flooring after them is normative."
    PRD §3.9: "`credit_variance_cents` is then `credit_final_cents` less `credit_estimate_cents`, and it goes negative whenever grading came in below the customer's own declaration — which is the whole point of grading, since the declared condition is ignored entirely and an `EXCELLENT` declaration cannot lift a cracked-screen handset above `FAIR`."

    Design: Difficulty/combinatorial_formula/trade_in_final_credit_nested_min_max_deductions
    """
    ctx = setup_trade_in_received(
        declared_condition="FAIR",
        model_overrides={"display_name": "Handset H", "retail_price_cents": 45_000,
                         "monthly_protection_premium_cents": 599,
                         "trade_in_base_credit_cents": 15_000})
    base_credit = ctx["model"]["trade_in_base_credit_cents"]
    assert base_credit == 15_000
    assert ctx["trade_in"]["credit_estimate_cents"] == 9_000, (
        "declared FAIR on a 15000 base is 15000 * 6000 / 10000 = 9000")

    report = grade_trade_in(ctx["trade_in_id"], screen_grade="CRACKED",
                            battery_health_pct=55)
    assert_diagnostic_report(report)
    assert report["sequence_no"] == 1
    assert report["report_type"] == "INITIAL"
    assert report["technician_user_id"] == "u-tech-1"
    assert report["override_reason"] is None
    assert report["diagnostic_result"] == "PASS"
    assert report["derived_condition"] == "FAIR", (
        "a CRACKED screen implies FAIR and a 55 percent battery implies FAIR")
    assert report["condition_multiplier_bps"] == expected_condition_multiplier_bps("FAIR") == 6_000
    assert report["screen_deduction_cents"] == SCREEN_DEDUCTION_CENTS["CRACKED"] == 9_500
    assert report["battery_deduction_cents"] == expected_battery_deduction_cents(55) == 8_000

    rounded_product = apply_bps(base_credit, 6_000)
    assert rounded_product == 9_000
    unfloored = rounded_product - 9_500 - 8_000
    assert unfloored == -8_500, "the chain genuinely goes negative before the floor"
    assert report["computed_credit_cents"] == TRADE_IN_CREDIT_FLOOR_CENTS == 0
    assert report["computed_credit_cents"] != unfloored

    trade_in = read_trade_in(ctx["trade_in_id"])
    assert_trade_in(trade_in)
    assert trade_in["status"] == "GRADED"
    assert trade_in["graded_condition"] == "FAIR"
    assert trade_in["diagnostic_result"] == "PASS"
    assert trade_in["credit_final_cents"] == 0
    assert trade_in["latest_report_sequence_no"] == 1
    assert trade_in["credit_variance_cents"] == 0 - 9_000 == -9_000
    assert trade_in["settled_at"] is None

    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURNED", (
        "a PASS leaves the handset RETURNED; only a FAIL drives RETURN_FAILED")
    customer = read_customer(ctx["customer_id"])
    assert customer["credit_score_band"] == "PRIME"
    assert customer["credit_limit_cents"] == 250_000
    assert customer["status"] == "ACTIVE"
    assert read_upgrade_request(ctx["upgrade_request_id"])["trade_in_credit_projection_cents"] == 0


def test_trade_in_fail_credit_is_flat_ten_percent_with_deductions_recorded_but_unapplied(api):
    """A FAIL short-circuits the whole PASS chain: the same CRACKED / 55-percent handset
    that floors to 0 on a PASS instead yields a flat 1000 bps of base, 1500 cents, with
    the 9500 and 8000 deduction tiers still recorded on the report but never subtracted.

    PRD §3.9: "The report's `diagnostic_result` is `FAIL` when `water_damage_flag` is true **or** `functional_pass` is false, and `PASS` otherwise."
    PRD §3.9: "A `FAIL` report short-circuits all of that."
    PRD §3.9: "`derived_condition` is forced to `POOR`, and `computed_credit_cents` is the base credit multiplied by 1,000 basis points and divided by 10,000, rounded half up — a flat 10 percent of base, the program's diagnostic-failure credit."
    PRD §3.9: "The screen and battery deductions are **not** applied on a `FAIL`, although `screen_deduction_cents` and `battery_deduction_cents` still record the tier amounts the measurements selected."
    PRD §3.9: "A `FAIL` result drives the handset `RETURNED → RETURN_FAILED` and fires two cascade links."

    Design: Difficulty/combinatorial_formula/trade_in_final_credit_nested_min_max_deductions
    """
    ctx = setup_trade_in_received(
        declared_condition="FAIR",
        model_overrides={"display_name": "Handset H", "retail_price_cents": 45_000,
                         "monthly_protection_premium_cents": 599,
                         "trade_in_base_credit_cents": 15_000})
    assert ctx["trade_in"]["credit_estimate_cents"] == 9_000

    report = grade_trade_in(ctx["trade_in_id"], screen_grade="CRACKED",
                            battery_health_pct=55, functional_pass=False)
    assert_diagnostic_report(report)
    assert report["functional_pass"] is False
    assert report["water_damage_flag"] is False
    assert report["diagnostic_result"] == "FAIL", "functional_pass false alone forces FAIL"
    assert report["derived_condition"] == "POOR", (
        "a FAIL forces POOR regardless of the CRACKED/FAIR readings")
    assert report["screen_deduction_cents"] == 9_500, "the tier is still recorded"
    assert report["battery_deduction_cents"] == 8_000, "the tier is still recorded"

    assert report["computed_credit_cents"] == apply_bps(15_000, DIAGNOSTIC_FAIL_CREDIT_BPS)
    assert report["computed_credit_cents"] == 1_500
    assert report["computed_credit_cents"] != 1_500 - 9_500 - 8_000, (
        "the deductions must not be applied on a FAIL")
    assert report["computed_credit_cents"] != 0, (
        "a FAIL does not run the PASS chain, so it does not hit the zero floor here")
    assert report["computed_credit_cents"] != apply_bps(15_000, CONDITION_MULTIPLIERS_BPS["POOR"]), (
        "the FAIL credit is 1000 bps of base, not the POOR condition multiplier of 3000 bps")

    trade_in = read_trade_in(ctx["trade_in_id"])
    assert trade_in["status"] == "GRADED"
    assert trade_in["graded_condition"] == "POOR"
    assert trade_in["diagnostic_result"] == "FAIL"
    assert trade_in["credit_final_cents"] == 1_500
    assert trade_in["credit_variance_cents"] == 1_500 - 9_000 == -7_500

    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURN_FAILED"
    customer = read_customer(ctx["customer_id"])
    assert customer["credit_score_band"] == "NEAR_PRIME", "one notch down from PRIME"
    assert customer["credit_limit_cents"] == 150_000
    assert customer["status"] == "ACTIVE", (
        "a first-strike diagnostic failure costs a credit notch and nothing more")
    assert customer["financing_lock_reason"] is None
    assert read_upgrade_request(ctx["upgrade_request_id"])["trade_in_credit_projection_cents"] == 1_500


HANDSET_H_TARGET_PREMIUM_CENTS = 1_099


def _completion_ready_with_target_retail(retail_price_cents: int):
    """A completion-ready upgrade on the reference 24-month Handset B loan whose target
    model carries the given sticker price. The rollover carried forward is always 6964:
    quote total_payoff 38714 less the graded trade-in credit 31750.
    """
    ctx = setup_completion_ready(
        declared_condition="GOOD",
        measurements={"screen_grade": "SCRATCHED", "battery_health_pct": 78},
        target_model_overrides={
            "retail_price_cents": int(retail_price_cents),
            "monthly_protection_premium_cents": HANDSET_H_TARGET_PREMIUM_CENTS})
    assert ctx["trade_in"]["credit_final_cents"] == 31_750
    assert ctx["quote"]["quote_type"] == "UPGRADE_ROLLOVER"
    assert ctx["quote"]["total_payoff_cents"] == 38_714
    assert ctx["target_model"]["retail_price_cents"] == int(retail_price_cents)
    return ctx


def test_successor_loan_fee_tier_reads_pre_fee_base_below_one_hundred_thousand(api):
    """A pre-fee base of 99900 cents takes the 1500-cent middle-tier fee and finishes at a
    principal of 101400 cents; the principal crossing 100000 does not promote it to 2500.

    PRD §3.10: "The pre-fee base is then the target model's `retail_price_cents`, plus the net rollover, minus the excess credit — the new handset's sticker price, carrying forward whatever the old loan still owed and giving back whatever the trade-in over-covered."
    PRD §3.10: "The origination fee for the successor loan is tiered off that pre-fee base and nothing else: `origination_fee_cents` is 0 when the pre-fee base is below 60,000 cents, 1,500 cents when it is below 100,000 cents, and 2,500 cents otherwise."
    PRD §3.10: "The tier is keyed on the pre-fee base, never on the resulting `principal_cents` — a pre-fee base of 99,000 cents takes the 1,500-cent fee and finishes at a principal of 100,500 cents, and that principal crossing the 100,000-cent boundary does not retroactively promote it to the 2,500-cent tier."
    PRD §3.10: "The successor loan's `principal_cents` is the pre-fee base plus that fee, and its `rolled_over_balance_cents` records the net rollover so the carried-forward debt stays visible on the new agreement."
    PRD §3.10: "The successor inherits the predecessor's `term_months` unchanged and takes its `monthly_protection_premium_cents` from the target model, and its amortisation schedule is then generated by the ordinary origination arithmetic with `origination_date` set to the logical clock."

    Design: Difficulty/combinatorial_formula/new_loan_principal_fee_tier_keyed_on_pre_fee_base
    """
    ctx = _completion_ready_with_target_retail(92_936)
    new_loan = complete_upgrade(ctx["upgrade_request_id"], ctx["quote"]["id"])
    assert_loan(new_loan)
    assert_loan_ledger_invariants(new_loan)

    pre_fee_base = 92_936 + 6_964
    assert pre_fee_base == 99_900
    assert expected_origination_fee_cents(pre_fee_base) == 1_500
    assert new_loan["rolled_over_balance_cents"] == 6_964
    assert new_loan["origination_fee_cents"] == 1_500
    assert new_loan["principal_cents"] == 101_400
    assert new_loan["principal_cents"] > 100_000, (
        "the resulting principal crosses 100000 while the fee stays in the 1500 tier")
    assert new_loan["origination_fee_cents"] != 2_500

    assert new_loan["term_months"] == 24, "the successor inherits the predecessor's term"
    assert new_loan["monthly_protection_premium_cents"] == HANDSET_H_TARGET_PREMIUM_CENTS
    assert new_loan["premium_total_cents"] == 26_376
    assert new_loan["monthly_installment_cents"] == 5_324
    assert new_loan["obligation_balance_cents"] == 127_776
    assert new_loan["predecessor_loan_id"] == ctx["loan_id"]
    assert new_loan["status"] == "ACTIVE"
    assert new_loan["paid_installment_count"] == 0
    assert_iso_equals(new_loan["origination_date"], "2027-06-27T00:00:00.000Z",
                      "successor origination_date")

    base, last = expected_schedule_components(101_400, 24)
    assert (base, last) == (4_225, 4_225)
    schedule = read_installments(new_loan["id"])
    assert len(schedule) == 24
    assert all(row["principal_component_cents"] == 4_225 for row in schedule)
    assert all(row["amount_due_cents"] == 5_324 for row in schedule)
    assert_schedule_sums_to_principal(schedule, new_loan)
    assert_iso_equals(schedule[0]["due_date"], "2027-07-27T00:00:00.000Z")

    old_loan = read_loan(ctx["loan_id"])
    assert old_loan["status"] == "ROLLED_OVER"
    assert old_loan["closure_reason"] == "UPGRADE_ROLLOVER"
    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "COMPLETED"
    assert read_trade_in(ctx["trade_in_id"])["status"] == "SETTLED"
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 0


def test_successor_loan_fee_tier_at_exactly_one_hundred_thousand_pre_fee_base(api):
    """A pre-fee base of exactly 100000 cents is NOT below 100000, so it takes the top
    2500-cent fee and the principal comes out at 102500 cents.

    PRD §3.10: "The origination fee for the successor loan is tiered off that pre-fee base and nothing else: `origination_fee_cents` is 0 when the pre-fee base is below 60,000 cents, 1,500 cents when it is below 100,000 cents, and 2,500 cents otherwise."
    PRD §3.10: "The successor loan's `principal_cents` is the pre-fee base plus that fee, and its `rolled_over_balance_cents` records the net rollover so the carried-forward debt stays visible on the new agreement."
    PRD §3.3: "For the last installment — and only the last — `principal_component_cents` is instead the loan's `principal_cents` less the base figure multiplied by one fewer than `term_months`; this residual guarantees that the principal components sum to `principal_cents` exactly, and it means the final installment's principal share may come out either smaller or larger than the base figure."

    Design: Difficulty/combinatorial_formula/new_loan_principal_fee_tier_keyed_on_pre_fee_base
    """
    ctx = _completion_ready_with_target_retail(93_036)
    new_loan = complete_upgrade(ctx["upgrade_request_id"], ctx["quote"]["id"])
    assert_loan_ledger_invariants(new_loan)

    pre_fee_base = 93_036 + 6_964
    assert pre_fee_base == 100_000
    assert expected_origination_fee_cents(pre_fee_base) == 2_500
    assert new_loan["rolled_over_balance_cents"] == 6_964
    assert new_loan["origination_fee_cents"] == 2_500, (
        "100000 is not below 100000, so the boundary falls into the 'otherwise' tier")
    assert new_loan["principal_cents"] == 102_500
    assert new_loan["monthly_installment_cents"] == 5_370
    assert new_loan["premium_total_cents"] == 26_376
    assert new_loan["obligation_balance_cents"] == 128_876

    base, last = expected_schedule_components(102_500, 24)
    assert (base, last) == (4_271, 4_267)
    schedule = read_installments(new_loan["id"])
    assert len(schedule) == 24
    for row in schedule[:23]:
        assert row["principal_component_cents"] == 4_271
        assert row["amount_due_cents"] == 5_370
    assert schedule[23]["principal_component_cents"] == 4_267
    assert schedule[23]["amount_due_cents"] == 5_366
    assert_schedule_sums_to_principal(schedule, new_loan)


def test_successor_loan_fee_tier_zero_below_sixty_thousand_pre_fee_base(api):
    """A pre-fee base of 59999 cents sits one cent below the 60000 boundary, so the
    successor loan carries no origination fee at all and its principal equals the base.

    PRD §3.10: "The origination fee for the successor loan is tiered off that pre-fee base and nothing else: `origination_fee_cents` is 0 when the pre-fee base is below 60,000 cents, 1,500 cents when it is below 100,000 cents, and 2,500 cents otherwise."
    PRD §3.10: "The tier is keyed on the pre-fee base, never on the resulting `principal_cents` — a pre-fee base of 99,000 cents takes the 1,500-cent fee and finishes at a principal of 100,500 cents, and that principal crossing the 100,000-cent boundary does not retroactively promote it to the 2,500-cent tier."
    PRD §3.10: "The gross rollover is the quote's `total_payoff_cents` less the trade-in's `credit_final_cents`, floored at zero."

    Design: Difficulty/combinatorial_formula/new_loan_principal_fee_tier_keyed_on_pre_fee_base
    """
    ctx = _completion_ready_with_target_retail(53_035)
    new_loan = complete_upgrade(ctx["upgrade_request_id"], ctx["quote"]["id"])
    assert_loan_ledger_invariants(new_loan)

    pre_fee_base = 53_035 + 6_964
    assert pre_fee_base == 59_999
    assert expected_origination_fee_cents(pre_fee_base) == 0
    assert new_loan["origination_fee_cents"] == 0
    assert new_loan["principal_cents"] == 59_999 == pre_fee_base
    assert new_loan["rolled_over_balance_cents"] == 6_964
    assert new_loan["monthly_installment_cents"] == 3_599
    assert new_loan["premium_total_cents"] == 26_376
    assert new_loan["obligation_balance_cents"] == 86_375

    base, last = expected_schedule_components(59_999, 24)
    assert (base, last) == (2_500, 2_499)
    schedule = read_installments(new_loan["id"])
    assert len(schedule) == 24
    for row in schedule[:23]:
        assert row["principal_component_cents"] == 2_500
        assert row["amount_due_cents"] == 3_599
    assert schedule[23]["principal_component_cents"] == 2_499
    assert schedule[23]["amount_due_cents"] == 3_598
    assert_schedule_sums_to_principal(schedule, new_loan)
