"""States that are revisited: the suspend-and-cure cycle and the two claim axes."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import (
    ADJUSTER,
    ADJUSTER_USER_ID,
    MANAGER,
    MANAGER_USER_ID,
    UNDERWRITER,
)

AUGUST = ("2026-08-01", "2026-08-31")


def swept_reporting_file(api):
    """A monthly reporting file whose August period is one day past its grace date."""
    ctx = fixtures.build_reporting_file(
        api, policy_kwargs=dict(policyholder_name="Ridgeline Yard Stock"))
    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    return ctx


def test_an_unanswered_period_suspends_the_policy_the_sweep_runs_against(api):
    """The sweep mints a zero-value delinquent report and takes the policy off risk.

    PRD: For every reporting period of the part, derived as described above, whose `due_date` is strictly before the logical clock's current date and for which no report on the part in status `SUBMITTED`, `ACCEPTED` or `PENALIZED` exists for that exact period, the sweep mints a report with `reported_value_cents` of zero, `period_earned_premium_cents` and `late_penalty_cents` of zero, `submitted_at` stamped from the logical clock, and status `DELINQUENT`.
    PRD: The response reports `swept_period_count`, the `delinquent_report_ids` it created, the resulting `policy_status`, and the `part_id` it ran against.
    Design: Difficulty/non_linear_state_machine/policy_suspend_and_cure_cycle_through_report_supersede
    """
    ctx = swept_reporting_file(api)
    before = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert before["status"] == "IN_FORCE"
    assert before["premium_balance_cents"] == 100000

    swept = validate_success(api.run_reporting_sweep(ctx.part_id, UNDERWRITER))

    assert swept["swept_period_count"] == 1
    assert swept["policy_status"] == "SUSPENDED"
    assert swept["part_id"] == ctx.part_id
    assert len(swept["delinquent_report_ids"]) == 1

    assert get_success_data(
        api.get_policy(ctx.policy_id, UNDERWRITER))["status"] == "SUSPENDED"
    minted = get_success_data(api.get_value_report(
        swept["delinquent_report_ids"][0], UNDERWRITER))
    assert minted["status"] == "DELINQUENT"
    assert minted["reported_value_cents"] == 0
    assert minted["period_start_date"] == AUGUST[0]
    assert minted["period_end_date"] == AUGUST[1]
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["latest_report_period_end_date"] == AUGUST[1]


def test_filing_the_missing_report_cures_the_suspension_and_earns_a_penalty(api):
    """The policy returns to a state it already left, carrying a different balance.

    PRD: If the predecessor being superseded was the last report in status `DELINQUENT` anywhere on the policy and the policy is `SUSPENDED`, the policy returns `SUSPENDED` → `IN_FORCE` in the same call: filing the missing report is itself the cure.
    PRD: The late branch moves the report `SUBMITTED` → `PENALIZED`, sets `late_penalty_cents` to 1,000 basis points — ten percent — of the **already-rounded** `period_earned_premium_cents`, divided by ten thousand and rounded half-up a second time, and appends **two** ledger entries: the same positive `REPORTING_ADJUSTMENT` for the period premium, plus a `LATE_REPORTING_PENALTY` for the positive `late_penalty_cents`.
    Design: Difficulty/non_linear_state_machine/policy_suspend_and_cure_cycle_through_report_supersede
    """
    ctx = swept_reporting_file(api)
    swept = validate_success(api.run_reporting_sweep(ctx.part_id, UNDERWRITER))
    delinquent_id = swept["delinquent_report_ids"][0]

    filed = fixtures.file_value_report(api, ctx.part_id, AUGUST[0], AUGUST[1], 9000000)

    assert filed["period_days"] == 31
    assert filed["due_date"] == "2026-09-15"
    assert filed["status"] == "SUBMITTED"
    superseded = get_success_data(api.get_value_report(delinquent_id, UNDERWRITER))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_report_id"] == filed["id"]
    assert get_success_data(
        api.get_policy(ctx.policy_id, UNDERWRITER))["status"] == "IN_FORCE"

    adjudicated = validate_success(
        api.adjudicate_value_report(filed["id"], UNDERWRITER))

    assert adjudicated["status"] == "PENALIZED"
    assert adjudicated["period_earned_premium_cents"] == 19110
    assert adjudicated["late_penalty_cents"] == 1911
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["earned_reported_premium_cents"] == 19110
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["premium_balance_cents"] == 121021
    assert policy["status"] == "IN_FORCE"

    chain, meta = validate_paginated(
        api.list_superseded_reports(filed["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
    assert chain[0]["id"] == delinquent_id


def two_rig_file_on_risk(api):
    """Two identically priced rigs on one scheduled part, both on risk from a quote."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Twin Rig Contractors")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    rig_a = fixtures.schedule_item(api, part["id"], policy["id"],
                                   description="Rig A")
    rig_b = fixtures.schedule_item(api, part["id"], policy["id"],
                                   description="Rig B")
    quoted = fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, rig_a["id"])
    fixtures.activate_item(api, rig_b["id"])
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    return fixtures.Ctx(policy_id=policy["id"], part_id=part["id"],
                        item_a_id=rig_a["id"], item_b_id=rig_b["id"],
                        quoted=quoted)


def adjusted_claim(api, ctx, item_id, loss_type, loss_date, repair_estimate_cents,
                   basis):
    """Open, inspect and adjust one claim on the named rig."""
    claim = get_success_data(api.create_claim(
        ctx.policy_id,
        factories.claim(ctx.part_id, loss_date=loss_date, loss_type=loss_type,
                        equipment_item_id=item_id),
        UNDERWRITER))
    get_success_data(api.inspect_claim(
        claim["id"], factories.inspection(repair_estimate_cents, 8160000), ADJUSTER))
    return get_success_data(api.adjust_claim(
        claim["id"], factories.adjustment(basis), ADJUSTER))


def two_claims_on_two_rigs(api):
    """One total loss on Rig A and one repair on Rig B, each awaiting authorisation."""
    ctx = two_rig_file_on_risk(api)
    ctx["claim_a"] = adjusted_claim(api, ctx, ctx.item_a_id, "FIRE", "2026-08-15",
                                    7000000, "TOTAL_LOSS")
    ctx["claim_b"] = adjusted_claim(api, ctx, ctx.item_b_id, "VANDALISM",
                                    "2026-08-16", 3000000, "REPAIR")
    return ctx


def test_the_repair_axis_closes_inside_settlement_while_the_total_loss_axis_waits(api):
    """One settlement call reaches CLOSED and the other stops at SETTLED.

    PRD: The two axes join at `CLOSED`: the claim reaches `CLOSED` only once the salvage axis is not `PENDING`.
    PRD: On the repair branch that is the whole call: because `salvage_status` is `NOT_APPLICABLE`, the adjustment axis advances straight through `SETTLED` to `CLOSED` in the same call, and the response shows `adjustment_status` `CLOSED`.
    Design: Difficulty/non_linear_state_machine/claim_parallel_axes_join_at_closed
    """
    ctx = two_claims_on_two_rigs(api)
    assert ctx.quoted["written_premium_cents"] == 360501
    assert ctx.claim_a["adjustment_status"] == "TOTAL_LOSS_DECLARED"
    assert ctx.claim_a["salvage_status"] == "PENDING"
    assert ctx.claim_b["adjustment_status"] == "REPAIR_APPROVED"
    assert ctx.claim_b["salvage_status"] == "NOT_APPLICABLE"

    repaired = fixtures.settle(api, ctx.claim_b["id"])

    assert repaired["adjustment_status"] == "CLOSED"
    assert repaired["salvage_status"] == "NOT_APPLICABLE"
    assert repaired["settlement_paid_cents"] == 2900000
    assert repaired["settled_by_user_id"] == MANAGER_USER_ID
    assert get_success_data(
        api.get_equipment_item(ctx.item_b_id, UNDERWRITER))["status"] == "ACTIVE"

    totalled = fixtures.settle(api, ctx.claim_a["id"])

    assert totalled["adjustment_status"] == "SETTLED"
    assert totalled["salvage_status"] == "PENDING"
    assert totalled["settlement_paid_cents"] == 8060000
    assert get_success_data(
        api.get_equipment_item(ctx.item_a_id, UNDERWRITER))["status"] == "TOTALED"


def test_recording_salvage_joins_the_axes_and_gives_capacity_back(api):
    """The recovery credit closes the claim and restores the part's drawn capacity.

    PRD: Proceeds above zero move the salvage axis `PENDING` → `RECOVERED` and set `salvage_credit_cents` to the smaller of `salvage_proceeds_cents` and `settlement_paid_cents`, so a recovery worth more than the cheque credits only what was paid; a `SALVAGE_RECOVERY` entry is appended to the loss ledger for the negative of `salvage_credit_cents`, `incurred_loss_cents` is refreshed, and the conserved capacity is compensated by subtracting `salvage_credit_cents` from `aggregate_paid_net_cents` and adding it back to `aggregate_available_cents`.
    PRD: Either branch closes the join: `adjustment_status` advances `SETTLED` → `CLOSED`, `CLOSED` is terminal on the adjustment axis, and `RECOVERED` and `WAIVED` are terminal on the salvage axis.
    Design: Difficulty/non_linear_state_machine/claim_parallel_axes_join_at_closed
    """
    ctx = two_claims_on_two_rigs(api)
    fixtures.settle(api, ctx.claim_b["id"])
    fixtures.settle(api, ctx.claim_a["id"])

    recovered = validate_success(api.record_salvage_recovery(
        ctx.claim_a["id"], factories.salvage(1500000), ADJUSTER))

    assert recovered["salvage_status"] == "RECOVERED"
    assert recovered["salvage_proceeds_cents"] == 1500000
    assert recovered["salvage_credit_cents"] == 1500000
    assert recovered["adjustment_status"] == "CLOSED"

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 9460000
    assert part["aggregate_available_cents"] == 190540000
    assert part["rated_premium_cents"] == 173318
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["incurred_loss_cents"] == 9460000
