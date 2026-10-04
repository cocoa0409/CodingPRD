"""Pools, loans, and engagements: composition gates, note-rate bands,
insurance rules, half-open engagement windows, OCC on pool creation."""
import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    assert_pool,
    create_engagement_payload,
    create_pool_payload,
    get_issuer,
    get_pool,
    get_success_data,
    make_document_custodian_headers,
    make_issuer_officer_headers,
    set_clock,
    setup_draft_pool_with_loans,
    setup_issuer_with_engagement,
    setup_live_pool,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestLoanNoteRateBand:
    def test_boundary_rates_accepted_and_outside_rejected(self, api):
        """PRD §3.3: "The loan's note rate must sit within a band above the
        security's note rate — at least 50 basis points above the pool's
        `note_rate_bps` and at most 150 basis points above it, both bounds
        inclusive; a loan outside the band is rejected with
        `ERR_LOAN_NOTE_RATE_OUT_OF_RANGE`."

        Design: Corner/validations/loan_note_rate_range_inclusive
        """
        set_clock()
        issuer, custodian, _ = setup_issuer_with_engagement("officer-rng")
        pool = get_success_data(api.create_pool(
            create_pool_payload(issuer["id"], custodian["id"], get_issuer(issuer["id"])["version"]),
            make_issuer_officer_headers(issuer["id"])))
        headers = make_issuer_officer_headers(issuer["id"])

        resp_low = api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 1000000,
             "note_rate_bps": 749, "government_insurance": "FHA", "escrow_monthly_cents": 1000},
            headers)
        validate_error(resp_low, ApiErrorId.ERR_LOAN_NOTE_RATE_OUT_OF_RANGE)

        ok_low = validate_success(api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 1000000,
             "note_rate_bps": 750, "government_insurance": "FHA", "escrow_monthly_cents": 1000},
            headers), expected_status=201)
        assert ok_low["note_rate_bps"] == 750

        ok_high = validate_success(api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 1000000,
             "note_rate_bps": 850, "government_insurance": "VA", "escrow_monthly_cents": 1000},
            headers), expected_status=201)
        assert ok_high["note_rate_bps"] == 850

        resp_high = api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 1000000,
             "note_rate_bps": 851, "government_insurance": "VA", "escrow_monthly_cents": 1000},
            headers)
        validate_error(resp_high, ApiErrorId.ERR_LOAN_NOTE_RATE_OUT_OF_RANGE)


class TestMultifamilyInsurance:
    def test_multifamily_requires_fha(self, api):
        """PRD §3.3: "The insurance program must be allowed for the pool type:
        a `MULTIFAMILY` pool accepts only `FHA` loans, and any other program
        there is rejected with `ERR_INSURER_NOT_ALLOWED`."

        Design: Corner/validations/multifamily_requires_fha_insurance
        """
        set_clock()
        issuer, custodian, _ = setup_issuer_with_engagement("officer-mf")
        pool = get_success_data(api.create_pool(
            create_pool_payload(
                issuer["id"], custodian["id"], get_issuer(issuer["id"])["version"],
                pool_type="MULTIFAMILY", term_months=360, note_rate_bps=700),
            make_issuer_officer_headers(issuer["id"])))
        headers = make_issuer_officer_headers(issuer["id"])
        resp_va = api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 60000000,
             "note_rate_bps": 800, "government_insurance": "VA", "escrow_monthly_cents": 1000},
            headers)
        validate_error(resp_va, ApiErrorId.ERR_INSURER_NOT_ALLOWED)
        ok_fha = validate_success(api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 60000000,
             "note_rate_bps": 800, "government_insurance": "FHA", "escrow_monthly_cents": 1000},
            headers), expected_status=201)
        assert ok_fha["government_insurance"] == "FHA"
        assert ok_fha["pool_id"] == pool["id"]


class TestPoolComputedFields:
    def test_draft_pool_computed_aggregate_fields(self, api):
        """PRD §3.3: "Each accepted loan starts in `CURRENT` status and
        triggers recomputation of the pool's read-only
        `aggregate_principal_cents` and `delinquency_rate_bps`."
        PRD §3.7: "when the denominator is zero the rate is zero" — and with
        no delinquent loans the numerator is zero, so the rate is zero.

        Design: Corner/entities/pool_get_returns_computed_aggregate_fields
        """
        set_clock()
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-cf",
            [dict(principal_balance_cents=1200000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=1200000, note_rate_bps=810, government_insurance="VA")],
        )
        data = validate_success(api.get_pool(pool["id"], TEST_USERS["platform_admin_headers"]))
        assert_pool(data)
        assert data["aggregate_principal_cents"] == 2400000
        assert data["delinquency_rate_bps"] == 0
        assert data["status"] == "DRAFT"


class TestPoolComposition:
    def test_assemble_with_exactly_three_loans_succeeds_and_loans_locked_after(self, api):
        """PRD §3.3: "Loans join a pool while it is in `DRAFT`."
        PRD §3.3: "the loan count must not exceed the per-type cap — three
        loans for `SINGLE_FAMILY`, three for `MANUFACTURED_HOME`, and two for
        `MULTIFAMILY` (else `ERR_POOL_LOAN_COUNT_EXCEEDED`)."

        Design: Corner/calculations/pool_composition_loan_count_threshold
        """
        set_clock()
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-comp",
            [dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="VA"),
             dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="USDA")],
        )
        assembled = validate_success(
            api.assemble_pool(pool["id"], make_issuer_officer_headers(issuer["id"])))
        assert assembled["status"] == "ASSEMBLED"
        # Loan creation is DRAFT-only: a 4th loan cannot be added now.
        resp = api.create_loan(
            {"pool_id": pool["id"], "principal_balance_cents": 40000000,
             "note_rate_bps": 800, "government_insurance": "FHA", "escrow_monthly_cents": 20000},
            make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)


class TestEngagementWindows:
    def test_touching_windows_allowed_overlapping_rejected(self, api):
        """PRD §3.2: "Two active engagements on the same custodian-and-issuer
        pair must have disjoint windows: windows that merely touch, where one
        engagement's `window_end` equals the other's `window_start`, are
        allowed, but any positive overlap is rejected with
        `ERR_ENGAGEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_touching_windows_allowed
        """
        set_clock()
        issuer, custodian, _ = setup_issuer_with_engagement("officer-int")
        headers = make_issuer_officer_headers(issuer["id"])
        # The setup engagement is [2026-01-01, 2027-01-01); end it so the
        # touching/overlap pair below is the only ACTIVE-window interplay.
        # Instead: create a fresh (custodian, issuer) pair via a second custodian.
        custodian2 = get_success_data(api.create_custodian(
            {"firm_name": "SecondVault Custody"}, TEST_USERS["platform_admin_headers"]))
        eng1 = validate_success(api.create_engagement(
            create_engagement_payload(custodian2["id"], issuer["id"],
                                      window_start="2026-01-01", window_end="2026-07-01"),
            headers), expected_status=201)
        assert eng1["status"] == "ACTIVE"
        # Touching: end == start is allowed.
        eng2 = validate_success(api.create_engagement(
            create_engagement_payload(custodian2["id"], issuer["id"],
                                      window_start="2026-07-01", window_end="2027-01-01"),
            headers), expected_status=201)
        assert eng2["status"] == "ACTIVE"
        # One-day overlap with eng1 is rejected.
        resp = api.create_engagement(
            create_engagement_payload(custodian2["id"], issuer["id"],
                                      window_start="2026-06-30", window_end="2026-12-01"),
            headers)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)

    def test_positive_overlap_rejected(self, api):
        """PRD §3.2: "Two active engagements on the same custodian-and-issuer
        pair must have disjoint windows: windows that merely touch, where one
        engagement's `window_end` equals the other's `window_start`, are
        allowed, but any positive overlap is rejected with
        `ERR_ENGAGEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_touching_windows_allowed
        """
        set_clock()
        issuer, custodian, _ = setup_issuer_with_engagement("officer-ovl")
        headers = make_issuer_officer_headers(issuer["id"])
        custodian2 = get_success_data(api.create_custodian(
            {"firm_name": "OverlapVault Custody"}, TEST_USERS["platform_admin_headers"]))
        get_success_data(api.create_engagement(
            create_engagement_payload(custodian2["id"], issuer["id"],
                                      window_start="2026-01-01", window_end="2026-07-01"),
            headers))
        # [2026-06-30, 2026-12-01) overlaps [2026-01-01, 2026-07-01) by one day.
        resp = api.create_engagement(
            create_engagement_payload(custodian2["id"], issuer["id"],
                                      window_start="2026-06-30", window_end="2026-12-01"),
            headers)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)
        # No second engagement was persisted for the pair.
        listed = get_success_data(api.list_engagements(
            TEST_USERS["platform_admin_headers"],
            params={"custodian_id": custodian2["id"], "issuer_id": issuer["id"]}))
        assert len(listed) == 1

    def test_end_engagement_then_second_end_invalid(self, api):
        """PRD §3.2: "An `IssuerOfficer` ends an engagement by an explicit end
        action, moving it from `ACTIVE` to the terminal `ENDED` state; ending
        an already-ended engagement fails with `ERR_ENGAGEMENT_INVALID_STATE`"

        Design: Corner/state_machines/engagement_end_transition
        """
        issuer, custodian, eng = setup_issuer_with_engagement("officer-eng")
        headers = make_issuer_officer_headers(issuer["id"])
        ended = validate_success(api.end_engagement(eng["id"], headers))
        assert ended["status"] == "ENDED"
        resp = api.end_engagement(eng["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE)


class TestStaleVersionOnPoolCreate:
    def test_stale_issuer_version_rejected_on_pool_create(self, api):
        """PRD §2.8: "creating a pool, which requires `expected_issuer_version`
        matching the issuing issuer's current `version`; ... the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot act
        on a parent state it has not observed."

        Design: Corner/errors/stale_version_on_pool_create
        """
        set_clock()
        issuer = get_issuer(setup_issuer_with_engagement("officer-st")[0]["id"])
        headers = make_issuer_officer_headers(issuer["id"])
        # Bump the issuer version via a financial patch.
        patched = get_success_data(api.patch_issuer_financials(
            issuer["id"],
            {"expected_issuer_version": issuer["version"], "liquid_assets_cents": 3100000},
            headers))
        assert patched["version"] == issuer["version"] + 1
        custodian = get_success_data(api.create_custodian(
            {"firm_name": "Stale Custody"}, TEST_USERS["platform_admin_headers"]))
        get_success_data(api.create_engagement(
            create_engagement_payload(custodian["id"], issuer["id"]), headers))
        resp = api.create_pool(
            create_pool_payload(issuer["id"], custodian["id"], issuer["version"]),
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # No pool row was created.
        listed = get_success_data(api.list_pools(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert listed == []


class TestPoolCreateImmediateConsistency:
    def test_created_pool_visible_in_list_immediately(self, api):
        """PRD §2.9: "These cascades run immediately within the triggering
        request — the consistency model is immediate, not eventual."

        Design: Corner/consistency_model/pool_create_immediately_visible_in_list
        """
        set_clock()
        issuer, custodian, _ = setup_issuer_with_engagement("officer-imm")
        pool = validate_success(api.create_pool(
            create_pool_payload(
                issuer["id"], custodian["id"], get_issuer(issuer["id"])["version"],
                pool_type="MANUFACTURED_HOME", term_months=240, note_rate_bps=650),
            make_issuer_officer_headers(issuer["id"])), expected_status=201)
        data = get_success_data(api.list_pools(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == pool["id"]
        assert data[0]["status"] == "DRAFT"
        assert data[0]["pool_type"] == "MANUFACTURED_HOME"
        assert data[0]["term_months"] == 240
        assert data[0]["version"] == 1


class TestPoolNotFound:
    def test_get_unknown_pool_returns_404(self, api):
        """PRD §2.7: "a pool id `ERR_POOL_NOT_FOUND`" — dangling resource
        identifiers are reported with the family's not-found error.

        Design: Corner/entities/pool_get_not_found_returns_404
        """
        resp = api.get_pool(
            "11111111-2222-3333-4444-555555555555",
            TEST_USERS["platform_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_FOUND)
