"""State modifications, the credit waterfall and the liability cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_pool_conserved,
    assert_money,
    assert_ratio,
    create_filing,
    make_controller_headers,
    read_credit_claim,
    read_filing,
    set_clock,
    setup_bare_registration,
    setup_computed_filing,
    setup_filed_filing,
    setup_filing_with_credits,
    setup_draft_filing,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]

TWO_CREDITS = [
    {"credit_code": "RD_CREDIT", "granted_amount": 30000.00, "priority_order": 1,
     "refundable": False, "expires_after_years": 5},
    {"credit_code": "JOBS_CREDIT", "granted_amount": 70000.00, "priority_order": 2,
     "refundable": False, "expires_after_years": 3},
]

THREE_LINES = [
    {"modification_code": "STATE_TAX_ADDBACK", "direction": "ADDITION",
     "raw_amount": 125042.00, "allocation_ratio": 0.008},
    {"modification_code": "MUNI_INTEREST_SUB", "direction": "SUBTRACTION",
     "raw_amount": 92379.00, "allocation_ratio": 0.008},
    {"modification_code": "DEPREC_ADJ", "direction": "ADDITION",
     "raw_amount": 51907.00, "allocation_ratio": 0.008},
]


def _rounding_order_filing():
    ctx = setup_bare_registration(group_overrides={"name": "Rounding Order Corp"})
    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=5000000,
    )
    ctx["filing_id"] = filing["id"]
    return ctx


def test_each_modification_line_is_rounded_to_cents_at_the_line(api):
    """PRD 3.5: "Each line's `line_amount` is its `raw_amount` multiplied by its `allocation_ratio`, rounded half up to 2 decimal places, and its `sequence_number` is its 1-based position among the return's modification lines ordered by `created_at` ascending."

    Design: Difficulty/combinatorial_formula/modification_per_line_rounding_before_summation
    """
    ctx = _rounding_order_filing()

    lines = [
        validate_success(api.create_modification(ctx["filing_id"], dict(spec), SA), 201)
        for spec in THREE_LINES
    ]

    assert_money(lines[0]["line_amount"], 1000.34, "STATE_TAX_ADDBACK line_amount")
    assert lines[0]["sequence_number"] == 1
    assert_money(lines[1]["line_amount"], 739.03, "MUNI_INTEREST_SUB line_amount")
    assert lines[1]["sequence_number"] == 2
    assert_money(lines[2]["line_amount"], 415.26, "DEPREC_ADJ line_amount")
    assert lines[2]["sequence_number"] == 3


def test_modification_total_rounds_at_the_line_before_summing(api):
    """PRD 3.5: "The return's `modification_total` is the signed sum of those per-line amounts: an `ADDITION` line contributes its `line_amount` positively, a `SUBTRACTION` line contributes it negatively, and the signed sum is itself rounded half up to 2 decimal places."
    PRD 3.5: "The rounding order is pinned: **round at the line, then sum**. The alternative discipline of summing the exact products and rounding once at the end is not what this system does, and generally differs by whole cents."

    Design: Difficulty/combinatorial_formula/modification_per_line_rounding_before_summation
    """
    ctx = _rounding_order_filing()
    for spec in THREE_LINES:
        validate_success(api.create_modification(ctx["filing_id"], dict(spec), SA), 201)

    filing = read_filing(ctx["filing_id"])

    assert_money(filing["modification_total"], 676.57, "modification_total")
    assert abs(filing["modification_total"] - 676.56) > 0.005, (
        "Summing the exact products and rounding once yields 676.56, which is the "
        "forbidden order"
    )
    assert_money(filing["state_taxable_income"], 0.0,
                 "state_taxable_income while apportionment_percentage is still 0")


def test_recompute_cascades_the_percentage_into_tax_and_the_credit_waterfall(api):
    """PRD 3.4: "Running the computation sets the return's `apportionment_variant` to the doctrine that was used and then drives a four-link cascade through the whole liability chain, in this order: the first link writes `apportionment_variant` and `apportionment_percentage`; the second link, caused by the first, recomputes `modification_total`, `state_taxable_income` and `tax_before_credits`; the third link, caused by the second, re-runs the credit waterfall over every credit claim on the return, rewriting each claim's `applied_amount`, `carryforward_amount`, `expired_amount` and `status` along with the return's `credits_applied_total`; and the fourth link, caused by the third, recomputes `balance_due` and re-derives `payment_status`."
    PRD 3.5: "A running remainder starts at the return's `tax_before_credits`. For each claim in order: a non-refundable claim's `applied_amount` is the lesser of its `granted_amount` and the current remainder, while a refundable claim's `applied_amount` is its full `granted_amount`, because a refundable credit pays out past the liability; the remainder then becomes the greater of zero and the previous remainder less that claim's `applied_amount`; the claim's `carryforward_amount` becomes its `granted_amount` less its `applied_amount`; and its `expired_amount` starts at zero."

    Design: Difficulty/transitive_cascade/compute_factors_four_link_liability_cascade
    """
    ctx = setup_filing_with_credits(credits=TWO_CREDITS, variant="JOYCE")
    rd_id, jobs_id = (claim["id"] for claim in ctx["credit_claims"])

    before = read_filing(ctx["filing_id"])
    assert_money(before["tax_before_credits"], 88411.96, "tax_before_credits before")
    assert_money(before["credits_applied_total"], 88411.96, "credits_applied_total before")
    assert_money(before["balance_due"], 0.00, "balance_due before")
    assert before["payment_status"] == "PAID"

    jobs_before = read_credit_claim(jobs_id)
    assert_money(jobs_before["applied_amount"], 58411.96, "JOBS applied before")
    assert_money(jobs_before["carryforward_amount"], 11588.04, "JOBS carryforward before")
    assert jobs_before["status"] == "PARTIALLY_APPLIED"

    after = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "FINNIGAN"}, SA)
    )

    assert_ratio(after["apportionment_percentage"], 0.245000, "apportionment_percentage")
    assert_money(after["state_taxable_income"], 1225165.76, "state_taxable_income")
    assert_money(after["tax_before_credits"], 108304.65, "tax_before_credits")

    assert_money(read_credit_claim(rd_id)["applied_amount"], 30000.00, "RD applied")
    jobs_after = read_credit_claim(jobs_id)
    assert_money(jobs_after["applied_amount"], 70000.00, "JOBS applied after")
    assert_money(jobs_after["carryforward_amount"], 0.00, "JOBS carryforward after")
    assert jobs_after["status"] == "FULLY_APPLIED"
    assert_money(after["credits_applied_total"], 100000.00, "credits_applied_total")


def test_recompute_final_link_moves_the_balance_and_the_settlement_axis(api):
    """PRD 3.5: "The return's `balance_due` is then its `tax_before_credits`, less `credits_applied_total`, less `estimated_credits_applied`, plus `assessment_added_total`, rounded half up to 2 decimal places."
    PRD 3.5: "A negative `balance_due` yields `OVERPAID`. A `balance_due` of exactly zero yields `PAID`. A positive `balance_due` yields `PARTIALLY_PAID` when `estimated_credits_applied` is greater than zero, and `UNPAID` when `estimated_credits_applied` is zero."

    Design: Difficulty/transitive_cascade/compute_factors_four_link_liability_cascade
    """
    ctx = setup_filing_with_credits(credits=TWO_CREDITS, variant="JOYCE")
    jobs_id = ctx["credit_claims"][1]["id"]

    before = read_filing(ctx["filing_id"])
    assert before["payment_status"] == "PAID"

    after = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "FINNIGAN"}, SA)
    )

    assert_money(after["balance_due"], 8304.65, "balance_due after the re-run")
    assert after["payment_status"] == "UNPAID", (
        "A positive balance with no applied remittance re-derives as UNPAID"
    )
    assert_money(read_credit_claim(jobs_id)["granted_amount"], 70000.00,
                 "granted_amount is untouched by the whole cascade")


def test_amendment_returns_every_credit_claim_to_pending(api):
    """PRD 3.7: "The reversal is total: every credit claim on the return returns to an `applied_amount` of 0, a `carryforward_amount` equal to its full `granted_amount`, an `expired_amount` of 0 and a `status` of `PENDING`, and the return's `credits_applied_total` returns to 0."
    PRD 3.7: "A `Controller` or `TaxManager` supplies a `reason` and may supply a replacement `federal_taxable_income`; the return moves `FILED → AMENDED` and its `amendment_count` increments by 1."

    Design: Difficulty/compensating_invariant/credit_pool_dollars_conserved_across_amend
    """
    ctx = setup_filed_filing(credits=TWO_CREDITS)
    rd_id, jobs_id = (claim["id"] for claim in ctx["credit_claims"])

    rd_before = read_credit_claim(rd_id)
    assert_money(rd_before["applied_amount"], 30000.00, "RD applied before")
    assert_money(rd_before["carryforward_amount"], 0.00, "RD carryforward before")
    assert rd_before["status"] == "FULLY_APPLIED"
    jobs_before = read_credit_claim(jobs_id)
    assert_money(jobs_before["applied_amount"], 58411.96, "JOBS applied before")
    assert_money(jobs_before["carryforward_amount"], 11588.04, "JOBS carryforward before")
    assert jobs_before["status"] == "PARTIALLY_APPLIED"

    amended = validate_success(api.amend_filing(
        ctx["filing_id"], {"reason": "Sourcing correction on service receipts"},
        make_controller_headers("controller-01"),
    ))

    assert amended["preparation_status"] == "AMENDED"
    assert amended["amendment_count"] == 1
    assert_money(amended["credits_applied_total"], 0.00, "credits_applied_total")
    assert_money(amended["balance_due"], 88411.96, "balance_due after amendment")
    assert amended["payment_status"] == "UNPAID"

    rd_after = read_credit_claim(rd_id)
    assert_money(rd_after["applied_amount"], 0.00, "RD applied after")
    assert_money(rd_after["carryforward_amount"], 30000.00, "RD carryforward after")
    assert rd_after["status"] == "PENDING"
    jobs_after = read_credit_claim(jobs_id)
    assert_money(jobs_after["applied_amount"], 0.00, "JOBS applied after")
    assert_money(jobs_after["carryforward_amount"], 70000.00, "JOBS carryforward after")
    assert jobs_after["status"] == "PENDING"


def test_credit_pool_dollars_survive_the_amendment_round_trip(api):
    """PRD 3.5: "One invariant is conserved across every run and across the amendment reversal of Section 3.7: for each claim, `granted_amount` equals `applied_amount` plus `carryforward_amount` plus `expired_amount`, rounded to 2 decimal places."
    PRD 3.7: "The conserved quantity survives the round trip untouched: for each claim, `granted_amount` still equals `applied_amount` plus `carryforward_amount` plus `expired_amount`."

    Design: Difficulty/compensating_invariant/credit_pool_dollars_conserved_across_amend
    """
    ctx = setup_filed_filing(credits=TWO_CREDITS)
    claim_ids = [claim["id"] for claim in ctx["credit_claims"]]

    def pool_total():
        total = 0.0
        for claim_id in claim_ids:
            claim = read_credit_claim(claim_id)
            assert_credit_pool_conserved(claim)
            total += (claim["applied_amount"] + claim["carryforward_amount"]
                      + claim["expired_amount"])
        return round(total, 2)

    before = pool_total()
    assert_money(before, 100000.00, "credit pool before the amendment")

    validate_success(api.amend_filing(
        ctx["filing_id"], {"reason": "Sourcing correction on service receipts"},
        make_controller_headers("controller-01"),
    ))

    after = pool_total()
    assert_money(after, 100000.00, "credit pool after the amendment")
    assert before == after, (
        f"The credit pool drifted across the round trip: {before} -> {after}"
    )


def test_lapsed_carryforward_life_moves_the_remainder_into_expired(api):
    """PRD 3.5: "If the return's `tax_year` plus the claim's `expires_after_years` is strictly less than the calendar year of the current logical clock, the carryforward life has lapsed: the claim's `expired_amount` takes over the whole `carryforward_amount` and `carryforward_amount` drops to zero."
    PRD 3.5: "It is `FULLY_APPLIED` when `applied_amount` equals `granted_amount`; `PARTIALLY_APPLIED` when `applied_amount` is greater than zero but less than `granted_amount`; `EXPIRED` when `applied_amount` is zero and `expired_amount` is greater than zero; and `CARRIED_FORWARD` when `applied_amount` is zero and `carryforward_amount` is greater than zero."

    Design: Corner/calculations/credit_carryforward_expires_after_declared_life
    """
    ctx = setup_computed_filing(variant="JOYCE")
    set_clock("2028-01-01T00:00:00Z")

    first = validate_success(api.create_credit_claim(ctx["filing_id"], {
        "credit_code": "OLD_RD_CREDIT", "granted_amount": 200000.00,
        "priority_order": 1, "refundable": False, "expires_after_years": 1,
        "expected_filing_version": read_filing(ctx["filing_id"])["version"],
    }, SA), 201)
    second = validate_success(api.create_credit_claim(ctx["filing_id"], {
        "credit_code": "OLD_JOBS_CREDIT", "granted_amount": 50000.00,
        "priority_order": 2, "refundable": False, "expires_after_years": 1,
        "expected_filing_version": read_filing(ctx["filing_id"])["version"],
    }, SA), 201)

    first = read_credit_claim(first["id"])
    assert_money(first["applied_amount"], 88411.96, "first claim applied_amount")
    assert_money(first["carryforward_amount"], 0.00, "first claim carryforward_amount")
    assert_money(first["expired_amount"], 111588.04, "first claim expired_amount")
    assert first["status"] == "PARTIALLY_APPLIED"

    second = read_credit_claim(second["id"])
    assert_money(second["applied_amount"], 0.00, "second claim applied_amount")
    assert_money(second["carryforward_amount"], 0.00, "second claim carryforward_amount")
    assert_money(second["expired_amount"], 50000.00, "second claim expired_amount")
    assert second["status"] == "EXPIRED"

    assert_credit_pool_conserved(first)
    assert_credit_pool_conserved(second)

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["credits_applied_total"], 88411.96, "credits_applied_total")
    assert_money(filing["balance_due"], 0.00, "balance_due")
    assert filing["payment_status"] == "PAID"


def test_second_credit_claim_on_a_stale_return_version_is_rejected(api):
    """PRD 2.8: "Adding a credit claim to a return requires `expected_filing_version` in the request body. This field is **not optional**: the caller must supply the `version` of the target `StateFiling` as it was last observed. If that value does not equal the return's current `version`, the request is rejected with `ERR_STALE_FILING_VERSION` (HTTP 412) and no claim is created."

    Design: Corner/cross_cutting_complexity_layers/stale_filing_version_rejects_second_credit_claim
    """
    ctx = setup_computed_filing(variant="JOYCE")
    observed_version = ctx["filing"]["version"]

    first = validate_success(api.create_credit_claim(ctx["filing_id"], {
        "credit_code": "RD_CREDIT", "granted_amount": 30000.00, "priority_order": 1,
        "refundable": False, "expires_after_years": 5,
        "expected_filing_version": observed_version,
    }, SA), 201)
    assert_money(read_credit_claim(first["id"])["applied_amount"], 30000.00,
                 "first claim applied_amount")

    stale = api.create_credit_claim(ctx["filing_id"], {
        "credit_code": "JOBS_CREDIT", "granted_amount": 40000.00, "priority_order": 2,
        "refundable": False, "expires_after_years": 3,
        "expected_filing_version": observed_version,
    }, SA)
    validate_error(stale, ApiErrorId.ERR_STALE_FILING_VERSION.value)

    rows, _ = validate_paginated(
        api.list_filing_credit_claims(ctx["filing_id"], AUD, {"limit": 100, "offset": 0})
    )
    assert len(rows) == 1, "A rejected claim create must write no row"

    refreshed = read_filing(ctx["filing_id"])["version"]
    second = validate_success(api.create_credit_claim(ctx["filing_id"], {
        "credit_code": "JOBS_CREDIT", "granted_amount": 40000.00, "priority_order": 2,
        "refundable": False, "expires_after_years": 3,
        "expected_filing_version": refreshed,
    }, SA), 201)
    assert_money(read_credit_claim(second["id"])["applied_amount"], 40000.00,
                 "second claim applied_amount after the retry")

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["credits_applied_total"], 70000.00, "credits_applied_total")
    assert_money(filing["balance_due"], 18411.96, "balance_due")


def test_return_version_advances_by_one_on_every_mutation(api):
    """PRD 2.4: "Most resources additionally carry an `updated_at` timestamp, in the same ISO 8601 UTC format with three fractional digits, and a `version`, which is an integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation of that resource."
    PRD 3.5: "Adding a modification line recomputes `modification_total`, then `state_taxable_income` and `tax_before_credits`, then the credit waterfall, then the balance — in that order — and advances the return's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/filing_version_increments_on_every_mutation
    """
    ctx = setup_draft_filing(with_modifications=False)

    assert read_filing(ctx["filing_id"])["version"] == 1, (
        "A newly opened return starts at version 1"
    )

    validate_success(api.create_modification(ctx["filing_id"], dict(THREE_LINES[0]), SA), 201)
    validate_success(api.create_modification(ctx["filing_id"], dict(THREE_LINES[1]), SA), 201)
    assert read_filing(ctx["filing_id"])["version"] == 3, (
        "Two modification writes advance the return's version by exactly 2"
    )

    computed = validate_success(
        api.compute_factors(ctx["filing_id"], {"apportionment_variant": "JOYCE"}, SA)
    )
    assert computed["version"] == 4, (
        f"The factor run advances the version to 4, got {computed['version']}"
    )
    assert_money(computed["modification_total"], 261.31, "modification_total")
