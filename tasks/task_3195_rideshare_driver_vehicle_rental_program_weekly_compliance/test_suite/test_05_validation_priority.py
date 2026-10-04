"""Priority clashes: when two guards both fail, the ordered sequence decides which
error the caller is told about.
"""
from test_helpers import (
    FLEET,
    agreement_version,
    api_client,
    get_agreement,
    get_option,
    get_week,
    lapse_grace,
    open_week,
    settle_week,
    set_clock,
    setup_active_agreement,
    setup_frozen_agreement_with_option,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_frozen_posture_wins_over_the_purchase_delinquency_block(api):
    """PRD §2.7: "A request is evaluated against a fixed, ordered sequence of
    guards, and the first guard that fails determines the error the caller sees."
    PRD §3.9: "Election is additionally blocked whenever any week of the
    agreement has week_status at DELINQUENT, and that attempt is rejected with
    ERR_PURCHASE_BLOCKED_BY_DELINQUENCY (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_purchase_delinquency_block
    """
    ctx = setup_frozen_agreement_with_option()
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "FROZEN"

    response = api_client.elect_purchase_option(
        ctx.option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_AGREEMENT_FROZEN, 409)

    assert error["error_id"] != ApiErrorId.ERR_PURCHASE_BLOCKED_BY_DELINQUENCY
    assert get_option(ctx.option["id"])["option_status"] == "OFFERED"
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "DELINQUENT"


def test_the_posture_gate_is_the_one_reported_on_a_frozen_delinquent_election(api):
    """PRD §2.7: "The freeze gate, guard 8, bars exactly five operations - opening
    a weekly period, settling a week, reporting a maintenance event, issuing a
    loaner, and completing an agreement - and applies to those five and to nothing
    else."
    PRD §2.7: "The openness gate, guard 9, bars exactly two - offering a purchase
    option and electing one."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_purchase_delinquency_block
    """
    ctx = setup_frozen_agreement_with_option()

    first = api_client.elect_purchase_option(
        ctx.option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    assert first.status_code == 409
    assert first.json()["data"]["error_id"] == "ERR_AGREEMENT_FROZEN"

    second = api_client.elect_purchase_option(
        ctx.option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    assert second.status_code == 409
    assert second.json()["data"]["error_id"] == "ERR_AGREEMENT_FROZEN"
    assert get_option(ctx.option["id"])["escrow_weeks_funded"] == 0


def test_frozen_posture_wins_over_the_agreement_term_ceiling(api):
    """PRD §3.4: "the seven-day period that would be opened, running from the
    logical clock instant, must not extend past the agreement's period_end, or the
    request is rejected with ERR_WEEK_OUTSIDE_AGREEMENT_TERM (HTTP 422)."
    PRD §2.7: "a caller who is pointing at a resource that is both frozen and in
    the wrong state should be told about the freeze."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_agreement_term_ceiling
    """
    ctx = setup_active_agreement(
        unlimited=True, period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
    )
    weeks = [open_week(ctx.agreement["id"]) for _ in range(2)]
    for week in weeks:
        settle_week(week["id"])
    set_clock("2026-09-11T00:00:00Z")
    for week in weeks:
        lapse_grace(week["id"])
    set_clock("2026-09-20T00:00:00Z")

    frozen = get_agreement(ctx.agreement["id"])
    assert frozen["compliance_posture"] == "FROZEN"
    assert frozen["current_week_number"] == 2

    response = api_client.open_week(
        {
            "agreement_id": ctx.agreement["id"],
            "expected_agreement_version": agreement_version(ctx.agreement["id"]),
        },
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_FROZEN, 409)

    after = get_agreement(ctx.agreement["id"])
    assert after["compliance_posture"] == "FROZEN"
    assert after["current_week_number"] == 2, "no further period was opened"


def test_the_same_term_ceiling_is_reported_on_an_unfrozen_agreement(api):
    """PRD §3.4: "The agreement must be in ACTIVE or RENEWAL_DUE; it must not be
    FROZEN in posture, or the request is rejected with ERR_AGREEMENT_FROZEN (HTTP
    409); and the seven-day period that would be opened, running from the logical
    clock instant, must not extend past the agreement's period_end, or the request
    is rejected with ERR_WEEK_OUTSIDE_AGREEMENT_TERM (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_agreement_term_ceiling
    """
    ctx = setup_active_agreement(
        unlimited=True, period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
    )
    first = open_week(ctx.agreement["id"])
    set_clock("2026-09-09T00:00:00Z")

    response = api_client.open_week(
        {
            "agreement_id": ctx.agreement["id"],
            "expected_agreement_version": agreement_version(ctx.agreement["id"]),
        },
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_WEEK_OUTSIDE_AGREEMENT_TERM, 422)
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "OPEN"
    assert get_agreement(ctx.agreement["id"])["current_week_number"] == 1
    assert get_week(first["id"])["week_status"] == "OPEN"

def test_a_frozen_agreement_refuses_a_maintenance_report_ahead_of_the_quiet_period(api):
    """PRD §3.7: "The agreement behind the event must not be FROZEN in posture, or
    the request is rejected with ERR_AGREEMENT_FROZEN (HTTP 409). And the unit
    must not still be inside a recovery interval"
    PRD §2.7: "the first guard that fails determines the error the caller sees"

    Design: Corner/validations/maintainer_normal_update_refused_while_frozen
    """
    from test_helpers import create_maintenance_event_payload, vehicle_version

    ctx = setup_frozen_agreement_with_option()
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "FROZEN"

    set_clock("2026-09-25T00:00:00Z")
    response = api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            event_type="UNSCHEDULED_REPAIR", odometer_at_service=40_300,
            downtime_hours=8,
        ),
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_FROZEN, 409)


def test_no_service_event_row_survives_the_frozen_report_refusal(api):
    """PRD §2.7: "Posture freeze. The agreement's compliance_posture must not be
    FROZEN. Failure is ERR_AGREEMENT_FROZEN (HTTP 409)."

    Design: Corner/validations/maintainer_normal_update_refused_while_frozen
    """
    from test_helpers import count_maintenance_events, create_maintenance_event_payload, vehicle_version

    ctx = setup_frozen_agreement_with_option()
    set_clock("2026-09-25T00:00:00Z")
    api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            event_type="UNSCHEDULED_REPAIR", odometer_at_service=40_300,
            downtime_hours=8,
        ),
        FLEET,
    )
    assert count_maintenance_events(agreement_id=ctx.agreement["id"]) == 0
