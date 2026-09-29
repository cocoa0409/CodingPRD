"""One call, four hops: the total-loss cascade and the floater acceptance cascade."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_earned_plus_unearned_is_rated,
    assert_ledger_entry_shape,
)
from test_helpers.test_users import ADJUSTER, UNDERWRITER


def stolen_rig_awaiting_authorisation(api):
    """The canonical on-risk file with a declared total loss late in the term."""
    ctx = fixtures.build_in_force_file(api)
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    ctx["claim"] = fixtures.build_total_loss_claim(
        api, ctx, loss_date="2026-11-01", loss_type="THEFT")
    return ctx


def test_settling_a_total_loss_books_the_loss_and_takes_the_unit_off_risk(api):
    """Hop one moves money into the loss book; hop two retires the subject.

    PRD: Settlement sets `settlement_paid_cents` to `settlement_amount_cents`, records `settled_by_user_id`, appends a `CLAIM_SETTLEMENT` entry to the **loss** ledger for the positive `settlement_paid_cents` carrying this claim's identifier, refreshes the policy's `incurred_loss_cents`, and moves the part's conserved capacity by adding the paid amount to `aggregate_paid_net_cents` and subtracting it from `aggregate_available_cents`.
    PRD: Hop two takes the loss subject off risk: an equipment item becomes `TOTALED`, an `IN_TRANSIT` transit shipment becomes `LOST` with the vehicle's `in_transit_value_cents` recomputed.
    Design: Difficulty/transitive_cascade/total_loss_settlement_four_hop_cascade
    """
    ctx = stolen_rig_awaiting_authorisation(api)
    assert ctx.claim["settlement_amount_cents"] == 8060000

    settled = fixtures.settle(api, ctx.claim["id"])

    assert settled["adjustment_status"] == "SETTLED"
    assert settled["salvage_status"] == "PENDING"
    assert settled["settlement_paid_cents"] == 8060000

    rows, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
    assert_ledger_entry_shape(rows[0])
    assert rows[0]["entry_type"] == "CLAIM_SETTLEMENT"
    assert rows[0]["ledger"] == "LOSS"
    assert rows[0]["amount_cents"] == 8060000

    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["incurred_loss_cents"] == 8060000
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 8060000
    assert part["aggregate_available_cents"] == 191940000
    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["status"] == "TOTALED"
    assert item["rated_premium_cents"] == 173318


def test_the_retired_unit_returns_its_unearned_premium_and_empties_the_part(api):
    """Hop three returns the prorated premium; hop four re-rolls the policy onto its floor.

    PRD: Hop three, for equipment subjects only, recomputes the parent part's `rated_premium_cents` over its remaining items in status `RATED` or `ACTIVE` and appends an `ENDORSEMENT_RETURN` entry for the removed item's prorated premium, computed exactly as an endorsement removal is.
    PRD: Otherwise the amount is the item's `rated_premium_cents` multiplied by `remaining_days`, divided by the policy's `term_days`, and rounded half-up once.
    Design: Difficulty/transitive_cascade/total_loss_settlement_four_hop_cascade
    """
    ctx = stolen_rig_awaiting_authorisation(api)
    before = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert before["written_premium_cents"] == 180251
    assert before["premium_balance_cents"] == 180251

    fixtures.settle(api, ctx.claim["id"])

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == 0

    returns = [row for row in fixtures.premium_ledger(api, ctx.policy_id)
               if row["entry_type"] == "ENDORSEMENT_RETURN"]
    assert len(returns) == 1
    assert returns[0]["amount_cents"] == -129632

    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["sum_of_part_premiums_cents"] == 0
    assert policy["written_premium_cents"] == 100000
    assert policy["total_insured_value_cents"] == 0
    assert policy["premium_balance_cents"] == 50619


def tower_file_with_a_sited_rig_and_a_live_floater(api):
    """One jobsite carrying both a credited rig and the only live floater on it."""
    fixtures.publish_rate_rule(api)
    site = fixtures.create_jobsite(api, name="J1 tower site")
    site = fixtures.survey_jobsite(api, site["id"], factories.SURVEY_TIER_2)
    policy = fixtures.create_policy(api, policyholder_name="Ridgeline Contractors")
    equipment = fixtures.create_part(api, policy["id"],
                                     factories.scheduled_equipment_part())
    floater_part = fixtures.create_part(api, policy["id"],
                                        factories.installation_floater_part())
    item = fixtures.schedule_item(api, equipment["id"], policy["id"],
                                  description="E1 excavator",
                                  geo_tracker_installed=False,
                                  assigned_jobsite_id=site["id"])
    floater = fixtures.open_floater(
        api, floater_part["id"], site["id"], project_name="Tower A fit-out",
        installed_value_limit_cents=20000000,
        coverage_start_date="2026-09-01", coverage_end_date="2026-12-01")
    quoted = fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, item["id"])
    fixtures.activate_floater(api, floater["id"])
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    return fixtures.Ctx(policy_id=policy["id"], jobsite_id=site["id"],
                        equipment_part_id=equipment["id"],
                        floater_part_id=floater_part["id"],
                        item_id=item["id"], floater_id=floater["id"],
                        quoted=quoted, floater=floater, item=item)


def test_accepting_the_work_returns_the_unearned_premium_and_releases_the_site(api):
    """Hop one splits the floater premium exactly; hop two empties the jobsite.

    PRD: On `ACCEPTANCE` — the owner has accepted the completed work — the floater moves to `TERMINATED_ACCEPTANCE`, `earned_premium_cents` is `rated_premium_cents` multiplied by `elapsed_days`, divided by `term_days`, rounded half-up once, `unearned_return_cents` is `rated_premium_cents` minus that earned figure, and an `ENDORSEMENT_RETURN` entry is appended to the premium ledger for the negative of `unearned_return_cents`.
    PRD: When the count falls to 0 from a positive value on a site that is `SURVEYED`, the site transitions `SURVEYED` → `RELEASED`, and the release is not cosmetic: a released site is no longer treated as secured, so every equipment item still assigned to it whose status is `RATED` or `ACTIVE` is re-rated with a jobsite security credit of zero.
    Design: Difficulty/transitive_cascade/floater_acceptance_termination_four_hop_cascade
    """
    ctx = tower_file_with_a_sited_rig_and_a_live_floater(api)
    live = get_success_data(api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert live["term_days"] == 92
    assert live["rated_premium_cents"] == 70575
    assert ctx.quoted["sum_of_part_premiums_cents"] == 231761
    assert ctx.quoted["written_premium_cents"] == 241031

    terminated = validate_success(api.terminate_installation_floater(
        ctx.floater_id,
        factories.floater_termination("ACCEPTANCE", "2026-10-01"),
        UNDERWRITER))

    assert terminated["status"] == "TERMINATED_ACCEPTANCE"
    assert terminated["termination_trigger"] == "ACCEPTANCE"
    assert terminated["earned_premium_cents"] == 23781
    assert terminated["unearned_return_cents"] == 46794
    assert_earned_plus_unearned_is_rated(terminated)

    returns = [row for row in fixtures.premium_ledger(api, ctx.policy_id)
               if row["entry_type"] == "ENDORSEMENT_RETURN"]
    assert len(returns) == 1
    assert returns[0]["amount_cents"] == -46794

    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["active_floater_count"] == 0
    assert site["status"] == "RELEASED"


def test_the_released_site_strips_the_credit_and_the_policy_still_rolls_down(api):
    """Hop three raises one item premium; hop four lowers the policy anyway.

    PRD: Those items keep their `assigned_jobsite_id` — they are still physically there — but they lose the credit, which raises their premium.
    PRD: The `INSTALLATION_FLOATER` part's `rated_premium_cents` is the sum, over **every** floater on the part in **any** status, of that floater's `rated_premium_cents` minus its `unearned_return_cents`.
    Design: Difficulty/transitive_cascade/floater_acceptance_termination_four_hop_cascade
    """
    ctx = tower_file_with_a_sited_rig_and_a_live_floater(api)
    assert ctx.item["applied_credit_bp"] == 700
    assert ctx.item["rated_premium_cents"] == 161186

    validate_success(api.terminate_installation_floater(
        ctx.floater_id,
        factories.floater_termination("ACCEPTANCE", "2026-10-01"),
        UNDERWRITER))

    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["applied_credit_bp"] == 0
    assert item["rated_premium_cents"] == 173318
    assert item["status"] == "ACTIVE"
    assert item["assigned_jobsite_id"] == ctx.jobsite_id

    assert get_success_data(api.get_coverage_part(
        ctx.equipment_part_id, UNDERWRITER))["rated_premium_cents"] == 173318
    assert get_success_data(api.get_coverage_part(
        ctx.floater_part_id, UNDERWRITER))["rated_premium_cents"] == 23781
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["sum_of_part_premiums_cents"] == 197099
    assert policy["written_premium_cents"] == 204983
