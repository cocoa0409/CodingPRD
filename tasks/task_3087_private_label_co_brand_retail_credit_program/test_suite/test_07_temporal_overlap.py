"""Temporal windows: the half-open settlement period and the inclusive promo
expiry instant.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    setup_program,
    setup_program_with_account,
    open_settlement_batch,
    post_promo_purchase,
    get_plan_for_transaction,
)


class TestSettlementPeriodHalfOpen:

    def test_adjacent_periods_sharing_only_an_endpoint_do_not_overlap(self, api, admin_headers):
        """PRD §3.7: "A `ProgramAdmin` opens a `SettlementBatch` against an
        `agreement_id` with a `period_start` instant that is inclusive and a
        `period_end` instant that is exclusive."

        Design: Difficulty/resource_temporal_overlap/settlement_periods_half_open_non_overlap
        """
        _partner, agreement, _program = setup_program(api)
        september = open_settlement_batch(api, agreement["id"],
                                          "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        validate_success(api.finalize_settlement_batch(september["id"], admin_headers), 200)

        october = validate_success(
            api.create_settlement_batch(
                {"agreement_id": agreement["id"],
                 "period_start": "2026-10-01T00:00:00Z",
                 "period_end": "2026-11-01T00:00:00Z",
                 "settlement_method": "AS_CHARGED",
                 "reconciliation_method": "PROJECTED"},
                admin_headers,
            ),
            201,
        )
        assert october["batch_status"] == "OPEN", (
            "[2026-09-01, 2026-10-01) and [2026-10-01, 2026-11-01) share no instant"
        )

    def test_a_period_that_ends_inside_a_settled_window_is_accepted_as_a_fresh_batch(
            self, api, admin_headers):
        """PRD §3.7: "It is every promotional plan whose `promo_start_at` falls
        within the half-open window running from `period_start` inclusive to
        `period_end` exclusive". PRD §3.7: "A batch may only finalize from the
        `OPEN` state."

        Design: Difficulty/resource_temporal_overlap/settlement_periods_half_open_non_overlap
        """
        _partner, agreement, _program = setup_program(api)
        september = open_settlement_batch(api, agreement["id"],
                                          "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        validate_success(api.finalize_settlement_batch(september["id"], admin_headers), 200)

        a_later_batch = validate_success(
            api.create_settlement_batch(
                {"agreement_id": agreement["id"],
                 "period_start": "2026-11-01T00:00:00Z",
                 "period_end": "2026-12-01T00:00:00Z",
                 "settlement_method": "AS_CHARGED",
                 "reconciliation_method": "PROJECTED"},
                admin_headers,
            ),
            201,
        )
        assert a_later_batch["batch_status"] == "OPEN"
        assert a_later_batch["transaction_count"] == 0, "no promotions fall in the later window"


class TestPromotionalExpiryInclusiveBoundary:

    def test_expiry_instant_derives_from_start_plus_term_times_thirty_days(self, api, admin_headers):
        """PRD §3.4: "`promo_start_at` is the logical-clock instant the plan
        qualified, and `promo_expires_at` is that instant advanced by the term
        length multiplied by 30 days."

        Design: Difficulty/resource_temporal_overlap/promotional_windows_payoff_at_expiry_boundary
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])

        assert plan["promo_expires_at"] == "2027-08-27T00:00:00Z", (
            "2026-09-01 advanced by 12 * 30 days"
        )

    def test_plan_expires_once_the_clock_reaches_the_expiry_instant(self, api, admin_headers):
        """PRD §3.4: "A cardholder-service operator can also expire a plan
        explicitly, but only once the clock is at or after `promo_expires_at`; an
        attempt to expire a plan early is rejected with `ERR_PROMO_NOT_EXPIRED`
        (HTTP 422), and the explicit expiry likewise sets the risk figure to zero
        and recomputes exposure."

        Design: Difficulty/resource_temporal_overlap/promotional_windows_payoff_at_expiry_boundary
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])

        too_early = api.expire_promo_plan(plan["id"], admin_headers)
        validate_error(too_early, ApiErrorId.ERR_PROMO_NOT_EXPIRED, 422)
        assert get_success_data(api.get_promo_plan(plan["id"], admin_headers))["plan_status"] == "ACTIVE"

        # 360 days lands exactly on promo_expires_at: the boundary is inclusive.
        get_success_data(api.advance_clock(360, admin_headers))
        expired = validate_success(api.expire_promo_plan(plan["id"], admin_headers), 200)
        assert expired["plan_status"] == "EXPIRED"
        assert expired["subsidy_at_risk_cents"] == 0