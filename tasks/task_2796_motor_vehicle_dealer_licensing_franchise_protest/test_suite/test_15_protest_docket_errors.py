"""The error contract on the protest and its docket: the duplicate-protest bar,
party agreement, exhibit-label scoping, the docket's four timing guards, the
good-cause gate on a sustain, the appeal freeze and the finalisation windows.
"""
from prd_bench_local_runner.testing import (
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
    HEARING_CLERK,
    make_dealer_headers,
    make_manufacturer_headers,
)


class TestProtestPartyAndExhibitGuards:
    def test_one_filed_protest_yields_four_distinct_refusals(self, api):
        """PRD 3.5: "And a protestant may hold only one live protest per filing: if
        it already has a protest against that same filing standing in `FILED`,
        `SCHEDULED`, `HEARD`, `SUSTAINED`, `DENIED` or `APPEALED`, the second is
        refused with `ERR_DUPLICATE_PROTEST`." PRD 3.6: "**Convening** the docketed
        hearing is the clerk's last act on it, and it is a fork with two entirely
        different consequences. It is admitted only from `SCHEDULED`, and only once
        the clock instant has reached `hearing_start_at`; an early attempt draws
        `ERR_HEARING_NOT_REACHED`." PRD 3.7: "As with exhibits, a `PROTESTANT` study
        must be posted by the protest's protestant dealership and a `MANUFACTURER`
        study by the protested filing's franchisor, and a mismatch is refused with
        `ERR_STUDY_PARTY_MISMATCH`." PRD 3.6: "Within one protest, an `exhibit_label`
        must be unique for a given `submitting_party`, so the two sides may each mark
        their own Exhibit A but neither may mark two; a repeat draws
        `ERR_DUPLICATE_EXHIBIT_LABEL`."

        Design: Corner/errors/protest_duplicate_party_and_exhibit_guards_rejected
        """
        ctx = fx.setup_filed_protest()
        protest, dealer = ctx["protest"], ctx["dealer"]
        manufacturer = ctx["manufacturer"]
        fresh = fx.read_filing(ctx["filing"]["id"])
        assert fresh["status"] == "PROTEST_PENDING"

        twin = api.create_protest(
            f.protest_payload(fresh["id"], dealer["id"], fresh["version"]),
            make_dealer_headers(dealer["id"]))
        validate_error(twin, ApiErrorId.ERR_DUPLICATE_PROTEST.value,
                       expected_status=409)

        undocketed = api.convene_protest_hearing(protest["id"], HEARING_CLERK)
        validate_error(undocketed, ApiErrorId.ERR_INVALID_PROTEST_STATE.value,
                       expected_status=409)

        wrong_party = api.create_market_study(
            protest["id"], f.statewide_study_payload("MANUFACTURER"),
            make_dealer_headers(dealer["id"]))
        validate_error(wrong_party, ApiErrorId.ERR_STUDY_PARTY_MISMATCH.value,
                       expected_status=422)

        first = fx.tender_protestant_exhibit(
            protest["id"], dealer["id"], exhibit_label="P-1", page_count=12)
        assert first["acceptance_status"] == "ACCEPTED"

        repeat = api.create_evidence_submission(
            protest["id"], f.exhibit_payload("PROTESTANT", "P-1", 4),
            make_dealer_headers(dealer["id"]))
        validate_error(repeat, ApiErrorId.ERR_DUPLICATE_EXHIBIT_LABEL.value,
                       expected_status=409)

        other_side = get_success_data(api.create_evidence_submission(
            protest["id"], f.exhibit_payload("MANUFACTURER", "P-1", 6),
            make_manufacturer_headers(manufacturer["id"])), 201)
        assert other_side["exhibit_label"] == "P-1"

        after = fx.read_protest(protest["id"])
        assert after["accepted_evidence_pages"] == 18
        assert after["late_evidence_count"] == 0
        _, meta = validate_paginated(
            api.list_evidence_submissions(protest["id"], BOARD_ADMIN))
        assert meta["total_count"] == 2


class TestDocketTimingGuards:
    def test_the_docket_enforces_window_hearing_instant_and_evidence_cutoff(self, api):
        """PRD 3.6: "The hearing must fall inside the statutory hearing window, which
        runs from the day 30 days after `filed_on` to the day 180 days after
        `filed_on`, both bounds inclusive; and `hearing_end_at` must be strictly later
        than `hearing_start_at`. A violation of either is
        `ERR_HEARING_OUTSIDE_WINDOW`." PRD 3.6: "Docketing stores all four docket
        fields on the protest, derives `evidence_deadline_at` as exactly 7 days before
        `hearing_start_at`, increments the room's `booked_hearing_count` by 1 and
        increments the room's `version` by 1." PRD 3.6: "An exhibit received after
        that deadline takes `LATE_ACCEPTED` only when `leave_granted` is true *and*
        the tender still precedes `hearing_start_at`; the boolean `is_late` records
        exactly that outcome. Anything else — after the deadline without leave, or at
        or after the hearing start instant — is refused with
        `ERR_EVIDENCE_DEADLINE_PASSED` and no row is stored." PRD 3.6: "That branch
        requires at least one probative market study tendered by the `PROTESTANT` to
        be on file, or the hearing cannot proceed and the request is refused with
        `ERR_NO_PROBATIVE_STUDY`."

        Design: Corner/errors/hearing_docket_window_convening_and_evidence_guards_rejected
        """
        ctx = fx.setup_filed_protest()
        protest, dealer = ctx["protest"], ctx["dealer"]
        room = fx.create_hearing_room()
        assert protest["filed_on"] == "2026-09-15"

        too_soon = api.schedule_protest_hearing(
            protest["id"],
            f.schedule_payload(room["id"], "2026-10-14T09:00:00Z",
                               "2026-10-14T12:00:00Z", room["version"]),
            HEARING_CLERK)
        validate_error(too_soon, ApiErrorId.ERR_HEARING_OUTSIDE_WINDOW.value,
                       expected_status=422)
        assert fx.read_room(room["id"])["version"] == room["version"]

        docketed = fx.schedule_hearing(
            protest["id"], room["id"], room["version"],
            "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")
        assert docketed["status"] == "SCHEDULED"
        assert docketed["evidence_deadline_at"].startswith("2026-10-26T10:00:00")
        assert fx.read_room(room["id"])["booked_hearing_count"] == 1

        early = api.convene_protest_hearing(protest["id"], HEARING_CLERK)
        validate_error(early, ApiErrorId.ERR_HEARING_NOT_REACHED.value,
                       expected_status=422)

        fx.set_clock("2026-10-27T00:00:00Z")
        no_leave = api.create_evidence_submission(
            protest["id"], f.exhibit_payload("PROTESTANT", "P-9", 5),
            make_dealer_headers(dealer["id"]))
        validate_error(no_leave, ApiErrorId.ERR_EVIDENCE_DEADLINE_PASSED.value,
                       expected_status=422)

        with_leave = get_success_data(api.create_evidence_submission(
            protest["id"],
            f.exhibit_payload("PROTESTANT", "P-9", 5, leave_granted=True),
            make_dealer_headers(dealer["id"])), 201)
        assert with_leave["acceptance_status"] == "LATE_ACCEPTED"
        assert with_leave["is_late"] is True
        late_state = fx.read_protest(protest["id"])
        assert late_state["late_evidence_count"] == 1
        assert late_state["accepted_evidence_pages"] == 5

        fx.set_clock("2026-11-02T10:00:00Z")
        no_study = api.convene_protest_hearing(protest["id"], HEARING_CLERK)
        validate_error(no_study, ApiErrorId.ERR_NO_PROBATIVE_STUDY.value,
                       expected_status=422)
        assert fx.read_protest(protest["id"])["status"] == "SCHEDULED"


def _heard_additional_point_protest():
    """An ADDITIONAL_POINT notice served 2026-09-01 for 2026-11-01, protested
    2026-09-15 and heard at 2026-11-02T10:00Z on one probative study."""
    ctx = fx.setup_served_additional_point_notice(
        notice_clock=None, proposed_effective_on="2026-11-01")
    fx.set_clock("2026-09-15T00:00:00Z")
    ctx["protest"] = fx.file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"],
        grounds_code="MARKET_ENCROACHMENT")
    fx.tender_protestant_study(
        ctx["protest"]["id"], ctx["dealer"]["id"],
        total_market_registrations=40000, line_make_registrations=3200,
        statewide_line_make_share_pct=12.50,
        permanency_investment_cents=250000000,
        consumer_access_drive_minutes=22, market_growth_pct=8.00)
    ctx["room"] = fx.create_hearing_room()
    ctx["protest"] = fx.schedule_hearing(
        ctx["protest"]["id"], ctx["room"]["id"], ctx["room"]["version"],
        "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")
    fx.set_clock("2026-11-02T10:00:00Z")
    ctx["protest"] = fx.convene_hearing(ctx["protest"]["id"])
    return ctx


class TestSubThresholdSustainAndAppealFreeze:
    def test_a_sub_threshold_sustain_is_refused_and_the_appeal_freezes_the_filing(self, api):
        """PRD 3.7: "Sustaining the protest — moving it `HEARD → SUSTAINED` — is
        permitted only when `good_cause_score` is greater than or equal to
        `good_cause_threshold`; otherwise the attempt is refused with
        `ERR_GOOD_CAUSE_NOT_ESTABLISHED`." PRD 3.7: "Where the protest is denied the
        protestant has lost, so `protestant_share_cents` is the remainder and
        `manufacturer_share_cents` is the rounded prevailing share." PRD 3.5: "A
        protest in `APPEALED` is deliberately excluded from it, because a pending
        court appeal is caught by the dedicated appeal guard described in §3.4 rather
        than by this count." PRD 3.4: "And no protest against the filing may stand in
        `APPEALED`: a pending court appeal freezes the filing, and the attempt draws
        `ERR_APPEAL_PENDING`."

        Design: Corner/errors/sub_threshold_sustain_and_pending_appeal_guards_rejected
        """
        ctx = _heard_additional_point_protest()
        protest, dealer, filing = ctx["protest"], ctx["dealer"], ctx["filing"]
        assert protest["status"] == "HEARD"
        analysis = fx.read_good_cause_analysis(protest["id"])
        assert analysis["good_cause_score"] == 55.40
        assert analysis["good_cause_threshold"] == 60.00
        assert analysis["good_cause_established"] is False

        refused = api.decide_protest(
            protest["id"],
            f.protest_decision_payload("SUSTAINED",
                                       findings_note="encroachment shown"),
            BOARD_ADMIN)
        validate_error(refused, ApiErrorId.ERR_GOOD_CAUSE_NOT_ESTABLISHED.value,
                       expected_status=422)
        assert fx.read_protest(protest["id"])["status"] == "HEARD"

        denied = fx.decide_protest(
            protest["id"], "DENIED", findings_note="good cause not established")
        assert denied["status"] == "DENIED"
        assert denied["decided_on"] == "2026-11-02"
        assert denied["assessment_total_cents"] == 45000
        assert denied["protestant_share_cents"] == 31500
        assert denied["manufacturer_share_cents"] == 13500
        resolved = fx.read_filing(filing["id"])
        assert resolved["status"] == "PROTEST_RESOLVED"
        assert resolved["active_protest_count"] == 0

        appealed = get_success_data(api.appeal_protest(
            protest["id"], f.appeal_payload("CV-2026-4417"),
            make_dealer_headers(dealer["id"])), 200)
        assert appealed["status"] == "APPEALED"
        assert appealed["appellant_party"] == "PROTESTANT"
        assert appealed["appeal_filed_on"] == "2026-11-02"
        assert appealed["court_docket_number"] == "CV-2026-4417"
        assert fx.read_filing(filing["id"])["active_protest_count"] == 0

        frozen = api_client.finalize_franchise_filing(filing["id"], BOARD_ADMIN)
        validate_error(frozen, ApiErrorId.ERR_APPEAL_PENDING.value,
                       expected_status=409)
        assert fx.read_filing(filing["id"])["status"] == "PROTEST_RESOLVED"


class TestFinalisationWindows:
    def test_an_unprotested_relocation_waits_for_both_dates(self, api):
        """PRD 3.4: "The protest window must already have closed, meaning the clock
        date is strictly later than `protest_window_ends_on`, or the request draws
        `ERR_PROTEST_WINDOW_OPEN`." PRD 3.4: "The proposed effective date must have
        arrived, meaning the clock date is on or after `proposed_effective_on`, or the
        request draws `ERR_EFFECTIVE_DATE_NOT_REACHED`." PRD 3.4: "On a `RELOCATION`,
        finalisation overwrites the affected dealership's `site_x_km` and `site_y_km`
        with the filing's coordinates." Ninety days' notice served on 2026-09-01
        closes the window on 2026-10-01 and leaves the effective date two months out.

        Design: Corner/errors/filing_finalized_before_the_window_closes_and_before_the_effective_date_rejected
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        filing = fx.open_relocation_filing(
            manufacturer["id"], dealer["id"], "2026-11-30",
            site_x_km=18, site_y_km=0)
        filing = fx.serve_notice(filing["id"], manufacturer["id"])
        assert filing["notice_served_on"] == "2026-09-01"
        assert filing["notice_days_provided"] == 90
        assert filing["protest_window_ends_on"] == "2026-10-01"

        fx.set_clock("2026-09-15T00:00:00Z")
        window_open = api_client.finalize_franchise_filing(filing["id"], BOARD_ADMIN)
        validate_error(window_open, ApiErrorId.ERR_PROTEST_WINDOW_OPEN.value,
                       expected_status=422)

        fx.set_clock("2026-10-02T00:00:00Z")
        too_early = api_client.finalize_franchise_filing(filing["id"], BOARD_ADMIN)
        validate_error(too_early, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED.value,
                       expected_status=422)
        assert fx.read_filing(filing["id"])["status"] == "NOTICE_SERVED"

        fx.set_clock("2026-11-30T00:00:00Z")
        effective = fx.finalize_filing(filing["id"])

        assert effective["status"] == "EFFECTIVE"
        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["site_x_km"] == 18
        assert after_dealer["site_y_km"] == 0
        assert after_dealer["license_status"] == "LICENSED"
        assert after_dealer["franchise_status"] == "FRANCHISED"
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 0
