"""The two filing bases of an expenditure report, and the two dues-deductibility
notice variants, computed over one and the same body of lobbying spend."""
from test_helpers import (
    api_client,
    assert_deductibility_notice,
    assert_expenditure_report,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    COMPLIANCE_2,
    certify_report,
    enroll_member,
    open_report,
    read_notice,
    read_registration,
    read_report,
    set_clock,
    setup_open_report_with_activities,
    setup_registration_with_activities,
)

# 2026-07-05: 3.333 h of staff time and 400,000 cents out of pocket.
# 2026-07-06: 2.667 h of staff time and 300,000 cents out of pocket.
ACTIVITY_A = {"activity_date": "2026-07-05", "hours": 3.333, "expenditure_cents": 400_000}
ACTIVITY_B = {"activity_date": "2026-07-06", "hours": 2.667, "expenditure_cents": 300_000}

METHOD_A_TOTAL = 700_000
METHOD_B_TOTAL = 751_001


def test_method_a_report_files_the_tax_code_total_while_storing_both_bases():
    """Both totals are stored on every report and only the selected one is filed.

    PRD 3.6: "Two totals are then computed side by side, and both are stored on
    every report regardless of which one is filed".
    PRD 3.6: "`method_a_total_cents` — the **tax-code basis**. It is the sum of
    `expenditure_cents` over the included activities, and nothing else; in-house staff time
    is excluded entirely."
    PRD 3.6: "`filed_total_cents` is then whichever of the two the `basis`
    selects — `method_a_total_cents` when `basis` is `METHOD_A`,
    `method_b_total_cents` when it is `METHOD_B`."

    Design: Difficulty/dual_variant_calc/expenditure_report_method_a_vs_method_b_divergence
    """
    state = setup_open_report_with_activities([ACTIVITY_A, ACTIVITY_B], basis="METHOD_A")
    report = state["report"]

    assert_expenditure_report(report)
    assert report["basis"] == "METHOD_A"
    assert report["status"] == "OPEN"
    assert report["included_activity_count"] == 2
    assert report["method_a_total_cents"] == METHOD_A_TOTAL
    assert report["method_b_total_cents"] == METHOD_B_TOTAL
    assert report["filed_total_cents"] == METHOD_A_TOTAL
    assert report["period_start_date"] == "2026-07-01"
    assert report["period_end_date"] == "2026-09-30"
    assert report["due_date"] == "2026-10-20"


def test_method_b_report_files_the_statutory_total_rounded_once_per_activity():
    """The statutory basis adds each activity's own rounded staff cost.

    PRD 3.6: "For each included activity, take its `expenditure_cents` and add
    that activity's own staff cost, which is its `hours` multiplied by 8500 cents
    and rounded half up to whole cents; then sum those per-activity amounts."
    PRD 3.6: "On any non-empty set of activities with non-zero hours, this basis
    yields a strictly larger total than the tax-code basis."

    Design: Difficulty/dual_variant_calc/expenditure_report_method_a_vs_method_b_divergence
    """
    state = setup_open_report_with_activities([ACTIVITY_A, ACTIVITY_B], basis="METHOD_B")
    report = state["report"]

    assert report["basis"] == "METHOD_B"
    assert report["method_a_total_cents"] == METHOD_A_TOTAL
    assert report["method_b_total_cents"] == METHOD_B_TOTAL
    assert report["filed_total_cents"] == METHOD_B_TOTAL
    # 3.333 h -> 28,331 cents and 2.667 h -> 22,670 cents, each rounded alone.
    assert report["method_b_total_cents"] - report["method_a_total_cents"] == 51_001
    assert report["method_b_total_cents"] > report["method_a_total_cents"]


def test_reopening_the_same_period_on_the_other_basis_supersedes_the_first_report():
    """A second report for the same period label discards the first.

    PRD 3.6: "any earlier report for the same registration and the same `period_code` that
    is still `OPEN` moves `OPEN → SUPERSEDED`, and its totals are frozen at their present
    values and never recomputed again".
    PRD 2.9: "a new report for a registration and period label that already has
    an open report **supersedes** that open report."

    Design: Difficulty/dual_variant_calc/expenditure_report_method_a_vs_method_b_divergence
    """
    state = setup_registration_with_activities([ACTIVITY_A, ACTIVITY_B])
    registration_id = state["registration"]["id"]

    first = open_report(registration_id, period_code="2026Q3", basis="METHOD_A")
    assert first["filed_total_cents"] == METHOD_A_TOTAL

    second = open_report(registration_id, period_code="2026Q3", basis="METHOD_B")
    assert second["basis"] == "METHOD_B"
    assert second["status"] == "OPEN"
    assert second["filed_total_cents"] == METHOD_B_TOTAL
    assert second["included_activity_count"] == 2

    superseded = read_report(registration_id, first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["filed_total_cents"] == METHOD_A_TOTAL
    assert superseded["method_b_total_cents"] == METHOD_B_TOTAL



# One quarter of lobbying spend large enough to be visible in the notice:
# 24,000,000 cents is 20.00 percent of the 120,000,000 cent annual budget.
BIG_SPEND = {"activity_date": "2026-07-15", "hours": 0, "expenditure_cents": 24_000_000}


def _association_with_certified_quarter():
    """Certify one 2026Q3 report carrying 24,000,000 cents of filed spend."""
    state = setup_registration_with_activities([BIG_SPEND])
    registration_id = state["registration"]["id"]

    # The spend landed past the federal threshold, so the registration is
    # amendment-pending; certifying the amendment returns it to ACTIVE.
    assert read_registration(registration_id)["status"] == "AMENDMENT_PENDING"
    validate_success(api_client.certify_registration_amendment(registration_id, COMPLIANCE))

    report = open_report(registration_id, period_code="2026Q3", basis="METHOD_A")
    assert report["filed_total_cents"] == 24_000_000
    set_clock("2026-10-01T00:00:00Z")
    report = certify_report(report["id"], COMPLIANCE_2)
    assert report["status"] == "CERTIFIED"
    assert report["late"] is False
    return {**state, "report": report}


def test_ratio_notice_charges_the_spend_share_against_the_whole_dues_amount():
    """A federally headquartered member is measured on the RATIO variant.

    PRD 3.6: "`ratio_pct` is one hundred times `lobbying_spend_cents` divided by
    the association's annual budget of 120,000,000 cents — 1.2 million dollars —
    rounded half up to two decimals, and then capped so that it never exceeds
    100.00."
    PRD 3.6: "`nondeductible_pct` is `ratio_pct` unchanged, with no floor.
    `nondeductible_amount_cents` is the member's `annual_dues_cents` multiplied
    by `nondeductible_pct`, divided by one hundred, rounded half up to whole
    cents. The full dues amount is the base; there is no exempt portion."

    Design: Difficulty/dual_variant_calc/dues_deductibility_ratio_vs_flat_floor_divergence
    """
    _association_with_certified_quarter()
    member = enroll_member(
        legal_name="Ratio Method Holdings Inc",
        home_jurisdiction_code="FEDERAL",
        annual_dues_cents=400_000,
        dues_year=2026,
    )
    assert member["notice_method"] == "RATIO"

    notice = read_notice(member["id"])
    assert_deductibility_notice(notice)
    assert notice["member_id"] == member["id"]
    assert notice["dues_year"] == 2026
    assert notice["notice_method"] == "RATIO"
    assert notice["lobbying_spend_cents"] == 24_000_000
    assert notice["ratio_pct"] == 20.00
    assert notice["nondeductible_pct"] == 20.00
    assert notice["nondeductible_amount_cents"] == 80_000
    assert notice["deductible_amount_cents"] == 320_000


def test_flat_floor_notice_lifts_the_share_to_the_floor_and_shrinks_the_base():
    """A Californian member is measured on the FLAT_FLOOR variant instead.

    PRD 3.6: "`nondeductible_pct` is the greater of `ratio_pct` and 25.00, so a
    low-spend year still yields a 25 percent notice. The base is not the full
    dues: it is the member's `annual_dues_cents` less an exempt base of 25,000
    cents, floored at 0 so that a small-dues member never produces a negative
    base."
    PRD 3.1: "Its `home_jurisdiction_code` is one of `FEDERAL`, `STATE_CA` or
    `STATE_NY` and decides which dues-deductibility method the company's annual
    notice will use".

    Design: Difficulty/dual_variant_calc/dues_deductibility_ratio_vs_flat_floor_divergence
    """
    _association_with_certified_quarter()
    member = enroll_member(
        legal_name="Flat Floor Fabrication LLC",
        home_jurisdiction_code="STATE_CA",
        home_district_code="CA-30",
        annual_dues_cents=400_000,
        dues_year=2026,
    )
    assert member["notice_method"] == "FLAT_FLOOR"

    notice = read_notice(member["id"])
    assert_deductibility_notice(notice)
    assert notice["notice_method"] == "FLAT_FLOOR"
    assert notice["lobbying_spend_cents"] == 24_000_000
    assert notice["ratio_pct"] == 20.00
    # 20.00 is below the floor, so the floor governs, on a base of 375,000.
    assert notice["nondeductible_pct"] == 25.00
    assert notice["nondeductible_amount_cents"] == 93_750
    assert notice["deductible_amount_cents"] == 306_250


def test_identical_dues_diverge_on_the_notice_method_alone():
    """Two members with identical dues receive different notices.

    PRD 3.6: "Two members with identical dues and identical years will therefore
    receive different notices when they are headquartered in different
    jurisdictions, which is exactly the outcome the tax rules intend."
    PRD 3.6: "In both variants `deductible_amount_cents` is the member's
    `annual_dues_cents` minus `nondeductible_amount_cents`."

    Design: Difficulty/dual_variant_calc/dues_deductibility_ratio_vs_flat_floor_divergence
    """
    _association_with_certified_quarter()
    federal = enroll_member(
        legal_name="Ratio Method Holdings Inc",
        home_jurisdiction_code="FEDERAL",
        annual_dues_cents=400_000,
        dues_year=2026,
    )
    californian = enroll_member(
        legal_name="Flat Floor Fabrication LLC",
        home_jurisdiction_code="STATE_CA",
        home_district_code="CA-30",
        annual_dues_cents=400_000,
        dues_year=2026,
    )

    federal_notice = read_notice(federal["id"])
    californian_notice = read_notice(californian["id"])

    assert federal_notice["lobbying_spend_cents"] == californian_notice["lobbying_spend_cents"]
    assert federal_notice["ratio_pct"] == californian_notice["ratio_pct"] == 20.00
    assert federal_notice["nondeductible_amount_cents"] == 80_000
    assert californian_notice["nondeductible_amount_cents"] == 93_750
    assert federal_notice["deductible_amount_cents"] == 320_000
    assert californian_notice["deductible_amount_cents"] == 306_250
    assert (federal_notice["nondeductible_amount_cents"]
            != californian_notice["nondeductible_amount_cents"])
