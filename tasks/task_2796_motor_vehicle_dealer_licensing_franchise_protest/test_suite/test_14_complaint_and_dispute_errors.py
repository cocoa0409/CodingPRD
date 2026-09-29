"""The error contract on the complaint file, the rate dispute and the salesperson
renewal: the resolution fork's three guards, sponsorship agreement, the dispute's
uniqueness and windows, the discipline bar and the dealer's renewal grace.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BOARD_ADMIN,
    COMPLAINT_INVESTIGATOR,
    make_dealer_headers,
    make_manufacturer_headers,
)


class TestResolutionForkGuards:
    def test_the_resolution_endpoint_refuses_three_different_ways(self, api):
        """PRD 3.9: "**Resolution** is an administrator's act, admitted only from
        `UNDER_INVESTIGATION` and only from an `X-User-ID` other than the stamped
        `investigator_user_id`." PRD 3.9: "`sanction_type` must be present exactly
        when `substantiated` is true and absent when it is false; either mismatch is
        refused with `ERR_SANCTION_TYPE_NOT_ALLOWED`." PRD 3.9: "A substantiated
        resolution additionally requires a `findings_code` other than
        `NO_VIOLATION_FOUND`, and an `alleged_loss_cents` strictly greater than zero
        so that the restitution ledger is never opened with a zero balance — a zero
        loss draws `ERR_LOSS_REQUIRED_FOR_SANCTION`." PRD 3.9 then leaves the
        unsubstantiated close bare: "`points_assessed` stays 0,
        `civil_penalty_cents`, `restitution_ordered_cents` and `restitution_due_on`
        all stay unset".

        Design: Corner/errors/complaint_resolution_state_loss_and_sanction_guards_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        complaint = fx.intake_complaint(
            dealer["id"], allegation_code="ADVERTISING_VIOLATION",
            alleged_loss_cents=0)
        assert complaint["status"] == "RECEIVED"

        too_early = api.resolve_consumer_complaint(
            complaint["id"], f.resolution_payload(substantiated=False), BOARD_ADMIN)
        validate_error(too_early, ApiErrorId.ERR_INVALID_COMPLAINT_STATE.value,
                       expected_status=409)

        investigating = fx.open_investigation(
            complaint["id"], findings_code="ADVERTISING_COPY_REVIEWED")
        assert investigating["status"] == "UNDER_INVESTIGATION"

        zero_loss = api.resolve_consumer_complaint(
            complaint["id"],
            f.resolution_payload(substantiated=True, sanction_type="WARNING"),
            BOARD_ADMIN)
        validate_error(zero_loss, ApiErrorId.ERR_LOSS_REQUIRED_FOR_SANCTION.value,
                       expected_status=422)

        stray_sanction = api.resolve_consumer_complaint(
            complaint["id"],
            {"substantiated": False, "sanction_type": "WARNING"}, BOARD_ADMIN)
        validate_error(stray_sanction,
                       ApiErrorId.ERR_SANCTION_TYPE_NOT_ALLOWED.value,
                       expected_status=422)

        closed = get_success_data(api.resolve_consumer_complaint(
            complaint["id"], f.resolution_payload(substantiated=False),
            BOARD_ADMIN), 200)

        assert closed["status"] == "CLOSED_UNSUBSTANTIATED"
        assert closed["points_assessed"] == 0
        assert closed["civil_penalty_cents"] is None
        assert closed["restitution_ordered_cents"] is None
        assert closed["restitution_due_on"] is None
        after = fx.read_dealer(dealer["id"])
        assert after["disciplinary_points"] == 0
        assert after["license_status"] == "PROSPECTIVE"


class TestSalespersonSponsorshipAgreement:
    def test_a_complaint_may_not_name_another_dealership_s_salesperson(self, api):
        """PRD 3.9: "A `salesperson_id` may be named where an individual is
        implicated, and is left unset for a dealership-only complaint; where one is
        named, that salesperson must be sponsored by the very dealership complained
        of, or the intake is refused with `ERR_SALESPERSON_DEALER_MISMATCH`." The
        same identifier is admitted against its own sponsor, and PRD 3.9 leaves the
        point total alone at intake: "A new complaint opens at `RECEIVED` with
        `points_assessed` at 0, `restitution_paid_cents` at 0 and
        `investigator_user_id`, `findings_code`, `substantiated`, `sanction_type`,
        `civil_penalty_cents`, `restitution_ordered_cents`, `restitution_due_on` and
        `resolved_at` all unset."

        Design: Corner/errors/complaint_naming_a_salesperson_of_another_dealer_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        fx.create_manufacturer()
        sponsor = fx.create_dealer(legal_name="Riverbend Aurora")
        fx.license_dealer(sponsor["id"])
        stranger = fx.create_dealer(legal_name="Lakeside Aurora",
                                    site_x_km=30, site_y_km=0)
        fx.license_dealer(stranger["id"])
        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(sponsor["id"], full_name="Kai Whitlock")

        refused = api.create_consumer_complaint(
            f.complaint_payload(stranger["id"],
                                allegation_code="UNLICENSED_SALESPERSON",
                                alleged_loss_cents=150000,
                                complainant_name="Tessa Lund",
                                salesperson_id=salesperson["id"]),
            COMPLAINT_INVESTIGATOR)
        validate_error(refused, ApiErrorId.ERR_SALESPERSON_DEALER_MISMATCH.value,
                       expected_status=422)
        _, meta = validate_paginated(api.list_consumer_complaints(
            BOARD_ADMIN, params={"dealer_id": stranger["id"]}))
        assert meta["total_count"] == 0

        admitted = get_success_data(api.create_consumer_complaint(
            f.complaint_payload(sponsor["id"],
                                allegation_code="UNLICENSED_SALESPERSON",
                                alleged_loss_cents=150000,
                                complainant_name="Tessa Lund",
                                salesperson_id=salesperson["id"]),
            COMPLAINT_INVESTIGATOR), 201)

        assert admitted["status"] == "RECEIVED"
        assert admitted["salesperson_id"] == salesperson["id"]
        assert admitted["points_assessed"] == 0
        assert fx.read_salesperson(salesperson["id"])["disciplinary_points"] == 0


class TestDisputeUniquenessWindowAndState:
    def test_the_dispute_refuses_a_twin_a_late_answer_and_a_post_decision_answer(self, api):
        """PRD 3.8 keys the pair: "that particular dealership-and-franchisor pair
        must not already have a dispute standing in `FILED` or `UNDER_REVIEW`
        (`ERR_OPEN_DISPUTE_EXISTS`)." PRD 3.8: "The franchisor must **answer** within
        30 days of `filed_on`, or the answer is refused with
        `ERR_RESPONSE_WINDOW_CLOSED`; the answer is admitted only from `FILED` and
        only from a `REGISTERED` franchisor, and moves the dispute `FILED →
        UNDER_REVIEW`." PRD 3.8: "A denial is admitted from either `FILED` or
        `UNDER_REVIEW`, records `denial_reason_code` and `decided_on`, and leaves the
        dealership's `approved_warranty_labor_rate_cents` exactly as it was." So the
        board may still deny a dispute nobody answered, after which the answer has
        nowhere to land.

        Design: Corner/errors/dispute_duplicate_response_window_and_state_guards_rejected
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        dispute = fx.file_rate_dispute(
            dealer["id"], manufacturer["id"],
            f.qualifying_lines(5, labor_charge_cents=7000, labor_hours=1.0))
        assert dispute["filed_on"] == "2026-09-01"
        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 1

        twin = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(
                dealer["id"], manufacturer["id"],
                f.qualifying_lines(5, labor_charge_cents=8000, labor_hours=1.0)),
            make_dealer_headers(dealer["id"]))
        validate_error(twin, ApiErrorId.ERR_OPEN_DISPUTE_EXISTS.value,
                       expected_status=409)
        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 1

        fx.set_clock("2026-10-02T00:00:00Z")
        late = api.respond_to_warranty_rate_dispute(
            dispute["id"], f.dispute_response_payload("ACCEPT"),
            make_manufacturer_headers(manufacturer["id"]))
        validate_error(late, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value,
                       expected_status=422)
        assert fx.read_dispute(dispute["id"])["status"] == "FILED"

        denied = get_success_data(api.decide_warranty_rate_dispute(
            dispute["id"],
            f.dispute_decision_payload(
                "DENIED", denial_reason_code="SAMPLE_NOT_REPRESENTATIVE"),
            BOARD_ADMIN), 200)
        assert denied["status"] == "DENIED"
        assert denied["decided_on"] == "2026-10-02"
        assert denied["approved_rate_cents"] is None
        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 0
        assert fx.read_dealer(dealer["id"])["approved_warranty_labor_rate_cents"] is None

        after_terminal = api.respond_to_warranty_rate_dispute(
            dispute["id"], f.dispute_response_payload("ACCEPT"),
            make_manufacturer_headers(manufacturer["id"]))
        validate_error(after_terminal, ApiErrorId.ERR_INVALID_DISPUTE_STATE.value,
                       expected_status=409)


class TestSalespersonRenewalDisciplineBar:
    def test_nine_rolling_points_bar_the_renewal_request_itself(self, api):
        """PRD 3.3: "A salesperson carrying 9 or more rolling `disciplinary_points`
        may not renew at all, and the request is refused with
        `ERR_SALESPERSON_DISCIPLINE_BAR`." The window is open on 2027-07-03, because
        PRD 3.3 requires "the clock date to fall inside the renewal window: on or
        after the day 60 days before `license_expires_on`, and on or before the day
        30 days after it", and PRD 3.3 leaves the licence dimension alone: "None of
        these movements touches `license_status`: a salesperson on `PROBATION` keeps
        selling, and the discipline dimension alone is what blocks a renewal
        approval."

        Design: Corner/errors/salesperson_renewal_with_nine_rolling_points_rejected
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")
        assert salesperson["license_expires_on"] == "2027-09-01"

        fx.set_clock("2026-09-05T00:00:00Z")
        complaint = fx.sanction_complaint(
            dealer["id"], "SUSPENSION_RECOMMENDED", 100000,
            "ODOMETER_MISREPRESENTATION", salesperson_id=salesperson["id"])
        assert complaint["points_assessed"] == 9
        assert complaint["civil_penalty_cents"] == 205000
        settled = fx.pay_restitution(complaint["id"], dealer["id"], 100000)
        assert settled["status"] == "CLOSED_SATISFIED"

        disciplined = fx.read_salesperson(salesperson["id"])
        assert disciplined["disciplinary_points"] == 9
        assert disciplined["discipline_status"] == "SUSPENDED_DISCIPLINARY"
        assert disciplined["license_status"] == "LICENSED"
        sponsor = fx.read_dealer(dealer["id"])
        assert sponsor["disciplinary_points"] == 9
        assert sponsor["license_status"] == "LICENSED"
        assert sponsor["restitution_outstanding_cents"] == 0

        fx.set_clock("2027-07-03T00:00:00Z")
        response = api.renew_salesperson(
            salesperson["id"], make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_SALESPERSON_DISCIPLINE_BAR.value,
                       expected_status=422)

        after = fx.read_salesperson(salesperson["id"])
        assert after["license_status"] == "LICENSED"
        assert after["renewal_count"] == 0
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 1


class TestDealerRenewalGrace:
    def test_a_renewal_submitted_one_day_past_the_grace_is_refused(self, api):
        """PRD 3.2: "It may not be submitted earlier than 60 days before the current
        expiry (`ERR_RENEWAL_WINDOW_NOT_OPEN`), nor later than 30 days after it
        (`ERR_RENEWAL_GRACE_EXPIRED`)." A term effective 2026-09-01 expires
        2028-08-30, because PRD 3.2 says "the dealer term runs 730 days, so
        `license_expires_on` is 729 days after `license_effective_on` and is the last
        day of the term inclusive", which puts the grace period's last day at
        2028-09-29. The requested term is perfectly contiguous, so
        `ERR_TERM_NOT_CONTIGUOUS` is not in play.

        Design: Corner/errors/dealer_renewal_submitted_after_the_thirty_day_grace_rejected
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        assert dealer["license_expires_on"] == "2028-08-30"
        renewal = fx.open_application(
            dealer["id"], application_type="RENEWAL",
            requested_term_start_on="2028-08-31")

        swept = fx.set_clock("2028-09-30T00:00:00Z")
        assert swept["swept_dealer_count"] == 1
        assert fx.read_dealer(dealer["id"])["license_status"] == "EXPIRED"

        response = api.submit_license_application(
            renewal["id"], make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_RENEWAL_GRACE_EXPIRED.value,
                       expected_status=422)

        after = fx.read_application(renewal["id"])
        assert after["status"] == "DRAFT"
        assert after["submitted_at"] is None
        assert after["fee_quoted_cents"] is None
        assert fx.read_dealer(dealer["id"])["license_expires_on"] == "2028-08-30"
