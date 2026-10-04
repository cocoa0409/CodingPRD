"""Battery module quality gating: registration defaults, registrar/inspector
segregation, and the rework loop with its counting auto-scrap termination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_battery_module,
    create_battery_module_payload,
    create_supplier,
    make_quality_inspector_headers,
    register_module,
    set_logical_clock,
    transition_module,
    transition_payload,
    validate_error,
    validate_success,
)

_PLANNER = TEST_USERS["production_planner_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]


def test_battery_module_create_defaults_registered_with_zero_failures(api, production_planner_headers):
    """PRD section 3.4: "Registration records the operator as
    `registered_by_user_id`, sets `quality_status` to `REGISTERED`, zeroes
    `failure_count`, and leaves `last_inspector_user_id` null."

    Design: Corner/entities/battery_module_create_defaults_registered_with_zero_failures
    """
    set_logical_clock()
    supplier = create_supplier()
    resp = api.create_battery_module(
        create_battery_module_payload(supplier["id"], module_serial="M-001", pack_kwh=77),
        production_planner_headers,
    )
    data = validate_success(resp, 201)
    assert_battery_module(data)
    assert data["quality_status"] == "REGISTERED"
    assert data["failure_count"] == 0
    assert data["last_inspector_user_id"] is None
    assert data["registered_by_user_id"] == "pp-1", "registrar captured from X-User-ID"


def test_module_registrar_cannot_inspect_own_module(api):
    """PRD section 2.9: "A `QualityInspector` may not inspect a battery module
    they themselves registered: on every inspection transition the caller's
    `X-User-ID` must differ from the module's `registered_by_user_id`."; PRD
    section 3.4: "Every inspection transition stamps `last_inspector_user_id`
    with the inspector's `X-User-ID`."

    Design: Corner/rbac/module_registrar_cannot_inspect_own_module
    """
    set_logical_clock()
    supplier = create_supplier()
    module = register_module(supplier["id"], module_serial="M-001")
    resp = api.transition_battery_module(
        module["id"],
        transition_payload("IN_QA"),
        make_quality_inspector_headers("pp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION)
    inspected = transition_module(module["id"], "IN_QA", _INSPECTOR)
    assert inspected["quality_status"] == "IN_QA"
    assert inspected["last_inspector_user_id"] == "qi-1"


def _walk_module_to_second_failure():
    """Supplier + module M-100 (52 kWh) driven REGISTERED -> IN_QA -> FAILED
    -> REWORK -> IN_QA -> FAILED. Returns (module_id, first_failed_data,
    second_failed_data)."""
    set_logical_clock()
    supplier = create_supplier()
    module = register_module(supplier["id"], module_serial="M-100", pack_kwh=52)
    transition_module(module["id"], "IN_QA", _INSPECTOR)
    first_fail = transition_module(module["id"], "FAILED", _INSPECTOR)
    transition_module(module["id"], "REWORK", _PLANNER)
    transition_module(module["id"], "IN_QA", _INSPECTOR)
    second_fail = transition_module(module["id"], "FAILED", _INSPECTOR)
    return module["id"], first_fail, second_fail


def test_battery_module_rework_cycle_accumulates_failures_and_auto_scraps(api):
    """PRD section 3.4: "Each `FAILED` outcome increments `failure_count` by
    1, and the moment `failure_count` reaches 2 the module auto-transitions
    from `FAILED` to `SCRAPPED` inside the same request — no separate scrap
    action exists. A failed module that has not yet hit that ceiling can be
    sent `FAILED → REWORK` by a `ProductionPlanner`, and after rework a
    `QualityInspector` returns it `REWORK → IN_QA` for a fresh inspection;
    the failure count survives rework."

    Design: Difficulty/non_linear_state_machine/battery_module_rework_cycle_with_auto_scrap
    """
    _module_id, first_fail, second_fail = _walk_module_to_second_failure()
    assert first_fail["quality_status"] == "FAILED"
    assert first_fail["failure_count"] == 1, "the loop preserved and accumulated the count"
    assert second_fail["quality_status"] == "SCRAPPED", (
        "the second FAILED auto-transitioned to SCRAPPED in the same request"
    )
    assert second_fail["failure_count"] == 2


def test_scrapped_module_is_terminal(api):
    """PRD section 3.4: "`SCRAPPED` and `ALLOCATED` are the terminal states;
    only a `PASSED`, never-allocated module can fulfill an order."; PRD
    section 2.8 rule 6: "any transition attempted from a terminal state is
    refused as `ERR_ALREADY_TERMINAL` (409)."

    Design: Difficulty/non_linear_state_machine/battery_module_rework_cycle_with_auto_scrap
    """
    module_id, _first, second_fail = _walk_module_to_second_failure()
    assert second_fail["quality_status"] == "SCRAPPED"
    resp = api.transition_battery_module(module_id, transition_payload("REWORK"), _PLANNER)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
