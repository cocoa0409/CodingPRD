"""Enrollment: creation, activation, suspension, exit and the slot accounting."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_enrollment_payload, open_assessment, open_screen,
    verify_screen, submit_assessment, route_assessment, determine_screen,
    walk_screen_to_eligible, walk_screen_to_routed, find_enrollment,
    list_enrollments_for, activate_enrollment, setup_landscape, setup_capacity_pair,
    setup_active_enrollment, setup_frozen_grant, refresh_screen, ApiErrorId,
    INTAKE, PROGRAM, COMPLIANCE,
)


def test_client_get_computed_open_enrollment_count_after_activation():
    """PRD §3.5: "The client's `open_enrollment_count` is defined as the number
    of that client's enrollment rows sitting in `PENDING`, `ACTIVE` or
    `SUSPENDED` status, and it is recomputed from live rows whenever the client
    record is read."
    PRD §3.5: "Both paths set the status to `ACTIVE`, increment the client's
    `open_enrollment_count` by one, and increment the enrollment's `version`."

    Design: Corner/entities/client_get_computed_open_enrollment_count_after_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()
    walked = walk_screen_to_eligible(client["id"], landscape["program"]["id"],
                                     landscape["grant"]["id"])

    activate_enrollment(walked["enrollment"]["id"])

    after = get_success_data(api_client.get_client(client["id"], INTAKE))
    assert after["open_enrollment_count"] == 1
    assert after["id"] == client["id"]
    assert after["confidentiality_tier"] == "STANDARD"


def test_enrollment_activate_from_terminal_exited_returns_invalid_state():
    """PRD §3.5: "The enrollment lifecycle admits `PENDING`, `ACTIVE`,
    `SUSPENDED`, `EXITED` and `DENIED`, and the last two are terminal — an
    enrollment that has exited or been denied can never be reactivated."
    PRD §2.10: "`ERR_INVALID_STATE` (HTTP 409) fires whenever the target
    resource's current status is not the from-state of any transition the
    endpoint may trigger — which includes any attempt to leave a terminal
    state".

    Design: Corner/state_machines/enrollment_activate_from_terminal_exited_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()
    walked = walk_screen_to_eligible(client["id"], landscape["program"]["id"],
                                     landscape["grant"]["id"])
    exited = get_success_data(api_client.exit_enrollment(
        walked["enrollment"]["id"], {"exit_reason": "WITHDRAWN"}, PROGRAM))

    resp = api_client.activate_enrollment(walked["enrollment"]["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api_client.get_enrollment(walked["enrollment"]["id"], PROGRAM))
    assert after["status"] == "EXITED"
    assert after["version"] == exited["version"]
    assert after["exited_at"] == "2026-09-01T00:00:00.000Z"


def test_enrollment_activate_twice_returns_invalid_state():
    """PRD §3.5: "A `PENDING` enrollment may be activated when its grant is in
    `OPEN` or `THROTTLED` posture".
    PRD §2.10: "`ERR_INVALID_STATE` (HTTP 409) fires whenever the target
    resource's current status is not the from-state of any transition the
    endpoint may trigger".

    Design: Corner/state_machines/enrollment_activate_twice_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment()

    resp = api_client.activate_enrollment(ctx["enrollment"]["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    client = get_success_data(api_client.get_client(ctx["client"]["id"], INTAKE))
    assert client["open_enrollment_count"] == 1, "no second increment happens"
    enrollment = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert enrollment["version"] == ctx["enrollment"]["version"]


def test_direct_enrollment_without_established_eligibility_screen_is_rejected():
    """PRD §3.5: "A direct enrollment names `client_id`, `program_id` and
    `grant_id`, and it is admissible only when the door has already done its
    work — an eligibility screen must exist for that client, program and grant
    carrying a `determination` of `ELIGIBLE` and a `verification_state` of
    `VERIFIED`. Without it the request is refused with
    `ERR_ELIGIBILITY_NOT_ESTABLISHED` (HTTP 409)."

    Design: Corner/validations/direct_enrollment_without_established_eligibility_screen_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()

    resp = api_client.create_enrollment(
        create_enrollment_payload(client["id"], landscape["program"]["id"],
                                  landscape["grant"]["id"]),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_NOT_ESTABLISHED)
    assert list_enrollments_for(client["id"]) == []


def test_direct_enrollment_after_eligible_screen_rejects_duplicate_program_enrollment():
    """PRD §3.5: "The client must also hold no enrollment for the same program
    in `PENDING`, `ACTIVE` or `SUSPENDED` status, or the request is refused with
    `ERR_CLIENT_ALREADY_ENROLLED` (HTTP 409)".
    PRD §3.4: "it sets `determination` to `ELIGIBLE` and creates an `Enrollment`
    in `PENDING` status carrying the assessment's client, the screen's
    `program_id` and the screen's `grant_id`."

    Design: Corner/validations/direct_enrollment_after_eligible_screen_rejects_duplicate_program_enrollment
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()
    walk_screen_to_eligible(client["id"], landscape["program"]["id"],
                            landscape["grant"]["id"])

    resp = api_client.create_enrollment(
        create_enrollment_payload(client["id"], landscape["program"]["id"],
                                  landscape["grant"]["id"]),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_ALREADY_ENROLLED)

    enrollments = list_enrollments_for(client["id"])
    assert len(enrollments) == 1, "only the cascade-created PENDING row exists"
    assert enrollments[0]["status"] == "PENDING"


def test_enrollment_create_then_withdrawn_exit_conserves_slots_and_open_count():
    """PRD §3.4: "creating an enrollment and then exiting it with an exit reason
    of `WITHDRAWN` leaves both the program's `enrolled_slots` and the client's
    `open_enrollment_count` at exactly the values they held before the
    enrollment was created."
    PRD §3.5: "A `PENDING` enrollment may exit only with an `exit_reason` of
    `WITHDRAWN` — a client who never started cannot have completed."

    Design: Difficulty/compensating_invariant/enrollment_create_then_withdrawn_exit_conserves_slots_and_open_count
    """
    ctx = setup_capacity_pair(capacity_slots=1, first_activate=True,
                              second_verify=True, second_route=True, second_submit=True,
                              clock="2026-09-02T00:00:00Z")

    refused = api_client.determine_eligibility_screen(
        ctx["screen_two"]["id"], {"determination": "ELIGIBLE"}, COMPLIANCE
    )
    validate_error(refused, ApiErrorId.ERR_PROGRAM_CAPACITY_EXCEEDED)

    exited = get_success_data(api_client.exit_enrollment(
        ctx["enrollment"]["id"], {"exit_reason": "WITHDRAWN"}, PROGRAM))
    assert exited["status"] == "EXITED"
    assert exited["exit_reason"] == "WITHDRAWN"

    admitted = api_client.determine_eligibility_screen(
        ctx["screen_two"]["id"], {"determination": "ELIGIBLE"}, COMPLIANCE
    )
    validate_success(admitted)

    second_enrollments = list_enrollments_for(ctx["client_two"]["id"])
    assert len(second_enrollments) == 1, "the freed slot admits the second client"

    first_client = get_success_data(api_client.get_client(ctx["client_one"]["id"], INTAKE))
    assert first_client["open_enrollment_count"] == 0, (
        "the compensating exit restores the pre-create count"
    )


def test_enrollment_activation_gated_by_governing_grant_posture():
    """PRD §2.12: "From that point on, the frozen grant refuses all child
    writes: creating an enrollment, activating an enrollment, authorizing
    service units, recording a delivery, documenting a delivery and billing a
    delivery are all rejected with `ERR_GRANT_FROZEN` (HTTP 409) while the
    governing grant remains frozen."
    PRD §3.5: "A `SUSPENDED` enrollment may be reinstated under a slightly
    narrower rule: the grant must again be `OPEN` or `THROTTLED`".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_gated_by_governing_grant_posture
    """
    ctx = setup_frozen_grant(
        units_delivered=1, unit_rate_cents=1000,
        grant_overrides={"total_award_cents": 1000, "admin_rate_pct": 0.10},
        # The authorization window must cover the clock the scenario runs at,
        # or the delivery is refused for want of a covering ACTIVE
        # authorization (§3.6) before the freeze can be reached.
        authorization_overrides={"authorized_units": 5, "unit_rate_cents": 1000,
                                 "period_start": "2026-09-01T00:00:00Z",
                                 "period_end": "2026-11-01T00:00:00Z"},
        clock="2026-10-02T00:00:00Z",
    )
    assert ctx["grant"]["status"] == "FROZEN", "the documentation froze the governing grant"
    assert ctx["enrollment"]["status"] == "SUSPENDED", (
        "the freeze cascade suspended the enrollment that produced the delivery"
    )

    resp = api_client.activate_enrollment(ctx["enrollment"]["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_GRANT_FROZEN)

    after = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert after["status"] == "SUSPENDED", "the refused reactivation changes nothing"


def test_exit_response_and_client_counter_agree_within_the_same_cycle():
    """PRD §3.5: "Every exit path sets the status to `EXITED`, stamps `exited_at`
    with the current logical clock, decrements the program's `enrolled_slots` by
    one, and increments the enrollment's `version`."
    PRD §3.5: "Exiting from `ACTIVE` additionally decrements the client's
    `open_enrollment_count` by one".

    Design: Corner/consistency_model/exit_response_and_client_counter_agree_within_the_same_cycle
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_enrollment(clock="2026-09-02T00:00:00Z")
    before = get_success_data(api_client.get_client(ctx["client"]["id"], INTAKE))
    assert before["open_enrollment_count"] == 1

    resp = api_client.exit_enrollment(ctx["enrollment"]["id"], {"exit_reason": "COMPLETED"},
                                      PROGRAM)
    data = validate_success(resp)
    assert data["status"] == "EXITED"
    assert data["exit_reason"] == "COMPLETED"
    assert data["exited_at"] == "2026-09-02T00:00:00.000Z"

    after = get_success_data(api_client.get_client(ctx["client"]["id"], INTAKE))
    assert after["open_enrollment_count"] == 0
