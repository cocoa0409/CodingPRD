"""Two pinned evaluation orders in the money: round-per-line, and tier-then-discount."""
from test_helpers import (
    BILLING_INVOICED,
    COMPLAINT_UTI,
    SERVICE_EKG,
    SERVICE_INJECTION_ADMIN,
    SERVICE_RAPID_STREP_TEST,
    SERVICE_URINALYSIS,
    VISIT_CLOSED,
    accept_quote,
    checkout,
    create_insured_patient,
    create_patient,
    quote_self_pay,
    read_patient,
    read_visit,
    staffed_clinic,
    treated_visit,
    verify_active_coverage,
)

INSURED_SERVICES = [SERVICE_RAPID_STREP_TEST, SERVICE_URINALYSIS]
SELF_PAY_SERVICES = [SERVICE_INJECTION_ADMIN, SERVICE_EKG]


def _insured_visit_ready_for_checkout(api):
    """A cosigned, coverage-verified encounter for a 9900 protocol at 12.5 percent."""
    env = staffed_clinic(api, protocol={"requires_cosign": True})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Cora Covered",
        date_of_birth="1979-11-11", payer_name="BlueCo", member_id="M-2002",
        pcp_consent_on_file=False)
    env["patient"] = patient
    bundle = treated_visit(api, env, patient["id"], cosign=True)
    verify_active_coverage(api, env, bundle["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)
    env["bundle"] = bundle
    return env


def test_insured_checkout_rounds_each_line_before_summing_the_shares(api):
    """Line shares 1238, 438 and 350 plus the copay give 4526, never 4525.

    PRD: "The three line shares round to 1238, 438 and 350, summing with the copay
    to a patient responsibility of 4526 against a total allowed amount of 16200,
    leaving the payer 11674."

    Design: Difficulty/combinatorial_formula/checkout_rounds_each_line_then_sums_not_sum_then_round
    """
    env = _insured_visit_ready_for_checkout(api)

    visit = checkout(api, env, env["bundle"]["visit_id"],
                     services_rendered=INSURED_SERVICES)

    assert visit["final_price_cents"] == 16200
    assert visit["patient_responsibility_cents"] == 4526
    assert visit["patient_responsibility_cents"] != 4525
    assert visit["payer_responsibility_cents"] == 11674


def test_the_patient_and_payer_shares_add_up_to_the_final_price(api):
    """4526 plus 11674 is exactly the 16200 total allowed amount.

    PRD: "The invariant that must always hold is that the patient's share plus the
    payer's share equals `final_price_cents` exactly."

    Design: Difficulty/combinatorial_formula/checkout_rounds_each_line_then_sums_not_sum_then_round
    """
    env = _insured_visit_ready_for_checkout(api)

    checkout(api, env, env["bundle"]["visit_id"], services_rendered=INSURED_SERVICES)

    visit = read_visit(api, env["bundle"]["visit_id"])
    assert (visit["patient_responsibility_cents"] + visit["payer_responsibility_cents"]
            == visit["final_price_cents"] == 16200)
    assert visit["clinical_status"] == VISIT_CLOSED
    assert visit["billing_status"] == BILLING_INVOICED


def test_the_balance_is_recomputed_from_the_newly_invoiced_visit(api):
    """The patient owes exactly the 4526 the one invoiced visit put on them.

    PRD: "A patient's `outstanding_balance_cents` is the sum of
    `patient_responsibility_cents` across that patient's visits whose
    `billing_status` is `INVOICED`, and it is recomputed from scratch on every
    billing transition that touches the patient."

    Design: Difficulty/combinatorial_formula/checkout_rounds_each_line_then_sums_not_sum_then_round
    """
    env = _insured_visit_ready_for_checkout(api)

    checkout(api, env, env["bundle"]["visit_id"], services_rendered=INSURED_SERVICES)

    patient = read_patient(api, env["patient"]["id"])
    assert patient["outstanding_balance_cents"] == 4526


def _self_pay_visit_ready_for_checkout(api):
    """A treated, quote-accepted self-pay encounter on a 12000 UTI protocol."""
    env = staffed_clinic(api, protocol={"complaint_code": COMPLAINT_UTI,
                                        "min_age_months": 24,
                                        "base_price_cents": 12000,
                                        "red_flag_codes": ["FLANK_PAIN"],
                                        "requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Sam Selfpay",
                             date_of_birth="1985-06-06", pcp_consent_on_file=False)
    env["patient"] = patient
    bundle = treated_visit(api, env, patient["id"], complaint_code=COMPLAINT_UTI,
                           vitals={"temp_c": 37.1, "heart_rate_bpm": 78,
                                   "spo2_pct": 99})
    env["bundle"] = bundle
    env["quote"] = quote_self_pay(api, env, bundle["visit_id"])
    return env


def test_the_up_front_self_pay_quote_discounts_the_base_line_by_ten_percent(api):
    """A 12000 base sits in the ten-percent tier and quotes 10800.

    PRD: "A base of 12000 cents quotes 10800: the subtotal lands in the ten-percent
    tier, giving a discount of 1200."

    Design: Difficulty/combinatorial_formula/self_pay_tier_keyed_on_pre_discount_subtotal
    """
    env = _self_pay_visit_ready_for_checkout(api)

    assert env["quote"]["quoted_price_cents"] == 10800
    assert env["quote"]["self_pay"] is True


def test_the_final_total_takes_its_tier_from_the_pre_discount_subtotal(api):
    """A 22700 subtotal discounts 3405 to 19295, not the post-discount 20430.

    PRD: "Selecting the tier from the discounted total instead of the subtotal is
    the forbidden reading — it would make the tier depend on the discount the tier
    itself defines."

    Design: Difficulty/combinatorial_formula/self_pay_tier_keyed_on_pre_discount_subtotal
    """
    env = _self_pay_visit_ready_for_checkout(api)
    accept_quote(api, env["bundle"]["visit_id"], 10800,
                 patient_id=env["patient"]["id"])

    visit = checkout(api, env, env["bundle"]["visit_id"],
                     services_rendered=SELF_PAY_SERVICES)

    assert visit["final_price_cents"] == 19295
    assert visit["final_price_cents"] != 20430


def test_a_self_pay_invoice_puts_the_whole_discounted_total_on_the_patient(api):
    """No payer participates, so the patient carries all 19295 cents.

    PRD: "For a self-pay visit the total allowed amount is run through the self-pay
    discount of §3.5 — subtotal first, tier from the subtotal, one rounded aggregate
    discount, then subtraction — and the discounted figure becomes
    `final_price_cents`, with `patient_responsibility_cents` equal to it and
    `payer_responsibility_cents` set to 0, since no payer is involved."

    Design: Difficulty/combinatorial_formula/self_pay_tier_keyed_on_pre_discount_subtotal
    """
    env = _self_pay_visit_ready_for_checkout(api)
    accept_quote(api, env["bundle"]["visit_id"], 10800,
                 patient_id=env["patient"]["id"])

    visit = checkout(api, env, env["bundle"]["visit_id"],
                     services_rendered=SELF_PAY_SERVICES)

    assert visit["patient_responsibility_cents"] == 19295
    assert visit["payer_responsibility_cents"] == 0
    assert visit["billing_status"] == BILLING_INVOICED
    patient = read_patient(api, env["patient"]["id"])
    assert patient["outstanding_balance_cents"] == 19295
