"""Exercises, after-action credit, the call-out roster and responder handling."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_asset,
    add_trainee,
    advance_activation,
    assert_activation,
    assert_exercise_participation,
    assert_fill_status_matches_counts,
    assert_hours,
    assert_instant,
    assert_roster_assignment,
    assert_score,
    build_roster,
    create_activation,
    create_exercise,
    issue_kit,
    make_trainee_headers,
    read_activation,
    read_assignment,
    read_exercise,
    read_participation,
    read_program,
    read_trainee,
    register_participation,
    respond_to_call_out,
    run_exercise_to_credit,
    set_clock,
    setup_credentialed_trainees,
    setup_program_and_curriculum,
    setup_rostered_activation,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
EMERGENCY = TEST_USERS["emergency_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
TWO_TRAINEES = (("tara", "Tara Nolan"), ("dev", "Dev Okafor"))


# ---------------------------------------------------------------------------
# Exercises and after-action credit
# ---------------------------------------------------------------------------

def test_after_action_acceptance_pays_each_role_its_rounded_multiple(api):
    """PRD §3.8: "Acceptance is where credit is finally paid. Every participation of the
    exercise standing at `REGISTERED` moves to `CREDITED`, with `hours_credited` set to the
    exercise's `base_credit_hours` multiplied by that row's `role_multiplier`, rounded half-up
    to one decimal place, per row."
    PRD §3.8: "Registration resolves the row's `role_multiplier` from that role — 1.50 for
    `TEAM_LEADER`, 1.25 for `SEARCH_RESCUE`, 1.25 for `MEDICAL`, 1.00 for `LOGISTICS`, and
    0.50 for `OBSERVER` — opens the row at `REGISTERED`, and leaves `hours_credited` at 0
    until the after-action report has been accepted."
    PRD §3.8: "The exercise's `accepted_participant_count` is then recomputed as the number
    of its participations standing at `CREDITED`."

    Design: Corner/calculations/exercise_hours_credit_applies_role_multiplier_with_half_up_rounding
    """
    ctx = setup_program_and_curriculum()
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    add_trainee(ctx, key="dev", full_name="Dev Okafor")
    create_exercise(ctx, "drill1", title="Drill 1", base_credit_hours=5.5,
                    starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z")
    register_participation(ctx, "drill1", "tara", role_played="TEAM_LEADER",
                           store_as="leader")
    register_participation(ctx, "drill1", "dev", role_played="OBSERVER",
                           store_as="observer")

    run_exercise_to_credit(ctx, "drill1", accept_at="2026-09-01T14:00:00Z")

    exercise = read_exercise(ctx, "drill1")
    assert exercise["status"] == "AAR_ACCEPTED"
    assert exercise["accepted_participant_count"] == 2

    leader = read_participation(ctx, ctx["participations"]["leader"])
    observer = read_participation(ctx, ctx["participations"]["observer"])
    assert_exercise_participation(leader)
    assert leader["role_multiplier"] == 1.50
    assert_hours(leader["hours_credited"], 8.3, "team leader hours_credited")
    assert observer["role_multiplier"] == 0.50
    assert_hours(observer["hours_credited"], 2.8, "observer hours_credited")
    assert leader["status"] == "CREDITED"
    assert observer["status"] == "CREDITED"


def test_cancelling_an_exercise_voids_its_registrations_without_credit(api):
    """PRD §3.8: "Cancelling an exercise from `PLANNED` or `RUNNING` instead moves every
    participation standing at `REGISTERED` to `VOIDED`, and voided rows never contribute
    hours to anything."
    PRD §3.8: "Registration resolves the row's `role_multiplier` from that role — 1.50 for
    `TEAM_LEADER`, 1.25 for `SEARCH_RESCUE`, 1.25 for `MEDICAL`, 1.00 for `LOGISTICS`, and
    0.50 for `OBSERVER` — opens the row at `REGISTERED`, and leaves `hours_credited` at 0
    until the after-action report has been accepted."

    Design: Corner/state_machines/cancel_exercise_voids_only_registered_participations
    """
    ctx = setup_program_and_curriculum()
    add_trainee(ctx, key="tara", full_name="Tara Nolan", enroll=False)
    create_exercise(ctx, "drill9", title="Drill 9", base_credit_hours=4.0)
    participation = register_participation(ctx, "drill9", "tara",
                                           role_played="SEARCH_RESCUE", store_as="p9")

    cancelled = validate_success(
        api.advance_exercise(ctx["exercises"]["drill9"]["id"],
                             {"to_status": "CANCELLED"}, EMERGENCY)
    )
    assert cancelled["status"] == "CANCELLED"

    voided = read_participation(ctx, participation)
    assert voided["status"] == "VOIDED"
    assert_hours(voided["hours_credited"], 0.0, "hours_credited")
    assert voided["role_multiplier"] == 1.25
    assert read_exercise(ctx, "drill9")["accepted_participant_count"] == 0


# ---------------------------------------------------------------------------
# The roster selector's cardinality boundary
# ---------------------------------------------------------------------------

def test_a_candidate_set_smaller_than_the_request_leaves_the_roster_partial(api):
    """PRD §3.9: "The number taken is the smaller of `requested_responders` and the size of
    the candidate set: an empty candidate set is refused with `ERR_NO_ELIGIBLE_RESPONDERS`,
    leaving the activation at `REQUESTED` with `fill_status` still `UNFILLED`; a candidate set
    smaller than the request rosters everyone available, moves the activation to `ROSTERED`,
    and leaves `fill_status` at `PARTIAL`; and a candidate set at least as large as the
    request rosters exactly `requested_responders` volunteers and leaves `fill_status` at
    `FILLED`."
    PRD §3.9: "Each selected volunteer gets an assignment row opening at `NOTIFIED`, with
    `source` `AUTO_ROSTER`, `notified_at` stamped from the logical clock, `responded_at` null,
    and `selection_rank` set to their 1-based position in the ranking just described."

    Design: Difficulty/boundary_precision_check/roster_selector_partial_fill_and_empty_candidate_set
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T15:00:00Z",
                                      extra_enrolled=(("dev", "Dev Okafor"),))
    create_activation(ctx, key="act1", incident_number="INC-2026-001",
                      severity="ROUTINE", requested_responders=3)

    activation = build_roster(ctx, key="act1", at="2026-08-05T15:00:00Z")
    assert_activation(activation)
    assert activation["status"] == "ROSTERED"
    assert activation["rostered_count"] == 1
    assert activation["requested_responders"] == 3
    assert activation["fill_status"] == "PARTIAL"
    assert_fill_status_matches_counts(activation)

    rows, meta = validate_paginated(
        api.list_roster_assignments(
            AUDITOR, {"activation_id": ctx["activations"]["act1"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assignment = rows[0]
    assert_roster_assignment(assignment)
    assert assignment["trainee_id"] == ctx["trainees"]["tara"]["id"]
    assert assignment["selection_rank"] == 1
    assert assignment["source"] == "AUTO_ROSTER"
    assert assignment["status"] == "NOTIFIED"


def test_an_empty_candidate_set_leaves_the_activation_requested_and_unfilled(api):
    """PRD §3.9: "they hold no roster assignment standing at `NOTIFIED`, `ACCEPTED`, or
    `DEPLOYED` on any activation that is itself standing at `REQUESTED`, `ROSTERED`, or
    `ACTIVATED`; and — this clause applies only when the activation's `severity` is
    `CRITICAL` — their credential stands specifically at `ACTIVE`."
    PRD §3.9: "The number taken is the smaller of `requested_responders` and the size of the
    candidate set: an empty candidate set is refused with `ERR_NO_ELIGIBLE_RESPONDERS`,
    leaving the activation at `REQUESTED` with `fill_status` still `UNFILLED`; a candidate set
    smaller than the request rosters everyone available, moves the activation to `ROSTERED`,
    and leaves `fill_status` at `PARTIAL`; and a candidate set at least as large as the
    request rosters exactly `requested_responders` volunteers and leaves `fill_status` at
    `FILLED`."

    Design: Difficulty/boundary_precision_check/roster_selector_partial_fill_and_empty_candidate_set
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T15:00:00Z",
                                      extra_enrolled=(("dev", "Dev Okafor"),))
    create_activation(ctx, key="act1", incident_number="INC-2026-001",
                      severity="ROUTINE", requested_responders=3)
    build_roster(ctx, key="act1", at="2026-08-05T15:00:00Z")

    create_activation(ctx, key="act2", incident_number="INC-2026-002",
                      severity="ROUTINE", requested_responders=1)
    validate_error(
        api.build_roster(ctx["activations"]["act2"]["id"], EMERGENCY),
        ApiErrorId.ERR_NO_ELIGIBLE_RESPONDERS.value,
    )

    activation = read_activation(ctx, key="act2")
    assert activation["status"] == "REQUESTED"
    assert activation["fill_status"] == "UNFILLED"
    assert activation["response_deadline_at"] is None

    _, meta = validate_paginated(
        api.list_roster_assignments(
            AUDITOR, {"activation_id": ctx["activations"]["act2"]["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Responding to the call-out
# ---------------------------------------------------------------------------

def test_a_responder_cannot_answer_once_the_activation_has_left_rostered(api):
    """PRD §3.9: "Answering requires the activation to be standing at `ROSTERED`, failing
    which the attempt is refused with `ERR_ACTIVATION_NOT_ROSTERED`, and requires the logical
    clock to be strictly before `response_deadline_at`; a clock that has reached the deadline
    is refused with `ERR_RESPONSE_WINDOW_CLOSED`."
    PRD §3.9: "Within a bucket, candidates are ordered by `readiness_score` descending, then
    by `last_deployed_at` ascending with never-deployed volunteers placed first, then by
    `created_at` ascending as the final tie-break."
    PRD §3.9: "The activation's `response_deadline_at` is stamped as the logical clock plus
    the window its `severity` earns: four hours for `ROUTINE`, two hours for `URGENT`, and one
    hour for `CRITICAL`."

    Design: Corner/validations/responding_once_the_activation_has_left_rostered_is_refused
    """
    ctx = setup_rostered_activation(trainees=TWO_TRAINEES, severity="URGENT",
                                    requested_responders=2)
    assert_score(read_trainee(ctx, "tara")["readiness_score"], 96.00, "Tara readiness")
    assert_score(read_trainee(ctx, "dev")["readiness_score"], 95.00, "Dev readiness")

    tara_assignment = read_assignment(ctx, ctx["assignments"]["tara"])
    dev_assignment = read_assignment(ctx, ctx["assignments"]["dev"])
    assert tara_assignment["selection_rank"] == 1
    assert dev_assignment["selection_rank"] == 2
    assert tara_assignment["source"] == "AUTO_ROSTER"
    assert dev_assignment["source"] == "AUTO_ROSTER"
    assert_instant(read_activation(ctx)["response_deadline_at"], "2026-08-05T17:00:00Z",
                   "response_deadline_at")

    respond_to_call_out(ctx, "tara", "ACCEPT")
    advance_activation(ctx, "ACTIVATED")

    validate_error(
        api.respond_roster_assignment(
            dev_assignment["id"], {"response": "ACCEPT"},
            make_trainee_headers(ctx["trainees"]["dev"]["id"]),
        ),
        ApiErrorId.ERR_ACTIVATION_NOT_ROSTERED.value,
    )
    assert read_assignment(ctx, dev_assignment)["status"] == "NOTIFIED"
    activation = read_activation(ctx)
    assert activation["accepted_count"] == 1
    assert activation["fill_status"] == "FILLED"


def test_a_response_at_the_deadline_is_closed_and_the_sweep_times_it_out(api):
    """PRD §3.9: "Answering requires the activation to be standing at `ROSTERED`, failing
    which the attempt is refused with `ERR_ACTIVATION_NOT_ROSTERED`, and requires the logical
    clock to be strictly before `response_deadline_at`; a clock that has reached the deadline
    is refused with `ERR_RESPONSE_WINDOW_CLOSED`."
    PRD §3.9: "Silence is handled by the same operational sweep that ages credentials: an
    assignment standing at `NOTIFIED` whose activation's `response_deadline_at` the logical
    clock has reached or passed moves `NOTIFIED → NO_RESPONSE`, and the activation's
    `rostered_count` and `fill_status` are recomputed."

    Design: Corner/validations/call_out_response_after_the_deadline_is_refused
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1)
    assignment = ctx["assignments"]["tara"]
    assert_instant(read_activation(ctx)["response_deadline_at"], "2026-08-05T19:00:00Z",
                   "response_deadline_at")

    set_clock("2026-08-05T19:00:00Z")
    validate_error(
        api.respond_roster_assignment(
            assignment["id"], {"response": "ACCEPT"},
            make_trainee_headers(ctx["trainees"]["tara"]["id"]),
        ),
        ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value,
    )
    still_open = read_assignment(ctx, assignment)
    assert still_open["status"] == "NOTIFIED"
    assert still_open["responded_at"] is None

    validate_success(api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD))

    assert read_assignment(ctx, assignment)["status"] == "NO_RESPONSE"
    activation = read_activation(ctx)
    assert activation["rostered_count"] == 0
    assert activation["fill_status"] == "UNFILLED"


def test_a_volunteer_may_answer_only_their_own_call_out(api):
    """PRD §2.1: "When `X-User-Role` is `Trainee`, `X-User-ID` is the `id` of the acting
    `Trainee`; ownership checks on any resource that references a `Trainee` compare the
    resource's foreign-key field to `X-User-ID`, so a trainee may answer only a call-out
    assignment whose `trainee_id` is their own, and may act on only their own trainee record."
    PRD §3.9: "Accepting moves the assignment `NOTIFIED → ACCEPTED`, stamps `responded_at`
    from the logical clock, and recomputes the activation's `accepted_count` and
    `fill_status`; declining moves it `NOTIFIED → DECLINED`, stamps `responded_at`, and
    recomputes `rostered_count` and `fill_status`."

    Design: Corner/rbac/trainee_cannot_answer_another_trainees_call_out
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1,
                                    extra_enrolled=(("dev", "Dev Okafor"),))
    assignment = ctx["assignments"]["tara"]

    validate_error(
        api.respond_roster_assignment(
            assignment["id"], {"response": "ACCEPT"},
            make_trainee_headers(ctx["trainees"]["dev"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    untouched = read_assignment(ctx, assignment)
    assert untouched["status"] == "NOTIFIED"
    assert untouched["responded_at"] is None

    accepted = validate_success(
        api.respond_roster_assignment(
            assignment["id"], {"response": "ACCEPT"},
            make_trainee_headers(ctx["trainees"]["tara"]["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant(accepted["responded_at"], "2026-08-05T15:00:00Z", "responded_at")
    activation = read_activation(ctx)
    assert activation["accepted_count"] == 1
    assert activation["fill_status"] == "FILLED"


def test_demobilising_closes_out_every_open_assignment(api):
    """PRD §3.9: "Demobilising the activation `ACTIVATED → DEMOBILIZED` requires that no
    assignment is still standing at `DEPLOYED`; it moves every assignment still at `NOTIFIED`
    to `NO_RESPONSE`, every assignment still at `ACCEPTED` to `WITHDRAWN`, and recomputes the
    activation's counts and `fill_status`."
    PRD §3.9: "`rostered_count` is the number of the activation's assignments standing at
    `NOTIFIED`, `ACCEPTED`, `DEPLOYED`, or `RELEASED`; `accepted_count` narrows that to
    `ACCEPTED`, `DEPLOYED`, or `RELEASED`; and `deployed_count` narrows it further to
    `DEPLOYED` or `RELEASED`."

    Design: Corner/state_machines/demobilizing_an_activation_closes_out_notified_and_accepted_rows
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1)
    accepted = respond_to_call_out(ctx, "tara", "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    assert_instant(accepted["responded_at"], "2026-08-05T15:00:00Z", "responded_at")

    activated = advance_activation(ctx, "ACTIVATED")
    assert activated["accepted_count"] == 1
    assert activated["fill_status"] == "FILLED"

    demobilized = advance_activation(ctx, "DEMOBILIZED")
    assert demobilized["status"] == "DEMOBILIZED"
    assert read_assignment(ctx, accepted)["status"] == "WITHDRAWN"

    activation = read_activation(ctx)
    assert activation["accepted_count"] == 0
    assert activation["rostered_count"] == 0
    assert activation["fill_status"] == "UNFILLED"


# ---------------------------------------------------------------------------
# Manual roster additions
# ---------------------------------------------------------------------------

def test_a_manual_addition_must_pass_the_same_eligibility_filter(api):
    """PRD §3.9: "A manual addition must satisfy exactly the same eligibility filter as the
    automatic selector, including the critical-severity restriction, and a volunteer who fails
    it is refused with `ERR_TRAINEE_NOT_ELIGIBLE`."
    PRD §3.9: "The **eligibility filter** admits a trainee only when every one of the
    following holds: the trainee belongs to the same program as the activation; their
    `enrollment_status` is `GRADUATED`; their `deployment_hold` flag is false; they hold a
    credential standing at `ACTIVE` or `GRACE`; they hold no roster assignment standing at
    `NOTIFIED`, `ACCEPTED`, or `DEPLOYED` on any activation that is itself standing at
    `REQUESTED`, `ROSTERED`, or `ACTIVATED`; and — this clause applies only when the
    activation's `severity` is `CRITICAL` — their credential stands specifically at `ACTIVE`."

    Design: Corner/validations/manual_roster_add_of_an_ineligible_trainee_is_refused
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=3,
                                    extra_enrolled=(("dev", "Dev Okafor"),))
    activation = read_activation(ctx)
    assert activation["rostered_count"] == 1
    assert activation["fill_status"] == "PARTIAL"

    validate_error(
        api.add_roster_assignment(
            activation["id"],
            {"trainee_id": ctx["trainees"]["dev"]["id"],
             "expected_activation_version": activation["version"]},
            EMERGENCY,
        ),
        ApiErrorId.ERR_TRAINEE_NOT_ELIGIBLE.value,
    )

    after = read_activation(ctx)
    assert after["rostered_count"] == 1
    assert after["fill_status"] == "PARTIAL"
    _, meta = validate_paginated(
        api.list_roster_assignments(AUDITOR, {"activation_id": activation["id"]})
    )
    assert meta["total_count"] == 1
    assert read_trainee(ctx, "dev")["enrollment_status"] == "ENROLLED"
    _, cred_meta = validate_paginated(
        api.list_credentials(AUDITOR, {"trainee_id": ctx["trainees"]["dev"]["id"]})
    )
    assert cred_meta["total_count"] == 0


def test_a_stale_activation_version_blocks_a_manual_roster_addition(api):
    """PRD §2.8: "Manually adding a responder to an activation roster likewise requires a
    non-optional `expected_activation_version` field carrying the client's last observed
    `version` of the target `Activation`. A mismatch with the activation's current `version`
    is rejected with `ERR_STALE_ACTIVATION_VERSION` and HTTP 412, and no assignment row is
    created — a client whose view of `rostered_count` and `fill_status` predates an earlier add
    is refused rather than allowed to over-fill the roster."
    PRD §3.9: "The new row opens at `NOTIFIED` with `source` `MANUAL_ADD` and a
    `selection_rank` one greater than the highest rank already present on that activation;
    `rostered_count` and `fill_status` are recomputed and the activation's `version` is
    incremented."

    Design: Corner/cross_cutting_layers/stale_activation_version_on_manual_roster_add_returns_412
    """
    ctx = setup_credentialed_trainees(trainees=TWO_TRAINEES,
                                      mint_at="2026-08-05T15:00:00Z")
    activation = create_activation(ctx, key="act1", incident_number="INC-2026-001",
                                   severity="ROUTINE", requested_responders=1)
    stale_version = read_activation(ctx)["version"]

    rostered = build_roster(ctx, key="act1", at="2026-08-05T15:00:00Z")
    assert rostered["rostered_count"] == 1
    assert rostered["fill_status"] == "FILLED"

    validate_error(
        api.add_roster_assignment(
            activation["id"],
            {"trainee_id": ctx["trainees"]["dev"]["id"],
             "expected_activation_version": stale_version},
            EMERGENCY,
        ),
        ApiErrorId.ERR_STALE_ACTIVATION_VERSION.value,
    )
    assert read_activation(ctx)["rostered_count"] == 1

    fresh_version = read_activation(ctx)["version"]
    added = validate_success(
        api.add_roster_assignment(
            activation["id"],
            {"trainee_id": ctx["trainees"]["dev"]["id"],
             "expected_activation_version": fresh_version},
            EMERGENCY,
        ),
        201,
    )
    assert added["source"] == "MANUAL_ADD"
    assert added["selection_rank"] == 2
    assert added["status"] == "NOTIFIED"

    final = read_activation(ctx)
    assert final["rostered_count"] == 2
    assert final["fill_status"] == "FILLED"


# ---------------------------------------------------------------------------
# Withdrawal blockers
# ---------------------------------------------------------------------------

def test_outstanding_equipment_is_reported_before_the_roster_commitment(api):
    """PRD §3.2: "Withdrawal from `ENROLLED` or `GRADUATED` is barred while the volunteer
    still holds equipment or a live call-out commitment: if any of that trainee's equipment
    issuances is still on issue the request fails with `ERR_EQUIPMENT_OUTSTANDING`, and if any
    of their roster assignments stands at `NOTIFIED`, `ACCEPTED`, or `DEPLOYED` it fails with
    `ERR_ROSTER_COMMITMENT_OUTSTANDING`."
    PRD §2.6: "Referential business rules, in this relative order: prerequisite not scheduled
    (`ERR_PREREQUISITE_NOT_SCHEDULED`), prerequisite not passed (`ERR_PREREQUISITE_NOT_PASSED`),
    curriculum cycle (`ERR_CURRICULUM_CYCLE`), equipment outstanding
    (`ERR_EQUIPMENT_OUTSTANDING`), and roster commitment outstanding
    (`ERR_ROSTER_COMMITMENT_OUTSTANDING`) — all 409."

    Design: Corner/validations/withdrawal_reports_equipment_before_roster_commitments
    """
    ctx = setup_rostered_activation(severity="ROUTINE", requested_responders=1)
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    issuance = issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as="backpack")
    trainee_id = ctx["trainees"]["tara"]["id"]

    validate_error(
        api.trainee_enrollment(trainee_id, {"action": "WITHDRAW"}, COORD),
        ApiErrorId.ERR_EQUIPMENT_OUTSTANDING.value,
    )

    validate_success(
        api.return_equipment_issuance(
            issuance["id"], {"condition": "SERVICEABLE"}, LOGISTICS
        )
    )
    validate_error(
        api.trainee_enrollment(trainee_id, {"action": "WITHDRAW"}, COORD),
        ApiErrorId.ERR_ROSTER_COMMITMENT_OUTSTANDING.value,
    )

    assert read_trainee(ctx, "tara")["enrollment_status"] == "GRADUATED"
    assert read_program(ctx)["equipment_committed_cents"] == 0
    assert read_assignment(ctx, ctx["assignments"]["tara"])["status"] == "NOTIFIED"
