"""Flavor lifecycle: promotion chain, retirement cascade, revival cycle (PRD §3.4, §3.5, §3.6)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_flavor_payload, create_revival_request_payload,
    create_production_slot_payload,
    make_flavor, make_flavor_in_state, make_limited_run_flavor,
    make_core_line_flavor, make_retired_flavor, get_flavor_version,
    substantiate_claim, make_published_claim_flavor,
    create_approved_supplier, make_verified_certification,
    make_operating_shop, make_confirmed_order,
    make_qualified_revival,
    make_independent_board_member_headers,
)

FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]
PS = TEST_USERS["plant_scheduler_headers"]
FA = TEST_USERS["franchise_admin_headers"]




def test_flavor_promote_skip_rejected(api):
    """PRD §3.4: "Promotion walks the lifecycle one step at a time, each step
    naming a `target_state`: `DEVELOPMENT` to `TEST_BATCH`, `TEST_BATCH` to
    `LIMITED_RUN` (the limited-batch introduction), and `LIMITED_RUN` to
    `CORE_LINE`. Every promotion bumps the flavor's `version`; no other
    promotion pairs exist."

    Design: Corner/state_machines/flavor_promote_skip_rejected
    """
    flavor = make_flavor(name="Skipper")
    resp = api.promote_flavor(flavor["id"], {"target_state": "LIMITED_RUN"}, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_read_after_write_immediate_visibility(api):
    """PRD §3.4: "Promotion walks the lifecycle one step at a time, each step naming a `target_state`: `DEVELOPMENT` to `TEST_BATCH`, `TEST_BATCH` to `LIMITED_RUN` (the limited-batch introduction), and `LIMITED_RUN` to `CORE_LINE`."
    PRD §2.4: "`version` (integer): starts at its initial value on creation and
    increments by one on every mutation".

    Design: Corner/consistency_model/read_after_write_immediate_visibility
    """
    flavor = make_flavor(name="Immediate Iris", base_type="NON_DAIRY",
                         chunk_load_pct=0, swirl_load_pct=10, pint_price_cents=149)
    promoted = validate_success(api.promote_flavor(
        flavor["id"], {"target_state": "TEST_BATCH"}, FM))
    assert promoted["status"] == "TEST_BATCH"

    read = get_success_data(api.get_flavor(flavor["id"], FM))
    assert read["status"] == "TEST_BATCH", "mutation must be visible in the next read"
    assert read["version"] == flavor["version"] + 1


def test_retire_cancels_open_orders_and_slots(api):
    """PRD §3.4: "Retiring a flavor stamps `retired_at` from the logical clock — the revival window of §3.6 measures from this instant — and then cascades: every supply order in `PLACED`, `CONFIRMED`, or `ALLOCATED` whose `lines` contain the flavor is cancelled to `CANCELLED`, with an `ALLOCATED` order's reserved pints released from its plant-day pool; every production slot of the flavor in `PLANNED` or `CONFIRMED` is cancelled to `CANCELLED`, releasing its reserved `capacity_units`; a claim in `PUBLISHED` is retracted to `RETRACTED`; and the flavor's `version` bumps."

    Design: Corner/cross_cutting_layers/retire_cancels_open_orders_and_slots
    """
    shop = make_operating_shop(name="Cascade Shop")
    flavor = make_limited_run_flavor(name="Retire Me", pint_price_cents=100)
    order = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 10}])
    assert order["status"] == "CONFIRMED"
    slot = get_success_data(api.create_production_slot(
        create_production_slot_payload(flavor["id"]), PS))
    assert slot["status"] == "PLANNED"

    retired = validate_success(api.retire_flavor(flavor["id"], POC))
    assert retired["status"] == "RETIRED"
    assert retired["retired_at"], "retired_at must be stamped from the logical clock"

    order_after = get_success_data(api.get_supply_order(order["id"], FA))
    assert order_after["status"] == "CANCELLED"
    slot_after = get_success_data(api.get_production_slot(slot["id"], PS))
    assert slot_after["status"] == "CANCELLED"


def test_flavor_cycle_with_parallel_claim_dimension(api):
    """PRD §3.4: "Retiring a flavor stamps `retired_at` from the logical clock — the revival window of §3.6 measures from this instant — and then cascades: every supply order in `PLACED`, `CONFIRMED`, or `ALLOCATED` whose `lines` contain the flavor is cancelled to `CANCELLED`, with an `ALLOCATED` order's reserved pints released from its plant-day pool; every production slot of the flavor in `PLANNED` or `CONFIRMED` is cancelled to `CANCELLED`, releasing its reserved `capacity_units`; a claim in `PUBLISHED` is retracted to `RETRACTED`; and the flavor's `version` bumps."
    PRD §3.4: "a `REVIVED` flavor returns to `CORE_LINE` when the `FlavorManager` returns it to the line, closing the cycle `CORE_LINE` to `RETIRED` to `REVIVED` to `CORE_LINE`; that return also bumps `version`."
    PRD §3.5: "Retraction is the system's own move, never a direct action: a claim in `PUBLISHED` retracts to `RETRACTED` when the flavor retires (§3.4) or when a cited certification expires under the logical clock (§2.5)." PRD §3.5: "From `CHALLENGED` or `RETRACTED`, the only way back is a fresh substantiation, which supersedes the old claim entirely."

    Design: Difficulty/non_linear_state_machine/flavor_cycle_with_parallel_claim_dimension
    """
    supplier = create_approved_supplier(name="Dairy Pure")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95)
    flavor = make_core_line_flavor(name="Cyclic Swirl", chunk_load_pct=10,
                                   swirl_load_pct=10)
    substantiate_claim(flavor["id"], [cert["id"]])
    published = validate_success(api.publish_claim(flavor["id"], FM))
    assert published["claim_status"] == "PUBLISHED"

    retired = validate_success(api.retire_flavor(flavor["id"], POC))
    assert retired["status"] == "RETIRED"
    assert retired["claim_status"] == "RETRACTED", "retire retracts the claim dimension"

    request = get_success_data(api.create_revival_request(
        flavor["id"], create_revival_request_payload(
            fan_email="fan1@example.com", title="Bring it back"),
        TEST_USERS["fan_headers"]))
    get_success_data(api.sign_revival_request(
        request["id"], {"fan_email": "fan1@example.com", "count": 500},
        TEST_USERS["fan_headers"]))
    validate_success(api.adopt_revival_request(
        request["id"], make_independent_board_member_headers("board-1")))

    mid = get_success_data(api.get_flavor(flavor["id"], FM))
    assert mid["status"] == "REVIVED"
    assert mid["claim_status"] == "RETRACTED", "dimensions evolve independently"

    back = validate_success(api.return_flavor_to_line(flavor["id"], FM))
    assert back["status"] == "CORE_LINE", "cycle CORE_LINE->RETIRED->REVIVED->CORE_LINE"

    re_sub = substantiate_claim(flavor["id"], [cert["id"]])
    assert re_sub["claim_status"] == "SUBSTANTIATED", \
        "claim dimension re-cycles from RETRACTED without touching lifecycle"
    assert re_sub["status"] == "CORE_LINE"


def test_revived_flavor_can_retire_again(api):
    """PRD §3.4: "Retirement is operational control, reserved to the
    `ParentOpsController`, and is available from `LIMITED_RUN`, `CORE_LINE`,
    or `REVIVED`."
    PRD §3.6: "or the parent can retire it again — which restarts the revival
    clock from the new `retired_at`."
    PRD §3.4: "a `REVIVED` flavor returns to `CORE_LINE` when the `FlavorManager` returns it to the line, closing the cycle `CORE_LINE` to `RETIRED` to `REVIVED` to `CORE_LINE`; that return also bumps `version`."

    Design: Difficulty/non_linear_state_machine/flavor_cycle_with_parallel_claim_dimension
    """
    flavor = make_retired_flavor(name="Boomerang")
    first_retired_at = flavor["retired_at"]

    request = make_qualified_revival(flavor["id"])
    validate_success(api.adopt_revival_request(
        request["id"], make_independent_board_member_headers("board-1")))
    revived = get_success_data(api.get_flavor(flavor["id"], FM))
    assert revived["status"] == "REVIVED"

    # Advance the clock so the second retirement stamps a different instant.
    validate_success(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, POC))
    re_retired = validate_success(api.retire_flavor(flavor["id"], POC))
    assert re_retired["status"] == "RETIRED", "retire is defined from REVIVED"
    assert re_retired["retired_at"].startswith("2026-10-01")
    assert re_retired["retired_at"] != first_retired_at
