"""Royalty reporting: the self-reported basis against the ledger-verified basis.

One franchisee, one club, two live memberships — one discounted to the bone and one
sold at list — and a self-report that claims three members. Every figure below was
computed from the pricing and royalty formulas the PRD pins.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    charge_and_pay,
    create_approved_promotion,
    create_corporate_account,
    create_member,
    read_franchisee,
    set_clock_date,
    setup_single_club_franchise,
    sign_agreement,
    submit_royalty_report,
)


def _report_over_two_live_memberships() -> dict:
    """Two ACTIVE agreements at one club — 3666 discounted and 4500 at list — and a
    royalty report for the closed month of August claiming three members."""
    scenario = setup_single_club_franchise(
        legal_name="Gulf Coast Fitness LLC",
        contact_email="ops@gulfcoastfit.example",
        royalty_rate_bps=650,
        club_name="Alpha Fitness Downtown",
        opened_on="2021-06-01",
    )
    franchisee = scenario["franchisee"]
    club = scenario["club"]
    plan_template = scenario["plan_template"]
    promotion = create_approved_promotion(
        franchisee["id"],
        plan_template["id"],
        code="SUMMER125",
        discount_pct=0.125,
        starts_on="2026-07-01",
        ends_on="2026-09-30",
    )
    corporate = create_corporate_account(
        name="Meridian Logistics",
        corporate_credit_pct=0.045,
        allocation_method="USAGE_SHARE",
    )
    discounted_member = create_member(
        club["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    list_price_member = create_member(
        club["id"], full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    discounted = sign_agreement(
        discounted_member["id"],
        club["id"],
        plan_template["id"],
        multi_club_access=True,
        promotion_id=promotion["id"],
        corporate_account_id=corporate["id"],
    )
    at_list = sign_agreement(
        list_price_member["id"], club["id"], plan_template["id"]
    )
    for agreement in (discounted, at_list):
        charge_and_pay(
            agreement["id"],
            agreement["effective_monthly_dues_cents"],
            occurred_on="2026-08-01",
            due_on="2026-09-05",
            paid_on="2026-08-02",
        )
    set_clock_date("2026-09-05")
    report = submit_royalty_report(franchisee["id"], "2026-08", 3)
    return {
        "franchisee": franchisee,
        "discounted_agreement": discounted,
        "list_price_agreement": at_list,
        "report": report,
    }


def test_verified_basis_is_net_of_every_credit_while_reported_basis_is_at_list_price():
    """The two bases are built from different sources: the verified one sums the pinned
    effective dues of the qualifying agreements (3666 + 4500 = 8166) while the reported
    one multiplies the claimed head count by the 4500-cent brand list price.

    PRD 3.9: "The reported basis, `reported_dues_basis_cents`, is `reported_member_count`
    multiplied by the brand list price of 4500 cents per member per month, which ignores
    every promotion, corporate credit and multi-club credit"

    Design: Difficulty/dual_variant_calc/royalty_reported_basis_vs_verified_basis_diverge_on_same_period
    """
    setup = _report_over_two_live_memberships()
    report = setup["report"]

    assert setup["discounted_agreement"]["effective_monthly_dues_cents"] == 3666
    assert setup["list_price_agreement"]["effective_monthly_dues_cents"] == 4500
    assert report["reported_member_count"] == 3
    assert report["verified_member_count"] == 2
    assert report["verified_dues_basis_cents"] == 8166
    assert report["reported_dues_basis_cents"] == 13500


def test_both_royalty_variants_are_stored_each_from_its_own_basis():
    """650 basis points on the verified 8166 gives 531 cents, while the same rate on the
    reported 13500 gives 878 — a 347-cent divergence on one period.

    PRD 3.9: "The verified basis produces `royalty_due_cents` the same way, from
    `verified_dues_basis_cents` and the same rate."

    Design: Difficulty/dual_variant_calc/royalty_reported_basis_vs_verified_basis_diverge_on_same_period
    """
    report = _report_over_two_live_memberships()["report"]

    assert report["royalty_due_cents"] == 531
    assert report["reported_royalty_cents"] == 878
    assert report["reported_royalty_cents"] - report["royalty_due_cents"] == 347


def test_overstated_head_count_auto_resolves_the_report_to_disputed():
    """One phantom member against a verified count of two is a 50.00 percent
    overstatement, ten times the tolerance, so the report resolves to DISPUTED.

    PRD 3.9: "The report is created `SUBMITTED` and immediately auto-resolves on the
    absolute value of `variance_pct` against a tolerance of 5.00 percent: a variance
    whose magnitude exceeds 5.00 resolves to `DISPUTED`, and anything at or within 5.00
    resolves to `ACCEPTED`."

    Design: Difficulty/dual_variant_calc/royalty_reported_basis_vs_verified_basis_diverge_on_same_period
    """
    report = _report_over_two_live_memberships()["report"]

    assert report["variance_pct"] == 50.00
    assert report["status"] == "DISPUTED"


def test_dispute_charges_the_ten_point_penalty_against_franchisee_standing():
    """The dispute is a compliance fact: it lifts disputed_royalty_count to 1 and takes
    ten points off the compliance score, which is still well clear of probation.

    PRD 3.9: "Resolving to `DISPUTED` increments the franchisee's
    `disputed_royalty_count` by 1, recomputes its `compliance_score` — demoting it to
    `PROBATION` if that drops it below 70 — and increments the franchisee's `version` by
    1 on that path."

    Design: Difficulty/dual_variant_calc/royalty_reported_basis_vs_verified_basis_diverge_on_same_period
    """
    setup = _report_over_two_live_memberships()

    franchisee = read_franchisee(setup["franchisee"]["id"])
    assert franchisee["disputed_royalty_count"] == 1
    assert franchisee["compliance_score"] == 90
    assert franchisee["status"] == "ACTIVE"


def test_report_is_listed_once_for_the_period_with_its_pinned_figures():
    """A submitted report is readable straight back with every stored figure, so the
    audit variant survives the round trip alongside the billable one.

    PRD 3.9: "`royalty_due_cents` is the only figure ever billed; `reported_royalty_cents`
    is stored purely for audit, and because the verified basis is net of every discount
    while the reported basis is at list price, the two disagree whenever any agreement
    carries a discount or the reported head count is wrong."

    Design: Difficulty/dual_variant_calc/royalty_reported_basis_vs_verified_basis_diverge_on_same_period
    """
    setup = _report_over_two_live_memberships()
    fetched = validate_success(
        api_client.get_royalty_report(
            setup["report"]["id"], TEST_USERS["brand_administrator_headers"]
        )
    )

    assert fetched["period_month"] == "2026-08"
    assert fetched["royalty_due_cents"] == 531
    assert fetched["reported_royalty_cents"] == 878
    assert fetched["verified_dues_basis_cents"] == 8166
    assert fetched["status"] == "DISPUTED"
