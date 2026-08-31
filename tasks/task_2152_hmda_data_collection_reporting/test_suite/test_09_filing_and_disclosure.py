"""Filing the register: the deadline comparison, the archive cascade, the public
disclosure artifacts and the reject-and-refile cycle."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_FILING_DEADLINE,
    TEST_USERS,
    assert_disclosure_statement,
    attach_run,
    certify_submission,
    file_submission,
    list_disclosure_statements,
    make_compliance_officer_headers,
    read_application,
    read_institution,
    read_submission,
    resubmit_submission,
    review_submission,
    set_clock,
    setup_certified_submission_on_empty_register,
    setup_certified_submission_over_locked_record,
    setup_filed_submission_on_empty_register,
    setup_filed_submission_over_locked_record,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_accepted_filing_is_terminal(api):
    """PRD §3.7: "An acceptance moves the submission `FILED → ACCEPTED`, which is
    terminal — nothing further happens to the register."
    PRD §3.7: "A `ComplianceOfficer` returns a rejected submission to draft by
    supplying a `reason`, which is defined only from `REJECTED` and otherwise
    refused with `ERR_INVALID_SUBMISSION_STATE`."

    Design: Corner/state_machines/accepted_submission_is_terminal_and_resubmit_rejected
    """
    _institution, _run, submission = setup_filed_submission_on_empty_register()
    review_submission(submission["id"], "ACCEPT")

    validate_error(
        api.resubmit_submission(
            submission["id"], {"reason": "Trying to reopen an accepted filing."},
            make_compliance_officer_headers(),
        ),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value,
    )

    after = read_submission(submission["id"])
    assert after["status"] == "ACCEPTED"
    assert after["resubmission_count"] == 0
    assert after["final_record_count"] == 0


def test_filing_archives_the_locked_record_and_closes_the_year(api):
    """PRD §3.7: "Caused by hop 1: every register record of the submission's final
    set whose stage reads `REGISTER_LOCKED` moves `REGISTER_LOCKED → ARCHIVED`."
    PRD §3.7: "Caused by hop 2: the institution's `open_register_count` is
    recomputed, and when it reaches 0 the institution's `filing_posture` moves
    `FILED_YEAR → CLOSED_YEAR`."
    PRD §3.7: "The submission moves `CERTIFIED → FILED` and `filed_at` is set to
    the current logical clock."
    PRD §3.7: "Lateness is evaluated against `deadline_at`: `is_late` is true
    only when `filed_at` is strictly later than `deadline_at`, so a filing landing
    exactly on the deadline instant is on time. When the filing is on time
    `late_by_days` is 0; when it is late, `late_by_days` is the elapsed seconds
    between `deadline_at` and `filed_at` divided by 86400 and rounded **up** to the
    next whole day, which means any lateness at all produces at least 1."

    Design: Difficulty/transitive_cascade/filing_drives_three_hop_archive_and_year_close
    """
    scenario = setup_certified_submission_over_locked_record()
    set_clock("2027-02-01T00:00:00Z")

    filed = validate_success(
        api.file_submission(scenario["submission"]["id"], make_compliance_officer_headers())
    )
    assert filed["status"] == "FILED"
    assert filed["filed_at"] == "2027-02-01T00:00:00.000Z"
    assert filed["is_late"] is False
    assert filed["late_by_days"] == 0

    assert read_application(scenario["application"]["id"])["stage"] == "ARCHIVED"

    institution = read_institution(scenario["institution"]["id"])
    assert institution["open_register_count"] == 0
    assert institution["filing_posture"] == "CLOSED_YEAR"


def test_filing_publishes_both_disclosure_statements_with_suppression_counts(api):
    """PRD §3.7: "Filing also publishes exactly two disclosure artifacts, appended
    in this order: first a statement whose `statement_type` reads `MODIFIED_LAR`,
    then one whose `statement_type` reads `DISCLOSURE_REPORT`."
    PRD §3.7: "Both carry the same numbers, and both carry `published_at` set to
    the logical clock at filing and a `submission_id` naming the filing that
    produced them. `record_count` on each equals the submission's
    `final_record_count`."
    PRD §3.7: "A group is suppressed when any one of three conditions holds: it is
    the group of records with no tract; or it holds fewer than 5 records; or the
    tract's `owner_occupied_units` is below 500."
    PRD §2.4: "`DisclosureStatement` rows are append-only publication artifacts:
    they likewise carry only `id` and `created_at`, with no `updated_at` and no
    `version`."
    PRD §3.7: "`tract_suppression_count` is the number of suppressed groups,
    `suppressed_record_count` is the total number of records inside them, and
    `redacted_field_count` is `suppressed_record_count` multiplied by 3, the three
    fields redacted from each suppressed record."

    Design: Difficulty/transitive_cascade/filing_drives_three_hop_archive_and_year_close
    """
    scenario = setup_filed_submission_over_locked_record()

    statements, meta = validate_paginated(
        api.list_submission_disclosure_statements(
            scenario["submission"]["id"], TEST_USERS["examiner_headers"]
        )
    )
    assert meta["total_count"] == 2
    assert [row["statement_type"] for row in statements] == [
        "MODIFIED_LAR", "DISCLOSURE_REPORT"
    ]

    for row in statements:
        assert_disclosure_statement(row)
        assert row["record_count"] == 1
        assert row["tract_suppression_count"] == 1
        assert row["suppressed_record_count"] == 1
        assert row["redacted_field_count"] == 3
        assert row["published_at"] == "2027-02-01T00:00:00.000Z"


def test_filing_exactly_on_the_deadline_instant_is_on_time(api):
    """PRD §3.7: "Lateness is evaluated against `deadline_at`: `is_late` is true
    only when `filed_at` is strictly later than `deadline_at`, so a filing landing
    exactly on the deadline instant is on time."
    PRD §3.1: "Sixth, `filing_deadline_at` is set to the first of March of the year
    following `activity_year`, at 23:59:59.000 UTC."

    Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_instant_versus_one_second_late
    """
    _institution, _run, submission = setup_certified_submission_on_empty_register()
    assert submission["deadline_at"] == DEFAULT_FILING_DEADLINE

    set_clock("2027-03-01T23:59:59Z")
    filed = validate_success(
        api.file_submission(submission["id"], make_compliance_officer_headers())
    )
    assert filed["status"] == "FILED"
    assert filed["is_late"] is False
    assert filed["late_by_days"] == 0


def test_filing_one_second_after_the_deadline_is_one_day_late(api):
    """PRD §3.7: "Lateness is evaluated against `deadline_at`: `is_late` is true
    only when `filed_at` is strictly later than `deadline_at`, so a filing landing
    exactly on the deadline instant is on time."
    PRD §3.7: "When the filing is on time `late_by_days` is 0; when it is late,
    `late_by_days` is the elapsed seconds between `deadline_at` and `filed_at`
    divided by 86400 and rounded **up** to the next whole day, which means any
    lateness at all produces at least 1."

    Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_instant_versus_one_second_late
    """
    _institution, _run, submission = setup_certified_submission_on_empty_register(
        officer_id="officer-beta"
    )

    set_clock("2027-03-02T00:00:00Z")
    filed = validate_success(
        api.file_submission(
            submission["id"], make_compliance_officer_headers("officer-beta")
        )
    )
    assert filed["status"] == "FILED"
    assert filed["is_late"] is True
    assert filed["late_by_days"] == 1


def test_a_rejected_filing_returns_to_draft_and_files_again(api):
    """PRD §3.7: "A rejection moves it `FILED → REJECTED`, stores
    `rejection_reason`, returns every record archived by this filing from
    `ARCHIVED` back to `REGISTER_LOCKED`, sets the institution's `filing_posture`
    back to `OPEN`, and recomputes `open_register_count`."
    PRD §3.7: "Lateness is evaluated against `deadline_at`: `is_late` is true
    only when `filed_at` is strictly later than `deadline_at`, so a filing landing
    exactly on the deadline instant is on time. When the filing is on time
    `late_by_days` is 0; when it is late, `late_by_days` is the elapsed seconds
    between `deadline_at` and `filed_at` divided by 86400 and rounded **up** to the
    next whole day, which means any lateness at all produces at least 1."
    PRD §3.7: "The submission moves `REJECTED → DRAFT`, its `resubmission_count`
    rises by one, and every downstream field is cleared so the cycle can begin
    again cleanly: `edit_run_id`, `certified_by_user_id`, `certified_at`,
    `attestation_text`, `final_record_count`, `filed_at`, `is_late`, and
    `late_by_days`."

    Design: Difficulty/non_linear_state_machine/submission_filed_rejected_resubmitted_and_refiled_cycle
    """
    scenario = setup_filed_submission_over_locked_record()
    submission_id = scenario["submission"]["id"]

    review_submission(
        submission_id, "REJECT",
        rejection_reason="Census tract assignment could not be reconciled against the FFIEC file.",
    )
    assert read_application(scenario["application"]["id"])["stage"] == "REGISTER_LOCKED"
    assert read_institution(scenario["institution"]["id"])["filing_posture"] == "OPEN"

    back_to_draft = validate_success(
        api.resubmit_submission(
            submission_id, {"reason": "Tract reconciled; refiling the same register."},
            make_compliance_officer_headers(),
        )
    )
    assert back_to_draft["status"] == "DRAFT"
    assert back_to_draft["resubmission_count"] == 1
    assert back_to_draft["edit_run_id"] is None
    assert back_to_draft["final_record_count"] is None

    attach_run(submission_id, scenario["run"]["id"])
    certify_submission(submission_id, attestation_text="Cycle two attestation.")
    refiled = file_submission(submission_id)

    assert refiled["status"] == "FILED"
    assert refiled["resubmission_count"] == 1
    assert refiled["final_record_count"] == 1
    assert refiled["is_late"] is False
    assert refiled["late_by_days"] == 0
    assert refiled["rejection_reason"] == (
        "Census tract assignment could not be reconciled against the FFIEC file."
    )


def test_the_second_filing_cycle_republishes_the_disclosure_artifacts(api):
    """PRD §3.7: "Filing also publishes exactly two disclosure artifacts, appended
    in this order: first a statement whose `statement_type` reads `MODIFIED_LAR`,
    then one whose `statement_type` reads `DISCLOSURE_REPORT`."
    PRD §3.7: "Caused by hop 2: the institution's `open_register_count` is
    recomputed, and when it reaches 0 the institution's `filing_posture` moves
    `FILED_YEAR → CLOSED_YEAR`."

    Design: Difficulty/non_linear_state_machine/submission_filed_rejected_resubmitted_and_refiled_cycle
    """
    scenario = setup_filed_submission_over_locked_record()
    submission_id = scenario["submission"]["id"]

    review_submission(
        submission_id, "REJECT",
        rejection_reason="Census tract assignment could not be reconciled against the FFIEC file.",
    )
    resubmit_submission(submission_id, reason="Tract reconciled; refiling the same register.")
    attach_run(submission_id, scenario["run"]["id"])
    certify_submission(submission_id, attestation_text="Cycle two attestation.")
    file_submission(submission_id)

    statements = list_disclosure_statements(submission_id, params={"limit": 100, "offset": 0})
    assert len(statements) == 4, (
        "each of the two filing cycles appends its own pair of disclosure artifacts"
    )
    assert [row["statement_type"] for row in statements] == [
        "MODIFIED_LAR", "DISCLOSURE_REPORT", "MODIFIED_LAR", "DISCLOSURE_REPORT"
    ]

    assert read_application(scenario["application"]["id"])["stage"] == "ARCHIVED"
    assert read_institution(scenario["institution"]["id"])["filing_posture"] == "CLOSED_YEAR"
