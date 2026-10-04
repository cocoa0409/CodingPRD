"""Combinatorial formulas: the four-term per-visit cap min() and the nested
per-entry allocation rounding.

Queue A — difficulty design rule ``combinatorial_formula``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def _drive_signed_units(api, ctx, count, quantity_each):
    """Create, complete, and fully sign ``count`` visits of
    ``quantity_each`` units to accumulate prescriber YTD usage."""
    for index in range(count):
        visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-08-31T{0:02d}:00:00Z".format(1 + index),
            scheduled_end="2026-08-31T{0:02d}:00:00Z".format(2 + index),
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        disbursement = get_success_data(
            api.create_sample_disbursement(
                f.create_sample_disbursement_payload(
                    visit["id"], ctx["lot"]["id"], quantity_each
                ),
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        fx.sign_disbursement(api, disbursement["id"], ctx["rep"])


class TestPerVisitCapMinTerm:
    """cap = min(per-visit max, annual remainder, rep forward balance, entry
    remainder).  This family pins the annual-remainder term as binding."""

    def _setup_annual_remainder_four(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="A",
            planned_sample_units=24,
            budget=200,
            rep_issue_qty=30,
            lot_quantity=100,
            per_visit_max_units=10,
            annual_max_units_per_prescriber=25,
        )
        # YTD 21 via three signed disbursements of 7.
        _drive_signed_units(api, ctx, 3, 7)
        return ctx

    def test_quantity_above_annual_remainder_rejected(self, api):
        """PRD section 3.5: "the acceptable ceiling is the smallest of the product's
        per_visit_max_units; the product's annual_max_units_per_prescriber minus the
        prescriber's year-to-date usage across all representatives ... floored at zero;
        the rep's qty_available_forward for the lot; and the entry's
        planned_sample_units minus its delivered_sample_units, floored at zero. ...
        anything above it is rejected with ERR_QUANTITY_LIMIT_EXCEEDED."

        Design: Difficulty/combinatorial_formula/per_visit_cap_four_term_min_selects_annual_remainder
        """
        ctx = self._setup_annual_remainder_four(api)
        visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-08-31T11:00:00Z",
            scheduled_end="2026-08-31T12:00:00Z",
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        response = api.create_sample_disbursement(
            f.create_sample_disbursement_payload(visit["id"], ctx["lot"]["id"], 5),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        # min(10, 25-21=4, 30-21=9, 24-21=3) -> entry remainder 3 binds too;
        # 5 exceeds both, so the cap rule rejects.
        validate_error(response, ApiErrorId.ERR_QUANTITY_LIMIT_EXCEEDED)

    def test_quantity_within_annual_remainder_accepted(self, api):
        """PRD section 3.5: "A quantity of at least 1 and no greater than this ceiling
        is accepted."

        Design: Difficulty/combinatorial_formula/per_visit_cap_four_term_min_selects_annual_remainder
        """
        ctx = self._setup_annual_remainder_four(api)
        visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-08-31T11:00:00Z",
            scheduled_end="2026-08-31T12:00:00Z",
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        response = api.create_sample_disbursement(
            f.create_sample_disbursement_payload(visit["id"], ctx["lot"]["id"], 3),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        data = validate_success(response, expected_status=201)
        assert data["reconciliation_status"] == "PENDING_SIGNATURE"


class TestTerritoryAllocationRounding:
    """Per-entry round-half-up, then sum — never the other way around.
    Budget 103 over tiers A/B/C (weights 6/3/1) yields 62 + 31 + 10."""

    def _setup_three_tier_territory(self, api, budget=103):
        region, territory, manager = fx.setup_manager_territory(api, budget=budget)
        product = fx.create_product(api)
        prescribers = [fx.create_prescriber(api) for _ in range(3)]
        entries = {}
        for tier, prescriber in zip(("A", "B", "C"), prescribers):
            entries[tier] = fx.add_target_entry(
                api,
                territory["id"],
                prescriber["id"],
                product["id"],
                manager,
                tier=tier,
                planned_sample_units=0,
            )
        return territory, manager, entries

    def test_per_entry_rounded_values(self, api):
        """PRD section 3.3: "each entry's share is the budget multiplied by the
        entry's tier weight and divided by the sum of weights across all active
        entries, rounded half-up to a whole unit per entry."

        Design: Difficulty/combinatorial_formula/territory_allocation_round_per_entry_then_sum
        """
        territory, manager, entries = self._setup_three_tier_territory(api)
        fx.create_plan(api, territory["id"], territory["version"], manager)
        a = get_success_data(
            api.get_target_list_entry(
                entries["A"]["id"],
                headers=make_district_manager_headers(manager["id"]),
            )
        )
        b = get_success_data(
            api.get_target_list_entry(
                entries["B"]["id"],
                headers=make_district_manager_headers(manager["id"]),
            )
        )
        c = get_success_data(
            api.get_target_list_entry(
                entries["C"]["id"],
                headers=make_district_manager_headers(manager["id"]),
            )
        )
        # round_half_up(103*6/10)=62, round_half_up(30.9)=31, round_half_up(10.3)=10.
        assert a["planned_sample_units"] == 62
        assert b["planned_sample_units"] == 31
        assert c["planned_sample_units"] == 10

    def test_territory_consumed_is_plain_sum_no_re_round(self, api):
        """PRD section 3.3: "The territory's consumed budget is then the plain sum of
        those per-entry rounded values, with no final re-rounding and no
        largest-remainder redistribution; the rounding happens per entry first and
        the sum is taken afterward, never the other way around."

        Design: Difficulty/combinatorial_formula/territory_allocation_round_per_entry_then_sum
        """
        territory, manager, entries = self._setup_three_tier_territory(api)
        fx.create_plan(api, territory["id"], territory["version"], manager)
        total = 0
        for tier in ("A", "B", "C"):
            entry = get_success_data(
                api.get_target_list_entry(
                    entries[tier]["id"],
                    headers=make_district_manager_headers(manager["id"]),
                )
            )
            total += entry["planned_sample_units"]
        assert total == 103, (
            "per-entry rounding then summing yields 103; a sum-then-round or "
            "largest-remainder scheme would distribute the units differently"
        )
