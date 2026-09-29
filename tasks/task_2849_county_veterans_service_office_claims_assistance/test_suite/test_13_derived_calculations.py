"""
The derived numbers: workload points, the ledger, the two ceilings and the clock.

Each family here is exercised at the exact cent or the exact day where the
comparison the PRD declares changes its answer.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    assert_caseload_decomposition,
    assert_caseload_weight,
    assert_category_eligible,
    assert_cents,
    assert_exact_whole,
    assert_screen_categories,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_counseled_review,
    create_represented_veteran,
    create_verified_veteran,
    elect_review_action,
    file_review_action,
    make_county_officer_headers,
    make_veteran_client_headers,
    offer_designation,
    read_caseload,
    read_decision_review,
    read_representative,
    read_veteran,
    screen_veteran,
    set_clock,
    set_clock_date,
    validate_error,
    validate_success,
    veteran_version,
)

WARTIME_TOUR = {
    "date_of_birth": "1979-03-04",
    "service_start_date": "2001-09-11",
    "service_end_date": "2005-09-10",
}


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


class TestCaseloadWeightDecomposition:
    """One designation and one claim in development make four points."""

    @pytest.fixture
    def one_open_claim(self, api):
        """A representative holding a single claim in EVIDENCE_DEVELOPMENT."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        ctx = create_claim_in_evidence_development(
            api,
            create_represented_veteran(api, designee=rep),
            claimed_conditions=conditions("tinnitus"),
        )
        return {"rep_id": rep["id"], "ctx": ctx}

    def test_the_designation_and_the_open_claim_sum_to_four_points(
        self, api, one_open_claim
    ):
        """
        "Each of the representative's `ACTIVE` designations contributes 1 point."
        "Each claim hanging off one of those designations contributes points according to the stage it is in: 3 points while in `EVIDENCE_DEVELOPMENT`, 5 points while in `PEER_REVIEW`, 2 points while in `READY_TO_FILE`, and 4 points while in `FILED`."

        Design: Corner/calculations/corner_caseload_weight_sums_designation_and_claim_stage_points
        """
        assert one_open_claim["ctx"]["claim"]["status"] == "EVIDENCE_DEVELOPMENT"
        assert_caseload_decomposition(
            read_caseload(api, one_open_claim["rep_id"]),
            representative_id=one_open_claim["rep_id"],
            active_poa_count=1,
            open_claim_count=1,
            planned_outreach_count=0,
            caseload_weight=4,
        )
        assert_caseload_weight(
            read_representative(api, one_open_claim["rep_id"])["caseload_weight"], 4
        )

    def test_the_workload_read_reports_the_row_as_assignment_eligible(
        self, api, one_open_claim
    ):
        """
        "Omitting it invokes the automatic selector, which builds its candidate set from the roster by three filters applied together: the representative's `accreditation_status` must be `ACTIVE`; their `accreditation_type` must be `COUNTY_CVSO` or `VSO_ORG`, so an `ATTORNEY` or a `CLAIMS_AGENT` is never auto-assigned however light their load; and their `active_poa_count` must be strictly less than 40."

        Design: Corner/calculations/corner_caseload_weight_sums_designation_and_claim_stage_points
        """
        decomposition = read_caseload(api, one_open_claim["rep_id"])
        assert decomposition["assignment_eligible"] is True
        stored = read_representative(api, one_open_claim["rep_id"])
        assert stored["accreditation_status"] == "ACTIVE"
        assert stored["accreditation_type"] == "COUNTY_CVSO"
        assert_exact_whole(stored["active_poa_count"], 1, "active_poa_count")


class TestActiveDesignationLedger:
    """An offer exists as a row and counts for nothing until it is accepted."""

    @pytest.fixture
    def offered_designation(self, api):
        """A verified veteran with one designation still sitting in OFFERED."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(rep["id"])
        built = create_verified_veteran(api, officer_headers, **WARTIME_TOUR)
        poa = offer_designation(api, built["veteran"]["id"], rep["id"])
        return {"rep_id": rep["id"], "veteran_id": built["veteran"]["id"], "poa": poa}

    def test_an_offered_designation_is_outside_the_ledger(self, api, offered_designation):
        """
        "A representative's `active_poa_count` equals the count of powers of attorney whose `representative_id` is that representative and whose `status` is `ACTIVE`."
        "Designations in `OFFERED`, `REVOKED` or `SUPERSEDED` are excluded."

        Design: Corner/calculations/corner_active_poa_ledger_counts_only_accepted_designations
        """
        assert offered_designation["poa"]["status"] == "OFFERED"
        stored = read_representative(api, offered_designation["rep_id"])
        assert_exact_whole(stored["active_poa_count"], 0, "active_poa_count")
        assert_caseload_weight(stored["caseload_weight"], 0)

    def test_acceptance_moves_the_row_into_the_ledger(self, api, offered_designation):
        """
        "Acceptance then sets `status` to `ACTIVE`, stamps `accepted_at` with the logical-clock instant, increments the designated representative's `active_poa_count` by 1, and increments the veteran's `version` by 1 — which is exactly why a client holding a stale version number loses the race."

        Design: Corner/calculations/corner_active_poa_ledger_counts_only_accepted_designations
        """
        veteran_id = offered_designation["veteran_id"]
        accepted = validate_success(
            api.accept_power_of_attorney(
                offered_designation["poa"]["id"],
                {"expected_veteran_version": veteran_version(api, veteran_id)},
                make_veteran_client_headers(veteran_id),
            ),
            200,
        )
        assert accepted["status"] == "ACTIVE"
        stored = read_representative(api, offered_designation["rep_id"])
        assert_exact_whole(stored["active_poa_count"], 1, "active_poa_count")
        assert_caseload_weight(stored["caseload_weight"], 1)


class TestPensionNetWorthCeiling:
    """The net-worth ceiling is inclusive, so the last cent still qualifies."""

    @pytest.fixture
    def two_net_worth_neighbours(self, api):
        """Two identical wartime veterans one cent apart in net worth."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        at_ceiling = create_verified_veteran(
            api,
            officer_headers,
            household_income_cents=1500000,
            net_worth_cents=15506000,
            dependent_count=0,
            homeless_status="NOT_HOMELESS",
            **WARTIME_TOUR,
        )
        over_ceiling = create_verified_veteran(
            api,
            officer_headers,
            household_income_cents=1500000,
            net_worth_cents=15506001,
            dependent_count=0,
            homeless_status="NOT_HOMELESS",
            **WARTIME_TOUR,
        )
        return {
            "at": screen_veteran(api, at_ceiling["veteran"]["id"], officer_headers),
            "over": screen_veteran(api, over_ceiling["veteran"]["id"], officer_headers),
            "at_veteran_id": at_ceiling["veteran"]["id"],
            "over_veteran_id": over_ceiling["veteran"]["id"],
        }

    def test_a_net_worth_exactly_at_the_ceiling_still_screens_pension_eligible(
        self, api, two_net_worth_neighbours
    ):
        """
        "`PENSION` is eligible when basic eligibility holds **and** the veteran's `wartime_service_days` is at least 90 days **and** `household_income_cents` is at most the income ceiling described above **and** `net_worth_cents` is at most one hundred fifty-five thousand sixty dollars, that is 15506000 cents."

        Design: Corner/calculations/corner_pension_screen_applies_the_net_worth_limit_constant_exactly
        """
        screen = two_net_worth_neighbours["at"]
        assert screen["basic_eligibility"] is True
        assert_exact_whole(
            screen["wartime_service_days_at_screen"], 1461, "wartime_service_days_at_screen"
        )
        assert_screen_categories(screen)
        assert_category_eligible(screen, "PENSION", True)
        assert_exact_whole(
            read_veteran(api, two_net_worth_neighbours["at_veteran_id"])[
                "wartime_service_days"
            ],
            1461,
            "wartime_service_days",
        )

    def test_one_cent_over_the_ceiling_names_net_worth_as_the_reason(
        self, api, two_net_worth_neighbours
    ):
        """
        "For every category that comes out false, the `reason` string names the leftmost condition in that category's list that failed — so a living veteran with honourable service gets `intake_status` named as the reason on `BURIAL_BENEFIT`, while a veteran with an other-than-honourable discharge gets the basic-eligibility conjunct named on all six."

        Design: Corner/calculations/corner_pension_screen_applies_the_net_worth_limit_constant_exactly
        """
        screen = two_net_worth_neighbours["over"]
        assert_screen_categories(screen)
        assert_category_eligible(screen, "PENSION", False)
        assert "net_worth_cents" in screen["category_results"]["PENSION"]["reason"]

    def test_the_disability_category_is_untouched_and_the_counts_differ_by_one(
        self, api, two_net_worth_neighbours
    ):
        """
        "`DISABILITY_COMPENSATION` is eligible exactly when basic eligibility holds."
        "`eligible_category_count` is simply how many of the six keys came out true, a value from 0 through 6."

        Design: Corner/calculations/corner_pension_screen_applies_the_net_worth_limit_constant_exactly
        """
        at_screen = two_net_worth_neighbours["at"]
        over_screen = two_net_worth_neighbours["over"]
        assert_category_eligible(at_screen, "DISABILITY_COMPENSATION", True)
        assert_category_eligible(over_screen, "DISABILITY_COMPENSATION", True)
        assert_exact_whole(
            at_screen["eligible_category_count"],
            over_screen["eligible_category_count"] + 1,
            "eligible_category_count",
        )


class TestPriorityGroupIncomeCeiling:
    """Two dependents lift the ceiling to 2850000, and the last cent is inside it."""

    @pytest.fixture
    def two_income_neighbours(self, api):
        """Two veterans with two dependents each, one cent apart in income."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        at_ceiling = create_verified_veteran(
            api,
            officer_headers,
            household_income_cents=2850000,
            net_worth_cents=2000000,
            dependent_count=2,
            homeless_status="NOT_HOMELESS",
            **WARTIME_TOUR,
        )
        over_ceiling = create_verified_veteran(
            api,
            officer_headers,
            household_income_cents=2850001,
            net_worth_cents=2000000,
            dependent_count=2,
            homeless_status="NOT_HOMELESS",
            **WARTIME_TOUR,
        )
        return {
            "at": screen_veteran(api, at_ceiling["veteran"]["id"], officer_headers),
            "over": screen_veteran(api, over_ceiling["veteran"]["id"], officer_headers),
            "at_veteran_id": at_ceiling["veteran"]["id"],
            "over_veteran_id": over_ceiling["veteran"]["id"],
        }

    def test_income_exactly_at_the_ceiling_bands_the_veteran_p3(
        self, api, two_income_neighbours
    ):
        """
        "Failing that, they land in `P3` when `household_income_cents` is at most the income ceiling for their dependent count."
        "`income_limit_applied_cents` is the countable-income ceiling in force at screen time: eighteen thousand eight hundred forty dollars — 1884000 cents — plus four thousand eight hundred thirty dollars, or 483000 cents, for each dependent claimed."

        Design: Corner/calculations/corner_priority_group_income_limit_is_inclusive_at_the_exact_cent
        """
        screen = two_income_neighbours["at"]
        assert_cents(screen["income_limit_applied_cents"], 2850000)
        assert screen["priority_group_assigned"] == "P3"
        assert read_veteran(api, two_income_neighbours["at_veteran_id"])[
            "priority_group"
        ] == "P3"

    def test_one_cent_over_the_ceiling_falls_through_to_p4(
        self, api, two_income_neighbours
    ):
        """
        "Failing all three, they land in `P4`, which is also the value a brand-new intake starts at."
        "Priority banding is evaluated strictly top to bottom, and the first branch that matches wins; the branches are not independent tests."

        Design: Corner/calculations/corner_priority_group_income_limit_is_inclusive_at_the_exact_cent
        """
        screen = two_income_neighbours["over"]
        assert_cents(screen["income_limit_applied_cents"], 2850000)
        assert screen["priority_group_assigned"] == "P4"
        assert read_veteran(api, two_income_neighbours["over_veteran_id"])[
            "priority_group"
        ] == "P4"


class TestWartimeDayCountIsInclusive:
    """Ninety days is reached only because both endpoints are counted."""

    @pytest.fixture
    def three_tours(self, api):
        """Three verified documents: ninety days, eighty-nine, and none at all."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        ninety = create_verified_veteran(
            api,
            officer_headers,
            document_kwargs={
                "claimed_service_start": "2001-09-11",
                "claimed_service_end": "2001-12-09",
            },
            date_of_birth="1979-03-04",
            service_start_date="2001-09-11",
            service_end_date="2001-12-09",
        )
        eighty_nine = create_verified_veteran(
            api,
            officer_headers,
            document_kwargs={
                "claimed_service_start": "2001-09-11",
                "claimed_service_end": "2001-12-08",
            },
            date_of_birth="1979-03-04",
            service_start_date="2001-09-11",
            service_end_date="2001-12-08",
        )
        peacetime = create_verified_veteran(
            api,
            officer_headers,
            document_kwargs={
                "claimed_service_start": "1980-01-01",
                "claimed_service_end": "1985-01-01",
            },
            date_of_birth="1960-05-05",
            service_start_date="1980-01-01",
            service_end_date="1985-01-01",
        )
        return {
            "ninety": ninety["veteran"],
            "eighty_nine": eighty_nine["veteran"],
            "peacetime": peacetime["veteran"],
        }

    def test_ninety_days_is_reached_by_counting_both_endpoints(self, api, three_tours):
        """
        "For each window in turn, take the later of the document's `claimed_service_start` and the window's opening date, and the earlier of the document's `claimed_service_end` and the window's closing date."
        "`wartime_service_days` is the sum of those contributions across all three windows."

        Design: Corner/calculations/corner_wartime_day_count_is_inclusive_of_both_endpoints
        """
        stored = read_veteran(api, three_tours["ninety"]["id"])
        assert_exact_whole(stored["wartime_service_days"], 90, "wartime_service_days")

    def test_one_day_short_of_the_window_counts_eighty_nine(self, api, three_tours):
        """
        "Because the three windows never overlap one another, no single day of service can be counted twice, and no rounding is ever involved: the result is a whole number of days."

        Design: Corner/calculations/corner_wartime_day_count_is_inclusive_of_both_endpoints
        """
        stored = read_veteran(api, three_tours["eighty_nine"]["id"])
        assert_exact_whole(stored["wartime_service_days"], 89, "wartime_service_days")

    def test_a_tour_outside_every_window_counts_nothing(self, api, three_tours):
        """
        "The count is taken against three fixed statutory wartime windows, evaluated in this order: 28 February 1961 through 7 May 1975, 2 August 1990 through 11 April 1991, and 11 September 2001 through 30 August 2021."

        Design: Corner/calculations/corner_wartime_day_count_is_inclusive_of_both_endpoints
        """
        stored = read_veteran(api, three_tours["peacetime"]["id"])
        assert_exact_whole(stored["wartime_service_days"], 0, "wartime_service_days")


class TestAppealDeadlineArithmetic:
    """Three hundred sixty-five days from the notice, re-derived on every read."""

    @pytest.fixture
    def counseled_review(self, api):
        """A claim decided on the clock's opening date with one counselled review."""
        ctx = create_counseled_review(api)
        return {
            "review": ctx["review"],
            "officer_headers": ctx["officer_headers"],
        }

    def test_the_deadline_is_the_notice_date_plus_three_hundred_sixty_five_days(
        self, api, counseled_review
    ):
        """
        "The server copies `decision_notice_date` from the claim's `decided_on` **once, at creation**, and never refreshes it afterwards; a claim that has been reopened to `FILED` has no current decision and cannot anchor a new review until it is decided again."
        "`deadline_on` is `decision_notice_date` plus 365 days."

        Design: Corner/calculations/corner_appeal_deadline_is_the_decision_date_plus_three_hundred_sixty_five_days
        """
        review = counseled_review["review"]
        assert review["decision_notice_date"] == "2026-08-01"
        assert review["deadline_on"] == "2027-08-01"
        assert_exact_whole(review["days_remaining"], 365, "days_remaining")
        assert review["status"] == "COUNSELED"

    def test_the_deadline_day_itself_still_admits_an_election(self, api, counseled_review):
        """
        "There is no grace period: `days_remaining` of exactly 0 means the deadline is today and the lane may still be elected or filed, while −1 is the first day on which it may not."

        Design: Corner/calculations/corner_appeal_deadline_is_the_decision_date_plus_three_hundred_sixty_five_days
        """
        set_clock_date(api, "2027-08-01", "09:00:00")
        assert_exact_whole(
            read_decision_review(api, counseled_review["review"]["id"])["days_remaining"],
            0,
            "days_remaining",
        )
        elected = validate_success(
            api.decision_review_status(
                counseled_review["review"]["id"],
                elect_review_action("2027-08-01"),
                counseled_review["officer_headers"],
            ),
            200,
        )
        assert elected["status"] == "ELECTED"
        assert elected["elected_on"] == "2027-08-01"

    def test_the_first_negative_day_refuses_the_filing(self, api, counseled_review):
        """
        "`days_remaining` is `deadline_on` minus the logical-clock date in whole days, and it is **re-derived on every read**, so moving the logical clock changes what a read reports without any write having occurred."
        "Either election or filing attempted once `days_remaining` has gone negative is refused with `ERR_APPEAL_DEADLINE_PASSED` at HTTP 409."

        Design: Corner/calculations/corner_appeal_deadline_is_the_decision_date_plus_three_hundred_sixty_five_days
        """
        review_id = counseled_review["review"]["id"]
        set_clock_date(api, "2027-08-01", "09:00:00")
        validate_success(
            api.decision_review_status(
                review_id,
                elect_review_action("2027-08-01"),
                counseled_review["officer_headers"],
            ),
            200,
        )
        set_clock_date(api, "2027-08-02", "09:00:00")
        assert_exact_whole(
            read_decision_review(api, review_id)["days_remaining"], -1, "days_remaining"
        )
        validate_error(
            api.decision_review_status(
                review_id,
                file_review_action("2027-08-02"),
                counseled_review["officer_headers"],
            ),
            "ERR_APPEAL_DEADLINE_PASSED",
            409,
        )
        stored = read_decision_review(api, review_id)
        assert stored["status"] == "ELECTED"
        assert stored["filed_on"] is None
