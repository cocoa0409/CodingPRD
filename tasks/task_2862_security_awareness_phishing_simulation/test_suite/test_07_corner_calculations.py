"""Derived-value arithmetic: windows, cadences, screens, thresholds and precision.

Every test in this module translates exactly one non-stub instance of the
`calculations` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_COMPLETED,
    COMPLIANCE_COMPLIANT,
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_SUSPENSION,
    DELIVERY_CLICKED,
    OUTCOME_CLICKED_NO_REPORT,
    OUTCOME_REPORTED_ONLY,
    POSTURE_NONE,
    POSTURE_SUSPENDED,
    REPORT_VARIANT_CONCURRENT,
    TEMPLATE_DRAFT,
    TENURE_EARLY,
    TENURE_ESTABLISHED,
    TENURE_NEW_HIRE,
    TIER_1,
    TIER_2,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_consequence,
    assert_delivery,
    assert_four_decimal_places,
    assert_instant_equals,
    assert_ledgers,
    assert_rate,
    assert_risk_scores,
    assert_sweep_counters,
)
from test_helpers.factories import (
    consequence_payload,
    effectiveness_params,
    template_payload,
)
from test_helpers.fixtures import (
    approved_template,
    assign_module,
    click,
    close_campaign,
    create_published_module,
    delivery_for,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    repeat_clicker_at_tier_two,
    report,
    reset_clock,
    run_sweep,
    running_campaign,
    set_clock,
)
from test_helpers.test_users import ADMIN, ANALYST, AUTHOR, make_learner_headers


def test_high_criticality_halves_the_new_hire_window_to_seven_days(api):
    """max(3, floor(14/2)) is 7, so the HIGH module is due a week earlier.

    PRD §3.2: "The base window is 14 days for a `NEW_HIRE` reason, 30 days for
    `ANNUAL`, 21 days for `ROLE_CHANGE`, and 7 days for `REMEDIAL`. If the
    referenced module's `criticality` is `HIGH`, the window becomes the greater of
    3 days and the base window halved with any fraction discarded"

    Design: Corner/calculations/assignment_due_date_high_criticality_halves_the_window
    """
    reset_clock(api)
    employee = register_employee(
        api, email="hana.high@corp.example", full_name="Hana High",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2026-07-28",
    )
    standard = create_published_module(
        api, code="NH-STD", title="New Hire Standard",
        module_type="NEW_HIRE", criticality="STANDARD",
    )
    critical = create_published_module(
        api, code="NH-HIGH", title="New Hire Critical",
        module_type="NEW_HIRE", criticality="HIGH",
    )

    std_assignment = assign_module(
        api, employee, standard, assignment_reason="NEW_HIRE")
    high_assignment = assign_module(
        api, read_employee(api, employee["id"]), critical,
        assignment_reason="NEW_HIRE",
    )

    assert_instant_equals(std_assignment["due_at"], "2026-08-15T00:00:00Z",
                          "standard due_at")
    assert_instant_equals(high_assignment["due_at"], "2026-08-08T00:00:00Z",
                          "high-criticality due_at")
    assert_instant_equals(high_assignment["effective_due_at"],
                          "2026-08-08T00:00:00Z", "effective_due_at")
    assert high_assignment["granted_extension_days"] == 0
    assert_instant_equals(high_assignment["assigned_at"], "2026-08-01T00:00:00Z",
                          "assigned_at")
    assert_assignment(high_assignment, state=ASSIGNMENT_ASSIGNED)

    # Different modules never supersede one another, so both rows survive.
    rows = validate_success(
        api.list_assignments({"employee_id": employee["id"]}, ADMIN))
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {ASSIGNMENT_ASSIGNED}


def test_each_sweep_sends_exactly_one_reminder_and_never_skips_ahead(api):
    """Three sweeps at one instant walk reminders_sent through 1, 2 and 3.

    PRD §3.4: "A single sweep sends **at most one reminder per assignment**, and it
    never skips ahead: an assignment whose first three reminder instants have all
    already passed emits exactly one reminder on this sweep, so three separate
    sweeps are required to drive `reminders_sent` to 3."

    Design: Corner/calculations/reminder_cadence_one_reminder_per_sweep_never_skips_ahead
    """
    reset_clock(api)
    employee = register_employee(
        api, email="cara.cadence@corp.example", full_name="Cara Cadence",
        department="HR", role_code="IC", hire_date="2018-06-06",
    )
    module = create_published_module(
        api, code="CAD-ANNUAL", title="Cadence Probe Module", module_type="ANNUAL")
    assignment = assign_module(api, employee, module, assignment_reason="ANNUAL")
    assert_instant_equals(assignment["effective_due_at"], "2026-08-31T00:00:00Z",
                          "effective_due_at")

    set_clock(api, "2026-08-30T12:00:00Z")
    for expected_count in (1, 2, 3):
        sweep = run_sweep(api)
        assert_sweep_counters(sweep, assignments_scanned=1,
                              reminders_sent_count=1, overdue_count=0,
                              escalations_created_count=0,
                              consequences_applied_count=0)
        assert read_assignment(api, assignment["id"])["reminders_sent"] \
            == expected_count

    final = read_assignment(api, assignment["id"])
    assert final["reminders_sent"] == 3
    assert_instant_equals(final["last_reminder_at"], "2026-08-30T12:00:00Z",
                          "last_reminder_at")
    assert_instant_equals(final["next_reminder_due_at"], "2026-09-02T00:00:00Z",
                          "next_reminder_due_at")
    assert_assignment(final, state=ASSIGNMENT_ASSIGNED, escalation_level=0)


def test_a_failure_older_than_180_days_falls_outside_the_repeat_window(api):
    """The window opens 180 days before the clock, so a January click stops counting.

    PRD §3.10: "The window opens exactly 180 days before the current logical clock,
    and its lower bound is inclusive. Inside that window, a failure delivery is one
    of this employee's own deliveries whose state is either `CLICKED` or
    `CREDENTIAL_SUBMITTED`, whose campaign is in state `RUNNING` or `CLOSED`, and
    whose `delivered_at` is at or after the window's opening instant."

    Design: Corner/calculations/repeat_clicker_tier_window_excludes_failures_older_than_180_days
    """
    reset_clock(api)
    set_clock(api, "2026-01-01T00:00:00Z")
    employee = register_employee(
        api, email="wanda.window@corp.example", full_name="Wanda Window",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2015-01-01",
    )
    template = approved_template(
        api, name="Window Probe Template", pretext_category="PACKAGE_DELIVERY",
        difficulty_tier=TIER_1, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )
    january = running_campaign(
        api, scheduled_send_at="2026-01-05T09:00:00Z", template=template,
        name="ENG January Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    old_delivery = delivery_for(api, january["campaign"]["id"], employee["id"])
    click(api, old_delivery["id"], "2026-01-05T09:30:00Z")

    set_clock(api, "2026-08-01T00:00:00Z")
    august = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="ENG August Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
    )
    new_delivery = delivery_for(api, august["campaign"]["id"], employee["id"])
    click(api, new_delivery["id"], "2026-08-02T09:30:00Z")

    after = read_employee(api, employee["id"])
    assert after["repeat_clicker_tier"] == 1, "only the August failure is in window"

    interventions = validate_success(
        api.list_interventions({"employee_id": employee["id"]}, ADMIN))
    assert interventions == [], "the tier never reached the intervention threshold"

    # The exclusion is by window, not by data loss: the old row still reads CLICKED.
    assert_delivery(read_delivery(api, old_delivery["id"]), state=DELIVERY_CLICKED)
    assert_delivery(read_delivery(api, new_delivery["id"]),
                    state=DELIVERY_CLICKED,
                    outcome_class=OUTCOME_CLICKED_NO_REPORT)


def test_the_harmful_theme_screen_reports_hits_in_the_declared_order(api):
    """Two prohibited tags come back in the prohibited list's order, not the author's.

    PRD §2.10: "The harmful-theme screen computes `harmful_flag_hits` as the list of
    prohibited themes that the template's `theme_tags` actually contains, ordered as
    the prohibited list is declared above rather than in the order the author
    happened to type them."

    PRD §2.10: "The last five are the prohibited themes, and they are prohibited in
    exactly that declaration order: `BONUS_COMPENSATION`, `LAYOFF_NOTICE`,
    `MEDICAL_RESULT`, `CHARITY_APPEAL`, `FAMILY_EMERGENCY`."

    Design: Corner/calculations/harmful_theme_screen_lists_only_prohibited_tags_in_declaration_order
    """
    reset_clock(api)
    submitted = ["FAMILY_EMERGENCY", "URGENCY", "BONUS_COMPENSATION"]

    flagged = validate_success(
        api.create_template(
            template_payload(
                name="Screen Order Probe",
                pretext_category="HR_BENEFITS_ENROLLMENT",
                difficulty_tier=TIER_2, theme_tags=list(submitted),
                credential_capture_enabled=False,
            ),
            AUTHOR,
        ),
        expected_status=201,
    )
    assert flagged["harmful_flag_hits"] == ["BONUS_COMPENSATION", "FAMILY_EMERGENCY"]
    assert flagged["theme_tags"] == submitted, "the submitted order is preserved"
    assert flagged["review_state"] == TEMPLATE_DRAFT
    assert flagged["blocked_reason"] is None

    fetched = validate_success(api.get_template(flagged["id"], AUTHOR))
    assert fetched["harmful_flag_hits"] == ["BONUS_COMPENSATION", "FAMILY_EMERGENCY"]

    clean = validate_success(
        api.create_template(
            template_payload(
                name="Only Safe Levers",
                pretext_category="PACKAGE_DELIVERY", difficulty_tier=TIER_2,
                theme_tags=["URGENCY", "AUTHORITY", "CURIOSITY", "REWARD"],
                credential_capture_enabled=False,
            ),
            AUTHOR,
        ),
        expected_status=201,
    )
    assert clean["harmful_flag_hits"] == []


def test_the_tenure_band_thresholds_belong_to_the_higher_band(api):
    """89, 90 and 365 whole days land in NEW_HIRE, EARLY and ESTABLISHED.

    PRD §3.1: "Fewer than 90 such days makes the `tenure_band` `NEW_HIRE`; from 90
    up to but not including 365 days it is `EARLY`; from 365 up to but not including
    1,095 days — that is, up to but not including the third anniversary — it is
    `ESTABLISHED`; and 1,095 days or more makes it `VETERAN`."

    Design: Corner/calculations/tenure_band_thresholds_at_exactly_90_and_365_days
    """
    reset_clock(api)

    eighty_nine = register_employee(
        api, email="t89@corp.example", full_name="Tina Eightynine",
        department="SALES", role_code="IC", hire_date="2026-05-04",
    )
    ninety = register_employee(
        api, email="t90@corp.example", full_name="Tom Ninety",
        department="SALES", role_code="IC", hire_date="2026-05-03",
    )
    three_sixty_five = register_employee(
        api, email="t365@corp.example", full_name="Tess Yearone",
        department="SALES", role_code="IC", hire_date="2025-08-01",
    )

    assert eighty_nine["tenure_band"] == TENURE_NEW_HIRE, "89 days is one day short"
    assert ninety["tenure_band"] == TENURE_EARLY, "exactly 90 days is the higher band"
    assert three_sixty_five["tenure_band"] == TENURE_ESTABLISHED

    for employee in (eighty_nine, ninety, three_sixty_five):
        assert employee["compliance_state"] == COMPLIANCE_COMPLIANT
        assert employee["access_posture"] == POSTURE_NONE


def test_two_reports_over_three_deliveries_round_to_four_decimal_places(api):
    """2/3 is 0.6667 rounded half up once, and resilience divides by max(1, clicks).

    PRD §3.9: "Otherwise `click_rate`, `report_rate` and `credential_rate` are each
    their numerator divided by the denominator, rounded half up to 4 decimal places,
    and `resilience_ratio` is the report numerator divided by the greater of 1 and
    the click numerator, rounded half up to 4 decimal places."

    Design: Corner/calculations/scorecard_precision_rounds_report_rate_to_four_decimals
    """
    reset_clock(api)
    first = register_employee(
        api, email="p1@corp.example", full_name="Pia One",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2015-01-01",
    )
    second = register_employee(
        api, email="p2@corp.example", full_name="Paul Two",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2015-02-01",
    )
    register_employee(
        api, email="p3@corp.example", full_name="Pam Three",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2015-03-01",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z",
        name="FIN Precision Wave", difficulty_tier=TIER_1,
        target_departments=["FINANCE"],
        template_overrides={
            "name": "Precision Probe",
            "pretext_category": "INVOICE_APPROVAL",
            "difficulty_tier": TIER_1,
            "theme_tags": ["AUTHORITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]
    first_delivery = delivery_for(api, campaign_id, first["id"])
    second_delivery = delivery_for(api, campaign_id, second["id"])

    report(api, first_delivery["id"], "2026-08-02T09:20:00Z")
    report(api, second_delivery["id"], "2026-08-02T09:20:00Z",
           advance_clock=False)

    scorecard = validate_success(api.get_scorecard(campaign_id, ANALYST))
    assert scorecard["campaign_id"] == campaign_id
    assert scorecard["evaluable_count"] == 3
    assert scorecard["excluded_count"] == 0
    assert_rate(scorecard["report_rate"], 0.6667, "report_rate")
    assert_four_decimal_places(scorecard["report_rate"], "report_rate")
    assert_rate(scorecard["click_rate"], 0.0000, "click_rate")
    assert_rate(scorecard["credential_rate"], 0.0000, "credential_rate")
    assert_rate(scorecard["resilience_ratio"], 2.0000, "resilience_ratio")

    settled = read_delivery(api, first_delivery["id"])
    assert_delivery(settled, outcome_class=OUTCOME_REPORTED_ONLY)
    assert settled["time_to_report_minutes"] == 20


def test_an_explicit_consequence_type_takes_its_rank_straight_from_the_map(api):
    """Supplying SYSTEM_ACCESS_SUSPENSION skips the derived pre_rank + 1 ladder.

    PRD §3.6: "Choose the new rank. If the request supplied a `consequence_type`,
    the new rank is simply that type's rank."

    PRD §3.6: "The rank mapping is fixed: `WARNING` ranks 1, `MFA_REVIEW` ranks 2,
    and `SYSTEM_ACCESS_SUSPENSION` ranks 3."

    Design: Corner/calculations/explicit_consequence_type_bypasses_severity_derivation
    """
    reset_clock(api)
    employee = register_employee(
        api, email="sam.susp@corp.example", full_name="Sam Susp",
        department="IT", role_code="IT_ADMIN", hire_date="2016-02-02",
    )

    consequence = validate_success(
        api.apply_access_consequence(
            employee["id"],
            consequence_payload(employee["version"],
                                reason_code="POLICY_BREACH_INVESTIGATION",
                                consequence_type=CONSEQUENCE_SUSPENSION),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_consequence(consequence, state=CONSEQUENCE_ACTIVE,
                       consequence_type=CONSEQUENCE_SUSPENSION, severity_rank=3)
    assert_instant_equals(consequence["applied_at"], "2026-08-01T00:00:00Z",
                          "applied_at")
    assert consequence["source_assignment_id"] is None

    after = read_employee(api, employee["id"])
    assert after["access_posture"] == POSTURE_SUSPENDED
    assert_ledgers(after, active_suspension_count=1)
    assert after["version"] == employee["version"] + 1


def test_closing_an_intervention_without_a_clean_streak_leaves_the_tier_alone(api):
    """Coaching alone never buys back a tier: the decay needs three clean runs.

    PRD §3.10: "The close is also the only place a tier ever decays, and the decay
    is conditional: only when the employee's `consecutive_clean_simulations` is 3 or
    more does the close decrement `repeat_clicker_tier` by one — floored at 0 — and
    set `tier_decay_applied` to true. Coaching alone does not earn the decay; a
    demonstrated clean streak does."

    Design: Corner/calculations/intervention_close_without_clean_streak_does_not_decay_tier
    """
    reset_clock(api)
    coaching_module = create_published_module(
        api, code="REM-COACH", title="Targeted Phishing Coaching",
        module_type="REMEDIAL",
    )
    ctx = repeat_clicker_at_tier_two(api, department="SALES",
                                     hire_date="2016-03-03")
    employee = ctx["employee"]
    intervention = ctx["intervention"]
    assert intervention is not None
    assert employee["consecutive_clean_simulations"] == 0

    assigned = validate_success(
        api.assign_coaching(
            intervention["id"], {"module_id": coaching_module["id"]}, ADMIN)
    )
    coaching_assignment_id = assigned["coaching_assignment_id"]
    learner = make_learner_headers(employee["id"])
    validate_success(api.start_assignment(coaching_assignment_id, learner))
    validate_success(
        api.submit_assignment(coaching_assignment_id, {"score_pct": 95}, learner))

    before_close = validate_success(api.get_intervention(intervention["id"], ADMIN))
    assert before_close["state"] == "COACHING_COMPLETED"

    closed = validate_success(
        api.close_intervention(
            intervention["id"], {"resolution_code": "COACHING_DELIVERED"}, ADMIN)
    )
    assert closed["state"] == "CLOSED_RESOLVED"
    assert closed["resolution_code"] == "COACHING_DELIVERED"
    assert_instant_equals(closed["closed_at"], "2026-08-08T10:00:00Z", "closed_at")
    assert closed["tier_decay_applied"] is False

    after = read_employee(api, employee["id"])
    assert after["repeat_clicker_tier"] == 2, "no decay without a clean streak of 3"
    assert_risk_scores(after, provisional=24.00)

    coaching = read_assignment(api, coaching_assignment_id)
    assert_assignment(coaching, state=ASSIGNMENT_COMPLETED)
    assert coaching["assignment_reason"] == "REMEDIAL"


def test_a_single_month_bucket_reports_insufficient_pairs(api):
    """One surviving pair is fewer than two, so the correlation is null with a reason.

    PRD §3.10: "If fewer than 2 pairs survive, or if either of the two paired series
    has zero variance, the `correlation` is `null` and a `correlation_reason_code` of
    `INSUFFICIENT_PAIRS` or `ZERO_VARIANCE` respectively explains why."

    PRD §3.10: "The computed `phish_related` flag is true exactly when the
    `incident_type` is `CREDENTIAL_PHISH` or `BEC`; malware-delivery and data-loss
    incidents are excluded from the correlation series entirely."

    Design: Corner/calculations/effectiveness_report_single_bucket_reports_insufficient_pairs
    """
    reset_clock(api)
    set_clock(api, "2026-03-01T00:00:00Z")
    employee = register_employee(
        api, email="mona.metric@corp.example", full_name="Mona Metric",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2015-04-04",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-03-05T09:00:00Z",
        name="ENG March Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
        template_overrides={
            "name": "Report Metric Probe",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])
    report(api, delivery["id"], "2026-03-05T09:15:00Z")

    set_clock(api, "2026-03-10T12:00:00Z")
    close_campaign(api, ctx["campaign"]["id"],
                   debrief_note="March wave closed with a single reported delivery.")

    set_clock(api, "2026-03-20T00:00:00Z")
    phish = validate_success(
        api.create_incident(
            {"incident_type": "BEC", "severity": "HIGH",
             "department": "ENGINEERING", "occurred_at": "2026-03-15T08:00:00Z",
             "summary": "Vendor payment redirection attempt."},
            ANALYST,
        ),
        expected_status=201,
    )
    malware = validate_success(
        api.create_incident(
            {"incident_type": "MALWARE_DELIVERY", "severity": "LOW",
             "department": "ENGINEERING", "occurred_at": "2026-03-16T08:00:00Z",
             "summary": "Blocked macro attachment."},
            ANALYST,
        ),
        expected_status=201,
    )
    assert phish["phish_related"] is True
    assert malware["phish_related"] is False

    result = validate_success(
        api.get_effectiveness_report(
            effectiveness_params("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z",
                                 variant=REPORT_VARIANT_CONCURRENT),
            ANALYST,
        )
    )
    assert result["variant"] == REPORT_VARIANT_CONCURRENT
    assert result["pair_count"] == 1
    assert result["correlation"] is None
    assert result["correlation_reason_code"] == "INSUFFICIENT_PAIRS"
    assert_rate(result["mean_report_rate"], 1.0000, "mean_report_rate")
    assert result["total_incidents"] == 1, "only the phish-related BEC row counts"
    assert len(result["buckets"]) == 1
