"""Endpoint contracts: the parent-backup route and the two operational controls.

Three endpoints answer for themselves here. `POST /pdn/shifts/{id}/parent-backup`
(PRD 3.6) drives a shift onto its terminal `PARENT_BACKUP` staffing state and
feeds the fill metrics of PRD 3.4 without consuming any of the authorized hours
of PRD 3.3. `POST /pdn/_ops/run-daily-checkpoint` (PRD 3.9) reports its four
sweep counts and runs the authorization-expiry cascade. `POST
/pdn/_clock/set_current_utc` (PRD 2.5) moves the logical clock and nothing else.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import canonicalize_instant
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import (
    assert_hours,
    assert_ratio,
    assert_shift_axes,
    assert_version_is,
)
from test_helpers.test_users import AGENCY_ADMIN, SCHEDULER
from test_helpers.types import (
    AuthorizationStatus,
    CaseStatus,
    EscalationTier,
    EvvStatus,
    HoldReason,
    ShiftCancelReason,
    StaffingStatus,
)

#: A Thursday shift of ISO week 32 of 2026, inside the canonical grant window.
SHIFT_START = "2026-08-06T08:00:00Z"
SHIFT_END = "2026-08-06T16:00:00Z"

#: A grant that ends with the week window itself, so a later clock outruns it.
WEEK32_AUTH_END = "2026-08-10T00:00:00Z"
WEEK32_PLAN_END = "2026-08-10"
#: Tuesday of the following week - past both the grant end and the shift start.
CLOCK_AFTER_GRANT = "2026-08-11T06:00:00Z"
#: A clock jump that lands far outside the grant window.
CLOCK_FAR_FUTURE = "2026-08-20T09:30:00Z"


def _escalated_shift(api):
    """An ACTIVE case for a family with `parent_backup_available` true and one
    future OPEN shift, already escalated to TIER1_AGENCY_POOL."""
    base = fx.setup_baseline(api, with_nurse=False)
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    escalated = validate_success(
        api.escalate_shift(
            shift["id"],
            f.escalate_payload("no vent-qualified nurse available for Thursday"),
            SCHEDULER,
        )
    )
    return base, escalated


def test_parent_backup_moves_the_escalated_shift_onto_its_terminal_state(api):
    """PRD 3.6: with the patient's `parent_backup_available` true, the tier-two
    move requires `staffing_status` exactly `ESCALATED` and takes the shift
    `ESCALATED -> PARENT_BACKUP` with `escalation_tier` `TIER2_PARENT_BACKUP`,
    incrementing the shift's `version`. Publication minted version 1 (PRD 2.4)
    and the first escalation made it 2, so the arrangement lands on 3. The
    verification axis of PRD 3.5 is not touched: `evv_status` stays
    `NOT_STARTED`.

    Design: Corner/endpoints/parent_backup_fills_the_shift_without_consuming_authorized_hours
    """
    _base, escalated = _escalated_shift(api)
    assert escalated["escalation_tier"] == EscalationTier.TIER1_AGENCY_POOL.value, escalated
    assert_version_is(escalated, 2)

    arranged = validate_success(
        api.parent_backup_shift(
            escalated["id"],
            SCHEDULER,
            f.parent_backup_payload("trained mother covering the 08:00-16:00 block"),
        )
    )

    assert_shift_axes(
        arranged, StaffingStatus.PARENT_BACKUP.value, EvvStatus.NOT_STARTED.value
    )
    assert arranged["escalation_tier"] == EscalationTier.TIER2_PARENT_BACKUP.value, arranged
    assert_version_is(arranged, 3)


def test_a_parent_covered_shift_counts_as_filled_yet_consumes_no_hours(api):
    """PRD 3.6 states a parent-covered shift consumes no authorized hours while
    still counting as covered for `fill_rate` and dropping out of
    `unfilled_shift_count`. While the shift is `ESCALATED` the PRD 3.4 window
    holds one shift in the denominator and none in the numerator, so `fill_rate`
    is 0.0000 with `unfilled_shift_count` 1; the arrangement flips those to
    1.0000 and 0. The 480 scheduled minutes never enter the committed sum of PRD
    2.12, so `hours_committed_this_week` stays 0.00 against the 40-hour grant
    and `hours_remaining_this_week` stays 40.00.

    Design: Corner/endpoints/parent_backup_fills_the_shift_without_consuming_authorized_hours
    """
    base, escalated = _escalated_shift(api)

    before = fx.refresh_case(api, base.case_id)
    assert_ratio(before, "fill_rate", 0.0000)
    assert before["unfilled_shift_count"] == 1, before

    validate_success(
        api.parent_backup_shift(
            escalated["id"],
            SCHEDULER,
            f.parent_backup_payload("trained mother covering the 08:00-16:00 block"),
        )
    )

    after = fx.refresh_case(api, base.case_id)
    assert_ratio(after, "fill_rate", 1.0000)
    assert after["unfilled_shift_count"] == 0, after

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 0.00)
    assert_hours(authorization, "hours_remaining_this_week", 40.00)


def test_escalating_a_parent_covered_shift_is_refused_as_an_invalid_state(api):
    """PRD 3.6 permits escalation only while `staffing_status` is `OPEN` or
    `ESCALATED`, and declares `PARENT_BACKUP` terminal on the staffing axis, so
    the follow-up escalate fails the transition-state check of PRD 2.8 priority
    9 with `ERR_INVALID_STATE` (409) and rewrites nothing: the shift keeps
    `TIER2_PARENT_BACKUP` and the version the arrangement left it on.

    Design: Corner/endpoints/parent_backup_fills_the_shift_without_consuming_authorized_hours
    """
    _base, escalated = _escalated_shift(api)
    arranged = validate_success(
        api.parent_backup_shift(
            escalated["id"],
            SCHEDULER,
            f.parent_backup_payload("trained mother covering the 08:00-16:00 block"),
        )
    )

    response = api.escalate_shift(
        arranged["id"],
        f.escalate_payload("trying to escalate a shift the family already absorbed"),
        SCHEDULER,
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    reread = fx.refresh_shift(api, arranged["id"])
    assert_shift_axes(
        reread, StaffingStatus.PARENT_BACKUP.value, EvvStatus.NOT_STARTED.value
    )
    assert reread["escalation_tier"] == EscalationTier.TIER2_PARENT_BACKUP.value, reread
    assert_version_is(reread, 3)


def _grant_expiring_before_the_clock(api):
    """A 40 h/wk grant effective 2026-08-03 .. 2026-08-10 with an ACTIVE case and
    one ASSIGNED Thursday shift, seen from Tuesday of the following week."""
    base = fx.setup_baseline(
        api,
        plan_overrides={"end_date": WEEK32_PLAN_END},
        authorization_overrides={"effective_end": WEEK32_AUTH_END},
    )
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    fx.set_clock(api, CLOCK_AFTER_GRANT)
    return base, shift, assignment


def test_the_daily_checkpoint_reports_one_expired_grant_and_no_other_sweep(api):
    """PRD 3.9: the checkpoint reports exactly four counts. The authorization is
    `ACTIVE` with `effective_end` 2026-08-10T00:00:00Z, at or before the clock,
    so `expired_authorization_count` is 1 and its `status` becomes `EXPIRED`.
    The two competencies expire on 2027-07-01, so `expired_competency_count` is
    0. The vent cadence of PRD 3.4 is 14 days from the case's `created_at`
    2026-08-03T06:00:00Z, making the visit due 2026-08-17T06:00:00Z - still
    ahead of the clock - so `overdue_case_count` is 0. The only shift is
    `ASSIGNED`, never `OPEN` or `ESCALATED`, so `cancelled_shift_count` is 0.

    Design: Corner/endpoints/daily_checkpoint_reports_each_sweep_count_and_expires_the_grant
    """
    base, _shift, _assignment = _grant_expiring_before_the_clock(api)

    counts = validate_success(api.run_daily_checkpoint(AGENCY_ADMIN))

    assert counts["expired_authorization_count"] == 1, counts
    assert counts["expired_competency_count"] == 0, counts
    assert counts["overdue_case_count"] == 0, counts
    assert counts["cancelled_shift_count"] == 0, counts

    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.EXPIRED.value, authorization


def test_the_expiry_cascade_holds_the_case_and_spares_the_past_shift(api):
    """PRD 3.9's expiry cascade runs its hops in order: the authorization
    becomes `EXPIRED`, then every case pointing at it whose `status` is
    `PENDING_STAFFING` or `ACTIVE` becomes `ON_HOLD` with `hold_reason`
    `AUTHORIZATION_EXPIRED`. Because the hold was not placed from an incident
    report, `hold_incident_report_id` is null (PRD 2.11). The cancellation hop
    reaches only shifts whose `start_at` is at or after the current clock (PRD
    2.10), and 2026-08-06 lies behind it, so the shift keeps
    `staffing_status` `ASSIGNED` and `cancel_reason` `NONE`.

    Design: Corner/endpoints/daily_checkpoint_reports_each_sweep_count_and_expires_the_grant
    """
    base, shift, _assignment = _grant_expiring_before_the_clock(api)

    validate_success(api.run_daily_checkpoint(AGENCY_ADMIN))

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ON_HOLD.value, case
    assert case["hold_reason"] == HoldReason.AUTHORIZATION_EXPIRED.value, case
    assert case["hold_incident_report_id"] is None, case

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.ASSIGNED.value, EvvStatus.NOT_STARTED.value)
    assert reread["cancel_reason"] == ShiftCancelReason.NONE.value, reread


def test_a_second_checkpoint_reports_every_count_as_zero(api):
    """PRD 3.9 defines the checkpoint as advancing every clock-driven derivation
    to the current clock, so once it has caught up there is nothing left to
    sweep: the authorization is already `EXPIRED` and therefore outside the
    `ACTIVE`/`REDUCTION_NOTICED`/`REDUCED` set that expiry considers, no
    competency has lapsed, no case is due a visit and no shift is `OPEN` or
    `ESCALATED`. Every one of the four counts is 0 on the second call.

    Design: Corner/endpoints/daily_checkpoint_reports_each_sweep_count_and_expires_the_grant
    """
    _base, _shift, _assignment = _grant_expiring_before_the_clock(api)

    first = validate_success(api.run_daily_checkpoint(AGENCY_ADMIN))
    assert first["expired_authorization_count"] == 1, first

    second = validate_success(api.run_daily_checkpoint(AGENCY_ADMIN))
    assert second["expired_authorization_count"] == 0, second
    assert second["expired_competency_count"] == 0, second
    assert second["overdue_case_count"] == 0, second
    assert second["cancelled_shift_count"] == 0, second


def _activated_grant_only(api):
    """One ACTIVE 40 h/wk grant effective 2026-08-03 .. 2026-08-10, with no
    nurse, no case and no shift, so every derived figure on it is 0.00."""
    return fx.setup_baseline(
        api,
        plan_overrides={"end_date": WEEK32_PLAN_END},
        authorization_overrides={"effective_end": WEEK32_AUTH_END},
        with_nurse=False,
        with_case=False,
    )


def test_the_clock_endpoint_answers_with_the_instant_it_was_handed(api):
    """PRD 2.5: an `AgencyAdmin` may reposition the logical clock to any instant
    by supplying `to_iso8601`, and the response reports the new value as
    `current_utc`. The jump to 2026-08-20T09:30:00Z is therefore echoed back
    verbatim.

    Design: Corner/endpoints/the_logical_clock_endpoint_moves_time_and_nothing_else
    """
    _activated_grant_only(api)

    moved = validate_success(
        api.set_clock(f.clock_payload(CLOCK_FAR_FUTURE), AGENCY_ADMIN)
    )

    assert moved["current_utc"] == canonicalize_instant(CLOCK_FAR_FUTURE), moved


def test_moving_the_clock_past_the_grant_end_mutates_no_business_entity(api):
    """PRD 2.5: repositioning the clock mutates no business entity - only the
    clock moves - and PRD 3.9 gives expiry to the daily checkpoint alone. So a
    jump to 2026-08-20T09:30:00Z, well past the authorization's `effective_end`
    of 2026-08-10T00:00:00Z, leaves the authorization read byte-identical: the
    same `status` `ACTIVE`, the same `version` and the same `updated_at`, with no
    mutation to refresh either of the last two (PRD 2.4).

    Design: Corner/endpoints/the_logical_clock_endpoint_moves_time_and_nothing_else
    """
    base = _activated_grant_only(api)
    before = fx.refresh_authorization(api, base)
    assert before["status"] == AuthorizationStatus.ACTIVE.value, before

    validate_success(api.set_clock(f.clock_payload(CLOCK_FAR_FUTURE), AGENCY_ADMIN))

    after = fx.refresh_authorization(api, base)
    assert after["status"] == AuthorizationStatus.ACTIVE.value, after
    assert_version_is(after, before["version"])
    assert after["updated_at"] == before["updated_at"], after
    assert after == before, after
