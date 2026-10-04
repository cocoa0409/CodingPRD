"""Multi-hop cascades and the ledger invariants they move: contract validation
unlocking overrides, lapses assessing chargebacks, the office cap, termination
recomputation, surrender and immediate read consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_chargeback_balance_invariant,
    assert_policy_credit_conservation,
    fetch_advisor,
    fetch_credits,
    fetch_policy,
    get_success_data,
    new_advisor,
    new_office,
    new_policy,
    any_headers,
    md_headers,
    set_clock,
    setup_capped_office_hierarchy,
    setup_chargeback_balance_blocked,
    setup_contracted_rep,
    setup_hierarchy,
    setup_joint_case,
    make_financial_rep_headers,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The contract-validation cascade and the override chain it unlocks
# ---------------------------------------------------------------------------
def test_window_pass_validates_the_contract_and_the_advisor():
    """PRD §3.4: "the window's `status` becomes `PASSED`, its `evaluated_at` is
    stamped with the clock, and the contract validates outright — contract
    `contract_status` becomes `VALIDATED`, and the advisor's `contract_status`
    and `validation_posture` both become `VALIDATED`."

    Design: Difficulty/transitive_cascade/contract_validation_cascade_of_depth_four
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000)

    window = get_success_data(api_client.get_validation_period(ctx["window"]["id"], any_headers))
    assert window["achieved_production_cents"] == 204000
    assert window["status"] == "PASSED"

    contract = get_success_data(api_client.get_employment_contract(ctx["contract"]["id"], any_headers))
    assert contract["contract_status"] == "VALIDATED"

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["contract_status"] == "VALIDATED"
    assert advisor["validation_posture"] == "VALIDATED"
    assert advisor["orphan_pool_access"] is True


def test_contract_validation_unlocks_the_sponsoring_chain_overrides():
    """PRD §3.6: "each of the descendant's qualifying credits contributes an
    accrual equal to that credit's gross multiplied by the ancestor's rank rate,
    rounded half up to the nearest cent" ... "the result is the smaller of that
    sum and the ancestor's district office's `override_cap_cents`."

    Design: Difficulty/transitive_cascade/contract_validation_cascade_of_depth_four
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000)

    dd = fetch_advisor(ctx["dd"]["id"])
    md = fetch_advisor(ctx["md"]["id"])
    assert dd["override_income_cents"] == 6120, "round(204000 * 0.03)"
    assert md["override_income_cents"] == 4080, "round(204000 * 0.02)"

    refreshed_office = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 10200
    assert refreshed_office["override_paid_cents"] == (dd["override_income_cents"]
                                                      + md["override_income_cents"])


def test_the_descendant_passes_nothing_up_until_its_own_contract_validates():
    """PRD §3.6: "a descendant passes nothing up the chain until its own
    contract has validated."

    Design: Difficulty/transitive_cascade/contract_validation_cascade_of_depth_four
    """
    set_clock()
    office = new_office()
    md = new_advisor(office["id"], name="Early Managing", rank="MANAGING_DIRECTOR",
                     email_prefix="early.md")
    dd = new_advisor(office["id"], name="Early Director", rank="DISTRICT_DIRECTOR",
                     sponsor_id=md["id"], email_prefix="early.dd")
    rep = setup_contracted_rep(office["id"], name="Early Producer", sponsor_id=dd["id"],
                               email_prefix="early.rep")

    # The representative is ACTIVE_TRAINING and has not validated, yet writes a
    # policy and therefore carries a live credit.
    new_policy(rep["advisor"]["id"], annual_premium_cents=510000, policy_number="NM-EARLY-1")

    assert fetch_advisor(dd["id"])["override_income_cents"] == 0
    assert fetch_advisor(md["id"])["override_income_cents"] == 0


# ---------------------------------------------------------------------------
# The policy-lapse cascade into the chargeback ledger
# ---------------------------------------------------------------------------
def test_a_lapse_assesses_the_unearned_chargeback_and_moves_the_balance():
    """PRD §3.6: "when the completed-month count is at most 11, the assessed
    amount is the credit's gross multiplied by one minus the count divided by
    24, rounded half up to the nearest cent."
    PRD §2.8: "The completed-month count is the year difference times twelve
    plus the month difference, minus one when the lapse day-of-month falls
    earlier in the month than the issue day-of-month."

    Design: Difficulty/transitive_cascade/policy_lapse_cascade_to_chargeback_ledger
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000,
                          activate_policy=True)

    lapsed = validate_success(api_client.lapse_policy(ctx["policy"]["id"], "2026-07-10T00:00:00Z",
                                                      md_headers))
    assert lapsed["status"] == "LAPSED"
    assert lapsed["months_inforce"] == 6
    assert lapsed["lapse_date"].startswith("2026-07-10")

    credits = fetch_credits(ctx["policy"]["id"])
    primary = [c for c in credits if c["credit_type"] == "PRIMARY"][0]
    assert primary["status"] == "CHARGED_BACK"
    assert primary["chargeback_assessed_cents"] == 153000, "round(204000 * (1 - 6/24))"
    assert primary["credit_pct"] == pytest.approx(1.00)

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["chargeback_balance_cents"] == 153000
    assert_chargeback_balance_invariant(advisor, credits)


def test_a_lapse_leaves_the_accrued_overrides_standing():
    """PRD §3.6: "Because descendant eligibility is a *contract* dimension and
    not a posture dimension, the consequences are specific: neither a policy
    lapse nor a persistency demotion ever retroactively destroys an
    already-accrued override."

    Design: Difficulty/transitive_cascade/policy_lapse_cascade_to_chargeback_ledger
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000,
                          activate_policy=True)

    validate_success(api_client.lapse_policy(ctx["policy"]["id"], "2026-07-10T00:00:00Z", md_headers))

    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] == 6120
    assert fetch_advisor(ctx["md"]["id"])["override_income_cents"] == 4080
    refreshed_office = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 10200


def test_surrender_assesses_the_full_gross_commission():
    """PRD §3.6: "For a surrender, the assessed amount is the credit's full
    `gross_commission_cents`, regardless of how many months the policy was in
    force."

    Design: Corner/calculations/assessed_surrender_assesses_the_full_gross_commission
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000,
                          activate_policy=True)

    surrendered = validate_success(api_client.surrender_policy(ctx["policy"]["id"], md_headers))
    assert surrendered["status"] == "SURRENDERED"

    primary = [c for c in fetch_credits(ctx["policy"]["id"])
               if c["credit_type"] == "PRIMARY"][0]
    assert primary["chargeback_assessed_cents"] == 204000
    assert primary["chargeback_reason"] == "SURRENDER"
    assert primary["gross_commission_cents"] == 204000
    assert primary["status"] == "CHARGED_BACK"

    assert fetch_advisor(ctx["advisor"]["id"])["chargeback_balance_cents"] == 204000


def test_chargeback_balance_above_the_block_refuses_new_policy_activation():
    """PRD §3.6: "while the writing advisor's `chargeback_balance_cents` exceeds
    `CHARGEBACK_BLOCK_CENTS`, which is 500000 cents, both writing a new policy
    and submitting a joint work case are refused with
    `ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS` at the payment-required status."

    Design: Corner/validations/chargeback_balance_above_threshold_blocks_new_policy_activation
    """
    set_clock()
    office = new_office()
    ctx = setup_chargeback_balance_blocked(office["id"], premium=1600000,
                                           lapse_date="2026-01-10T00:00:00Z")

    advisor = ctx["advisor"]
    # A zero-completed-month lapse assesses the full 640000-cent gross.
    assert advisor["chargeback_balance_cents"] == 640000
    assert advisor["chargeback_balance_cents"] > 500000

    refused = api_client.activate_policy(ctx["new_policy"]["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS.value)

    still_issued = fetch_policy(ctx["new_policy"]["id"])
    assert still_issued["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# The office cap and the full-recompute semantics
# ---------------------------------------------------------------------------
def test_override_income_is_min_capped_by_the_office_cap():
    """PRD §3.6: "the office cap is applied once to the summed accrual: the
    result is the smaller of that sum and the ancestor's district office's
    `override_cap_cents`."

    Design: Corner/calculations/override_income_is_min_capped_by_the_office_cap
    """
    set_clock()
    ctx = setup_capped_office_hierarchy(cap_cents=1000, rate_pct=0.03, premium=510000)

    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] == 1000
    assert fetch_advisor(ctx["md"]["id"])["override_income_cents"] == 1000
    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] != 6120

    refreshed_office = get_success_data(api_client.get_district_office(ctx["office"]["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 2000


def test_override_income_fully_recomputes_on_termination_of_a_downline():
    """PRD §2.7: "All rollup fields in this system — `team_production_cents`,
    `override_income_cents`, ... — are recomputed from live source rows rather
    than incremented in place."
    PRD §3.8: "the removal of the terminated advisor's production removes its
    contribution to every ancestor's override at the next recompute, with no
    residual."

    Design: Corner/calculations/override_income_fully_recomputes_on_termination_of_a_downline
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000)

    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] == 6120
    assert fetch_advisor(ctx["md"]["id"])["override_income_cents"] == 4080

    terminated = validate_success(api_client.terminate_advisor(ctx["advisor"]["id"], md_headers))
    assert terminated["contract_status"] == "TERMINATED"
    assert terminated["validation_posture"] == "FAILED_POSTURE"

    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] == 0
    assert fetch_advisor(ctx["md"]["id"])["override_income_cents"] == 0
    refreshed_office = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 0
    assert fetch_advisor(ctx["dd"]["id"])["team_production_cents"] == 0


# ---------------------------------------------------------------------------
# Immediate read consistency
# ---------------------------------------------------------------------------
def test_derived_posture_fields_are_reconciled_on_the_read_after_a_cascade():
    """PRD §2.9: "It is recomputed on every child mutation and it is what gates
    the advisor's economics: it gates commission payout, renewal accrual,
    joint-work participation, and orphan reception."

    Design: Corner/cross_cutting_complexity_layers/derived_posture_fields_are_reconciled_on_read_after_a_cascade
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000)

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["validation_posture"] == "VALIDATED"
    assert advisor["insurance_license_status"] == "ACTIVE"
    assert advisor["appointment_status"] == "APPROVED"
    assert advisor["team_production_cents"] == 204000

    refreshed_office = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 10200
    assert fetch_advisor(ctx["dd"]["id"])["override_income_cents"] == 6120
    assert fetch_advisor(ctx["md"]["id"])["override_income_cents"] == 4080


def test_joint_case_split_credit_is_visible_in_the_submit_response_state():
    """PRD §3.6: "The `SPLIT_LEAD` credit to the joint case's `lead_advisor_id`
    takes the lead's raw share *rounded half up to the nearest cent*. The
    `SPLIT_SUPPORT` credit to the case's `support_advisor_id` takes the
    remainder — the case gross minus that rounded lead amount — and is never
    rounded independently."

    Design: Corner/consistency_model/joint_case_split_credit_is_visible_in_the_submit_response_state
    """
    set_clock()
    office = new_office()
    ctx = setup_joint_case(office["id"], split_pct_lead=0.6, annual_premium_cents=510000)

    policy_id = ctx["policy"]["id"]
    lead_id = ctx["lead"]["advisor"]["id"]
    support_id = ctx["support"]["advisor"]["id"]

    validate_success(api_client.submit_joint_work_case(ctx["case"]["id"],
                                                       make_financial_rep_headers(lead_id)))

    credits = fetch_credits(policy_id)
    lead_credit = [c for c in credits if c["credit_type"] == "SPLIT_LEAD"][0]
    support_credit = [c for c in credits if c["credit_type"] == "SPLIT_SUPPORT"][0]
    primary = [c for c in credits if c["credit_type"] == "PRIMARY"][0]

    assert lead_credit["advisor_id"] == lead_id
    assert lead_credit["gross_commission_cents"] == 122400
    assert support_credit["advisor_id"] == support_id
    assert support_credit["gross_commission_cents"] == 81600
    assert primary["status"] == "VOIDED"
    assert primary["gross_commission_cents"] == 0

    assert_policy_credit_conservation(credits)
    assert fetch_advisor(lead_id)["team_production_cents"] == 122400
    assert fetch_advisor(support_id)["team_production_cents"] == 81600