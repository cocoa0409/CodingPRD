"""Publications: lazy circulation derivation, ad cost rounding, and the
half-open term-coverage boundary."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household_with_term, cancel_term_ok, get_household,
    create_publication_ok, get_publication,
    create_ad_booking_payload,
)

STD = TEST_USERS["standards_reviewer_headers"]
MSA = TEST_USERS["member_services_headers"]


class TestCirculationRecompute:
    def test_publication_circulation_recomputed_after_cancel(self, api):
        """PRD §3.7: "An issue's `circulation_count` is derived, never stored
        as a mutable figure: it counts the distinct households holding at
        least one membership term in `ACTIVE` or `RENEWED` status whose
        window covers the issue's `publication_date`". PRD §3.7: "The count
        is recomputed on every read of the publication and at every booking."
        PRD §3.7: "`CANCELLED` or `LAPSED` terms never cover, regardless of
        when they flipped."

        Design: Corner/entities/publication_circulation_recomputed_after_cancel
        """
        set_clock()
        hh_a, term_a, _ = create_household_with_term(
            state_code="ME", term_years=1, primary_full_name="Gus Gow",
            primary_date_of_birth="1969-09-09")
        create_household_with_term(
            state_code="ME", term_years=3, primary_full_name="Hal Hume",
            primary_date_of_birth="1961-01-01")
        publication = create_publication_ok(
            title="October Issue", publication_date="2026-10-01")

        assert get_publication(publication["id"])["circulation_count"] == 2
        cancel_term_ok(term_a["id"], "VOLUNTARY")
        assert get_publication(publication["id"])["circulation_count"] == 1


class TestAdCostEstimate:
    def test_ad_cost_estimate_rounding_half_up(self, api):
        """PRD §3.7: "The booking's `estimated_cost_cents` is then the agreed
        rate times the current circulation, divided by one thousand, rounded
        half up once to integer cents — evaluated once, at booking time,
        against the circulation at that moment".

        Design: Corner/calculations/ad_cost_estimate_rounding_half_up
        """
        set_clock()
        for name, dob in (("Sal Sudd", "1963-03-03"), ("Tess Todd", "1961-01-01"),
                          ("Uma Uhl", "1971-11-11")):
            create_household_with_term(
                state_code="MS", term_years=1, primary_full_name=name,
                primary_date_of_birth=dob)
        publication = create_publication_ok(
            title="Autumn Issue", publication_date="2026-10-01")
        assert get_publication(publication["id"])["circulation_count"] == 3

        payload = create_ad_booking_payload(
            advertiser_name="Riverboat Tours", category="TRAVEL",
            agreed_cpm_cents=2500)
        booking = validate_success(
            api.create_ad_booking(publication["id"], payload, STD),
            expected_status=201)
        # round_half_up(2500 * 3 / 1000) = round_half_up(7.5) = 8.
        assert booking["estimated_cost_cents"] == 8
        assert booking["status"] == "BOOKED"


class TestTermCoverageHalfOpenBoundary:
    def test_term_coverage_half_open_boundary(self, api):
        """PRD §3.1: "Coverage is a half-open window: the start date is
        covered and the end date is not." PRD §3.7: "Finally, an issue with a
        `circulation_count` of 0 has no audience to sell and rejects the
        booking with `ERR_NO_CIRCULATION_BASE` (HTTP 422) before any cost
        computation runs." PRD §3.2: "A household's `status` is a derived
        value, never stored as a mutable field: it is `ACTIVE` when at least
        one of the household's membership terms is itself `ACTIVE` and covers
        the current clock date — `start_date` on or before the clock date and
        the clock date strictly before `end_date` — and `LAPSED` otherwise."

        Design: Corner/state_machines/term_coverage_half_open_boundary
        """
        set_clock()
        hh, term, _member = create_household_with_term(
            state_code="KS", term_years=1, primary_full_name="Lou Lamm",
            primary_date_of_birth="1959-07-07", auto_renew_enabled=False)
        assert term["start_date"] == "2026-09-01"
        assert term["end_date"] == "2027-09-01"
        pub_early = create_publication_ok(
            title="Boundary Eve Issue", publication_date="2027-08-31")
        pub_boundary = create_publication_ok(
            title="Boundary Day Issue", publication_date="2027-09-01")

        # The renewal batch has NOT run: the term row still reads ACTIVE.
        set_clock("2027-09-01T00:00:00Z")
        assert get_publication(pub_early["id"])["circulation_count"] == 1
        assert get_publication(pub_boundary["id"])["circulation_count"] == 0

        payload = create_ad_booking_payload(
            advertiser_name="Sunset Cruises", category="TRAVEL",
            agreed_cpm_cents=3000)
        resp = api.create_ad_booking(pub_boundary["id"], payload, STD)
        validate_error(resp, ApiErrorId.ERR_NO_CIRCULATION_BASE)

        # Standing is coverage-derived: LAPSED at the end date even though
        # the term row has not been flipped by the sweep.
        assert get_household(hh["id"])["status"] == "LAPSED"
