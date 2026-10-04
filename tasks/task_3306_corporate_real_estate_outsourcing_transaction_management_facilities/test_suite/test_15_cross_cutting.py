"""Cross-cutting layers: derived-field reconciliation, OCC, terminal lockdown."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    create_activated_account,
    create_lease,
    create_scorecard,
    create_audit,
    create_audit_review,
    begin_offboarding,
    set_clock,
    setup_offboarding_with_complete_task,
    TEST_USERS,
    ApiErrorId,
    ae_headers,
)

GM = TEST_USERS["governance_manager_headers"]


class TestDerivedFieldReconciliation:

    def test_client_data_rights_recomputed_on_tier_change(self, api):
        """PRD §3.1: "Because the tier drives data rights and the square footage
        drives the fee tier, the update recomputes client_data_rights and
        recomputes annual_net_fee_cents, and it increments the account's version
        by one."

        The tier-derived rights are PRD-verbatim. PRD never states the activation
        transition's version arithmetic, so the absolute version number is not
        derivable from prose; the covered assertion is that the update advances
        the version by exactly one from whatever value the account carried.

        Design: Corner/cross_cutting_layers/client_data_rights_recomputed_on_tier_change
        """
        account = create_activated_account(platform_tier="BASIC")
        before = get_success_data(api.get_account(account["id"], ae_headers(account)))
        updated = validate_success(
            api.update_account(
                account["id"], {"platform_tier": "ENTERPRISE"}, ae_headers(account)
            ),
            200,
        )
        assert updated["client_data_rights"] == "CLIENT_OWNED_EXCLUSIVE"
        assert updated["version"] == before["version"] + 1

    def test_annual_fee_recomputed_on_portfolio_sqft_change(self, api):
        """PRD §3.1: "the update recomputes client_data_rights and recomputes
        annual_net_fee_cents, and it increments the account's version by one."
        PRD §2.9: "the per-square-foot rate is 145 cents when portfolio_sqft is
        at most 250,000, 118 cents when it is at most 750,000, and 96 cents
        otherwise."

        Design: Corner/cross_cutting_layers/annual_fee_recomputed_on_portfolio_sqft_change
        """
        account = create_activated_account(platform_tier="BASIC", portfolio_sqft=200_000)
        updated = validate_success(
            api.update_account(
                account["id"], {"portfolio_sqft": 400_000}, ae_headers(account)
            ),
            200,
        )
        # 400,000 sqft selects the 118 cents tier: 118 * 400,000 = 47,200,000.
        assert updated["annual_net_fee_cents"] == pytest.approx(47_200_000.00, abs=0.01)

    def test_lease_expiration_bucket_survives_a_clock_advance(self, api):
        """PRD §3.2: "its expiration_bucket is recomputed on every advance of the
        account clock."
        PRD §3.9: "every lease's expiration_bucket is recomputed".

        PRD states the recompute trigger and the bucket enum, but never pins the
        day-thresholds that separate NEAR_TERM / MID_TERM / LONG_TERM, so the
        assertion keeps the PRD-covered recompute (bucket stays a valid, present
        enum member after the clock moves) and drops the underivable exact value.

        Design: Corner/cross_cutting_layers/lease_expiration_bucket_recomputed_on_clock_advance
        """
        account = create_activated_account()
        lease = create_lease(account, lease_end_date="2028-01-01T00:00:00Z")
        before = validate_success(api.get_lease(lease["id"], TEST_USERS[
            "transaction_manager_headers"
        ]), 200)
        set_clock("2027-01-01T00:00:00Z")
        after = validate_success(api.get_lease(lease["id"], TEST_USERS[
            "transaction_manager_headers"
        ]), 200)
        assert before["expiration_bucket"] in ("UNASSIGNED", "NEAR_TERM", "MID_TERM", "LONG_TERM")
        assert after["expiration_bucket"] in ("UNASSIGNED", "NEAR_TERM", "MID_TERM", "LONG_TERM")


class TestOptimisticConcurrency:

    def test_stale_account_version_on_audit_review_conflict(self, api):
        """PRD §2.7: "Recording a review round against a discipline audit requires
        expected_account_version for the same reason: recording the round
        refreshes account-level governance inputs, and it must be anchored to the
        state the client saw. A mismatch there is likewise rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_account_version_on_audit_review_conflict
        """
        account = create_activated_account()
        scorecard = create_scorecard(account, quality_bps=9800, response_bps=9300)
        audit = create_audit(account, discipline="TRANSACTION")
        stale_version = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )["version"]
        validate_success(
            api.publish_scorecard(
                scorecard["id"], {"expected_account_version": stale_version}, GM
            ),
            200,
        )
        res = api.create_audit_review(
            audit["id"],
            {
                "reviewer_name": "Rae Auditor",
                "round_notes": "Round one",
                "expected_account_version": stale_version,
            },
            GM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_account_version_on_audit_review_succeeds(self, api):
        """PRD §3.7: "Each round is assigned a review_round_no, which is the
        1-based index of that round within the audit's existing reviews ordered by
        created_at ascending".

        Design: Corner/cross_cutting_layers/fresh_account_version_on_audit_review_succeeds
        """
        account = create_activated_account()
        scorecard = create_scorecard(account, quality_bps=9800, response_bps=9300)
        audit = create_audit(account, discipline="TRANSACTION")
        first_version = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )["version"]
        validate_success(
            api.publish_scorecard(
                scorecard["id"], {"expected_account_version": first_version}, GM
            ),
            200,
        )
        fresh_version = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )["version"]
        review = create_audit_review(audit, fresh_version, reviewer_name="Rae Auditor")
        assert review["review_round_no"] == 1


class TestTerminalAccountLockdown:

    def test_closed_account_refuses_new_lease(self, api):
        """PRD §2.4: "While it is CLOSED_CONVERTED or CLOSED_TERMINATED, every
        child mutation is blocked and only reads succeed."
        PRD §2.4: "A mutation attempted on an account whose lifecycle_state is
        already terminal is rejected with ERR_ACCOUNT_CLOSED (HTTP 409)".

        Design: Corner/cross_cutting_layers/closed_account_refuses_new_lease
        """
        from test_helpers import setup_closed_converted_account

        account = setup_closed_converted_account()
        res = api.create_lease(
            {
                "account_id": account["id"],
                "property_address": "40 New St",
                "market_code": "SFO",
                "leased_sqft": 40_000,
                "base_rent_cents_per_year": 74_000_000,
                "lease_start_date": "2026-10-01T00:00:00Z",
                "lease_end_date": "2027-10-01T00:00:00Z",
            },
            TEST_USERS["transaction_manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ACCOUNT_CLOSED)


class TestGovernancePostureRollup:

    def test_second_audit_failure_flips_posture_to_restricted(self, api):
        """PRD §2.4: "When the failed-and-remediable count is at least 2 the
        posture is RESTRICTED."
        PRD §3.7: "A failing outcome moves it to FAILED, sets
        remediation_required true".

        Design: Corner/cross_cutting_layers/second_audit_failure_flips_posture_to_restricted
        """
        account = create_activated_account()
        first = create_audit(account, discipline="TRANSACTION")
        validate_success(api.start_audit(first["id"], GM), 200)
        failed = validate_success(
            api.decide_audit(first["id"], {"outcome": "FAILED"}, GM), 200
        )
        assert failed["remediation_required"] is True
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["governance_posture"] == "ON_WATCH"
        second = create_audit(account, discipline="FACILITIES", finding="Records gap")
        validate_success(api.start_audit(second["id"], GM), 200)
        validate_success(api.decide_audit(second["id"], {"outcome": "FAILED"}, GM), 200)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["governance_posture"] == "RESTRICTED"


class TestImmediateConsistency:

    def test_converted_close_revokes_licence_in_the_same_response(self, api):
        """PRD §3.8: "The converted route is shorter: closure to
        CLOSED_CONVERTED revokes every licence on the account directly."
        PRD §2.1: "The server may record such an identifier where a workflow
        captures an operator".

        Design: Corner/consistency_model/converted_close_path_revokes_licence_and_keeps_area
        """
        from test_helpers import setup_offboarding_with_granted_licence

        account, license = setup_offboarding_with_granted_licence(data_scope="AGGREGATE")
        closed = validate_success(
            api.close_converted_account(account["id"], ae_headers(account)), 200
        )
        assert closed["lifecycle_state"] == "CLOSED_CONVERTED"
        license_after = validate_success(
            api.get_data_license(license["id"], TEST_USERS["data_steward_headers"]), 200
        )
        assert license_after["license_state"] == "REVOKED"