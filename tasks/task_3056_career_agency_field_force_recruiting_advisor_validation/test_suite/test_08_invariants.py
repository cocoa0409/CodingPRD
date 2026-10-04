"""Compensating actions and their conserved quantities: reinstatement versus the
unrecovered chargeback balance, and joint-case void versus the per-policy credit
sum."""
import pytest

from test_helpers import (
    api_client,
    assert_chargeback_balance_invariant,
    assert_policy_credit_conservation,
    fetch_advisor,
    fetch_credits,
    fetch_policy,
    get_success_data,
    make_financial_rep_headers,
    new_office,
    any_headers,
    md_headers,
    set_clock,
    setup_hierarchy,
    setup_joint_case,
    validate_success,
)


# ---------------------------------------------------------------------------
# Reinstatement and the chargeback balance
# ---------------------------------------------------------------------------
def _lapsed_with_chargeback(office_id: str, premium: int = 510000, months: int = 6):
    """A VALIDATED representative with an in-force policy, then lapsed."""
    ctx = setup_hierarchy(office_id, premium=premium, required_production_cents=100000,
                          activate_policy=True)
    validate_success(api_client.lapse_policy(ctx["policy"]["id"], "2026-07-10T00:00:00Z",
                                             md_headers))
    ctx["primary"] = [c for c in fetch_credits(ctx["policy"]["id"])
                      if c["credit_type"] == "PRIMARY"][0]
    return ctx


def test_a_partial_recovery_reduces_the_chargeback_balance():
    """PRD §3.6: "A successful recovery adds the amount to `recovered_cents`
    and subtracts it from the advisor's `chargeback_balance_cents`."

    Design: Difficulty/compensating_invariant/reinstatement_preserves_only_unrecovered_chargeback_balance
    """
    set_clock()
    office = new_office()
    ctx = _lapsed_with_chargeback(office["id"])
    assert fetch_advisor(ctx["advisor"]["id"])["chargeback_balance_cents"] == 153000

    recovered = validate_success(api_client.recover_commission_credit(
        ctx["primary"]["id"], 100000, md_headers))
    assert recovered["recovered_cents"] == 100000

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["chargeback_balance_cents"] == 53000, "153000 - 100000"
    assert_chargeback_balance_invariant(advisor, fetch_credits(ctx["policy"]["id"]))


def test_reinstatement_clears_the_assessed_remainder_without_refunding_recoveries():
    """PRD §3.6: "Every credit of that policy that is currently `CHARGED_BACK`
    reverts to `PAID`, with `chargeback_assessed_cents` reset to zero and
    `chargeback_reason` reset to null, while `recovered_cents` is left
    **unchanged**."
    PRD §2.7: "reversing a partly recovered chargeback leaves a credit in the
    advisor's favour equal to exactly the recovered amount; money already
    recovered is never refunded, and any reversal that pays recovered money back
    breaks the invariant."

    Design: Difficulty/compensating_invariant/reinstatement_preserves_only_unrecovered_chargeback_balance
    """
    set_clock()
    office = new_office()
    ctx = _lapsed_with_chargeback(office["id"])

    validate_success(api_client.recover_commission_credit(ctx["primary"]["id"], 100000, md_headers))
    assert fetch_advisor(ctx["advisor"]["id"])["chargeback_balance_cents"] == 53000

    reinstated = validate_success(api_client.reinstate_policy(ctx["policy"]["id"], md_headers))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["lapse_date"] is None

    credit = get_success_data(api_client.get_commission_credit(ctx["primary"]["id"], any_headers))
    assert credit["status"] == "PAID"
    assert credit["chargeback_assessed_cents"] == 0
    assert credit["recovered_cents"] == 100000, "the resumed money is never returned"

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["chargeback_balance_cents"] == 0
    assert advisor["chargeback_balance_cents"] != -100000


def test_reinstatement_restores_the_original_gross_commission():
    """PRD §3.6: "the `PRIMARY` credit is restored to `credit_pct` 1.00 with its
    `gross_commission_cents` recomputed."

    Design: Difficulty/compensating_invariant/reinstatement_preserves_only_unrecovered_chargeback_balance
    """
    set_clock()
    office = new_office()
    ctx = _lapsed_with_chargeback(office["id"])

    validate_success(api_client.reinstate_policy(ctx["policy"]["id"], md_headers))

    credit = get_success_data(api_client.get_commission_credit(ctx["primary"]["id"], any_headers))
    assert credit["gross_commission_cents"] == 204000
    assert credit["credit_pct"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Joint-case void and per-policy credit conservation
# ---------------------------------------------------------------------------
def _submitted_joint_case(office_id: str, split_pct_lead: float = 0.6):
    ctx = setup_joint_case(office_id, split_pct_lead=split_pct_lead,
                           annual_premium_cents=510000)
    lead_id = ctx["lead"]["advisor"]["id"]
    validate_success(api_client.submit_joint_work_case(ctx["case"]["id"],
                                                       make_financial_rep_headers(lead_id)))
    return ctx


def test_submitting_a_joint_case_reallocates_the_policy_credits():
    """PRD §3.6: "When the policy *does* have a joint case in `SUBMITTED`, the
    allocation splits" ... "The `PRIMARY` credit is simultaneously voided, set
    to `gross_commission_cents` zero and `credit_pct` 0.00."

    Design: Difficulty/compensating_invariant/joint_case_void_restores_the_primary_credit_exactly
    """
    set_clock()
    office = new_office()
    ctx = _submitted_joint_case(office["id"], split_pct_lead=0.6)

    credits = fetch_credits(ctx["policy"]["id"])
    lead_credit = [c for c in credits if c["credit_type"] == "SPLIT_LEAD"][0]
    support_credit = [c for c in credits if c["credit_type"] == "SPLIT_SUPPORT"][0]
    primary = [c for c in credits if c["credit_type"] == "PRIMARY"][0]

    assert lead_credit["gross_commission_cents"] == 122400
    assert support_credit["gross_commission_cents"] == 81600
    assert primary["status"] == "VOIDED"
    assert primary["gross_commission_cents"] == 0

    case = get_success_data(api_client.get_joint_work_case(ctx["case"]["id"], any_headers))
    assert case["status"] == "SUBMITTED"


def test_voiding_a_submitted_joint_case_restores_the_primary_credit_exactly():
    """PRD §3.6: "Voiding a submitted joint case reverses this precisely: the
    `SPLIT_LEAD` and `SPLIT_SUPPORT` credits are set to `VOIDED`, and the
    `PRIMARY` credit is restored to `credit_pct` 1.00 with
    `gross_commission_cents` recomputed to the case gross."
    PRD §2.7: "the sum of `gross_commission_cents` over that policy's
    non-`VOIDED` credits of type `PRIMARY`, `SPLIT_LEAD`, and `SPLIT_SUPPORT`
    must equal `case_gross_commission_cents` exactly, to the cent."

    Design: Difficulty/compensating_invariant/joint_case_void_restores_the_primary_credit_exactly
    """
    set_clock()
    office = new_office()
    ctx = _submitted_joint_case(office["id"], split_pct_lead=0.6)
    policy_id = ctx["policy"]["id"]
    lead_id = ctx["lead"]["advisor"]["id"]
    support_id = ctx["support"]["advisor"]["id"]

    voided = validate_success(api_client.void_joint_work_case(ctx["case"]["id"], md_headers))
    assert voided["status"] == "VOIDED"

    credits = fetch_credits(policy_id)
    primary = [c for c in credits if c["credit_type"] == "PRIMARY"][0]
    splits = [c for c in credits if c["credit_type"] in ("SPLIT_LEAD", "SPLIT_SUPPORT")]

    assert primary["status"] != "VOIDED"
    assert primary["credit_pct"] == pytest.approx(1.00)
    assert primary["gross_commission_cents"] == 204000
    assert all(c["status"] == "VOIDED" for c in splits)
    assert all(c["gross_commission_cents"] == 0 for c in splits)

    assert_policy_credit_conservation(credits)
    assert primary["case_gross_commission_cents"] == 204000

    assert fetch_advisor(lead_id)["team_production_cents"] == 204000
    assert fetch_advisor(support_id)["team_production_cents"] == 0


def test_the_split_remainder_lands_on_the_support_advisor():
    """PRD §3.6: "The `SPLIT_SUPPORT` credit to the case's `support_advisor_id`
    takes the remainder — the case gross minus that rounded lead amount — and is
    never rounded independently. The one-cent residual, which may be either plus
    or minus one cent, lands on the support advisor by construction."

    Design: Difficulty/compensating_invariant/joint_case_void_restores_the_primary_credit_exactly
    """
    set_clock()
    office = new_office()
    # A premium chosen so the split is not exact: 0.6 of 205333 is 123199.8.
    ctx = setup_joint_case(office["id"], split_pct_lead=0.6, annual_premium_cents=513333)
    lead_id = ctx["lead"]["advisor"]["id"]
    validate_success(api_client.submit_joint_work_case(ctx["case"]["id"],
                                                       make_financial_rep_headers(lead_id)))

    credits = fetch_credits(ctx["policy"]["id"])
    lead_credit = [c for c in credits if c["credit_type"] == "SPLIT_LEAD"][0]
    support_credit = [c for c in credits if c["credit_type"] == "SPLIT_SUPPORT"][0]
    case_gross = lead_credit["case_gross_commission_cents"]

    assert lead_credit["gross_commission_cents"] + support_credit["gross_commission_cents"] == case_gross
    assert_policy_credit_conservation(credits)


def test_the_policy_carries_one_case_gross_value_on_every_credit_row():
    """PRD §2.7: "Every commission credit row belonging to a policy carries
    `case_gross_commission_cents`, and that value is the policy's first-year
    gross commission, identical on every credit row of that policy."

    Design: Difficulty/compensating_invariant/joint_case_void_restores_the_primary_credit_exactly
    """
    set_clock()
    office = new_office()
    ctx = _submitted_joint_case(office["id"], split_pct_lead=0.6)

    credits = fetch_credits(ctx["policy"]["id"])
    values = {c["case_gross_commission_cents"] for c in credits}
    assert values == {204000}, "case_gross_commission_cents must be identical on every row"
    assert_policy_credit_conservation(credits)