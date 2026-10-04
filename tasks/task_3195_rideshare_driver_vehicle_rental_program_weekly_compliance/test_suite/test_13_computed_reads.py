"""Computed reads and the logical clock's fixed default."""
from test_helpers import (
    COMPLIANCE,
    agreement_summary,
    api_client,
    get_success_data,
    open_week,
    settle_week,
    setup_active_agreement,
    setup_agreement_with_paid_week,
)


def test_the_agreement_summary_agrees_with_its_source_rows(api):
    """PRD §3.2: "The renewal credit is reported to the driver on the agreement
    summary alongside outstanding_balance_cents, outstanding_delinquent_weeks,
    escrow_balance_cents and the agreement's current_week_number and
    agreement_status"

    Design: Corner/endpoints/agreement_summary_reports_aggregated_agreement_fields
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    paid = ctx.weeks[0]
    summary = agreement_summary(ctx.agreement["id"])

    assert summary["outstanding_delinquent_weeks"] == 0
    assert summary["compliance_posture"] == "OPEN"
    assert summary["total_billed_cents"] == paid["amount_due_cents"]
    assert summary["renewal_credit_cents"] == paid["amount_due_cents"]
    assert summary["current_week_number"] == 1
    assert summary["agreement_status"] == "RENEWAL_DUE"


def test_the_summary_equity_credit_matches_the_settled_week(api):
    """PRD §3.9: "Its derived counters begin at zero: current_week_number is 0,
    total_billed_cents is 0 and total_waived_cents is 0."
    PRD §3.9: "The driver's equity share is one tenth of that subtotal, taken with
    integer division so any remainder below a whole cent is discarded."

    Design: Corner/endpoints/agreement_summary_reports_aggregated_agreement_fields
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    paid = ctx.weeks[0]
    summary = agreement_summary(ctx.agreement["id"])

    assert summary["equity_credit_cents"] == paid["amount_due_cents"] // 10
    assert summary["escrow_balance_cents"] == 0
    assert summary["total_waived_cents"] == 0


def test_the_driver_summary_joins_standing_enrolment_and_holding(api):
    """PRD §2.4: "Every top-level resource in this API - Driver, DriverEnrollment,
    ProgramVehicle, RentalAgreement, RentalWeek, MaintenanceEvent, RentalPayment,
    PurchaseOption, PlatformIntegration and FleetFact - carries the same four
    system-managed properties"

    Design: Corner/endpoints/driver_summary_reports_assignment_and_open_week
    """
    ctx = setup_active_agreement(unlimited=True)
    open_week(ctx.agreement["id"])

    summary = get_success_data(api_client.get_driver_summary(ctx.driver["id"], COMPLIANCE))
    assert summary["eligibility_status"] == "ELIGIBLE"
    assert summary["active_enrollment_id"] == ctx.enrollment["id"]
    assert summary["assigned_vehicle_id"] == ctx.vehicle["id"]
    assert summary["open_week_number"] == 1


def test_the_driver_summary_reports_the_open_week_balance(api):
    """PRD §3.5: "Because no mileage has been closed, mileage_overage_cents is 0
    and damage_charge_cents is 0, so amount_due_cents is simply the weekly rate
    plus the premium minus platform_credit_cents."

    Design: Corner/endpoints/driver_summary_reports_assignment_and_open_week
    """
    ctx = setup_active_agreement(unlimited=True)
    opened = open_week(ctx.agreement["id"])

    summary = get_success_data(api_client.get_driver_summary(ctx.driver["id"], COMPLIANCE))
    assert summary["outstanding_balance_cents"] == opened["amount_due_cents"]


def test_an_unset_clock_still_stamps_periods_from_the_fixed_default(api):
    """PRD §2.9: "The server reads a logical clock whose initial value is
    2026-09-01T00:00:00Z, and every timestamp the programme stamps - a weekly
    period boundary, a payment deadline, a verification instant, a loaner deadline
    - is derived from that clock. The server never falls back to the host's real
    time, so a test run is reproducible regardless of when it executes."

    Design: Corner/endpoints/clock_default_is_fixed_when_unset
    """
    ctx = setup_active_agreement(unlimited=True)
    week = open_week(ctx.agreement["id"])

    assert week["period_start"] == "2026-09-01T00:00:00Z"
    assert week["period_end"] == "2026-09-08T00:00:00Z"


def test_the_default_clock_leaves_collection_deadlines_unstamped(api):
    """PRD §3.5: "Settlement also stamps the two collection deadlines.
    payment_deadline is the week's own period_end. grace_deadline is the payment
    deadline plus 72 hours."

    Design: Corner/endpoints/clock_default_is_fixed_when_unset
    """
    ctx = setup_active_agreement(unlimited=True)
    week = open_week(ctx.agreement["id"])

    assert week["payment_deadline"] is None, (
        "the deadlines are stamped at settlement, not at opening"
    )
    assert week["grace_deadline"] is None

    settled = settle_week(week["id"])
    assert settled["payment_deadline"] == "2026-09-08T00:00:00Z"
    assert settled["grace_deadline"] == "2026-09-11T00:00:00Z"