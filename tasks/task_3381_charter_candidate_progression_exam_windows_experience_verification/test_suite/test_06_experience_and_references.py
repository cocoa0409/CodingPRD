"""Work-experience submissions and reference verification: the months
calculation conventions, reference-count gates, the revision cycle, lazy
reference expiry, reference identity rules, and OCC on amend."""
from test_helpers import (
    ApiErrorId,
    add_reference,
    amend_submission_payload,
    compute_provisional_months,
    create_candidate,
    create_experience_submission,
    create_submission_with_references,
    decline_reference,
    experience_segment,
    get_experience_submission,
    list_references,
    make_candidate_headers,
    make_reference_provider_headers,
    months_between,
    respond_reference_payload,
    review_submission,
    review_submission_payload,
    set_logical_clock,
    submit_submission,
    validate_error,
    validate_success,
    verify_reference,
)

CLOCK = "2027-01-05T00:00:00Z"


class TestExperienceMonths:
    def test_months_between_partial_month_precision(self, api):
        """PRD §2.9: "take the difference in calendar years multiplied by
        twelve, add the difference in month numbers, and subtract one if the end
        date's day-of-month is earlier than the start date's day-of-month."
        PRD §3.6: "among the qualifying segments — those whose
        `qualifying_activity_pct` is at least 50 — the whole-calendar-month
        length of each segment (per the convention of §2.9) is summed, and
        overlapping periods are deliberately counted twice."

        Design: Corner/calculations/c_months_between_partial_month_precision
        """
        assert months_between("2024-01-15", "2025-01-14") == 11
        assert months_between("2025-03-15", "2026-03-15") == 12
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        segments = [
            experience_segment(
                employer_name="Gamma Partners",
                role_title="Associate",
                start_date="2024-01-15",
                end_date="2025-01-14",
                qualifying_activity_pct=80,
                hours=1900,
            ),
            experience_segment(
                employer_name="Delta Investors",
                role_title="Associate",
                start_date="2025-03-15",
                end_date="2026-03-15",
                qualifying_activity_pct=80,
                hours=2000,
            ),
        ]
        assert compute_provisional_months(segments) == 23
        bundle = create_submission_with_references(candidate, segments=segments)
        submitted = submit_submission(bundle["submission"], candidate)
        assert submitted["provisional_months"] == 23

    def test_provisional_excludes_sub_threshold_segments(self, api):
        """PRD §3.6: "At submission time the system computes
        `provisional_months`, the **cumulative** variant of the experience
        figure: among the qualifying segments — those whose
        `qualifying_activity_pct` is at least 50 — the whole-calendar-month
        length of each segment (per the convention of §2.9) is summed, and
        overlapping periods are deliberately counted twice. Segments below the
        50-percent qualifying bar feed neither variant."

        Design: Corner/calculations/c_provisional_excludes_sub_threshold_segments
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        segments = [
            experience_segment(
                employer_name="Epsilon Advisors",
                role_title="Analyst",
                start_date="2022-01-10",
                end_date="2023-01-10",
                qualifying_activity_pct=50,
                hours=1800,
            ),
            experience_segment(
                employer_name="Zeta Funds",
                role_title="Operations",
                start_date="2023-02-10",
                end_date="2024-02-10",
                qualifying_activity_pct=49,
                hours=1900,
            ),
        ]
        assert compute_provisional_months(segments) == 12
        bundle = create_submission_with_references(candidate, segments=segments)
        submitted = submit_submission(bundle["submission"], candidate)
        assert submitted["provisional_months"] == 12


class TestSubmissionLifecycle:
    def test_submission_revision_cycle_returns_to_draft(self, api):
        """PRD §3.6: "A returned submission cycles back to `DRAFT` through
        amendment, a guarded write: the request carries the replacement
        `segments` and must carry `expected_submission_version` matching the
        submission's current `version`, else `ERR_STALE_VERSION` (§2.7); only a
        `RETURNED_FOR_REVISION` submission is amendable, else
        `ERR_SUBMISSION_NOT_EDITABLE`. Amending replaces the segments wholesale,
        resets both `provisional_months` and `committee_months` to `null`,
        increments the submission's `version` by one, and leaves the attached
        references in whatever status they currently hold."

        Design: Corner/state_machines/c_submission_revision_cycle_returns_to_draft
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        submitted = submit_submission(bundle["submission"], candidate)
        assert submitted["provisional_months"] == 12
        returned = review_submission(submitted, decision="RETURNED_FOR_REVISION")
        new_segments = [
            experience_segment(
                employer_name="Alpha Asset Management",
                role_title="Analyst",
                start_date="2023-01-05",
                end_date="2024-07-05",
                qualifying_activity_pct=80,
                hours=3200,
            )
        ]
        amended_resp = api.amend_experience_submission(
            submitted["id"],
            amend_submission_payload(new_segments, returned["version"]),
            make_candidate_headers(candidate["id"]),
        )
        amended = validate_success(amended_resp, 200)
        assert amended["status"] == "DRAFT"
        assert amended["version"] == returned["version"] + 1
        assert amended["provisional_months"] is None
        assert amended["committee_months"] is None
        resubmitted = submit_submission(amended, candidate)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["provisional_months"] == 18
        references = list_references(
            params={"experience_submission_id": submitted["id"]}
        )
        assert len(references) == 2
        assert all(ref["status"] == "PENDING" for ref in references)

    def test_review_on_draft_submission_rejected(self, api, experience_reviewer_headers):
        """PRD §3.6: "Review belongs to an `ExperienceReviewer`, who issues a
        `decision` of `APPROVED`, `REJECTED` or `RETURNED_FOR_REVISION` —
        optionally annotated with `reviewer_notes` — against a `SUBMITTED`
        submission (any other state fails with `ERR_INVALID_SUBMISSION_STATE`)."

        Design: Corner/errors/c_review_on_draft_submission_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        submission = create_experience_submission(candidate)
        resp = api.review_experience_submission(
            submission["id"],
            review_submission_payload("APPROVED"),
            experience_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUBMISSION_STATE)
        assert resp.status_code == 409
        assert get_experience_submission(submission["id"])["status"] == "DRAFT"

    def test_amend_non_returned_submission_rejected(self, api):
        """PRD §3.6: "only a `RETURNED_FOR_REVISION` submission is amendable,
        else `ERR_SUBMISSION_NOT_EDITABLE`"

        Design: Corner/errors/c_amend_non_returned_submission_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        submitted = submit_submission(bundle["submission"], candidate)
        resp = api.amend_experience_submission(
            submitted["id"],
            amend_submission_payload(
                [
                    experience_segment(
                        employer_name="New Employer",
                        start_date="2022-01-10",
                        end_date="2023-01-10",
                        hours=2000,
                    )
                ],
                submitted["version"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_EDITABLE)
        assert resp.status_code == 409
        assert get_experience_submission(submitted["id"])["status"] == "SUBMITTED"

    def test_occ_amend_stale_version_returns_412(self, api):
        """PRD §2.7: "Amending a returned work-experience submission requires
        `expected_submission_version`, carrying the caller's last observed
        `version` of that submission; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412), since the `RETURNED_FOR_REVISION` state
        the caller observed has been superseded by another committed write."

        Design: Corner/cross_cutting_layers/c_occ_amend_stale_version_returns_412
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        submitted = submit_submission(bundle["submission"], candidate)
        returned = review_submission(submitted, decision="RETURNED_FOR_REVISION")
        stale_version = returned["version"]
        amended_resp = api.amend_experience_submission(
            submitted["id"],
            amend_submission_payload(
                [
                    experience_segment(
                        start_date="2023-01-05", end_date="2024-07-05", hours=3200
                    )
                ],
                stale_version,
            ),
            make_candidate_headers(candidate["id"]),
        )
        amended = validate_success(amended_resp, 200)
        assert amended["version"] == stale_version + 1
        assert amended["status"] == "DRAFT"
        replay = api.amend_experience_submission(
            submitted["id"],
            amend_submission_payload(
                [experience_segment()], stale_version
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        assert replay.status_code == 412
        current = get_experience_submission(submitted["id"])
        assert current["segments"][0]["end_date"] == "2024-07-05"


class TestReferenceGates:
    def test_submit_with_insufficient_references_rejected(self, api):
        """PRD §3.6: "Submitting moves the submission from `DRAFT` to
        `SUBMITTED` (from any other state the call fails with
        `ERR_INVALID_SUBMISSION_STATE`) and requires at least two attached
        reference contacts in any non-`EXPIRED` status, else
        `ERR_INSUFFICIENT_REFERENCES`."

        Design: Corner/errors/c_submit_with_insufficient_references_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        submission = create_experience_submission(candidate)
        add_reference(submission, candidate)
        resp = api.submit_experience_submission(
            submission["id"], make_candidate_headers(candidate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REFERENCES)
        assert resp.status_code == 422
        after = get_experience_submission(submission["id"])
        assert after["status"] == "DRAFT"
        assert after["provisional_months"] is None

    def test_approve_with_unverified_references_rejected(self, api, experience_reviewer_headers):
        """PRD §3.6: "Approval carries an extra gate: at least two of the
        submission's references must stand at `VERIFIED`, else
        `ERR_INSUFFICIENT_VERIFIED_REFERENCES`."

        Design: Corner/errors/c_approve_with_unverified_references_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        submitted = submit_submission(bundle["submission"], candidate)
        resp = api.review_experience_submission(
            submitted["id"],
            review_submission_payload("APPROVED"),
            experience_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VERIFIED_REFERENCES)
        assert resp.status_code == 422
        for reference in bundle["references"]:
            verify_reference(reference)
        approved = review_submission(submitted, decision="APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["committee_months"] == 12

    def test_declined_reference_blocks_approval(self, api, experience_reviewer_headers):
        """PRD §3.6: "A `VERIFIED` decision stamps `verified_at` with the
        current clock; a `DECLINED` decision closes the reference without
        verification."
        PRD §3.6: "Approval carries an extra gate: at least two of the
        submission's references must stand at `VERIFIED`, else
        `ERR_INSUFFICIENT_VERIFIED_REFERENCES`."

        Design: Corner/errors/c_declined_reference_blocks_approval
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        verify_reference(bundle["references"][0])
        declined = decline_reference(bundle["references"][1])
        assert declined["status"] == "DECLINED"
        submitted = submit_submission(bundle["submission"], candidate)
        assert submitted["status"] == "SUBMITTED"
        resp = api.review_experience_submission(
            submitted["id"],
            review_submission_payload("APPROVED"),
            experience_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VERIFIED_REFERENCES)
        assert resp.status_code == 422

    def test_reference_respond_after_expiry(self, api):
        """PRD §3.6: "Expiry is lazy: a response arriving when the clock has
        already passed `expires_at` first transitions the reference to `EXPIRED`
        and then the call fails with `ERR_REFERENCE_NOT_PENDING`, and the same
        error greets any response to a reference no longer `PENDING`."

        Design: Corner/errors/c_reference_respond_after_expiry
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        submission = create_experience_submission(candidate)
        reference = add_reference(submission, candidate)
        set_logical_clock("2027-02-05T00:00:00Z")
        resp = api.respond_reference(
            reference["id"],
            respond_reference_payload("VERIFIED"),
            make_reference_provider_headers(reference["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_PENDING)
        assert resp.status_code == 409
        rows = list_references(params={"experience_submission_id": submission["id"]})
        assert rows[0]["status"] == "EXPIRED"

    def test_reference_respond_with_wrong_user_id(self, api):
        """PRD §2.1: "When `X-User-Role` is `ReferenceProvider`, `X-User-ID` is
        the `id` of the `ReferenceContact` record being answered; a reference
        response submitted under any other identifier fails the same ownership
        check with `ERR_OWNERSHIP_MISMATCH`."
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        Design: Corner/rbac/c_reference_respond_with_wrong_user_id
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        ref1, ref2 = bundle["references"]
        wrong_ref = api.respond_reference(
            ref1["id"],
            respond_reference_payload("VERIFIED"),
            make_reference_provider_headers(ref2["id"]),
        )
        validate_error(wrong_ref, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        assert wrong_ref.status_code == 403
        as_candidate = api.respond_reference(
            ref1["id"],
            respond_reference_payload("VERIFIED"),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(as_candidate, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert as_candidate.status_code == 403
        rows = list_references(
            params={"experience_submission_id": bundle["submission"]["id"]}
        )
        assert all(ref["status"] == "PENDING" for ref in rows)

    def test_candidate_cannot_review_submissions(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/c_candidate_cannot_review_submissions
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        bundle = create_submission_with_references(candidate)
        submitted = submit_submission(bundle["submission"], candidate)
        resp = api.review_experience_submission(
            submitted["id"],
            review_submission_payload("APPROVED"),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        assert get_experience_submission(submitted["id"])["status"] == "SUBMITTED"
