"""Certification, enrollment status determination, and the servicer feed."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    advance_clock, get_period_version, upload_file, certify_file,
    setup_period_scenario, setup_uploaded_file, setup_certified_file,
    list_file_entries, list_entry_notifications, enrollment_row,
    make_submitter_headers, make_certifier_headers,
)

OPS = TEST_USERS["ops_headers"]


def _census_scene(api):
    """Certified file (2026-11-15) with one UNDERGRAD 12.0 row withdrawn
    2026-10-15 — after the census date 2026-09-15."""
    return setup_certified_file(rows=[enrollment_row(
        withdrawal_date="2026-10-15", servicer_ref="SVC-100",
    )])


def test_mid_census_withdrawal_census_keeps_credit_band(api):
    """PRD section 3.4: "For the as-of-census variant, withdrawal counts only
    when the `withdrawal_date` falls on or before the census date; a student
    who withdrew after census keeps the credit-based band."
    PRD section 3.4: "the entry is `WITHDRAWN` when a `withdrawal_date` is
    present and falls on or before D; otherwise the credit band applies."

    Design: Difficulty/dual_variant_calc/enrollment_status_census_vs_report_date
    """
    ctx = _census_scene(api)
    entry = ctx["entries"][0]
    assert entry["census_status_code"] == "FULL_TIME", (
        "withdrawal 2026-10-15 is after census 2026-09-15, so the census "
        "variant keeps the 12.0-credit band"
    )
    assert entry["status_code"] == "WITHDRAWN", (
        "the report variant as-of certification 2026-11-15 sees the "
        "withdrawal"
    )


def test_mid_census_withdrawal_grace_notification(api):
    """PRD section 3.4: "A `WITHDRAWN` student is measured against a grace
    end computed as the `withdrawal_date` plus 180 days: strictly before
    that grace end the entry is `WITHDRAWN_GRACE`".
    PRD section 3.4: "setting `notification_type` to the entry's
    `deferment_status` at generation, and setting `grace_end_date` to the
    withdrawal date plus 180 days only when the type is `WITHDRAWN_GRACE` —
    otherwise null."

    Design: Difficulty/dual_variant_calc/enrollment_status_census_vs_report_date
    """
    ctx = _census_scene(api)
    entry = ctx["entries"][0]
    assert entry["deferment_status"] == "WITHDRAWN_GRACE", (
        "2026-11-15 is strictly before the grace end"
    )
    notifications = list_entry_notifications(entry["id"])
    assert notifications[0]["notification_type"] == "WITHDRAWN_GRACE"
    assert notifications[0]["grace_end_date"] == "2027-04-13T00:00:00Z", (
        "withdrawal 2026-10-15 plus 180 days"
    )


def test_graduate_9_credits_is_full_time(api):
    """PRD section 3.4: "a `GRADUATE` is `FULL_TIME` at 9.0 credits or more,
    `HALF_TIME` at 4.5 or more, and `LESS_THAN_HALF_TIME` below that."

    Design: Difficulty/combinatorial_formula/enrollment_status_grad_vs_undergrad_branch
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="G1", full_name="Grad One",
                       date_of_birth="2000-03-01", career_level="GRADUATE",
                       credit_hours=9.0),
        enrollment_row(student_ref="U1", full_name="Undergrad One",
                       date_of_birth="2004-03-01", career_level="UNDERGRAD",
                       credit_hours=9.0),
    ])
    assert ctx["entries"][0]["status_code"] == "FULL_TIME"


def test_undergrad_9_credits_is_half_time(api):
    """PRD section 3.4: "an `UNDERGRAD` is `FULL_TIME` at 12.0 credits or
    more, `HALF_TIME` at 6.0 or more, and `LESS_THAN_HALF_TIME` below that".

    Design: Difficulty/combinatorial_formula/enrollment_status_grad_vs_undergrad_branch
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="G1", full_name="Grad One",
                       date_of_birth="2000-03-01", career_level="GRADUATE",
                       credit_hours=9.0),
        enrollment_row(student_ref="U1", full_name="Undergrad One",
                       date_of_birth="2004-03-01", career_level="UNDERGRAD",
                       credit_hours=9.0),
    ])
    assert ctx["entries"][1]["status_code"] == "HALF_TIME", (
        "the same 9.0 credits fall in the UNDERGRAD band [6.0, 12.0)"
    )


def test_11_99_credits_is_half_time(api):
    """PRD section 3.4: "an `UNDERGRAD` is `FULL_TIME` at 12.0 credits or
    more, `HALF_TIME` at 6.0 or more".

    Design: Difficulty/boundary_precision_check/full_time_threshold_boundary_12_credits
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="S1", full_name="Boundary Below",
                       date_of_birth="2004-02-01", credit_hours=11.99),
        enrollment_row(student_ref="S2", full_name="Boundary Exact",
                       date_of_birth="2004-02-02", credit_hours=12.0),
    ])
    assert ctx["entries"][0]["status_code"] == "HALF_TIME", "11.99 < 12.0"
    assert ctx["entries"][0]["deferment_status"] == "DEFERMENT_ELIGIBLE"


def test_12_0_credits_is_full_time(api):
    """PRD section 3.4: "an `UNDERGRAD` is `FULL_TIME` at 12.0 credits or
    more".
    PRD section 3.4: "A `FULL_TIME` or `HALF_TIME` student is
    `DEFERMENT_ELIGIBLE`".

    Design: Difficulty/boundary_precision_check/full_time_threshold_boundary_12_credits
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="S1", full_name="Boundary Below",
                       date_of_birth="2004-02-01", credit_hours=11.99),
        enrollment_row(student_ref="S2", full_name="Boundary Exact",
                       date_of_birth="2004-02-02", credit_hours=12.0),
    ])
    assert ctx["entries"][1]["status_code"] == "FULL_TIME", (
        "12.0 >= 12.0 — the boundary is inclusive"
    )
    assert ctx["entries"][1]["deferment_status"] == "DEFERMENT_ELIGIBLE"


def test_immediate_read_after_write_consistency(api):
    """PRD section 3.4: "Certification stamps `certified_at` with the current
    logical time and derives `late_submission`: true exactly when
    `certified_at` falls strictly after the period's `submission_due_at`, so
    certification on the due date itself is on time."
    PRD section 3.4: "When the period's `outcome` is still `NONE`, it becomes
    `ON_TIME` or `LATE` according to `late_submission`".

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = setup_uploaded_file()
    file = certify_file(ctx, ctx["file_id"])
    assert file["status"] == "CERTIFIED"
    assert file["certified_at"] == "2026-11-15T00:00:00Z"
    assert file["late_submission"] is False
    got = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert got["status"] == "CERTIFIED"
    assert got["certified_at"] == "2026-11-15T00:00:00Z"
    assert got["late_submission"] is False
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["outcome"] == "ON_TIME", (
        "the certification's calendar side effect is visible immediately"
    )


def test_certify_is_not_idempotent_on_certified_file(api):
    """PRD section 2.9: "an action fired against a resource in the wrong
    state — including re-firing an action whose effect has already been
    applied, or acting on a resource in a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD section 3.4: "a `RegistrarCertifier` certifies a file still in
    `UPLOADED` status, moving it `UPLOADED` → `CERTIFIED`."

    Design: Corner/state_machines/certify_is_not_idempotent_on_certified_file
    """
    ctx = setup_certified_file()
    resp = api_client.certify_enrollment_file(
        ctx["file_id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "CERTIFIED"


def test_err_unresolved_rows_blocks_certify(api):
    """PRD section 3.4: "the file must be clean: a `rejected_rows` count
    above zero blocks certification with `ERR_UNRESOLVED_ROWS` (HTTP 409)."

    Design: Corner/errors/err_unresolved_rows_blocks_certify
    """
    ctx = setup_uploaded_file(rows=[
        enrollment_row(student_ref="S1", full_name="Good One",
                       date_of_birth="2004-01-01"),
        enrollment_row(student_ref="S2", full_name="Bad Credits",
                       date_of_birth="2004-01-02", credit_hours=31.0),
    ])
    assert ctx["file"]["rejected_rows"] == 1
    resp = api_client.certify_enrollment_file(
        ctx["file_id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ROWS)
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "UPLOADED"


def test_rbac_submitter_cannot_certify(api):
    """PRD section 3.4: "Certification is the certifier's act, never the
    submitter's".
    PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_submitter_cannot_certify
    """
    ctx = setup_uploaded_file()
    resp = api_client.certify_enrollment_file(
        ctx["file_id"], make_submitter_headers(ctx["sub_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    file = validate_success(api_client.get_enrollment_file(ctx["file_id"], OPS), 200)
    assert file["status"] == "UPLOADED"


def test_certify_exactly_on_due_date_counts_on_time(api):
    """PRD section 3.4: "Certification stamps `certified_at` with the current
    logical time and derives `late_submission`: true exactly when
    `certified_at` falls strictly after the period's `submission_due_at`, so
    certification on the due date itself is on time."
    PRD section 3.2: "At close, the period's `outcome` becomes `ON_TIME` when
    a `CERTIFIED` file exists whose `certified_at` is on or before
    `submission_due_at`".

    Design: Corner/calculations/certify_exactly_on_due_date_counts_on_time
    """
    ctx = setup_uploaded_file()
    advance_clock("2026-12-20T00:00:00Z")
    file = certify_file(ctx, ctx["file_id"])
    assert file["certified_at"] == "2026-12-20T00:00:00Z"
    assert file["late_submission"] is False
    advance_clock("2027-01-04T00:00:00Z")
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["status"] == "CLOSED"
    assert data[0]["outcome"] == "ON_TIME"


def test_delinquent_period_remediated_to_late_flips_standing(api):
    """PRD section 3.2: "uploading into a `CLOSED` period is the sanctioned
    remedy path (§3.3), and when a file for a `DELINQUENT` period is
    certified late, the period's outcome flips from `DELINQUENT` to `LATE`
    (§3.4)."
    PRD section 3.2: "If any of those periods is `DELINQUENT`, the
    institution becomes `NON_COMPLIANT`; otherwise, if any is `LATE`, it
    moves to `WATCH`".

    Design: Corner/calculations/delinquent_period_remediated_to_late_flips_standing
    """
    ctx = setup_period_scenario(advance_to=None)
    advance_clock("2027-01-04T00:00:00Z")
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["outcome"] == "DELINQUENT"
    mid = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert mid["compliance_standing"] == "NON_COMPLIANT"

    file = upload_file(ctx, [enrollment_row()])
    file = certify_file(ctx, file["id"])
    assert file["late_submission"] is True, (
        "certified 2027-01-04, strictly after due 2026-12-20"
    )
    data, _m = validate_paginated(
        api_client.list_reporting_periods(ctx["inst_id"], OPS),
    )
    assert data[0]["outcome"] == "LATE"
    end = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert end["compliance_standing"] == "WATCH"


def test_certified_file_supersession_cascades_notifications(api):
    """PRD section 3.4: "If another file for the same reporting period was
    already `CERTIFIED`, certification supersedes it: that file moves to
    `SUPERSEDED`, its `ACCEPTED` entries move to `SUPERSEDED`, and its
    still-undelivered notifications — `QUEUED` or `SENT` — move to
    `SUPERSEDED`, while `ACKNOWLEDGED` notifications remain as history."

    Design: Corner/state_machines/certified_file_supersession_cascades_notifications
    """
    ctx = setup_certified_file(rows=[enrollment_row(servicer_ref="SVC-100")])
    f1_id = ctx["file_id"]
    f2 = upload_file(ctx, [enrollment_row(
        student_ref="S2", full_name="Second Student",
        date_of_birth="2004-06-01", credit_hours=9.0, servicer_ref="SVC-100",
    )])
    certify_file(ctx, f2["id"])

    f1 = validate_success(api_client.get_enrollment_file(f1_id, OPS), 200)
    assert f1["status"] == "SUPERSEDED"
    data, _m = validate_paginated(api_client.list_servicer_notifications(OPS))
    assert data[0]["status"] == "SUPERSEDED", "the old file's QUEUED notice"
    assert data[1]["status"] == "QUEUED", "the new file's generated notice"


def test_file_list_filters_and_status_partition(api):
    """PRD section 3.3: "Upload supersedes the period's prior uncertified
    file".
    PRD section 3.3: "Enrollment files are listed in `created_at` ascending
    order, filtered by `institution_id`, `reporting_period_id`,
    `submitted_by_user_id`, or `status`".

    Design: Corner/endpoints/file_list_filters_and_status_partition
    """
    ctx = setup_certified_file()
    f1_id = ctx["file_id"]
    f2 = upload_file(ctx, [enrollment_row(
        student_ref="S2", full_name="Second Student",
        date_of_birth="2004-06-01", credit_hours=9.0,
    )])
    certified, meta_c = validate_paginated(
        api_client.list_enrollment_files(
            OPS, params={"institution_id": ctx["inst_id"], "status": "CERTIFIED"},
        ),
    )
    assert meta_c["total_count"] == 1
    assert certified[0]["id"] == f1_id, (
        "the certified file survives a later upload"
    )
    uploaded, meta_u = validate_paginated(
        api_client.list_enrollment_files(
            OPS, params={"institution_id": ctx["inst_id"], "status": "UPLOADED"},
        ),
    )
    assert meta_u["total_count"] == 1
    assert uploaded[0]["id"] == f2["id"]
    all_files, meta_all = validate_paginated(
        api_client.list_enrollment_files(
            OPS, params={"institution_id": ctx["inst_id"]},
        ),
    )
    assert meta_all["total_count"] == 2
    assert all_files[0]["id"] == f1_id, "created_at ascending"


def test_deferment_ineligible_for_less_than_half_time(api):
    """PRD section 3.4: "a `LESS_THAN_HALF_TIME` student is
    `DEFERMENT_INELIGIBLE`."
    PRD section 3.4: "setting `grace_end_date` to the withdrawal date plus
    180 days only when the type is `WITHDRAWN_GRACE` — otherwise null."

    Design: Corner/calculations/deferment_ineligible_for_less_than_half_time
    """
    ctx = setup_certified_file(rows=[enrollment_row(
        full_name="Part Timer", credit_hours=3.0, servicer_ref="SVC-100",
    )])
    entry = ctx["entries"][0]
    assert entry["status_code"] == "LESS_THAN_HALF_TIME", "3.0 < 6.0"
    assert entry["deferment_status"] == "DEFERMENT_INELIGIBLE"
    notifications = list_entry_notifications(entry["id"])
    assert notifications[0]["notification_type"] == "DEFERMENT_INELIGIBLE"
    assert notifications[0]["grace_end_date"] is None


def test_deferment_repayment_due_at_grace_end_boundary(api):
    """PRD section 3.4: "A `WITHDRAWN` student is measured against a grace
    end computed as the `withdrawal_date` plus 180 days: strictly before
    that grace end the entry is `WITHDRAWN_GRACE`; on or after it, the entry
    is `REPAYMENT_DUE`."

    Design: Corner/calculations/deferment_repayment_due_at_grace_end_boundary
    """
    ctx = setup_uploaded_file(rows=[enrollment_row(
        full_name="Withdrawn Early", withdrawal_date="2026-09-10",
        servicer_ref="SVC-100",
    )])
    advance_clock("2027-03-09T00:00:00Z")
    file = certify_file(ctx, ctx["file_id"])
    assert file["late_submission"] is True
    entry = list_file_entries(ctx["file_id"])[0]
    assert entry["status_code"] == "WITHDRAWN", (
        "withdrawal 2026-09-10 is on or before the as-of date 2027-03-09"
    )
    assert entry["deferment_status"] == "REPAYMENT_DUE", (
        "the as-of date equals the grace end 2027-03-09; the comparison is "
        "strictly-before"
    )
    notifications = list_entry_notifications(entry["id"])
    assert notifications[0]["notification_type"] == "REPAYMENT_DUE"
    assert notifications[0]["grace_end_date"] is None
