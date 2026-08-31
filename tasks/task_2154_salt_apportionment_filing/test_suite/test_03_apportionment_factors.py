"""Computing the sales, property and payroll apportionment factors."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_apportionment_factor,
    assert_money,
    assert_ratio,
    compute_factors,
    create_activity_record,
    create_filing,
    factor_by_type,
    list_factors,
    read_filing,
    setup_bare_registration,
    setup_computed_filing,
    setup_draft_filing,
    setup_state_profile,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import REFERENCE_MODIFICATIONS
from test_helpers.fixtures import add_modification

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


# ─── JOYCE versus FINNIGAN ────────────────────────────────────────────────────

def test_joyce_and_finnigan_diverge_on_the_same_return(api):
    """PRD 3.4: "Under `JOYCE`, a record counts toward the numerators only if its own member is taxable in the state — a P.L. 86-272 protected member contributes nothing to the sales, property or payroll numerators while still sitting inside the everywhere denominators. Under `FINNIGAN`, every in-scope record counts regardless of its member's own taxability, so a protected member's destination sales, market-sourced services, property and payroll all flow into the numerators."
    PRD 3.5: "The return's `state_taxable_income` is that apportionable income multiplied by the return's `apportionment_percentage`, rounded half up to 2 decimal places. The return's `tax_before_credits` is `state_taxable_income` multiplied by the registration's `tax_rate`, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/joyce_vs_finnigan_apportionment_divergence
    """
    ctx = setup_draft_filing()
    assert_money(ctx["filing"]["modification_total"], 676.57, "modification_total")

    joyce = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )
    assert joyce["apportionment_variant"] == "JOYCE"
    assert_ratio(joyce["apportionment_percentage"], 0.200000, "JOYCE apportionment_percentage")
    assert_money(joyce["state_taxable_income"], 1000135.31, "JOYCE state_taxable_income")
    assert_money(joyce["tax_before_credits"], 88411.96, "JOYCE tax_before_credits")

    finnigan = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "FINNIGAN"}, SA)
    )
    assert finnigan["apportionment_variant"] == "FINNIGAN"
    assert_ratio(finnigan["apportionment_percentage"], 0.245000,
                 "FINNIGAN apportionment_percentage")
    assert_money(finnigan["state_taxable_income"], 1225165.76,
                 "FINNIGAN state_taxable_income")
    assert_money(finnigan["tax_before_credits"], 108304.65, "FINNIGAN tax_before_credits")


def test_joyce_and_finnigan_factor_numerators_differ_by_the_protected_member(api):
    """PRD 3.4: "Each run of the computation creates or replaces exactly three `ApportionmentFactor` rows for the return — one with `factor_type` `SALES`, one `PROPERTY`, one `PAYROLL` — each carrying its own `filing_id`, `numerator`, `denominator`, `ratio`, `weight`, `included`, `throwback_added` and `throwout_removed`."
    PRD 3.4: "Under `JOYCE`, a record counts toward the numerators only if its own member is taxable in the state — a P.L. 86-272 protected member contributes nothing to the sales, property or payroll numerators while still sitting inside the everywhere denominators. Under `FINNIGAN`, every in-scope record counts regardless of its member's own taxability, so a protected member's destination sales, market-sourced services, property and payroll all flow into the numerators."

    Design: Difficulty/dual_variant_calc/joyce_vs_finnigan_apportionment_divergence
    """
    ctx = setup_draft_filing()

    compute_factors(ctx["filing_id"], "JOYCE")
    rows = list_factors(ctx["filing_id"])
    assert len(rows) == 3, f"Expected exactly three factor rows, got {len(rows)}"
    for row in rows:
        assert_apportionment_factor(row)

    sales = factor_by_type(rows, "SALES")
    assert_money(sales["numerator"], 1500000, "JOYCE SALES numerator")
    assert_money(sales["denominator"], 10000000, "JOYCE SALES denominator")
    assert_ratio(sales["ratio"], 0.150000, "JOYCE SALES ratio")
    payroll = factor_by_type(rows, "PAYROLL")
    assert_money(payroll["numerator"], 500000, "JOYCE PAYROLL numerator")
    assert_ratio(payroll["ratio"], 0.250000, "JOYCE PAYROLL ratio")
    assert_ratio(factor_by_type(rows, "PROPERTY")["ratio"], 0.250000,
                 "JOYCE PROPERTY ratio")

    compute_factors(ctx["filing_id"], "FINNIGAN")
    rows = list_factors(ctx["filing_id"])
    assert len(rows) == 3, "The run replaces the three rows rather than adding more"
    sales = factor_by_type(rows, "SALES")
    assert_money(sales["numerator"], 2150000, "FINNIGAN SALES numerator")
    assert_ratio(sales["ratio"], 0.215000, "FINNIGAN SALES ratio")
    payroll = factor_by_type(rows, "PAYROLL")
    assert_money(payroll["numerator"], 600000, "FINNIGAN PAYROLL numerator")
    assert_ratio(payroll["ratio"], 0.300000, "FINNIGAN PAYROLL ratio")
    assert_ratio(factor_by_type(rows, "PROPERTY")["ratio"], 0.250000,
                 "The protected member holds no property, so PROPERTY is unchanged")


# ─── Excluded factors and weight renormalization ──────────────────────────────

def _zero_property_scenario():
    return setup_draft_filing(
        group_overrides={"name": "Zero Property Holdings", "everywhere_property": 0},
        complete_registration=False,
    )


def test_zero_denominator_excludes_the_property_factor_and_renormalizes(api):
    """PRD 3.4: "A factor is `included` when its denominator is greater than zero, and excluded when its denominator is exactly zero. An included factor's `ratio` is its numerator divided by its denominator, rounded half up to 6 decimal places; an excluded factor's `ratio` is 0."
    PRD 3.4: "Otherwise each included factor's `weight` is its base weight divided by that weight denominator, rounded half up to 6 decimal places, and every excluded factor's `weight` is 0."
    PRD 3.4: "Base weights come from the registration's `factor_formula`: `EQUAL_WEIGHTED_THREE` gives sales, property and payroll a base weight of 1 each; `DOUBLE_WEIGHTED_SALES` gives sales a base weight of 2 and property and payroll 1 each; `SINGLE_SALES_FACTOR` gives sales a base weight of 1 and gives property and payroll a base weight of 0."

    Design: Difficulty/combinatorial_formula/factor_weight_renormalization_on_zero_denominator
    """
    ctx = _zero_property_scenario()

    validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )
    rows = list_factors(ctx["filing_id"])

    prop = factor_by_type(rows, "PROPERTY")
    assert prop["denominator"] == 0
    assert prop["included"] is False, "A factor with a zero denominator is excluded"
    assert_ratio(prop["ratio"], 0.0, "excluded PROPERTY ratio")
    assert_ratio(prop["weight"], 0.0, "excluded PROPERTY weight")

    sales = factor_by_type(rows, "SALES")
    assert_ratio(sales["weight"], 0.666667, "renormalized SALES weight")
    assert_ratio(sales["ratio"], 0.150000, "SALES ratio")

    payroll = factor_by_type(rows, "PAYROLL")
    assert_ratio(payroll["weight"], 0.333333, "renormalized PAYROLL weight")
    assert_ratio(payroll["ratio"], 0.250000, "PAYROLL ratio")


def test_renormalized_weights_drive_the_percentage_and_the_liability(api):
    """PRD 3.4: "The weight denominator is the sum of the base weights of the *included* factors only. If that sum is zero — no factor carrying a non-zero base weight survived exclusion — the request is rejected with `ERR_FACTOR_DENOMINATOR_ZERO`."
    PRD 3.4: "Each factor's `ratio` is rounded to 6 decimal places **first**; each rounded ratio is then multiplied by its `weight`; the three products are summed; and the sum is rounded half up to 6 decimal places once more to produce the return's `apportionment_percentage`."
    PRD 3.5: "The return's `state_taxable_income` is that apportionable income multiplied by the return's `apportionment_percentage`, rounded half up to 2 decimal places. The return's `tax_before_credits` is `state_taxable_income` multiplied by the registration's `tax_rate`, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/factor_weight_renormalization_on_zero_denominator
    """
    ctx = _zero_property_scenario()

    filing = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )

    assert_ratio(filing["apportionment_percentage"], 0.183333, "apportionment_percentage")
    assert_money(filing["state_taxable_income"], 916789.04, "state_taxable_income")
    assert_money(filing["tax_before_credits"], 81044.15, "tax_before_credits")


# ─── Nexus safety outranks the zero-denominator constraint ────────────────────

def _no_nexus_zero_denominator_scenario():
    ctx = setup_bare_registration(
        group_overrides={
            "name": "Nowhere Holdings", "everywhere_sales": 0,
            "everywhere_property": 0, "everywhere_payroll": 0,
        },
        registration_overrides={
            "state_code": "CA", "factor_formula": "SINGLE_SALES_FACTOR",
            "tax_rate": 0.0884, "throwback_rule": "NONE",
            "service_sourcing_rule": "MARKET_BASED",
        },
        include_member=True,
    )
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 250000, "protected_solicitation_only": False,
    })
    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=1000000,
    )
    ctx["filing_id"] = filing["id"]
    return ctx


def test_absent_nexus_is_reported_ahead_of_a_zero_factor_denominator(api):
    """PRD 2.11: "A factor computation run against a registration with no nexus whose sales denominator is also zero fails at band 15 with `ERR_NEXUS_NOT_ESTABLISHED`, not at band 29."
    PRD 3.4: "The computation refuses to run at all against a registration whose `nexus_status` is still `NONE`, rejecting with `ERR_NEXUS_NOT_ESTABLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/nexus_safety_beats_zero_denominator_constraint
    """
    ctx = _no_nexus_zero_denominator_scenario()

    response = api.compute_factors(
        ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA
    )

    error = validate_error(response, ApiErrorId.ERR_NEXUS_NOT_ESTABLISHED.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_FACTOR_DENOMINATOR_ZERO.value


def test_a_rejected_factor_run_writes_no_factor_rows(api):
    """PRD 3.4: "The computation refuses to run at all against a registration whose `nexus_status` is still `NONE`, rejecting with `ERR_NEXUS_NOT_ESTABLISHED`."
    PRD 3.4: "Running the computation sets the return's `apportionment_variant` to the doctrine that was used and then drives a four-link cascade through the whole liability chain, in this order: the first link writes `apportionment_variant` and `apportionment_percentage`; the second link, caused by the first, recomputes `modification_total`, `state_taxable_income` and `tax_before_credits`; the third link, caused by the second, re-runs the credit waterfall over every credit claim on the return, rewriting each claim's `applied_amount`, `carryforward_amount`, `expired_amount` and `status` along with the return's `credits_applied_total`; and the fourth link, caused by the third, recomputes `balance_due` and re-derives `payment_status`."

    Design: Difficulty/priority_pair_validation_conflict/nexus_safety_beats_zero_denominator_constraint
    """
    ctx = _no_nexus_zero_denominator_scenario()

    validate_error(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA),
        ApiErrorId.ERR_NEXUS_NOT_ESTABLISHED.value,
    )

    rows, meta = validate_paginated(
        api.list_filing_factors(ctx["filing_id"], AUD, {"limit": 100, "offset": 0})
    )
    assert rows == [], "No ApportionmentFactor row may be written by a rejected run"
    assert meta["total_count"] == 0

    filing = read_filing(ctx["filing_id"])
    assert filing["apportionment_percentage"] == 0
    assert filing["apportionment_variant"] is None


# ─── Sourcing and inclusion rules ─────────────────────────────────────────────

def test_throwout_removes_nowhere_sales_from_the_sales_denominator(api):
    """PRD 3.4: "Summing the nowhere amounts across the counting records gives the adjustment the state's `throwback_rule` decides what to do with: under `THROWBACK` that sum becomes `throwback_added` and is added to the sales numerator; under `THROWOUT` it becomes `throwout_removed` and is subtracted from the sales denominator; under `NONE` both are zero."
    PRD 3.4: "The sales numerator is therefore the sum over the counting records of `destination_sales` plus sourced service receipts, plus `throwback_added`; the sales denominator is the group's `everywhere_sales` less `throwout_removed`."

    Design: Corner/calculations/throwout_rule_shrinks_sales_denominator
    """
    ctx = setup_draft_filing(registration_overrides={"throwback_rule": "THROWOUT"})

    filing = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )

    sales = factor_by_type(list_factors(ctx["filing_id"]), "SALES")
    assert_money(sales["numerator"], 1200000, "SALES numerator under THROWOUT")
    assert_money(sales["denominator"], 9700000, "SALES denominator under THROWOUT")
    assert_money(sales["throwout_removed"], 300000, "throwout_removed")
    assert_money(sales["throwback_added"], 0, "throwback_added")
    assert_ratio(sales["ratio"], 0.123711, "SALES ratio under THROWOUT")

    assert_ratio(filing["apportionment_percentage"], 0.186856, "apportionment_percentage")
    assert_money(filing["state_taxable_income"], 934406.42, "state_taxable_income")
    assert_money(filing["tax_before_credits"], 82601.53, "tax_before_credits")


def test_cost_of_performance_sourcing_drops_out_of_state_service_receipts(api):
    """PRD 3.4: "A record's sourced service receipts are its `service_receipts` outright when the registration's `service_sourcing_rule` is `MARKET_BASED`, and are its `service_receipts` only when its `cost_of_performance_state_code` equals the registration's `state_code` (zero otherwise) when the rule is `COST_OF_PERFORMANCE`."

    Design: Corner/calculations/cost_of_performance_sourcing_drops_out_of_state_services
    """
    ctx = setup_draft_filing(
        registration_overrides={"service_sourcing_rule": "COST_OF_PERFORMANCE"}
    )

    filing = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "FINNIGAN"}, SA)
    )

    sales = factor_by_type(list_factors(ctx["filing_id"]), "SALES")
    assert_money(sales["numerator"], 1900000,
                 "SALES numerator with NV-performed services excluded")
    assert_ratio(sales["ratio"], 0.190000, "SALES ratio")

    assert_ratio(filing["apportionment_percentage"], 0.232500, "apportionment_percentage")
    assert_money(filing["state_taxable_income"], 1162657.30, "state_taxable_income")
    assert_money(filing["tax_before_credits"], 102778.91, "tax_before_credits")


def test_separate_entity_basis_narrows_the_included_members(api):
    """PRD 3.4: "On a `SEPARATE_ENTITY` return the included set is the single member named by `primary_legal_entity_id`. On a `COMBINED_UNITARY` or `CONSOLIDATED` return it is every `LegalEntity` of the group whose `is_unitary_member` is true."

    Design: Corner/calculations/separate_entity_basis_limits_members_to_primary_entity
    """
    ctx = setup_state_profile()
    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis="SEPARATE_ENTITY",
        federal_taxable_income=5000000, primary_legal_entity_id=ctx["le_a_id"],
    )
    for line in REFERENCE_MODIFICATIONS:
        add_modification(filing["id"], dict(line))

    computed = validate_success(
        api.compute_factors(filing["id"], {"apportionment_variant": "FINNIGAN"}, SA)
    )

    assert_ratio(computed["apportionment_percentage"], 0.200000,
                 "A separate-entity return excludes the other member even under FINNIGAN")
    rows = list_factors(filing["id"])
    assert_money(factor_by_type(rows, "SALES")["numerator"], 1500000, "SALES numerator")
    assert_money(factor_by_type(rows, "PAYROLL")["numerator"], 500000, "PAYROLL numerator")
    assert_money(computed["tax_before_credits"], 88411.96, "tax_before_credits")


def test_property_numerator_capitalizes_rent_at_eight_times_annual_rent(api):
    """PRD 3.4: "The **property factor** numerator is the sum, over the counting records, of `property_average_value` plus eight times `rented_property_annual_rent` — the standard UDITPA convention of capitalizing rented property at eight times annual rent — and its denominator is the group's `everywhere_property`."
    PRD 3.4: "Base weights come from the registration's `factor_formula`: `EQUAL_WEIGHTED_THREE` gives sales, property and payroll a base weight of 1 each; `DOUBLE_WEIGHTED_SALES` gives sales a base weight of 2 and property and payroll 1 each; `SINGLE_SALES_FACTOR` gives sales a base weight of 1 and gives property and payroll a base weight of 0."

    Design: Corner/calculations/property_numerator_capitalizes_rent_at_eight_times
    """
    ctx = setup_computed_filing(variant="JOYCE")

    rows, meta = validate_paginated(
        api.list_filing_factors(ctx["filing_id"], AUD, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 3, "A return carries exactly three factor rows"
    assert len(rows) == 3

    prop = factor_by_type(rows, "PROPERTY")
    assert_money(prop["numerator"], 1000000,
                 "800000 owned plus eight times 25000 of annual rent")
    assert_money(prop["denominator"], 4000000, "PROPERTY denominator")
    assert_ratio(prop["ratio"], 0.250000, "PROPERTY ratio")
    assert prop["included"] is True
    assert_ratio(prop["weight"], 0.250000, "PROPERTY weight under DOUBLE_WEIGHTED_SALES")
    assert_ratio(factor_by_type(rows, "SALES")["weight"], 0.500000, "SALES weight")
    assert_ratio(factor_by_type(rows, "PAYROLL")["weight"], 0.250000, "PAYROLL weight")


def test_factor_run_without_activity_for_the_return_year_is_rejected(api):
    """PRD 3.4: "The records in scope are then the activity records whose `registration_id` matches the return's registration, whose `tax_year` matches the return's tax year, and whose `legal_entity_id` is one of the included members. If that set is empty, the request is rejected with `ERR_NO_ACTIVITY_RECORDS`."

    Design: Corner/validations/no_activity_records_for_filing_year_returns_error
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "No Activity Group"},
        registration_overrides={
            "state_code": "CA", "factor_formula": "SINGLE_SALES_FACTOR",
            "tax_rate": 0.0884, "throwback_rule": "NONE",
            "service_sourcing_rule": "MARKET_BASED",
        },
        include_member=True,
    )
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2025,
        "destination_sales": 900000, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 0,
        "protected_solicitation_only": False,
    })
    registration = validate_success(
        api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2025}, TM)
    )
    assert registration["nexus_status"] == "ECONOMIC"
    registration = validate_success(api.complete_registration(
        ctx["registration_id"], {"state_account_number": "CA-70001111"}, TM
    ))
    assert registration["registration_status"] == "REGISTERED"

    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=1000000,
    )

    response = api.compute_factors(filing["id"], {"apportionment_variant": "JOYCE"}, SA)

    validate_error(response, ApiErrorId.ERR_NO_ACTIVITY_RECORDS.value)
    rows, _ = validate_paginated(
        api.list_filing_factors(filing["id"], AUD, {"limit": 100, "offset": 0})
    )
    assert rows == []


def test_activity_written_after_the_factor_run_makes_the_freeze_stale(api):
    """PRD 3.7: "And the factors must be both present and current: at least one `ApportionmentFactor` row must exist for the return, and no activity record for the return's registration and tax year may have been created after the return's most recent factor computation. A freeze attempted before the factors have ever been computed, or after fresh activity has landed underneath them, is rejected with `ERR_FACTORS_STALE`."

    Design: Corner/validations/late_activity_record_makes_factors_stale_on_lock
    """
    ctx = setup_computed_filing(variant="JOYCE")

    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 50000, "protected_solicitation_only": False,
    })

    validate_error(
        api.lock_factors(ctx["filing_id"], {}, SA),
        ApiErrorId.ERR_FACTORS_STALE.value,
    )
    assert read_filing(ctx["filing_id"])["preparation_status"] == "DRAFT"

    recomputed = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )
    assert_ratio(recomputed["apportionment_percentage"], 0.202500,
                 "apportionment_percentage after the re-run")

    frozen = validate_success(api.lock_factors(ctx["filing_id"], {}, SA))
    assert frozen["preparation_status"] == "FACTORS_LOCKED"


def test_solicitation_protected_state_cannot_freeze_a_return(api):
    """PRD 3.7: "It must have a `nexus_status` other than `PROTECTED_PL86272`, because a state whose only claim rests on protected solicitation cannot assess net income tax whatever the registration paperwork says; that rejection carries `ERR_PL86272_PROTECTED`."
    PRD 2.11: "16. The state is not solicitation-protected when a return is frozen (`ERR_PL86272_PROTECTED`)."
    PRD 2.11: "17. The registration is complete before a return is frozen (`ERR_REGISTRATION_NOT_COMPLETE`)."

    Design: Corner/validations/pl86272_protected_registration_blocks_lock_factors
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Protected Group"},
        registration_overrides={
            "state_code": "CA", "factor_formula": "DOUBLE_WEIGHTED_SALES",
            "tax_rate": 0.0884, "throwback_rule": "THROWBACK",
            "service_sourcing_rule": "MARKET_BASED",
        },
        include_member=True,
    )
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 300000, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 3,
        "protected_solicitation_only": True,
    })
    registration = validate_success(
        api.evaluate_nexus(ctx["registration_id"], {"as_of_tax_year": 2026}, TM)
    )
    assert registration["nexus_status"] == "PROTECTED_PL86272"
    assert registration["registration_status"] == "NOT_REQUIRED", (
        "Protected solicitation creates no filing obligation"
    )

    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=1000000,
    )
    computed = validate_success(
        api.compute_factors(filing["id"], {"apportionment_variant": "JOYCE"}, SA)
    )
    assert_ratio(computed["apportionment_percentage"], 0.000000,
                 "Under JOYCE the only member is protected, so every numerator is zero")

    response = api.lock_factors(filing["id"], {}, SA)

    error = validate_error(response, ApiErrorId.ERR_PL86272_PROTECTED.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_REGISTRATION_NOT_COMPLETE.value, (
        "The solicitation-protection band is evaluated before the registration-complete band"
    )
