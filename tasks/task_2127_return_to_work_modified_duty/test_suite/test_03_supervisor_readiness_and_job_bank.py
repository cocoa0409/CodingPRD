"""Supervisor readiness, the curriculum ladder and the transitional job bank."""
from test_helpers import (
    ApiErrorId,
    assert_supervisor,
    assert_training_record,
    assert_transitional_job,
    create_transitional_job_payload,
    fixtures,
    validate_error,
    validate_success,
)


def test_job_bank_entry_applies_its_declared_defaults(api, program_admin_headers):
    """PRD §3.3: "the two optional booleans `requires_overhead_reach` and `requires_driving` each default to false. An optional `risk_class` records the ergonomic band as `LOW`, `MEDIUM` or `HIGH`, defaulting to `LOW`. A new entry starts with `job_status` `OPEN` and `filled_seats` at zero"

    Design: Corner/entities/transitional_job_defaults_applied_when_optional_fields_omitted
    """
    supervisor = fixtures.create_supervisor()
    payload = create_transitional_job_payload(supervisor["id"])
    payload.pop("risk_class")

    data = validate_success(api.create_transitional_job(payload, program_admin_headers), 201)

    assert_transitional_job(data)
    assert data["risk_class"] == "LOW"
    assert data["requires_overhead_reach"] is False
    assert data["requires_driving"] is False
    assert data["job_status"] == "OPEN"
    assert data["filled_seats"] == 0


def test_pausing_a_bank_entry_writes_the_status_and_raises_the_version(api):
    """PRD §3.3: "Availability and capacity can later be adjusted by writing `job_status` — `OPEN`, `PAUSED` or `RETIRED` — or `seat_capacity`, each raising the job's `version` by 1."

    Design: Corner/endpoints/patch_transitional_job_pauses_the_bank_entry
    """
    ctx = fixtures.setup_program()
    before = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))

    data = validate_success(
        api.update_transitional_job(ctx["job_id"], {"job_status": "PAUSED"}, fixtures.COORD)
    )

    assert data["job_status"] == "PAUSED"
    assert data["seat_capacity"] == before["seat_capacity"], "seat_capacity is untouched"
    assert data["version"] == before["version"] + 1


def test_a_newer_curriculum_record_supersedes_the_prior_one(api, program_admin_headers):
    """PRD §3.3: "Filing a record has a displacement effect: any earlier record of the same supervisor with the same `curriculum_code` that is not already `SUPERSEDED` moves to `SUPERSEDED` — `VALID → SUPERSEDED`, `EXPIRING_SOON → SUPERSEDED` or `EXPIRED → SUPERSEDED` according to where it stood, the supervisor's `training_status` is recomputed, and the supervisor's `version` rises by 1."
    PRD §3.3: "Otherwise the governing record is the one in the pool with the greatest `valid_through`, and when two share the greatest `valid_through` the one with the earlier `created_at` governs — never the one with a particular `id` — and the supervisor's `training_status` is simply that governing record's `record_status`, so it reads `VALID`, `EXPIRING_SOON` or `EXPIRED`."

    Design: Corner/state_machines/newer_training_record_supersedes_prior_same_curriculum
    """
    supervisor = fixtures.create_supervisor()
    first = fixtures.create_training_record(
        supervisor["id"], curriculum_code="RTW_CORE",
        completed_on="2026-05-01", valid_through="2027-05-01",
    )

    second = validate_success(
        api.create_training_record(
            supervisor["id"],
            {"curriculum_code": "RTW_CORE", "completed_on": "2026-08-01",
             "valid_through": "2028-05-01"},
            program_admin_headers,
        ),
        201,
    )

    assert_training_record(second)
    assert second["record_status"] == "VALID"
    displaced = validate_success(api.get_training_record(first["id"], program_admin_headers))
    assert displaced["record_status"] == "SUPERSEDED"
    sup = validate_success(api.get_supervisor(supervisor["id"], program_admin_headers))
    assert sup["training_status"] == "VALID", (
        "readiness is read from the surviving record with the greatest valid_through"
    )


def test_training_status_ignores_non_core_curricula(api, program_admin_headers):
    """PRD §3.3: "A supervisor's `training_status` is a projection over `RTW_CORE` records only — records certifying `RESTRICTION_HANDLING` or `REINJURY_RESPONSE` are recorded and expire like any other but never move the supervisor's readiness. The pool consists of every `RTW_CORE` record of the supervisor whose `record_status` is not `SUPERSEDED`. If that pool is empty, `training_status` is `NONE`."

    Design: Corner/calculations/supervisor_training_status_reads_only_rtw_core_records
    """
    supervisor = fixtures.create_supervisor()
    handling = fixtures.create_training_record(
        supervisor["id"], curriculum_code="RESTRICTION_HANDLING",
        completed_on="2026-05-01", valid_through="2027-05-01",
    )

    before = validate_success(api.get_supervisor(supervisor["id"], program_admin_headers))
    assert_supervisor(before)
    assert before["training_status"] == "NONE", (
        "a RESTRICTION_HANDLING record never enters the readiness pool"
    )

    fixtures.create_training_record(
        supervisor["id"], curriculum_code="RTW_CORE",
        completed_on="2026-05-01", valid_through="2027-05-01",
    )
    after = validate_success(api.get_supervisor(supervisor["id"], program_admin_headers))
    assert after["training_status"] == "VALID"
    untouched = validate_success(api.get_training_record(handling["id"], program_admin_headers))
    assert untouched["record_status"] == "VALID", (
        "the non-core record is recorded and unaffected by the core filing"
    )


def test_activation_is_refused_while_the_supervisors_training_reads_expired(api):
    """PRD §3.6: "that supervisor's `training_status` must be `VALID` or `EXPIRING_SOON`, or the request answers `ERR_SUPERVISOR_TRAINING_EXPIRED` with HTTP 409 at priority 24. A supervisor whose training reads `EXPIRED` or `NONE` may not host a live assignment"
    PRD §3.3: "A record whose `record_status` is `VALID` or `EXPIRING_SOON` moves to `EXPIRED` — `EXPIRING_SOON → EXPIRED`, and `VALID → EXPIRED` when the warning window was skipped over — when the clock's calendar date passes `valid_through`, refreshing the supervisor's `training_status` to `EXPIRED` and returning the record's id in `expired_training_record_ids`."

    Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_supervisor_training_status
    """
    ctx = fixtures.setup_authorized_placement(
        training_overrides={"valid_through": "2026-08-10"}
    )
    clock = fixtures.set_clock("2026-08-20T00:00:00Z")
    assert ctx["training_id"] in clock["expired_training_record_ids"]

    resp = api.activate_placement(ctx["placement_id"], fixtures.COORD)

    validate_error(resp, ApiErrorId.ERR_SUPERVISOR_TRAINING_EXPIRED, 409)
    supervisor = validate_success(api.get_supervisor(ctx["supervisor_id"], fixtures.ADMIN))
    assert supervisor["training_status"] == "EXPIRED"


def test_renewing_the_core_certification_unblocks_the_identical_activation(api):
    """PRD §3.3: "Renewal is the compensating action, and it is the only path out of `EXPIRED`. The caller supplies `new_valid_through`, which must be strictly later than the clock's calendar date; the record's `record_status` returns to `VALID` from `VALID`, `EXPIRING_SOON` or `EXPIRED` alike, so `EXPIRED → VALID` and `EXPIRING_SOON → VALID` are both legal renewals, `valid_through` is overwritten with the supplied date, `renewal_count` rises by 1, the supervisor's `training_status` is recomputed, and the record's `version` rises by 1."
    PRD §3.6: "When all gates pass, the placement advances `ADJUSTER_PENDING → ACTIVE`, `activated_on` is set to the placement's `start_date`"

    Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_supervisor_training_status
    """
    ctx = fixtures.setup_authorized_placement(
        training_overrides={"valid_through": "2026-08-10"}
    )
    fixtures.set_clock("2026-08-20T00:00:00Z")
    validate_error(
        api.activate_placement(ctx["placement_id"], fixtures.COORD),
        ApiErrorId.ERR_SUPERVISOR_TRAINING_EXPIRED,
        409,
    )

    renewed = validate_success(
        api.renew_training_record(
            ctx["training_id"], {"new_valid_through": "2027-05-01"}, ctx["supervisor_headers"]
        )
    )
    assert renewed["record_status"] == "VALID"
    assert renewed["renewal_count"] == 1
    supervisor = validate_success(api.get_supervisor(ctx["supervisor_id"], fixtures.ADMIN))
    assert supervisor["training_status"] == "VALID"

    activated = validate_success(api.activate_placement(ctx["placement_id"], fixtures.COORD))
    assert activated["placement_status"] == "ACTIVE"
    assert activated["activated_on"] == "2026-08-03"


def test_a_suspended_supervisor_blocks_a_second_activation(api):
    """PRD §3.6: "the placement's supervisor must have `oversight_status` `ACTIVE`, or the request answers `ERR_SUPERVISOR_OVERSIGHT_SUSPENDED` with HTTP 409 at priority 23"
    PRD §3.8: "The second, caused by the first, recomputes the hosting supervisor's `compliance_strike_points` and, when their `effective_strike_points` has reached the suspension threshold of 2 points or more, flips that supervisor's `oversight_status` from `ACTIVE` to `SUSPENDED`."

    Design: Corner/errors/suspended_supervisor_blocks_a_second_placement_activation
    """
    ctx = fixtures.setup_active_placement()
    second = fixtures.add_second_placement(
        ctx, start_date="2026-10-01", end_date="2026-10-31"
    )
    routed = fixtures.route_to_adjuster(ctx, placement_id=second["id"])
    fixtures.decide_directive(ctx, directive_id=routed["current_adjuster_directive_id"])
    fixtures.set_clock("2026-08-05T00:00:00Z")
    fixtures.drive_supervisor_to_suspension(ctx)

    resp = api.activate_placement(second["id"], fixtures.COORD)

    validate_error(resp, ApiErrorId.ERR_SUPERVISOR_OVERSIGHT_SUSPENDED, 409)
    supervisor = validate_success(api.get_supervisor(ctx["supervisor_id"], fixtures.ADMIN))
    assert supervisor["oversight_status"] == "SUSPENDED"
    blocked = validate_success(api.get_placement(second["id"], fixtures.COORD))
    assert blocked["placement_status"] == "ADJUSTER_PENDING"
