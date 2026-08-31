"""The decertification cascade, the two independent register dimensions and the
conserved accounting identities either side of a compensating correction."""

from test_helpers import (
    assert_edit_run_ledger_identity,
    assert_register_accounting_identity,
    advance_application,
    list_run_exceptions,
    read_application,
    read_edit_run,
    read_institution,
    read_submission,
    record_action,
    reopen_application,
    setup_certified_submission_over_verified_exception,
    setup_institution_and_tract,
    setup_decisioned_application,
    setup_register_with_quality_exception,
    verify_exception,
)

LAGGED = {"application_date": "2026-01-05T00:00:00Z"}
LAGGED_ACTION = {"action_taken_date": "2026-07-20T00:00:00Z"}


def test_verification_moves_the_quality_dimension_without_touching_the_stage(api):
    """PRD §3.2: "Every register record carries `stage`, describing how far the
    field-capture workflow has progressed, and `lar_status`, describing how clean
    the record currently is. They evolve independently on the same row: a record
    may perfectly well be `DECISIONED` and `PENDING_FIELDS` at the same time, or
    `DECISIONED` and `EXCEPTION_FLAGGED`."
    PRD §3.6: "It then bubbles upward in three hops: if the record now carries no
    open exception from the current run, it moves `EXCEPTION_FLAGGED → CLEARED`
    and the institution's `cleared_record_count` rises by one; caused by that, the
    run's own `cleared_record_count` rises by one; and caused by that, when the
    run's `cleared_record_count` reaches `snapshot_record_count`, the run moves
    `COMPLETED → CLEARED_ALL`."

    Design: Difficulty/non_linear_state_machine/application_stage_and_lar_status_are_independent_dimensions
    """
    scenario = setup_register_with_quality_exception()
    flagged = scenario["application"]
    assert flagged["stage"] == "REGISTER_LOCKED"
    assert flagged["lar_status"] == "EXCEPTION_FLAGGED"

    verify_exception(scenario["exception"]["id"], "analyst-nova",
                     verification_note="Lag verified against the underwriting file.")

    after = read_application(flagged["id"])
    assert after["stage"] == "REGISTER_LOCKED", (
        "the capture stage is untouched by the register-quality movement"
    )
    assert after["lar_status"] == "CLEARED"


def test_the_field_counts_and_run_ledger_after_the_dimensions_diverge(api):
    """PRD §3.2: "Ten fields are always applicable: `uli`, `application_date`,
    `application_channel`, `loan_type`, `loan_purpose`, `occupancy_type`,
    `lien_status`, `loan_amount_cents`, `action_taken`, and `action_taken_date`. If
    the owning institution is **not** partially exempt, `income_thousands` joins the
    applicable set, and three further conditional additions apply on top of it: when
    `action_taken` reads `ORIGINATED`, both `rate_spread` and `purchaser_type`
    become applicable; when `action_taken` reads `PURCHASED_LOAN`, `purchaser_type`
    becomes applicable; and when `action_taken` reads `DENIED`,
    `denial_reason_codes` becomes applicable."
    PRD §3.6: "A successful verification moves the exception `OPEN → VERIFIED`,
    stores the `verification_note`, records the acting analyst's identifier as
    `verified_by_user_id` and the current logical clock as `verified_at`, decrements
    the run's `open_exception_count` by one, increments its
    `verified_exception_count` by one, and increments the exception's `version` by
    1."

    Design: Difficulty/non_linear_state_machine/application_stage_and_lar_status_are_independent_dimensions
    """
    scenario = setup_register_with_quality_exception()
    verify_exception(scenario["exception"]["id"], "analyst-nova",
                     verification_note="Lag verified against the underwriting file.")

    record = read_application(scenario["application"]["id"])
    assert record["captured_field_count"] == 13
    assert record["applicable_field_count"] == 13

    run = read_edit_run(scenario["run"]["id"])
    assert run["quality_count"] == 1
    assert run["status"] == "CLEARED_ALL"

    exception = list_run_exceptions(run["id"])[0]
    assert exception["status"] == "VERIFIED"
    assert exception["verified_by_user_id"] == "analyst-nova"


def test_reopening_reverts_the_record_and_its_verified_exception(api):
    """PRD §3.2: "The record returns `REGISTER_LOCKED → DECISIONED`, and both
    `action_taken` and `action_taken_date` are cleared. Completeness is recomputed,
    which necessarily moves the register-quality dimension to `PENDING_FIELDS` —
    including from `CLEARED`, the one path by which a record leaves `CLEARED` for
    `PENDING_FIELDS`."
    PRD §3.2: "Caused by hop 1: every edit exception naming this record whose status
    reads `VERIFIED` reverts to `OPEN`, with its `verified_by_user_id`,
    `verified_at`, and `verification_note` all cleared. The owning edit run's
    `verified_exception_count` falls, its `open_exception_count` rises, and its
    `cleared_record_count` falls by one."

    Design: Difficulty/transitive_cascade/reopen_drives_five_hop_decertification_chain
    """
    scenario = setup_certified_submission_over_verified_exception()

    reopen_application(
        scenario["application"]["id"], "analyst-nova",
        reason="Source document shows a different application date.",
    )

    record = read_application(scenario["application"]["id"])
    assert record["stage"] == "DECISIONED"
    assert record["action_taken"] is None
    assert record["action_taken_date"] is None
    assert record["lar_status"] == "PENDING_FIELDS"

    exception = list_run_exceptions(scenario["run"]["id"])[0]
    assert exception["status"] == "OPEN"
    assert exception["verified_by_user_id"] is None
    assert exception["verified_at"] is None
    assert exception["verification_note"] is None

    run = read_edit_run(scenario["run"]["id"])
    assert run["verified_exception_count"] == 0
    assert run["open_exception_count"] == 1
    assert run["cleared_record_count"] == 0


def test_reopening_invalidates_the_run_and_decertifies_the_submission(api):
    """PRD §3.2: "Caused by hop 2: that edit run's status becomes `INVALIDATED`,
    because its snapshot no longer describes the register."
    PRD §3.2: "Caused by hop 3: every filing submission attached to that run whose
    status reads `EDITS_ATTACHED` or `CERTIFIED` returns to `DRAFT`. On a submission
    returning from `CERTIFIED`, the attachment and the whole certification are
    erased — `edit_run_id`, `certified_by_user_id`, `certified_at`,
    `attestation_text`, and `final_record_count` are all cleared."
    PRD §3.2: "Caused by hop 4: the institution's `filing_posture` returns from
    `LOCKED_FOR_FILING` to `OPEN`."

    Design: Difficulty/transitive_cascade/reopen_drives_five_hop_decertification_chain
    """
    scenario = setup_certified_submission_over_verified_exception()
    assert scenario["submission"]["status"] == "CERTIFIED"
    assert scenario["institution"]["filing_posture"] == "LOCKED_FOR_FILING"

    reopen_application(
        scenario["application"]["id"], "analyst-nova",
        reason="Source document shows a different application date.",
    )

    assert read_edit_run(scenario["run"]["id"])["status"] == "INVALIDATED"

    submission = read_submission(scenario["submission"]["id"])
    assert submission["status"] == "DRAFT"
    assert submission["edit_run_id"] is None
    assert submission["certified_by_user_id"] is None
    assert submission["certified_at"] is None
    assert submission["final_record_count"] is None

    institution = read_institution(scenario["institution"]["id"])
    assert institution["filing_posture"] == "OPEN"
    assert institution["cleared_record_count"] == 0


def test_recording_the_action_moves_a_record_from_pending_to_reportable(api):
    """PRD §3.2: "Otherwise, if `captured_field_count` equals
    `applicable_field_count`, the record becomes `COMPLETE` with `exclusion_reason`
    set back to `NOT_EXCLUDED`, and the institution's `pending_record_count` falls
    by one while `reportable_record_count` rises by one."
    PRD §3.1: "`total_application_count` counts every register record belonging to
    the institution, `pending_record_count` counts those whose register-quality
    dimension reads `PENDING_FIELDS`, `reportable_record_count` counts those reading
    `COMPLETE`, `EXCEPTION_FLAGGED`, or `CLEARED`, `excluded_record_count` counts
    those reading `EXCLUDED`, `cleared_record_count` counts those reading `CLEARED`,
    and `open_register_count` counts every record whose capture stage is anything
    other than `ARCHIVED`."

    Design: Difficulty/compensating_invariant/register_record_accounting_survives_action_taken_then_reopen
    """
    institution, _tract = setup_institution_and_tract()
    record = setup_decisioned_application(
        institution["id"], geocode=True,
        submitted_tract_code="06075010100",
        application_channel="FACE_TO_FACE",
        demographic_overrides={
            "collection_method": "VISUAL_OBSERVATION_OR_SURNAME",
            "observation_basis": "VISUAL",
        },
    )

    before = read_institution(institution["id"])
    assert before["pending_record_count"] == 1
    assert before["reportable_record_count"] == 0
    assert_register_accounting_identity(before)

    record_action(record["id"])

    after = read_institution(institution["id"])
    assert after["pending_record_count"] == 0
    assert after["reportable_record_count"] == 1
    assert_register_accounting_identity(after)


def test_reopening_returns_every_register_counter_to_its_pre_action_value(api):
    """PRD §3.2: "The institution's `pending_record_count`,
    `reportable_record_count`, and `cleared_record_count` are recomputed
    accordingly, with `cleared_record_count` and `reportable_record_count` each
    falling by one and `pending_record_count` rising by one when the record had been
    `CLEARED`."
    PRD §3.1: "`total_application_count` counts every register record belonging to
    the institution, `pending_record_count` counts those whose register-quality
    dimension reads `PENDING_FIELDS`, `reportable_record_count` counts those reading
    `COMPLETE`, `EXCEPTION_FLAGGED`, or `CLEARED`, `excluded_record_count` counts
    those reading `EXCLUDED`, `cleared_record_count` counts those reading `CLEARED`,
    and `open_register_count` counts every record whose capture stage is anything
    other than `ARCHIVED`."

    Design: Difficulty/compensating_invariant/register_record_accounting_survives_action_taken_then_reopen
    """
    institution, _tract = setup_institution_and_tract()
    record = setup_decisioned_application(
        institution["id"], geocode=True,
        submitted_tract_code="06075010100",
        application_channel="FACE_TO_FACE",
        demographic_overrides={
            "collection_method": "VISUAL_OBSERVATION_OR_SURNAME",
            "observation_basis": "VISUAL",
        },
    )
    before = read_institution(institution["id"])

    record_action(record["id"])
    advance_application(record["id"], "REGISTER_LOCKED")

    reopen_application(
        record["id"], "analyst-nova",
        reason="Compensating correction: action taken recorded against the wrong file.",
    )

    after = read_institution(institution["id"])
    assert after["pending_record_count"] == before["pending_record_count"] == 1
    assert after["reportable_record_count"] == before["reportable_record_count"] == 0
    assert after["excluded_record_count"] == 0
    assert after["total_application_count"] == 1
    assert_register_accounting_identity(after)
    assert read_application(record["id"])["lar_status"] == "PENDING_FIELDS"


def test_verification_moves_one_exception_from_open_to_verified(api):
    """PRD §3.6: "`syntactical_count`, `validity_count`, `quality_count`, and
    `macro_count` hold the number of exceptions raised at each severity, and
    `total_exception_count` is their sum. Every newly raised exception starts
    `OPEN`, so `open_exception_count` initially equals `total_exception_count`,
    while `verified_exception_count` and `stale_exception_count` both start at
    zero."
    PRD §3.6: "A successful verification moves the exception `OPEN → VERIFIED`,
    stores the `verification_note`, records the acting analyst's identifier as
    `verified_by_user_id` and the current logical clock as `verified_at`, decrements
    the run's `open_exception_count` by one, increments its
    `verified_exception_count` by one, and increments the exception's `version` by
    1."

    Design: Difficulty/compensating_invariant/edit_exception_ledger_survives_verify_then_reopen
    """
    scenario = setup_register_with_quality_exception()
    before = scenario["run"]
    assert before["total_exception_count"] == 1
    assert before["open_exception_count"] == 1
    assert before["verified_exception_count"] == 0
    assert before["stale_exception_count"] == 0
    assert_edit_run_ledger_identity(before)

    verify_exception(scenario["exception"]["id"], "analyst-nova",
                     verification_note="Lag confirmed against the underwriting file.")

    after = read_edit_run(before["id"])
    assert after["open_exception_count"] == 0
    assert after["verified_exception_count"] == 1
    assert after["total_exception_count"] == 1
    assert_edit_run_ledger_identity(after)


def test_reopening_returns_the_exception_ledger_to_its_pre_verification_state(api):
    """PRD §3.6: "The reverse path exists too. When a register record is reopened
    (§3.2), its `VERIFIED` exceptions revert `VERIFIED → OPEN` with
    `verified_by_user_id`, `verified_at`, and `verification_note` all cleared, and
    the owning run moves to `INVALIDATED` from either `COMPLETED` or
    `CLEARED_ALL`."
    PRD §3.6: "`syntactical_count`, `validity_count`, `quality_count`, and
    `macro_count` hold the number of exceptions raised at each severity, and
    `total_exception_count` is their sum. Every newly raised exception starts
    `OPEN`, so `open_exception_count` initially equals `total_exception_count`,
    while `verified_exception_count` and `stale_exception_count` both start at
    zero."

    Design: Difficulty/compensating_invariant/edit_exception_ledger_survives_verify_then_reopen
    """
    scenario = setup_register_with_quality_exception()
    verify_exception(scenario["exception"]["id"], "analyst-nova",
                     verification_note="Lag confirmed against the underwriting file.")

    reopen_application(
        scenario["application"]["id"], "analyst-nova",
        reason="Compensating correction after verification.",
    )

    after = read_edit_run(scenario["run"]["id"])
    assert after["open_exception_count"] == 1
    assert after["verified_exception_count"] == 0
    assert after["stale_exception_count"] == 0
    assert after["total_exception_count"] == 1
    assert_edit_run_ledger_identity(after)

    exception = list_run_exceptions(scenario["run"]["id"])[0]
    assert exception["status"] == "OPEN"
