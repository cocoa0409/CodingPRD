"""Temporal overlap tests: half-open outage intervals vs closed host-agreement
intervals."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_boiler,
    make_host_municipality,
    make_host_agreement,
    create_outage_window_payload,
    create_host_community_agreement_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


class TestOutageWindowsHalfOpenAdjacency:
    def test_touching_windows_allowed_but_straddling_window_rejected(self):
        """PRD §3.4: "Two windows for the same boiler must not overlap while either is `SCHEDULED` or `ACTIVE`; the intervals are half-open, so back-to-back outages — one window's `ends_at` exactly equal to the other's `starts_at` — are allowed, and any true overlap is rejected with `ERR_OUTAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_windows_half_open_adjacency
        """
        boiler = make_boiler()
        get_success_data(
            api_client.create_outage_window(
                create_outage_window_payload(
                    boiler_id=boiler["id"],
                    starts_at="2026-09-05T00:00:00Z",
                    ends_at="2026-09-10T00:00:00Z",
                    reason="S1",
                ),
                PO,
            )
        )
        # Touching at the boundary: ends_at of S1 == starts_at of S2 — allowed.
        s2 = validate_success(
            api_client.create_outage_window(
                create_outage_window_payload(
                    boiler_id=boiler["id"],
                    starts_at="2026-09-10T00:00:00Z",
                    ends_at="2026-09-12T00:00:00Z",
                    reason="S2",
                ),
                PO,
            ),
            expected_status=201,
        )
        assert s2["status"] == "SCHEDULED"

        # Straddling the S1/S2 boundary: true overlap.
        resp = api_client.create_outage_window(
            create_outage_window_payload(
                boiler_id=boiler["id"],
                starts_at="2026-09-09T23:00:00Z",
                ends_at="2026-09-11T00:00:00Z",
                reason="S3",
                kind="EMERGENCY",
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_OUTAGE_OVERLAP)

    def test_contained_window_is_an_overlap(self):
        """PRD §3.4: "the intervals are half-open, so back-to-back outages — one window's `ends_at` exactly equal to the other's `starts_at` — are allowed, and any true overlap is rejected with `ERR_OUTAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_windows_half_open_adjacency
        """
        boiler = make_boiler()
        get_success_data(
            api_client.create_outage_window(
                create_outage_window_payload(
                    boiler_id=boiler["id"],
                    starts_at="2026-09-05T00:00:00Z",
                    ends_at="2026-09-10T00:00:00Z",
                    reason="S1",
                ),
                PO,
            )
        )
        # Fully contained inside S1.
        resp = api_client.create_outage_window(
            create_outage_window_payload(
                boiler_id=boiler["id"],
                starts_at="2026-09-06T00:00:00Z",
                ends_at="2026-09-08T00:00:00Z",
                reason="contained",
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_OUTAGE_OVERLAP)


class TestHostAgreementClosedIntervalTouchingIsOverlap:
    def test_touching_effective_windows_are_an_overlap(self):
        """PRD §3.1: "Only one host agreement may be in force for a municipality at a time: the effective windows of a municipality's host agreements must not overlap, and these intervals are treated as closed on both ends — `effective_end` is inclusive — so a new agreement whose `effective_start` equals an existing agreement's `effective_end` *is* an overlap and is rejected with `ERR_HOST_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/host_agreement_closed_interval_touching_is_overlap
        """
        h1 = make_host_municipality()
        make_host_agreement(
            h1["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-12-31T00:00:00Z",
        )
        resp = api_client.create_host_community_agreement(
            create_host_community_agreement_payload(
                municipality_id=h1["id"],
                annual_payment_cents=52000000,
                effective_start="2026-12-31T00:00:00Z",
                effective_end="2027-12-31T00:00:00Z",
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_HOST_AGREEMENT_OVERLAP)

    def test_disjoint_effective_windows_are_allowed(self):
        """PRD §3.1: "Only one host agreement may be in force for a municipality at a time: the effective windows of a municipality's host agreements must not overlap, and these intervals are treated as closed on both ends — `effective_end` is inclusive — so a new agreement whose `effective_start` equals an existing agreement's `effective_end` *is* an overlap and is rejected with `ERR_HOST_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/host_agreement_closed_interval_touching_is_overlap
        """
        h1 = make_host_municipality()
        make_host_agreement(
            h1["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-12-31T00:00:00Z",
        )
        # Starts one second after the existing window closes: disjoint.
        created = validate_success(
            api_client.create_host_community_agreement(
                create_host_community_agreement_payload(
                    municipality_id=h1["id"],
                    annual_payment_cents=52000000,
                    effective_start="2026-12-31T00:00:01Z",
                    effective_end="2027-12-31T00:00:00Z",
                ),
                CM,
            ),
            expected_status=201,
        )
        assert created["municipality_id"] == h1["id"]
