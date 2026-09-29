"""Endpoint round trips: the create/read/list trio on a complaint, the renewal
action, the always-available derived read, and the dispute that links two
parties.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BOARD_ADMIN,
    COMPLAINT_INVESTIGATOR,
    make_dealer_headers,
    make_manufacturer_headers,
)


class TestComplaintCreateReadList:
    def test_the_intake_trio_round_trips_through_all_three_reads(self, api):
        """PRD 3.9: "A new complaint opens at `RECEIVED` with `points_assessed` at
        0, `restitution_paid_cents` at 0 and `investigator_user_id`,
        `findings_code`, `substantiated`, `sanction_type`, `civil_penalty_cents`,
        `restitution_ordered_cents`, `restitution_due_on` and `resolved_at` all
        unset." PRD 3.9: "Complaints may be read individually or listed with
        filters on `dealer_id`, `salesperson_id`, `status` and `allegation_code`."
        so the `RECEIVED` filter finds the row and the terminal-status filter
        cannot.

        Design: Corner/endpoints/consumer_complaint_create_read_and_filtered_list
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]

        created = get_success_data(api.create_consumer_complaint(
            f.complaint_payload(dealer["id"], allegation_code="DEPOSIT_RETENTION",
                                alleged_loss_cents=75000,
                                complainant_name="Rosa Ibarra"),
            COMPLAINT_INVESTIGATOR), 201)
        assert created["status"] == "RECEIVED"

        detail = get_success_data(
            api.get_consumer_complaint(created["id"], BOARD_ADMIN), 200)
        assert detail["alleged_loss_cents"] == 75000
        assert detail["complainant_name"] == "Rosa Ibarra"
        assert detail["points_assessed"] == 0
        assert detail["restitution_paid_cents"] == 0
        assert detail["civil_penalty_cents"] is None
        assert detail["restitution_ordered_cents"] is None
        assert detail["restitution_due_on"] is None
        assert detail["investigator_user_id"] is None
        assert detail["findings_code"] is None
        assert detail["sanction_type"] is None
        assert detail["resolved_at"] is None

        data, meta = validate_paginated(api.list_consumer_complaints(
            COMPLAINT_INVESTIGATOR,
            params={"dealer_id": dealer["id"], "status": "RECEIVED",
                    "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert data[0]["id"] == created["id"]

        _, closed_meta = validate_paginated(api.list_consumer_complaints(
            COMPLAINT_INVESTIGATOR,
            params={"dealer_id": dealer["id"],
                    "status": "CLOSED_UNSUBSTANTIATED",
                    "limit": 10, "offset": 0}))
        assert closed_meta["total_count"] == 0


class TestSalespersonRenewalAction:
    def test_the_renewal_request_moves_the_licence_dimension_alone(self, api):
        """PRD 3.3: "Requesting a renewal moves the salesperson `LICENSED →
        RENEWAL_PENDING` and requires the clock date to fall inside the renewal
        window: on or after the day 60 days before `license_expires_on`, and on or
        before the day 30 days after it." Against a 2027-09-01 expiry the window
        opens on 2027-07-03. PRD 3.3: "Entering `RENEWAL_PENDING` decrements the
        sponsoring dealership's `licensed_salesperson_count` — the licence is
        momentarily not in force — and leaves `discipline_status` completely
        untouched, because the two dimensions are orthogonal." The stored term
        dates wait for the analyst.

        Design: Corner/endpoints/salesperson_renewal_action_moves_only_the_licence_dimension
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")
        assert salesperson["license_effective_on"] == "2026-09-02"
        assert salesperson["license_expires_on"] == "2027-09-01"
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 1

        fx.set_clock("2027-07-03T00:00:00Z")
        renewing = get_success_data(api.renew_salesperson(
            salesperson["id"], make_dealer_headers(dealer["id"])), 200)

        assert renewing["license_status"] == "RENEWAL_PENDING"
        assert renewing["discipline_status"] == "CLEAR"
        assert renewing["license_expires_on"] == "2027-09-01"
        assert renewing["license_effective_on"] == "2026-09-02"
        assert renewing["renewal_count"] == 0
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 0


class TestGoodCauseAnalysisReadBeforeHearing:
    def test_the_weighting_is_readable_while_the_protest_is_still_filed(self, api):
        """PRD 3.7: "The whole weighting is readable at any time, not only after a
        hearing, through a computed read on the protest that reports
        `controlling_protestant_study_id`, `controlling_manufacturer_study_id`,
        `net_shortfall_pts`, `inadequacy_component`, `investment_component`,
        `access_component`, `growth_component`, `good_cause_score`,
        `good_cause_threshold` and the boolean `good_cause_established`." PRD 3.7:
        "Good cause is established when `good_cause_score` is greater than or
        equal to `good_cause_threshold`, inclusive at the threshold itself." A net
        shortfall of 2.50 against a `TERMINATION` scores 41.00 on a threshold of
        40.00.

        Design: Corner/endpoints/good_cause_analysis_read_before_the_hearing_is_convened
        """
        ctx = fx.setup_filed_protest()
        protest, dealer = ctx["protest"], ctx["dealer"]
        manufacturer = ctx["manufacturer"]

        protestant_study = fx.tender_protestant_study(
            protest["id"], dealer["id"],
            total_market_registrations=40000, line_make_registrations=3200,
            statewide_line_make_share_pct=12.50,
            permanency_investment_cents=250000000,
            consumer_access_drive_minutes=22, market_growth_pct=8.00)
        manufacturer_study = get_success_data(api.create_market_study(
            protest["id"],
            f.comparable_study_payload(
                "MANUFACTURER", total_market_registrations=40000,
                line_make_registrations=3200,
                comparable_market_shares_pct=[9.00, 10.00, 11.00],
                permanency_investment_cents=0,
                consumer_access_drive_minutes=12, market_growth_pct=8.00),
            make_manufacturer_headers(manufacturer["id"])), 201)
        assert manufacturer_study["expected_penetration_pct"] == 10.00

        analysis = get_success_data(api.get_good_cause_analysis(
            protest["id"], make_manufacturer_headers(manufacturer["id"])), 200)

        assert analysis["controlling_protestant_study_id"] == protestant_study["id"]
        assert analysis["controlling_manufacturer_study_id"] == manufacturer_study["id"]
        assert analysis["net_shortfall_pts"] == 2.50
        assert analysis["inadequacy_component"] == 20.00
        assert analysis["investment_component"] == 100.00
        assert analysis["access_component"] == 10.00
        assert analysis["growth_component"] == 40.00
        assert analysis["good_cause_score"] == 41.00
        assert analysis["good_cause_threshold"] == 40.00
        assert analysis["good_cause_established"] is True

        after = fx.read_protest(protest["id"])
        assert after["status"] == "FILED"
        assert after["distance_to_site_km"] is None


class TestRateDisputeLinksBothParties:
    def test_creating_the_dispute_freezes_the_sample_and_counts_it_open(self, api):
        """PRD 3.8: "`qualifying_line_count` is the number of qualifying lines
        across the whole sample and is frozen at filing; the franchisor's later
        exclusions never shrink it, so the sample-sufficiency test is a filing-time
        property." PRD 3.8: "A surviving dispute is created at `FILED`, with
        `filed_on` stamped as the clock date, `counter_rate_cents`, `spread_pct`,
        `manufacturer_response_type`, `approved_rate_cents`, `effective_on`,
        `decided_on` and `denial_reason_code` all unset, and
        `excluded_line_indexes` empty; the franchisor's `open_dispute_count` is
        recomputed." Five identical orders of 7,000 cents over one hour mean each
        per-order rate is 7000 and so is their mean.

        Design: Corner/endpoints/warranty_dispute_links_dealer_and_franchisor_on_create
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        assert manufacturer["posted_warranty_labor_rate_cents"] == 6000
        assert manufacturer["open_dispute_count"] == 0

        dispute = get_success_data(api.create_warranty_rate_dispute(
            f.rate_dispute_payload(
                dealer["id"], manufacturer["id"],
                f.qualifying_lines(5, labor_charge_cents=7000, labor_hours=1.0)),
            make_dealer_headers(dealer["id"])), 201)

        assert dispute["status"] == "FILED"
        assert dispute["dealer_id"] == dealer["id"]
        assert dispute["manufacturer_id"] == manufacturer["id"]
        assert dispute["qualifying_line_count"] == 5
        assert dispute["declared_rate_cents"] == 7000
        assert dispute["filed_on"] == "2026-09-01"
        assert dispute["counter_rate_cents"] is None
        assert dispute["spread_pct"] is None
        assert dispute["approved_rate_cents"] is None
        assert dispute["manufacturer_response_type"] is None
        assert dispute["excluded_line_indexes"] == []

        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 1
        assert fx.read_dealer(dealer["id"])["approved_warranty_labor_rate_cents"] is None
