"""Salary-floor composition and the pinned encumbrance rounding order.

The floor is assembled from four independent inputs and the encumbrance from a
five-step order in which each intermediate rounding is part of the contract.
"""

from test_helpers import (
    api_client,
    assert_award_ledger,
    assert_money,
    draft_appointment,
    register_faculty_mentor,
    register_funding_source,
    register_postdoc,
    validate_success,
)


# ─── Shared setup: three drafts varying one floor input each ───────────────

def _three_floor_drafts(officer_headers):
    """One mentor, an NIH-scale grant and an NIH-scale external fellowship, and
    three scholars whose prior rank months and classifications differ."""
    mentor = register_faculty_mentor(
        officer_headers,
        full_name="S. Adeyemi",
        department="Biochemistry",
        mentor_training_valid_through="2029-01-31",
        max_concurrent_postdocs=3,
    )
    grant = register_funding_source(
        verify=False,
        headers=officer_headers,
        sponsor_name="NIH R01 CA-901",
        funding_type="FEDERAL_GRANT",
        salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01",
        award_end_date="2027-12-31",
        annual_budget_usd=400000.00,
        requires_mentoring_plan=False,
        requires_idp=False,
    )
    fellowship = register_funding_source(
        verify=False,
        headers=officer_headers,
        sponsor_name="Damon Runyon Fellowship",
        funding_type="EXTERNAL_FELLOWSHIP",
        salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01",
        award_end_date="2027-12-31",
        annual_budget_usd=400000.00,
        requires_mentoring_plan=False,
        requires_idp=False,
    )
    band_0 = register_postdoc(
        officer_headers,
        full_name="Nia Boateng",
        citizenship_country="US",
        requires_sponsorship=False,
        phd_award_date="2026-06-01",
        prior_external_months_in_rank=0,
    )
    band_4 = register_postdoc(
        officer_headers,
        full_name="Tomas Silva",
        citizenship_country="US",
        requires_sponsorship=False,
        phd_award_date="2022-06-01",
        prior_external_months_in_rank=48,
    )
    fellow = register_postdoc(
        officer_headers,
        full_name="Ines Marchetti",
        citizenship_country="US",
        requires_sponsorship=False,
        phd_award_date="2026-06-15",
        prior_external_months_in_rank=0,
    )

    uplifted = draft_appointment(
        band_0["id"], mentor["id"], grant["id"], officer_headers,
        title_classification="POSTDOC_SCHOLAR_EMPLOYEE",
        employment_class="EMPLOYEE",
        term_start_date="2026-10-01",
        term_end_date="2027-09-30",
        annual_salary_usd=68000.00,
    )
    top_band = draft_appointment(
        band_4["id"], mentor["id"], grant["id"], officer_headers,
        title_classification="POSTDOC_ASSOCIATE",
        employment_class="EMPLOYEE",
        term_start_date="2026-10-01",
        term_end_date="2027-09-30",
        annual_salary_usd=70000.00,
    )
    discounted = draft_appointment(
        fellow["id"], mentor["id"], fellowship["id"], officer_headers,
        title_classification="POSTDOC_FELLOW",
        employment_class="FELLOWSHIP",
        term_start_date="2026-10-01",
        term_end_date="2027-09-30",
        annual_salary_usd=60000.00,
    )
    return uplifted, top_band, discounted


def test_salary_floor_composes_band_policy_class_and_title(officer_headers):
    """Three drafts on identical terms yield three different floors.

    PRD 3.3: "First the appointment's experience band is fixed: divide
    `months_in_rank_at_start` by twelve and discard any remainder, then take
    whichever is smaller, that quotient or four." "Under `NIH_SCALE` the five
    bands read 61008, 61428, 62124, 64536 and 67284 US dollars in band order."
    "it is multiplied by 1.00 when `employment_class` is `EMPLOYEE` and by 0.95
    when it is `FELLOWSHIP`, and a title uplift of 3000 US dollars is then added
    when and only when `title_classification` is `POSTDOC_SCHOLAR_EMPLOYEE`, and
    nothing is added for the other two titles."

    Design: Difficulty/combinatorial_formula/salary_floor_band_policy_class_and_title_composition
    """
    uplifted, top_band, discounted = _three_floor_drafts(officer_headers)

    assert_money(uplifted["salary_floor_usd"], 64008.00, "band 0 employee floor")
    assert_money(top_band["salary_floor_usd"], 67284.00, "band 4 associate floor")
    assert_money(discounted["salary_floor_usd"], 57957.60, "fellowship floor")


def test_rank_ledger_quantities_accompany_the_three_floors(officer_headers):
    """The rank quantities the floor is derived from are whole integers.

    PRD 3.2: "`months_in_rank_at_start` is then the scholar's
    `prior_external_months_in_rank` plus that sum, and
    `cumulative_months_in_rank_at_end` is `months_in_rank_at_start` plus this
    appointment's own `term_months`." The month count itself is pinned:
    "multiply the end date's year by twelve and add its month number; do the
    same for the start date; subtract the start figure from the end figure; then
    add one further month when the end date's day-of-month is greater than or
    equal to the start date's day-of-month, and add nothing otherwise."

    Design: Difficulty/combinatorial_formula/salary_floor_band_policy_class_and_title_composition
    """
    uplifted, top_band, discounted = _three_floor_drafts(officer_headers)

    for label, appointment in (("uplifted", uplifted), ("top band", top_band),
                               ("discounted", discounted)):
        assert appointment["term_months"] == 12, (
            f"Expected term_months 12 on the {label} draft, "
            f"got {appointment['term_months']}"
        )

    assert uplifted["months_in_rank_at_start"] == 0
    assert uplifted["cumulative_months_in_rank_at_end"] == 12
    assert top_band["months_in_rank_at_start"] == 48
    assert top_band["cumulative_months_in_rank_at_end"] == 60
    assert discounted["months_in_rank_at_start"] == 0
    assert discounted["cumulative_months_in_rank_at_end"] == 12


def test_benefits_package_follows_class_and_award_family(officer_headers):
    """The same three drafts carry two different benefit packages.

    PRD 3.3: "An `EMPLOYEE` appointment whose `term_months` is 12 or more is
    `EMPLOYEE_FULL`; an `EMPLOYEE` appointment whose `term_months` is fewer than
    12 is `EMPLOYEE_LIMITED`. A `FELLOWSHIP` appointment on an award whose
    `funding_type` is `EXTERNAL_FELLOWSHIP` is `FELLOWSHIP_STIPEND_ONLY`"

    Design: Difficulty/combinatorial_formula/salary_floor_band_policy_class_and_title_composition
    """
    uplifted, top_band, discounted = _three_floor_drafts(officer_headers)

    assert uplifted["benefits_package"] == "EMPLOYEE_FULL"
    assert top_band["benefits_package"] == "EMPLOYEE_FULL"
    assert discounted["benefits_package"] == "FELLOWSHIP_STIPEND_ONLY"


# ─── Shared setup: two identical drafts on awards of different length ──────

def _two_encumbrance_drafts(officer_headers, hr_approver_headers):
    """Two VERIFIED NIH-scale grants of different length carrying one identical
    twelve-month appointment each, both still DRAFT."""
    mentor = register_faculty_mentor(
        officer_headers,
        full_name="K. Villanueva",
        department="Neuroscience",
        mentor_training_valid_through="2029-03-31",
        max_concurrent_postdocs=3,
    )
    full_year_award = register_funding_source(
        verify=True,
        headers=officer_headers,
        approver_headers=hr_approver_headers,
        sponsor_name="NIH R01 NS-114 (full year)",
        funding_type="FEDERAL_GRANT",
        salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01",
        award_end_date="2027-12-31",
        annual_budget_usd=400000.00,
        requires_mentoring_plan=False,
        requires_idp=False,
    )
    short_award = register_funding_source(
        verify=True,
        headers=officer_headers,
        approver_headers=hr_approver_headers,
        sponsor_name="NIH R21 NS-115 (short award)",
        funding_type="FEDERAL_GRANT",
        salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01",
        award_end_date="2027-06-30",
        annual_budget_usd=400000.00,
        requires_mentoring_plan=False,
        requires_idp=False,
    )
    scholar_a = register_postdoc(
        officer_headers, full_name="Omar Haddad", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-01",
        prior_external_months_in_rank=0,
    )
    scholar_b = register_postdoc(
        officer_headers, full_name="Grace Lindqvist", citizenship_country="US",
        requires_sponsorship=False, phd_award_date="2026-05-02",
        prior_external_months_in_rank=0,
    )
    term = {
        "title_classification": "POSTDOC_SCHOLAR_EMPLOYEE",
        "employment_class": "EMPLOYEE",
        "term_start_date": "2026-10-01",
        "term_end_date": "2027-09-30",
        "annual_salary_usd": 68000.00,
    }
    full_year_draft = draft_appointment(
        scholar_a["id"], mentor["id"], full_year_award["id"], officer_headers, **term
    )
    short_draft = draft_appointment(
        scholar_b["id"], mentor["id"], short_award["id"], officer_headers, **term
    )
    return full_year_award, short_award, full_year_draft, short_draft


def test_encumbrance_rounds_the_fringe_before_adding_it_to_the_rounded_base(
    officer_headers, hr_approver_headers
):
    """A partial-year overlap exposes both the rounding order and the band key.

    PRD 3.3: "Step three rounds the fringe amount before it is added to
    anything: multiply the already-rounded base by `fringe_rate` and round the
    product half up to two decimal places. Step four adds the already-rounded
    base to the already-rounded fringe amount and rounds the sum half up to two
    decimal places, giving the appointment's `encumbrance_usd`." "Otherwise the
    rate is banded on the prorated base from step one: 0.28 while the base is
    below 40000.00 US dollars, 0.31 while the base is below 65000.00, and 0.335
    at 65000.00 or above."

    Design: Difficulty/combinatorial_formula/encumbrance_pinned_rounding_order_and_base_keyed_fringe_tier
    """
    _award, _short_award, _full, short_draft = _two_encumbrance_drafts(
        officer_headers, hr_approver_headers
    )

    issued = validate_success(
        api_client.issue_offer(short_draft["id"], officer_headers)
    )

    assert issued["fringe_rate"] == 0.31, (
        f"The band is keyed on the prorated base, so 50860.27 selects 0.31, "
        f"got {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 66626.95, "encumbrance_usd")
    assert issued["encumbrance_usd"] != 66626.96, (
        "Rounding once at the end instead of rounding the fringe first yields "
        "66626.96, which is a different calculation"
    )
    assert issued["encumbrance_usd"] != 67898.46, (
        "Keying the fringe band on the step-four total instead of the prorated "
        "base yields 67898.46"
    )
    assert issued["appointment_status"] == "OFFER_ISSUED"


def test_full_year_overlap_takes_the_top_fringe_band(
    officer_headers, hr_approver_headers
):
    """A full-year overlap prorates the whole salary and reaches the 0.335 band.

    PRD 3.3: "the prorated base is `annual_salary_usd` multiplied by that
    inclusive day count, divided by 365, and rounded half up to two decimal
    places." "Otherwise the rate is banded on the prorated base from step one:
    0.28 while the base is below 40000.00 US dollars, 0.31 while the base is
    below 65000.00, and 0.335 at 65000.00 or above."

    Design: Difficulty/combinatorial_formula/encumbrance_pinned_rounding_order_and_base_keyed_fringe_tier
    """
    _award, _short_award, full_draft, _short = _two_encumbrance_drafts(
        officer_headers, hr_approver_headers
    )

    issued = validate_success(
        api_client.issue_offer(full_draft["id"], officer_headers)
    )

    assert issued["fringe_rate"] == 0.335, (
        f"A prorated base of 68000.00 sits at or above 65000.00, "
        f"got fringe_rate {issued['fringe_rate']}"
    )
    assert_money(issued["encumbrance_usd"], 90780.00, "encumbrance_usd")


def test_each_offer_rolls_its_own_figure_onto_its_award(
    officer_headers, hr_approver_headers
):
    """The award ledger carries exactly the appointment's own encumbrance.

    PRD 3.3: "The award's `encumbered_usd` is the sum of `encumbrance_usd` over
    the appointments charged to that award whose `appointment_status` is
    `OFFER_ISSUED`, `OFFER_ACCEPTED`, `ACTIVE` or `NON_RENEWED`, rounded half up
    to two decimal places" and "The award's `available_balance_usd` is then
    `annual_budget_usd` less `encumbered_usd`, rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/encumbrance_pinned_rounding_order_and_base_keyed_fringe_tier
    """
    full_award, short_award, full_draft, short_draft = _two_encumbrance_drafts(
        officer_headers, hr_approver_headers
    )

    validate_success(api_client.issue_offer(full_draft["id"], officer_headers))
    validate_success(api_client.issue_offer(short_draft["id"], officer_headers))

    full_after = validate_success(
        api_client.get_funding_source(full_award["id"], officer_headers)
    )
    short_after = validate_success(
        api_client.get_funding_source(short_award["id"], officer_headers)
    )

    assert_award_ledger(full_after, 90780.00, 309220.00)
    assert_award_ledger(short_after, 66626.95, 333373.05)
