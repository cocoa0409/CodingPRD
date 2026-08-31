"""Advancing a register record through the capture workflow, and the cross-entity
guards that block an advance."""

from test_helpers import (
    ApiErrorId,
    advance_application,
    create_application,
    create_institution,
    geocode_application,
    make_compliance_analyst_headers,
    make_loan_officer_headers,
    read_application,
    record_action,
    record_demographics,
    setup_decisioned_application,
    setup_institution_with_two_tracts,
    validate_error,
    validate_paginated,
)


def _decisioned_record_with_ambiguous_geocode():
    """Two tracts in one county make a county-only geocode ambiguous; the record
    itself still satisfies every one of its own locking preconditions."""
    institution, _tract_a, _tract_b = setup_institution_with_two_tracts()
    record = create_application(institution["id"])
    assignment = geocode_application(
        record["id"], record["version"], street_address="17 Folsom St"
    )
    record_demographics(record["id"])
    advance_application(record["id"], "UNDERWRITING")
    advance_application(record["id"], "DECISIONED")
    record_action(record["id"])
    return institution, record, assignment


def test_skipping_a_capture_stage_is_an_invalid_transition(api):
    """PRD §3.2: "Any advance request naming a stage not reachable from the
    record's present stage is likewise `ERR_INVALID_STAGE_TRANSITION`."

    Design: Corner/state_machines/advance_from_intake_straight_to_decisioned_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"])
    record_demographics(record["id"])

    validate_error(
        api.advance_application(record["id"], {"to_stage": "DECISIONED"},
                                make_loan_officer_headers()),
        ApiErrorId.ERR_INVALID_STAGE_TRANSITION.value,
    )
    assert read_application(record["id"])["stage"] == "INTAKE"


def test_leaving_intake_requires_an_applicant_demographic_row(api):
    """PRD §3.2: "`INTAKE → UNDERWRITING` requires that at least one applicant
    demographic row already exists on the record with an `applicant_role` of
    `APPLICANT`; without one the advance is refused with
    `ERR_MISSING_APPLICANT_DEMOGRAPHICS`."

    Design: Corner/state_machines/advance_to_underwriting_without_applicant_demographics_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"])
    record_demographics(
        record["id"], applicant_role="CO_APPLICANT",
        ethnicity_codes=["HISPANIC_OR_LATINO"], sex_code="FEMALE",
    )

    validate_error(
        api.advance_application(record["id"], {"to_stage": "UNDERWRITING"},
                                make_loan_officer_headers()),
        ApiErrorId.ERR_MISSING_APPLICANT_DEMOGRAPHICS.value,
    )
    assert read_application(record["id"])["stage"] == "INTAKE"


def test_reopening_a_record_that_was_never_locked_is_rejected(api):
    """PRD §3.2: "Reopening is only defined for a record whose stage reads
    `REGISTER_LOCKED`; from any other stage the request is refused with
    `ERR_INVALID_STAGE_TRANSITION`."

    Design: Corner/state_machines/reopen_from_decisioned_stage_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(institution["id"])
    assert record["stage"] == "DECISIONED"

    validate_error(
        api.reopen_application(
            record["id"], {"reason": "Attempt to reopen a record that was never locked."},
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_INVALID_STAGE_TRANSITION.value,
    )
    assert read_application(record["id"])["stage"] == "DECISIONED"


def test_locking_is_blocked_while_the_current_geocode_is_ambiguous(api):
    """PRD §3.2: "`DECISIONED → REGISTER_LOCKED` carries three preconditions:
    `action_taken` must already be recorded, otherwise
    `ERR_INVALID_STAGE_TRANSITION`; the record's current geocode assignment must
    have resolved to a tract, meaning its status reads either `MATCHED` or
    `MANUAL_OVERRIDE`, otherwise `ERR_GEOCODE_UNRESOLVED`; and `lar_status` must
    read either `COMPLETE` or `EXCLUDED`, otherwise
    `ERR_INVALID_STAGE_TRANSITION`."
    PRD §3.4: "Two or more candidates, which can only arise when no
    `submitted_tract_code` was supplied: the assignment moves `PENDING →
    AMBIGUOUS`, with `census_tract_id` and `msa_md_code` both left null."

    Design: Difficulty/cross_entity_state_dependency/register_lock_blocked_while_geocode_is_ambiguous
    """
    _institution, record, assignment = _decisioned_record_with_ambiguous_geocode()
    assert assignment["status"] == "AMBIGUOUS"

    validate_error(
        api.advance_application(record["id"], {"to_stage": "REGISTER_LOCKED"},
                                make_loan_officer_headers()),
        ApiErrorId.ERR_GEOCODE_UNRESOLVED.value,
    )


def test_ambiguous_assignment_and_record_survive_the_refused_lock(api):
    """PRD §3.4: "When no `submitted_tract_code` is supplied, the candidate set is
    every loaded tract whose `county_fips` and `state_code` both equal the
    request's."
    PRD §3.4: "Two or more candidates, which can only arise when no
    `submitted_tract_code` was supplied: the assignment moves `PENDING →
    AMBIGUOUS`, with `census_tract_id` and `msa_md_code` both left null."
    PRD §3.2: "`DECISIONED → REGISTER_LOCKED` carries three preconditions:
    `action_taken` must already be recorded, otherwise
    `ERR_INVALID_STAGE_TRANSITION`; the record's current geocode assignment must
    have resolved to a tract, meaning its status reads either `MATCHED` or
    `MANUAL_OVERRIDE`, otherwise `ERR_GEOCODE_UNRESOLVED`; and `lar_status` must
    read either `COMPLETE` or `EXCLUDED`, otherwise
    `ERR_INVALID_STAGE_TRANSITION`."

    Design: Difficulty/cross_entity_state_dependency/register_lock_blocked_while_geocode_is_ambiguous
    """
    _institution, record, assignment = _decisioned_record_with_ambiguous_geocode()

    validate_error(
        api.advance_application(record["id"], {"to_stage": "REGISTER_LOCKED"},
                                make_loan_officer_headers()),
        ApiErrorId.ERR_GEOCODE_UNRESOLVED.value,
    )

    rows, _meta = validate_paginated(
        api.list_application_geocode_assignments(
            record["id"], make_loan_officer_headers()
        )
    )
    current = [row for row in rows if row["id"] == assignment["id"]][0]
    assert current["status"] == "AMBIGUOUS"
    assert current["candidate_count"] == 2
    assert current["census_tract_id"] is None
    assert current["msa_md_code"] is None

    after = read_application(record["id"])
    assert after["stage"] == "DECISIONED"
    assert after["lar_status"] == "COMPLETE"
