"""Notices, the audit trail, reconcile sweeps, and the retention purge."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_notice,
    assign_active_investigator,
    attach_report,
    begin_jurisdiction_review,
    case_version,
    confirm_jurisdiction,
    create_case,
    create_directive,
    create_measure,
    create_packet,
    dismiss_case,
    drive_to_investigation,
    file_formal_complaint,
    get_case,
    make_cast,
    make_coordinator_headers,
    make_investigator_headers,
    make_party_headers,
    notice_payload,
    release_packet,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client


class TestNoticeImmutability:
    def test_notice_immutable_no_version_field(self, api):
        """PRD 2.4: "Two resources are deliberately thinner: a `Notice` and a
        `CaseEvent` are immutable records that carry only `id` and `created_at`;
        both `updated_at` and `version` are absent on them."
        PRD 3.1: "Filing moves the case `AWAITING_FORMAL_COMPLAINT →
        INVESTIGATION`, sets `formal_complaint_signed` to true, stamps
        `formal_complaint_filed_at` from the logical clock, automatically issues
        an `ALLEGATIONS` notice to `BOTH` parties — this auto-notice is the
        prerequisite for any later `INTERVIEW` notice — appends
        `FORMAL_COMPLAINT_FILED`, and increments `version`."
        PRD 2.8: "Non-event notice types (`ALLEGATIONS`, `EVIDENCE_RELEASE`,
        `DETERMINATION`, `DISMISSAL`, `APPEAL_FILED`, `APPEAL_OUTCOME`,
        `INFORMAL_PROPOSAL`) always have `lead_time_sufficient` set to true."

        Design: Corner/entities/notice_immutable_no_version_field
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"])
        drive_to_investigation(case["id"], cast["coord"]["id"], cast["comp"]["id"])

        notices, meta = validate_paginated(
            api.list_case_notices(case["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert meta["total_count"] == 1, "filing auto-issues exactly one notice"
        notice = notices[0]
        assert_notice(notice)
        assert notice["notice_type"] == "ALLEGATIONS"
        assert notice["recipient_side"] == "BOTH"
        assert notice["lead_time_sufficient"] is True
        assert_instant_equals(notice["sent_at"], "2026-08-01T00:00:00Z", "sent_at")


class TestNoticeLeadAndOrder:
    def test_interview_notice_five_day_lead_boundary(self, api):
        """PRD 2.8: "An `INTERVIEW` notice must give at least 5 days of lead and a
        `HEARING` notice at least 10 days: the gap between the notice's
        `scheduled_event_at` and its `sent_at` must be at least the required lead
        days expressed in seconds (86,400 seconds per day), and a gap of exactly
        the required lead passes — the comparison is inclusive."
        PRD 2.8: "A shortfall is rejected with `ERR_NOTICE_LEAD_TIME_INSUFFICIENT`
        (422)."

        Design: Corner/calculations/interview_notice_five_day_lead_boundary
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        drive_to_investigation(case["id"], cast["coord"]["id"], cast["comp"]["id"])
        inv_h = make_investigator_headers(cast["inv"]["id"])

        # sent_at is the default clock 2026-08-01T00:00:00Z; 4d23h is short.
        short = api.create_notice(
            case["id"],
            notice_payload(
                notice_type="INTERVIEW", recipient_side="RESPONDENT",
                body="Interview invitation", scheduled_event_at="2026-08-05T23:00:00Z",
            ),
            inv_h,
        )
        validate_error(short, ApiErrorId.ERR_NOTICE_LEAD_TIME_INSUFFICIENT)

        # Exactly 5 days of lead passes the inclusive comparison.
        exact = api.create_notice(
            case["id"],
            notice_payload(
                notice_type="INTERVIEW", recipient_side="RESPONDENT",
                body="Interview invitation", scheduled_event_at="2026-08-06T00:00:00Z",
            ),
            inv_h,
        )
        notice = validate_success(exact, 201)
        assert_notice(notice)
        assert notice["lead_time_sufficient"] is True

    def test_interview_notice_before_allegations_rejected(self, api):
        """PRD 3.4: "an `INTERVIEW` notice may only be created after an
        `ALLEGATIONS` notice exists for the case — parties must receive the
        allegations before any interview — failing as `ERR_NOTICE_ORDER_VIOLATION`
        (422)."

        Design: Corner/validations/interview_notice_before_allegations_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])

        resp = api.create_notice(
            case["id"],
            notice_payload(
                notice_type="INTERVIEW", recipient_side="RESPONDENT",
                body="Come in", scheduled_event_at="2026-08-20T10:00:00Z",
            ),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        # No ALLEGATIONS notice exists before a formal complaint is filed, so
        # the ordering rule fires even with a comfortable lead time.
        validate_error(resp, ApiErrorId.ERR_NOTICE_ORDER_VIOLATION)


class TestReconcileSweep:
    def test_reconcile_checkpoint_sweeps_all_clock_gates(self, api):
        """PRD 3.8: "Clock-gated transitions do not fire on their own: a
        `TitleIXCoordinator` or `CaseAdministrator` runs a per-case
        **reconcile**, which sweeps the case and applies every pending
        clock-driven change in one checkpoint."
        PRD 3.8: "The reconcile response enumerates exactly what fired:
        `expired_measure_ids`, `expired_directive_ids`,
        `review_closed_packet_ids`, and `completed_sanction_ids`."
        PRD 2.8: "When `effective_to` is set, expiry fires as soon as the logical
        clock reaches that instant."

        Design: Corner/endpoints/reconcile_checkpoint_sweeps_all_clock_gates
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])

        measure = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="ESCORT", party_side="BOTH", description="Escort program",
            effective_to="2026-08-05T00:00:00Z",
        )
        directive = create_directive(
            case["id"], cast["coord"]["id"],
            party_side="RESPONDENT", restrictions=["PROXIMITY"], proximity_feet=50,
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-06T00:00:00Z",
        )
        confirm_jurisdiction(case["id"], cast["coord"]["id"])
        file_formal_complaint(case["id"], cast["comp"]["id"])
        assign_active_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        packet = create_packet(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        attach_report(packet["id"], cast["inv"]["id"])
        packet = release_packet(packet["id"], cast["inv"]["id"])

        # All three gates reached at 2026-08-11T00:00:00Z (review closes then).
        set_clock("2026-08-11T00:00:00Z")
        resp = api.reconcile_case(case["id"], TEST_USERS["case_admin_headers"])
        data = validate_success(resp, 200)
        assert sorted(data["expired_measure_ids"]) == [measure["id"]]
        assert sorted(data["expired_directive_ids"]) == [directive["id"]]
        assert sorted(data["review_closed_packet_ids"]) == [packet["id"]]

        m_after = validate_success(api.get_supportive_measure(measure["id"], coord_h))
        assert m_after["status"] == "EXPIRED"
        d_after = validate_success(api.get_no_contact_directive(directive["id"], coord_h))
        assert d_after["status"] == "EXPIRED"
        p_after = validate_success(api.get_evidence_packet(packet["id"], coord_h))
        assert p_after["status"] == "REVIEW_CLOSED"

        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["active_supportive_measure_count"] == 0
        # Exposure recomputed after the directive expired: SEXUAL_HARASSMENT
        # base 25, no ACTIVE directive, no in-window violations, no priors.
        assert case_after["exposure_score"] == 25


class TestAuditTrail:
    def test_audit_trail_order_and_staff_only(self, api):
        """PRD 2.5: "Every consequential mutation on a case or one of its
        descendants appends a row to that case's **audit trail**."
        PRD 2.5: "Reading the audit log is a staff privilege extended to
        `TitleIXCoordinator`, `CaseAdministrator`, `Investigator`,
        `DecisionMaker`, and `AppealOfficer`; parties and advisors may not read
        it."
        PRD 2.4: "At server startup the logical clock is exactly
        `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time
        under any circumstance."

        Design: Corner/endpoints/audit_trail_order_and_staff_only
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        confirm_jurisdiction(case["id"], cast["coord"]["id"])
        file_formal_complaint(case["id"], cast["comp"]["id"])

        events, _ = validate_paginated(api.list_case_events(case["id"], coord_h))
        types = [e["event_type"] for e in events]
        # The intake chain is append-only and chronological across transitions.
        assert types[0] == "REPORT_RECEIVED"
        assert types[1] == "JURISDICTION_REVIEW_STARTED"
        assert types[2] == "JURISDICTION_CONFIRMED"
        # Filing appends FORMAL_COMPLAINT_FILED plus the NOTICE_SENT row of the
        # auto-issued ALLEGATIONS notice; both belong to the filing transition.
        assert set(types[3:]) == {"FORMAL_COMPLAINT_FILED", "NOTICE_SENT"}
        assert len(events) == 5
        for event in events:
            assert_instant_equals(event["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")
            assert isinstance(event["actor_role"], str) and event["actor_role"]
            assert isinstance(event["actor_id"], str) and event["actor_id"]
            assert "version" not in event and "updated_at" not in event

        denied = api.list_case_events(case["id"], make_party_headers(cast["comp"]["id"]))
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestRetentionPurge:
    def test_retention_purge_seven_year_inclusive_boundary(self, api):
        """PRD 2.5: "A retention sweep, run by a `CaseAdministrator`, permanently
        deletes audit-trail rows belonging to cases in a terminal state whose
        closure is at least seven years old — that is, a case whose `closed_at`
        plus seven years is on or before the current logical clock qualifies,
        the boundary included. The sweep returns the `purged_event_count` and the
        list of `purged_case_ids`. Cases themselves and all annual statistics are
        preserved; only event rows are purged."

        Design: Corner/endpoints/retention_purge_seven_year_inclusive_boundary
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        case_a = create_case(
            cast, categories=["STALKING"], occurred_in_program_activity=False,
            received_via="EMAIL",
        )
        begin_jurisdiction_review(case_a["id"], cast["coord"]["id"])
        set_clock("2026-08-03T00:00:00Z")
        dismiss_case(case_a["id"], cast["coord"]["id"],
                     dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=False)

        set_clock("2026-08-03T12:00:00Z")
        case_b = create_case(
            cast, categories=["STALKING"], occurred_in_program_activity=False,
            occurred_at="2026-07-16T22:00:00Z", received_via="EMAIL",
        )
        begin_jurisdiction_review(case_b["id"], cast["coord"]["id"])
        set_clock("2026-08-04T00:00:00Z")
        dismiss_case(case_b["id"], cast["coord"]["id"],
                     dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=False)

        # A closed exactly seven years ago (inclusive); B is one day short.
        set_clock("2033-08-03T00:00:00Z")
        resp = api.run_retention_purge(TEST_USERS["case_admin_headers"])
        data = validate_success(resp, 200)
        assert case_a["id"] in data["purged_case_ids"]
        assert case_b["id"] not in data["purged_case_ids"]
        assert data["purged_event_count"] == 4, (
            "case A's four audit rows (intake, review start, dismissal, notice) are purged"
        )

        # Case rows survive; only event rows are purged.
        case_a_after = validate_success(api.get_case(case_a["id"], coord_h))
        assert case_a_after["status"] == "DISMISSED"
        events_a, meta_a = validate_paginated(api.list_case_events(case_a["id"], coord_h))
        assert events_a == [] and meta_a["total_count"] == 0
        events_b, _ = validate_paginated(api.list_case_events(case_b["id"], coord_h))
        assert len(events_b) == 4
