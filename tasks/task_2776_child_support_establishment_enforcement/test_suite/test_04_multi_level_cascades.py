"""
One request that settles a chain of dependent entities before it answers.

Each scenario here fires a single documented operation and then reads every
level the operation reaches, so the depth of the chain — and the fact that the
response already reflects the settled end state — is observable from the API
alone.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_START


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _order_with_a_partly_paid_charge_and_a_served_withholding_order() -> fx.Scenario:
    """
    An entered order at 75,000 cents carrying one part-paid charge and one
    served withholding order at a Minnesota employer.

    The clock is moved to 2026-08-20 before the money is posted so that the
    charge's due date of 2026-08-15 has passed: the case then really does carry
    arrears principal, which is what makes the withholding request include an
    arrears-recovery add-on and what makes the post-vacatur balance observable.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Xena Pike",
            "ssn_last4": "1212",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Yusuf Pike",
            "ssn_last4": "1313",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [
        fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)
    ]
    fx.set_clock("2026-08-20T00:00:00Z")
    scenario.payments = [fx.post_payment(scenario.case_id, 50000, source="DIRECT_PAY")]
    scenario.employer = fx.create_employer(
        state_code="MN",
        legal_name="Duluth Freight Lines",
        remittance_fee_cents=0,
    )
    scenario.withholding_order = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=234000,
    )
    scenario.withholding_order = fx.serve_withholding_order(scenario.iwo_id)
    scenario.reload_case()
    scenario.reload_employer()
    return scenario


def _settlement_offer_beside_an_active_licence_remedy() -> fx.Scenario:
    """
    Six unpaid monthly charges of 82,500 cents, a proposed seven-installment
    settlement, and an active licence suspension standing over the same case.

    The clock ends at 2027-03-04, one day past the contest deadline, so the
    remedy activates on the uncontested branch and the ledger has been carried
    through the 2027-02-28 month end.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Zoe Hartt",
            "ssn_last4": "1414",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Abel Hartt",
            "ssn_last4": "1515",
            "monthly_gross_income_cents": 330000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id,
        [
            "2026-08-01",
            "2026-09-01",
            "2026-10-01",
            "2026-11-01",
            "2026-12-01",
            "2027-01-01",
        ],
        due_day=15,
    )
    fx.set_clock("2027-02-01T00:00:00Z")
    fx.run_accrual(scenario.case_id)

    scenario.compromise_offer = fx.create_compromise_offer(
        scenario.case_id, installment_count=7
    )
    action = fx.propose_enforcement_action(scenario.case_id, "LICENSE_SUSPENSION")
    action = fx.send_enforcement_notice(action["id"])
    fx.set_clock("2027-03-04T00:00:00Z")
    scenario.enforcement_action = fx.activate_enforcement_action(action["id"])
    fx.run_accrual(scenario.case_id)
    scenario.reload_case()
    return scenario


# ---------------------------------------------------------------------------
# Vacatur: order, then charge and withholding order, then case and employer
# ---------------------------------------------------------------------------


def test_01_vacatur_reaches_the_charge_and_the_withholding_order_in_the_same_request():
    """
    One vacatur settles the order, its charge and its served withholding order.

    `terminated_date` is set to the current logical clock date. Every `OPEN` charge of the order becomes `VOID`.

    Design: Difficulty/transitive_cascade/order_vacatur_three_level_cascade_to_employer_counter
    """
    scenario = _order_with_a_partly_paid_charge_and_a_served_withholding_order()
    charge_id = scenario.charges[0]["id"]

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.charges[0]["status"] == "OPEN"
    assert scenario.withholding_order["service_status"] == "SERVED"

    version_before = fx.read_order(scenario.order_id)["version"]
    vacated = fx.vacate_order(scenario.order_id, "CLERICAL_ERROR")

    # Level one: the order itself.
    assert vacated["status"] == "VACATED"
    assert vacated["vacate_reason"] == "CLERICAL_ERROR"
    assert vacated["terminated_date"] == "2026-08-20"
    assert vacated["version"] == version_before + 1

    # Level two, first branch: the charge the order produced.
    assert fx.read_charge(charge_id)["status"] == "VOID"

    # Level two, second branch: the withholding order the order produced.
    terminated = fx.read_withholding_order(scenario.iwo_id)
    assert terminated["service_status"] == "TERMINATED"
    assert terminated["terminated_reason"] == "ORDER_VACATED"


def test_02_the_money_already_applied_comes_back_as_unapplied_credit():
    """
    The part-paid charge is voided anyway and its 50,000 cents is not lost.

    Any money that had already been applied to those charges is returned to the case's `unapplied_credit_cents`, so the ledger stays balanced rather than losing the payment.

    Design: Difficulty/transitive_cascade/order_vacatur_three_level_cascade_to_employer_counter
    """
    scenario = _order_with_a_partly_paid_charge_and_a_served_withholding_order()

    # The whole payment landed on the charge whose period contains 2026-08-20.
    assert scenario.payments[0]["applied_current_cents"] == 50000
    assert scenario.payments[0]["unapplied_credit_cents"] == 0
    part_paid = fx.read_charge(scenario.charges[0]["id"])
    assert part_paid["paid_cents"] == 50000
    assert part_paid["unpaid_balance_cents"] == 25000
    assert scenario.case["unapplied_credit_cents"] == 0
    assert scenario.case["total_charged_principal_cents"] == 75000
    # The due date of 2026-08-15 has passed, so the unpaid remainder is arrears.
    assert scenario.case["arrears_principal_cents"] == 25000

    fx.vacate_order(scenario.order_id, "CLERICAL_ERROR")

    settled = fx.read_case(scenario.case_id)
    assert settled["unapplied_credit_cents"] == 50000
    assert settled["version"] == scenario.case["version"] + 1


def test_03_voidance_by_cascade_empties_the_case_ledger_it_had_charged():
    """
    The voided charge leaves the charged total and the arrears balance behind.

    Voidance subtracts the charge's `amount_cents` from the case's `total_charged_principal_cents`, recomputes the case's `arrears_principal_cents`, and increases the case's `version` by 1 — the charge itself has no version to increase.

    Design: Difficulty/transitive_cascade/order_vacatur_three_level_cascade_to_employer_counter
    """
    scenario = _order_with_a_partly_paid_charge_and_a_served_withholding_order()

    fx.vacate_order(scenario.order_id, "CLERICAL_ERROR")

    settled = fx.read_case(scenario.case_id)
    assert settled["total_charged_principal_cents"] == 0
    assert settled["arrears_principal_cents"] == 0


def test_04_the_employer_withholding_counter_falls_at_the_far_end_of_the_chain():
    """
    A third-level entity, reached only through the terminated withholding order.

    Every withholding order of the vacated order that had reached `SERVED` or `AMENDED` becomes `TERMINATED` with `terminated_reason` `ORDER_VACATED`, and the corresponding employer's `active_iwo_count` is decremented for each one.

    Design: Difficulty/transitive_cascade/order_vacatur_three_level_cascade_to_employer_counter
    """
    scenario = _order_with_a_partly_paid_charge_and_a_served_withholding_order()

    # The request that produced the withholding order stood on real arrears.
    assert scenario.withholding_order["arrears_recovery_cents"] == 15000
    assert scenario.withholding_order["requested_amount_cents"] == 90000
    assert scenario.withholding_order["federal_cap_pct"] == 0.60
    assert scenario.withholding_order["ccpa_cap_amount_cents"] == 140400
    assert scenario.withholding_order["withholding_amount_cents"] == 90000
    assert scenario.employer["active_iwo_count"] == 1

    fx.vacate_order(scenario.order_id, "CLERICAL_ERROR")

    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 0


# ---------------------------------------------------------------------------
# Compromise acceptance: offer, then case, then remedy, then participant
# ---------------------------------------------------------------------------


def test_05_acceptance_stays_the_case_and_writes_off_the_waived_interest():
    """
    The obligor's own act moves the offer and the case in one request.

    Acceptance stamps `accepted_at` from the logical clock, sets `next_installment_due_date` to one month after the acceptance date, adds `interest_waiver_cents` to the case's `interest_written_off_cents` — which is what removes the waived interest from `interest_receivable_cents` — and sets the case's `enforcement_posture` to `STAYED`.

    Design: Difficulty/transitive_cascade/compromise_acceptance_cascade_releases_license_remedy
    """
    scenario = _settlement_offer_beside_an_active_licence_remedy()

    assert scenario.compromise_offer["status"] == "PROPOSED"
    assert scenario.compromise_offer["principal_due_snapshot_cents"] == 495000
    # The settlement figure is the ledger's aggregate measure at 2027-02-01.
    assert scenario.compromise_offer["interest_due_snapshot_cents"] == 8664
    assert scenario.compromise_offer["pre_waiver_total_cents"] == 503664
    assert scenario.compromise_offer["waiver_tier_pct"] == 0.50
    assert scenario.compromise_offer["interest_waiver_cents"] == 4332
    assert scenario.compromise_offer["settlement_total_cents"] == 499332
    assert scenario.case["enforcement_posture"] == "ESCALATED"
    assert scenario.case["interest_written_off_cents"] == 0

    accepted = fx.accept_compromise_offer(
        scenario.compromise_offer["id"], scenario.ncp_id
    )

    # Level one: the offer and the case.
    assert accepted["status"] == "ACCEPTED"
    a.assert_instant_equals(accepted["accepted_at"], "2027-03-04T00:00:00Z", "accepted_at")
    assert accepted["next_installment_due_date"] == "2027-04-04"
    assert accepted["compliance_payment_count"] == 0

    settled = fx.read_case(scenario.case_id)
    assert settled["enforcement_posture"] == "STAYED"
    assert settled["interest_written_off_cents"] == 4332


def test_06_the_stay_releases_the_active_remedy_with_a_reason_no_caller_supplied():
    """
    Nobody named a release reason and no attorney acted, yet the remedy is out.

    From `ACTIVE`, a compromise acceptance, an order vacatur or a case closure releases the remedy as a cascade, setting `release_reason` to `COMPROMISE_ACCEPTED` or `ORDER_VACATED` as appropriate rather than deriving it from a caller's input, and reversing the participant flag in full.

    Design: Difficulty/transitive_cascade/compromise_acceptance_cascade_releases_license_remedy
    """
    scenario = _settlement_offer_beside_an_active_licence_remedy()
    action = scenario.enforcement_action

    assert action["status"] == "ACTIVE"
    assert action["action_type"] == "LICENSE_SUSPENSION"
    assert action["remedy_applied"] is True
    a.assert_instant_equals(action["contest_deadline_at"], "2027-03-03T00:00:00Z", "contest_deadline_at")
    a.assert_instant_equals(action["activated_at"], "2027-03-04T00:00:00Z", "activated_at")
    assert action["release_reason"] is None or "release_reason" not in action

    fx.accept_compromise_offer(scenario.compromise_offer["id"], scenario.ncp_id)

    # Level two: the remedy the acceptance reached through the case.
    released = fx.read_enforcement_action(action["id"])
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "COMPROMISE_ACCEPTED"
    a.assert_instant_equals(released["released_at"], "2027-03-04T00:00:00Z", "released_at")
    assert released["remedy_applied"] is False


def test_07_the_release_restores_the_obligor_licence_flags_and_leaves_principal_alone():
    """
    The furthest level is the participant row, two entities from the offer.

    The stay is not merely a flag: every enforcement action on the case in `ACTIVE` *or* in `NOTICE_SENT` is released with a `release_reason` of `COMPROMISE_ACCEPTED`, and for the `ACTIVE` ones the participant remedy flags are reversed exactly as a manual release reverses them, so `license_suspension_active` becomes false with `has_valid_drivers_license` restored to true, `lien_recorded` becomes false and `credit_bureau_reported` becomes false.

    Design: Difficulty/transitive_cascade/compromise_acceptance_cascade_releases_license_remedy
    """
    scenario = _settlement_offer_beside_an_active_licence_remedy()

    obligor_before = fx.read_participant(scenario.ncp_id)
    assert obligor_before["license_suspension_active"] is True
    assert obligor_before["has_valid_drivers_license"] is False

    fx.accept_compromise_offer(scenario.compromise_offer["id"], scenario.ncp_id)

    obligor_after = fx.read_participant(scenario.ncp_id)
    assert obligor_after["license_suspension_active"] is False
    assert obligor_after["has_valid_drivers_license"] is True

    # Only interest is ever waived, so the principal is exactly where it was.
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 495000


def test_08_the_waiver_lands_on_receivable_without_touching_the_measured_interest():
    """
    The receivable falls by the waiver alone, from 11,139 cents to 6,807 cents.

    `interest_receivable_cents` is a computed field: the aggregate month-end interest total, less `interest_written_off_cents`, less `interest_collected_cents`, floored at zero so it never goes negative.

    Design: Difficulty/transitive_cascade/compromise_acceptance_cascade_releases_license_remedy
    """
    scenario = _settlement_offer_beside_an_active_licence_remedy()

    # Six month-end snapshots to 2027-01-31, plus the 2027-02-28 snapshot.
    assert scenario.case["interest_receivable_cents"] == 11139
    assert scenario.case["interest_collected_cents"] == 0

    fx.accept_compromise_offer(scenario.compromise_offer["id"], scenario.ncp_id)
    fx.run_accrual(scenario.case_id)

    settled = fx.read_case(scenario.case_id)
    assert settled["interest_written_off_cents"] == 4332
    assert settled["interest_receivable_cents"] == 6807
    ledger = fx.read_ledger(scenario.case_id)
    assert ledger["aggregate_interest_cents"] == 11139
    assert ledger["interest_receivable_cents"] == 6807
