"""Dual-variant calculations and combinatorial formulas.

Every test in this module translates exactly one instance of the §1.8 depth
index: the two `dual_variant_calc` instances and the three
`combinatorial_formula` instances.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.constants import (
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_MFA_REVIEW,
    CONSEQUENCE_WARNING,
    DELIVERY_CLICKED,
    DELIVERY_NO_INTERACTION,
    OUTCOME_CLICKED_NO_REPORT,
    OUTCOME_NO_INTERACTION,
    POSTURE_ELEVATED_REVIEW,
    POSTURE_WARNED,
    REPORT_VARIANT_CONCURRENT,
    REPORT_VARIANT_LAGGED,
    TENURE_NEW_HIRE,
    TENURE_VETERAN,
    TIER_1,
    TIER_2,
    TIER_3,
)
from test_helpers.factories import consequence_payload, effectiveness_params
from test_helpers.fixtures import (
    approved_template,
    click,
    close_campaign,
    delivery_for,
    read_delivery,
    read_employee,
    register_employee,
    report,
    reset_clock,
    running_campaign,
    set_clock,
)
from test_helpers.assertions import (
    assert_delivery,
    assert_rate,
    assert_risk_scores,
    assert_score,
)
from test_helpers.test_users import ADMIN, ANALYST


# --------------------------------------------------------------------------- #
# dual_variant_calc                                                           #
# --------------------------------------------------------------------------- #


def _one_closed_clean_and_one_running_click(api) -> dict:
    """A VETERAN with an ignored delivery in a CLOSED wave and a click in a RUNNING one."""
    reset_clock(api)
    employee = register_employee(
        api,
        full_name="Vera Teran",
        department="ENGINEERING",
        role_code="ENGINEER",
        hire_date="2018-01-01",
    )
    template = approved_template(
        api,
        name="Package Delivery Notice",
        pretext_category="PACKAGE_DELIVERY",
        difficulty_tier=TIER_1,
        theme_tags=["URGENCY"],
        credential_capture_enabled=False,
    )
    wave_one = running_campaign(
        api,
        scheduled_send_at="2026-08-02T09:00:00Z",
        template=template,
        name="Aug Wave 1 ENG",
        difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    closed_delivery = delivery_for(api, wave_one["campaign"]["id"], employee["id"])
    set_clock(api, "2026-08-02T12:00:00Z")
    close_campaign(
        api,
        wave_one["campaign"]["id"],
        debrief_note="Wave 1 baseline: no interaction observed.",
    )
    wave_two = running_campaign(
        api,
        scheduled_send_at="2026-08-08T09:00:00Z",
        template=template,
        name="Aug Wave 2 ENG",
        difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    running_delivery = delivery_for(api, wave_two["campaign"]["id"], employee["id"])
    click(api, running_delivery["id"], "2026-08-08T10:00:00Z")
    return {
        "employee": employee,
        "closed_delivery": closed_delivery,
        "running_delivery": running_delivery,
        "closed_campaign": wave_one["campaign"],
        "running_campaign": wave_two["campaign"],
    }


def test_risk_score_variants_diverge_in_one_employee_response(api):
    """The two variants read 11.00 and 0.00 out of the same stored rows.

    PRD §3.10: "Identical stored data therefore yields two different numbers: an
    employee who ignored one closed campaign and clicked in a still-running one
    scores 11.00 provisional against 0.00 settled."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_settled_diverge_on_one_employee
    """
    ctx = _one_closed_clean_and_one_running_click(api)

    employee = validate_success(api.get_employee(ctx["employee"]["id"], ADMIN))

    assert employee["tenure_band"] == TENURE_VETERAN
    assert employee["repeat_clicker_tier"] == 1
    assert_risk_scores(employee, provisional=11.00, settled=0.00)
    assert (
        round(float(employee["risk_score_provisional"])
              - float(employee["risk_score_settled"]), 2) == 11.00
    ), "the two variant fields must differ by exactly 11.00 in one and the same response"


def test_settled_variant_ignores_the_running_campaign_delivery(api):
    """Only CLOSED-campaign deliveries are in scope for the settled variant.

    PRD §3.10: "For `risk_score_settled`, the audit view that feeds the
    effectiveness report, in-scope deliveries are only those whose campaign is in
    state `CLOSED`, and the count of settled clean deliveries is the number of
    those in-scope deliveries whose state is `NO_INTERACTION`, each earning its 2
    points."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_settled_diverge_on_one_employee
    """
    ctx = _one_closed_clean_and_one_running_click(api)

    closed = read_delivery(api, ctx["closed_delivery"]["id"])
    running = read_delivery(api, ctx["running_delivery"]["id"])
    employee = read_employee(api, ctx["employee"]["id"])

    assert_delivery(closed, state=DELIVERY_NO_INTERACTION,
                    outcome_class=OUTCOME_NO_INTERACTION)
    assert_delivery(running, state=DELIVERY_CLICKED,
                    outcome_class=OUTCOME_CLICKED_NO_REPORT)
    assert employee["consecutive_clean_simulations"] == 0, (
        "the click resets the clean streak the close had incremented"
    )
    assert_score(employee["risk_score_settled"], 0.00, "risk_score_settled")
    assert_score(employee["risk_score_provisional"], 11.00, "risk_score_provisional")


def _three_closed_monthly_waves(api) -> dict:
    """Three monthly closed campaigns over a two-person cohort plus real incidents."""
    set_clock(api, "2026-03-01T00:00:00Z")
    first = register_employee(
        api, full_name="Ana Ruiz", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2018-01-01",
    )
    second = register_employee(
        api, full_name="Ben Cole", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2018-02-01",
    )
    template = approved_template(
        api, name="Shared Document Invite", pretext_category="SHARED_DOCUMENT",
        difficulty_tier=TIER_1, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )

    march = running_campaign(
        api, scheduled_send_at="2026-03-10T09:00:00Z", template=template,
        name="March Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    report(api, delivery_for(api, march["campaign"]["id"], first["id"])["id"],
           "2026-03-10T10:00:00Z")
    set_clock(api, "2026-03-15T00:00:00Z")
    close_campaign(api, march["campaign"]["id"], debrief_note="March wave debrief.")
    validate_success(
        api.create_incident(
            {"incident_type": "CREDENTIAL_PHISH", "severity": "HIGH",
             "department": "ENGINEERING", "occurred_at": "2026-03-05T08:00:00Z",
             "summary": "Real credential phish, engineering."}, ANALYST),
        expected_status=201,
    )
    validate_success(
        api.create_incident(
            {"incident_type": "BEC", "severity": "MEDIUM",
             "department": "ENGINEERING", "occurred_at": "2026-03-20T08:00:00Z",
             "summary": "Real BEC attempt, engineering."}, ANALYST),
        expected_status=201,
    )

    april = running_campaign(
        api, scheduled_send_at="2026-04-10T09:00:00Z", template=template,
        name="April Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    report(api, delivery_for(api, april["campaign"]["id"], first["id"])["id"],
           "2026-04-10T10:00:00Z")
    report(api, delivery_for(api, april["campaign"]["id"], second["id"])["id"],
           "2026-04-10T10:00:00Z")
    set_clock(api, "2026-04-15T00:00:00Z")
    close_campaign(api, april["campaign"]["id"], debrief_note="April wave debrief.")
    validate_success(
        api.create_incident(
            {"incident_type": "CREDENTIAL_PHISH", "severity": "HIGH",
             "department": "ENGINEERING", "occurred_at": "2026-04-18T08:00:00Z",
             "summary": "Real credential phish, april."}, ANALYST),
        expected_status=201,
    )

    may = running_campaign(
        api, scheduled_send_at="2026-05-12T09:00:00Z", template=template,
        name="May Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    set_clock(api, "2026-05-20T00:00:00Z")
    close_campaign(api, may["campaign"]["id"],
                   debrief_note="May wave debrief: silence everywhere.")
    return {"employees": [first, second]}


def test_effectiveness_concurrent_variant_pairs_each_bucket_with_itself(api):
    """CONCURRENT keeps all three buckets and correlates 0.5000.

    PRD §3.10: "Under `CONCURRENT`, each bucket's report rate is paired with that
    same bucket's own incident count, so every bucket in the period can
    contribute a pair."

    Design: Difficulty/dual_variant_calc/effectiveness_correlation_concurrent_vs_lagged_diverge
    """
    _three_closed_monthly_waves(api)

    data = validate_success(
        api.get_effectiveness_report(
            effectiveness_params("2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z",
                                 variant=REPORT_VARIANT_CONCURRENT),
            ANALYST,
        )
    )

    assert data["variant"] == REPORT_VARIANT_CONCURRENT
    assert len(data["buckets"]) == 3, "March, April and May are the three buckets"
    assert data["pair_count"] == 3
    assert_rate(data["correlation"], 0.5000, "correlation")
    assert data["correlation_reason_code"] is None
    assert data["total_incidents"] == 3
    assert_rate(data["mean_report_rate"], 0.5000, "mean_report_rate")


def test_effectiveness_lagged_variant_drops_the_final_bucket(api):
    """LAGGED pairs each rate with the next month and correlates -1.0000.

    PRD §3.10: "Under `LAGGED`, each bucket's report rate is paired with the
    *following* month's incident count — the lag is exactly 1 month — so the
    final bucket of the period contributes its report rate to nothing and is
    dropped; the pair count is consequently one lower and the correlation differs
    for identical data."

    Design: Difficulty/dual_variant_calc/effectiveness_correlation_concurrent_vs_lagged_diverge
    """
    _three_closed_monthly_waves(api)

    data = validate_success(
        api.get_effectiveness_report(
            effectiveness_params("2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z",
                                 variant=REPORT_VARIANT_LAGGED),
            ANALYST,
        )
    )

    assert data["variant"] == REPORT_VARIANT_LAGGED
    assert len(data["buckets"]) == 3, "the bucket list still spans the whole period"
    assert data["pair_count"] == 2, "the final bucket is dropped after pairing"
    assert_rate(data["correlation"], -1.0000, "correlation")
    assert data["correlation_reason_code"] is None
    assert data["total_incidents"] == 3


# --------------------------------------------------------------------------- #
# combinatorial_formula                                                       #
# --------------------------------------------------------------------------- #


def _spear_campaign_over_a_new_hire_and_a_veteran(api) -> dict:
    """A TIER_3_SPEAR campaign scheduled over one NEW_HIRE and one VETERAN."""
    reset_clock(api)
    new_hire = register_employee(
        api, full_name="Nina New", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2026-07-20",
    )
    veteran = register_employee(
        api, full_name="Val Vetera", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2018-01-01",
    )
    template = approved_template(
        api, name="Exec Urgent Wire Review", pretext_category="EXEC_URGENT_REQUEST",
        difficulty_tier=TIER_3, theme_tags=["AUTHORITY", "URGENCY"],
        credential_capture_enabled=False,
    )
    from test_helpers.fixtures import scheduled_campaign

    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-05T09:00:00Z", template=template,
        name="Spear Wave ENG", difficulty_tier=TIER_3,
        target_departments=["ENGINEERING"],
    )
    return {
        "new_hire": new_hire,
        "veteran": veteran,
        "campaign": ctx["campaign"],
        "new_hire_delivery": delivery_for(api, ctx["campaign"]["id"], new_hire["id"]),
        "veteran_delivery": delivery_for(api, ctx["campaign"]["id"], veteran["id"]),
    }


def test_new_hire_cap_lands_after_the_global_cap_in_the_tier_composition(api):
    """One TIER_3_SPEAR campaign freezes two different effective tiers.

    PRD §3.8: "The raw rank is then capped at 3. Finally, if the employee's
    `tenure_band` is `NEW_HIRE`, the rank is capped again at 2, because a
    brand-new hire is never spear-phished; for every other band the previous
    value stands."

    Design: Difficulty/combinatorial_formula/difficulty_escalation_nested_max_then_min_with_newhire_cap
    """
    ctx = _spear_campaign_over_a_new_hire_and_a_veteran(api)

    assert_delivery(ctx["veteran_delivery"], effective_difficulty_tier=TIER_3)
    assert ctx["veteran_delivery"]["base_difficulty_tier"] == TIER_3
    assert_delivery(ctx["new_hire_delivery"], effective_difficulty_tier=TIER_2)
    assert ctx["new_hire_delivery"]["base_difficulty_tier"] == TIER_3, (
        "the base tier is copied from the campaign for every cohort member alike"
    )


def test_spear_reservation_records_both_cohort_members(api):
    """The reservation counts the whole cohort and bumps each member's ledger.

    PRD §3.8: "Creating the reservation increments each targeted employee's
    `reserved_simulation_slots` by one and bumps each such `Employee.version` by
    one, sets `scheduled_send_at`, `target_count` and `evaluable_count` on the
    campaign, and bumps the campaign's `version` by one."

    Design: Difficulty/combinatorial_formula/difficulty_escalation_nested_max_then_min_with_newhire_cap
    """
    ctx = _spear_campaign_over_a_new_hire_and_a_veteran(api)

    assert ctx["campaign"]["state"] == "SCHEDULED"
    assert ctx["campaign"]["target_count"] == 2
    assert ctx["campaign"]["evaluable_count"] == 2

    new_hire = read_employee(api, ctx["new_hire"]["id"])
    veteran = read_employee(api, ctx["veteran"]["id"])
    assert new_hire["tenure_band"] == TENURE_NEW_HIRE
    assert new_hire["reserved_simulation_slots"] == 1
    assert veteran["tenure_band"] == TENURE_VETERAN
    assert veteran["reserved_simulation_slots"] == 1


def _one_click_in_three_deliveries(api) -> dict:
    """One click over a three-member, two-department cohort."""
    reset_clock(api)
    eng_one = register_employee(
        api, full_name="Sam One", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2018-01-01",
    )
    register_employee(
        api, full_name="Sue Two", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2018-01-02",
    )
    register_employee(
        api, full_name="Sid Three", department="FINANCE",
        role_code="FINANCE_APPROVER", hire_date="2018-01-03",
    )
    template = approved_template(
        api, name="IT Password Reset", pretext_category="IT_PASSWORD_RESET",
        difficulty_tier=TIER_1, theme_tags=["URGENCY"],
        credential_capture_enabled=False,
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="Company Wide Wave", difficulty_tier=TIER_1,
    )
    clicked = delivery_for(api, ctx["campaign"]["id"], eng_one["id"])
    click(api, clicked["id"], "2026-08-02T10:00:00Z")
    return {"campaign": ctx["campaign"], "clicked_delivery": clicked}


def test_program_click_rate_divides_raw_counts_once(api):
    """One click over three evaluable deliveries is 0.3333, never 0.2500.

    PRD §2.6: "Rounding happens exactly once, at the end, and the order is
    pinned: a rate is computed by dividing raw integer counts and only then
    rounded. A program-level rate is never the average of its segment rates."

    Design: Difficulty/combinatorial_formula/scorecard_rates_divide_then_round_never_average_segments
    """
    ctx = _one_click_in_three_deliveries(api)

    scorecard = validate_success(api.get_scorecard(ctx["campaign"]["id"], ANALYST))

    assert scorecard["evaluable_count"] == 3
    assert scorecard["excluded_count"] == 0
    assert_rate(scorecard["click_rate"], 0.3333, "click_rate")
    assert abs(float(scorecard["click_rate"]) - 0.2500) > 0.0001, (
        "0.2500 is the value a round-then-average implementation returns"
    )


def test_scorecard_reports_segments_alongside_the_program_figures(api):
    """The remaining program-level figures come from the same raw counts.

    PRD §3.9: "Otherwise `click_rate`, `report_rate` and `credential_rate` are
    each their numerator divided by the denominator, rounded half up to 4 decimal
    places, and `resilience_ratio` is the report numerator divided by the greater
    of 1 and the click numerator, rounded half up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/scorecard_rates_divide_then_round_never_average_segments
    """
    ctx = _one_click_in_three_deliveries(api)

    scorecard = validate_success(api.get_scorecard(ctx["campaign"]["id"], ANALYST))

    assert_rate(scorecard["report_rate"], 0.0000, "report_rate")
    assert_rate(scorecard["credential_rate"], 0.0000, "credential_rate")
    assert_rate(scorecard["resilience_ratio"], 0.0000, "resilience_ratio")
    assert scorecard["campaign_id"] == ctx["campaign"]["id"]
    assert isinstance(scorecard["segments"], list)
    assert_delivery(read_delivery(api, ctx["clicked_delivery"]["id"]),
                    outcome_class=OUTCOME_CLICKED_NO_REPORT)


def _two_derived_consequences(api) -> dict:
    """One employee receiving two derived access consequences in a row."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Cara Cons", department="SALES",
        role_code="IC", hire_date="2019-05-06",
    )
    first = validate_success(
        api.apply_access_consequence(
            employee["id"],
            consequence_payload(employee["version"], reason_code="MISSED_ANNUAL_TRAINING"),
            ADMIN,
        ),
        expected_status=201,
    )
    refreshed = read_employee(api, employee["id"])
    second = validate_success(
        api.apply_access_consequence(
            employee["id"],
            consequence_payload(refreshed["version"], reason_code="SECOND_MISSED_MODULE"),
            ADMIN,
        ),
        expected_status=201,
    )
    return {"employee": employee, "first": first, "second": second}


def test_derived_severity_climbs_one_rung_because_step_one_excludes_the_new_row(api):
    """The second derived consequence lands on rank 2, not rank 1 or rank 3.

    PRD §3.6: "Because step 1 excludes the row being created, the derived ladder
    climbs one rung per application: an employee already at `WARNED` who receives
    a second derived consequence gets `MFA_REVIEW`, a third gets
    `SYSTEM_ACCESS_SUSPENSION`, and a fourth stays at
    `SYSTEM_ACCESS_SUSPENSION` because of the cap — and that fourth row supersedes
    the third, lifting it with `SUPERSEDED`."

    Design: Difficulty/combinatorial_formula/access_consequence_severity_pinned_order_breaks_circularity
    """
    ctx = _two_derived_consequences(api)

    assert ctx["first"]["consequence_type"] == CONSEQUENCE_WARNING
    assert ctx["first"]["severity_rank"] == 1
    assert ctx["second"]["consequence_type"] == CONSEQUENCE_MFA_REVIEW
    assert ctx["second"]["severity_rank"] == 2
    assert ctx["second"]["state"] == CONSEQUENCE_ACTIVE

    active = validate_success(
        api.list_access_consequences(
            {"employee_id": ctx["employee"]["id"], "state": CONSEQUENCE_ACTIVE}, ADMIN)
    )
    rows = active["data"] if isinstance(active, dict) else active
    assert len(rows) == 2, "a different consequence_type is never superseded"


def test_posture_follows_the_recomputed_rank_after_the_second_application(api):
    """Step 4 projects the highest ACTIVE rank onto access_posture.

    PRD §3.6: "Recompute the employee's post-application rank as the highest
    `severity_rank` among that employee's `ACTIVE` rows, now including the row
    just created, and set `access_posture` from it: rank 0 gives `NONE`, rank 1
    gives `WARNED`, rank 2 gives `ELEVATED_REVIEW`, and rank 3 gives
    `SUSPENDED`."

    Design: Difficulty/combinatorial_formula/access_consequence_severity_pinned_order_breaks_circularity
    """
    ctx = _two_derived_consequences(api)

    after_first = validate_success(api.get_access_consequence(ctx["first"]["id"], ADMIN))
    assert after_first["state"] == CONSEQUENCE_ACTIVE
    assert after_first["severity_rank"] == 1

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["access_posture"] == POSTURE_ELEVATED_REVIEW
    assert employee["active_suspension_count"] == 0
    assert_risk_scores(employee, provisional=0.00, settled=0.00)
    assert POSTURE_WARNED != employee["access_posture"], (
        "one WARNING row alone would have left the posture at WARNED"
    )
