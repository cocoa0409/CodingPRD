"""Proactive employer outreach: trust gates and the daily messaging allowance."""
from test_helpers import (
    ApiErrorId,
    create_outreach_message_payload,
    create_student,
    get_employer,
    make_employer_recruiter_headers,
    patch_student,
    send_outreach,
    setup_low_risk_marketplace,
    setup_messaging_marketplace,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PA


def _send_raw(api, employer_id, student_id, body):
    return api.create_outreach_message(
        create_outreach_message_payload(employer_id, student_id, body=body),
        make_employer_recruiter_headers(employer_id),
    )


class TestElevatedTierAllowance:
    def test_elevated_tier_cap_allows_two_messages(self, api):
        """PRD §3.8: "The employer's `trust_tier` sets a tier cap by scaling a base of
        5 messages: the tier multiplier is 200 percent for `LOW_RISK`, 100 percent for
        `STANDARD`, 40 percent for `ELEVATED`, and 0 percent for `HIGH_RISK`, and the
        tier cap is the integer floor of five times the multiplier percent divided by
        one hundred — that is, 10 messages per logical day for a `LOW_RISK` employer,
        5 for `STANDARD`, 2 for `ELEVATED`, and none at all for `HIGH_RISK`."
        PRD §3.8: "the message's `university_id` is denormalized from the student's
        roster home at send time — that denormalization is what scopes the daily count —
        and `sent_day` records the logical-day bucket, the calendar date of the logical
        clock in year-month-day form, against which the count is tallied."

        Design: Difficulty/combinatorial_formula/messaging_allowance_nested_min_tier_floor
        """
        ctx = setup_messaging_marketplace()
        employer = get_employer(ctx["employer"]["id"])
        # Auto score 50 (STANDARD) + analyst adjustment 1 = 51 -> ELEVATED.
        assert employer["fraud_risk_score"] == 51
        assert employer["trust_tier"] == "ELEVATED"

        msg1 = send_outreach(ctx["employer"]["id"], ctx["student"]["id"],
                             body="Opportunity 1")
        assert msg1["university_id"] == ctx["university"]["id"]
        assert msg1["sent_day"] == "2026-09-01"
        msg2 = send_outreach(ctx["employer"]["id"], ctx["student"]["id"],
                             body="Opportunity 2")
        assert msg2["employer_id"] == ctx["employer"]["id"]

    def test_third_message_at_effective_cap_rejected(self, api):
        """PRD §3.8: "The effective cap is the minimum of that tier cap and the
        recipient university's `employer_daily_message_cap`, so a university can
        tighten — never widen — what an employer's tier would allow."
        PRD §3.8: "The send is allowed only while the count of messages already sent by
        this employer to students of this university on the current logical day is
        strictly below the effective cap; when the count has reached the cap, the send
        is rejected with `ERR_MESSAGE_LIMIT_REACHED` (HTTP 429)."

        Design: Difficulty/combinatorial_formula/messaging_allowance_nested_min_tier_floor
        """
        ctx = setup_messaging_marketplace()
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 1")
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 2")
        # effective_cap = min(10, floor(5 * 40 / 100)) = min(10, 2) = 2; sent_today 2
        # is not strictly below 2.
        response = _send_raw(api, ctx["employer"]["id"], ctx["student"]["id"],
                             "Opportunity 3")
        validate_error(response, ApiErrorId.ERR_MESSAGE_LIMIT_REACHED, 429)
        rows, _meta = validate_paginated(
            api.list_outreach_messages(PA, params={"employer_id": ctx["employer"]["id"]})
        )
        assert len(rows) == 2, "the rejected third send must not persist a message"


class TestVisibilityGateBeatsCapacity:
    def test_hidden_profile_rejected_even_when_allowance_exhausted(self, api):
        """PRD §3.8: "Only after all trust gates pass does the allowance check run —
        it sits at priority ten, deliberately after every cheaper rejection."
        PRD §3.8: "the student's `profile_visibility` must be
        `PUBLIC_TO_APPROVED_EMPLOYERS`, any other setting failing with
        `ERR_PROFILE_NOT_VISIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/outreach_visibility_error_beats_capacity_error
        """
        ctx = setup_messaging_marketplace()
        helen = create_student(
            ctx["university"]["id"], email="helen@stateu.edu", full_name="Helen Park",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="HIDDEN",
        )
        # Burn the ELEVATED daily allowance of 2 on the visible student first.
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 1")
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 2")
        response = _send_raw(api, ctx["employer"]["id"], helen["id"], "Opportunity 3")
        error = validate_error(response, ApiErrorId.ERR_PROFILE_NOT_VISIBLE, 403)
        # The capacity violation is equally true (sent_today == effective_cap), yet the
        # earlier safety gate is the one reported.
        assert error["error_id"] != "ERR_MESSAGE_LIMIT_REACHED"
        rows, _meta = validate_paginated(
            api.list_outreach_messages(PA, params={"employer_id": ctx["employer"]["id"]})
        )
        assert len(rows) == 2

    def test_visible_recipient_at_cap_yields_limit_error(self, api):
        """PRD §3.8: "The send is allowed only while the count of messages already sent
        by this employer to students of this university on the current logical day is
        strictly below the effective cap; when the count has reached the cap, the send
        is rejected with `ERR_MESSAGE_LIMIT_REACHED` (HTTP 429)."

        Design: Difficulty/priority_pair_validation_conflict/outreach_visibility_error_beats_capacity_error
        """
        ctx = setup_messaging_marketplace()
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 1")
        send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body="Opportunity 2")
        # Every trust gate passes for Sam; only the allowance remains to fail.
        response = _send_raw(api, ctx["employer"]["id"], ctx["student"]["id"],
                             "Opportunity 3")
        validate_error(response, ApiErrorId.ERR_MESSAGE_LIMIT_REACHED, 429)


class TestCapBoundary:
    def test_low_risk_sends_up_to_university_ceiling(self, api):
        """PRD §3.8: "The effective cap is the minimum of that tier cap and the
        recipient university's `employer_daily_message_cap`, so a university can
        tighten — never widen — what an employer's tier would allow."
        PRD §3.8: "The send is allowed only while the count of messages already sent by
        this employer to students of this university on the current logical day is
        strictly below the effective cap"

        Design: Difficulty/boundary_precision_check/message_cap_boundary_at_exactly_effective_cap
        """
        ctx = setup_low_risk_marketplace()
        employer = get_employer(ctx["employer"]["id"])
        # Auto score 10 (email-domain match -25, .edu TLD -15) -> LOW_RISK;
        # tier cap floor(5 * 200 / 100) = 10; university cap 3 binds: min(3, 10) = 3.
        assert employer["fraud_risk_score"] == 10
        assert employer["trust_tier"] == "LOW_RISK"
        assert ctx["university"]["employer_daily_message_cap"] == 3
        for body in ("m1", "m2", "m3"):
            message = send_outreach(ctx["employer"]["id"], ctx["student"]["id"],
                                    body=body)
            assert message["sent_day"] == "2026-09-01"

    def test_send_at_exactly_effective_cap_rejected(self, api):
        """PRD §3.8: "The send is allowed only while the count of messages already sent
        by this employer to students of this university on the current logical day is
        strictly below the effective cap; when the count has reached the cap, the send
        is rejected with `ERR_MESSAGE_LIMIT_REACHED` (HTTP 429)."

        Design: Difficulty/boundary_precision_check/message_cap_boundary_at_exactly_effective_cap
        """
        ctx = setup_low_risk_marketplace()
        for body in ("m1", "m2", "m3"):
            send_outreach(ctx["employer"]["id"], ctx["student"]["id"], body=body)
        # sent_today == 3 == effective_cap; '==' is on the rejected side.
        response = _send_raw(api, ctx["employer"]["id"], ctx["student"]["id"], "m4")
        validate_error(response, ApiErrorId.ERR_MESSAGE_LIMIT_REACHED, 429)
        rows, _meta = validate_paginated(
            api.list_outreach_messages(PA, params={"employer_id": ctx["employer"]["id"]})
        )
        assert len(rows) == 3


class TestOutreachRecipientState:
    def test_outreach_to_withdrawn_student_returns_not_enrolled(self, api):
        """PRD §3.8: "the student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) at an
        `ACTIVE` university (`ERR_UNIVERSITY_NOT_ACTIVE`)"
        PRD §3.1: "Withdrawal is the destructive branch and cascades in two hops."

        Design: Corner/errors/outreach_to_withdrawn_student_returns_not_enrolled
        """
        ctx = setup_messaging_marketplace()
        sally = create_student(
            ctx["university"]["id"], email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        patch_student(sally["id"], ctx["university"]["id"], {"status": "WITHDRAWN"})
        response = _send_raw(api, ctx["employer"]["id"], sally["id"], "Hello")
        validate_error(response, ApiErrorId.ERR_STUDENT_NOT_ENROLLED, 409)
        rows, _meta = validate_paginated(
            api.list_outreach_messages(PA, params={"employer_id": ctx["employer"]["id"]})
        )
        assert len(rows) == 0
