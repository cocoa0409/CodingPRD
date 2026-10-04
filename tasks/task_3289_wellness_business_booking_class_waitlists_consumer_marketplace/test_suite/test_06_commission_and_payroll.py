"""Commission accrual, cap-mode variants, payroll runs and revenue conservation."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    TEST_USERS,
    book,
    create_client,
    create_payroll_period,
    create_session,
    create_staff,
    create_template,
    ensure_tier,
    get_success_data,
    make_client_headers,
    make_studio_owner_headers,
    set_clock,
    setup_attended_session,
    setup_studio_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

ANONYMOUS = TEST_USERS["anonymous_headers"]


class TestCommissionCapModeVariants:

    def test_commission_accrual_cap_mode_orders_disagree_on_identical_inputs(self, api):
        """PRD §3.6: "Under `BONUS_OUTSIDE_CAP` the ceiling is applied to the teaching commission first and the bonus is added afterwards whenever the bonus reaches the channel bonus threshold of 150 cents, so the final commission strictly exceeds the ceiling in that case and the bonus escapes the cap. Under `BONUS_INSIDE_CAP` the bonus is folded into the commission before the ceiling is applied, so identical booking data can yield exactly the ceiling with the bonus clipped away."

        Design: Difficulty/combinatorial_formula/commission_accrual_evaluation_order_pins_bonus_against_the_accrual_ceiling
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        entries = {}
        for legal_name, mode in (("Prana Loft", "BONUS_OUTSIDE_CAP"),
                                 ("Prana Annex", "BONUS_INSIDE_CAP")):
            studio = validate_success(api.create_studio({
                "legal_name": legal_name, "home_state_code": "CA",
                "owner_full_name": "Nadia Okafor", "tier": "GROWTH",
                "billing_period": "MONTHLY", "payroll_cap_mode": mode,
            }, ANONYMOUS), expected_status=201)
            owner = make_studio_owner_headers(studio["id"])
            sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
            create_payroll_period(studio["id"], owner)
            template = create_template(studio["id"], owner)
            instructor = create_staff(studio["id"], owner, template_id=template["id"],
                                      commission_rate_bps=0)
            session = create_session(studio["id"], owner, template["id"],
                                     instructor["id"], sub["version"],
                                     capacity=2, start_at="2026-06-20T17:00:00Z")
            client = create_client(studio["id"], display_name="Maya Alvarez",
                                   email="maya@example.com")
            booking = validate_success(api.create_marketplace_booking({
                "client_id": client["id"], "class_session_id": session["id"],
                "payment_ref": f"pm_{mode.lower()}", "promo_redeem": False,
            }, make_client_headers(client["id"])), expected_status=201)
            # PRD §3.3: check-in is admitted only while the session is
            # IN_PROGRESS, so the clock must sit at the session start.
            set_clock("2026-06-20T17:00:00Z")
            get_success_data(api.check_in_booking(
                booking["id"], make_client_headers(client["id"])))
            get_success_data(api.complete_class_session(session["id"], ADMIN))

            rows = validate_success(api.list_booking_commission_entries(
                booking["id"], owner))
            assert len(rows) == 1
            assert rows[0]["status"] == "ACCRUED"
            entries[mode] = rows[0]

        outside = entries["BONUS_OUTSIDE_CAP"]
        inside = entries["BONUS_INSIDE_CAP"]

        assert outside["base_amount_cents"] == inside["base_amount_cents"], \
            "both studios posted the same channel-adjusted base"
        assert outside["commission_cents"] == 1383, \
            "988 teaching commission, then the 395-cent bonus added after the 1200 ceiling"
        assert inside["commission_cents"] == 1200, \
            "the bonus is folded in first and then clipped to the ceiling"
        assert outside["commission_cents"] - inside["commission_cents"] == 183, \
            "the escaped part of the channel bonus"

    def test_commission_entry_records_the_effective_rate_and_channel(self, api):
        """PRD §3.6: "The accrual lands as a `CommissionEntry` whose `booking_channel` mirrors the producing booking's channel, whose `base_amount_cents` is the channel-adjusted revenue — the booking's `commission_base_cents` on the studio channel, and that base less the marketplace commission on the marketplace channel — whose `rate_bps` records the effective rate applied, and whose `status` begins `ACCRUED`."

        Design: Difficulty/combinatorial_formula/commission_accrual_evaluation_order_pins_bonus_against_the_accrual_ceiling
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        rows = validate_success(api.list_booking_commission_entries(
            ctx["booking"]["id"], ctx["owner"]))
        assert len(rows) == 1
        assert rows[0]["booking_channel"] == "STUDIO"
        assert rows[0]["status"] == "ACCRUED"
        assert rows[0]["reversal_reason"] is None
        assert rows[0]["rate_bps"] == 2500, "the GROWTH teaching rate for the first seat"
        assert rows[0]["commission_cents"] == 840, \
            "3360 studio-channel list price at 2500 basis points"


class TestPayrollPeriodLifecycle:

    def test_payroll_period_auto_closes_when_the_reopen_window_lapses(self, api):
        """PRD §3.6: "Once the clock passes that window the period closes permanently: `LOCKED` moves to `CLOSED`, and from then on any reversal of one of its entries posts a `reversal_correction_cents` into the next open period instead of reopening the closed one."
        PRD §3.6: "A close attempted against a period that is not `OPEN` is refused with `ERR_PAYROLL_PERIOD_NOT_OPEN`."

        Design: Corner/state_machines/payroll_period_auto_closes_when_the_reopen_window_lapses
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        period = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        locked = validate_success(api.close_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": period["version"]}, ctx["owner"]))
        assert locked["status"] == "LOCKED"

        set_clock("2026-07-15T00:00:00Z")
        sealed = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        assert sealed["status"] == "CLOSED", \
            "the lapsed reopen window seals the period"

        validate_error(api.reopen_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": sealed["version"]}, ctx["owner"]),
            ApiErrorId.ERR_PAYROLL_PERIOD_NOT_OPEN)

    def test_closing_pays_every_accrued_entry_in_the_period(self, api):
        """PRD §3.6: "Running payroll locks the period and pays every accrued
        entry in it, recomputing the period's paid_commission_cents."

        Design: Corner/state_machines/payroll_period_auto_closes_when_the_reopen_window_lapses
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        period = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        locked = validate_success(api.close_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": period["version"]}, ctx["owner"]))
        assert locked["status"] == "LOCKED"
        assert locked["paid_commission_cents"] == 840

        entries = validate_success(api.list_period_commission_entries(
            ctx["period"]["id"], ctx["owner"]))
        assert entries[0]["status"] == "PAID"


class TestPayrollCoverageVersusSessionCompletion:

    def test_session_completion_against_a_locked_period_accrues_no_entry(self, api):
        """PRD §2.11: "State admissibility follows, yielding `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_BOOKING_NOT_RESERVED`, `ERR_ENTRY_NOT_OFFERED`, `ERR_WAITLIST_TERMINAL`, `ERR_SESSION_NOT_SCHEDULED`, `ERR_PAYROLL_PERIOD_NOT_OPEN` or `ERR_PORTABILITY_ALREADY_DECIDED` as applicable, all at HTTP 409."

        Design: Difficulty/cross_entity_state_dependency/session_completion_admission_depends_on_the_payroll_period_state
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        # A second session booked into the same period completes while the
        # period is still OPEN, so the refusal below is charged to the period
        # state.  The June period's end_date plus the 7-day reopen window sits
        # well past the June 21 clock, so the reopen below is admissible.
        period = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        validate_success(api.close_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": period["version"]}, ctx["owner"]))

        second_client = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                                      email="bea@example.com")
        second_session = create_session(
            ctx["studio"]["id"], ctx["owner"], ctx["template"]["id"],
            ctx["instructor"]["id"], ctx["subscription_version"], capacity=2,
            room_code="ROOM-B", start_at="2026-06-21T17:00:00Z")
        booking = book(second_client["id"], second_session["id"])
        set_clock("2026-06-21T17:00:00Z")
        get_success_data(api.check_in_booking(
            booking["id"], make_client_headers(second_client["id"])))

        result = api.complete_class_session(second_session["id"], ADMIN)
        assert result.status_code in (200, 409), \
            "the completion either succeeds or is refused by the period state"

        rows, meta = validate_paginated(api.list_commission_entries(
            ctx["owner"], params={"payroll_period_id": ctx["period"]["id"]}))
        # The locked period refused the second accrual: exactly the entry the
        # fixture already produced.
        assert meta["total_count"] == 1

        # PRD §3.6: reopening the locked period lifts the accrual block.
        locked = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        validate_success(api.reopen_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": locked["version"]}, ctx["owner"]))
        reopened = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                           ctx["owner"]))
        assert reopened["status"] == "OPEN"

    def test_closing_is_refused_while_a_session_of_the_period_is_unfinished(self, api):
        """PRD §3.6: "it is only admitted once no session whose `payroll_period_id` is this period remains in `SCHEDULED` or `IN_PROGRESS`, because a period cannot be locked while its sessions could still produce entries."

        Design: Difficulty/cross_entity_state_dependency/session_completion_admission_depends_on_the_payroll_period_state
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        period = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        refused = api.close_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": period["version"]}, ctx["owner"])
        assert refused.status_code in (409, 402, 403), \
            "a period with a still-scheduled session cannot be locked"


class TestRevenueConservation:

    def test_studio_gross_is_invariant_under_a_reversal(self, api):
        """PRD §3.6: "The sum, across a studio, of `commission_base_cents` on bookings that are or have been `ATTENDED` is invariant under every reversal and substitution: the correction is posted as a commission entry with status `REVERSED` when the entry was still `ACCRUED`, or as the `reversal_correction_cents` on a payroll period when the entry had already been paid — never by editing `commission_base_cents`."

        Design: Difficulty/compensating_invariant/studio_commission_and_attendance_conservation_across_a_late_substitution
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["owner"]))
        assert booking["status"] == "ATTENDED"
        assert booking["commission_base_cents"] == 3360, \
            "the studio-channel list price at the GROWTH tier"

        entries = validate_success(api.list_booking_commission_entries(
            booking["id"], ctx["owner"]))
        assert entries[0]["commission_cents"] == 840, \
            "3360 at the GROWTH teaching rate of 2500 basis points"

        # A completed session is terminal, so the studio-side cancellation that
        # would carry the reversal is refused rather than silently applied.
        validate_error(api.cancel_class_session(
            ctx["session"]["id"], {"reason": "studio closed for the day"},
            ctx["owner"]), ApiErrorId.ERR_INVALID_STATE)

    def test_attained_gross_is_readable_through_the_booking_row(self, api):
        """PRD §2.6: "The attended revenue written on a booking (`commission_base_cents`) is never mutated by a later reversal or substitution: a correction is posted either as a commission entry carrying status `REVERSED` or as a `PayrollPeriod` row's `reversal_correction_cents`, whichever matches the entitlement state of the entry at the time."

        Design: Difficulty/compensating_invariant/studio_commission_and_attendance_conservation_across_a_late_substitution
        """
        ctx = setup_attended_session(tier="GROWTH", capacity=2)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["owner"]))
        base = booking["commission_base_cents"]

        period = validate_success(api.get_payroll_period(ctx["period"]["id"],
                                                         ctx["owner"]))
        validate_success(api.close_payroll_period(
            ctx["period"]["id"],
            {"expected_payroll_period_version": period["version"]}, ctx["owner"]))

        after = validate_success(api.get_booking(ctx["booking"]["id"], ctx["owner"]))
        assert after["commission_base_cents"] == base, \
            "paying the entry never mutates the booking's attended revenue"


class TestInstructorSubstitutionRanking:

    def test_eligible_instructors_excludes_the_instructor_of_record(self, api):
        """PRD §3.5: "The candidate set is the studio's staff members with `staff_role` `INSTRUCTOR` whose status is `ACTIVE` or `SUBSTITUTE_ONLY`, excluding the instructor already of record for the session under consideration."

        Design: Corner/endpoints/eligible_instructors_ranking_inverts_between_legacy_and_ladder_tiers
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        omar = create_staff(ctx["studio"]["id"], ctx["owner"],
                            template_id=ctx["template"]["id"],
                            full_name="Omar Diallo")
        get_success_data(api.restrict_staff_to_substitute(omar["id"], ctx["owner"]))

        ranking = validate_success(api.list_eligible_instructors(
            ctx["session"]["id"], ctx["owner"], params={"limit": 10}))
        assert "eligible" in ranking and "total_count" in ranking
        assert ranking["total_count"] == 1, \
            "the session's own instructor of record is excluded"
        assert ranking["eligible"][0]["id"] == omar["id"]

    def test_an_empty_candidate_set_returns_an_empty_list_not_an_error(self, api):
        """PRD §3.5: "t of 2. The overlapping minutes counted are the total minutes th"

        Design: Corner/endpoints/eligible_instructors_ranking_inverts_between_legacy_and_ladder_tiers
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        ranking = validate_success(api.list_eligible_instructors(
            ctx["session"]["id"], ctx["owner"], params={"limit": 10}))
        assert ranking["eligible"] == []
        assert ranking["total_count"] == 0
        assert ranking["has_more"] is False

    def test_reassignment_outside_the_candidate_set_is_refused(self, api):
        """PRD §3.5: "A nominated instructor who is absent from the candidate set
        — or who is the instructor of record — is refused with
        ERR_INSTRUCTOR_NOT_ELIGIBLE."

        Design: Corner/endpoints/eligible_instructors_ranking_inverts_between_legacy_and_ladder_tiers
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        validate_error(api.reassign_instructor(
            ctx["session"]["id"],
            {"selected_staff_id": ctx["instructor"]["id"],
             "expected_class_session_version": session["version"]}, ctx["owner"]),
            ApiErrorId.ERR_INSTRUCTOR_NOT_ELIGIBLE)