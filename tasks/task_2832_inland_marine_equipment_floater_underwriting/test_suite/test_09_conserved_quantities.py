"""Quantities that must reconcile: the premium ledger and the part's aggregate capacity."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import ADJUSTER, MANAGER, UNDERWRITER
from test_helpers.types import Ledger


def priced_file_in_november(api):
    """The canonical on-risk file, plus a generator cell, with 273 term days left."""
    ctx = fixtures.build_in_force_file(api)
    fixtures.publish_rate_rule(api, equipment_type="GENERATOR",
                               age_band_min_years=6, age_band_max_years=12,
                               base_rate_bp=120, theft_hazard_grade="C")
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    return ctx


def endorse_a_generator_on(api, ctx):
    """Schedule a 2018 generator onto the live part at the November clock."""
    return fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                  description="E2 generator",
                                  equipment_type="GENERATOR", model_year=2018,
                                  original_cost_cents=2000000,
                                  geo_tracker_installed=False)


def premium_rows(api, policy_id):
    """The PREMIUM book with its pagination envelope."""
    return validate_paginated(api.list_ledger_entries(
        policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.PREMIUM))


def test_a_mid_term_addition_books_the_unloaded_prorated_premium(api):
    """The ledger moves by 6721 while the written premium moves by 9345.

    PRD: The territory expense load is deliberately not re-applied to a mid-term endorsement, so the ledger records the unloaded prorated item premium while `written_premium_cents` is independently re-derived, loaded and floored.
    PRD: The two conserved quantities on a policy follow directly: `premium_balance_cents` is the sum of `amount_cents` over that policy's entries in the `PREMIUM` ledger, and `incurred_loss_cents` is the sum over its entries in the `LOSS` ledger.
    Design: Difficulty/compensating_invariant/premium_balance_reconciles_after_endorsement_add_then_remove
    """
    ctx = priced_file_in_november(api)
    before = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert before["written_premium_cents"] == 180251
    assert before["premium_balance_cents"] == 180251

    generator = endorse_a_generator_on(api, ctx)

    assert generator["age_years_at_rating"] == 8
    assert generator["insured_value_cents"] == 720000
    assert generator["rated_premium_cents"] == 8986
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 182304

    rows, meta = premium_rows(api, ctx.policy_id)
    added = find_entry(rows, "ENDORSEMENT_PREMIUM")
    assert added is not None
    assert added["ledger"] == "PREMIUM"
    assert added["amount_cents"] == 6721

    after = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert after["written_premium_cents"] == 189596
    assert after["premium_balance_cents"] == 186972
    assert after["premium_balance_cents"] == sum(r["amount_cents"] for r in rows)
    assert after["written_premium_cents"] - before["written_premium_cents"] == 9345


def test_endorsing_the_same_unit_back_off_leaves_the_balance_exactly_where_it_was(api):
    """Two 6721 rows in opposite directions, three rows in the book, no drift.

    PRD: Adding a unit and removing it again on the same logical day is therefore an exact compensating pair: `remaining_days` is identical, so `premium_balance_cents` and `written_premium_cents` both return to their prior values.
    PRD: An item may be endorsed off the schedule from either `RATED` or `ACTIVE`, moving to `REMOVED` with `removed_at` stamped from the logical clock.
    Design: Difficulty/compensating_invariant/premium_balance_reconciles_after_endorsement_add_then_remove
    """
    ctx = priced_file_in_november(api)
    generator = endorse_a_generator_on(api, ctx)

    get_success_data(api.delete_equipment_item(generator["id"], UNDERWRITER))

    removed = get_success_data(api.get_equipment_item(generator["id"], UNDERWRITER))
    assert removed["status"] == "REMOVED"
    assert_instant_equals(removed["removed_at"], "2026-11-01T00:00:00Z")

    rows, meta = premium_rows(api, ctx.policy_id)
    returned = find_entry(rows, "ENDORSEMENT_RETURN")
    assert returned is not None
    assert returned["amount_cents"] == -6721
    assert meta["total_count"] == 3
    assert sum(row["amount_cents"] for row in rows) == 180251

    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 173318
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["written_premium_cents"] == 180251
    assert policy["premium_balance_cents"] == 180251
    assert policy["total_insured_value_cents"] == 8160000
    survivor = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert survivor["status"] == "ACTIVE"
    assert survivor["rated_premium_cents"] == 173318


def total_loss_awaiting_the_cheque(api):
    """The canonical file with an October total loss declared and salvage armed."""
    ctx = fixtures.build_in_force_file(api)
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    ctx["claim"] = fixtures.build_total_loss_claim(
        api, ctx, loss_date="2026-10-20", loss_type="FIRE")
    return ctx


def capacity(api, part_id):
    """The part's two capacity halves, which must always add to the limit."""
    part = get_success_data(api.get_coverage_part(part_id, UNDERWRITER))
    return part["aggregate_available_cents"], part["aggregate_paid_net_cents"]


def test_settlement_moves_capacity_from_available_to_paid_without_losing_any(api):
    """Eight million and sixty thousand crosses the line and the sum is unmoved.

    PRD: The identity `aggregate_limit_cents` equals `aggregate_available_cents` plus `aggregate_paid_net_cents` holds at every observable moment.
    PRD: A claim settlement adds the amount paid to `aggregate_paid_net_cents` and subtracts the same amount from `aggregate_available_cents`.
    Design: Difficulty/compensating_invariant/part_aggregate_capacity_conserved_across_settlement_and_salvage
    """
    ctx = total_loss_awaiting_the_cheque(api)
    assert capacity(api, ctx.part_id) == (200000000, 0)
    assert ctx.claim["valuation_at_loss_cents"] == 8160000
    assert ctx.claim["total_loss_basis_settlement_cents"] == 8060000
    assert ctx.claim["settlement_amount_cents"] == 8060000
    assert ctx.claim["adjustment_status"] == "TOTAL_LOSS_DECLARED"
    assert ctx.claim["salvage_status"] == "PENDING"

    settled = validate_success(api.settle_claim(ctx.claim["id"], MANAGER))

    assert settled["adjustment_status"] == "SETTLED"
    assert settled["settlement_paid_cents"] == 8060000
    available, paid = capacity(api, ctx.part_id)
    assert (available, paid) == (191940000, 8060000)
    assert available + paid == 200000000
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "TOTALED"
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 8060000


def test_salvage_credits_the_capacity_back_and_closes_the_join(api):
    """The recovery is a compensating move, not a memorandum of proceeds.

    PRD: A salvage recovery makes the compensating move, subtracting the credited salvage from `aggregate_paid_net_cents` and adding it back to `aggregate_available_cents`.
    PRD: Proceeds above zero move the salvage axis `PENDING` → `RECOVERED` and set `salvage_credit_cents` to the smaller of `salvage_proceeds_cents` and `settlement_paid_cents`, so a recovery worth more than the cheque credits only what was paid; a `SALVAGE_RECOVERY` entry is appended to the loss ledger for the negative of `salvage_credit_cents`, `incurred_loss_cents` is refreshed, and the conserved capacity is compensated by subtracting `salvage_credit_cents` from `aggregate_paid_net_cents` and adding it back to `aggregate_available_cents`.
    Design: Difficulty/compensating_invariant/part_aggregate_capacity_conserved_across_settlement_and_salvage
    """
    ctx = total_loss_awaiting_the_cheque(api)
    validate_success(api.settle_claim(ctx.claim["id"], MANAGER))

    recovered = validate_success(api.record_salvage_recovery(
        ctx.claim["id"], factories.salvage(1500000), ADJUSTER))

    assert recovered["salvage_proceeds_cents"] == 1500000
    assert recovered["salvage_credit_cents"] == 1500000
    assert recovered["salvage_status"] == "RECOVERED"
    assert recovered["adjustment_status"] == "CLOSED"

    available, paid = capacity(api, ctx.part_id)
    assert (available, paid) == (193440000, 6560000)
    assert available + paid == 200000000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 6560000

    rows, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 2
    assert sum(row["amount_cents"] for row in rows) == 6560000
    assert find_entry(rows, "CLAIM_SETTLEMENT")["amount_cents"] == 8060000
    assert find_entry(rows, "SALVAGE_RECOVERY")["amount_cents"] == -1500000
    assert find_entry(rows, "SALVAGE_RECOVERY")["ledger"] == "LOSS"
