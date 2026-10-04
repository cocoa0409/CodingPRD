"""The two escalating delinquency thresholds that sit on one overdue invoice.

Fourteen days past due blocks new offers while the partner stays ACTIVE; thirty
days is what suspends it outright (PRD §2.10, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    acceptance_payload,
    advance_student_to_internship,
    create_cohort,
    create_enrolled_student,
    invoice_payload,
    make_student_headers,
    placement_payload,
    read_partner,
    record_interview_outcome,
    schedule_interview_for,
    set_clock,
    setup_two_matched_placements,
    staff_headers,
    validate_error,
    validate_success,
)

FOURTEEN_DAYS_PAST_DUE = "2026-11-03T00:00:00Z"
FIFTEEN_DAYS_PAST_DUE = "2026-11-04T00:00:00Z"


def test_offer_is_blocked_once_the_invoice_is_past_due_by_more_than_fourteen_days(api):
    """PRD §3.4: "the partner must not carry an invoice at status `OVERDUE` whose
    `due_date` is strictly more than 14 days before the logical-clock date
    (`ERR_PARTNER_PAST_DUE`, 402)"
    PRD §2.10: "The partner's `status` is driven to `SUSPENDED` when the partner
    carries an invoice at status `OVERDUE` whose `due_date` is strictly more than 30
    days before the logical-clock date"
    PRD §2.10: "The `credit_hold` flag is true exactly when the partner carries an
    invoice at status `OVERDUE` whose `due_date` is strictly before the logical-clock
    date"

    The offer is still allowed at exactly fourteen days and refused at fifteen,
    while the partner is on credit hold but not yet suspended.

    Design: Corner/validations/partner_past_due_and_suspension_thresholds
    """
    scenario = setup_two_matched_placements(agreement_overrides={"slot_count": 3})
    # Cara needs a cohort of her own: each of the two matched students completed
    # their cohort on reaching INTERNSHIP (PRD §3.2), which closes it to further
    # enrollment. Cohort membership is not part of the rule under test.
    third = create_enrolled_student(
        create_cohort()["id"],
        full_name="Cara Nguyen", email="cara.nguyen@example.com",
        date_of_birth="2003-08-08", education_status="ASSOCIATE",
        household_income_cents=1_600_000,
    )
    advance_student_to_internship(third["id"])
    placement_three = validate_success(
        api.create_placement(
            placement_payload(scenario.agreement["id"], third["id"]), staff_headers()
        ),
        201,
    )

    # The first placement is accepted and running, which is what raises the invoice.
    first_round = schedule_interview_for(scenario.placement["id"])
    record_interview_outcome(first_round["id"], scenario.partner["id"], outcome="PASSED")
    validate_success(api.extend_offer(scenario.placement["id"], staff_headers()), 200)
    set_clock("2026-10-06T00:00:00Z")
    validate_success(
        api.accept_offer(
            scenario.placement["id"], acceptance_payload(),
            make_student_headers(scenario.student["id"]),
        ),
        200,
    )
    partner_now = read_partner(scenario.partner["id"])
    validate_success(
        api.issue_invoice(
            invoice_payload(
                partner_now["id"], scenario.placement["id"], partner_now["version"],
                due_date="2026-10-20",
            ),
            staff_headers(),
        ),
        201,
    )

    # Two more placements are interviewed and waiting for their offers.
    second_round = schedule_interview_for(
        scenario.placement_two["id"], scheduled_for="2026-09-21T15:00:00Z"
    )
    record_interview_outcome(second_round["id"], scenario.partner["id"], outcome="PASSED")
    third_round = schedule_interview_for(
        placement_three["id"], scheduled_for="2026-09-22T15:00:00Z"
    )
    record_interview_outcome(third_round["id"], scenario.partner["id"], outcome="PASSED")

    set_clock(FOURTEEN_DAYS_PAST_DUE)
    partner_at_fourteen = read_partner(scenario.partner["id"])
    assert partner_at_fourteen["credit_hold"] is True, partner_at_fourteen["credit_hold"]
    assert partner_at_fourteen["status"] == "ACTIVE", partner_at_fourteen["status"]

    offer = validate_success(
        api.extend_offer(scenario.placement_two["id"], staff_headers()), 200
    )
    assert offer["placement_fee_cents"] == 296572, offer["placement_fee_cents"]
    assert offer["state"] == "OFFERED", offer["state"]

    set_clock(FIFTEEN_DAYS_PAST_DUE)
    response = api.extend_offer(placement_three["id"], staff_headers())

    validate_error(response, ApiErrorId.ERR_PARTNER_PAST_DUE, expected_status=402)
