"""Research studies: computed study_status, enrollment guards, contribution dataset."""
from test_helpers import (
    ApiErrorId,
    create_member_with_term,
    create_ingest_payload,
    create_study_payload,
    get_success_data,
    make_member_headers,
    make_platform_admin_headers,
    set_clock,
    setup_member_with_active_device,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStudyStatusComputed:
    def test_study_status_computed_from_window(self, api, anonymous_headers):
        """PRD: "The study's study_status is computed, not stored as an input: it
        is RECRUITING whenever today falls inside that inclusive window and CLOSED
        otherwise, and it is recomputed as the logical clock moves."

        Design: Corner/entities/study_status_computed_from_window
        """
        admin = make_platform_admin_headers()
        study = validate_success(
            api.create_research_study(
                create_study_payload(
                    code="S1",
                    enrollment_window_start_on="2026-09-01",
                    enrollment_window_end_on="2026-09-10",
                ),
                admin,
            ),
            expected_status=201,
        )
        assert study["study_status"] == "RECRUITING"
        set_clock("2026-09-11T00:00:00Z")
        reread = validate_success(api.get_research_study(study["id"], admin))
        assert reread["study_status"] == "CLOSED"

    def test_study_status_recruiting_at_window_end_inclusive(self, api, anonymous_headers):
        """PRD: "it is RECRUITING whenever today falls inside that inclusive window
        and CLOSED otherwise".

        Design: Corner/entities/study_status_computed_from_window
        """
        admin = make_platform_admin_headers()
        study = validate_success(
            api.create_research_study(
                create_study_payload(
                    enrollment_window_start_on="2026-09-01",
                    enrollment_window_end_on="2026-09-10",
                ),
                admin,
            ),
            expected_status=201,
        )
        set_clock("2026-09-10T00:00:00Z")
        reread = validate_success(api.get_research_study(study["id"], admin))
        assert reread["study_status"] == "RECRUITING"


class TestEnrollmentGuards:
    def test_enrollment_window_closed_rejected(self, api, anonymous_headers):
        """PRD: "Enrollment requires the study to be RECRUITING today — otherwise
        ERR_ENROLLMENT_WINDOW_CLOSED".

        Design: Corner/errors/enrollment_window_and_duplicate_enrollment
        """
        admin = make_platform_admin_headers()
        member, term = create_member_with_term()
        study = validate_success(
            api.create_research_study(
                create_study_payload(
                    code="SA",
                    enrollment_window_start_on="2026-09-01",
                    enrollment_window_end_on="2026-09-02",
                ),
                admin,
            ),
            expected_status=201,
        )
        set_clock("2026-09-03T00:00:00Z")
        resp = api.enroll_in_study(
            study["id"], {"member_id": member["id"]}, make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED, expected_status=422)

    def test_duplicate_enrollment_rejected(self, api, anonymous_headers):
        """PRD: "no existing ENROLLED enrollment for the same member in the same
        study (ERR_ALREADY_ENROLLED)".

        Design: Corner/errors/enrollment_window_and_duplicate_enrollment
        """
        admin = make_platform_admin_headers()
        member, term = create_member_with_term()
        study = validate_success(
            api.create_research_study(
                create_study_payload(
                    code="SB",
                    enrollment_window_start_on="2026-09-01",
                    enrollment_window_end_on="2026-09-30",
                ),
                admin,
            ),
            expected_status=201,
        )
        headers = make_member_headers(member["id"])
        validate_success(
            api.enroll_in_study(study["id"], {"member_id": member["id"]}, headers),
            expected_status=201,
        )
        resp = api.enroll_in_study(study["id"], {"member_id": member["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_ENROLLED, expected_status=409)


class TestContributionDataset:
    def _setup_two_enrolled_members(self, api):
        admin = make_platform_admin_headers()
        study = validate_success(
            api.create_research_study(
                create_study_payload(
                    code="DS",
                    enrollment_window_start_on="2026-09-01",
                    enrollment_window_end_on="2026-09-30",
                ),
                admin,
            ),
            expected_status=201,
        )
        members = []
        enrollments = []
        for email in ("ds1@x.com", "ds2@x.com"):
            member, term, device = setup_member_with_active_device(email=email)
            get_success_data(
                api.ingest_metrics(
                    device["id"],
                    create_ingest_payload(),
                    make_member_headers(member["id"]),
                )
            )
            enrollment = validate_success(
                api.enroll_in_study(
                    study["id"],
                    {"member_id": member["id"]},
                    make_member_headers(member["id"]),
                ),
                expected_status=201,
            )
            members.append(member)
            enrollments.append(enrollment)
        return study, members, enrollments

    def test_contribution_dataset_deidentified_and_withdrawal(self, api, anonymous_headers):
        """PRD: "For every enrollment of the study still in ENROLLED status, and
        for every metric set of that member whose day_on is on or after the
        enrollment's enrolled_on, the dataset emits one row of member_seq, day_on,
        strain_score, recovery_score, and sleep_performance_pct, ordered by
        member_seq ascending and then day_on ascending."
        PRD: "A WITHDRAWN enrollment contributes zero rows — withdrawal removes
        all prior contribution retroactively — and its member_seq is never
        reused."

        Design: Corner/calculations/contribution_dataset_deidentified_and_withdrawal
        """
        study, members, enrollments = self._setup_two_enrolled_members(api)
        admin = make_platform_admin_headers()
        assert enrollments[0]["member_seq"] == 1
        assert enrollments[1]["member_seq"] == 2
        before = validate_success(api.get_contribution_dataset(study["id"], admin))
        assert len(before["rows"]) == 2
        validate_success(
            api.withdraw_enrollment(
                enrollments[0]["id"], make_member_headers(members[0]["id"])
            )
        )
        after = validate_success(api.get_contribution_dataset(study["id"], admin))
        assert len(after["rows"]) == 1
        assert after["rows"][0]["member_seq"] == 2

    def test_contribution_dataset_rows_are_deidentified(self, api, anonymous_headers):
        """PRD: "the dataset emits one row of member_seq, day_on, strain_score,
        recovery_score, and sleep_performance_pct, ordered by member_seq ascending
        and then day_on ascending. No member_id, email, or name ever appears."

        Design: Corner/calculations/contribution_dataset_deidentified_and_withdrawal
        """
        study, members, enrollments = self._setup_two_enrolled_members(api)
        admin = make_platform_admin_headers()
        dataset = validate_success(api.get_contribution_dataset(study["id"], admin))
        assert len(dataset["rows"]) == 2
        for row in dataset["rows"]:
            assert "member_id" not in row
            assert "email" not in row
            assert "full_name" not in row
            assert set(row.keys()) == {
                "member_seq",
                "day_on",
                "strain_score",
                "recovery_score",
                "sleep_performance_pct",
            }
