"""Interest, liquidated damages, settlements and the employer delinquency ledger."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_delinquency_assessment,
    assess_delinquency,
    file_single_line_report,
    make_employer_headers,
    read_employer,
    read_report,
    remit,
    set_clock,
    setup_assessed_report,
    setup_employer_with_one_participant,
    setup_superseded_report_pair,
    setup_three_line_report_sixty_days_late,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_the_statutory_basis_doubles_the_charge_with_no_grace_period(api):
    """PRD §3.6: "At assessment time the server stamps `assessed_on` from the
    logical clock date and computes `days_late` as the number of whole days from
    the report's `due_date` to `assessed_on`, discarding any fractional day and
    never falling below 0."
    PRD §3.6: "Under the `STATUTORY` basis, which mirrors the doubling remedy of
    the federal statute, interest runs from the first day after the due date with
    no grace period at all: `interest_cents` is the principal multiplied by the
    fund's `interest_rate_annual_bps`, divided by 10,000 to turn basis points
    into a rate, multiplied by `days_late` and divided by 365, then rounded half
    up to whole cents."
    PRD §3.6: "`liquidated_damages_cents` is the larger of two figures — the
    interest just computed, and the principal multiplied by the fund's
    `ld_rate_bps` and divided by 10,000, rounded half up to whole cents — which
    is what makes the remedy a doubling in the ordinary case. The fund's
    `ld_floor_cents` is **not** applied under this basis."
    PRD §3.6: "Under both bases, interest and liquidated damages are each rounded
    half up to whole cents **independently**, and only then added; there is no
    intermediate unrounded total. `total_cents` is `principal_cents` plus
    `interest_cents` plus `liquidated_damages_cents`."

    Design: Difficulty/dual_variant_calc/delinquency_basis_statutory_vs_plan_schedule_diverge
    """
    base = setup_three_line_report_sixty_days_late()
    report = read_report(base["report"]["id"])
    assert report["due_date"] == "2026-04-20"
    assert report["total_contributions_due_cents"] == 357668

    statutory = validate_success(
        api.create_delinquency_assessment(report["id"], {"basis": "STATUTORY"}, ADMIN),
        201,
    )

    assert_delinquency_assessment(statutory)
    assert statutory["basis"] == "STATUTORY"
    assert statutory["days_late"] == 60
    assert statutory["principal_cents"] == 357668
    assert statutory["interest_cents"] == 5292
    assert statutory["liquidated_damages_cents"] == 71534
    assert statutory["total_cents"] == 434494
    assert statutory["status"] == "ASSESSED"
    assert statutory["settlement_amount_cents"] is None
    assert statutory["waived_cents"] is None


def test_the_plan_schedule_basis_graces_the_interest_but_not_the_damages_tier(api):
    """PRD §3.6: "Effective days are `days_late` less the fund's `grace_days`,
    floored at zero, and `interest_cents` is the principal multiplied by
    `interest_rate_annual_bps`, divided by 10,000, multiplied by those effective
    days and divided by 365, rounded half up to whole cents."
    PRD §3.6: "The damages tier is keyed on the raw `days_late` and not on the
    effective days: 500 basis points when the report is 30 days late or fewer,
    1,000 basis points when it is between 31 and 60 days late inclusive, and
    2,000 basis points when it is more than 60 days late."
    PRD §3.6: "`liquidated_damages_cents` is then the larger of two figures — the
    principal multiplied by that tier and divided by 10,000, rounded half up to
    whole cents, and the fund's `ld_floor_cents` — so on a small principal the
    floor can lift the charge above the tiered percentage."

    Design: Difficulty/dual_variant_calc/delinquency_basis_statutory_vs_plan_schedule_diverge
    """
    base = setup_three_line_report_sixty_days_late()
    report_id = base["report"]["id"]

    statutory = assess_delinquency(report_id, "STATUTORY")
    plan_schedule = validate_success(
        api.create_delinquency_assessment(report_id, {"basis": "PLAN_SCHEDULE"}, ADMIN),
        201,
    )

    assert plan_schedule["basis"] == "PLAN_SCHEDULE"
    assert plan_schedule["days_late"] == 60, "the same clock instant, the same lateness"
    assert plan_schedule["principal_cents"] == 357668
    assert plan_schedule["interest_cents"] == 3969, "45 effective days rather than 60"
    assert plan_schedule["liquidated_damages_cents"] == 35767, "the 1000 bps tier"
    assert plan_schedule["total_cents"] == 397404

    assert statutory["total_cents"] - plan_schedule["total_cents"] == 37090, (
        "the two bases part company by 37090 cents on one identical report"
    )


def test_the_damages_tier_doubles_on_the_sixty_first_day(api):
    """PRD §3.6: "The damages tier is keyed on the raw `days_late` and not on the
    effective days: 500 basis points when the report is 30 days late or fewer,
    1,000 basis points when it is between 31 and 60 days late inclusive, and
    2,000 basis points when it is more than 60 days late."
    PRD §3.6: "Effective days are `days_late` less the fund's `grace_days`,
    floored at zero, and `interest_cents` is the principal multiplied by
    `interest_rate_annual_bps`, divided by 10,000, multiplied by those effective
    days and divided by 365, rounded half up to whole cents."
    PRD §3.6: "The second is open assessments: across every delinquency
    assessment raised on a report of this employer whose `status` is `ASSESSED`,
    add up that assessment's `total_cents`."

    Design: Corner/calculations/plan_schedule_ld_tier_flips_between_sixty_and_sixty_one_days
    """
    base = setup_three_line_report_sixty_days_late()
    report_id = base["report"]["id"]

    at_sixty = assess_delinquency(report_id, "PLAN_SCHEDULE")
    set_clock("2026-06-20T00:00:00Z")
    at_sixty_one = assess_delinquency(report_id, "PLAN_SCHEDULE")

    assert at_sixty["days_late"] == 60
    assert at_sixty["liquidated_damages_cents"] == 35767
    assert at_sixty["interest_cents"] == 3969
    assert at_sixty["total_cents"] == 397404

    assert at_sixty_one["days_late"] == 61
    assert at_sixty_one["liquidated_damages_cents"] == 71534, "the 2000 bps tier"
    assert at_sixty_one["interest_cents"] == 4057
    assert at_sixty_one["total_cents"] == 433259

    assert at_sixty["principal_cents"] == 357668
    assert at_sixty_one["principal_cents"] == 357668

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 1188331, (
        "357668 outstanding plus both open assessments"
    )


def test_a_settled_assessment_leaves_the_ledger_whole_not_partially(api):
    """PRD §3.6: "Settlement records the accepted cents in
    `settlement_amount_cents`, moves the assessment to `SETTLED`, and recomputes
    the employer ledger, from which the assessment now drops out entirely rather
    than being reduced to the settled figure; as with a remittance, a ledger that
    reaches 0 restores a suspended employer to `ACTIVE`."
    PRD §3.6: "Assessments that have been `SETTLED` or `WAIVED` leave the sum
    entirely — they do not contribute their settled or waived amount, they
    contribute nothing."
    PRD §3.6: "The assessments raised on a report may be listed and filtered by
    `status` and by `basis`."

    Design: Corner/calculations/employer_ledger_excludes_settled_assessment_regardless_of_settlement_amount
    """
    base = setup_assessed_report()
    assessment_id = base["assessment"]["id"]

    assert read_employer(base["employer"]["id"])["cumulative_delinquent_cents"] == 182831

    settled = validate_success(
        api.settle_delinquency_assessment(
            assessment_id, {"settlement_amount_cents": 40_000}, ADMIN
        )
    )

    assert settled["status"] == "SETTLED"
    assert settled["settlement_amount_cents"] == 40_000
    assert settled["waived_cents"] is None
    assert settled["total_cents"] == 100281, "the assessed total is not rewritten"

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 82550, (
        "only the unpaid contribution remains; the assessment left the sum entirely"
    )

    _rows, meta = validate_paginated(
        api.list_report_delinquency_assessments(
            base["report"]["id"], ADMIN, params={"status": "SETTLED"}
        )
    )
    assert meta["total_count"] == 1


def test_an_assessment_needs_both_lateness_and_an_outstanding_principal(api):
    """PRD §3.6: "The report must not be `SUPERSEDED`; `days_late` must be
    greater than 0, and an assessment demanded on a report that is not yet late
    is refused with `ERR_REPORT_NOT_DELINQUENT`."
    PRD §3.6: "`principal_cents` is the report's `total_contributions_due_cents`
    less its `amount_remitted_cents` as of that moment, and it must be strictly
    positive — a report with nothing outstanding is refused with
    `ERR_NO_DELINQUENT_PRINCIPAL`."

    Design: Corner/validations/delinquency_assessment_guards_reject_on_due_date_and_when_fully_paid
    """
    base = setup_employer_with_one_participant(
        name="Assessment Guard Fund", ein="36-6000003"
    )
    late_employer = base["employer"]
    paid_employer = validate_success(
        api.create_employer(
            {
                "fund_id": base["fund"]["id"],
                "legal_name": "Paid Up Piping",
                "ein": "36-7654322",
                "contribution_rate_millicents_per_hour": 825_500,
                "prior_year_contributions_cents": [4_000_000, 5_000_000, 6_000_000, 5_500_000, 4_500_000],
                "prior_year_base_units": [4800, 6000, 7200, 6600, 5400],
            },
            ADMIN,
        ),
        201,
    )

    late_report = file_single_line_report(
        late_employer["id"], base["participant"]["id"], "2026-03", 100.00
    )
    paid_report = file_single_line_report(
        paid_employer["id"], base["participant"]["id"], "2026-03", 100.00
    )
    remit(paid_report["id"], 82_550)

    set_clock("2026-04-20T00:00:00Z")
    validate_error(
        api.create_delinquency_assessment(late_report["id"], {"basis": "STATUTORY"}, ADMIN),
        ApiErrorId.ERR_REPORT_NOT_DELINQUENT.value,
    )

    set_clock("2026-06-19T00:00:00Z")
    validate_error(
        api.create_delinquency_assessment(paid_report["id"], {"basis": "STATUTORY"}, ADMIN),
        ApiErrorId.ERR_NO_DELINQUENT_PRINCIPAL.value,
    )

    settled_report = read_report(paid_report["id"])
    assert settled_report["payment_status"] == "PAID_IN_FULL"
    assert settled_report["amount_remitted_cents"] == 82550

    for report_id in (late_report["id"], paid_report["id"]):
        _rows, meta = validate_paginated(
            api.list_report_delinquency_assessments(report_id, ADMIN)
        )
        assert meta["total_count"] == 0


def test_money_bounds_refuse_overpayment_oversettlement_and_a_second_settlement(api):
    """PRD §3.6: "A report whose filing state is `SUPERSEDED` accepts no
    remittance and returns `ERR_REPORT_NOT_REMITTABLE`; an amount larger than the
    report's outstanding balance — its `total_contributions_due_cents` less its
    `amount_remitted_cents` — is refused with `ERR_REMITTANCE_EXCEEDS_BALANCE`."
    PRD §3.6: "A fund administrator may record a negotiated settlement by
    supplying `settlement_amount_cents`, which may not exceed the assessment's
    `total_cents` — an excess is refused with `ERR_SETTLEMENT_EXCEEDS_ASSESSMENT`
    — and which is only accepted while the assessment's `status` is still
    `ASSESSED`, an attempt against any other status being refused with
    `ERR_ASSESSMENT_INVALID_STATE`."

    Design: Corner/validations/money_bound_guards_reject_overpayment_oversettlement_and_double_settlement
    """
    base = setup_assessed_report()
    report_id = base["report"]["id"]
    assessment_id = base["assessment"]["id"]
    employer_headers = make_employer_headers(base["employer"]["id"])

    validate_error(
        api.remit_contribution_report(report_id, {"amount_cents": 82_551}, employer_headers),
        ApiErrorId.ERR_REMITTANCE_EXCEEDS_BALANCE.value,
    )
    assert read_report(report_id)["amount_remitted_cents"] == 0

    validate_error(
        api.settle_delinquency_assessment(
            assessment_id, {"settlement_amount_cents": 100_282}, ADMIN
        ),
        ApiErrorId.ERR_SETTLEMENT_EXCEEDS_ASSESSMENT.value,
    )

    settled = validate_success(
        api.settle_delinquency_assessment(
            assessment_id, {"settlement_amount_cents": 100_281}, ADMIN
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["settlement_amount_cents"] == 100281

    validate_error(
        api.settle_delinquency_assessment(
            assessment_id, {"settlement_amount_cents": 1}, ADMIN
        ),
        ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value,
    )

    assert read_employer(base["employer"]["id"])["cumulative_delinquent_cents"] == 82550


def test_a_superseded_report_refuses_the_remittance_before_the_money_bound_is_read(api):
    """PRD §3.6: "A report whose filing state is `SUPERSEDED` accepts no
    remittance and returns `ERR_REPORT_NOT_REMITTABLE`; an amount larger than the
    report's outstanding balance — its `total_contributions_due_cents` less its
    `amount_remitted_cents` — is refused with `ERR_REMITTANCE_EXCEEDS_BALANCE`."
    PRD §2.8: "**Payment-axis preconditions.** A report whose filing state is
    `SUPERSEDED` accepts no remittance (`ERR_REPORT_NOT_REMITTABLE`), and an
    installment that is already `PAID` or `DEFAULTED`, or one that is `MISSED`
    and whose cure window has closed, accepts no payment
    (`ERR_INSTALLMENT_NOT_PAYABLE`); both at HTTP 409."
    PRD §2.8: "The practical consequence worth internalizing: a governance
    failure surfaces before a money-bound failure, and a from-state failure
    surfaces before either."

    Design: Difficulty/priority_pair_validation_conflict/superseded_report_state_beats_remittance_fiscal
    """
    base = setup_superseded_report_pair()
    employer_headers = make_employer_headers(base["employer"]["id"])

    response = api.remit_contribution_report(
        base["original"]["id"], {"amount_cents": 999_999_999}, employer_headers
    )

    error_data = validate_error(response, ApiErrorId.ERR_REPORT_NOT_REMITTABLE.value)
    assert error_data["error_id"] != ApiErrorId.ERR_REMITTANCE_EXCEEDS_BALANCE.value
    assert response.status_code == 409


def test_the_refused_remittance_leaves_both_reports_exactly_as_they_stood(api):
    """PRD §3.4: "The first hop applies only to amendments: if
    `amends_report_id` is non-null, the report it names moves from `POSTED` to
    `SUPERSEDED` and its own `version` increments by 1."
    PRD §3.6: "A report whose filing state is `SUPERSEDED` accepts no remittance
    and returns `ERR_REPORT_NOT_REMITTABLE`; an amount larger than the report's
    outstanding balance — its `total_contributions_due_cents` less its
    `amount_remitted_cents` — is refused with `ERR_REMITTANCE_EXCEEDS_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/superseded_report_state_beats_remittance_fiscal
    """
    base = setup_superseded_report_pair()
    employer_headers = make_employer_headers(base["employer"]["id"])

    api.remit_contribution_report(
        base["original"]["id"], {"amount_cents": 999_999_999}, employer_headers
    )

    original = read_report(base["original"]["id"])
    assert original["filing_status"] == "SUPERSEDED"
    assert original["amount_remitted_cents"] == 0, "not one cent was applied"

    amendment = read_report(base["amendment"]["id"])
    assert amendment["filing_status"] == "POSTED"
    assert amendment["total_contributions_due_cents"] == 82550
