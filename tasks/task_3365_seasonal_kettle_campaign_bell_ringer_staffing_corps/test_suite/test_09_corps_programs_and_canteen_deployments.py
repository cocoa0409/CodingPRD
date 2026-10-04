"""Corps community program enrollment and disaster canteen deployment billing."""
from test_helpers import (
    approve_deployment,
    create_corps_program,
    create_deployment,
    create_unit,
    deploy_deployment,
    demobilize_deployment,
    enroll_participant,
    get_unit,
    set_clock,
    stage_deployment,
    validate_success,
    withdraw_participant,
)


def setup_full_program() -> dict:
    """A capacity-2 program with waitlisting enabled and three enrollments."""
    set_clock("2026-11-15T00:00:00Z")
    unit = create_unit()
    program = create_corps_program(unit["id"], capacity=2, waitlist_enabled=True)
    enroll_participant(program["id"], "Alice Nguyen")
    enroll_participant(program["id"], "Bruno Salas")
    third = enroll_participant(program["id"], "Chloe Adeyemi")
    return {"unit": unit, "program": program, "third": third}


def test_program_capacity_allocation_waitlists_third_participant(api):
    """PRD §3.7: "The program's `enrolled_count` is the number of log entries up
    to the program's `capacity`, and its `waitlist_count` is the number of
    entries beyond it, never below zero."
    PRD §3.7: "The first enrollment of a `PLANNED` program moves it to `ACTIVE`".

    Design: Corner/calculations/program_capacity_allocation_waterfall_waitlist_promotion
    """
    scenario = setup_full_program()
    assert scenario["third"]["enrolled_count"] == 2
    assert scenario["third"]["waitlist_count"] == 1
    assert scenario["third"]["status"] == "ACTIVE"


def test_program_withdraw_promotes_earliest_waitlisted(api):
    """PRD §3.7: "the named `participant_name`'s entry is removed from the log,
    and the earliest waitlisted entry — by the same enrolled-then-name ordering
    — is promoted into the freed seat, so the queue advances by exactly one."

    Design: Corner/calculations/program_capacity_allocation_waterfall_waitlist_promotion
    """
    scenario = setup_full_program()
    after_withdraw = withdraw_participant(scenario["program"]["id"], "Alice Nguyen")

    assert after_withdraw["enrolled_count"] == 2
    assert after_withdraw["waitlist_count"] == 0, "Chloe Adeyemi takes the freed seat"


def test_canteen_deployment_cost_tiered_marginal_surge(api):
    """PRD §3.8: "The daily base rate depends on the incident command level:
    95000 cents for `TYPE_1`, 72000 for `TYPE_2`, 48000 for `TYPE_3`, 30000 for
    `TYPE_4` and 18000 for `TYPE_5`."
    PRD §3.8: "The first 14 billed days are charged at that base rate; any billed
    days beyond the fourteenth are surge days and are charged at 60 percent of
    the base rate."

    Design: Corner/calculations/canteen_deployment_cost_tiered_marginal_surge
    """
    set_clock("2026-11-01T00:00:00Z")
    unit = create_unit(canteen_pool_size=6)
    deployment = create_deployment(unit["id"], incident_command_level="TYPE_3",
                                   requested_canteens=2)
    approved = approve_deployment(deployment["id"])
    assert approved["assigned_canteen_count"] == 2
    stage_deployment(deployment["id"])
    deploy_deployment(deployment["id"])

    demobilized = demobilize_deployment(deployment["id"], "2026-11-21T00:00:00Z")
    assert demobilized["status"] == "DEMOBILIZED"
    # 20 billed days: 14 regular at 48000 plus 6 surge at 60 percent, for 2 canteens.
    assert demobilized["deployment_cost_cents"] == 1689600


def test_canteen_deployment_releases_unit_pool_on_demobilization(api):
    """PRD §3.8: "Demobilization moves the deployment to `DEMOBILIZED`, which is
    terminal, stores the instant, releases the canteens by setting
    `assigned_canteen_count` to 0 and recomputing the unit's committed count".
    PRD §2.4: "The `committed_canteen_count` is the sum of `assigned_canteen_count`
    across all of the unit's disaster deployments that are in `APPROVED`,
    `STAGED` or `DEPLOYED` status".

    Design: Corner/calculations/canteen_deployment_cost_tiered_marginal_surge
    """
    set_clock("2026-11-01T00:00:00Z")
    unit = create_unit(canteen_pool_size=6)
    deployment = create_deployment(unit["id"], incident_command_level="TYPE_3",
                                   requested_canteens=2)
    approve_deployment(deployment["id"])
    assert get_unit(unit["id"])["committed_canteen_count"] == 2

    stage_deployment(deployment["id"])
    deploy_deployment(deployment["id"])
    demobilized = demobilize_deployment(deployment["id"], "2026-11-21T00:00:00Z")

    assert demobilized["assigned_canteen_count"] == 0
    assert get_unit(unit["id"])["committed_canteen_count"] == 0
