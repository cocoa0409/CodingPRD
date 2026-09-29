"""Derived arithmetic: match scores, candidate pools, supervisory cadences, fill
rate and the settled renewal ratio.

Every figure here is a computation the PRD pins exactly - match points in
Section 3.6, the acuity cadence in Section 3.4, the four-decimal fill rate in
Section 3.4, and the settled-basis renewal gate in Sections 3.3 and 3.9. The
tests fix one world and read the number back, so a rounding or anchor mistake
cannot hide behind a plausible-looking value.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import canonicalize_instant
from test_helpers.assertions import assert_ratio, assert_units
from test_helpers.test_users import AGENCY_ADMIN, CLINICAL_SUPERVISOR, SCHEDULER
from test_helpers.types import (
    AssignmentStatus,
    AuthorizationStatus,
    LicenseType,
    NurseStatus,
    Skill,
    SupervisoryStatus,
    UtilizationBasis,
    VisitOutcome,
)

WEEK32_WED_08 = "2026-08-05T08:00:00Z"
WEEK32_WED_16 = "2026-08-05T16:00:00Z"
WEEK32_WED_18 = "2026-08-05T18:00:00Z"
WEEK32_THU_08 = "2026-08-06T08:00:00Z"
WEEK32_THU_16 = "2026-08-06T16:00:00Z"
WEEK32_THU_18 = "2026-08-06T18:00:00Z"
WEEK32_FRI_08 = "2026-08-07T08:00:00Z"
WEEK32_FRI_16 = "2026-08-07T16:00:00Z"

#: Tuesday 06:00Z - the instant the DEFICIENT visit is recorded at. PRD 3.4
#: forbids a `visit_at` after the current logical clock, so the clock is moved
#: here first and the visit is recorded at exactly that instant.
CLOCK_WEEK32_TUESDAY_06 = "2026-08-04T06:00:00Z"
#: Case created at Monday 06:00Z plus the 14-day vent cadence.
BASE_CADENCE_DUE_AT = "2026-08-17T06:00:00.000Z"
#: The Tuesday visit plus the halved 7-day cadence.
HALVED_CADENCE_DUE_AT = "2026-08-11T06:00:00.000Z"


def _three_eligible_nurses_on_one_vent_shift(api):
    """One vent shift and three unloaded nurses: the continuity RN, another RN
    and an LPN, all holding VALID TRACH and VENT competencies."""
    base = fx.setup_baseline(api, with_case=False)
    nurse2 = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Dana Ross",
        license_number="RN-100002",
    )
    nurse3 = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Ivy Lane",
        license_type=LicenseType.LPN.value,
        license_number="LPN-200001",
    )
    case = fx.open_case(
        api,
        base.patient_id,
        base.authorization_id,
        continuity_nurse_id=base.nurse_id,
    )
    fx.activate_case(api, case["id"])
    shift = fx.publish_shift(api, case["id"], WEEK32_WED_08, WEEK32_WED_16)
    return base, nurse2, nurse3, shift


def test_candidate_ranking_scores_the_continuity_rn_at_one_hundred(api):
    """PRD 3.6 adds three signals. The continuity nurse takes 40 continuity
    points; the two others take `min(30, strict continuity score)` which is 0 on
    an empty history. All three match both `required_skills`, so skill points are
    2 x 10 = 20, and the two `RN` rows collect the further 10 points because
    `VENT` is required. Nobody has scheduled minutes, so availability is the full
    30. That is 100, 60 and 50, and `ranked_nurse_ids` orders them by score
    descending with `top_match_score` reporting the head of the list.

    Design: Corner/calculations/match_score_reaches_one_hundred_for_the_rn_continuity_nurse
    """
    base, nurse2, nurse3, shift = _three_eligible_nurses_on_one_vent_shift(api)

    candidates = validate_success(api.get_staffing_candidates(shift["id"], SCHEDULER))

    assert candidates["shift_id"] == shift["id"]
    assert candidates["candidate_count"] == 3, candidates
    assert candidates["ranked_nurse_ids"] == [
        base.nurse_id,
        nurse2["id"],
        nurse3["id"],
    ], candidates
    assert candidates["selected_nurse_id"] == base.nurse_id, candidates
    assert candidates["top_match_score"] == 100, candidates


def test_manual_assignment_freezes_the_hundred_point_match_score(api):
    """PRD 3.5 attaches two computed values to a new `ShiftAssignment`:
    `continuity_match`, true exactly when the nurse is the case's
    `continuity_nurse_id`, and `match_score_at_assignment`, the score evaluated
    at creation time. A manual assignment stores it just as an automatic one
    does, so naming the continuity RN by hand must record the same 100 the
    candidates read advertised.

    Design: Corner/calculations/match_score_reaches_one_hundred_for_the_rn_continuity_nurse
    """
    base, _nurse2, _nurse3, shift = _three_eligible_nurses_on_one_vent_shift(api)

    assignment = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], base.nurse_id, shift["version"]),
            SCHEDULER,
        ),
        201,
    )

    assert assignment["nurse_id"] == base.nurse_id
    assert assignment["match_score_at_assignment"] == 100, assignment
    assert assignment["continuity_match"] is True, assignment
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment


def _one_eligible_nurse_among_five(api):
    """Five nurses, four of which fail exactly one clause of the PRD 3.6 pool
    predicate: SUSPENDED status, membership in `excluded_nurse_ids`, no VENT
    competency row, and a licence lapsing the day before the shift ends."""
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)

    suspended = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Sam Ott",
        license_number="RN-100011",
    )
    validate_success(
        api.set_nurse_status(
            suspended["id"],
            F.nurse_status_payload(NurseStatus.SUSPENDED.value),
            AGENCY_ADMIN,
        )
    )
    excluded = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Rae Kim",
        license_number="RN-100012",
    )
    missing_skill = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value,),
        full_name="Tom Blake",
        license_number="RN-100013",
    )
    lapsed_licence = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Gia Cole",
        license_number="RN-100014",
        license_expires_on="2026-08-04",
    )
    eligible = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Dana Ross",
        license_number="RN-100002",
    )

    case = fx.open_case(
        api,
        base.patient_id,
        base.authorization_id,
        excluded_nurse_ids=[excluded["id"]],
    )
    fx.activate_case(api, case["id"])
    shift = fx.publish_shift(api, case["id"], WEEK32_WED_08, WEEK32_WED_16)
    return {
        "base": base,
        "suspended": suspended["id"],
        "excluded": excluded["id"],
        "missing_skill": missing_skill["id"],
        "lapsed_licence": lapsed_licence["id"],
        "eligible": eligible["id"],
        "case": case,
        "shift": shift,
    }


def test_candidate_pool_admits_only_the_one_eligible_nurse(api):
    """PRD 3.6 admits a nurse only when every clause holds: `status` `ACTIVE`,
    `license_expires_on` strictly after the shift's `end_at` date, absence from
    the case's `excluded_nurse_ids`, and a `VALID` competency for every skill in
    `required_skills`. Each of four nurses breaks exactly one clause, so
    `candidate_count` is 1. The survivor is a non-continuity `RN`: 0 continuity +
    20 skill + 10 RN/VENT bonus + 30 availability = 60.

    Design: Corner/calculations/candidate_pool_filters_out_every_ineligible_nurse
    """
    world = _one_eligible_nurse_among_five(api)

    candidates = validate_success(
        api.get_staffing_candidates(world["shift"]["id"], SCHEDULER)
    )

    assert candidates["candidate_count"] == 1, candidates
    assert candidates["ranked_nurse_ids"] == [world["eligible"]], candidates
    assert candidates["selected_nurse_id"] == world["eligible"], candidates
    assert candidates["top_match_score"] == 60, candidates

    for label in ("suspended", "excluded", "missing_skill", "lapsed_licence"):
        assert world[label] not in candidates["ranked_nurse_ids"], (
            f"the {label} nurse must not be a candidate: {candidates}"
        )


def test_auto_staff_selects_the_only_eligible_nurse(api):
    """PRD 3.6 makes the automatic selector commit to the head of the same
    ordered pool the candidates read exposes, and the resulting assignment is
    identical in every respect to a manual one. With a single-member pool the
    selection is forced.

    Design: Corner/calculations/candidate_pool_filters_out_every_ineligible_nurse
    """
    world = _one_eligible_nurse_among_five(api)
    shift = world["shift"]

    assignment = validate_success(
        api.auto_staff_shift(
            shift["id"], F.auto_staff_payload(shift["version"]), SCHEDULER
        ),
        201,
    )

    assert assignment["nurse_id"] == world["eligible"], assignment
    assert assignment["status"] == AssignmentStatus.ACTIVE.value, assignment
    assert assignment["match_score_at_assignment"] == 60, assignment
    assert assignment["continuity_match"] is False, assignment


def test_vent_base_cadence_is_fourteen_days_from_case_creation(api):
    """PRD 3.4 fixes the base cadence at 14 days when the patient's
    `requires_vent` is true, and anchors it on the case's own `created_at` while
    the case has no supervisory visit. The canonical case is opened at Monday
    06:00Z, so `next_supervisory_visit_due_at` is 2026-08-17T06:00:00Z and
    `supervisory_status` still reads `CURRENT`.

    Design: Corner/calculations/cadence_constants_halve_after_a_deficient_visit
    """
    base = fx.setup_baseline(api)

    case = fx.refresh_case(api, base.case_id)

    assert case["next_supervisory_visit_due_at"] == BASE_CADENCE_DUE_AT, case
    assert case["supervisory_status"] == SupervisoryStatus.CURRENT.value, case


def test_deficient_visit_halves_the_vent_cadence_to_seven_days(api):
    """PRD 3.4 halves the applied cadence and rounds up when the latest visit's
    `outcome` is `DEFICIENT`: ceil(14 / 2) = 7 days, stored on the visit as
    `cadence_days_applied`. The anchor becomes that visit's `visit_at`, so
    `next_due_at` is 2026-08-11T06:00:00Z rather than the 2026-08-17T06:00:00Z a
    base cadence from `created_at` would have produced, and the case's
    `next_supervisory_visit_due_at` is set to the same instant. With the clock
    sitting exactly on the due instant, `supervisory_status` is already `OVERDUE`.

    Design: Corner/calculations/cadence_constants_halve_after_a_deficient_visit
    """
    base = fx.setup_baseline(api)

    # PRD 3.4 forbids a `visit_at` after the current logical clock, so the clock
    # moves to the visit instant first; equality is explicitly allowed.
    fx.set_clock(api, CLOCK_WEEK32_TUESDAY_06)
    visit = validate_success(
        api.create_supervisory_visit(
            base.case_id,
            F.supervisory_visit_payload(
                CLOCK_WEEK32_TUESDAY_06,
                VisitOutcome.DEFICIENT.value,
                notes="suction technique not per plan; re-education required",
            ),
            CLINICAL_SUPERVISOR,
        ),
        201,
    )

    assert visit["cadence_days_applied"] == 7, visit
    assert visit["next_due_at"] == HALVED_CADENCE_DUE_AT, visit
    assert visit["next_due_at"] != BASE_CADENCE_DUE_AT, visit

    case = fx.refresh_case(api, base.case_id)
    assert case["next_supervisory_visit_due_at"] == HALVED_CADENCE_DUE_AT, case

    fx.set_clock(api, "2026-08-11T06:00:00Z")
    overdue = fx.refresh_case(api, base.case_id)
    assert overdue["supervisory_status"] == SupervisoryStatus.OVERDUE.value, overdue


def test_fill_rate_rounds_two_thirds_to_four_decimals(api):
    """PRD 3.4 counts every non-`CANCELLED` shift starting between the clock and
    the authorization's `effective_end` in the denominator, and the `ASSIGNED`,
    `COMPLETED` or `PARENT_BACKUP` ones in the numerator. Two of three forward
    shifts are staffed, so `fill_rate` is round_half_up(2 / 3, 4) = 0.6667 - four
    decimals, per PRD 2.9, not 0.67 and not 0.6666. `unfilled_shift_count` is the
    separate raw count of `OPEN` or `ESCALATED` forward shifts, which is 1, and
    the nurse's conserved `scheduled_minutes_this_week` is 2 x 480 = 960.

    Design: Corner/calculations/fill_rate_rounds_two_thirds_to_four_decimals
    """
    base = fx.setup_baseline(api)
    shift1 = fx.publish_shift(api, base.case_id, WEEK32_WED_08, WEEK32_WED_16)
    shift2 = fx.publish_shift(api, base.case_id, WEEK32_THU_08, WEEK32_THU_16)
    fx.publish_shift(api, base.case_id, WEEK32_FRI_08, WEEK32_FRI_16)

    fx.assign_nurse(api, shift1["id"], base.nurse_id)
    fx.assign_nurse(api, shift2["id"], base.nurse_id)

    case = fx.refresh_case(api, base.case_id)
    assert_ratio(case, "fill_rate", 0.6667)
    assert case["unfilled_shift_count"] == 1, case

    nurse = fx.refresh_nurse(api, base.nurse_id)
    assert nurse["scheduled_minutes_this_week"] == 960, nurse


def _two_ten_hour_visits_submitted(api):
    """Two 600-minute visits worked end to end in ISO week 32 and submitted for
    billing, with the clock left in week 33 so week 32 is the last completed
    ISO week."""
    base = fx.setup_baseline(api)

    shift1 = fx.publish_shift(api, base.case_id, WEEK32_WED_08, WEEK32_WED_18)
    assignment1 = fx.assign_nurse(api, shift1["id"], base.nurse_id)
    shift2 = fx.publish_shift(api, base.case_id, WEEK32_THU_08, WEEK32_THU_18)
    assignment2 = fx.assign_nurse(api, shift2["id"], base.nurse_id)

    timesheet1 = fx.work_shift(
        api,
        shift1["id"],
        base.nurse_id,
        assignment1["id"],
        clock_in_at=WEEK32_WED_08,
        clock_out_at=WEEK32_WED_18,
    )
    fx.submit_timesheet(api, timesheet1["id"])
    timesheet2 = fx.work_shift(
        api,
        shift2["id"],
        base.nurse_id,
        assignment2["id"],
        clock_in_at=WEEK32_THU_08,
        clock_out_at=WEEK32_THU_18,
    )
    fx.submit_timesheet(api, timesheet2["id"])

    fx.set_clock(api, C.CLOCK_WEEK33_MONDAY_06)
    return base, timesheet1, timesheet2


def test_settled_week_is_exactly_half_the_approved_minutes(api):
    """PRD 3.3 builds the SETTLED basis from timesheets that are `SUBMITTED` or
    `BILL_ACCEPTED`, summing each row's own `gross_billable_units` and
    `net_billable_units`. Each visit caps at its 600 scheduled minutes and bills
    600 / 15 = 40 units with no deduction, since the method is `GPS`, the shift
    carries no exception and the clock-in was punctual. That is 80 gross and 80
    net units, `settled_minutes` of 80 x 15 = 1200 against the 40 x 60 = 2400
    minute ceiling, so `utilization_ratio` is exactly 0.5000. The window is the
    half-open ISO week of PRD 2.5, reported as the `week_start` and `week_end`
    instants 2026-08-03T00:00:00Z and 2026-08-10T00:00:00Z.

    Design: Corner/calculations/renewal_gate_passes_at_exactly_half_the_approved_minutes
    """
    base, _timesheet1, _timesheet2 = _two_ten_hour_visits_submitted(api)

    settled = fx.utilization(
        api, base, UtilizationBasis.SETTLED.value, C.WEEK32_START
    )

    assert_units(settled, "settled_gross_units", 80)
    assert_units(settled, "settled_net_units", 80)
    assert settled["settled_minutes"] == 1200, settled
    assert_ratio(settled, "utilization_ratio", 0.5000)
    assert settled["week_start"] == canonicalize_instant(C.WEEK32_START), settled
    assert settled["week_end"] == canonicalize_instant(C.WEEK32_END), settled


def test_renewal_passes_at_exactly_the_half_ratio_and_chains(api):
    """PRD 3.9 gates renewal on the settled utilization of the last completed ISO
    week and rejects with `ERR_RENEWAL_UTILIZATION_TOO_LOW` only when that ratio
    is *below* 0.5000. Week 32 settles at exactly 1200 / 2400 = 0.5000, so the
    boundary is inclusive and the call succeeds: a successor authorization is
    created `PENDING` with `renewal_chain_depth` one greater than the
    predecessor's 0, `supersedes_authorization_id` naming the predecessor and
    `effective_start` continuing from the predecessor's `effective_end`. The
    predecessor is not touched - it stays `ACTIVE` until the successor activates.

    Design: Corner/calculations/renewal_gate_passes_at_exactly_half_the_approved_minutes
    """
    base, _timesheet1, _timesheet2 = _two_ten_hour_visits_submitted(api)

    successor = validate_success(
        api.renew_authorization(
            base.authorization_id,
            F.renew_payload("2027-02-01T00:00:00Z", 40.0),
            base.payer_headers,
        ),
        201,
    )

    assert successor["id"] != base.authorization_id, successor
    assert successor["status"] == AuthorizationStatus.PENDING.value, successor
    assert successor["renewal_chain_depth"] == 1, successor
    assert successor["supersedes_authorization_id"] == base.authorization_id, successor
    assert successor["effective_start"] == canonicalize_instant(
        C.AUTH_EFFECTIVE_END
    ), successor

    predecessor = fx.refresh_authorization(api, base)
    assert predecessor["status"] == AuthorizationStatus.ACTIVE.value, predecessor
    assert predecessor["renewal_chain_depth"] == 0, predecessor
