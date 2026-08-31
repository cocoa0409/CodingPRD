"""Activation, reassignment, disenrolment and graduation."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, assert_caseload_points, assert_enrollment,
    complete_intervention, complete_touch, create_care_manager, create_member,
    create_program, enroll, enrollment_version, plan_intervention,
    read_care_manager, read_care_plan, read_enrollment, read_goal, read_program,
    read_touch, schedule_touch, set_clock, setup_active_care_plan,
    setup_program_and_managers, stratify, validate_error, validate_paginated,
    validate_success,
)

TOUCH_ONE = ("2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z")
TOUCH_TWO = ("2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z")


def _scenario_with_two_reached_touches():
    scenario = setup_active_care_plan(
        program_overrides={"name": "Parallel Dim Program", "min_risk_tier": "LOW"},
        member_overrides={"external_member_id": "MBR-5001", "full_name": "Nia Park",
                          "birth_date": "1974-03-19", "chronic_condition_count": 0},
        goal_specs=[{"domain": "CLINICAL", "description": "Reduce ED use"}],
        plan_title="Parallel plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    enrollment_id = scenario["enrollment"]["id"]
    scenario["touches"] = [
        schedule_touch(enrollment_id, care_manager_id,
                       scheduled_start_at=start, scheduled_end_at=end)
        for start, end in (TOUCH_ONE, TOUCH_TWO)
    ]
    return scenario


def test_engagement_dimension_advances_while_the_enrollment_stays_active(api):
    """PRD §3.6: "This dimension is cyclic in both directions: `UNREACHED` →
    `ENGAGED`, `UNREACHED` → `AT_RISK`, `UNREACHED` → `DISENGAGED`, `ENGAGED` →
    `AT_RISK`, `AT_RISK` → `ENGAGED`, `AT_RISK` → `DISENGAGED`, `DISENGAGED` →
    `ENGAGED` and `DISENGAGED` → `AT_RISK` are all reachable, and none of them
    disturbs the enrollment's `enrollment_status`, which stays `ACTIVE`
    throughout."
    PRD §3.6: "Otherwise, if `engagement_score` is 60 or more, it becomes
    `ENGAGED`. Otherwise it becomes `AT_RISK`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_dimensions_advance_independently
    """
    scenario = _scenario_with_two_reached_touches()
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]

    set_clock(TOUCH_ONE[0])
    complete_touch(scenario["touches"][0]["id"], care_manager_id, "REACHED",
                   "First contact made.")
    after_first = read_enrollment(enrollment_id)
    assert after_first["enrollment_status"] == "ACTIVE"
    assert after_first["engagement_status"] == "AT_RISK"

    set_clock(TOUCH_TWO[0])
    complete_touch(scenario["touches"][1]["id"], care_manager_id, "REACHED",
                   "Second contact made.")
    after_second = read_enrollment(enrollment_id)
    assert after_second["enrollment_status"] == "ACTIVE"
    assert after_second["engagement_status"] == "ENGAGED"
    assert after_second["engagement_score"] == 67


def test_disenrolment_leaves_the_engagement_dimension_untouched(api):
    """PRD §3.4: "`GOALS_MET` graduates the enrollment into `GRADUATED`; every
    other reason disenrolls it into `DISENROLLED`. Both destinations stamp
    `disenrolled_at` with the logical-clock instant, store the supplied reason in
    `disenrollment_reason`, null out both `next_touch_due_at` and `toc_due_at`,
    and increment `version`."
    PRD §3.3: "The new enrollment begins with `enrollment_status` `PENDING` and
    `engagement_status` `UNREACHED` — two dimensions that advance on entirely
    disjoint triggers, so an enrollment's engagement state is never a function of
    its lifecycle state and vice versa, with the single proviso that engagement
    transitions are only recorded while `enrollment_status` is `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_dimensions_advance_independently
    """
    scenario = _scenario_with_two_reached_touches()
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]

    set_clock(TOUCH_ONE[0])
    complete_touch(scenario["touches"][0]["id"], care_manager_id, "REACHED",
                   "First contact made.")
    set_clock(TOUCH_TWO[0])
    complete_touch(scenario["touches"][1]["id"], care_manager_id, "REACHED",
                   "Second contact made.")

    data = validate_success(
        api.disenroll_enrollment(enrollment_id, {"reason": "MEMBER_REQUEST"},
                                 PROGRAM_ADMIN)
    )
    assert_enrollment(data)
    assert data["enrollment_status"] == "DISENROLLED"
    assert data["engagement_status"] == "ENGAGED", (
        "ending the lifecycle dimension never resets the engagement dimension"
    )
    assert data["disenrollment_reason"] == "MEMBER_REQUEST"
    assert data["engagement_score"] == 67
    assert data.get("next_touch_due_at") is None
    assert data.get("toc_due_at") is None
    assert_caseload_points(
        read_care_manager(care_manager_id)["assigned_caseload_points"], 0.0
    )


def _transfer_setting():
    program = create_program(name="Transfer Invariant Program", min_risk_tier="LOW")
    first = create_care_manager(full_name="Rita Nolan", capacity_points=10.0)
    second = create_care_manager(full_name="Dana Ruiz", capacity_points=10.0)
    member = create_member(external_member_id="MBR-2301", full_name="Nel Ford",
                           birth_date="1956-05-05", chronic_condition_count=10)
    assert stratify(member["id"], "CONCURRENT")["tier"] == "RISING"
    enrollment = enroll(member["id"], program["id"], first["id"])
    from test_helpers import activate
    enrollment = activate(enrollment["id"])
    assert_caseload_points(enrollment["acuity_weight_points"], 4.0)
    return program, first, second, member, enrollment


def test_transfer_moves_caseload_points_between_the_two_ledgers(api):
    """PRD §3.4: "An accepted transfer rewrites `care_manager_id` to the target
    and records `assignment_reason` as `TRANSFERRED`. The enrollment's weight
    leaves the previous manager's ledger and joins the target's, and both managers
    have their `capacity_status` refreshed from their new sums."
    PRD §2.9: "A care manager's `assigned_caseload_points` is never adjusted by
    deltas."

    Design: Difficulty/compensating_invariant/caseload_points_conserved_across_transfer_round_trip
    """
    _, first, second, _, enrollment = _transfer_setting()
    assert_caseload_points(
        read_care_manager(first["id"])["assigned_caseload_points"], 4.0
    )

    data = validate_success(
        api.transfer_enrollment(
            enrollment["id"],
            {"to_care_manager_id": second["id"],
             "expected_enrollment_version": enrollment["version"]},
            PROGRAM_ADMIN,
        )
    )
    assert data["care_manager_id"] == second["id"]
    assert data["assignment_reason"] == "TRANSFERRED"
    assert_caseload_points(data["acuity_weight_points"], 4.0)

    losing = read_care_manager(first["id"])
    gaining = read_care_manager(second["id"])
    assert_caseload_points(losing["assigned_caseload_points"], 0.0)
    assert losing["capacity_status"] == "OPEN"
    assert_caseload_points(gaining["assigned_caseload_points"], 4.0)


def test_transfer_round_trip_conserves_the_caseload_total(api):
    """PRD §2.9: "Whenever anything happens that could change it, the figure is
    recomputed from scratch as the full sum of `acuity_weight_points` over every
    enrollment that names that manager in `care_manager_id` and whose
    `enrollment_status` is either `PENDING` or `ACTIVE`, rounded to one decimal
    place."
    PRD §3.4: "`enrollment_status` itself is unchanged by a transfer; the
    observable movement is the ownership field and the two ledgers. The
    enrollment's `version` increases by one."

    Design: Difficulty/compensating_invariant/caseload_points_conserved_across_transfer_round_trip
    """
    _, first, second, _, enrollment = _transfer_setting()
    before_total = (read_care_manager(first["id"])["assigned_caseload_points"]
                    + read_care_manager(second["id"])["assigned_caseload_points"])

    outbound = validate_success(
        api.transfer_enrollment(
            enrollment["id"],
            {"to_care_manager_id": second["id"],
             "expected_enrollment_version": enrollment["version"]},
            PROGRAM_ADMIN,
        )
    )
    inbound = validate_success(
        api.transfer_enrollment(
            enrollment["id"],
            {"to_care_manager_id": first["id"],
             "expected_enrollment_version": outbound["version"]},
            PROGRAM_ADMIN,
        )
    )

    assert inbound["care_manager_id"] == first["id"]
    assert inbound["version"] == outbound["version"] + 1
    assert inbound["enrollment_status"] == "ACTIVE"
    assert_caseload_points(inbound["acuity_weight_points"], 4.0)

    final_first = read_care_manager(first["id"])
    final_second = read_care_manager(second["id"])
    assert_caseload_points(final_first["assigned_caseload_points"], 4.0)
    assert_caseload_points(final_second["assigned_caseload_points"], 0.0)
    assert final_first["capacity_status"] == "OPEN"
    assert final_second["capacity_status"] == "OPEN"
    assert_caseload_points(
        final_first["assigned_caseload_points"]
        + final_second["assigned_caseload_points"],
        before_total,
    )


def test_activating_an_already_active_enrollment_is_rejected(api):
    """PRD §3.4: "Either plan operations or a care manager may activate it, moving
    `enrollment_status` from `PENDING` to `ACTIVE`; attempting this on an
    enrollment in any other state yields `ERR_ENROLLMENT_NOT_PENDING`."

    Design: Corner/state_machines/enrollment_activate_twice_returns_enrollment_not_pending
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Idem Program"}, with_reviewer=False
    )
    member = create_member(external_member_id="MBR-4101", full_name="Idem Ida",
                           birth_date="1973-03-03", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])
    first = validate_success(api.activate_enrollment(enrollment["id"], PROGRAM_ADMIN))
    assert first["activated_at"] == "2026-08-01T00:00:00.000Z"

    response = api.activate_enrollment(enrollment["id"], PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_PENDING.value)
    assert response.status_code == 409

    after = read_enrollment(enrollment["id"])
    assert after["activated_at"] == first["activated_at"]
    assert after["version"] == first["version"], (
        "a rejected activation is not a mutation and must not bump version"
    )


def test_second_disenrolment_reports_the_enrollment_already_terminal(api):
    """PRD §3.4: "The enrollment must be in `PENDING` or `ACTIVE` — a `GRADUATED`
    or `DISENROLLED` enrollment cannot be reassigned, and the attempt returns
    `ERR_ENROLLMENT_ALREADY_TERMINAL`."
    PRD §2.6: "**Source state** — the target resource must currently be in a state
    from which the requested transition is declared."

    Design: Corner/state_machines/enrollment_disenroll_after_disenroll_returns_already_terminal
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Terminal Program"}, with_reviewer=False
    )
    member = create_member(external_member_id="MBR-4201", full_name="Term Tom",
                           birth_date="1974-04-04", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])

    first = validate_success(
        api.disenroll_enrollment(enrollment["id"], {"reason": "INELIGIBLE"},
                                 PROGRAM_ADMIN)
    )
    assert first["enrollment_status"] == "DISENROLLED"

    response = api.disenroll_enrollment(
        enrollment["id"], {"reason": "MEMBER_REQUEST"}, PROGRAM_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_ALREADY_TERMINAL.value)
    assert response.status_code == 409

    after = read_enrollment(enrollment["id"])
    assert after["disenrollment_reason"] == "INELIGIBLE"
    assert after["disenrolled_at"] == first["disenrolled_at"]
    assert_caseload_points(
        read_care_manager(setting["care_manager"]["id"])["assigned_caseload_points"],
        0.0,
    )


def test_disenrolment_cascade_closes_the_plan_and_voids_planned_work(api):
    """PRD §3.4: "Ending an `ACTIVE` enrollment for any reason other than
    `GOALS_MET` runs a four-hop cascade. First, every touch on this enrollment
    still in `SCHEDULED` moves to `CANCELLED` with `cancel_reason` set to
    `ENROLLMENT_ENDED`, freeing the care manager's calendar intervals. Second, the
    enrollment's care plan — the one whose `status` is `ACTIVE` or `SUSPENDED` —
    moves to `CLOSED` and takes a `closed_at` stamp. Third, caused by that
    closure, every goal under that plan whose `status` is `OPEN` or `AT_RISK`
    moves to `CLOSED_UNMET`. Fourth, caused by those goal closures, every
    intervention under those goals whose `status` is still `PLANNED` moves to
    `VOIDED` with `void_reason` set to `PLAN_CLOSED`, and each one releases its
    `staff_minutes` back from the program's `committed_staff_minutes`."

    Design: Corner/state_machines/disenroll_cascade_closes_plan_and_voids_planned_interventions
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Cascade Down Program"},
        member_overrides={"external_member_id": "MBR-4601", "full_name": "Cas Cade",
                          "birth_date": "1966-06-16"},
        goal_specs=[{"domain": "CLINICAL", "description": "Cascade goal"}],
        plan_title="Cascade plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    intervention = plan_intervention(scenario["goal"]["id"], care_manager_id,
                                     modality="HOME_VISIT", staff_minutes=40)
    touch = schedule_touch(scenario["enrollment"]["id"], care_manager_id,
                           scheduled_start_at="2026-08-20T09:00:00Z",
                           scheduled_end_at="2026-08-20T09:30:00Z")
    assert read_program(scenario["program"]["id"])["committed_staff_minutes"] == 40

    data = validate_success(
        api.disenroll_enrollment(scenario["enrollment"]["id"],
                                 {"reason": "LOST_CONTACT"}, PROGRAM_ADMIN)
    )
    assert data["enrollment_status"] == "DISENROLLED"

    cancelled = read_touch(touch["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "ENROLLMENT_ENDED"

    plan = read_care_plan(scenario["plan"]["id"])
    assert plan["status"] == "CLOSED"
    assert plan["closed_at"] == "2026-08-01T00:00:00.000Z"

    assert read_goal(scenario["goal"]["id"])["status"] == "CLOSED_UNMET"

    voided, meta = validate_paginated(
        api.list_interventions(scenario["goal"]["id"], PROGRAM_ADMIN,
                               params={"status": "VOIDED"})
    )
    assert meta["total_count"] == 1
    assert voided[0]["id"] == intervention["id"]
    assert voided[0]["void_reason"] == "PLAN_CLOSED"

    program = read_program(scenario["program"]["id"])
    assert program["committed_staff_minutes"] == 0
    assert program["delivered_staff_minutes"] == 0

    manager = read_care_manager(care_manager_id)
    assert_caseload_points(manager["assigned_caseload_points"], 0.0)
    assert manager["active_enrollment_count"] == 0


def test_transfer_cancels_the_previous_managers_scheduled_touches(api):
    """PRD §3.4: "And because the previous manager is no longer the one making the
    calls, every touch on this enrollment that is still `SCHEDULED` and still
    names the previous manager moves from `SCHEDULED` to `CANCELLED`, with a
    `cancel_reason` of `CARE_MANAGER_TRANSFER`, releasing those calendar
    intervals."

    Design: Corner/state_machines/transfer_cancels_previous_managers_scheduled_touches
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Transfer Cascade Program"},
        member_overrides={"external_member_id": "MBR-4701", "full_name": "Tra Nsfer",
                          "birth_date": "1965-05-15"},
        goal_specs=[{"domain": "CLINICAL", "description": "Transfer goal"}],
        plan_title="Transfer plan",
    )
    losing_id = scenario["care_manager"]["id"]
    gaining_id = scenario["reviewer"]["id"]
    enrollment_id = scenario["enrollment"]["id"]

    live = schedule_touch(enrollment_id, losing_id,
                          scheduled_start_at="2026-08-18T09:00:00Z",
                          scheduled_end_at="2026-08-18T09:30:00Z")
    already_cancelled = schedule_touch(enrollment_id, losing_id,
                                       scheduled_start_at="2026-08-19T09:00:00Z",
                                       scheduled_end_at="2026-08-19T09:30:00Z")
    from test_helpers import cancel_touch
    cancel_touch(already_cancelled["id"], losing_id, "Member rescheduled.")

    data = validate_success(
        api.transfer_enrollment(
            enrollment_id,
            {"to_care_manager_id": gaining_id,
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            PROGRAM_ADMIN,
        )
    )
    assert data["care_manager_id"] == gaining_id

    swept = read_touch(live["id"])
    assert swept["status"] == "CANCELLED"
    assert swept["cancel_reason"] == "CARE_MANAGER_TRANSFER"
    assert read_touch(already_cancelled["id"])["cancel_reason"] == "Member rescheduled."

    _, meta = validate_paginated(
        api.list_touches(PROGRAM_ADMIN,
                         params={"care_manager_id": losing_id, "status": "SCHEDULED"})
    )
    assert meta["total_count"] == 0
    assert_caseload_points(
        read_care_manager(losing_id)["assigned_caseload_points"], 0.0
    )
    assert_caseload_points(
        read_care_manager(gaining_id)["assigned_caseload_points"], 1.0
    )


def test_graduation_requires_every_goal_to_be_met(api):
    """PRD §3.4: "Ending an `ACTIVE` enrollment with `GOALS_MET` first demands
    proof: the enrollment must have a care plan whose `status` is `ACTIVE`, that
    plan must carry at least one goal, and every one of those goals must be in
    `MET`. A plan with no goals at all, or with any goal outside `MET`, fails this
    check with `ERR_GOALS_NOT_MET`."
    PRD §3.4: "When the proof holds, `enrollment_status` becomes `GRADUATED`,
    `disenrollment_reason` records `GOALS_MET`, every `SCHEDULED` touch on the
    enrollment moves to `CANCELLED` with `cancel_reason` `ENROLLMENT_ENDED`, and
    the `ACTIVE` care plan moves to `CLOSED`."

    Design: Corner/validations/graduation_with_open_goals_returns_goals_not_met
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Graduation Program"},
        member_overrides={"external_member_id": "MBR-7001", "full_name": "Grad Gail",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Goal one"},
                    {"domain": "BEHAVIORAL", "description": "Goal two"}],
        plan_title="Graduation plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    first_goal, second_goal = scenario["goals"]
    first_intervention = plan_intervention(first_goal["id"], care_manager_id,
                                           modality="PHONE", staff_minutes=20)
    second_intervention = plan_intervention(second_goal["id"], care_manager_id,
                                            modality="EDUCATION", staff_minutes=20)
    complete_intervention(first_intervention["id"], care_manager_id)

    rejected = api.disenroll_enrollment(
        scenario["enrollment"]["id"], {"reason": "GOALS_MET"}, PROGRAM_ADMIN
    )
    validate_error(rejected, ApiErrorId.ERR_GOALS_NOT_MET.value)
    assert rejected.status_code == 409
    assert read_enrollment(scenario["enrollment"]["id"])["enrollment_status"] == "ACTIVE"

    complete_intervention(second_intervention["id"], care_manager_id)
    graduated = validate_success(
        api.disenroll_enrollment(scenario["enrollment"]["id"],
                                 {"reason": "GOALS_MET"}, PROGRAM_ADMIN)
    )
    assert graduated["enrollment_status"] == "GRADUATED"
    assert graduated["disenrollment_reason"] == "GOALS_MET"
    assert read_care_plan(scenario["plan"]["id"])["status"] == "CLOSED"
    assert read_goal(first_goal["id"])["status"] == "MET"
    assert read_goal(second_goal["id"])["status"] == "MET"
    assert_caseload_points(
        read_care_manager(care_manager_id)["assigned_caseload_points"], 0.0
    )


def test_transfer_to_the_current_manager_is_rejected(api):
    """PRD §3.4: "The target must genuinely be a different manager than the
    enrollment's current `care_manager_id`, else `ERR_TRANSFER_TO_SAME_MANAGER`."

    Design: Corner/validations/transfer_to_current_manager_returns_transfer_to_same_manager
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Same Manager Program"}, with_reviewer=False
    )
    member = create_member(external_member_id="MBR-7101", full_name="Same Sid",
                           birth_date="1970-01-01", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])
    from test_helpers import activate
    enrollment = activate(enrollment["id"])

    response = api.transfer_enrollment(
        enrollment["id"],
        {"to_care_manager_id": setting["care_manager"]["id"],
         "expected_enrollment_version": enrollment["version"]},
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_TRANSFER_TO_SAME_MANAGER.value)
    assert response.status_code == 409

    after = read_enrollment(enrollment["id"])
    assert after["version"] == enrollment["version"]
    assert after["assignment_reason"] == "EXPLICIT"


def test_stale_expected_version_blocks_a_transfer(api):
    """PRD §2.8: "Both take a mandatory input field named
    `expected_enrollment_version`, carrying the `version` the client last observed
    on that enrollment."
    PRD §2.8: "If `expected_enrollment_version` does not equal the enrollment's
    current `version`, the transfer is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) and neither ledger moves."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_transfer_returns_stale_enrollment_version
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "OCC Program"},
    )
    member = create_member(external_member_id="MBR-9601", full_name="Occ Ozzy",
                           birth_date="1970-01-01", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    created = enroll(member["id"], setting["program"]["id"],
                     setting["care_manager"]["id"])
    from test_helpers import activate
    activated = activate(created["id"])
    assert activated["version"] == created["version"] + 1

    stale = api.transfer_enrollment(
        created["id"],
        {"to_care_manager_id": setting["reviewer"]["id"],
         "expected_enrollment_version": created["version"]},
        PROGRAM_ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value)
    assert stale.status_code == 412

    unchanged = read_enrollment(created["id"])
    assert unchanged["care_manager_id"] == setting["care_manager"]["id"]
    assert unchanged["version"] == activated["version"]

    fresh = validate_success(
        api.transfer_enrollment(
            created["id"],
            {"to_care_manager_id": setting["reviewer"]["id"],
             "expected_enrollment_version": activated["version"]},
            PROGRAM_ADMIN,
        )
    )
    assert fresh["care_manager_id"] == setting["reviewer"]["id"]
    assert fresh["version"] == activated["version"] + 1
    assert_caseload_points(
        read_care_manager(setting["care_manager"]["id"])["assigned_caseload_points"],
        0.0,
    )
    assert_caseload_points(
        read_care_manager(setting["reviewer"]["id"])["assigned_caseload_points"], 1.0
    )


def test_activation_response_carries_every_derived_field(api):
    """PRD §3.4: "It sets the outreach intensity: `cadence_tier` becomes
    `INTENSIVE` when `risk_tier_at_enrollment` is `HIGH`, and `STANDARD`
    otherwise, and `cadence_tier_snapshot` is set to that same value, opening the
    first engagement measurement window."
    PRD §3.4: "Finally it projects `next_touch_due_at` from a base instant equal
    to `activated_at`, and resets the engagement counters: `engagement_score` to 0
    and `reached_touch_count` to 0."
    PRD §2.10: "Cascades run to completion within the request that triggered them,
    and the response returned to the caller reflects the settled state, not an
    intermediate one."

    Design: Corner/consistency_model/activation_response_reflects_every_derived_field_in_the_same_request
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Immediate Program", "min_risk_tier": "LOW"},
        with_reviewer=False,
    )
    member = create_member(external_member_id="MBR-9901", full_name="Imm Ida",
                           birth_date="1946-04-06", chronic_condition_count=15)
    stratification = stratify(member["id"], "CONCURRENT")
    assert stratification["tier"] == "HIGH"
    assert stratification["score"] == 90

    pending = enroll(member["id"], setting["program"]["id"],
                     setting["care_manager"]["id"])
    assert pending["cadence_tier"] == "STANDARD"
    assert_caseload_points(pending["acuity_weight_points"], 7.0)

    activated = validate_success(api.activate_enrollment(pending["id"], PROGRAM_ADMIN))
    assert activated["cadence_tier"] == "INTENSIVE"
    assert activated["cadence_tier_snapshot"] == "INTENSIVE"
    assert_caseload_points(activated["acuity_weight_points"], 10.5)
    assert activated["activated_at"] == "2026-08-01T00:00:00.000Z"
    assert activated["next_touch_due_at"] == "2026-08-15T00:00:00.000Z"
    assert activated["engagement_score"] == 0
    assert activated["reached_touch_count"] == 0

    ledger = read_care_manager(setting["care_manager"]["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 10.5)
    assert ledger["capacity_status"] == "OPEN"
    assert ledger["active_enrollment_count"] == 1
