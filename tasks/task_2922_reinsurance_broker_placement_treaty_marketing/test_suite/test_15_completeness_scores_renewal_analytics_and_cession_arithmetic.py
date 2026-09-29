"""Weighted scoring, the certainty constant, staged renewal analytics and the cession waterfall.

Queue B — the ``calculations`` corner index (PRD §3.1, §3.2, §3.7, §3.8, §3.9):
the four weighted completeness components with their zero-record guard and
five-year clamp, a revision that rescores only its own package, the thirty-day
certainty constant across three month lengths, renewal analytics feeding each
rounded stage forward over a denominator that counts released lines, the
narrowest bucket of the cession waterfall on both layer types, and the fiduciary
balance projection that reads settled rows only.
"""
from test_helpers import (
    ACCOUNTANT,
    ACTUARY,
    CLOCK,
    COMPLIANCE,
    LEAD,
    ApiErrorId,
    acknowledge_disclosure,
    add_layer,
    agree_wording,
    api_client,
    approve_transaction,
    assert_append_only_fields,
    assert_instant_equals,
    assert_money_equals,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    bind_program,
    book_transaction,
    create_cedent,
    create_exposure_submission,
    create_layer,
    create_program,
    create_reinsurer,
    firm_order,
    generate_renewal_report,
    go_to_market,
    make_cedent_underwriter_headers,
    notify_claim,
    place_line,
    quote_on,
    raise_dispute,
    read_advocacy,
    read_cedent,
    read_dispute,
    read_layer,
    read_program,
    read_signing_line,
    read_submission,
    read_transaction,
    refresh,
    release_line,
    resolve_dispute,
    review_claim,
    revise_exposure_submission_payload,
    set_advocacy_route,
    set_clock,
    settle_transaction,
    setup_bound_program,
    setup_draft_program,
    sign_off_exposure,
    signoff,
    submit_for_review,
    submit_to_market,
    validate_error,
    validate_paginated,
    get_success_data,
)

# The three exposure packages of the scoring instance. Every score is
# 40 * (1 - flags/records) + 25 * min(years, 5)/5 + 25 * loss_pct/100 + 10 when
# an actuarial report is attached, rounded half up to two decimals.
ORDINARY_PACKAGE = {
    "package_label": "NW-PROP-2026-ORDINARY",
    "exposure_records_count": 1000,
    "data_quality_flags_count": 20,
    "historical_years_supplied": 5,
    "loss_history_completeness_pct": 90.0000,
    "actuarial_report_attached": True,
}
ORDINARY_SCORE = 96.70

# No records at all: the data-quality proportion is defined to be zero rather
# than a division by zero, so only 25 + 22.5 + 10 survive.
ZERO_RECORD_PACKAGE = {
    "package_label": "NW-PROP-2026-ZERO-RECORDS",
    "exposure_records_count": 0,
    "data_quality_flags_count": 0,
    "historical_years_supplied": 5,
    "loss_history_completeness_pct": 90.0000,
    "actuarial_report_attached": True,
}
ZERO_RECORD_SCORE = 57.50

# Seven years of history earn exactly the five-year target, so a spotless
# package tops out at the full hundred rather than overshooting it.
CLAMPED_PACKAGE = {
    "package_label": "NW-PROP-2026-CLAMPED",
    "exposure_records_count": 1000,
    "data_quality_flags_count": 0,
    "historical_years_supplied": 7,
    "loss_history_completeness_pct": 100.0000,
    "actuarial_report_attached": True,
}
FIVE_YEAR_PACKAGE = dict(
    CLAMPED_PACKAGE, package_label="NW-PROP-2026-FIVE-YEARS", historical_years_supplied=5
)
PERFECT_SCORE = 100.00

# The revision that re-scores package A: half the records flagged and the
# actuarial report withdrawn, so 20 + 25 + 22.5 + 0.
REVISION_FIELDS = {"data_quality_flags_count": 500, "actuarial_report_attached": False}
REVISED_SCORE = 67.50
REJECTION_NOTE = "Data quality scrub incomplete"


def _revise(submission_id: str, cedent_id: str, **fields):
    """Resupply data on a rejected package as the cedent that owns it."""
    return get_success_data(
        api_client.revise_exposure_submission(
            submission_id,
            revise_exposure_submission_payload(**fields),
            make_cedent_underwriter_headers(cedent_id),
        )
    )


def _packages(program_id: str):
    """Every exposure package of the program."""
    rows, _meta = validate_paginated(
        api_client.list_program_exposure_submissions(program_id, LEAD)
    )
    return rows


def test_the_completeness_score_adds_the_four_weighted_components():
    """1000 records with 20 flags, five years, 90.0000% loss history and a report score 96.70.

    PRD: "The four weighted components are added together and the resulting raw
    total is rounded half up to two decimal places to give `completeness_score`."

    Design: Corner/calculations/completeness_score_combines_four_weighted_components_with_clamp_and_zero_record_guard
    """
    ctx = setup_draft_program(with_layer=False, submission_overrides=ORDINARY_PACKAGE)

    package = ctx["submission"]
    assert_score_equals(package["completeness_score"], ORDINARY_SCORE, "completeness_score")
    assert_status(package, "status", "DRAFT")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "DRAFT")
    assert_score_equals(
        read_submission(package["id"])["completeness_score"],
        ORDINARY_SCORE,
        "completeness_score on read-back",
    )


def test_a_package_with_no_exposure_records_scores_nothing_on_data_quality():
    """Zero records forfeit the whole 40-point quality component, leaving 57.50.

    PRD: "When no records at all were supplied, this proportion is defined to be
    zero rather than an arithmetic error — a package with an
    `exposure_records_count` of zero scores nothing on data quality and does not
    crash the scorer."

    Design: Corner/calculations/completeness_score_combines_four_weighted_components_with_clamp_and_zero_record_guard
    """
    ctx = setup_draft_program(with_layer=False, submission_overrides=ORDINARY_PACKAGE)
    program_id = ctx["program"]["id"]

    zero_record = create_exposure_submission(
        program_id, ctx["cedent"]["id"], **ZERO_RECORD_PACKAGE
    )

    assert_score_equals(
        zero_record["completeness_score"], ZERO_RECORD_SCORE, "zero-record completeness_score"
    )
    assert_status(zero_record, "status", "DRAFT")
    assert_score_equals(
        read_submission(ctx["submission"]["id"])["completeness_score"],
        ORDINARY_SCORE,
        "the ordinary package is untouched",
    )
    assert_status(read_program(program_id), "placement_status", "DRAFT")


def test_seven_years_of_history_clamp_to_the_five_year_target():
    """Seven years and five years both earn the full 25 points, so both packages score 100.00.

    PRD: "The second component is worth 25 points and rewards loss history: it is
    the number of years supplied, capped at a target of five years, divided by
    five, so five or more years earns the full 25 and four years earns four
    fifths of it."

    Design: Corner/calculations/completeness_score_combines_four_weighted_components_with_clamp_and_zero_record_guard
    """
    ctx = setup_draft_program(with_layer=False, submission_overrides=CLAMPED_PACKAGE)
    program_id = ctx["program"]["id"]

    five_years = create_exposure_submission(
        program_id, ctx["cedent"]["id"], **FIVE_YEAR_PACKAGE
    )

    assert_score_equals(
        ctx["submission"]["completeness_score"], PERFECT_SCORE, "seven-year completeness_score"
    )
    assert_score_equals(
        five_years["completeness_score"], PERFECT_SCORE, "five-year completeness_score"
    )
    assert ctx["submission"]["historical_years_supplied"] == 7, (
        "the seven supplied years are recorded as supplied, only the scorer caps them, "
        f"got {ctx['submission']['historical_years_supplied']}"
    )

    rows = _packages(program_id)
    assert len(rows) == 2, f"both packages must be on record, got {len(rows)}"
    for row in rows:
        assert_status(row, "status", "DRAFT")


def _two_packages_with_one_rejected():
    """Package A (96.70) is rejected with a note; package B (100.00) is left in DRAFT."""
    ctx = setup_draft_program(with_layer=False, submission_overrides=ORDINARY_PACKAGE)
    ctx["package_a"] = ctx["submission"]
    ctx["package_b"] = create_exposure_submission(
        ctx["program"]["id"], ctx["cedent"]["id"], **CLAMPED_PACKAGE
    )
    submit_for_review(ctx["package_a"]["id"])
    ctx["package_a"] = signoff(
        ctx["package_a"]["id"], "REJECTED", review_note=REJECTION_NOTE
    )
    return refresh(ctx)


def test_revising_a_rejected_package_rescores_it_and_leaves_its_sibling_alone():
    """A drops from 96.70 to 67.50 on revision while B stays at 100.00.

    PRD: "The ceding insurer then resupplies data on its own rejected package,
    moving it back to `DRAFT`: this revision accepts any subset of
    `exposure_records_count`, `data_quality_flags_count`,
    `historical_years_supplied`, `cat_model_version`,
    `loss_history_completeness_pct` and `actuarial_report_attached`, overwrites
    exactly the fields supplied, and recomputes `completeness_score` from the
    merged result."

    Design: Corner/calculations/revising_a_rejected_package_recomputes_only_its_own_score
    """
    ctx = _two_packages_with_one_rejected()
    assert_score_equals(ctx["package_a"]["completeness_score"], ORDINARY_SCORE, "A before")
    assert_score_equals(ctx["package_b"]["completeness_score"], PERFECT_SCORE, "B before")
    assert_status(ctx["package_a"], "status", "REJECTED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "DRAFT")

    revised = _revise(ctx["package_a"]["id"], ctx["cedent"]["id"], **REVISION_FIELDS)

    assert_score_equals(revised["completeness_score"], REVISED_SCORE, "A after revision")
    assert_status(revised, "status", "DRAFT")

    sibling = read_submission(ctx["package_b"]["id"])
    assert_score_equals(sibling["completeness_score"], PERFECT_SCORE, "B after A's revision")
    assert_status(sibling, "status", "DRAFT")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "DRAFT")


def test_a_revision_overwrites_exactly_the_fields_supplied():
    """The two fields left out of the revision keep their original values, and so does the note.

    PRD: "The ceding insurer then resupplies data on its own rejected package,
    moving it back to `DRAFT`: this revision accepts any subset of
    `exposure_records_count`, `data_quality_flags_count`,
    `historical_years_supplied`, `cat_model_version`,
    `loss_history_completeness_pct` and `actuarial_report_attached`, overwrites
    exactly the fields supplied, and recomputes `completeness_score` from the
    merged result."

    Design: Corner/calculations/revising_a_rejected_package_recomputes_only_its_own_score
    """
    ctx = _two_packages_with_one_rejected()

    _revise(ctx["package_a"]["id"], ctx["cedent"]["id"], **REVISION_FIELDS)

    package = read_submission(ctx["package_a"]["id"])
    assert_score_equals(package["completeness_score"], REVISED_SCORE, "completeness_score")
    assert_status(package, "status", "DRAFT")
    assert package["data_quality_flags_count"] == 500, (
        f"the supplied flag count must be overwritten, got {package['data_quality_flags_count']}"
    )
    assert package["actuarial_report_attached"] is False, (
        "the supplied report flag must be overwritten"
    )
    assert package["exposure_records_count"] == 1000, (
        f"the record count was not supplied, got {package['exposure_records_count']}"
    )
    assert package["historical_years_supplied"] == 5, (
        f"the year count was not supplied, got {package['historical_years_supplied']}"
    )
    assert_pct_equals(
        package["loss_history_completeness_pct"], 90.0000, "loss_history_completeness_pct"
    )
    assert package["review_note"] == REJECTION_NOTE, (
        f"the review note was not a revisable field, got {package['review_note']!r}"
    )


# Three cedents so that three programs incepting in three different months never
# share a treaty period, and the thirty-day constant is visible on its own.
CERTAINTY_CEDENTS = [
    {"name": "Northwind Mutual", "domicile_code": "USNYC", "financial_rating": "A"},
    {"name": "Southgate Casualty", "domicile_code": "GBLON", "financial_rating": "A"},
    {"name": "Eastwater Marine", "domicile_code": "SGSIN", "financial_rating": "B_PLUS"},
]

# inception -> the thirty-calendar-day deadline. January is 31 days long so the
# deadline lands inside January; February 2026 is 28 days long so thirty days
# from the first of February reaches the third of March, not the first.
CERTAINTY_PROGRAMS = [
    {
        "program_name": "January Start",
        "line_of_business": "PROPERTY",
        "inception_date": "2026-01-01T00:00:00.000Z",
        "expiry_date": "2027-01-01T00:00:00.000Z",
        "estimated_premium_income_minor": 2_000_000_000,
        "expected_deadline": "2026-01-31T00:00:00.000Z",
    },
    {
        "program_name": "February Start",
        "line_of_business": "CASUALTY",
        "inception_date": "2026-02-01T00:00:00.000Z",
        "expiry_date": "2027-02-01T00:00:00.000Z",
        "estimated_premium_income_minor": 1_000_000_000,
        "expected_deadline": "2026-03-03T00:00:00.000Z",
    },
    {
        "program_name": "Mid July Start",
        "line_of_business": "MARINE",
        "inception_date": "2026-07-15T00:00:00.000Z",
        "expiry_date": "2027-07-15T00:00:00.000Z",
        "estimated_premium_income_minor": 500_000_000,
        "expected_deadline": "2026-08-14T00:00:00.000Z",
    },
]


def _three_programs_incepting_in_three_months():
    """One program per cedent, incepting in a 31-day, a 28-day and a mid-month period."""
    set_clock(CLOCK["PLACEMENT_START"])
    programs = []
    for cedent_spec, program_spec in zip(CERTAINTY_CEDENTS, CERTAINTY_PROGRAMS):
        cedent = create_cedent(**cedent_spec)
        fields = {
            key: value for key, value in program_spec.items() if key != "expected_deadline"
        }
        programs.append(create_program(cedent["id"], underwriting_year=2026, **fields))
    return programs


def test_the_certainty_deadline_adds_thirty_calendar_days_to_every_inception():
    """January, a 28-day February and a mid-July start land on 01-31, 03-03 and 08-14.

    PRD: "At creation the program's `contract_certainty_deadline` is materialised
    as the `inception_date` advanced by thirty days, and
    `disclosure_acknowledged` is false."

    Design: Corner/calculations/certainty_deadline_adds_the_thirty_day_constant_to_inception_across_month_lengths
    """
    programs = _three_programs_incepting_in_three_months()

    for program, spec in zip(programs, CERTAINTY_PROGRAMS):
        label = f"{spec['program_name']} contract_certainty_deadline"
        assert_instant_equals(
            program["contract_certainty_deadline"], spec["expected_deadline"], label
        )
        assert_instant_equals(
            program["inception_date"], spec["inception_date"], f"{spec['program_name']} inception"
        )
        assert program["disclosure_acknowledged"] is False, (
            f"{spec['program_name']} must start with disclosure_acknowledged false"
        )
        assert_status(program, "placement_status", "DRAFT")
        assert_status(program, "documentation_status", "NOT_STARTED")


def test_a_checkpoint_landing_exactly_on_the_deadline_is_not_yet_a_breach():
    """The clock moved to 2026-01-31 exactly is refused, and the other two deadlines do not move.

    PRD: "The checkpoint requires the current logical clock to be **strictly
    after** the deadline — landing exactly on the deadline instant is not yet a
    breach — and requires the `documentation_status` to be `NOT_STARTED`,
    `SLIP_ISSUED` or `WORDING_DRAFTED`, since a program that already has agreed
    wording, or is already in breach, has nothing to test."

    Design: Corner/calculations/certainty_deadline_adds_the_thirty_day_constant_to_inception_across_month_lengths
    """
    january, february, july = _three_programs_incepting_in_three_months()

    set_clock(CERTAINTY_PROGRAMS[0]["expected_deadline"])
    response = api_client.documentation_checkpoint(january["id"], COMPLIANCE)

    validate_error(response, ApiErrorId.ERR_CERTAINTY_NOT_BREACHED.value)

    refused = read_program(january["id"])
    assert_status(refused, "documentation_status", "NOT_STARTED")
    assert_status(refused, "placement_status", "DRAFT")
    assert_instant_equals(
        refused["contract_certainty_deadline"],
        CERTAINTY_PROGRAMS[0]["expected_deadline"],
        "the refused program keeps its deadline",
    )

    for program, spec in ((february, CERTAINTY_PROGRAMS[1]), (july, CERTAINTY_PROGRAMS[2])):
        later = read_program(program["id"])
        assert_instant_equals(
            later["contract_certainty_deadline"],
            spec["expected_deadline"],
            f"{spec['program_name']} deadline survives the clock move",
        )
        assert_status(later, "documentation_status", "NOT_STARTED")


# The prior placement year: a smaller CAT layer priced at 7.0000 base on a
# 1,000,000,000 subject base, so 7.35 loaded, 73,500,000 provisional, tier 5%,
# frozen at 69,825,000 against a bound limit of 800,000,000.
PRIOR_LAYER = {
    "layer_label": "PROP CAT 800M xs 2B",
    "layer_type": "CATASTROPHE",
    "attachment_minor": 2_000_000_000,
    "limit_minor": 800_000_000,
    "base_rate_pct": 7.0000,
    "subject_premium_base_minor": 1_000_000_000,
    "expected_loss_cost_minor": 48_000_000,
    "reinstatements_total": 1,
    "reinstatement_premium_pct": 100.0000,
    "sublimit_minor": 0,
}
PRIOR_PREMIUM_MINOR = 69_825_000
CURRENT_PREMIUM_MINOR = 97_125_000

PRIOR_CLOCK = "2025-01-01T00:00:00.000Z"
PRIOR_RESPONSE_DEADLINE = "2025-02-01T00:00:00.000Z"
PRIOR_QUOTE_EXPIRY = "2025-02-15T00:00:00.000Z"

# 8.7281 = 100 * 69,825,000 / 800,000,000 rounded once at four decimals, and
# 9.7125 = 100 * 97,125,000 / 1,000,000,000.
PRIOR_RATE_ON_LINE_PCT = 8.7281
CURRENT_RATE_ON_LINE_PCT = 9.7125
RATE_CHANGE_PCT = 11.28
EXPOSURE_CHANGE_PCT = 25.00
RISK_ADJUSTED_RATE_CHANGE_PCT = -1.22
# 100.0000 bound over 120.0000 ever offered, Bravo's released 20.0000 included.
PLACEMENT_EFFICIENCY_PCT = 83.33
# 0.6 * (-1.22) + 0.4 * (100 - 83.33) = 5.936, so 5.94; unstaged it reads 5.93.
MARKET_CONDITION_INDEX = 5.94


def _renewal_placement():
    """A bound 2025 program and its 2026 renewal, whose Bravo line was handed back.

    Bravo takes its 20.0000 line first and Alpha fills the layer afterwards,
    because a firm order is only admitted while the program is still
    ``IN_MARKET`` and Alpha's full line carries the program to ``FIRM_ORDER``.
    """
    set_clock(PRIOR_CLOCK)
    cedent = create_cedent(name="Northwind Mutual")
    charlie = create_reinsurer(name="Charlie Re", lead_authorised=True)
    alpha = create_reinsurer(name="Alpha Re", lead_authorised=True)
    bravo = create_reinsurer(name="Bravo Re", security_rating="A", lead_authorised=False)

    prior = create_program(
        cedent["id"],
        program_name="Northwind Property CAT 2025",
        underwriting_year=2025,
        inception_date=PRIOR_CLOCK,
        expiry_date="2026-01-01T00:00:00.000Z",
        estimated_premium_income_minor=1_600_000_000,
        brokerage_pct=2.5000,
    )
    prior_submission = create_exposure_submission(
        prior["id"], cedent["id"], package_label="NW-2025-EDP", cat_model_version="RMS-22.1"
    )
    prior_layer = create_layer(prior["id"], **PRIOR_LAYER)
    sign_off_exposure(prior_submission["id"])
    go_to_market(prior["id"])
    prior_market_submission = submit_to_market(
        prior_layer["id"], charlie["id"], response_deadline=PRIOR_RESPONSE_DEADLINE
    )
    prior_quote = quote_on(
        prior_market_submission["id"],
        charlie["id"],
        quoted_rate_pct=7.0000,
        expires_at=PRIOR_QUOTE_EXPIRY,
        is_lead=True,
    )
    firm_order(prior_quote["id"], 100.0000, layer_id=prior_layer["id"])
    acknowledge_disclosure(prior["id"], cedent["id"], brokerage_pct=2.5000)
    prior = bind_program(prior["id"])

    set_clock(CLOCK["PLACEMENT_START"])
    program = create_program(
        cedent["id"],
        program_name="Northwind Property CAT 2026",
        underwriting_year=2026,
        brokerage_pct=2.5000,
        prior_program_id=prior["id"],
    )
    submission = create_exposure_submission(
        program["id"], cedent["id"], package_label="NW-2026-EDP"
    )
    layer = create_layer(program["id"])
    sign_off_exposure(submission["id"])
    go_to_market(program["id"])

    bravo_submission = submit_to_market(layer["id"], bravo["id"])
    alpha_submission = submit_to_market(layer["id"], alpha["id"])
    bravo_quote = quote_on(
        bravo_submission["id"],
        bravo["id"],
        offered_line_pct=20.0000,
        quoted_rate_pct=8.5000,
        is_lead=False,
    )
    alpha_quote = quote_on(alpha_submission["id"], alpha["id"], is_lead=True)
    bravo_line = firm_order(bravo_quote["id"], 20.0000, layer_id=layer["id"])
    alpha_line = firm_order(alpha_quote["id"], 100.0000, layer_id=layer["id"])
    released = release_line(bravo_line["id"])
    acknowledge_disclosure(program["id"], cedent["id"], brokerage_pct=2.5000)
    program = bind_program(program["id"])

    return {
        "cedent": cedent,
        "prior_program": prior,
        "prior_layer": prior_layer,
        "program": program,
        "layer": layer,
        "alpha_line": alpha_line,
        "bravo_line": released,
    }


def test_the_two_rates_on_line_are_each_rounded_once_at_four_decimals():
    """69,825,000 over 800,000,000 reads 8.7281 and 97,125,000 over 1,000,000,000 reads 9.7125.

    PRD: "The rate on line of a program is one hundred multiplied by its
    `gross_written_premium_minor` and divided by the total `limit_minor` of its
    `BOUND` layers, rounded half up to four decimal places, and is `0.0000` when
    the program has no bound limit at all."

    Design: Corner/calculations/renewal_analytics_feeds_each_rounded_stage_forward_and_counts_released_lines
    """
    ctx = _renewal_placement()

    assert_money_equals(
        read_layer(ctx["prior_layer"]["id"])["quoted_gross_premium_minor"],
        PRIOR_PREMIUM_MINOR,
        "prior quoted_gross_premium_minor",
    )
    assert_money_equals(
        read_layer(ctx["layer"]["id"])["quoted_gross_premium_minor"],
        CURRENT_PREMIUM_MINOR,
        "current quoted_gross_premium_minor",
    )
    assert_money_equals(
        ctx["prior_program"]["gross_written_premium_minor"],
        PRIOR_PREMIUM_MINOR,
        "prior gross_written_premium_minor",
    )
    assert_money_equals(
        ctx["program"]["gross_written_premium_minor"],
        CURRENT_PREMIUM_MINOR,
        "current gross_written_premium_minor",
    )

    report = generate_renewal_report(ctx["program"]["id"])

    assert_pct_equals(
        report["prior_rate_on_line_pct"], PRIOR_RATE_ON_LINE_PCT, "prior_rate_on_line_pct"
    )
    assert_pct_equals(
        report["current_rate_on_line_pct"],
        CURRENT_RATE_ON_LINE_PCT,
        "current_rate_on_line_pct",
    )


def test_every_change_figure_consumes_the_already_rounded_rate_on_line():
    """11.28 against a 25.00 exposure rise leaves a risk-adjusted change of -1.22.

    PRD: "Every downstream figure consumes the **already-rounded** rate on line
    rather than the unrounded ratio; the rounding order is part of the contract."

    Design: Corner/calculations/renewal_analytics_feeds_each_rounded_stage_forward_and_counts_released_lines
    """
    ctx = _renewal_placement()

    report = generate_renewal_report(ctx["program"]["id"])

    assert_score_equals(report["rate_change_pct"], RATE_CHANGE_PCT, "rate_change_pct")
    assert_score_equals(
        report["exposure_change_pct"], EXPOSURE_CHANGE_PCT, "exposure_change_pct"
    )
    assert_score_equals(
        report["risk_adjusted_rate_change_pct"],
        RISK_ADJUSTED_RATE_CHANGE_PCT,
        "risk_adjusted_rate_change_pct",
    )
    assert_score_equals(
        report["market_condition_index"], MARKET_CONDITION_INDEX, "market_condition_index"
    )


def test_the_released_line_still_counts_in_the_efficiency_denominator():
    """A 100.0000 bound line over 120.0000 ever offered reads 83.33, so the index is 5.94.

    PRD: "Its denominator is the sum of `written_line_pct` over **every** signing
    line of this program's layers whatever its status, `RELEASED` lines
    emphatically included, because a line the broker had to hand back was still
    capacity the broker had to find."

    Design: Corner/calculations/renewal_analytics_feeds_each_rounded_stage_forward_and_counts_released_lines
    """
    ctx = _renewal_placement()

    handed_back = read_signing_line(ctx["bravo_line"]["id"])
    assert_status(handed_back, "status", "RELEASED")
    assert_pct_equals(handed_back["written_line_pct"], 20.0000, "released written_line_pct")
    bound = read_signing_line(ctx["alpha_line"]["id"])
    assert_status(bound, "status", "BOUND")
    assert_pct_equals(bound["signed_line_pct"], 100.0000, "bound signed_line_pct")

    report = generate_renewal_report(ctx["program"]["id"])

    assert_score_equals(
        report["placement_efficiency_pct"],
        PLACEMENT_EFFICIENCY_PCT,
        "placement_efficiency_pct",
    )
    assert_score_equals(
        report["market_condition_index"], MARKET_CONDITION_INDEX, "market_condition_index"
    )
    assert_instant_equals(report["as_of"], CLOCK["PLACEMENT_START"], "as_of")
    assert report["generated_by_user_id"] == "act-1", (
        f"the generating actuary must be recorded, got {report['generated_by_user_id']!r}"
    )
    assert report["program_id"] == ctx["program"]["id"], "the report names its own program"
    assert_append_only_fields(report)

    rows, _meta = validate_paginated(
        api_client.list_program_renewal_reports(ctx["program"]["id"], ACTUARY)
    )
    assert len(rows) == 1, f"exactly one report was generated, got {len(rows)}"


# A quota-share layer whose 50,000,000 limit is deliberately wider than the
# 40.0000% share of the test loss, so the subject amount itself binds.
WATERFALL_QS_LAYER = {
    "layer_label": "PROP QS 40pct",
    "layer_type": "QUOTA_SHARE",
    "attachment_minor": 0,
    "limit_minor": 50_000_000,
    "cession_pct": 40.0000,
    "base_rate_pct": 40.0000,
    "subject_premium_base_minor": 200_000_000,
    "expected_loss_cost_minor": 30_000_000,
    "ceding_commission_pct": 25.0000,
    "reinstatements_total": 0,
    "reinstatement_premium_pct": 0.0000,
    "sublimit_minor": 0,
}
# The catastrophe layer carries an agreed per-event sublimit that is narrower
# than both its own limit and the aggregate, so the sublimit binds instead.
WATERFALL_CAT_LAYER = {"sublimit_minor": 250_000_000}

WATERFALL_CLOCK = "2026-03-01T00:00:00.000Z"
EVENT_DATE = "2026-02-20T00:00:00.000Z"
QS_GROSS_CLAIM_MINOR = 100_000_000
QS_CEDED_MINOR = 40_000_000
CAT_GROSS_CLAIM_MINOR = 2_600_000_000
CAT_CEDED_MINOR = 250_000_000
DISPUTED_MINOR = 100_000_000
ARBITRATION_COST_MINOR = 3_750_000
COLLECTIBLE_WHILE_RAISED_MINOR = 150_000_000
CONCEDED_MINOR = 40_000_000
COLLECTIBLE_AFTER_PARTIAL_MINOR = 190_000_000
RESOLUTION_NOTE = "Exclusion partially conceded"

WATERFALL_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 2_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    },
]


def _mixed_bound_program():
    """One bound program carrying a quota-share layer and a catastrophe layer.

    Both layers are cut while the file is still ``DRAFT``, since a layer cannot be
    added from a later placement state. The quota-share line is taken first: the
    program only reaches ``FIRM_ORDER`` once the catastrophe layer fills too, so
    both firm orders land while the program is still ``IN_MARKET``.
    """
    ctx = setup_draft_program(
        layer_kind="QS",
        layer_overrides=WATERFALL_QS_LAYER,
        market_specs=WATERFALL_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Mixed 2026", "brokerage_pct": 2.5000},
    )
    ctx["qs_layer"] = ctx["layer"]
    ctx["cat_layer"] = add_layer(ctx, layer_kind="CAT", **WATERFALL_CAT_LAYER)
    ctx["submission"] = sign_off_exposure(ctx["submission"]["id"])
    ctx["program"] = go_to_market(ctx["program"]["id"])

    qs_line = place_line(
        ctx,
        market_index=0,
        layer_index=0,
        accepted_line_pct=100.0000,
        quote_overrides={"quoted_rate_pct": 40.0000, "ceding_commission_pct": 25.0000,
                         "reinstatements_offered": 0, "sublimit_minor": 0},
        is_lead=True,
    )
    cat_line = place_line(
        ctx,
        market_index=1,
        layer_index=1,
        accepted_line_pct=100.0000,
        quote_overrides={"sublimit_minor": 250_000_000},
        is_lead=True,
    )
    acknowledge_disclosure(ctx["program"]["id"], ctx["cedent"]["id"], brokerage_pct=2.5000)
    ctx["program"] = bind_program(ctx["program"]["id"])
    ctx["qs_line"] = qs_line
    ctx["cat_line"] = cat_line
    set_clock(WATERFALL_CLOCK)
    return ctx


def _notify_both_losses(ctx):
    """A 100,000,000 ground-up loss on the share layer and a 2,600,000,000 one on the cat layer."""
    qs_advocacy = notify_claim(
        ctx["qs_layer"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-QS-CLM-001",
        event_date=EVENT_DATE,
        gross_claim_minor=QS_GROSS_CLAIM_MINOR,
    )
    cat_advocacy = notify_claim(
        ctx["cat_layer"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-CAT-CLM-001",
        event_date=EVENT_DATE,
        gross_claim_minor=CAT_GROSS_CLAIM_MINOR,
    )
    return qs_advocacy, cat_advocacy


def test_the_quota_share_layer_cedes_its_agreed_share_of_the_ground_up_loss():
    """40.0000% of a 100,000,000 loss cedes 40,000,000, and the 50,000,000 limit never bites.

    PRD: "On a `QUOTA_SHARE` layer the subject amount is the `gross_claim_minor`
    multiplied by the layer's `cession_pct` and divided by one hundred, rounded
    half up to whole minor units — the layer takes its agreed share of every
    loss."

    Design: Corner/calculations/cession_waterfall_lets_the_narrowest_bucket_bind_on_both_layer_types
    """
    ctx = _mixed_bound_program()

    qs_advocacy, _cat_advocacy = _notify_both_losses(ctx)

    assert_money_equals(qs_advocacy["ceded_claim_minor"], QS_CEDED_MINOR, "ceded_claim_minor")
    assert_money_equals(
        qs_advocacy["collectible_minor"], QS_CEDED_MINOR, "collectible_minor"
    )
    assert_money_equals(qs_advocacy["disputed_minor"], 0, "disputed_minor")
    assert_status(qs_advocacy, "status", "NOTIFIED")

    layer = read_layer(ctx["qs_layer"]["id"])
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor")
    assert_money_equals(layer["incurred_ceded_minor"], 0, "incurred_ceded_minor")


def test_the_agreed_sublimit_binds_ahead_of_the_limit_and_the_aggregate():
    """A 600,000,000 excess loss is cut to the 250,000,000 per-event sublimit.

    PRD: "The `ceded_claim_minor` is then the minimum of the subject amount, the
    per-event cap, the layer's `limit_minor` and the aggregate available amount."

    Design: Corner/calculations/cession_waterfall_lets_the_narrowest_bucket_bind_on_both_layer_types
    """
    ctx = _mixed_bound_program()

    _qs_advocacy, cat_advocacy = _notify_both_losses(ctx)

    assert_money_equals(cat_advocacy["ceded_claim_minor"], CAT_CEDED_MINOR, "ceded_claim_minor")
    assert_money_equals(
        cat_advocacy["collectible_minor"], CAT_CEDED_MINOR, "collectible_minor"
    )
    assert cat_advocacy["reinstatement_triggered"] is False, (
        "notification alone never consumes a reinstatement"
    )
    assert_money_equals(
        cat_advocacy["arbitration_cost_minor"], 0, "arbitration_cost_minor before any route"
    )
    assert_status(cat_advocacy, "status", "NOTIFIED")

    layer = read_layer(ctx["cat_layer"]["id"])
    assert_money_equals(layer["sublimit_minor"], 250_000_000, "the layer's own sublimit_minor")
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 0, (
        f"notification never erodes, got reinstatements_used {layer['reinstatements_used']}"
    )


def test_the_arbitration_route_accrues_one_and_a_half_per_cent_of_the_ceded_amount():
    """250,000,000 ceded accrues 3,750,000 of arbitration cost while 100,000,000 stays contested.

    PRD: "Separately, `arbitration_cost_minor` is the `ceded_claim_minor`
    multiplied by one and a half per cent, rounded half up to whole minor units,
    when the `advocacy_route` is `ARBITRATION`, and 0 otherwise."

    Design: Corner/calculations/cession_waterfall_lets_the_narrowest_bucket_bind_on_both_layer_types
    """
    ctx = _mixed_bound_program()
    _qs_advocacy, cat_advocacy = _notify_both_losses(ctx)

    review_claim(cat_advocacy["id"])
    raise_dispute(
        cat_advocacy["id"],
        ctx["reinsurers"][1]["id"],
        ctx["cat_line"]["id"],
        DISPUTED_MINOR,
        dispute_reason="EXCLUSION_APPLIES",
    )
    routed = set_advocacy_route(cat_advocacy["id"], "ARBITRATION")

    assert routed["advocacy_route"] == "ARBITRATION", (
        f"the chosen route must be recorded, got {routed['advocacy_route']!r}"
    )
    assert_money_equals(
        routed["arbitration_cost_minor"], ARBITRATION_COST_MINOR, "arbitration_cost_minor"
    )
    assert_money_equals(routed["disputed_minor"], DISPUTED_MINOR, "disputed_minor")
    assert_money_equals(
        routed["collectible_minor"], COLLECTIBLE_WHILE_RAISED_MINOR, "collectible_minor"
    )
    assert_money_equals(routed["ceded_claim_minor"], CAT_CEDED_MINOR, "ceded_claim_minor")
    assert_status(routed, "status", "ADVOCACY_ARBITRATION")


def test_a_partial_settlement_leaves_only_the_unconceded_part_contested():
    """Conceding 40,000,000 of a 100,000,000 dispute lifts the collectible to 190,000,000.

    PRD: "Each dispute contributes according to its own status: a dispute still
    `RAISED` contributes its full `disputed_minor`; a dispute `UPHELD`, meaning
    the market's objection succeeded, also contributes its full `disputed_minor`;
    a dispute `SETTLED_PARTIAL` contributes its `disputed_minor` less the
    `settled_minor` the market conceded; and a `WITHDRAWN` dispute contributes
    nothing at all, because the market conceded in full."

    Design: Corner/calculations/cession_waterfall_lets_the_narrowest_bucket_bind_on_both_layer_types
    """
    ctx = _mixed_bound_program()
    qs_advocacy, cat_advocacy = _notify_both_losses(ctx)
    review_claim(cat_advocacy["id"])
    dispute = raise_dispute(
        cat_advocacy["id"],
        ctx["reinsurers"][1]["id"],
        ctx["cat_line"]["id"],
        DISPUTED_MINOR,
        dispute_reason="EXCLUSION_APPLIES",
    )
    set_advocacy_route(cat_advocacy["id"], "ARBITRATION")

    resolved = resolve_dispute(
        dispute["id"], "SETTLED_PARTIAL", CONCEDED_MINOR, resolution_note=RESOLUTION_NOTE
    )

    assert_status(resolved, "status", "SETTLED_PARTIAL")
    assert_money_equals(resolved["settled_minor"], CONCEDED_MINOR, "settled_minor")
    assert_money_equals(
        read_dispute(dispute["id"])["disputed_minor"], DISPUTED_MINOR, "disputed_minor on the dispute"
    )

    file_ = read_advocacy(cat_advocacy["id"])
    assert_money_equals(
        file_["disputed_minor"], DISPUTED_MINOR - CONCEDED_MINOR, "disputed_minor on the file"
    )
    assert_money_equals(
        file_["collectible_minor"], COLLECTIBLE_AFTER_PARTIAL_MINOR, "collectible_minor"
    )
    assert_status(file_, "status", "RESOLVED")
    assert_money_equals(
        read_layer(ctx["cat_layer"]["id"])["incurred_ceded_minor"],
        CAT_CEDED_MINOR,
        "incurred_ceded_minor",
    )

    untouched = read_advocacy(qs_advocacy["id"])
    assert_status(untouched, "status", "NOTIFIED")
    assert_money_equals(untouched["ceded_claim_minor"], QS_CEDED_MINOR, "QS ceded_claim_minor")
    assert_money_equals(untouched["disputed_minor"], 0, "QS disputed_minor")
    assert_money_equals(untouched["collectible_minor"], QS_CEDED_MINOR, "QS collectible_minor")


# The bind money on the canonical CAT placement: 97,125,000 gross, 2.5000%
# brokerage taken on the single bound line, and nothing left over.
BOUND_GWP_MINOR = 97_125_000
BROKERAGE_EARNED_MINOR = 2_428_125
NET_REMITTANCE_MINOR = 94_696_875
SECOND_RECEIPT_MINOR = 20_000_000


def _bound_program_with_agreed_wording():
    """A BOUND placement whose wording is agreed, so an outbound remittance may settle."""
    ctx = setup_bound_program()
    agree_wording(ctx["program"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def _walk_the_ledger(ctx):
    """A settled receipt, a receipt left PENDING, and a remittance left APPROVED."""
    program_id = ctx["program"]["id"]
    receipt = book_transaction(program_id, "CEDENT_RECEIPT", BOUND_GWP_MINOR)
    approve_transaction(receipt["id"])
    receipt = settle_transaction(receipt["id"])
    pending_receipt = book_transaction(program_id, "CEDENT_RECEIPT", SECOND_RECEIPT_MINOR)
    remittance = book_transaction(
        program_id,
        "REINSURER_REMITTANCE",
        NET_REMITTANCE_MINOR,
        signing_line_id=ctx["signing_lines"][0]["id"],
    )
    remittance = approve_transaction(remittance["id"])
    return receipt, pending_receipt, remittance


def test_booking_and_approving_a_receipt_move_no_money_at_all():
    """The balance stays 0 through PENDING and APPROVED and only jumps on settlement.

    PRD: "Movements in `PENDING`, `APPROVED` or `HELD` are invisible to the
    balance: booking, approving and holding a movement never move money."

    Design: Corner/calculations/fiduciary_projection_reads_only_settled_and_reversed_rows
    """
    ctx = _bound_program_with_agreed_wording()
    program_id = ctx["program"]["id"]
    assert_status(ctx["program"], "documentation_status", "WORDING_AGREED")
    assert_money_equals(
        ctx["program"]["fiduciary_holding_minor"], 0, "fiduciary_holding_minor at bind"
    )

    receipt = book_transaction(program_id, "CEDENT_RECEIPT", BOUND_GWP_MINOR)
    assert_status(receipt, "status", "PENDING")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor with the receipt booked",
    )

    approved = approve_transaction(receipt["id"])
    assert_status(approved, "status", "APPROVED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor with the receipt approved",
    )

    settled = settle_transaction(receipt["id"])
    assert_status(settled, "status", "SETTLED")
    assert_instant_equals(settled["value_date"], CLOCK["PLACEMENT_START"], "value_date")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        BOUND_GWP_MINOR,
        "fiduciary_holding_minor once the receipt settles",
    )


def test_the_projection_sums_settled_inflows_less_settled_outflows():
    """One settled receipt and one settled remittance leave exactly the brokerage behind.

    PRD: "It considers the program's movements whose status is `SETTLED` **or**
    `REVERSED`, and is the sum of `amount_minor` over the inflow types in that
    set less the sum of `amount_minor` over the outflow types in that set."

    Design: Corner/calculations/fiduciary_projection_reads_only_settled_and_reversed_rows
    """
    ctx = _bound_program_with_agreed_wording()
    program_id = ctx["program"]["id"]
    assert_money_equals(
        ctx["program"]["gross_written_premium_minor"], BOUND_GWP_MINOR, "gross_written_premium_minor"
    )
    assert_money_equals(
        ctx["program"]["brokerage_earned_minor"], BROKERAGE_EARNED_MINOR, "brokerage_earned_minor"
    )
    assert_money_equals(
        ctx["program"]["net_remittance_minor"], NET_REMITTANCE_MINOR, "net_remittance_minor"
    )
    assert_money_equals(
        ctx["program"]["rounding_residue_minor"], 0, "rounding_residue_minor"
    )

    _receipt, pending_receipt, remittance = _walk_the_ledger(ctx)

    assert_status(read_transaction(pending_receipt["id"]), "status", "PENDING")
    assert_status(remittance, "status", "APPROVED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        BOUND_GWP_MINOR,
        "neither the PENDING receipt nor the APPROVED remittance shifts the balance",
    )

    settled_remittance = settle_transaction(remittance["id"])
    assert_status(settled_remittance, "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        BROKERAGE_EARNED_MINOR,
        "fiduciary_holding_minor after the remittance settles",
    )


def test_the_cedent_aggregate_counts_the_settled_receipt_and_ignores_the_pending_one():
    """97,125,000 received and 20,000,000 still pending, so the cedent shows 97,125,000.

    PRD: "`settled_receipts_minor` is the sum of `amount_minor` over the cedent's
    movements whose `txn_type` is `CEDENT_RECEIPT` and whose status is `SETTLED`
    — money genuinely received."

    Design: Corner/calculations/fiduciary_projection_reads_only_settled_and_reversed_rows
    """
    ctx = _bound_program_with_agreed_wording()
    program_id = ctx["program"]["id"]

    _receipt, _pending_receipt, remittance = _walk_the_ledger(ctx)
    settle_transaction(remittance["id"])

    cedent = read_cedent(ctx["cedent"]["id"])
    assert_money_equals(
        cedent["settled_receipts_minor"], BOUND_GWP_MINOR, "settled_receipts_minor"
    )
    assert_money_equals(
        cedent["outstanding_reinstatement_premium_minor"],
        0,
        "outstanding_reinstatement_premium_minor",
    )

    rows, _meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(program_id, ACCOUNTANT)
    )
    assert len(rows) == 3, (
        f"binding creates no movement of its own, so exactly three rows exist, got {len(rows)}"
    )
    assert sorted(row["status"] for row in rows) == ["PENDING", "SETTLED", "SETTLED"], (
        f"one receipt is still pending and two rows have settled, got "
        f"{sorted(row['status'] for row in rows)}"
    )
