"""Role-based access control and entity-backed ownership.

The header contract of PRD 2.1, the per-endpoint role table of PRD section 4,
the four authorization priorities that open the precedence ladder of PRD 2.8
(1 `ERR_MISSING_AUTH_HEADER`, 2 `ERR_UNAUTHORIZED_ROLE`, 3 the `Nurse`
ownership check, 4 `ERR_PAYER_SCOPE_VIOLATION`) and the case-resume split of
PRD 2.11 (`ERR_SEGREGATION_OF_DUTIES`, priority 13).

Every negative header in this file is sent as the empty string, never as
whitespace, because PRD 2.1 fails a header that is "absent or empty".
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_MISSING_AUTH_HEADER,
    ERR_PAYER_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED_ROLE,
)
from test_helpers.assertions import (
    assert_shift_axes,
    assert_version_is,
    validate_unpaginated,
)
from test_helpers.test_users import (
    AGENCY_ADMIN_USER_ID,
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    CLINICAL_SUPERVISOR_2,
    SCHEDULER,
    SUPERVISOR_USER_ID,
    headers_missing_role,
    make_nurse_headers,
    make_payer_reviewer_headers,
)
from test_helpers.types import (
    AuthorizationStatus,
    CaseStatus,
    EvvStatus,
    HoldReason,
    IncidentCategory,
    IncidentSeverity,
    PlanOfCareStatus,
    PlanType,
    StaffingStatus,
    TimesheetStatus,
)

# ISO week 32 of 2026 runs Monday 2026-08-03 .. Sunday 2026-08-09.
WEEK32_WEDNESDAY_08 = "2026-08-05T08:00:00Z"
WEEK32_WEDNESDAY_16 = "2026-08-05T16:00:00Z"
WEEK32_THURSDAY_08 = "2026-08-06T08:00:00Z"
WEEK32_THURSDAY_16 = "2026-08-06T16:00:00Z"


# ---------------------------------------------------------------------------
# rbac / an_absent_role_header_is_rejected_before_anything_else
# ---------------------------------------------------------------------------
def test_an_empty_role_header_is_rejected_on_a_plain_read(api):
    """PRD 2.1 requires `X-User-Role` on *every* request, "including reads", and
    fails an absent or empty value with `ERR_MISSING_AUTH_HEADER` (HTTP 401).
    The nurse listing is a read that `AgencyAdmin` is otherwise entitled to, so
    only the blank role header can explain the rejection.

    Design: Corner/rbac/an_absent_role_header_is_rejected_before_anything_else
    """
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)

    response = api.list_nurses(headers_missing_role(AGENCY_ADMIN_USER_ID))

    validate_error(response, ERR_MISSING_AUTH_HEADER, 401)


def test_an_empty_role_header_outranks_both_the_unknown_path_id_and_the_illegal_enum(api):
    """Priority 1 of PRD 2.8 "precedes every other check in the system", so a
    request whose `X-User-ID` and `X-User-Role` are both empty, whose path
    identifier resolves to nothing (priority 5, `ERR_CASE_NOT_FOUND`) and whose
    `hold_reason` is not a legal enum member (priority 7,
    `ERR_INVALID_REQUEST`) still answers `ERR_MISSING_AUTH_HEADER` with 401.

    Design: Corner/rbac/an_absent_role_header_is_rejected_before_anything_else
    """
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)

    # Both headers present but empty - never whitespace, per PRD 2.1.
    blank_headers = headers_missing_role("")
    response = api.hold_case(
        C.UNKNOWN_UUID, f.hold_payload("NOT_A_LEGAL_REASON"), blank_headers
    )

    validate_error(response, ERR_MISSING_AUTH_HEADER, 401)


# ---------------------------------------------------------------------------
# rbac / a_role_cannot_perform_another_roles_exclusive_write
# ---------------------------------------------------------------------------
def _case_with_one_open_shift(api):
    """The canonical chain plus one future OPEN shift in ISO week 32."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, WEEK32_THURSDAY_08, WEEK32_THURSDAY_16)
    return base, shift


def test_three_cross_role_exclusive_writes_are_each_unauthorized_role(api):
    """PRD section 4 assigns `POST /pdn/authorizations` to `PayerReviewer`,
    `POST /pdn/shift-assignments` to `Scheduler` and `POST /pdn/incident-reports`
    to `ClinicalSupervisor`. PRD 2.1 rejects "a recognised role that the target
    operation does not permit" with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), and
    priority 2 of PRD 2.8 puts that check ahead of every body check, so all
    three otherwise-perfect payloads answer 403.

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_write
    """
    base, shift = _case_with_one_open_shift(api)

    as_scheduler = api.create_authorization(
        f.authorization_payload(
            base.plan_of_care_id,
            base.payer_id,
            base.plan_of_care["version"],
            approved_hours_per_week=32.0,
        ),
        SCHEDULER,
    )
    validate_error(as_scheduler, ERR_UNAUTHORIZED_ROLE, 403)

    as_case_manager = api.create_assignment(
        f.assignment_payload(shift["id"], base.nurse_id, shift["version"]),
        CASE_MANAGER,
    )
    validate_error(as_case_manager, ERR_UNAUTHORIZED_ROLE, 403)

    as_nurse = api.create_incident_report(
        f.incident_payload(
            base.case_id,
            "2026-08-03T05:00:00Z",
            category=IncidentCategory.FALL.value,
            severity=IncidentSeverity.LOW.value,
            narrative="filed by the wrong role",
        ),
        make_nurse_headers(base.nurse_id),
    )
    validate_error(as_nurse, ERR_UNAUTHORIZED_ROLE, 403)


def test_a_rejected_cross_role_write_leaves_the_shift_untouched(api):
    """Because the role check sits at priority 2 of PRD 2.8 - ahead of the
    optimistic-concurrency guard of priority 8 and the assignment gauntlet - a
    `CaseManager` assignment attempt writes nothing at all: the shift keeps
    `staffing_status` `OPEN`, `evv_status` `NOT_STARTED` and the very `version`
    it was published with.

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_write
    """
    base, shift = _case_with_one_open_shift(api)
    published_version = shift["version"]

    rejected = api.create_assignment(
        f.assignment_payload(shift["id"], base.nurse_id, published_version),
        CASE_MANAGER,
    )
    validate_error(rejected, ERR_UNAUTHORIZED_ROLE, 403)

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.OPEN.value, EvvStatus.NOT_STARTED.value)
    assert_version_is(reread, published_version)

    rows, meta = validate_paginated(
        api.list_assignments(SCHEDULER, {"shift_id": shift["id"]})
    )
    assert meta["total_count"] == 0, rows


# ---------------------------------------------------------------------------
# rbac / a_nurse_may_only_clock_in_on_their_own_assignment
# ---------------------------------------------------------------------------
def _two_nurses_and_an_assigned_shift(api):
    """Two equally competent nurses; the Wednesday shift is assigned to the
    first and the clock is then parked on the shift's own `start_at`."""
    base = fx.setup_baseline(api)
    other_nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002"
    )
    shift = fx.publish_shift(api, base.case_id, WEEK32_WEDNESDAY_08, WEEK32_WEDNESDAY_16)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    fx.set_clock(api, WEEK32_WEDNESDAY_08)
    return base, other_nurse, shift, assignment


def test_an_unassigned_nurse_cannot_clock_in_on_someone_elses_shift(api):
    """Priority 3 of PRD 2.8 compares a `Nurse`'s `X-User-ID` against "the
    `nurse_id` of the shift's `ACTIVE` `ShiftAssignment`" on clock-in and answers
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403). This is not the priority-2 role check:
    the caller sends the legal role `Nurse` and is fully competent for
    `required_skills`; only the ownership comparison fails, so nothing is written
    and `evv_status` stays `NOT_STARTED`.

    Design: Corner/rbac/a_nurse_may_only_clock_in_on_their_own_assignment
    """
    base, other_nurse, shift, assignment = _two_nurses_and_an_assigned_shift(api)

    response = api.clock_in(
        shift["id"],
        f.clock_in_payload(geo_verified=True),
        make_nurse_headers(other_nurse["id"]),
    )

    validate_error(response, ERR_UNAUTHORIZED_ROLE, 403)

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(
        reread, StaffingStatus.ASSIGNED.value, EvvStatus.NOT_STARTED.value
    )
    rows, _meta = validate_unpaginated(
        api.list_assignment_timesheets(assignment["id"], SCHEDULER)
    )
    assert rows == [], rows


def test_the_assigned_nurse_clocks_in_and_opens_the_timesheet(api):
    """The very same route succeeds for the nurse named on the `ACTIVE`
    assignment: PRD 3.7 creates a timesheet in `CAPTURED` and section 4 answers
    201 because a row comes into existence. PRD 3.5 keeps the two axes
    independent, so `evv_status` advances `NOT_STARTED -> CLOCKED_IN` while
    `staffing_status` stays `ASSIGNED`.

    Design: Corner/rbac/a_nurse_may_only_clock_in_on_their_own_assignment
    """
    base, _other_nurse, shift, _assignment = _two_nurses_and_an_assigned_shift(api)

    response = api.clock_in(
        shift["id"],
        f.clock_in_payload(geo_verified=True),
        make_nurse_headers(base.nurse_id),
    )

    timesheet = validate_success(response, 201)
    assert timesheet["status"] == TimesheetStatus.CAPTURED.value, timesheet

    reread = fx.refresh_shift(api, shift["id"])
    assert_shift_axes(reread, StaffingStatus.ASSIGNED.value, EvvStatus.CLOCKED_IN.value)


# ---------------------------------------------------------------------------
# rbac / a_payer_reviewer_cannot_reach_another_payers_authorization
# ---------------------------------------------------------------------------
def _two_payers_and_a_pending_authorization(api):
    """Two payers exist; the `PENDING` authorization belongs to the first only."""
    base = fx.setup_baseline(
        api,
        activate_authorization_after_create=False,
        with_nurse=False,
        with_case=False,
    )
    other_payer = fx.create_payer(
        api,
        name="Harbor Commercial",
        plan_type=PlanType.COMMERCIAL.value,
        weekly_hour_cap=60.0,
    )
    return base, other_payer


def test_a_foreign_payer_reviewer_cannot_activate_another_payers_authorization(api):
    """PRD 2.1 makes `PayerReviewer` entity-backed - `X-User-ID` "is the `id` of
    the acting `Payer`" - and lists activation among the nine operations whose
    `payer_id` mismatch is `ERR_PAYER_SCOPE_VIOLATION` (HTTP 403). The foreign
    reviewer holds a recognised, permitted role, so priority 2 passes and only
    priority 4 can explain the 403; the rightful reviewer then activates the same
    row, driving the plan of care to its terminal `AUTHORIZED` state (PRD 3.3).

    Design: Corner/rbac/a_payer_reviewer_cannot_reach_another_payers_authorization
    """
    base, other_payer = _two_payers_and_a_pending_authorization(api)

    foreign = api.activate_authorization(
        base.authorization_id, make_payer_reviewer_headers(other_payer["id"])
    )
    validate_error(foreign, ERR_PAYER_SCOPE_VIOLATION, 403)

    rightful = api.activate_authorization(base.authorization_id, base.payer_headers)
    authorization = validate_success(rightful, 200)
    assert authorization["status"] == AuthorizationStatus.ACTIVE.value, authorization

    plan = validate_success(
        api.get_plan_of_care(base.plan_of_care_id, base.payer_headers)
    )
    assert plan["status"] == PlanOfCareStatus.AUTHORIZED.value, plan


def test_payer_scope_is_reported_ahead_of_the_state_error_on_a_foreign_reduce(api):
    """Noticing a reduction is another of the nine scope-guarded operations of
    PRD 2.1, and PRD 2.8 orders payer scope at priority 4 against the transition
    check at priority 9 - "a request that violates both a payer scope rule and a
    weekly hour cap must report the scope violation". A `PENDING` authorization
    can never be reduced (PRD 3.9 requires `ACTIVE`), yet the foreign reviewer
    still gets `ERR_PAYER_SCOPE_VIOLATION` rather than `ERR_INVALID_STATE`, and
    the grant is left untouched in `PENDING`.

    Design: Corner/rbac/a_payer_reviewer_cannot_reach_another_payers_authorization
    """
    base, other_payer = _two_payers_and_a_pending_authorization(api)

    foreign = api.reduce_authorization(
        base.authorization_id,
        f.reduce_payload(24.0, "poaching another payer's case"),
        make_payer_reviewer_headers(other_payer["id"]),
    )
    validate_error(foreign, ERR_PAYER_SCOPE_VIOLATION, 403)

    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.PENDING.value, authorization


# ---------------------------------------------------------------------------
# rbac / the_incident_reporter_cannot_lift_their_own_case_hold
# ---------------------------------------------------------------------------
def _held_case_after_a_high_severity_incident(api):
    """sup-001 files a HIGH-severity FALL incident, which holds the case with
    `hold_reason` `INCIDENT_REVIEW`, and then closes that report."""
    base = fx.setup_baseline(api)
    incident = fx.file_incident(
        api,
        base.case_id,
        "2026-08-03T05:30:00Z",
        category=IncidentCategory.FALL.value,
        severity=IncidentSeverity.HIGH.value,
        narrative="child fell during a transfer, no injury found",
    )
    fx.close_incident(
        api,
        incident["id"],
        True,
        resolution="transfer technique retrained with the family",
    )
    return base, incident


def test_the_incident_reporter_is_refused_on_resume_of_their_own_hold(api):
    """PRD 3.8 makes a HIGH-severity non-hospitalization report set
    `triggered_case_hold` true and hold the case with `hold_incident_report_id`
    pointing at it. PRD 2.11 then requires the resuming `ClinicalSupervisor`'s
    `X-User-ID` to differ from that report's `reported_by_user_id`; the same
    person is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403, priority 13),
    and because the check compares user identifiers rather than roles the case
    stays `ON_HOLD` with `hold_reason` `INCIDENT_REVIEW`.

    Design: Corner/rbac/the_incident_reporter_cannot_lift_their_own_case_hold
    """
    base, incident = _held_case_after_a_high_severity_incident(api)

    assert incident["triggered_case_hold"] is True, incident
    assert incident["reported_by_user_id"] == SUPERVISOR_USER_ID, incident

    held = fx.refresh_case(api, base.case_id)
    assert held["status"] == CaseStatus.ON_HOLD.value, held
    assert held["hold_incident_report_id"] == incident["id"], held

    response = api.resume_case(base.case_id, CLINICAL_SUPERVISOR)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    still_held = fx.refresh_case(api, base.case_id)
    assert still_held["status"] == CaseStatus.ON_HOLD.value, still_held
    assert still_held["hold_reason"] == HoldReason.INCIDENT_REVIEW.value, still_held


def test_a_second_supervisor_resumes_the_hold_the_first_one_created(api):
    """The two supervisors are interchangeable on every other route, so a
    `ClinicalSupervisor` whose `X-User-ID` differs from the report's
    `reported_by_user_id` clears PRD 2.11's split and PRD 3.8's resume gates -
    the report is `CLOSED` and the child was never `HOSPITALIZED`. On success
    "`hold_reason` and `hold_incident_report_id` are both cleared to null".

    Design: Corner/rbac/the_incident_reporter_cannot_lift_their_own_case_hold
    """
    base, _incident = _held_case_after_a_high_severity_incident(api)

    resumed = validate_success(
        api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2), 200
    )

    assert resumed["status"] == CaseStatus.ACTIVE.value, resumed
    assert resumed["hold_reason"] is None, resumed
    assert resumed["hold_incident_report_id"] is None, resumed
