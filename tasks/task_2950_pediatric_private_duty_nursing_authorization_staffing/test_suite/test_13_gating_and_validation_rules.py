"""Gates and refusals: which check fires, with which code, and what it leaves behind.

Every case here stages a request that must be refused and then re-stages the
same request in a world where the gate is satisfied, so the rule is shown to be
live rather than merely absent. Where two checks are armed at once the ascending
priority list of PRD 2.8 decides the answer, and a refused call is expected to
mutate nothing at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import canonicalize_instant
from test_helpers.api_errors import (
    ERR_APPROVED_EXCEEDS_REQUESTED,
    ERR_CASE_ON_HOLD,
    ERR_CLOCK_IN_TOO_EARLY,
    ERR_COMPETENCY_DUPLICATE,
    ERR_COMPETENCY_EXPIRED,
    ERR_DECIDED_HOURS_OUT_OF_RANGE,
    ERR_DISPUTE_ALREADY_OPEN,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_EVV_NOT_VERIFIED,
    ERR_LICENSE_NUMBER_TAKEN,
    ERR_NO_ELIGIBLE_NURSE,
    ERR_NO_PARENT_BACKUP,
    ERR_NURSE_EXCLUDED_FROM_CASE,
    ERR_NURSE_LICENSE_EXPIRED,
    ERR_NURSE_SKILL_MISMATCH,
    ERR_PAYER_HOUR_CAP_EXCEEDED,
    ERR_REDUCTION_NOT_EFFECTIVE,
    ERR_RENEWAL_UTILIZATION_TOO_LOW,
    ERR_SHIFT_OUTSIDE_AUTH_WINDOW,
    ERR_SUPERVISORY_VISIT_OVERDUE,
)
from test_helpers.assertions import assert_hours, assert_ratio, assert_total_count
from test_helpers.test_users import (
    AGENCY_ADMIN,
    CASE_MANAGER,
    CASE_MANAGER_2,
    CLINICAL_SUPERVISOR,
    CLINICAL_SUPERVISOR_2,
    SCHEDULER,
    make_nurse_headers,
    make_payer_reviewer_headers,
)
from test_helpers.types import (
    AuthorizationStatus,
    CaseStatus,
    CompetencyStatus,
    DisputeOutcome,
    DisputeStatus,
    EscalationTier,
    EvvMethod,
    EvvStatus,
    HoldReason,
    LicenseType,
    Skill,
    StaffingStatus,
    SupervisoryStatus,
    TimesheetStatus,
    UtilizationBasis,
    VisitOutcome,
)

WEEK32_WED_08 = "2026-08-05T08:00:00Z"
WEEK32_WED_16 = "2026-08-05T16:00:00Z"
WEEK32_THU_08 = "2026-08-06T08:00:00Z"
WEEK32_THU_16 = "2026-08-06T16:00:00Z"

#: The clock instant the DEFICIENT supervisory visit is recorded at. PRD 3.4
#: forbids a `visit_at` after the current logical clock, so the clock is moved
#: here first and the visit is recorded at exactly that instant.
CLOCK_WEEK32_TUESDAY_06 = "2026-08-04T06:00:00Z"
#: That visit plus the halved 7-day vent cadence: the case is OVERDUE here.
CADENCE_DUE_AT = "2026-08-11T06:00:00Z"
#: A PASS visit at the due instant plus the full 14-day vent cadence.
RESTORED_DUE_AT = "2026-08-25T06:00:00.000Z"
#: The clock plus the payer's 10-day `reduction_notice_days`.
REDUCTION_EFFECTIVE_AT = "2026-08-13T06:00:00Z"


def _submitted_plan_requesting_fifty_six_hours(api):
    """The canonical payer with an 84-hour cap and a SUBMITTED plan of care
    requesting 56 hours a week."""
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)
    payer = fx.create_payer(api)
    patient = fx.create_patient(api, payer["id"])
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    return payer, plan


def test_the_payer_cap_outranks_the_requested_hours_ceiling(api):
    """Two fiscal ceilings guard an authorization: PRD 2.8 step 34 caps
    `approved_hours_per_week` at the payer's `weekly_hour_cap` of 84 and step 35
    caps it at the plan's `requested_hours_per_week` of 56. An approval of 90
    breaks both, and because checks run in ascending priority order the answer is
    the lower-numbered step 34, `ERR_PAYER_HOUR_CAP_EXCEEDED`, never
    `ERR_APPROVED_EXCEEDS_REQUESTED`. An approval of 60 breaks step 35 alone and
    reports it, which proves the outranked check is live rather than missing.

    Design: Corner/validations/fiscal_ceilings_reject_the_payer_cap_before_the_requested_hours
    """
    payer, plan = _submitted_plan_requesting_fifty_six_hours(api)
    payer_headers = make_payer_reviewer_headers(payer["id"])

    both_broken = api.create_authorization(
        F.authorization_payload(
            plan["id"], payer["id"], plan["version"], approved_hours_per_week=90.0
        ),
        payer_headers,
    )
    validate_error(both_broken, ERR_PAYER_HOUR_CAP_EXCEEDED, 422)

    only_requested_broken = api.create_authorization(
        F.authorization_payload(
            plan["id"], payer["id"], plan["version"], approved_hours_per_week=60.0
        ),
        payer_headers,
    )
    validate_error(only_requested_broken, ERR_APPROVED_EXCEEDS_REQUESTED, 422)


def test_an_authorization_inside_both_ceilings_is_issued_after_the_rejections(api):
    """PRD 2.5 makes a refused call a no-op, so neither fiscal rejection may
    advance the plan of care's `version`: the third call reuses the very same
    `expected_plan_of_care_version` and is accepted. 40 hours sits under both the
    84-hour cap and the 56-hour request, and PRD 3.3 creates the authorization in
    `PENDING` with `renewal_chain_depth` 0.

    Design: Corner/validations/fiscal_ceilings_reject_the_payer_cap_before_the_requested_hours
    """
    payer, plan = _submitted_plan_requesting_fifty_six_hours(api)
    payer_headers = make_payer_reviewer_headers(payer["id"])

    for hours in (90.0, 60.0):
        api.create_authorization(
            F.authorization_payload(
                plan["id"], payer["id"], plan["version"], approved_hours_per_week=hours
            ),
            payer_headers,
        )

    unchanged_plan = validate_success(api.get_plan_of_care(plan["id"], CASE_MANAGER))
    assert unchanged_plan["version"] == plan["version"], unchanged_plan

    authorization = validate_success(
        api.create_authorization(
            F.authorization_payload(
                plan["id"], payer["id"], plan["version"], approved_hours_per_week=40.0
            ),
            payer_headers,
        ),
        201,
    )

    assert_hours(authorization, "approved_hours_per_week", 40.00)
    assert authorization["status"] == AuthorizationStatus.PENDING.value, authorization


def _nurse_holding_one_trach_competency(api):
    """One RN on licence RN-100001 with a single VALID TRACH competency."""
    fx.set_clock(api, C.CLOCK_WEEK32_MONDAY_06)
    nurse = fx.register_nurse(api)
    competency = fx.attest_competency(api, nurse["id"], Skill.TRACH.value)
    return nurse, competency


def test_duplicate_licence_numbers_and_duplicate_competencies_are_conflicts(api):
    """PRD 2.8 step 30 makes `license_number` unique across the whole roster, so a
    second nurse claiming RN-100001 is `ERR_LICENSE_NUMBER_TAKEN` even under a
    different `license_type`. Step 31 allows at most one competency per nurse per
    `skill` in any status other than `REVOKED`, so a second TRACH attestation for
    the same nurse is `ERR_COMPETENCY_DUPLICATE`. Both are 409 conflicts in the
    PRD 5 catalogue rather than 422 validation failures.

    Design: Corner/validations/uniqueness_rules_bite_on_licence_numbers_and_competencies
    """
    nurse, _competency = _nurse_holding_one_trach_competency(api)

    duplicate_licence = api.create_nurse(
        F.nurse_payload(
            full_name="Other Nurse",
            license_type=LicenseType.LPN.value,
            license_number=C.NURSE_LICENSE_NUMBER,
        ),
        AGENCY_ADMIN,
    )
    validate_error(duplicate_licence, ERR_LICENSE_NUMBER_TAKEN, 409)

    duplicate_skill = api.create_competency(
        nurse["id"],
        F.competency_payload(
            Skill.TRACH.value, validated_on="2026-07-01", expires_on="2027-08-01"
        ),
        CLINICAL_SUPERVISOR,
    )
    validate_error(duplicate_skill, ERR_COMPETENCY_DUPLICATE, 409)


def test_revoking_a_competency_frees_the_skill_for_re_attestation(api):
    """The uniqueness set of PRD 2.8 step 31 excludes `REVOKED` rows, so revoking
    the TRACH competency releases the (nurse, skill) pair and the identical
    attestation that was just refused now succeeds with `status` `VALID`. PRD 2.4
    derives `verified_skills` only from `VALID` rows whose `expires_on` is after
    the clock date, so the revoked row contributes nothing and the nurse still
    reads exactly one verified skill.

    Design: Corner/validations/uniqueness_rules_bite_on_licence_numbers_and_competencies
    """
    nurse, competency = _nurse_holding_one_trach_competency(api)

    revoked = validate_success(
        api.revoke_competency(
            competency["id"],
            F.revoke_competency_payload("return demonstration failed on re-check"),
            CLINICAL_SUPERVISOR,
        )
    )
    assert revoked["status"] == CompetencyStatus.REVOKED.value, revoked

    re_attested = validate_success(
        api.create_competency(
            nurse["id"],
            F.competency_payload(
                Skill.TRACH.value, validated_on="2026-07-01", expires_on="2027-08-01"
            ),
            CLINICAL_SUPERVISOR,
        ),
        201,
    )
    assert re_attested["status"] == CompetencyStatus.VALID.value, re_attested
    assert re_attested["id"] != competency["id"], re_attested

    refreshed = fx.refresh_nurse(api, nurse["id"])
    assert refreshed["verified_skills"] == [Skill.TRACH.value], refreshed


def test_a_shift_outside_either_end_of_the_grant_is_refused(api):
    """PRD 2.8 step 22 requires a published shift to sit inside the grant:
    `start_at` at or after the authorization's `effective_start` of
    2026-08-03T00:00:00Z and `end_at` at or before its `effective_end` of
    2026-11-01T00:00:00Z. A shift on 2026-08-02 breaches the lower bound and a
    shift running 2026-10-31T20:00Z to 2026-11-01T04:00Z breaches the upper one;
    both answer `ERR_SHIFT_OUTSIDE_AUTH_WINDOW`, so the check is two-sided.

    Design: Corner/validations/shifts_must_sit_inside_the_authorization_window
    """
    base = fx.setup_baseline(api, with_nurse=False)

    before_window = api.create_shift(
        F.shift_payload(
            base.case_id,
            "2026-08-02T08:00:00Z",
            "2026-08-02T16:00:00Z",
            [Skill.TRACH.value],
        ),
        SCHEDULER,
    )
    validate_error(before_window, ERR_SHIFT_OUTSIDE_AUTH_WINDOW, 422)

    after_window = api.create_shift(
        F.shift_payload(
            base.case_id,
            "2026-10-31T20:00:00Z",
            "2026-11-01T04:00:00Z",
            [Skill.TRACH.value],
        ),
        SCHEDULER,
    )
    validate_error(after_window, ERR_SHIFT_OUTSIDE_AUTH_WINDOW, 422)


def test_the_only_shift_inside_the_grant_is_published(api):
    """A 2026-08-05 08:00-16:00 shift sits wholly inside the same grant, so it is
    created with `scheduled_minutes` derived as the 480 whole minutes between its
    bounds (PRD 3.5). Because a refused publication creates nothing, the case then
    owns exactly one shift and the list read's `total_count` is 1.

    Design: Corner/validations/shifts_must_sit_inside_the_authorization_window
    """
    base = fx.setup_baseline(api, with_nurse=False)

    for start_at, end_at in (
        ("2026-08-02T08:00:00Z", "2026-08-02T16:00:00Z"),
        ("2026-10-31T20:00:00Z", "2026-11-01T04:00:00Z"),
    ):
        api.create_shift(
            F.shift_payload(base.case_id, start_at, end_at, [Skill.TRACH.value]),
            SCHEDULER,
        )

    shift = validate_success(
        api.create_shift(
            F.shift_payload(
                base.case_id, WEEK32_WED_08, WEEK32_WED_16, [Skill.TRACH.value]
            ),
            SCHEDULER,
        ),
        201,
    )
    assert shift["scheduled_minutes"] == 480, shift

    assert_total_count(api.list_shifts(SCHEDULER, {"case_id": base.case_id}), 1)


def _five_nurses_and_one_vent_shift(api):
    """One OPEN TRACH+VENT shift on 2026-08-05 and five nurses, four of whom break
    exactly one gate of the assignment gauntlet."""
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)

    excluded = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Rae Kim",
        license_number="RN-100012",
    )
    lapsed_licence = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value, Skill.VENT.value),
        full_name="Gia Cole",
        license_number="RN-100014",
        license_expires_on="2026-08-04",
    )
    no_vent_row = fx.create_nurse_with_skills(
        api,
        (Skill.TRACH.value,),
        full_name="Tom Blake",
        license_number="RN-100013",
    )
    expiring_vent = fx.register_nurse(
        api, full_name="Lea Marsh", license_number="RN-100015"
    )
    fx.attest_competency(api, expiring_vent["id"], Skill.TRACH.value)
    fx.attest_competency(api, expiring_vent["id"], Skill.VENT.value, expires_on="2026-08-05")
    qualified = fx.create_nurse_with_skills(
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
        "excluded": excluded["id"],
        "lapsed_licence": lapsed_licence["id"],
        "no_vent_row": no_vent_row["id"],
        "expiring_vent": expiring_vent["id"],
        "qualified": qualified["id"],
        "shift": shift,
    }


def test_each_ineligible_nurse_reports_its_own_first_failing_gate(api):
    """The eligibility gauntlet of PRD 2.8 runs 15, 17, 18 then 19, and each nurse
    here breaks exactly one of them on the same 2026-08-05 08:00-16:00 vent shift.
    Step 15 catches the nurse named in the case's `excluded_nurse_ids`. Step 17
    catches the licence expiring 2026-08-04, because `license_expires_on` must be
    strictly after the shift's `end_at` date. Step 18 catches the nurse with no
    `VENT` row at all - the PRD states a missing row is a mismatch rather than an
    expiry, so the answer is `ERR_NURSE_SKILL_MISMATCH` and not
    `ERR_COMPETENCY_EXPIRED`. Step 19 then catches the nurse whose `VENT`
    competency expires exactly on the shift's start date, which the PRD declares a
    failure.

    Design: Corner/validations/assignment_safety_gauntlet_reports_the_first_failing_gate
    """
    world = _five_nurses_and_one_vent_shift(api)
    shift = world["shift"]

    for nurse_key, expected_error in (
        ("excluded", ERR_NURSE_EXCLUDED_FROM_CASE),
        ("lapsed_licence", ERR_NURSE_LICENSE_EXPIRED),
        ("no_vent_row", ERR_NURSE_SKILL_MISMATCH),
        ("expiring_vent", ERR_COMPETENCY_EXPIRED),
    ):
        refused = api.create_assignment(
            F.assignment_payload(shift["id"], world[nurse_key], shift["version"]),
            SCHEDULER,
        )
        validate_error(refused, expected_error, 422)


def test_the_qualified_nurse_is_assigned_on_the_still_unchanged_shift_version(api):
    """Four refusals in a row must leave the shift untouched, so the accepted call
    carries the very same `expected_shift_version` the rejected ones did and still
    satisfies the optimistic-concurrency check of PRD 2.8 step 8. The fifth nurse
    passes every gate - not excluded, licence good to 2027-06-30, both required
    competencies `VALID` well past the shift - so the assignment is created.

    Design: Corner/validations/assignment_safety_gauntlet_reports_the_first_failing_gate
    """
    world = _five_nurses_and_one_vent_shift(api)
    shift = world["shift"]

    for nurse_key in ("excluded", "lapsed_licence", "no_vent_row", "expiring_vent"):
        api.create_assignment(
            F.assignment_payload(shift["id"], world[nurse_key], shift["version"]),
            SCHEDULER,
        )

    assignment = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], world["qualified"], shift["version"]),
            SCHEDULER,
        ),
        201,
    )

    assert assignment["nurse_id"] == world["qualified"], assignment
    assert fx.refresh_shift(api, shift["id"])["staffing_status"] == (
        StaffingStatus.ASSIGNED.value
    )


def _case_overdue_after_a_deficient_visit(api):
    """A vent case whose latest visit came back DEFICIENT, with the clock parked
    exactly on the resulting due instant and one future shift OPEN."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(
        api, base.case_id, "2026-08-12T08:00:00Z", "2026-08-12T16:00:00Z"
    )

    # PRD 3.4 forbids a `visit_at` after the current logical clock, so the clock
    # moves to the visit instant first; equality is explicitly allowed.
    fx.set_clock(api, CLOCK_WEEK32_TUESDAY_06)
    fx.record_supervisory_visit(
        api,
        base.case_id,
        CLOCK_WEEK32_TUESDAY_06,
        VisitOutcome.DEFICIENT.value,
        notes="ventilator circuit change not documented",
    )
    fx.set_clock(api, CADENCE_DUE_AT)
    return base, shift


def test_an_overdue_supervisory_cadence_blocks_the_assignment(api):
    """PRD 3.4 halves the 14-day vent cadence to 7 days after a `DEFICIENT` visit,
    so the visit of 2026-08-04T06:00Z makes the case due at 2026-08-11T06:00Z, and
    a clock sitting exactly on the due instant already reads `OVERDUE`. PRD 2.8
    step 20 then refuses the assignment with `ERR_SUPERVISORY_VISIT_OVERDUE`, a 409
    conflict, even though the nurse and the shift are otherwise impeccable.

    Design: Corner/validations/overdue_supervisory_visit_blocks_staffing_until_a_visit_is_recorded
    """
    base, shift = _case_overdue_after_a_deficient_visit(api)

    overdue_case = fx.refresh_case(api, base.case_id)
    assert overdue_case["supervisory_status"] == SupervisoryStatus.OVERDUE.value, overdue_case

    refused = api.create_assignment(
        F.assignment_payload(shift["id"], base.nurse_id, shift["version"]),
        SCHEDULER,
    )
    validate_error(refused, ERR_SUPERVISORY_VISIT_OVERDUE, 409)


def test_a_pass_visit_restores_the_cadence_and_unblocks_the_same_assignment(api):
    """PRD 3.4 applies the full base cadence again once the latest visit's
    `outcome` is `PASS`, measuring it from that visit's `visit_at`: 2026-08-11T06:00Z
    plus 14 days puts `next_due_at` at 2026-08-25T06:00Z and returns
    `supervisory_status` to `CURRENT`. The byte-identical assignment that was just
    refused - same nurse, same shift, same `expected_shift_version`, since the
    refusal changed nothing - is then accepted and the shift becomes `ASSIGNED`.

    Design: Corner/validations/overdue_supervisory_visit_blocks_staffing_until_a_visit_is_recorded
    """
    base, shift = _case_overdue_after_a_deficient_visit(api)
    api.create_assignment(
        F.assignment_payload(shift["id"], base.nurse_id, shift["version"]), SCHEDULER
    )

    visit = validate_success(
        api.create_supervisory_visit(
            base.case_id,
            F.supervisory_visit_payload(
                CADENCE_DUE_AT,
                VisitOutcome.PASS.value,
                notes="re-education complete, technique correct",
            ),
            CLINICAL_SUPERVISOR,
        ),
        201,
    )
    assert visit["cadence_days_applied"] == 14, visit
    assert visit["next_due_at"] == RESTORED_DUE_AT, visit

    restored_case = fx.refresh_case(api, base.case_id)
    assert restored_case["supervisory_status"] == SupervisoryStatus.CURRENT.value, restored_case

    assignment = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], base.nurse_id, shift["version"]),
            SCHEDULER,
        ),
        201,
    )
    assert assignment["status"] == "ACTIVE", assignment
    assert fx.refresh_shift(api, shift["id"])["staffing_status"] == (
        StaffingStatus.ASSIGNED.value
    )


def _escalated_shift_for_a_family_without_backup(api):
    """A tier-one escalated shift for a child whose `parent_backup_available` is
    false."""
    base = fx.setup_baseline(
        api, patient_overrides={"parent_backup_available": False}, with_nurse=False
    )
    shift = fx.publish_shift(api, base.case_id, WEEK32_THU_08, WEEK32_THU_16)
    escalated = validate_success(
        api.escalate_shift(
            shift["id"],
            F.escalate_payload("agency pool exhausted for the vent-qualified roster"),
            SCHEDULER,
        )
    )
    return base, shift, escalated


def test_the_parent_backup_route_is_refused_without_the_family_flag(api):
    """PRD 3.6 makes the first escalation move the shift `OPEN -> ESCALATED`, set
    `escalation_tier` to `TIER1_AGENCY_POOL` and stamp `escalated_at` with the
    logical clock of 2026-08-03T06:00Z. Tier two is then unreachable for this
    family: PRD 2.8 step 21 requires the patient's `parent_backup_available` to be
    true, so arranging the backup is refused with `ERR_NO_PARENT_BACKUP` and, a
    refusal being a no-op, the shift keeps both its `ESCALATED` status and its
    tier-one label.

    Design: Corner/validations/parent_backup_gate_depends_on_the_family_flag_and_routes_tier_three
    """
    _base, shift, escalated = _escalated_shift_for_a_family_without_backup(api)

    assert escalated["staffing_status"] == StaffingStatus.ESCALATED.value, escalated
    assert escalated["escalation_tier"] == EscalationTier.TIER1_AGENCY_POOL.value, escalated
    assert escalated["escalated_at"] == canonicalize_instant(C.CLOCK_WEEK32_MONDAY_06), escalated

    refused = api.parent_backup_shift(
        shift["id"], SCHEDULER, F.parent_backup_payload("asking the family to cover")
    )
    validate_error(refused, ERR_NO_PARENT_BACKUP, 422)

    unchanged = fx.refresh_shift(api, shift["id"])
    assert unchanged["staffing_status"] == StaffingStatus.ESCALATED.value, unchanged
    assert unchanged["escalation_tier"] == EscalationTier.TIER1_AGENCY_POOL.value, unchanged


def test_the_second_escalation_jumps_straight_to_tier_three(api):
    """PRD 3.6 splits the ladder on the same family flag: when
    `parent_backup_available` is false a second escalation of an already
    `ESCALATED` shift advances `escalation_tier` to `TIER3_PAYER_NOTIFICATION` and
    leaves `escalated_at` at its original value. `TIER2_PARENT_BACKUP` is therefore
    never visited - it is reachable only by actually arranging the backup, which
    this family cannot do.

    Design: Corner/validations/parent_backup_gate_depends_on_the_family_flag_and_routes_tier_three
    """
    _base, shift, escalated = _escalated_shift_for_a_family_without_backup(api)
    api.parent_backup_shift(
        shift["id"], SCHEDULER, F.parent_backup_payload("asking the family to cover")
    )

    advanced = validate_success(
        api.escalate_shift(
            shift["id"],
            F.escalate_payload("no family backup on file, notifying the payer"),
            SCHEDULER,
        )
    )

    assert advanced["escalation_tier"] == EscalationTier.TIER3_PAYER_NOTIFICATION.value, advanced
    assert advanced["escalated_at"] == escalated["escalated_at"], advanced
    assert advanced["staffing_status"] == StaffingStatus.ESCALATED.value, advanced


def _feeding_tube_case_on_a_manual_hold(api):
    """A feeding-tube child's case put on a manual FAMILY_REQUEST hold, staffed
    only by a nurse competent in TRACH and VENT."""
    base = fx.setup_baseline(
        api,
        patient_overrides={"requires_feeding_tube": True},
        continuity_nurse=False,
    )
    held = validate_success(
        api.hold_case(
            base.case_id,
            F.hold_payload(HoldReason.FAMILY_REQUEST.value),
            CLINICAL_SUPERVISOR,
        )
    )
    return base, held


def test_shift_publication_is_refused_while_the_case_is_on_hold(api):
    """PRD 2.8 step 10 refuses six operations, publication among them, while the
    governing case is `ON_HOLD` - a cross-entity gate, since the shift being
    created has no state of its own yet. The answer is `ERR_CASE_ON_HOLD`, a 409.
    PRD 3.8 also fixes the shape of a manual hold: it records the supplied
    `hold_reason` and leaves `hold_incident_report_id` null.

    Design: Corner/validations/hold_blocks_shift_creation_and_an_empty_pool_blocks_auto_staffing
    """
    base, held = _feeding_tube_case_on_a_manual_hold(api)

    assert held["status"] == CaseStatus.ON_HOLD.value, held
    assert held["hold_reason"] == HoldReason.FAMILY_REQUEST.value, held
    assert held["hold_incident_report_id"] is None, held

    refused = api.create_shift(
        F.shift_payload(base.case_id, WEEK32_THU_08, WEEK32_THU_16), SCHEDULER
    )
    validate_error(refused, ERR_CASE_ON_HOLD, 409)


def test_auto_staffing_an_empty_pool_leaves_the_shift_exactly_as_it_was(api):
    """Because the hold was manual its `hold_incident_report_id` is null, so PRD
    2.11 makes no supervisor comparison and any `ClinicalSupervisor` may resume;
    resuming clears `hold_reason` to null and the window that was just refused is
    publishable. The new shift requires `FEEDING_TUBE`, which the only nurse on the
    roster does not hold, so the pool of PRD 3.6 is empty and PRD 2.8 step 33
    answers `ERR_NO_ELIGIBLE_NURSE`. That refusal must mutate nothing: the shift is
    still `OPEN` at the same `version` and the nurse still has zero
    `scheduled_minutes_this_week`.

    Design: Corner/validations/hold_blocks_shift_creation_and_an_empty_pool_blocks_auto_staffing
    """
    base, _held = _feeding_tube_case_on_a_manual_hold(api)
    api.create_shift(
        F.shift_payload(base.case_id, WEEK32_THU_08, WEEK32_THU_16), SCHEDULER
    )

    resumed = validate_success(api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2))
    assert resumed["status"] == CaseStatus.ACTIVE.value, resumed
    assert resumed["hold_reason"] is None, resumed

    shift = validate_success(
        api.create_shift(
            F.shift_payload(
                base.case_id,
                WEEK32_THU_08,
                WEEK32_THU_16,
                [Skill.FEEDING_TUBE.value],
            ),
            SCHEDULER,
        ),
        201,
    )

    refused = api.auto_staff_shift(
        shift["id"], F.auto_staff_payload(shift["version"]), SCHEDULER
    )
    validate_error(refused, ERR_NO_ELIGIBLE_NURSE, 422)

    untouched = fx.refresh_shift(api, shift["id"])
    assert untouched["staffing_status"] == StaffingStatus.OPEN.value, untouched
    assert untouched["version"] == shift["version"], untouched
    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 0


def test_a_manual_clock_in_completes_the_staffing_axis_but_blocks_billing(api):
    """The submit gate reads a field on another entity. PRD 3.7 makes verification
    a three-part conjunction, and a `MANUAL` `evv_method` fails the first part
    outright, so clocking out drives the shift's `staffing_status` to `COMPLETED`
    on the staffing axis while the verification axis lands on `EXCEPTION`. PRD 2.8
    step 38 then requires the shift's `evv_status` to be `VERIFIED` before a
    timesheet may be submitted, so submission is refused with
    `ERR_EVV_NOT_VERIFIED`, a 409, and the timesheet stays in `CAPTURED`.

    Design: Corner/validations/manual_evv_blocks_submission_while_the_staffing_axis_completes
    """
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, WEEK32_WED_08, WEEK32_WED_16)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    timesheet = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at=WEEK32_WED_08,
        clock_out_at=WEEK32_WED_16,
        evv_method=EvvMethod.MANUAL.value,
        geo_verified=False,
    )

    refused = api.submit_timesheet(timesheet["id"], SCHEDULER)
    validate_error(refused, ERR_EVV_NOT_VERIFIED, 409)

    worked_shift = fx.refresh_shift(api, shift["id"])
    assert worked_shift["evv_status"] == EvvStatus.EXCEPTION.value, worked_shift
    assert worked_shift["staffing_status"] == StaffingStatus.COMPLETED.value, worked_shift

    unbilled = fx.refresh_timesheet(api, timesheet["id"])
    assert unbilled["status"] == TimesheetStatus.CAPTURED.value, unbilled


def _noticed_reduction_with_one_filed_appeal(api):
    """A reduction noticed down to 24 hours, effective 2026-08-13T06:00Z, already
    contested by one FILED REDUCTION_APPEAL."""
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)
    noticed = validate_success(
        api.reduce_authorization(
            base.authorization_id,
            F.reduce_payload(24.0, "utilization review reduced the nursing benefit"),
            base.payer_headers,
        )
    )
    dispute = validate_success(
        api.create_dispute(
            F.dispute_payload(
                base.authorization_id,
                40.0,
                reason="the child's vent dependence has not changed",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    return base, noticed, dispute


def test_a_second_filing_inside_the_window_reports_the_open_dispute(api):
    """PRD 3.9 sets `reduction_effective_at` to the clock plus the payer's
    `reduction_notice_days` of 10, so the notice given at 2026-08-03T06:00Z takes
    effect at 2026-08-13T06:00Z, and the first appeal drives the authorization
    `REDUCTION_NOTICED -> UNDER_APPEAL`. While the clock is still inside that window
    only PRD 2.8 step 28 is armed, so a second filing by another case manager is
    `ERR_DISPUTE_ALREADY_OPEN`. Notably it is not `ERR_INVALID_STATE`: step 9
    carves filing out of the generic transition check precisely so these codes
    surface instead.

    Design: Corner/validations/dispute_window_outranks_the_already_open_dispute_check
    """
    base, noticed, _dispute = _noticed_reduction_with_one_filed_appeal(api)

    assert noticed["reduction_effective_at"] == canonicalize_instant(
        REDUCTION_EFFECTIVE_AT
    ), noticed

    under_appeal = fx.refresh_authorization(api, base)
    assert under_appeal["status"] == AuthorizationStatus.UNDER_APPEAL.value, under_appeal

    duplicate = api.create_dispute(
        F.dispute_payload(
            base.authorization_id,
            40.0,
            reason="duplicate filing by a second case manager",
        ),
        CASE_MANAGER_2,
    )
    validate_error(duplicate, ERR_DISPUTE_ALREADY_OPEN, 409)


def test_the_closed_dispute_window_outranks_the_open_dispute_check(api):
    """Once the clock reaches `reduction_effective_at` both checks are armed, and
    ascending priority decides: PRD 2.8 step 26 - the `REDUCTION_APPEAL` window,
    which requires the clock to be *strictly* before that instant, so equality is
    already closed - precedes step 28's open-dispute conflict. The identical
    duplicate filing therefore answers `ERR_DISPUTE_WINDOW_CLOSED` with a 422 where
    a moment earlier it answered a 409. Neither refusal creates a row: the
    authorization still owns exactly one dispute, still `FILED`.

    Design: Corner/validations/dispute_window_outranks_the_already_open_dispute_check
    """
    base, _noticed, dispute = _noticed_reduction_with_one_filed_appeal(api)
    api.create_dispute(
        F.dispute_payload(
            base.authorization_id,
            40.0,
            reason="duplicate filing by a second case manager",
        ),
        CASE_MANAGER_2,
    )

    fx.set_clock(api, REDUCTION_EFFECTIVE_AT)
    late_duplicate = api.create_dispute(
        F.dispute_payload(
            base.authorization_id, 40.0, reason="late duplicate filing"
        ),
        CASE_MANAGER_2,
    )
    validate_error(late_duplicate, ERR_DISPUTE_WINDOW_CLOSED, 422)

    listed = api.list_disputes(
        base.payer_headers, {"authorization_id": base.authorization_id}
    )
    assert_total_count(listed, 1)
    rows, _meta = validate_paginated(listed)
    assert [row["id"] for row in rows] == [dispute["id"]], rows
    assert rows[0]["status"] == DisputeStatus.FILED.value, rows


def _noticed_reduction_without_a_dispute(api):
    """A reduction noticed down to 24 hours and left uncontested."""
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)
    validate_success(
        api.reduce_authorization(
            base.authorization_id,
            F.reduce_payload(24.0, "utilization review reduced the nursing benefit"),
            base.payer_headers,
        )
    )
    return base


def test_applying_a_reduction_before_its_instant_is_refused(api):
    """PRD 3.9 lets a payer apply a notice only once its instant arrives, and PRD
    2.8 step 27 states the comparison: the clock must be at or after
    `reduction_effective_at`. One day short, at 2026-08-12T06:00Z against an
    effective instant of 2026-08-13T06:00Z, the call is refused with
    `ERR_REDUCTION_NOT_EFFECTIVE`, a 409, and the grant is untouched - the
    authorization is still `REDUCTION_NOTICED` at 40 approved hours, because PRD
    3.9 explicitly leaves `approved_hours_per_week` alone throughout the notice
    period.

    Design: Corner/validations/reduction_cannot_be_applied_before_its_effective_instant
    """
    base = _noticed_reduction_without_a_dispute(api)

    fx.set_clock(api, "2026-08-12T06:00:00Z")
    refused = api.apply_reduction(base.authorization_id, base.payer_headers)
    validate_error(refused, ERR_REDUCTION_NOT_EFFECTIVE, 409)

    unchanged = fx.refresh_authorization(api, base)
    assert unchanged["status"] == AuthorizationStatus.REDUCTION_NOTICED.value, unchanged
    assert_hours(unchanged, "approved_hours_per_week", 40.00)


def test_applying_a_reduction_at_its_instant_rewrites_the_grant(api):
    """The step 27 comparison is inclusive, so the identical call made at exactly
    2026-08-13T06:00Z succeeds. PRD 3.9 then sets `approved_hours_per_week` to the
    stored `noticed_hours_per_week` of 24, clears both notice fields to null and
    moves the authorization `REDUCTION_NOTICED -> REDUCED`. No shift was ever
    committed on this grant, so the recomputed `hours_remaining_this_week` is the
    whole new grant, 24.00 hours to two decimal places.

    Design: Corner/validations/reduction_cannot_be_applied_before_its_effective_instant
    """
    base = _noticed_reduction_without_a_dispute(api)
    fx.set_clock(api, "2026-08-12T06:00:00Z")
    api.apply_reduction(base.authorization_id, base.payer_headers)

    fx.set_clock(api, REDUCTION_EFFECTIVE_AT)
    applied = validate_success(
        api.apply_reduction(base.authorization_id, base.payer_headers)
    )

    assert applied["status"] == AuthorizationStatus.REDUCED.value, applied
    assert_hours(applied, "approved_hours_per_week", 24.00)
    assert applied["noticed_hours_per_week"] is None, applied
    assert applied["reduction_effective_at"] is None, applied
    assert_hours(applied, "hours_remaining_this_week", 24.00)


def _appeal_under_review(api):
    """A 40 -> 24 hour reduction appealed for the full 40 hours, with the appeal
    accepted for review."""
    base = fx.setup_baseline(api, with_nurse=False, with_case=False)
    validate_success(
        api.reduce_authorization(
            base.authorization_id,
            F.reduce_payload(24.0, "utilization review reduced the nursing benefit"),
            base.payer_headers,
        )
    )
    dispute = validate_success(
        api.create_dispute(
            F.dispute_payload(
                base.authorization_id,
                40.0,
                reason="the child's vent dependence has not changed",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    reviewed = validate_success(
        api.review_dispute(dispute["id"], base.payer_headers)
    )
    assert reviewed["status"] == DisputeStatus.UNDER_REVIEW.value, reviewed
    return base, dispute


def test_partially_granted_hours_must_sit_strictly_inside_the_band(api):
    """PRD 3.9 requires a `PARTIALLY_GRANTED` outcome to carry
    `decided_hours_per_week` strictly between the noticed 24 and the previously
    approved 40, so both endpoints of the band are rejected: 24 is not above the
    noticed floor and 40 is not below the approved ceiling. Each is
    `ERR_DECIDED_HOURS_OUT_OF_RANGE`, a 422 by PRD 2.8 step 29, and neither
    attempt decides anything - the dispute stays `UNDER_REVIEW` with
    `decided_hours_per_week` and `decided_at` still null, so the second refusal is
    reported as the range error and not as a state error.

    Design: Corner/validations/partially_granted_hours_must_sit_strictly_inside_the_appeal_band
    """
    base, dispute = _appeal_under_review(api)

    at_the_floor = api.decide_dispute(
        dispute["id"],
        F.decide_dispute_payload(DisputeOutcome.PARTIALLY_GRANTED.value, 24.0),
        base.payer_headers,
    )
    validate_error(at_the_floor, ERR_DECIDED_HOURS_OUT_OF_RANGE, 422)

    at_the_ceiling = api.decide_dispute(
        dispute["id"],
        F.decide_dispute_payload(DisputeOutcome.PARTIALLY_GRANTED.value, 40.0),
        base.payer_headers,
    )
    validate_error(at_the_ceiling, ERR_DECIDED_HOURS_OUT_OF_RANGE, 422)

    undecided = validate_success(api.get_dispute(dispute["id"], base.payer_headers))
    assert undecided["status"] == DisputeStatus.UNDER_REVIEW.value, undecided
    assert undecided["decided_hours_per_week"] is None, undecided
    assert undecided["decided_at"] is None, undecided


def test_an_interior_partial_grant_rewrites_the_approved_hours(api):
    """One hour inside either endpoint the same call succeeds. PRD 3.9 makes a
    `PARTIALLY_GRANTED` decision write `decided_hours_per_week` onto the
    authorization's `approved_hours_per_week` and move it `UNDER_APPEAL ->
    REDUCED`, and PRD 3.9 makes all three outcomes terminal for the dispute, whose
    status becomes `PARTIALLY_GRANTED`. The settled grant is therefore 32.00 hours
    - neither the noticed 24 the payer wanted nor the 40 the case manager asked
    for.

    Design: Corner/validations/partially_granted_hours_must_sit_strictly_inside_the_appeal_band
    """
    base, dispute = _appeal_under_review(api)

    decided = validate_success(
        api.decide_dispute(
            dispute["id"],
            F.decide_dispute_payload(DisputeOutcome.PARTIALLY_GRANTED.value, 32.0),
            base.payer_headers,
        )
    )

    assert decided["status"] == DisputeStatus.PARTIALLY_GRANTED.value, decided
    assert_hours(decided, "decided_hours_per_week", 32.00)

    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.REDUCED.value, authorization
    assert_hours(authorization, "approved_hours_per_week", 32.00)


def _assigned_wednesday_day_shift(api):
    """One 08:00-16:00 Wednesday shift with the continuity nurse assigned, read
    back so the caller holds the post-assignment `version`."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, WEEK32_WED_08, WEEK32_WED_16)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    assigned = fx.refresh_shift(api, shift["id"])
    return base, assigned, assignment


def test_clocking_in_one_minute_too_soon_is_refused(api):
    """PRD 3.7 opens the clock-in window 15 minutes before `start_at` and PRD 2.8
    step 25 rejects anything earlier as `ERR_CLOCK_IN_TOO_EARLY`, a 422. At
    07:44Z, one minute outside a window that opens at 07:45Z for an 08:00Z shift,
    the refusal must leave the shift completely alone: `evv_status` is still
    `NOT_STARTED` and `version` is unchanged from the value the assignment left
    behind, since PRD 2.7 only bumps a version on a successful mutation.

    Design: Corner/validations/clock_in_opens_exactly_fifteen_minutes_before_the_shift
    """
    base, assigned, _assignment = _assigned_wednesday_day_shift(api)

    fx.set_clock(api, "2026-08-05T07:44:00Z")
    too_early = api.clock_in(
        assigned["id"], F.clock_in_payload(), make_nurse_headers(base.nurse_id)
    )
    validate_error(too_early, ERR_CLOCK_IN_TOO_EARLY, 422)

    untouched = fx.refresh_shift(api, assigned["id"])
    assert untouched["evv_status"] == EvvStatus.NOT_STARTED.value, untouched
    assert untouched["version"] == assigned["version"], untouched


def test_clocking_in_exactly_fifteen_minutes_early_opens_the_timesheet(api):
    """The step 25 boundary is inclusive, so one minute later - exactly `start_at`
    minus 15 minutes - the same call is accepted with a 201, because PRD 4 counts
    EVV clock-in among the operations that bring a row into existence. PRD 3.7
    stamps `clock_in_at` with the current logical clock rather than the shift's
    `start_at`, so the timesheet records 07:45Z, opens in `CAPTURED`, and the
    shift's `evv_status` advances `NOT_STARTED -> CLOCKED_IN`.

    Design: Corner/validations/clock_in_opens_exactly_fifteen_minutes_before_the_shift
    """
    base, assigned, assignment = _assigned_wednesday_day_shift(api)

    fx.set_clock(api, "2026-08-05T07:45:00Z")
    validate_success(
        api.clock_in(
            assigned["id"], F.clock_in_payload(), make_nurse_headers(base.nurse_id)
        ),
        201,
    )

    timesheet = fx.timesheet_of_assignment(api, assignment["id"], base.nurse_id)
    assert timesheet["clock_in_at"] == canonicalize_instant(
        "2026-08-05T07:45:00Z"
    ), timesheet
    assert timesheet["status"] == TimesheetStatus.CAPTURED.value, timesheet

    started = fx.refresh_shift(api, assigned["id"])
    assert started["evv_status"] == EvvStatus.CLOCKED_IN.value, started


def test_renewal_is_refused_when_the_last_completed_week_settled_nothing(api):
    """PRD 3.9 gates renewal on the settled utilization of the last completed ISO
    week and refuses below 0.5000. Nothing was ever worked on this grant, so with
    the clock in week 33 the week-32 SETTLED read is 0 `settled_minutes` and a
    0.0000 `utilization_ratio`, well under the floor: PRD 2.8 step 37 answers
    `ERR_RENEWAL_UTILIZATION_TOO_LOW` with a 422. The refusal creates nothing -
    the plan of care still owns exactly one authorization, still `ACTIVE` at
    `renewal_chain_depth` 0, because a successor would have been depth 1.

    Design: Corner/validations/renewal_is_refused_when_the_last_completed_week_settled_nothing
    """
    base = fx.setup_baseline(api)

    fx.set_clock(api, C.CLOCK_WEEK33_MONDAY_06)
    refused = api.renew_authorization(
        base.authorization_id,
        F.renew_payload("2027-02-01T00:00:00Z", 40.0),
        base.payer_headers,
    )
    validate_error(refused, ERR_RENEWAL_UTILIZATION_TOO_LOW, 422)

    settled = fx.utilization(
        api, base, UtilizationBasis.SETTLED.value, C.WEEK32_START
    )
    assert settled["settled_minutes"] == 0, settled
    assert_ratio(settled, "utilization_ratio", 0.0000)

    listed = api.list_authorizations(
        base.payer_headers, {"plan_of_care_id": base.plan_of_care_id}
    )
    assert_total_count(listed, 1)

    unchanged = fx.refresh_authorization(api, base)
    assert unchanged["status"] == AuthorizationStatus.ACTIVE.value, unchanged
    assert unchanged["renewal_chain_depth"] == 0, unchanged
