"""Declared lifecycles: initial states, legal hops, refusals and cascades.

The plan of care, the authorization and the case each start where PRD 3.3 and
PRD 3.4 say they start, and they may only move along the hops those sections
declare. Everything else - a replayed submit, an activation of an already
`ACTIVE` grant, any transition on a `CLOSED` case - is caught by check 9 of the
PRD 2.8 order as `ERR_INVALID_STATE`. The remaining tests follow the side effects
that ride along with a legal hop: the manual hold cascade of PRD 3.4, the
in-flight-timesheet precondition on closing a case, the revision loop of PRD 3.3
and the conditional incident cascade of PRD 3.8.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import assert_ratio, assert_units
from test_helpers.test_users import (
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    CLINICAL_SUPERVISOR_2,
    SCHEDULER,
    SUPERVISOR_USER_ID,
    make_payer_reviewer_headers,
)
from test_helpers.types import (
    AssignmentCancelReason,
    AssignmentStatus,
    AuthorizationStatus,
    CaseStatus,
    HoldReason,
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    PatientStatus,
    PlanOfCareStatus,
    ShiftCancelReason,
    StaffingStatus,
    TimesheetStatus,
    UtilizationBasis,
)

SHIFT_A_START = "2026-08-05T08:00:00Z"
SHIFT_A_END = "2026-08-05T16:00:00Z"
SHIFT_B_START = "2026-08-06T08:00:00Z"
SHIFT_B_END = "2026-08-06T16:00:00Z"
SHIFT_C_START = "2026-08-03T05:00:00Z"
SHIFT_C_END = "2026-08-03T13:00:00Z"
WEEK32_WEDNESDAY = "2026-08-05T00:00:00Z"
CLOCK_IN_AT = "2026-08-05T07:50:00Z"
CLOCK_OUT_AT = "2026-08-05T16:00:00Z"
INCIDENT_LOW_AT = "2026-08-03T05:30:00Z"
INCIDENT_HIGH_AT = "2026-08-03T05:45:00Z"


def _payer_and_patient(api):
    """The clock parked in ISO week 32 of 2026, one payer and one enrolled child."""
    fx.set_clock(api)
    payer = fx.create_payer(api)
    patient = fx.create_patient(api, payer["id"])
    return payer, patient


def test_a_fresh_plan_of_care_and_authorization_start_in_draft_and_pending(api):
    """PRD 3.3 creates a plan of care in `DRAFT` with `revision_round` at 0, and
    creates an authorization in `PENDING` with `renewal_chain_depth` 0 and a null
    `supersedes_authorization_id` for the first grant of a plan. Neither creation
    call may short-circuit into a live state.

    Design: Corner/state_machines/freshly_created_rows_start_in_their_declared_initial_states
    """
    payer, patient = _payer_and_patient(api)

    plan = validate_success(
        api.create_plan_of_care(f.plan_of_care_payload(patient["id"]), CASE_MANAGER), 201
    )
    assert plan["status"] == PlanOfCareStatus.DRAFT.value, plan
    assert plan["revision_round"] == 0, plan
    assert plan["version"] == 1, plan

    submitted = fx.submit_plan_of_care(api, plan["id"])
    authorization = validate_success(
        api.create_authorization(
            f.authorization_payload(plan["id"], payer["id"], submitted["version"]),
            make_payer_reviewer_headers(payer["id"]),
        ),
        201,
    )

    assert authorization["status"] == AuthorizationStatus.PENDING.value, authorization
    assert authorization["renewal_chain_depth"] == 0, authorization
    assert authorization["supersedes_authorization_id"] is None, authorization
    assert authorization["version"] == 1, authorization


def test_a_fresh_case_starts_in_pending_staffing_with_its_counters_at_zero(api):
    """PRD 3.4 creates a case in `PENDING_STAFFING`; PRD 3.4 also says `hold_reason`
    reads null on any case that is not `ON_HOLD`, and a manual hold is what sets
    `hold_incident_report_id`, so both are null at birth. The two counters the case
    carries - `unfilled_shift_count` over its shifts and `billed_units_to_date`
    over its accepted timesheets - start at 0 because it has neither.

    Design: Corner/state_machines/freshly_created_rows_start_in_their_declared_initial_states
    """
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)

    case = validate_success(
        api.create_case(
            f.case_payload(base.patient_id, base.authorization_id, SUPERVISOR_USER_ID),
            CASE_MANAGER,
        ),
        201,
    )

    assert case["status"] == CaseStatus.PENDING_STAFFING.value, case
    assert case["hold_reason"] is None, case
    assert case["hold_incident_report_id"] is None, case
    assert case["unfilled_shift_count"] == 0, case
    assert_units(case, "billed_units_to_date", 0)
    assert case["version"] == 1, case


def test_plan_of_care_walks_draft_submitted_under_review_authorized(api):
    """Three writes carry the plan to its terminal state and each increments its
    `version`: submission moves `DRAFT -> SUBMITTED` (PRD 3.3), issuing the
    authorization moves `SUBMITTED -> UNDER_REVIEW`, and activating that
    authorization moves `UNDER_REVIEW -> AUTHORIZED`. The plan therefore lands on
    version 4 with `revision_round` still 0, having been moved twice by endpoints
    that are not its own.

    Design: Corner/state_machines/plan_of_care_walks_draft_submitted_under_review_authorized
    """
    payer, patient = _payer_and_patient(api)
    payer_headers = make_payer_reviewer_headers(payer["id"])
    plan = fx.create_plan_of_care(api, patient["id"])

    submitted = validate_success(api.submit_plan_of_care(plan["id"], CASE_MANAGER))
    assert submitted["status"] == PlanOfCareStatus.SUBMITTED.value, submitted
    assert submitted["version"] == 2, submitted

    authorization = validate_success(
        api.create_authorization(
            f.authorization_payload(plan["id"], payer["id"], submitted["version"]),
            payer_headers,
        ),
        201,
    )
    assert authorization["status"] == AuthorizationStatus.PENDING.value, authorization

    activated = validate_success(
        api.activate_authorization(authorization["id"], payer_headers)
    )
    assert activated["status"] == AuthorizationStatus.ACTIVE.value, activated

    final = validate_success(api.get_plan_of_care(plan["id"], CASE_MANAGER))
    assert final["status"] == PlanOfCareStatus.AUTHORIZED.value, final
    assert final["version"] == 4, final
    assert final["revision_round"] == 0, final


def test_issuing_the_authorization_moves_the_plan_into_under_review(api):
    """PRD 3.3 makes the intermediate hop explicit: issuing the authorization is
    only possible while the plan sits in `SUBMITTED`, and it moves the plan
    `SUBMITTED -> UNDER_REVIEW` while incrementing its `version`. Before any
    activation the plan must therefore read `UNDER_REVIEW` at version 3.

    Design: Corner/state_machines/plan_of_care_walks_draft_submitted_under_review_authorized
    """
    payer, patient = _payer_and_patient(api)
    plan = fx.create_submitted_plan_of_care(api, patient["id"])

    fx.create_authorization(api, plan["id"], payer["id"], plan["version"])

    reread = validate_success(api.get_plan_of_care(plan["id"], CASE_MANAGER))
    assert reread["status"] == PlanOfCareStatus.UNDER_REVIEW.value, reread
    assert reread["version"] == 3, reread


def test_submitting_an_already_submitted_plan_is_rejected_not_replayed(api):
    """PRD 3.3 permits submission only while the plan is still `DRAFT`, so a second
    submit fails check 9 of the PRD 2.8 order with `ERR_INVALID_STATE` and HTTP
    409. A rejected call performs no write, so the plan stays `SUBMITTED` at
    version 2 with `revision_round` 0 - the endpoint is not idempotent and must not
    bump the version.

    Design: Corner/state_machines/submitting_an_already_submitted_plan_is_rejected_not_replayed
    """
    _payer, patient = _payer_and_patient(api)
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    assert plan["version"] == 2, plan

    response = api.submit_plan_of_care(plan["id"], CASE_MANAGER)
    validate_error(response, ERR_INVALID_STATE, 409)

    reread = validate_success(api.get_plan_of_care(plan["id"], CASE_MANAGER))
    assert reread["status"] == PlanOfCareStatus.SUBMITTED.value, reread
    assert reread["version"] == 2, reread
    assert reread["revision_round"] == 0, reread


def test_activating_an_authorization_that_is_already_active_is_refused(api):
    """PRD 3.3 declares activation only from `PENDING`, and `ACTIVE` has no
    activate hop of its own, so a second activation fails check 9 of PRD 2.8 with
    `ERR_INVALID_STATE` and HTTP 409. The refusal writes nothing: the grant is
    still `ACTIVE` at the very `version` it held before the call.

    Design: Corner/state_machines/transitions_absent_from_the_declared_list_are_refused
    """
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)

    before = validate_success(
        api.get_authorization(base.authorization_id, base.payer_headers)
    )
    assert before["status"] == AuthorizationStatus.ACTIVE.value, before

    response = api.activate_authorization(base.authorization_id, base.payer_headers)
    validate_error(response, ERR_INVALID_STATE, 409)

    after = validate_success(
        api.get_authorization(base.authorization_id, base.payer_headers)
    )
    assert after["status"] == AuthorizationStatus.ACTIVE.value, after
    assert after["version"] == before["version"], (before, after)


def test_an_authorized_plan_accepts_neither_a_return_nor_a_resubmission(api):
    """PRD 3.3 permits a return only while the plan is `SUBMITTED` or
    `UNDER_REVIEW`, and it names `AUTHORIZED` the plan's terminal state, so neither
    a return nor a submit is declared from there. Both calls answer
    `ERR_INVALID_STATE` with HTTP 409 under check 9 of PRD 2.8, and the plan holds
    its `AUTHORIZED` status at version 4 with `revision_round` untouched.

    Design: Corner/state_machines/transitions_absent_from_the_declared_list_are_refused
    """
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)

    returned = api.return_plan_of_care(
        base.plan_of_care_id,
        f.return_plan_payload("physician order needs a wording change"),
        base.payer_headers,
    )
    validate_error(returned, ERR_INVALID_STATE, 409)

    resubmitted = api.submit_plan_of_care(base.plan_of_care_id, CASE_MANAGER)
    validate_error(resubmitted, ERR_INVALID_STATE, 409)

    reread = validate_success(api.get_plan_of_care(base.plan_of_care_id, CASE_MANAGER))
    assert reread["status"] == PlanOfCareStatus.AUTHORIZED.value, reread
    assert reread["version"] == 4, reread
    assert reread["revision_round"] == 0, reread


def _closed_case(api):
    """The canonical chain with its single case closed while nothing is in flight."""
    base = fx.setup_baseline(api, with_nurse=False)
    closed = validate_success(
        api.close_case(
            base.case_id,
            f.close_case_payload("family relocated out of the service area"),
            CASE_MANAGER,
        )
    )
    assert closed["status"] == CaseStatus.CLOSED.value, closed
    return base


def test_a_closed_case_refuses_hold_resume_and_a_second_close(api):
    """PRD 3.4 declares a manual hold only from `ACTIVE`, a resume only from
    `ON_HOLD`, and a close only from `PENDING_STAFFING`, `ACTIVE` or `ON_HOLD`.
    `CLOSED` is outside all three, so each call is refused by check 9 of PRD 2.8
    with `ERR_INVALID_STATE` and HTTP 409 - the state check precedes the
    patient-status and segregation checks that sit at priorities 12 and 13. The
    case keeps its `CLOSED` status and its null `hold_reason`.

    Design: Corner/state_machines/a_closed_case_accepts_no_further_transition
    """
    base = _closed_case(api)

    hold = api.hold_case(
        base.case_id, f.hold_payload(HoldReason.INCIDENT_REVIEW.value), CLINICAL_SUPERVISOR
    )
    validate_error(hold, ERR_INVALID_STATE, 409)

    resume = api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2)
    validate_error(resume, ERR_INVALID_STATE, 409)

    second_close = api.close_case(
        base.case_id, f.close_case_payload("duplicate closure attempt"), CASE_MANAGER
    )
    validate_error(second_close, ERR_INVALID_STATE, 409)

    reread = fx.refresh_case(api, base.case_id)
    assert reread["status"] == CaseStatus.CLOSED.value, reread
    assert reread["hold_reason"] is None, reread
    assert reread["hold_incident_report_id"] is None, reread


def test_closing_the_only_case_of_a_patient_discharges_the_child(api):
    """PRD 3.4 ends the close with a patient hop: once every case of the patient has
    reached `CLOSED`, the patient's `status` becomes `DISCHARGED`. This child has
    exactly one case, so that single close is enough.

    Design: Corner/state_machines/a_closed_case_accepts_no_further_transition
    """
    base = _closed_case(api)

    patient = validate_success(api.get_patient(base.patient_id, CASE_MANAGER))
    assert patient["status"] == PatientStatus.DISCHARGED.value, patient


def _case_with_two_future_shifts_and_one_behind_the_clock(api):
    """Shift A (Wed 08:00-16:00) assigned, shift B (Thu 08:00-16:00) open, shift C
    (Mon 05:00-13:00) open but already started against the 06:00 clock."""
    base = fx.setup_baseline(api)
    shift_a = fx.publish_shift(api, base.case_id, SHIFT_A_START, SHIFT_A_END)
    shift_b = fx.publish_shift(api, base.case_id, SHIFT_B_START, SHIFT_B_END)
    shift_c = fx.publish_shift(api, base.case_id, SHIFT_C_START, SHIFT_C_END)
    assignment = fx.assign_nurse(api, shift_a["id"], base.nurse_id)
    return base, shift_a, shift_b, shift_c, assignment


def _hold_for_family_request(api, case_id):
    """Place the manual `FAMILY_REQUEST` hold that drives the cascade."""
    return validate_success(
        api.hold_case(
            case_id, f.hold_payload(HoldReason.FAMILY_REQUEST.value), CLINICAL_SUPERVISOR
        )
    )


def test_a_manual_hold_cancels_the_future_shifts_with_cancel_reason_case_hold(api):
    """PRD 3.4 accepts a manual hold only from `ACTIVE`, records the supplied
    `hold_reason`, leaves `hold_incident_report_id` null because no incident drove
    it, and runs the same cascade as an incident hold: every shift that is `OPEN`,
    `ASSIGNED` or `ESCALATED` with `start_at` at or after the clock becomes
    `CANCELLED` with `cancel_reason` `CASE_HOLD`, and each such shift's `ACTIVE`
    assignment is cancelled with the same reason.

    Design: Corner/state_machines/manual_hold_cancels_future_shifts_but_spares_the_visit_in_progress
    """
    base, shift_a, shift_b, _shift_c, assignment = (
        _case_with_two_future_shifts_and_one_behind_the_clock(api)
    )

    held = _hold_for_family_request(api, base.case_id)
    assert held["status"] == CaseStatus.ON_HOLD.value, held
    assert held["hold_reason"] == HoldReason.FAMILY_REQUEST.value, held
    assert held["hold_incident_report_id"] is None, held

    for shift in (shift_a, shift_b):
        reread = fx.refresh_shift(api, shift["id"])
        assert reread["staffing_status"] == StaffingStatus.CANCELLED.value, reread
        assert reread["cancel_reason"] == ShiftCancelReason.CASE_HOLD.value, reread

    reread_assignment = validate_success(api.get_assignment(assignment["id"], SCHEDULER))
    assert reread_assignment["status"] == AssignmentStatus.CANCELLED.value, reread_assignment
    assert (
        reread_assignment["cancel_reason"] == AssignmentCancelReason.CASE_HOLD.value
    ), reread_assignment


def test_a_manual_hold_spares_the_shift_already_behind_the_clock(api):
    """The PRD 3.4 cascade only reaches shifts whose `start_at` is at or after the
    current logical clock, so the 05:00 shift under a 06:00 clock keeps
    `staffing_status` `OPEN` and `cancel_reason` `NONE`. The PRD 3.4 fill metrics
    look strictly forward from the clock and exclude cancelled shifts, so with A and
    B cancelled and C behind the clock the denominator is empty:
    `unfilled_shift_count` is 0 and `fill_rate` is exactly 1.0000.

    Design: Corner/state_machines/manual_hold_cancels_future_shifts_but_spares_the_visit_in_progress
    """
    base, _shift_a, _shift_b, shift_c, _assignment = (
        _case_with_two_future_shifts_and_one_behind_the_clock(api)
    )

    _hold_for_family_request(api, base.case_id)

    spared = fx.refresh_shift(api, shift_c["id"])
    assert spared["staffing_status"] == StaffingStatus.OPEN.value, spared
    assert spared["cancel_reason"] == ShiftCancelReason.NONE.value, spared

    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 0, case
    assert_ratio(case, "fill_rate", 1.0000)


def test_a_manual_hold_returns_the_committed_minutes_and_the_nurse_ledger_to_zero(api):
    """PRD 3.3 counts `committed_minutes` over the `ASSIGNED`-or-`COMPLETED` shifts
    of the week, so the 480-minute assigned shift is the whole projected figure
    before the hold. PRD 3.4 has the hold cancel that assignment and recompute the
    nurse's `scheduled_minutes_this_week` together with the authorization's
    committed figure, so both fall to 0 - the conserved quantities follow the
    cascade rather than lagging it.

    Design: Corner/state_machines/manual_hold_cancels_future_shifts_but_spares_the_visit_in_progress
    """
    base, _shift_a, _shift_b, _shift_c, _assignment = (
        _case_with_two_future_shifts_and_one_behind_the_clock(api)
    )
    params = {"basis": UtilizationBasis.PROJECTED.value, "week_of": WEEK32_WEDNESDAY}

    before = validate_success(
        api.get_utilization(base.authorization_id, SCHEDULER, params)
    )
    assert before["committed_minutes"] == 480, before

    _hold_for_family_request(api, base.case_id)

    after = validate_success(api.get_utilization(base.authorization_id, SCHEDULER, params))
    assert after["committed_minutes"] == 0, after

    nurse = fx.refresh_nurse(api, base.nurse_id)
    assert nurse["scheduled_minutes_this_week"] == 0, nurse


def _active_case_with_a_captured_timesheet(api):
    """One worked visit on an ACTIVE case, its timesheet still `CAPTURED`."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, SHIFT_A_START, SHIFT_A_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    fx.clock_in(api, shift["id"], base.nurse_id, at=CLOCK_IN_AT)
    fx.clock_out(api, shift["id"], base.nurse_id, at=CLOCK_OUT_AT)
    timesheet = fx.timesheet_of_assignment(api, assignment["id"], base.nurse_id)
    assert timesheet["status"] == TimesheetStatus.CAPTURED.value, timesheet
    return base, shift, timesheet


def test_closing_a_case_is_blocked_while_a_timesheet_is_still_in_flight(api):
    """PRD 3.4 accepts a close only when no timesheet of the case has `status`
    `CAPTURED`, `EDITED`, `SUBMITTED` or `BILL_REJECTED`, and names an in-flight
    timesheet an `ERR_INVALID_STATE`. The precondition reaches into another
    aggregate: the case itself is `ACTIVE` and closable, yet the captured visit
    blocks it with HTTP 409 and nothing changes.

    Design: Corner/state_machines/closing_a_case_is_blocked_while_a_timesheet_is_still_open
    """
    base, _shift, timesheet = _active_case_with_a_captured_timesheet(api)

    response = api.close_case(
        base.case_id, f.close_case_payload("transfer to another agency"), CASE_MANAGER
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ACTIVE.value, case

    reread = fx.refresh_timesheet(api, timesheet["id"])
    assert reread["status"] == TimesheetStatus.CAPTURED.value, reread


def test_voiding_the_in_flight_timesheet_unblocks_the_identical_close(api):
    """PRD 3.7 accepts a void from `SUBMITTED`, `BILL_ACCEPTED` or `BILL_REJECTED`
    and moves the row to `VOIDED`; `VOIDED` is outside the blocking set PRD 3.4
    lists for closing a case, while `SUBMITTED` is inside it. The same close body
    therefore fails at 409 while the row is `SUBMITTED` and succeeds at 200 once it
    is `VOIDED`, leaving the case `CLOSED`.

    Design: Corner/state_machines/closing_a_case_is_blocked_while_a_timesheet_is_still_open
    """
    base, _shift, timesheet = _active_case_with_a_captured_timesheet(api)
    close_body = f.close_case_payload("transfer to another agency")

    submitted = fx.submit_timesheet(api, timesheet["id"])
    assert submitted["status"] == TimesheetStatus.SUBMITTED.value, submitted
    validate_error(
        api.close_case(base.case_id, close_body, CASE_MANAGER), ERR_INVALID_STATE, 409
    )

    voided = validate_success(
        api.void_timesheet(
            timesheet["id"],
            f.void_timesheet_payload("visit billed under the transferring agency"),
            SCHEDULER,
        )
    )
    assert voided["status"] == TimesheetStatus.VOIDED.value, voided

    closed = validate_success(api.close_case(base.case_id, close_body, CASE_MANAGER))
    assert closed["status"] == CaseStatus.CLOSED.value, closed


def _submitted_plan_with_a_pending_grant(api):
    """A plan of care in UNDER_REVIEW carrying one PENDING authorization."""
    payer, patient = _payer_and_patient(api)
    payer_headers = make_payer_reviewer_headers(payer["id"])
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    assert plan["revision_round"] == 0, plan
    first_grant = fx.create_authorization(api, plan["id"], payer["id"], plan["version"])
    assert first_grant["status"] == AuthorizationStatus.PENDING.value, first_grant
    return payer, plan, payer_headers, first_grant


def test_each_return_increments_the_revision_round_but_a_resubmission_does_not(api):
    """PRD 3.3 has a return move the plan to `RETURNED` and increase
    `revision_round` by 1, while the `CaseManager`'s resubmission only moves
    `RETURNED` -> `SUBMITTED`. The counter therefore reads 1 after the first return,
    is still 1 across the resubmission, and reaches 2 on the second return: the
    loop `RETURNED -> SUBMITTED -> UNDER_REVIEW -> RETURNED` "may repeat any number
    of times, with `revision_round` counting the rounds".

    Design: Corner/state_machines/returned_plan_resubmission_loops_and_expires_the_pending_grant
    """
    payer, plan, payer_headers, _first_grant = _submitted_plan_with_a_pending_grant(api)

    first_return = validate_success(
        api.return_plan_of_care(
            plan["id"],
            f.return_plan_payload("hours requested exceed the documented nursing need"),
            payer_headers,
        )
    )
    assert first_return["status"] == PlanOfCareStatus.RETURNED.value, first_return
    assert first_return["revision_round"] == 1, first_return

    resubmitted = fx.submit_plan_of_care(api, plan["id"])
    assert resubmitted["status"] == PlanOfCareStatus.SUBMITTED.value, resubmitted
    assert resubmitted["revision_round"] == 1, resubmitted

    fx.create_authorization(
        api,
        plan["id"],
        payer["id"],
        resubmitted["version"],
        approved_hours_per_week=32.00,
    )
    second_return = validate_success(
        api.return_plan_of_care(
            plan["id"],
            f.return_plan_payload("physician signature page still missing"),
            payer_headers,
        )
    )
    assert second_return["status"] == PlanOfCareStatus.RETURNED.value, second_return
    assert second_return["revision_round"] == 2, second_return


def test_every_return_expires_the_pending_grant_of_that_round(api):
    """PRD 3.3 has each return take "every `PENDING` authorization of that plan out
    of consideration by moving it to `EXPIRED`", and `EXPIRED` is terminal - the
    grant of round one is never resurrected by the resubmission. Because no
    authorization of the plan is `ACTIVE`, `REDUCTION_NOTICED`, `UNDER_APPEAL` or
    `REDUCED`, the second return is permitted too, leaving both grants `EXPIRED` and
    a two-row `plan_of_care_id` listing.

    Design: Corner/state_machines/returned_plan_resubmission_loops_and_expires_the_pending_grant
    """
    payer, plan, payer_headers, first_grant = _submitted_plan_with_a_pending_grant(api)

    validate_success(
        api.return_plan_of_care(
            plan["id"],
            f.return_plan_payload("hours requested exceed the documented nursing need"),
            payer_headers,
        )
    )
    expired_first = validate_success(api.get_authorization(first_grant["id"], payer_headers))
    assert expired_first["status"] == AuthorizationStatus.EXPIRED.value, expired_first

    resubmitted = fx.submit_plan_of_care(api, plan["id"])
    still_expired = validate_success(api.get_authorization(first_grant["id"], payer_headers))
    assert still_expired["status"] == AuthorizationStatus.EXPIRED.value, still_expired

    second_grant = fx.create_authorization(
        api,
        plan["id"],
        payer["id"],
        resubmitted["version"],
        approved_hours_per_week=32.00,
    )
    assert second_grant["status"] == AuthorizationStatus.PENDING.value, second_grant

    validate_success(
        api.return_plan_of_care(
            plan["id"],
            f.return_plan_payload("physician signature page still missing"),
            payer_headers,
        )
    )
    expired_second = validate_success(api.get_authorization(second_grant["id"], payer_headers))
    assert expired_second["status"] == AuthorizationStatus.EXPIRED.value, expired_second

    rows, meta = validate_paginated(
        api.list_authorizations(
            payer_headers,
            dict(f.pagination(10, 0), plan_of_care_id=plan["id"]),
        )
    )
    assert meta["total_count"] == 2, meta
    assert {row["status"] for row in rows} == {AuthorizationStatus.EXPIRED.value}, rows


def test_a_low_severity_non_hospitalization_incident_cascades_nothing(api):
    """PRD 3.8 sets `triggered_case_hold` true exactly when the `category` is
    `HOSPITALIZATION` or the `severity` is `HIGH`; a `LOW` `MEDICATION_ERROR` is
    neither, so "cascades nothing at all". The report still opens in `OPEN`, and the
    case keeps `status` `ACTIVE` with `hold_reason` and `hold_incident_report_id`
    both null - PRD 3.8 reads `hold_reason` as null on any case not `ON_HOLD`.

    Design: Corner/state_machines/only_hospitalization_or_high_severity_incidents_cascade_a_hold
    """
    base = fx.setup_baseline(api)

    low = fx.file_incident(
        api,
        base.case_id,
        INCIDENT_LOW_AT,
        category=IncidentCategory.MEDICATION_ERROR.value,
        severity=IncidentSeverity.LOW.value,
        narrative="dose given twenty minutes late, no clinical effect",
    )

    assert low["triggered_case_hold"] is False, low
    assert low["status"] == IncidentStatus.OPEN.value, low

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ACTIVE.value, case
    assert case["hold_reason"] is None, case
    assert case["hold_incident_report_id"] is None, case


def test_a_high_severity_non_hospitalization_incident_holds_the_case_but_spares_the_child(api):
    """PRD 3.8's middle branch: a `HIGH` `EQUIPMENT_FAILURE` sets
    `triggered_case_hold` true and "cascades the identical case hold ... but with
    `hold_reason` `INCIDENT_REVIEW`, and the patient-status hop is skipped entirely".
    The case therefore lands `ON_HOLD` pointing at this report through
    `hold_incident_report_id`, while the patient stays `ACTIVE` because only
    `HOSPITALIZATION` marks the child `HOSPITALIZED`.

    Design: Corner/state_machines/only_hospitalization_or_high_severity_incidents_cascade_a_hold
    """
    base = fx.setup_baseline(api)
    fx.file_incident(
        api,
        base.case_id,
        INCIDENT_LOW_AT,
        category=IncidentCategory.MEDICATION_ERROR.value,
        severity=IncidentSeverity.LOW.value,
        narrative="dose given twenty minutes late, no clinical effect",
    )

    high = fx.file_incident(
        api,
        base.case_id,
        INCIDENT_HIGH_AT,
        category=IncidentCategory.EQUIPMENT_FAILURE.value,
        severity=IncidentSeverity.HIGH.value,
        narrative="home ventilator alarmed and switched to the backup circuit",
    )
    assert high["triggered_case_hold"] is True, high

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ON_HOLD.value, case
    assert case["hold_reason"] == HoldReason.INCIDENT_REVIEW.value, case
    assert case["hold_incident_report_id"] == high["id"], case

    patient = validate_success(api.get_patient(base.patient_id, CASE_MANAGER))
    assert patient["status"] == PatientStatus.ACTIVE.value, patient
