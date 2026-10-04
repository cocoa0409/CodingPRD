"""Enrollment file upload: screening, student resolution, supersession, OCC."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    create_institution_with_registrars, create_period_payload,
    add_agreement, add_period, advance_clock, get_period_version,
    setup_period_scenario, setup_uploaded_file, upload_file,
    list_file_entries, enrollment_row, create_enrollment_file_payload,
    make_submitter_headers, make_certifier_headers, make_rows,
    assert_enrollment_entry,
)

OPS = TEST_USERS["ops_headers"]


def test_file_upload_row_partition_computed(api):
    """PRD section 3.3: "`credit_hours` below zero or above the 30-credit
    ceiling as `INVALID_CREDITS`".
    PRD section 3.3: "The file records `row_count` (every row ever attached,
    including correction-created entries later), `accepted_rows`, and
    `rejected_rows`".
    PRD section 3.3: "Each accepted entry's status fields — `status_code`,
    `census_status_code`, and `deferment_status` — are computed as-of the
    upload date per §3.4; rejected rows keep `NONE` in all of them."

    Design: Corner/entities/file_upload_row_partition_computed
    """
    ctx = setup_period_scenario()
    file = upload_file(ctx, [
        enrollment_row(student_ref="S1", full_name="Good One",
                       date_of_birth="2004-01-01"),
        enrollment_row(student_ref="S2", full_name="Bad Credits",
                       date_of_birth="2004-01-02", credit_hours=31.0),
        enrollment_row(student_ref="S3", full_name="Good Two",
                       date_of_birth="2004-01-03", credit_hours=9.0),
    ])
    assert file["row_count"] == 3
    assert file["accepted_rows"] == 2
    assert file["rejected_rows"] == 1
    entries = list_file_entries(file["id"])
    assert entries[1]["entry_status"] == "REJECTED"
    assert entries[1]["reject_reason"] == "INVALID_CREDITS", "31.0 > 30"
    assert entries[1]["status_code"] == "NONE"
    assert_enrollment_entry(entries[0])


def test_screening_reject_reason_matrix(api):
    """PRD section 3.3: "a later row repeating an already-seen `student_ref`
    is rejected with `reject_reason` `DUPLICATE_STUDENT_IN_FILE`. A row
    missing a required field is rejected as `MISSING_FIELD`; an unrecognized
    `career_level` value as `INVALID_ENUM_VALUE`; `credit_hours` below zero
    or above the 30-credit ceiling as `INVALID_CREDITS`; a `term_end` not
    strictly after its `term_start` as `INVALID_TERM_DATES`; and a
    `withdrawal_date` that falls before the row's `term_start` or after its
    `term_end` as `INVALID_WITHDRAWAL_DATE`."
    PRD section 3.4: "an `UNDERGRAD` is `FULL_TIME` at 12.0 credits or more".

    Design: Corner/entities/screening_reject_reason_matrix
    """
    ctx = setup_period_scenario()
    missing_credits = enrollment_row(
        student_ref="M1", full_name="Miss Field", date_of_birth="2004-01-03",
    )
    del missing_credits["credit_hours"]
    file = upload_file(ctx, [
        enrollment_row(student_ref="DUP", full_name="Dup One",
                       date_of_birth="2004-01-01"),
        enrollment_row(student_ref="DUP", full_name="Dup Two",
                       date_of_birth="2004-01-02"),
        missing_credits,
        enrollment_row(student_ref="E1", full_name="Enum Bad",
                       date_of_birth="2004-01-04", career_level="PHD"),
        enrollment_row(student_ref="C1", full_name="Credits Bad",
                       date_of_birth="2004-01-05", credit_hours=30.5),
        enrollment_row(student_ref="T1", full_name="Term Bad",
                       date_of_birth="2004-01-06", term_end="2026-09-01"),
        enrollment_row(student_ref="W1", full_name="Wd Bad",
                       date_of_birth="2004-01-07",
                       withdrawal_date="2026-12-20"),
        enrollment_row(student_ref="MAX", full_name="Max Credits",
                       date_of_birth="2004-01-08", credit_hours=30.0),
    ])
    assert file["row_count"] == 8
    assert file["accepted_rows"] == 2
    assert file["rejected_rows"] == 6
    entries = list_file_entries(file["id"])
    assert entries[1]["reject_reason"] == "DUPLICATE_STUDENT_IN_FILE"
    assert entries[2]["reject_reason"] == "MISSING_FIELD"
    assert entries[3]["reject_reason"] == "INVALID_ENUM_VALUE"
    assert entries[4]["reject_reason"] == "INVALID_CREDITS"
    assert entries[5]["reject_reason"] == "INVALID_TERM_DATES"
    assert entries[6]["reject_reason"] == "INVALID_WITHDRAWAL_DATE"
    assert entries[7]["entry_status"] == "ACCEPTED"
    assert entries[7]["status_code"] == "FULL_TIME", "30.0 is not above 30"


def test_student_resolution_matches_normalized_name_and_dob(api):
    """PRD section 3.3: "Every accepted row resolves its student: the system
    matches on the lowercased, whitespace-trimmed `full_name` together with
    `date_of_birth`, reusing the existing StudentRecord on a match and
    creating one otherwise."
    PRD section 3.3: "Rows are examined in payload order — the first row
    carries `row_index` zero".

    Design: Corner/entities/student_resolution_matches_normalized_name_and_dob
    """
    ctx = setup_period_scenario()
    file = upload_file(ctx, [
        enrollment_row(student_ref="S1", full_name="Ada Lovelace"),
        enrollment_row(student_ref="S2", full_name="ada lovelace",
                       credit_hours=9.0),
        enrollment_row(student_ref="S3", full_name="Ada Lovelace",
                       date_of_birth="2004-05-13", credit_hours=9.0),
    ])
    entries = list_file_entries(file["id"])
    assert entries[0]["student_id"] == entries[1]["student_id"], (
        "case-normalized name plus the same date_of_birth resolve to one "
        "student"
    )
    assert entries[2]["student_id"] != entries[0]["student_id"], (
        "same name with a different date_of_birth is a distinct student"
    )
    student = validate_success(
        api_client.get_student(entries[0]["student_id"], OPS), 200,
    )
    assert student["full_name"] == "Ada Lovelace", (
        "the record is created from the first row's reported name"
    )


def test_student_deferment_standing_defaults_to_none(api):
    """PRD section 3.3: "A student record carries `full_name`,
    `date_of_birth`, and a `deferment_standing` that begins at `NONE` and
    thereafter reflects the most recently acknowledged servicer
    notification (§3.4)."
    PRD section 2.5: "`version` (integer): starts at 1 at creation".

    Design: Corner/entities/student_deferment_standing_defaults_to_none
    """
    ctx = setup_uploaded_file()
    student = validate_success(
        api_client.get_student(ctx["entries"][0]["student_id"], OPS), 200,
    )
    assert student["deferment_standing"] == "NONE"
    assert student["version"] == 1


def test_uploaded_file_superseded_by_reupload(api):
    """PRD section 3.3: "Upload supersedes the period's prior uncertified
    file: any previous file still `UPLOADED` for the same period moves to
    `SUPERSEDED`, and its entries — both `REJECTED` ones, which keep their
    `reject_reason`, and `ACCEPTED` ones — move to `SUPERSEDED` with it."
    PRD section 3.2: "`upload_count`, which begins at zero and increments by
    one on every successful enrollment-file upload for the period".

    Design: Corner/state_machines/uploaded_file_superseded_by_reupload
    """
    ctx = setup_uploaded_file()
    f1_id = ctx["file_id"]
    f2 = upload_file(ctx, [enrollment_row(
        student_ref="S2", full_name="Second Student",
        date_of_birth="2004-06-01", credit_hours=9.0,
    )])
    f1 = validate_success(api_client.get_enrollment_file(f1_id, OPS), 200)
    assert f1["status"] == "SUPERSEDED"
    f1_entries = list_file_entries(f1_id)
    assert f1_entries[0]["entry_status"] == "SUPERSEDED"
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["upload_count"] == 2


def test_occ_stale_period_version_rejected(api):
    """PRD section 2.6: "An upload legitimately supersedes any prior
    uncertified file for the period and increments the period's
    `upload_count` — hence its `version` — so a stale token means the
    client's view of the period is out of date; the upload is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.2: "Each such advance increments the period's `version`."

    Design: Corner/complexity_layers/occ_stale_period_version_rejected
    """
    ctx = setup_period_scenario()
    observed = get_period_version(ctx["inst_id"])
    assert observed == 2, "1 at create plus 1 on the SCHEDULED-to-OPEN advance"
    upload_file(ctx, [enrollment_row()], expected_version=observed)

    stale = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], observed,
            [enrollment_row(student_ref="S2", full_name="Second Student",
                            date_of_birth="2004-06-01", credit_hours=9.0)],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    refreshed = get_period_version(ctx["inst_id"])
    assert refreshed == 3
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["upload_count"] == 1
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], refreshed,
            [enrollment_row(student_ref="S2", full_name="Second Student",
                            date_of_birth="2004-06-01", credit_hours=9.0)],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_success(resp, 201)


def test_upload_while_period_scheduled_rejected(api):
    """PRD section 3.3: "the period must not still be `SCHEDULED` — uploads
    are accepted while the period is `OPEN`, in `GRACE`, or `CLOSED`, with
    the closed period serving as the delinquency remedy path, while a
    `SCHEDULED` period rejects the upload with `ERR_PERIOD_NOT_OPEN`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/file_upload_requires_period_not_scheduled
    """
    # No clock advance: at the pinned default time the Fall period is
    # still SCHEDULED, and the OCC token presented is the correct one.
    ctx = setup_period_scenario(advance_to=None)
    version = get_period_version(ctx["inst_id"])
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], version, [enrollment_row()],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN)


def test_upload_accepted_once_period_opens(api):
    """PRD section 3.3: "the period must not still be `SCHEDULED` — uploads
    are accepted while the period is `OPEN`, in `GRACE`, or `CLOSED`".
    PRD section 3.2: "`OPEN` once now reaches `submission_opens_at`".

    Design: Difficulty/cross_entity_state_dependency/file_upload_requires_period_not_scheduled
    """
    ctx = setup_period_scenario(advance_to=None)
    advance_clock("2026-11-01T00:00:00Z")
    version = get_period_version(ctx["inst_id"])
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], version, [enrollment_row()],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    file = validate_success(resp, 201)
    assert file["status"] == "UPLOADED"


def test_err_file_not_found(api):
    """PRD section 2.8: "Each kind of unresolved reference reports its own
    error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or
    `ERR_DATASET_NOT_FOUND`, each HTTP 404".

    Design: Corner/errors/err_file_not_found
    """
    create_institution_with_registrars()
    resp = api_client.get_enrollment_file(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_FILE_NOT_FOUND)


def test_err_period_not_found(api):
    """PRD section 3.3: "the referenced institution and then the referenced
    period must exist (`ERR_INSTITUTION_NOT_FOUND`, then
    `ERR_PERIOD_NOT_FOUND`)".

    Design: Corner/errors/err_period_not_found
    """
    ctx = setup_period_scenario(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    version = get_period_version(ctx["inst_id"])
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], NON_EXISTENT_UUID, version,
            [enrollment_row(term_start="2026-08-01")],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_FOUND)


def test_err_institution_suspended_on_upload(api):
    """PRD section 3.3: "the institution must be `ACTIVE`
    (`ERR_INSTITUTION_SUSPENDED`)".

    Design: Corner/errors/err_institution_suspended_on_upload
    """
    ctx = setup_period_scenario(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    version = get_period_version(ctx["inst_id"])
    validate_success(api_client.suspend_institution(ctx["inst_id"], OPS), 200)
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], version,
            [enrollment_row(term_start="2026-08-01")],
        ),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTITUTION_SUSPENDED)
    data, meta = validate_paginated(
        api_client.list_enrollment_files(OPS, params={"institution_id": ctx["inst_id"]}),
    )
    assert meta["total_count"] == 0, "no file was persisted"


def test_rbac_certifier_cannot_upload(api):
    """PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 3.3: "Reporting begins when a `RegistrarSubmitter` uploads an
    enrollment file."

    Design: Corner/rbac/rbac_certifier_cannot_upload
    """
    ctx = setup_period_scenario()
    version = get_period_version(ctx["inst_id"])
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], version, [enrollment_row()],
        ),
        make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_rbac_ops_cannot_upload(api):
    """PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 3.3: "Reporting begins when a `RegistrarSubmitter` uploads an
    enrollment file."

    Design: Corner/rbac/rbac_ops_cannot_upload
    """
    ctx = setup_period_scenario()
    version = get_period_version(ctx["inst_id"])
    resp = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            ctx["inst_id"], ctx["period_id"], version, [enrollment_row()],
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_cross_institution_preempts_period_existence(api):
    """PRD section 3.3: "Before any row is examined, the upload passes an
    ordered gauntlet, and the first failure wins. The submitter's institution
    must match the file's institution (`ERR_CROSS_INSTITUTION_ACCESS`); the
    payload must be well-formed (`ERR_VALIDATION`); the referenced
    institution and then the referenced period must exist
    (`ERR_INSTITUTION_NOT_FOUND`, then `ERR_PERIOD_NOT_FOUND`)".

    Design: Corner/validations/cross_institution_preempts_period_existence
    """
    a = create_institution_with_registrars(name="University A",
                                           ope_id="00123400")
    b = create_institution_with_registrars(name="University B",
                                           ope_id="00999900")
    add_agreement(a["inst_id"])
    period = add_period(
        a["inst_id"], term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    version = get_period_version(a["inst_id"])
    rows = [enrollment_row(term_start="2026-08-01")]

    bogus_period = api_client.create_enrollment_file(
        create_enrollment_file_payload(
            a["inst_id"], NON_EXISTENT_UUID, version, rows,
        ),
        make_submitter_headers(b["sub_uid"]),
    )
    validate_error(bogus_period, ApiErrorId.ERR_CROSS_INSTITUTION_ACCESS)

    real_period = api_client.create_enrollment_file(
        create_enrollment_file_payload(a["inst_id"], period["id"], version, rows),
        make_submitter_headers(b["sub_uid"]),
    )
    validate_error(real_period, ApiErrorId.ERR_CROSS_INSTITUTION_ACCESS)


def test_entries_list_pagination_envelope(api):
    """PRD section 2.3: "`limit` caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips
    a number of items and defaults to 0."
    PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."
    PRD section 3.3: "entries are listed in file order — `row_index`
    ascending within a file, then `created_at` ascending".

    Design: Corner/endpoints/entries_list_pagination_envelope
    """
    ctx = setup_period_scenario()
    file = upload_file(ctx, make_rows(12))
    page1, meta1 = validate_paginated(
        api_client.list_enrollment_entries(OPS, params={"file_id": file["id"]}),
    )
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert page1[0]["student_ref"] == "S01"
    assert page1[9]["student_ref"] == "S10"

    page2, meta2 = validate_paginated(
        api_client.list_enrollment_entries(
            OPS, params={"file_id": file["id"], "limit": 10, "offset": 10},
        ),
    )
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
    assert page2[0]["student_ref"] == "S11"
    assert page2[1]["student_ref"] == "S12"
