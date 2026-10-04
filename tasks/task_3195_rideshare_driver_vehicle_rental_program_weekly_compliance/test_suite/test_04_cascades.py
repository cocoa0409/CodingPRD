"""Transitive cascades: one declaration or election fanning out across weeks,
posture, driver and enrolment without a second request.
"""
from test_helpers import (
    ADMIN,
    SUPPORT,
    agreement_version,
    api_client,
    create_purchase_option_payload,
    get_agreement,
    get_driver,
    get_enrollment,
    get_success_data,
    get_vehicle,
    get_week,
    open_week,
    setup_agreement_with_paid_week,
    setup_with_delinquent_weeks,
)


def test_one_grace_lapse_carries_posture_driver_and_enrolment(api):
    """PRD §3.8: "Declaring the week delinquent bumps the count, and when that
    bump takes the count to 2 compliance_posture reaches FROZEN, which fans out
    in three directions at once: agreement_status is set to DELINQUENT; the
    driver's eligibility_status is moved from ELIGIBLE to SUSPENDED; and the
    unit's vehicle_status is moved from ASSIGNED to RECOVERY. The driver's
    suspension then triggers the enrolment's own enrollment_status transition
    from ACTIVE to SUSPENDED, which is the final hop of the cascade."

    Design: Difficulty/transitive_cascade/grace_lapse_cascade_reaches_driver_enrollment
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)

    for week in ctx.weeks:
        assert week["week_status"] == "DELINQUENT"

    agreement = get_agreement(ctx.agreement["id"])
    assert agreement["compliance_posture"] == "FROZEN"
    assert agreement["agreement_status"] == "DELINQUENT"

    assert get_driver(ctx.driver["id"])["eligibility_status"] == "SUSPENDED"
    assert get_enrollment(ctx.enrollment["id"])["enrollment_status"] == "SUSPENDED"
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "RECOVERY"


def test_the_unit_leaves_the_road_as_a_direct_co_effect_of_the_freeze(api):
    """PRD §3.8: "The unit's move to RECOVERY is a direct co-effect of the
    posture change rather than a chained hop - it does not wait on anything
    downstream."
    PRD §3.8: "A count of 0 yields OPEN; a count of exactly 1 yields RESTRICTED;
    a count of 2 or more yields FROZEN."

    Design: Difficulty/transitive_cascade/grace_lapse_cascade_reaches_driver_enrollment
    """
    single = setup_with_delinquent_weeks(count=1, unlimited=True)
    assert get_agreement(single.agreement["id"])["compliance_posture"] == "RESTRICTED"
    assert get_vehicle(single.vehicle["id"])["vehicle_status"] == "ASSIGNED", (
        "one delinquent week restricts the agreement but does not move the unit"
    )
    assert get_driver(single.driver["id"])["eligibility_status"] == "ELIGIBLE"
    assert get_enrollment(single.enrollment["id"])["enrollment_status"] == "ACTIVE"


def test_paying_one_of_two_delinquent_weeks_drops_the_freeze_to_restricted(api):
    """PRD §3.8: "Paying one delinquent week of two therefore drops a frozen
    agreement back to RESTRICTED and restores the driver to ELIGIBLE standing,
    and paying the second drops it back to OPEN."

    Design: Difficulty/transitive_cascade/grace_lapse_cascade_reaches_driver_enrollment
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)

    first = get_week(ctx.weeks[0]["id"])
    get_success_data(api_client.tender_payment(
        first["id"],
        {"amount_cents": first["amount_due_cents"], "payment_outcome": "SUCCEEDED"},
        SUPPORT,
    ), expected_status=201)

    agreement = get_agreement(ctx.agreement["id"])
    assert agreement["compliance_posture"] == "RESTRICTED"
    assert get_driver(ctx.driver["id"])["eligibility_status"] == "ELIGIBLE"
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "ASSIGNED"

    second = get_week(ctx.weeks[1]["id"])
    get_success_data(api_client.tender_payment(
        second["id"],
        {"amount_cents": second["amount_due_cents"], "payment_outcome": "SUCCEEDED"},
        SUPPORT,
    ), expected_status=201)

    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "OPEN"


def test_purchase_election_defers_the_open_week(api):
    """PRD §3.9: "On success option_status moves from OFFERED to ELECTED with
    elected_at stamped, agreement_status moves from ACTIVE to PURCHASE_PENDING,
    and every week of the agreement still at OPEN is moved to DEFERRED, at which
    point the maintenance of the deferred week is charged at escrow rates rather
    than at ordinary rental rates."

    Design: Difficulty/transitive_cascade/purchase_election_cascade_reaches_deferred_week
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    second = open_week(ctx.agreement["id"])
    assert second["week_status"] == "OPEN"

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(ctx.agreement["id"], ctx.driver["id"]),
        ADMIN,
    ), expected_status=201)

    elected = get_success_data(api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    ))

    assert elected["option_status"] == "ELECTED", "hop 1"
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "PURCHASE_PENDING", "hop 2"
    assert get_week(second["id"])["week_status"] == "DEFERRED", "hop 3"
    assert get_week(ctx.weeks[0]["id"])["week_status"] == "PAID", (
        "the already-paid week is untouched by the cascade"
    )


def test_a_paid_week_is_not_deferred_by_the_election_cascade(api):
    """PRD §3.9: "Election requires option_status to be OFFERED, the agreement's
    compliance_posture to be exactly OPEN (otherwise ERR_POSTURE_NOT_OPEN, HTTP
    409), the agreement's delinquent count to be 0, and
    PurchaseOption.agreement_id to actually name that agreement."

    Design: Difficulty/transitive_cascade/purchase_election_cascade_reaches_deferred_week
    """
    ctx = setup_agreement_with_paid_week(weeks=2, unlimited=True)
    third = open_week(ctx.agreement["id"])

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(ctx.agreement["id"], ctx.driver["id"]),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )

    for paid in ctx.weeks:
        assert get_week(paid["id"])["week_status"] == "PAID"
    assert get_week(third["id"])["week_status"] == "DEFERRED"


def test_withdrawing_the_option_reverses_the_deferral(api):
    """PRD §3.9: "Withdrawal reverses everything the election did: the deferred
    week returns to OPEN with fresh deadlines - payment_deadline seven days from
    the logical clock instant and grace_deadline 72 hours after that - and
    agreement_status returns from PURCHASE_PENDING to ACTIVE."

    Design: Difficulty/transitive_cascade/purchase_election_cascade_reaches_deferred_week
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    second = open_week(ctx.agreement["id"])

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(ctx.agreement["id"], ctx.driver["id"]),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    assert get_week(second["id"])["week_status"] == "DEFERRED"

    withdrawn = get_success_data(api_client.withdraw_purchase_option(
        option["id"], ctx.driver_headers
    ))
    assert withdrawn["option_status"] == "WITHDRAWN"

    reopened = get_week(second["id"])
    assert reopened["week_status"] == "OPEN"
    assert reopened["payment_deadline"] == "2026-09-08T00:00:00Z"
    assert reopened["grace_deadline"] == "2026-09-11T00:00:00Z"
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "ACTIVE"