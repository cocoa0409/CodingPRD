"""The two optimistic-concurrency comparands end to end, the per-write version
counter, the clock sweep's deterministic counters, and the immediacy of every
derived consequence.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import (
    BOARD_ADMIN,
    HEARING_CLERK,
    LICENSING_ANALYST,
    make_dealer_headers,
)


class TestProtestNeedsTheFreshFilingVersion:
    def test_the_amendment_invalidates_the_version_the_protestant_was_holding(self, api):
        """PRD 2.8: "A franchisor may legitimately amend a served notice, which
        re-stamps the proposed effective date and restarts the 30-day protest window and
        advances the filing's `version`; a protest computed against superseded notice
        terms would otherwise be docketed against terms that no longer exist." PRD 2.8:
        "If `expected_franchise_filing_version` does not equal the filing's current
        `version`, the protest is refused with `ERR_STALE_FILING_VERSION` (HTTP 412)."
        PRD 3.4: "The amendment increments `amendment_count` by 1, re-stamps
        `notice_served_on` to the clock date, recomputes `notice_days_provided`, and
        restarts the protest window by setting `protest_window_ends_on` to 30 days after
        the clock date."

        Design: Corner/cross_cutting_complexity_layers/protest_against_an_amended_notice_needs_the_fresh_filing_version
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        filing = fx.open_termination_filing(manufacturer["id"], dealer["id"],
                                            "2026-12-01")
        served = fx.serve_notice(filing["id"], manufacturer["id"])
        stale_version = served["version"]

        fx.set_clock("2026-09-10T00:00:00Z")
        amended = fx.amend_filing(filing["id"], manufacturer["id"], "2026-12-15")
        fresh_version = amended["version"]

        assert fresh_version == stale_version + 1
        assert amended["amendment_count"] == 1
        assert amended["status"] == "NOTICE_SERVED"
        assert amended["notice_served_on"] == "2026-09-10"
        assert amended["protest_window_ends_on"] == "2026-10-10"
        assert amended["proposed_effective_on"] == "2026-12-15"

        fx.set_clock("2026-09-15T00:00:00Z")
        superseded = api.create_protest(
            f.protest_payload(filing["id"], dealer["id"], stale_version),
            make_dealer_headers(dealer["id"]))
        validate_error(superseded, ApiErrorId.ERR_STALE_FILING_VERSION.value,
                       expected_status=412)
        _, meta = validate_paginated(api.list_protests(BOARD_ADMIN))
        assert meta["total_count"] == 0

        protest = get_success_data(api.create_protest(
            f.protest_payload(filing["id"], dealer["id"], fresh_version),
            make_dealer_headers(dealer["id"])), 201)

        assert protest["status"] == "FILED"
        after = fx.read_filing(filing["id"])
        assert after["status"] == "PROTEST_PENDING"
        assert after["active_protest_count"] == 1
        assert after["version"] == fresh_version + 1


class TestDocketNeedsTheFreshRoomVersion:
    def test_a_booking_by_another_protest_invalidates_the_clerk_s_booking_sheet(self, api):
        """PRD 2.8: "Every booking, every release of a slot and every change to the
        room's daily capacity advances `HearingRoom.version`, so a clerk holding an
        older value was reading a booking sheet that no longer describes the room's
        occupancy." PRD 2.8: "If `expected_hearing_room_version` does not equal the
        room's current `version`, the scheduling request is refused with
        `ERR_STALE_ROOM_VERSION` (HTTP 412)." PRD 3.6: "Docketing stores all four docket
        fields on the protest, derives `evidence_deadline_at` as exactly 7 days before
        `hearing_start_at`, increments the room's `booked_hearing_count` by 1 and
        increments the room's `version` by 1." The two intervals are three days apart,
        so nothing here is a room conflict.

        Design: Corner/cross_cutting_complexity_layers/second_hearing_docketed_from_a_stale_room_booking_sheet
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer()
        room = fx.create_hearing_room(room_code="HR-L2", seating_capacity=40,
                                      max_hearings_per_day=2)
        stale_version = room["version"]
        first = fx.create_dealer(legal_name="Lakeside Aurora")
        second = fx.create_dealer(legal_name="Northgate Aurora", site_x_km=5,
                                  site_y_km=0)
        fx.license_dealer(first["id"])
        fx.license_dealer(second["id"])

        first_filing = fx.serve_notice(
            fx.open_termination_filing(manufacturer["id"], first["id"],
                                       "2026-12-01")["id"], manufacturer["id"])
        second_filing = fx.serve_notice(
            fx.open_termination_filing(manufacturer["id"], second["id"],
                                       "2026-12-01")["id"], manufacturer["id"])

        fx.set_clock("2026-09-15T00:00:00Z")
        first_protest = fx.file_protest(first_filing["id"], first["id"],
                                        first_filing["version"])
        second_protest = fx.file_protest(second_filing["id"], second["id"],
                                         second_filing["version"])
        fx.schedule_hearing(first_protest["id"], room["id"], stale_version,
                            "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")

        booked = fx.read_room(room["id"])
        fresh_version = booked["version"]
        assert fresh_version == stale_version + 1
        assert booked["booked_hearing_count"] == 1

        docket = f.schedule_payload(room["id"], "2026-11-05T10:00:00Z",
                                    "2026-11-05T13:00:00Z", stale_version)
        refused = api.schedule_protest_hearing(second_protest["id"], docket,
                                               HEARING_CLERK)
        validate_error(refused, ApiErrorId.ERR_STALE_ROOM_VERSION.value,
                       expected_status=412)
        held = fx.read_protest(second_protest["id"])
        assert held["status"] == "FILED"
        assert held["hearing_room_id"] is None

        scheduled = get_success_data(api.schedule_protest_hearing(
            second_protest["id"],
            f.schedule_payload(room["id"], "2026-11-05T10:00:00Z",
                               "2026-11-05T13:00:00Z", fresh_version),
            HEARING_CLERK))

        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["hearing_start_at"].startswith("2026-11-05T10:00:00")
        after_room = fx.read_room(room["id"])
        assert after_room["booked_hearing_count"] == 2
        assert after_room["version"] == fresh_version + 1


class TestVersionCountsWritesOnly:
    def test_the_filing_version_advances_on_each_write_and_never_on_a_read(self, api):
        """PRD 2.4: "Most records additionally carry `updated_at`, in the same timestamp
        format, and `version`, an integer that starts at 1 when the record is created and
        increases by exactly 1 on every mutation of that record." PRD 2.4:
        "`Manufacturer`, `HearingRoom`, `Dealer`, `LicenseApplication`, `Salesperson`,
        `FranchiseFiling`, `Protest`, `WarrantyRateDispute` and `ConsumerComplaint` all
        behave this way: whenever the server writes to one of them — including writes
        that only touch a derived counter — it refreshes `updated_at` and increments
        `version`." PRD 3.1 scopes the franchisor's counter to the served states: "A
        franchisor record also exposes two derived counters the board reads constantly:
        `open_dispute_count`, the number of that franchisor's warranty rate disputes
        still in `FILED` or `UNDER_REVIEW`, and `active_filing_count`, the number of its
        franchise filings still in `NOTICE_SERVED` or `PROTEST_PENDING`."

        Design: Corner/cross_cutting_complexity_layers/filing_version_advances_once_per_write_and_never_on_a_read
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = fx.create_manufacturer()

        filing = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-11-01",
            site_x_km=9, site_y_km=12)
        assert filing["status"] == "DRAFT"
        assert filing["version"] == 1
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 0

        assert fx.read_filing(filing["id"])["version"] == 1
        assert fx.read_filing(filing["id"])["version"] == 1

        served = fx.serve_notice(filing["id"], manufacturer["id"])
        assert served["status"] == "NOTICE_SERVED"
        assert served["version"] == 2
        assert served["notice_served_on"] == "2026-09-01"
        assert served["protest_window_ends_on"] == "2026-10-01"
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 1

        assert fx.read_filing(filing["id"])["version"] == 2

        amended = fx.amend_filing(filing["id"], manufacturer["id"], "2026-11-15")

        assert amended["version"] == 3
        assert amended["amendment_count"] == 1
        assert amended["proposed_effective_on"] == "2026-11-15"
        assert fx.read_manufacturer(manufacturer["id"])["active_filing_count"] == 1


class TestClockSweepExpiresOneTermOnly:
    def test_the_sweep_expires_the_salesperson_and_leaves_the_sponsor_licensed(self, api):
        """PRD 2.7: "Independently, the clock sweep moves a salesperson from `LICENSED`
        to `EXPIRED` whenever its own `license_expires_on` falls earlier than the new
        clock date, decrementing the sponsor's count, and moves a `SUSPENDED_BY_SPONSOR`
        salesperson to `EXPIRED` on the same condition without any count change." PRD
        2.3: "The response to a clock advance reports the resulting `current_utc`
        together with four counters describing what the sweep touched:
        `swept_dealer_count`, `swept_salesperson_count`, `swept_protest_count` and
        `swept_complaint_count`." PRD 3.3: "An approval from `PENDING` moves the licence
        dimension `PENDING → LICENSED`, sets `license_effective_on` to the clock date and
        `license_expires_on` to 364 days later — a salesperson term is 365 days, with the
        expiry date the last day of the term inclusive — and increments the sponsoring
        dealership's `licensed_salesperson_count`." The dealership's own 730-day term
        runs to 2028-08-30, so the sweep of 2027-09-02 touches one row only.

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_a_salesperson_and_reports_deterministic_counters
        """
        ctx = fx.setup_licensed_used_only_dealer()
        dealer = ctx["dealer"]
        assert dealer["license_expires_on"] == "2028-08-30"

        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")
        assert salesperson["license_status"] == "LICENSED"
        assert salesperson["license_expires_on"] == "2027-09-01"
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 1

        swept = fx.set_clock("2027-09-02T00:00:00Z")

        assert_same_instant(swept["current_utc"], "2027-09-02T00:00:00Z")
        assert swept["swept_salesperson_count"] == 1
        assert swept["swept_dealer_count"] == 0
        assert swept["swept_protest_count"] == 0
        assert swept["swept_complaint_count"] == 0
        expired = fx.read_salesperson(salesperson["id"])
        assert expired["license_status"] == "EXPIRED"
        assert expired["discipline_status"] == "CLEAR"
        sponsor = fx.read_dealer(dealer["id"])
        assert sponsor["licensed_salesperson_count"] == 0
        assert sponsor["license_status"] == "LICENSED"

        again = fx.set_clock("2027-09-03T00:00:00Z")

        assert again["swept_salesperson_count"] == 0
        assert again["swept_dealer_count"] == 0
        assert again["swept_protest_count"] == 0
        assert again["swept_complaint_count"] == 0
        assert fx.read_salesperson(salesperson["id"])["license_status"] == "EXPIRED"


class TestApprovalIsImmediatelyConsistent:
    def test_the_decision_response_and_the_reads_after_it_already_agree(self, api):
        """PRD 2.7: "Cascades in this system are **transactional and multi-link**: a
        single request may move a dealer, its sponsored salespersons, its open rate
        disputes and its open applications, and every link must land in the same
        request." PRD 3.2: "Both halves stamp `decided_at`, set `decision_outcome` to
        `APPROVED` or `DENIED`, and recompute `fee_total_cents` and `fee_delta_cents`."
        PRD 3.2: "At decision time the reference date is the decision date, so any
        additional delinquent days that accrued while the board deliberated are billed;
        that result is written to `fee_total_cents`, and `fee_delta_cents` is
        `fee_total_cents` less `fee_quoted_cents`." PRD 3.2: "On the same approval the
        franchise dimension advances from `NONE` to `FRANCHISED` when the `dealer_type`
        is `NEW_MOTOR_VEHICLE`, and stays at `NONE` for a `USED_ONLY` dealership — the
        franchise dimension moving here independently of the licence dimension, exactly
        as §2.7 describes."

        Design: Corner/consistency_model/approval_response_already_carries_every_derived_consequence
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        fx.create_manufacturer()
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        application = fx.open_application(dealer["id"])
        submitted = fx.submit_application(application["id"], dealer["id"])
        assert submitted["fee_quoted_cents"] == 141000

        approved = get_success_data(api.decide_license_application(
            application["id"], f.application_decision_payload("APPROVED"),
            BOARD_ADMIN))

        assert approved["status"] == "APPROVED"
        assert approved["decision_outcome"] == "APPROVED"
        assert approved["deficiency_count"] == 0
        assert approved["fee_quoted_cents"] == 141000
        assert approved["fee_total_cents"] == 141000
        assert approved["fee_delta_cents"] == 0
        assert approved["decided_at"].startswith("2026-09-01T00:00:00")

        licensed = get_success_data(api.get_dealer(dealer["id"], BOARD_ADMIN))
        assert licensed["license_status"] == "LICENSED"
        assert licensed["franchise_status"] == "FRANCHISED"
        assert licensed["license_effective_on"] == "2026-09-01"
        assert licensed["license_expires_on"] == "2028-08-30"
        assert licensed["licensed_salesperson_count"] == 0

        _, meta = validate_paginated(api.list_license_applications(
            LICENSING_ANALYST,
            params={"dealer_id": dealer["id"], "status": "APPROVED",
                    "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
