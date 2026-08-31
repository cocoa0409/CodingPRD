"""Nexus determination, the obligation counter and the compliance posture."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_obligation_counter_matches,
    create_activity_record,
    create_registration,
    read_filing,
    read_group,
    read_registration,
    setup_approved_filing,
    setup_bare_registration,
    setup_group_with_members,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


def _threshold_scenario(destination_sales):
    """A TX profile whose only 2026 activity is receipts — no payroll, property or days."""
    ctx = setup_group_with_members(
        group_overrides={
            "name": "Threshold Traders", "everywhere_sales": 5000000,
            "everywhere_property": 1000000, "everywhere_payroll": 800000,
        },
        include_member_b=False,
    )
    registration = create_registration(
        ctx["group_id"], state_code="TX", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.0075, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
        economic_nexus_sales_threshold=500000,
        economic_nexus_employee_days_threshold=15,
    )
    ctx["registration_id"] = registration["id"]
    create_activity_record(registration["id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": destination_sales, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 0,
        "protected_solicitation_only": False,
    })
    return ctx


def test_receipts_one_cent_below_the_economic_threshold_leave_nexus_none(api):
    """PRD 3.2: "2. Otherwise the result is `ECONOMIC` when the total state receipts is greater than or equal to the registration's `economic_nexus_sales_threshold`. Receipts are compared at 2 decimal places, and the comparison is inclusive: a figure exactly equal to the threshold **does** attach economic nexus."
    PRD 3.2: "1. The result is `PHYSICAL` when unprotected activity exists **and** the maximum employee days is greater than or equal to the registration's `economic_nexus_employee_days_threshold`."
    PRD 2.9: "2. Otherwise the posture is `EXPOSED` if `open_registration_obligations` is at least 1."

    Design: Difficulty/boundary_precision_check/economic_nexus_receipts_threshold_exact_equality
    """
    ctx = _threshold_scenario(499999.99)

    registration = validate_success(
        api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2026}, TM)
    )

    assert registration["nexus_status"] == "NONE", (
        "499999.99 of receipts is one cent short of the 500000 threshold, "
        f"so the ladder must resolve NONE, got {registration['nexus_status']}"
    )
    assert registration["registration_status"] == "NOT_REQUIRED"

    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 0
    assert group["compliance_posture"] == "COMPLIANT"


def test_receipts_exactly_at_the_economic_threshold_attach_nexus(api):
    """PRD 3.2: "2. Otherwise the result is `ECONOMIC` when the total state receipts is greater than or equal to the registration's `economic_nexus_sales_threshold`. Receipts are compared at 2 decimal places, and the comparison is inclusive: a figure exactly equal to the threshold **does** attach economic nexus."
    PRD 3.2: "The evaluation writes the result into `nexus_status` and then runs a four-link cascade. When the result is `ECONOMIC` or `PHYSICAL` — whether the axis moved `NONE → ECONOMIC`, `NONE → PHYSICAL` or `PROTECTED_PL86272 → ECONOMIC` — the first link promotes a `registration_status` of `NOT_REQUIRED` to `REGISTRATION_REQUIRED`; the second link, caused by the first, increments the group's `open_registration_obligations` by 1; the third link, caused by the second, re-derives the group's `compliance_posture`, which turns from `COMPLIANT` to `EXPOSED` once the counter reaches 1; and the fourth link, caused by the third, demotes every `APPROVED` return of that group to `IN_REVIEW` and clears each one's `approver_user_id`."

    Design: Difficulty/boundary_precision_check/economic_nexus_receipts_threshold_exact_equality
    """
    ctx = _threshold_scenario(499999.99)
    validate_success(
        api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2026}, TM)
    )

    # One more cent of receipts takes the state to exactly 500000.00.
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 0.01, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 0,
        "protected_solicitation_only": False,
    })

    registration = validate_success(
        api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2026}, TM)
    )

    assert registration["nexus_status"] == "ECONOMIC", (
        "Receipts of exactly 500000.00 must attach economic nexus, "
        f"got {registration['nexus_status']}"
    )
    assert registration["registration_status"] == "REGISTRATION_REQUIRED"

    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 1
    assert group["compliance_posture"] == "EXPOSED"


def _two_state_obligation_scenario():
    ctx = setup_group_with_members(
        group_overrides={
            "name": "Obligation Count Co", "everywhere_sales": 7000000,
            "everywhere_property": 1500000, "everywhere_payroll": 1000000,
        },
        include_member_b=False,
    )
    reg_ca = create_registration(
        ctx["group_id"], state_code="CA", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.0884, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
    )
    reg_ny = create_registration(
        ctx["group_id"], state_code="NY", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.065, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
    )
    for registration, receipts in ((reg_ca, 900000), (reg_ny, 700000)):
        create_activity_record(registration["id"], {
            "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
            "destination_sales": receipts, "payroll_compensation": 0,
            "property_average_value": 0, "employee_days_in_state": 0,
            "protected_solicitation_only": False,
        })
    ctx["reg_ca_id"] = reg_ca["id"]
    ctx["reg_ny_id"] = reg_ny["id"]
    return ctx


def _group_registrations(api, group_id):
    rows, _ = validate_paginated(
        api.list_group_registrations(group_id, AUD, {"limit": 100, "offset": 0})
    )
    return rows


def test_obligation_counter_rises_with_each_discovered_registration_duty(api):
    """PRD 2.9: "`open_registration_obligations` is an integer counter, initialized to 0 when the group is created, whose value must at all times equal the number of `StateRegistration` rows belonging to that group whose `registration_status` is `REGISTRATION_REQUIRED`."
    PRD 2.9: "2. Otherwise the posture is `EXPOSED` if `open_registration_obligations` is at least 1."

    Design: Difficulty/compensating_invariant/registration_obligation_count_conserved_across_completion
    """
    ctx = _two_state_obligation_scenario()

    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 0
    assert group["compliance_posture"] == "COMPLIANT"
    assert_obligation_counter_matches(group, _group_registrations(api, ctx["group_id"]))

    validate_success(api.evaluate_nexus(ctx["reg_ca_id"], {"as_of_tax_year": 2026}, TM))
    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 1
    assert group["compliance_posture"] == "EXPOSED"
    assert_obligation_counter_matches(group, _group_registrations(api, ctx["group_id"]))

    validate_success(api.evaluate_nexus(ctx["reg_ny_id"], {"as_of_tax_year": 2026}, TM))
    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 2
    assert group["compliance_posture"] == "EXPOSED"
    assert_obligation_counter_matches(group, _group_registrations(api, ctx["group_id"]))


def test_completing_both_registrations_returns_the_counter_to_zero(api):
    """PRD 3.2: "A `TaxManager` supplies the `state_account_number` the revenue department issued; the axis moves `REGISTRATION_REQUIRED → REGISTERED`, `registered_on_date` is stamped from the logical clock, the group's `open_registration_obligations` decrements by 1, the group's `compliance_posture` is re-derived — returning `EXPOSED` to `COMPLIANT` once the counter reaches 0 — and the registration's `version` advances."
    PRD 2.9: "`open_registration_obligations` is an integer counter, initialized to 0 when the group is created, whose value must at all times equal the number of `StateRegistration` rows belonging to that group whose `registration_status` is `REGISTRATION_REQUIRED`."

    Design: Difficulty/compensating_invariant/registration_obligation_count_conserved_across_completion
    """
    ctx = _two_state_obligation_scenario()
    validate_success(api.evaluate_nexus(ctx["reg_ca_id"], {"as_of_tax_year": 2026}, TM))
    validate_success(api.evaluate_nexus(ctx["reg_ny_id"], {"as_of_tax_year": 2026}, TM))

    validate_success(api.complete_registration(
        ctx["reg_ca_id"], {"state_account_number": "CA-11112222"}, TM
    ))
    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 1
    assert group["compliance_posture"] == "EXPOSED"
    assert_obligation_counter_matches(group, _group_registrations(api, ctx["group_id"]))

    validate_success(api.complete_registration(
        ctx["reg_ny_id"], {"state_account_number": "NY-33334444"}, TM
    ))
    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 0, (
        "The obligation counter must return to its starting value of 0"
    )
    assert group["compliance_posture"] == "COMPLIANT"
    assert_obligation_counter_matches(group, _group_registrations(api, ctx["group_id"]))

    assert read_registration(ctx["reg_ca_id"])["registration_status"] == "REGISTERED"
    assert read_registration(ctx["reg_ny_id"])["registration_status"] == "REGISTERED"


def _approved_filing_plus_second_state():
    ctx = setup_approved_filing()
    reg_ny = create_registration(
        ctx["group_id"], state_code="NY", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.065, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
        economic_nexus_sales_threshold=500000,
    )
    create_activity_record(reg_ny["id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 600000, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 0,
        "protected_solicitation_only": False,
    })
    ctx["reg_ny_id"] = reg_ny["id"]
    return ctx


def test_discovering_nexus_elsewhere_opens_an_obligation_and_exposes_the_group(api):
    """PRD 3.2: "The evaluation writes the result into `nexus_status` and then runs a four-link cascade. When the result is `ECONOMIC` or `PHYSICAL` — whether the axis moved `NONE → ECONOMIC`, `NONE → PHYSICAL` or `PROTECTED_PL86272 → ECONOMIC` — the first link promotes a `registration_status` of `NOT_REQUIRED` to `REGISTRATION_REQUIRED`; the second link, caused by the first, increments the group's `open_registration_obligations` by 1; the third link, caused by the second, re-derives the group's `compliance_posture`, which turns from `COMPLIANT` to `EXPOSED` once the counter reaches 1; and the fourth link, caused by the third, demotes every `APPROVED` return of that group to `IN_REVIEW` and clears each one's `approver_user_id`."

    Design: Difficulty/transitive_cascade/nexus_evaluation_posture_demotes_approved_filing
    """
    ctx = _approved_filing_plus_second_state()

    group_before = read_group(ctx["group_id"])
    assert group_before["open_registration_obligations"] == 0
    assert group_before["compliance_posture"] == "COMPLIANT"

    registration = validate_success(
        api.evaluate_nexus(ctx["reg_ny_id"], {"as_of_tax_year": 2026}, TM)
    )

    assert registration["nexus_status"] == "ECONOMIC"
    assert registration["registration_status"] == "REGISTRATION_REQUIRED"

    group_after = read_group(ctx["group_id"])
    assert group_after["open_registration_obligations"] == 1
    assert group_after["compliance_posture"] == "EXPOSED"


def test_posture_flip_demotes_an_approved_return_in_a_different_state(api):
    """PRD 2.9: "When a re-derivation moves the posture from `COMPLIANT` to `EXPOSED`, every `StateFiling` belonging to that group whose `preparation_status` is `APPROVED` at that moment is demoted back to `IN_REVIEW`, its `approver_user_id` is cleared to null, and its `version` advances."
    PRD 3.7: "A `StateAnalyst` or a `Controller` moves the return `FACTORS_LOCKED → IN_REVIEW`, optionally attaching a `preparer_note`, and the service records that caller's `X-User-ID` as the return's `preparer_user_id`."

    Design: Difficulty/transitive_cascade/nexus_evaluation_posture_demotes_approved_filing
    """
    ctx = _approved_filing_plus_second_state()

    filing_before = read_filing(ctx["filing_id"])
    assert filing_before["preparation_status"] == "APPROVED"
    assert filing_before["approver_user_id"] == "controller-01"

    validate_success(api.evaluate_nexus(ctx["reg_ny_id"], {"as_of_tax_year": 2026}, TM))

    filing_after = read_filing(ctx["filing_id"])
    assert filing_after["preparation_status"] == "IN_REVIEW", (
        "The already-approved CA return must be knocked back to IN_REVIEW, "
        f"got {filing_after['preparation_status']}"
    )
    assert filing_after["approver_user_id"] is None, (
        "The demotion clears approver_user_id"
    )
    assert filing_after["preparer_user_id"] == "analyst-01", (
        "The demotion clears only the approver, never the preparer"
    )
    assert filing_after["version"] > filing_before["version"], (
        "A resource mutated as part of a cascade advances its own version"
    )


def test_withdrawn_registration_refuses_a_later_nexus_evaluation(api):
    """PRD 3.2: "Withdrawal retires a state profile permanently. A `TaxManager` supplies a `reason`, and the axis moves to `WITHDRAWN` from `NOT_REQUIRED`, from `REGISTRATION_REQUIRED` or from `REGISTERED`."
    PRD 3.2: "An evaluation may not be run at all against a withdrawn registration; that write, like every other write against such a row, is rejected with `ERR_REGISTRATION_WITHDRAWN`."

    Design: Corner/state_machines/withdrawn_registration_rejects_further_writes
    """
    ctx = setup_bare_registration(group_overrides={"name": "Withdraw Group"})

    withdrawn = validate_success(api.withdraw_registration(
        ctx["registration_id"], {"reason": "State exit completed"}, TM
    ))
    assert withdrawn["registration_status"] == "WITHDRAWN"

    response = api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2026}, TM)
    validate_error(response, ApiErrorId.ERR_REGISTRATION_WITHDRAWN.value)

    registration = read_registration(ctx["registration_id"])
    assert registration["nexus_status"] == "NONE"
    assert read_group(ctx["group_id"])["open_registration_obligations"] == 0
