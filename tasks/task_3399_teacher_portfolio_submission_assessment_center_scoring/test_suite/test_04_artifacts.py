"""Evidence artifact technical limits and the portfolio composition gates at
submit time."""
from test_helpers import (
    ApiErrorId,
    SubmissionStatus,
    assert_artifact,
    create_eligible_candidate,
    create_open_cycle,
    create_submission,
    document_artifact_payload,
    make_candidate_headers,
    release_form_artifact_payload,
    upload_artifact,
    upload_minimal_portfolio_artifacts,
    validate_created,
    validate_error,
    validate_success,
    video_artifact_payload,
)


def test_artifact_immutable_record_has_no_version_or_update(api):
    """PRD §2.5: "One resource breaks this pattern deliberately: the evidence
    **artifact** record is immutable once uploaded, has no update endpoint, and
    carries only `id` and `created_at`. Both `updated_at` and `version` are absent
    from artifacts — clients must not expect them."

    Design: Corner/entities/artifact_immutable_record_has_no_version_or_update
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")

    artifact = validate_created(
        api.upload_artifact(
            submission["id"],
            document_artifact_payload("WRITTEN_COMMENTARY"),
            make_candidate_headers(candidate["id"]),
        )
    )

    assert_artifact(artifact)  # pins: id + created_at present; no version/updated_at


def test_artifact_video_wrong_format_rejected(api):
    """PRD §3.3: "Videos accept only the mp4 or mov containers and at most 500 MB;
    the three document types (`STUDENT_WORK`, `WRITTEN_COMMENTARY`, `RELEASE_FORM`)
    accept only pdf or docx and at most 50 MB. A container outside the allowed set
    for its type is `ERR_ARTIFACT_FORMAT_INVALID` (HTTP 422); a file over its type's
    size limit is `ERR_ARTIFACT_SIZE_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/artifact_video_wrong_format_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")

    response = api.upload_artifact(
        submission["id"],
        video_artifact_payload(file_format="avi"),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ARTIFACT_FORMAT_INVALID)


def test_artifact_video_duration_over_15_minutes_rejected(api):
    """PRD §3.3: "`duration_minutes` is required if and only if the artifact is a
    `VIDEO` — omitting it for a video, or supplying it for a non-video, is
    `ERR_INVALID_REQUEST` (HTTP 400) — and a video longer than 15 minutes is
    rejected with `ERR_VIDEO_DURATION_EXCEEDED` (HTTP 422)."

    Boundary: exactly 15 minutes passes; 16 minutes fails.

    Design: Corner/validations/artifact_video_duration_over_15_minutes_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    headers = make_candidate_headers(candidate["id"])

    ok = validate_created(
        api.upload_artifact(
            submission["id"], video_artifact_payload(duration_minutes=15), headers
        )
    )
    assert_artifact(ok)

    response = api.upload_artifact(
        submission["id"], video_artifact_payload(duration_minutes=16), headers
    )
    validate_error(response, ApiErrorId.ERR_VIDEO_DURATION_EXCEEDED)


def test_artifact_document_size_over_limit_rejected(api):
    """PRD §3.3: "Videos accept only the mp4 or mov containers and at most 500 MB;
    the three document types (`STUDENT_WORK`, `WRITTEN_COMMENTARY`, `RELEASE_FORM`)
    accept only pdf or docx and at most 50 MB. A container outside the allowed set
    for its type is `ERR_ARTIFACT_FORMAT_INVALID` (HTTP 422); a file over its type's
    size limit is `ERR_ARTIFACT_SIZE_EXCEEDED` (HTTP 422)."

    Boundary for the document types: exactly 50 MB passes; 51 MB fails.

    Design: Corner/validations/artifact_document_size_over_limit_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    headers = make_candidate_headers(candidate["id"])

    ok = validate_created(
        api.upload_artifact(
            submission["id"],
            document_artifact_payload("WRITTEN_COMMENTARY", file_size_mb=50),
            headers,
        )
    )
    assert_artifact(ok)

    response = api.upload_artifact(
        submission["id"],
        document_artifact_payload("WRITTEN_COMMENTARY", file_size_mb=51),
        headers,
    )
    validate_error(response, ApiErrorId.ERR_ARTIFACT_SIZE_EXCEEDED)


def test_artifact_video_missing_required_duration_returns_invalid_request(api):
    """PRD §3.3: "`duration_minutes` is required if and only if the artifact is a
    `VIDEO` — omitting it for a video, or supplying it for a non-video, is
    `ERR_INVALID_REQUEST` (HTTP 400) — and a video longer than 15 minutes is
    rejected with `ERR_VIDEO_DURATION_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/artifact_video_missing_required_duration_returns_invalid_request
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    payload = video_artifact_payload()
    payload.pop("duration_minutes")

    response = api.upload_artifact(
        submission["id"], payload, make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_portfolio_submit_composition_error_precedes_release_error(api):
    """PRD §2.8: "A submission-submit request checks the state gate
    (`ERR_SUBMISSION_NOT_SUBMITTABLE`) **before** any temporal rule, and among the
    composition gates the required-artifact check (`ERR_REQUIRED_ARTIFACT_MISSING`)
    fires **before** the release-form check (`ERR_RELEASE_FORM_MISSING`)."
    PRD §3.3: "Portfolio composition follows for `PORTFOLIO` attempts: the
    submission must carry at least one `WRITTEN_COMMENTARY` artifact and at least
    one of `VIDEO` or `STUDENT_WORK`, else `ERR_REQUIRED_ARTIFACT_MISSING`
    (HTTP 422); and when any `VIDEO` or `STUDENT_WORK` artifact on the submission
    reports a `subject_student_count` of 1 or more, at least one `RELEASE_FORM`
    artifact must ride on the same submission, else `ERR_RELEASE_FORM_MISSING`
    (HTTP 422)."

    A lone VIDEO showing students violates both gates; the composition error
    answers first.

    Design: Corner/validations/portfolio_submit_composition_error_precedes_release_error
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    upload_artifact(
        submission["id"],
        candidate,
        video_artifact_payload(subject_student_count=2),
    )

    response = api.submit_submission(
        submission["id"], make_candidate_headers(candidate["id"])
    )

    validate_error(response, ApiErrorId.ERR_REQUIRED_ARTIFACT_MISSING)


def test_portfolio_submit_missing_release_form_rejected(api):
    """PRD §3.3: "Portfolio composition follows for `PORTFOLIO` attempts: the
    submission must carry at least one `WRITTEN_COMMENTARY` artifact and at least
    one of `VIDEO` or `STUDENT_WORK`, else `ERR_REQUIRED_ARTIFACT_MISSING`
    (HTTP 422); and when any `VIDEO` or `STUDENT_WORK` artifact on the submission
    reports a `subject_student_count` of 1 or more, at least one `RELEASE_FORM`
    artifact must ride on the same submission, else `ERR_RELEASE_FORM_MISSING`
    (HTTP 422)."

    Composition is satisfied here; only the release-documentation gate can fire,
    and it clears once a RELEASE_FORM rides on the submission.

    Design: Corner/validations/portfolio_submit_missing_release_form_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    submission = create_submission(cycle["id"], candidate, "P1")
    headers = make_candidate_headers(candidate["id"])
    upload_minimal_portfolio_artifacts(submission["id"], candidate, student_count=2)

    response = api.submit_submission(submission["id"], headers)
    validate_error(response, ApiErrorId.ERR_RELEASE_FORM_MISSING)

    upload_artifact(submission["id"], candidate, release_form_artifact_payload())
    submitted = validate_success(api.submit_submission(submission["id"], headers))
    assert submitted["status"] == SubmissionStatus.SUBMITTED.value
