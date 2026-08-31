"""Undercharge sampling, extrapolation and the recovery claim."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_audit_sample,
    assert_iso_instant_equals,
    create_audit_sample_payload,
    draw_sample,
    make_auditor_headers,
    new_carrier,
    read_carrier,
    read_coupon,
    read_sample,
    set_clock,
    setup_audit_population,
    setup_audit_sample_in_review,
    setup_cleared_invoice,
    setup_flown_final_prorated_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Drawing the sample
# --------------------------------------------------------------------------- #
def test_draw_over_a_partner_with_no_invoiced_coupons_is_refused(api):
    """PRD §3.9: "An empty population is refused with `ERR_EMPTY_AUDIT_POPULATION`. A
    population containing any coupon flown earlier than 730 days before the current logical
    clock is time-barred and refused with `ERR_AUDIT_TIME_BARRED`. Every identifier in
    `sample_coupon_ids` must be a member of that derived population, or the draw is refused
    with `ERR_COUPON_NOT_IN_POPULATION`."
    PRD §3.9: "At draw time the server derives the population the sample is drawn from: every
    coupon whose `operating_carrier_id` is the `audited_carrier_id`, whose `coupon_status` is
    `FLOWN` or `ADJUSTED`, whose `flown_at` falls in the half-open window from the period's
    `period_start` inclusive to its `period_end` exclusive, whose `billing_invoice_id` is not
    null — unbilled coupons are outside the audit's reach — and whose owning ticket's
    `sale_currency` equals the sample's `claim_currency`."

    Design: Corner/validations/audit_draw_over_a_partner_with_no_invoiced_coupons_returns_empty_population
    """
    ctx = setup_cleared_invoice(ticket_number="0054000000001")
    cc = new_carrier("CC")

    resp = api.create_audit_sample(
        create_audit_sample_payload(
            ctx["aa"]["id"], cc["id"], ctx["period"]["id"], [ctx["coupon"]["id"]]
        ),
        make_auditor_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_AUDIT_POPULATION.value)

    _rows, meta = validate_paginated(
        api.list_audit_samples(OPERATOR, params={"settlement_period_id": ctx["period"]["id"]})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_audit_sample(
            create_audit_sample_payload(
                ctx["aa"]["id"], ctx["bb"]["id"], ctx["period"]["id"], [ctx["coupon"]["id"]]
            ),
            make_auditor_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert accepted["population_coupon_count"] == 1, (
        "the same draw against the carrier that did operate the coupon succeeds"
    )


def test_sampling_a_coupon_outside_the_derived_population_is_refused(api):
    """PRD §3.9: "At draw time the server derives the population the sample is drawn from:
    every coupon whose `operating_carrier_id` is the `audited_carrier_id`, whose
    `coupon_status` is `FLOWN` or `ADJUSTED`, whose `flown_at` falls in the half-open window
    from the period's `period_start` inclusive to its `period_end` exclusive, whose
    `billing_invoice_id` is not null — unbilled coupons are outside the audit's reach — and
    whose owning ticket's `sale_currency` equals the sample's `claim_currency`."
    PRD §2.7: "**Sample within population.** Every identifier in `sample_coupon_ids` is a
    member of the derived population — otherwise `ERR_COUPON_NOT_IN_POPULATION` (422). Applies
    to audit-sample draw."

    Design: Corner/errors/sampling_a_coupon_outside_the_derived_population_returns_not_in_population
    """
    ctx = setup_audit_population(ticket_specs=((100000, 2),))
    _ticket, outsiders, _run = setup_flown_final_prorated_ticket(
        ctx["aa"]["id"],
        ctx["cc"]["id"],
        ticket_number="0063000000002",
        total_fare_minor=40000,
        tpm_miles=500,
        origin="CDG",
        destination="FCO",
    )
    outsider = read_coupon(outsiders[0]["id"])
    assert outsider["billing_invoice_id"] is None
    assert outsider["allocated_amount_minor"] == 40000

    resp = api.create_audit_sample(
        create_audit_sample_payload(
            ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [outsider["id"]]
        ),
        make_auditor_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_NOT_IN_POPULATION.value)

    _rows, meta = validate_paginated(
        api.list_audit_samples(OPERATOR, params={"settlement_period_id": ctx["period"]["id"]})
    )
    assert meta["total_count"] == 0


def test_audit_draw_beyond_the_seven_hundred_thirty_day_bar_is_refused(api):
    """PRD §3.9: "A population containing any coupon flown earlier than 730 days before the
    current logical clock is time-barred and refused with `ERR_AUDIT_TIME_BARRED`."
    PRD §2.7: "**Audit time bar.** No coupon in the derived audit population was flown earlier
    than 730 days before the current logical clock — otherwise `ERR_AUDIT_TIME_BARRED` (409).
    Applies to audit-sample draw."

    Design: Corner/errors/audit_draw_beyond_the_seven_hundred_thirty_day_bar_returns_time_barred
    """
    ctx = setup_audit_population(ticket_specs=((100000, 2),))
    sampled = ctx["coupons"][0]

    set_clock("2028-08-11T00:00:00Z")
    resp = api.create_audit_sample(
        create_audit_sample_payload(
            ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [sampled["id"]]
        ),
        make_auditor_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_TIME_BARRED.value)

    _rows, meta = validate_paginated(
        api.list_audit_samples(OPERATOR, params={"settlement_period_id": ctx["period"]["id"]})
    )
    assert meta["total_count"] == 0

    set_clock("2026-09-06T00:00:00Z")
    accepted = validate_success(
        api.create_audit_sample(
            create_audit_sample_payload(
                ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [sampled["id"]]
            ),
            make_auditor_headers(ctx["aa"]["id"]),
        ),
        201,
    )
    assert accepted["status"] == "DRAWN", "only the clock position separates the two outcomes"


# --------------------------------------------------------------------------- #
# Findings and the state gate on closing
# --------------------------------------------------------------------------- #
def test_closing_a_sample_with_no_findings_is_refused(api):
    """PRD §2.7: "**Sample state.** Recording a finding requires `DRAWN` or `IN_REVIEW`;
    closing requires `IN_REVIEW`; a claim decision requires `CLAIM_RAISED` — otherwise
    `ERR_SAMPLE_STATE_INVALID` (409). Applies to audit finding recording, audit-sample close
    and audit claim decision."
    PRD §3.9: "The sample opens in `DRAWN` status with `sampled_undercharge_minor` and
    `findings_count` at zero."

    Design: Corner/errors/closing_a_sample_with_no_findings_returns_sample_state_invalid
    """
    ctx = setup_audit_population(ticket_specs=((100000, 2),))
    sample = draw_sample(
        ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [ctx["coupons"][0]["id"]]
    )

    resp = api.close_audit_sample(sample["id"], make_auditor_headers(ctx["aa"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SAMPLE_STATE_INVALID.value)

    unchanged = read_sample(sample["id"])
    assert unchanged["status"] == "DRAWN"
    assert unchanged["findings_count"] == 0
    assert unchanged["undercharge_ratio_bp"] == 0
    assert unchanged["claim_amount_minor"] == 0


def test_finding_against_a_coupon_outside_the_sample_is_refused(api):
    """PRD §3.9: "The `coupon_id` must be a member of `sample_coupon_ids`, or the finding is
    refused with `ERR_COUPON_NOT_IN_SAMPLE`."
    PRD §3.9: "A successful draw freezes four figures and never recomputes them:
    `population_coupon_count` as the number of coupons in the population,
    `population_allocated_minor` as the sum of their `allocated_amount_minor`,
    `sampled_coupon_count` as the number of identifiers supplied, and
    `sampled_allocated_minor` as the sum of `allocated_amount_minor` over the sampled coupons
    as they stood at draw time."

    Design: Corner/errors/finding_recorded_for_a_coupon_outside_the_sample_returns_not_in_sample
    """
    ctx = setup_audit_population(ticket_specs=((100000, 2),))
    drawn, undrawn = ctx["coupons"][0], ctx["coupons"][1]
    sample = draw_sample(ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [drawn["id"]])

    resp = api.record_finding(
        sample["id"],
        {"coupon_id": undrawn["id"], "correct_amount_minor": 60000},
        make_auditor_headers(ctx["aa"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_NOT_IN_SAMPLE.value)

    unchanged = read_sample(sample["id"])
    assert unchanged["sampled_undercharge_minor"] == 0
    assert unchanged["findings_count"] == 0
    assert unchanged["status"] == "DRAWN"
    assert unchanged["population_coupon_count"] == 2
    assert unchanged["sampled_coupon_count"] == 1


def test_ratio_one_basis_point_under_materiality_closes_immaterial(api):
    """PRD §3.9: "When `undercharge_ratio_bp` is strictly below 200 the finding is immaterial:
    `claim_amount_minor` and `claim_settlement_minor` are both set to zero and the sample
    closes into `CLOSED_IMMATERIAL`. `extrapolated_gross_minor`, `coverage_bp` and
    `haircut_bp` are still written in that branch, for the audit trail."
    PRD §3.9: "Closing requires `IN_REVIEW` and computes the extrapolation in a pinned order.
    First, `undercharge_ratio_bp` is `sampled_undercharge_minor` multiplied by 10000, divided
    by `sampled_allocated_minor`, rounded half up — the shortfall as a proportion of what was
    sampled, in basis points. Second, `coverage_bp` is `sampled_allocated_minor` multiplied by
    10000, divided by `population_allocated_minor`, rounded half up — how much of the
    population by value the sample actually saw. Third, `haircut_bp` is selected from that
    coverage on a three-tier scale: no haircut at all when `coverage_bp` is 2000 or more, 1500
    basis points when it is at least 500 but below 2000, and 3500 basis points when it is
    below 500. Thin samples are discounted hard. Fourth, `extrapolated_gross_minor` is
    `sampled_undercharge_minor` multiplied by `population_allocated_minor`, divided by
    `sampled_allocated_minor`, rounded half up — the sampled shortfall scaled up to the whole
    population."

    Design: Corner/calculations/audit_sample_at_one_hundred_ninety_nine_bp_closes_immaterial
    """
    ctx = setup_audit_sample_in_review(correct_amount_minor=50995)
    before_payable = read_carrier(ctx["cc"]["id"])["settled_payable_minor"]

    closed = validate_success(
        api.close_audit_sample(ctx["sample"]["id"], make_auditor_headers(ctx["aa"]["id"])), 200
    )
    assert_audit_sample(closed)
    assert closed["sampled_undercharge_minor"] == 995
    assert closed["undercharge_ratio_bp"] == 199, "one basis point under the 200 threshold"
    assert closed["status"] == "CLOSED_IMMATERIAL"
    assert closed["claim_amount_minor"] == 0
    assert closed["claim_settlement_minor"] == 0
    assert closed["extrapolated_gross_minor"] == 1990
    assert closed["coverage_bp"] == 5000
    assert closed["haircut_bp"] == 0

    assert read_carrier(ctx["cc"]["id"])["settled_payable_minor"] == before_payable


# --------------------------------------------------------------------------- #
# The materiality boundary
# --------------------------------------------------------------------------- #
def test_ratio_of_exactly_two_hundred_basis_points_raises_a_claim(api):
    """PRD §3.9: "When `undercharge_ratio_bp` is 200 or more the sample closes into
    `CLAIM_RAISED` and the recovery claim is computed: the extrapolated gross is first
    **capped** at 25 times `sampled_undercharge_minor`, taking whichever of the two is
    smaller, and only then discounted by the haircut — `claim_amount_minor` is the capped
    figure multiplied by 10000 less `haircut_bp`, divided by 10000, rounded half up."

    Design: Difficulty/boundary_precision_check/audit_materiality_at_exactly_two_hundred_basis_points
    """
    ctx = setup_audit_sample_in_review(correct_amount_minor=51000)
    assert ctx["sample"]["sampled_allocated_minor"] == 50000
    assert ctx["sample"]["sampled_undercharge_minor"] == 1000

    closed = validate_success(
        api.close_audit_sample(ctx["sample"]["id"], make_auditor_headers(ctx["aa"]["id"])), 200
    )
    assert closed["undercharge_ratio_bp"] == 200, "exactly on the materiality threshold"
    assert closed["status"] == "CLAIM_RAISED", (
        "the comparison fires at 200; it is not exclusive"
    )


def test_full_coverage_sample_takes_no_haircut_at_the_materiality_boundary(api):
    """PRD §3.9: "Third, `haircut_bp` is selected from that coverage on a three-tier scale: no
    haircut at all when `coverage_bp` is 2000 or more, 1500 basis points when it is at least
    500 but below 2000, and 3500 basis points when it is below 500."
    PRD §3.9: "Either way `closed_at` is stamped with the current logical clock and the
    sample's `version` bumps."

    Design: Difficulty/boundary_precision_check/audit_materiality_at_exactly_two_hundred_basis_points
    """
    ctx = setup_audit_sample_in_review(correct_amount_minor=51000)

    closed = validate_success(
        api.close_audit_sample(ctx["sample"]["id"], make_auditor_headers(ctx["aa"]["id"])), 200
    )
    assert closed["coverage_bp"] == 5000, "50000 sampled out of a 100000 population"
    assert closed["haircut_bp"] == 0
    assert closed["extrapolated_gross_minor"] == 2000
    assert closed["claim_amount_minor"] == 2000
    assert_iso_instant_equals(closed["closed_at"], "2026-09-06T00:00:00Z")


# --------------------------------------------------------------------------- #
# Cap before haircut
# --------------------------------------------------------------------------- #
def _thin_sample_over_a_mixed_population():
    return setup_audit_sample_in_review(
        ticket_specs=((100000, 2), (20000, 2)),
        sample_index=2,
        correct_amount_minor=10500,
    )


def test_audit_close_derives_coverage_and_haircut_from_allocated_value(api):
    """PRD §3.9: "Second, `coverage_bp` is `sampled_allocated_minor` multiplied by 10000,
    divided by `population_allocated_minor`, rounded half up — how much of the population by
    value the sample actually saw."
    PRD §3.9: "Third, `haircut_bp` is selected from that coverage on a three-tier scale: no
    haircut at all when `coverage_bp` is 2000 or more, 1500 basis points when it is at least
    500 but below 2000, and 3500 basis points when it is below 500."
    PRD §3.9: "A successful draw freezes four figures and never recomputes them:
    `population_coupon_count` as the number of coupons in the population,
    `population_allocated_minor` as the sum of their `allocated_amount_minor`,
    `sampled_coupon_count` as the number of identifiers supplied, and
    `sampled_allocated_minor` as the sum of `allocated_amount_minor` over the sampled coupons
    as they stood at draw time."

    Design: Difficulty/combinatorial_formula/audit_claim_cap_before_haircut_composition
    """
    ctx = _thin_sample_over_a_mixed_population()

    closed = validate_success(
        api.close_audit_sample(ctx["sample"]["id"], make_auditor_headers(ctx["aa"]["id"])), 200
    )
    assert closed["population_coupon_count"] == 4
    assert closed["population_allocated_minor"] == 120000
    assert closed["sampled_coupon_count"] == 1
    assert closed["sampled_allocated_minor"] == 10000
    assert closed["sampled_undercharge_minor"] == 500
    assert closed["undercharge_ratio_bp"] == 500
    assert closed["coverage_bp"] == 833, "10000 of a 120000 population, by value"
    assert closed["haircut_bp"] == 1500, "833 bp of coverage sits on the middle tier"


def test_audit_claim_caps_the_extrapolation_before_applying_the_haircut(api):
    """PRD §3.9: "When `undercharge_ratio_bp` is 200 or more the sample closes into
    `CLAIM_RAISED` and the recovery claim is computed: the extrapolated gross is first
    **capped** at 25 times `sampled_undercharge_minor`, taking whichever of the two is
    smaller, and only then discounted by the haircut — `claim_amount_minor` is the capped
    figure multiplied by 10000 less `haircut_bp`, divided by 10000, rounded half up."
    PRD §3.9: "Finally `claim_settlement_minor` converts `claim_amount_minor` from
    `claim_currency` into the audited period's `settlement_currency` using the quote prevailing
    at that period's `rate_fixing_date`, by the same conversion procedure as everywhere else,
    and a missing quote fails the close with `ERR_NO_EXCHANGE_RATE`."

    Design: Difficulty/combinatorial_formula/audit_claim_cap_before_haircut_composition
    """
    ctx = _thin_sample_over_a_mixed_population()

    closed = validate_success(
        api.close_audit_sample(ctx["sample"]["id"], make_auditor_headers(ctx["aa"]["id"])), 200
    )
    assert closed["extrapolated_gross_minor"] == 6000, "500 scaled by 120000/10000"
    assert closed["claim_amount_minor"] == 5100, (
        "6000 is under the 12500 cap, then discounted by the 1500 bp haircut"
    )
    assert closed["claim_settlement_minor"] == 5100, "USD into a USD-settled period"
    assert closed["status"] == "CLAIM_RAISED"
