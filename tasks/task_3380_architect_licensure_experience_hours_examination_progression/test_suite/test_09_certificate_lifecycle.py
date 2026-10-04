"""Certificate issuance, CE entries, renewal windows, lapse and
reinstatement (PRD §3.1, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId, MAX_CE_ENTRY_HOURS, TEST_USERS, create_candidate,
    create_jurisdiction, log_ce_entry, make_candidate_headers,
    run_expiry_sweep, set_clock, setup_certificate_holder, validate_error,
    validate_paginated, validate_success,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]
BOARD = TEST_USERS["board_admin_headers"]


def _cert(api, ctx):
    return validate_success(api.get_certificate(
        ctx["certificate"]["id"], NCARB,
    ))


def _renew(api, ctx):
    return api.renew_certificate(
        ctx["certificate"]["id"], make_candidate_headers(ctx["candidate"]["id"]),
    )


class TestIssuance:
    def test_certificate_issuance_before_eligible_rejected(self, api):
        """PRD §3.6: "Issuing while `certificate_eligible` is false fails with
        `ERR_ELIGIBILITY_NOT_MET`; issuing while any `OPEN` disciplinary
        report exists against the candidate fails with
        `ERR_OPEN_DISCIPLINARY_BLOCK`".
        PRD §3.6: "Reading a candidate's certificate history returns an array
        that holds at most one certificate while that certificate is not
        `REVOKED`".

        Design: Corner/validations/certificate_issuance_before_eligible_rejected
        """
        create_jurisdiction(code=J1)
        candidate = create_candidate(home_jurisdiction_code=J1)
        validate_error(
            api.issue_certificate(candidate["id"], NCARB),
            ApiErrorId.ERR_ELIGIBILITY_NOT_MET,
        )
        history, meta = validate_paginated(
            api.get_candidate_certificate(candidate["id"], NCARB)
        )
        assert history == [], "no certificate exists for the candidate"
        assert meta["total_count"] == 0

    def test_certificate_snapshot_and_double_issuance(self, api):
        """PRD §3.6: "a `home_jurisdiction_code` snapshot of the candidate's
        home board, `ce_hours_required` and `ce_hsw_hours_required` snapshots
        copied from that board's flags at issuance time (so later board edits
        do not retroactively change the certificate's obligations)".
        PRD §3.6: "issuing while the candidate already holds a certificate
        that is not `REVOKED` fails with `ERR_CERTIFICATE_EXISTS`."

        Design: Corner/validations/certificate_snapshot_and_double_issuance
        """
        ctx = setup_certificate_holder(
            jurisdiction_code=J1,
            ce_hours_required=30, ce_hsw_hours_required=15,
        )
        # Council later loosens the board's CE requirements.
        validate_success(api.update_jurisdiction(
            ctx["jurisdiction"]["id"],
            {"expected_jurisdiction_version": ctx["jurisdiction"]["version"],
             "ce_hours_required": 20, "ce_hsw_hours_required": 10},
            NCARB,
        ))
        cert = _cert(api, ctx)
        assert cert["ce_hours_required"] == 30, "issuance snapshot pinned"
        assert cert["ce_hsw_hours_required"] == 15, "issuance snapshot pinned"
        validate_error(
            api.issue_certificate(ctx["candidate"]["id"], NCARB),
            ApiErrorId.ERR_CERTIFICATE_EXISTS,
        )

    def test_board_admin_cannot_issue_certificate_unauthorized(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in
        the endpoint's authorized-role list and the ownership rules of §2.6
        must hold; either failure is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."
        PRD §3.6: "Issuance is an `NcarbAdministrator` action and is gated
        three ways beyond eligibility."
        PRD §2.6: "When several checks could reject the same request, the
        first failure in a fixed evaluation order wins, and only that
        failure's error is returned." (authorization, tier 2, precedes the
        eligibility business-safety gate, tier 5)

        Design: Corner/rbac/board_admin_cannot_issue_certificate_unauthorized
        """
        # Fresh registry: the candidate exists but has no progress at all, so
        # only the role gate can fire (eligibility is a later tier).
        create_jurisdiction(code=J1)
        candidate = create_candidate(home_jurisdiction_code=J1)
        validate_error(
            api.issue_certificate(candidate["id"], BOARD),
            ApiErrorId.ERR_UNAUTHORIZED,
        )


class TestCeEntryAddVoidConservation:
    def test_add_entry_raises_period_and_lifetime_totals(self, api):
        """PRD §3.7: "`ce_hours_current_period` sums the hours of non-voided
        entries whose `completed_date` falls inside the current half-open
        period, `ce_hsw_current_period` sums the same restricted to `hsw`
        entries, and `lifetime_ce_hours` sums every non-voided entry across
        all periods and is never reset by renewal, lapse, or reinstatement."

        Design: Difficulty/compensating_invariant/ce_entry_add_void_period_conservation
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        cert0 = _cert(api, ctx)
        assert cert0["ce_hours_current_period"] == 0
        assert cert0["lifetime_ce_hours"] == 0
        entry = log_ce_entry(
            ctx["candidate"], ctx["certificate"]["id"],
            hours=6, hsw=True, completed_date="2026-10-06",
        )
        assert entry["voided"] is False
        cert = _cert(api, ctx)
        assert cert["ce_hours_current_period"] == 6
        assert cert["ce_hsw_current_period"] == 6
        assert cert["lifetime_ce_hours"] == 6

    def test_void_restores_totals_exactly(self, api):
        """PRD §3.7: "An erroneous entry may be voided by the certificate's
        owner; voiding sets `voided` to true and the entry counts toward
        nothing from then on."

        Design: Difficulty/compensating_invariant/ce_entry_add_void_period_conservation
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        entry = log_ce_entry(
            ctx["candidate"], ctx["certificate"]["id"],
            hours=6, hsw=True, completed_date="2026-10-06",
        )
        cert = _cert(api, ctx)
        assert cert["ce_hours_current_period"] == 6
        ch = make_candidate_headers(ctx["candidate"]["id"])
        voided = validate_success(api.void_ce_entry(entry["id"], ch))
        assert voided["voided"] is True
        cert = _cert(api, ctx)
        assert cert["ce_hours_current_period"] == 0, "invariant restored"
        assert cert["ce_hsw_current_period"] == 0
        assert cert["lifetime_ce_hours"] == 0


class TestReinstatement:
    def _lapsed_certificate(self, api):
        """Certificate issued 2026-10-06 (period ends 2028-10-06), lapsed by
        the sweep at period end; clock then moved to 2028-10-10."""
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        set_clock("2028-10-06T00:00:00Z")
        sweep = run_expiry_sweep()
        assert sweep["lapsed_certificates"] == 1
        cert = _cert(api, ctx)
        assert cert["status"] == "LAPSED", (
            "lapse is unconditional at period end"
        )
        set_clock("2028-10-10T00:00:00Z")
        return ctx

    def test_reinstatement_with_hsw_penalty(self, api):
        """PRD §3.7: "Reinstatement always uses strict accounting —
        carry-over never applies — and raises the Health-Safety-Welfare bar by
        a penalty of 4 hours: non-voided entries completed within the closed
        period must total at least `ce_hours_required`, and their `hsw` subset
        must reach `ce_hsw_hours_required` plus 4. A successful reinstatement
        returns the certificate to `ACTIVE`, starts a fresh period at the
        current date with `period_end` twenty-four calendar months later,
        increments `renewal_count` by one, and resets the carry bookkeeping to
        zero."
        PRD §3.7: "Each entry records `certificate_id`, an integer `hours` of
        at least 1 and at most 24, an `hsw` flag marking Health-Safety-Welfare
        content, a `completed_date` that must fall on or before the current
        date, and a `provider` name; an entry violating those bounds is
        rejected with `ERR_CE_ENTRY_INVALID`."

        Design: Corner/validations/reinstatement_with_hsw_penalty
        """
        ctx = self._lapsed_certificate(api)
        candidate = ctx["candidate"]
        cert_id = ctx["certificate"]["id"]
        ch = make_candidate_headers(candidate["id"])
        # Entry validation: future-dated and over-cap entries are rejected.
        validate_error(
            api.create_ce_entry(
                cert_id,
                {"hours": 4, "hsw": True, "completed_date": "2028-10-11",
                 "provider": "AIA"},
                ch,
            ),
            ApiErrorId.ERR_CE_ENTRY_INVALID,
        )
        validate_error(
            api.create_ce_entry(
                cert_id,
                {"hours": MAX_CE_ENTRY_HOURS + 1, "hsw": True,
                 "completed_date": "2028-06-01", "provider": "AIA"},
                ch,
            ),
            ApiErrorId.ERR_CE_ENTRY_INVALID,
        )
        # Make-up logging while LAPSED is legal; both entries fall inside the
        # closed period [2026-10-06, 2028-10-06).
        log_ce_entry(candidate, cert_id, hours=8, hsw=True,
                     completed_date="2028-06-01")
        log_ce_entry(candidate, cert_id, hours=16, hsw=False,
                     completed_date="2028-07-01")
        # Total 24 >= 24 but HSW 8 < 12 + 4: strict reinstatement fails.
        validate_error(
            api.renew_certificate(cert_id, ch),
            ApiErrorId.ERR_CE_HOURS_INSUFFICIENT,
        )
        log_ce_entry(candidate, cert_id, hours=8, hsw=True,
                     completed_date="2028-08-01")
        cert = validate_success(api.renew_certificate(cert_id, ch))
        assert cert["status"] == "ACTIVE", "HSW 16 >= 12 + 4 penalty now met"
        assert cert["renewal_count"] == 1
        assert cert["period_start"] == "2028-10-10"
        assert cert["period_end"] == "2030-10-10"
        assert cert["lifetime_ce_hours"] == 32, "8 + 16 + 8 across all periods"

    def test_reinstatement_window_closed_after_12_months(self, api):
        """PRD §3.7: "It remains available until the day twelve calendar
        months after `period_end`; a request on or before that day is
        admissible, and after it the door is shut with
        `ERR_REINSTATEMENT_WINDOW_CLOSED`."

        Design: Corner/validations/reinstatement_window_closed_after_12_months
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        set_clock("2028-10-06T00:00:00Z")
        run_expiry_sweep()
        ch = make_candidate_headers(ctx["candidate"]["id"])
        cert_id = ctx["certificate"]["id"]
        # Boundary day 2028-10-06 + 12 months == 2029-10-06: window open, so
        # evaluation reaches the CE leg and fails there (zero hours logged).
        set_clock("2029-10-06T00:00:00Z")
        validate_error(
            api.renew_certificate(cert_id, ch),
            ApiErrorId.ERR_CE_HOURS_INSUFFICIENT,
        )
        # One day later the temporal gate itself is shut.
        set_clock("2029-10-07T00:00:00Z")
        validate_error(
            api.renew_certificate(cert_id, ch),
            ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED,
        )
        cert = _cert(api, ctx)
        assert cert["status"] == "LAPSED", "both attempts leave it LAPSED"


class TestRenewalWindowsAndVariants:
    def test_renewal_window_boundary_and_carry_over_cap(self, api):
        """PRD §3.7: "While `ACTIVE`, renewal is open during a sixty-day
        window: the current date must fall on or after the day sixty days
        before `period_end` and strictly before `period_end`; outside that
        window the request is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."
        PRD §3.7: "Under the carry-over variant — flag true — the
        current-period total is augmented by a carry of up to 12 hours: the
        excess of the immediately preceding period's total over
        `ce_hours_required`, floored at zero and capped at 12, counts toward
        the current period's total requirement, while the
        Health-Safety-Welfare subset receives no carry and must stand on
        current-period entries alone; the preceding period is treated as zero
        for the first period and after any reinstatement."

        Design: Corner/calculations/renewal_window_boundary_and_carry_over_cap
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        candidate = ctx["candidate"]
        cert_id = ctx["certificate"]["id"]
        ch = make_candidate_headers(candidate["id"])
        # Period 1: 24 HSW + 16 non-HSW == 40 total (excess 16 over 24).
        set_clock("2027-07-02T00:00:00Z")
        log_ce_entry(candidate, cert_id, hours=24, hsw=True,
                     completed_date="2027-06-01")
        log_ce_entry(candidate, cert_id, hours=16, hsw=False,
                     completed_date="2027-07-01")
        # The home board now allows carry-over (read live at renewal time).
        validate_success(api.update_jurisdiction(
            ctx["jurisdiction"]["id"],
            {"expected_jurisdiction_version": ctx["jurisdiction"]["version"],
             "ce_carry_over_allowed": True},
            NCARB,
        ))
        # period_end 2028-10-06 minus 60 days == 2028-08-07; one day earlier
        # is outside the window.
        set_clock("2028-08-06T00:00:00Z")
        validate_error(
            api.renew_certificate(cert_id, ch),
            ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN,
        )
        set_clock("2028-08-07T00:00:00Z")
        cert = validate_success(api.renew_certificate(cert_id, ch))
        assert cert["renewal_count"] == 1
        assert cert["period_start"] == "2028-10-06"
        assert cert["period_end"] == "2030-10-06"
        # Period 2: only 11 HSW hours. Carry is capped at 12 although the
        # prior excess was 16, so 11 + 12 == 23 < 24 fails.
        set_clock("2029-06-02T00:00:00Z")
        log_ce_entry(candidate, cert_id, hours=11, hsw=True,
                     completed_date="2029-06-01")
        set_clock("2030-09-06T00:00:00Z")
        validate_error(
            api.renew_certificate(cert_id, ch),
            ApiErrorId.ERR_CE_HOURS_INSUFFICIENT,
        )
        # One more HSW hour: 12 + 12 == 24 >= 24 and HSW 12 >= 12.
        log_ce_entry(candidate, cert_id, hours=1, hsw=True,
                     completed_date="2030-09-06")
        cert = validate_success(api.renew_certificate(cert_id, ch))
        assert cert["renewal_count"] == 2
        assert cert["period_start"] == "2030-10-06"
        assert cert["period_end"] == "2032-10-06"

    def _period2_with_18_hours(self, api):
        """Certificate under J1 defaults (carry-over false at issuance);
        renewed once into period 2 (carry booked min(30-24, 12) == 6); period
        2 holds 18 hours (12 HSW); clock inside the period-2 renewal window
        at 2030-09-06."""
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        candidate = ctx["candidate"]
        cert_id = ctx["certificate"]["id"]
        set_clock("2027-07-02T00:00:00Z")
        log_ce_entry(candidate, cert_id, hours=18, hsw=True,
                     completed_date="2027-06-01")
        log_ce_entry(candidate, cert_id, hours=12, hsw=False,
                     completed_date="2027-07-01")
        set_clock("2028-09-01T00:00:00Z")
        first = validate_success(api.renew_certificate(
            cert_id, make_candidate_headers(candidate["id"]),
        ))
        assert first["renewal_count"] == 1
        assert first["period_start"] == "2028-10-06"
        set_clock("2029-07-02T00:00:00Z")
        log_ce_entry(candidate, cert_id, hours=12, hsw=True,
                     completed_date="2029-06-01")
        log_ce_entry(candidate, cert_id, hours=6, hsw=False,
                     completed_date="2029-07-01")
        set_clock("2030-09-06T00:00:00Z")
        return ctx

    def test_strict_variant_rejects_identical_history(self, api):
        """PRD §3.7: "Under the strict variant — flag false — the current
        period's hours alone must meet `ce_hours_required` and its
        Health-Safety-Welfare subset must meet `ce_hsw_hours_required`."
        PRD §3.7: "Identical entry history can therefore pass in one
        jurisdiction and fail in another, and insufficient totals are rejected
        with `ERR_CE_HOURS_INSUFFICIENT`."

        Design: Difficulty/dual_variant_calc/ce_renewal_strict_vs_carry_over
        """
        ctx = self._period2_with_18_hours(api)
        validate_error(_renew(api, ctx), ApiErrorId.ERR_CE_HOURS_INSUFFICIENT)
        cert = _cert(api, ctx)
        assert cert["status"] == "ACTIVE", "rejection changes nothing"
        assert cert["renewal_count"] == 1
        assert cert["period_end"] == "2030-10-06"

    def test_carry_over_variant_accepts_identical_history(self, api):
        """PRD §3.1: "the `ce_carry_over_allowed` flag in force at the moment
        of each renewal decides which compliance variant applies."
        PRD §3.7: "Under the carry-over variant — flag true — the
        current-period total is augmented by a carry of up to 12 hours: the
        excess of the immediately preceding period's total over
        `ce_hours_required`, floored at zero and capped at 12, counts toward
        the current period's total requirement, while the
        Health-Safety-Welfare subset receives no carry and must stand on
        current-period entries alone".
        PRD §3.7: "A successful renewal advances the period: `period_start`
        becomes the old `period_end`, `period_end` extends twenty-four
        calendar months beyond it, `renewal_count` increments by one".

        Design: Difficulty/dual_variant_calc/ce_renewal_strict_vs_carry_over
        """
        ctx = self._period2_with_18_hours(api)
        validate_error(_renew(api, ctx), ApiErrorId.ERR_CE_HOURS_INSUFFICIENT)
        # Same history, flag flipped live: 18 + min(30-24, 12) == 24 >= 24
        # and HSW 12 >= 12.
        validate_success(api.update_jurisdiction(
            ctx["jurisdiction"]["id"],
            {"expected_jurisdiction_version": ctx["jurisdiction"]["version"],
             "ce_carry_over_allowed": True},
            NCARB,
        ))
        cert = validate_success(_renew(api, ctx))
        assert cert["status"] == "ACTIVE"
        assert cert["renewal_count"] == 2
        assert cert["period_start"] == "2030-10-06"
        assert cert["period_end"] == "2032-10-06"
