"""The edit battery: the snapshot, the nine edits, exception verification, the
verification quota and the half-open review windows."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    TRACT_A,
    assert_edit_exception,
    assert_edit_run,
    create_application,
    create_edit_run,
    create_edit_run_payload,
    create_institution,
    list_run_exceptions,
    make_compliance_analyst_headers,
    read_application,
    read_edit_run,
    setup_institution_and_tract,
    setup_originated_application,
    setup_register_with_macro_exception,
    setup_register_with_quality_exception,
    setup_register_with_validity_exception,
    validate_error,
    validate_paginated,
    validate_success,
    verify_exception,
    verify_exception_payload,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_a_record_with_no_geocode_draws_a_validity_exception(api):
    """PRD §3.6: "`V631`, severity `VALIDITY`, on `census_tract_id`: fires when the
    record has no current geocode assignment at all, or when its current
    assignment's status is `AMBIGUOUS`, `NOT_MATCHED`, or `PENDING`."
    PRD §3.6: "Each snapshot record that drew at least one record-level exception
    moves to `EXCEPTION_FLAGGED` — from `COMPLETE`, from `PENDING_FIELDS`, or back
    from `CLEARED` if a later run finds a new problem on a record an earlier run
    had cleared, in which case the institution's `cleared_record_count` falls by
    one."
    PRD §3.6: "If at least one exception was raised, it settles `RUNNING →
    COMPLETED`."

    Design: Corner/calculations/edit_run_flags_unresolved_geocode_as_a_validity_exception
    """
    scenario = setup_register_with_validity_exception()
    run = scenario["run"]
    assert_edit_run(run)

    assert run["snapshot_record_count"] == 1
    assert run["validity_count"] == 1
    assert run["syntactical_count"] == 0
    assert run["quality_count"] == 0
    assert run["macro_count"] == 0
    assert run["total_exception_count"] == 1
    assert run["open_exception_count"] == 1
    assert run["cleared_record_count"] == 0
    assert run["status"] == "COMPLETED"
    assert run["required_verified_quota"] == 0
    assert scenario["application"]["lar_status"] == "EXCEPTION_FLAGGED"

    exceptions = scenario["exceptions"]
    assert len(exceptions) == 1
    assert_edit_exception(exceptions[0])
    assert exceptions[0]["edit_code"] == "V631"
    assert exceptions[0]["severity"] == "VALIDITY"


def test_a_short_loan_identifier_draws_a_syntactical_exception(api):
    """PRD §3.6: "`S300`, severity `SYNTACTICAL`, on `uli`: fires when the record's
    `uli` is shorter than 23 characters."
    PRD §3.6: "Each exception records its `edit_code`, its `severity`, the
    `field_name` the edit points at, a human-readable `message`, the `edit_run_id`
    of the run that raised it, and the `application_id` of the record it
    concerns."

    Design: Corner/calculations/edit_run_flags_short_uli_as_a_syntactical_exception
    """
    institution, _tract = setup_institution_and_tract()
    record = setup_originated_application(
        institution["id"], uli="10BX939C554", geocode=True,
        submitted_tract_code=TRACT_A["tract_code"],
    )
    run = create_edit_run(institution["id"])

    assert run["syntactical_count"] == 1
    assert run["validity_count"] == 0
    assert run["total_exception_count"] == 1

    exceptions = list_run_exceptions(run["id"])
    assert len(exceptions) == 1
    assert exceptions[0]["edit_code"] == "S300"
    assert exceptions[0]["severity"] == "SYNTACTICAL"
    assert exceptions[0]["field_name"] == "uli"
    assert read_application(record["id"])["lar_status"] == "EXCEPTION_FLAGGED"


def test_the_macro_edit_carries_a_null_register_record(api):
    """PRD §3.6: "`Q800`, severity `MACRO`, on `action_taken`, fires when the
    snapshot holds at least one record and the share of snapshot records whose
    `action_taken` reads `WITHDRAWN`, expressed as a percentage of
    `snapshot_record_count`, is strictly greater than 30.0 percent."
    PRD §3.6: "A macro exception carries a null `application_id`, since it
    describes the register as a whole rather than any one record."
    PRD §3.6: "The raw quota is one tenth of `snapshot_record_count`, rounded up to
    the next whole number; `required_verified_quota` is then the smaller of that
    raw quota and the sum of `quality_count` and `macro_count`, so a run can never
    demand more verifications than it has verifiable exceptions."

    Design: Corner/calculations/edit_run_macro_edit_fires_with_null_application_id
    """
    scenario = setup_register_with_macro_exception()
    run = scenario["run"]

    assert run["macro_count"] == 1
    assert run["syntactical_count"] == 0
    assert run["validity_count"] == 0
    assert run["quality_count"] == 0
    assert run["required_verified_quota"] == 1
    assert run["cleared_record_count"] == 1
    assert run["status"] == "COMPLETED"

    assert scenario["application"]["lar_status"] == "CLEARED"
    assert scenario["application"]["applicable_field_count"] == 11

    exceptions = scenario["exceptions"]
    assert len(exceptions) == 1
    assert exceptions[0]["edit_code"] == "Q800"
    assert exceptions[0]["application_id"] is None


def test_the_snapshot_skips_records_with_no_action_taken(api):
    """PRD §3.6: "The run freezes a snapshot of the register at the moment it
    starts: every register record of the institution that has an `action_taken`
    recorded, whose `is_superseded` flag is false, whose `lar_status` is anything
    other than `EXCLUDED`, and whose `stage` reads either `DECISIONED` or
    `REGISTER_LOCKED`."
    PRD §3.6: "Records outside the snapshot are untouched by the run in every
    respect."

    Design: Corner/calculations/edit_run_snapshot_excludes_intake_records_without_action_taken
    """
    institution = create_institution()
    at_intake = create_application(institution["id"])
    decisioned = setup_originated_application(
        institution["id"], application_date="2026-02-11T00:00:00Z",
        loan_purpose="REFINANCING", loan_amount_cents=28000000, income_thousands=130,
    )

    run = create_edit_run(institution["id"])
    assert run["snapshot_record_count"] == 1
    assert run["total_exception_count"] == 1

    untouched = read_application(at_intake["id"])
    assert untouched["lar_status"] == "PENDING_FIELDS"
    assert untouched["stage"] == "INTAKE"

    intake_rows, intake_meta = validate_paginated(
        api.list_application_edit_exceptions(at_intake["id"], TEST_USERS["examiner_headers"])
    )
    assert intake_rows == []
    assert intake_meta["total_count"] == 0

    decisioned_rows, decisioned_meta = validate_paginated(
        api.list_application_edit_exceptions(
            decisioned["id"], TEST_USERS["examiner_headers"]
        )
    )
    assert decisioned_meta["total_count"] == 1
    assert len(decisioned_rows) == 1


def test_verifying_an_already_verified_exception_is_rejected(api):
    """PRD §3.6: "Verification is defined only from `OPEN`; an exception already
    `VERIFIED` or `STALE` is refused with `ERR_EXCEPTION_NOT_OPEN`."
    PRD §3.6: "A successful verification moves the exception `OPEN → VERIFIED`,
    stores the `verification_note`, records the acting analyst's identifier as
    `verified_by_user_id` and the current logical clock as `verified_at`,
    decrements the run's `open_exception_count` by one, increments its
    `verified_exception_count` by one, and increments the exception's `version` by
    1."

    Design: Corner/state_machines/verify_same_exception_twice_returns_exception_not_open
    """
    scenario = setup_register_with_quality_exception()
    exception = scenario["exception"]
    verify_exception(exception["id"], "analyst-nova", verification_note="First verification.")

    validate_error(
        api.verify_edit_exception(
            exception["id"],
            verify_exception_payload(verification_note="Second verification attempt."),
            make_compliance_analyst_headers("analyst-vega"),
        ),
        ApiErrorId.ERR_EXCEPTION_NOT_OPEN.value,
    )

    after = list_run_exceptions(scenario["run"]["id"])[0]
    assert after["verified_by_user_id"] == "analyst-nova"

    run = read_edit_run(scenario["run"]["id"])
    assert run["verified_exception_count"] == 1
    assert run["total_exception_count"] == 1


def test_a_validity_exception_may_not_be_verified(api):
    """PRD §3.6: "Only `QUALITY` and `MACRO` exceptions may be verified at all —
    `SYNTACTICAL` and `VALIDITY` exceptions describe data that is simply wrong and
    must be corrected in the register and cleared by a later run, so verifying one
    is refused with `ERR_SEVERITY_NOT_VERIFIABLE`."

    Design: Corner/validations/verify_on_a_validity_exception_rejected
    """
    scenario = setup_register_with_validity_exception()
    exception = scenario["exception"]

    validate_error(
        api.verify_edit_exception(
            exception["id"],
            verify_exception_payload(verification_note="Trying to wave through a validity edit."),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_SEVERITY_NOT_VERIFIABLE.value,
    )

    after = list_run_exceptions(scenario["run"]["id"])[0]
    assert after["status"] == "OPEN"
    assert after["severity"] == "VALIDITY"
    assert read_edit_run(scenario["run"]["id"])["verified_exception_count"] == 0


def test_verifying_an_unknown_exception_is_a_not_found(api):
    """PRD §2.6: "Path identifiers are resolved strictly left to right, and the
    first identifier that fails to resolve determines the response."
    PRD §2.9: "Path identifier resolution, left to right — the relevant not-found
    error, 404."

    Design: Corner/errors/verify_unknown_exception_returns_not_found
    """
    validate_error(
        api.verify_edit_exception(
            UNKNOWN_ID,
            verify_exception_payload(verification_note="No such exception."),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EDIT_EXCEPTION_NOT_FOUND.value,
    )


def test_a_review_window_that_ends_where_it_starts_is_malformed(api):
    """PRD §3.6: "A run's window must be well formed: `window_end` must be strictly
    later than `window_start`, and a run whose end is at or before its start is
    refused with `ERR_INVALID_WINDOW`."
    PRD §2.9: "Interval well-formedness — `ERR_INVALID_WINDOW`, 422.
    15. Structural constraints, in this order — `ERR_EDIT_RUN_WINDOW_OVERLAP`
    (409), `ERR_REMEDIATION_WINDOW_OVERLAP` (409), `ERR_DUPLICATE_ULI` (409),
    `ERR_DUPLICATE_LEI` (409), `ERR_DUPLICATE_DEMOGRAPHIC_ROLE` (409),
    `ERR_TOO_MANY_RACE_CODES` (422), `ERR_SEVERITY_NOT_VERIFIABLE` (422)."

    Design: Corner/validations/edit_run_window_end_before_start_rejected
    """
    institution = create_institution()
    first = create_edit_run(
        institution["id"], window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )

    error = validate_error(
        api.create_edit_run(
            create_edit_run_payload(
                institution["id"], scope="INCREMENTAL",
                window_start="2026-08-02T00:00:00Z", window_end="2026-08-02T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_INVALID_WINDOW.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_EDIT_RUN_WINDOW_OVERLAP.value

    assert read_edit_run(first["id"])["status"] == "CLEARED_ALL"
    rows, meta = validate_paginated(
        api.list_institution_edit_runs(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_the_verification_quota_is_pinned_to_the_frozen_snapshot(api):
    """PRD §3.6: "It is computed exactly once, inside the run that creates it, and
    is never recomputed while exceptions are being worked — this is deliberate,
    because verifying an exception clears records, which would change what counts
    as reportable, which would change the quota, and the platform breaks that
    circularity by pinning the base to the snapshot frozen at run start, before any
    verification has happened."
    PRD §3.6: "The raw quota is one tenth of `snapshot_record_count`, rounded up to
    the next whole number; `required_verified_quota` is then the smaller of that
    raw quota and the sum of `quality_count` and `macro_count`, so a run can never
    demand more verifications than it has verifiable exceptions."

    Design: Difficulty/combinatorial_formula/verification_quota_pinned_to_pre_verification_snapshot
    """
    scenario = setup_register_with_quality_exception()
    run_before = scenario["run"]
    assert run_before["snapshot_record_count"] == 1
    assert run_before["quality_count"] == 1
    assert run_before["macro_count"] == 0
    assert run_before["required_verified_quota"] == 1

    verify_exception(scenario["exception"]["id"], "analyst-nova")

    run_after = read_edit_run(run_before["id"])
    assert run_after["required_verified_quota"] == 1, (
        "the quota is pinned to the snapshot frozen at run start"
    )
    assert run_after["snapshot_record_count"] == 1
    assert run_after["cleared_record_count"] == 1


def test_verifying_the_only_quality_exception_clears_the_run(api):
    """PRD §3.6: "`Q615`, severity `QUALITY`, on `action_taken_date`: fires when
    the whole number of days between `application_date` and `action_taken_date`
    exceeds 180, the half-year mark from receipt to decision."
    PRD §3.6: "It then bubbles upward in three hops: if the record now carries no
    open exception from the current run, it moves `EXCEPTION_FLAGGED → CLEARED`
    and the institution's `cleared_record_count` rises by one; caused by that, the
    run's own `cleared_record_count` rises by one; and caused by that, when the
    run's `cleared_record_count` reaches `snapshot_record_count`, the run moves
    `COMPLETED → CLEARED_ALL`."

    Design: Difficulty/combinatorial_formula/verification_quota_pinned_to_pre_verification_snapshot
    """
    scenario = setup_register_with_quality_exception()
    assert scenario["exception"]["edit_code"] == "Q615"

    verify_exception(scenario["exception"]["id"], "analyst-nova")

    run = read_edit_run(scenario["run"]["id"])
    assert run["verified_exception_count"] == 1
    assert run["open_exception_count"] == 0
    assert run["cleared_record_count"] == 1
    assert run["status"] == "CLEARED_ALL"
    assert read_application(scenario["application"]["id"])["lar_status"] == "CLEARED"


def test_an_overlapping_review_window_is_rejected(api):
    """PRD §3.6: "A new run is refused with `ERR_EDIT_RUN_WINDOW_OVERLAP` when an
    existing run of the same institution whose status is anything other than
    `INVALIDATED` satisfies both of the following: the new run's start is strictly
    earlier than the existing run's end, and the existing run's start is strictly
    earlier than the new run's end."

    Design: Difficulty/resource_temporal_overlap/edit_run_half_open_windows_adjacency_allowed_overlap_rejected
    """
    institution = create_institution()
    create_edit_run(
        institution["id"], window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )

    validate_error(
        api.create_edit_run(
            create_edit_run_payload(
                institution["id"], scope="INCREMENTAL",
                window_start="2026-08-02T00:00:00Z", window_end="2026-08-04T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EDIT_RUN_WINDOW_OVERLAP.value,
    )


def test_a_review_window_starting_at_an_existing_end_instant_is_accepted(api):
    """PRD §3.6: "Review windows on one institution are **half-open**, covering
    their start instant and everything up to but excluding their end instant."
    PRD §3.6: "Touching windows are therefore accepted — a new run starting at
    exactly the instant an existing run ends does not collide — while a run
    already invalidated never blocks anything."
    PRD §3.6: "Completing a run supersedes the institution's earlier work: every
    exception belonging to every earlier non-invalidated run of the same
    institution moves to `STALE` — from `OPEN`, decrementing that run's
    `open_exception_count` and incrementing its `stale_exception_count`, or from
    `VERIFIED`, decrementing that run's `verified_exception_count` and incrementing
    its `stale_exception_count` — and each of those earlier runs moves to
    `INVALIDATED`."

    Design: Difficulty/resource_temporal_overlap/edit_run_half_open_windows_adjacency_allowed_overlap_rejected
    """
    institution = create_institution()
    first = create_edit_run(
        institution["id"], window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )

    validate_error(
        api.create_edit_run(
            create_edit_run_payload(
                institution["id"], scope="INCREMENTAL",
                window_start="2026-08-02T00:00:00Z", window_end="2026-08-04T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EDIT_RUN_WINDOW_OVERLAP.value,
    )

    adjacent = validate_success(
        api.create_edit_run(
            create_edit_run_payload(
                institution["id"], scope="INCREMENTAL",
                window_start="2026-08-03T00:00:00Z", window_end="2026-08-04T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert adjacent["window_start"] == "2026-08-03T00:00:00.000Z"
    assert adjacent["status"] == "CLEARED_ALL"
    assert read_edit_run(first["id"])["status"] == "INVALIDATED"

    rows, meta = validate_paginated(
        api.list_institution_edit_runs(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
