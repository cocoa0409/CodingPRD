"""Replacement transactions: the commitment REPLACEMENT_PENDING loop, OCC,
deliverability, owner-standing priority, and revenue reconciliation
(PRD §2.6, §2.7, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_commitment,
    get_success_data,
    make_resource_owner_headers,
    setup_cleared_year_with_replacement_resource,
    submit_replacement,
    validate_error,
)

ADMIN = TEST_USERS["market_admin_headers"]


def _rt_payload(ctx, replacement_mw=4.0, expected_version=None,
                replacement_resource_id=None):
    return {
        "commitment_id": ctx["c1"]["id"],
        "replacement_resource_id": (
            replacement_resource_id or ctx["r2"]["id"]
        ),
        "replacement_mw": replacement_mw,
        "price_per_mw_day": 55.0,
        "expected_commitment_version": (
            expected_version
            if expected_version is not None
            else ctx["c1"]["version"]
        ),
    }


class TestReplacementLoop:
    def test_reject_reverts_commitment_to_active_unchanged(self, api):
        """PRD §3.5: "Rejection moves the transaction to `REJECTED` and reverts
        the commitment `REPLACEMENT_PENDING` → `ACTIVE` with `committed_mw`
        unchanged."

        Design: Difficulty/non_linear_state_machine/commitment_replacement_loop_revert_and_reapply
        """
        ctx = setup_cleared_year_with_replacement_resource()
        rt = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, ctx["c1"]["version"],
        )
        mid = get_commitment(ctx["c1"]["id"])
        assert mid["status"] == "REPLACEMENT_PENDING"
        rejected = get_success_data(api.reject_replacement(rt["id"], ADMIN))
        assert rejected["status"] == "REJECTED"
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"
        assert c_after["committed_mw"] == pytest.approx(10.0, abs=1e-9)

    def test_loop_reapplied_and_approved_reduces_commitment(self, api):
        """PRD §3.5: "Approval moves the transaction to `APPROVED`, returns the
        commitment to `ACTIVE` with `committed_mw` reduced by `replacement_mw`,
        recomputes its `daily_revenue_dollars`, and creates a new `ACTIVE`
        commitment for the replacement resource: its `committed_mw` is the
        replaced quantity, its `clearing_price_per_mw_day` is copied from the
        original commitment"

        Design: Difficulty/non_linear_state_machine/commitment_replacement_loop_revert_and_reapply
        """
        ctx = setup_cleared_year_with_replacement_resource()
        # First pass: create + reject (the loop reverts).
        rt1 = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, ctx["c1"]["version"],
        )
        get_success_data(api.reject_replacement(rt1["id"], ADMIN))
        # Second pass: re-read the version, create again, approve.
        c_mid = get_commitment(ctx["c1"]["id"])
        rt2 = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, c_mid["version"],
        )
        approved = get_success_data(api.approve_replacement(rt2["id"], ADMIN))
        assert approved["status"] == "APPROVED"

        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"
        assert c_after["committed_mw"] == pytest.approx(6.0, abs=1e-9)
        assert c_after["daily_revenue_dollars"] == pytest.approx(420.0, abs=1e-9)

        new_commitments = get_success_data(
            api.list_commitments(ADMIN, params={"resource_id": ctx["r2"]["id"]})
        )
        assert len(new_commitments) == 1
        assert new_commitments[0]["committed_mw"] == pytest.approx(4.0, abs=1e-9)
        assert new_commitments[0]["clearing_price_per_mw_day"] == pytest.approx(70.0, abs=1e-9)
        assert new_commitments[0]["status"] == "ACTIVE"


class TestReplacementRejectConservation:
    def test_reject_conserves_committed_mw_and_revenue(self, api):
        """PRD §3.5: "Rejection moves the transaction to `REJECTED` and reverts
        the commitment `REPLACEMENT_PENDING` → `ACTIVE` with `committed_mw`
        unchanged." PRD §3.5: "Its `daily_revenue_dollars` is the
        `committed_mw` times its locked `clearing_price_per_mw_day`"

        Design: Difficulty/compensating_invariant/replacement_reject_conserves_committed_mw_and_revenue
        """
        ctx = setup_cleared_year_with_replacement_resource()
        assert ctx["c1"]["committed_mw"] == pytest.approx(10.0, abs=1e-9)
        assert ctx["c1"]["daily_revenue_dollars"] == pytest.approx(700.0, abs=1e-9)
        rt = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, ctx["c1"]["version"],
        )
        get_success_data(api.reject_replacement(rt["id"], ADMIN))
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"
        assert c_after["committed_mw"] == pytest.approx(10.0, abs=1e-9)
        assert c_after["daily_revenue_dollars"] == pytest.approx(700.0, abs=1e-9)

    def test_reject_creates_no_replacement_commitment(self, api):
        """PRD §3.5: "Rejection moves the transaction to `REJECTED` and reverts
        the commitment `REPLACEMENT_PENDING` → `ACTIVE` with `committed_mw`
        unchanged."
        PRD §3.5: "Approval moves the transaction to `APPROVED`, returns the
        commitment to `ACTIVE` with `committed_mw` reduced by `replacement_mw`,
        recomputes its `daily_revenue_dollars`, and creates a new `ACTIVE`
        commitment for the replacement resource: its `committed_mw` is the
        replaced quantity, its `clearing_price_per_mw_day` is copied from the
        original commitment, it belongs to the same delivery year, and its
        `offer_id` is copied from the original commitment."

        Design: Difficulty/compensating_invariant/replacement_reject_conserves_committed_mw_and_revenue
        """
        ctx = setup_cleared_year_with_replacement_resource()
        rt = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, ctx["c1"]["version"],
        )
        get_success_data(api.reject_replacement(rt["id"], ADMIN))
        rt_after = get_success_data(api.get_replacement_transaction(rt["id"], ADMIN))
        assert rt_after["status"] == "REJECTED"
        r2_commitments = get_success_data(
            api.list_commitments(ADMIN, params={"resource_id": ctx["r2"]["id"]})
        )
        assert r2_commitments == []


class TestReplacementDeliverability:
    def test_self_replacement_rejected(self, api):
        """PRD §3.5: "the replacement resource must be `ACCREDITED` for the
        commitment's delivery year, must have remaining accredited headroom —
        its `accredited_ucap_mw` less its `ACTIVE` committed megawatts in the
        same delivery year — of at least `replacement_mw`, must not be the
        commitment's own resource, and must sit in the commitment's zone or in
        an ancestor or descendant LDA of it; any of these failures is an
        `ERR_REPLACEMENT_NOT_DELIVERABLE`."

        Design: Corner/validations/err_replacement_not_deliverable_same_resource
        """
        ctx = setup_cleared_year_with_replacement_resource()
        headers = make_resource_owner_headers(ctx["owner"]["id"])
        resp = api.create_replacement_transaction(
            _rt_payload(ctx, replacement_mw=4.0,
                        replacement_resource_id=ctx["r1"]["id"]),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_NOT_DELIVERABLE,
                       expected_status=422)
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"


class TestOwnerStandingPriority:
    def test_suspended_owner_replacement_rejected_owner_suspended(self, api):
        """PRD §2.6: "Owner standing — a `SUSPENDED` owner may not submit
        offers, replacements, or measurement reports; failure yields
        `ERR_OWNER_SUSPENDED`." and "the first failing gate determines the
        response" with "Temporal and business rules" (which includes
        replacement bounds) listed after "Owner standing".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_replacement
        """
        ctx = setup_cleared_year_with_replacement_resource()
        get_success_data(api.suspend_owner(ctx["owner"]["id"], ADMIN))
        headers = make_resource_owner_headers(ctx["owner"]["id"])
        # replacement_mw 15.0 also exceeds committed_mw 10.0; the
        # owner-standing gate runs first.
        resp = api.create_replacement_transaction(
            _rt_payload(ctx, replacement_mw=15.0), headers,
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_SUSPENDED, expected_status=422)

    def test_suspended_owner_replacement_leaves_commitment_untouched(self, api):
        """PRD §2.6: "Owner standing — a `SUSPENDED` owner may not submit
        offers, replacements, or measurement reports; failure yields
        `ERR_OWNER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_replacement
        """
        ctx = setup_cleared_year_with_replacement_resource()
        get_success_data(api.suspend_owner(ctx["owner"]["id"], ADMIN))
        headers = make_resource_owner_headers(ctx["owner"]["id"])
        resp = api.create_replacement_transaction(
            _rt_payload(ctx, replacement_mw=15.0), headers,
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_SUSPENDED, expected_status=422)
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"
        assert c_after["committed_mw"] == pytest.approx(10.0, abs=1e-9)


class TestReplacementOcc:
    def test_stale_commitment_version_rejected(self, api):
        """PRD §2.7: "If the commitment's current `version` has advanced since
        then — for instance because an earlier replacement against the same
        commitment was approved, or a prior pending replacement already moved
        the commitment — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_commitment_version_rejected
        """
        ctx = setup_cleared_year_with_replacement_resource()
        original_version = ctx["c1"]["version"]
        rt1 = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            2.0, original_version,
        )
        get_success_data(api.reject_replacement(rt1["id"], ADMIN))
        headers = make_resource_owner_headers(ctx["owner"]["id"])
        resp = api.create_replacement_transaction(
            _rt_payload(ctx, replacement_mw=2.0,
                        expected_version=original_version),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["status"] == "ACTIVE"
        assert c_after["committed_mw"] == pytest.approx(10.0, abs=1e-9)


class TestDerivedFieldReconciliation:
    def test_daily_revenue_recomputed_after_approval(self, api):
        """PRD §3.5: "Approval moves the transaction to `APPROVED`, returns the
        commitment to `ACTIVE` with `committed_mw` reduced by `replacement_mw`,
        recomputes its `daily_revenue_dollars`, and creates a new `ACTIVE`
        commitment for the replacement resource: its `committed_mw` is the
        replaced quantity, its `clearing_price_per_mw_day` is copied from the
        original commitment" and "Its `daily_revenue_dollars` is the
        `committed_mw` times its locked `clearing_price_per_mw_day`, rounded
        to 2 decimal places round half up, and is recomputed whenever
        `committed_mw` changes."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_daily_revenue_after_replacement
        """
        ctx = setup_cleared_year_with_replacement_resource()
        rt = submit_replacement(
            ctx["c1"]["id"], ctx["owner"]["id"], ctx["r2"]["id"],
            4.0, ctx["c1"]["version"],
        )
        get_success_data(api.approve_replacement(rt["id"], ADMIN))
        c_after = get_commitment(ctx["c1"]["id"])
        assert c_after["committed_mw"] == pytest.approx(6.0, abs=1e-9)
        assert c_after["daily_revenue_dollars"] == pytest.approx(420.0, abs=1e-9)
        new_commitments = get_success_data(
            api.list_commitments(ADMIN, params={"resource_id": ctx["r2"]["id"]})
        )
        assert len(new_commitments) == 1
        assert new_commitments[0]["committed_mw"] == pytest.approx(4.0, abs=1e-9)
        assert new_commitments[0]["daily_revenue_dollars"] == pytest.approx(280.0, abs=1e-9)
