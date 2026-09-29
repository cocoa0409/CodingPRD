"""Lifecycle state machines: initial states, terminal states, the bounded
revision loop, the cascades a service or a decision fires, and the sweeps.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_assessment_split_resums,
    assert_docket_released,
    assert_same_instant,
)
from test_helpers.test_users import (
    LICENSING_ANALYST,
    make_dealer_headers,
    make_manufacturer_headers,
)


class TestApplicationRevisionLoop:
    def test_a_fresh_application_sits_in_draft_with_nothing_scanned(self, api):
        """PRD 3.2: "A freshly created application sits at `DRAFT` with
        `deficiency_codes` empty, `deficiency_count` at 0, `resubmission_count` at
        0, and `submitted_at`, `decided_at`, `decision_outcome`,
        `fee_quoted_cents`, `fee_total_cents`, `fee_delta_cents` and
        `deficiency_note` all unset." PRD 3.2 also withholds the scan: "Every
        comparison is an integer comparison, and an application still in `DRAFT` is
        never scanned."

        Design: Corner/state_machines/license_application_created_starts_in_draft
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")

        application = get_success_data(api.create_license_application(
            f.license_application_payload(dealer["id"], facility_sqft=5000),
            make_dealer_headers(dealer["id"])), 201)

        assert application["status"] == "DRAFT"
        assert application["deficiency_count"] == 0
        assert application["deficiency_codes"] == []
        assert application["resubmission_count"] == 0
        assert application["fee_quoted_cents"] is None
        assert application["fee_total_cents"] is None
        assert application["fee_delta_cents"] is None
        assert application["submitted_at"] is None
        assert application["decided_at"] is None
        assert application["decision_outcome"] is None
        assert application["deficiency_note"] is None
        assert fx.read_dealer(dealer["id"])["license_status"] == "PROSPECTIVE"

    def test_submitting_a_submitted_application_neither_reprices_nor_rescans(self, api):
        """PRD 3.2: "**Submitting** a draft moves the application `DRAFT →
        SUBMITTED` and is the dealership's own act; it is refused with
        `ERR_INVALID_APPLICATION_STATE` unless the application is in `DRAFT`, and a
        dealership whose `license_status` is `REVOKED` or `CANCELLED` may not
        submit at all." The first submission froze the quote at 120000 + 25000 -
        4000 = 141000, and the refused replay may not touch it.

        Design: Corner/state_machines/application_submit_twice_rejected_as_invalid_state
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        application = fx.open_application(dealer["id"])
        submitted = fx.submit_application(application["id"], dealer["id"])
        assert submitted["fee_quoted_cents"] == 141000

        response = api.submit_license_application(
            application["id"], make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
                       expected_status=409)

        after = fx.read_application(application["id"])
        assert after["status"] == "SUBMITTED"
        assert after["fee_quoted_cents"] == 141000
        assert after["resubmission_count"] == 0
        assert_same_instant(after["submitted_at"], submitted["submitted_at"])

    def test_a_deficiency_notice_needs_a_submitted_application(self, api):
        """PRD 3.2: "The analyst may only do this from `SUBMITTED` and only when
        `deficiency_count` is at least 1; a `BoardAdmin` may not issue deficiency
        notices at all." A draft has never been scanned, so the notice cannot
        arrive first.

        Design: Corner/state_machines/deficiency_notice_on_draft_application_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        application = fx.open_application(dealer["id"], facility_sqft=5000)

        response = api_client.issue_deficiency_notice(
            application["id"],
            f.deficiency_notice_payload(deficiency_note="Facility photographs missing."),
            LICENSING_ANALYST)
        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
                       expected_status=409)

        after = fx.read_application(application["id"])
        assert after["status"] == "DRAFT"
        assert after["deficiency_note"] is None
        assert after["deficiency_count"] == 0

    def test_the_revision_loop_stops_after_the_second_resubmission(self, api):
        """PRD 3.2: "The revision loop is bounded at two resubmissions: a third
        attempt, made when `resubmission_count` already stands at 2, is refused
        with `ERR_RESUBMISSION_LIMIT_REACHED`." PRD 3.2 fixes what each pass
        recomputes: "then increments `resubmission_count` by 1, re-stamps
        `submitted_at` from the clock, and re-runs both the sufficiency scan and
        the quoted-fee evaluation at the new clock position." A facility below
        8,000 square feet earns no credit, so every pass quotes 145000.

        Design: Corner/state_machines/application_deficiency_resubmit_cycle_capped_at_two
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        application = fx.open_application(dealer["id"], facility_sqft=5000)

        submitted = fx.submit_application(application["id"], dealer["id"])
        assert submitted["deficiency_codes"] == ["FACILITY_TOO_SMALL"]
        assert submitted["deficiency_count"] == 1
        assert submitted["fee_quoted_cents"] == 145000

        for pass_number, sqft in enumerate((6000, 7000), start=1):
            fx.return_application_as_deficient(application["id"])
            assert fx.read_application(application["id"])["status"] == "DEFICIENT"
            resubmitted = fx.resubmit_application(
                application["id"], dealer["id"], facility_sqft=sqft)
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["resubmission_count"] == pass_number
            assert resubmitted["deficiency_codes"] == ["FACILITY_TOO_SMALL"]
            assert resubmitted["fee_quoted_cents"] == 145000

        fx.return_application_as_deficient(application["id"])
        response = api_client.resubmit_license_application(
            application["id"], {"facility_sqft": 9000},
            make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value,
                       expected_status=409)

        after = fx.read_application(application["id"])
        assert after["status"] == "DEFICIENT"
        assert after["facility_sqft"] == 7000
        assert after["resubmission_count"] == 2
        assert fx.read_dealer(dealer["id"])["license_status"] == "PROSPECTIVE"


class TestTerminalStatesAdmitNoSecondAct:
    def test_a_denied_salesperson_cannot_be_approved_afterwards(self, api):
        """PRD 3.3: "A denial from `PENDING` moves it `PENDING → DENIED`, stamps no
        term dates at all, and is terminal." PRD 3.3: "The same act serves both the
        initial grant and the completion of a renewal, so it is admitted only from
        `PENDING` or `RENEWAL_PENDING`; anywhere else it is refused with
        `ERR_INVALID_SALESPERSON_STATE`."

        Design: Corner/state_machines/salesperson_denied_is_terminal_second_decision_rejected
        """
        ctx = fx.setup_licensed_dealer()
        fx.set_clock("2026-09-02T00:00:00Z")
        applicant = fx.sponsor_salesperson(ctx["dealer"]["id"], full_name="Dana Reyes")
        denied = fx.decide_salesperson(
            applicant["id"], "DENIED",
            denial_reason_code="INCOMPLETE_BACKGROUND_DISCLOSURE")
        assert denied["license_status"] == "DENIED"

        response = api.decide_salesperson_license(
            applicant["id"], f.salesperson_decision_payload("APPROVED"),
            LICENSING_ANALYST)
        validate_error(response, ApiErrorId.ERR_INVALID_SALESPERSON_STATE.value,
                       expected_status=409)

        after = fx.read_salesperson(applicant["id"])
        assert after["license_status"] == "DENIED"
        assert after["denial_reason_code"] == "INCOMPLETE_BACKGROUND_DISCLOSURE"
        assert after["license_effective_on"] is None
        assert after["license_expires_on"] is None
        assert after["discipline_status"] == "CLEAR"
        assert fx.read_dealer(ctx["dealer"]["id"])["licensed_salesperson_count"] == 0

    def test_an_effective_filing_can_no_longer_be_amended(self, api):
        """PRD 3.4: "`EFFECTIVE` and `BARRED` are the filing's terminal states."
        PRD 3.4: "An amendment is admitted from `NOTICE_SERVED`, where it returns
        the filing to `NOTICE_SERVED`, and from `PROTEST_PENDING`, where it also
        returns the filing to `NOTICE_SERVED`." An unprotested notice served
        2026-09-01 for 2026-11-30 gives 90 days' notice and a window closing
        2026-10-01, so the filing takes effect on the proposed date and then stands
        outside the amendment loop for good.

        Design: Corner/state_machines/effective_filing_is_terminal_amend_rejected
        """
        ctx = fx.setup_served_additional_point_notice(
            notice_clock=None, proposed_effective_on="2026-11-30")
        filing = ctx["filing"]
        assert filing["notice_served_on"] == "2026-09-01"
        assert filing["notice_days_provided"] == 90
        assert filing["protest_window_ends_on"] == "2026-10-01"

        fx.set_clock("2026-11-30T00:00:00Z")
        effective = fx.finalize_filing(filing["id"])
        assert effective["status"] == "EFFECTIVE"
        assert effective["amendment_count"] == 0

        fx.set_clock("2026-12-01T00:00:00Z")
        response = api.amend_franchise_filing(
            filing["id"], f.amendment_payload("2027-02-01"),
            make_manufacturer_headers(ctx["manufacturer"]["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_FILING_STATE.value,
                       expected_status=409)

        after = fx.read_filing(filing["id"])
        assert after["status"] == "EFFECTIVE"
        assert after["amendment_count"] == 0
        assert after["proposed_effective_on"] == "2026-11-30"
        assert fx.read_manufacturer(ctx["manufacturer"]["id"])["active_filing_count"] == 0


class TestTerminationNoticeTouchesOneDimension:
    def test_service_moves_the_franchise_dimension_and_leaves_the_licence(self, api):
        """PRD 3.4: "On a `TERMINATION`, service also moves the affected
        dealership's franchise dimension `FRANCHISED → TERMINATION_PENDING` and
        increments that dealership's `version`; the licence dimension is
        deliberately left alone, because the dealership keeps selling throughout the
        notice period." PRD 3.4: "Service stamps `notice_served_on` with the clock
        date, records `notice_days_provided` as the whole days from
        `notice_served_on` to `proposed_effective_on`, and sets
        `protest_window_ends_on` to 30 days after `notice_served_on` — the last day,
        inclusive, on which an incumbent may protest." From 2026-09-01 to
        2026-12-01 is 91 whole days, clear of the 60-day floor for a termination.

        Design: Corner/state_machines/termination_notice_moves_dealer_franchise_dimension_only
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        before = fx.read_dealer(dealer["id"])
        assert before["franchise_status"] == "FRANCHISED"
        filing = fx.open_termination_filing(
            manufacturer["id"], dealer["id"], "2026-12-01")
        assert filing["status"] == "DRAFT"

        served = get_success_data(api.serve_filing_notice(
            filing["id"], make_manufacturer_headers(manufacturer["id"])))

        assert served["status"] == "NOTICE_SERVED"
        assert served["notice_served_on"] == "2026-09-01"
        assert served["notice_days_provided"] == 91
        assert served["protest_window_ends_on"] == "2026-10-01"

        after = fx.read_dealer(dealer["id"])
        assert after["franchise_status"] == "TERMINATION_PENDING"
        assert after["license_status"] == "LICENSED"
        assert after["version"] > before["version"]
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 1


_PROBATIVE_PROTESTANT_STUDY = {
    "total_market_registrations": 40000,
    "line_make_registrations": 3200,
    "statewide_line_make_share_pct": 12.50,
    "permanency_investment_cents": 250000000,
    "consumer_access_drive_minutes": 22,
    "market_growth_pct": 8.00,
}


def _scheduled_additional_point_protest():
    """An ADDITIONAL_POINT notice served 2026-09-01 for 2026-11-30, protested
    2026-09-15 with one probative protestant study, hearing docketed
    2026-11-02T10:00:00Z-13:00:00Z in a fresh room.

    The study reports an 8.00 percent actual share against a 12.50 statewide
    expectation, so its shortfall is 4.50 points.
    """
    ctx = fx.setup_served_additional_point_notice(
        notice_clock=None, proposed_effective_on="2026-11-30")
    fx.set_clock("2026-09-15T00:00:00Z")
    ctx["protest"] = fx.file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"],
        grounds_code="MARKET_ENCROACHMENT")
    ctx["protestant_study"] = fx.tender_protestant_study(
        ctx["protest"]["id"], ctx["dealer"]["id"], **_PROBATIVE_PROTESTANT_STUDY)
    ctx["room"] = fx.create_hearing_room()
    ctx["protest"] = fx.schedule_hearing(
        ctx["protest"]["id"], ctx["room"]["id"], ctx["room"]["version"],
        "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")
    ctx["room"] = fx.read_room(ctx["room"]["id"])
    return ctx


class TestConveneForksOnProtestantStanding:
    def test_a_delinquency_suspended_protestant_loses_the_hearing_and_the_room(self, api):
        """PRD 3.6: "Where the protestant has instead lost standing — its
        `license_status` is `SUSPENDED`, `EXPIRED`, `REVOKED` or `CANCELLED` — the
        protest moves `SCHEDULED → DISMISSED` and gives up the room." PRD 3.6: "No
        `good_cause_score` is computed on this branch and no cost assessment is
        ever levied. And where the dismissed protest was the last one still live
        against its filing, the filing moves `PROTEST_PENDING → PROTEST_RESOLVED`
        in the same request." The protestant is put out of standing by the fiscal
        route rather than by points: PRD 3.9: "The inequality is strict: a payment
        deadline falling exactly on the new clock date is not yet delinquent."

        Design: Corner/state_machines/convene_dismisses_protest_when_protestant_suspended
        """
        ctx = _scheduled_additional_point_protest()
        assert ctx["room"]["booked_hearing_count"] == 1
        assert_same_instant(ctx["protest"]["evidence_deadline_at"],
                            "2026-10-26T10:00:00Z")

        complaint = fx.sanction_complaint(
            ctx["dealer"]["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            findings_code="MISLEADING_PRICE_ADVERTISING")
        assert complaint["restitution_due_on"] == "2026-10-15"

        swept = fx.set_clock("2026-11-02T10:00:00Z")
        assert swept["swept_dealer_count"] == 1
        suspended = fx.read_dealer(ctx["dealer"]["id"])
        assert suspended["license_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "RESTITUTION_DELINQUENT"
        assert suspended["disciplinary_points"] == 6

        dismissed = fx.convene_hearing(ctx["protest"]["id"])

        assert dismissed["status"] == "DISMISSED"
        assert_docket_released(dismissed)
        assert dismissed["good_cause_score"] is None
        assert dismissed["assessment_total_cents"] is None
        assert dismissed["protestant_share_cents"] is None
        assert dismissed["manufacturer_share_cents"] is None

        assert fx.read_room(ctx["room"]["id"])["booked_hearing_count"] == 0
        filing = fx.read_filing(ctx["filing"]["id"])
        assert filing["status"] == "PROTEST_RESOLVED"
        assert filing["active_protest_count"] == 0


class TestDeniedProtestHardensOnlyAfterThirtyDays:
    def test_the_thirtieth_day_leaves_the_denial_appealable(self, api):
        """PRD 3.7: "If nobody appeals, the disposition hardens by itself. On a
        clock advance, any protest standing in `SUSTAINED` or `DENIED` whose
        `decided_on` is more than 30 days behind the new clock date moves to
        `FINAL`: the appeal window has lapsed and the disposition is unappealable,
        and where the protest was denied the filing may now be finalised." PRD 3.7
        fixes the score the denial rests on: "The **access component** is neutral at
        exactly 50.00 whenever the franchisor has no controlling study." A net
        shortfall of 4.50 gives 36.00 inadequacy, 100.00 investment, 50.00 access
        and 40.00 growth, weighting to 55.40 against the 60.00 threshold an
        additional point carries.

        Design: Corner/state_machines/denied_protest_reaches_final_only_after_appeal_window_lapses
        """
        ctx = _scheduled_additional_point_protest()
        fx.set_clock("2026-11-02T10:00:00Z")
        heard = fx.convene_hearing(ctx["protest"]["id"])
        assert heard["status"] == "HEARD"
        assert heard["good_cause_score"] == 55.40
        assert heard["good_cause_threshold"] == 60.00

        denied = fx.decide_protest(
            ctx["protest"]["id"], "DENIED",
            findings_note="Penetration shortfall does not establish good cause.")
        assert denied["status"] == "DENIED"
        assert denied["decided_on"] == "2026-11-02"
        assert denied["assessment_total_cents"] == 45000
        assert denied["protestant_share_cents"] == 31500
        assert denied["manufacturer_share_cents"] == 13500
        assert_assessment_split_resums(denied)

        edge = fx.set_clock("2026-12-02T00:00:00Z")
        assert edge["swept_protest_count"] == 0
        assert fx.read_protest(ctx["protest"]["id"])["status"] == "DENIED"

    def test_the_thirty_first_day_makes_the_denial_final(self, api):
        """PRD 3.7: "On a clock advance, any protest standing in `SUSTAINED` or
        `DENIED` whose `decided_on` is more than 30 days behind the new clock date
        moves to `FINAL`: the appeal window has lapsed and the disposition is
        unappealable, and where the protest was denied the filing may now be
        finalised." PRD 2.5 counts the move: "makes a decided protest unappealable
        once the new clock date is later than 30 days after the decision date."

        Design: Corner/state_machines/denied_protest_reaches_final_only_after_appeal_window_lapses
        """
        ctx = _scheduled_additional_point_protest()
        fx.set_clock("2026-11-02T10:00:00Z")
        fx.convene_hearing(ctx["protest"]["id"])
        fx.decide_protest(
            ctx["protest"]["id"], "DENIED",
            findings_note="Penetration shortfall does not establish good cause.")
        fx.set_clock("2026-12-02T00:00:00Z")

        swept = fx.set_clock("2026-12-03T00:00:00Z")

        assert swept["swept_protest_count"] == 1
        final = fx.read_protest(ctx["protest"]["id"])
        assert final["status"] == "FINAL"
        assert final["appeal_filed_on"] is None
        assert final["court_docket_number"] is None
        assert fx.read_filing(ctx["filing"]["id"])["status"] == "PROTEST_RESOLVED"


class TestSustainedProtestBarsTheFiling:
    def test_sustaining_the_only_protest_bars_the_filing_and_restores_the_franchise(self, api):
        """PRD 3.7: "A sustained protest bars the filing. Where the sustained
        protest is the only protest against that filing not already in `WITHDRAWN`
        or `DISMISSED`, the filing moves `PROTEST_PENDING → BARRED` and may never be
        finalised, and the franchisor's `active_filing_count` is recomputed." PRD
        3.7: "Where the barred filing was a `TERMINATION`, the affected
        dealership's franchise dimension is restored `TERMINATION_PENDING →
        FRANCHISED`, because a filing that may never take effect cannot terminate
        anybody, and that dealership's `version` increments by 1." PRD 3.7 splits
        the bill: "Where the protest is sustained the franchisor has lost, so
        `protestant_share_cents` is the rounded prevailing share and
        `manufacturer_share_cents` is the remainder."

        Design: Corner/state_machines/sustained_termination_protest_bars_filing_and_restores_franchise
        """
        ctx = fx.setup_served_termination_notice()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        fx.set_clock("2026-09-15T00:00:00Z")
        protest = fx.file_protest(
            ctx["filing"]["id"], dealer["id"], ctx["filing"]["version"])
        fx.tender_protestant_study(
            protest["id"], dealer["id"], **_PROBATIVE_PROTESTANT_STUDY)
        get_success_data(api.create_market_study(
            protest["id"],
            f.comparable_study_payload(
                "MANUFACTURER", total_market_registrations=40000,
                line_make_registrations=3200,
                comparable_market_shares_pct=[9.00, 10.00, 11.00],
                permanency_investment_cents=0,
                consumer_access_drive_minutes=12, market_growth_pct=8.00),
            make_manufacturer_headers(manufacturer["id"])), 201)

        room = fx.create_hearing_room()
        fx.schedule_hearing(protest["id"], room["id"], room["version"],
                            "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")
        fx.set_clock("2026-11-02T10:00:00Z")
        heard = fx.convene_hearing(protest["id"])
        assert heard["status"] == "HEARD"
        assert heard["good_cause_threshold"] == 40.00
        assert heard["good_cause_score"] == 41.00
        assert heard["distance_to_site_km"] is None

        sustained = fx.decide_protest(
            protest["id"], "SUSTAINED",
            findings_note="Franchisor failed to establish good cause.")

        assert sustained["status"] == "SUSTAINED"
        assert sustained["decided_on"] == "2026-11-02"
        assert sustained["assessment_total_cents"] == 45000
        assert sustained["protestant_share_cents"] == 13500
        assert sustained["manufacturer_share_cents"] == 31500
        assert_assessment_split_resums(sustained)

        filing = fx.read_filing(ctx["filing"]["id"])
        assert filing["status"] == "BARRED"
        # PRD 3.5 defines the counter as "the number of protests against the
        # filing standing in `FILED`, `SCHEDULED`, `HEARD` or `SUSTAINED`", so
        # the sustained protest keeps counting; only the denied branch of PRD 3.7
        # recomputes it to 0.
        assert filing["active_protest_count"] == 1
        after = fx.read_dealer(dealer["id"])
        assert after["franchise_status"] == "FRANCHISED"
        assert after["license_status"] == "LICENSED"
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 0


class TestSweepDrivenDimensionMovements:
    def test_a_lapsing_sponsor_suspends_its_freshly_renewed_salesperson(self, api):
        """PRD 3.3: "Whenever a sponsoring dealership leaves `LICENSED` — by
        disciplinary suspension, by restitution-delinquency suspension, by
        revocation, by licence expiry or by franchise cancellation — each of its
        salespersons in `LICENSED` or `RENEWAL_PENDING` moves to
        `SUSPENDED_BY_SPONSOR` and the dealership's `licensed_salesperson_count` is
        decremented accordingly." The salesperson's own term outlives the sponsor's
        by a day, and PRD 3.3 makes expiry turn on that own date: "Independently,
        the clock sweep moves a salesperson from `LICENSED` to `EXPIRED` whenever
        its own `license_expires_on` falls earlier than the new clock date". PRD
        3.3: "sets `license_effective_on` to the day after the previous
        `license_expires_on` so consecutive terms abut exactly, sets the new
        `license_expires_on` to 364 days after that, and increments both
        `renewal_count` and the sponsoring dealership's
        `licensed_salesperson_count`."

        Design: Corner/state_machines/dealer_expiry_sweep_suspends_renewed_salesperson
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        assert fx.read_dealer(dealer["id"])["license_expires_on"] == "2028-08-30"

        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")
        assert salesperson["license_expires_on"] == "2027-09-01"

        fx.set_clock("2027-08-15T00:00:00Z")
        pending = fx.request_salesperson_renewal(salesperson["id"], dealer["id"])
        assert pending["license_status"] == "RENEWAL_PENDING"
        renewed = fx.decide_salesperson(salesperson["id"], "APPROVED")
        assert renewed["license_effective_on"] == "2027-09-02"
        assert renewed["license_expires_on"] == "2028-08-31"
        assert renewed["renewal_count"] == 1
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 1

        swept = fx.set_clock("2028-08-31T00:00:00Z")

        assert swept["swept_dealer_count"] == 1
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["license_status"] == "EXPIRED"
        assert after_dealer["franchise_status"] == "FRANCHISED"
        assert after_dealer["licensed_salesperson_count"] == 0
        after_salesperson = fx.read_salesperson(salesperson["id"])
        assert after_salesperson["license_status"] == "SUSPENDED_BY_SPONSOR"
        assert after_salesperson["license_expires_on"] == "2028-08-31"
        assert after_salesperson["discipline_status"] == "CLEAR"

    def test_points_aging_out_reinstate_the_discipline_dimension_alone(self, api):
        """PRD 3.3: "The lower bound is inclusive: a sanction dated exactly 730 days
        back still counts, one dated 731 days back does not." PRD 3.3: "Rollback
        happens only on the clock sweep, as points age out: once the recomputed
        total falls below 9 a salesperson in `SUSPENDED_DISCIPLINARY` moves to
        `REINSTATED`, and once it falls below 6 a salesperson on `PROBATION`
        returns to `CLEAR`. Again `license_status` is untouched in both cases." A
        sanction dated 2026-09-05 is exactly 730 days behind 2028-09-04 and 731
        days behind 2028-09-05, so the roll-off lands between the two sweeps while
        the licence dimension keeps its own counsel.

        Design: Corner/state_machines/salesperson_discipline_reinstated_when_points_age_out
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")

        fx.set_clock("2026-09-05T00:00:00Z")
        complaint = fx.sanction_complaint(
            dealer["id"], "SUSPENSION_RECOMMENDED", 100000,
            "ODOMETER_MISREPRESENTATION", salesperson_id=salesperson["id"])
        assert complaint["points_assessed"] == 9
        assert complaint["civil_penalty_cents"] == 205000
        assert complaint["restitution_ordered_cents"] == 100000
        assert complaint["restitution_due_on"] == "2026-10-05"
        disciplined = fx.read_salesperson(salesperson["id"])
        assert disciplined["disciplinary_points"] == 9
        assert disciplined["discipline_status"] == "SUSPENDED_DISCIPLINARY"
        assert disciplined["license_status"] == "LICENSED"

        # PRD 3.9: "A complaint's sanction date is the date part of its
        # `resolved_at` where it has one", and settling the ledger "stamps
        # `resolved_at` with the clock instant" -- so the payment is made later
        # the same day to keep the sanction date on 2026-09-05.
        fx.set_clock("2026-09-05T12:00:00Z")
        settled = fx.pay_restitution(complaint["id"], dealer["id"], 100000)
        assert settled["status"] == "CLOSED_SATISFIED"
        assert fx.read_dealer(dealer["id"])["restitution_outstanding_cents"] == 0
        assert fx.read_dealer(dealer["id"])["license_status"] == "LICENSED"

        fx.set_clock("2028-09-04T00:00:00Z")
        still_counted = fx.read_salesperson(salesperson["id"])
        assert still_counted["disciplinary_points"] == 9
        assert still_counted["discipline_status"] == "SUSPENDED_DISCIPLINARY"

        fx.set_clock("2028-09-05T00:00:00Z")

        aged_out = fx.read_salesperson(salesperson["id"])
        assert aged_out["disciplinary_points"] == 0
        assert aged_out["discipline_status"] == "REINSTATED"
        assert aged_out["license_status"] == "EXPIRED"
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["disciplinary_points"] == 0
        assert after_dealer["licensed_salesperson_count"] == 0
