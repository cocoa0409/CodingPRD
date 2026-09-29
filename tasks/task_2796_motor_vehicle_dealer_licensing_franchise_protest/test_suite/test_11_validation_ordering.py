"""Validation: reference-data uniqueness, the scope of the open-application
bar, and the places where two faults are live at once and the §2.10 order
decides which one is reported.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BOARD_ADMIN,
    make_dealer_headers,
    make_manufacturer_headers,
)


class TestReferenceDataUniqueness:
    def test_a_second_franchisor_may_not_claim_the_same_line_make(self, api):
        """PRD 3.1: "The `line_make` is an uppercase A-to-Z token between 2 and 20
        characters (for example `AURORA`) and must be unique across all franchisors;
        a repeat is refused with `ERR_DUPLICATE_LINE_MAKE`." A different legal name
        and a different home office state do not make the token free, and the
        incumbent's own posted rate must survive the refusal untouched.

        Design: Corner/validations/duplicate_line_make_rejected
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        incumbent = fx.create_manufacturer()
        assert incumbent["line_make"] == "AURORA"
        assert incumbent["posted_warranty_labor_rate_cents"] == 6000

        response = api.create_manufacturer(
            f.manufacturer_payload(
                legal_name="Aurora Distribution West", line_make="AURORA",
                home_office_state="CA", posted_warranty_labor_rate_cents=7000),
            BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_DUPLICATE_LINE_MAKE.value,
                       expected_status=409)

        _, meta = validate_paginated(api.list_manufacturers(BOARD_ADMIN))
        assert meta["total_count"] == 1
        after = fx.read_manufacturer(incumbent["id"])
        assert after["posted_warranty_labor_rate_cents"] == 6000
        assert after["legal_name"] == incumbent["legal_name"]

    def test_the_open_application_bar_is_scoped_to_the_application_type(self, api):
        """PRD 3.2: "but a dealership may never hold two live applications of the
        same type: if another application of that same `application_type` is already
        in `DRAFT`, `SUBMITTED` or `DEFICIENT`, the request is refused with
        `ERR_OPEN_APPLICATION_EXISTS`." A `RELOCATION` opened at the same moment is
        not of that same type, so it is admitted while the second `INITIAL` is
        turned away.

        Design: Corner/validations/open_application_blocks_same_type_but_not_another_type
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        first = fx.open_application(dealer["id"])
        assert first["status"] == "DRAFT"

        relocation = fx.open_application(
            dealer["id"], application_type="RELOCATION",
            relocation_site_x_km=5, relocation_site_y_km=12)
        assert relocation["status"] == "DRAFT"

        response = api.create_license_application(
            f.license_application_payload(
                dealer["id"], facility_sqft=10000, display_spaces=14,
                service_bays=5, bond_amount_cents=6000000,
                insurance_liability_cents=120000000),
            make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_OPEN_APPLICATION_EXISTS.value,
                       expected_status=409)

        assert fx.read_application(first["id"])["status"] == "DRAFT"
        _, meta = validate_paginated(api.list_license_applications(
            BOARD_ADMIN, params={"dealer_id": dealer["id"]}))
        assert meta["total_count"] == 2


class TestExistenceOutranksConcurrency:
    def test_an_unknown_protestant_is_reported_before_a_stale_filing_version(self, api):
        """PRD 2.10 lists "**Body foreign-key existence** — every foreign key in the
        body resolves, in the order the operation declares its inputs (the 404
        catalogue)." ahead of "**Stale-version guards** —
        `ERR_STALE_FILING_VERSION` and `ERR_STALE_ROOM_VERSION` (HTTP 412)." The
        comparand supplied here is one behind the served filing's own `version`, so
        both faults are live and only the ordering decides the answer.

        Design: Corner/validations/protest_unknown_dealer_outranks_stale_filing_version
        """
        ctx = fx.setup_served_additional_point_notice(notice_clock=None)
        filing = ctx["filing"]

        response = api.create_protest(
            f.protest_payload(filing["id"], NON_EXISTENT_UUID,
                              filing["version"] - 1,
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(NON_EXISTENT_UUID))
        validate_error(response, ApiErrorId.ERR_DEALER_NOT_FOUND.value,
                       expected_status=404)

        after = fx.read_filing(filing["id"])
        assert after["status"] == "NOTICE_SERVED"
        assert after["active_protest_count"] == 0
        _, meta = validate_paginated(api.list_protests(BOARD_ADMIN))
        assert meta["total_count"] == 0


class TestNoticeServiceGuards:
    def test_a_lapsed_franchisor_may_not_serve_its_own_notice(self, api):
        """PRD 3.4: "Only a franchisor whose `state_registration_status` is
        `REGISTERED` may serve; a lapsed franchisor is refused with
        `ERR_MANUFACTURER_REGISTRATION_LAPSED`." Every field on the filing itself is
        in order, so the refusal turns entirely on another entity's state, and PRD
        3.4 makes the untouched row explicit: "the filing opens at `DRAFT` with
        `amendment_count` and `active_protest_count` at 0 and `notice_served_on`,
        `notice_days_provided` and `protest_window_ends_on` all unset."

        Design: Corner/validations/lapsed_franchisor_cannot_serve_a_franchise_notice
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer(state_registration_status="LAPSED")
        filing = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-11-30",
            site_x_km=9, site_y_km=12)

        response = api.serve_filing_notice(
            filing["id"], make_manufacturer_headers(manufacturer["id"]))
        validate_error(response, ApiErrorId.ERR_MANUFACTURER_REGISTRATION_LAPSED.value,
                       expected_status=422)

        after = fx.read_filing(filing["id"])
        assert after["status"] == "DRAFT"
        assert after["notice_served_on"] is None
        assert after["notice_days_provided"] is None
        assert after["protest_window_ends_on"] is None
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 0

    def test_an_additional_point_notice_is_admitted_at_exactly_thirty_days(self, api):
        """PRD 3.4: "The notice period must reach the statutory minimum, measured as
        the whole days from the clock date to `proposed_effective_on`: at least 60
        days for a `TERMINATION` or a `RELOCATION`, at least 30 days for an
        `ADDITIONAL_POINT`. A shorter period is refused with
        `ERR_NOTICE_PERIOD_TOO_SHORT`." From 2026-09-01 a 2026-09-30 effective date
        gives 29 whole days and 2026-10-01 gives exactly 30, so the floor is
        reached only by the second.

        Design: Corner/validations/additional_point_notice_needs_exactly_thirty_days
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer()
        short = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-09-30",
            site_x_km=9, site_y_km=12)
        exact = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-10-01",
            site_x_km=9, site_y_km=12)

        refused = api.serve_filing_notice(
            short["id"], make_manufacturer_headers(manufacturer["id"]))
        validate_error(refused, ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT.value,
                       expected_status=422)
        assert fx.read_filing(short["id"])["status"] == "DRAFT"

        served = get_success_data(api.serve_filing_notice(
            exact["id"], make_manufacturer_headers(manufacturer["id"])))

        assert served["status"] == "NOTICE_SERVED"
        assert served["notice_served_on"] == "2026-09-01"
        assert served["notice_days_provided"] == 30
        assert served["protest_window_ends_on"] == "2026-10-01"
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 1


class TestPartyStandingOutranksTheClock:
    def test_a_delinquency_suspended_protestant_is_told_about_its_licence(self, api):
        """PRD 2.10 places "**Party-standing safety checks**, in this order:
        franchisor registration standing (`ERR_MANUFACTURER_REGISTRATION_LAPSED`),
        then application deficiencies (`ERR_APPLICATION_HAS_DEFICIENCIES`), then
        sponsor licensure (`ERR_SPONSOR_NOT_LICENSED`), then the two discipline bars
        — the undisclosed-history bar (`ERR_UNDISCLOSED_DISCIPLINE`) and the
        salesperson renewal bar (`ERR_SALESPERSON_DISCIPLINE_BAR`) — and finally the
        acting dealer's own licence standing (`ERR_DEALER_LICENSE_NOT_ACTIVE`)."
        ahead of the temporal stage. PRD 3.5: "The protestant must itself be a
        dealership in good standing: a protestant whose `license_status` is not
        `LICENSED` is turned away with `ERR_DEALER_LICENSE_NOT_ACTIVE`." The window
        closed on 2026-10-01 and the sweep to 2026-10-10 suspended the dealership,
        so both faults are live at once.

        Design: Corner/validations/suspended_protestant_safety_check_outranks_closed_window
        """
        ctx = fx.setup_served_additional_point_notice(
            notice_clock=None, proposed_effective_on="2026-11-30")
        dealer, filing = ctx["dealer"], ctx["filing"]
        assert filing["protest_window_ends_on"] == "2026-10-01"

        fx.set_clock("2026-09-05T00:00:00Z")
        complaint = fx.sanction_complaint(
            dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            findings_code="MISLEADING_PRICE_ADVERTISING")
        assert complaint["restitution_due_on"] == "2026-10-05"
        fx.set_clock("2026-10-10T00:00:00Z")
        suspended = fx.read_dealer(dealer["id"])
        assert suspended["license_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "RESTITUTION_DELINQUENT"

        current = fx.read_filing(filing["id"])
        response = api.create_protest(
            f.protest_payload(filing["id"], dealer["id"], current["version"],
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_DEALER_LICENSE_NOT_ACTIVE.value,
                       expected_status=422)

        after = fx.read_filing(filing["id"])
        assert after["status"] == "NOTICE_SERVED"
        assert after["active_protest_count"] == 0


class TestRestitutionLedgerRefusesOverpayment:
    def test_a_cumulative_overpayment_is_refused_rather_than_clipped(self, api):
        """PRD 3.9: "A payment that would push `restitution_paid_cents` above
        `restitution_ordered_cents` is refused outright with
        `ERR_RESTITUTION_OVERPAYMENT` rather than being clipped to the balance." PRD
        3.9: "A payment that leaves a balance outstanding keeps the complaint in
        `SANCTIONED`, increases `restitution_paid_cents` by the amount paid and
        decreases the dealership's `restitution_outstanding_cents` by exactly that
        same amount, conserving the ledger invariant of §2.11." Each instalment is
        plausible on its own; only the running total is not.

        Design: Corner/validations/restitution_overpayment_refused_not_clipped
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")
        complaint = fx.sanction_complaint(
            dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            findings_code="MISLEADING_PRICE_ADVERTISING")
        assert complaint["restitution_ordered_cents"] == 200000
        assert complaint["civil_penalty_cents"] == 60000

        partial = fx.pay_restitution(complaint["id"], dealer["id"], 120000)
        assert partial["restitution_paid_cents"] == 120000
        assert partial["status"] == "SANCTIONED"
        assert fx.read_dealer(dealer["id"])["restitution_outstanding_cents"] == 80000

        response = api_client.pay_restitution(
            complaint["id"], f.restitution_payment_payload(100000),
            make_dealer_headers(dealer["id"]))
        validate_error(response, ApiErrorId.ERR_RESTITUTION_OVERPAYMENT.value,
                       expected_status=422)

        after = fx.read_complaint(complaint["id"])
        assert after["restitution_paid_cents"] == 120000
        assert after["status"] == "SANCTIONED"
        assert after["restitution_ordered_cents"] == 200000
        outstanding = fx.read_dealer(dealer["id"])["restitution_outstanding_cents"]
        assert outstanding == 80000
        assert after["restitution_ordered_cents"] == after["restitution_paid_cents"] + outstanding


class TestApprovalReadsTheScan:
    def test_a_deficient_application_may_not_be_approved(self, api):
        """PRD 3.2: "The recomputed `deficiency_count` must be 0 — the statutory
        minimums are not waivable by the board, and an approval attempted on a
        deficient application is refused with `ERR_APPLICATION_HAS_DEFICIENCIES`."
        PRD 3.2 fixes the minimum the site misses: "A new-motor-vehicle applicant
        must show at least 8,000 square feet of enclosed facility, at least 10
        display spaces, at least 3 service bays, a bond of at least 5,000,000 cents
        (fifty thousand dollars) and garage liability of at least 100,000,000 cents
        (one million dollars)."

        Design: Corner/validations/deficiency_scan_must_run_before_an_approval_is_allowed
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        application = fx.open_application(dealer["id"], facility_sqft=5000)
        submitted = fx.submit_application(application["id"], dealer["id"])
        assert submitted["deficiency_codes"] == ["FACILITY_TOO_SMALL"]

        response = api.decide_license_application(
            application["id"], f.application_decision_payload("APPROVED"),
            BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_APPLICATION_HAS_DEFICIENCIES.value,
                       expected_status=422)

        after = fx.read_application(application["id"])
        assert after["status"] == "SUBMITTED"
        assert after["deficiency_codes"] == ["FACILITY_TOO_SMALL"]
        assert after["decision_outcome"] is None
        assert after["fee_total_cents"] is None
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["license_status"] == "PROSPECTIVE"
        assert after_dealer["license_effective_on"] is None


class TestRenewalWindowOpeningEdge:
    def test_the_renewal_window_opens_on_the_sixtieth_day_before_expiry(self, api):
        """PRD 3.2: "It may not be submitted earlier than 60 days before the current
        expiry (`ERR_RENEWAL_WINDOW_NOT_OPEN`), nor later than 30 days after it
        (`ERR_RENEWAL_GRACE_EXPIRED`)." Against a 2028-08-30 expiry the opening edge
        is 2028-07-01, and the quote there carries no delinquency, because PRD 3.2
        says to "count the whole days from that prior expiry to the reference date,
        treat a negative count as zero, charge 5,000 cents per late day, and cap the
        penalty at 50,000 cents" — so a renewal base of 90,000 plus 25,000 less
        4,000 quotes 111000.

        Design: Corner/validations/renewal_window_opens_exactly_sixty_days_before_expiry
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        assert fx.read_dealer(dealer["id"])["license_expires_on"] == "2028-08-30"

        fx.set_clock("2028-06-30T00:00:00Z")
        renewal = fx.open_application(
            dealer["id"], application_type="RENEWAL",
            requested_term_start_on="2028-08-31")

        too_early = api.submit_license_application(
            renewal["id"], make_dealer_headers(dealer["id"]))
        validate_error(too_early, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value,
                       expected_status=422)
        assert fx.read_application(renewal["id"])["status"] == "DRAFT"

        fx.set_clock("2028-07-01T00:00:00Z")
        submitted = get_success_data(api.submit_license_application(
            renewal["id"], make_dealer_headers(dealer["id"])))

        assert submitted["status"] == "SUBMITTED"
        assert submitted["deficiency_count"] == 0
        assert submitted["fee_quoted_cents"] == 111000
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["license_status"] == "LICENSED"
        assert after_dealer["license_expires_on"] == "2028-08-30"
