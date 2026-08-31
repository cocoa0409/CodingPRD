"""Opening a filing submission, binding an edit run to it and certifying it."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_filing_submission,
    certify_payload,
    create_application,
    create_edit_run,
    create_institution,
    create_second_institution,
    create_submission_payload,
    make_compliance_officer_headers,
    read_application,
    read_edit_run,
    read_institution,
    read_submission,
    setup_draft_submission_on_empty_register,
    setup_invalidated_run_with_draft_submission,
    setup_register_with_macro_exception,
    setup_register_with_validity_exception,
    setup_superseded_pair_with_attached_submission,
    setup_two_banks_with_runs_and_one_attached_submission,
    setup_verified_quality_exception,
    attach_run,
    open_submission,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_opening_a_submission_with_a_stale_institution_version_is_rejected(api):
    """PRD §2.8: "Opening a filing submission requires the client to supply
    `expected_institution_version`, carrying the `version` of the `Institution` the
    client last observed. If that value does not equal the institution's current
    `version`, the create is rejected with `ERR_STALE_INSTITUTION_VERSION` and HTTP
    412, and no `FilingSubmission` row is written at all."

    Design: Corner/cross_cutting_layers/stale_expected_institution_version_on_submission_create_rejected
    """
    institution = create_institution()
    observed_version = institution["version"]
    create_application(institution["id"])

    validate_error(
        api.create_submission(
            create_submission_payload(institution["id"], observed_version),
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_STALE_INSTITUTION_VERSION.value,
    )

    fresh = read_institution(institution["id"])
    submission = validate_success(
        api.create_submission(
            create_submission_payload(institution["id"], fresh["version"]),
            make_compliance_officer_headers(),
        ),
        201,
    )
    assert_filing_submission(submission)
    assert submission["status"] == "DRAFT"
    assert submission["provisional_record_count"] == 0

    rows, meta = validate_paginated(
        api.list_institution_submissions(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_attaching_an_unknown_edit_run_is_a_not_found(api):
    """PRD §2.9: "Body foreign-key resolution — the relevant not-found error, 404.
    This applies to opening a register record, recording a demographic entry,
    creating a geocode assignment, pinning a tract by manual override, starting an
    edit run, opening a submission, attaching an edit run to a submission, drawing
    an audit sample, recording an audit finding, and computing a fair lending
    analysis."

    Design: Corner/errors/attach_unknown_edit_run_returns_not_found
    """
    _institution, _run, submission = setup_draft_submission_on_empty_register()

    validate_error(
        api.attach_edit_run(
            submission["id"], {"edit_run_id": UNKNOWN_ID}, make_compliance_officer_headers()
        ),
        ApiErrorId.ERR_EDIT_RUN_NOT_FOUND.value,
    )
    assert read_submission(submission["id"])["status"] == "DRAFT"


def test_attaching_another_banks_edit_run_is_rejected(api):
    """PRD §3.7: "The named run must belong to the same institution as the
    submission, and a run from another bank is refused with
    `ERR_EDIT_RUN_INSTITUTION_MISMATCH`."

    Design: Corner/errors/attach_edit_run_from_another_institution_rejected
    """
    institution_one = create_institution()
    institution_two = create_second_institution()
    foreign_run = create_edit_run(institution_two["id"])
    submission = open_submission(institution_one["id"])

    validate_error(
        api.attach_edit_run(
            submission["id"], {"edit_run_id": foreign_run["id"]},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_EDIT_RUN_INSTITUTION_MISMATCH.value,
    )

    after = read_submission(submission["id"])
    assert after["status"] == "DRAFT"
    assert after["edit_run_id"] is None


def test_the_runs_submissions_listing_shows_the_attachment(api):
    """PRD §3.7: "Attachment moves the submission `DRAFT → EDITS_ATTACHED`, stores
    `edit_run_id`, and increments the submission's `version` by 1."
    PRD §4: "GET | `/hmda/edit-runs/{id}/submissions` | List submissions attached
    to this run | SystemAdmin, InstitutionAdmin, ComplianceAnalyst,
    ComplianceOfficer, Examiner"

    Design: Corner/endpoints/edit_run_submissions_sub_resource_lists_the_attached_submission
    """
    _institution, run, submission = setup_draft_submission_on_empty_register()

    before, before_meta = validate_paginated(
        api.list_edit_run_submissions(run["id"], TEST_USERS["examiner_headers"])
    )
    assert before == []
    assert before_meta["total_count"] == 0

    attach_run(submission["id"], run["id"])

    after, after_meta = validate_paginated(
        api.list_edit_run_submissions(run["id"], TEST_USERS["examiner_headers"])
    )
    assert after_meta["total_count"] == 1
    assert after[0]["id"] == submission["id"]

    reread = read_submission(submission["id"])
    assert reread["edit_run_id"] == run["id"]
    assert reread["status"] == "EDITS_ATTACHED"


def test_certifying_an_unknown_submission_is_a_not_found(api):
    """PRD §2.9: "Path identifier resolution, left to right — the relevant
    not-found error, 404."
    PRD §2.6: "A request naming an institution that does not exist yields
    `ERR_INSTITUTION_NOT_FOUND`; an unknown register record yields
    `ERR_APPLICATION_NOT_FOUND`; and the same pattern holds for
    `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND`, `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CENSUS_TRACT_NOT_FOUND`, `ERR_EDIT_RUN_NOT_FOUND`,
    `ERR_EDIT_EXCEPTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, and
    `ERR_AUDIT_SAMPLE_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/errors/certify_unknown_submission_returns_not_found
    """
    validate_error(
        api.certify_submission(
            UNKNOWN_ID, certify_payload(attestation_text="No such submission."),
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value,
    )


def test_certification_is_blocked_by_an_open_validity_edit(api):
    """PRD §3.7: "Second, the attached run must carry no `OPEN` exception whose
    `severity` is `SYNTACTICAL` or `VALIDITY` — those describe data that is wrong
    rather than merely unusual, and they can only be cleared by fixing the register
    and running the battery again; an attempt while any remains is refused with
    `ERR_OPEN_VALIDITY_EDITS`."
    PRD §3.7: "Against the same database state the final count is never greater
    than the provisional one, and the two differ whenever any record is superseded,
    pending, or exception-flagged. Before certification, `final_record_count` is
    null."

    Design: Corner/validations/certify_with_open_validity_edits_rejected
    """
    scenario = setup_register_with_validity_exception()
    submission = open_submission(scenario["institution"]["id"])
    attach_run(submission["id"], scenario["run"]["id"])

    validate_error(
        api.certify_submission(
            submission["id"], certify_payload(attestation_text="Premature attestation."),
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_OPEN_VALIDITY_EDITS.value,
    )

    after = read_submission(submission["id"])
    assert after["status"] == "EDITS_ATTACHED"
    assert after["final_record_count"] is None
    assert after["provisional_record_count"] == 1
    assert read_institution(scenario["institution"]["id"])["filing_posture"] == "OPEN"


def test_certification_is_blocked_before_the_verification_quota_is_met(api):
    """PRD §3.7: "Third, the run's `verified_exception_count` must have reached at
    least its `required_verified_quota`, and a shortfall is refused with
    `ERR_VERIFICATION_QUOTA_NOT_MET`."

    Design: Corner/validations/certify_before_meeting_the_verification_quota_rejected
    """
    scenario = setup_register_with_macro_exception()
    submission = open_submission(scenario["institution"]["id"])
    attach_run(submission["id"], scenario["run"]["id"])

    validate_error(
        api.certify_submission(
            submission["id"],
            certify_payload(attestation_text="Attestation before the macro edit was reviewed."),
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_VERIFICATION_QUOTA_NOT_MET.value,
    )

    run = read_edit_run(scenario["run"]["id"])
    assert run["required_verified_quota"] == 1
    assert run["verified_exception_count"] == 0
    assert read_submission(submission["id"])["status"] == "EDITS_ATTACHED"


def test_the_analyst_who_verified_may_not_also_certify(api):
    """PRD §2.11: "The platform enforces this as a hard rule: when a
    `ComplianceOfficer` certifies a submission, the caller's `X-User-ID` must
    differ from every `verified_by_user_id` recorded on a `VERIFIED` exception of
    the attached edit run. If it matches even one, certification is refused with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD §3.7: "A successful certification moves the submission `EDITS_ATTACHED →
    CERTIFIED`, records `certified_by_user_id` as the acting officer's identifier
    and `certified_at` as the current logical clock, stores `attestation_text`,
    freezes `final_record_count` as described above, sets the institution's
    `filing_posture` to `LOCKED_FOR_FILING`, and increments the institution's
    `version` by 1."

    Design: Corner/validations/certifier_who_verified_an_exception_is_rejected_by_segregation_of_duties
    """
    scenario = setup_verified_quality_exception("shared-user-1")
    submission = open_submission(scenario["institution"]["id"], "shared-user-1")
    attach_run(submission["id"], scenario["run"]["id"], "shared-user-1")

    validate_error(
        api.certify_submission(
            submission["id"], certify_payload(attestation_text="Self-certification attempt."),
            make_compliance_officer_headers("shared-user-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    certified = validate_success(
        api.certify_submission(
            submission["id"],
            certify_payload(attestation_text="Independent officer attestation."),
            make_compliance_officer_headers("officer-alpha"),
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "officer-alpha"
    assert certified["final_record_count"] == 1
    assert read_institution(scenario["institution"]["id"])["filing_posture"] == "LOCKED_FOR_FILING"


def test_attaching_to_an_already_attached_submission_reports_the_state_error(api):
    """PRD §3.7: "Attachment is defined only from `DRAFT`; from any other status it
    is refused with `ERR_INVALID_SUBMISSION_STATE`."
    PRD §2.9: "State preconditions: the target row is in a state from which the
    requested transition is declared — `ERR_INVALID_STAGE_TRANSITION`,
    `ERR_INVALID_SUBMISSION_STATE`, `ERR_EXCEPTION_NOT_OPEN`,
    `ERR_GEOCODE_NOT_OVERRIDABLE`, `ERR_SAMPLE_NOT_OPEN`,
    `ERR_APPLICATION_ARCHIVED`, or `ERR_EDIT_RUN_INVALIDATED`, all 409."
    PRD §2.9: "Cross-field referential accuracy, in this order —
    `ERR_DENIAL_REASON_REQUIRED`, `ERR_DENIAL_REASON_NOT_PERMITTED`,
    `ERR_PURCHASER_TYPE_REQUIRED`, `ERR_GEOCODE_TRACT_MISMATCH`,
    `ERR_EDIT_RUN_INSTITUTION_MISMATCH`, `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`,
    all 422."

    Design: Difficulty/priority_pair_validation_conflict/attach_edit_run_state_error_outranks_institution_mismatch
    """
    scenario = setup_two_banks_with_runs_and_one_attached_submission()

    error = validate_error(
        api.attach_edit_run(
            scenario["submission"]["id"],
            {"edit_run_id": scenario["run_two"]["id"]},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_EDIT_RUN_INSTITUTION_MISMATCH.value


def test_the_refused_reattachment_leaves_the_original_binding_intact(api):
    """PRD §3.7: "Attachment is defined only from `DRAFT`; from any other status it
    is refused with `ERR_INVALID_SUBMISSION_STATE`."
    PRD §3.7: "Attachment moves the submission `DRAFT → EDITS_ATTACHED`, stores
    `edit_run_id`, and increments the submission's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/attach_edit_run_state_error_outranks_institution_mismatch
    """
    scenario = setup_two_banks_with_runs_and_one_attached_submission()

    validate_error(
        api.attach_edit_run(
            scenario["submission"]["id"],
            {"edit_run_id": scenario["run_two"]["id"]},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value,
    )

    after = read_submission(scenario["submission"]["id"])
    assert after["status"] == "EDITS_ATTACHED"
    assert after["edit_run_id"] == scenario["run_one"]["id"]


def test_attaching_an_invalidated_edit_run_is_rejected(api):
    """PRD §3.7: "The run's status must read either `COMPLETED` or `CLEARED_ALL`; a
    run still `RUNNING`, or one already `INVALIDATED`, is refused with
    `ERR_EDIT_RUN_INVALIDATED`."

    Design: Difficulty/cross_entity_state_dependency/attach_edit_run_blocked_when_run_was_invalidated_by_a_newer_run
    """
    scenario = setup_invalidated_run_with_draft_submission()
    assert scenario["run_one"]["status"] == "INVALIDATED"

    validate_error(
        api.attach_edit_run(
            scenario["submission"]["id"],
            {"edit_run_id": scenario["run_one"]["id"]},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_EDIT_RUN_INVALIDATED.value,
    )


def test_the_superseding_run_survives_and_the_draft_is_untouched(api):
    """PRD §3.6: "Completing a run supersedes the institution's earlier work: every
    exception belonging to every earlier non-invalidated run of the same
    institution moves to `STALE` — from `OPEN`, decrementing that run's
    `open_exception_count` and incrementing its `stale_exception_count`, or from
    `VERIFIED`, decrementing that run's `verified_exception_count` and incrementing
    its `stale_exception_count` — and each of those earlier runs moves to
    `INVALIDATED`."
    PRD §3.6: "If none was raised, it settles `RUNNING → CLEARED_ALL`, its
    `cleared_record_count` is set equal to `snapshot_record_count`, and its
    `required_verified_quota` is zero."

    Design: Difficulty/cross_entity_state_dependency/attach_edit_run_blocked_when_run_was_invalidated_by_a_newer_run
    """
    scenario = setup_invalidated_run_with_draft_submission()

    validate_error(
        api.attach_edit_run(
            scenario["submission"]["id"],
            {"edit_run_id": scenario["run_one"]["id"]},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_EDIT_RUN_INVALIDATED.value,
    )

    assert read_edit_run(scenario["run_one"]["id"])["status"] == "INVALIDATED"
    assert read_edit_run(scenario["run_two"]["id"])["status"] == "CLEARED_ALL"

    after = read_submission(scenario["submission"]["id"])
    assert after["status"] == "DRAFT"
    assert after["edit_run_id"] is None


def test_the_provisional_count_still_holds_the_superseded_original(api):
    """PRD §3.7: "`provisional_record_count` is frozen at creation and counts the
    base-set records whose `lar_status` is anything other than `EXCLUDED` — so it
    includes records still `PENDING_FIELDS` or `EXCEPTION_FLAGGED`, and it includes
    superseded originals."
    PRD §3.7: "A submission carries two counts of the register, and they are
    computed from the identical base set: every register record of the institution
    that has an `action_taken` recorded and whose `action_taken_date` falls in the
    institution's `activity_year`."

    Design: Difficulty/dual_variant_calc/submission_provisional_vs_final_record_count
    """
    scenario = setup_superseded_pair_with_attached_submission()

    assert scenario["submission"]["provisional_record_count"] == 2
    assert scenario["original"]["is_superseded"] is True
    assert scenario["original"]["lar_status"] == "CLEARED"
    assert scenario["correction"]["is_superseded"] is False
    assert scenario["correction"]["lar_status"] == "CLEARED"


def test_certification_freezes_a_final_count_that_drops_the_superseded_original(api):
    """PRD §3.7: "`final_record_count` is frozen at certification and counts only
    the base-set records whose `lar_status` reads `CLEARED` and whose
    `is_superseded` flag is false."
    PRD §3.7: "Against the same database state the final count is never greater
    than the provisional one, and the two differ whenever any record is superseded,
    pending, or exception-flagged."

    Design: Difficulty/dual_variant_calc/submission_provisional_vs_final_record_count
    """
    scenario = setup_superseded_pair_with_attached_submission()

    certified = validate_success(
        api.certify_submission(
            scenario["submission"]["id"],
            certify_payload(
                attestation_text="Register certified complete and accurate for activity year 2026."
            ),
            make_compliance_officer_headers(),
        )
    )
    assert_filing_submission(certified)
    assert certified["status"] == "CERTIFIED"
    assert certified["provisional_record_count"] == 2
    assert certified["final_record_count"] == 1
    assert certified["final_record_count"] != certified["provisional_record_count"]
    assert read_application(scenario["original"]["id"])["is_superseded"] is True
