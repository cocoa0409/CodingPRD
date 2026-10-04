"""Pool lifecycle and loan delivery gates (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    setup_counterparty_chain,
    create_draft_loan,
    create_pool_for,
    create_underwritten_loan,
    underwrite_loan,
    deliver_loan,
    issue_pool,
    get_loan,
    get_pool,
    make_seller_officer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["gse_admin_headers"]


class TestPoolCreation:
    def test_pool_create_with_past_issue_date_rejected(self, api):
        """PRD §3.5: "The `issue_date` must lie strictly after the current
        logical time, failing with `ERR_INVALID_REQUEST` otherwise."

        Design: Corner/validations/pool_create_with_past_issue_date_rejected
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_pool(
            {
                "seller_id": seller["id"],
                "agreement_id": agreement["id"],
                "pool_number": "PL-PAST",
                "issue_date": "2026-08-01T00:00:00Z",
                "target_balance_cents": 500000000,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPoolStateMachine:
    def test_pool_lock_requires_at_least_one_loan(self, api):
        """PRD §3.5: "From `OPEN`, a pool may be locked — but only when it
        holds at least one delivered loan, failing with `ERR_POOL_EMPTY`
        otherwise — moving `OPEN → LOCKED`."

        Design: Corner/state_machines/pool_lock_requires_at_least_one_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-PE")
        headers = make_seller_officer_headers(seller["id"])
        resp = api.lock_pool(pool["id"], headers)
        validate_error(resp, ApiErrorId.ERR_POOL_EMPTY)
        deliver_loan(loan, pool, seller)
        data = validate_success(api.lock_pool(pool["id"], headers))
        assert data["status"] == "LOCKED"

    def test_pool_unlock_lock_cycle_and_issue_from_open_rejected(self, api):
        """PRD §3.5: "Issuance is OCC-guarded: the request carries
        `expected_pool_version`, and a pool whose version has advanced since
        the caller's last read is rejected with `ERR_STALE_VERSION`. On success
        the pool moves `LOCKED → ISSUED`."
        PRD §3.5: "A `LOCKED` pool may be unlocked back to `OPEN` without
        preconditions, or issued."
        PRD §2.9: "After existence, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/pool_unlock_lock_cycle_and_issue_from_open_rejected
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-PGATE")
        deliver_loan(loan, pool, seller)
        headers = make_seller_officer_headers(seller["id"])
        current = get_pool(pool["id"])
        # Issue from OPEN is an invalid transition.
        resp = api.issue_pool(
            pool["id"], {"expected_pool_version": current["version"]}, headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # lock -> unlock -> lock again is legal.
        validate_success(api.lock_pool(pool["id"], headers))
        validate_success(api.unlock_pool(pool["id"], headers))
        data = validate_success(api.lock_pool(pool["id"], headers))
        assert data["status"] == "LOCKED"

    def test_error_stale_version_on_pool_issue(self, api):
        """PRD §2.8: "Issuing a pool requires `expected_pool_version` matching
        the pool's current `version`; deliveries, cancellations, or a prior
        issue attempt may have changed the pool contents the caller priced
        against, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "On success the pool moves `LOCKED → ISSUED`, its `version`
        increments, and every loan in the pool that is `DELIVERED` moves to
        `PURCHASED`."

        Design: Corner/errors/error_stale_version_on_pool_issue
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-OCCP")
        deliver_loan(loan, pool, seller)
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.lock_pool(pool["id"], headers))
        current = get_pool(pool["id"])
        stale = api.issue_pool(
            pool["id"], {"expected_pool_version": current["version"] - 1}, headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert get_pool(pool["id"])["status"] == "LOCKED"
        issued = validate_success(
            api.issue_pool(pool["id"], {"expected_pool_version": current["version"]}, headers)
        )
        assert issued["status"] == "ISSUED"
        assert get_loan(loan["id"])["status"] == "PURCHASED"


class TestDeliveryGates:
    def test_deliver_draft_loan_returns_invalid_state(self, api):
        """PRD §3.5: "A successful delivery moves the loan `UNDERWRITTEN →
        DELIVERED`."
        PRD §2.9: "After existence, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/deliver_draft_loan_returns_invalid_state
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-DELIV-DRAFT")
        headers = make_seller_officer_headers(seller["id"])
        resp = api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_loan(loan["id"])["status"] == "DRAFT"
        assert get_pool(pool["id"])["current_balance_cents"] == 0

    def test_deliver_with_refer_recommendation_rejected(self, api):
        """PRD §3.4: "A `PASS` with `REFER_WITH_CAUTION` leaves the loan in
        `DRAFT` — a cautionary recommendation does not advance the loan — while
        setting its `au_status` to `RECOMMEND_REFER`."
        PRD §3.5: "A successful delivery moves the loan `UNDERWRITTEN →
        DELIVERED`."
        PRD §2.9: "After existence, the target resource must be in a state that
        permits the requested transition, failing with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/validations/deliver_with_refer_recommendation_rejected
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-REF",
                                 credit_score=670)
        case = underwrite_loan(loan, seller)
        assert case["recommendation"] == "REFER_WITH_CAUTION"
        after = get_loan(loan["id"])
        assert after["au_status"] == "RECOMMEND_REFER"
        assert after["status"] == "DRAFT"
        headers = make_seller_officer_headers(seller["id"])
        resp = api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_conditional_action_delivery_blocked_when_seller_suspended(self, api):
        """PRD §3.5: "The seller must be `APPROVED`, else
        `ERR_SELLER_NOT_APPROVED`."
        PRD §3.1: "When a `SUSPENDED` seller is approved again — again subject
        to the net-worth and defect-rate gates, with
        `ERR_NET_WORTH_BELOW_MINIMUM` or `ERR_QC_DEFECT_RATE_EXCEEDED` on
        failure — its `approval_cycle` increments by one. The moment
        `approval_cycle` reaches 2, the system sets `probation_relief_enabled`
        to true on the seller."

        Design: Corner/endpoints/conditional_action_delivery_blocked_when_seller_suspended
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-SUSP")
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.suspend_seller(seller["id"], ADMIN))
        resp = api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_SELLER_NOT_APPROVED)
        validate_success(api.approve_seller(seller["id"], ADMIN))
        data = validate_success(api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers))
        assert data["status"] == "DELIVERED"
        from test_helpers import get_seller

        seller_after = get_seller(seller["id"])
        assert seller_after["approval_cycle"] == 2
        assert seller_after["probation_relief_enabled"] is True

    def test_error_agreement_not_effective_on_delivery(self, api):
        """PRD §3.5: "Delivering a loan is the central commercial act and is
        guarded by five preconditions, all enforced at delivery time. The
        loan's `au_status` must be `RECOMMEND_APPROVE`, else
        `ERR_LOAN_NOT_ELIGIBLE`. The seller must be `APPROVED`, else
        `ERR_SELLER_NOT_APPROVED`. The agreement must be `ACTIVE`, else
        `ERR_AGREEMENT_NOT_EFFECTIVE`."

        Design: Corner/errors/error_agreement_not_effective_on_delivery
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-AGR")
        validate_success(api.terminate_master_agreement(agreement["id"], ADMIN))
        headers = make_seller_officer_headers(seller["id"])
        resp = api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EFFECTIVE)
        assert get_loan(loan["id"])["status"] == "UNDERWRITTEN"


class TestDeliveryPricing:
    def test_delivery_price_rounding_half_up(self, api):
        """PRD §3.5: "The dollar adjustment is the unpaid principal balance
        multiplied by the row's `llpa_bps` and divided by ten thousand, rounded
        half-up to a whole cent, and the `delivery_price_cents` is the unpaid
        principal balance minus that adjustment."
        PRD §3.5: "The row's `llpa_bps` is pinned onto the loan as
        `applied_llpa_bps`, and these two pinned values never change afterward."

        Design: Corner/calculations/delivery_price_rounding_half_up
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(
            seller, servicer, agreement, loan_number="LN-RND",
            unpaid_principal_balance_cents=400000001,
        )
        deliver_loan(loan, pool, seller)
        after = get_loan(loan["id"])
        # round_half_up(400000001 * 100 / 10000) = round_half_up(4000000.01) = 4000000
        assert after["delivery_price_cents"] == 396000001
        assert after["applied_llpa_bps"] == 100

    def test_llpa_row_selection_nonlinear_multi_input(self, api):
        """PRD §3.5: "The system selects the pricing row of the `ACTIVE` grid
        at the delivery instant by matching the loan's `occupancy` and
        `product_type` exactly, requiring the loan's `ltv_bp` to be strictly
        above the row's `ltv_min_bp` and at most its `ltv_max_bp`, and
        requiring the loan's `credit_score` to be at least the row's
        `credit_min` and at most its `credit_max`; exactly one row must match
        for a loan to be priced."

        Design: Difficulty/combinatorial_formula/llpa_row_selection_nonlinear_multi_input
        """
        from test_helpers import create_active_llpa_matrix

        rows = [
            {"occupancy": "PRIMARY_RESIDENCE", "product_type": "FIXED_30", "llpa_bps": 150,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 739},
            {"occupancy": "PRIMARY_RESIDENCE", "product_type": "FIXED_30", "llpa_bps": 50,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 740, "credit_max": 850},
            {"occupancy": "INVESTMENT", "product_type": "FIXED_30", "llpa_bps": 300,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 739},
            {"occupancy": "INVESTMENT", "product_type": "FIXED_30", "llpa_bps": 200,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 740, "credit_max": 850},
            {"occupancy": "SECOND_HOME", "product_type": "ARM_5_1", "llpa_bps": 175,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 850},
            {"occupancy": "INVESTMENT", "product_type": "ARM_5_1", "llpa_bps": 325,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 850},
        ]
        seller, servicer, agreement, _ = setup_counterparty_chain()
        create_active_llpa_matrix(rows=rows)
        pool = create_pool_for(seller, agreement, target_balance_cents=2000000000)
        low = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-LOW",
                                       credit_score=739)
        high = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-HIGH",
                                        credit_score=740)
        deliver_loan(low, pool, seller)
        deliver_loan(high, pool, seller)
        low_after = get_loan(low["id"])
        high_after = get_loan(high["id"])
        assert low_after["applied_llpa_bps"] == 150
        assert low_after["delivery_price_cents"] == 394000000
        assert high_after["applied_llpa_bps"] == 50
        assert high_after["delivery_price_cents"] == 398000000
        assert (
            high_after["delivery_price_cents"] - low_after["delivery_price_cents"]
        ) == 4000000

    def test_pool_capacity_exact_fit_then_one_cent_over(self, api):
        """PRD §3.5: "Finally, capacity: the pool's `current_balance_cents`
        plus the incoming loan's `unpaid_principal_balance_cents` must not
        exceed the pool's `target_balance_cents`; a sum exactly equal to the
        target is allowed, and exceeding it by any amount yields
        `ERR_POOL_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fit_then_one_cent_over
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        cap = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-CAP")
        over = create_underwritten_loan(
            seller, servicer, agreement, loan_number="LN-OVER",
            unpaid_principal_balance_cents=100000001,
            appraised_value_cents=200000000,
        )
        deliver_loan(cap, pool, seller)
        assert get_loan(cap["id"])["status"] == "DELIVERED"
        headers = make_seller_officer_headers(seller["id"])
        # 400,000,000 + 100,000,001 = 500,000,001 > 500,000,000 target.
        resp = api.deliver_loan(over["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)
        pool_after = get_pool(pool["id"])
        assert pool_after["current_balance_cents"] == 400000000
        assert pool_after["loan_count"] == 1

    def test_pool_capacity_rejects_delivery_one_cent_over(self, api):
        """PRD §3.5: "Finally, capacity: the pool's `current_balance_cents`
        plus the incoming loan's `unpaid_principal_balance_cents` must not
        exceed the pool's `target_balance_cents`; a sum exactly equal to the
        target is allowed, and exceeding it by any amount yields
        `ERR_POOL_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fit_then_one_cent_over
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        # Target exactly equals the first loan's UPB: exact fit is allowed.
        pool = create_pool_for(seller, agreement, target_balance_cents=400000000)
        first = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-FIT")
        second = create_underwritten_loan(
            seller, servicer, agreement, loan_number="LN-1C",
            unpaid_principal_balance_cents=1,
            appraised_value_cents=200000000,
        )
        deliver_loan(first, pool, seller)
        assert get_pool(pool["id"])["current_balance_cents"] == 400000000
        headers = make_seller_officer_headers(seller["id"])
        # One cent over capacity fails.
        resp = api.deliver_loan(second["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)
        assert get_pool(pool["id"])["loan_count"] == 1

    def test_llpa_row_selection_investment_band_pricing(self, api):
        """PRD §3.5: "The system selects the pricing row of the `ACTIVE` grid
        at the delivery instant by matching the loan's `occupancy` and
        `product_type` exactly, requiring the loan's `ltv_bp` to be strictly
        above the row's `ltv_min_bp` and at most its `ltv_max_bp`, and
        requiring the loan's `credit_score` to be at least the row's
        `credit_min` and at most its `credit_max`; exactly one row must match
        for a loan to be priced."
        PRD §3.5: "The dollar adjustment is the unpaid principal balance
        multiplied by the row's `llpa_bps` and divided by ten thousand, rounded
        half-up to a whole cent, and the `delivery_price_cents` is the unpaid
        principal balance minus that adjustment."

        Design: Difficulty/combinatorial_formula/llpa_row_selection_nonlinear_multi_input
        """
        from test_helpers import create_active_llpa_matrix

        rows = [
            {"occupancy": "PRIMARY_RESIDENCE", "product_type": "FIXED_30", "llpa_bps": 150,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 739},
            {"occupancy": "PRIMARY_RESIDENCE", "product_type": "FIXED_30", "llpa_bps": 50,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 740, "credit_max": 850},
            {"occupancy": "INVESTMENT", "product_type": "FIXED_30", "llpa_bps": 300,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 620, "credit_max": 739},
            {"occupancy": "INVESTMENT", "product_type": "FIXED_30", "llpa_bps": 200,
             "ltv_min_bp": 0, "ltv_max_bp": 9500, "credit_min": 740, "credit_max": 850},
        ]
        seller, servicer, agreement, _ = setup_counterparty_chain()
        create_active_llpa_matrix(rows=rows)
        pool = create_pool_for(seller, agreement, target_balance_cents=2000000000)
        inv_low = create_underwritten_loan(
            seller, servicer, agreement, loan_number="LN-INV-LOW",
            occupancy="INVESTMENT", credit_score=700,
        )
        inv_high = create_underwritten_loan(
            seller, servicer, agreement, loan_number="LN-INV-HIGH",
            occupancy="INVESTMENT", credit_score=800,
        )
        deliver_loan(inv_low, pool, seller)
        deliver_loan(inv_high, pool, seller)
        low_after = get_loan(inv_low["id"])
        high_after = get_loan(inv_high["id"])
        # INVESTMENT/FIXED_30, score 700 -> 300 bps row: 400,000,000 - 12,000,000.
        assert low_after["applied_llpa_bps"] == 300
        assert low_after["delivery_price_cents"] == 388000000
        # INVESTMENT/FIXED_30, score 800 -> 200 bps row: 400,000,000 - 8,000,000.
        assert high_after["applied_llpa_bps"] == 200
        assert high_after["delivery_price_cents"] == 392000000
