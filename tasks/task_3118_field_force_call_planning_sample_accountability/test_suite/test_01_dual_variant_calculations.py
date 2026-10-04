"""Dual-variant calculations: the same ledger inputs feed two documented
figures that diverge by a documented difference.

Queue A — difficulty design rule ``dual_variant_calc``.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


class TestRepBalanceForwardVsConfirmed:
    """RepLotBalance carries both a forward-looking and a confirmed-ledger
    availability (PRD section 2.8)."""

    def test_forward_subtracts_open_transfer_reserve(self, api):
        """PRD section 2.8: "The forward-looking availability, qty_available_forward,
        subtracts the in-transit reserve: it is qty_issued minus qty_dispensed, minus
        qty_returned, minus qty_transferred_out, minus qty_in_transit_out, plus
        qty_transferred_in."

        Design: Difficulty/dual_variant_calc/rep_available_units_forward_vs_confirmed_during_open_transfer
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=50, lot_quantity=500)
        fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 8
        )
        balance = get_success_data(
            api.get_lot_balance(
                ctx["sender_balance"]["id"],
                headers=make_field_rep_headers(ctx["sender"]["id"]),
            )
        )
        assert balance["qty_issued"] == 50
        assert balance["qty_in_transit_out"] == 8
        assert balance["qty_available_forward"] == 42

    def test_confirmed_ignores_open_transfer_reserve(self, api):
        """PRD section 2.8: "The confirmed-ledger availability, qty_available_confirmed,
        ignores the in-transit reserve: it is qty_issued minus qty_dispensed, minus
        qty_returned, minus qty_transferred_out, plus qty_transferred_in."

        Design: Difficulty/dual_variant_calc/rep_available_units_forward_vs_confirmed_during_open_transfer
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=50, lot_quantity=500)
        fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 8
        )
        balance = get_success_data(
            api.get_lot_balance(
                ctx["sender_balance"]["id"],
                headers=make_field_rep_headers(ctx["sender"]["id"]),
            )
        )
        assert balance["qty_available_confirmed"] == 50
        assert (
            balance["qty_available_confirmed"] - balance["qty_available_forward"] == 8
        ), "the two variants diverge by exactly the open reserve"


class TestCallAttainmentVariants:
    """A tier-A entry with 5 completed, 4 cancelled, 3 scheduled visits
    yields 41.67 planned-basis and 62.50 delivered-basis."""

    def _setup_partial_cycle(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api, tier="A", planned_sample_units=24, budget=200
        )
        plan, entry, rep = ctx["plan"], ctx["entry"], ctx["rep"]
        visits = []
        # 9 visits on one day (back-to-back hours, all before the default
        # clock) + 3 later visits still SCHEDULED.
        for hour in range(9):
            visits.append(
                fx.schedule_visit(
                    api,
                    plan["id"],
                    entry["id"],
                    rep,
                    scheduled_start="2026-08-31T{0:02d}:00:00Z".format(hour + 1),
                    scheduled_end="2026-08-31T{0:02d}:00:00Z".format(hour + 2),
                )
            )
        for day in ("2026-09-08", "2026-09-09", "2026-09-10"):
            visits.append(
                fx.schedule_visit(
                    api,
                    plan["id"],
                    entry["id"],
                    rep,
                    scheduled_start="{0}T09:00:00Z".format(day),
                    scheduled_end="{0}T10:00:00Z".format(day),
                )
            )
        for v in visits[:5]:
            fx.complete_visit(api, v["id"], rep)
        for v in visits[5:9]:
            get_success_data(
                api.cancel_call_visit(
                    v["id"], headers=make_field_rep_headers(rep["id"])
                )
            )
        return ctx

    def test_planned_basis_uses_fixed_denominator(self, api):
        """PRD section 3.4: "The planned-basis attainment, call_attainment_pct_planned_basis,
        divides delivered_calls by planned_calls_per_cycle, multiplies by one hundred,
        and rounds half-up to two decimal places; its denominator is fixed at plan
        time."

        Design: Difficulty/dual_variant_calc/call_attainment_planned_basis_vs_delivered_basis_after_cancellation
        """
        ctx = self._setup_partial_cycle(api)
        entry = get_success_data(
            api.get_target_list_entry(
                ctx["entry"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert entry["delivered_calls"] == 5
        assert entry["planned_calls_per_cycle"] == 12
        assert entry["call_attainment_pct_planned_basis"] == pytest.approx(
            41.67, abs=0.005
        )

    def test_delivered_basis_shrinks_with_cancellations(self, api):
        """PRD section 3.4: "The delivered-basis attainment,
        call_attainment_pct_delivered_basis, divides delivered_calls by the larger of
        delivered_calls plus the count of that entry's visits still in SCHEDULED
        status, or one — whichever is greater — multiplies by one hundred, and rounds
        half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/call_attainment_planned_basis_vs_delivered_basis_after_cancellation
        """
        ctx = self._setup_partial_cycle(api)
        entry = get_success_data(
            api.get_target_list_entry(
                ctx["entry"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        # 5 delivered over (5 delivered + 3 still scheduled) = 62.50.
        assert entry["call_attainment_pct_delivered_basis"] == pytest.approx(
            62.50, abs=0.005
        )
        assert entry["call_attainment_pct_delivered_basis"] > (
            entry["call_attainment_pct_planned_basis"]
        )
