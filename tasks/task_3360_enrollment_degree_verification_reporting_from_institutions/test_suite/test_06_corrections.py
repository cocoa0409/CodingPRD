"""The correction and amendment cycle (PRD section 3.5)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    advance_clock, create_institution_with_registrars,
    setup_certified_file, list_file_entries, list_student_notifications,
    list_entry_notifications, enrollment_row, create_correction_payload,
    make_submitter_headers, make_certifier_headers, make_servicer_headers,
)

OPS = TEST_USERS["ops_headers"]


def _file_case(ctx, entry_id, headers=None, **overrides):
    resp = api_client.create_correction_case(
        create_correction_payload(entry_id, **overrides),
        headers or make_submitter_headers(ctx["sub_uid"]),
    )
    return resp


def _decide(ctx, case_id, outcome="APPROVED", cert_uid=None):
    resp = api_client.decide_correction_case(
        case_id, {"outcome": outcome},
        make_certifier_headers(cert_uid or ctx["cert_uid"]),
    )
    return resp


def _filed_case_scene(api, **row_overrides):
    """Certified one-entry file with a FILED case against the entry."""
    ctx = setup_certified_file(rows=[enrollment_row(**row_overrides)])
    entry_id = ctx["entries"][0]["id"]
    case = validate_success(_file_case(
        ctx, entry_id, corrected_credit_hours=15.0,
    ), 201)
    ctx["entry_id"] = entry_id
    ctx["case_id"] = case["id"]
    return ctx


def test_correction_filing_moves_file_to_amendment_pending(api):
    """PRD section 3.5: "the case begins `FILED`, and filing has immediate
    structural effects: the owning file, if `CERTIFIED`, moves to
    `AMENDMENT_PENDING`, and its `open_correction_count` increments by one."

    Design: Difficulty/non_linear_state_machine/enrollment_file_certified_amendment_recertified_cycle
    """
    ctx = _filed_case_scene(api)
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "AMENDMENT_PENDING"
    assert file["open_correction_count"] == 1


def test_decided_case_returns_file_to_certified(api):
    """PRD section 3.5: "The file's `open_correction_count` decrements by
    one, and when the count drains to zero on a file in `AMENDMENT_PENDING`,
    the file returns to `CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/enrollment_file_certified_amendment_recertified_cycle
    """
    ctx = _filed_case_scene(api)
    validate_success(_decide(ctx, ctx["case_id"], "APPROVED"), 200)
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "CERTIFIED"
    assert file["open_correction_count"] == 0


def _applied_withdrawal_scene(api):
    """The correction cascade mid-state: N1 acknowledged, then a withdrawal
    correction APPROVED at 2026-11-16."""
    ctx = setup_certified_file(rows=[enrollment_row(
        credit_hours=15.0, servicer_ref="SVC-100",
    )])
    ctx["entry_id"] = ctx["entries"][0]["id"]
    ctx["student_id"] = ctx["entries"][0]["student_id"]
    n1 = list_entry_notifications(ctx["entry_id"])[0]
    ctx["n1_id"] = n1["id"]
    advance_clock("2026-11-16T00:00:00Z")
    validate_success(
        api_client.acknowledge_servicer_notification(
            n1["id"], make_servicer_headers("SVC-100"),
        ),
        200,
    )
    case = validate_success(_file_case(
        ctx, ctx["entry_id"],
        corrected_withdrawal_date="2026-10-15",
        reason_code="LATE_WITHDRAWAL_NOTICE",
    ), 201)
    ctx["case_id"] = case["id"]
    validate_success(_decide(ctx, case["id"], "APPROVED"), 200)
    return ctx


def test_correction_apply_supersedes_entry_and_regenerates_notification(api):
    """PRD section 3.5: "An approved case moves `FILED` → `APPLIED`, stamps
    `decided_at`, and rewrites the row. The old entry moves `ACCEPTED` →
    `SUPERSEDED`, and a replacement `ACCEPTED` entry is created on the same
    file carrying the corrected fields — or the cleared withdrawal date —
    with `row_index` set to the file's current `row_count`; the file's
    `row_count` and `accepted_rows` then each increment by one, and the
    replacement's `source_case_id` points back to the case that created it."
    PRD section 3.5: "When the replacement's `deferment_status` differs from
    the old entry's and a `servicer_ref` is present, a new `QUEUED`
    ServicerNotification is generated for the replacement while the old
    entry's `QUEUED` and `SENT` notifications move to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/correction_apply_cascades_to_servicer_feed_and_standing
    """
    ctx = _applied_withdrawal_scene(api)
    entries = list_file_entries(ctx["file_id"])
    assert entries[0]["entry_status"] == "SUPERSEDED", "hop 1: old entry"
    replacement = entries[1]
    assert replacement["status_code"] == "WITHDRAWN", (
        "decision date 2026-11-16 is on or after withdrawal 2026-10-15"
    )
    assert replacement["census_status_code"] == "FULL_TIME", (
        "census 2026-09-15 predates the withdrawal, so the band is kept"
    )
    assert replacement["deferment_status"] == "WITHDRAWN_GRACE"
    assert replacement["source_case_id"] == ctx["case_id"]

    notifications = list_student_notifications(ctx["student_id"])
    assert notifications[0]["status"] == "ACKNOWLEDGED", (
        "hop 2: the old entry's notification was acknowledged before the "
        "correction; per PRD 3.4 only QUEUED and SENT notifications move to "
        "SUPERSEDED — 'acknowledged ones are historical and remain'"
    )
    assert notifications[1]["notification_type"] == "WITHDRAWN_GRACE"
    assert notifications[1]["grace_end_date"] == "2027-04-13T00:00:00Z"
    assert notifications[1]["status"] == "QUEUED", (
        "generated at the decision; dispatched only on the next advance"
    )

    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "CERTIFIED"
    assert file["row_count"] == 2
    assert file["accepted_rows"] == 2


def test_acknowledged_new_notification_rewrites_student_standing(api):
    """PRD section 3.4: "A `Servicer` acknowledges a `SENT` notification —
    the caller's `X-User-ID` must equal the notification's `servicer_ref`,
    otherwise `ERR_UNAUTHORIZED` — moving it `SENT` → `ACKNOWLEDGED` and
    writing the notification's `notification_type` onto the student's
    `deferment_standing`."
    PRD section 3.4: "A student's `deferment_standing` therefore always
    reflects the most recently acknowledged notification for that student,
    latest by `created_at`."

    Design: Difficulty/transitive_cascade/correction_apply_cascades_to_servicer_feed_and_standing
    """
    ctx = _applied_withdrawal_scene(api)
    notifications = list_student_notifications(ctx["student_id"])
    n2 = notifications[1]
    advance_clock("2026-11-17T00:00:00Z")
    validate_success(
        api_client.acknowledge_servicer_notification(
            n2["id"], make_servicer_headers("SVC-100"),
        ),
        200,
    )
    student = validate_success(api_client.get_student(ctx["student_id"], OPS), 200)
    assert student["deferment_standing"] == "WITHDRAWN_GRACE", (
        "hop 3: acknowledging the replacement notification rewrites the "
        "student's standing"
    )


def test_correction_conserves_student_coverage(api):
    """PRD section 3.5: "a replacement `ACCEPTED` entry is created on the
    same file carrying the corrected fields — or the cleared withdrawal date
    — with `row_index` set to the file's current `row_count`".

    Design: Difficulty/compensating_invariant/correction_conserves_period_student_coverage
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="S1", full_name="Student One",
                       date_of_birth="2004-01-01"),
        enrollment_row(student_ref="S2", full_name="Student Two",
                       date_of_birth="2004-01-02"),
        enrollment_row(student_ref="S3", full_name="Student Three",
                       date_of_birth="2004-01-03"),
    ])
    entry_id = ctx["entries"][0]["id"]
    student_id = ctx["entries"][0]["student_id"]
    case = validate_success(_file_case(
        ctx, entry_id, corrected_credit_hours=3.0,
    ), 201)
    validate_success(_decide(ctx, case["id"], "APPROVED"), 200)

    accepted, meta = validate_paginated(
        api_client.list_enrollment_entries(
            OPS, params={"institution_id": ctx["inst_id"],
                         "entry_status": "ACCEPTED"},
        ),
    )
    assert meta["total_count"] == 3, (
        "coverage is conserved: exactly the three students remain covered "
        "by ACCEPTED entries"
    )
    entries = list_file_entries(ctx["file_id"])
    replacement = entries[3]
    assert replacement["student_id"] == student_id, (
        "the replacement covers the same student"
    )
    assert replacement["credit_hours"] == 3.0
    assert replacement["status_code"] == "LESS_THAN_HALF_TIME"


def test_correction_conserves_row_partition(api):
    """PRD section 3.5: "The old entry moves `ACCEPTED` → `SUPERSEDED`, and
    a replacement `ACCEPTED` entry is created on the same file carrying the
    corrected fields — or the cleared withdrawal date — with `row_index`
    set to the file's current `row_count`; the file's `row_count` and
    `accepted_rows` then each increment by one, and the replacement's
    `source_case_id` points back to the case that created it."
    PRD section 3.3: "The file records `row_count` (every row ever attached,
    including correction-created entries later), `accepted_rows`, and
    `rejected_rows`".

    Design: Difficulty/compensating_invariant/correction_conserves_period_student_coverage
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="S1", full_name="Student One",
                       date_of_birth="2004-01-01"),
        enrollment_row(student_ref="S2", full_name="Student Two",
                       date_of_birth="2004-01-02"),
        enrollment_row(student_ref="S3", full_name="Student Three",
                       date_of_birth="2004-01-03"),
    ])
    entry_id = ctx["entries"][0]["id"]
    case = validate_success(_file_case(
        ctx, entry_id, corrected_credit_hours=3.0,
    ), 201)
    validate_success(_decide(ctx, case["id"], "APPROVED"), 200)

    entries = list_file_entries(ctx["file_id"])
    assert entries[0]["entry_status"] == "SUPERSEDED"
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["row_count"] == 4
    assert file["accepted_rows"] == 4
    assert file["rejected_rows"] == 0, "the partition 4 == 4 + 0 is conserved"


def test_correction_denied_restores_certified_without_replacement(api):
    """PRD section 3.5: "A denied case moves `FILED` → `DENIED` with
    `decided_at` stamped; the entry stands unchanged, and only the file's
    `open_correction_count` decrements — again returning an
    `AMENDMENT_PENDING` file to `CERTIFIED` once the count reaches zero."

    Design: Corner/state_machines/correction_denied_restores_certified_without_replacement
    """
    ctx = _filed_case_scene(api)
    case = validate_success(_decide(ctx, ctx["case_id"], "DENIED"), 200)
    assert case["status"] == "DENIED"
    assert case["decided_at"] == "2026-11-15T00:00:00Z"
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "CERTIFIED"
    assert file["open_correction_count"] == 0
    assert file["row_count"] == 1, "a denial creates no replacement entry"
    entries = list_file_entries(ctx["file_id"])
    assert entries[0]["entry_status"] == "ACCEPTED"


def test_decision_on_decided_case_rejected(api):
    """PRD section 3.5: "the case must exist (`ERR_CASE_NOT_FOUND`) and
    still be `FILED` (`ERR_INVALID_STATE`)".
    PRD section 2.9: "terminal states accept no further transitions".

    Design: Corner/state_machines/decision_on_decided_case_rejected
    """
    ctx = _filed_case_scene(api)
    validate_success(_decide(ctx, ctx["case_id"], "APPROVED"), 200)
    resp = _decide(ctx, ctx["case_id"], "DENIED")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    case = validate_success(
        api_client.get_correction_case(ctx["case_id"], OPS), 200,
    )
    assert case["status"] == "APPLIED"


def test_err_open_correction_exists(api):
    """PRD section 3.5: "an entry that already has a `FILED` case open
    against it rejects the new filing with `ERR_OPEN_CORRECTION_EXISTS`
    (HTTP 409)".

    Design: Corner/errors/err_open_correction_exists
    """
    ctx = _filed_case_scene(api)
    resp = _file_case(
        ctx, ctx["entry_id"],
        headers=make_certifier_headers(ctx["cert_uid"]),
        corrected_credit_hours=9.0, reason_code="STATUS_MISSTATEMENT",
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_CORRECTION_EXISTS)


def test_err_entry_superseded_correction(api):
    """PRD section 3.5: "filing against a `SUPERSEDED` entry is rejected
    distinctly with `ERR_ENTRY_SUPERSEDED` (HTTP 409)".

    Design: Corner/errors/err_entry_superseded_correction
    """
    ctx = _filed_case_scene(api)
    validate_success(_decide(ctx, ctx["case_id"], "APPROVED"), 200)
    resp = _file_case(ctx, ctx["entry_id"], corrected_credit_hours=9.0)
    validate_error(resp, ApiErrorId.ERR_ENTRY_SUPERSEDED)


def test_err_segregation_of_duties_on_own_decision(api):
    """PRD section 3.5: "the deciding user, recorded as
    `decided_by_user_id`, must differ from `filed_by_user_id`: a same-user
    decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/errors/err_segregation_of_duties_on_own_decision
    """
    ctx = setup_certified_file()
    entry_id = ctx["entries"][0]["id"]
    case = validate_success(_file_case(
        ctx, entry_id,
        headers=make_certifier_headers(ctx["cert_uid"]),
        corrected_credit_hours=15.0,
    ), 201)
    resp = _decide(ctx, case["id"], "APPROVED")
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    case = validate_success(api_client.get_correction_case(case["id"], OPS), 200)
    assert case["status"] == "FILED"


def test_correction_clear_and_set_withdrawal_conflict(api):
    """PRD section 3.5: "`clear_withdrawal_date` and
    `corrected_withdrawal_date` are mutually exclusive; supplying both is
    rejected with `ERR_VALIDATION`."

    Design: Corner/validations/correction_clear_and_set_withdrawal_conflict
    """
    ctx = setup_certified_file()
    entry_id = ctx["entries"][0]["id"]
    resp = _file_case(
        ctx, entry_id,
        corrected_withdrawal_date="2026-10-15", clear_withdrawal_date=True,
        reason_code="STATUS_MISSTATEMENT",
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_rbac_submitter_cannot_decide_case(api):
    """PRD section 3.5: "Decision belongs to a certifier of the same
    institution — and never to the filer."
    PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_submitter_cannot_decide_case
    """
    ctx = _filed_case_scene(api)
    resp = api_client.decide_correction_case(
        ctx["case_id"], {"outcome": "APPROVED"},
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    case = validate_success(
        api_client.get_correction_case(ctx["case_id"], OPS), 200,
    )
    assert case["status"] == "FILED"


def test_err_entry_not_found(api):
    """PRD section 3.5: "the entry must exist (`ERR_ENTRY_NOT_FOUND`)".

    Design: Corner/errors/err_entry_not_found
    """
    ctx = create_institution_with_registrars()
    resp = api_client.create_correction_case(
        create_correction_payload(NON_EXISTENT_UUID,
                                  corrected_credit_hours=9.0),
        make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_FOUND)


def test_err_case_not_found(api):
    """PRD section 3.5: "the case must exist (`ERR_CASE_NOT_FOUND`)".

    Design: Corner/errors/err_case_not_found
    """
    ctx = create_institution_with_registrars()
    resp = api_client.decide_correction_case(
        NON_EXISTENT_UUID, {"outcome": "APPROVED"},
        make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)
