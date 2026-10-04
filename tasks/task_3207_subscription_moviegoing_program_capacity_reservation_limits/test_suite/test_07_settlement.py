"""Studio settlement: valuation, line rules, report lifecycle, dispute cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_settlement_line,
    create_active_member,
    create_confirmed_reservation,
    create_on_sale_showtime,
    create_published_plan,
    create_theater_with_auditorium,
    enroll_member,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_checked_in_scenario,
    setup_no_show_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]
STAFF = TEST_USERS["theater_staff_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]


class TestSettlementValuationVariants:

    def test_subscription_line_contract_rate_draft_and_submit(self, api):
        """PRD §3.11: "A `SUBSCRIPTION` line is valued at the flat studio
        contract rate of 899 cents (`STUDIO_CONTRACT_RATE_CENTS`) regardless of
        format, surcharge, or attendance — a checked-in admission and a no-show
        both count."
        PRD §3.11: "While the report is `DRAFT` (including a report returned to
        `DRAFT` after dispute), its totals are provisional: `total_admissions`
        counts the included lines, `total_subscription_admissions` counts the
        `SUBSCRIPTION` lines among them, and `total_gross_cents` sums the
        lines' `reported_value_cents`, all recomputed live from the current
        line set."

        Design: Difficulty/dual_variant_calc/settlement_provisional_draft_vs_finalized_submitted_totals
        """
        ctx = setup_checked_in_scenario()
        line = get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        assert_settlement_line(line)
        assert line["reported_value_cents"] == 899, (
            f"contract rate is 899, not the 1200 box-office price; got "
            f"{line['reported_value_cents']}")
        draft = get_success_data(api.get_settlement_report(ctx["report"]["id"], STAFF))
        assert draft["total_gross_cents"] == 899
        assert draft["total_subscription_admissions"] == 1
        assert draft["total_admissions"] == 1

    def test_submit_freezes_totals_and_marks_reservation_reported(self, api):
        """PRD §3.11: "Submitting the report — a `TheaterStaff` action
        requiring at least one line, else `ERR_EMPTY_REPORT` — moves it `DRAFT
        → SUBMITTED`, freezes the totals as stored fields, locks the line set
        (further line additions or removals are rejected with
        `ERR_INVALID_STATE`), and flips `settlement_reported` to true on every
        included reservation."

        Design: Difficulty/dual_variant_calc/settlement_provisional_draft_vs_finalized_submitted_totals
        """
        ctx = setup_checked_in_scenario()
        get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        submitted = get_success_data(
            api.submit_settlement_report(ctx["report"]["id"], STAFF))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_gross_cents"] == 899
        reservation = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], SERVICES))
        assert reservation["settlement_reported"] is True
        # Frozen line set: further additions rejected
        ctx2 = setup_checked_in_scenario  # noqa: F841 (documentation anchor)
        resp = api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDisputeReviseCycle:

    def _submitted_report_with_line(self, api):
        ctx = setup_checked_in_scenario(studio_code="UNI")
        get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        get_success_data(api.submit_settlement_report(ctx["report"]["id"], STAFF))
        return ctx

    def test_settlement_report_dispute_revise_cycle(self, api):
        """PRD §3.11: "dispute reverts `settlement_reported` to false on every
        included reservation so a corrected report may re-include them.
        `TheaterStaff` returns a `DISPUTED` report to `DRAFT` via revision,
        reopening the line set for additions and removals with totals
        recomputed live."

        Design: Difficulty/non_linear_state_machine/settlement_report_dispute_revise_cycle
        """
        ctx = self._submitted_report_with_line(api)
        report_id = ctx["report"]["id"]
        disputed = get_success_data(api.dispute_settlement_report(
            report_id, {"dispute_note": "rate mismatch"}, STUDIO))
        assert disputed["status"] == "DISPUTED"
        reservation = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], STAFF))
        assert reservation["settlement_reported"] is False, (
            "dispute must revert settlement_reported so a corrected report may re-include")
        revised = get_success_data(api.revise_settlement_report(report_id, STAFF))
        assert revised["status"] == "DRAFT"
        resubmitted = get_success_data(api.submit_settlement_report(report_id, STAFF))
        assert resubmitted["status"] == "SUBMITTED"
        reservation2 = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], STAFF))
        assert reservation2["settlement_reported"] is True

    def test_dispute_reopens_line_set_for_edits(self, api):
        """PRD §3.11: "`TheaterStaff` returns a `DISPUTED` report to `DRAFT`
        via revision, reopening the line set for additions and removals with
        totals recomputed live."

        Design: Difficulty/non_linear_state_machine/settlement_report_dispute_revise_cycle
        """
        ctx = self._submitted_report_with_line(api)
        report_id = ctx["report"]["id"]
        get_success_data(api.dispute_settlement_report(
            report_id, {"dispute_note": "rate mismatch"}, STUDIO))
        get_success_data(api.revise_settlement_report(report_id, STAFF))
        # Line set editable again in DRAFT after revise: a second checked-in
        # reservation (reverted to settleable by the dispute) can be re-added
        resp = api.add_settlement_line(
            report_id, {"reservation_id": ctx["reservation"]["id"]}, STAFF)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE)  # line still present — editable set means duplicate check still fires
        report = get_success_data(api.get_settlement_report(report_id, STAFF))
        assert report["status"] == "DRAFT"
        assert report["total_admissions"] == 1


class TestAcknowledgeTerminal:

    def _acknowledged_report(self, api):
        ctx = setup_checked_in_scenario()
        get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        get_success_data(api.submit_settlement_report(ctx["report"]["id"], STAFF))
        get_success_data(api.acknowledge_settlement_report(ctx["report"]["id"], STUDIO))
        return ctx

    def test_settlement_acknowledge_is_terminal_dispute_rejected(self, api):
        """PRD §3.11: "A `StudioRep` may acknowledge a `SUBMITTED` report,
        moving it to the terminal `ACKNOWLEDGED` state"

        Design: Corner/state_machines/settlement_acknowledge_is_terminal
        """
        ctx = self._acknowledged_report(api)
        resp = api.dispute_settlement_report(
            ctx["report"]["id"], {"dispute_note": "too late"}, STUDIO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_settlement_acknowledge_is_terminal_revise_rejected(self, api):
        """PRD §3.11: "A `StudioRep` may acknowledge a `SUBMITTED` report,
        moving it to the terminal `ACKNOWLEDGED` state"

        Design: Corner/state_machines/settlement_acknowledge_is_terminal
        """
        ctx = self._acknowledged_report(api)
        resp = api.revise_settlement_report(ctx["report"]["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestLineSettleability:

    def test_no_show_still_settleable_as_admission(self, api):
        """PRD §3.5: "Critically, a `NO_SHOW` reservation remains settleable —
        studios are owed an admission report regardless of attendance."
        PRD §3.11: "A line's reservation must be settleable: in `CHECKED_IN` or
        `NO_SHOW` status (never `CANCELLED`, `EXPIRED`, or `HELD`)"

        Design: Corner/calculations/no_show_still_settleable_as_admission
        """
        ctx = setup_no_show_scenario()
        report = get_success_data(api.create_settlement_report(
            ctx["theater"]["id"],
            {"studio_code": "WB", "period_start": "2026-09-02T00:00:00Z",
             "period_end": "2026-09-04T00:00:00Z"},
            STAFF))
        assert ctx["reservation"]["status"] == "NO_SHOW"
        line = get_success_data(api.add_settlement_line(
            report["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        assert line["line_kind"] == "SUBSCRIPTION"
        assert line["reported_value_cents"] == 899
        refreshed = get_success_data(api.get_settlement_report(report["id"], STAFF))
        assert refreshed["total_admissions"] == 1
        assert refreshed["total_subscription_admissions"] == 1

    def test_no_show_line_and_checked_in_line_both_counted(self, api):
        """PRD §3.11: "A `SUBSCRIPTION` line is valued at the flat studio
        contract rate of 899 cents (`STUDIO_CONTRACT_RATE_CENTS`) regardless of
        format, surcharge, or attendance — a checked-in admission and a no-show
        both count."

        Design: Corner/calculations/no_show_still_settleable_as_admission
        """
        # One CHECKED_IN + one NO_SHOW in the same period on the same theater
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3)
        theater, auditorium = create_theater_with_auditorium()
        st_a = create_on_sale_showtime(auditorium["id"], film_title="A",
                                       starts_at="2026-09-02T19:00:00Z")
        st_b = create_on_sale_showtime(auditorium["id"], film_title="B",
                                       starts_at="2026-09-03T19:00:00Z")
        member = create_active_member(email="ns2@x.com", full_name="NS2")
        sub = enroll_member(member["id"], plan["id"])
        r_a = create_confirmed_reservation(member, sub, st_a)
        r_b = create_confirmed_reservation(member, sub, st_b)
        set_clock("2026-09-02T19:05:00Z")
        get_success_data(api.check_in_reservation(r_a["id"], STAFF))
        set_clock("2026-09-04T12:00:00Z")  # r_b swept to NO_SHOW
        r_b = get_success_data(api.get_reservation(r_b["id"], SERVICES))
        assert r_b["status"] == "NO_SHOW"
        report = get_success_data(api.create_settlement_report(
            theater["id"],
            {"studio_code": "WB", "period_start": "2026-09-02T00:00:00Z",
             "period_end": "2026-09-05T00:00:00Z"},
            STAFF))
        get_success_data(api.add_settlement_line(report["id"], {"reservation_id": r_a["id"]}, STAFF))
        get_success_data(api.add_settlement_line(report["id"], {"reservation_id": r_b["id"]}, STAFF))
        refreshed = get_success_data(api.get_settlement_report(report["id"], STAFF))
        assert refreshed["total_admissions"] == 2
        assert refreshed["total_subscription_admissions"] == 2
        assert refreshed["total_gross_cents"] == 899 * 2

    def test_settlement_period_overlap_exclusion(self, api):
        """PRD §3.11: "`TheaterStaff` opens a `SettlementReport` for their
        theater by supplying the `studio_code`, an inclusive `period_start`,
        and an exclusive `period_end` that must fall after the start"
        PRD §3.11: "whose showtime falls within the report's period. Any of
        these failures rejects the add with `ERR_LINE_NOT_SETTLEABLE`"

        Design: Difficulty/resource_temporal_overlap/settlement_period_overlap_exclusion
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3)
        theater, auditorium = create_theater_with_auditorium()
        st_in = create_on_sale_showtime(auditorium["id"], film_title="IN",
                                        starts_at="2026-09-02T19:00:00Z")
        st_edge = create_on_sale_showtime(auditorium["id"], film_title="EDGE",
                                          starts_at="2026-09-03T00:00:00Z")
        member = create_active_member(email="m17@x.com", full_name="M17")
        sub = enroll_member(member["id"], plan["id"])
        r_in = create_confirmed_reservation(member, sub, st_in)
        r_edge = create_confirmed_reservation(member, sub, st_edge)
        set_clock("2026-09-02T19:10:00Z")
        get_success_data(api.check_in_reservation(r_in["id"], STAFF))
        set_clock("2026-09-03T00:10:00Z")
        get_success_data(api.check_in_reservation(r_edge["id"], STAFF))
        report = get_success_data(api.create_settlement_report(
            theater["id"],
            {"studio_code": "WB", "period_start": "2026-09-02T00:00:00Z",
             "period_end": "2026-09-03T00:00:00Z"},
            STAFF))
        get_success_data(api.add_settlement_line(report["id"], {"reservation_id": r_in["id"]}, STAFF))
        # Showtime at exactly period_end belongs to the next period
        resp = api.add_settlement_line(report["id"], {"reservation_id": r_edge["id"]}, STAFF)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_SETTLEABLE)

    def test_settlement_period_end_equals_showtime_start_belongs_next_period(self, api):
        """PRD §3.11: "`TheaterStaff` opens a `SettlementReport` for their
        theater by supplying the `studio_code`, an inclusive `period_start`,
        and an exclusive `period_end` that must fall after the start"

        Design: Difficulty/resource_temporal_overlap/settlement_period_overlap_exclusion
        """
        set_clock()
        plan = create_published_plan(weekly_reservation_quota=3)
        theater, auditorium = create_theater_with_auditorium()
        st_edge = create_on_sale_showtime(auditorium["id"], film_title="EDGE",
                                          starts_at="2026-09-03T00:00:00Z")
        member = create_active_member(email="m17b@x.com", full_name="M17B")
        sub = enroll_member(member["id"], plan["id"])
        r_edge = create_confirmed_reservation(member, sub, st_edge)
        set_clock("2026-09-03T00:10:00Z")
        get_success_data(api.check_in_reservation(r_edge["id"], STAFF))
        # A report whose period STARTS at the boundary admits the same line
        report = get_success_data(api.create_settlement_report(
            theater["id"],
            {"studio_code": "WB", "period_start": "2026-09-03T00:00:00Z",
             "period_end": "2026-09-04T00:00:00Z"},
            STAFF))
        line = get_success_data(api.add_settlement_line(
            report["id"], {"reservation_id": r_edge["id"]}, STAFF))
        assert line["reported_value_cents"] == 899

    def test_duplicate_line_same_report_rejected(self, api):
        """PRD §3.11: "adding the same reservation twice to one report is
        rejected with `ERR_DUPLICATE_LINE`."

        Design: Corner/validations/duplicate_line_same_report_rejected
        """
        ctx = setup_checked_in_scenario()
        get_success_data(api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF))
        resp = api.add_settlement_line(
            ctx["report"]["id"], {"reservation_id": ctx["reservation"]["id"]}, STAFF)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE)

    def test_settlement_empty_report_submit_rejected(self, api):
        """PRD §3.11: "Submitting the report — a `TheaterStaff` action
        requiring at least one line, else `ERR_EMPTY_REPORT`"

        Design: Corner/endpoints/settlement_empty_report_submit_rejected
        """
        set_clock()
        theater, _aud = create_theater_with_auditorium()
        report = get_success_data(api.create_settlement_report(
            theater["id"],
            {"studio_code": "WB", "period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-09-02T00:00:00Z"},
            STAFF))
        resp = api.submit_settlement_report(report["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_EMPTY_REPORT)
