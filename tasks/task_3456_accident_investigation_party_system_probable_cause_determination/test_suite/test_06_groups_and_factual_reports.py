"""Investigative groups and factual reports: enum validation, chairman
segregation, the transcript conditional-field rule, recorder data protection
on verification, and the completion evidence gate (PRD §3.3, §3.5, §3.6).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_factual_report,
    create_group_payload,
    factual_report_payload,
    find_report,
    get_group,
    get_investigation,
    make_iic_headers,
    setup_factual,
    setup_launched_investigation,
    setup_recorder_with_pending_session,
    validate_error,
    validate_paginated,
    verify_report,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]


class TestGroupCreationRules:
    def test_group_create_with_invalid_enum_specialty_returns_invalid_request(self, api):
        """PRD §3.3: groups are "named by a `specialty` of `OPERATIONS`,
        `STRUCTURES`, `HUMAN_PERFORMANCE`, or `RECORDERS`". PRD §2.8: "a
        request that is malformed — a required field missing, an enum value
        outside its declared set, a conditional-field rule violated, or a
        numeric range violated — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/group_create_with_invalid_enum_specialty_returns_invalid_request
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_group(
            create_group_payload(inv_id, "METALLURGY", "gc-1"),
            make_iic_headers(ctx["iic_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        rows, _ = validate_paginated(
            api.list_groups(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert rows == []

    def test_iic_cannot_chair_own_investigation_group(self, api):
        """PRD §3.3: "Segregation of duties bars the investigator-in-charge
        from chairing a group on their own investigation: a `chairman_user_id`
        equal to the investigation's `iic_user_id` is rejected with
        `ERR_SOD_IIC_CANNOT_CHAIR`."

        Design: Corner/validations/iic_cannot_chair_own_investigation_group
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_group(
            create_group_payload(inv_id, "OPERATIONS", ctx["iic_user_id"]),
            make_iic_headers(ctx["iic_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_IIC_CANNOT_CHAIR)

        rows, _ = validate_paginated(
            api.list_groups(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert rows == []


class TestTranscriptReports:
    def test_transcript_report_without_recorder_reference_returns_invalid_request(self, api):
        """PRD §3.5: "A `recorder_id` is required exactly when the kind is
        `RECORDER_TRANSCRIPT` and must be absent for the other kinds
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/transcript_report_without_recorder_reference_returns_invalid_request
        """
        ctx = setup_factual()
        group_id = ctx["group"]["id"]

        resp = api.create_factual_report(
            group_id,
            factual_report_payload("RECORDER_TRANSCRIPT", "CVR transcript excerpt."),
            TEST_USERS["group_chairman_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        group = get_group(group_id)
        assert len(group["factual_reports"]) == 1, "nothing may be persisted"
        assert group["factual_reports"][0]["report_id"] == ctx["report_id"]

    def test_transcript_verify_blocked_until_readout_complete(self, api):
        """PRD §3.5: "A transcript report carries an additional data-protection
        gate: the recorder it references must have reached `READOUT_COMPLETE`
        or `RELEASED`, else verification is rejected with
        `ERR_RECORDER_READOUT_INCOMPLETE`."

        Design: Corner/validations/transcript_verify_blocked_until_readout_complete
        """
        ctx = setup_factual()
        inv_id = ctx["investigation"]["id"]
        group_id = ctx["group"]["id"]

        # One CVR whose only session window is still in the future relative to
        # the logical clock (pinned at 2026-09-01T00:00:00Z by the chain).
        recorder = setup_recorder_with_pending_session(inv_id, recorder_type="CVR")
        group = create_factual_report(
            group_id,
            report_kind="RECORDER_TRANSCRIPT",
            content="CVR transcript excerpt.",
            recorder_id=recorder["id"],
        )
        transcript = find_report(group)

        resp = api.verify_factual_report(
            group_id, transcript["report_id"], make_iic_headers(ctx["iic_user_id"])
        )
        validate_error(resp, ApiErrorId.ERR_RECORDER_READOUT_INCOMPLETE)
        assert (
            find_report(get_group(group_id), report_id=transcript["report_id"])["status"]
            == "SUBMITTED"
        )


class TestVerificationAndCompletionGates:
    def test_verify_already_verified_report_returns_report_state_invalid(self, api):
        """PRD §3.5: verification is "performed while the group is still
        `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the investigation is in the
        `FACTUAL` phase, and the report is `SUBMITTED`
        (`ERR_REPORT_STATE_INVALID`)". PRD §3.5: "Verification stamps
        `verified_at` from the logical clock, moves the report to `VERIFIED`,
        and increments the group's `version`."

        Design: Corner/errors/verify_already_verified_report_returns_report_state_invalid
        """
        ctx = setup_factual()
        group_id = ctx["group"]["id"]
        group = verify_report(group_id, ctx["report_id"], iic_user_id=ctx["iic_user_id"])
        verified_at_first = find_report(group, report_id=ctx["report_id"])["verified_at"]
        assert verified_at_first is not None

        resp = api.verify_factual_report(
            group_id, ctx["report_id"], make_iic_headers(ctx["iic_user_id"])
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_STATE_INVALID)

        report = find_report(get_group(group_id), report_id=ctx["report_id"])
        assert report["status"] == "VERIFIED"
        assert report["verified_at"] == verified_at_first

    def test_complete_group_without_verified_report_returns_not_completable(self, api):
        """PRD §3.5: "A chairman marks their group complete once the
        investigation is in the `FACTUAL` phase, the group is `ACTIVE`, at
        least one party seat is `SEATED` on it, and at least one of its reports
        is `VERIFIED` or `DOCKETED` — a shortfall on either of the last two
        conditions is rejected with `ERR_GROUP_NOT_COMPLETABLE`."

        Design: Corner/errors/complete_group_without_verified_report_returns_not_completable
        """
        ctx = setup_factual()
        group_id = ctx["group"]["id"]
        # The group holds a SEATED seat but its only report is SUBMITTED.
        assert find_report(get_group(group_id), report_id=ctx["report_id"])["status"] == "SUBMITTED"

        resp = api.complete_group(group_id, TEST_USERS["group_chairman_headers"])
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_COMPLETABLE)

        assert get_group(group_id)["status"] == "ACTIVE"
        assert get_investigation(ctx["investigation"]["id"])["docket_completeness_pct"] == 0
