"""Derived-arithmetic breadth: interval tables, caps, clamps, tiers and windows."""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_cfs,
    assert_freeboard,
    assert_instant,
    assert_score,
    assert_storage_conservation,
)
from test_helpers import factories as f
from test_helpers.constants import (
    ALERT_CRITICAL,
    ASSESSMENT_CERTIFIED,
    CATEGORY_EAP_EXERCISE,
    CATEGORY_SPILLWAY_CAPACITY,
    CATEGORY_STRUCTURAL,
    CLOCK_ORIGIN,
    DEFICIENCY_OPEN,
    DEFICIENCY_ORDERED,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    DRAWDOWN_COMPLETED,
    DRAWDOWN_COORDINATED,
    EAP_APPROVED,
    EAP_NONE,
    ENTRY_PAYMENT_RECEIVED,
    ENTRY_PERMIT_REVIEW_FEE,
    EVENT_EMERGENCY,
    EXERCISE_ACCEPTED,
    EXERCISE_DEFICIENT,
    EXERCISE_TABLETOP,
    HAZARD_HIGH,
    HAZARD_LOW,
    HAZARD_UNCLASSIFIED,
    ORDER_ISSUED,
    ORDER_TYPE_EMERGENCY,
    ORDER_TYPE_NOTICE,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_CONSTRUCTION,
    PERMIT_TYPE_REPAIR,
    REASON_INSUFFICIENT_PARTICIPANTS,
    REASON_NOTIFICATION_TEST_FAILED,
    SEVERITY_CRITICAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SOURCE_SYSTEM_EXERCISE,
)
from test_helpers.test_users import make_owner_headers


# ---------------------------------------------------------------------------
# LOW and UNCLASSIFIED read the same 60-month interval
# ---------------------------------------------------------------------------
def test_the_unclassified_dam_starts_on_the_sixty_month_interval(program, base):
    """A brand new dam is already scheduled, on the unclassified interval.

    PRD 3.1: "Its inspection clock starts immediately on the unclassified interval: `next_inspection_due_at` is `registered_at` advanced by 60 calendar months, and `inspection_overdue` is derived from that against the current logical clock."

    Design: Corner/calculations/low_and_unclassified_dams_share_the_sixty_month_inspection_interval
    """
    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_UNCLASSIFIED
    assert dam["current_consequence_score"] is None
    # Registered 2019-04-15 advanced by 60 calendar months.
    assert_instant(
        dam["next_inspection_due_at"],
        "2024-04-15T00:00:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is True


def test_a_zero_consequence_row_maps_to_low_under_both_variants(program, base):
    """One mapping table serves the screening figure and the certified figure alike.

    PRD 3.2: "This same mapping produces `recommended_hazard_class` from the screening score at filing and `certified_hazard_class` from the certified score at certification."

    Design: Corner/calculations/low_and_unclassified_dams_share_the_sixty_month_inspection_interval
    """
    filed = program.create_assessment(f.assessment_a3(base.dam_id), base.engineer_a_id)
    assert_score(filed["screening_score"], 0.00, "screening_score")
    assert filed["recommended_hazard_class"] == HAZARD_LOW
    assert filed["certified_score"] is None
    assert filed["certified_hazard_class"] is None

    certified = program.certify_assessment(filed["id"], base.engineer_a_id)
    assert certified["status"] == ASSESSMENT_CERTIFIED
    assert_score(certified["certified_score"], 0.00, "certified_score")
    assert certified["certified_hazard_class"] == HAZARD_LOW
    assert_instant(certified["certified_at"], CLOCK_ORIGIN, "certified_at")


def test_publishing_low_does_not_move_the_due_date_it_inherited(program, base):
    """The constant table, not the transition, is what moves an inspection date.

    PRD 2.8: "A `HIGH`-hazard dam is inspected every 12 months; a `SIGNIFICANT` dam every 24 months; a `LOW` dam every 60 months. An `UNCLASSIFIED` dam is scheduled on the same 60-month interval as a `LOW` dam."

    Design: Corner/calculations/low_and_unclassified_dams_share_the_sixty_month_inspection_interval
    """
    program.classify_low(base.dam_id, base.engineer_a_id)

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_LOW
    assert_score(dam["current_consequence_score"], 0.00, "current_consequence_score")
    assert_instant(
        dam["next_inspection_due_at"],
        "2024-04-15T00:00:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is True


def test_a_low_dam_carries_no_emergency_action_plan_duty(program, base):
    """The plan obligation switches off at the bottom two rungs of the dial.

    PRD 2.8: "The derived flag `eap_required` on a dam is true exactly when its `hazard_class` is `SIGNIFICANT` or `HIGH`, and false for `LOW` and `UNCLASSIFIED`."

    Design: Corner/calculations/low_and_unclassified_dams_share_the_sixty_month_inspection_interval
    """
    assert program.get_dam(base.dam_id)["eap_required"] is False

    program.classify_low(base.dam_id, base.engineer_a_id)
    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_LOW
    assert dam["eap_required"] is False
    assert dam["latest_eap_status"] == EAP_NONE
    assert dam["open_deficiency_count"] == 0


# ---------------------------------------------------------------------------
# The four score components saturate before they are added
# ---------------------------------------------------------------------------
def test_every_score_component_saturates_before_the_four_are_added(program, base):
    """Population 300, structures 60, facilities 50 and 9 economic points all clamp.

    PRD 3.2: "Each of the four is capped individually **before** the four are added together, and the sum is never capped again; a score can therefore reach exactly `100.00` only when all four components sit at their caps."

    Design: Corner/calculations/consequence_score_components_are_capped_before_the_sum
    """
    filed = program.create_assessment(f.assessment_a4(base.dam_id), base.engineer_a_id)
    # 60 + 20 + 15 with the economic component forced to 0 while screening.
    assert_score(filed["screening_score"], 95.00, "screening_score")
    assert filed["recommended_hazard_class"] == HAZARD_HIGH

    certified = program.certify_assessment(filed["id"], base.engineer_a_id)
    # The same three caps plus the 5-point economic cap taken from 900 acres.
    assert_score(certified["certified_score"], 100.00, "certified_score")
    assert certified["certified_hazard_class"] == HAZARD_HIGH


def test_the_capped_score_moves_the_dam_onto_the_twelve_month_interval(program, base):
    """A 100.00 certified score publishes HIGH and halves the interval twice over.

    PRD 3.3: "`next_inspection_due_at` is that baseline advanced by the hazard class's interval in whole calendar months — 12 months at `HIGH`, 24 at `SIGNIFICANT`, 60 at `LOW` and 60 while `UNCLASSIFIED` — preserving the day of month."

    Design: Corner/calculations/consequence_score_components_are_capped_before_the_sum
    """
    program.classify(base.dam_id, base.engineer_a_id, f.assessment_a4)

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_HIGH
    assert_score(dam["current_consequence_score"], 100.00, "current_consequence_score")
    # Registered 2019-04-15 advanced by the HIGH interval of 12 months.
    assert_instant(
        dam["next_inspection_due_at"],
        "2020-04-15T00:00:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is True
    assert dam["eap_required"] is True
    # No plan was ever approved, so the plan-gap cascade opens nothing.
    assert dam["open_deficiency_count"] == 0


# ---------------------------------------------------------------------------
# Response-day clamps on a HIGH-hazard dam
# ---------------------------------------------------------------------------
@pytest.fixture()
def high_dam_defects(program, base):
    """A HIGH-hazard dam whose submitted inspection found CRITICAL and MINOR defects."""
    program.classify(base.dam_id, base.engineer_a_id, f.assessment_a4)
    inspection = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_SPILLWAY_CAPACITY,
                severity=SEVERITY_CRITICAL,
                description="Service spillway crest undermined across three bays.",
            ),
            f.deficiency_item(
                category=CATEGORY_STRUCTURAL,
                severity=SEVERITY_MINOR,
                description="Minor spalling along the upstream parapet wall.",
            ),
        ],
    )
    rows = program.deficiencies_for(base.dam_id)
    return {
        "critical": next(r for r in rows if r["severity"] == SEVERITY_CRITICAL),
        "minor": next(r for r in rows if r["severity"] == SEVERITY_MINOR),
    }


def test_the_critical_emergency_order_lands_on_the_five_day_floor(
    program, high_dam_defects
):
    """Ten days compressed by 0.5 hits the floor, the ceiling of an emergency order.

    PRD 3.4: "The rounded-down figure is then clamped to a floor of 5 days and a ceiling of 365 days, in that order: the larger of 5 and the smaller of 365 and the rounded product."

    Design: Corner/calculations/emergency_order_response_days_clamp_to_the_five_day_floor
    """
    order = program.issue_order(
        high_dam_defects["critical"]["id"],
        order_type=ORDER_TYPE_EMERGENCY,
        requested_response_days=30,
    )
    assert order["status"] == ORDER_ISSUED
    assert order["effective_response_days"] == 5
    assert_instant(order["issued_at"], "2026-08-05T13:00:00Z", "issued_at")
    assert_instant(
        order["compliance_deadline_at"],
        "2026-08-10T13:00:00Z",
        "compliance_deadline_at",
    )
    assert_cents(order["assessed_penalty_cents"], 0, "assessed_penalty_cents")
    assert order["defaulted_at"] is None


def test_the_minor_notice_clamps_the_four_hundred_day_request_down_to_ninety(
    program, high_dam_defects
):
    """The state may grant less time than the schedule allows but never more.

    PRD 3.4: "The result is the schedule's allowance, and `effective_response_days` is the smaller of `requested_response_days` and that allowance."

    Design: Corner/calculations/emergency_order_response_days_clamp_to_the_five_day_floor
    """
    order = program.issue_order(
        high_dam_defects["minor"]["id"],
        order_type=ORDER_TYPE_NOTICE,
        requested_response_days=400,
    )
    # 180 days for MINOR compressed by the HIGH factor of 0.5.
    assert order["effective_response_days"] == 90
    assert_instant(
        order["compliance_deadline_at"],
        "2026-11-03T13:00:00Z",
        "compliance_deadline_at",
    )


def test_both_orders_pin_the_hazard_uplifted_daily_rate_and_move_their_defects(
    program, base, high_dam_defects
):
    """Each order prices its own severity at issue time and takes its deficiency.

    PRD 3.4: "The rate is the severity's daily base — 2,000 cents for `MINOR`, 5,000 cents for `MODERATE`, 12,500 cents for `SERIOUS` and 25,000 cents for `CRITICAL` — multiplied by the hazard penalty factor of 1.6 for `HIGH`, 1.25 for `SIGNIFICANT` and 1.0 for both `LOW` and `UNCLASSIFIED`, with the product rounded half up to whole cents."

    Design: Corner/calculations/emergency_order_response_days_clamp_to_the_five_day_floor
    """
    critical_order = program.issue_order(
        high_dam_defects["critical"]["id"],
        order_type=ORDER_TYPE_EMERGENCY,
        requested_response_days=30,
    )
    minor_order = program.issue_order(
        high_dam_defects["minor"]["id"],
        order_type=ORDER_TYPE_NOTICE,
        requested_response_days=400,
    )
    assert_cents(
        critical_order["daily_penalty_rate_cents"],
        40000,
        "daily_penalty_rate_cents",
    )
    assert_cents(
        minor_order["daily_penalty_rate_cents"], 3200, "daily_penalty_rate_cents"
    )

    rows = program.deficiencies_for(base.dam_id)
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == DEFICIENCY_ORDERED
        assert row["order_count"] == 1
    deadlines = {
        SEVERITY_CRITICAL: critical_order["compliance_deadline_at"],
        SEVERITY_MINOR: minor_order["compliance_deadline_at"],
    }
    for row in rows:
        assert_instant(
            row["remediation_due_at"],
            deadlines[row["severity"]],
            "remediation_due_at",
        )
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 2


# ---------------------------------------------------------------------------
# The permit base-fee tier boundary is exclusive at the top
# ---------------------------------------------------------------------------
@pytest.fixture()
def tier_boundary_permits(program, base):
    """Two REPAIR applications one cent apart across the 5,000,000-cent boundary."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    first = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        scope_description="Crest repaving just under the tier boundary.",
        estimated_project_cost_cents=4_999_999,
    )
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-52_500,
        memo="Tier 1 review fee settled.",
    )
    second = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        scope_description="Crest repaving exactly at the tier boundary.",
        estimated_project_cost_cents=5_000_000,
        proposed_start_date="2026-11-01T00:00:00Z",
    )
    return {"first": first, "second": second}


def test_one_cent_across_the_tier_boundary_costs_seventy_five_thousand_more(
    tier_boundary_permits
):
    """Every tier's upper bound is exclusive, so the boundary cost pays the next tier.

    PRD 3.6: "**First**, a flat base tier on project cost, with every tier's upper bound exclusive: a cost below 5,000,000 cents pays a base of 25,000 cents; a cost of 5,000,000 cents or more but below 50,000,000 cents pays 100,000 cents; a cost of 50,000,000 cents or more but below 500,000,000 cents pays 350,000 cents; and a cost of 500,000,000 cents or more pays 900,000 cents."

    Design: Corner/calculations/permit_base_fee_tier_boundary_is_exclusive_at_five_million_cents
    """
    first = tier_boundary_permits["first"]
    second = tier_boundary_permits["second"]
    assert_cents(first["base_fee_cents"], 25000, "base_fee_cents")
    assert_cents(second["base_fee_cents"], 100000, "base_fee_cents")
    assert_cents(first["total_fee_cents"], 52500, "total_fee_cents")
    assert_cents(second["total_fee_cents"], 127500, "total_fee_cents")
    assert first["status"] == PERMIT_SUBMITTED
    assert second["status"] == PERMIT_SUBMITTED
    assert first["revision_count"] == 0
    assert second["revision_count"] == 0


def test_the_percentage_review_fee_rounds_to_the_same_figure_on_both_sides(
    tier_boundary_permits
):
    """A one-cent difference in cost disappears in the rounding of the review fee.

    PRD 3.6: "**Second**, an engineering review fee proportional to the project: the cost is multiplied by the work class's percentage — 0.75 percent for `CONSTRUCTION`, 0.5 percent for `REPAIR`, 0.35 percent for `REMOVAL` — and then by the hazard uplift of 1.25 at `HIGH`, 1.10 at `SIGNIFICANT`, and 1.0 at both `LOW` and `UNCLASSIFIED`; the product is rounded half up to whole cents and then capped at 750,000 cents."

    Design: Corner/calculations/permit_base_fee_tier_boundary_is_exclusive_at_five_million_cents
    """
    for permit in (tier_boundary_permits["first"], tier_boundary_permits["second"]):
        assert_cents(
            permit["engineering_review_fee_cents"],
            27500,
            "engineering_review_fee_cents",
        )
        assert_cents(permit["volume_credit_cents"], 0, "volume_credit_cents")


def test_the_intervening_payment_keeps_the_second_application_surcharge_free(
    program, base, tier_boundary_permits
):
    """Delinquency is read at the moment of application, and the ledger was clear.

    PRD 3.6: "**Third**, if the owner's `delinquency_status` is `DELINQUENT` at the moment of application, a surcharge of 15 percent of that subtotal, rounded half up to whole cents, is charged as `delinquency_surcharge_cents`; a current owner is charged 0."

    Design: Corner/calculations/permit_base_fee_tier_boundary_is_exclusive_at_five_million_cents
    """
    for permit in (tier_boundary_permits["first"], tier_boundary_permits["second"]):
        assert_cents(
            permit["delinquency_surcharge_cents"],
            0,
            "delinquency_surcharge_cents",
        )

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 3
    assert [row["entry_type"] for row in rows] == [
        ENTRY_PERMIT_REVIEW_FEE,
        ENTRY_PAYMENT_RECEIVED,
        ENTRY_PERMIT_REVIEW_FEE,
    ]
    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 127500, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT


# ---------------------------------------------------------------------------
# The review fee cap and the volume credit
# ---------------------------------------------------------------------------
@pytest.fixture()
def capped_review_permit(program, base):
    """A 500,000,000-cent CONSTRUCTION application on a HIGH-hazard dam."""
    program.classify(base.dam_id, base.engineer_a_id, f.assessment_a4)
    assert program.get_owner(base.owner_id)["delinquency_status"] == DELINQUENCY_CURRENT
    return program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="Full spillway reconstruction and crest raise.",
        estimated_project_cost_cents=500_000_000,
        proposed_start_date="2027-04-01T00:00:00Z",
    )


def test_the_review_fee_stops_at_seven_hundred_fifty_thousand_cents(
    capped_review_permit
):
    """A 4,687,500-cent proportional fee is cut back to the statutory cap.

    PRD 3.6: "**Second**, an engineering review fee proportional to the project: the cost is multiplied by the work class's percentage — 0.75 percent for `CONSTRUCTION`, 0.5 percent for `REPAIR`, 0.35 percent for `REMOVAL` — and then by the hazard uplift of 1.25 at `HIGH`, 1.10 at `SIGNIFICANT`, and 1.0 at both `LOW` and `UNCLASSIFIED`; the product is rounded half up to whole cents and then capped at 750,000 cents."

    Design: Corner/calculations/engineering_review_fee_is_capped_at_seven_hundred_fifty_thousand_cents
    """
    assert_cents(capped_review_permit["base_fee_cents"], 900000, "base_fee_cents")
    assert_cents(
        capped_review_permit["engineering_review_fee_cents"],
        750000,
        "engineering_review_fee_cents",
    )
    assert_cents(
        capped_review_permit["delinquency_surcharge_cents"],
        0,
        "delinquency_surcharge_cents",
    )


def test_the_volume_credit_is_decided_once_on_the_pre_credit_total(
    program, base, capped_review_permit
):
    """A 1,650,000-cent pre-credit total earns ten percent back as a credit.

    PRD 3.6: "**Fourth**, a program volume credit is decided **once** on that pre-credit total: if the pre-credit total is at least 500,000 cents, `volume_credit_cents` is 10 percent of it rounded half up to whole cents, and otherwise it is 0."

    Design: Corner/calculations/engineering_review_fee_is_capped_at_seven_hundred_fifty_thousand_cents
    """
    assert_cents(
        capped_review_permit["volume_credit_cents"], 165000, "volume_credit_cents"
    )
    assert_cents(capped_review_permit["total_fee_cents"], 1485000, "total_fee_cents")

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == ENTRY_PERMIT_REVIEW_FEE
    assert_cents(rows[0]["amount_cents"], 1485000, "amount_cents")
    assert_cents(rows[0]["balance_after_cents"], 1485000, "balance_after_cents")

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 1485000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT


# ---------------------------------------------------------------------------
# The rolling 365-day exercise window is exclusive at its lower bound
# ---------------------------------------------------------------------------
@pytest.fixture()
def live_plan(program, base):
    """An APPROVED plan with four notification contacts on a SIGNIFICANT dam."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    return program.approved_plan(base.dam_id, base.owner_id, base.engineer_b_id)


def test_the_approved_plan_runs_sixty_months_at_significant(program, base, live_plan):
    """Approval stamps the plan and prices its validity off the hazard dial.

    PRD 3.5: "`APPROVE` moves the plan `SUBMITTED → APPROVED`, stamps `approved_at` with the logical clock, and computes `expires_at` as `approved_at` advanced by the hazard class's validity in whole calendar months preserving the day of month — 36 months at `HIGH`, 60 months at `SIGNIFICANT`, and no expiry at all at `LOW`, where `expires_at` stays null."

    Design: Corner/calculations/exercise_currency_excludes_an_exercise_exactly_365_days_old
    """
    assert live_plan["status"] == EAP_APPROVED
    assert_instant(live_plan["approved_at"], CLOCK_ORIGIN, "approved_at")
    assert_instant(live_plan["expires_at"], "2031-08-01T00:00:00Z", "expires_at")
    assert live_plan["accepted_exercise_count"] == 0
    assert live_plan["exercise_current"] is False
    assert live_plan["last_accepted_exercise_at"] is None

    assert program.get_dam(base.dam_id)["latest_eap_status"] == EAP_APPROVED


def test_an_exercise_conducted_exactly_365_days_ago_is_no_longer_current(
    program, base, live_plan
):
    """The lower bound of the currency window excludes the instant itself.

    PRD 3.5: "The plan is current exactly when at least one exercise on the dam's `APPROVED` plan is graded `ACCEPTED` and its `conducted_at` is **strictly later** than the clock less 365 days and at or before the clock — the lower bound is exclusive, so an exercise conducted exactly 365 days ago no longer counts, while the upper bound is inclusive."

    Design: Corner/calculations/exercise_currency_excludes_an_exercise_exactly_365_days_old
    """
    logged = program.log_exercise(
        live_plan["id"],
        make_owner_headers(base.owner_id),
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2025-08-01T00:00:00Z",
        participant_count=4,
        notification_test_passed=True,
    )
    assert logged["outcome"] == EXERCISE_ACCEPTED
    assert logged["deficiency_reason"] is None

    plan = program.get_plan(live_plan["id"])
    assert plan["accepted_exercise_count"] == 1
    assert_instant(
        plan["last_accepted_exercise_at"],
        "2025-08-01T00:00:00Z",
        "last_accepted_exercise_at",
    )
    assert plan["exercise_current"] is False

    summary = program.summary(base.dam_id)
    assert summary["eap_exercise_current"] is False
    assert summary["latest_eap_status"] == EAP_APPROVED
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 0


def test_one_second_inside_the_window_makes_the_plan_current(
    program, base, live_plan
):
    """A second exercise one second later sits inside the rolling window.

    PRD 3.5: "Currency runs on a **rolling 365-day window** ending at the current clock."

    Design: Corner/calculations/exercise_currency_excludes_an_exercise_exactly_365_days_old
    """
    owner = make_owner_headers(base.owner_id)
    program.log_exercise(
        live_plan["id"],
        owner,
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2025-08-01T00:00:00Z",
        participant_count=4,
        notification_test_passed=True,
    )
    program.log_exercise(
        live_plan["id"],
        owner,
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2025-08-01T00:00:01Z",
        participant_count=4,
        notification_test_passed=True,
    )

    plan = program.get_plan(live_plan["id"])
    assert plan["accepted_exercise_count"] == 2
    assert_instant(
        plan["last_accepted_exercise_at"],
        "2025-08-01T00:00:01Z",
        "last_accepted_exercise_at",
    )
    assert plan["exercise_current"] is True
    assert program.summary(base.dam_id)["eap_exercise_current"] is True


# ---------------------------------------------------------------------------
# Exercise grading reports the first failure in the declared order
# ---------------------------------------------------------------------------
def test_a_failed_notification_test_outranks_the_participant_shortfall(
    program, base, live_plan
):
    """Two simultaneous failures report the earlier check, not the worse one.

    PRD 3.5: "If any fails, `outcome` is `DEFICIENT` and `deficiency_reason` is the **first** failure in that same fixed order, recorded as `NOTIFICATION_TEST_FAILED`, `INSUFFICIENT_PARTICIPANTS` or `EXERCISE_TYPE_NOT_PERMITTED`; a tabletop exercise on a high-hazard dam that also failed its notification test records `NOTIFICATION_TEST_FAILED`, not the format failure."

    Design: Corner/calculations/exercise_deficiency_reason_reports_the_first_failure_in_the_declared_order
    """
    both_failed = program.log_exercise(
        live_plan["id"],
        make_owner_headers(base.owner_id),
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2026-07-15T00:00:00Z",
        participant_count=2,
        notification_test_passed=False,
    )
    assert both_failed["outcome"] == EXERCISE_DEFICIENT
    assert both_failed["deficiency_reason"] == REASON_NOTIFICATION_TEST_FAILED

    short_only = program.log_exercise(
        live_plan["id"],
        program.coordinator,
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2026-07-16T00:00:00Z",
        participant_count=3,
        notification_test_passed=True,
    )
    assert short_only["outcome"] == EXERCISE_DEFICIENT
    assert short_only["deficiency_reason"] == REASON_INSUFFICIENT_PARTICIPANTS


def test_each_deficient_run_opens_its_own_system_exercise_deficiency(
    api, program, base, live_plan
):
    """Two failed drills leave two separate program deficiencies behind.

    PRD 3.5: "A deficient exercise additionally opens a deficiency with `source` of `SYSTEM_EXERCISE`, `category` of `EAP_EXERCISE`, `severity` of `MODERATE` and `status` of `OPEN`, incrementing the dam's `open_deficiency_count`."

    Design: Corner/calculations/exercise_deficiency_reason_reports_the_first_failure_in_the_declared_order
    """
    owner = make_owner_headers(base.owner_id)
    program.log_exercise(
        live_plan["id"],
        owner,
        conducted_at="2026-07-15T00:00:00Z",
        participant_count=2,
        notification_test_passed=False,
    )
    program.log_exercise(
        live_plan["id"],
        owner,
        conducted_at="2026-07-16T00:00:00Z",
        participant_count=3,
        notification_test_passed=True,
    )

    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 2
    rows = program.deficiencies_for(base.dam_id)
    assert len(rows) == 2
    for row in rows:
        assert row["source"] == SOURCE_SYSTEM_EXERCISE
        assert row["category"] == CATEGORY_EAP_EXERCISE
        assert row["severity"] == SEVERITY_MODERATE
        assert row["status"] == DEFICIENCY_OPEN
        assert row["inspection_id"] is None

    deficient, meta = validate_paginated(
        api.list_exercises(live_plan["id"], program.admin, {"outcome": EXERCISE_DEFICIENT})
    )
    assert len(deficient) == 2
    assert meta["total_count"] == 2


def test_only_a_clean_run_refreshes_the_plans_currency_fields(
    program, base, live_plan
):
    """The deficient drills leave the counters alone until a clean one lands.

    PRD 3.5: "An accepted exercise refreshes the plan's currency fields: `accepted_exercise_count`, `last_accepted_exercise_at`, and the boolean `exercise_current`."

    Design: Corner/calculations/exercise_deficiency_reason_reports_the_first_failure_in_the_declared_order
    """
    owner = make_owner_headers(base.owner_id)
    program.log_exercise(
        live_plan["id"],
        owner,
        conducted_at="2026-07-15T00:00:00Z",
        participant_count=2,
        notification_test_passed=False,
    )
    interim = program.get_plan(live_plan["id"])
    assert interim["accepted_exercise_count"] == 0
    assert interim["exercise_current"] is False
    assert interim["last_accepted_exercise_at"] is None

    clean = program.log_exercise(
        live_plan["id"],
        owner,
        conducted_at="2026-07-17T00:00:00Z",
        participant_count=4,
        notification_test_passed=True,
    )
    assert clean["outcome"] == EXERCISE_ACCEPTED
    assert clean["deficiency_reason"] is None

    plan = program.get_plan(live_plan["id"])
    assert plan["accepted_exercise_count"] == 1
    assert_instant(
        plan["last_accepted_exercise_at"],
        "2026-07-17T00:00:00Z",
        "last_accepted_exercise_at",
    )
    assert plan["exercise_current"] is True


# ---------------------------------------------------------------------------
# A completed order leaves the windowed channel-capacity input set
# ---------------------------------------------------------------------------
@pytest.fixture()
def escalated_event(api, program, base):
    """A MONITORING event driven into EMERGENCY by two rising critical readings."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    event = program.declare_event(
        base.dam_id,
        declared_at=CLOCK_ORIGIN,
        trigger_description="Basin-wide thunderstorm cell parked over the watershed.",
        declared_inflow_cfs=1500,
    )
    program.set_clock("2026-08-01T04:00:00Z")
    first = validate_success(
        api.create_reading(
            event["id"],
            f.reading_payload("2026-08-01T02:00:00Z", 1041.9),
            program.coordinator,
        ),
        201,
    )
    second = validate_success(
        api.create_reading(
            event["id"],
            f.reading_payload("2026-08-01T04:00:00Z", 1042.0),
            program.coordinator,
        ),
        201,
    )
    return {"event": event, "first": first, "second": second}


def test_both_readings_land_in_the_critical_freeboard_band(escalated_event):
    """Half a foot and six tenths of a foot of margin are both critical.

    PRD 3.7: "The reading's `alert_level` is then a four-band ladder on that freeboard, each band inclusive at its upper bound: a freeboard of 0.00 feet or below is `OVERTOPPING`; above that but at or below 1.00 feet is `CRITICAL`; above that but at or below 3.00 feet is `WATCH`; anything greater is `NORMAL`."

    Design: Corner/calculations/completed_orders_leave_the_windowed_capacity_input_set
    """
    first = escalated_event["first"]
    assert_freeboard(first["freeboard_ft"], 0.60, "freeboard_ft")
    assert first["alert_level"] == ALERT_CRITICAL
    assert first["rising"] is False

    second = escalated_event["second"]
    assert_freeboard(second["freeboard_ft"], 0.50, "freeboard_ft")
    assert second["alert_level"] == ALERT_CRITICAL
    assert second["rising"] is True


def test_the_rising_critical_reading_escalates_the_event(program, escalated_event):
    """The second reading trends upward, so the event escalates by itself.

    PRD 3.7: "If the event is still `MONITORING` and the new reading's `alert_level` is `CRITICAL` or `OVERTOPPING` **and** its `rising` flag is true, the event moves `MONITORING → EMERGENCY` and `escalated_at` is stamped with the logical clock."

    Design: Corner/calculations/completed_orders_leave_the_windowed_capacity_input_set
    """
    event = program.get_event(escalated_event["event"]["id"])
    assert event["status"] == EVENT_EMERGENCY
    assert_instant(event["escalated_at"], "2026-08-01T04:00:00Z", "escalated_at")
    assert event["reading_count"] == 2
    assert event["current_alert_level"] == ALERT_CRITICAL
    assert event["peak_pool_elevation_ft"] == pytest.approx(1042.0, abs=0.005)


def test_completion_hands_back_the_planned_volume_not_the_actual_one(
    program, base, escalated_event
):
    """Closing the release restores the reach and the reservoir to their opening figures.

    PRD 3.7: "Note that the released commitment is the **planned** volume, not the actual one: `actual_release_acre_ft` is recorded for the hydrologic record and does not enter the conservation arithmetic."

    Design: Corner/calculations/completed_orders_leave_the_windowed_capacity_input_set
    """
    order = program.request_drawdown(
        base.dam_id,
        escalated_event["event"]["id"],
        requested_release_cfs=800,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    assert_acre_feet(order["planned_release_acre_ft"], 396.694, "planned_release_acre_ft")
    program.coordinate_drawdown(order["id"], reach_id=base.reach_id)
    program.activate_drawdown(order["id"])
    completed = program.complete_drawdown(order["id"], 402.115)

    assert completed["status"] == DRAWDOWN_COMPLETED
    assert_instant(completed["completed_at"], "2026-08-01T04:00:00Z", "completed_at")
    assert_acre_feet(
        completed["planned_release_acre_ft"], 396.694, "planned_release_acre_ft"
    )
    assert_acre_feet(
        completed["actual_release_acre_ft"], 402.115, "actual_release_acre_ft"
    )

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 0
    assert reach["version"] == 3

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(dam["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft")
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)


def test_the_completed_order_no_longer_competes_for_the_same_window(
    program, base, escalated_event
):
    """An identical replacement release coordinates cleanly over the freed window.

    PRD 3.7: "Orders in `REQUESTED`, `COMPLETED` or `CANCELLED` contribute nothing to that sum, which is exactly what makes a cancellation genuinely free the channel again."

    Design: Corner/calculations/completed_orders_leave_the_windowed_capacity_input_set
    """
    first = program.request_drawdown(
        base.dam_id,
        escalated_event["event"]["id"],
        requested_release_cfs=800,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    program.coordinate_drawdown(first["id"], reach_id=base.reach_id)
    program.activate_drawdown(first["id"])
    program.complete_drawdown(first["id"], 402.115)

    replacement = program.request_drawdown(
        base.dam_id,
        escalated_event["event"]["id"],
        requested_release_cfs=800,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    coordinated = program.coordinate_drawdown(replacement["id"], reach_id=base.reach_id)
    assert coordinated["status"] == DRAWDOWN_COORDINATED
    assert_acre_feet(
        coordinated["planned_release_acre_ft"], 396.694, "planned_release_acre_ft"
    )

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 800.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1
    assert reach["version"] == 4

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 396.694, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1103.306,
        "available_conservation_storage_acre_ft",
    )
