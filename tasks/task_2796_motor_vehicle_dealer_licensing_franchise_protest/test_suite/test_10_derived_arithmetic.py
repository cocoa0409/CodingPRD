"""Derived arithmetic: the sufficiency scan's minimums and ordering, the
relevant-market radius, controlling-study selection, and the sanction ledger.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import BOARD_ADMIN, make_dealer_headers


class TestSufficiencyScanMinimums:
    def test_a_used_only_applicant_is_scanned_against_used_only_minimums(self, api):
        """PRD 3.2: "A used-only applicant must show at least 2,000 square feet, at
        least 3 display spaces, no service bays at all, a bond of at least 2,500,000
        cents and garage liability of at least 50,000,000 cents." PRD 3.2: "produces
        `deficiency_codes`, a list of unmet-requirement codes sorted in ascending
        lexicographic order — never in the order the checks happen to run —
        together with `deficiency_count`, which is simply the number of entries in
        that list." Zero bays meets a minimum of none, so
        `SERVICE_BAYS_INSUFFICIENT` never appears; PRD 3.1 leaves the fee at the
        bare base, since a `TIER_2` county charges "exactly the base in `TIER_2`".

        Design: Corner/calculations/deficiency_scan_uses_used_only_minimums_and_sorts_codes
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_used_only_dealer(legal_name="Lakeside Preowned")
        application = get_success_data(api.create_license_application(
            f.used_only_application_payload(
                dealer["id"], facility_sqft=1500, display_spaces=2, service_bays=0,
                bond_amount_cents=2000000, insurance_liability_cents=40000000,
                zoning_certificate_status="PENDING", line_make_count=0),
            make_dealer_headers(dealer["id"])), 201)

        submitted = get_success_data(api.submit_license_application(
            application["id"], make_dealer_headers(dealer["id"])))

        assert submitted["status"] == "SUBMITTED"
        assert submitted["deficiency_count"] == 5
        assert submitted["deficiency_codes"] == [
            "BOND_INSUFFICIENT",
            "DISPLAY_SPACES_INSUFFICIENT",
            "FACILITY_TOO_SMALL",
            "INSURANCE_INSUFFICIENT",
            "ZONING_NOT_APPROVED",
        ]
        assert "SERVICE_BAYS_INSUFFICIENT" not in submitted["deficiency_codes"]
        assert submitted["fee_quoted_cents"] == 120000

    def test_conditional_zoning_is_clean_for_a_relocation_and_deficient_for_an_initial(self, api):
        """PRD 3.2: "Zoning is satisfactory when `zoning_certificate_status` is
        `APPROVED`, and also when it is `CONDITIONAL` provided the
        `application_type` is `RENEWAL` or `RELOCATION`; in every other case the
        scan records `ZONING_NOT_APPROVED`." PRD 3.2 also swaps the base under the
        same certificate: "First, the base fee is selected by action: 120,000 cents
        for an `INITIAL` licence, 90,000 cents for a `RENEWAL`, 150,000 cents for a
        `CHANGE_OF_OWNERSHIP` and 75,000 cents for a `RELOCATION`." With one line
        make and 9,000 square feet the two quotes are 141000 and 96000.

        Design: Corner/calculations/conditional_zoning_clean_for_relocation_but_deficient_for_initial
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_dealer(legal_name="Lakeside Aurora")
        initial = fx.open_application(
            dealer["id"], zoning_certificate_status="CONDITIONAL")
        relocation = fx.open_application(
            dealer["id"], application_type="RELOCATION",
            zoning_certificate_status="CONDITIONAL",
            relocation_site_x_km=5, relocation_site_y_km=12)

        submitted_initial = fx.submit_application(initial["id"], dealer["id"])
        assert submitted_initial["deficiency_codes"] == ["ZONING_NOT_APPROVED"]
        assert submitted_initial["deficiency_count"] == 1
        assert submitted_initial["fee_quoted_cents"] == 141000

        submitted_relocation = get_success_data(api.submit_license_application(
            relocation["id"], make_dealer_headers(dealer["id"])))

        assert submitted_relocation["status"] == "SUBMITTED"
        assert submitted_relocation["deficiency_count"] == 0
        assert submitted_relocation["deficiency_codes"] == []
        assert submitted_relocation["fee_quoted_cents"] == 96000


class TestRelevantMarketRadius:
    def test_the_radius_admits_exactly_twenty_four_and_refuses_thirty(self, api):
        """PRD 3.5: "the distance is the square root of the sum of the two squared
        differences, rounded half up to two decimal places, and is recorded on the
        protest as `distance_to_site_km`." PRD 3.5: "Standing requires the proposed
        site to fall inside or exactly on a relevant-market radius of 24.00
        kilometres, so a computed distance of exactly 24.00 confers standing and
        anything greater is refused with `ERR_OUTSIDE_RELEVANT_MARKET`." From the
        origin the point (14.4, 19.2) lies at 24.00 km and (18, 24) at 30.00 km.

        Design: Corner/calculations/relevant_market_radius_inclusive_at_twentyfour_km
        """
        ctx = fx.setup_licensed_dealer()
        dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]
        near = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-11-30",
            site_x_km=14.4, site_y_km=19.2)
        far = fx.open_additional_point_filing(
            manufacturer["id"], proposed_effective_on="2026-11-30",
            site_x_km=18, site_y_km=24)
        near = fx.serve_notice(near["id"], manufacturer["id"])
        far = fx.serve_notice(far["id"], manufacturer["id"])

        refused = api.create_protest(
            f.protest_payload(far["id"], dealer["id"], far["version"],
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(dealer["id"]))
        validate_error(refused, ApiErrorId.ERR_OUTSIDE_RELEVANT_MARKET.value,
                       expected_status=422)
        after_far = fx.read_filing(far["id"])
        assert after_far["status"] == "NOTICE_SERVED"
        assert after_far["active_protest_count"] == 0
        _, meta = validate_paginated(api.list_protests(BOARD_ADMIN))
        assert meta["total_count"] == 0

        admitted = get_success_data(api.create_protest(
            f.protest_payload(near["id"], dealer["id"], near["version"],
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(dealer["id"])), 201)

        assert admitted["distance_to_site_km"] == 24.00
        assert admitted["status"] == "FILED"
        after_near = fx.read_filing(near["id"])
        assert after_near["status"] == "PROTEST_PENDING"
        assert after_near["active_protest_count"] == 1


class TestControllingStudySelection:
    def test_a_zero_divisor_study_cannot_displace_the_probative_one(self, api):
        """PRD 3.7: "Where `total_market_registrations` is zero there is no divisor,
        so `actual_penetration_pct` is 0.00 and `is_probative` is false; otherwise
        `actual_penetration_pct` is 100 multiplied by `line_make_registrations`,
        divided by `total_market_registrations`, rounded half up to two decimals, and
        `is_probative` is true." PRD 3.7: "A non-probative study is stored but is
        excluded from good-cause scoring entirely, which is what stops a party from
        displacing its own controlling study with a zero-divisor filing." The later
        study would otherwise control, because PRD 3.7 ranks newest first: "For each
        party the server first selects that party's *controlling* study among its
        probative studies only, ranking candidates by `created_at` descending, then
        by `shortfall_pts` descending, then by `total_market_registrations`
        descending; the row identifier is never a ranking key."

        Design: Corner/calculations/non_probative_study_never_controls_good_cause_read
        """
        ctx = fx.setup_filed_additional_point_protest()
        protest, dealer = ctx["protest"], ctx["dealer"]

        probative = fx.tender_protestant_study(
            protest["id"], dealer["id"],
            total_market_registrations=40000, line_make_registrations=3200,
            statewide_line_make_share_pct=12.50,
            permanency_investment_cents=250000000,
            consumer_access_drive_minutes=22, market_growth_pct=8.00)
        assert probative["is_probative"] is True
        assert probative["actual_penetration_pct"] == 8.00
        assert probative["expected_penetration_pct"] == 12.50
        assert probative["shortfall_pts"] == 4.50

        hollow = fx.tender_protestant_study(
            protest["id"], dealer["id"],
            total_market_registrations=0, line_make_registrations=0,
            statewide_line_make_share_pct=90.00,
            permanency_investment_cents=1000000000,
            consumer_access_drive_minutes=5, market_growth_pct=100.00)
        assert hollow["is_probative"] is False
        assert hollow["actual_penetration_pct"] == 0.00
        assert hollow["shortfall_pts"] == 90.00

        analysis = fx.read_good_cause_analysis(protest["id"])

        assert analysis["controlling_protestant_study_id"] == probative["id"]
        assert analysis["controlling_manufacturer_study_id"] is None
        assert analysis["net_shortfall_pts"] == 4.50
        assert analysis["inadequacy_component"] == 36.00
        assert analysis["investment_component"] == 100.00
        assert analysis["access_component"] == 50.00
        assert analysis["growth_component"] == 40.00
        assert analysis["good_cause_score"] == 55.40
        assert analysis["good_cause_threshold"] == 60.00
        assert analysis["good_cause_established"] is False


class TestSanctionLedgerArithmetic:
    def test_the_restitution_cap_binds_before_the_loss_linked_penalty(self, api):
        """PRD 3.9: "Note the ordering: the restitution cap binds before the penalty
        is computed, so a capped loss also caps the loss-linked half of the penalty,
        and both caps apply after the addition." PRD 3.9: "for every other sanction
        it is the allegation's base amount plus five percent of the restitution
        ordered, that loss-linked component rounded half up to a whole cent, with
        the sum then capped at 500,000 cents." An 1,800,000-cent loss is ordered at
        1,500,000, so the penalty is 200,000 plus 75,000 rather than the 290,000 an
        uncapped loss would carry.

        Design: Corner/calculations/restitution_cap_binds_before_loss_linked_penalty
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")

        complaint = fx.sanction_complaint(
            dealer["id"], "PROBATION", 1800000, "ODOMETER_MISREPRESENTATION")

        assert complaint["status"] == "SANCTIONED"
        assert complaint["restitution_ordered_cents"] == 1500000
        assert complaint["civil_penalty_cents"] == 275000
        assert complaint["civil_penalty_cents"] != 290000
        assert complaint["points_assessed"] == 6
        assert complaint["restitution_paid_cents"] == 0
        assert complaint["restitution_due_on"] == "2026-10-05"

        after = fx.read_dealer(dealer["id"])
        assert after["restitution_outstanding_cents"] == 1500000
        assert after["disciplinary_points"] == 6
        assert after["license_status"] == "LICENSED"

    def test_only_the_complaint_naming_the_salesperson_reaches_its_point_total(self, api):
        """PRD 3.3: "A salesperson's `disciplinary_points` is the sum of the points
        assessed by every complaint that names that salesperson and stands in either
        `SANCTIONED` or `CLOSED_SATISFIED`, counting only complaints whose sanction
        date falls on or after the day exactly 730 days before the reference date."
        PRD 3.9 pools the dealership's total over all of its own complaints: "A
        dealership's `disciplinary_points` is the sum of `points_assessed` across
        every one of its complaints standing in `SANCTIONED` or `CLOSED_SATISFIED`
        whose sanction date falls on or after the day exactly 730 days before the
        reference date". So a 3-point dealership-only sanction and a 6-point
        salesperson sanction give the dealership 9 and the salesperson 6.

        Design: Corner/calculations/salesperson_points_count_only_complaints_naming_that_salesperson
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-02T00:00:00Z")
        salesperson = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")

        fx.set_clock("2026-09-05T00:00:00Z")
        dealership_only = fx.sanction_complaint(
            dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
            findings_code="DEPOSIT_NOT_REFUNDED")
        assert dealership_only["points_assessed"] == 3
        assert dealership_only["civil_penalty_cents"] == 80000
        assert dealership_only["restitution_ordered_cents"] == 100000
        assert dealership_only["salesperson_id"] is None

        naming = fx.sanction_complaint(
            dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            salesperson_id=salesperson["id"],
            findings_code="MISLEADING_PRICE_ADVERTISING")

        assert naming["points_assessed"] == 6
        assert naming["civil_penalty_cents"] == 60000
        after_salesperson = fx.read_salesperson(salesperson["id"])
        assert after_salesperson["disciplinary_points"] == 6
        assert after_salesperson["discipline_status"] == "PROBATION"
        assert after_salesperson["license_status"] == "LICENSED"

        after_dealer = fx.read_dealer(dealer["id"])
        assert after_dealer["disciplinary_points"] == 9
        assert after_dealer["license_status"] == "LICENSED"
        assert after_dealer["restitution_outstanding_cents"] == 300000
        assert after_dealer["licensed_salesperson_count"] == 1
