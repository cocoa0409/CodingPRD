"""Layered flows: optimistic concurrency, the selector's tie-break, and the
read-your-write consistency of a cascading hold.

The optimistic-concurrency contract of PRD 2.6 with priority 8 of PRD 2.8, the
match-score and tie-break rules of PRD 3.6, and the immediate-consistency
promise that PRD 2.2 and 2.10 make together: a write's own response body already
carries every figure the cascade re-derived, so no follow-up read can add
anything.
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
    ERR_STALE_PLAN_OF_CARE_VERSION,
    ERR_STALE_SHIFT_VERSION,
)
from test_helpers.assertions import assert_hours, assert_ratio, assert_version_is
from test_helpers.test_users import (
    CLINICAL_SUPERVISOR,
    SCHEDULER,
    make_payer_reviewer_headers,
)
from test_helpers.types import (
    AssignmentCancelReason,
    AssignmentStatus,
    CaseStatus,
    HoldReason,
    PlanOfCareStatus,
    ShiftCancelReason,
    StaffingStatus,
)

# ISO week 32 of 2026 runs Monday 2026-08-03 .. Sunday 2026-08-09.
WEEK32_TUESDAY_08 = "2026-08-04T08:00:00Z"
WEEK32_TUESDAY_10 = "2026-08-04T10:00:00Z"
WEEK32_WEDNESDAY_08 = "2026-08-05T08:00:00Z"
WEEK32_WEDNESDAY_16 = "2026-08-05T16:00:00Z"
WEEK32_THURSDAY_08 = "2026-08-06T08:00:00Z"
WEEK32_THURSDAY_16 = "2026-08-06T16:00:00Z"
WEEK32_FRIDAY_08 = "2026-08-07T08:00:00Z"
WEEK32_FRIDAY_16 = "2026-08-07T16:00:00Z"


# ---------------------------------------------------------------------------
# complexity_layers / stale_plan_of_care_version_is_refused_then_the_refreshed_one_is_taken
# ---------------------------------------------------------------------------
def _submitted_plan_before_any_authorization(api):
    """A `SUBMITTED` plan of care whose post-submit `version` is captured while
    no authorization exists yet, so that token is about to go stale."""
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)
    payer = fx.create_payer(api)
    patient = fx.create_patient(api, payer["id"])
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    return payer, plan


def test_replaying_the_pre_create_plan_version_is_refused_and_writes_nothing(api):
    """PRD 2.6 requires `expected_plan_of_care_version` to equal the plan's
    current `version` and rejects a mismatch with
    `ERR_STALE_PLAN_OF_CARE_VERSION` (HTTP 412), "and nothing is written". The
    first issuance moves the plan `SUBMITTED -> UNDER_REVIEW` and increments its
    `version` by exactly 1 (PRD 3.3), so replaying the pre-create token is now
    stale: the 412 leaves the plan's `version` where the accepted create left it
    and adds no second authorization.

    Design: Corner/complexity_layers/stale_plan_of_care_version_is_refused_then_the_refreshed_one_is_taken
    """
    payer, plan = _submitted_plan_before_any_authorization(api)
    stale_version = plan["version"]
    reviewer = make_payer_reviewer_headers(payer["id"])

    first = validate_success(
        api.create_authorization(
            f.authorization_payload(plan["id"], payer["id"], stale_version), reviewer
        ),
        201,
    )

    after_first = validate_success(api.get_plan_of_care(plan["id"], reviewer))
    assert after_first["status"] == PlanOfCareStatus.UNDER_REVIEW.value, after_first
    assert_version_is(after_first, stale_version + 1)

    replay = api.create_authorization(
        f.authorization_payload(
            plan["id"], payer["id"], stale_version, approved_hours_per_week=32.0
        ),
        reviewer,
    )
    validate_error(replay, ERR_STALE_PLAN_OF_CARE_VERSION, 412)

    after_replay = validate_success(api.get_plan_of_care(plan["id"], reviewer))
    assert_version_is(after_replay, stale_version + 1)

    rows, meta = validate_paginated(
        api.list_authorizations(reviewer, {"plan_of_care_id": plan["id"]})
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == first["id"], rows


# ---------------------------------------------------------------------------
# complexity_layers / stale_shift_version_is_refused_on_both_the_manual_and_the_auto_route
# ---------------------------------------------------------------------------
def _assigned_shift_holding_a_stale_version_token(api):
    """A Thursday shift already assigned to the case's continuity nurse, with a
    second equally competent nurse standing by and the pre-assignment `version`
    kept as the token that is now one behind."""
    base = fx.setup_baseline(api)
    other_nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002"
    )
    shift = fx.publish_shift(api, base.case_id, WEEK32_THURSDAY_08, WEEK32_THURSDAY_16)
    stale_version = shift["version"]
    incumbent = fx.assign_nurse(
        api, shift["id"], base.nurse_id, expected_shift_version=stale_version
    )
    return base, other_nurse, shift, stale_version, incumbent


def test_the_stale_shift_version_is_refused_on_the_manual_assignment_route(api):
    """PRD 2.6 pins `expected_shift_version` to the shift's live `version` on
    manual assignment and answers `ERR_STALE_SHIFT_VERSION` (HTTP 412) otherwise.
    The first assignment moved the shift `OPEN -> ASSIGNED` and bumped its
    `version` by 1 (PRD 3.5), so the swap replaying the pre-assignment token is
    refused with nothing written: the shift keeps that one incremented `version`
    and the incumbent assignment is still the only row.

    Design: Corner/complexity_layers/stale_shift_version_is_refused_on_both_the_manual_and_the_auto_route
    """
    base, other_nurse, shift, stale_version, incumbent = (
        _assigned_shift_holding_a_stale_version_token(api)
    )

    refused = api.create_assignment(
        f.assignment_payload(shift["id"], other_nurse["id"], stale_version), SCHEDULER
    )
    validate_error(refused, ERR_STALE_SHIFT_VERSION, 412)

    reread = fx.refresh_shift(api, shift["id"])
    assert reread["staffing_status"] == StaffingStatus.ASSIGNED.value, reread
    assert_version_is(reread, stale_version + 1)

    rows, meta = validate_paginated(
        api.list_assignments(SCHEDULER, {"shift_id": shift["id"]})
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == incumbent["id"], rows
    assert rows[0]["nurse_id"] == base.nurse_id, rows
    assert rows[0]["status"] == AssignmentStatus.ACTIVE.value, rows


def test_the_stale_shift_version_is_refused_before_the_selector_runs(api):
    """PRD 2.6 puts the same guard on the auto-staff route, and PRD 2.8 orders the
    optimistic-concurrency check at priority 8 - ahead of the transition check at
    priority 9 and of everything the selector of PRD 3.6 would do. So a stale
    `expected_shift_version` answers `ERR_STALE_SHIFT_VERSION` rather than any
    staffing outcome: no candidate is scored, no assignment is created and the
    shift's `version` is untouched.

    Design: Corner/complexity_layers/stale_shift_version_is_refused_on_both_the_manual_and_the_auto_route
    """
    _base, _other_nurse, shift, stale_version, incumbent = (
        _assigned_shift_holding_a_stale_version_token(api)
    )

    refused = api.auto_staff_shift(
        shift["id"], f.auto_staff_payload(stale_version), SCHEDULER
    )
    validate_error(refused, ERR_STALE_SHIFT_VERSION, 412)

    reread = fx.refresh_shift(api, shift["id"])
    assert_version_is(reread, stale_version + 1)

    rows, meta = validate_paginated(
        api.list_assignments(SCHEDULER, {"shift_id": shift["id"]})
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == incumbent["id"], rows


def test_the_refreshed_shift_version_completes_the_continuity_swap(api):
    """PRD 2.6 calls "swapping the nurse on an already `ASSIGNED` shift" a
    legitimate operation, so only the version token separates the refused call
    from the accepted one. PRD 3.5 then supersedes the incumbent: its assignment
    becomes `CANCELLED` with `cancel_reason` `REPLACED` while the new one is
    `ACTIVE`. Because PRD 2.12 counts only `ACTIVE` or `COMPLETED` assignments,
    the whole 480 minutes moves off the incumbent's
    `scheduled_minutes_this_week` and onto the replacement's.

    Design: Corner/complexity_layers/stale_shift_version_is_refused_on_both_the_manual_and_the_auto_route
    """
    base, other_nurse, shift, stale_version, incumbent = (
        _assigned_shift_holding_a_stale_version_token(api)
    )
    validate_error(
        api.create_assignment(
            f.assignment_payload(shift["id"], other_nurse["id"], stale_version), SCHEDULER
        ),
        ERR_STALE_SHIFT_VERSION,
        412,
    )

    fresh_version = fx.refresh_shift(api, shift["id"])["version"]
    replacement = validate_success(
        api.create_assignment(
            f.assignment_payload(shift["id"], other_nurse["id"], fresh_version), SCHEDULER
        ),
        201,
    )
    assert replacement["nurse_id"] == other_nurse["id"], replacement
    assert replacement["status"] == AssignmentStatus.ACTIVE.value, replacement

    superseded = validate_success(api.get_assignment(incumbent["id"], SCHEDULER))
    assert superseded["status"] == AssignmentStatus.CANCELLED.value, superseded
    assert (
        superseded["cancel_reason"] == AssignmentCancelReason.REPLACED.value
    ), superseded

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 0
    assert fx.refresh_nurse(api, other_nurse["id"])["scheduled_minutes_this_week"] == 480


# ---------------------------------------------------------------------------
# complexity_layers / the_selector_breaks_a_score_tie_on_workload_then_creation_order
# ---------------------------------------------------------------------------
def _two_tied_candidates_one_of_them_busier(api):
    """Two identically competent RNs whose match scores tie at 60, registered so
    that the *busier* one is the older row.

    The busy nurse already holds a two-hour Tuesday assignment on a second
    child's case, which is 120 minutes - short of one complete four-hour block,
    so PRD 3.6 deducts nothing and the two scores stay level. Neither case names
    a `continuity_nurse_id`, so neither candidate collects continuity points.
    """
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)
    payer = fx.create_payer(api)

    patient = fx.create_patient(api, payer["id"])
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    authorization = fx.create_authorization(api, plan["id"], payer["id"], plan["version"])
    fx.activate_authorization(api, authorization["id"], payer["id"])

    other_patient = fx.create_patient(
        api, payer["id"], full_name="Eli Navarro", date_of_birth="2018-02-02"
    )
    other_plan = fx.create_submitted_plan_of_care(api, other_patient["id"])
    other_authorization = fx.create_authorization(
        api, other_plan["id"], payer["id"], other_plan["version"]
    )
    fx.activate_authorization(api, other_authorization["id"], payer["id"])

    # Registration order matters: the busy nurse is deliberately the older row.
    busy_nurse = fx.create_nurse_with_skills(api)
    free_nurse = fx.create_nurse_with_skills(
        api, full_name="Dana Ross", license_number="RN-100002"
    )

    other_case = fx.open_case(api, other_patient["id"], other_authorization["id"])
    other_case = fx.activate_case(api, other_case["id"])
    other_shift = fx.publish_shift(
        api, other_case["id"], WEEK32_TUESDAY_08, WEEK32_TUESDAY_10
    )
    fx.assign_nurse(api, other_shift["id"], busy_nurse["id"])

    case = fx.open_case(api, patient["id"], authorization["id"])
    case = fx.activate_case(api, case["id"])
    target_shift = fx.publish_shift(
        api, case["id"], WEEK32_THURSDAY_08, WEEK32_THURSDAY_16
    )
    return busy_nurse, free_nurse, target_shift


def test_the_candidate_read_breaks_the_score_tie_on_workload_not_creation_order(api):
    """Both nurses score exactly 60 under PRD 3.6: 0 continuity points (neither is
    the case's `continuity_nurse_id` and the strict continuity score is 0), 20
    skill points for the two matched `required_skills`, 10 more because an `RN`
    faces a `VENT` shift, and a full 30 availability points because 120 scheduled
    minutes is not "a whole multiple of 240 minutes". With the scores level, PRD
    3.6 breaks the tie "first by the nurse's scheduled minutes in that same week
    window ascending", so the idle nurse leads `ranked_nurse_ids` and is the
    `selected_nurse_id`; `created_at` never gets consulted.

    Design: Corner/complexity_layers/the_selector_breaks_a_score_tie_on_workload_then_creation_order
    """
    busy_nurse, free_nurse, target_shift = _two_tied_candidates_one_of_them_busier(api)

    candidates = validate_success(
        api.get_staffing_candidates(target_shift["id"], SCHEDULER)
    )

    assert candidates["shift_id"] == target_shift["id"], candidates
    assert candidates["candidate_count"] == 2, candidates
    assert candidates["top_match_score"] == 60, candidates
    assert candidates["ranked_nurse_ids"] == [
        free_nurse["id"],
        busy_nurse["id"],
    ], candidates
    assert candidates["selected_nurse_id"] == free_nurse["id"], candidates


def test_auto_staff_selects_the_least_loaded_of_two_tied_candidates(api):
    """PRD 3.6 makes the selector take "the first row of the ordered list", so the
    committing call must agree with the candidates read: the idle nurse is
    assigned even though the busy one is the older row, and
    `match_score_at_assignment` freezes the tied score of 60. PRD 2.12 then moves
    exactly the target shift's 480 `scheduled_minutes` onto that nurse's
    `scheduled_minutes_this_week` and leaves the busy nurse's Tuesday 120
    untouched.

    Design: Corner/complexity_layers/the_selector_breaks_a_score_tie_on_workload_then_creation_order
    """
    busy_nurse, free_nurse, target_shift = _two_tied_candidates_one_of_them_busier(api)

    assignment = validate_success(
        api.auto_staff_shift(
            target_shift["id"],
            f.auto_staff_payload(target_shift["version"]),
            SCHEDULER,
        ),
        201,
    )

    assert assignment["nurse_id"] == free_nurse["id"], assignment
    assert assignment["match_score_at_assignment"] == 60, assignment
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment
    assert assignment["continuity_match"] is False, assignment

    assert fx.refresh_nurse(api, busy_nurse["id"])["scheduled_minutes_this_week"] == 120
    assert fx.refresh_nurse(api, free_nurse["id"])["scheduled_minutes_this_week"] == 480


# ---------------------------------------------------------------------------
# consistency_model / the_hold_response_already_carries_every_recomputed_figure
# ---------------------------------------------------------------------------
def _active_case_with_one_assigned_and_one_open_shift(api):
    """The canonical ACTIVE case with a Wednesday shift assigned to its continuity
    nurse and a Friday shift still OPEN - two rows for the hold to cascade into."""
    base = fx.setup_baseline(api)
    assigned_shift = fx.publish_shift(
        api, base.case_id, WEEK32_WEDNESDAY_08, WEEK32_WEDNESDAY_16
    )
    assignment = fx.assign_nurse(api, assigned_shift["id"], base.nurse_id)
    open_shift = fx.publish_shift(api, base.case_id, WEEK32_FRIDAY_08, WEEK32_FRIDAY_16)
    return base, assigned_shift, assignment, open_shift


def test_the_hold_write_response_already_reports_the_recomputed_case_figures(api):
    """PRD 2.2 returns "the affected resource" in a write's own `data`, and PRD
    2.10 requires the hold cascade to re-derive the case's `unfilled_shift_count`
    and `fill_rate` before that response is built. Cancelling both shifts empties
    the fill-rate denominator, and PRD 3.4 pins that case to exactly 1.0000 "when
    the denominator is zero" while `unfilled_shift_count` - which counts only
    `OPEN` or `ESCALATED` shifts - falls to 0. Re-reading the case afterwards can
    therefore add nothing: the four fields are identical.

    Design: Corner/consistency_model/the_hold_response_already_carries_every_recomputed_figure
    """
    base, _assigned_shift, _assignment, _open_shift = (
        _active_case_with_one_assigned_and_one_open_shift(api)
    )

    held = validate_success(
        api.hold_case(
            base.case_id,
            f.hold_payload(HoldReason.FAMILY_REQUEST.value),
            CLINICAL_SUPERVISOR,
        ),
        200,
    )

    assert held["status"] == CaseStatus.ON_HOLD.value, held
    assert held["hold_reason"] == HoldReason.FAMILY_REQUEST.value, held
    assert held["unfilled_shift_count"] == 0, held
    assert_ratio(held, "fill_rate", 1.0000)

    reread = fx.refresh_case(api, base.case_id)
    for field in ("status", "hold_reason", "unfilled_shift_count", "fill_rate"):
        assert reread[field] == held[field], (field, reread, held)


def test_the_hold_cascade_is_visible_in_every_related_row_with_no_intervening_call(api):
    """PRD 2.10 insists the chain "runs to its end" inside the one hold request:
    both future shifts become `CANCELLED` with `cancel_reason` `CASE_HOLD`, the
    assigned shift's `ACTIVE` assignment is cancelled with the same reason, and
    the authorization's `hours_committed_this_week` and
    `hours_remaining_this_week` are re-derived. Since PRD 2.12 counts only
    `ASSIGNED` or `COMPLETED` shifts, the single 480-minute commitment is released
    in full: 0.00 committed against the 40.00-hour grant, with the whole 40.00
    remaining. No checkpoint or second write is needed to make any of this true.

    Design: Corner/consistency_model/the_hold_response_already_carries_every_recomputed_figure
    """
    base, assigned_shift, assignment, open_shift = (
        _active_case_with_one_assigned_and_one_open_shift(api)
    )

    validate_success(
        api.hold_case(
            base.case_id,
            f.hold_payload(HoldReason.FAMILY_REQUEST.value),
            CLINICAL_SUPERVISOR,
        ),
        200,
    )

    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 0.00)
    assert_hours(authorization, "hours_remaining_this_week", 40.00)

    cancelled = validate_success(api.get_assignment(assignment["id"], SCHEDULER))
    assert cancelled["status"] == AssignmentStatus.CANCELLED.value, cancelled
    assert (
        cancelled["cancel_reason"] == AssignmentCancelReason.CASE_HOLD.value
    ), cancelled

    rows, meta = validate_paginated(
        api.list_shifts(SCHEDULER, {"case_id": base.case_id})
    )
    assert meta["total_count"] == 2, rows
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {assigned_shift["id"], open_shift["id"]}, rows
    for shift in rows:
        assert shift["staffing_status"] == StaffingStatus.CANCELLED.value, shift
        assert shift["cancel_reason"] == ShiftCancelReason.CASE_HOLD.value, shift
