"""Royalty statements: marginal-tier computation, provisional vs final
variants, supersede mechanics, bucket conservation, and agreement OCC."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, get_provider, get_agreement,
    setup_provider_with_active_agreement, setup_agreement_with_two_statements,
    setup_agreement_with_three_statements,
    submit_statement_ok, finalize_statement_ok, list_statements,
    create_royalty_statement_payload, make_provider_manager_headers,
    assert_royalty_exposure_invariant,
)

FIN = TEST_USERS["finance_controller_headers"]
GOV = TEST_USERS["governance_officer_headers"]


class TestProvisionalVsFinalSettlement:
    def test_provisional_royalties_at_submission(self, api):
        """PRD §3.4: "The provisional variant of this computation runs at
        submission on `reported_sales_cents` and posts the resulting
        `provisional_royalty_cents` into the provider's `royalty_balance_cents`
        and the agreement's `provisional_outstanding_cents`." PRD §3.4: "the
        first 100,000,000 cents (one million dollars) of year-to-date sales is
        taxed at 8%, the next tranche up to 500,000,000 cents (five million
        dollars) of year-to-date sales at 10%, and everything above
        500,000,000 cents at 12%".

        Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_settlement
        """
        set_clock()
        provider, agreement, q1, q2 = setup_agreement_with_two_statements()
        # Q1: 80,000,000 wholly inside tier 1 -> 6,400,000.
        assert q1["provisional_royalty_cents"] == 6_400_000
        assert q1["status"] == "PROVISIONAL"
        # Q2 against YTD-before 80,000,000: 20,000,000 @8% + 40,000,000 @10%.
        assert q2["provisional_royalty_cents"] == 5_600_000
        assert get_provider(provider["id"])["royalty_balance_cents"] == 12_000_000
        assert get_agreement(agreement["id"])["provisional_outstanding_cents"] == 12_000_000

    def test_finalize_recomputes_on_audited_sales(self, api):
        """PRD §3.4: "The final variant runs at finalization on
        `audited_sales_cents`." PRD §3.4: "On success, `final_royalty_cents`
        is recomputed by the marginal-tier schedule against the prior
        quarters' effective sales, `delta_cents` is set to the final royalty
        minus the provisional royalty, and the ledger postings land: the
        provider's `royalty_balance_cents` moves by exactly `delta_cents`
        (negative deltas post downward corrections), the agreement's
        `recognized_royalty_cents` grows by `final_royalty_cents`, and its
        `provisional_outstanding_cents` shrinks by the released
        `provisional_royalty_cents` — bucket conservation."

        Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_settlement
        """
        set_clock()
        provider, agreement, q1, q2 = setup_agreement_with_two_statements()
        finalized = finalize_statement_ok(q2["id"], 30_000_000)
        assert finalized["status"] == "FINALIZED"
        # Audited 30,000,000 against YTD-before 80,000,000 (Q1 reported):
        # 20,000,000 @8% + 10,000,000 @10% = 2,600,000.
        assert finalized["final_royalty_cents"] == 2_600_000
        assert finalized["delta_cents"] == -3_000_000
        assert get_provider(provider["id"])["royalty_balance_cents"] == 9_000_000
        agreement_after = get_agreement(agreement["id"])
        assert agreement_after["recognized_royalty_cents"] == 2_600_000
        # Q1's 6,400,000 remains provisional outstanding.
        assert agreement_after["provisional_outstanding_cents"] == 6_400_000


class TestRoyaltyExposureInvariant:
    def test_late_binding_provisional_uses_reported_prior_quarters(self, api):
        """PRD §3.4: "For any given statement, the system first sums the
        effective sales of the agreement's same-calendar-year statements from
        strictly earlier quarters, where a `FINALIZED` statement contributes
        its `audited_sales_cents` and any other counted statement contributes
        its `reported_sales_cents`". PRD §3.4: "Later statements are never
        re-based: each statement's tier allocation is fixed at its own
        computation time, so finalizing an earlier quarter does not change a
        later quarter's provisional figure."

        Design: Difficulty/compensating_invariant/royalty_exposure_balance_conservation
        """
        set_clock()
        provider, agreement, _q1, _q2, q3 = setup_agreement_with_three_statements()
        # Q3 against YTD-before 140,000,000 (Q1 + Q2 reported):
        # 360,000,000 @10% + 40,000,000 @12% = 40,800,000.
        assert q3["provisional_royalty_cents"] == 40_800_000
        agreement_now = get_agreement(agreement["id"])
        provider_now = get_provider(provider["id"])
        assert provider_now["royalty_balance_cents"] == 52_800_000
        assert agreement_now["recognized_royalty_cents"] == 0
        assert agreement_now["provisional_outstanding_cents"] == 52_800_000
        assert_royalty_exposure_invariant(agreement_now, provider_now)

    def test_negative_delta_finalize_preserves_invariant(self, api):
        """PRD §3.4: "The agreement's `royalty_exposure_cents`, defined as
        its `recognized_royalty_cents` plus its `provisional_outstanding_cents`,
        is maintained as an invariant equal to this agreement's contribution
        to the provider's `royalty_balance_cents`."

        Design: Difficulty/compensating_invariant/royalty_exposure_balance_conservation
        """
        set_clock()
        provider, agreement, _q1, q2, _q3 = setup_agreement_with_three_statements()
        finalized = finalize_statement_ok(q2["id"], 30_000_000)
        assert finalized["delta_cents"] == -3_000_000
        provider_after = get_provider(provider["id"])
        agreement_after = get_agreement(agreement["id"])
        assert provider_after["royalty_balance_cents"] == 49_800_000
        assert agreement_after["recognized_royalty_cents"] == 2_600_000
        # 6,400,000 (Q1) + 40,800,000 (Q3) still outstanding.
        assert agreement_after["provisional_outstanding_cents"] == 47_200_000
        assert_royalty_exposure_invariant(agreement_after, provider_after)


class TestRoyaltyTierBoundary:
    def test_tier1_cap_boundary_crossing(self, api):
        """PRD §3.4: "the first 100,000,000 cents (one million dollars) of
        year-to-date sales is taxed at 8%, the next tranche up to
        500,000,000 cents (five million dollars) of year-to-date sales at
        10%, and everything above 500,000,000 cents at 12%". PRD §2.6: "a
        value landing precisely on a boundary passes or fires exactly as the
        inclusive reading implies."

        Design: Corner/calculations/royalty_tier1_cap_boundary_crossing
        """
        set_clock()
        provider, agreement = setup_provider_with_active_agreement(
            "INSURANCE_HEALTH", "Capstone Health Mutual")
        s1 = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                 100_000_000)
        # Exactly at the tier-1 cap: 100,000,000 * 0.08.
        assert s1["provisional_royalty_cents"] == 8_000_000
        s2 = submit_statement_ok(agreement["id"], provider["id"], 2026, 2, 100)
        # YTD-before exhausts tier 1: the 100 cents land in tier 2 at 10%.
        assert s2["provisional_royalty_cents"] == 10
        assert get_provider(provider["id"])["royalty_balance_cents"] == 8_000_010


class TestStatementLifecycle:
    def test_finalize_superseded_statement_rejected(self, api):
        """PRD §3.4: "Only a `PROVISIONAL` statement can be finalized; a
        statement already `FINALIZED` or `SUPERSEDED` is rejected with
        `ERR_STATEMENT_NOT_PROVISIONAL` (HTTP 409)."

        Design: Corner/state_machines/finalize_superseded_statement_rejected
        """
        set_clock()
        provider, agreement = setup_provider_with_active_agreement(
            "TRAVEL_SERVICES", "Wander Travel Co")
        old = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                  1_000_000)
        new = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                  1_500_000)
        resp = api.finalize_statement(old["id"], {"audited_sales_cents": 1_000_000},
                                      FIN)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_PROVISIONAL)
        rows = list_statements(agreement["id"])
        by_id = {r["id"]: r for r in rows}
        assert by_id[old["id"]]["status"] == "SUPERSEDED"
        assert by_id[new["id"]]["status"] == "PROVISIONAL"

    def test_resubmit_finalized_quarter_rejected(self, api):
        """PRD §3.4: "One quarter can hold only one live statement: if a
        `FINALIZED` statement already exists for the same agreement, year,
        and quarter, the submission is rejected with
        `ERR_QUARTER_ALREADY_FINALIZED` (HTTP 409)."

        Design: Corner/errors/resubmit_finalized_quarter_rejected
        """
        set_clock()
        provider, agreement = setup_provider_with_active_agreement(
            "INSURANCE_AUTO", "Closed Books Insurance")
        statement = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                        1_000_000)
        finalized = finalize_statement_ok(statement["id"], 1_000_000)
        assert finalized["final_royalty_cents"] == 80_000
        assert finalized["delta_cents"] == 0

        fresh_version = get_agreement(agreement["id"])["version"]
        payload = create_royalty_statement_payload(
            fresh_version, period_year=2026, period_quarter=1,
            reported_sales_cents=2_000_000)
        resp = api.submit_royalty_statement(
            agreement["id"], payload, make_provider_manager_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_QUARTER_ALREADY_FINALIZED)

        rows = list_statements(agreement["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "FINALIZED"

    def test_occ_statement_resubmission_supersedes(self, api):
        """PRD §3.4: "If a `PROVISIONAL` statement exists for that quarter,
        the new submission supersedes it — the superseded statement's
        provisional posting is first reversed out of both the agreement's
        `provisional_outstanding_cents` and the provider's
        `royalty_balance_cents`, the old statement moves to `SUPERSEDED`, and
        the agreement's `version` increments for the reversal before the new
        submission's own effects increment it again."

        Design: Corner/cross_cutting_complexity_layers/occ_statement_resubmission_supersedes
        """
        set_clock()
        provider, agreement = setup_provider_with_active_agreement(
            "HOME_SERVICES", "Corrected Filing Mutual")
        old = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                  1_000_000)
        new = submit_statement_ok(agreement["id"], provider["id"], 2026, 1,
                                  2_000_000)
        assert new["provisional_royalty_cents"] == 160_000

        rows = list_statements(agreement["id"])
        assert len(rows) == 2
        by_id = {r["id"]: r for r in rows}
        assert by_id[old["id"]]["status"] == "SUPERSEDED"
        assert by_id[new["id"]]["status"] == "PROVISIONAL"
        # 80,000 reversed, then 160,000 posted — not 240,000.
        assert get_provider(provider["id"])["royalty_balance_cents"] == 160_000
        assert get_agreement(agreement["id"])["provisional_outstanding_cents"] == 160_000

    def test_occ_stale_agreement_version_rejected(self, api):
        """PRD §2.7: "Submitting a royalty statement under a license agreement
        (`POST /api/license-agreements/{id}/royalty-statements`) requires a
        non-optional `expected_agreement_version` field carrying the client's
        last observed `version` of that agreement." PRD §2.7: "If the value
        does not match the agreement's current `version`, the request is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_agreement_version_rejected
        """
        set_clock()
        provider, agreement = setup_provider_with_active_agreement(
            "TRAVEL_SERVICES", "Stale Write Insurance")
        stale_version = agreement["version"]  # 2, observed at activation
        submit_statement_ok(agreement["id"], provider["id"], 2026, 1, 1_000_000)

        payload = create_royalty_statement_payload(
            stale_version, period_year=2026, period_quarter=1,
            reported_sales_cents=2_000_000)
        resp = api.submit_royalty_statement(
            agreement["id"], payload, make_provider_manager_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

        rows = list_statements(agreement["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "PROVISIONAL"
        assert rows[0]["reported_sales_cents"] == 1_000_000
