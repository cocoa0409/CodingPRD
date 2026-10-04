"""Difficulty queue — transitive cascades (PRD §2.5, §3.2, §3.8).

Depth-3 cascades: appeal decision -> JD reversal -> application suspension
-> credit release; and clock advance -> report overdue -> permit suspension
-> auto-opened enforcement case.
"""
import pytest

from test_helpers import (
    AppealOutcome,
    ApplicationStatus,
    CaseSource,
    CaseStatus,
    CreditTxnStatus,
    FIRST_PERMIT_NUMBER,
    JdStatus,
    PermitStatus,
    ReportStatus,
    assert_bank_inventory_conserved,
    assert_iso_instants_equal,
    decide_appeal,
    file_appeal,
    get_cases_for_applicant,
    iso_add_days,
    reserve_credits,
    set_clock,
    setup_aa_accepted,
    setup_active_permit,
    setup_operational_bank,
    setup_plan_approved,
    validate_success,
)


def test_appeal_sustain_cascades_jd_application_credits(api, reviewer_headers):
    """PRD §3.2: "A decision of `SUSTAINED` is far more consequential: the
    appeal moves `FILED` to `SUSTAINED`, and the referenced determination
    reverses from `ISSUED` to `REVERSED`, firing the suspension cascade."
    PRD §3.2: "Every permit application that references the reversed
    determination and sits in `SUBMITTED`, `SCREENING`,
    `RETURNED_TO_APPLICANT`, `ALTERNATIVES_REVIEW`, `PUBLIC_NOTICE_OPEN`, or
    `DECISION_PENDING` transitions to `SUSPENDED_PENDING_JD`; and for each
    such application, every credit transaction of the application's
    mitigation plans still in `RESERVED` transitions to `RELEASED`,
    restoring the bank's inventory."

    Three caused links from one POST /appeals/{id}/decide: appeal SUSTAINED,
    JD REVERSED, application SUSPENDED_PENDING_JD, reservation RELEASED with
    the bank's availability fully restored.

    Design: Difficulty/transitive_cascade/appeal_sustain_cascades_jd_application_credits
    """
    ctx = setup_aa_accepted()
    applicant, jd, app = ctx["applicant"], ctx["jd"], ctx["app"]
    plan = setup_plan_approved(app, applicant)
    bank = setup_operational_bank()
    txn = reserve_credits(bank, plan, applicant, credits=7.0)
    assert txn["status"] == CreditTxnStatus.RESERVED.value

    appeal = file_appeal(jd, applicant,
                         "Delineation omitted an intermittent channel")
    decided = decide_appeal(appeal, AppealOutcome.SUSTAINED.value,
                            "Delineation error confirmed on remand")
    assert decided["status"] == "SUSTAINED"

    jd_after = validate_success(api.get_jd(jd["id"], reviewer_headers))
    assert jd_after["status"] == JdStatus.REVERSED.value, (
        "link 1: the appeal decision mutated the determination"
    )

    app_after = validate_success(api.get_application(app["id"], reviewer_headers))
    assert app_after["status"] == ApplicationStatus.SUSPENDED_PENDING_JD.value, (
        "link 2: the JD reversal suspended the application"
    )

    txn_after = validate_success(api.get_credit_transaction(txn["id"], reviewer_headers))
    assert txn_after["status"] == CreditTxnStatus.RELEASED.value, (
        "link 3: the application suspension released the reservation"
    )

    bank_after = validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))
    assert bank_after["available_credits_by_type"]["FORESTED_WETLAND"] == pytest.approx(
        20.0, abs=1e-6
    ), "the bank's inventory is fully restored"
    assert_bank_inventory_conserved(bank_after)


def test_monitoring_breach_cascades_permit_suspension_and_case(api, reviewer_headers):
    """PRD §2.5: "Breach escalation: any report in `OVERDUE` whose `due_date`
    is more than 60 days in the past (new clock strictly greater than
    `due_date` plus 60 days) on a permit still `ACTIVE` suspends that permit
    (`ACTIVE` to `SUSPENDED`) and auto-creates an enforcement case of
    `case_source` `MONITORING_BREACH`."
    PRD §3.8: "the system auto-opens an enforcement case with `case_source`
    `MONITORING_BREACH`, pulling `site_id` and `responsible_applicant_id`
    from the permit's application, recording `unauthorized_fill_acres` as 0 —
    the one situation in which zero fill acres appear on a case — and
    `opened_by_officer_id` as `SYSTEM`, opening in `OPENED`."

    Clock advance to report-1 due_date + 61 days: report flips OVERDUE, the
    ACTIVE permit suspends, and the suspension opens the breach referral.

    Design: Difficulty/transitive_cascade/monitoring_breach_cascades_permit_suspension_and_case
    """
    ctx = setup_active_permit()
    app, permit, reports = ctx["app"], ctx["permit"], ctx["reports"]
    assert app["status"] == ApplicationStatus.ISSUED.value
    assert permit["permit_number"] == FIRST_PERMIT_NUMBER
    assert permit["status"] == PermitStatus.ACTIVE.value

    rep1 = reports[0]
    assert rep1["period_index"] == 1
    assert_iso_instants_equal(
        rep1["due_date"], iso_add_days(permit["issue_date"], 365),
        label="report 1 due_date = issue_date + 365 days",
    )

    # Strictly greater than due_date + 60 days (PRD §2.5 step 4).
    set_clock(iso_add_days(rep1["due_date"], 61))

    rep1_after = validate_success(api.get_monitoring_report(rep1["id"], reviewer_headers))
    assert rep1_after["status"] == ReportStatus.OVERDUE.value, (
        "link 1: the clock move mutated the report"
    )

    permit_after = validate_success(api.get_permit(permit["id"], reviewer_headers))
    assert permit_after["status"] == PermitStatus.SUSPENDED.value, (
        "link 2: the overdue report suspended the permit"
    )

    cases = get_cases_for_applicant(ctx["applicant"])
    breach = [c for c in cases if c["case_source"] == CaseSource.MONITORING_BREACH.value]
    assert len(breach) == 1, f"expected exactly one MONITORING_BREACH case, got {len(breach)}"
    case = breach[0]
    assert case["case_status"] == CaseStatus.OPENED.value, (
        "link 3: the suspension itself opened the referral case"
    )
    assert case["unauthorized_fill_acres"] == 0
    assert case["opened_by_officer_id"] == "SYSTEM"
    assert case["site_id"] == ctx["site"]["id"]
    assert case["responsible_applicant_id"] == ctx["applicant"]["id"]
