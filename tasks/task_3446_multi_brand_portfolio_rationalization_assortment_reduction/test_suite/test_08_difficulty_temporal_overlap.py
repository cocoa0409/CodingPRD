"""Difficulty queue: resource temporal overlap — half-open capital-cycle
windows (adjacency allowed) versus closed negotiation effective windows (a
shared boundary day is already an overlap).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_brand_term,
    create_capital_cycle_payload,
    create_combined_negotiation_payload,
    create_retailer,
    validate_created,
    validate_error,
)

PM = TEST_USERS["portfolio_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestCapitalCycleHalfOpenWindowOverlap:
    def _create_c1(self):
        resp = api_client.create_capital_cycle(
            create_capital_cycle_payload(
                period_code="2026-H2",
                total_capital_cents=1000000000,
                window_start="2026-09-01T00:00:00Z",
                window_end="2027-03-01T00:00:00Z",
            ),
            FC,
        )
        return validate_created(resp)

    def test_adjacent_cycle_window_allowed(self):
        """PRD §3.7: "Overlap is tested under the half-open convention — two
        windows overlap when each starts before the other ends — so a new
        window that begins exactly when an existing window ends is adjacency,
        not overlap, and is allowed; a true overlap is rejected with
        `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/capital_cycle_half_open_window_overlap
        """
        self._create_c1()
        resp = api_client.create_capital_cycle(
            create_capital_cycle_payload(
                period_code="2027-H1",
                total_capital_cents=500000000,
                window_start="2027-03-01T00:00:00Z",  # == C1 window_end: adjacency
                window_end="2027-09-01T00:00:00Z",
            ),
            FC,
        )
        c2 = validate_created(resp)
        assert c2["cycle_status"] == "ALLOCATING"

    def test_intersecting_cycle_window_rejected(self):
        """PRD §3.7: "it must not overlap any existing cycle's window. Overlap
        is tested under the half-open convention — two windows overlap when
        each starts before the other ends".

        Design: Difficulty/resource_temporal_overlap/capital_cycle_half_open_window_overlap
        """
        self._create_c1()
        # [2027-02-01, 2027-08-01) starts before C1 ends (2027-03-01) and ends
        # after C1 starts -> true overlap under the half-open convention.
        resp = api_client.create_capital_cycle(
            create_capital_cycle_payload(
                period_code="2027-X1",
                total_capital_cents=1000,
                window_start="2027-02-01T00:00:00Z",
                window_end="2027-08-01T00:00:00Z",
            ),
            FC,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)


class TestNegotiationClosedWindowOverlap:
    def _setup_retailer_and_n1(self):
        """Retailer with two ACTIVE brands and negotiation N1 (period 2026-H2)
        effective over the CLOSED interval [2026-09-01, 2026-12-31]."""
        retailer = create_retailer(risk_rating="MEDIUM")
        brand1 = create_brand(private_label_share_pct=40)
        brand2 = create_brand(private_label_share_pct=10,
                              annual_net_revenue_cents=500000000)
        terms = [create_brand_term(brand1["id"], 100, 90),
                 create_brand_term(brand2["id"], 60, 50)]
        resp = api_client.create_combined_negotiation(
            create_combined_negotiation_payload(
                retailer["id"], terms,
                period_code="2026-H2",
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-12-31T00:00:00Z",
            ),
            PM,
        )
        n1 = validate_created(resp)
        assert n1["negotiation_status"] == "TERMS_PROPOSED", "Setup failed"
        return retailer, brand1, brand2

    def test_shared_boundary_day_counts_as_overlap(self):
        """PRD §3.6: "the closed interval from `effective_from` through
        `effective_to` must not overlap any other negotiation of the same
        retailer in `TERMS_PROPOSED` or `ACCEPTED`; overlap is tested
        inclusively, so two windows that share even a single boundary day count
        as overlapping, and a violation is rejected with
        `ERR_NEGOTIATION_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/negotiation_closed_window_shared_day_overlap
        """
        retailer, brand1, brand2 = self._setup_retailer_and_n1()
        terms = [create_brand_term(brand1["id"], 100, 90),
                 create_brand_term(brand2["id"], 60, 50)]
        # Starts ON N1's closed end day 2026-12-31 -> shared day -> overlap.
        resp = api_client.create_combined_negotiation(
            create_combined_negotiation_payload(
                retailer["id"], terms,
                period_code="2027-H1",
                effective_from="2026-12-31T00:00:00Z",
                effective_to="2027-03-31T00:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_WINDOW_OVERLAP)

    def test_day_after_closed_window_end_allowed(self):
        """PRD §3.6: "overlap is tested inclusively, so two windows that share
        even a single boundary day count as overlapping".

        Design: Difficulty/resource_temporal_overlap/negotiation_closed_window_shared_day_overlap
        """
        retailer, brand1, brand2 = self._setup_retailer_and_n1()
        terms = [create_brand_term(brand1["id"], 100, 90),
                 create_brand_term(brand2["id"], 60, 50)]
        # Starts the day AFTER N1's closed end -> no shared day -> no overlap.
        resp = api_client.create_combined_negotiation(
            create_combined_negotiation_payload(
                retailer["id"], terms,
                period_code="2027-H1",
                effective_from="2027-01-01T00:00:00Z",
                effective_to="2027-03-31T00:00:00Z",
            ),
            PM,
        )
        n3 = validate_created(resp)
        assert n3["negotiation_status"] == "TERMS_PROPOSED"
