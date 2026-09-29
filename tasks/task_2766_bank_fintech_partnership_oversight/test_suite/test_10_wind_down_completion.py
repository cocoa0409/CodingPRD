"""A wind-down plan completes only when the cycle close finds a zero residual."""
from test_helpers import (
    api_client,
    approve_wind_down_plan,
    close_cycle,
    create_batch,
    drain_custody,
    draft_wind_down_plan,
    fund_batch,
    get_success_data,
    open_second_cycle,
    read_custody_account,
    read_partner,
    reconcile_batch,
    set_clock,
    setup_live_partner,
    terminate_agreement,
    validate_success,
)
from test_helpers.fixtures import PO


def _read_plan(plan_id):
    return get_success_data(api_client.get_wind_down_plan(plan_id, PO))


def _larkspur_in_execution():
    ctx = setup_live_partner(
        partner_overrides={
            "legal_name": "Larkspur Money Inc",
            "business_model": "DEPOSIT_WALLET",
            "funding_stage": "SERIES_A",
            "months_runway": 18,
            "disclosed_complaints_per_10k": 2.00,
            "end_user_account_count": 1200,
        },
        agreement_overrides={
            "reserve_requirement_bps": 500,
            "termination_triggers": ["VOLUNTARY"],
        },
        fbo_balance_cents=5_000_000,
        reserve_balance_cents=312_500,
    )
    partner_id = ctx["partner"]["id"]

    batch = create_batch(
        partner_id,
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-15T00:00:00Z",
        gross_settlement_cents=1_000_000,
        interchange_cents=0,
        returns_cents=0,
        partner_reported_net_cents=1_000_000,
    )
    reconcile_batch(batch["id"], 1_000_000)
    funded = fund_batch(batch["id"], funding_reference="WIRE-L-1")
    assert funded["bank_fee_bps_applied"] == 45
    assert funded["bank_fee_cents"] == 29_500
    assert funded["reserve_funding_cents"] == 50_000
    assert funded["net_to_partner_cents"] == 920_500

    ctx["agreement"] = terminate_agreement(ctx["agreement"]["id"], "VOLUNTARY", notice_days=30)
    assert ctx["agreement"]["status"] == "TERMINATED"
    assert read_partner(partner_id)["status"] == "WIND_DOWN"

    plan = draft_wind_down_plan(
        partner_id, notice_days=30, target_completion_date="2026-10-01T00:00:00Z"
    )
    plan = approve_wind_down_plan(plan["id"])
    assert plan["status"] == "APPROVED"

    set_clock("2026-08-31T00:00:00Z")
    ctx["plan"] = validate_success(api_client.execute_wind_down_plan(plan["id"], {}, PO))
    assert ctx["plan"]["status"] == "IN_EXECUTION"
    return ctx


class TestWindDownCompletion:
    def test_a_close_with_cents_still_in_custody_leaves_the_plan_in_execution(self):
        """`residual_balance_cents` is the sum of `balance_cents` over the partner's custody
        accounts whose `status` is `ACTIVE` or `FROZEN`; accounts already `CLOSED` are excluded. Both
        account types are included, so the plan cannot complete while either end-user funds or
        reserve funds remain in custody.

        Design: Difficulty/cross_entity_state_dependency/wind_down_completion_depends_on_custody_residual_at_cycle_close
        """
        ctx = _larkspur_in_execution()
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 4_000_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 333_000

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["plans_completed_count"] == 0

        plan = _read_plan(ctx["plan"]["id"])
        assert plan["status"] == "IN_EXECUTION"
        assert plan["residual_balance_cents"] == 4_333_000, plan["residual_balance_cents"]
        assert plan["completed_at"] is None
        partner = read_partner(ctx["partner"]["id"])
        assert partner["status"] == "WIND_DOWN"
        assert read_custody_account(ctx["fbo"]["id"])["status"] == "ACTIVE"

    def test_draining_custody_lets_the_next_close_complete_the_plan_and_terminate_the_partner(self):
        """A residual of 0 means each of those accounts individually holds a `balance_cents` of 0,
        which is exactly the condition under which an account may close; the plan advances
        `IN_EXECUTION → COMPLETED`: `completed_at` is stamped with the logical clock, every custody
        account belonging to that partner is moved to `CLOSED`, the partner advances `WIND_DOWN →
        TERMINATED`.

        Design: Difficulty/cross_entity_state_dependency/wind_down_completion_depends_on_custody_residual_at_cycle_close
        """
        ctx = _larkspur_in_execution()
        partner_id = ctx["partner"]["id"]
        set_clock("2026-09-01T00:00:00Z")
        first_close = close_cycle(ctx["cycle"]["id"])
        assert first_close["plans_completed_count"] == 0

        second_cycle = open_second_cycle()
        drain_custody(
            partner_id, ctx["fbo"], ctx["reserve"], effective_at="2026-09-01T00:00:00Z"
        )
        mid = _read_plan(ctx["plan"]["id"])
        assert mid["status"] == "IN_EXECUTION", "there is no manual completion step"

        set_clock("2026-10-01T00:00:00Z")
        closed = close_cycle(second_cycle["id"])
        assert closed["status"] == "CLOSED"
        assert closed["plans_completed_count"] == 1

        plan = _read_plan(ctx["plan"]["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["residual_balance_cents"] == 0
        assert plan["completed_at"] is not None

        fbo = read_custody_account(ctx["fbo"]["id"])
        reserve = read_custody_account(ctx["reserve"]["id"])
        assert fbo["balance_cents"] == 0 and fbo["status"] == "CLOSED"
        assert reserve["balance_cents"] == 0 and reserve["status"] == "CLOSED"

        partner = read_partner(partner_id)
        assert partner["status"] == "TERMINATED"
        assert partner["cumulative_paid_out_cents"] == 920_500
        assert partner["cumulative_bank_fee_cents"] == 29_500
