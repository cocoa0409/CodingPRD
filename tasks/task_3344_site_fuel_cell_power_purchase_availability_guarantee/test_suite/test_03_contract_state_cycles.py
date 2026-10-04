"""The cyclic edges of the contract machine: exit/cure and the two plan axes."""
from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    OPERATOR,
    SERVICE_ENGINEER,
    get_ppa,
    get_service_plan,
    get_site,
    list_transitions,
    setup_active_ppa,
)


def test_exit_then_cure_returns_the_contract_to_active():
    """PRD §3.8: "On acceptance the
    contract returns to `PPA_ACTIVE` — this is the cyclic edge that makes the contract state
    machine non-linear, the path from `PPA_ACTIVE` through `PPA_EXIT_PENDING` and back".

    Design: Difficulty/non_linear_state_machine/ppa_exit_cure_cycle_reverts_to_active
    """
    ctx = setup_active_ppa()
    exiting = validate_success(api_client.request_exit(ctx["ppa_id"], OPERATOR))
    assert exiting["state"] == "PPA_EXIT_PENDING"

    cured = validate_success(api_client.cure_ppa(ctx["ppa_id"], OPERATOR))
    assert cured["state"] == "PPA_ACTIVE", (
        f"a cure reverts the contract to PPA_ACTIVE, got {cured['state']}"
    )


def test_exit_cure_cycle_is_traversable_twice_and_zeroes_the_fee_each_time():
    """PRD §3.8: "its `exit_fee_cents` is reset to zero".
    PRD §3.8: "the most recent
    transition record for that contract has its `transition_reversed` flag set to true, and a new
    transition record is appended with trigger code `EXIT_CURED`".

    Design: Difficulty/non_linear_state_machine/ppa_exit_cure_cycle_reverts_to_active
    """
    ctx = setup_active_ppa()

    validate_success(api_client.request_exit(ctx["ppa_id"], OPERATOR))
    first_cure = validate_success(api_client.cure_ppa(ctx["ppa_id"], OPERATOR))
    assert first_cure["exit_fee_cents"] == 0

    validate_success(api_client.request_exit(ctx["ppa_id"], OPERATOR))
    second_cure = validate_success(api_client.cure_ppa(ctx["ppa_id"], OPERATOR))

    assert second_cure["state"] == "PPA_ACTIVE"
    assert second_cure["exit_fee_cents"] == 0, (
        "each cure zeroes the fee, so the second cure also reads 0; got "
        f"{second_cure['exit_fee_cents']}"
    )

    transitions = list_transitions(ctx["ppa_id"])
    states = [t["to_state"] for t in transitions]
    assert states == [
        "PPA_ACTIVE",
        "PPA_EXIT_PENDING",
        "PPA_ACTIVE",
        "PPA_EXIT_PENDING",
        "PPA_ACTIVE",
    ], f"the cycle must be replayable; recorded to_state sequence was {states}"


def test_the_two_service_plan_axes_cycle_without_overwriting_each_other():
    """PRD §3.7: "A plan already `SERVICE_ACTIVE` whose window boundaries are both non-null
    enters `SERVICE_MAINTENANCE_WINDOW_OPEN`".
    PRD §3.7: "when the site is unfrozen, every blocked plan whose lifecycle is
    `SERVICE_ACTIVE` returns to `REPLACEMENT_SCHEDULED`".

    Design: Difficulty/non_linear_state_machine/service_plan_lifecycle_and_replacement_cycles_interleave
    """
    ctx = setup_active_ppa()
    plan_id = ctx["plan_id"]
    validate_success(
        api_client.schedule_replacement(ctx["ppa_id"], plan_id, SERVICE_ENGINEER)
    )

    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "GRID_INTERCONNECT_FAILURE")
    )
    frozen_plan = get_service_plan(ctx["ppa_id"], plan_id)
    assert frozen_plan["module_replacement_stage"] == "REPLACEMENT_BLOCKED"

    validate_success(api_client.unfreeze_site(ctx["site_id"], OPERATOR))
    thawed_plan = get_service_plan(ctx["ppa_id"], plan_id)

    assert thawed_plan["lifecycle_state"] == "SERVICE_ACTIVE", (
        "the lifecycle dimension returns to SERVICE_ACTIVE on the unfreeze; got "
        f"{thawed_plan['lifecycle_state']}"
    )
    assert thawed_plan["module_replacement_stage"] == "REPLACEMENT_SCHEDULED", (
        "the hardware dimension cycles back on its own axis; got "
        f"{thawed_plan['module_replacement_stage']}"
    )


def test_plan_reads_both_dimensions_on_the_same_row_at_the_same_read():
    """PRD §3.7: "the plan carries three independent dimensions that move on their own schedules:
    an operational lifecycle, an independent hardware-replacement stage, and a monitoring health
    reading."

    Design: Difficulty/non_linear_state_machine/service_plan_lifecycle_and_replacement_cycles_interleave
    """
    ctx = setup_active_ppa()
    plan_id = ctx["plan_id"]
    validate_success(
        api_client.schedule_replacement(ctx["ppa_id"], plan_id, SERVICE_ENGINEER)
    )

    plan = get_service_plan(ctx["ppa_id"], plan_id)

    assert plan["lifecycle_state"] == "SERVICE_ACTIVE"
    assert plan["module_replacement_stage"] == "REPLACEMENT_SCHEDULED"
    # A second read of the same row confirms the dimensions are carried together.
    again = get_service_plan(ctx["ppa_id"], plan_id)
    assert (again["lifecycle_state"], again["module_replacement_stage"]) == (
        "SERVICE_ACTIVE",
        "REPLACEMENT_SCHEDULED",
    )
    assert get_site(ctx["site_id"])["status"] == "SITE_ACTIVE"