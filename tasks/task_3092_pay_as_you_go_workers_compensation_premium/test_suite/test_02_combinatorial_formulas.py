"""Combinatorial formulas: remuneration basis branching and pinned rounding order."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    TEST_USERS, api_client, class_code_entry, create_and_bind_policy,
    create_employer, payroll_line, set_clock, setup_rating_table,
    sole_invoice_for_report, submit_report, validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def _ca_nv_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    setup_rating_table("NV")
    employer = create_employer(legal_name="Basis Branching Co",
                               fein="12-3456780",
                               contact_email="ops@basis.example",
                               home_state="CA")
    return create_and_bind_policy(
        employer["id"], policy_number="WC-BAS-001", experience_mod=1.1,
        class_codes=[class_code_entry("CA", "8810", 250000000),
                     class_code_entry("CA", "5645", 400000000),
                     class_code_entry("NV", "8810", 150000000)])


def test_net_ot_state_excludes_ot_premium_from_remuneration_basis(api):
    """PRD §3.3: "Severance is always excluded: the base is the line's
    gross_wages_cents minus its severance_cents. When the line's state table
    declares an ot_basis of NET, the ot_premium_cents are subtracted as well; in a
    GROSS state the overtime premium half stays in, so identical gross wages yield
    a lower basis in a NET state than in a GROSS one."

    Design: Difficulty/combinatorial_formula/remuneration_basis_branching_net_ot_severance_and_exec_cap
    """
    policy = _ca_nv_policy()
    report = submit_report(
        policy["id"], "bas-run-001",
        period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        lines=[payroll_line("CA", "5645", gross_wages_cents=200000,
                            ot_premium_cents=10000, headcount=2),
               payroll_line("NV", "8810", gross_wages_cents=600000,
                            severance_cents=50000,
                            executive_wages_cents=250000, headcount=1)])

    lines, _meta = validate_paginated(api.list_report_lines(report["id"], UW))
    assert len(lines) == 2
    by_state = {line["state_code"]: line for line in lines}
    # NET state: 200000 - 0 severance - 10000 OT premium = 190000.
    assert by_state["CA"]["remuneration_basis_cents"] == 190000, (
        "a GROSS-basis treatment would leave 200000; the NET branch must bite")


def test_gross_state_executive_cap_min_applies_after_severance(api):
    """PRD §3.3: "the includable executive component is the lesser of
    executive_wages_cents and the week count times the state's
    max_payroll_per_executive_cents; the non-executive component is the base minus
    the full executive_wages_cents, floored at zero. The line's
    remuneration_basis_cents is the non-executive component plus the capped
    executive component."

    Design: Difficulty/combinatorial_formula/remuneration_basis_branching_net_ot_severance_and_exec_cap
    """
    policy = _ca_nv_policy()
    report = submit_report(
        policy["id"], "bas-run-002",
        period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        lines=[payroll_line("NV", "8810", gross_wages_cents=600000,
                            severance_cents=50000,
                            executive_wages_cents=250000, headcount=1)])

    lines, _meta = validate_paginated(api.list_report_lines(report["id"], UW))
    line = lines[0]
    # GROSS state, one-week period: base 600000 - 50000 = 550000;
    # executive component min(250000, 1 * 200000) = 200000;
    # non-executive 550000 - 250000 = 300000; basis 300000 + 200000 = 500000.
    assert line["remuneration_basis_cents"] == 500000, (
        "an uncapped executive treatment would leave 550000; the min() must bite")


def _rounding_policy():
    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api_client.create_state_rating_table({
        "state_code": "CA",
        "effective_from": "2027-01-01T00:00:00Z",
        "effective_to": "2028-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 250,
        "expense_constant_cents": 30000,
        "min_payroll_threshold_cents": 0,
        "state_minimum_premium_cents": 0,
        "ot_basis": "NET",
        "class_rates": [{"class_code": "8745", "rate_per_100_cents": 889}],
        "max_payroll_per_executive_cents": 250000,
    }, ADMIN))
    employer = create_employer(legal_name="Rounding Ranches LLC",
                               fein="11-2222333",
                               contact_email="books@rounding.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-RND-003",
        effective_date="2027-01-01T00:00:00Z",
        expiry_date="2028-01-01T00:00:00Z", experience_mod=1.0,
        class_codes=[class_code_entry("CA", "8745", 1000000)],
        _clock="2027-01-01T00:00:00Z")
    return policy


def test_per_line_premium_rounded_half_up_before_summation(api):
    """PRD §3.3: "each line's premium is its remuneration_basis_cents multiplied by
    the rate_per_100_cents for its state and class from the rating table effective
    over the period, divided by ten thousand — the per-hundred-dollars factor and
    the cents conversion combined — and rounded half up to whole cents. Rounding is
    per line, before any summation; summing exact fractions and rounding once is
    forbidden because it yields different cents."

    Design: Difficulty/combinatorial_formula/manual_premium_round_per_line_then_sum_pinned
    """
    policy = _rounding_policy()
    report = submit_report(
        policy["id"], "rnd-run-001",
        period_start="2027-01-01T00:00:00Z", period_end="2027-01-08T00:00:00Z",
        lines=[payroll_line("CA", "8745", gross_wages_cents=200001),
               payroll_line("CA", "8745", gross_wages_cents=200001)])

    invoice = sole_invoice_for_report(policy["id"], report["id"])
    # Per line: round_half_up(200001 * 889 / 10000) = round_half_up(17780.0889)
    # = 17780; manual = 2 * 17780 = 35560.
    assert invoice["manual_premium_cents"] == 35560


def test_invoice_total_uses_the_per_line_rounded_manual_premium(api):
    """PRD §3.3: "The invoice's premium_after_mod_cents is the sum of the
    substituted state subtotals, and its total_cents is that sum plus the
    per-capita fees plus the single expense constant."

    Design: Difficulty/combinatorial_formula/manual_premium_round_per_line_then_sum_pinned
    """
    policy = _rounding_policy()
    report = submit_report(
        policy["id"], "rnd-run-001",
        period_start="2027-01-01T00:00:00Z", period_end="2027-01-08T00:00:00Z",
        lines=[payroll_line("CA", "8745", gross_wages_cents=200001),
               payroll_line("CA", "8745", gross_wages_cents=200001)])

    invoice = sole_invoice_for_report(policy["id"], report["id"])
    # 35560 post-mod at 1.0 + per-capita 2 * 250 + expense constant 30000.
    assert invoice["per_capita_fees_cents"] == 500
    assert invoice["expense_constant_cents"] == 30000
    assert invoice["total_cents"] == 66060
