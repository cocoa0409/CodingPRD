"""Identity requests: MEDIA intake refusal and channel-conditional fork."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_identity_request_payload,
    create_user,
    set_clock,
    validate_error,
    validate_success,
)

LEGAL = TEST_USERS["legal_ops_headers"]


class TestMediaIntakeRefusal:
    def test_media_channel_refused_at_intake(self, api):
        """PRD §3.10: "A request with `channel` = `MEDIA` is refused at intake
        — the platform's standing policy is that media requests never disclose
        reviewer identity — and is rejected with `ERR_MEDIA_REQUEST_REFUSED`
        (HTTP 422)."

        Design: Corner/validations/media_request_refused_at_intake
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        r = api.create_identity_request(
            create_identity_request_payload(
                subject_user_id=subject["id"],
                requester_label="Daily Gazette",
                channel="MEDIA",
                legal_process_ref=None,
            ),
            LEGAL,
        )
        validate_error(r, ApiErrorId.ERR_MEDIA_REQUEST_REFUSED.value)

    def test_media_channel_with_process_ref_also_refused(self, api):
        """PRD §3.10: "The same rejection fires when `legal_process_ref` is
        missing for a `LEGAL_SUBPOENA` or `LAW_ENFORCEMENT` request, or is
        supplied on a `MEDIA` request."

        Design: Corner/validations/media_request_refused_at_intake
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        r = api.create_identity_request(
            create_identity_request_payload(
                subject_user_id=subject["id"],
                requester_label="Daily Gazette",
                channel="MEDIA",
                legal_process_ref="PRESS-1",
            ),
            LEGAL,
        )
        validate_error(r, ApiErrorId.ERR_MEDIA_REQUEST_REFUSED.value)


class TestChannelForkAtUnderReview:
    def test_law_enforcement_releases_directly_from_under_review(self, api):
        """PRD §3.10: "For a `LAW_ENFORCEMENT` request, no notice step is
        required: `LegalOps` releases directly from `UNDER_REVIEW` to terminal
        `RELEASED`."

        Design: Difficulty/non_linear_state_machine/identity_request_branching_fork
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        ir = validate_success(
            api.create_identity_request(
                create_identity_request_payload(
                    subject_user_id=subject["id"],
                    requester_label="City PD",
                    channel="LAW_ENFORCEMENT",
                    legal_process_ref="CASE-77",
                ),
                LEGAL,
            ),
            expected_status=201,
        )
        validate_success(api.start_review_identity_request(ir["id"], LEGAL))
        released = validate_success(api.release_identity_request(ir["id"], LEGAL))
        assert released["status"] == "RELEASED"

    def test_legal_subpoena_release_blocked_before_notice_deadline(self, api):
        """PRD §3.10: "Release from `NOTICE_SENT` is blocked until the logical
        clock reaches `notice_deadline`; an early release attempt is rejected
        with `ERR_NOTICE_PERIOD_ACTIVE` (HTTP 409)".

        Design: Difficulty/non_linear_state_machine/identity_request_branching_fork
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        ir = validate_success(
            api.create_identity_request(
                create_identity_request_payload(
                    subject_user_id=subject["id"],
                    requester_label="Doe v. Roe counsel",
                    channel="LEGAL_SUBPOENA",
                    legal_process_ref="DOCKET-2026-100",
                ),
                LEGAL,
            ),
            expected_status=201,
        )
        validate_success(api.start_review_identity_request(ir["id"], LEGAL))
        noticed = validate_success(api.send_notice_identity_request(ir["id"], LEGAL))
        assert noticed["status"] == "NOTICE_SENT"
        r = api.release_identity_request(ir["id"], LEGAL)
        validate_error(r, ApiErrorId.ERR_NOTICE_PERIOD_ACTIVE.value)

    def test_send_notice_stamps_deadline_fourteen_days_out(self, api):
        """PRD §3.10: "For a `LEGAL_SUBPOENA` request, `LegalOps` sends notice
        to the subject user, moving the request to `NOTICE_SENT` and stamping
        `notice_sent_at` with the current logical time and `notice_deadline`
        with `notice_sent_at` plus 14 days."

        Design: Difficulty/non_linear_state_machine/identity_request_branching_fork
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        ir = validate_success(
            api.create_identity_request(
                create_identity_request_payload(
                    subject_user_id=subject["id"],
                    requester_label="Counsel LLP",
                    channel="LEGAL_SUBPOENA",
                    legal_process_ref="DOCKET-55",
                ),
                LEGAL,
            ),
            expected_status=201,
        )
        validate_success(api.start_review_identity_request(ir["id"], LEGAL))
        noticed = validate_success(api.send_notice_identity_request(ir["id"], LEGAL))
        assert noticed["notice_sent_at"].startswith("2026-09-01T00:00:00")
        assert noticed["notice_deadline"].startswith("2026-09-15T00:00:00")
        after_block = validate_success(api.get_identity_request(ir["id"], LEGAL))
        assert after_block["status"] == "NOTICE_SENT"


class TestNoticePeriodBoundary:
    def test_release_one_second_before_deadline_fails(self, api):
        """PRD §3.10: "Release from `NOTICE_SENT` is blocked until the logical
        clock reaches `notice_deadline`; an early release attempt is rejected
        with `ERR_NOTICE_PERIOD_ACTIVE` (HTTP 409)".

        Design: Corner/errors/err_notice_period_active_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        ir = validate_success(
            api.create_identity_request(
                create_identity_request_payload(
                    subject_user_id=subject["id"], legal_process_ref="DOCKET-56"
                ),
                LEGAL,
            ),
            expected_status=201,
        )
        validate_success(api.start_review_identity_request(ir["id"], LEGAL))
        validate_success(api.send_notice_identity_request(ir["id"], LEGAL))
        set_clock("2026-09-14T23:59:59Z")
        r = api.release_identity_request(ir["id"], LEGAL)
        validate_error(r, ApiErrorId.ERR_NOTICE_PERIOD_ACTIVE.value)

    def test_release_exactly_at_deadline_succeeds(self, api):
        """PRD §3.10: "Release from `NOTICE_SENT` is blocked until the logical
        clock reaches `notice_deadline`; an early release attempt is rejected
        with `ERR_NOTICE_PERIOD_ACTIVE` (HTTP 409), and once the deadline has
        passed a successful release moves the request to terminal `RELEASED`."

        Design: Corner/errors/err_notice_period_active_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        subject = create_user()
        ir = validate_success(
            api.create_identity_request(
                create_identity_request_payload(
                    subject_user_id=subject["id"], legal_process_ref="DOCKET-57"
                ),
                LEGAL,
            ),
            expected_status=201,
        )
        validate_success(api.start_review_identity_request(ir["id"], LEGAL))
        validate_success(api.send_notice_identity_request(ir["id"], LEGAL))
        set_clock("2026-09-15T00:00:00Z")
        released = validate_success(api.release_identity_request(ir["id"], LEGAL))
        assert released["status"] == "RELEASED"
