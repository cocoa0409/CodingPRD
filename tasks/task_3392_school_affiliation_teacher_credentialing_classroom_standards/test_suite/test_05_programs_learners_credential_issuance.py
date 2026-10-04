"""Teacher education programs, learner enrollment constraints, and the
credential-issuance gates (practicum verification, program accreditation,
per-level uniqueness).
"""

from test_helpers import (
    ACCREDITATION_REVIEWER,
    REGISTRAR,
    ApiErrorId,
    create_accredited_program,
    create_active_catalog,
    create_adult_learner_payload,
    create_credential_payload,
    create_placement,
    create_program,
    create_verified_placement,
    date_of,
    enroll_learner,
    issue_credential,
    log_hours,
    make_program_director_headers,
    read_learner,
    read_program,
    reset_clock,
    set_program_status,
    set_program_status_payload,
    setup_affiliate_host_school,
    validate_error,
    validate_success,
    verify_placement,
)


def test_learner_enrollment_rejected_for_unoffered_age_level(api):
    """PRD section 3.4: "an `age_level` the program does not offer fails with
    `ERR_AGE_LEVEL_MISMATCH` (HTTP 422)". PRD section 2.7: "Tier 4 is field
    shape: required fields present, enum members valid, numeric ranges honored,
    `materials_groups` non-empty with `present_count` no greater than
    `required_count` in every group, logged `hours` greater than zero — all
    failing with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/learner_enrollment_rejected_for_unoffered_age_level
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Levels TEP")

    wrong_level = api.create_adult_learner(
        create_adult_learner_payload(program["id"], full_name="Wrong Level", age_level="SECONDARY"),
        headers=make_program_director_headers(program["id"]),
    )
    validate_error(wrong_level, ApiErrorId.ERR_AGE_LEVEL_MISMATCH)

    garbage_level = api.create_adult_learner(
        create_adult_learner_payload(
            program["id"], full_name="Garbage Level", age_level="KINDERGARTEN"
        ),
        headers=make_program_director_headers(program["id"]),
    )
    validate_error(garbage_level, ApiErrorId.ERR_VALIDATION)


def test_program_accreditation_rejected_when_practicum_below_catalog(api):
    """PRD section 3.4: "Five transitions exist: `PROVISIONAL` to `ACCREDITED`,
    granted only when the program's `practicum_hours_by_level` meets or exceeds
    the `ACTIVE` catalog's `practicum_min_hours_by_level` for every offered
    level — shortfalls are rejected with `ERR_PRACTICUM_STANDARD_UNMET`
    (HTTP 422)".

    Design: Corner/state_machines/program_accreditation_rejected_when_practicum_below_catalog
    """
    reset_clock()
    create_active_catalog()
    short = create_program(
        name="Short TEP", practicum_hours_by_level={"EARLY_CHILDHOOD": 539}
    )
    full = create_program(name="Full TEP")

    rejected = api.set_program_status(
        short["id"],
        set_program_status_payload("ACCREDITED"),
        headers=ACCREDITATION_REVIEWER,
    )
    validate_error(rejected, ApiErrorId.ERR_PRACTICUM_STANDARD_UNMET)
    assert read_program(short["id"])["status"] == "PROVISIONAL"

    granted = set_program_status(full["id"], "ACCREDITED")
    assert granted["status"] == "ACCREDITED", "equality meets the 540-hour minimum"


def test_issuance_blocked_while_program_not_accredited(api):
    """PRD section 3.5: "the learner's program must be `ACCREDITED`, failing
    with `ERR_PROGRAM_NOT_ACCREDITED` (HTTP 409)".

    Design: Corner/validations/issuance_blocked_while_program_not_accredited
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Prov TEP")
    learner = enroll_learner(program["id"], full_name="Prov Learner")
    host = setup_affiliate_host_school()
    create_verified_placement(learner["id"], program["id"], host.school["id"])

    blocked = api.create_credential(
        create_credential_payload(learner["id"]), headers=REGISTRAR
    )
    validate_error(blocked, ApiErrorId.ERR_PROGRAM_NOT_ACCREDITED)

    set_program_status(program["id"], "ACCREDITED")
    issued = issue_credential(learner["id"])
    assert issued["status"] == "ACTIVE"


def _staged_placement_at_539():
    """Accredited program, enrolled learner, AFFILIATE host, placement logged
    to 539 of the 540 target hours (still ACTIVE)."""
    create_active_catalog()
    program = create_accredited_program(name="Gate TEP")
    learner = enroll_learner(program["id"], full_name="Gate Learner")
    host = setup_affiliate_host_school()
    placement = create_placement(learner["id"], host.school["id"], program["id"])
    log_hours(placement["id"], learner["id"], 539)
    return program, learner, placement


def test_issuance_rejected_until_practicum_verified(api):
    """PRD section 3.5: "the learner must sit in `PRACTICUM_COMPLETE` —
    issuance ahead of verification fails with `ERR_PRACTICUM_NOT_VERIFIED`
    (HTTP 422)". PRD section 3.4: "When `hours_logged` reaches the pinned
    `target_hours` the placement auto-transitions from `ACTIVE` to
    `HOURS_COMPLETE`; landing exactly on the target completes it."

    Design: Difficulty/cross_entity_state_dependency/credential_issuance_gated_by_practicum_verification
    """
    reset_clock()
    program, learner, placement = _staged_placement_at_539()

    first = api.create_credential(
        create_credential_payload(learner["id"]),
        headers=REGISTRAR,
    )
    validate_error(first, ApiErrorId.ERR_PRACTICUM_NOT_VERIFIED)

    completed = log_hours(placement["id"], learner["id"], 1, work_date="2026-12-02")
    assert completed["status"] == "HOURS_COMPLETE", "the 1-hour log lands exactly on 540"

    second = api.create_credential(
        create_credential_payload(learner["id"]),
        headers=REGISTRAR,
    )
    validate_error(second, ApiErrorId.ERR_PRACTICUM_NOT_VERIFIED)
    assert read_learner(learner["id"])["status"] == "IN_PRACTICUM"


def test_issuance_succeeds_after_verification(api):
    """PRD section 3.4: "Verification moves the placement to `VERIFIED` and
    advances the learner from `IN_PRACTICUM` to `PRACTICUM_COMPLETE`." PRD
    section 3.5: "Issuance lands the credential in `ACTIVE` with `issued_at`
    stamped from the logical clock, `cycle_start` set to the issuance date,
    `expires_at` computed as `cycle_start` extended by the `ACTIVE` catalog's
    `credential_validity_months`, and `renewed_count` at zero".

    Design: Difficulty/cross_entity_state_dependency/credential_issuance_gated_by_practicum_verification
    """
    reset_clock()
    program, learner, placement = _staged_placement_at_539()
    log_hours(placement["id"], learner["id"], 1, work_date="2026-12-02")
    verify_placement(placement["id"], program["id"])
    assert read_learner(learner["id"])["status"] == "PRACTICUM_COMPLETE"

    issued = issue_credential(learner["id"])
    assert issued["status"] == "ACTIVE"
    assert issued["renewed_count"] == 0
    assert date_of(issued["expires_at"]) == "2029-09-01", "2026-09-01 + 36 validity months"
    assert read_learner(learner["id"])["status"] == "CREDENTIALED"
