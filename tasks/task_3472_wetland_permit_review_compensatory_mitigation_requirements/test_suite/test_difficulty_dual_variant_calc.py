"""Difficulty queue — dual-variant calculations (PRD §3.5, §3.6).

Both tests pin the two variants of one calculation on identical inputs:
the provisional vs. final mitigation credit requirement, and the standard
vs. after-the-fact public interest review score.
"""
import pytest

from test_helpers import (
    PirOutcome,
    PlanStatus,
    advance_to_decision,
    assert_credit_requirement,
    close_comment_period,
    confirm_case,
    create_application,
    create_case,
    create_plan,
    iso_add_days,
    publish_notice,
    reserve_and_purchase,
    review_plan,
    secure_plan,
    set_clock,
    set_resolution_atf,
    setup_aa_accepted,
    setup_application_decision_pending,
    setup_operational_bank,
    setup_site_with_issued_jd,
    submit_plan,
    walk_application_to_alternatives_review,
)


def test_mitigation_credits_provisional_vs_final_timing_lag(api):
    """PRD §3.6: "The provisional requirement multiplies the line's
    `impact_acres` by its base ratio, then by a location multiplier and a lag
    multiplier both fixed at 1.0 at creation — no bank has been chosen and no
    lag has elapsed — and finally by the after-the-fact multiplier".
    PRD §3.6: "The lag multiplier prices delay: take the whole days elapsed
    from the application's `submitted_date` to the current clock, and apply
    1.0 when that lag is at most 365 days, 1.10 when it is between 366 and
    730 days inclusive, and 1.20 once it exceeds 730 days."
    PRD §3.6: "Identical plan data therefore yields a strictly larger final
    requirement whenever the lag has passed one year or an out-of-basin bank
    was used."

    Provisional (creation): 2.0 FORESTED_WETLAND acres * 3.0 * 1.0 * 1.0 =
    6.00 credits. Final (secure-credits 400 days after submission):
    2.0 * 3.0 * 1.0 in-basin * 1.10 lag = 6.60 credits; 7.0 purchased
    credits satisfy the final requirement.

    Design: Difficulty/dual_variant_calc/mitigation_credits_provisional_vs_final_timing_lag
    """
    ctx = setup_application_decision_pending()
    app, applicant = ctx["app"], ctx["applicant"]

    # PRD §3.5 default scenario: 2.0 FORESTED_WETLAND acres, 2 minimization
    # steps, cost 750000, no comments, no secured plan:
    # 0.40*(-10*2.0 + 5*2) + 0.35*((750000-250000)/10000) + 0.25*15 = 17.25.
    assert app["pir_score"] == pytest.approx(17.25, abs=0.005), (
        f"pir_score at advance-to-decision: expected 17.25, got {app['pir_score']}"
    )
    assert app["pir_outcome"] == PirOutcome.FAVORABLE.value

    # Provisional variant at plan creation (location/lag fixed at 1.0).
    plan = create_plan(app, applicant)
    assert_credit_requirement(plan, {"FORESTED_WETLAND": 6.00})
    assert plan["final_credits_required_by_type"] is None, (
        "final_credits_required_by_type stays null until secured (PRD §3.6)"
    )

    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()
    reserve_and_purchase(bank, plan, applicant, credits=7.0)

    # Jump the clock 400 days past submission (lag tier 366..730 -> 1.10).
    set_clock(iso_add_days(app["submitted_date"], 400))

    secured = secure_plan(plan, applicant)
    assert_credit_requirement(
        secured, {"FORESTED_WETLAND": 6.60}, field="final_credits_required_by_type"
    )
    final_fw = secured["final_credits_required_by_type"]["FORESTED_WETLAND"]
    prov_fw = plan["required_credits_by_type"]["FORESTED_WETLAND"]
    assert final_fw != prov_fw, (
        f"final {final_fw} must differ from provisional {prov_fw} for identical "
        "plan inputs once the lag tier lifts the multiplier"
    )
    assert secured["status"] == PlanStatus.CREDITS_SECURED.value, (
        f"7.0 purchased >= 6.60 final requirement; got status {secured['status']}"
    )


def test_pir_score_standard_vs_atf_deterrence(api):
    """PRD §3.5: "The environmental component starts from a per-acre harm
    term: negative 10.0 points per impacted acre of `total_impact_acres` on
    the standard variant, or — for an after-the-fact application — negative
    15.0 points per impacted acre plus a flat negative 10.0 deterrence
    adjustment, so identical application data always scores strictly lower on
    the after-the-fact variant."
    PRD §3.5: "The `pir_score` is the weighted sum — 0.40 times the
    environmental component, 0.35 times the economic component, and 0.25
    times the navigation component — rounded half-up to two decimal places."

    Identical inputs (2.0 FORESTED_WETLAND acres, 2 minimization steps, cost
    750000, no comments, no secured plan): standard 0.40*(-20+10) +
    0.35*50 + 0.25*15 = 17.25; after-the-fact 0.40*(-30+10-10) + 0.35*50 +
    0.25*15 = 9.25.

    Design: Difficulty/dual_variant_calc/pir_score_standard_vs_atf_deterrence
    """
    applicant, site, jd = setup_site_with_issued_jd()

    # --- standard variant: INDIVIDUAL pathway ---
    app_std = create_application(site, jd, applicant)
    app_std = walk_application_to_alternatives_review(app_std, applicant)
    ctx_std = {"applicant": applicant, "site": site, "jd": jd, "app": app_std}
    ctx_std = setup_aa_accepted(ctx_std)
    ctx_std["app"] = publish_notice(ctx_std["app"], 30)
    close_comment_period(ctx_std["app"])
    app_std = advance_to_decision(ctx_std["app"])
    assert app_std["pir_score"] == pytest.approx(17.25, abs=0.005), (
        f"standard variant: expected 17.25, got {app_std['pir_score']}"
    )
    assert app_std["pir_outcome"] == PirOutcome.FAVORABLE.value

    # --- after-the-fact variant: ATF_INDIVIDUAL pathway, same inputs ---
    case = create_case(site, applicant, 2.0)
    case = confirm_case(case)
    app_atf = create_application(
        site, jd, applicant, pathway="ATF_INDIVIDUAL",
        enforcement_case_id=case["id"],
    )
    case = set_resolution_atf(case, app_atf)
    app_atf = walk_application_to_alternatives_review(app_atf, applicant)
    ctx_atf = {"applicant": applicant, "site": site, "jd": jd, "app": app_atf}
    ctx_atf = setup_aa_accepted(ctx_atf)
    ctx_atf["app"] = publish_notice(ctx_atf["app"], 30)
    close_comment_period(ctx_atf["app"])
    app_atf = advance_to_decision(ctx_atf["app"])

    assert app_atf["is_after_the_fact"] is True
    assert app_atf["pir_score"] == pytest.approx(9.25, abs=0.005), (
        f"after-the-fact deterrence variant: expected 9.25, got {app_atf['pir_score']}"
    )
    assert app_atf["pir_outcome"] == PirOutcome.FAVORABLE.value
    assert app_atf["pir_score"] < app_std["pir_score"], (
        "identical application data must score strictly lower on the "
        f"after-the-fact variant: {app_atf['pir_score']} !< {app_std['pir_score']}"
    )
